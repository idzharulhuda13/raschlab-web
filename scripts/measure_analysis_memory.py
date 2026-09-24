#!/usr/bin/env python3
"""Measure memory consumption of ingest and analysis phases at the 2M cell cap."""

from __future__ import annotations

import argparse, contextlib, gc, io, json, os, resource, subprocess, sys, tempfile, time, types
from pathlib import Path
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CACHE_PATH = os.path.join(tempfile.gettempdir(), "raschlab_measure_matrix.gz")


def generate_synthetic_data() -> tuple[list[str], list[str], list[list[str]], dict[str, str]]:
    rng = np.random.default_rng(42)
    tokens = np.array(["1", "0", ""])
    idx = rng.choice(3, size=(4000, 500), p=[0.6, 0.3, 0.1])
    return (
        [f"P{i+1:04d}" for i in range(4000)],
        [f"I{j+1:03d}" for j in range(500)],
        tokens[idx].tolist(),
        {"1": "correct", "0": "incorrect", "": "missing"},
    )


def phase_ingest() -> int:
    from app.analysis import build_matrix_gzip

    person_labels, item_labels, rows, mapping = generate_synthetic_data()
    gz = build_matrix_gzip(
        kind="delimited",
        person_labels=person_labels,
        item_labels=item_labels,
        rows=rows,
        mapping=mapping,
        control=None,
    )
    with open(CACHE_PATH, "wb") as f:
        f.write(gz)
    container_mb = len(gz) / (1024 * 1024)
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"INGEST: peak {peak_mb:.2f} MB, container {container_mb:.2f} MB")
    return 0


def phase_analyze() -> int:
    from app.analysis import build_matrix_gzip, write_inputs
    from raschlab.cli import run_analyze

    if os.path.isfile(CACHE_PATH):
        with open(CACHE_PATH, "rb") as f:
            gz = f.read()
    else:
        person_labels, item_labels, rows, mapping = generate_synthetic_data()
        gz = build_matrix_gzip(
            kind="delimited",
            person_labels=person_labels,
            item_labels=item_labels,
            rows=rows,
            mapping=mapping,
            control=None,
        )
        del person_labels, rows, mapping

    item_labels = [f"I{j+1:03d}" for j in range(500)]
    dataset = types.SimpleNamespace(n_items=500, item_labels_json=json.dumps(item_labels))
    with tempfile.TemporaryDirectory(prefix="raschlab_mem_") as td:
        con_path, data_path = write_inputs(td, dataset, gz)
        del gz
        t0 = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()):
            run_analyze(
                con_path,
                data_path,
                out_dir=td,
                mode="compat",
                out_format="csv",
                digits=2,
                lconv=None,
                person_order="misfit",
            )
        wall_s = time.perf_counter() - t0
        files = sorted(f for f in os.listdir(td) if f.endswith(".csv"))
        peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        print(f"ANALYZE: peak {peak_mb:.2f} MB, wall {wall_s:.2f} s, files: {files}")
    return 0


def phase_engine_cli() -> int:
    from app.analysis import build_matrix_gzip, write_inputs

    person_labels, item_labels, rows, mapping = generate_synthetic_data()
    gz = build_matrix_gzip(
        kind="delimited",
        person_labels=person_labels,
        item_labels=item_labels,
        rows=rows,
        mapping=mapping,
        control=None,
    )
    dataset = types.SimpleNamespace(n_items=len(item_labels), item_labels_json=json.dumps(item_labels))
    with tempfile.TemporaryDirectory(prefix="raschlab_cli_") as td:
        con_path, data_path = write_inputs(td, dataset, gz)
        del person_labels, item_labels, rows, mapping, gz, dataset
        gc.collect()

        cmd = [
            sys.executable,
            "-m",
            "raschlab",
            "analyze",
            "--con",
            con_path,
            "--data",
            data_path,
            "--out",
            td,
            "--format",
            "csv",
        ]
        t0 = time.perf_counter()
        proc = subprocess.run(cmd, cwd=td, capture_output=True, text=True)
        wall_s = time.perf_counter() - t0
        if proc.returncode != 0:
            stderr_tail = "\n".join(proc.stderr.strip().splitlines()[-10:]) if proc.stderr else ""
            raise RuntimeError(
                f"Engine CLI failed with exit code {proc.returncode}"
                + (f":\n{stderr_tail}" if stderr_tail else "")
            )
        peak_mb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
        print(f"ENGINE-CLI: peak {peak_mb:.2f} MB, wall {wall_s:.2f} s")
    return 0


def phase_app() -> int:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app.models import AnalysisFile, Base, Dataset, User

    if os.path.isfile(CACHE_PATH):
        with open(CACHE_PATH, "rb") as f:
            gz = f.read()
    else:
        from app.analysis import build_matrix_gzip

        person_labels, item_labels, rows, mapping = generate_synthetic_data()
        gz = build_matrix_gzip(
            kind="delimited",
            person_labels=person_labels,
            item_labels=item_labels,
            rows=rows,
            mapping=mapping,
            control=None,
        )
        del person_labels, item_labels, rows, mapping
        gc.collect()

    with tempfile.TemporaryDirectory(prefix="raschlab_db_") as db_dir:
        db_path = os.path.join(db_dir, "app_measure.db")
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)

        with Session(engine) as db:
            user = User(
                email="measure@example.com",
                email_normalized="measure@example.com",
                password_hash="hash",
                created_at=int(time.time()),
                verified_at=int(time.time()),
            )
            db.add(user)
            db.commit()

            item_labels = [f"I{j+1:03d}" for j in range(500)]
            dataset = Dataset(
                user_id=user.id,
                filename="synthetic.csv",
                kind="delimited",
                format="csv",
                status="ready",
                n_persons=4000,
                n_items=500,
                item_labels_json=json.dumps(item_labels),
                mapping_json=json.dumps({"1": "correct", "0": "incorrect", "": "missing"}),
                summary_json=json.dumps({}),
                raw_gzip=b"",
                raw_bytes=0,
                created_at=int(time.time()),
                committed_at=int(time.time()),
                matrix_gzip=gz,
            )
            db.add(dataset)
            db.commit()
            del gz
            gc.collect()

            import app.analysis

            t0 = time.perf_counter()
            analysis = app.analysis.run_for_dataset(db, dataset)
            wall_s = time.perf_counter() - t0

            files = db.scalars(
                select(AnalysisFile).where(AnalysisFile.analysis_id == analysis.id)
            ).all()
            n_files = len(files)
            if n_files != 6:
                raise RuntimeError(f"Expected 6 analysis_files rows, got {n_files}")

            peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            print(f"APP: peak {peak_mb:.2f} MB, wall {wall_s:.2f} s, status {analysis.status}, files: {n_files}")

    return 0


def run_child(phase: str) -> tuple[float, str]:
    r_pipe, w_pipe = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r_pipe)
        cmd = [sys.executable, str(Path(__file__).resolve()), "--phase", phase]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        rss_kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        msg = proc.stdout.strip()
        if proc.returncode != 0:
            err = proc.stderr.strip()
            msg = f"{msg}\n{err}".strip() if msg else err
        os.write(w_pipe, f"{rss_kb}::{msg}::{proc.returncode}".encode())
        os.close(w_pipe)
        os._exit(proc.returncode)
    os.close(w_pipe)
    os.waitpid(pid, 0)
    data = os.read(r_pipe, 65536).decode()
    os.close(r_pipe)
    rss_kb_str, out, code_str = data.split("::", 2)
    if int(code_str) != 0:
        raise RuntimeError(f"Phase {phase} failed (exit {code_str}):\n{out}")
    return float(rss_kb_str) / 1024, out


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure analysis memory at the 2M cell cap.")
    parser.add_argument(
        "--phase",
        choices=["ingest", "analyze", "engine-cli", "app"],
        default=None,
    )
    args = parser.parse_args()

    if args.phase:
        if args.phase == "ingest":
            return phase_ingest()
        elif args.phase == "analyze":
            return phase_analyze()
        elif args.phase == "engine-cli":
            return phase_engine_cli()
        elif args.phase == "app":
            return phase_app()

    try:
        peak_ingest, out_ingest = run_child("ingest")
        peak_analyze, out_analyze = run_child("analyze")
        peak_engine_cli, out_engine_cli = run_child("engine-cli")
        peak_app, out_app = run_child("app")
        print(out_ingest)
        print(out_analyze)
        print(out_engine_cli)
        print(out_app)
        peak = max(peak_ingest, peak_app)
        verdict = "PASS" if peak <= 400.0 else "FAIL"
        print(f"PEAK {peak:.2f} MB\nBUDGET 512 MiB\n{verdict}")
        return 0 if verdict == "PASS" else 1
    finally:
        if os.path.exists(CACHE_PATH):
            os.remove(CACHE_PATH)


if __name__ == "__main__":
    sys.exit(main())
