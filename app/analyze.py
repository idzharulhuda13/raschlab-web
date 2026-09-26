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

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import (
    RETENTION_DAYS,
    STALE_RUN_S,
    AnalysisError,
    id_num,
    latest_done_analysis,
    load_tables,
    paginate,
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

MISFIT_THRESHOLD = 1.50  # INFIT MNSQ at or above this value flags an item (same rule the explorer uses)

templates.env.filters["id_num"] = id_num


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


@router.post("/datasets/{id}/analyze")
def post_dataset_analyze(
    id: int,
    request: Request,
    db: Session = Depends(get_session),
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
        analysis = run_for_dataset(db, dataset)
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

    params = json.loads(analysis.params_json) if analysis.params_json else {}
    anchors = params.get("anchors")
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
        "anchors": anchors,
        "is_anchored": bool(anchors),
    }

    if analysis.status == "done":
        tables = load_tables(analysis)
        item_rows = tables.get("item_table_15.1.csv", [])
        option_rows = tables.get("option_table_15.3.csv", [])
        person_rows = tables.get("person_table.csv", [])
        summary_rows = tables.get("summary_table.csv", [])

        n_misfit = 0
        n_item = 0
        if len(item_rows) >= 3:
            long_headers = [str(h).strip().upper() for h in item_rows[0]]
            try:
                infit_idx = long_headers.index("INFIT MNSQ")
            except ValueError:
                infit_idx = -1

            if infit_idx != -1:
                item_data_rows = item_rows[2:]
                n_item = len(item_data_rows)
                for r in item_data_rows:
                    if infit_idx < len(r):
                        try:
                            if float(r[infit_idx]) >= MISFIT_THRESHOLD:
                                n_misfit += 1
                        except (ValueError, TypeError):
                            pass

        item_headers = item_rows[:2] if len(item_rows) >= 2 else []
        item_data = item_rows[2:] if len(item_rows) >= 2 else []
        page_item = request.query_params.get("page_item", 1)
        item_paged = paginate(item_data, page_item)

        option_headers = option_rows[:2] if len(option_rows) >= 2 else []
        option_data = option_rows[2:] if len(option_rows) >= 2 else []
        page_option = request.query_params.get("page_option", 1)
        option_paged = paginate(option_data, page_option)

        person_headers = person_rows[:2] if len(person_rows) >= 2 else []
        person_data = person_rows[2:] if len(person_rows) >= 2 else []
        page_person = request.query_params.get("page_person", 1)
        person_paged = paginate(person_data, page_person)

        summary_headers = summary_rows[:1] if summary_rows else []

        rekap: dict[str, str] = {}
        for row in summary_rows:
            if len(row) >= 3:
                k = f"{row[0]} {row[1]}".strip()
                rekap[k] = row[2]

        context.update(
            {
                "n_misfit": n_misfit,
                "n_item": n_item,
                "tables": tables,
                "item_headers": item_headers,
                "item_paged": item_paged,
                "item_rows": item_paged,
                "option_headers": option_headers,
                "option_paged": option_paged,
                "option_rows": option_paged,
                "person_headers": person_headers,
                "person_paged": person_paged,
                "person_rows": person_paged,
                "summary_headers": summary_headers,
                "summary_rows": summary_rows,
                "rekap": rekap,
                "page_item": item_paged.page,
                "page_option": option_paged.page,
                "page_person": person_paged.page,
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="analysis.html",
        context=context,
        status_code=200,
    )
