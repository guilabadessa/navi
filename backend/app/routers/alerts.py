from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import AlertRule, Client, Dispatch, Event, MessageTemplate
from ..schemas import RuleIn, TemplateIn, TestSend
from ..security import require
from ..services import factory, notification_service as N
from ..util import to_dict

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/rules")
def rules(db: Session = Depends(get_db), _=Depends(require("alerts.view"))):
    names = dict(db.execute(select(Client.id, Client.trade_name)).all())
    return [{**to_dict(r), "client_name": names.get(r.client_id)} for r in db.scalars(select(AlertRule).order_by(AlertRule.name))]


@router.post("/rules")
def create_rule(body: RuleIn, request: Request, db: Session = Depends(get_db), _=Depends(require("alerts.edit"))):
    r = AlertRule(**body.model_dump())
    db.add(r)
    db.flush()
    audit.log(db, request, "alert_rule_create", "alert_rule", r.id, detail={"name": r.name})
    db.commit()
    return to_dict(r)


@router.put("/rules/{rid}")
def update_rule(rid: int, body: RuleIn, request: Request, db: Session = Depends(get_db), _=Depends(require("alerts.edit"))):
    r = db.get(AlertRule, rid)
    if not r:
        raise HTTPException(404)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    audit.log(db, request, "alert_rule_update", "alert_rule", rid, detail={"name": r.name})
    db.commit()
    return to_dict(r)


@router.delete("/rules/{rid}")
def delete_rule(rid: int, request: Request, db: Session = Depends(get_db), _=Depends(require("alerts.edit"))):
    r = db.get(AlertRule, rid)
    if not r:
        raise HTTPException(404)
    db.delete(r)
    audit.log(db, request, "alert_rule_delete", "alert_rule", rid)
    db.commit()
    return {"ok": True}


@router.get("/templates")
def templates(db: Session = Depends(get_db), _=Depends(require("alerts.view"))):
    return [to_dict(t) for t in db.scalars(select(MessageTemplate).order_by(MessageTemplate.kind, MessageTemplate.name))]


@router.post("/templates")
def create_template(body: TemplateIn, request: Request, db: Session = Depends(get_db), _=Depends(require("alerts.edit"))):
    t = MessageTemplate(**body.model_dump())
    db.add(t)
    db.flush()
    if t.is_default:
        for o in db.scalars(select(MessageTemplate).where(MessageTemplate.kind == t.kind, MessageTemplate.id != t.id)):
            o.is_default = False
    audit.log(db, request, "template_create", "template", t.id)
    db.commit()
    return to_dict(t)


@router.put("/templates/{tid}")
def update_template(tid: int, body: TemplateIn, request: Request, db: Session = Depends(get_db), _=Depends(require("alerts.edit"))):
    t = db.get(MessageTemplate, tid)
    if not t:
        raise HTTPException(404)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    if t.is_default:
        for o in db.scalars(select(MessageTemplate).where(MessageTemplate.kind == t.kind, MessageTemplate.id != t.id)):
            o.is_default = False
    audit.log(db, request, "template_update", "template", tid)
    db.commit()
    return to_dict(t)


@router.delete("/templates/{tid}")
def delete_template(tid: int, request: Request, db: Session = Depends(get_db), _=Depends(require("alerts.edit"))):
    t = db.get(MessageTemplate, tid)
    if not t:
        raise HTTPException(404)
    if t.is_default:
        raise HTTPException(400, "Não é possível excluir o template padrão")
    db.delete(t)
    audit.log(db, request, "template_delete", "template", tid)
    db.commit()
    return {"ok": True}


@router.post("/templates/preview")
def preview(body: TemplateIn, db: Session = Depends(get_db), _=Depends(require("alerts.view"))):
    ev = db.scalar(select(Event).order_by(Event.started_at.desc()).limit(1))
    if not ev:
        from datetime import datetime, timezone
        ev = Event(zbx_eventid="123456", host="FortiGate-Matriz", ip="10.0.0.1", trigger_name="WAN2 Down",
                   item_name="ifOperStatus[wan2]", severity=4, started_at=datetime.now(timezone.utc), opdata="down(2)")
    client = db.get(Client, ev.client_id) if ev.client_id else None
    if not client:
        client = Client(trade_name="Cliente Exemplo")
    return {"text": N.render(body.body, ev, client)}


@router.get("/dispatches")
def dispatches(status: str | None = None, page: int = 1, size: int = 50, db: Session = Depends(get_db),
               _=Depends(require("whatsapp.view"))):
    stmt = select(Dispatch)
    if status:
        stmt = stmt.where(Dispatch.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Dispatch.id.desc()).offset((page - 1) * size).limit(min(size, 200))).all()
    evs = {e.id: e for e in db.scalars(select(Event).where(Event.id.in_([d.event_id for d in rows])))}
    items = [{**to_dict(d), "host": evs[d.event_id].host if d.event_id in evs else None,
              "trigger": evs[d.event_id].trigger_name if d.event_id in evs else None} for d in rows]
    return {"total": total, "items": items}


@router.post("/test-whatsapp")
def test_whatsapp(body: TestSend, request: Request, db: Session = Depends(get_db), _=Depends(require("alerts.edit"))):
    try:
        resp = factory.evolution(db).send_text(body.to if "@" in body.to else body.to, body.text)
        ok, detail = True, "Mensagem enviada"
    except Exception as e:  # noqa: BLE001
        ok, detail = False, str(e)
    audit.log(db, request, "whatsapp_test", "whatsapp", result="ok" if ok else "falha", detail={"to": body.to})
    db.commit()
    return {"ok": ok, "detail": detail}
