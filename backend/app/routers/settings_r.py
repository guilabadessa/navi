import json
from datetime import datetime

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, settings_store as S
from ..db import get_db
from ..models import HealthCheck
from ..schemas import EvolutionSettingsIn, LetterheadIn, PreviewIn, SmtpSettingsIn, TestSend
from ..security import require
from ..services import factory, mailer
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
    sig_img = S.get(db, "smtp.sig_image")
    return {"host": S.get(db, "smtp.host"), "port": int(S.get(db, "smtp.port", "587") or 587), "user": S.get(db, "smtp.user"),
            "from": S.get(db, "smtp.from"), "from_name": S.get(db, "smtp.from_name", "NOC Orca TI"), "password_set": bool(S.get(db, "smtp.password")),
            "sig_enabled": S.get(db, "smtp.sig_enabled") == "1", "sig_mode": S.get(db, "smtp.sig_mode") or "text",
            "sig_text": S.get(db, "smtp.sig_text"), "sig_image": bool(sig_img and Path(sig_img).exists())}


@router.put("/smtp")
def smtp_put(body: SmtpSettingsIn, request: Request, db: Session = Depends(get_db), me=Depends(require("settings.edit"))):
    S.put(db, "smtp.host", body.host, me.email)
    S.put(db, "smtp.port", str(body.port), me.email)
    S.put(db, "smtp.user", body.user or "", me.email)
    S.put(db, "smtp.from", body.from_ or "", me.email)
    S.put(db, "smtp.from_name", body.from_name or "", me.email)
    S.put(db, "smtp.sig_enabled", "1" if body.sig_enabled else "0", me.email)
    S.put(db, "smtp.sig_mode", body.sig_mode, me.email)
    S.put(db, "smtp.sig_text", body.sig_text or "", me.email)
    if body.password:
        S.put(db, "smtp.password", body.password, me.email)
    audit.log(db, request, "settings_smtp", "settings", detail={"host": body.host, "port": body.port, "pwd_changed": bool(body.password),
                                                              "signature": body.sig_enabled and body.sig_mode})
    db.commit()
    return {"ok": True}


@router.post("/smtp/signature-image")
async def sig_upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db), me=Depends(require("settings.edit"))):
    data = await file.read()
    try:
        path = mailer.save_signature_image(data)
    except ValueError as e:
        raise HTTPException(422, str(e))
    S.put(db, "smtp.sig_image", path, me.email)
    audit.log(db, request, "settings_signature_image", "settings")
    db.commit()
    return {"ok": True}


@router.delete("/smtp/signature-image")
def sig_delete(request: Request, db: Session = Depends(get_db), me=Depends(require("settings.edit"))):
    p = S.get(db, "smtp.sig_image")
    if p:
        Path(p).unlink(missing_ok=True)
    S.put(db, "smtp.sig_image", "", me.email)
    audit.log(db, request, "settings_signature_image_delete", "settings")
    db.commit()
    return {"ok": True}


@router.get("/smtp/signature-image")
def sig_get(db: Session = Depends(get_db), _=Depends(require("settings.view"))):
    p = S.get(db, "smtp.sig_image")
    if not p or not Path(p).exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.post("/smtp/preview")
def smtp_preview(body: PreviewIn, db: Session = Depends(get_db), _=Depends(require("settings.view"))):
    ctxs = {
        "report": mailer.report_ctx("Cliente Exemplo", "01/09/2026 a 30/09/2026", "Relatório Mensal", "Relatorio_Mensal.pdf",
                                    {"availability": 99.742, "incidents": 7, "hosts_total": 12}),
        "notice": mailer.notice_ctx("Aviso de manutenção programada", ["Informamos que será realizada uma manutenção programada no ambiente, sem previsão de indisponibilidade."],
                                    highlight="Sábado, 10/10 · 22:00 às 23:30", greeting="Prezados,"),
        "new_user": mailer.new_user_ctx("Maria Souza", "maria.souza@orcati.com.br", "Temp-4821-xQ", "Analista NOC"),
        "invite": mailer.invite_ctx("Maria Souza", "Analista NOC", "https://navi.orcati.com.br/cliente/convite/exemplo"),
    }
    if body.kind == "digest":
        from ..services import noc_service
        ctxs["digest"] = noc_service.digest_ctx(noc_service.digest_data(db), datetime.now().strftime("%d/%m/%Y"))
    html, _t, _i = mailer.build(db, body.kind, ctxs[body.kind], preview=True)
    return {"html": html}


@router.post("/smtp/test")
def smtp_test(body: TestSend, request: Request, db: Session = Depends(get_db), _=Depends(require("settings.edit"))):
    try:
        mailer.send(db, "notice", body.to, "Teste de e-mail — NAVI",
                    mailer.notice_ctx("Teste de envio", ["Se você recebeu esta mensagem, o SMTP da NAVI está configurado corretamente."],
                                      highlight="SMTP autenticado com sucesso ✔", greeting="Olá!"))
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
    return {"token_set": bool(S.get(db, "webhook.token")), "path": "/cliente/api/webhook/zabbix"}


@router.post("/webhook/rotate")
def webhook_rotate(request: Request, db: Session = Depends(get_db), me=Depends(require("settings.edit"))):
    import secrets
    tok = secrets.token_urlsafe(32)
    S.put(db, "webhook.token", tok, me.email)
    audit.log(db, request, "webhook_token_rotate", "settings")
    db.commit()
    return {"token": tok}  # exibido uma unica vez
