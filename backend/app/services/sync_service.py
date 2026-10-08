"""Sincronizacao incremental e nao destrutiva: objetos que somem da API sao marcados active=False, nunca apagados."""
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import SyncRun, ZbxHost, ZbxHostGroup, ZbxItem, ZbxTrigger
from .zabbix_service import ZabbixService


def _ts(v):
    try:
        v = int(v)
        return datetime.fromtimestamp(v, tz=timezone.utc) if v > 0 else None
    except (TypeError, ValueError):
        return None


def _upsert(db: Session, model, pk_name: str, rows: list[dict]):
    existing = {getattr(o, pk_name): o for o in db.scalars(select(model).where(getattr(model, pk_name).in_([r[pk_name] for r in rows])))} if rows else {}
    for r in rows:
        o = existing.get(r[pk_name])
        if o is None:
            db.add(model(**r))
        else:
            for k, v in r.items():
                setattr(o, k, v)


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def sync_inventory(db: Session, z: ZabbixService, with_items: bool = False, trigger: str = "schedule") -> dict:
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
        seen = [g["groupid"] for g in groups]
        db.execute(update(ZbxHostGroup).where(ZbxHostGroup.groupid.notin_(seen)).values(active=False))
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
                "active": True, "synced_at": now})
        _upsert(db, ZbxHost, "hostid", rows)
        seen_h = [r["hostid"] for r in rows]
        db.execute(update(ZbxHost).where(ZbxHost.hostid.notin_(seen_h)).values(active=False))
        counts["hosts"] = len(rows)

        trigs = z.triggers()
        trows, tcount = [], {}
        for t in trigs:
            hid = (t.get("hosts") or [{}])[0].get("hostid")
            tcount[hid] = tcount.get(hid, 0) + 1
            trows.append({"triggerid": t["triggerid"], "description": t["description"][:1000],
                          "priority": int(t["priority"]), "status": int(t["status"]), "value": int(t["value"]),
                          "hostid": hid, "last_change": _ts(t.get("lastchange")), "active": True, "synced_at": now})
        for part in _chunks(trows, 2000):
            _upsert(db, ZbxTrigger, "triggerid", part)
        seen_t = [r["triggerid"] for r in trows]
        db.execute(update(ZbxTrigger).where(ZbxTrigger.triggerid.notin_(seen_t)).values(active=False))
        for hid, c in tcount.items():
            if hid:
                db.execute(update(ZbxHost).where(ZbxHost.hostid == hid).values(trigger_count=c))
        counts["triggers"] = len(trows)

        if with_items:
            items = z.items()
            irows, icount = [], {}
            for i in items:
                icount[i["hostid"]] = icount.get(i["hostid"], 0) + 1
                irows.append({"itemid": i["itemid"], "hostid": i["hostid"], "name": i["name"][:1000],
                              "key_": i["key_"][:1000], "status": int(i["status"]), "state": int(i.get("state") or 0),
                              "units": (i.get("units") or "")[:60], "lastvalue": (i.get("lastvalue") or "")[:250],
                              "lastclock": _ts(i.get("lastclock")), "active": True, "synced_at": now})
            for part in _chunks(irows, 2000):
                _upsert(db, ZbxItem, "itemid", part)
                db.flush()
            seen_i = {r["itemid"] for r in irows}
            gone = [x for x in db.scalars(select(ZbxItem.itemid).where(ZbxItem.active.is_(True))) if x not in seen_i]
            for part in _chunks(gone, 5000):
                db.execute(update(ZbxItem).where(ZbxItem.itemid.in_(part)).values(active=False))
            for hid, c in icount.items():
                db.execute(update(ZbxHost).where(ZbxHost.hostid == hid).values(item_count=c))
            counts["items"] = len(irows)
        run.status, run.counts = "ok", counts
    except Exception as e:  # noqa: BLE001
        db.rollback()
        run = db.get(SyncRun, run.id)
        run.status, run.error = "error", str(e)[:2000]
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    return counts
