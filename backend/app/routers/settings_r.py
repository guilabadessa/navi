import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, settings_store as S
from ..db import get_db
from ..models import HealthCheck
from ..schemas import EvolutionSettingsIn, LetterheadIn, SmtpSettingsIn, TestSend
from ..security import require
from ..services import factory
from ..services.email_service import split_addrs
from ..services.report_service import letterhead

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/status")
def status(db: Session = Depends(get_db), _=Depends(require("dashboard.view"))):
    return {h.name: {"ok": h.ok, "detail": h.detail, "checked_at": h.checked_at.isoformat()} for h in db.scalars(select(HealthCheck))}


@router.get("/evolution")
def evo(db: Session = Depends(get_db), _=Depends(require("settings.view"))):
    return {"url": S.get(db, "evolution.url"), "instance": S.get(db, "evolution.instance"), "api_key_set": bool(S.get(db, "evolution.api_key"))}


@router.put("/evolution")
def evo_put(body: EvolutionSettingsIn, request: Request, db: Session = Depends(get_db), me=Depends(require("settings.edit"))):
    S.put(db, "evolution.url", body.url, me.email)
    S.put(db, "evolution.instance", body.instance, me.email)
    if body.api_key:
        S.put(db, "evolution.api_key", body.api_key, me.email)
    audit.log(db, request, "settings_evolution", "settings", detail={"url": body.url, "instance": body.instance, "key_changed": bool(body.api_key)})
    db.commit()
    return {"ok": True}


@router.post("/evolution/test")
def evo_test(request: Request, db: Session = Depends(get_db), _=Depends(require("settings.edit"))):
    try:
        st = factory.evolution(db).status()
        res = {"ok": True, "detail": f"Conectado: {json.dumps(st)[:200]}"}
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "detail": str(e)}
    audit.log(db, request, "evolution_test", "settings", result="ok" if res["ok"] else "falha")
    db.commit()
    return res


@router.get("/smtp")
def smtp(db: Session = Depends(get_db), _=Depends(require("settings.view"))):
    return {"host": S.get(db, "smtp.host"), "port": int(S.get(db, "smtp.port", "587") or 587), "user": S.get(db, "smtp.user"),
            "from": S.get(db, "smtp.from"), "password_set": bool(S.get(db, "smtp.password"))}


@router.put("/smtp")
def smtp_put(body: SmtpSettingsIn, request: Request, db: Session = Depends(get_db), me=Depends(require("settings.edit"))):
    S.put(db, "smtp.host", body.host, me.email)
    S.put(db, "smtp.port", str(body.port), me.email)
    S.put(db, "smtp.user", body.user or "", me.email)
    S.put(db, "smtp.from", body.from_ or "", me.email)
    if body.password:
        S.put(db, "smtp.password", body.password, me.email)
    audit.log(db, request, "settings_smtp", "settings", detail={"host": body.host, "port": body.port, "pwd_changed": bool(body.password)})
    db.commit()
    return {"ok": True}


@router.post("/smtp/test")
def smtp_test(body: TestSend, request: Request, db: Session = Depends(get_db), _=Depends(require("settings.edit"))):
    try:
        factory.email(db).send(split_addrs(body.to), "Teste de e-mail — NAVI", "Se você recebeu esta mensagem, o SMTP da NAVI está funcionando.")
        res = {"ok": True, "detail": "E-mail de teste enviado"}
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "detail": str(e)}
    audit.log(db, request, "smtp_test", "settings", result="ok" if res["ok"] else "falha", detail={"to": body.to})
    db.commit()
    return res


@router.get("/letterhead")
def lh_get(db: Session = Depends(get_db), _=Depends(require("settings.view"))):
    return letterhead(db)


@router.put("/letterhead")
def lh_put(body: LetterheadIn, request: Request, db: Session = Depends(get_db), me=Depends(require("settings.edit"))):
    S.put(db, "letterhead.orca", json.dumps(body.model_dump(), ensure_ascii=False), me.email)
    audit.log(db, request, "settings_letterhead", "settings")
    db.commit()
    return {"ok": True}


@router.get("/webhook")
def webhook_info(db: Session = Depends(get_db), _=Depends(require("settings.edit"))):
    return {"token_set": bool(S.get(db, "webhook.token")), "path": "/navi/api/webhook/zabbix"}


@router.post("/webhook/rotate")
def webhook_rotate(request: Request, db: Session = Depends(get_db), me=Depends(require("settings.edit"))):
    import secrets
    tok = secrets.token_urlsafe(32)
    S.put(db, "webhook.token", tok, me.email)
    audit.log(db, request, "webhook_token_rotate", "settings")
    db.commit()
    return {"token": tok}  # exibido uma unica vez
