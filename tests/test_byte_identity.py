"""Acceptance comparator test: byte-for-byte identity between platform and CLI.

Validates that analyzing `sample_300x40.csv` via the web application produces
decompressed CSV outputs that are byte-for-byte identical to running the raschlab
CLI directly on independently re-derived inputs with matching SHA-256 hashes.
"""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.analysis import OUTPUT_FILES, build_matrix_gzip, write_inputs
from app.auth import COOKIE_NAME
from app.db import SessionLocal
from app.models import Analysis, AnalysisFile, Dataset, SessionRow, User
from app.parsers import parse_delimited
from app.security import hash_password, hash_token, new_token, now_epoch

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _create_authenticated_user(client: TestClient, email: str = "comparator@example.test") -> int:
    with SessionLocal() as db:
        now = now_epoch()
        user = User(
            email=email,
            email_normalized=email.lower().strip(),
            password_hash=hash_password("katasandi-comparator-123"),
            created_at=now,
            verified_at=now,
        )
        db.add(user)
        db.commit()
        user_id = user.id

        token = new_token()
        session_row = SessionRow(
            user_id=user_id,
            token_hash=hash_token(token),
            created_at=now,
            expires_at=now + 86400 * 30,
        )
        db.add(session_row)
        db.commit()

    client.cookies.set(COOKIE_NAME, token)
    return user_id


def test_byte_identity_sample_300x40(client: TestClient, tmp_path: Path) -> None:
    # 1. Drive the full HTTP flow on sample_300x40.csv
    fixture_path = FIXTURES_DIR / "sample_300x40.csv"
    csv_bytes = fixture_path.read_bytes()

    _create_authenticated_user(client)

    upload_resp = client.post(
        "/datasets",
        files={"data": ("sample_300x40.csv", csv_bytes, "text/csv")},
        follow_redirects=False,
    )
    assert upload_resp.status_code == 303
    dataset_id = int(upload_resp.headers["location"].split("/")[-1])

    commit_resp = client.post(
        f"/datasets/{dataset_id}/commit",
        data={
            "t0": "1",
            "m0": "correct",
            "t1": "0",
            "m1": "incorrect",
            "t2": "NA",
            "m2": "missing",
            "t3": "",
            "m3": "missing",
        },
        follow_redirects=False,
    )
    assert commit_resp.status_code == 303

    post_resp = client.post(f"/datasets/{dataset_id}/analyze", follow_redirects=False)
    assert post_resp.status_code == 303
    location = post_resp.headers["location"]
    analysis_id = int(location.split("/")[-1])

    get_resp = client.get(location)
    assert get_resp.status_code == 200

    # Retrieve stored platform output files and dataset record from DB
    with SessionLocal() as db:
        analysis = db.scalar(select(Analysis).where(Analysis.id == analysis_id))
        assert analysis is not None
        assert analysis.status == "done"

        dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
        assert dataset is not None

        files = list(
            db.scalars(
                select(AnalysisFile).where(AnalysisFile.analysis_id == analysis_id)
            ).all()
        )
        assert len(files) == 6
        platform_files = {f.filename: f for f in files}
        assert set(platform_files.keys()) == set(OUTPUT_FILES)

    # 2. Independently re-derive the inputs with build_matrix_gzip + write_inputs into tmp_path
    parsed = parse_delimited(csv_bytes)
    mapping = {"1": "correct", "0": "incorrect", "NA": "missing", "": "missing"}
    matrix_gzip = build_matrix_gzip(
        kind="delimited",
        person_labels=parsed.person_labels,
        item_labels=parsed.item_labels,
        rows=parsed.rows,
        mapping=mapping,
    )

    con_path, data_path = write_inputs(tmp_path, dataset, matrix_gzip)

    out_dir = tmp_path / "cli_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 3. Run the CLI
    cmd = [
        sys.executable,
        "-m",
        "raschlab",
        "analyze",
        "--con",
        str(con_path),
        "--data",
        str(data_path),
        "--out",
        str(out_dir),
        "--format",
        "csv",
    ]
    subprocess.run(cmd, check=True)

    # 4. Assert for all six output files that gzip.decompress(platform_bytes) == cli_bytes
    #    byte-for-byte and that the sha256 values match.
    for filename in OUTPUT_FILES:
        cli_file_path = out_dir / filename
        assert cli_file_path.is_file(), f"Berkas luaran CLI tidak ditemukan: {filename}"
        cli_bytes = cli_file_path.read_bytes()
        cli_sha256 = hashlib.sha256(cli_bytes).hexdigest()

        af = platform_files[filename]
        platform_bytes = gzip.decompress(af.content_gzip)
        platform_sha256 = hashlib.sha256(platform_bytes).hexdigest()

        # Byte-for-byte identity
        assert (
            platform_bytes == cli_bytes
        ), f"Perbedaan byte-for-byte pada {filename}"
        # SHA-256 match with stored DB record and recomputed hash
        assert af.sha256 == cli_sha256, f"Perbedaan sha256 tersimpan pada {filename}"
        assert (
            platform_sha256 == cli_sha256
        ), f"Perbedaan sha256 hasil dekompresi pada {filename}"
        assert af.bytes == len(cli_bytes), f"Perbedaan ukuran byte pada {filename}"
