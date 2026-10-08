"""Financeiro do cliente a partir do Conta Azul: vinculo por CNPJ, titulos a receber e notas fiscais (somente leitura)."""
import logging
import unicodedata
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import settings_store as S
from ..models import Client, ExtTenant, FinDoc
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


def sync_people(db: Session, ca: ContaAzul) -> dict:
    """Atualiza o cadastro de pessoas do Conta Azul e vincula, automaticamente, SOMENTE por CNPJ identico.
    Vinculos manuais nunca sao alterados. Quando o CNPJ nao casa, apenas sugere (por nome) para o usuario confirmar."""
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
    linked = 0
    for c in db.scalars(select(Client).where(Client.status == "ativo")):
        if c.ca_match == "manual":
            continue
        doc = digits(c.cnpj)
        pids = by_doc.get(doc) if len(doc) >= 11 else None
        if pids:
            c.ca_person_id, c.ca_match = pids[0], "cnpj"
            linked += 1
        elif c.ca_match == "cnpj" and c.ca_person_id not in seen:
            c.ca_person_id, c.ca_match = None, None  # cadastro deixou de existir no Conta Azul
    db.flush()
    return {"people": len(seen), "linked": linked}


def suggestions(db: Session) -> dict[int, list[dict]]:
    """Para clientes sem vinculo: cadastros do Conta Azul com nome igual/parecido (apenas sugestao)."""
    people = list(db.scalars(select(ExtTenant).where(ExtTenant.source == SRC, ExtTenant.active.is_(True))))
    taken = {c.ca_person_id for c in db.scalars(select(Client)) if c.ca_person_id}
    idx = [(_norm(p.name), p) for p in people if p.ext_id not in taken]
    out: dict[int, list[dict]] = {}
    for c in db.scalars(select(Client).where(Client.status == "ativo", Client.ca_person_id.is_(None))):
        names = {n for n in (_norm(c.trade_name), _norm(c.legal_name)) if n}
        hit = [{"id": p.ext_id, "name": p.name, "doc": p.kind} for n, p in idx if n and any(n == m or (len(m) > 5 and (m in n or n in m)) for m in names)]
        if hit:
            out[c.id] = hit[:3]
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
    pid_client = {c.ca_person_id: c.id for c in db.scalars(select(Client).where(Client.ca_person_id.is_not(None)))}
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
    # link do boleto: so para titulos em aberto (limita as chamadas)
    for f in to_detail[:150]:
        try:
            lk = _links(ca.installment(f.ext_id))
            f.links = lk or None
        except ContaAzulError as e:
            log.warning("parcela %s: %s", f.ext_id, e)
            break
    return {"titles": len(seen)}


def sync_notes(db: Session, ca: ContaAzul) -> dict:
    pid_client = {c.ca_person_id: c.id for c in db.scalars(select(Client).where(Client.ca_person_id.is_not(None)))}
    doc_client = {digits(c.cnpj): c.id for c in db.scalars(select(Client)) if len(digits(c.cnpj)) >= 11}
    if not pid_client and not doc_client:
        return {"notes": 0}
    today = date.today()
    n = 0

    def put(kind_tag: str, it: dict):
        nonlocal n
        ext = str(it.get("id") or it.get("chave_acesso") or it.get("numero") or "")
        if not ext:
            return
        who = it.get("cliente") or it.get("destinatario") or {}
        cid = pid_client.get(who.get("id")) or doc_client.get(digits(who.get("documento") or who.get("cnpj") or who.get("cpf_cnpj")))
        if not cid:
            return
        key = f"{kind_tag}:{ext}"
        f = db.scalar(select(FinDoc).where(FinDoc.kind == "nota", FinDoc.ext_id == key)) or FinDoc(kind="nota", ext_id=key)
        if f.id is None:
            db.add(f)
        f.client_id = cid
        f.number = str(it.get("numero") or it.get("numero_nota") or "")[:64] or None
        f.description = (it.get("descricao") or it.get("discriminacao") or ("NFS-e" if kind_tag == "nfse" else "NF-e"))[:512]
        f.status = str(it.get("status") or it.get("situacao") or "emitida")[:32].lower()
        f.amount = float(it.get("valor") or it.get("valor_total") or it.get("total") or 0)
        f.issue_date = _d(it.get("data_emissao") or it.get("data_competencia") or it.get("data"))
        f.links = _links(it) or None
        f.synced_at = datetime.now(timezone.utc)
        n += 1

    try:
        for it in ca.service_notes((today - timedelta(days=180)).isoformat(), today.isoformat()):
            put("nfse", it)
        start = today - timedelta(days=90)
        while start < today:  # NF-e: janelas de ate 15 dias
            end = min(start + timedelta(days=14), today)
            for it in ca.product_notes(start.isoformat(), end.isoformat()):
                put("nfe", it)
            start = end + timedelta(days=1)
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


def client_finance(db: Session, client_id: int) -> dict:
    docs = list(db.scalars(select(FinDoc).where(FinDoc.client_id == client_id).order_by(FinDoc.due_date.desc().nullslast(), FinDoc.issue_date.desc().nullslast())))
    tit = [d for d in docs if d.kind == "titulo"]
    today = date.today()

    def row(d: FinDoc) -> dict:
        return {"id": d.id, "description": d.description, "number": d.number, "status": d.status, "amount": d.amount, "paid": d.paid,
                "due_date": d.due_date.isoformat() if d.due_date else None, "issue_date": d.issue_date.isoformat() if d.issue_date else None,
                "links": sorted((d.links or {}).keys())}

    open_ = [d for d in tit if d.status in ("aberto", "vencido")]
    return {
        "summary": {"open_total": round(sum((d.amount or 0) - (d.paid or 0) for d in open_), 2),
                    "overdue_total": round(sum((d.amount or 0) - (d.paid or 0) for d in open_ if d.status == "vencido"), 2),
                    "overdue_count": sum(1 for d in open_ if d.status == "vencido"), "open_count": len(open_),
                    "next_due": (lambda x: x.isoformat() if x else None)(min((d.due_date for d in open_ if d.due_date and d.due_date >= today), default=None))},
        "titles": [row(d) for d in tit if d.status != "cancelado"][:200],
        "notes": [row(d) for d in docs if d.kind == "nota"][:200],
        "last_sync": S.get(db, "contaazul.last_sync") or None,
    }
