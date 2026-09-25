"""Rasch analysis orchestration, matrix container building, and result persistence.

Bridges the frozen raschlab engine with the web application database and UI.
Handles matrix container creation (validation and encoding), in-process engine
invocation under isolated memory caps, deterministic result storage, and
data retention lifecycles.
"""

from __future__ import annotations

import contextlib
import csv
import gzip
import hashlib
import io
import json
import logging
import math
import os
import re
import tempfile
import time
from typing import Any

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, object_session

from app import auth
from app.db import SessionLocal
from app.models import Analysis, AnalysisFile, Dataset, User
from app.parsers import (
    classify,
    parse_delimited,
    parse_prn,
    parse_xlsx,
)
from app.security import now_epoch
from app.storage import decompress
from raschlab.cli import run_analyze

logger = logging.getLogger("app.analysis")

ENGINE_REF = "8e8ac67"
RETENTION_DAYS = 180
NOTICE_DAYS = 14
STALE_RUN_S = 900
RENDER_PAGE = 500

OUTPUT_FILES = (
    "item_table_15.1.csv",
    "option_table_15.3.csv",
    "person_table.csv",
    "summary_table.csv",
    "wright_map_measure.csv",
    "wright_map_frequency.csv",
)

PARAMS_DEFAULT = {
    "mode": "compat",
    "digits": 2,
    "lconv": None,
    "person_order": "misfit",
    "anchors": None,
    "pdfile": None,
}


class AnalysisError(Exception):
    """User-facing analysis exception with Indonesian error copy."""


def id_num(value: object) -> str:
    """Transform numeric string by grouping integer part with '.' and decimal with ','.

    Non-plain-number strings pass through untouched. Never parses to float.
    """
    if value is None:
        return ""
    s = str(value)
    m = re.fullmatch(r"([+-]?)(\d+)(?:\.(\d+))?", s)
    if not m:
        return s
    sign, int_part, dec_part = m.groups()
    rev = int_part[::-1]
    grouped_rev = ".".join(rev[i : i + 3] for i in range(0, len(rev), 3))
    grouped = grouped_rev[::-1]
    if dec_part is not None:
        return f"{sign}{grouped},{dec_part}"
    return f"{sign}{grouped}"


def _is_missing_token(token: str, mapping: dict[str, str] | None) -> bool:
    """True when a cell carries no response: blank, declared missing, or a default marker."""
    if not token:
        return True
    if mapping:
        cls = mapping.get(token) or mapping.get(token.strip().lower())
        if cls == "missing":
            return True
    try:
        return classify(token, mapping=None) == "missing"
    except ValueError:
        return False


def build_matrix_gzip(
    kind: str,
    person_labels: list[str],
    item_labels: list[str],
    rows: list[Any],
    mapping: dict[str, str] | None = None,
    control: dict[str, Any] | None = None,
    key: str | None = None,
) -> bytes:
    """Encode tabular or Winsteps response matrix into a deterministic gzip container."""
    if kind == "delimited":
        if not rows:
            raise AnalysisError("Tidak ada baris data respon.")
        n_items = len(item_labels) if item_labels else len(rows[0])
        if n_items == 0:
            raise AnalysisError("Tidak ada kolom butir yang valid.")

        unassigned: list[str] = []
        cell_tokens: set[str] = set()
        for row in rows:
            for cell in row:
                cell_tokens.add(str(cell).strip() if cell is not None else "")

        answer_key = (key or "").strip()
        if answer_key and len(answer_key) != n_items:
            raise AnalysisError(
                f"Panjang kunci jawaban ({len(answer_key)}) tidak sama dengan jumlah butir ({n_items})."
            )

        if answer_key:
            # An answer key scores every item on its own terms: the response letters travel
            # through unchanged and KEY1 carries the key, so the same letter can be right for
            # one item and wrong for another. Cells outside the response codes stay missing.
            missing_tokens = {t for t in cell_tokens if _is_missing_token(t, mapping)}
            response_tokens = {t for t in cell_tokens if t and t not in missing_tokens}
            invalid = sorted(t for t in response_tokens if t not in "ABCDE")
            if invalid:
                raise AnalysisError(
                    f"Kode respon '{', '.join(invalid)}' di luar huruf A-E; mesin hanya menerima A-E."
                )
            codes = "".join(sorted(response_tokens)) or "A"
            byte_space = ord(" ")
            mat = np.full((len(rows), n_items), byte_space, dtype=np.uint8)
            for r_idx, row in enumerate(rows):
                row_arr = mat[r_idx]
                for c_idx, cell in enumerate(row[:n_items]):
                    tok = str(cell).strip() if cell is not None else ""
                    if tok in response_tokens:
                        row_arr[c_idx] = ord(tok)
            key = answer_key
        else:
            for token in cell_tokens:
                try:
                    classify(token, mapping=mapping)
                except ValueError:
                    if token not in unassigned:
                        unassigned.append(token)

            if unassigned:
                raise AnalysisError(f"Ada token yang belum dipetakan: {', '.join(unassigned)}.")

            cell_incorrect = {t for t in cell_tokens if classify(t, mapping=mapping) == "incorrect"}
            mapped_incorrect = {
                str(k).strip() for k, v in (mapping or {}).items() if v == "incorrect"
            }
            all_incorrect = cell_incorrect | mapped_incorrect
            if len(all_incorrect) > 4:
                incorrect_sorted = sorted(all_incorrect)
                raise AnalysisError(
                    f"Jumlah token salah ({len(incorrect_sorted)}) melebihi batas maksimal 4 (huruf B-E): {', '.join(incorrect_sorted)}."
                )

            incorrect_tokens = sorted(all_incorrect)
            letters_pool = ["B", "C", "D", "E"]
            letter_map = {tok: letters_pool[i] for i, tok in enumerate(incorrect_tokens)}
            letters = "".join(letters_pool[i] for i in range(len(incorrect_tokens)))
            key = "A" * n_items
            codes = "A" + letters

            byte_map = {tok: ord(letter_map[tok]) for tok in incorrect_tokens}
            byte_a = ord("A")
            byte_space = ord(" ")

            mat = np.full((len(rows), n_items), byte_space, dtype=np.uint8)
            for r_idx, row in enumerate(rows):
                row_arr = mat[r_idx]
                for c_idx, cell in enumerate(row[:n_items]):
                    tok = str(cell).strip() if cell is not None else ""
                    cls = classify(tok, mapping=mapping)
                    if cls == "correct":
                        row_arr[c_idx] = byte_a
                    elif cls == "incorrect":
                        row_arr[c_idx] = byte_map[tok]
                    else:
                        row_arr[c_idx] = byte_space

        if not np.any(mat != byte_space):
            raise AnalysisError("Tidak ada data respon yang valid (semua sel kosong).")

        raw_bytes = mat.tobytes()
        del mat
        encoded_rows = [
            raw_bytes[i * n_items : (i + 1) * n_items].decode("ascii")
            for i in range(len(rows))
        ]
        del raw_bytes

    elif kind == "winsteps":
        if not rows:
            raise AnalysisError("Berkas PRN tidak memuat data baris responden yang valid.")

        key = ""
        codes = ""
        extra_missing = ""
        if mapping:
            key = str(mapping.get("key") or mapping.get("KEY1") or "").strip()
            codes = str(mapping.get("codes") or mapping.get("CODES") or "").strip()
            extra_missing = str(mapping.get("extra_missing") or "")
        if control:
            if not key:
                key = str(control.get("KEY1") or control.get("key") or "").strip()
            if not codes:
                codes = str(control.get("CODES") or control.get("codes") or "").strip()
        if not codes:
            codes = "ABCDE"

        invalid_codes = set(codes) - set("ABCDE")
        if invalid_codes:
            raise AnalysisError(f"Kode respon '{codes}' di luar huruf A-E; mesin hanya menerima A-E.")

        n_items = len(item_labels) if item_labels else (
            int(control.get("NI") or control.get("ni"))
            if control and (control.get("NI") or control.get("ni"))
            else len(rows[0])
        )

        if len(key) != n_items:
            raise AnalysisError(
                f"Panjang kunci jawaban ({len(key)}) tidak sama dengan jumlah butir ({n_items})."
            )
        for j, k_char in enumerate(key):
            if k_char not in codes:
                raise AnalysisError(
                    f"Karakter kunci jawaban '{k_char}' pada butir ke-{j+1} tidak ada dalam kode respon ({codes})."
                )

        extra_missing_set = set(extra_missing)
        valid_codes = set(codes) - extra_missing_set
        encoded_rows = []
        for row in rows:
            if isinstance(row, str):
                encoded_row = "".join(char if char in valid_codes else " " for char in row[:n_items])
            else:
                encoded_row = "".join(
                    str(cell).strip() if (str(cell).strip() in valid_codes) else " "
                    for cell in row[:n_items]
                )
            if len(encoded_row) < n_items:
                encoded_row = encoded_row.ljust(n_items, " ")
            encoded_rows.append(encoded_row)

        if not any(c != " " for r in encoded_rows for c in r):
            raise AnalysisError("Tidak ada data respon yang valid (semua sel kosong).")

    else:
        raise AnalysisError(f"Jenis dataset '{kind}' tidak didukung.")

    n_persons = len(encoded_rows)
    labels: list[str] = []
    for i in range(n_persons):
        p_label = person_labels[i] if i < len(person_labels) else ""
        p_str = str(p_label).strip() if p_label is not None else ""
        if not p_str:
            p_str = f"P{i+1:04d}"
        labels.append(p_str)

    namlen = max(1, max(len(l) for l in labels)) if labels else 1

    prn_lines = [
        labels[i].ljust(namlen) + encoded_rows[i]
        for i in range(n_persons)
    ]
    text = "\n".join(prn_lines)

    container = {
        "v": 1,
        "namlen": namlen,
        "key": key,
        "codes": codes,
        "prn": text,
    }
    return gzip.compress(json.dumps(container).encode("utf-8"), mtime=0.0)


def write_inputs(
    tmp_dir: str | os.PathLike, dataset: Dataset, matrix_gzip: bytes
) -> tuple[str, str]:
    """Write engine-ready data.prn, items.lbl, and analyze.CON into tmp_dir."""
    container = json.loads(gzip.decompress(matrix_gzip).decode("utf-8"))
    namlen = container["namlen"]
    key = container["key"]
    codes = container["codes"]
    prn_text = container["prn"]

    data_path = os.path.join(tmp_dir, "data.prn")
    with open(data_path, "w", encoding="utf-8") as f:
        f.write(f"{prn_text}\n")

    raw_labels = json.loads(dataset.item_labels_json) if dataset.item_labels_json else []
    lbl_lines = []
    for i in range(dataset.n_items):
        if i < len(raw_labels) and raw_labels[i] is not None:
            lbl = str(raw_labels[i]).replace("\r\n", " ").replace("\n", " ").replace("\r", " ").strip()
        else:
            lbl = f"I{i+1:02d}"
        if not lbl:
            lbl = f"I{i+1:02d}"
        lbl_lines.append(lbl)

    lbl_path = os.path.join(tmp_dir, "items.lbl")
    with open(lbl_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lbl_lines) + "\n")

    con_lines = [
        "&INST",
        "NAME1 = 1",
        f"NAMLEN = {namlen}",
        f"ITEM1 = {namlen + 1}",
        f"NI = {dataset.n_items}",
        f"KEY1 = {key}",
        f"CODES = {codes}",
        "DATA = data.prn",
        "ILABEL = items.lbl",
        "&END",
    ]
    con_path = os.path.join(tmp_dir, "analyze.CON")
    with open(con_path, "w", encoding="utf-8") as f:
        f.write("\n".join(con_lines) + "\n")

    return os.path.abspath(con_path), os.path.abspath(data_path)


def ensure_matrix(db: Session, dataset: Dataset) -> bytes:
    """Return precomputed matrix_gzip or lazily backfill legacy pre-F3 datasets."""
    if dataset.matrix_gzip is not None and len(dataset.matrix_gzip) > 0:
        return dataset.matrix_gzip

    raw_bytes = decompress(dataset.raw_gzip)
    summary = json.loads(dataset.summary_json) if dataset.summary_json else {}
    mapping = json.loads(dataset.mapping_json) if dataset.mapping_json else {}

    if dataset.kind == "delimited":
        parsed = parse_xlsx(raw_bytes) if dataset.format == "xlsx" else parse_delimited(raw_bytes)
        item_labels = (
            json.loads(dataset.item_labels_json)
            if dataset.item_labels_json
            else parsed.item_labels
        )
        matrix_gzip = build_matrix_gzip(
            kind="delimited",
            person_labels=parsed.person_labels,
            item_labels=item_labels,
            rows=parsed.rows,
            mapping=mapping,
            control=summary.get("control"),
        )
    else:
        control = summary.get("control", {})
        parsed = parse_prn(raw_bytes, control)
        item_labels = (
            json.loads(dataset.item_labels_json)
            if dataset.item_labels_json
            else [f"I{i+1:02d}" for i in range(dataset.n_items)]
        )
        matrix_gzip = build_matrix_gzip(
            kind="winsteps",
            person_labels=parsed.person_labels,
            item_labels=item_labels,
            rows=parsed.rows,
            mapping=mapping,
            control=control,
        )

    dataset.matrix_gzip = matrix_gzip
    db.commit()
    return matrix_gzip


def run_for_dataset(db: Session, dataset: Dataset) -> Analysis:
    """Execute analysis for dataset using the in-process engine and persist outputs."""
    matrix_gzip = ensure_matrix(db, dataset)

    created = now_epoch()
    expires = created + RETENTION_DAYS * 86400
    analysis = Analysis(
        user_id=dataset.user_id,
        dataset_id=dataset.id,
        status="queued",
        params_json=json.dumps(PARAMS_DEFAULT),
        engine_ref=ENGINE_REF,
        created_at=created,
        expires_at=expires,
    )
    db.add(analysis)
    db.commit()

    try:
        analysis.status = "running"
        analysis.started_at = now_epoch()
        db.commit()

        start_perf = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="raschlab_") as td:
            con_path, prn_path = write_inputs(td, dataset, matrix_gzip)
            del matrix_gzip

            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                    run_analyze(
                        con_path=con_path,
                        data_path=prn_path,
                        out_dir=td,
                        mode="compat",
                        out_format="csv",
                        digits=2,
                        lconv=None,
                        person_order="misfit",
                    )
            except (SystemExit, Exception) as exc:
                err_text = stderr_buf.getvalue()
                err_lines = [line.strip() for line in err_text.splitlines() if line.strip()]
                last_err = err_lines[-1] if err_lines else str(exc)
                if not last_err:
                    last_err = "kesalahan mesin"
                raise AnalysisError(f"Analisis gagal dijalankan mesin: {last_err[:1000]}") from exc

            elapsed_ms = int((time.perf_counter() - start_perf) * 1000)

            files_to_insert: list[AnalysisFile] = []
            for filename in OUTPUT_FILES:
                file_path = os.path.join(td, filename)
                if not os.path.isfile(file_path):
                    raise AnalysisError(f"Berkas luaran mesin '{filename}' tidak ditemukan.")
                with open(file_path, "rb") as f:
                    raw_file_bytes = f.read()
                compressed = gzip.compress(raw_file_bytes, mtime=0.0)
                sha = hashlib.sha256(raw_file_bytes).hexdigest()
                files_to_insert.append(
                    AnalysisFile(
                        analysis_id=analysis.id,
                        filename=filename,
                        content_gzip=compressed,
                        sha256=sha,
                        bytes=len(raw_file_bytes),
                    )
                )

            db.add_all(files_to_insert)
            analysis.status = "done"
            analysis.finished_at = now_epoch()
            analysis.elapsed_ms = elapsed_ms
            analysis.error = None
            db.commit()
            return analysis

    except (Exception, SystemExit) as exc:
        db.rollback()
        analysis.status = "failed"
        analysis.error = str(exc)
        analysis.finished_at = now_epoch()
        db.commit()
        return analysis


def load_tables(analysis: Analysis) -> dict[str, list[list[str]]]:
    """Decompress and parse all six engine CSV output files into table rows."""
    session = object_session(analysis)
    close_session = False
    if session is None:
        session = SessionLocal()
        close_session = True
    try:
        files = session.scalars(
            select(AnalysisFile).where(AnalysisFile.analysis_id == analysis.id)
        ).all()
    finally:
        if close_session:
            session.close()

    file_dict = {f.filename: f for f in files}
    result: dict[str, list[list[str]]] = {}
    for filename in OUTPUT_FILES:
        af = file_dict.get(filename)
        if af is None:
            result[filename] = []
            continue
        raw_csv = gzip.decompress(af.content_gzip).decode("utf-8")
        reader = csv.reader(io.StringIO(raw_csv))
        result[filename] = list(reader)
    return result


def latest_done_analysis(db: Session, dataset_id: int) -> Analysis | None:
    """Return the most recently completed analysis for a dataset."""
    return db.scalars(
        select(Analysis)
        .where(Analysis.dataset_id == dataset_id, Analysis.status == "done")
        .order_by(Analysis.id.desc())
    ).first()


class Paginated:
    """Paginated view of rows supporting iteration, indexing, and attributes."""

    def __init__(
        self,
        rows: list[Any],
        page: int,
        total_pages: int,
        total_rows: int,
        per_page: int = RENDER_PAGE,
    ) -> None:
        self.rows = rows
        self.items = rows
        self.page = page
        self.total_pages = total_pages
        self.total_rows = total_rows
        self.per_page = per_page
        self.has_prev = page > 1
        self.has_next = page < total_pages
        self.prev_page = page - 1 if self.has_prev else 1
        self.next_page = page + 1 if self.has_next else total_pages

    def __iter__(self):
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            if hasattr(self, item):
                return getattr(self, item)
            raise KeyError(item)
        return self.rows[item]

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


def paginate(rows: list[Any], page: Any, per_page: int = RENDER_PAGE) -> Paginated:
    """Clamp page number and slice rows into a Paginated view."""
    total_rows = len(rows)
    if per_page <= 0:
        per_page = RENDER_PAGE
    total_pages = max(1, math.ceil(total_rows / per_page))

    try:
        p = int(page)
    except (ValueError, TypeError):
        p = 1

    if p < 1:
        p = 1
    elif p > total_pages:
        p = total_pages

    start = (p - 1) * per_page
    end = start + per_page
    sliced = rows[start:end]

    return Paginated(
        rows=sliced,
        page=p,
        total_pages=total_pages,
        total_rows=total_rows,
        per_page=per_page,
    )


def retention_sweep(db: Session, now: int | None = None) -> dict[str, int]:
    """Purge expired analyses and dispatch near-expiry email notices."""
    if now is None:
        now = now_epoch()

    expired_ids = list(
        db.scalars(select(Analysis.id).where(Analysis.expires_at <= now)).all()
    )
    deleted_count = len(expired_ids)
    if expired_ids:
        db.execute(delete(AnalysisFile).where(AnalysisFile.analysis_id.in_(expired_ids)))
        db.execute(delete(Analysis).where(Analysis.id.in_(expired_ids)))
        db.commit()

    notice_threshold = now + NOTICE_DAYS * 86400
    candidates = list(
        db.scalars(
            select(Analysis).where(
                Analysis.status == "done",
                Analysis.notice_sent_at.is_(None),
                Analysis.expires_at > now,
                Analysis.expires_at <= notice_threshold,
            )
        ).all()
    )

    notified_count = 0
    for analysis in candidates:
        user = db.scalar(select(User).where(User.id == analysis.user_id))
        if user is None or not user.email:
            continue
        dataset = db.scalar(select(Dataset).where(Dataset.id == analysis.dataset_id))
        filename = dataset.filename if dataset else "berkas pengukuran"
        days_left = max(1, (analysis.expires_at - now) // 86400)

        subject = "Pemberitahuan Masa Simpan Hasil Analisis RaschLab"
        html = (
            f"<p>Halo,</p>"
            f"<p>Hasil analisis Rasch untuk berkas <strong>{filename}</strong> akan kedaluwarsa "
            f"dan dihapus dalam {days_left} hari.</p>"
            f"<p>Hasil analisis disimpan selama {RETENTION_DAYS} hari. "
            f"Silakan unduh atau tinjau kembali hasil analisis Anda sebelum batas waktu berakhir.</p>"
        )
        text = (
            f"Halo,\n\n"
            f"Hasil analisis Rasch untuk berkas {filename} akan kedaluwarsa "
            f"dan dihapus dalam {days_left} hari.\n\n"
            f"Hasil analisis disimpan selama {RETENTION_DAYS} hari. "
            f"Silakan unduh atau tinjau kembali hasil analisis Anda sebelum batas waktu berakhir."
        )
        try:
            auth.send_email(to=user.email, subject=subject, html=html, text=text)
            analysis.notice_sent_at = now
            db.commit()
            notified_count += 1
        except Exception:
            logger.exception(
                "Gagal mengirim surel pemberitahuan retensi analisis %s", analysis.id
            )

    return {"deleted": deleted_count, "notified": notified_count}
