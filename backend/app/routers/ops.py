"""Recursos operacionais: cobertura de clientes, reclassificacao de severidade, modo sombra, busca global."""
import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, settings_store
from ..db import get_db
from ..models import Client, ClientHost, ClientHostGroup, Event, MaintenanceWindow, SeverityRule, ZbxHost, ZbxHostGroup
from ..security import require
from ..services import commlog, event_service, factory, maintenance_service, noc_service, severity_service
from ..util import by_client, parse_dt, to_dict

router = APIRouter(tags=["ops"])


# ---------------- cobertura ----------------
@router.get("/coverage")
def coverage(db: Session = Depends(get_db), _=Depends(require("clients.view"))):
    """Host groups sem cliente associado e eventos sem cliente (nao geram alerta/SLA/relatorio)."""
    assigned = set(db.scalars(select(ClientHostGroup.zbx_groupid)))
    hosts_assigned = set(db.scalars(select(ClientHost.zbx_hostid)))
    hosts = list(db.scalars(select(ZbxHost).where(ZbxHost.active.is_(True), ZbxHost.status == 0)))
    since = datetime.now(timezone.utc) - timedelta(days=30)
    ev30 = dict(db.execute(select(Event.hostid, func.count()).where(Event.kind == "infra", Event.client_id.is_(None), Event.started_at >= since)
                           .group_by(Event.hostid)).all())
    groups = []
    for g in db.scalars(select(ZbxHostGroup).where(ZbxHostGroup.active.is_(True)).order_by(ZbxHostGroup.name)):
        if g.groupid in assigned:
            continue
        members = [h for h in hosts if g.groupid in (h.group_ids or [])]
        # grupo vazio ou cujos hosts ja estao cobertos por outro grupo/host de cliente nao e pendencia
        pend = [h for h in members if not (set(h.group_ids or []) & assigned) and h.hostid not in hosts_assigned]
        if not pend:
            continue
        groups.append({"groupid": g.groupid, "name": g.name, "hosts": len(pend),
                       "events_30d": sum(ev30.get(h.hostid, 0) for h in pend), "sample": [h.name for h in pend[:4]]})
    uncovered = [h for h in hosts if not (set(h.group_ids or []) & assigned) and h.hostid not in hosts_assigned]
    return {"groups": sorted(groups, key=lambda x: -x["events_30d"]), "hosts_uncovered": len(uncovered), "hosts_total": len(hosts),
            "events_without_client_30d": db.scalar(select(func.count()).select_from(Event).where(Event.kind == "infra", Event.client_id.is_(None), Event.started_at >= since))}


class AssignIn(BaseModel):
    client_id: int
    groupids: list[str]


@router.post("/coverage/assign")
def assign(body: AssignIn, request: Request, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    c = db.get(Client, body.client_id)
    if not c:
        raise HTTPException(404, "Cliente não encontrado")
    have = {g.zbx_groupid for g in c.groups}
    names = {g.groupid: g.name for g in db.scalars(select(ZbxHostGroup))}
    add = [g for g in dict.fromkeys(body.groupids) if g not in have and g in names]
    c.groups.extend(ClientHostGroup(zbx_groupid=g, name=names[g]) for g in add)
    audit.log(db, request, "client_assign_groups", "client", c.id, detail={"groups": [names[g] for g in add]})
    db.commit()
    changed = event_service.relink_events(db)
    return {"added": len(add), "events_relinked": changed}


class MaintIn(BaseModel):
    hours: float = 2


@router.post("/clients/{cid}/maintenance")
def maintenance(cid: int, body: MaintIn, request: Request, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    now = datetime.now(timezone.utc)
    c.maintenance_until = None if body.hours <= 0 else now + timedelta(hours=min(body.hours, 72))
    # registra tambem como janela (para o SLA descontar o periodo); ao encerrar, fecha as janelas rapidas em curso
    for w in db.scalars(select(MaintenanceWindow).where(MaintenanceWindow.client_id == cid, MaintenanceWindow.name == "Manutenção rápida",
                                                        MaintenanceWindow.kind == "once", MaintenanceWindow.end_at > now)):
        w.end_at = now
    if body.hours > 0:
        db.add(MaintenanceWindow(name="Manutenção rápida", client_id=cid, kind="once", start_at=now, end_at=c.maintenance_until,
                                 created_by=getattr(request.state, "user", None) and request.state.user.email))
    audit.log(db, request, "client_maintenance", "client", cid, detail={"hours": body.hours})
    db.commit()
    return {"maintenance_until": c.maintenance_until.isoformat() if c.maintenance_until else None}


# ---------------- reclassificacao de severidade ----------------
class SevRuleIn(BaseModel):
    name: str
    host_pattern: str | None = None
    trigger_pattern: str | None = None
    from_max: int = 0
    severity: int = 4
    enabled: bool = True


@router.get("/severity-rules")
def sev_rules(db: Session = Depends(get_db), _=Depends(require("alerts.view"))):
    return [to_dict(r) for r in db.scalars(select(SeverityRule).order_by(SeverityRule.id))]


@router.post("/severity-rules")
def sev_create(body: SevRuleIn, request: Request, db: Session = Depends(get_db), _=Depends(require("alerts.edit"))):
    if not (body.host_pattern or body.trigger_pattern):
        raise HTTPException(422, "Informe host e/ou trigger para a regra")
    r = SeverityRule(**body.model_dump())
    db.add(r)
    db.flush()
    audit.log(db, request, "severity_rule_create", "severity_rule", r.id, detail={"name": r.name})
    db.commit()
    return to_dict(r)


@router.put("/severity-rules/{rid}")
def sev_update(rid: int, body: SevRuleIn, request: Request, db: Session = Depends(get_db), _=Depends(require("alerts.edit"))):
    r = db.get(SeverityRule, rid)
    if not r:
        raise HTTPException(404)
    if not (body.host_pattern or body.trigger_pattern):
        raise HTTPException(422, "Informe host e/ou trigger para a regra")
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    audit.log(db, request, "severity_rule_update", "severity_rule", rid, detail={"name": r.name})
    db.commit()
    return to_dict(r)


@router.delete("/severity-rules/{rid}")
def sev_delete(rid: int, request: Request, db: Session = Depends(get_db), _=Depends(require("alerts.edit"))):
    r = db.get(SeverityRule, rid)
    if not r:
        raise HTTPException(404)
    db.delete(r)
    audit.log(db, request, "severity_rule_delete", "severity_rule", rid)
    db.commit()
    return {"ok": True}


@router.post("/severity-rules/reapply")
def sev_reapply(request: Request, db: Session = Depends(get_db), _=Depends(require("alerts.edit"))):
    n = severity_service.reapply(db)
    audit.log(db, request, "severity_reapply", detail={"changed": n})
    db.commit()
    return {"changed": n}


# ---------------- modo sombra ----------------
@router.get("/alerts/shadow")
def shadow_get(db: Session = Depends(get_db), _=Depends(require("alerts.view"))):
    return {"shadow": settings_store.get(db, "alerts.shadow") == "1"}


class ShadowIn(BaseModel):
    shadow: bool


@router.put("/alerts/shadow")
def shadow_put(body: ShadowIn, request: Request, db: Session = Depends(get_db), user=Depends(require("alerts.edit"))):
    settings_store.put(db, "alerts.shadow", "1" if body.shadow else "0", getattr(user, "email", None))
    audit.log(db, request, "alerts_shadow", detail={"shadow": body.shadow})
    db.commit()
    return {"shadow": body.shadow}


# ---------------- busca global ----------------
@router.get("/search")
def search(q: str, db: Session = Depends(get_db), _=Depends(require("dashboard.view"))):
    q = q.strip()
    if len(q) < 2:
        return {"clients": [], "hosts": [], "events": []}
    like = f"%{q}%"
    return {
        "clients": [{"id": c.id, "name": c.trade_name} for c in db.scalars(select(Client).where(Client.trade_name.ilike(like) | Client.cnpj.ilike(like)).limit(6))],
        "hosts": [{"hostid": h.hostid, "name": h.name, "ip": h.ip} for h in db.scalars(
            select(ZbxHost).where(ZbxHost.active.is_(True), ZbxHost.name.ilike(like) | ZbxHost.ip.ilike(like)).limit(8))],
        "events": [{"id": e.id, "host": e.host, "trigger": e.trigger_name, "status": e.status, "severity": e.severity, "started_at": e.started_at.isoformat()}
                   for e in db.scalars(select(Event).where(Event.host.ilike(like) | Event.trigger_name.ilike(like)).order_by(Event.started_at.desc()).limit(6))]}


# ---------------- exportacao CSV de eventos ----------------
@router.get("/events-export")
def export_events(status: str | None = None, client_id: int | None = None, q: str | None = None, min_severity: int | None = None,
                  since: str | None = None, until: str | None = None, db: Session = Depends(get_db), _=Depends(require("events.view"))):
    stmt = select(Event)
    if status:
        stmt = stmt.where(Event.status == status.upper())
    if client_id:
        stmt = stmt.where(by_client(Event.client_id, client_id))
    if min_severity is not None:
        stmt = stmt.where(Event.severity >= min_severity)
    if since:
        stmt = stmt.where(Event.started_at >= parse_dt(since))
    if until:
        stmt = stmt.where(Event.started_at < parse_dt(until))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Event.host.ilike(like) | Event.trigger_name.ilike(like) | Event.ip.ilike(like) | Event.item_name.ilike(like))
    names = dict(db.execute(select(Client.id, Client.trade_name)).all())
    sev = ["Não classificado", "Informação", "Atenção", "Média", "Alta", "Desastre"]
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["Status", "Severidade", "Cliente", "Host", "IP", "Problema", "Item", "Início", "Recuperação", "Duração (s)"])
    for e in db.scalars(stmt.order_by(Event.started_at.desc()).limit(20000)):
        w.writerow([e.status, sev[e.severity or 0], names.get(e.client_id, ""), e.host, e.ip or "", e.trigger_name or "", e.item_name or "",
                    e.started_at.isoformat(), e.recovered_at.isoformat() if e.recovered_at else "", e.duration_s or ""])
    return Response("﻿" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="eventos-navi.csv"'})


# ---------------- janelas de manutencao programadas ----------------
class WindowIn(BaseModel):
    name: str
    client_id: int | None = None
    kind: str = "once"  # once | weekly
    start_at: datetime | None = None
    end_at: datetime | None = None
    weekdays: list[int] | None = None
    start_time: str | None = None
    duration_min: int | None = None
    enabled: bool = True


def _check_window(b: WindowIn):
    if b.kind == "once":
        if not (b.start_at and b.end_at) or b.end_at <= b.start_at:
            raise HTTPException(422, "Informe início e fim (o fim deve ser depois do início)")
    elif b.kind == "weekly":
        if not b.weekdays or not b.start_time or not b.duration_min or b.duration_min <= 0 or b.duration_min > 1440:
            raise HTTPException(422, "Informe os dias da semana, o horário de início e a duração (1 a 1440 min)")
        try:
            hh, mm = b.start_time.split(":")
            assert 0 <= int(hh) < 24 and 0 <= int(mm) < 60
        except Exception:  # noqa: BLE001
            raise HTTPException(422, "Horário inválido (use HH:MM)") from None
        if any(d < 0 or d > 6 for d in b.weekdays):
            raise HTTPException(422, "Dia da semana inválido")
    else:
        raise HTTPException(422, "Tipo inválido")


@router.get("/maintenance")
def windows_list(db: Session = Depends(get_db), _=Depends(require("alerts.view"))):
    names = dict(db.execute(select(Client.id, Client.trade_name)).all())
    now = datetime.now(timezone.utc)
    out = []
    for w in db.scalars(select(MaintenanceWindow).where(MaintenanceWindow.name != "Manutenção rápida").order_by(MaintenanceWindow.id.desc())):
        nxt = [i for i in maintenance_service.expand(w, now - timedelta(days=1), now + timedelta(days=60)) if i[1] > now]
        d = to_dict(w)
        d["client_name"] = names.get(w.client_id)
        d["next"] = [x.isoformat() for x in (nxt[0] if nxt else [])]
        d["active"] = bool(nxt and nxt[0][0] <= now)
        out.append(d)
    return out


@router.post("/maintenance")
def windows_create(body: WindowIn, request: Request, db: Session = Depends(get_db), me=Depends(require("alerts.edit"))):
    _check_window(body)
    w = MaintenanceWindow(**body.model_dump(), created_by=me.email)
    db.add(w)
    db.flush()
    audit.log(db, request, "maintenance_create", "maintenance", w.id, detail={"name": w.name, "kind": w.kind})
    db.commit()
    return to_dict(w)


@router.put("/maintenance/{wid}")
def windows_update(wid: int, body: WindowIn, request: Request, db: Session = Depends(get_db), _=Depends(require("alerts.edit"))):
    w = db.get(MaintenanceWindow, wid)
    if not w:
        raise HTTPException(404)
    _check_window(body)
    for k, v in body.model_dump().items():
        setattr(w, k, v)
    audit.log(db, request, "maintenance_update", "maintenance", wid, detail={"name": w.name})
    db.commit()
    return to_dict(w)


@router.delete("/maintenance/{wid}")
def windows_delete(wid: int, request: Request, db: Session = Depends(get_db), _=Depends(require("alerts.edit"))):
    w = db.get(MaintenanceWindow, wid)
    if not w:
        raise HTTPException(404)
    db.delete(w)
    audit.log(db, request, "maintenance_delete", "maintenance", wid)
    db.commit()
    return {"ok": True}


# ---------------- NOC: destinos internos, escalonamento, agrupamento e resumo diario ----------------
class NocIn(BaseModel):
    noc_wa: str = ""
    noc_emails: str = ""
    escalation_enabled: bool = False
    escalation_minutes: int = 15
    escalation_min_severity: int = 4
    storm_enabled: bool = True
    storm_threshold: int = 3
    storm_hold_s: int = 15
    digest_enabled: bool = False
    digest_time: str = "08:00"


@router.get("/noc-settings")
def noc_get(db: Session = Depends(get_db), _=Depends(require("alerts.view"))):
    return noc_service.cfg(db)


@router.put("/noc-settings")
def noc_put(body: NocIn, request: Request, db: Session = Depends(get_db), me=Depends(require("alerts.edit"))):
    if not noc_service.validate_time(body.digest_time):
        raise HTTPException(422, "Horário do resumo inválido (use HH:MM)")
    if not 0 <= body.escalation_min_severity <= 5:
        raise HTTPException(422, "Severidade mínima inválida")
    if body.escalation_enabled and not (body.noc_wa.strip() or body.noc_emails.strip()):
        raise HTTPException(422, "Para escalonar, informe o grupo de WhatsApp e/ou os e-mails do NOC")
    noc_service.save(db, body.model_dump(), me.email)
    audit.log(db, request, "noc_settings", detail={"escalation": body.escalation_enabled, "digest": body.digest_enabled, "storm": body.storm_enabled})
    db.commit()
    return noc_service.cfg(db)


class NocTest(BaseModel):
    what: str = "message"  # message | digest


@router.post("/noc-settings/test")
def noc_test(body: NocTest, db: Session = Depends(get_db), _=Depends(require("alerts.edit"))):
    """Envia ao NOC (destinos internos) uma mensagem de teste ou o resumo diario agora."""
    c = noc_service.cfg(db)
    if body.what == "digest":
        return {"result": noc_service.send_digest(db, factory.evolution(db), manual=True)}
    res = []
    if c["noc_wa"]:
        try:
            factory.evolution(db).send_text(c["noc_wa"], "🧪 *TESTE NAVI* — este é o canal do NOC para escalonamentos e resumo diário. Não é um incidente real.")
            res.append("WhatsApp ok")
            commlog.record("whatsapp", "Teste do canal do NOC", c["noc_wa"], "sent")
        except Exception as e:  # noqa: BLE001
            res.append(f"WhatsApp erro: {str(e)[:120]}")
            commlog.record("whatsapp", "Teste do canal do NOC", c["noc_wa"], "failed", str(e))
    if c["noc_emails"]:
        try:
            from ..services import mailer
            mailer.send(db, "notice", c["noc_emails"], "[TESTE] Canal do NOC — NAVI",
                        mailer.notice_ctx("Teste do canal do NOC", ["Este é o canal interno do NOC para escalonamentos e resumo diário.", "Mensagem de teste — não é um incidente real."]))
            res.append("e-mail ok")
        except Exception as e:  # noqa: BLE001
            res.append(f"e-mail erro: {str(e)[:120]}")
    return {"result": " · ".join(res) or "Informe o grupo de WhatsApp e/ou e-mails do NOC e salve antes de testar."}
