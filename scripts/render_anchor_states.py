#!/usr/bin/env python3
"""Render anchor probe states into HTML files for review."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import warnings

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

tmp_dir = tempfile.TemporaryDirectory()
tmp_path = Path(tmp_dir.name)

db_path = tmp_path / "probe.db"
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["GATE_OPEN"] = "true"

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME
from app.db import SessionLocal, get_engine
from app.main import app
from app.models import Analysis, Base, SessionRow, User
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

        fixture_path = REPO_ROOT / "tests" / "fixtures" / "sample_300x40.csv"
        if not fixture_path.is_file():
            fixture_path = Path("tests/fixtures/sample_300x40.csv").resolve()

        if not fixture_path.is_file():
            print(f"Fixture file not found: {fixture_path}", file=sys.stderr)
            return 1

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

        dataset_id = int(upload_resp.headers["location"].split("/")[-1].split("?")[0])

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

        now = now_epoch()
        with SessionLocal() as db:
            row2 = Analysis(
                dataset_id=dataset_id,
                user_id=user_id,
                status="done",
                params_json=json.dumps({"misfit": 1.5, "mode": "compat", "digits": 2}),
                engine_ref="raschlab-engine-test",
                error=None,
                elapsed_ms=100,
                created_at=now,
                started_at=now,
                finished_at=now,
                expires_at=now + 180 * 86400,
            )
            db.add(row2)
            db.commit()
            row2_id = row2.id

            row1 = Analysis(
                dataset_id=dataset_id,
                user_id=user_id,
                status="done",
                params_json=json.dumps(
                    {
                        "misfit": 1.5,
                        "mode": "compat",
                        "digits": 2,
                        "anchors": {
                            "name": "jangkar-tbs.txt",
                            "requested": 3,
                            "used": 1,
                            "anchors": {"1": 0.5, "2": -0.25, "5": 1.1},
                            "by_position": 2,
                            "by_label": 1,
                        },
                    }
                ),
                engine_ref="raschlab-engine-test",
                error=None,
                elapsed_ms=120,
                created_at=now + 1,
                started_at=now + 1,
                finished_at=now + 1,
                expires_at=now + 1 + 180 * 86400,
            )
            db.add(row1)
            db.commit()
            row1_id = row1.id

        anchored_resp = client.get(f"/analyses/{row1_id}")
        if anchored_resp.status_code != 200:
            print(
                f"GET /analyses/{row1_id} failed with status {anchored_resp.status_code}",
                file=sys.stderr,
            )
            return 1
        if "Jangkar Aktif (Anchored)" not in anchored_resp.text:
            print("Missing marker 'Jangkar Aktif (Anchored)' in anchored.html", file=sys.stderr)
            return 1

        unanchored_resp = client.get(f"/analyses/{row2_id}")
        if unanchored_resp.status_code != 200:
            print(
                f"GET /analyses/{row2_id} failed with status {unanchored_resp.status_code}",
                file=sys.stderr,
            )
            return 1
        if "Hasil Tanpa Jangkar" not in unanchored_resp.text:
            print("Missing marker 'Hasil Tanpa Jangkar' in unanchored.html", file=sys.stderr)
            return 1

        settings_resp = client.get(f"/datasets/{dataset_id}/analysis-settings")
        if settings_resp.status_code != 200:
            print(
                f"GET /datasets/{dataset_id}/analysis-settings failed with status {settings_resp.status_code}",
                file=sys.stderr,
            )
            return 1
        if 'name="inherit_anchors"' not in settings_resp.text:
            print("Missing marker 'name=\"inherit_anchors\"' in settings.html", file=sys.stderr)
            return 1

        out_dir = Path("/tmp/raschlab_probe")
        out_dir.mkdir(parents=True, exist_ok=True)

        anchored_path = (out_dir / "anchored.html").resolve()
        unanchored_path = (out_dir / "unanchored.html").resolve()
        settings_path = (out_dir / "settings.html").resolve()

        anchored_path.write_text(anchored_resp.text, encoding="utf-8")
        unanchored_path.write_text(unanchored_resp.text, encoding="utf-8")
        settings_path.write_text(settings_resp.text, encoding="utf-8")

        print(str(anchored_path))
        print(str(unanchored_path))
        print(str(settings_path))
        return 0

    finally:
        engine = get_engine()
        if engine is not None:
            engine.dispose()
        tmp_dir.cleanup()


if __name__ == "__main__":
    sys.exit(main())
