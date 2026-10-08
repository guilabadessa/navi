"""NAVI — nucleo de inteligencia. Hoje: respostas deterministicas (consultas ao banco da NAVI).
Preparado para um provedor LLM plugavel: NUNCA envia segredos/credenciais ao modelo; so dados agregados autorizados."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Client, Event, ZbxHost


class LLMProvider:
    name = "none"

    def complete(self, system: str, prompt: str) -> str:  # pragma: no cover - ponto de extensao
        raise NotImplementedError


class NaviService:
    SAFE_FIELDS = ("host", "ip", "trigger_name", "severity", "status", "started_at", "recovered_at", "duration_s")

    def __init__(self, db: Session, provider: LLMProvider | None = None):
        self.db, self.provider = db, provider

    # ---- Contexto autorizado (jamais inclui settings/segredos) ----
    def top_hosts(self, days=30, n=10):
        since = datetime.now(timezone.utc) - timedelta(days=days)
        q = (select(Event.host, func.count(), func.coalesce(func.sum(Event.duration_s), 0))
             .where(Event.started_at >= since).group_by(Event.host).order_by(func.count().desc()).limit(n))
        return [{"host": h, "incidents": c, "downtime_s": int(d)} for h, c, d in self.db.execute(q)]

    def top_clients(self, days=30, n=10):
        since = datetime.now(timezone.utc) - timedelta(days=days)
        q = (select(Client.trade_name, func.count(Event.id), func.coalesce(func.sum(Event.duration_s), 0))
             .join(Event, Event.client_id == Client.id).where(Event.started_at >= since)
             .group_by(Client.trade_name).order_by(func.sum(Event.duration_s).desc().nullslast()).limit(n))
        return [{"client": c, "incidents": i, "downtime_s": int(d)} for c, i, d in self.db.execute(q)]

    def top_triggers(self, days=30, n=10):
        since = datetime.now(timezone.utc) - timedelta(days=days)
        q = (select(Event.trigger_name, func.count()).where(Event.started_at >= since)
             .group_by(Event.trigger_name).order_by(func.count().desc()).limit(n))
        return [{"trigger": t, "incidents": c} for t, c in self.db.execute(q)]

    def ask(self, question: str) -> dict:
        qn = question.lower()
        days = 30 if "30" in qn or "mês" in qn or "mes" in qn else (7 if "7" in qn or "semana" in qn else 30)
        if self.provider and self.provider.name != "none":
            ctx = {"top_hosts": self.top_hosts(days), "top_clients": self.top_clients(days), "top_triggers": self.top_triggers(days)}
            ans = self.provider.complete("Você é a NAVI, assistente do NOC da Orca TI. Responda em português, com base só no contexto.",
                                         f"Contexto: {ctx}\n\nPergunta: {question}")
            return {"answer": ans, "data": ctx, "mode": "llm"}
        if "host" in qn:
            d = self.top_hosts(days)
            return {"answer": f"Top {len(d)} hosts com mais incidentes nos últimos {days} dias.", "data": {"hosts": d}, "mode": "rules"}
        if "cliente" in qn:
            d = self.top_clients(days)
            return {"answer": f"Clientes com maior indisponibilidade nos últimos {days} dias.", "data": {"clients": d}, "mode": "rules"}
        if "trigger" in qn or "link" in qn or "problema" in qn:
            d = self.top_triggers(days)
            return {"answer": f"Problemas mais recorrentes nos últimos {days} dias.", "data": {"triggers": d}, "mode": "rules"}
        return {"answer": "Posso listar hosts, clientes ou problemas mais recorrentes (ex.: 'top 10 hosts com mais problemas'). "
                          "A análise por IA será habilitada ao configurar um provedor de LLM.", "data": {}, "mode": "rules"}
