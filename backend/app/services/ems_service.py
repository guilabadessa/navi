"""Cliente da API do FortiClient EMS 8.x (multi-site). Somente leitura (apenas GET, alem do login).
Autenticacao: login de usuario e senha (o mesmo que a interface web usa) -> cookies de sessao; cada "site" (tenant)
e escolhido pelo cabecalho 'Site'. Tentativa de login com senha errada conta para o bloqueio da conta: por isso a NAVI
nao repete login que falhou (veja ems.auth_blocked)."""
import httpx


class EmsError(RuntimeError):
    pass


class EmsService:
    def __init__(self, host: str, port: int, user: str, password: str):
        self.host, self.port, self.user, self.password = (host or "").strip(), port, user, password
        self.base = f"https://{self.host}" + (f":{port}" if port and port != 443 else "")
        self.http = httpx.Client(timeout=40, verify=False, headers={"User-Agent": "NAVI/1.0"})  # certificado interno/autoassinado
        self._logged = False

    @property
    def configured(self) -> bool:
        return bool(self.host and self.user and self.password)

    def login(self):
        if not self.configured:
            raise EmsError("EMS não configurado (endereço, usuário e senha)")
        try:
            r = self.http.post(f"{self.base}/api/v1/auth/ws_jwt/signin", json={"name": self.user, "password": self.password},
                               headers={"Ems-Call-Type": "1"})
        except httpx.ConnectError:
            raise EmsError(f"Sem conexão com {self.host}:{self.port} (porta fechada ou bloqueada por firewall)") from None
        except httpx.TimeoutException:
            raise EmsError(f"Tempo esgotado ao conectar em {self.host}:{self.port}") from None
        ok = False
        try:
            ok = r.status_code == 200 and int(r.json().get("result", {}).get("retval", 0)) > 0  # retval 1 = "Login successful."
        except Exception:  # noqa: BLE001
            pass
        if not ok:
            msg = ""
            try:
                msg = r.json().get("result", {}).get("message", "")
            except Exception:  # noqa: BLE001
                msg = r.text[:120]
            raise EmsAuthError(f"EMS recusou o login do usuário '{self.user}': {msg}")
        self._logged = True

    def get(self, path: str, site: str | None = None, _retry: bool = True, **params):
        if not self._logged:
            self.login()
        headers = {"X-CSRFToken": self.http.cookies.get("csrftoken") or "", "Ems-Call-Type": "2"}
        if site:
            headers["Site"] = site
        try:
            r = self.http.get(f"{self.base}/api/v1/{path.lstrip('/')}", params=params, headers=headers)
        except httpx.TimeoutException:
            raise EmsError(f"Tempo esgotado em {path}") from None
        if r.status_code == 401 and _retry:  # sessao expirou: um novo login (credenciais ja validadas)
            self._logged = False
            return self.get(path, site, False, **params)
        if r.status_code != 200:
            try:
                msg = r.json().get("result", {}).get("message", r.text[:120])
            except Exception:  # noqa: BLE001
                msg = r.text[:120]
            raise EmsError(f"{path}: HTTP {r.status_code} {msg}")
        d = r.json()
        res = d.get("result", {})
        if int(res.get("retval", 1)) < 0:
            raise EmsError(f"{path}: {res.get('message')}")
        return d.get("data")

    def sites(self) -> list[str]:
        return list(self.get("sites/names/index") or [])

    def endpoints(self, site: str) -> list[dict]:
        out, start = [], 0
        while True:
            d = self.get("endpoints/index", site=site, count=1000, start=start) or {}
            batch = d.get("endpoints") or []
            out += batch
            if len(batch) < 1000:
                return out
            start += 1000

    def test(self) -> str:
        sites = self.sites()
        return f"EMS conectado · {len(sites)} site(s): {', '.join(sites)}"


class EmsAuthError(EmsError):
    pass
