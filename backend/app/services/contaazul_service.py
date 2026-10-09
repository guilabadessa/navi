"""Cliente da API do Conta Azul (somente leitura: apenas GET, alem da troca/renovacao do token OAuth2)."""
import base64
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import settings_store as S

API = "https://api-v2.contaazul.com"
AUTH = "https://login.contaazul.com/#/oauth/authorize"
SCOPE = "openid profile aws.cognito.signin.user.admin"
DEFAULT_REDIRECT = "https://navi.orcati.com.br/cliente/api/finance/callback"
_LOCK = 7311041  # impede que API e worker renovem o token ao mesmo tempo (o refresh_token e rotativo)


class ContaAzulError(RuntimeError):
    pass


def digits(v: str | None) -> str:
    return "".join(ch for ch in (v or "") if ch.isdigit())


class ContaAzul:
    def __init__(self, db: Session):
        self.db = db
        self.http = httpx.Client(timeout=40, headers={"User-Agent": "NAVI/1.0"})

    # ---- configuracao ----
    @property
    def cid(self) -> str:
        return S.get(self.db, "contaazul.client_id")

    @property
    def secret(self) -> str:
        return S.get(self.db, "contaazul.client_secret")

    @property
    def redirect(self) -> str:
        return S.get(self.db, "contaazul.redirect_uri") or DEFAULT_REDIRECT

    @property
    def configured(self) -> bool:
        return bool(self.cid and self.secret)

    @property
    def authorized(self) -> bool:
        return bool(S.get(self.db, "contaazul.refresh_token") or self._valid_access())

    def _valid_access(self) -> str:
        tok = S.get(self.db, "contaazul.access_token")
        try:
            exp = float(S.get(self.db, "contaazul.expires_at") or 0)
        except ValueError:
            exp = 0
        return tok if tok and time.time() < exp - 90 else ""

    def authorize_url(self, state: str) -> str:
        from urllib.parse import urlencode
        q = urlencode({"response_type": "code", "client_id": self.cid, "redirect_uri": self.redirect, "state": state, "scope": SCOPE}, safe="/:")
        return f"{AUTH}?{q}"

    # ---- token ----
    def _basic(self) -> str:
        return "Basic " + base64.b64encode(f"{self.cid}:{self.secret}".encode()).decode()

    def _save(self, d: dict):
        S.put(self.db, "contaazul.access_token", d["access_token"], "contaazul")
        if d.get("refresh_token"):
            S.put(self.db, "contaazul.refresh_token", d["refresh_token"], "contaazul")
        S.put(self.db, "contaazul.expires_at", str(time.time() + int(d.get("expires_in", 3600))), "contaazul")
        S.put(self.db, "contaazul.auth_error", "", "contaazul")

    def _token_call(self, data: dict) -> dict:
        r = self.http.post(f"{API}/oauth/token", headers={"Authorization": self._basic(), "Content-Type": "application/x-www-form-urlencoded"}, data=data)
        if r.status_code != 200:
            raise ContaAzulError(f"Conta Azul recusou a autenticação (HTTP {r.status_code}). Autorize novamente em Configurações.")
        return r.json()

    def exchange_code(self, code: str):
        if not self.configured:
            raise ContaAzulError("Informe o ID do cliente e o segredo antes de autorizar")
        self._save(self._token_call({"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect}))

    def token(self) -> str:
        if not self.configured:
            raise ContaAzulError("Conta Azul não configurado (ID do cliente e segredo)")
        if S.get(self.db, "contaazul.auth_error"):
            raise ContaAzulError("Autorização do Conta Azul inválida ou expirada. Autorize novamente em Configurações.")
        t = self._valid_access()
        if t:
            return t
        rt = S.get(self.db, "contaazul.refresh_token")
        if not rt:
            raise ContaAzulError("Conta Azul ainda não autorizado. Gere o código de autorização em Configurações.")
        self.db.execute(text("select pg_advisory_xact_lock(:k)"), {"k": _LOCK})
        self.db.expire_all()
        t = self._valid_access()  # outro processo pode ter renovado enquanto esperavamos
        if t:
            return t
        rt = S.get(self.db, "contaazul.refresh_token")
        try:
            self._save(self._token_call({"grant_type": "refresh_token", "refresh_token": rt}))
        except ContaAzulError:
            # refresh_token invalido: nao insistir (evita loop de falhas); exige nova autorizacao
            S.put(self.db, "contaazul.auth_error", datetime.now(timezone.utc).isoformat(), "contaazul")
            self.db.commit()
            raise
        self.db.commit()
        return S.get(self.db, "contaazul.access_token")

    # ---- leitura ----
    def get(self, path: str, **params) -> dict:
        r = self.http.get(f"{API}{path}", params={k: v for k, v in params.items() if v is not None},
                          headers={"Authorization": f"Bearer {self.token()}"})
        if r.status_code == 429:
            time.sleep(2)
            r = self.http.get(f"{API}{path}", params={k: v for k, v in params.items() if v is not None},
                              headers={"Authorization": f"Bearer {self.token()}"})
        if r.status_code != 200:
            raise ContaAzulError(f"{path}: HTTP {r.status_code} {r.text[:160]}")
        return r.json()

    def people(self):
        page = 1
        while True:
            d = self.get("/v1/pessoas", pagina=page, tamanho_pagina=1000)
            items = d.get("items") or []
            yield from items
            if len(items) < 1000:
                return
            page += 1

    def receivables(self, de: str, ate: str):
        page = 1
        while True:
            d = self.get("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", pagina=page, tamanho_pagina=1000,
                         data_vencimento_de=de, data_vencimento_ate=ate)
            items = d.get("itens") or []
            yield from items
            if len(items) < 1000:
                return
            page += 1

    def contracts(self):
        """Contratos (GET): lista paginada + detalhe de cada um (o campo observacoes so vem no detalhe)."""
        page = 1
        while True:
            d = self.get("/v1/contratos", pagina=page, tamanho_pagina=100, data_inicio="2000-01-01", data_fim="2100-12-31")
            items = d.get("itens") or []
            for it in items:
                try:
                    det = self.get(f"/v1/contratos/{it['id']}")
                except ContaAzulError:
                    yield {"_list": it}
                    continue
                det["_items"] = self.contract_items(det)
                yield det | {"_list": it}
            if len(items) < 100:
                return
            page += 1

    def contract_items(self, contract: dict) -> list[dict] | None:
        """Servicos do contrato = itens da proxima venda agendada (ou da ultima confirmada). None se nao foi possivel ler."""
        for sid in (contract.get("id_proxima_venda_agendada"), contract.get("id_ultima_venda_confirmada")):
            if not sid:
                continue
            try:
                d = self.get(f"/v1/venda/{sid}/itens")
            except ContaAzulError:
                continue
            return [{"name": (i.get("nome") or "").strip(), "desc": (i.get("descricao") or "").strip(), "qty": i.get("quantidade")} for i in d.get("itens") or []]
        return None

    def installment(self, ext_id: str) -> dict:
        return self.get(f"/v1/financeiro/eventos-financeiros/parcelas/{ext_id}")

    def service_notes(self, de: str, ate: str):
        page = 1
        while True:
            d = self.get("/v1/notas-fiscais-servico", pagina=page, tamanho_pagina=100, data_competencia_de=de, data_competencia_ate=ate)
            items = d.get("itens") or []
            yield from items
            if len(items) < 100:
                return
            page += 1

    def product_notes(self, de: str, ate: str):
        """NF-e: a API limita a janela a 15 dias."""
        page = 1
        while True:
            d = self.get("/v1/notas-fiscais", pagina=page, tamanho_pagina=100, data_inicial=de, data_final=ate)
            items = d.get("itens") or []
            yield from items
            if len(items) < 100:
                return
            page += 1

    def test(self) -> dict:
        d = self.get("/v1/pessoas", pagina=1, tamanho_pagina=10)
        return {"ok": True, "detail": f"Conectado ao Conta Azul ({d.get('totalItems', 0)} cadastros de pessoas)"}
