from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, settings_store as S
from ..db import get_db
from ..models import (Client, ClientHost, ClientHostGroup, Event, SyncRun, ZbxHost, ZbxHostGroup)
from ..schemas import ZabbixSettingsIn
from ..security import require
from ..services import event_service, factory, sync_service
from ..services.zabbix_service import ZabbixError
from ..util import to_dict

router = APIRouter(prefix="/zabbix", tags=["zabbix"])


@router.get("/settings")
def get_settings_(db: Session = Depends(get_db), _=Depends(require("settings.view"))):
    last = db.scalar(select(SyncRun).order_by(SyncRun.id.desc()).limit(1))
    return {"url": S.get(db, "zabbix.url"), "token_set": bool(S.get(db, "zabbix.token")),
            "last_sync": to_dict(last) if last else None,
            "objects": {"hosts": db.scalar(select(func.count()).select_from(ZbxHost).where(ZbxHost.active.is_(True))),
                        "host_groups": db.scalar(select(func.count()).select_from(ZbxHostGroup).where(ZbxHostGroup.active.is_(True))),
                        "triggers": db.scalar(select(func.coalesce(func.sum(ZbxHost.trigger_count), 0))),
                        "items": db.scalar(select(func.coalesce(func.sum(ZbxHost.item_count), 0)))}}


@router.put("/settings")
def put_settings(body: ZabbixSettingsIn, request: Request, db: Session = Depends(get_db), me=Depends(require("settings.edit"))):
    S.put(db, "zabbix.url", body.url, me.email)
    if body.token:
        S.put(db, "zabbix.token", body.token, me.email)
    audit.log(db, request, "settings_zabbix", "settings", detail={"url": body.url, "token_changed": bool(body.token)})
    db.commit()
    return {"ok": True}


@router.post("/test")
def test(request: Request, db: Session = Depends(get_db), _=Depends(require("settings.edit"))):
    z = factory.zabbix(db)
    try:
        v = z.version()
        info = z.call("hostgroup.get", {"limit": 1, "output": ["groupid"]})
        res = {"ok": True, "version": v, "detail": "Conexão e autenticação OK"}
    except ZabbixError as e:
        res = {"ok": False, "version": None, "detail": str(e)}
    audit.log(db, request, "zabbix_test", "settings", result="ok" if res["ok"] else "falha")
    db.commit()
    return res


@router.post("/sync")
def sync(request: Request, db: Session = Depends(get_db), _=Depends(require("settings.edit"))):
    try:
        counts = sync_service.sync_inventory(db, factory.zabbix(db), trigger="manual")
        ev = event_service.poll(db, factory.zabbix(db))
    except ZabbixError as e:
        audit.log(db, request, "zabbix_sync", "settings", result="falha", detail={"error": str(e)})
        db.commit()
        raise HTTPException(502, str(e))
    audit.log(db, request, "zabbix_sync", "settings", detail={**counts, **ev})
    db.commit()
    return {"counts": counts, "events": ev}


@router.get("/groups")
def groups(q: str | None = None, db: Session = Depends(get_db), _=Depends(require("monitoring.view"))):
    stmt = select(ZbxHostGroup).where(ZbxHostGroup.active.is_(True)).order_by(ZbxHostGroup.name)
    if q:
        stmt = stmt.where(ZbxHostGroup.name.ilike(f"%{q}%"))
    owner = {}
    for r in db.execute(select(ClientHostGroup.zbx_groupid, Client.trade_name).join(Client)):
        owner.setdefault(r[0], []).append(r[1])
    out = []
    for g in db.scalars(stmt):
        d = to_dict(g)
        d["clients"] = owner.get(g.groupid, [])
        out.append(d)
    return out


@router.get("/hosts")
def hosts(q: str | None = None, groupid: str | None = None, client_id: int | None = None, available: int | None = None,
          page: int = 1, size: int = 50, db: Session = Depends(get_db), _=Depends(require("monitoring.view"))):
    rows = list(db.scalars(select(ZbxHost).where(ZbxHost.active.is_(True)).order_by(ZbxHost.name)))
    gmap = {g.groupid: g.name for g in db.scalars(select(ZbxHostGroup))}
    if q:
        ql = q.lower()
        rows = [h for h in rows if ql in (h.name or "").lower() or ql in (h.ip or "") or ql in (h.dns or "").lower()]
    if groupid:
        rows = [h for h in rows if groupid in (h.group_ids or [])]
    if client_id:
        c = db.get(Client, client_id)
        ids = {x.zbx_hostid for x in c.hosts} if c else set()
        gids = {x.zbx_groupid for x in c.groups} if c else set()
        rows = [h for h in rows if h.hostid in ids or (set(h.group_ids or []) & gids)]
    if available is not None:
        rows = [h for h in rows if h.available == available]
    open_by = dict(db.execute(select(Event.hostid, func.count()).where(Event.status == "PROBLEM").group_by(Event.hostid)).all())
    total = len(rows)
    out = []
    for h in rows[(page - 1) * size: page * size]:
        d = to_dict(h, {"interfaces"})
        d["groups"] = [gmap.get(g, g) for g in (h.group_ids or [])]
        d["open_events"] = open_by.get(h.hostid, 0)
        out.append(d)
    return {"total": total, "items": out}


@router.get("/hosts/{hostid}")
def host(hostid: str, db: Session = Depends(get_db), _=Depends(require("monitoring.view"))):
    h = db.get(ZbxHost, hostid)
    if not h:
        raise HTTPException(404)
    gmap = {g.groupid: g.name for g in db.scalars(select(ZbxHostGroup))}
    d = to_dict(h)
    d["groups"] = [gmap.get(g, g) for g in (h.group_ids or [])]
    # itens e triggers sao consultados ao vivo na API (nao sao armazenados na NAVI)
    try:
        z = factory.zabbix(db)
        d["triggers"] = [{"triggerid": t["triggerid"], "description": t["description"], "priority": int(t["priority"]),
                          "value": int(t["value"]), "status": int(t["status"])} for t in z.host_triggers(hostid)]
        d["items"] = [{"itemid": i["itemid"], "name": i["name"], "key_": i["key_"], "units": i.get("units"),
                       "lastvalue": i.get("lastvalue"), "state": int(i.get("state") or 0)} for i in z.host_items(hostid)]
        d["live_error"] = None
    except ZabbixError as e:
        d["triggers"], d["items"], d["live_error"] = [], [], str(e)
    d["events"] = [to_dict(e) for e in db.scalars(select(Event).where(Event.hostid == hostid).order_by(Event.started_at.desc()).limit(50))]
    return d
