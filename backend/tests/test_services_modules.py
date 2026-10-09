"""Servicos por cliente (infra/backup/estacoes): modulos do relatorio e interpretacao de perguntas da NAVI IA."""
from types import SimpleNamespace as NS

import pytest

from app.services import report_service as R
from app.services import services_service as SS
from app.services.navi_service import NaviService


def _patch(monkeypatch, have):
    monkeypatch.setattr(SS, "of_client", lambda db, c: {"infra": "infra" in have, "backup": "backup" in have, "endpoint": "endpoint" in have})


def test_modulos_automaticos_seguem_o_que_o_cliente_tem(monkeypatch):
    _patch(monkeypatch, {"backup", "endpoint"})
    assert R.resolve_modules(None, NS(modules=None), NS(id=1)) == ["backup", "endpoint"]
    _patch(monkeypatch, {"infra", "backup", "endpoint"})
    assert R.resolve_modules(None, NS(modules=None), NS(id=1)) == ["infra", "backup", "endpoint"]


def test_modulos_escolhidos_sao_limitados_ao_que_existe(monkeypatch):
    _patch(monkeypatch, {"infra", "backup"})
    assert R.resolve_modules(None, NS(modules=["backup", "endpoint"]), NS(id=1)) == ["backup"]
    with pytest.raises(ValueError):
        R.resolve_modules(None, NS(modules=["endpoint"]), NS(id=1))


def test_relatorio_geral_e_sempre_infra():
    assert R.resolve_modules(None, NS(modules=["backup"]), None) == ["infra"]


def test_navi_entende_o_tipo_de_servico_da_pergunta():
    k = NaviService._kind
    assert k("backups com falha agora") == "backup"
    assert k("estações sem contato") == "endpoint" and k("antivírus desligado") == "endpoint"
    assert k("top 10 hosts") == "infra" and k("qual a cor do céu") is None
