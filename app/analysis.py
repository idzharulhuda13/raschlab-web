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
from sqlalchemy import delete, select, update
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

ENGINE_REF = "3b40711"
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
    "subsubtes_summary.csv",
    "tabulasi_summary.csv",
    "tabulasi_item.csv",
)

MISFIT_THRESHOLD_DEFAULT = 1.5
MISFIT_MIN, MISFIT_MAX = 0.5, 5.0
DIGITS_MIN, DIGITS_MAX = 1, 4
MODE_CHOICES = ("compat", "exact")

DELETE_LIST_MAX_BYTES = 2 * 1024 * 1024
DELETE_LIST_EXTENSIONS = (".txt", ".csv", ".dat")
DELETE_LIST_NAME_MAX = 120
PICK_DELETE_LIST_NAMES = {"pdfile": "peserta-dipilih.txt", "idfile": "butir-dipilih.txt"}

ANCHOR_MAX_BYTES = 64 * 1024
ANCHOR_MAX_LINES = 5000
PICK_ANCHOR_NAME = "jangkar-dipilih.txt"

PARAMS_DEFAULT = {
    "misfit": MISFIT_THRESHOLD_DEFAULT,
    "mode": "compat",
    "digits": 2,
    "lconv": None,
    "person_order": "misfit",
    "anchors": None,
    "pdfile": None,
    "idfile": None,
}


def format_threshold(value) -> str:
    """Render a misfit threshold the way the pages show it: two decimals, comma separator."""
    return f"{float(value):.2f}".replace(".", ",")


def parse_settings_form(form) -> dict:
    """Return analysis params from the settings form, defaulting anything absent or empty.

    form is any mapping with .get (a Starlette FormData). Raises AnalysisError with Indonesian copy
    when a value is present but not a usable one. Never falls back to the default on bad input.
    """
    params = dict(PARAMS_DEFAULT)
    raw_misfit = form.get("misfit")
    if raw_misfit is not None and str(raw_misfit).strip() != "":
        text = str(raw_misfit).strip().replace(",", ".")
        try:
            misfit = float(text)
        except ValueError as exc:
            raise AnalysisError("Ambang misfit harus berupa angka antara 0,5 dan 5,0.") from exc
        if not (MISFIT_MIN <= misfit <= MISFIT_MAX):
            raise AnalysisError("Ambang misfit harus berada antara 0,5 dan 5,0.")
        params["misfit"] = misfit
    raw_mode = form.get("mode")
    if raw_mode is not None and str(raw_mode).strip() != "":
        mode = str(raw_mode).strip()
        if mode not in MODE_CHOICES:
            raise AnalysisError("Mode kalibrasi harus compat atau exact.")
        params["mode"] = mode
    raw_digits = form.get("digits")
    if raw_digits is not None and str(raw_digits).strip() != "":
        text = str(raw_digits).strip()
        try:
            digits = int(text)
        except ValueError as exc:
            raise AnalysisError("Desimal harus berupa bilangan bulat antara 1 dan 4.") from exc
        if not (DIGITS_MIN <= digits <= DIGITS_MAX):
            raise AnalysisError("Desimal harus berada antara 1 dan 4.")
        params["digits"] = digits
    return params


def _looks_binary(text: str) -> bool:
    """True when decoded text carries the fingerprints of a binary file.

    latin-1 decodes every byte sequence, so the decode loop on its own can never reject a binary
    upload. A NUL byte, or a run of control characters no numbering list contains, is what tells the
    two apart.
    """
    if "\x00" in text:
        return True
    control = sum(1 for ch in text if ord(ch) < 32 and ch not in "\t\n\r\f")
    return control > max(8, len(text) // 100)


def parse_delete_list(filename: str, content: bytes) -> dict:
    """Validate an uploaded delete list and return the metadata plus decoded text.

    The text is handed to the engine only; it never reaches a log, an error message, or
    params_json. Raises AnalysisError with Indonesian copy when the upload is unusable.
    """
    base = os.path.basename(str(filename).replace("\\", "/"))
    if os.path.splitext(base)[1].lower() not in DELETE_LIST_EXTENSIONS:
        raise AnalysisError("Daftar hapus harus berupa berkas teks (.txt, .csv, atau .dat).")
    if len(content) > DELETE_LIST_MAX_BYTES:
        raise AnalysisError("Daftar hapus terlalu besar (maksimal 2 MB).")

    text = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None or _looks_binary(text):
        raise AnalysisError("Daftar hapus harus berupa teks biasa, bukan berkas biner.")

    rows = sum(1 for line in text.splitlines() if line.strip())
    if rows == 0:
        raise AnalysisError("Daftar hapus kosong.")

    return {
        "name": base[:DELETE_LIST_NAME_MAX],
        "text": text,
        "rows": rows,
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "content": content,
    }


def parse_anchors(filename: str, content: bytes, item_labels: list[str]) -> dict:
    """Validate an uploaded anchor file and return the anchor map.

    Accepted lines, mixed freely in one file:
      - "<nomor_butir> <nilai>": 1-based item position in the built matrix;
      - "<nama_butir> <nilai>": item label as it appears in the dataset columns.
    Blank lines and lines starting with # are skipped. Extra tokens after the value are ignored
    (engine parity). A line whose first token is an integer is always read as a position.
    Precedence: label lines are applied first, then position lines, so a position line wins when both
    name the same item; within one form the LAST line wins. Values must be finite numbers.
    The returned map is the record used to rebuild the engine anchor file for a re-run, so the anchor
    values are stored together with the analysis. Raises AnalysisError with Indonesian copy when the
    upload is unusable.
    """
    base = os.path.basename(str(filename).replace("\\", "/"))
    if len(content) > ANCHOR_MAX_BYTES:
        raise AnalysisError("Berkas jangkar terlalu besar (maksimal 64 KB).")

    text = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None or _looks_binary(text):
        raise AnalysisError("Berkas jangkar harus berupa teks biasa, bukan berkas biner.")
    if not text.strip():
        raise AnalysisError("Berkas jangkar kosong.")
    if len(text.splitlines()) > ANCHOR_MAX_LINES:
        raise AnalysisError("Berkas jangkar terlalu banyak baris (maksimal 5000 baris).")

    n_items = len(item_labels)
    by_label: dict[int, float] = {}
    by_position: dict[int, float] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            raise AnalysisError(
                f"Baris jangkar '{line}' tidak lengkap: butuh nomor atau nama butir lalu nilai jangkar."
            )
        is_position = re.fullmatch(r"[+-]?\d+", parts[0]) is not None
        if is_position:
            position = int(parts[0])
            if position < 1 or position > n_items:
                raise AnalysisError(f"Nomor butir {position} di luar rentang 1 sampai {n_items}.")
            value_token = parts[1]
        else:
            label = None
            for width in range(len(parts) - 1, 0, -1):
                candidate = " ".join(parts[:width])
                if candidate in item_labels:
                    label, value_token = candidate, parts[width]
                    break
            if label is None:
                raise AnalysisError(
                    f"Nama butir '{' '.join(parts[:-1])}' tidak ada pada kolom butir dataset."
                )
            if item_labels.count(label) > 1:
                raise AnalysisError(f"Nama butir '{label}' ganda pada kolom butir; pakai nomor butir.")
            position = item_labels.index(label) + 1
        try:
            value = float(value_token)
        except ValueError:
            raise AnalysisError(f"Nilai jangkar '{value_token}' pada baris '{line}' bukan angka.")
        if not math.isfinite(value):
            raise AnalysisError(f"Nilai jangkar '{value_token}' pada baris '{line}' bukan angka.")
        if is_position:
            by_position[position] = value
        else:
            by_label[position] = value

    anchors = {**by_label, **by_position}
    if not anchors:
        raise AnalysisError("Tidak ada baris jangkar yang dapat dibaca.")
    from_position = sum(1 for position in by_position if position in anchors)
    return {
        "name": base[:DELETE_LIST_NAME_MAX],
        "requested": len(anchors),
        "anchors": anchors,
        "by_position": from_position,
        "by_label": len(anchors) - from_position,
    }


class AnalysisError(Exception):
    """User-facing analysis exception with Indonesian error copy."""


def validate_control_directives(control: dict, n_items: int, container_codes: str) -> dict:
    """Narrow and check the honoured .CON directives, raising AnalysisError on a value the engine cannot use.

    Rules come from the engine's own format document: CODES is an alphabet (any distinct single
    characters, not just A to E), every response code in the data must appear in it, a KEY1 may only
    use characters that CODES declares valid, and MISSCORE is either a number or a list of codes.
    """
    honoured: dict[str, str] = {}
    for name in ("KEY1", "CODES", "MISSCORE"):
        value = control.get(name)
        if value is None or str(value).strip() == "":
            continue
        honoured[name] = str(value).strip()

    codes = honoured.get("CODES", container_codes)
    if honoured.get("CODES"):
        if any(ch.isspace() for ch in codes):
            raise AnalysisError(f"Kode respon pada berkas kontrol ({codes}) tidak boleh memuat spasi.")
        if len(set(codes)) != len(codes):
            raise AnalysisError(f"Kode respon pada berkas kontrol ({codes}) tidak boleh memuat karakter berulang.")
    for ch in container_codes:
        if ch not in codes:
            raise AnalysisError(
                f"Kode respon pada berkas kontrol ({codes}) tidak mencakup kode data ({container_codes})."
            )

    key = honoured.get("KEY1")
    if key is not None:
        if len(key) != n_items:
            raise AnalysisError(
                f"Panjang kunci jawaban pada berkas kontrol ({len(key)}) tidak sama dengan jumlah butir ({n_items})."
            )
        outside = sorted({ch for ch in key if ch not in codes})
        if outside:
            raise AnalysisError(
                f"Kunci jawaban pada berkas kontrol memuat kode yang tidak ada di CODES: {''.join(outside)}."
            )

    misscore = honoured.get("MISSCORE")
    if misscore is not None and not _is_number(misscore):
        outside = sorted({ch for ch in misscore if ch not in codes})
        if outside:
            raise AnalysisError(
                f"Nilai MISSCORE pada berkas kontrol ({misscore}) harus berupa angka atau daftar kode "
                f"yang ada di CODES: {''.join(outside)} tidak dikenal."
            )
    return honoured


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True



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
            ctrl_codes = ""
            if control and isinstance(control, dict):
                ctrl_codes = str(control.get("CODES") or control.get("codes") or "").strip()
            effective = ctrl_codes if ctrl_codes else ("".join(sorted(response_tokens)) or "A")
            invalid = sorted(t for t in response_tokens if len(t) != 1 or t not in effective)
            if invalid:
                raise AnalysisError(
                    f"Kode respon '{', '.join(invalid)}' tidak ada di alfabet berkas kontrol ({effective}). Satu karakter per sel."
                )
            codes = effective
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

        invalid_codes = [c for c in codes if len(c) != 1 or c.isspace()]
        if invalid_codes or not codes:
            raise AnalysisError(f"Kode respon '{codes}' harus satu karakter per sel tanpa spasi.")

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


def effective_item_labels(dataset: Dataset) -> list[str]:
    """Return the item labels the engine will see, one entry per item column.

    The order is the dataset item-column order and the list always holds exactly
    dataset.n_items entries; a missing or blank label falls back to I<nn>.
    """
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
    return lbl_lines


def effective_person_labels(dataset: Dataset) -> list[str]:
    """Return person labels the engine sees, extracted from the stored matrix container."""
    if not dataset.matrix_gzip:
        return []
    try:
        container = json.loads(gzip.decompress(dataset.matrix_gzip).decode("utf-8"))
        namlen = int(container.get("namlen", 0))
        prn = str(container.get("prn", ""))
        if namlen <= 0 or not prn:
            return []
        labels = []
        for line in prn.splitlines():
            labels.append(line[:namlen].strip())
        return labels
    except Exception:
        return []


def delete_list_from_positions(values: list[str], max_rows: int, name: str) -> dict | None:
    """Build and parse a delete list from submitted position numbers."""
    cleaned = []
    seen = set()
    for v in values:
        t = str(v).strip()
        if not t:
            continue
        if re.fullmatch(r"[+-]?\d+", t) is None:
            raise AnalysisError(f"Nomor baris '{v}' bukan bilangan bulat.")
        n = int(t)
        if n < 1 or n > max_rows:
            raise AnalysisError(f"Nomor baris {n} di luar rentang 1 sampai {max_rows}.")
        if n not in seen:
            seen.add(n)
            cleaned.append(n)
    if not cleaned:
        return None
    cleaned.sort()
    content = "".join(f"{n}\n" for n in cleaned).encode("utf-8")
    return parse_delete_list(name, content)


def anchors_from_positions(
    pos_values: list[str], value_values: list[str], item_labels: list[str]
) -> dict | None:
    """Build and parse anchor values from submitted position numbers and logit values."""
    lines = []
    for p_raw, v_raw in zip(pos_values, value_values):
        v = str(v_raw).strip()
        if not v:
            continue
        p = str(p_raw).strip()
        if re.fullmatch(r"[+-]?\d+", p) is None:
            raise AnalysisError(f"Nomor butir '{p}' pada pilihan jangkar bukan bilangan bulat.")
        lines.append(f"{p} {v}\n")
    if not lines:
        return None
    content = "".join(lines).encode("utf-8")
    return parse_anchors(PICK_ANCHOR_NAME, content, item_labels)


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

    lbl_lines = effective_item_labels(dataset)

    lbl_path = os.path.join(tmp_dir, "items.lbl")
    with open(lbl_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lbl_lines) + "\n")

    control = {}
    if dataset.summary_json:
        try:
            control = (json.loads(dataset.summary_json).get("control") or {})
        except (TypeError, ValueError):
            control = {}
    if not isinstance(control, dict):
        control = {}

    honoured = validate_control_directives(control, dataset.n_items, codes)
    if "KEY1" in honoured:
        key = honoured["KEY1"]
    if "CODES" in honoured:
        codes = honoured["CODES"]

    con_lines = [
        "&INST",
        "NAME1 = 1",
        f"NAMLEN = {namlen}",
        f"ITEM1 = {namlen + 1}",
        f"NI = {dataset.n_items}",
        f"KEY1 = {key}",
        f"CODES = {codes}",
    ]
    if "MISSCORE" in honoured:
        con_lines.append(f"MISSCORE = {honoured['MISSCORE']}")
    con_lines.extend(
        [
            "DATA = data.prn",
            "ILABEL = items.lbl",
            "&END",
        ]
    )
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


def run_for_dataset(
    db: Session,
    dataset: Dataset,
    params: dict | None = None,
    delete_lists: dict | None = None,
) -> Analysis:
    """Execute analysis for dataset using the in-process engine and persist outputs.

    delete_lists optionally carries the parsed pdfile/idfile uploads (see parse_delete_list).
    Each supplied list is written into the run's temp dir, passed to the engine, and stored as
    an extra AnalysisFile row; only its metadata is recorded in params_json, never its text.
    params may carry an "anchors" entry (see parse_anchors): it is validated here, written into
    the run's temp dir, handed to the engine, and its requested/used counts are recorded in
    params_json. Anchors deleted by the item delete list are dropped by the engine, so "used"
    counts only the anchors the engine really applies.
    """
    merged = {**PARAMS_DEFAULT, **(params or {})}
    lists = delete_lists or {}
    for key in ("pdfile", "idfile"):
        entry = lists.get(key)
        if entry is not None:
            merged[key] = {
                "name": entry["name"],
                "sha256": entry["sha256"],
                "rows": entry["rows"],
                "bytes": entry["bytes"],
            }
    anchors_map: dict[int, float] = {}
    stored_anchors = merged.get("anchors")
    if stored_anchors is not None:
        invalid = "Struktur jangkar tersimpan tidak valid. Jalankan ulang tanpa jangkar."
        if not isinstance(stored_anchors, dict) or not isinstance(stored_anchors.get("anchors"), dict):
            raise AnalysisError(invalid)
        for raw_position, raw_value in stored_anchors["anchors"].items():
            try:
                position = int(raw_position)
                value = float(raw_value)
            except (TypeError, ValueError):
                raise AnalysisError(invalid)
            if position < 1 or position > dataset.n_items:
                raise AnalysisError(invalid)
            if not math.isfinite(value):
                raise AnalysisError(invalid)
            anchors_map[position] = value
        if not anchors_map:
            stored_anchors = None
        else:
            deleted_items = set()
            idfile_entry = lists.get("idfile")
            if idfile_entry is not None:
                for token in str(idfile_entry.get("text") or "").split():
                    if re.fullmatch(r"[+-]?\d+", token):
                        deleted_items.add(int(token))
            stored_anchors = {
                **stored_anchors,
                "requested": len(anchors_map),
                "used": sum(1 for position in anchors_map if position not in deleted_items),
            }
        merged["anchors"] = stored_anchors

    matrix_gzip = ensure_matrix(db, dataset)

    created = now_epoch()
    expires = created + RETENTION_DAYS * 86400
    analysis = Analysis(
        user_id=dataset.user_id,
        dataset_id=dataset.id,
        status="queued",
        params_json=json.dumps(merged),
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

            list_paths: dict[str, str] = {}
            for key, dest_name in (
                ("pdfile", "pdfile_input.TXT"),
                ("idfile", "idfile_input.TXT"),
            ):
                entry = lists.get(key)
                if entry is None:
                    continue
                dest_path = os.path.join(td, dest_name)
                with open(dest_path, "wb") as f:
                    f.write(entry.get("content") or entry["text"].encode("utf-8"))
                list_paths[key] = os.path.abspath(dest_path)

            anchors_path = None
            if anchors_map:
                anchors_dest = os.path.join(td, "anchors_input.TXT")
                with open(anchors_dest, "w", encoding="utf-8") as f:
                    for position in sorted(anchors_map):
                        f.write(f"{position} {anchors_map[position]}\n")
                anchors_path = os.path.abspath(anchors_dest)

            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                    run_analyze(
                        con_path=con_path,
                        data_path=prn_path,
                        out_dir=td,
                        mode=merged["mode"],
                        out_format="csv",
                        digits=merged["digits"],
                        lconv=merged.get("lconv"),
                        person_order=merged.get("person_order") or "misfit",
                        pdfile_path=list_paths.get("pdfile"),
                        idfile_path=list_paths.get("idfile"),
                        anchors_path=anchors_path,
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

            for key, stored_name in (
                ("pdfile", "input_pdfile.TXT"),
                ("idfile", "input_idfile.TXT"),
            ):
                list_path = list_paths.get(key)
                if list_path is None:
                    continue
                with open(list_path, "rb") as f:
                    raw_list_bytes = f.read()
                files_to_insert.append(
                    AnalysisFile(
                        analysis_id=analysis.id,
                        filename=stored_name,
                        content_gzip=gzip.compress(raw_list_bytes, mtime=0.0),
                        sha256=hashlib.sha256(raw_list_bytes).hexdigest(),
                        bytes=len(raw_list_bytes),
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
    """Decompress and parse every engine CSV listed in OUTPUT_FILES into table rows."""
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


def mark_analysis(db: Session, analysis: Analysis, marked: bool) -> None:
    """Mark an analysis as the version in use for its dataset, or clear the mark.

    At most one analysis per dataset carries the mark, and the invariant lives here rather than in
    a constraint because the same models build the SQLite test schema while production is Postgres.
    Marking demotes every sibling of the dataset in the same commit as the mark itself, so a reader
    can never catch two marked rows between the two statements. The timestamp records when the run
    was marked and is never refreshed: calling this on an already marked analysis changes nothing.
    Clearing the mark never touches the siblings, because unmarking one run says nothing about
    which other run should take over.
    """
    if not marked:
        analysis.primary_at = None
        db.commit()
        return

    already_marked = analysis.primary_at is not None
    db.execute(
        update(Analysis)
        .where(Analysis.dataset_id == analysis.dataset_id, Analysis.id != analysis.id)
        .values(primary_at=None)
    )
    if not already_marked:
        analysis.primary_at = now_epoch()
    db.commit()


def marked_analysis_id(db: Session, dataset_id: int) -> int | None:
    """Return the id of the analysis marked as the version in use for a dataset, or None.

    Defensive by design: a store written before the write path kept the invariant can carry more
    than one marked row, so the newest by primary_at and then by id answers instead of raising.
    """
    return db.scalars(
        select(Analysis.id)
        .where(Analysis.dataset_id == dataset_id, Analysis.primary_at.isnot(None))
        .order_by(Analysis.primary_at.desc(), Analysis.id.desc())
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
