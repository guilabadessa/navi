from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.security import current_user
from app.services import notification_service as N
from app.services import silence_service as SS

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def ev(**kw):
    base = dict(id=1, kind="infra", host="SRV-01", hostid="10", triggerid="555", trigger_name="Link down", severity=4, status="PROBLEM", client_id=7, source="api")
    return NS(**{**base, **kw})


def sil(**kw):
    base = dict(id=1, scope="host", kind="infra", host="SRV-01", triggerid=None, trigger_name=None, until=None, reason=None, asset_id=None)
    return NS(**{**base, **kw})


def test_escopos_do_silencio():
    assert SS.matches(sil(), ev()) and SS.matches(sil(host="srv-01"), ev())  # host sem diferenciar maiusculas
    assert not SS.matches(sil(host="OUTRO"), ev())
    assert SS.matches(sil(scope="problem_host", triggerid="555"), ev()) and not SS.matches(sil(scope="problem_host", triggerid="999"), ev())
    assert SS.matches(sil(scope="problem", host=None, triggerid="555"), ev(host="QUALQUER"))
    assert SS.matches(sil(scope="problem", host=None, triggerid=None, trigger_name="link DOWN"), ev())  # por nome quando nao ha triggerid
    assert not SS.matches(sil(kind="backup"), ev())  # outra origem
    assert not SS.matches(sil(host=None), ev())  # silencio vazio nunca casa com tudo


def test_chave_do_silencio_por_evento():
    assert SS.key_for(ev(), "host") == {"scope": "host", "kind": "infra", "host": "SRV-01"}
    assert SS.key_for(ev(), "problem") == {"scope": "problem", "kind": "infra", "triggerid": "555"}
    assert SS.key_for(ev(triggerid=None), "problem_host")["trigger_name"] == "Link down"
    for bad in (dict(host=None), ):
        with pytest.raises(ValueError):
            SS.key_for(ev(**bad), "host")
    with pytest.raises(ValueError):
        SS.key_for(ev(triggerid=None, trigger_name=None), "problem")
    with pytest.raises(ValueError):
        SS.key_for(ev(), "tudo")


def test_criar_silencio_com_prazo_permanente_e_sem_duplicar(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(SS, "active", lambda d, at=None: [])
    s = SS.create(db, ev(), "host", 4, "janela do cliente", "a@x.com")
    assert s.until is not None and timedelta(hours=3, minutes=59) < s.until - SS.now() < timedelta(hours=4, minutes=1) and s.reason == "janela do cliente"
    existente = sil(until=None, reason="velho")
    monkeypatch.setattr(SS, "active", lambda d, at=None: [existente])
    s2 = SS.create(db, ev(), "host", 24, "novo motivo", "a@x.com")
    assert s2 is existente and existente.reason == "novo motivo" and existente.until is not None  # atualiza em vez de duplicar


def test_silencio_permanente_de_backup_ignora_a_maquina_tambem(monkeypatch):
    asset = NS(id=9, ignored=False)
    db = MagicMock()
    db.scalar.return_value = asset
    monkeypatch.setattr(SS, "active", lambda d, at=None: [])
    s = SS.create(db, ev(kind="backup", hostid="abc", source="acronis"), "host", None, None, "a@x.com")
    assert asset.ignored is True and s.asset_id == 9
    db.get.return_value = asset
    SS.remove(db, s)
    assert asset.ignored is False and db.delete.called  # reativar devolve o monitoramento
    a2 = NS(id=9, ignored=False)
    db.scalar.return_value = a2
    SS.create(db, ev(kind="backup", hostid="abc", source="acronis"), "host", 2, None, "a@x.com")
    assert a2.ignored is False  # silencio temporario nao mexe na maquina


def test_silencio_vence_o_alerta_de_problema_e_recuperacao(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(SS, "active", lambda d, at=None: [sil()])
    assert N.plan_problem(db, ev()) == 0 and not db.add.called
    pend = NS(status="pending", error=None)
    db.scalars.return_value.all.return_value = [pend]
    assert N.plan_recovery(db, ev()) == 0 and pend.status == "skipped"


def test_escalonamento_e_resumo_ignoram_silenciados(monkeypatch):
    from app.services import noc_service as NS_
    monkeypatch.setattr(SS, "active", lambda d, at=None: [sil()])
    db = MagicMock()
    monkeypatch.setattr(NS_, "cfg", lambda d: {"escalation_enabled": True, "noc_wa": "x@g.us", "noc_emails": "", "escalation_min_severity": 3, "escalation_minutes": 10})
    antigo = ev(started_at=datetime.now(timezone.utc) - timedelta(minutes=30), acknowledged=False)
    db.scalars.side_effect = [[antigo], []]
    assert NS_.escalate(db) == 0 and not [c for c in db.add.call_args_list if c.args and c.args[0].__class__.__name__ == "Dispatch"]


# ---- API ----
def _api(role="ANALISTA_NOC"):
    db = MagicMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: NS(id=7, email="a@x.com", name="Ana", role=role, active=True, extra_perms=[])
    return TestClient(app), db


def test_api_criar_e_reativar_exige_edicao(monkeypatch):
    c, db = _api("VISUALIZADOR")
    try:
        assert c.post("/cliente/api/event-silences", json={"event_ids": [1], "scope": "host"}).status_code == 403
        assert c.delete("/cliente/api/event-silences/1").status_code == 403
        assert c.get("/cliente/api/event-silences").status_code in (200, 500)
        c2, db2 = _api("ANALISTA_NOC")
        db2.scalars.return_value.all.return_value = [ev()]
        monkeypatch.setattr(SS, "active", lambda d, at=None: [])
        monkeypatch.setattr("app.routers.event_silences.out", lambda d, s: {"id": 1})
        assert c2.post("/cliente/api/event-silences", json={"event_ids": [1], "scope": "host", "hours": 4, "reason": "x"}).status_code == 200
        assert c2.post("/cliente/api/event-silences", json={"event_ids": [1], "scope": "tudo"}).status_code == 422
        assert c2.post("/cliente/api/event-silences", json={"event_ids": [], "scope": "host"}).status_code == 422
        assert c2.post("/cliente/api/event-silences", json={"event_ids": [1], "scope": "host", "hours": 0}).status_code == 422
        db2.scalars.return_value.all.return_value = []
        assert c2.post("/cliente/api/event-silences", json={"event_ids": [99], "scope": "host"}).status_code == 404
        db2.get.return_value = None
        assert c2.delete("/cliente/api/event-silences/5").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_api_evento_sem_dado_para_o_escopo_da_422(monkeypatch):
    c, db = _api()
    db.scalars.return_value.all.return_value = [ev(host=None)]
    monkeypatch.setattr(SS, "active", lambda d, at=None: [])
    try:
        assert c.post("/cliente/api/event-silences", json={"event_ids": [1], "scope": "host"}).status_code == 422
    finally:
        app.dependency_overrides.clear()
