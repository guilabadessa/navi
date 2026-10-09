"""Backup (Acronis) e endpoints (EMS): sincroniza tenants/maquinas e transforma problemas em eventos NAVI (kind=backup),
que passam pelo mesmo motor de alertas do Zabbix (regras, agrupamento, escalonamento, manutencao, modo sombra)."""
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import settings_store as S
from ..models import Client, Event, ExtAsset, ExtTenant
from . import event_service
from . import notification_service as N

log = logging.getLogger("navi.protection")
SRC = "acronis"
SEV = {"critical": 5, "error": 4, "warning": 2, "information": 1}
TEXT = {
    "BackupFailed": "Falha no backup",
    "BackupFinishedWithWarnings": "Backup concluído com avisos",
    "BackupCancelled": "Backup cancelado",
    "BackupMissed": "Backup não executado no horário",
    "BackupDidNotStart": "Backup não iniciou",
    "ActiveProtectionServiceNotRunning": "Serviço de proteção ativa parado",
    "MalwareDetected": "Malware detectado",
    "AgentOffline": "Agente offline",
    "LicenseExpired": "Licença expirada",
    "QuotaExceeded": "Cota de armazenamento excedida",
}


def human_type(t: str | None) -> str:
    if not t:
        return "Alerta do Acronis"
    if t in TEXT:
        return TEXT[t]
    return re.sub(r"(?<!^)(?=[A-Z])", " ", t).strip()  # camelCase -> palavras


def cfg(db: Session) -> dict:
    return {"ems_offline_days": int(S.get(db, "protection.ems_offline_days") or 7), "stale_h": int(S.get(db, "protection.stale_h") or 72), "offline_min": int(S.get(db, "protection.offline_min") or 240),
            "acronis_enabled": (S.get(db, "protection.acronis_enabled") or "1") == "1"}


def _dt(v) -> datetime | None:
    if not v:
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc)
    t = re.sub(r"(\.\d{6})\d+", r"\1", str(v).replace("Z", "+00:00"))
    d = datetime.fromisoformat(t)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ---------------- tenants ----------------
def sync_tenants(db: Session, svc, dc: str = "br") -> tuple[dict, dict]:
    tree = svc.tenant_tree()
    by_id = {t["id"]: t for t in tree}

    def customer(t):
        seen = 0
        while t and t.get("kind") != "customer" and seen < 12:
            t, seen = by_id.get(t.get("parent_id")), seen + 1
        return t if t and t.get("kind") == "customer" else None

    existing = {x.ext_id: x for x in db.scalars(select(ExtTenant).where(ExtTenant.source == SRC))}
    now = datetime.now(timezone.utc)
    seen_ids = set()
    for t in tree:
        if t.get("kind") != "customer":
            continue
        x = existing.get(t["id"]) or ExtTenant(source=SRC, ext_id=t["id"], name=t["name"])
        x.name, x.kind, x.enabled, x.active, x.synced_at = t["name"], "customer", bool(t.get("enabled", True)), True, now
        x.info = {**(x.info or {}), "dc": dc}
        if x.id is None:
            db.add(x)
            existing[t["id"]] = x
        seen_ids.add(t["id"])
    for k, x in existing.items():
        if k not in seen_ids and (x.info or {}).get("dc", "br") == dc:  # so desativa os tenants deste datacenter
            x.active = False
    db.flush()
    by_uuid, by_name = {}, {}
    for t in tree:
        c = customer(t)
        if c and c["id"] in existing:
            by_uuid[t["id"]] = existing[c["id"]]
            by_name[(t.get("name") or "").strip().lower()] = existing[c["id"]]
    return by_uuid, by_name


# ---------------- servicos contratados (licencas/uso) ----------------
# (fragmento do nome do item, rotulo, grupo). A ordem importa: o primeiro que casar vale.
CATALOG = [
    ("pack_adv_security_awareness", "Treinamento de conscientização em segurança", "Segurança"),
    ("pack_adv_security_m365", "Advanced Security — Microsoft 365", "Segurança"),
    ("pack_adv_security", "Advanced Security (antimalware + EDR)", "Segurança"),
    ("pack_adv_email_security_m365", "Advanced Email Security — apps Microsoft 365", "E-mail"),
    ("pack_adv_email_security", "Advanced Email Security", "E-mail"),
    ("pack_adv_management_m365", "Advanced Management — Microsoft 365", "Gerenciamento"),
    ("pack_adv_management", "Advanced Management (RMM, patch, inventário)", "Gerenciamento"),
    ("pack_adv_dlp", "Advanced DLP (prevenção de vazamento de dados)", "DLP"),
    ("pack_adv_backup_m365", "Advanced Backup — Microsoft 365", "Backup"),
    ("pack_adv_backup_gworkspace", "Advanced Backup — Google Workspace", "Backup"),
    ("pack_adv_backup_workstations", "Advanced Backup — estações", "Backup"),
    ("pack_adv_backup_servers", "Advanced Backup — servidores", "Backup"),
    ("pack_adv_backup_vms", "Advanced Backup — VMs", "Backup"),
    ("pack_adv_dr_azure", "Disaster Recovery (Azure)", "Continuidade"),
    ("m365_email_archiving", "Arquivamento de e-mail Microsoft 365", "E-mail"),
    ("m365_sharepoint_sites", "Backup de SharePoint (sites)", "Backup"),
    ("m365_teams", "Backup do Microsoft Teams", "Backup"),
    ("m365_seats", "Backup de caixas Microsoft 365", "Backup"),
    ("gworkspace_seats", "Backup do Google Workspace", "Backup"),
    ("hosted_exchange", "Backup de Exchange hospedado", "Backup"),
    ("web_hosting_servers", "Backup de servidores de hospedagem web", "Backup"),
    ("_workstations", "Backup de estações de trabalho", "Backup"),
    ("_servers", "Backup de servidores", "Backup"),
    ("_vms", "Backup de máquinas virtuais", "Backup"),
    ("_mobiles", "Backup de dispositivos móveis", "Backup"),
    ("_nas", "Backup de NAS", "Backup"),
    ("adv_dr_", "Disaster Recovery", "Continuidade"),
]
_SKIP = ("fc_seats", "secondary", "archiving_storage", "c2c_storage", "fc_storage", "fc_notarizations", "fc_esignatures", "drives_shipped", "local_storage", "public_ips", "compute_points", "cloud_servers", "dr_storage", "ms_powered")


def contracted_services(usages: list[dict]) -> list[dict]:
    """Itens realmente contratados (cota definida ou em uso), com nome claro. Itens padrao do parceiro com cota/uso zero ficam de fora."""
    out, seen = [], set()
    for u in usages:
        name = u.get("name") or ""
        if any(s in name for s in _SKIP) or name.endswith("_storage"):
            continue
        quota = ((u.get("offering_item") or {}).get("quota") or {}).get("value")
        val = u.get("value") or 0
        if (u.get("offering_item") or {}).get("status") != 1:
            continue
        if not (quota is not None or val > 0):
            continue
        for frag, label, group in CATALOG:
            if frag in name:
                if label in seen:
                    break
                seen.add(label)
                out.append({"key": name, "label": label, "group": group, "used": val, "quota": quota, "unit": u.get("measurement_unit") or "quantity"})
                break
    return out


def sync_usages(db: Session, svc, tenants: list[ExtTenant]):
    """Atualiza ext_tenants.info (servicos contratados). Falha aqui nao impede o restante da sincronizacao."""
    try:
        by_id = {t.ext_id: t for t in tenants}
        for it in svc.usages(list(by_id)):
            t = by_id.get(it.get("tenant"))
            if t is not None:
                t.info = {**(t.info or {}), "services": contracted_services(it.get("usages") or []), "updated": datetime.now(timezone.utc).isoformat()}
        db.flush()
    except Exception as e:  # noqa: BLE001
        log.warning("acronis: servicos contratados indisponiveis: %s", e)


def license_flags(t: ExtTenant | None) -> dict:
    labels = {s["label"] for s in ((t.info or {}).get("services") or [])} if t else set()
    has = lambda *k: any(any(x in l for x in k) for l in labels)  # noqa: E731
    return {"security": has("Advanced Security"), "management": has("Advanced Management"), "dlp": has("DLP"), "email": has("Email Security")}


UNIT_TECH = {"content-analyzer-edr": "EDR", "dlp-unit": "DLP", "active_protection": "Antimalware", "cyber-scripting-executor": "RMM", "remote-shell-agent": "RMM"}


def device_techs(units: list[str], flags: dict) -> list[str]:
    """Tecnologias efetivamente ativas no equipamento: unidade instalada no agente E licenca contratada pelo cliente."""
    need = {"EDR": "security", "Antimalware": "security", "DLP": "dlp", "RMM": "management"}
    out = []
    for u in units:
        t = UNIT_TECH.get(u)
        if t and flags.get(need[t]) and t not in out:
            out.append(t)
    return out


# ---------------- ativos e atividades ----------------
def _asset(db: Session, cache: dict, ext_id: str, name: str, typ: str, tenant: ExtTenant | None) -> ExtAsset:
    ext_id = ext_id.lower()
    a = cache.get(ext_id)
    if a is None:
        a = ExtAsset(source=SRC, ext_id=ext_id, name=name, type=typ)
        db.add(a)
        cache[ext_id] = a
    a.name, a.type, a.active = name or a.name, typ or a.type, True
    if tenant is not None:
        a.ext_tenant_id = tenant.id
    a.last_seen_at = datetime.now(timezone.utc)
    return a


def sync_assets(db: Session, svc, by_uuid: dict, by_name: dict, dc: str = "br"):
    cache = {a.ext_id: a for a in db.scalars(select(ExtAsset).where(ExtAsset.source == SRC))}
    agents = {a["id"]: a for a in svc.agents()}
    now = datetime.now(timezone.utc)
    cfg_ = cfg(db)
    tflags = {t.id: license_flags(t) for t in db.scalars(select(ExtTenant).where(ExtTenant.source == SRC))}
    for r in svc.resources("resource.machine"):
        tn = by_name.get((r.get("tenant_name") or "").strip().lower())
        a = _asset(db, cache, r["id"], r.get("user_defined_name") or r.get("name") or r["id"], "machine", tn)
        ag = agents.get(r.get("agent_id"))
        if ag is not None:
            units = [u.get("name") for u in ag.get("units") or []]
            a.meta = {**(a.meta or {}), "dc": dc, "techs": device_techs(units, tflags.get(a.ext_tenant_id or (tn.id if tn else None), {})),
                      "agent_version": ((ag.get("core_version") or {}).get("current") or {}).get("release_id"), "hostname": ag.get("hostname")}
            if a.ext_tenant_id is None:
                t2 = by_name.get(((ag.get("tenant") or {}).get("name") or "").strip().lower())
                a.ext_tenant_id = t2.id if t2 else None
            online = bool(ag.get("online")) if ag.get("enabled", True) else None
            if online is False and a.online is not False:
                a.offline_since = now
            if online is not False:
                a.offline_since = None
            a.online = online
    # atividades de backup: ultimo sucesso/falha por recurso
    ckey = "acronis.activity_cursor" + ("" if dc == "br" else "." + dc)
    cur = S.get(db, ckey)
    since = (_dt(cur) - timedelta(minutes=30)) if cur else now - timedelta(days=8)
    started = now
    by_name_asset = {}
    for x in cache.values():
        if x.type == "machine":
            by_name_asset.setdefault((x.name or "").strip().lower(), x)
    for act in svc.backup_activities(since):
        res = act["resource"]
        t = by_uuid.get(((act.get("tenant") or {}).get("uuid")) or "")
        rtype = (res.get("type") or "resource").lower()
        a = by_name_asset.get((res.get("name") or "").strip().lower()) if rtype == "instance" else None  # "instance" = a propria maquina
        if a is None:
            nm = res.get("name") or res["id"]
            mach = (act.get("context") or {}).get("MachineName")
            if rtype == "instance":  # instancia que nao e uma maquina registrada = banco de dados (SQL etc.)
                rtype = "database"
                if mach and mach.lower() not in nm.lower():
                    nm = f"{nm} ({mach})"
            a = _asset(db, cache, res["id"], nm, rtype, t)
        a.policy_name = (act.get("policy") or {}).get("name") or a.policy_name
        if (act.get("policy") or {}).get("id"):
            a.meta = {**(a.meta or {}), "policy_id": act["policy"]["id"], "dc": dc}
        if act.get("state") != "completed":
            continue
        done = _dt(act.get("completedAt")) or _dt(act.get("startedAt"))
        code = ((act.get("result") or {}).get("code") or "").lower()
        a.last_result = code
        if code in ("ok", "warning", "warnings"):
            if not a.last_success_at or done > a.last_success_at:
                a.last_success_at = done
        elif not a.last_failure_at or done > a.last_failure_at:
            a.last_failure_at = done
    S.put(db, ckey, started.isoformat())
    db.flush()
    return cache


# ---------------- eventos ----------------
def _desired(db: Session, svc, cache: dict, by_uuid: dict, by_name: dict) -> dict[str, dict]:
    now = datetime.now(timezone.utc)
    c = cfg(db)
    tenants = {t.id: t for t in db.scalars(select(ExtTenant).where(ExtTenant.source == SRC))}
    out: dict[str, dict] = {}
    for al in svc.alerts():
        det = al.get("details") or {}
        rid = (det.get("resourceId") or "").lower()
        a = cache.get(rid)
        ten = tenants.get(a.ext_tenant_id) if a else None
        out[f"alert:{al['id']}"] = {
            "host": det.get("resourceName") or (a.name if a else "—"), "hostid": rid or None, "tenant": ten,
            "triggerid": al.get("type"), "trigger_name": human_type(al.get("type")), "item_name": det.get("planName"),
            "severity": SEV.get((al.get("severity") or "").lower(), 3), "started_at": _dt(al.get("createdAt")) or now,
            "opdata": ("Plano: " + det["planName"]) if det.get("planName") else None, "type": al.get("type")}
    for a in cache.values():
        if not a.active or a.ignored:
            continue
        ten = tenants.get(a.ext_tenant_id)
        last_ok = a.last_success_at
        if last_ok and (now - last_ok) > timedelta(hours=c["stale_h"]):
            h = int((now - last_ok).total_seconds() // 3600)
            out[f"stale:{a.ext_id}"] = {"host": a.name, "hostid": a.ext_id, "tenant": ten, "triggerid": "NoRecentBackup",
                                        "trigger_name": f"Sem backup bem-sucedido há {h // 24}d {h % 24}h" if h >= 48 else f"Sem backup bem-sucedido há {h}h",
                                        "item_name": a.policy_name, "severity": 4, "started_at": now, "type": "NoRecentBackup",
                                        "opdata": f"Último sucesso: {last_ok.astimezone().strftime('%d/%m/%Y %H:%M')}"}
        if a.online is False and a.offline_since and (now - a.offline_since) > timedelta(minutes=c["offline_min"]):
            out[f"offline:{a.ext_id}"] = {"host": a.name, "hostid": a.ext_id, "tenant": ten, "triggerid": "AgentOffline",
                                          "trigger_name": "Agente de backup offline", "item_name": a.policy_name, "severity": 3,
                                          "started_at": a.offline_since, "type": "AgentOffline",
                                          "opdata": f"Offline desde {a.offline_since.astimezone().strftime('%d/%m/%Y %H:%M')}"}
    return out


def reconcile(db: Session, desired: dict[str, dict], source: str = SRC, kind: str = "backup", origin: str = "Acronis") -> dict:
    now = datetime.now(timezone.utc)
    stats = {"new": 0, "resolved": 0, "open": 0}
    open_evs = {e.zbx_eventid: e for e in db.scalars(select(Event).where(Event.kind == kind, Event.source == source, Event.status == "PROBLEM"))}
    for key, d in desired.items():
        eid = f"{source}:{key}"
        ten: ExtTenant | None = d["tenant"]
        ev = open_evs.get(eid) or db.scalar(select(Event).where(Event.zbx_eventid == eid))
        if ev is None:
            ev = Event(zbx_eventid=eid, status="PROBLEM", started_at=d["started_at"], kind=kind, source=source)
            db.add(ev)
            created = True
        else:
            created = False
            if ev.status == "RESOLVED":  # voltou a ocorrer: reabre como novo ciclo
                ev.status, ev.recovered_at, ev.duration_s, ev.started_at, created = "PROBLEM", None, None, d["started_at"], True
        ev.hostid, ev.host, ev.triggerid, ev.trigger_name = d["hostid"], d["host"], d["triggerid"], d["trigger_name"]
        ev.item_name, ev.opdata, ev.severity = d.get("item_name"), d.get("opdata"), d["severity"]
        ev.group_ids, ev.group_names = ([ten.ext_id] if ten else []), ([ten.name] if ten else [])
        ev.client_id = ten.client_id if ten else None
        ev.tags = [{"tag": "origem", "value": origin}, {"tag": "tipo", "value": d.get("type") or ""}]
        db.flush()
        stats["open"] += 1
        if created:
            stats["new"] += 1
            from ..models import SEVERITIES  # noqa: F401
            if (now - ev.started_at) <= event_service.ALERT_WINDOW:
                N.plan_problem(db, ev)
    for eid, ev in open_evs.items():
        if eid.split(":", 1)[1] not in desired:
            if event_service.mark_resolved(db, ev, now):
                stats["resolved"] += 1
    db.commit()
    return stats


def relink(db: Session) -> int:
    """Reaplica a associacao tenant -> cliente aos eventos de backup/endpoint (apos mapear um tenant)."""
    tmap = {(t.source, t.ext_id): t.client_id for t in db.scalars(select(ExtTenant))}
    n = 0
    for ev in db.scalars(select(Event).where(Event.kind.in_(("backup", "endpoint")))):
        cid = tmap.get((ev.source, (ev.group_ids or [None])[0]))
        if cid != ev.client_id:
            ev.client_id, n = cid, n + 1
    db.commit()
    return n


def sync_acronis(db: Session) -> dict:
    """Sincroniza todos os datacenters do Acronis configurados (ex.: Brasil e Phoenix/EUA) em uma unica rodada de alertas."""
    from . import factory
    if not cfg(db)["acronis_enabled"]:
        return {"skipped": True}
    accounts = factory.acronis_all(db)
    if not accounts:
        return {"skipped": True}
    desired, total_assets, total_tenants = {}, 0, 0
    for dc, sv in accounts:
        by_uuid, by_name = sync_tenants(db, sv, dc)
        sync_usages(db, sv, list({t.id: t for t in by_uuid.values()}.values()))
        cache = sync_assets(db, sv, by_uuid, by_name, dc)
        db.commit()
        desired.update(_desired(db, sv, cache, by_uuid, by_name))
        total_assets, total_tenants = len(cache), total_tenants + len(by_uuid)
    stats = reconcile(db, desired)
    relink(db)
    return {**stats, "assets": total_assets, "tenants": total_tenants, "datacenters": [dc for dc, _ in accounts]}


# ======================= FortiClient EMS (endpoints) =======================
EMS = "ems"


def ems_status(a: ExtAsset, offline_days: int, now: datetime) -> str:
    m = a.meta or {}
    if a.ignored:
        return "ignorado"
    if m.get("quarantined"):
        return "quarentena"
    last = a.last_success_at  # ultimo contato com o EMS
    if a.online is False and last and (now - last) > timedelta(days=offline_days):
        return "sem contato"
    if a.online and m.get("av_enabled") is False:
        return "antivírus off"
    if a.online and m.get("sig_ok") is False and m.get("av_enabled"):
        return "assinaturas"
    if (m.get("health_errors") or 0) > 0:
        return "atenção"
    return "online" if a.online else "offline"


def sync_ems(db: Session, svc) -> dict:
    if not svc.configured or S.get(db, "ems.enabled") != "1":
        return {"skipped": True}
    if S.get(db, "ems.auth_blocked") == "1":
        return {"skipped": True, "blocked": True}
    from ..models import HealthCheck
    now = datetime.now(timezone.utc)
    off_days = cfg(db)["ems_offline_days"]
    try:
        sites = svc.sites()
        tenants = {t.ext_id: t for t in db.scalars(select(ExtTenant).where(ExtTenant.source == EMS))}
        for name in sites:
            t = tenants.get(name) or ExtTenant(source=EMS, ext_id=name, name=name, kind="site")
            t.name, t.active, t.synced_at = name, True, now
            if t.id is None:
                db.add(t)
                tenants[name] = t
        for k, t in tenants.items():
            if k not in sites:
                t.active = False
        db.flush()
        cache = {a.ext_id: a for a in db.scalars(select(ExtAsset).where(ExtAsset.source == EMS))}
        seen = set()
        for site in sites:
            for e in svc.endpoints(site):
                uid = str(e.get("uid") or f"{site}:{e.get('device_id')}")
                a = cache.get(uid)
                if a is None:
                    a = ExtAsset(source=EMS, ext_id=uid, name=e.get("name") or uid, type="endpoint")
                    db.add(a)
                    cache[uid] = a
                a.name, a.active, a.ext_tenant_id, a.last_seen_at = e.get("name") or e.get("host") or uid, True, tenants[site].id, now
                a.policy_name = e.get("endpoint_policy_name")
                online = bool(e.get("is_ems_online"))
                if not online and a.online is not False:
                    a.offline_since = now
                if online:
                    a.offline_since = None
                a.online = online
                a.last_success_at = _dt(e.get("last_seen")) or a.last_success_at
                users = [u.get("machine_user_name") or u.get("auth_user_name") for u in (e.get("fct_users") or [])]
                a.meta = {"av_enabled": e.get("av_enabled"), "sig_ok": e.get("client_av_sig_version_up_to_date"), "version_ok": e.get("client_version_up_to_date"),
                          "quarantined": bool(e.get("is_quarantined")), "health_errors": e.get("health_error_count") or 0,
                          "health_warnings": e.get("health_warning_count") or 0, "fct_version": e.get("fct_version"), "os": e.get("os_version"),
                          "user": next((u for u in users if u), None), "ip": e.get("ip_addr"), "managed": bool(e.get("is_managed", True))}
                seen.add(uid)
        for uid, a in cache.items():
            if uid not in seen:
                a.active = False
        db.flush()
        desired: dict[str, dict] = {}
        for a in cache.values():
            if not a.active or a.ignored:
                continue
            ten = db.get(ExtTenant, a.ext_tenant_id)
            m, base = a.meta or {}, {"host": a.name, "hostid": a.ext_id, "tenant": ten, "item_name": a.policy_name, "started_at": now}
            if m.get("quarantined"):
                desired[f"quarantine:{a.ext_id}"] = {**base, "triggerid": "Quarantined", "trigger_name": "Endpoint em quarentena", "severity": 4, "type": "Quarantined",
                                                     "opdata": f"Usuário: {m.get('user') or '—'}"}
            if a.online is False and a.last_success_at and (now - a.last_success_at) > timedelta(days=off_days):
                d = (now - a.last_success_at).days
                desired[f"offline:{a.ext_id}"] = {**base, "triggerid": "NoContact", "trigger_name": f"Endpoint sem contato com o EMS há {d} dias", "severity": 2, "type": "NoContact",
                                                  "started_at": a.last_success_at + timedelta(days=off_days), "opdata": f"Último contato: {a.last_success_at.astimezone().strftime('%d/%m/%Y %H:%M')}"}
            if a.online and m.get("av_enabled") is False:
                desired[f"av_off:{a.ext_id}"] = {**base, "triggerid": "AvDisabled", "trigger_name": "Antivírus (FortiClient) desativado", "severity": 3, "type": "AvDisabled",
                                                 "opdata": f"Usuário: {m.get('user') or '—'}"}
            if a.online and m.get("av_enabled") and m.get("sig_ok") is False:
                desired[f"sig:{a.ext_id}"] = {**base, "triggerid": "AvSignatures", "trigger_name": "Assinaturas do antivírus desatualizadas", "severity": 2, "type": "AvSignatures",
                                              "opdata": f"FortiClient {m.get('fct_version') or ''}"}
            if (m.get("health_errors") or 0) > 0:
                desired[f"health:{a.ext_id}"] = {**base, "triggerid": "HealthError", "trigger_name": f"Erros de saúde no FortiClient ({m['health_errors']})", "severity": 2, "type": "HealthError"}
        stats = reconcile(db, desired, source=EMS, kind="endpoint", origin="FortiClient EMS")
        relink(db)
        h = db.get(HealthCheck, "ems") or HealthCheck(name="ems")
        h.ok, h.detail, h.checked_at = True, f"EMS · {len(seen)} endpoint(s) em {len(sites)} site(s)", now
        db.merge(h)
        db.commit()
        return {**stats, "endpoints": len(seen), "sites": len(sites)}
    except Exception as e:  # noqa: BLE001
        db.rollback()
        from .ems_service import EmsAuthError
        if isinstance(e, EmsAuthError):  # nao repete login que falhou (evita bloquear a conta no EMS)
            S.put(db, "ems.auth_blocked", "1")
        h = db.get(HealthCheck, "ems") or HealthCheck(name="ems")
        h.ok, h.detail, h.checked_at = False, str(e)[:300], now
        db.merge(h)
        db.commit()
        raise


# ======================= Endpoints (EMS + dispositivos protegidos pelo Acronis) =======================
def endpoint_rows(db: Session, client_id: int) -> list[dict]:
    """Endpoints do cliente, venham do FortiClient EMS ou do Acronis (EDR/antimalware/DLP/RMM). Mesmo formato para portal, relatorio e telas."""
    from ..routers.protection import asset_status
    now, c = datetime.now(timezone.utc), cfg(db)
    rows = []
    tens = list(db.scalars(select(ExtTenant).where(ExtTenant.client_id == client_id, ExtTenant.active.is_(True))))
    ems_ids = [t.id for t in tens if t.source == EMS]
    ac = {t.id: t for t in tens if t.source == SRC}
    if ems_ids:
        for a in db.scalars(select(ExtAsset).where(ExtAsset.ext_tenant_id.in_(ems_ids), ExtAsset.active.is_(True), ExtAsset.ignored.is_(False)).order_by(ExtAsset.name)):
            m, st = a.meta or {}, ems_status(a, c["ems_offline_days"], now)
            rows.append({"id": a.id, "name": a.name, "user": m.get("user"), "os": m.get("os"), "source": "FortiClient EMS", "techs": ["Antivírus (FortiClient)"],
                         "status": st, "ok": st in ("online", "offline"), "last": a.last_success_at, "av_enabled": m.get("av_enabled"), "sig_ok": m.get("sig_ok")})
    flagged = {tid for tid, t in ac.items() if any(license_flags(t)[k] for k in ("security", "management", "dlp"))}
    if flagged:
        for a in db.scalars(select(ExtAsset).where(ExtAsset.ext_tenant_id.in_(list(flagged)), ExtAsset.type == "machine", ExtAsset.active.is_(True), ExtAsset.ignored.is_(False)).order_by(ExtAsset.name)):
            techs = (a.meta or {}).get("techs") or []
            if not techs:
                continue
            st = "sem contato" if asset_status(a, c, now) == "offline" else ("online" if a.online else "offline")
            rows.append({"id": a.id, "name": a.name, "user": (a.meta or {}).get("hostname"), "os": None, "source": "Acronis", "techs": techs, "status": st,
                         "ok": st in ("online", "offline"), "last": a.last_success_at, "av_enabled": None, "sig_ok": None})
    return rows
