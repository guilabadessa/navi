from types import SimpleNamespace as NS
from unittest.mock import patch

from app.services import push_service


def u(role, **kw):
    return NS(id=1, role=role, active=True, portal_min_sev=kw.get("min", 4), client_id=kw.get("cid"), push_min_sev=kw.get("pmin", 3),
              push_quiet_start=kw.get("qs"), push_quiet_end=kw.get("qe"))


def ev(sev, cid):
    return NS(severity=sev, client_id=cid)


def test_staff_recebe_so_incidentes():
    assert push_service.wants(None, u("ANALISTA_NOC"), ev(3, 1))
    assert not push_service.wants(None, u("ANALISTA_NOC"), ev(2, 1))


def test_cliente_so_o_proprio_e_severidade_minima():
    with patch.object(push_service.PA, "client_ids", return_value=[7]):
        assert push_service.wants(None, u("CLIENTE", min=3), ev(3, 7))
        assert not push_service.wants(None, u("CLIENTE", min=3), ev(3, 8))   # outro cliente
        assert not push_service.wants(None, u("CLIENTE", min=4), ev(3, 7))   # abaixo da minima do usuario
        assert not push_service.wants(None, u("CLIENTE", min=1), ev(2, 7))   # nunca abaixo de incidente


def test_inativo_nao_recebe():
    x = u("ANALISTA_NOC"); x.active = False
    assert not push_service.wants(None, x, ev(5, 1))


def test_minima_do_proprio_usuario():
    assert not push_service.wants(None, u("ANALISTA_NOC", pmin=4), ev(3, 1))
    assert push_service.wants(None, u("ANALISTA_NOC", pmin=4), ev(4, 1))
    assert push_service.wants(None, u("ANALISTA_NOC", pmin=1), ev(3, 1))  # nunca abaixo de incidente


def test_horario_silencioso():
    from datetime import datetime
    t = lambda h: datetime(2026, 10, 11, h, 30)  # noqa: E731
    assert push_service.in_quiet(u("X", qs=22, qe=7), t(23)) and push_service.in_quiet(u("X", qs=22, qe=7), t(3))  # vira a noite
    assert not push_service.in_quiet(u("X", qs=22, qe=7), t(12))
    assert push_service.in_quiet(u("X", qs=13, qe=15), t(14)) and not push_service.in_quiet(u("X", qs=13, qe=15), t(15))
    assert not push_service.in_quiet(u("X"), t(3))


def test_link_do_incidente_por_perfil():
    class DB:
        def get(self, *_): return None
    e = NS(id=42, severity=4, client_id=None, host="h", trigger_name="t")
    assert push_service.payload(DB(), e, u("ANALISTA_NOC"))["url"] == "/cliente/eventos?open=42"
    assert push_service.payload(DB(), e, u("CLIENTE"))["url"] == "/cliente/"
    assert push_service.payload(DB(), e, u("CLIENTE"), recovered=True)["title"].startswith("Resolvido")
