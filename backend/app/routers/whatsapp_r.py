"""WhatsApp (WA-AKG): webhook de entrada assinado e configuracao do provedor. Token/segredos nunca saem na API."""
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, settings_store as S
from ..db import get_db
from ..security import require
from ..services import wa_inbound
from ..services.wa_akg_service import WaAkgService

router = APIRouter(prefix="/wa", tags=["whatsapp"])


@router.post("/webhook")
async def webhook(request: Request, x_webhook_signature: str = Header(default=""), db: Session = Depends(get_db)):
    raw = await request.body()
    if not wa_inbound.verify_signature(S.get(db, "wa_akg.webhook_secret"), raw, x_webhook_signature):
        audit.log(db, request, "wa_webhook", "whatsapp", result="negado")
        db.commit()
        raise HTTPException(401, "Assinatura inválida")
    try:
        payload = json.loads(raw)
    except ValueError:
        return {"ok": True, "stored": False}  # corpo ilegivel: 200 para o gateway nao reentregar para sempre
    parsed = wa_inbound.parse_payload(payload) if isinstance(payload, dict) else None
    if not parsed:
        return {"ok": True, "stored": False}
    msg = wa_inbound.store_inbound(db, parsed)
    if msg is not None:
        db.commit()
        wa_inbound.on_inbound(db, msg)
    return {"ok": True, "stored": msg is not None}


class WaSettingsIn(BaseModel):
    provider: str = Field(pattern="^(evolution|wa_akg)$")
    url: str = Field(max_length=512)
    session: str = Field(max_length=64)
    api_key: str | None = None
    webhook_secret: str | None = None


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), _=Depends(require("settings.view"))):
    return {"provider": S.get(db, "whatsapp.provider", "evolution"), "url": S.get(db, "wa_akg.url"), "session": S.get(db, "wa_akg.session"),
            "api_key_set": bool(S.get(db, "wa_akg.api_key")), "webhook_secret_set": bool(S.get(db, "wa_akg.webhook_secret")),
            "webhook_path": "/cliente/api/wa/webhook"}


@router.put("/settings")
def put_settings(body: WaSettingsIn, request: Request, db: Session = Depends(get_db), me=Depends(require("settings.edit"))):
    S.put(db, "whatsapp.provider", body.provider, me.email)
    S.put(db, "wa_akg.url", body.url.strip(), me.email)
    S.put(db, "wa_akg.session", body.session.strip(), me.email)
    if body.api_key:
        S.put(db, "wa_akg.api_key", body.api_key, me.email)
    if body.webhook_secret:
        S.put(db, "wa_akg.webhook_secret", body.webhook_secret, me.email)
    audit.log(db, request, "settings_whatsapp", "settings", detail={"provedor": body.provider, "url": body.url, "sessao": body.session,
                                                                    "key_changed": bool(body.api_key), "secret_changed": bool(body.webhook_secret)})
    db.commit()
    return {"ok": True}


def _gateway(db: Session) -> WaAkgService:
    """Sempre o WA-AKG (nao o provedor ativo): precisa dar para testar e parear antes de trocar o provedor."""
    return WaAkgService(S.get(db, "wa_akg.url"), S.get(db, "wa_akg.session"), S.get(db, "wa_akg.api_key"))


@router.post("/test")
def test(request: Request, db: Session = Depends(get_db), _=Depends(require("settings.edit"))):
    try:
        st = _gateway(db).status()
        res = {"ok": True, "detail": f"Conectado: {json.dumps(st)[:200]}"}
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "detail": str(e)}
    audit.log(db, request, "wa_test", "settings", result="ok" if res["ok"] else "falha")
    db.commit()
    return res


@router.get("/qr")
def qr(db: Session = Depends(get_db), _=Depends(require("settings.edit"))):
    return _gateway(db).qr()
