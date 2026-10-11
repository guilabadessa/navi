from types import SimpleNamespace as NS
from unittest.mock import patch

from app.services import push_service


def u(role, **kw):
    return NS(id=1, role=role, active=True, portal_min_sev=kw.get("min", 4), client_id=kw.get("cid"))


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
