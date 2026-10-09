"""Cliente da API do Acronis Cyber Protect Cloud. Consultas (GET) + UMA acao opcional: iniciar um plano de backup (run_policy),
usada apenas pelo botao "Executar backup agora" e somente se habilitada em Configuracoes."""
import time
from datetime import datetime, timezone

import httpx


class AcronisError(RuntimeError):
    pass


class AcronisService:
    def __init__(self, url: str, client_id: str, secret: str):
        self.base = (url or "").rstrip("/")
        self.cid, self.secret = client_id, secret
        self._tok, self._exp = None, 0.0
        self.http = httpx.Client(timeout=40, headers={"User-Agent": "NAVI/1.0"})

    @property
    def configured(self) -> bool:
        return bool(self.base and self.cid and self.secret)

    def token(self) -> str:
        if self._tok and time.time() < self._exp - 120:
            return self._tok
        if not self.configured:
            raise AcronisError("Acronis não configurado (URL, ID do cliente e segredo)")
        r = self.http.post(f"{self.base}/api/2/idp/token", auth=(self.cid, self.secret), data={"grant_type": "client_credentials"})
        if r.status_code != 200:
            raise AcronisError(f"Autenticação recusada pelo Acronis (HTTP {r.status_code})")
        d = r.json()
        self._tok, self._exp = d["access_token"], time.time() + int(d.get("expires_in", 7200))
        return self._tok

    def get(self, path: str, **params) -> dict:
        r = self.http.get(f"{self.base}{path}", params={k: v for k, v in params.items() if v is not None},
                          headers={"Authorization": f"Bearer {self.token()}"})
        if r.status_code != 200:
            raise AcronisError(f"{path}: HTTP {r.status_code} {r.text[:200]}")
        return r.json()

    def pages(self, path: str, max_pages: int = 20, **params):
        after = None
        for _ in range(max_pages):
            # com o cursor "after" a API nao aceita outros filtros
            d = self.get(path, after=after) if after else self.get(path, **params)
            yield from d.get("items", [])
            after = ((d.get("paging") or {}).get("cursors") or {}).get("after")
            if not after:
                return

    # ---- recursos ----
    def root_tenant(self) -> str:
        return self.get(f"/api/2/clients/{self.cid}")["tenant_id"]

    def tenant_tree(self) -> list[dict]:
        """Todos os tenants abaixo do parceiro (clientes e unidades)."""
        out, queue = [], [self.root_tenant()]
        while queue:
            pid = queue.pop(0)
            for t in self.pages("/api/2/tenants", parent_id=pid):
                out.append(t)
                if t.get("kind") in ("customer", "folder", "partner", "group") or t.get("has_children"):
                    queue.append(t["id"])
        return out

    def alerts(self) -> list[dict]:
        return list(self.pages("/api/alert_manager/v1/alerts", limit=200))

    def agents(self) -> list[dict]:
        return list(self.pages("/api/agent_manager/v2/agents", limit=500))

    def resources(self, rtype: str = "resource.machine") -> list[dict]:
        return list(self.pages("/api/resource_management/v4/resources", max_pages=30, type=rtype, limit=500))

    def backup_activities(self, since: datetime):
        s = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for a in self.pages("/api/task_manager/v2/activities", max_pages=40, limit=200, startedAt=f"gt({s})", order="desc(startedAt)"):
            # atividades de backup: tem plano (policy) do tipo backup; maquinas aparecem como resource.type "instance"
            if (a.get("policy") or {}).get("type") == "backup" and a.get("resource"):
                yield a

    def usages(self, tenant_ids: list[str]) -> list[dict]:
        """Licencas/uso por tenant (servicos contratados)."""
        out = []
        for i in range(0, len(tenant_ids), 20):
            out += self.get("/api/2/tenants/usages", tenants=",".join(tenant_ids[i:i + 20])).get("items", [])
        return out

    def run_policy(self, policy_id: str, resource_id: str) -> dict:
        """Executa um plano (backup) agora em um recurso. PUT /api/policy_management/v4/applications/run (resposta 202)."""
        r = self.http.put(f"{self.base}/api/policy_management/v4/applications/run", json={"state": "running", "policy_id": policy_id, "context_ids": [resource_id]},
                          headers={"Authorization": f"Bearer {self.token()}"})
        if r.status_code not in (200, 202, 204):
            raise AcronisError(f"HTTP {r.status_code} {r.text[:200]}")
        return {"status": r.status_code}

    def test(self) -> str:
        tid = self.root_tenant()
        n = len([t for t in self.pages("/api/2/tenants", parent_id=tid) if t.get("kind") == "customer"])
        return f"Acronis conectado · {n} cliente(s) (tenants)"
