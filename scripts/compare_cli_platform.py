#!/usr/bin/env python3
"""Standalone comparator for CLI and platform output byte-for-byte identity."""

from __future__ import annotations

import gzip
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import warnings

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Prepare temporary storage and environment variables before app imports
tmp_dir = tempfile.TemporaryDirectory()
tmp_path = Path(tmp_dir.name)

db_path = tmp_path / "compare.db"
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["GATE_OPEN"] = "true"

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.analysis import OUTPUT_FILES, build_matrix_gzip, write_inputs
from app.auth import COOKIE_NAME
from app.db import SessionLocal, get_engine
from app.main import app
from app.models import Analysis, AnalysisFile, Base, Dataset, SessionRow, User
from app.parsers import parse_delimited
from app.security import hash_password, hash_token, new_token, now_epoch


def setup_user_and_session() -> tuple[int, str]:
    now = now_epoch()
    with SessionLocal() as db:
        user = User(
            email="verifier@example.test",
            email_normalized="verifier@example.test",
            password_hash=hash_password("katasandi-verifier-123"),
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
        return user_id, token


def main() -> int:
    try:
        engine = get_engine()
        Base.metadata.create_all(engine)

        user_id, token = setup_user_and_session()

        client = TestClient(app, base_url="https://testserver")
        client.cookies.set(COOKIE_NAME, token)

        fixture_path = (
            Path(__file__).resolve().parent.parent
            / "tests"
            / "fixtures"
            / "sample_300x40.csv"
        )
        if not fixture_path.is_file():
            fixture_path = Path("tests/fixtures/sample_300x40.csv").resolve()

        csv_bytes = fixture_path.read_bytes()

        upload_resp = client.post(
            "/datasets",
            files={"data": ("sample_300x40.csv", csv_bytes, "text/csv")},
            follow_redirects=False,
        )
        if upload_resp.status_code != 303:
            print(
                f"Upload gagal: status {upload_resp.status_code}: {upload_resp.text}",
                file=sys.stderr,
            )
            return 1

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
        if commit_resp.status_code != 303:
            print(
                f"Commit gagal: status {commit_resp.status_code}: {commit_resp.text}",
                file=sys.stderr,
            )
            return 1

        post_resp = client.post(f"/datasets/{dataset_id}/analyze", follow_redirects=False)
        if post_resp.status_code != 303:
            print(
                f"Analyze gagal: status {post_resp.status_code}: {post_resp.text}",
                file=sys.stderr,
            )
            return 1

        location = post_resp.headers["location"]
        analysis_id = int(location.split("/")[-1])

        get_resp = client.get(location)
        if get_resp.status_code != 200:
            print(
                f"GET hasil analisis gagal: status {get_resp.status_code}",
                file=sys.stderr,
            )
            return 1

        with SessionLocal() as db:
            analysis = db.scalar(select(Analysis).where(Analysis.id == analysis_id))
            if analysis is None or analysis.status != "done":
                print(
                    f"Status analisis bukan done: {getattr(analysis, 'status', None)}",
                    file=sys.stderr,
                )
                return 1

            dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
            if dataset is None:
                print(f"Dataset {dataset_id} tidak ditemukan", file=sys.stderr)
                return 1

            files = list(
                db.scalars(
                    select(AnalysisFile).where(AnalysisFile.analysis_id == analysis_id)
                ).all()
            )
            if len(files) != len(OUTPUT_FILES):
                print(
                    f"Jumlah berkas luaran platform {len(files)} != {len(OUTPUT_FILES)}",
                    file=sys.stderr,
                )
                return 1

            platform_files = {f.filename: f for f in files}

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

        cli_out_dir = tmp_path / "cli_out"
        cli_out_dir.mkdir(parents=True, exist_ok=True)

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
            str(cli_out_dir),
            "--format",
            "csv",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            print(
                f"CLI analyze gagal (kode {proc.returncode}):\n{proc.stderr}",
                file=sys.stderr,
            )
            return proc.returncode or 1

        all_match = True
        for filename in OUTPUT_FILES:
            cli_file_path = cli_out_dir / filename
            if not cli_file_path.is_file():
                print(f"{filename}: CLI file missing MISMATCH")
                all_match = False
                continue

            cli_bytes = cli_file_path.read_bytes()
            cli_sha256 = hashlib.sha256(cli_bytes).hexdigest()

            af = platform_files.get(filename)
            if af is None:
                print(f"{filename}: platform file missing MISMATCH")
                all_match = False
                continue

            platform_bytes = gzip.decompress(af.content_gzip)
            platform_sha256 = hashlib.sha256(platform_bytes).hexdigest()

            is_identical = (
                platform_bytes == cli_bytes
                and platform_sha256 == cli_sha256
                and af.sha256 == cli_sha256
            )
            status = "MATCH" if is_identical else "MISMATCH"
            if not is_identical:
                all_match = False

            print(f"{filename}: platform {platform_sha256}  cli {cli_sha256}  {status}")

        if all_match and len(platform_files) == 6:
            print("ALL 6 FILES BYTE-IDENTICAL")
            return 0
        return 1

    finally:
        engine = get_engine()
        if engine is not None:
            engine.dispose()
        tmp_dir.cleanup()


if __name__ == "__main__":
    sys.exit(main())
