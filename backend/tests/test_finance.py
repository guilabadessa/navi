"""Financeiro: regras puras do mes atual, status de titulos e extracao de links."""
from datetime import date, timedelta
from types import SimpleNamespace as NS

from app.services import finance_service as F


def test_status_do_titulo():
    hoje = date(2026, 10, 8)
    assert F._title_status({"status_traduzido": "EM_ABERTO", "nao_pago": 50, "pago": 0, "data_vencimento": "2026-11-08"}, hoje) == "aberto"
    assert F._title_status({"status_traduzido": "EM_ABERTO", "nao_pago": 50, "pago": 0, "data_vencimento": "2026-09-01"}, hoje) == "vencido"
    assert F._title_status({"status_traduzido": "RECEBIDO", "nao_pago": 0, "pago": 50, "data_vencimento": "2026-09-01"}, hoje) == "pago"
    assert F._title_status({"status_traduzido": "CANCELADO", "nao_pago": 50, "pago": 0}, hoje) == "cancelado"


def test_janelas_de_15_dias():
    ws = list(F._windows(date(2026, 1, 1), date(2026, 2, 15)))
    assert ws[0] == ("2026-01-01", "2026-01-15") and ws[-1][1] == "2026-02-15"
    assert all((date.fromisoformat(b) - date.fromisoformat(a)).days <= 14 for a, b in ws)
    assert date.fromisoformat(ws[1][0]) - date.fromisoformat(ws[0][1]) == timedelta(days=1)


def test_links_so_aceita_http():
    j = {"solicitacoes_cobrancas": [{"url": "https://faturas.contaazul.com/x", "campo": "javascript:alert(1)"}], "outro": {"pdf_url": "ftp://x"}}
    assert F._links(j) == {"pdf": "https://faturas.contaazul.com/x"}


def test_normaliza_nomes_para_sugestao():
    assert F._norm("  Cocal  Comércio – Indústria ") == "cocal comercio industria"
