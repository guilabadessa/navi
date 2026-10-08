"""Testes de regras puras (sem banco/rede): casamento de padroes, severidade, numeros e KPIs."""
from types import SimpleNamespace as NS

from app.formats import fmt_phone
from app.services import severity_service
from app.services.evolution_service import normalize_target
from app.services.notification_service import _match


def test_match_substring_e_glob():
    assert _match("link", "BSIDE BH - LINK SAMM")
    assert _match("*samm", "bside - link samm")
    assert not _match("vpn", "link samm")
    assert _match(None, "qualquer")


def test_normalize_target_adiciona_55_e_preserva_grupo():
    assert normalize_target("(14) 99633-8761") == "5514996338761"
    assert normalize_target("5514996338761") == "5514996338761"
    assert normalize_target("120363000000000000@g.us").endswith("@g.us")


def test_fmt_phone_mascara():
    assert fmt_phone("14996338761") == "(14) 99633-8761"


def _r(host=None, trig=None, frm=0, to=4):
    return NS(host_pattern=host, trigger_pattern=trig, from_max=frm, severity=to)


def test_severidade_eleva_nao_classificado():
    rs = [_r(trig="health", to=4)]
    assert severity_service.effective(rs, "SDWAN-X", "Health check failed", 0) == 4


def test_severidade_nunca_rebaixa():
    rs = [_r(trig="health", to=3)]
    assert severity_service.effective(rs, "h", "health", 5) == 5


def test_severidade_respeita_limite_origem():
    rs = [_r(trig="health", frm=0, to=4)]
    assert severity_service.effective(rs, "h", "health", 2) == 2


def test_regra_sem_padrao_nao_aplica():
    assert severity_service.effective([_r()], "h", "t", 0) == 0
