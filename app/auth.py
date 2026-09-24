import datetime
import logging
from pathlib import Path
import secrets

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, get_session
from app.emailer import EmailSendError, send_email
from app.models import Analysis, Dataset, EmailToken, SessionRow, User
from app.storage import MAX_CELLS, MAX_UPLOAD_BYTES
from app.ratelimit import check_limit, client_ip
from app.ui import initials_for
from app.security import (
    hash_password,
    hash_token,
    new_token,
    now_epoch,
    password_policy,
    verify_password,
)

router = APIRouter()
logger = logging.getLogger("app.auth")
_DUMMY_HASH = hash_password("penyamar-waktu-1")

COOKIE_NAME = "raschlab_sid"
SESSION_TTL_S = 2592000
VERIFY_TTL_S = 86400
RESET_TTL_S = 3600

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
templates.env.globals["initials_for"] = initials_for


def _gate_closed() -> bool:
    return not settings.gate_open


def _norm(email: str) -> str:
    return email.strip().lower()


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_S,
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def _current_user(request: Request, db: Session) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    token_h = hash_token(token)
    session_row = db.execute(
        select(SessionRow).where(SessionRow.token_hash == token_h)
    ).scalar_one_or_none()
    if session_row is None or session_row.expires_at <= now_epoch():
        return None
    return db.execute(select(User).where(User.id == session_row.user_id)).scalar_one_or_none()


def _issue_verify(db: Session, user: User) -> str:
    now = now_epoch()
    db.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user.id,
            EmailToken.purpose == "verify",
            EmailToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    raw = new_token()
    token_obj = EmailToken(
        user_id=user.id,
        purpose="verify",
        token_hash=hash_token(raw),
        created_at=now,
        expires_at=now + VERIFY_TTL_S,
        used_at=None,
    )
    db.add(token_obj)
    return raw


def _send_verify(user: User, raw: str) -> None:
    link = f"{settings.app_base_url}/verify?token={raw}"
    subject = "Verifikasi email kamu di RaschLab"
    try:
        html = templates.TemplateResponse(
            request=None,
            name="email/verify.html",
            context={"link": link, "subject": subject},
        ).body.decode("utf-8")
    except Exception:
        html = templates.get_template("email/verify.html").render(link=link, subject=subject)
    text = f"Verifikasi email kamu di RaschLab: {link}\n\nTautan berlaku 24 jam."
    domain = user.email.split("@")[-1] if "@" in user.email else ""
    try:
        send_email(user.email, subject, html, text)
    except EmailSendError:
        logger.warning("email_send_failed purpose=verify to_domain=%s", domain)
        raise


def _issue_reset(db: Session, user: User) -> str:
    now = now_epoch()
    db.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user.id,
            EmailToken.purpose == "reset",
            EmailToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    raw = new_token()
    token_obj = EmailToken(
        user_id=user.id,
        purpose="reset",
        token_hash=hash_token(raw),
        created_at=now,
        expires_at=now + RESET_TTL_S,
        used_at=None,
    )
    db.add(token_obj)
    return raw


def _send_reset(user: User, raw: str) -> None:
    link = f"{settings.app_base_url}/reset?token={raw}"
    subject = "Reset password RaschLab"
    try:
        html = templates.TemplateResponse(
            request=None,
            name="email/reset.html",
            context={"link": link, "subject": subject},
        ).body.decode("utf-8")
    except Exception:
        html = templates.get_template("email/reset.html").render(link=link, subject=subject)
    text = f"Reset password RaschLab: {link}\n\nTautan berlaku 1 jam."
    domain = user.email.split("@")[-1] if "@" in user.email else ""
    try:
        send_email(user.email, subject, html, text)
    except EmailSendError:
        logger.warning("email_send_failed purpose=reset to_domain=%s", domain)
        raise


@router.get("/register", response_class=HTMLResponse)
def get_register(request: Request, db: Session = Depends(get_session)):
    if _gate_closed():
        return RedirectResponse("/", 303)
    if _current_user(request, db):
        return RedirectResponse("/datasets", 303)
    return templates.TemplateResponse(request=request, name="register.html", context={})


@router.post("/register")
def post_register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_session),
):
    if _gate_closed():
        return RedirectResponse("/", 303)
    allowed, retry_after = check_limit("register:" + client_ip(request), 5, 3600)
    if not allowed:
        return HTMLResponse(
            "Terlalu banyak percobaan. Coba lagi nanti.",
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
    local_part, _, domain_part = email.partition("@")
    if not local_part.strip() or not domain_part or "." not in domain_part:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "Email tidak valid."},
            status_code=200,
        )
    if not password_policy(password):
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "Password minimal 10 karakter."},
            status_code=200,
        )
    norm_email = _norm(email)
    user = db.execute(select(User).where(User.email_normalized == norm_email)).scalar_one_or_none()
    if user is not None:
        if user.verified_at is not None:
            return templates.TemplateResponse(
                request=request,
                name="register.html",
                context={"error": "Email sudah terdaftar. Silakan masuk atau reset password."},
                status_code=200,
            )
        raw = _issue_verify(db, user)
        db.commit()
        try:
            _send_verify(user, raw)
            return RedirectResponse("/register?msg=sent", 303)
        except EmailSendError:
            return RedirectResponse("/register?msg=send_failed", 303)
    new_user = User(
        email=email,
        email_normalized=norm_email,
        password_hash=hash_password(password),
        created_at=now_epoch(),
        verified_at=None,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    raw = _issue_verify(db, new_user)
    db.commit()
    try:
        _send_verify(new_user, raw)
        return RedirectResponse("/register?msg=sent", 303)
    except EmailSendError:
        return RedirectResponse("/register?msg=send_failed", 303)


@router.get("/verify")
def get_verify(token: str = "", db: Session = Depends(get_session)):
    if not token:
        return RedirectResponse("/login?msg=verify_failed", 303)
    token_h = hash_token(token)
    token_row = db.execute(
        select(EmailToken).where(EmailToken.token_hash == token_h)
    ).scalar_one_or_none()
    now = now_epoch()
    if (
        token_row is None
        or token_row.purpose != "verify"
        or token_row.used_at is not None
        or token_row.expires_at <= now
    ):
        return RedirectResponse("/login?msg=verify_failed", 303)
    res = db.execute(
        update(EmailToken)
        .where(EmailToken.id == token_row.id, EmailToken.used_at.is_(None))
        .values(used_at=now)
    )
    if res.rowcount != 1:
        db.rollback()
        return RedirectResponse("/login?msg=verify_failed", 303)
    user = db.execute(select(User).where(User.id == token_row.user_id)).scalar_one_or_none()
    if user is None:
        db.rollback()
        return RedirectResponse("/login?msg=verify_failed", 303)
    if user.verified_at is None:
        user.verified_at = now
    db.commit()
    return RedirectResponse("/login?msg=verified", 303)


@router.get("/login", response_class=HTMLResponse)
def get_login(request: Request, db: Session = Depends(get_session)):
    if _gate_closed():
        return RedirectResponse("/", 303)
    if _current_user(request, db):
        return RedirectResponse("/datasets", 303)
    msg = request.query_params.get("msg", "")
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"msg": msg, "show_resend": False, "resend_email": ""},
        status_code=200,
    )


@router.post("/login")
def post_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_session),
):
    if _gate_closed():
        return RedirectResponse("/", 303)
    ip = client_ip(request)
    allowed, retry_after = check_limit("login:" + ip, 30, 3600)
    if not allowed:
        return HTMLResponse(
            "Terlalu banyak percobaan. Coba lagi nanti.",
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
    norm_email = _norm(email)
    allowed, retry_after = check_limit("login:" + ip + ":" + norm_email, 5, 60)
    if not allowed:
        return HTMLResponse(
            "Terlalu banyak percobaan. Coba lagi nanti.",
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
    user = db.execute(select(User).where(User.email_normalized == norm_email)).scalar_one_or_none()
    if user is not None:
        valid_password = verify_password(user.password_hash, password)
    else:
        verify_password(_DUMMY_HASH, password)
        valid_password = False
    if not valid_password:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Email atau password salah.",
                "show_resend": False,
                "resend_email": "",
            },
            status_code=200,
        )
    if user.verified_at is None:
        msg = "Email belum diverifikasi. Cek kotak masuk kamu, atau kirim ulang email verifikasi."
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": msg,
                "message": msg,
                "show_resend": True,
                "resend_email": norm_email,
            },
            status_code=200,
        )
    raw = new_token()
    now = now_epoch()
    session_row = SessionRow(
        user_id=user.id,
        token_hash=hash_token(raw),
        created_at=now,
        expires_at=now + SESSION_TTL_S,
    )
    db.add(session_row)
    db.commit()
    response = RedirectResponse("/datasets", 303)
    _set_cookie(response, raw)
    return response


@router.post("/logout")
def post_logout(request: Request, db: Session = Depends(get_session)):
    if _gate_closed():
        return RedirectResponse("/", 303)
    token = request.cookies.get(COOKIE_NAME)
    if token:
        token_h = hash_token(token)
        db.execute(delete(SessionRow).where(SessionRow.token_hash == token_h))
        db.commit()
    response = RedirectResponse("/", 303)
    _clear_cookie(response)
    return response


@router.get("/account", response_class=HTMLResponse)
def get_account(request: Request, db: Session = Depends(get_session)):
    if _gate_closed():
        return RedirectResponse("/", 303)
    user = _current_user(request, db)
    if user is None:
        return RedirectResponse("/login", 303)
    created_at_str = datetime.datetime.fromtimestamp(user.created_at).strftime("%Y-%m-%d")
    file_count = db.execute(
        select(func.count()).select_from(Dataset).where(Dataset.user_id == user.id)
    ).scalar_one()
    analysis_count = db.execute(
        select(func.count()).select_from(Analysis).where(Analysis.user_id == user.id)
    ).scalar_one()
    last_row = db.execute(
        select(Analysis.id, Analysis.status, Analysis.created_at, Dataset.filename)
        .join(Dataset, Analysis.dataset_id == Dataset.id)
        .where(Analysis.user_id == user.id)
        .where(Dataset.user_id == user.id)
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .limit(1)
    ).first()
    last_analysis = None
    if last_row is not None:
        last_analysis = {
            "id": last_row.id,
            "status": last_row.status,
            "created_at": datetime.datetime.fromtimestamp(last_row.created_at).strftime("%Y-%m-%d"),
            "filename": last_row.filename,
        }
    return templates.TemplateResponse(
        request=request,
        name="account.html",
        context={
            "email": user.email,
            "verified": user.verified_at is not None,
            "created_at": created_at_str,
            "file_count": file_count,
            "analysis_count": analysis_count,
            "last_analysis": last_analysis,
            "limit_mb": f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
            "limit_cells": f"{MAX_CELLS:,}".replace(",", ".") + " sel",
        },
        status_code=200,
    )


@router.get("/forgot", response_class=HTMLResponse)
def get_forgot(request: Request):
    if _gate_closed():
        return RedirectResponse("/", 303)
    msg = request.query_params.get("msg", "")
    return templates.TemplateResponse(
        request=request,
        name="forgot.html",
        context={"msg": msg},
        status_code=200,
    )


@router.post("/forgot")
def post_forgot(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_session),
):
    if _gate_closed():
        return RedirectResponse("/", 303)
    norm_email = _norm(email)
    allowed, retry_after = check_limit(
        "forgot:" + client_ip(request) + ":" + norm_email, 3, 3600
    )
    allowed_ip, retry_after_ip = check_limit("forgot:ip:" + client_ip(request), 10, 3600)
    if not allowed_ip:
        return HTMLResponse(
            "Terlalu banyak percobaan. Coba lagi nanti.",
            status_code=429,
            headers={"Retry-After": str(retry_after_ip)},
        )
    if not allowed:
        return HTMLResponse(
            "Terlalu banyak percobaan. Coba lagi nanti.",
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
    user = db.execute(select(User).where(User.email_normalized == norm_email)).scalar_one_or_none()
    if user is not None:
        raw = _issue_reset(db, user)
        db.commit()
        try:
            _send_reset(user, raw)
        except EmailSendError:
            pass
    return RedirectResponse("/forgot?msg=sent", 303)


@router.get("/reset", response_class=HTMLResponse)
def get_reset(request: Request, token: str = "", db: Session = Depends(get_session)):
    if not token:
        return RedirectResponse("/forgot?msg=token_bad", 303)
    token_h = hash_token(token)
    token_row = db.execute(
        select(EmailToken).where(EmailToken.token_hash == token_h)
    ).scalar_one_or_none()
    now = now_epoch()
    if (
        token_row is None
        or token_row.purpose != "reset"
        or token_row.used_at is not None
        or token_row.expires_at <= now
    ):
        return RedirectResponse("/forgot?msg=token_bad", 303)
    return templates.TemplateResponse(
        request=request,
        name="reset.html",
        context={"token": token},
        status_code=200,
    )


@router.post("/reset")
def post_reset(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_session),
):
    allowed, retry_after = check_limit("reset:" + client_ip(request), 10, 3600)
    if not allowed:
        return HTMLResponse(
            "Terlalu banyak percobaan. Coba lagi nanti.",
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
    if not password_policy(password):
        return templates.TemplateResponse(
            request=request,
            name="reset.html",
            context={"token": token, "error": "Password minimal 10 karakter."},
            status_code=200,
        )
    token_h = hash_token(token)
    token_row = db.execute(
        select(EmailToken).where(EmailToken.token_hash == token_h)
    ).scalar_one_or_none()
    now = now_epoch()
    if (
        token_row is None
        or token_row.purpose != "reset"
        or token_row.used_at is not None
        or token_row.expires_at <= now
    ):
        return RedirectResponse("/forgot?msg=token_bad", 303)
    res = db.execute(
        update(EmailToken)
        .where(EmailToken.id == token_row.id, EmailToken.used_at.is_(None))
        .values(used_at=now)
    )
    if res.rowcount != 1:
        db.rollback()
        return RedirectResponse("/forgot?msg=token_bad", 303)
    user = db.execute(select(User).where(User.id == token_row.user_id)).scalar_one_or_none()
    if user is None:
        db.rollback()
        return RedirectResponse("/forgot?msg=token_bad", 303)
    user.password_hash = hash_password(password)
    db.execute(delete(SessionRow).where(SessionRow.user_id == user.id))
    db.commit()
    return RedirectResponse("/login?msg=reset_done", 303)


@router.post("/resend")
def post_resend(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_session),
):
    if _gate_closed():
        return RedirectResponse("/", 303)
    norm_email = _norm(email)
    allowed, retry_after = check_limit(
        "resend:" + client_ip(request) + ":" + norm_email, 3, 3600
    )
    allowed_ip, retry_after_ip = check_limit("resend:ip:" + client_ip(request), 10, 3600)
    if not allowed_ip:
        return HTMLResponse(
            "Terlalu banyak percobaan. Coba lagi nanti.",
            status_code=429,
            headers={"Retry-After": str(retry_after_ip)},
        )
    if not allowed:
        return HTMLResponse(
            "Terlalu banyak percobaan. Coba lagi nanti.",
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
    user = db.execute(select(User).where(User.email_normalized == norm_email)).scalar_one_or_none()
    if user is not None and user.verified_at is None:
        raw = _issue_verify(db, user)
        db.commit()
        try:
            _send_verify(user, raw)
        except EmailSendError:
            pass
    return RedirectResponse("/login?msg=resent", 303)
