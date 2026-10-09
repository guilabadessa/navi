"""Regras de seguranca (sem banco/rede): toda rota exige login/permissao, sessoes, IP real e nomes."""
from types import SimpleNamespace as NS

from fastapi.routing import APIRoute

from app.config import get_settings
from app.main import app
from app.security import PERMS, current_user, client_ip, make_session, read_session, user_has
from app.util import titlecase

PUBLICAS = {  # unicas rotas que podem funcionar sem sessao
    ("POST", "/auth/login"), ("POST", "/auth/logout"), ("GET", "/auth/invite/{token}"), ("POST", "/auth/accept-invite"), ("POST", "/auth/forgot"),
    ("POST", "/webhook/zabbix"), ("GET", "/finance/callback"), ("GET", "/health"),
}


def _deps(dep, acc):
    for d in dep.dependencies:
        acc.append(d.call)
        _deps(d, acc)
    return acc


def _routes():
    """(rota, caminho completo). O FastAPI novo inclui os routers de forma preguicosa, entao percorremos os dois formatos."""
    for r in app.routes:
        if isinstance(r, APIRoute):
            yield r, r.path
        elif hasattr(r, "original_router"):
            for x in r.original_router.routes:
                if isinstance(x, APIRoute):
                    yield x, f"{BASE}/api{x.path}"


BASE = get_settings().NAVI_BASE_PATH.rstrip("/")


def test_toda_rota_exige_autenticacao_exceto_as_publicas():
    abertas = set()
    for r, full in _routes():
        if full.startswith(f"{BASE}/api") and current_user not in _deps(r.dependant, []):
            for m in r.methods - {"HEAD", "OPTIONS"}:
                abertas.add((m, full.removeprefix(f"{BASE}/api")))
    assert abertas == PUBLICAS, f"rotas sem autenticacao inesperadas: {abertas ^ PUBLICAS}"


def test_escrita_nunca_depende_so_de_permissao_de_leitura_na_equipe_exceto_previas():
    previas = {"/alerts/templates/preview", "/reports/{rid}/preview", "/settings/smtp/preview", "/finance/sync",
               "/finance/clients/{cid}/link", "/finance/clients/{cid}/link/{person_id}", "/auth/change-password"}
    for r, full in _routes():
        if r.methods & {"POST", "PUT", "PATCH", "DELETE"} and full.startswith(f"{BASE}/api"):
            perms = [c.__closure__[0].cell_contents for c in _deps(r.dependant, []) if getattr(c, "__name__", "") == "dep" and c.__closure__]
            perms = [p for p in perms if isinstance(p, str)]
            path = full.removeprefix(f"{BASE}/api")
            if path in PUBLICAS or path in previas or path.startswith("/auth/") or path == "/webhook/zabbix":
                continue
            assert perms and not all(p.endswith(".view") for p in perms), f"escrita sem permissao de edicao: {path}"


def test_configuracoes_somente_administrador():
    for role in ("GESTOR", "ANALISTA_NOC", "VISUALIZADOR", "CLIENTE"):
        u = NS(role=role, extra_perms=["finance.view", "portal.finance"])
        assert not user_has(u, "settings.view") and not user_has(u, "settings.edit") and not user_has(u, "users.manage")
    assert user_has(NS(role="ADMIN", extra_perms=[]), "settings.edit")


def test_permissoes_extras_respeitam_o_perfil():
    assert user_has(NS(role="CLIENTE", extra_perms=["portal.finance"]), "portal.finance")
    assert not user_has(NS(role="CLIENTE", extra_perms=["finance.view"]), "finance.view")  # permissao da equipe nao vale para cliente
    assert not user_has(NS(role="GESTOR", extra_perms=["portal.finance"]), "portal.finance")
    assert not user_has(NS(role="CLIENTE", extra_perms=[]), "portal.finance")
    assert PERMS["CLIENTE"] == {"portal.view", "portal.run", "cloud.run"}  # o cliente so enxerga o proprio ambiente e pode pedir novo backup dos itens dele


def test_sessao_assinada_e_adulteracao():
    tok, csrf = make_session(7, "abc123")
    s = read_session(tok)
    assert s["uid"] == 7 and s["csrf"] == csrf and s["fp"] == "abc123"
    assert read_session(tok[:-2] + "xx") is None
    assert read_session(None) is None


def _req(xff=None, peer="127.0.0.1", cf=None):
    h = {}
    if xff:
        h["x-forwarded-for"] = xff
    if cf:
        h["cf-connecting-ip"] = cf
    return NS(headers=h, client=NS(host=peer))


def test_ip_do_cliente_nao_aceita_xff_forjado():
    assert client_ip(_req("1.2.3.4, 200.10.10.10")) == "200.10.10.10"  # a ultima entrada e a que o Apache acrescentou
    assert client_ip(_req(None, "10.0.0.5")) == "10.0.0.5"
    # via Cloudflare: vale o CF-Connecting-IP; fora da Cloudflare ele e ignorado (nao e forjavel por quem chega direto)
    assert client_ip(_req("9.9.9.9, 172.71.1.1", cf="201.1.1.1")) == "201.1.1.1"
    assert client_ip(_req("9.9.9.9, 200.10.10.10", cf="201.1.1.1")) == "200.10.10.10"


def test_titlecase():
    assert titlecase("LABADESSA ENGENHARIA") == "Labadessa Engenharia"
    assert titlecase("b2b side servicos financeiros e administrativos") == "B2B Side Servicos Financeiros e Administrativos"
    assert titlecase("lider brasil comissaria DE avarias LTDA") == "Lider Brasil Comissaria de Avarias Ltda"
    assert titlecase("td synnex") == "TD Synnex"
    assert titlecase(None) is None and titlecase("  ") == "  "


def test_like_escapa_curingas():
    from app.util import like
    assert like("a%b_c") == "%a\\%b\\_c%"
    assert like("100") == "%100%"
