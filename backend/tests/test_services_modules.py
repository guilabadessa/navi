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


def test_servicos_contratados_do_acronis_mostram_so_o_que_foi_contratado():
    from app.services.protection_service import contracted_services

    def u(name, val, quota=None, status=1):
        return {"name": name, "value": val, "measurement_unit": "quantity", "offering_item": {"status": status, "quota": {"value": quota}}}

    usages = [u("pg_base_storage", 83_000_000_000), u("pg_base_workstations", 0, 6), u("pg_pack_adv_security", 6, 6), u("pg_pack_adv_dlp", 6, 6),
              u("pg_pack_adv_management", 6, 6), u("pg_base_secondary_workstations", 6), u("pw_base_servers", 0), u("pu_base_fc_seats", 1), u("pg_pack_adv_dlp_x", 0, None, 0)]
    labels = [s["label"] for s in contracted_services(usages)]
    assert "Advanced Security (antimalware + EDR)" in labels and "Advanced DLP (prevenção de vazamento de dados)" in labels
    assert "Advanced Management (RMM, patch, inventário)" in labels and "Backup de estações de trabalho" in labels
    assert not any("secundário" in x.lower() or "File Sync" in x or "servidores" in x for x in labels)  # itens padrao sem uso/cota


def test_tecnologias_do_equipamento_exigem_unidade_instalada_e_licenca():
    from app.services.protection_service import device_techs
    units = ["active_protection", "content-analyzer-edr", "dlp-unit", "cyber-scripting-executor", "mms"]
    assert set(device_techs(units, {"security": True, "dlp": True, "management": True})) == {"Antimalware", "EDR", "DLP", "RMM"}
    assert device_techs(units, {"security": False, "dlp": False, "management": False}) == []
    assert device_techs(units, {"dlp": True}) == ["DLP"]
