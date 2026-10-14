from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from app.services import ticket_service as TS


def q(name="SOC", emails="soc@orcati.com.br", wa="120@g.us", active=True):
    return NS(name=name, notify_emails=emails, notify_wa_jid=wa, active=active)


def ticket(queue=None, watchers=None, client_id=1, number=1042, status="aberto", priority="media", subject="Sem internet"):
    return NS(number=number, client_id=client_id, queue_id=1 if queue else None, subject=subject, status=status, priority=priority,
             watchers=watchers or [])


def test_notify_usa_fila_e_observadores_sem_duplicar():
    db = MagicMock()
    cliente = NS(trade_name="Echoes Capital")
    fila = q()
    t = ticket(queue=fila, watchers=[NS(kind="email", target="soc@orcati.com.br", label=None),  # mesmo e-mail da fila: nao duplica envio
                                     NS(kind="whatsapp", target="5511999990000", label="Analista")])
    db.get.side_effect = lambda model, id: cliente if model.__name__ == "Client" else fila
    with patch.object(TS, "_mail_send") as mail, patch.object(TS, "_wa_send") as wa:
        TS.notify(db, t, "aberto")
        assert mail.call_args.args[1] == ["soc@orcati.com.br"]  # uniao (set) elimina a duplicata
        assert wa.call_count == 2  # grupo da fila + numero do observador


def test_notify_fila_inativa_nao_recebe_mas_observador_recebe():
    db = MagicMock()
    cliente = NS(trade_name="PBX")
    fila = q(active=False)
    t = ticket(queue=fila, watchers=[NS(kind="email", target="cliente@ex.com.br", label=None)])
    db.get.side_effect = lambda model, id: cliente if model.__name__ == "Client" else fila
    with patch.object(TS, "_mail_send") as mail, patch.object(TS, "_wa_send") as wa:
        TS.notify(db, t, "atualizado")
        assert mail.call_args.args[1] == ["cliente@ex.com.br"]
        wa.assert_not_called()


def test_notify_sem_fila_nem_observador_nao_envia_nada():
    db = MagicMock()
    db.get.return_value = NS(trade_name="X")
    t = ticket()
    with patch.object(TS, "_mail_send") as mail, patch.object(TS, "_wa_send") as wa:
        TS.notify(db, t, "encerrado")
        mail.assert_not_called()
        wa.assert_not_called()


def test_notify_lembrete_de_escalonamento_nao_quebra():
    db = MagicMock()
    db.get.return_value = NS(trade_name="X")
    t = ticket(status="aguardando_orca")
    with patch.object(TS, "_mail_send"), patch.object(TS, "_wa_send"):
        TS.notify(db, t, "lembrete", extra_text="sem resposta ha 24h")  # kind usado pelo job de escalonamento
