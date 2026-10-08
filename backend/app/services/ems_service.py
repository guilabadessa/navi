"""Cliente da API do FortiClient EMS 8.x (multi-tenant). Somente leitura (GET).
ATENCAO: a forma exata da API ainda nao foi validada contra o servidor (a porta HTTPS estava inacessivel);
por isso a sincronizacao de alertas fica desligada ate o teste de conexao passar."""
import httpx


class EmsError(RuntimeError):
    pass


class EmsService:
    def __init__(self, host: str, port: int, api_key: str):
        self.host, self.port, self.key = (host or "").strip(), port, api_key
        self.base = f"https://{self.host}" + (f":{port}" if port and port != 443 else "")
        self.http = httpx.Client(timeout=25, verify=False, headers={"User-Agent": "NAVI/1.0"})  # EMS costuma ter certificado autoassinado

    @property
    def configured(self) -> bool:
        return bool(self.host and self.key)

    def get(self, path: str, **params):
        if not self.configured:
            raise EmsError("EMS não configurado (endereço e chave de API)")
        try:
            r = self.http.get(f"{self.base}{path}", params=params, headers={"Authorization": f"Bearer {self.key}"})
        except httpx.ConnectError:
            raise EmsError(f"Sem conexão com {self.host}:{self.port} (porta fechada ou bloqueada por firewall)") from None
        except httpx.TimeoutException:
            raise EmsError(f"Tempo esgotado ao conectar em {self.host}:{self.port} (firewall descartando pacotes?)") from None
        if r.status_code in (401, 403):
            raise EmsError(f"EMS recusou a chave de API (HTTP {r.status_code})")
        if r.status_code != 200:
            raise EmsError(f"{path}: HTTP {r.status_code} {r.text[:160]}")
        return r.json()

    def test(self) -> str:
        d = self.get("/api/v1/system/consts/get")
        return "EMS conectado" + (f" · {d.get('data', {}).get('version', '')}" if isinstance(d, dict) else "")
