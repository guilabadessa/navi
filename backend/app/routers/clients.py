import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..formats import try_phone
from ..models import (AlertRule, Client, ClientContact, ClientHost, ClientHostGroup, Event, Report, ReportRun,
                      ZbxHost, ZbxHostGroup)
from ..schemas import ClientIn
from ..security import require
from ..services import kpi_service
from ..util import to_dict

router = APIRouter(prefix="/clients", tags=["clients"])


def _full(db: Session, c: Client) -> dict:
    d = to_dict(c)
    gmap = {g.groupid: g.name for g in db.scalars(select(ZbxHostGroup))}
    d["group_ids"] = [g.zbx_groupid for g in c.groups]
    d["groups"] = [{"groupid": g.zbx_groupid, "name": gmap.get(g.zbx_groupid, g.name)} for g in c.groups]
    d["host_ids"] = [h.zbx_hostid for h in c.hosts]
    d["contacts"] = [to_dict(x) for x in c.contacts]
    return d


def _apply(db: Session, c: Client, b: ClientIn):
    for k, v in b.model_dump(exclude={"group_ids", "host_ids", "contacts"}).items():
        setattr(c, k, v)
    gmap = {g.groupid: g.name for g in db.scalars(select(ZbxHostGroup))}
    want_g, want_h = list(dict.fromkeys(b.group_ids)), list(dict.fromkeys(b.host_ids))
    # atualizacao por diferenca (evita violar a unicidade ao recriar linhas iguais)
    c.groups[:] = [g for g in c.groups if g.zbx_groupid in want_g]
    have = {g.zbx_groupid for g in c.groups}
    c.groups.extend(ClientHostGroup(zbx_groupid=g, name=gmap.get(g)) for g in want_g if g not in have)
    c.hosts[:] = [h for h in c.hosts if h.zbx_hostid in want_h]
    have = {h.zbx_hostid for h in c.hosts}
    c.hosts.extend(ClientHost(zbx_hostid=h) for h in want_h if h not in have)
    c.contacts = [ClientContact(name=x.get("name", "")[:255], role=x.get("role"), email=x.get("email"), phone=try_phone(x.get("phone")))
                  for x in b.contacts if x.get("name")]


@router.get("")
def list_clients(q: str | None = None, db: Session = Depends(get_db), _=Depends(require("clients.view"))):
    stmt = select(Client).order_by(Client.trade_name)
    if q:
        stmt = stmt.where(Client.trade_name.ilike(f"%{q}%") | Client.cnpj.ilike(f"%{q}%"))
    open_by = dict(db.execute(select(Event.client_id, func.count()).where(Event.status == "PROBLEM")
                              .group_by(Event.client_id)).all())
    out = []
    for c in db.scalars(stmt):
        d = to_dict(c)
        d["group_count"], d["open_events"] = len(c.groups), open_by.get(c.id, 0)
        out.append(d)
    return out


@router.post("")
def create(body: ClientIn, request: Request, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    c = Client()
    _apply(db, c, body)
    db.add(c)
    db.flush()
    audit.log(db, request, "client_create", "client", c.id, detail={"name": c.trade_name})
    db.commit()
    return _full(db, c)


@router.get("/{cid}")
def get(cid: int, db: Session = Depends(get_db), _=Depends(require("clients.view"))):
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    return _full(db, c)


@router.put("/{cid}")
def update(cid: int, body: ClientIn, request: Request, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    _apply(db, c, body)
    audit.log(db, request, "client_update", "client", c.id, detail={"name": c.trade_name})
    db.commit()
    return _full(db, c)


@router.delete("/{cid}")
def deactivate(cid: int, request: Request, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    c.status = "inativo"  # nunca apaga historico
    audit.log(db, request, "client_deactivate", "client", c.id)
    db.commit()
    return {"ok": True}


@router.post("/{cid}/logo")
def upload_logo(cid: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                _=Depends(require("clients.edit"))):
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".svg", ".webp"):
        raise HTTPException(422, "Formato inválido (use PNG, JPG, SVG ou WEBP)")
    dest_dir = Path(get_settings().NAVI_STORAGE) / "logos"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"client_{cid}{ext}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    c.logo_path = str(dest)
    audit.log(db, request, "client_logo", "client", c.id)
    db.commit()
    return {"ok": True}


def client_hosts(db: Session, c: Client) -> list[ZbxHost]:
    ids = {h.zbx_hostid for h in c.hosts}
    gids = {g.zbx_groupid for g in c.groups}
    return [h for h in db.scalars(select(ZbxHost).where(ZbxHost.active.is_(True)))
            if h.hostid in ids or (set(h.group_ids or []) & gids)]


@router.get("/{cid}/dashboard")
def dashboard(cid: int, days: int = 30, db: Session = Depends(get_db), _=Depends(require("clients.view"))):
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    days = max(1, min(days, 90))  # limite = retencao local de eventos
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    hosts = client_hosts(db, c)
    hids = [h.hostid for h in hosts]
    evs = list(db.scalars(select(Event).where(Event.client_id == cid, Event.started_at < end,
                                              (Event.recovered_at.is_(None)) | (Event.recovered_at > start))
                          .order_by(Event.started_at.desc())))
    k = kpi_service.compute(evs, [{"hostid": h.hostid, "name": h.name, "ip": h.ip} for h in hosts], start, end, c.sla_target)
    active = [to_dict(e) for e in evs if e.status == "PROBLEM"]
    links = [h for h in hosts if any(w in (h.name or "").lower() for w in ("link", "wan", "vpn", "fortigate", "fw"))]
    return {"client": to_dict(c), "kpis": k, "hosts": [{"hostid": h.hostid, "name": h.name, "ip": h.ip,
            "available": h.available, "status": h.status} for h in hosts], "active_events": active,
            "history": [to_dict(e) for e in evs[:100]], "links": len(links),
            "reports": [to_dict(r, {"kpis"}) for r in db.scalars(select(ReportRun).where(ReportRun.client_id == cid)
                                                                 .order_by(ReportRun.generated_at.desc()).limit(10))],
            "rules": [to_dict(r) for r in db.scalars(select(AlertRule).where(AlertRule.client_id == cid))]}
