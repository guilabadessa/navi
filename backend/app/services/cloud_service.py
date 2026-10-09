"""Nuvem Orca (BRASCLOUD / plataforma 4bdigital): consulta e energia das maquinas virtuais de UM cliente.
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
        return [{"type": q.get("quotaType"), "used": q.get("usedLimit"), "max": q.get("maximumLimit"), "available": q.get("availableLimit")} for q in rows if q.get("maximumLimit")]

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
