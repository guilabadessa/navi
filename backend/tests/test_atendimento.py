from unittest.mock import MagicMock

from app.models import WaConversation, WaMessage
from app.security import has_perm


def test_permissoes_atendimento():
    assert has_perm("ANALISTA_NOC", "atendimento.act") and has_perm("GESTOR", "atendimento.view")
    assert has_perm("VISUALIZADOR", "atendimento.view") and not has_perm("VISUALIZADOR", "atendimento.act")
    assert not has_perm("CLIENTE", "atendimento.view")


def test_modelo_conversa():
    c = WaConversation(jid="5514999999999@s.whatsapp.net", queue="geral", state="menu")
    assert c.state == "menu" and hasattr(WaMessage, "conversation_id") and hasattr(WaMessage, "sent_by")
