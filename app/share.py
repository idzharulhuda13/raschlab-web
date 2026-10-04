"""Read-only share links: one analysis, one password, seven days."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import COOKIE_NAME, _current_user, _gate_closed, templates
from app.config import settings
from app.db import get_session
from app.explore import PAGE_NOT_FOUND_MSG, render_explore
from app.models import Analysis, AnalysisShare, Dataset
from app.ratelimit import check_limit, client_ip
from app.security import (
    hash_password,
    hash_token,
    new_token,
    now_epoch,
    password_policy,
    verify_password,
)

SHARE_COOKIE = "raschlab_share"
SHARE_TTL_S = 604800
WRONG_PW_MSG = "Password salah. Coba lagi."
TOO_MANY_MSG = "Terlalu banyak percobaan. Coba lagi nanti."
SHARE_PW_POLICY_MSG = "Password tautan minimal 10 karakter."
SHARE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex",
}
EXEMPT_PREFIXES = ("/s/", "/static/", "/health")

router = APIRouter()


def _harden(response):
    for key, value in SHARE_HEADERS.items():
        response.headers[key] = value
    return response


def share_cookie_value(row: AnalysisShare) -> str:
    return hash_token(f"{row.token_hash}:{row.password_hash}")


def share_guard(request: Request) -> None:
    """A share session must never reach an owner route."""
    if request.cookies.get(SHARE_COOKIE) is None:
        return
    if request.cookies.get(COOKIE_NAME) is not None:
        return
    path = request.url.path
    if any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES):
        return
    raise HTTPException(status_code=404, detail=PAGE_NOT_FOUND_MSG)


def resolve_share(db: Session, raw_token: str):
    """Return (share, analysis, dataset) for a live link, or None."""
    row = db.scalar(select(AnalysisShare).where(AnalysisShare.token_hash == hash_token(raw_token)))
    if row is None or row.revoked_at is not None or row.expires_at <= now_epoch():
        return None
    analysis = db.scalar(select(Analysis).where(Analysis.id == row.analysis_id))
    if analysis is None or analysis.status != "done" or analysis.user_id != row.user_id:
        return None
    dataset = db.scalar(
        select(Dataset).where(Dataset.id == analysis.dataset_id, Dataset.user_id == row.user_id)
    )
    if dataset is None:
        return None
    return row, analysis, dataset


def _gate_page(request: Request, error: str | None, status_code: int = 200):
    return templates.TemplateResponse(
        request=request,
        name="share_password.html",
        context={"share_mode": True, "error": error},
        status_code=status_code,
    )


@router.get("/s/{token}", response_class=HTMLResponse)
def get_share(token: str, request: Request, db: Session = Depends(get_session)):
    resolved = resolve_share(db, token)
    if resolved is None:
        return _harden(JSONResponse(status_code=404, content={"detail": PAGE_NOT_FOUND_MSG}))
    row, analysis, dataset = resolved
    if request.cookies.get(SHARE_COOKIE) != share_cookie_value(row):
        return _harden(_gate_page(request, None))
    try:
        rendered = render_explore(request, db, analysis, dataset, user=None, share={"token": token})
    except HTTPException as exc:
        return _harden(JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}))
    return _harden(rendered)


@router.post("/s/{token}")
def post_share(
    token: str,
    request: Request,
    password: str = Form(""),
    db: Session = Depends(get_session),
):
    resolved = resolve_share(db, token)
    if resolved is None:
        return _harden(JSONResponse(status_code=404, content={"detail": PAGE_NOT_FOUND_MSG}))
    row, analysis, dataset = resolved
    allowed, retry_after = check_limit(f"share:{client_ip(request)}:{row.id}", 10, 900)
    if not allowed:
        response = _gate_page(request, TOO_MANY_MSG, status_code=429)
        response.headers["Retry-After"] = str(retry_after)
        return _harden(response)
    if not verify_password(row.password_hash, password):
        return _harden(_gate_page(request, WRONG_PW_MSG))
    response = RedirectResponse(f"/s/{token}", status_code=303)
    response.set_cookie(
        SHARE_COOKIE,
        share_cookie_value(row),
        max_age=max(row.expires_at - now_epoch(), 0),
        path=f"/s/{token}",
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return _harden(response)


def _owner_analysis(request: Request, db: Session, analysis_id: int):
    if _gate_closed():
        raise HTTPException(status_code=404, detail=PAGE_NOT_FOUND_MSG)
    user = _current_user(request, db)
    if user is None:
        raise HTTPException(status_code=404, detail=PAGE_NOT_FOUND_MSG)
    analysis = db.scalar(select(Analysis).where(Analysis.id == analysis_id))
    if analysis is None or analysis.user_id != user.id or analysis.status != "done":
        raise HTTPException(status_code=404, detail=PAGE_NOT_FOUND_MSG)
    dataset = db.scalar(
        select(Dataset).where(Dataset.id == analysis.dataset_id, Dataset.user_id == user.id)
    )
    if dataset is None:
        raise HTTPException(status_code=404, detail=PAGE_NOT_FOUND_MSG)
    return user, analysis, dataset


@router.post("/analyses/{id}/share")
def create_share(
    id: int,
    request: Request,
    password: str = Form(""),
    db: Session = Depends(get_session),
):
    user, analysis, dataset = _owner_analysis(request, db, id)
    allowed, _retry_after = check_limit(f"share-create:{user.id}", 20, 3600)
    if not allowed:
        raise HTTPException(status_code=429, detail=TOO_MANY_MSG)
    if not password_policy(password):
        return _harden(
            render_explore(
                request, db, analysis, dataset, user=user, extra={"share_error": SHARE_PW_POLICY_MSG}
            )
        )
    now = now_epoch()
    for old in db.scalars(
        select(AnalysisShare).where(
            AnalysisShare.analysis_id == analysis.id, AnalysisShare.revoked_at.is_(None)
        )
    ):
        old.revoked_at = now
    raw = new_token()
    db.add(
        AnalysisShare(
            analysis_id=analysis.id,
            user_id=user.id,
            token_hash=hash_token(raw),
            password_hash=hash_password(password),
            created_at=now,
            expires_at=now + SHARE_TTL_S,
            revoked_at=None,
        )
    )
    db.commit()
    return _harden(
        render_explore(
            request,
            db,
            analysis,
            dataset,
            user=user,
            extra={"share_new_url": f"{settings.app_base_url}/s/{raw}"},
        )
    )


@router.post("/analyses/{id}/share/revoke")
def revoke_share(id: int, request: Request, db: Session = Depends(get_session)):
    user, analysis, _dataset = _owner_analysis(request, db, id)
    now = now_epoch()
    for old in db.scalars(
        select(AnalysisShare).where(
            AnalysisShare.analysis_id == analysis.id, AnalysisShare.revoked_at.is_(None)
        )
    ):
        old.revoked_at = now
    db.commit()
    return RedirectResponse(f"/analyses/{analysis.id}/explore", status_code=303)
