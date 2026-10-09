"""Cache de configuracoes (1 fotografia em memoria) e aceite de falhas de rotina (sem banco)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from app import settings_store as S
from app.routers import dashboard as D


class FakeDb:
    def __init__(self, rows):
        self.rows, self.info, self.loads, self.gets = rows, {}, 0, 0

    def execute(self, _stmt):
        self.loads += 1
        return list(self.rows)

    def get(self, _model, key):
        self.gets += 1
        r = next((x for x in self.rows if x[0] == key), None)
        return NS(value=r[1], is_secret=r[2]) if r else None


def test_cache_le_a_tabela_uma_vez_e_invalida():
    db = FakeDb([("alerts.shadow", "1", False)])
    S.invalidate()
    assert S.get(db, "alerts.shadow") == "1" and S.get(db, "alerts.shadow") == "1"
    assert db.loads == 1  # segunda leitura veio da memoria
    S.invalidate()
    S.get(db, "alerts.shadow")
    assert db.loads == 2


def test_cache_ignora_conta_azul_e_gravacao_pendente():
    db = FakeDb([("contaazul.refresh_token", "abc", False), ("x.y", "v", False)])
    S.invalidate()
    assert S.get(db, "contaazul.refresh_token") == "abc" and db.gets == 1 and db.loads == 0
    db.info["settings_dirty"] = True
    S.get(db, "x.y")
    assert db.gets == 2  # sessao com gravacao pendente le direto do banco


def _job(**kw):
    base = dict(name="j", label="Rotina", enabled=True, status="ok", error=None, interval_s=60, ack_sig=None,
                last_run=datetime.now(timezone.utc))
    return NS(**(base | kw))


class JobDb:
    def __init__(self, jobs):
        self.jobs = jobs

    def scalars(self, _s):
        return iter(self.jobs)


def test_aceite_esconde_ate_surgir_falha_nova():
    j = _job(status="error", error="Boom: falhou")
    assert [a["kind"] for a in D.job_alerts(JobDb([j]))] == ["erro"]
    j.ack_sig = D._sig(j, "erro")
    assert D.job_alerts(JobDb([j])) == []
    j.error = "Outro erro"  # falha diferente reaparece
    assert len(D.job_alerts(JobDb([j]))) == 1


def test_atraso_e_rotina_desabilitada():
    velho = datetime.now(timezone.utc) - timedelta(hours=1)
    j = _job(last_run=velho)
    assert [a["kind"] for a in D.job_alerts(JobDb([j]))] == ["atraso"]
    j.ack_sig = D._sig(j, "atraso")
    assert D.job_alerts(JobDb([j])) == []
    assert D.job_alerts(JobDb([_job(last_run=velho, enabled=False)])) == []
