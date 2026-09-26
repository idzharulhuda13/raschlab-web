"""Module for exporting RaschLab analysis tables to XLSX format."""

import io
import openpyxl
from openpyxl.cell import WriteOnlyCell
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.analysis import load_tables
from app.auth import _current_user, _gate_closed
from app.db import get_session
from app.explore import (
    ANALYSIS_NOT_FOUND_MSG,
    DATASET_NOT_FOUND_MSG,
    PAGE_NOT_FOUND_MSG,
    build_compare_pairs,
)
from app.models import Analysis, Dataset
from app.ratelimit import check_limit, client_ip
from raschlab.report import coerce_cell, number_format_for_header, summary_value_format

TABLE_KEYS = {"butir": "item_table_15.1.csv", "opsi": "option_table_15.3.csv", "responden": "person_table.csv", "ringkasan": "summary_table.csv", "wright": "wright_map_measure.csv"}
HEADER_ROWS = {"butir": 2, "opsi": 2, "responden": 2, "ringkasan": 1, "wright": 2, "bandingkan": 1}
SHEET_TITLES = {"butir": "butir", "opsi": "opsi", "responden": "responden", "ringkasan": "ringkasan", "wright": "wright", "bandingkan": "bandingkan"}
COMPARE_HEADER = ["Nomor", "Butir", "Measure analisis pertama", "Measure analisis kedua", "Selisih (kedua − pertama)"]
COMPARE_NUMERIC = {0: "int", 2: "float", 3: "float", 4: "float"}
SUMMARY_NUMERIC = {2: "summary"}
WRIGHT_NUMERIC = {0: "raw", 1: "raw", 3: "raw"}
TABLE_NUMERIC = {"ringkasan": SUMMARY_NUMERIC, "wright": WRIGHT_NUMERIC}
EXPORT_MAX_ROWS = 1_048_000
EXPORT_MAX_CELLS = 2_500_000
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXPORT_TABLE_NOT_FOUND_MSG = "Tabel unduhan tidak tersedia untuk analisis ini."
EXPORT_RATE_MSG = "Batasan unduhan Excel tercapai (30 unduhan per jam). Silakan coba lagi nanti."
EXPORT_RATE_LIMIT = 30
EXPORT_RATE_WINDOW_S = 3600


def build_xlsx(sheet_title: str, rows: list[list[str]], header_rows: int, numeric: dict[int, str] | None = None) -> bytes:
    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet(title=sheet_title)
    labels = rows[header_rows - 1] if rows and header_rows >= 1 else []
    for r_idx, row in enumerate(rows):
        row_cells = []
        for c_idx, raw in enumerate(row):
            value = "" if raw is None else str(raw)
            if r_idx < header_rows:
                row_cells.append(WriteOnlyCell(ws, value=value or None))
                continue
            fmt = None
            mode = None if numeric is None else numeric.get(c_idx)
            if mode == "raw":
                value, _ = coerce_cell(value, "0.00" if "." in value else "0")
            elif mode == "summary":
                fmt = summary_value_format(value)
                if fmt is not None:
                    value, fmt = coerce_cell(value, fmt)
            elif mode == "int":
                value, fmt = coerce_cell(value, "0")
            elif mode == "float":
                value, fmt = coerce_cell(value, "0.00")
            else:
                fmt = number_format_for_header(labels[c_idx] if c_idx < len(labels) else "")
                if fmt is not None:
                    value, fmt = coerce_cell(value, fmt)
            if value == "":
                value = None
            cell = WriteOnlyCell(ws, value=value)
            if fmt:
                cell.number_format = fmt
            row_cells.append(cell)
        ws.append(row_cells)
    ws.freeze_panes = "A" + str(header_rows + 1)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def message_page(text: str, status_code: int, extra_headers: dict[str, str] | None = None) -> Response:
    body = "<!doctype html><html lang=\"id\"><head><meta charset=\"utf-8\"><title>Unduhan Excel: RaschLab</title></head><body><p>" + text + "</p><p><a href=\"/analyses\">Kembali ke daftar hasil analisis</a></p></body></html>"
    return Response(content=body, status_code=status_code, media_type="text/html", headers=extra_headers)


def _compare_rows(db: Session, user, request: Request) -> list[list[str]] | None:
    """Rows of the comparison sheet, mirroring the pairing the explore view renders."""
    from_val = request.query_params.get("from")
    to_val = request.query_params.get("to")
    if not from_val or not to_val:
        return None
    try:
        from_id = int(from_val)
        to_id = int(to_val)
    except (TypeError, ValueError):
        return None
    if from_id == to_id:
        return None
    from_analysis = db.scalar(select(Analysis).where(Analysis.id == from_id))
    if from_analysis is None or from_analysis.user_id != user.id or from_analysis.status != "done":
        return None
    to_analysis = db.scalar(select(Analysis).where(Analysis.id == to_id))
    if to_analysis is None or to_analysis.user_id != user.id or to_analysis.status != "done":
        return None
    items_from = load_tables(from_analysis).get("item_table_15.1.csv", [])
    items_to = load_tables(to_analysis).get("item_table_15.1.csv", [])
    pairs = build_compare_pairs(items_from, items_to)["pairs"]
    return [COMPARE_HEADER] + [[pair[0], pair[1], pair[2], pair[3], pair[4]] for pair in pairs]


router = APIRouter()


@router.get("/analyses/{id}/export")
def export_table(id: int, request: Request, table: str | None = None,
                 db: Session = Depends(get_session)) -> Response:
    """Download one result table of one finished analysis as an XLSX workbook."""
    if _gate_closed():
        raise HTTPException(status_code=404, detail=PAGE_NOT_FOUND_MSG)
    user = _current_user(request, db)
    if user is None:
        raise HTTPException(status_code=404, detail=PAGE_NOT_FOUND_MSG)

    analysis = db.scalar(select(Analysis).where(Analysis.id == id))
    if analysis is None or analysis.user_id != user.id:
        raise HTTPException(status_code=404, detail=ANALYSIS_NOT_FOUND_MSG)

    dataset = db.scalar(select(Dataset).where(Dataset.id == analysis.dataset_id))
    if dataset is None or dataset.user_id != user.id:
        raise HTTPException(status_code=404, detail=DATASET_NOT_FOUND_MSG)

    if analysis.status != "done":
        return RedirectResponse(f"/analyses/{analysis.id}", status_code=303)

    table = (table or "").strip()
    if table not in SHEET_TITLES:
        raise HTTPException(status_code=404, detail=EXPORT_TABLE_NOT_FOUND_MSG)

    allowed, retry_after = check_limit(
        "export:" + client_ip(request) + ":" + str(user.id),
        EXPORT_RATE_LIMIT,
        EXPORT_RATE_WINDOW_S,
    )
    if not allowed:
        return message_page(EXPORT_RATE_MSG, 429, {"Retry-After": str(retry_after)})

    if table == "bandingkan":
        rows = _compare_rows(db, user, request)
        if rows is None:
            raise HTTPException(status_code=404, detail=EXPORT_TABLE_NOT_FOUND_MSG)
        numeric = COMPARE_NUMERIC
        header_rows = HEADER_ROWS["bandingkan"]
    else:
        stored = load_tables(analysis).get(TABLE_KEYS[table]) or []
        rows = [row for row in stored]
        if not rows or all(not any(str(cell).strip() for cell in row) for row in rows):
            raise HTTPException(status_code=404, detail=EXPORT_TABLE_NOT_FOUND_MSG)
        numeric = TABLE_NUMERIC.get(table)
        header_rows = HEADER_ROWS[table]

    cells = sum(len(row) for row in rows)
    if len(rows) > EXPORT_MAX_ROWS or cells > EXPORT_MAX_CELLS:
        message = (
            f"Tabel ini memuat {len(rows)} baris dan {cells} sel, melebihi batas unduhan Excel"
            f" ({EXPORT_MAX_ROWS} baris dan {EXPORT_MAX_CELLS} sel)."
        )
        return message_page(message, 413)

    body = build_xlsx(SHEET_TITLES[table], rows, header_rows, numeric)
    filename = f"raschlab-{id}-{table}.xlsx"
    return Response(
        content=body,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{filename}",
            "Cache-Control": "no-store",
        },
    )
