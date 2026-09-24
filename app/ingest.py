"""Dataset ingestion, preview, and commitment routes.

Template context contract:

datasets.html:
  - request: Request
  - user: User (current authenticated user)
  - datasets: list[Dataset] (user datasets, newest first)
  - error: str | None (Indonesian error message if upload or validation failed)

dataset_detail.html:
  - request: Request
  - user: User (current authenticated user)
  - dataset: Dataset (dataset database record)
  - status: str ('staged' or 'ready')
  - summary: dict (parsed summary JSON: shape, tokens, missing counts)
  - mapping: dict (token to canonical class mapping, or PRN key/codes)
  - item_labels: list[str] (item column labels)
  - distinct_tokens: list[tuple[str, int]] (token strings and counts)
  - unassigned_tokens: list[str] (tokens lacking mapping assignment)
  - missing_per_item: list[int] (missing counts per item column)
  - total_missing: int (sum of missing counts across all items)
  - preview_rows: list[list[str]] (first 10 rows, first 12 columns)
  - preview_person_labels: list[str] (first 10 respondent identifiers)
  - preview_item_labels: list[str] (first 12 item labels)
  - has_more_rows: bool (True when n_persons > 10)
  - more_rows_count: int (n_persons - 10 when positive)
  - has_more_cols: bool (True when n_items > 12)
  - more_cols_count: int (n_items - 12 when positive)
  - all_missing_items: list[str] (items with 100% missing values)
  - key: str (PRN answer key string)
  - codes: str (PRN valid response code set)
  - extra_missing: str (PRN additional missing characters)
  - error: str | None (Indonesian error message if commit blocked)
"""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import _current_user, _gate_closed, templates
from app.db import get_session
from app.models import Dataset, User
from app.parsers import (
    count_all_missing_persons,
    default_mapping,
    distinct_tokens,
    missing_per_item,
    parse_control,
    parse_delimited,
    parse_prn,
    parse_xlsx,
    validate_mapping,
)
from app.ratelimit import check_limit, client_ip
from app.security import now_epoch
from app.storage import (
    MAX_UPLOAD_BYTES,
    StorageError,
    compress,
    decompress,
)

router = APIRouter()

CHUNK_SIZE: int = 1024 * 1024  # 1 MiB


async def _read_upload_bounded(
    upload: UploadFile,
    max_bytes: int = MAX_UPLOAD_BYTES,
    error_message: str | None = None,
) -> bytes:
    buf = bytearray()
    while True:
        chunk = await upload.read(CHUNK_SIZE)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > max_bytes:
            msg = (
                error_message
                if error_message is not None
                else f"Ukuran berkas melebihi batas maksimal ({max_bytes} bytes)."
            )
            raise StorageError(msg)
    return bytes(buf)


def _format_error(exc: Exception) -> str:
    msg = str(exc)
    if "MAX_UPLOAD_BYTES" in msg or "melebihi batas" in msg:
        return "Ukuran berkas melebihi batas maksimal 16 MB."
    if "MAX_CELLS" in msg:
        return "Jumlah sel berkas melebihi batas maksimal 1.000.000 sel."
    if isinstance(exc, (ValueError, StorageError)):
        return f"Berkas tidak valid: {msg}"
    return "Terjadi kesalahan saat memproses berkas. Pastikan format berkas sesuai."


def _user_datasets(db: Session, user_id: int) -> list[Dataset]:
    stmt = (
        select(Dataset)
        .where(Dataset.user_id == user_id)
        .order_by(Dataset.created_at.desc(), Dataset.id.desc())
    )
    return list(db.execute(stmt).scalars().all())


def _build_dataset_context(
    request: Request,
    user: User,
    dataset: Dataset,
    error: str | None = None,
    unassigned_tokens: list[str] | None = None,
) -> dict[str, Any]:
    summary = json.loads(dataset.summary_json) if dataset.summary_json else {}
    mapping = json.loads(dataset.mapping_json) if dataset.mapping_json else {}
    item_labels = json.loads(dataset.item_labels_json) if dataset.item_labels_json else []

    distinct_dict = summary.get("distinct_tokens", {})
    if unassigned_tokens is None:
        if dataset.kind == "delimited":
            unassigned_tokens = validate_mapping(distinct_dict.keys(), mapping)
        else:
            unassigned_tokens = []

    missing_counts = summary.get("missing_per_item", [])
    total_missing = summary.get("total_missing", sum(missing_counts))
    all_missing_items = [
        item_labels[i]
        for i, m in enumerate(missing_counts)
        if m == dataset.n_persons and i < len(item_labels)
    ]

    key = mapping.get("key", "") or summary.get("control", {}).get("KEY1", "")
    codes = mapping.get("codes", "") or summary.get("control", {}).get("CODES", "ABCDE")
    extra_missing = mapping.get("extra_missing", "")

    return {
        "user": user,
        "dataset": dataset,
        "status": dataset.status,
        "summary": summary,
        "mapping": mapping,
        "item_labels": item_labels,
        "distinct_tokens": list(distinct_dict.items()),
        "unassigned_tokens": unassigned_tokens,
        "missing_per_item": missing_counts,
        "total_missing": total_missing,
        "all_missing_items": all_missing_items,
        "preview_rows": summary.get("preview_rows", []),
        "preview_person_labels": summary.get("preview_person_labels", []),
        "preview_item_labels": item_labels[:12],
        "has_more_rows": dataset.n_persons > 10,
        "more_rows_count": max(0, dataset.n_persons - 10),
        "has_more_cols": dataset.n_items > 12,
        "more_cols_count": max(0, dataset.n_items - 12),
        "key": key,
        "codes": codes,
        "extra_missing": extra_missing,
        "error": error,
    }


@router.get("/datasets", response_class=HTMLResponse)
def get_datasets(request: Request, db: Session = Depends(get_session)):
    if _gate_closed():
        return RedirectResponse("/", 303)
    user = _current_user(request, db)
    if user is None:
        return RedirectResponse("/login", 303)

    return templates.TemplateResponse(
        request=request,
        name="datasets.html",
        context={"user": user, "datasets": _user_datasets(db, user.id), "error": None},
        status_code=200,
    )


@router.post("/datasets")
async def post_datasets(
    request: Request,
    data: UploadFile = File(...),
    con: UploadFile | None = File(None),
    db: Session = Depends(get_session),
):
    if _gate_closed():
        return RedirectResponse("/", 303)
    user = _current_user(request, db)
    if user is None:
        return RedirectResponse("/login", 303)

    allowed, retry_after = check_limit(
        "upload:" + client_ip(request) + ":" + str(user.id), 20, 3600
    )
    if not allowed:
        return templates.TemplateResponse(
            request=request,
            name="datasets.html",
            context={
                "user": user,
                "datasets": _user_datasets(db, user.id),
                "error": "Batas unggah tercapai (maksimal 20 berkas per jam). Silakan coba lagi nanti.",
            },
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    try:
        filename = (data.filename or "").strip()
        if not filename:
            raise ValueError("Nama berkas tidak boleh kosong.")

        suffix = Path(filename).suffix.lower()
        if suffix not in (".csv", ".xlsx", ".prn"):
            raise ValueError("Format berkas tidak didukung. Gunakan CSV, XLSX, atau PRN.")

        data_bytes = await _read_upload_bounded(
            data,
            max_bytes=MAX_UPLOAD_BYTES,
            error_message=f"Ukuran berkas melebihi batas maksimal ({MAX_UPLOAD_BYTES} bytes).",
        )
        if not data_bytes:
            raise ValueError("Berkas yang diunggah kosong.")

        if suffix in (".csv", ".xlsx"):
            kind = "delimited"
            fmt = suffix.lstrip(".")
            parsed = parse_delimited(data_bytes) if suffix == ".csv" else parse_xlsx(data_bytes)
            n_persons = len(parsed.person_labels)
            n_items = len(parsed.item_labels)
            if n_persons == 0 or n_items == 0:
                raise ValueError("Tabel data tidak memuat baris data atau kolom butir yang valid.")
            item_labels = parsed.item_labels
            tokens_dict = distinct_tokens(parsed)
            mapping = default_mapping(tokens_dict.keys())
            missing_counts = missing_per_item(parsed, mapping=mapping)
            all_missing_persons = count_all_missing_persons(parsed, mapping=mapping)
            preview_rows = [row[:12] for row in parsed.rows[:10]]
            preview_persons = parsed.person_labels[:10]
            summary_control = None
        else:
            kind = "winsteps"
            fmt = "prn"
            if con is None or not (con.filename or "").strip():
                raise ValueError("Berkas kontrol Winsteps (.CON) wajib disertakan untuk format PRN.")
            con_bytes = await _read_upload_bounded(
                con,
                max_bytes=MAX_UPLOAD_BYTES,
                error_message="Ukuran berkas kontrol melebihi batas maksimal.",
            )
            if not con_bytes:
                raise ValueError("Berkas kontrol Winsteps (.CON) kosong.")
            control = parse_control(con_bytes)
            parsed = parse_prn(data_bytes, control)
            n_persons = len(parsed.person_labels)
            n_items = int(control.get("NI") or (len(parsed.rows[0]) if parsed.rows else 0))
            if n_persons == 0 or n_items == 0:
                raise ValueError("Berkas PRN tidak memuat data baris responden yang valid.")
            item_labels = [f"I{i+1:02d}" for i in range(n_items)]
            tokens_dict = distinct_tokens(parsed)
            mapping = {
                "key": str(control.get("KEY1", "")),
                "codes": str(control.get("CODES", "ABCDE")),
            }
            missing_counts = missing_per_item(parsed, codes=control.get("CODES"))
            all_missing_persons = count_all_missing_persons(parsed, codes=control.get("CODES"))
            preview_rows = [list(row[:12]) for row in parsed.rows[:10]]
            preview_persons = parsed.person_labels[:10]
            summary_control = control

        summary = {
            "n_persons": n_persons,
            "n_items": n_items,
            "item_labels": item_labels,
            "distinct_tokens": tokens_dict,
            "missing_per_item": missing_counts,
            "total_missing": sum(missing_counts),
            "all_missing_persons_count": all_missing_persons,
            "preview_rows": preview_rows,
            "preview_person_labels": preview_persons,
        }
        if summary_control is not None:
            summary["control"] = summary_control

        dataset = Dataset(
            user_id=user.id,
            filename=filename,
            kind=kind,
            format=fmt,
            status="staged",
            n_persons=n_persons,
            n_items=n_items,
            item_labels_json=json.dumps(item_labels),
            mapping_json=json.dumps(mapping),
            summary_json=json.dumps(summary),
            raw_gzip=compress(data_bytes),
            raw_bytes=len(data_bytes),
            created_at=now_epoch(),
            committed_at=None,
        )
        db.add(dataset)
        db.commit()
        return RedirectResponse(f"/datasets/{dataset.id}", status_code=303)

    except Exception as exc:
        db.rollback()
        return templates.TemplateResponse(
            request=request,
            name="datasets.html",
            context={
                "user": user,
                "datasets": _user_datasets(db, user.id),
                "error": _format_error(exc),
            },
            status_code=200,
        )


@router.get("/datasets/{id}", response_class=HTMLResponse)
def get_dataset(id: int, request: Request, db: Session = Depends(get_session)):
    if _gate_closed():
        return RedirectResponse("/", 303)
    user = _current_user(request, db)
    if user is None:
        return RedirectResponse("/login", 303)

    dataset = db.execute(select(Dataset).where(Dataset.id == id)).scalar_one_or_none()
    if dataset is None or dataset.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dataset tidak ditemukan.")

    return templates.TemplateResponse(
        request=request,
        name="dataset_detail.html",
        context=_build_dataset_context(request, user, dataset),
        status_code=200,
    )


@router.post("/datasets/{id}/commit")
async def post_dataset_commit(id: int, request: Request, db: Session = Depends(get_session)):
    if _gate_closed():
        return RedirectResponse("/", 303)
    user = _current_user(request, db)
    if user is None:
        return RedirectResponse("/login", 303)

    dataset = db.execute(select(Dataset).where(Dataset.id == id)).scalar_one_or_none()
    if dataset is None or dataset.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dataset tidak ditemukan.")

    if dataset.status == "ready":
        return RedirectResponse(f"/datasets/{dataset.id}", status_code=303)

    form = await request.form()
    summary = json.loads(dataset.summary_json) if dataset.summary_json else {}

    if dataset.kind == "delimited":
        submitted_mapping: dict[str, str] = {}
        i = 0
        while f"t{i}" in form:
            t_val = str(form.get(f"t{i}"))
            m_val = str(form.get(f"m{i}", "")).strip()
            if m_val:
                submitted_mapping[t_val] = m_val
            i += 1

        distinct_dict = summary.get("distinct_tokens", {})
        if not submitted_mapping:
            for token in distinct_dict.keys():
                if token in form:
                    val = str(form.get(token, "")).strip()
                    if val:
                        submitted_mapping[token] = val
                elif f"mapping[{token}]" in form:
                    val = str(form.get(f"mapping[{token}]", "")).strip()
                    if val:
                        submitted_mapping[token] = val

        unassigned = validate_mapping(distinct_dict.keys(), submitted_mapping)
        if unassigned:
            error_msg = f"Ada token yang belum dipetakan: {', '.join(unassigned)}."
            context = _build_dataset_context(
                request, user, dataset, error=error_msg, unassigned_tokens=unassigned
            )
            context["mapping"] = submitted_mapping
            return templates.TemplateResponse(
                request=request,
                name="dataset_detail.html",
                context=context,
                status_code=422,
            )

        raw_bytes = decompress(dataset.raw_gzip)
        parsed = parse_xlsx(raw_bytes) if dataset.format == "xlsx" else parse_delimited(raw_bytes)
        missing_counts = missing_per_item(parsed, mapping=submitted_mapping)
        summary["missing_per_item"] = missing_counts
        summary["total_missing"] = sum(missing_counts)
        summary["all_missing_persons_count"] = count_all_missing_persons(
            parsed, mapping=submitted_mapping
        )

        dataset.mapping_json = json.dumps(submitted_mapping)
        dataset.summary_json = json.dumps(summary)
        dataset.status = "ready"
        dataset.committed_at = now_epoch()
        db.commit()
        return RedirectResponse(f"/datasets/{dataset.id}", status_code=303)

    else:
        control = dict(summary.get("control", {}))
        key = str(form.get("key", "")).strip() or str(control.get("KEY1", ""))
        codes = str(form.get("codes", "")).strip() or str(control.get("CODES", "ABCDE"))
        extra_missing = str(form.get("extra_missing", "")).strip()

        if len(key) != dataset.n_items:
            error_msg = (
                f"Panjang kunci jawaban ({len(key)}) tidak sama dengan jumlah butir ({dataset.n_items})."
            )
            context = _build_dataset_context(request, user, dataset, error=error_msg)
            context["key"] = key
            context["codes"] = codes
            context["extra_missing"] = extra_missing
            return templates.TemplateResponse(
                request=request,
                name="dataset_detail.html",
                context=context,
                status_code=422,
            )

        control["KEY1"] = key
        control["CODES"] = codes
        raw_bytes = decompress(dataset.raw_gzip)
        parsed = parse_prn(raw_bytes, control)

        missing_counts = missing_per_item(parsed, codes=codes, extra_missing=extra_missing)
        summary["missing_per_item"] = missing_counts
        summary["total_missing"] = sum(missing_counts)
        summary["all_missing_persons_count"] = count_all_missing_persons(
            parsed, codes=codes, extra_missing=extra_missing
        )
        summary["control"] = control

        final_mapping = {"key": key, "codes": codes}
        if extra_missing:
            final_mapping["extra_missing"] = extra_missing

        dataset.mapping_json = json.dumps(final_mapping)
        dataset.summary_json = json.dumps(summary)
        dataset.status = "ready"
        dataset.committed_at = now_epoch()
        db.commit()
        return RedirectResponse(f"/datasets/{dataset.id}", status_code=303)


@router.post("/datasets/{id}/discard")
def post_dataset_discard(id: int, request: Request, db: Session = Depends(get_session)):
    if _gate_closed():
        return RedirectResponse("/", 303)
    user = _current_user(request, db)
    if user is None:
        return RedirectResponse("/login", 303)

    dataset = db.execute(select(Dataset).where(Dataset.id == id)).scalar_one_or_none()
    if dataset is None or dataset.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dataset tidak ditemukan.")

    db.delete(dataset)
    db.commit()
    return RedirectResponse("/datasets", status_code=303)
