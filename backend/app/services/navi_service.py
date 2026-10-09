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
    # `kind`: infra | backup | endpoint (None = tudo). `cid`: restringe a um cliente.
    @staticmethod
    def _flt(since, kind=None, cid=None):
        f = [Event.started_at >= since]
        if kind:
            f.append(Event.kind == kind)
        if cid:
            f.append(Event.client_id == cid)
        return f

    def top_hosts(self, days=30, n=10, kind=None, cid=None):
        since = datetime.now(timezone.utc) - timedelta(days=days)
        q = (select(Event.host, func.count(), func.coalesce(func.sum(Event.duration_s), 0))
             .where(*self._flt(since, kind, cid)).group_by(Event.host).order_by(func.count().desc()).limit(n))
        return [{"host": h, "incidents": c, "downtime_s": int(d)} for h, c, d in self.db.execute(q)]

    def top_clients(self, days=30, n=10, kind=None):
        since = datetime.now(timezone.utc) - timedelta(days=days)
        q = (select(Client.trade_name, func.count(Event.id), func.coalesce(func.sum(Event.duration_s), 0))
             .join(Event, Event.client_id == Client.id).where(*self._flt(since, kind))
             .group_by(Client.trade_name).order_by(func.sum(Event.duration_s).desc().nullslast()).limit(n))
        return [{"client": c, "incidents": i, "downtime_s": int(d)} for c, i, d in self.db.execute(q)]

    def top_triggers(self, days=30, n=10, kind=None, cid=None):
        since = datetime.now(timezone.utc) - timedelta(days=days)
        q = (select(Event.trigger_name, func.count()).where(*self._flt(since, kind, cid))
             .group_by(Event.trigger_name).order_by(func.count().desc()).limit(n))
        return [{"trigger": t, "incidents": c} for t, c in self.db.execute(q)]

    def open_alerts(self, kind=None, cid=None, n=30):
        q = select(Event, Client.trade_name).join(Client, Client.id == Event.client_id, isouter=True).where(Event.status == "PROBLEM")
        if kind:
            q = q.where(Event.kind == kind)
        if cid:
            q = q.where(Event.client_id == cid)
        rows = self.db.execute(q.order_by(Event.severity.desc(), Event.started_at).limit(n)).all()
        return [{"client": nm or "Sem cliente", "item": e.host, "trigger": e.trigger_name, "since": e.started_at.isoformat(), "kind": e.kind} for e, nm in rows]

    def services(self):
        from . import services_service as SS
        cl = list(self.db.scalars(select(Client).where(Client.status == "ativo").order_by(Client.trade_name)))
        m = SS.of_clients(self.db, cl)
        return [{"client": c.trade_name, "infra": "sim" if m[c.id]["infra"] else "—", "backup": "sim" if m[c.id]["backup"] else "—",
                 "endpoint": "sim" if m[c.id]["endpoint"] else "—"} for c in cl]

    def _client_in(self, qn):
        best = None
        for cid, name in self.db.execute(select(Client.id, Client.trade_name)):
            n = (name or "").lower().strip()
            if len(n) >= 3 and n in qn and (best is None or len(n) > len(best[1])):
                best = (cid, n, name)
        return (best[0], best[2]) if best else (None, None)

    @staticmethod
    def _kind(qn):
        if any(w in qn for w in ("backup", "acronis")):
            return "backup"
        if any(w in qn for w in ("estaç", "estac", "endpoint", "antiv", "forticlient", " ems", "notebook", "computador")):
            return "endpoint"
        if any(w in qn for w in ("infra", "host", "link", "servidor", "zabbix")):
            return "infra"
        return None

    def ask(self, question: str) -> dict:
        qn = question.lower()
        days = 30 if "30" in qn or "mês" in qn or "mes" in qn else (7 if "7" in qn or "semana" in qn else 30)
        kind, (cid, cname) = self._kind(qn), self._client_in(qn)
        kname = {"backup": "de backup", "endpoint": "de estações/antivírus", "infra": "de infraestrutura"}.get(kind, "")
        scope = f" de {cname}" if cname else ""
        if self.provider and self.provider.name != "none":
            ctx = {"top_hosts": self.top_hosts(days, kind=kind, cid=cid), "top_clients": self.top_clients(days, kind=kind),
                   "top_triggers": self.top_triggers(days, kind=kind, cid=cid), "servicos_por_cliente": self.services(),
                   "alertas_abertos": self.open_alerts(kind, cid, 15)}
            ans = self.provider.complete("Você é a NAVI, assistente do NOC da Orca TI. Cada cliente pode ter infraestrutura (Zabbix), backup (Acronis) e/ou estações (FortiClient EMS). Responda em português, com base só no contexto.",
                                         f"Contexto: {ctx}\n\nPergunta: {question}")
            return {"answer": ans, "data": ctx, "mode": "llm"}
        if any(w in qn for w in ("serviço", "servico", "contrat", "cobertura", "quais clientes tem", "quais clientes têm", "possui")):
            d = self.services()
            return {"answer": "Serviços ativos por cliente (infraestrutura, backup e estações).", "data": {"services": d}, "mode": "rules"}
        if kind in ("backup", "endpoint") and "top" not in qn and "recorrent" not in qn and "mais" not in qn:
            d = self.open_alerts(kind, cid)
            return {"answer": (f"{len(d)} alerta(s) em aberto {kname}{scope}." if d else f"Nenhum alerta em aberto {kname}{scope}. 🎉"), "data": {"alerts": d} if d else {}, "mode": "rules"}
        if "cliente" in qn and not cid:
            d = self.top_clients(days, kind=kind)
            return {"answer": f"Clientes com maior indisponibilidade{' ' + kname if kname else ''} nos últimos {days} dias.", "data": {"clients": d}, "mode": "rules"}
        if "host" in qn or kind in ("backup", "endpoint") or cid:
            if "trigger" in qn or "recorrent" in qn or "problema" in qn:
                d = self.top_triggers(days, kind=kind, cid=cid)
                return {"answer": f"Problemas mais recorrentes{' ' + kname if kname else ''}{scope} nos últimos {days} dias.", "data": {"triggers": d}, "mode": "rules"}
            d = self.top_hosts(days, kind=kind, cid=cid)
            return {"answer": f"Top {len(d)} {'itens' if kind in ('backup', 'endpoint') else 'hosts'} com mais ocorrências{scope} nos últimos {days} dias.", "data": {"hosts": d}, "mode": "rules"}
        if "trigger" in qn or "link" in qn or "problema" in qn:
            d = self.top_triggers(days, kind=kind)
            return {"answer": f"Problemas mais recorrentes nos últimos {days} dias.", "data": {"triggers": d}, "mode": "rules"}
        return {"answer": "Posso listar hosts, clientes ou problemas mais recorrentes, alertas de backup e de estações em aberto e os serviços de cada cliente "
                          "(ex.: 'backups com falha', 'estações offline da Octo', 'quais serviços cada cliente tem'). "
                          "A análise por IA será habilitada ao configurar um provedor de LLM.", "data": {}, "mode": "rules"}
