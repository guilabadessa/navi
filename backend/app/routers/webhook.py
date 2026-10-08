import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .. import audit, settings_store as S
from ..db import get_db
from ..security import api_limiter, client_ip
from ..services import event_service

router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.post("/zabbix")
async def zabbix_webhook(request: Request, x_navi_token: str = Header(default=""), db: Session = Depends(get_db)):
    ip = client_ip(request)
    if api_limiter.blocked("wh|" + ip):
        raise HTTPException(429)
    api_limiter.hit("wh|" + ip)
    expected = S.get(db, "webhook.token")
    if not expected or not hmac.compare_digest(x_navi_token, expected):
        audit.log(db, request, "webhook", "webhook", result="negado")
        db.commit()
        raise HTTPException(401, "Token inválido")
    payload = await request.json()
    if "eventid" not in payload:
        raise HTTPException(422, "eventid obrigatório")
    res = event_service.from_webhook(db, payload)
    return res
