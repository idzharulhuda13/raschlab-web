from __future__ import annotations

import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import (
    RETENTION_DAYS,
    STALE_RUN_S,
    id_num,
    load_tables,
    paginate,
)
from app.auth import _current_user, _gate_closed, templates
from app.db import get_session
from app.models import Analysis, Dataset
from app.security import now_epoch

templates.env.filters["id_num"] = id_num

PAGE_NOT_FOUND_MSG = "Halaman tidak ditemukan."
ANALYSIS_NOT_FOUND_MSG = "Analisis tidak ditemukan."
DATASET_NOT_FOUND_MSG = "Dataset tidak ditemukan."
STALE_RUN_ERROR_MSG = "Analisis terhenti saat berjalan. Jalankan ulang."
WRIGHT_ERROR_MSG = "Data peta Wright tidak dapat dibaca untuk analisis ini."
HIST_ERROR_MSG = "Sebaran partisipan tidak dapat digambar dari berkas analisis ini."
COMPARE_CAVEAT_MSG = (
    "Selisih lintas berkas hanya bermakna bila kedua analisis memakai butir penghubung (anchor) yang sama."
)
COMPARE_EMPTY_REASON_MSG = (
    "Belum ada analisis lain yang sudah selesai untuk dibandingkan. "
    "Jalankan analisis pada berkas ini atau berkas lain untuk membandingkan."
)
COMPARE_MISMATCH_REASON_MSG = (
    "Butir tidak dapat dipasangkan: berkas tanpa label butir hanya dapat dibandingkan bila jumlah butirnya sama."
)

VIEWS = ("wright", "butir", "partisipan", "ringkasan", "bandingkan")
FRAGMENT_VIEWS = ("butir", "partisipan", "ringkasan", "bandingkan")
TWO_DECIMALS = Decimal("0.01")


class ExplorerDataError(Exception):
    """Raised when Wright map or item data is malformed or empty."""


def build_person_histogram(payload: dict[str, Any]) -> dict[str, Any]:
    """Bars for the participant distribution, taken from the Wright binning.

    Reuses the map's own bins on purpose: one edge and one count per bin, so the histogram and the
    person bars on the map can never disagree about either. Returns
    ``{bins: [[measure, persons], ...], total, filled, step, min, max}``.
    """
    bins: list[list[Any]] = []
    for entry in payload.get("bins", []):
        try:
            measure = float(entry[0])
            persons = int(entry[1])
        except (IndexError, TypeError, ValueError):
            continue
        bins.append([f"{measure:.2f}", persons])
    bins.sort(key=lambda item: float(item[0]))
    total = sum(item[1] for item in bins)
    step = "0.25"
    if len(bins) > 1:
        delta = abs(float(bins[1][0]) - float(bins[0][0]))
        if delta > 0:
            step = f"{delta:.2f}"
    return {
        "schema": 1,
        "bins": bins,
        "total": total,
        "filled": sum(1 for item in bins if item[1] > 0),
        "step": step,
        "min": bins[0][0] if bins else None,
        "max": bins[-1][0] if bins else None,
    }


def build_wright_payload(
    wright_rows: list[list[str]],
    item_rows: list[list[str]],
) -> dict[str, Any]:
    """Parse raw CSV rows into client-facing Wright map schema 1 structure."""
    if not wright_rows or not wright_rows[0] or wright_rows[0][0] != "MEASURE":
        raise ExplorerDataError("Header MEASURE tidak ditemukan pada baris pertama peta Wright.")

    bins: list[list[str]] = []
    for row in wright_rows:
        if not row:
            continue
        try:
            float(row[0])
        except (ValueError, TypeError):
            continue
        nr_person = (row[1].strip() if len(row) > 1 else "") or "0"
        nr_item = (row[3].strip() if len(row) > 3 else "") or "0"
        item_entries = row[7] if len(row) > 7 else ""
        bins.append([row[0], nr_person, nr_item, item_entries])

    items: list[list[Any]] = []
    for row in item_rows:
        if not row or len(row) < 14:
            continue
        try:
            entry = int(row[0])
        except (ValueError, TypeError):
            continue
        items.append([
            entry,
            row[13],
            row[3],
            row[4],
            row[5],
            row[6],
            row[7],
            row[8],
            row[9],
            row[11],
        ])

    if not bins or not items:
        raise ExplorerDataError("Data bins atau items tidak boleh kosong.")

    return {
        "schema": 1,
        "bins": bins,
        "items": items,
    }


def filter_rows(
    rows: list[list[str]],
    q: str | None,
    cols: tuple[int, ...] | list[int],
) -> list[list[str]]:
    """Filter table rows by case-insensitive substring matching against target columns."""
    if not q:
        return rows
    needle = q.lower()
    return [
        row
        for row in rows
        if any(needle in str(row[c]).lower() for c in cols if c < len(row))
    ]


def build_compare_pairs(
    item_rows_from: list[list[str]],
    item_rows_to: list[list[str]],
) -> dict[str, Any]:
    """Join item tables on LABEL or ENTRY and compute measure deltas."""

    def _data_rows(rows: list[list[str]]) -> list[list[str]]:
        data: list[list[str]] = []
        if len(rows) > 2:
            for r in rows[2:]:
                if not r:
                    continue
                try:
                    int(r[0])
                except (ValueError, TypeError):
                    continue
                data.append(r)
        return data

    def _calc_delta(m_from: str, m_to: str) -> str:
        try:
            delta = (Decimal(m_to) - Decimal(m_from)).quantize(TWO_DECIMALS, rounding=ROUND_HALF_UP)
            if delta == 0:
                return "0.00"
            if delta > 0:
                return f"+{delta}"
            return f"{delta}"
        except Exception:
            return "0.00"

    from_data = _data_rows(item_rows_from)
    to_data = _data_rows(item_rows_to)

    from_has_labels = any(len(r) > 13 and bool(r[13].strip()) for r in from_data)
    to_has_labels = any(len(r) > 13 and bool(r[13].strip()) for r in to_data)

    pairs: list[list[Any]] = []
    matched: int = 0
    unmatched_from: int = 0
    unmatched_to: int = 0
    key_used: str | None = None
    empty_reason: str | None = None

    if from_has_labels and to_has_labels:
        key_used = "label"
        from_items: dict[str, tuple[int, str, str]] = {}
        for r in from_data:
            lbl = r[13].strip() if len(r) > 13 else ""
            if not lbl:
                continue
            entry = int(r[0])
            m = r[3] if len(r) > 3 else ""
            if lbl not in from_items:
                from_items[lbl] = (entry, lbl, m)

        to_items: dict[str, tuple[int, str, str]] = {}
        for r in to_data:
            lbl = r[13].strip() if len(r) > 13 else ""
            if not lbl:
                continue
            entry = int(r[0])
            m = r[3] if len(r) > 3 else ""
            if lbl not in to_items:
                to_items[lbl] = (entry, lbl, m)

        from_keys = set(from_items.keys())
        to_keys = set(to_items.keys())
        common_labels = from_keys & to_keys

        for lbl in common_labels:
            entry_from, _, m_from = from_items[lbl]
            _, _, m_to = to_items[lbl]
            delta_str = _calc_delta(m_from, m_to)
            pairs.append([entry_from, lbl, m_from, m_to, delta_str])

        pairs.sort(key=lambda p: p[0])
        matched = len(pairs)
        unmatched_from = len(from_keys - to_keys)
        unmatched_to = len(to_keys - from_keys)
        empty_reason = None if pairs else COMPARE_MISMATCH_REASON_MSG

    elif not from_has_labels and not to_has_labels and len(from_data) == len(to_data) and len(from_data) > 0:
        key_used = "entry"
        from_by_entry: dict[int, tuple[int, str, str]] = {}
        for r in from_data:
            entry = int(r[0])
            lbl = r[13] if len(r) > 13 else ""
            m = r[3] if len(r) > 3 else ""
            if entry not in from_by_entry:
                from_by_entry[entry] = (entry, lbl, m)

        to_by_entry: dict[int, tuple[int, str, str]] = {}
        for r in to_data:
            entry = int(r[0])
            lbl = r[13] if len(r) > 13 else ""
            m = r[3] if len(r) > 3 else ""
            if entry not in to_by_entry:
                to_by_entry[entry] = (entry, lbl, m)

        from_keys_e = set(from_by_entry.keys())
        to_keys_e = set(to_by_entry.keys())
        common_entries = from_keys_e & to_keys_e

        for entry in common_entries:
            entry_from, lbl, m_from = from_by_entry[entry]
            _, _, m_to = to_by_entry[entry]
            delta_str = _calc_delta(m_from, m_to)
            pairs.append([entry_from, lbl, m_from, m_to, delta_str])

        pairs.sort(key=lambda p: p[0])
        matched = len(pairs)
        unmatched_from = len(from_keys_e - to_keys_e)
        unmatched_to = len(to_keys_e - from_keys_e)
        empty_reason = None if pairs else COMPARE_MISMATCH_REASON_MSG

    else:
        pairs = []
        matched = 0
        unmatched_from = 0
        unmatched_to = 0
        key_used = None
        empty_reason = COMPARE_MISMATCH_REASON_MSG

    return {
        "pairs": pairs,
        "matched": matched,
        "unmatched_from": unmatched_from,
        "unmatched_to": unmatched_to,
        "key_used": key_used,
        "empty_reason": empty_reason,
    }


def _to_positive_int(val: Any) -> int:
    try:
        n = int(val)
        return n if n >= 1 else 1
    except (ValueError, TypeError):
        return 1


router = APIRouter()


@router.get("/analyses/{id}/explore", response_class=HTMLResponse)
def get_explore(
    id: int,
    request: Request,
    db: Session = Depends(get_session),
):
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

    now = now_epoch()
    ref_time = analysis.started_at or analysis.created_at
    if analysis.status in ("queued", "running") and (
        (now - ref_time > STALE_RUN_S) or (now - analysis.created_at > STALE_RUN_S)
    ):
        analysis.status = "failed"
        analysis.error = STALE_RUN_ERROR_MSG
        analysis.finished_at = now
        db.commit()

    if analysis.status != "done":
        return RedirectResponse(f"/analyses/{analysis.id}", status_code=303)

    raw_view = request.query_params.get("view", "wright")
    active_view = raw_view if raw_view in VIEWS else "wright"

    fragment = request.query_params.get("fragment")
    if fragment is not None:
        if fragment not in FRAGMENT_VIEWS:
            raise HTTPException(status_code=404, detail=PAGE_NOT_FOUND_MSG)
        render_view = fragment
    else:
        render_view = active_view

    q_item = request.query_params.get("q_item", "")
    q_person = request.query_params.get("q_person", "")

    page_item_req = _to_positive_int(request.query_params.get("page_item", 1))
    page_person_req = _to_positive_int(request.query_params.get("page_person", 1))

    from_val = request.query_params.get("from")
    to_val = request.query_params.get("to")
    from_analysis = None
    to_analysis = None
    from_id = None
    to_id = None

    if from_val is not None or to_val is not None:
        if from_val is None or to_val is None:
            raise HTTPException(status_code=404, detail=ANALYSIS_NOT_FOUND_MSG)
        try:
            from_id = int(from_val)
            to_id = int(to_val)
        except (ValueError, TypeError):
            raise HTTPException(status_code=404, detail=ANALYSIS_NOT_FOUND_MSG)

        if from_id == to_id:
            raise HTTPException(status_code=404, detail=ANALYSIS_NOT_FOUND_MSG)

        from_analysis = db.scalar(select(Analysis).where(Analysis.id == from_id))
        if from_analysis is None or from_analysis.user_id != user.id or from_analysis.status != "done":
            raise HTTPException(status_code=404, detail=ANALYSIS_NOT_FOUND_MSG)

        to_analysis = db.scalar(select(Analysis).where(Analysis.id == to_id))
        if to_analysis is None or to_analysis.user_id != user.id or to_analysis.status != "done":
            raise HTTPException(status_code=404, detail=ANALYSIS_NOT_FOUND_MSG)

    tables = load_tables(analysis)
    item_rows = tables.get("item_table_15.1.csv", [])
    person_rows = tables.get("person_table.csv", [])
    summary_rows = tables.get("summary_table.csv", [])
    wright_rows = tables.get("wright_map_measure.csv", [])

    rekap: dict[str, str] = {}
    for row in summary_rows:
        if len(row) >= 3:
            k = f"{row[0]} {row[1]}".strip()
            rekap[k] = row[2]

    tab_params = "&".join(f"{k}={quote(str(v))}" for k, v in request.query_params.multi_items() if k != "view")

    context: dict[str, Any] = {
        "user": user,
        "dataset": dataset,
        "analysis": analysis,
        "status": analysis.status,
        "engine_ref": analysis.engine_ref,
        "elapsed_ms": analysis.elapsed_ms,
        "retention_days": RETENTION_DAYS,
        "rekap": rekap,
        "params": json.loads(analysis.params_json) if analysis.params_json else {},
        "active_view": active_view,
        "render_view": render_view,
        "views": list(VIEWS),
        "tab_params": tab_params,
        "q_item": q_item,
        "q_person": q_person,
        "page_item": page_item_req,
        "page_person": page_person_req,
        "from": from_id,
        "to": to_id,
        "wright_error": None,
        "hist_json": None,
        "hist_ctx": None,
        "hist_error": None,
        "item_ctx": None,
        "person_ctx": None,
        "summary_headers": [],
        "summary_rows": [],
        "sum_headers": [],
        "sum_data": [],
        "compare_ctx": None,
    }

    if fragment is None:
        try:
            payload = build_wright_payload(wright_rows, item_rows)
            context["payload_json"] = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
        except (ExplorerDataError, ValueError, IndexError, KeyError):
            context["wright_error"] = WRIGHT_ERROR_MSG

    if render_view == "butir":
        item_headers = item_rows[:2] if len(item_rows) >= 2 else []
        item_data = item_rows[2:] if len(item_rows) >= 2 else []
        filtered_items = filter_rows(item_data, q_item, (0, 13))
        item_paged = paginate(filtered_items, page_item_req)
        context["item_ctx"] = {
            "headers": item_headers,
            "rows": item_paged.rows,
            "count": len(filtered_items),
            "paged": item_paged,
        }
        context["page_item"] = item_paged.page

    elif render_view == "partisipan":
        person_headers = person_rows[:2] if len(person_rows) >= 2 else []
        person_data = person_rows[2:] if len(person_rows) >= 2 else []
        filtered_persons = filter_rows(person_data, q_person, (0, 13))
        person_paged = paginate(filtered_persons, page_person_req)
        context["person_ctx"] = {
            "headers": person_headers,
            "rows": person_paged.rows,
            "count": len(filtered_persons),
            "paged": person_paged,
        }
        context["page_person"] = person_paged.page
        try:
            histogram = build_person_histogram(build_wright_payload(wright_rows, item_rows))
            context["hist_json"] = json.dumps(histogram, separators=(",", ":")).replace("</", "<\\/")
            context["hist_ctx"] = {
                "total": histogram["total"],
                "bins": len(histogram["bins"]),
                "step": histogram["step"],
            }
        except (ExplorerDataError, ValueError, IndexError, KeyError, TypeError):
            context["hist_error"] = HIST_ERROR_MSG

    elif render_view == "ringkasan":
        summary_headers = summary_rows[:1] if summary_rows else []
        sum_headers = (
            summary_rows[:2]
            if (len(summary_rows) >= 2 and summary_rows[1] == ["", "", ""])
            else summary_headers
        )
        sum_data = (
            summary_rows[2:]
            if (len(summary_rows) >= 2 and summary_rows[1] == ["", "", ""])
            else (summary_rows[1:] if len(summary_rows) >= 1 else [])
        )
        context["summary_headers"] = summary_headers
        context["summary_rows"] = summary_rows
        context["sum_headers"] = sum_headers
        context["sum_data"] = sum_data

    elif render_view == "bandingkan":
        options_stmt = (
            select(Analysis.id, Analysis.created_at, Dataset.filename)
            .join(Dataset, Analysis.dataset_id == Dataset.id)
            .where(Analysis.user_id == user.id, Analysis.status == "done")
            .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        )
        done_analyses = db.execute(options_stmt).all()
        options = [
            {
                "id": row.id,
                "dataset_filename": row.filename,
                "created_at": row.created_at,
                "created_at_label": datetime.datetime.fromtimestamp(row.created_at).strftime("%Y-%m-%d %H:%M"),
            }
            for row in done_analyses
        ]
        empty_reason = COMPARE_EMPTY_REASON_MSG if len(options) < 2 else None

        if from_analysis is not None and to_analysis is not None:
            from_dataset = db.scalar(select(Dataset).where(Dataset.id == from_analysis.dataset_id))
            to_dataset = db.scalar(select(Dataset).where(Dataset.id == to_analysis.dataset_id))
            from_fn = from_dataset.filename if from_dataset else ""
            to_fn = to_dataset.filename if to_dataset else ""

            from_time = datetime.datetime.fromtimestamp(from_analysis.created_at).strftime("%Y-%m-%d %H:%M")
            to_time = datetime.datetime.fromtimestamp(to_analysis.created_at).strftime("%Y-%m-%d %H:%M")
            statement = f"Membandingkan Analisis #{from_id} ({from_time}) dengan Analisis #{to_id} ({to_time})."

            if from_id == analysis.id:
                items_from = item_rows
                rekap_from = rekap
            else:
                tables_from = load_tables(from_analysis)
                items_from = tables_from.get("item_table_15.1.csv", [])
                summary_from = tables_from.get("summary_table.csv", [])
                rekap_from = {}
                for r in summary_from:
                    if len(r) >= 3:
                        rekap_from[f"{r[0]} {r[1]}".strip()] = r[2]

            if to_id == analysis.id:
                items_to = item_rows
                rekap_to = rekap
            else:
                tables_to = load_tables(to_analysis)
                items_to = tables_to.get("item_table_15.1.csv", [])
                summary_to = tables_to.get("summary_table.csv", [])
                rekap_to = {}
                for r in summary_to:
                    if len(r) >= 3:
                        rekap_to[f"{r[0]} {r[1]}".strip()] = r[2]

            means = {
                "from": rekap_from.get("ITEM MEASURE MEAN", ""),
                "to": rekap_to.get("ITEM MEASURE MEAN", ""),
            }

            cmp_result = build_compare_pairs(items_from, items_to)
            cmp_payload = {
                "schema": 1,
                "from_id": from_id,
                "to_id": to_id,
                "from_label": f"Analisis #{from_id} ({from_fn})",
                "to_label": f"Analisis #{to_id} ({to_fn})",
                "pairs": cmp_result["pairs"],
            }
            cmp_data_json = json.dumps(cmp_payload, separators=(",", ":")).replace("</", "<\\/")

            context["compare_ctx"] = {
                "options": options,
                "from_id": from_id,
                "to_id": to_id,
                "from_dataset_filename": from_fn,
                "to_dataset_filename": to_fn,
                "statement": statement,
                "means": means,
                "matched": cmp_result["matched"],
                "unmatched_from": cmp_result["unmatched_from"],
                "unmatched_to": cmp_result["unmatched_to"],
                "key_used": cmp_result["key_used"],
                "caveat": COMPARE_CAVEAT_MSG,
                "empty_reason": empty_reason,
                "pairs": cmp_result["pairs"],
                "cmp_data_json": cmp_data_json,
            }
        else:
            context["compare_ctx"] = {
                "options": options,
                "from_id": None,
                "to_id": None,
                "from_dataset_filename": None,
                "to_dataset_filename": None,
                "statement": None,
                "means": None,
                "matched": 0,
                "unmatched_from": 0,
                "unmatched_to": 0,
                "key_used": None,
                "caveat": COMPARE_CAVEAT_MSG,
                "empty_reason": empty_reason,
                "pairs": [],
                "cmp_data_json": None,
            }

    template_name = "explore/fragment.html" if fragment is not None else "explore.html"
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=context,
        status_code=200,
    )
