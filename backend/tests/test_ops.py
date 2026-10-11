"""Janelas de manutencao, SLA com descontos, escalonamento, agrupamento e convites."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from app.security import make_invite_token, read_invite_token
from app.services import kpi_service, maintenance_service, noc_service

UTC = timezone.utc


def test_janela_pontual_e_recorrente():
    a = datetime(2026, 10, 10, 2, 0, tzinfo=UTC)
    once = NS(kind="once", start_at=a, end_at=a + timedelta(hours=2), weekdays=None, start_time=None, duration_min=None)
    assert maintenance_service.expand(once, a - timedelta(days=1), a + timedelta(days=1)) == [(a, a + timedelta(hours=2))]
    assert maintenance_service.expand(once, a + timedelta(days=1), a + timedelta(days=2)) == []
    weekly = NS(kind="weekly", start_at=None, end_at=None, weekdays=[5], start_time="02:00", duration_min=120)  # sabado
    out = maintenance_service.expand(weekly, datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 31, tzinfo=UTC))
    assert len(out) == 4 and all((e - s) == timedelta(hours=2) for s, e in out)


def test_subtract_remove_trechos():
    assert kpi_service._subtract((0, 100), [(20, 30), (50, 60)]) == [(0, 20), (30, 50), (60, 100)]
    assert kpi_service._subtract((10, 20), [(0, 100)]) == []


def test_sla_desconta_manutencao():
    start = datetime(2026, 10, 1, tzinfo=UTC)
    end = start + timedelta(hours=10)
    ev = NS(hostid="1", host="h", ip=None, started_at=start + timedelta(hours=1), recovered_at=start + timedelta(hours=3), status="RESOLVED",
            severity=4, trigger_name="t", item_name=None)
    hosts = [{"hostid": "1", "name": "h", "ip": None}]
    base = kpi_service.compute([ev], hosts, start, end)["summary"]
    ex = [((start + timedelta(hours=1)).timestamp(), (start + timedelta(hours=3)).timestamp())]
    desc = kpi_service.compute([ev], hosts, start, end, exclude=ex)["summary"]
    assert base["downtime_s"] == 7200 and base["incidents"] == 1
    assert desc["downtime_s"] == 0 and desc["incidents"] == 0 and desc["availability"] == 100


def _ev(i, minutes_ago, sev=4, status="PROBLEM", client=1, ack=False, now=None):
    return NS(id=i, status=status, client_id=client, acknowledged=ack, severity=sev, started_at=(now - timedelta(minutes=minutes_ago)))


def test_escalonamento_candidatos():
    now = datetime.now(UTC)
    evs = [_ev(1, 20, now=now), _ev(2, 5, now=now), _ev(3, 30, sev=2, now=now), _ev(4, 30, ack=True, now=now),
           _ev(5, 30, client=None, now=now), _ev(6, 30, status="RESOLVED", now=now), _ev(7, 30 * 60, now=now), _ev(8, 40, now=now)]
    ids = [e.id for e in noc_service.escalation_candidates(evs, {8}, now, 15, 4)]
    assert ids == [1]


def _d(i, kind="problem", dest="14996338761", ch="whatsapp"):
    return NS(id=i, kind=kind, channel=ch, dest_jid=dest)


def test_agrupamento_por_cliente_e_destino():
    items = [(_d(1), NS(client_id=1)), (_d(2, dest="(14) 99633-8761"), NS(client_id=1)), (_d(3), NS(client_id=1)),
             (_d(4), NS(client_id=2)), (_d(5, ch="email", dest="a@x.com"), NS(client_id=1))]
    groups, rest = noc_service.pick_groups(items, 3)
    assert len(groups) == 1 and len(groups[0]) == 3  # mesmo numero escrito de formas diferentes
    assert {d.id for d, _ in rest} == {4, 5}


def test_horario_do_resumo():
    assert noc_service.validate_time("08:00") and not noc_service.validate_time("8:00") and not noc_service.validate_time("25:00")


class _DB:
    def __init__(self, u): self.u = u
    def get(self, _m, _id): return self.u


def test_convite_vale_uma_vez(monkeypatch):
    u = NS(id=7, active=True, password_hash="x" * 20 + "ABCDEFGHIJKL")
    tok = make_invite_token(u)
    assert read_invite_token(tok, _DB(u)) is u
    u.password_hash = "y" * 32  # senha definida: o link deixa de valer
    assert read_invite_token(tok, _DB(u)) is None
    assert read_invite_token("lixo", _DB(u)) is None


def test_protecao_textos_e_datas():
    from app.services import protection_service as P
    assert P.human_type("BackupFailed") == "Falha no backup"
    assert P.human_type("SomethingNewHappened") == "Something New Happened"
    d = P._dt("2026-10-08T03:32:16.123456789Z")
    assert d.tzinfo is not None and d.year == 2026 and d.microsecond == 123456
    assert P._dt(1791430336).year == 2026


def test_status_do_ativo_de_backup():
    from app.routers.protection import asset_status
    now = datetime.now(UTC)
    c = {"stale_h": 72, "offline_min": 240}
    mk = lambda **k: NS(**{"ignored": False, "online": None, "offline_since": None, "last_success_at": None, "last_failure_at": None,
                           "meta": {"os_name": "Windows Server 2022 Standard"}, "name": "SRV-01", "source": "acronis", **k})  # noqa: E731
    assert asset_status(mk(last_success_at=now - timedelta(hours=2)), c, now) == "ok"
    assert asset_status(mk(last_success_at=now - timedelta(days=5)), c, now) == "sem backup"
    assert asset_status(mk(last_success_at=now - timedelta(hours=30), last_failure_at=now - timedelta(hours=1)), c, now) == "falha"
    assert asset_status(mk(online=False, offline_since=now - timedelta(hours=9)), c, now) == "offline"
    # estacao de trabalho desligada fora do expediente NAO e "offline"
    ws = {"os_name": "Windows 11 Pro"}
    assert asset_status(mk(online=False, offline_since=now - timedelta(hours=9), meta=ws, name="NOTE-ANA", last_success_at=now - timedelta(hours=20)), c, now) == "ok"
    assert asset_status(mk(ignored=True, last_success_at=now - timedelta(days=9)), c, now) == "ignorado"
    assert asset_status(mk(), c, now) == "sem dados"


def test_status_do_endpoint_ems():
    from app.services.protection_service import ems_status
    now = datetime.now(UTC)
    mk = lambda **k: NS(**{"ignored": False, "online": True, "last_success_at": now, "meta": {}, **k})  # noqa: E731
    assert ems_status(mk(), 7, now) == "online"
    assert ems_status(mk(online=False, last_success_at=now - timedelta(days=2)), 7, now) == "offline"
    assert ems_status(mk(online=False, last_success_at=now - timedelta(days=9)), 7, now) == "sem contato"
    assert ems_status(mk(meta={"av_enabled": False}), 7, now) == "antivírus off"
    assert ems_status(mk(meta={"av_enabled": True, "sig_ok": False}), 7, now) == "assinaturas"
    assert ems_status(mk(meta={"quarantined": True}), 7, now) == "quarentena"
    assert ems_status(mk(ignored=True), 7, now) == "ignorado"


def test_servidor_x_estacao():
    from app.services.protection_service import machine_role
    mk = lambda name, **m: NS(name=name, source=m.pop("source", "acronis"), meta=m)  # noqa: E731
    assert machine_role(mk("SRV-PS-PRD-40", os_name="Windows Server 2025 Datacenter")) == "server"
    assert machine_role(mk("ubuntu01", os_name="Ubuntu", os_family="LINUX")) == "server"
    assert machine_role(mk("EC-SEC-00025", os_name="Windows 11 Pro")) == "workstation"
    assert machine_role(mk("PC-ANA", os="Microsoft Windows 10 Professional Edition", source="ems")) == "workstation"
    assert machine_role(mk("srvmegadan", os_name="windows")) == "server"          # SO generico: o nome indica servidor
    assert machine_role(mk("COC_NT_542", os_name="windows", source="ems")) == "workstation"
    assert machine_role(mk("COCPRDFS", os_name="windows")) == "server"            # duvida no Acronis = servidor (nao esconde problema)
    assert machine_role(mk("PC-ANA", os_name="Windows 11 Pro", role="server")) == "server"   # ajuste manual vale sempre
    assert machine_role(mk("SRV-01", os_name="Windows Server 2019", role="workstation")) == "workstation"


def test_atencao_nao_e_incidente():
    from app.models import INCIDENT_MIN_SEV
    from app.services import notification_service as N
    assert INCIDENT_MIN_SEV == 3
    ev = NS(severity=2)
    assert N.plan_problem(None, ev) == 0       # nem consulta o banco: Atencao so fica registrado
    assert N.plan_problem(None, NS(severity=1)) == 0


def test_resumo_diario_so_incidentes_abertos():
    from app.services import noc_service
    d = {"now": datetime.now(UTC), "open": 3, "by_sev": {5: 1, 3: 2}, "maint": ["Cliente M"], "platform": [], "status": "crit",
         "clients": [{"name": "Cocal", "worst": 5, "items": [{"sev": 5, "kind": "cloud", "host": "VM-01", "text": "Máquina virtual com erro"}]},
                     {"name": "Codifica", "worst": 3, "items": [{"sev": 3, "kind": "infra", "host": "SRV", "text": "CPU alta"}, {"sev": 3, "kind": "infra", "host": "SRV2", "text": "Disco"}]}]}
    txt = "\n".join(noc_service.digest_text(d, "10/10/2026"))
    for banned in ("24h", "enviados", "há mais tempo", "novos", "resolvidos", "WhatsApp:", "E-mail:"):
        assert banned not in txt
    assert "3 incidentes em aberto" in txt and "Cocal" in txt and "VM-01" in txt and "Em manutenção" in txt
    ok = noc_service.digest_text({**d, "open": 0, "by_sev": {}, "clients": [], "maint": [], "status": "ok"}, "10/10/2026")
    assert "Tudo em ordem" in ok[0] and len(ok) == 1
    ctx = noc_service.digest_ctx(d, "10/10/2026")
    assert ctx["open"] == 3 and len(ctx["groups"]) == 2 and "new24" not in ctx


def test_saude_da_vm_pelo_zabbix():
    from app.services.cloud_service import parse_health
    it = lambda k, v, c=1791644686: {"key_": k, "lastvalue": str(v), "lastclock": str(c), "state": "0"}  # noqa: E731
    h = parse_health([it("system.cpu.util", 37.25), it("vm.memory.size[pavailable]", 40), it("vfs.fs.size[C:,pused]", 71.1), it("vfs.fs.size[/,pused]", 12),
                      it("icmpping", 1), it("icmppingsec", 0.0021), it("icmppingloss", 0)])
    assert h["cpu"] == 37.2 or h["cpu"] == 37.3
    assert h["mem"] == 60.0 and [d["mount"] for d in h["disks"]] == ["/", "C:"] and h["ping"] == {"up": True, "rtt_ms": 2.1, "loss_pct": 0.0}
    only_ping = parse_health([it("icmpping", 0)])
    assert only_ping["cpu"] is None and only_ping["disks"] == [] and only_ping["ping"]["up"] is False
