"""Analysis routes: execution triggering, status monitoring, and result presentation.

Provides endpoints for launching Rasch calibration on prepared datasets,
querying analysis lifecycle progress, inspecting output tables, and orchestrating
background data retention sweeps.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import (
    MISFIT_THRESHOLD_DEFAULT,
    MODE_CHOICES,
    PARAMS_DEFAULT,
    RETENTION_DAYS,
    STALE_RUN_S,
    AnalysisError,
    PICK_DELETE_LIST_NAMES,
    anchors_from_positions,
    delete_list_from_positions,
    effective_item_labels,
    effective_person_labels,
    format_threshold,
    id_num,
    latest_done_analysis,
    mark_analysis,
    parse_anchors,
    parse_delete_list,
    parse_settings_form,
    retention_sweep,
    run_for_dataset,
)
from app.auth import _current_user, _gate_closed, templates
from app.db import SessionLocal, get_session
from app.ingest import _build_dataset_context
from app.models import Analysis, Dataset
from app.ratelimit import check_limit, client_ip
from app.security import now_epoch

logger = logging.getLogger("app.analyze")

templates.env.filters["id_num"] = id_num


STATUS_KEYS = ("kept", "deleted", "lacking", "extreme_min", "extreme_max")
BAND_X0, BAND_X1 = 10.0, 550.0


def _clean_audit(person_rows: list[list[str]], rekap: dict[str, str]) -> dict[str, Any] | None:
    """What the engine kept and dropped, read from the STATUS column it now writes.

    Returns None when the respondent table carries no STATUS column, which is the case for every
    analysis run before that column existed: the page then says so in words instead of drawing
    zeros, because a zero here reads as "nothing was removed" and that would be a lie.

    Geometry is computed here rather than in the template so the band's segment widths are derived
    from the data and stay in one place.
    """
    if len(person_rows) < 2:
        return None
    header = [str(h).strip().upper() for h in person_rows[1]]
    if "STATUS" not in header:
        return None
    idx = header.index("STATUS")
    counts: dict[str, int] = dict.fromkeys(STATUS_KEYS, 0)
    for row in person_rows[2:]:
        if len(row) <= idx:
            continue
        key = str(row[idx]).strip().lower()
        if key in counts:
            counts[key] += 1
    total = sum(counts.values())
    if total == 0:
        return None
    span = BAND_X1 - BAND_X0
    ekstrem = counts["extreme_min"] + counts["extreme_max"]

    def width(value: int) -> float:
        return round(span * value / total, 2)

    def pct(value: int) -> str:
        return f"{value / total * 100:.1f}".replace(".", ",")

    def summary_int(statistic: str) -> int:
        raw = str(rekap.get(f"COUNTS {statistic}", "0")).strip() or "0"
        try:
            return max(0, int(float(raw)))
        except ValueError:
            return 0

    w_ekstrem = width(ekstrem)
    return {
        "dipakai": counts["kept"],
        "dihapus": counts["deleted"],
        "kurang": counts["lacking"],
        "ekstrem_bawah": counts["extreme_min"],
        "ekstrem_atas": counts["extreme_max"],
        "ekstrem": ekstrem,
        "total": total,
        "butir_dihapus": summary_int("ITEM DELETED"),
        "pct_dipakai": pct(counts["kept"]),
        "pct_dihapus": pct(counts["deleted"]),
        "pct_ekstrem": pct(ekstrem),
        "x_dipakai": BAND_X0,
        "w_dipakai": width(counts["kept"]),
        "x_dihapus": round(BAND_X0 + width(counts["kept"]), 2),
        "w_dihapus": width(counts["deleted"]),
        "x_ekstrem": round(BAND_X1 - w_ekstrem, 2),
        "w_ekstrem": w_ekstrem,
    }


def _infit_mnsq_column(item_rows: list[list[str]]) -> int:
    """Return the INFIT MNSQ column index, or -1 when the table does not carry it.

    Two layouts exist: the engine writes the name across the two header rows (INFIT, then
    MNSQ in the same column), while older hand-built tables carry it as a single cell that
    reads INFIT MNSQ. Both must resolve to the same column, so that a real analysis and a
    legacy fixture produce the same misfit count.
    """
    if not item_rows:
        return -1
    first = [str(h).strip().upper() for h in item_rows[0]]
    second = [str(h).strip().upper() for h in item_rows[1]] if len(item_rows) > 1 else []
    try:
        return first.index("INFIT MNSQ")
    except ValueError:
        pass
    for i, cell in enumerate(first):
        if cell.startswith("INFIT") and i < len(second) and second[i] == "MNSQ":
            return i
    return -1


DELETE_LIST_LABELS = (
    ("pdfile", "Daftar hapus peserta"),
    ("idfile", "Daftar hapus butir"),
)


def _delete_lists_from_params(params: Any) -> list[dict[str, Any]]:
    """Read the delete lists a run recorded, tolerating anything older or malformed.

    A legacy params_json without these keys, a None, or an entry that is not a readable
    dict yields nothing for that key: the page says nothing rather than raising.
    """
    if not isinstance(params, dict):
        return []
    lists: list[dict[str, Any]] = []
    for key, label in DELETE_LIST_LABELS:
        entry = params.get(key)
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        sha = entry.get("sha256")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(sha, str) or not sha.strip():
            continue
        try:
            rows = int(entry.get("rows"))
        except (TypeError, ValueError):
            continue
        lists.append(
            {
                "label": label,
                "name": name,
                "rows": rows,
                "sha256_short": sha.strip()[:8].upper(),
            }
        )
    return lists


def _inherited_anchors(db: Session, dataset: Dataset, raw_id: str | None) -> dict | None:
    """Read the anchor block of an earlier analysis of the same dataset, when it is usable.

    Anything unexpected (missing row, foreign dataset, unreadable params, no anchor map) yields
    None, so a run without an explicit anchor upload stays unanchored exactly as before.
    """
    if raw_id is None:
        return None
    try:
        earlier_id = int(str(raw_id).strip())
    except (TypeError, ValueError):
        return None
    earlier = db.scalar(
        select(Analysis).where(Analysis.id == earlier_id, Analysis.dataset_id == dataset.id)
    )
    if earlier is None or not earlier.params_json:
        return None
    try:
        params = json.loads(earlier.params_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(params, dict):
        return None
    entry = params.get("anchors")
    if isinstance(entry, dict) and isinstance(entry.get("anchors"), dict) and entry["anchors"]:
        return entry
    return None


def _anchor_band(anchors: Any) -> dict | None:
    """Shape the stored anchor block for the result page, or None when there is nothing to show.

    A legacy row without the key, a None, or a malformed entry yields None so the page stays as it
    was; the count of anchors that survived the run is clamped to the requested count.
    """
    if not isinstance(anchors, dict):
        return None
    name = anchors.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        requested = int(anchors.get("requested"))
        used = int(anchors.get("used", requested))
    except (TypeError, ValueError):
        return None
    if requested < 1:
        return None
    return {"name": name, "requested": requested, "used": min(max(used, 0), requested)}


def _marked_ids(db: Session, user_id: int) -> dict[int, int]:
    """Map each of a user's datasets to the id of the analysis marked as the version in use.

    One query for a whole page, so listing rows never becomes a query per row. Defensive the same
    way as app.analysis.marked_analysis_id: a store written before the mark kept its invariant can
    carry two marked rows for one dataset, so the newest by primary_at then id answers for it, and a
    store that cannot be read yields no marks instead of taking the page down.
    """
    try:
        rows = db.execute(
            select(Analysis.dataset_id, Analysis.id)
            .join(Dataset, Analysis.dataset_id == Dataset.id)
            .where(Dataset.user_id == user_id, Analysis.primary_at.isnot(None))
            .order_by(Analysis.primary_at.desc(), Analysis.id.desc())
        ).all()
    except Exception:
        logger.exception("Tanda versi dipakai tidak dapat dibaca.")
        return {}

    marks: dict[int, int] = {}
    for dataset_id, analysis_id in rows:
        marks.setdefault(dataset_id, analysis_id)
    return marks


def _mark_state(marks: dict[int, int], dataset_id: int, analysis_id: int) -> str:
    """How one analysis stands against the dataset's version in use, in words the pages render.

    dipakai: this analysis carries the mark. arsip: a sibling of the same dataset does. belum: the
    dataset has no marked run, and no chip is drawn at all.
    """
    marked_id = marks.get(dataset_id)
    if marked_id == analysis_id:
        return "dipakai"
    if marked_id is not None:
        return "arsip"
    return "belum"


def _picker_context(dataset: Dataset) -> dict[str, Any]:
    return {
        "person_labels": effective_person_labels(dataset),
        "picker_item_labels": effective_item_labels(dataset),
    }


def _do_retention_sweep() -> None:
    with SessionLocal() as db:
        retention_sweep(db)


async def _retention_worker() -> None:
    try:
        await asyncio.sleep(30)
        while True:
            try:
                await asyncio.to_thread(_do_retention_sweep)
            except Exception:
                logger.exception("Pembersihan retensi gagal dijalankan.")
            await asyncio.sleep(6 * 3600)
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Tugas latar pembersihan retensi mengalami kesalahan.")


@contextlib.asynccontextmanager
async def lifespan(app: Any):
    task = asyncio.create_task(_retention_worker())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


router = APIRouter(lifespan=lifespan)


@router.get("/datasets/{id}/analysis-settings", response_class=HTMLResponse)
def get_analysis_settings(
    request: Request,
    id: int,
    db: Session = Depends(get_session),
):
    if _gate_closed():
        raise HTTPException(status_code=404, detail="Halaman tidak ditemukan.")
    user = _current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    dataset = db.execute(select(Dataset).where(Dataset.id == id)).scalar_one_or_none()
    if dataset is None or dataset.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dataset tidak ditemukan.")

    if dataset.status != "ready":
        return RedirectResponse(f"/datasets/{dataset.id}", status_code=303)

    newest = db.scalars(
        select(Analysis).where(Analysis.dataset_id == dataset.id).order_by(Analysis.id.desc())
    ).first()
    params = dict(PARAMS_DEFAULT)
    if newest is not None and newest.params_json:
        with contextlib.suppress(TypeError, ValueError):
            stored = json.loads(newest.params_json)
            if isinstance(stored, dict):
                params.update({k: v for k, v in stored.items() if v is not None})

    inherit_anchors_id = None
    inherited_entry = params.get("anchors")
    if newest is not None and isinstance(inherited_entry, dict) and inherited_entry.get("anchors"):
        inherit_anchors_id = newest.id

    context = _build_dataset_context(request, user, dataset)
    context.update(_picker_context(dataset))
    context.update(
        {
            "params": params,
            "inherit_anchors_id": inherit_anchors_id,
            "misfit_input": f"{float(params['misfit']):.2f}",
            "submitted": None,
            "defaults": {
                "misfit": format_threshold(MISFIT_THRESHOLD_DEFAULT),
                "mode": MODE_CHOICES[0],
                "digits": str(PARAMS_DEFAULT["digits"]),
            },
        }
    )
    return templates.TemplateResponse(
        request=request, name="analysis_settings.html", context=context, status_code=200
    )


PICKER_PAGE_LIMIT = 5


@router.get("/datasets/{id}/picker")
def get_dataset_picker(
    request: Request,
    id: int,
    kind: str = "",
    q: str = "",
    offset: int = 0,
    db: Session = Depends(get_session),
):
    if _gate_closed():
        raise HTTPException(status_code=404, detail="Halaman tidak ditemukan.")
    user = _current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    dataset = db.execute(select(Dataset).where(Dataset.id == id)).scalar_one_or_none()
    if dataset is None or dataset.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dataset tidak ditemukan.")

    allowed, retry_after = check_limit(
        f"analyze:{client_ip(request)}:{user.id}", 12, 3600
    )
    if not allowed:
        return Response(
            content="Batas analisis tercapai (maksimal 12 per jam). Silakan coba lagi nanti.",
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    if kind not in ("persons", "items"):
        raise HTTPException(
            status_code=400,
            detail="Jenis pilihan harus persons atau items.",
        )

    if kind == "persons":
        labels = effective_person_labels(dataset)
    else:
        labels = effective_item_labels(dataset)

    query = q.strip() if q else ""
    if query:
        q_lower = query.lower()
        exact_pos = []
        other_matches = []
        for pos, label in enumerate(labels, start=1):
            pos_str = str(pos)
            is_exact = (pos_str == query)
            match = is_exact or (query in pos_str) or (q_lower in label.lower())
            if is_exact:
                exact_pos.append({"pos": pos, "label": label})
            elif match:
                other_matches.append({"pos": pos, "label": label})
        filtered = exact_pos + other_matches
    else:
        filtered = [{"pos": pos, "label": label} for pos, label in enumerate(labels, start=1)]

    total = len(filtered)
    start_offset = max(0, offset)
    limit = PICKER_PAGE_LIMIT
    items = filtered[start_offset : start_offset + limit]
    has_more = (start_offset + len(items)) < total

    return {
        "kind": kind,
        "total": total,
        "offset": start_offset,
        "limit": limit,
        "has_more": has_more,
        "items": items,
    }


@router.post("/datasets/{id}/analyze")
def post_dataset_analyze(
    id: int,
    request: Request,
    db: Session = Depends(get_session),
    misfit: str | None = Form(None),
    mode: str | None = Form(None),
    digits: str | None = Form(None),
    pdfile: UploadFile | None = File(None),
    idfile: UploadFile | None = File(None),
    anchors: UploadFile | None = File(None),
    inherit_anchors: str | None = Form(None),
    pd_pick: list[str] | None = Form(None),
    id_pick: list[str] | None = Form(None),
    anchor_pos: list[str] | None = Form(None),
    anchor_value: list[str] | None = Form(None),
):
    if _gate_closed():
        return RedirectResponse("/", status_code=303)
    user = _current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    dataset = db.execute(select(Dataset).where(Dataset.id == id)).scalar_one_or_none()
    if dataset is None or dataset.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dataset tidak ditemukan.")

    if dataset.status != "ready":
        return RedirectResponse(f"/datasets/{dataset.id}", status_code=303)

    def settings_error(message: str) -> HTMLResponse:
        context = _build_dataset_context(request, user, dataset)
        context.update(_picker_context(dataset))
        anchor_map = {
            str(p).strip(): str(v).strip()
            for p, v in zip(anchor_pos or [], anchor_value or [])
            if str(v).strip()
        }
        context.update(
            {
                "params": dict(PARAMS_DEFAULT),
                "misfit_input": f"{float(PARAMS_DEFAULT['misfit']):.2f}",
                "submitted": {
                    "misfit": misfit,
                    "mode": mode,
                    "digits": digits,
                    "pd_pick": [str(x) for x in (pd_pick or [])],
                    "id_pick": [str(x) for x in (id_pick or [])],
                    "anchor_values": anchor_map,
                },
                "error": message,
                "defaults": {
                    "misfit": format_threshold(MISFIT_THRESHOLD_DEFAULT),
                    "mode": MODE_CHOICES[0],
                    "digits": str(PARAMS_DEFAULT["digits"]),
                },
            }
        )
        return templates.TemplateResponse(
            request=request, name="analysis_settings.html", context=context, status_code=422
        )

    try:
        params = parse_settings_form({"misfit": misfit, "mode": mode, "digits": digits})
    except AnalysisError as exc:
        return settings_error(str(exc))

    delete_lists: dict[str, dict] = {}
    for key, upload in (("pdfile", pdfile), ("idfile", idfile)):
        if upload is None:
            continue
        filename = (upload.filename or "").strip()
        if not filename:
            continue
        try:
            delete_lists[key] = parse_delete_list(filename, upload.file.read())
        except AnalysisError as exc:
            return settings_error(str(exc))

    for key, picks, max_rows in (
        ("pdfile", pd_pick, dataset.n_persons),
        ("idfile", id_pick, dataset.n_items),
    ):
        if key in delete_lists or not picks:
            continue
        try:
            entry = delete_list_from_positions(picks, max_rows, PICK_DELETE_LIST_NAMES[key])
        except AnalysisError as exc:
            return settings_error(str(exc))
        if entry is not None:
            delete_lists[key] = entry

    anchors_entry = None
    if anchors is not None:
        anchor_name = (anchors.filename or "").strip()
        if anchor_name:
            try:
                anchors_entry = parse_anchors(
                    anchor_name, anchors.file.read(), effective_item_labels(dataset)
                )
            except AnalysisError as exc:
                return settings_error(str(exc))
    if anchors_entry is None and anchor_pos and anchor_value:
        try:
            anchors_entry = anchors_from_positions(
                anchor_pos, anchor_value, effective_item_labels(dataset)
            )
        except AnalysisError as exc:
            return settings_error(str(exc))
    if anchors_entry is None and inherit_anchors:
        anchors_entry = _inherited_anchors(db, dataset, inherit_anchors)
    if anchors_entry is not None:
        params["anchors"] = anchors_entry

    allowed, retry_after = check_limit(
        f"analyze:{client_ip(request)}:{user.id}", 12, 3600
    )
    if not allowed:
        return Response(
            content="Batas analisis tercapai (maksimal 12 per jam). Silakan coba lagi nanti.",
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    threshold = now_epoch() - STALE_RUN_S
    existing_running = db.scalars(
        select(Analysis)
        .where(
            Analysis.dataset_id == dataset.id,
            Analysis.status == "running",
            Analysis.created_at >= threshold,
        )
        .order_by(Analysis.id.desc())
    ).first()
    if existing_running is not None:
        return RedirectResponse(f"/analyses/{existing_running.id}?msg=analyzed", status_code=303)

    try:
        analysis = run_for_dataset(db, dataset, params, delete_lists=delete_lists)
    except AnalysisError as exc:
        context = _build_dataset_context(request, user, dataset, error=str(exc))
        context["latest_analysis"] = latest_done_analysis(db, dataset.id)
        return templates.TemplateResponse(
            request=request,
            name="dataset_detail.html",
            context=context,
            status_code=422,
        )

    return RedirectResponse(f"/analyses/{analysis.id}?msg=analyzed", status_code=303)


@router.get("/analyses", response_class=HTMLResponse)
def get_analyses(
    request: Request,
    db: Session = Depends(get_session),
):
    if _gate_closed():
        raise HTTPException(status_code=404, detail="Halaman tidak ditemukan.")
    user = _current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    # ponytail: ceiling is unpaginated list of user's finished analyses; upgrade path is cursor/page pagination when count exceeds 100.
    stmt = (
        select(Analysis, Dataset)
        .join(Dataset, Analysis.dataset_id == Dataset.id)
        .where(
            Analysis.user_id == user.id,
            Analysis.status == "done",
            Dataset.user_id == user.id,
        )
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
    )
    rows = db.execute(stmt).all()

    marks = _marked_ids(db, user.id)
    analyses = [
        {
            "id": analysis.id,
            "created_at": datetime.datetime.fromtimestamp(
                analysis.finished_at or analysis.created_at
            ).strftime("%Y-%m-%d %H:%M"),
            "dataset_id": dataset.id,
            "dataset_filename": dataset.filename,
            "filename": dataset.filename,
            "n_persons": dataset.n_persons,
            "n_items": dataset.n_items,
            "analysis": analysis,
            "dataset": dataset,
            "mark_state": _mark_state(marks, dataset.id, analysis.id),
        }
        for analysis, dataset in rows
    ]

    return templates.TemplateResponse(
        request=request,
        name="analyses.html",
        context={
            "request": request,
            "user": user,
            "analyses": analyses,
            "rows": analyses,
        },
    )


@router.get("/analyses/{id}", response_class=HTMLResponse)
def get_analysis(
    id: int,
    request: Request,
    db: Session = Depends(get_session),
):
    if _gate_closed():
        raise HTTPException(status_code=404, detail="Halaman tidak ditemukan.")
    user = _current_user(request, db)
    if user is None:
        raise HTTPException(status_code=404, detail="Halaman tidak ditemukan.")

    analysis = db.scalar(select(Analysis).where(Analysis.id == id))
    if analysis is None or analysis.user_id != user.id:
        raise HTTPException(status_code=404, detail="Analisis tidak ditemukan.")

    dataset = db.scalar(select(Dataset).where(Dataset.id == analysis.dataset_id))
    if dataset is None or dataset.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dataset tidak ditemukan.")

    now = now_epoch()
    ref_time = analysis.started_at or analysis.created_at
    if analysis.status in ("queued", "running") and (
        (now - ref_time > STALE_RUN_S) or (now - analysis.created_at > STALE_RUN_S)
    ):
        analysis.status = "failed"
        analysis.error = "Analisis terhenti saat berjalan. Jalankan ulang."
        analysis.finished_at = now
        db.commit()

    if analysis.status == "done":
        target = f"/analyses/{analysis.id}/explore"
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return RedirectResponse(target, status_code=303)

    params = json.loads(analysis.params_json) if analysis.params_json else {}
    misfit_threshold = float(params.get("misfit", MISFIT_THRESHOLD_DEFAULT))
    anchors = params.get("anchors")
    anchor_band = _anchor_band(anchors)
    marks = _marked_ids(db, user.id)
    context: dict[str, Any] = {
        "user": user,
        "dataset": dataset,
        "analysis": analysis,
        "status": analysis.status,
        "error": analysis.error,
        "engine_ref": analysis.engine_ref,
        "elapsed_ms": analysis.elapsed_ms,
        "retention_days": RETENTION_DAYS,
        "n_misfit": 0,
        "n_item": 0,
        "params": params,
        "delete_lists": _delete_lists_from_params(params),
        "misfit_threshold": format_threshold(misfit_threshold),
        "anchors": anchors,
        "anchor_band": anchor_band,
        "is_anchored": bool(anchors)
        and not (anchor_band is not None and anchor_band["used"] == 0),
        "mark_state": _mark_state(marks, dataset.id, analysis.id),
        "can_mark": analysis.user_id == user.id,
    }
    return templates.TemplateResponse(
        request=request,
        name="analysis.html",
        context=context,
        status_code=200,
    )


@router.post("/analyses/{id}/mark")
def post_analysis_mark(
    id: int,
    request: Request,
    db: Session = Depends(get_session),
    primary: str | None = Form(None),
):
    if _gate_closed():
        return RedirectResponse("/", status_code=303)
    user = _current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    analysis = db.scalar(select(Analysis).where(Analysis.id == id))
    if analysis is None or analysis.user_id != user.id:
        raise HTTPException(status_code=404, detail="Analisis tidak ditemukan.")

    mark_analysis(db, analysis, (primary or "").strip() == "1")
    return RedirectResponse(f"/analyses/{analysis.id}", status_code=303)
