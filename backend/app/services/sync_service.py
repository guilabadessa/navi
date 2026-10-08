"""Sincronizacao espelho: grupos e hosts do Zabbix. Itens/triggers NAO sao armazenados (consulta ao vivo via API).
Objetos que deixam de existir no Zabbix sao removidos aqui tambem."""
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import SyncRun, ZbxHost, ZbxHostGroup
from .zabbix_service import ZabbixService


def _upsert(db: Session, model, pk_name: str, rows: list[dict]):
    existing = {getattr(o, pk_name): o for o in db.scalars(select(model))}
    for r in rows:
        o = existing.get(r[pk_name])
        if o is None:
            db.add(model(**r))
        else:
            for k, v in r.items():
                setattr(o, k, v)


def sync_inventory(db: Session, z: ZabbixService, trigger: str = "schedule") -> dict:
    run = SyncRun(trigger=trigger)
    db.add(run)
    db.commit()
    now = datetime.now(timezone.utc)
    counts = {}
    try:
        groups = z.host_groups()
        _upsert(db, ZbxHostGroup, "groupid", [{
            "groupid": g["groupid"], "name": g["name"], "host_count": int(g.get("hosts") or 0), "active": True,
            "synced_at": now} for g in groups])
        seen_g = [g["groupid"] for g in groups]
        removed_g = db.execute(delete(ZbxHostGroup).where(ZbxHostGroup.groupid.notin_(seen_g))).rowcount
        counts["host_groups"] = len(groups)

        hosts = z.hosts()
        rows = []
        for h in hosts:
            ifs = h.get("interfaces") or []
            main = next((i for i in ifs if str(i.get("main")) == "1"), ifs[0] if ifs else {})
            avail = [int(i.get("available") or 0) for i in ifs]
            a = 2 if 2 in avail else (1 if 1 in avail else 0)
            rows.append({
                "hostid": h["hostid"], "host": h["host"], "name": h.get("name") or h["host"],
                "status": int(h.get("status") or 0), "ip": main.get("ip") or None, "dns": main.get("dns") or None,
                "available": a, "interfaces": ifs, "group_ids": [g["groupid"] for g in h.get("hostgroups", [])],
                "templates": [t["name"] for t in h.get("parentTemplates", [])], "tags": h.get("tags", []),
                "item_count": int(h.get("items") or 0), "trigger_count": int(h.get("triggers") or 0),
                "active": True, "synced_at": now})
        _upsert(db, ZbxHost, "hostid", rows)
        seen_h = [r["hostid"] for r in rows]
        removed_h = db.execute(delete(ZbxHost).where(ZbxHost.hostid.notin_(seen_h))).rowcount
        counts["hosts"] = len(rows)
        counts["removidos"] = {"hosts": removed_h, "host_groups": removed_g}
        run.status, run.counts = "ok", counts
        db.flush()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        run = db.get(SyncRun, run.id)
        run.status, run.error = "error", str(e)[:2000]
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    from . import event_service
    counts["eventos_reassociados"] = event_service.relink_events(db)
    return counts
