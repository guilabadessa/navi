"""Financeiro do cliente a partir do Conta Azul: vinculo por CNPJ, titulos a receber e notas fiscais (somente leitura)."""
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import settings_store as S
from ..models import Client, ClientPerson, ExtTenant, FinDoc
from ..util import titlecase
from .contaazul_service import ContaAzul, ContaAzulError, digits

log = logging.getLogger("navi.finance")
SRC = "contaazul"


def _norm(v: str | None) -> str:
    v = unicodedata.normalize("NFKD", v or "").encode("ascii", "ignore").decode().lower()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in v).split())


def _d(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _links(obj, depth: int = 0) -> dict:
    """Procura, de forma tolerante, enderecos de PDF/XML/boleto na resposta (o formato varia por tipo de documento)."""
    out: dict = {}
    if depth > 4:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            kk = str(k).lower()
            if isinstance(v, str) and v.startswith("http"):
                tag = "xml" if "xml" in kk else "boleto" if "boleto" in kk else "pdf" if ("pdf" in kk or "danfe" in kk or "link" in kk or "url" in kk) else None
                if tag:
                    out.setdefault(tag, v)
            else:
                for t, u in _links(v, depth + 1).items():
                    out.setdefault(t, u)
    elif isinstance(obj, list):
        for v in obj[:10]:
            for t, u in _links(v, depth + 1).items():
                out.setdefault(t, u)
    return out


def person_map(db: Session) -> dict[str, int]:
    """cadastro do Conta Azul -> cliente da NAVI (vinculos ativos)."""
    return {cp.person_id: cp.client_id for cp in db.scalars(select(ClientPerson).where(ClientPerson.match != "blocked"))}


def refresh_primary(db: Session):
    """Mantem Client.ca_person_id = primeiro cadastro vinculado (usado para saber se o financeiro esta vinculado)."""
    first: dict[int, ClientPerson] = {}
    for cp in db.scalars(select(ClientPerson).where(ClientPerson.match != "blocked").order_by(ClientPerson.person_id)):
        first.setdefault(cp.client_id, cp)
    for c in db.scalars(select(Client)):
        cp = first.get(c.id)
        c.ca_person_id, c.ca_match = (cp.person_id, cp.match) if cp else (None, None)
    db.flush()


def sync_people(db: Session, ca: ContaAzul) -> dict:
    """Atualiza o cadastro de pessoas do Conta Azul e vincula, automaticamente, SOMENTE por CNPJ identico ao do cliente.
    Vinculos manuais e desvinculos nunca sao alterados. Outros CNPJs do mesmo cliente sao adicionados manualmente."""
    seen: set[str] = set()
    existing = {t.ext_id: t for t in db.scalars(select(ExtTenant).where(ExtTenant.source == SRC))}
    by_doc: dict[str, list[str]] = {}
    for p in ca.people():
        pid = p.get("id")
        if not pid:
            continue
        seen.add(pid)
        doc = digits(p.get("documento"))
        t = existing.get(pid)
        if t is None:
            t = ExtTenant(source=SRC, ext_id=pid, name=(p.get("nome") or "")[:255])
            db.add(t)
            existing[pid] = t
        t.name, t.kind, t.active, t.synced_at = (p.get("nome") or "")[:255], doc[:32] or None, bool(p.get("ativo", True)), datetime.now(timezone.utc)
        if doc:
            by_doc.setdefault(doc, []).append(pid)
    for pid, t in existing.items():
        if pid not in seen:
            t.active = False
    db.flush()
    rows = {cp.person_id: cp for cp in db.scalars(select(ClientPerson))}
    linked = 0
    for c in db.scalars(select(Client).where(Client.status == "ativo")):
        doc = digits(c.cnpj)
        for pid in (by_doc.get(doc) or []) if len(doc) >= 11 else []:
            if pid not in rows:  # cadastro livre: vincula; se ja pertence a outro cliente ou foi desvinculado, respeita
                rows[pid] = ClientPerson(person_id=pid, client_id=c.id, match="cnpj")
                db.add(rows[pid])
                linked += 1
    for pid, cp in list(rows.items()):
        if cp.match == "cnpj" and pid not in seen:
            db.delete(cp)  # cadastro deixou de existir no Conta Azul
    db.flush()
    refresh_primary(db)
    return {"people": len(seen), "linked": linked}


def suggestions(db: Session) -> dict[int, list[dict]]:
    """Cadastros ainda livres que PARECEM ser do cliente: mesma raiz de CNPJ (filiais) ou nome igual/parecido. Apenas sugestao."""
    taken = {cp.person_id for cp in db.scalars(select(ClientPerson).where(ClientPerson.match != "blocked"))}
    people = [p for p in db.scalars(select(ExtTenant).where(ExtTenant.source == SRC, ExtTenant.active.is_(True))) if p.ext_id not in taken]
    out: dict[int, list[dict]] = {}
    for c in db.scalars(select(Client).where(Client.status == "ativo")):
        names = {n for n in (_norm(c.trade_name), _norm(c.legal_name)) if n}
        root = digits(c.cnpj)[:8] if len(digits(c.cnpj)) == 14 else ""
        hit = []
        for p in people:
            same_root = bool(root and p.kind and len(p.kind) == 14 and p.kind[:8] == root)
            n = _norm(p.name)
            by_name = bool(n and any(n == m or (len(m) > 5 and (m in n or n in m)) for m in names))
            if same_root or by_name:
                hit.append({"id": p.ext_id, "name": titlecase(p.name), "doc": p.kind, "why": "mesma raiz de CNPJ" if same_root else "nome parecido"})
        if hit:
            out[c.id] = hit[:5]
    return out


def _title_status(it: dict, today: date) -> str:
    st = str(it.get("status_traduzido") or it.get("status") or "").upper()
    if "CANCEL" in st:
        return "cancelado"
    nao_pago, pago = float(it.get("nao_pago") or 0), float(it.get("pago") or 0)
    if nao_pago <= 0.004 and pago > 0:
        return "pago"
    due = _d(it.get("data_vencimento"))
    return "vencido" if due and due < today else "aberto"


def sync_titles(db: Session, ca: ContaAzul) -> dict:
    pid_client = person_map(db)
    if not pid_client:
        return {"titles": 0}
    today = date.today()
    de, ate = (today - timedelta(days=400)).isoformat(), (today + timedelta(days=365)).isoformat()
    seen: set[str] = set()
    old = {f.ext_id: f for f in db.scalars(select(FinDoc).where(FinDoc.kind == "titulo"))}
    to_detail: list[FinDoc] = []
    for it in ca.receivables(de, ate):
        pid = (it.get("cliente") or {}).get("id")
        cid = pid_client.get(pid)
        if not cid or not it.get("id"):
            continue
        seen.add(it["id"])
        f = old.get(it["id"])
        if f is None:
            f = FinDoc(kind="titulo", ext_id=it["id"])
            db.add(f)
        f.client_id, f.person_id = cid, pid
        f.description = (it.get("descricao") or "")[:512]
        f.status, f.amount, f.paid = _title_status(it, today), float(it.get("total") or 0), float(it.get("pago") or 0)
        f.due_date, f.issue_date, f.synced_at = _d(it.get("data_vencimento")), _d(it.get("data_competencia")), datetime.now(timezone.utc)
        if f.status in ("aberto", "vencido"):
            to_detail.append(f)
    for ext_id, f in old.items():
        if ext_id not in seen:
            db.delete(f)
    db.flush()
    # link do boleto/fatura: so para titulos em aberto (limita as chamadas)
    for f in to_detail[:200]:
        try:
            det = ca.installment(f.ext_id)
        except ContaAzulError as e:
            log.warning("parcela %s: %s", f.ext_id, e)
            break
        lk: dict = {}
        for sol in det.get("solicitacoes_cobrancas") or []:
            url = sol.get("url")
            if url and str(url).startswith("http"):
                # a pagina da fatura do Conta Azul reune o boleto e a nota fiscal: e o unico endereco que a API fornece
                lk.setdefault("boleto" if sol.get("tipo_solicitacao_cobranca") == "BOLETO" else "fatura", url)
        f.links = lk or _links(det) or None
    return {"titles": len(seen)}


def _windows(start: date, end: date):
    """A API do Conta Azul aceita no maximo 15 dias por consulta de notas fiscais."""
    while start <= end:
        e = min(start + timedelta(days=14), end)
        yield start.isoformat(), e.isoformat()
        start = e + timedelta(days=1)


_NOTE_ST = {"EMITIDA": "emitida", "CANCELAMENTO_MANUAL": "cancelada", "CANCELADA": "cancelada", "AUTORIZADA": "emitida"}


def sync_notes(db: Session, ca: ContaAzul) -> dict:
    """Notas fiscais SEPARADAS das vendas: NFS-e (documento do cliente) e NF-e (destinatario por nome)."""
    pid_client = person_map(db)
    by_doc: dict[str, tuple[int, str | None]] = {}
    by_name: dict[str, tuple[int, str | None]] = {}
    for t in db.scalars(select(ExtTenant).where(ExtTenant.source == SRC, ExtTenant.ext_id.in_(list(pid_client) or ["-"]))):
        cid = pid_client[t.ext_id]
        if t.kind:
            by_doc.setdefault(digits(t.kind), (cid, t.ext_id))
        if _norm(t.name):
            by_name.setdefault(_norm(t.name), (cid, t.ext_id))
    for c in db.scalars(select(Client).where(Client.id.in_(set(pid_client.values()) or {-1}))):
        for nm in (c.trade_name, c.legal_name):
            if _norm(nm):
                by_name.setdefault(_norm(nm), (c.id, None))
    if not by_doc and not by_name:
        return {"notes": 0}
    today = date.today()
    have = db.scalar(select(FinDoc.id).where(FinDoc.kind == "nota").limit(1)) is not None
    start = today - timedelta(days=(75 if have else 400))  # primeira carga busca o ultimo ano; depois so o recente
    old = {f.ext_id: f for f in db.scalars(select(FinDoc).where(FinDoc.kind == "nota"))}
    n = 0

    def put(key: str, who: tuple[int, str | None] | None, **kw):
        nonlocal n
        if not who:
            return
        cid, pid = who
        f = old.get(key)
        if f is None:
            f = FinDoc(kind="nota", ext_id=key)
            db.add(f)
            old[key] = f
        f.client_id, f.person_id = cid, pid
        for k_, v_ in kw.items():
            setattr(f, k_, v_)
        f.synced_at = datetime.now(timezone.utc)
        n += 1

    try:
        for de, ate in _windows(start, today):
            for it in ca.service_notes(de, ate):
                st = _NOTE_ST.get(str(it.get("status") or "").upper(), "cancelada" if "CANCEL" in str(it.get("status") or "").upper() else str(it.get("status") or "").lower()[:32])
                num = it.get("numero_nfse")
                put(f"nfse:{it.get('id')}", by_doc.get(digits(it.get("documento_cliente"))), number=str(num) if num else None,
                    description=f"NFS-e {num or '(RPS ' + str(it.get('numero_rps')) + ')'} · Venda {it.get('numero_venda') or '—'}"[:512],
                    status=st or "emitida", amount=float(it.get("valor_total_nfse") or 0), issue_date=_d(it.get("data_competencia")), links=None)
            for it in ca.product_notes(de, ate):
                num = it.get("numero_nota")
                put(f"nfe:{it.get('chave_acesso') or num}", by_name.get(_norm(it.get("nome_destinatario"))), number=str(num) if num else None,
                    description=f"NF-e {num}"[:512], status=_NOTE_ST.get(str(it.get("status") or "").upper(), str(it.get("status") or "").lower()[:32] or "emitida"),
                    amount=float(it.get("valor_total") or 0) or None, issue_date=_d(it.get("data_emissao")), links=None)
    except ContaAzulError as e:
        log.warning("notas fiscais: %s", e)
        return {"notes": n, "error": str(e)[:160]}
    return {"notes": n}


def sync_all(db: Session, ca: ContaAzul) -> dict:
    if not ca.configured or not ca.authorized or S.get(db, "contaazul.enabled") != "1":
        return {"skipped": True}
    res = {}
    for fn in (sync_people, sync_titles, sync_notes):
        res.update(fn(db, ca))
        db.commit()
    S.put(db, "contaazul.last_sync", datetime.now(timezone.utc).isoformat(), "contaazul")
    db.commit()
    return res


_NF = re.compile(r"NFS-?e\s*:?\s*(\d+)", re.I)
_MONTHS = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _ym(d: date | None) -> str | None:
    return f"{d.year:04d}-{d.month:02d}" if d else None


def client_finance(db: Session, client_id: int, month: str | None = None) -> dict:
    """month = 'AAAA-MM' (padrao: mes atual) ou 'all'. Titulos em atraso de meses anteriores sempre aparecem."""
    docs = list(db.scalars(select(FinDoc).where(FinDoc.client_id == client_id).order_by(FinDoc.due_date.desc().nullslast(), FinDoc.issue_date.desc().nullslast())))
    tit = [d for d in docs if d.kind == "titulo" and d.status != "cancelado"]
    notes = [d for d in docs if d.kind == "nota"]
    today = date.today()
    cur = _ym(today)
    month = month or cur
    if month != "all" and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        month = cur
    open_ = [d for d in tit if d.status in ("aberto", "vencido")]
    lo, hi = _ym(date(today.year - 1, today.month, 1)), _ym(date(today.year + (1 if today.month > 1 else 0), (today.month - 2) % 12 + 1, 1))
    months = sorted(m for m in ({_ym(d.due_date) for d in tit if d.due_date} | {_ym(d.issue_date) for d in notes if d.issue_date} | {cur}) if m and lo <= m <= hi)

    def row(d: FinDoc) -> dict:
        m = _NF.search(d.description or "")
        return {"id": d.id, "description": d.description, "number": d.number or (m.group(1) if m else None), "nfse": m.group(1) if m else None,
                "status": d.status, "amount": d.amount, "paid": d.paid,
                "due_date": d.due_date.isoformat() if d.due_date else None, "issue_date": d.issue_date.isoformat() if d.issue_date else None,
                "links": sorted((d.links or {}).keys())}

    sel_t = [d for d in tit if month == "all" or _ym(d.due_date) == month]
    late = [d for d in open_ if d.status == "vencido" and d not in sel_t and month != "all"]
    sel_n = [d for d in notes if month == "all" or _ym(d.issue_date) == month]
    nxt = min((d.due_date for d in open_ if d.due_date and d.due_date >= today), default=None)
    label = "Todos os períodos" if month == "all" else f"{_MONTHS[int(month[5:])].capitalize()} de {month[:4]}"
    return {
        "month": month, "month_label": label, "months": [{"value": m, "label": f"{_MONTHS[int(m[5:])].capitalize()} de {m[:4]}"} for m in months if m],
        "summary": {"open_total": round(sum((d.amount or 0) - (d.paid or 0) for d in open_), 2),
                    "overdue_total": round(sum((d.amount or 0) - (d.paid or 0) for d in open_ if d.status == "vencido"), 2),
                    "overdue_count": sum(1 for d in open_ if d.status == "vencido"), "open_count": len(open_),
                    "month_total": round(sum(d.amount or 0 for d in sel_t), 2), "month_paid": round(sum(d.paid or 0 for d in sel_t), 2),
                    "next_due": nxt.isoformat() if nxt else None},
        "late": [row(d) for d in sorted(late, key=lambda x: x.due_date or today)][:100],
        "titles": [row(d) for d in sorted(sel_t, key=lambda x: (x.due_date or today))][:300],
        "notes": [row(d) for d in sel_n][:300],
        "last_sync": S.get(db, "contaazul.last_sync") or None,
    }
