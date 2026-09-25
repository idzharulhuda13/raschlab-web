"""Parsers and classification rules for tabular and Winsteps datasets.

Pure functions converting in-memory raw bytes (CSV, XLSX, .CON, .prn) into
standardised person-item matrices without database or disk I/O.
Per PLAN.md D2, D4, and D5, parsing and classification live in the platform
to keep the parity-verified engine frozen while guaranteeing zero drift
between preview, commit, and verification tests.
"""

import csv
import io
import re
from typing import Any, Iterable, NamedTuple
import openpyxl

from app.storage import (
    MAX_CELLS as _MAX_CELLS,
    MAX_UPLOAD_BYTES as _MAX_UPLOAD_BYTES,
    StorageError as _StorageError,
)

__all__ = [
    "CANONICAL_CLASSES",
    "DEFAULT_MISSING_TOKENS",
    "KEY_ROW_LABELS",
    "MAX_DISTINCT_TOKENS_PER_ITEM",
    "PERSON_LABEL_HEADERS",
    "ParsedDataset",
    "PrnDataset",
    "classify",
    "count_all_missing_persons",
    "default_mapping",
    "distinct_tokens",
    "implausible_item_columns",
    "missing_per_item",
    "parse_control",
    "parse_delimited",
    "parse_prn",
    "parse_xlsx",
    "validate_mapping",
]

# Canonical response classifications defined by PLAN.md D5.
CANONICAL_CLASSES: frozenset[str] = frozenset({"correct", "incorrect", "missing"})

# Standard missing tokens for delimited/spreadsheet tables (matches pandas default NA).
DEFAULT_MISSING_TOKENS: frozenset[str] = frozenset({"", "na", "n/a", "x", ".", "-"})

# Column 0 headers that signal an explicit person identifier rather than an item response.
PERSON_LABEL_HEADERS: frozenset[str] = frozenset(
    {
        "id",
        "nama",
        "name",
        "no",
        "respondent",
        "person",
        "responden",
        "responden_id",
        "nama_responden",
        "subjek",
        "subjek_id",
        "siswa",
        "peserta",
        "kode",
        "kode_responden",
        "no_responden",
        # Identity columns as exported by the assessment platforms in use.
        # Without these, the identity column is read as an item column, which both
        # loses the real person identifiers and turns every identifier into a
        # response token that the mapping page would have to enumerate.
        "username",
        "user",
        "user_id",
        "uname",
        "login",
        "akun",
        "peserta_id",
        "id_peserta",
        "nomor",
        "nomor_peserta",
        "no_peserta",
        "nopes",
        "kode_peserta",
        "nis",
        "nisn",
        "nip",
        "kandidat",
        "testee",
        "uid",
        "subject",
        "subject_id",
        "respondent_id",
        "person_id",
        "sample",
        "sampel",
    }
)

# A first cell naming the answer-key row of a wide matrix export.
KEY_ROW_LABELS: frozenset[str] = frozenset(
    {
        "kunci",
        "kunci_jawaban",
        "kunci_jawaban_benar",
        "jawaban",
        "key",
        "answer_key",
        "answerkey",
    }
)

# An item column whose values are this many distinct tokens, and mostly unique per
# row, is an identity column that was not recognised by PERSON_LABEL_HEADERS.
MAX_DISTINCT_TOKENS_PER_ITEM: int = 64
UNIQUE_COLUMN_RATIO: float = 0.5


def _cells_over_limit(total_cells: int) -> str:
    """Message for a matrix larger than MAX_CELLS, carrying the observed size."""
    return (
        f"Dataset cell count exceeds MAX_CELLS limit ({_MAX_CELLS}) "
        f"(found {total_cells} cells)"
    )


def _normalize_header(header: str) -> str:
    s = header.strip().rstrip("*").strip().lower()
    return re.sub(r"[\s\-_]+", "_", s)


class ParsedDataset(NamedTuple):
    """Standard container for wide person-by-item response matrices."""

    person_labels: list[str]
    item_labels: list[str]
    rows: list[list[str]]
    key: list[str] | None = None

    @property
    def matrix(self) -> list[list[str]]:
        return self.rows


class PrnDataset(NamedTuple):
    """Container for parsed fixed-width Winsteps matrix rows."""

    person_labels: list[str]
    rows: list[str]

    @property
    def labels(self) -> list[str]:
        return self.person_labels


def _sniff_delimiter(sample: str | Iterable[str]) -> str:
    delims = [",", ";", "\t"]
    if isinstance(sample, str):
        lines = [line for line in sample.splitlines() if line.strip()]
    else:
        lines = [line for line in sample if line.strip()]

    sample_lines = lines[:10]
    if not sample_lines:
        return ","

    best_delim = ","
    best_count = 1

    for d in delims:
        try:
            reader = csv.reader(sample_lines, delimiter=d)
            counts = [len(row) for row in reader]
        except Exception:
            continue
        if counts and all(c == counts[0] for c in counts) and counts[0] > 1:
            if counts[0] > best_count:
                best_count = counts[0]
                best_delim = d

    return best_delim


def _format_cell(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return str(val)
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val).strip()


def parse_delimited(raw: bytes) -> ParsedDataset:
    """Parse UTF-8/UTF-8-SIG delimited text into person labels, item labels, and cells."""
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise _StorageError(
            f"Payload size {len(raw)} bytes exceeds MAX_UPLOAD_BYTES ({_MAX_UPLOAD_BYTES})"
        )

    lines = raw.decode("utf-8-sig").splitlines()
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return ParsedDataset(person_labels=[], item_labels=[], rows=[])

    reader = csv.reader(lines, delimiter=_sniff_delimiter(non_empty[:10]))
    header: list[str] | None = None
    has_person_col, item_labels = False, []
    person_labels, rows = [], []
    answer_key: list[str] | None = None
    total_cells, row_idx = 0, 0

    for raw_row in reader:
        if not any(cell.strip() for cell in raw_row):
            continue

        if header is None:
            header = [c.strip() for c in raw_row]
            while header and not header[-1]:
                header.pop()
            if not header:
                header = None
                continue
            has_person_col = _normalize_header(header[0]) in PERSON_LABEL_HEADERS
            item_labels = header[1:] if has_person_col else header
            continue

        n_items = len(item_labels)
        if has_person_col:
            marker = _normalize_header(raw_row[0]) if raw_row else ""
            item_cells = [c.strip() for c in raw_row[1 : 1 + n_items]]
        else:
            marker = ""
            item_cells = [c.strip() for c in raw_row[:n_items]]

        if len(item_cells) < n_items:
            item_cells.extend([""] * (n_items - len(item_cells)))

        # A row whose first cell names the answer key, with every item filled, is the
        # key row of the export: it is the key, never a respondent.
        if (
            answer_key is None
            and marker in KEY_ROW_LABELS
            and item_cells
            and all(cell for cell in item_cells)
        ):
            answer_key = item_cells
            continue

        row_idx += 1
        if not has_person_col:
            p_label = f"P{row_idx:04d}"
        else:
            p_label = (raw_row[0].strip() or f"P{row_idx:04d}") if raw_row else f"P{row_idx:04d}"

        total_cells += n_items
        if total_cells > _MAX_CELLS:
            # Report the whole file, not the partial count at the moment the cap tripped.
            projected = max(total_cells, (len(non_empty) - 1) * n_items)
            raise _StorageError(_cells_over_limit(projected))

        person_labels.append(p_label)
        rows.append(item_cells)

    return ParsedDataset(person_labels=person_labels, item_labels=item_labels, rows=rows, key=answer_key)


def parse_xlsx(raw: bytes) -> ParsedDataset:
    """Read first sheet of an Excel workbook in read-only mode under memory caps."""
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise _StorageError(
            f"Payload size {len(raw)} bytes exceeds MAX_UPLOAD_BYTES ({_MAX_UPLOAD_BYTES})"
        )

    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        sheet_names = wb.sheetnames
        if not sheet_names:
            return ParsedDataset(person_labels=[], item_labels=[], rows=[])
        ws = wb[sheet_names[0]]

        header: list[str] | None = None
        has_person_col, item_labels = False, []
        person_labels, rows = [], []
        total_cells, row_idx = 0, 0

        for raw_row in ws.iter_rows(values_only=True):
            formatted_cells = [_format_cell(v) for v in raw_row]
            if not any(formatted_cells):
                continue

            if header is None:
                header = formatted_cells
                while header and not header[-1]:
                    header.pop()
                if not header:
                    header = None
                    continue
                has_person_col = _normalize_header(header[0]) in PERSON_LABEL_HEADERS
                item_labels = header[1:] if has_person_col else header
                continue

            row_idx += 1
            n_items = len(item_labels)
            if has_person_col:
                p_label = (
                    formatted_cells[0].strip() or f"P{row_idx:04d}"
                    if formatted_cells
                    else f"P{row_idx:04d}"
                )
                item_cells = formatted_cells[1 : 1 + n_items]
            else:
                p_label = f"P{row_idx:04d}"
                item_cells = formatted_cells[:n_items]

            if len(item_cells) < n_items:
                item_cells.extend([""] * (n_items - len(item_cells)))

            total_cells += n_items
            if total_cells > _MAX_CELLS:
                raise _StorageError(_cells_over_limit(total_cells))

            person_labels.append(p_label)
            rows.append(item_cells)

        return ParsedDataset(person_labels=person_labels, item_labels=item_labels, rows=rows)
    finally:
        wb.close()


def parse_control(raw: bytes) -> dict[str, Any]:
    """Parse Winsteps control directives from the &INST ... &END block."""
    lines = raw.decode("utf-8-sig").splitlines()
    inst_idx: int | None = None
    end_idx: int | None = None

    for i, line in enumerate(lines):
        s = line.strip().upper()
        if s.startswith("&INST") and inst_idx is None:
            inst_idx = i
        elif s.startswith("&END") and inst_idx is not None:
            end_idx = i
            break

    if inst_idx is None:
        raise ValueError("Missing &INST in control file")
    if end_idx is None:
        raise ValueError("Missing &END in control file")

    result: dict[str, Any] = {}
    for line in lines[inst_idx + 1 : end_idx]:
        content = line.split(";", 1)[0]
        if "=" not in content:
            continue
        key_raw, val_raw = content.split("=", 1)
        key, val = key_raw.strip().upper(), val_raw.strip()

        if key != "KEY1":
            if val.isdigit() or (val.startswith(("-", "+")) and len(val) > 1 and val[1:].isdigit()):
                result[key] = int(val)
            else:
                result[key] = val
        else:
            result[key] = str(val)

    if "KEY1" in result:
        result["KEY1"] = str(result["KEY1"])
        if "NI" in result and len(result["KEY1"]) != int(result["NI"]):
            raise ValueError(f"KEY1 length ({len(result['KEY1'])}) does not match NI ({result['NI']})")

    return result


def parse_prn(raw: bytes, control: dict[str, Any]) -> PrnDataset:
    """Parse fixed-width Winsteps matrix rows using control directives."""
    item1 = int(control.get("ITEM1") or control.get("item1"))
    ni = int(control.get("NI") or control.get("ni"))
    namlen = int(control.get("NAMLEN") or control.get("namlen"))

    lines = raw.decode("utf-8-sig").splitlines()
    labels, rows = [], []
    total_cells = 0

    for line in lines:
        if not line.strip():
            continue
        total_cells += ni
        if total_cells > _MAX_CELLS:
            raise _StorageError(_cells_over_limit(total_cells))
        labels.append(line[0:namlen].strip())
        raw_row = line[item1 - 1 : item1 - 1 + ni]
        rows.append(raw_row.ljust(ni, " "))

    return PrnDataset(person_labels=labels, rows=rows)


def classify(
    value: str,
    mapping: dict[str, str] | None = None,
    *,
    key_char: str | None = None,
    codes: str | set[str] | None = None,
) -> str:
    """Classify a response token into 'correct', 'incorrect', or 'missing' per D5."""
    if key_char is not None or codes is not None:
        valid_codes = set(codes) if codes is not None else set("ABCDE")
        if value not in valid_codes:
            return "missing"
        if key_char is not None and value == key_char:
            return "correct"
        return "incorrect"

    if mapping is not None:
        val_str = str(value)
        cls = (
            mapping.get(val_str)
            or mapping.get(val_str.strip())
            or mapping.get(val_str.strip().lower())
        )
        if cls in CANONICAL_CLASSES:
            return cls
        if cls is not None:
            raise ValueError(f"Invalid canonical class '{cls}' for token '{value}'")
        raise ValueError(f"Unassigned token: '{value}'")

    val_str = str(value).strip()
    if val_str.lower() in DEFAULT_MISSING_TOKENS:
        return "missing"
    if val_str == "1":
        return "correct"
    if val_str == "0":
        return "incorrect"
    raise ValueError(f"Unassigned token: '{value}'")


def implausible_item_columns(
    data: ParsedDataset | PrnDataset | list[list[str]],
) -> list[tuple[str, int, int]]:
    """Return ``(label, distinct, rows)`` for item columns that cannot be answer codes.

    A response column holds a small set of codes (A-E, 0/1, missing markers). A column
    whose values are almost all unique is an identity column that ``PERSON_LABEL_HEADERS``
    did not recognise: reading it as an item column loses the real identifiers and turns
    every identifier into a token the mapping page would have to enumerate.
    """
    if isinstance(data, ParsedDataset):
        rows = data.rows
        labels = list(data.item_labels)
    elif isinstance(data, PrnDataset):
        rows = data.rows
        labels = [f"I{i + 1:02d}" for i in range(len(rows[0]) if rows else 0)]
    else:
        rows = data
        labels = [f"I{i + 1:02d}" for i in range(len(rows[0]) if rows else 0)]

    n_rows = len(rows)
    if n_rows == 0 or not labels:
        return []

    offenders: list[tuple[str, int, int]] = []
    for idx, label in enumerate(labels):
        values = {row[idx].strip() for row in rows if idx < len(row) and row[idx].strip()}
        distinct = len(values)
        if distinct > MAX_DISTINCT_TOKENS_PER_ITEM and distinct >= UNIQUE_COLUMN_RATIO * n_rows:
            offenders.append((str(label), distinct, n_rows))
    return offenders


def distinct_tokens(
    data: ParsedDataset | PrnDataset | list[list[str]] | list[str] | tuple[list[str], list[str]],
) -> dict[str, int]:
    """Tally distinct response tokens across all item cells."""
    if isinstance(data, (ParsedDataset, PrnDataset)):
        rows = data.rows
    elif isinstance(data, tuple) and len(data) == 2 and isinstance(data[1], list):
        rows = data[1]
    else:
        rows = data

    counts: dict[str, int] = {}
    if not rows:
        return counts

    if isinstance(rows[0], str):
        for row in rows:
            for char in row:
                counts[char] = counts.get(char, 0) + 1
    else:
        for row in rows:
            for cell in row:
                token = str(cell).strip() if cell is not None else ""
                counts[token] = counts.get(token, 0) + 1

    return counts


def validate_mapping(tokens: Iterable[str], mapping: dict[str, str]) -> list[str]:
    """Return all tokens lacking an explicit assignment in CANONICAL_CLASSES."""
    unassigned: list[str] = []
    for token in tokens:
        t_str = str(token)
        cls = (
            mapping.get(t_str)
            or mapping.get(t_str.strip())
            or mapping.get(t_str.strip().lower())
        )
        if cls not in CANONICAL_CLASSES:
            unassigned.append(t_str)
    return unassigned


def default_mapping(tokens: Iterable[str]) -> dict[str, str]:
    """Build default Path A value mapping for distinct tokens per PLAN.md D5."""
    mapping: dict[str, str] = {}
    tokens_list = list(tokens)
    remaining: list[str] = []

    for t in tokens_list:
        if str(t).strip().lower() in DEFAULT_MISSING_TOKENS:
            mapping[t] = "missing"
        else:
            remaining.append(t)

    remaining_clean = {str(t).strip() for t in remaining}
    if remaining_clean.issubset({"0", "1"}) and remaining_clean:
        for t in remaining:
            clean = str(t).strip()
            if clean == "1":
                mapping[t] = "correct"
            elif clean == "0":
                mapping[t] = "incorrect"

    return mapping


def missing_per_item(
    data: ParsedDataset | PrnDataset | list[list[str]] | list[str] | tuple[list[str], list[str]],
    mapping: dict[str, str] | None = None,
    *,
    codes: str | set[str] | None = None,
    extra_missing: str = "",
) -> list[int]:
    """Compute per-item missing count vector across respondents.

    If extra_missing is provided, any characters in extra_missing are treated
    as missing responses, even if they appear in codes.
    """
    if isinstance(data, (ParsedDataset, PrnDataset)):
        rows = data.rows
    elif isinstance(data, tuple) and len(data) == 2 and isinstance(data[1], list):
        rows = data[1]
    else:
        rows = data

    if not rows:
        return []

    is_prn = isinstance(rows[0], str)
    n_items = len(rows[0])
    counts = [0] * n_items
    extra_missing_set = set(extra_missing) if extra_missing else set()

    if is_prn:
        valid_codes = (set(codes) if codes is not None else set("ABCDE")) - extra_missing_set
        for row in rows:
            for c in range(n_items):
                char = row[c] if c < len(row) else " "
                if char not in valid_codes:
                    counts[c] += 1
    else:
        for row in rows:
            for c in range(n_items):
                cell = row[c] if c < len(row) else ""
                token = str(cell).strip()
                if extra_missing_set and token in extra_missing_set:
                    counts[c] += 1
                elif mapping is not None:
                    cls = mapping.get(token) or mapping.get(token.lower())
                    if cls == "missing":
                        counts[c] += 1
                else:
                    if token.lower() in DEFAULT_MISSING_TOKENS:
                        counts[c] += 1

    return counts


def count_all_missing_persons(
    data: ParsedDataset | PrnDataset | list[list[str]] | list[str] | tuple[list[str], list[str]],
    mapping: dict[str, str] | None = None,
    *,
    codes: str | set[str] | None = None,
    extra_missing: str = "",
) -> int:
    """Count respondents whose item responses are all missing."""
    if isinstance(data, (ParsedDataset, PrnDataset)):
        rows = data.rows
    elif isinstance(data, tuple) and len(data) == 2 and isinstance(data[1], list):
        rows = data[1]
    else:
        rows = data

    if not rows:
        return 0

    is_prn = isinstance(rows[0], str)
    extra_missing_set = set(extra_missing) if extra_missing else set()
    count = 0

    if is_prn:
        valid_codes = (set(codes) if codes is not None else set("ABCDE")) - extra_missing_set
        for row in rows:
            if not row:
                continue
            if all(char not in valid_codes for char in row):
                count += 1
    else:
        for row in rows:
            if not row:
                continue
            row_all_missing = True
            for cell in row:
                token = str(cell).strip() if cell is not None else ""
                if extra_missing_set and token in extra_missing_set:
                    continue
                if mapping is not None:
                    cls = mapping.get(token) or mapping.get(token.lower())
                    if cls != "missing":
                        row_all_missing = False
                        break
                else:
                    if token.lower() not in DEFAULT_MISSING_TOKENS:
                        row_all_missing = False
                        break
            if row_all_missing:
                count += 1

    return count