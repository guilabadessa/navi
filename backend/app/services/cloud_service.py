"""Cloud Orca (BRASCLOUD / plataforma 4bdigital): consulta e energia das maquinas virtuais de UM cliente.
Autenticacao por cabecalhos `apikey` + `secretkey` da conta do cliente. Ligar/desligar sao chamadas GET da propria API,
por isso so sao feitas pelas funcoes `power` (nunca nas consultas)."""
import threading
import time

import httpx
from sqlalchemy.orm import Session

from .. import settings_store as S
from ..models import CloudAccount
from ..security import decrypt

DEFAULT_URL = "https://cloud02.orcati.com.br"


class CloudError(RuntimeError):
    pass


def base_url(db: Session) -> str:
    return (S.get(db, "cloud.url") or DEFAULT_URL).rstrip("/")


class Cloud:
    def __init__(self, base: str, api_key: str, secret: str):
        self.base = base
        self.http = httpx.Client(timeout=45, headers={"apikey": api_key, "secretkey": secret, "Accept": "application/json", "User-Agent": "NAVI/1.0"})

    @classmethod
    def for_account(cls, db: Session, acc: CloudAccount) -> "Cloud":
        return cls(base_url(db), decrypt(acc.api_key), decrypt(acc.secret_key))

    def get(self, path: str, **params):
        try:
            r = self.http.get(f"{self.base}{path}", params={k: v for k, v in params.items() if v is not None})
        except httpx.HTTPError as e:
            raise CloudError(f"Sem conexão com a nuvem: {e.__class__.__name__}") from None
        if r.status_code == 550 or r.status_code == 401:
            raise CloudError("A nuvem recusou a chave de API (confira a chave, o segredo e se o IP do servidor da NAVI está liberado).")
        if r.status_code != 200:
            raise CloudError(f"{path}: HTTP {r.status_code} {r.text[:160]}")
        try:
            return r.json()
        except ValueError:
            raise CloudError(f"{path}: resposta inválida") from None

    # ---- consultas (somente leitura) ----
    def zones(self) -> list[dict]:
        return self.get("/restapi/zone/zonelist").get("listZoneResponse") or []

    def instances(self) -> list[dict]:
        out = []
        for z in self.zones():
            for v in self.get("/restapi/instance/instanceList", zoneUuid=z["uuid"]).get("listInstanceResponse") or []:
                out.append(_vm(v, z.get("name")))
        return out

    def quotas(self) -> list[dict]:
        rows = self.get("/restapi/resource-quota/get-resource-limit").get("listResourceQuotaResponse") or []
        out = []
        for q in rows:
            mx, used, unit = q.get("maximumLimit"), q.get("usedLimit") or 0, (q.get("unitType") or "")
            if not mx or mx < 0:
                continue
            if unit.lower() == "gib" and used > mx * 1024:  # a nuvem informa o uso em bytes e o limite em GB: tudo em GB
                used = round(used / 1024 ** 3)
            out.append({"type": q.get("quotaType"), "used": used, "max": mx, "unit": "gb" if unit.lower() == "gib" else ("mb" if unit == "MB" else None)})
        return out

    def status(self, uuid: str) -> str:
        d = self.get("/restapi/instance/vmStatus", uuid=uuid)
        return str(d.get("state") or d.get("status") or d.get("vmState") or "").upper() if isinstance(d, dict) else ""

    # ---- energia (acoes) ----
    def power(self, action: str, uuid: str):
        if action == "start":
            return self.get("/restapi/instance/startInstance", uuid=uuid)
        if action == "stop":
            return self.get("/restapi/instance/stopInstance", uuid=uuid, forceStop="false")
        if action == "force-stop":
            return self.get("/restapi/instance/stopInstance", uuid=uuid, forceStop="true")
        raise CloudError("Ação inválida")


def _vm(v: dict, zone: str | None) -> dict:
    ram = int(v.get("memory") or 0)
    vol = v.get("volumeSize")
    return {"uuid": v["uuid"], "name": v.get("displayName") or v.get("name"), "state": (v.get("state") or v.get("status") or "").upper(), "zone": zone, "zone_uuid": v.get("zoneUuid"),
            "cpu": int(v.get("cpuCore") or 0), "ram_mb": ram, "disk_gb": round(int(vol) / 1024 ** 3) if vol else v.get("rootDiskSize"), "root_gb": v.get("rootDiskSize"),
            "ip": v.get("instancePrivateIp"), "network": v.get("networkName"), "os": v.get("templateName"), "owner": v.get("instanceOwnerName")}


# Reinicio = desligar, esperar parar e ligar. Roda em segundo plano; o estado fica em memoria para a tela acompanhar.
_reboots: dict[str, dict] = {}
_lock = threading.Lock()


def reboot_state(uuid: str) -> dict | None:
    with _lock:
        s = _reboots.get(uuid)
        return dict(s) if s else None


def reboot(cloud: Cloud, uuid: str):
    with _lock:
        if _reboots.get(uuid, {}).get("phase") in ("parando", "ligando"):
            return
        _reboots[uuid] = {"phase": "parando", "since": time.time()}
    try:
        cloud.power("stop", uuid)
        for _ in range(45):  # ate ~3 min
            time.sleep(4)
            if cloud.status(uuid) in ("STOPPED", "SHUTOFF"):
                break
        else:
            raise CloudError("A máquina não desligou a tempo (use Desligar forçado e ligue em seguida).")
        with _lock:
            _reboots[uuid]["phase"] = "ligando"
        cloud.power("start", uuid)
        with _lock:
            _reboots[uuid] = {"phase": "concluído", "since": time.time()}
    except Exception as e:  # noqa: BLE001
        with _lock:
            _reboots[uuid] = {"phase": "erro", "error": str(e)[:200], "since": time.time()}


# ======================= sincronizacao (worker) =======================
OFF_STATES = ("STOPPED", "SHUTOFF", "ERROR", "DESTROYED")


def sync_all(db: Session) -> dict:
    """Atualiza as maquinas de todas as contas ativas, detecta mudancas de estado e abre/fecha incidentes (kind="cloud")
    pelo mesmo motor de alertas das demais origens. Maquinas desligadas pela NAVI (ou ignoradas) nao geram alerta."""
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace as NS

    from sqlalchemy import select

    from ..models import Client, CloudAccount, CloudVm
    from . import protection_service as P
    now = datetime.now(timezone.utc)
    stats = {"accounts": 0, "vms": 0, "errors": 0}
    names = dict(db.execute(select(Client.id, Client.trade_name)).all())
    desired: dict[str, dict] = {}
    for acc in db.scalars(select(CloudAccount).where(CloudAccount.enabled.is_(True))):
        stats["accounts"] += 1
        tenant = NS(ext_id=f"cloud:{acc.client_id}", name="Cloud Orca", client_id=acc.client_id)
        try:
            vms = Cloud.for_account(db, acc).instances()
            acc.last_ok, acc.last_error, acc.fails = now, None, 0
        except CloudError as e:
            acc.fails, acc.last_error = (acc.fails or 0) + 1, str(e)[:500]
            stats["errors"] += 1
            if acc.fails >= 3:  # so alerta depois de 3 falhas seguidas (evita oscilacao)
                desired[f"api:{acc.client_id}"] = {"host": "Cloud Orca", "hostid": f"cloud-api-{acc.client_id}", "tenant": tenant, "triggerid": "CloudApi", "trigger_name": "Cloud Orca inacessível pela NAVI",
                                                   "item_name": None, "severity": 3, "started_at": acc.last_ok or now, "type": "CloudApi", "opdata": acc.last_error[:200]}
            continue
        have = {v.uuid: v for v in db.scalars(select(CloudVm).where(CloudVm.client_id == acc.client_id))}
        seen = set()
        for v in vms:
            row = have.get(v["uuid"]) or CloudVm(uuid=v["uuid"], client_id=acc.client_id, state_since=now)
            if row.state != v["state"]:
                row.state_since = now if row.id else (row.state_since or now)
                if v["state"] == "RUNNING":
                    row.expected_off = False
            row.name, row.state, row.zone, row.cpu, row.ram_mb, row.disk_gb = v["name"], v["state"], v["zone"], v["cpu"], v["ram_mb"], v["disk_gb"]
            row.ip, row.os, row.network, row.last_seen, row.active = v["ip"], v["os"], v["network"], now, True
            db.add(row)
            seen.add(v["uuid"])
            stats["vms"] += 1
        for u, row in have.items():
            if u not in seen:
                row.active = False
        db.flush()
        for row in db.scalars(select(CloudVm).where(CloudVm.client_id == acc.client_id, CloudVm.active.is_(True))):
            if row.state in OFF_STATES and not (row.ignored or row.expected_off) and not (row.grace_until and row.grace_until > now) and row.state_since and now - row.state_since > timedelta(minutes=3):
                err = row.state == "ERROR"
                desired[f"off:{row.uuid}"] = {"host": row.name, "hostid": row.uuid, "tenant": tenant, "triggerid": "CloudVmOff", "item_name": f"{names.get(acc.client_id) or ''} · {row.zone or ''}".strip(" ·"),
                                              "trigger_name": "Máquina virtual com erro" if err else "Máquina virtual desligada", "severity": 5 if err else 4, "started_at": row.state_since, "type": "CloudVmOff",
                                              "opdata": f"{row.cpu} vCPU · {round((row.ram_mb or 0) / 1024)} GB · {row.ip or ''}"}
    db.commit()
    stats.update(P.reconcile(db, desired, source="cloud", kind="cloud", origin="Cloud Orca"))
    return stats
