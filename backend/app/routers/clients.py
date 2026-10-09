import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..formats import try_phone
from ..models import (UserClient, AlertRule, Client, ClientContact, ClientHost, ClientHostGroup, Event, MaintenanceWindow, Report, ReportRun,
                      User, ZbxHost, ZbxHostGroup, ExtAsset, ExtTenant)
from pydantic import BaseModel, EmailStr, Field

from ..schemas import ClientIn
from ..security import require, user_has
from .. import portal_access as PA
from ..services import destinations, event_service, services_service
from ..services import kpi_service, maintenance_service
from ..util import titlecase, to_dict, like

router = APIRouter(prefix="/clients", tags=["clients"])


def _full(db: Session, c: Client) -> dict:
    d = to_dict(c)
    gmap = {g.groupid: g.name for g in db.scalars(select(ZbxHostGroup))}
    d["group_ids"] = [g.zbx_groupid for g in c.groups]
    d["groups"] = [{"groupid": g.zbx_groupid, "name": gmap.get(g.zbx_groupid, g.name)} for g in c.groups]
    d["host_ids"] = [h.zbx_hostid for h in c.hosts]
    d["contacts"] = [to_dict(x) for x in c.contacts]
    d["services"] = services_service.of_client(db, c)
    d["destinations"] = destinations.describe(c)
    tens = list(db.scalars(select(ExtTenant).where(ExtTenant.client_id == c.id)))
    d["acronis_tenant_ids"] = [t.id for t in tens if t.source == "acronis"]
    d["ems_tenant_ids"] = [t.id for t in tens if t.source == "ems"]
    return d


def _apply(db: Session, c: Client, b: ClientIn):
    for k, v in b.model_dump(exclude={"group_ids", "host_ids", "contacts", "acronis_tenant_ids", "ems_tenant_ids"}).items():
        setattr(c, k, v)
    gmap = {g.groupid: g.name for g in db.scalars(select(ZbxHostGroup))}
    want_g, want_h = list(dict.fromkeys(b.group_ids)), list(dict.fromkeys(b.host_ids))
    # atualizacao por diferenca (evita violar a unicidade ao recriar linhas iguais)
    c.groups[:] = [g for g in c.groups if g.zbx_groupid in want_g]
    have = {g.zbx_groupid for g in c.groups}
    c.groups.extend(ClientHostGroup(zbx_groupid=g, name=gmap.get(g)) for g in want_g if g not in have)
    c.hosts[:] = [h for h in c.hosts if h.zbx_hostid in want_h]
    have = {h.zbx_hostid for h in c.hosts}
    c.hosts.extend(ClientHost(zbx_hostid=h) for h in want_h if h not in have)
    c.contacts = [ClientContact(name=x.get("name", "")[:255], role=x.get("role"), email=x.get("email"), phone=try_phone(x.get("phone")))
                  for x in b.contacts if x.get("name")]


def _link_tenants(db: Session, c: Client, b: ClientIn):
    """Associa/desassocia clientes do Acronis e sites do EMS a este cliente (marcados no cadastro, como os host groups do Zabbix)."""
    for src, ids in (("acronis", b.acronis_tenant_ids), ("ems", b.ems_tenant_ids)):
        if ids is None:
            continue
        want = set(ids)
        for t in db.scalars(select(ExtTenant).where(ExtTenant.source == src)):
            if t.id in want:
                t.client_id = c.id
            elif t.client_id == c.id:
                t.client_id = None
    db.flush()


def _digits(v: str | None) -> str:
    return "".join(ch for ch in (v or "") if ch.isdigit())


def _dupe_check(db: Session, name: str, cnpj: str | None, exclude_id: int | None = None):
    """Impede cadastro duplicado (ex.: duplo clique em Salvar): mesmo nome ou mesmo CNPJ."""
    for o in db.scalars(select(Client)):
        if o.id == exclude_id:
            continue
        if (o.trade_name or "").strip().lower() == (name or "").strip().lower():
            raise HTTPException(409, f"Já existe um cliente com este nome ({o.trade_name}).")
        if _digits(cnpj) and _digits(o.cnpj) == _digits(cnpj):
            raise HTTPException(409, f"Já existe um cliente com este CNPJ ({o.trade_name}).")


@router.get("")
def list_clients(q: str | None = None, db: Session = Depends(get_db), _=Depends(require("clients.view"))):
    stmt = select(Client).order_by(Client.trade_name)
    if q:
        stmt = stmt.where(Client.trade_name.ilike(like(q), escape="\\") | Client.cnpj.ilike(like(q), escape="\\"))
    open_by = dict(db.execute(select(Event.client_id, func.count()).where(Event.status == "PROBLEM")
                              .group_by(Event.client_id)).all())
    pu = dict(db.execute(select(User.client_id, func.count()).where(User.role == "CLIENTE").group_by(User.client_id)).all())
    for k_, n_ in db.execute(select(UserClient.client_id, func.count()).group_by(UserClient.client_id)).all():
        pu[k_] = pu.get(k_, 0) + n_
    out = []
    rows = list(db.scalars(stmt))
    svc = services_service.of_clients(db, rows)
    for c in rows:
        d = to_dict(c)
        d["services"] = svc[c.id]
        d["group_count"], d["open_events"], d["portal_users"] = len(c.groups), open_by.get(c.id, 0), pu.get(c.id, 0)
        out.append(d)
    return out


def _addr(j: dict) -> str | None:
    cep = "".join(ch for ch in (j.get("cep") or "") if ch.isdigit()).zfill(8)
    street = " ".join(x for x in [j.get("tipo"), j.get("logradouro")] if x)
    num = (j.get("numero") or "").strip()
    if num.upper().replace("/", "").replace(" ", "") == "SN":
        num = "S/N"
    out = street + (f", {num}" if num else "")
    if j.get("complemento"):
        out += f" - {j['complemento'].strip()}"
    if j.get("bairro"):
        out += f" - {j['bairro']}"
    out = titlecase(out) if out else ""
    out = out.replace("S/n", "S/N")
    if cep.strip("0"):
        out += f" - CEP {cep[:5]}-{cep[5:]}"
    return out or None


def _parse_brasilapi(x: dict) -> dict:
    ph = "".join(ch for ch in (x.get("ddd_telefone_1") or "") if ch.isdigit())
    return {"razao": x["razao_social"], "fantasia": x.get("nome_fantasia"), "tipo": x.get("descricao_tipo_de_logradouro"), "logradouro": x.get("logradouro"),
            "numero": x.get("numero"), "complemento": x.get("complemento"), "bairro": x.get("bairro"), "cep": x.get("cep"), "cidade": x.get("municipio"),
            "uf": x.get("uf"), "phone": ph or None, "email": (x.get("email") or "").lower() or None, "situacao": x.get("descricao_situacao_cadastral")}


def _parse_cnpjws(x: dict) -> dict:
    e = x["estabelecimento"]
    ph = "".join(ch for ch in f"{e.get('ddd1') or ''}{e.get('telefone1') or ''}" if ch.isdigit())
    return {"razao": x["razao_social"], "fantasia": e.get("nome_fantasia"), "tipo": e.get("tipo_logradouro"), "logradouro": e.get("logradouro"),
            "numero": e.get("numero"), "complemento": e.get("complemento"), "bairro": e.get("bairro"), "cep": e.get("cep"),
            "cidade": (e.get("cidade") or {}).get("nome"), "uf": (e.get("estado") or {}).get("sigla"), "phone": ph or None,
            "email": (e.get("email") or "").lower() or None, "situacao": (e.get("situacao_cadastral") or "").upper()}


_cnpj_cache: dict[str, tuple[float, dict]] = {}


@router.get("/cnpj/{cnpj}")
def cnpj_lookup(cnpj: str, _=Depends(require("clients.edit"))):
    """Consulta publica do CNPJ (BrasilAPI / dados da Receita Federal) para preencher o cadastro. So o CNPJ sai do servidor."""
    import time
    import httpx
    d = "".join(ch for ch in cnpj if ch.isdigit())
    if len(d) != 14:
        raise HTTPException(422, "CNPJ deve ter 14 dígitos")
    hit = _cnpj_cache.get(d)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    j = None
    for url, parse in ((f"https://brasilapi.com.br/api/cnpj/v1/{d}", _parse_brasilapi), (f"https://publica.cnpj.ws/cnpj/{d}", _parse_cnpjws)):
        try:
            r = httpx.get(url, timeout=12, headers={"User-Agent": "NAVI/1.0"})
        except httpx.HTTPError:
            continue
        if r.status_code == 404:
            raise HTTPException(404, "CNPJ não encontrado na base da Receita Federal")
        if r.status_code == 400:
            raise HTTPException(422, "CNPJ inválido")
        if r.status_code == 200:
            try:
                j = parse(r.json())
                break
            except (KeyError, TypeError, ValueError):
                continue
    if j is None:
        raise HTTPException(502, "A consulta de CNPJ está indisponível no momento. Preencha manualmente ou tente de novo em instantes.")
    out = {"legal_name": titlecase(j["razao"]), "trade_name": titlecase(j["fantasia"] or j["razao"]), "address": _addr(j), "city": titlecase(j["cidade"]),
           "state": j["uf"], "phone": j["phone"], "email": j["email"], "situacao": j["situacao"]}
    _cnpj_cache[d] = (time.time(), out)
    return out


@router.post("")
def create(body: ClientIn, request: Request, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    body.trade_name, body.legal_name, body.contact_name = titlecase(body.trade_name), titlecase(body.legal_name), titlecase(body.contact_name)
    _dupe_check(db, body.trade_name, body.cnpj)
    c = Client()
    _apply(db, c, body)
    db.add(c)
    db.flush()
    _link_tenants(db, c, body)
    audit.log(db, request, "client_create", "client", c.id, detail={"name": c.trade_name})
    db.commit()
    event_service.relink_events(db)
    return _full(db, c)


@router.get("/{cid}")
def get(cid: int, db: Session = Depends(get_db), _=Depends(require("clients.view"))):
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    return _full(db, c)


@router.put("/{cid}")
def update(cid: int, body: ClientIn, request: Request, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    body.trade_name, body.legal_name, body.contact_name = titlecase(body.trade_name), titlecase(body.legal_name), titlecase(body.contact_name)
    _dupe_check(db, body.trade_name, body.cnpj, cid)
    _apply(db, c, body)
    _link_tenants(db, c, body)
    audit.log(db, request, "client_update", "client", c.id, detail={"name": c.trade_name})
    db.commit()
    from ..services import protection_service
    protection_service.relink(db)
    event_service.relink_events(db)
    return _full(db, c)


def _impact(db: Session, cid: int) -> dict:
    rep_ids = list(db.scalars(select(Report.id).where(Report.client_id == cid)))
    runs = db.scalars(select(ReportRun).where((ReportRun.client_id == cid) | (ReportRun.report_id.in_(rep_ids)) if rep_ids else (ReportRun.client_id == cid))).all()
    return {"reports": len(rep_ids), "pdfs": len(runs), "rules": db.scalar(select(func.count()).select_from(AlertRule).where(AlertRule.client_id == cid)),
            "events": db.scalar(select(func.count()).select_from(Event).where(Event.client_id == cid)),
            "portal_users": len(PA.users_of(db, cid)),
            "windows": db.scalar(select(func.count()).select_from(MaintenanceWindow).where(MaintenanceWindow.client_id == cid))}


@router.get("/{cid}/impact")
def impact(cid: int, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    if not db.get(Client, cid):
        raise HTTPException(404)
    return _impact(db, cid)


@router.delete("/{cid}")
def delete_client(cid: int, request: Request, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    """Exclui o cliente e o que depende dele (relatorios, PDFs, rotinas, regras, janelas, usuarios do portal).
    Os eventos ficam no historico, apenas sem cliente. O Zabbix nao e alterado."""
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    info = _impact(db, cid)
    rep_ids = list(db.scalars(select(Report.id).where(Report.client_id == cid)))
    runs = db.scalars(select(ReportRun).where((ReportRun.client_id == cid) | (ReportRun.report_id.in_(rep_ids)) if rep_ids else (ReportRun.client_id == cid))).all()
    for r in runs:
        if r.file_path:
            Path(r.file_path).unlink(missing_ok=True)
        db.delete(r)
    for r in db.scalars(select(Report).where(Report.client_id == cid)):
        db.delete(r)  # rotinas (schedules) saem por cascata
    for u in PA.users_of(db, cid):
        PA.detach(db, u, cid)  # quem acompanha outros clientes continua com eles
    for e in db.scalars(select(Event).where(Event.client_id == cid)):
        e.client_id = None
    logo = Path(c.logo_path) if c.logo_path else None
    name = c.trade_name
    db.delete(c)
    audit.log(db, request, "client_delete", "client", cid, detail={"name": name, **info})
    db.commit()
    if logo:
        logo.unlink(missing_ok=True)
    return {"ok": True, **info}


@router.post("/{cid}/logo")
def upload_logo(cid: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                _=Depends(require("clients.edit"))):
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".svg", ".webp"):
        raise HTTPException(422, "Formato inválido (use PNG, JPG, SVG ou WEBP)")
    dest_dir = Path(get_settings().NAVI_STORAGE) / "logos"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"client_{cid}{ext}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    c.logo_path = str(dest)
    audit.log(db, request, "client_logo", "client", c.id)
    db.commit()
    return {"ok": True}


def client_hosts(db: Session, c: Client) -> list[ZbxHost]:
    ids = {h.zbx_hostid for h in c.hosts}
    gids = {g.zbx_groupid for g in c.groups}
    return [h for h in db.scalars(select(ZbxHost).where(ZbxHost.active.is_(True)))
            if h.hostid in ids or (set(h.group_ids or []) & gids)]


@router.get("/{cid}/dashboard")
def dashboard(cid: int, days: float = 30, db: Session = Depends(get_db), _=Depends(require("clients.view"))):
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    days = round(max(1 / 24, min(days, 90)), 4)  # limite = retencao local de eventos
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    hosts = client_hosts(db, c)
    hids = [h.hostid for h in hosts]
    allev = list(db.scalars(select(Event).where(Event.client_id == cid, Event.started_at < end,
                                                (Event.recovered_at.is_(None)) | (Event.recovered_at > start))
                            .order_by(Event.started_at.desc())))
    evs = [e for e in allev if (e.kind or "infra") == "infra"]
    k = kpi_service.compute(evs, [{"hostid": h.hostid, "name": h.name, "ip": h.ip} for h in hosts], start, end, None,
                            exclude=maintenance_service.exclusions(db, cid, start, end))
    active = [to_dict(e) for e in allev if e.status == "PROBLEM"]
    links = [h for h in hosts if any(w in (h.name or "").lower() for w in ("link", "wan", "vpn", "fortigate", "fw"))]
    from ..services import protection_service as P
    from .protection import asset_status
    pc, nowx = P.cfg(db), datetime.now(timezone.utc)

    def prot(source, status_fn):
        tids = list(db.scalars(select(ExtTenant.id).where(ExtTenant.client_id == cid, ExtTenant.source == source)))
        if not tids:
            return {"enabled": False}
        assets = list(db.scalars(select(ExtAsset).where(ExtAsset.ext_tenant_id.in_(tids), ExtAsset.active.is_(True), ExtAsset.ignored.is_(False))))
        counts: dict = {}
        for a in assets:
            st = status_fn(a)
            counts[st] = counts.get(st, 0) + 1
        kind = "backup" if source == "acronis" else "endpoint"
        alerts = [{"id": e.id, "host": e.host, "trigger_name": e.trigger_name, "severity": e.severity, "started_at": e.started_at.isoformat()}
                  for e in db.scalars(select(Event).where(Event.kind == kind, Event.status == "PROBLEM", Event.client_id == cid).order_by(Event.severity.desc()))]
        return {"enabled": True, "total": len(assets), "counts": counts, "alerts": alerts}

    backup = prot("acronis", lambda a: asset_status(a, pc, nowx))
    endpoints = prot("ems", lambda a: P.ems_status(a, pc["ems_offline_days"], nowx))
    from ..services import finance_service
    return {"contracts": finance_service.client_contracts(db, cid), "services": services_service.of_client(db, c), "backup": backup, "endpoints": endpoints, "client": to_dict(c), "kpis": k, "hosts": [{"hostid": h.hostid, "name": h.name, "ip": h.ip,
            "available": h.available, "status": h.status} for h in hosts], "active_events": active,
            "history": [to_dict(e) for e in allev[:100]], "links": len(links),
            "reports": [to_dict(r, {"kpis"}) for r in db.scalars(select(ReportRun).where(ReportRun.client_id == cid)
                                                                 .order_by(ReportRun.generated_at.desc()).limit(10))],
            "rules": [to_dict(r) for r in db.scalars(select(AlertRule).where(AlertRule.client_id == cid))]}


# ---------------- usuarios do portal do cliente ----------------
class PortalUserIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    finance: bool = False  # acesso ao financeiro (Conta Azul): exige que quem concede tenha finance.view
    min_sev: int = Field(default=4, ge=0, le=5)  # menor severidade que a pessoa enxerga no portal (padrao: Alta)


class PortalUserPatch(BaseModel):
    finance: bool | None = None
    min_sev: int | None = Field(default=None, ge=0, le=5)
    active: bool | None = None


@router.get("/{cid}/portal-users")
def portal_users(cid: int, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    if not db.get(Client, cid):
        raise HTTPException(404)
    return [{"id": u.id, "name": u.name, "email": u.email, "active": u.active, "invite_pending": u.invite_pending,
             "last_login": u.last_login.isoformat() if u.last_login else None,
             "finance": "portal.finance" in (u.extra_perms or []), "min_sev": u.portal_min_sev,
             "other_clients": max(0, len(PA.client_ids(db, u)) - 1)}
            for u in PA.users_of(db, cid)]


@router.post("/{cid}/portal-users")
def invite_portal_user(cid: int, body: PortalUserIn, request: Request, db: Session = Depends(get_db), me=Depends(require("clients.edit"))):
    """Convida uma pessoa do cliente para o portal (somente leitura, restrito a este cliente)."""
    import secrets
    from .users import send_invite
    from ..security import hash_password
    if not db.get(Client, cid):
        raise HTTPException(404)
    if body.finance and not user_has(me, "finance.view"):
        raise HTTPException(403, "Você não tem permissão para conceder acesso ao financeiro")
    body.name = titlecase(body.name)
    ex = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if ex:
        # a mesma pessoa (ex.: prestador) pode acompanhar varios clientes com o mesmo login
        if ex.role != "CLIENTE":
            raise HTTPException(409, "Este e-mail pertence a um usuário da equipe Orca")
        if PA.belongs(db, ex, cid):
            raise HTTPException(409, "Esta pessoa já tem acesso a este cliente")
        db.add(UserClient(user_id=ex.id, client_id=cid))
        audit.log(db, request, "portal_user_link", "user", ex.id, detail={"email": ex.email, "client_id": cid})
        db.commit()
        return {"id": ex.id, "linked": True, "email_status": f"{ex.email} já tinha acesso à NAVI: o cliente foi adicionado ao login existente (sem novo convite)"}
    u = User(email=body.email.lower(), name=body.name, role="CLIENTE", client_id=cid, active=True,
             password_hash=hash_password(secrets.token_urlsafe(48)), invite_pending=True, invited_at=datetime.now(timezone.utc),
             extra_perms=["portal.finance"] if body.finance else [], portal_min_sev=body.min_sev)
    db.add(u)
    db.flush()
    audit.log(db, request, "portal_user_invite", "user", u.id, detail={"email": u.email, "client_id": cid})
    db.commit()
    return {"id": u.id, "email_status": send_invite(db, u)}


class PortalSettingsIn(BaseModel):
    notify_boleto: bool | None = None
    notify_monthly: bool | None = None


@router.get("/{cid}/portal-settings")
def portal_settings(cid: int, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    return {"notify_boleto": bool(c.notify_boleto), "notify_monthly": bool(c.notify_monthly), "finance_linked": bool(c.ca_person_id)}


@router.put("/{cid}/portal-settings")
def portal_settings_put(cid: int, body: PortalSettingsIn, request: Request, db: Session = Depends(get_db), me=Depends(require("clients.edit"))):
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    if body.notify_boleto is not None:
        if body.notify_boleto and not user_has(me, "finance.view"):
            raise HTTPException(403, "Você não tem permissão para ativar avisos financeiros")
        c.notify_boleto = body.notify_boleto
    if body.notify_monthly is not None:
        c.notify_monthly = body.notify_monthly
    audit.log(db, request, "portal_settings", "client", cid, detail=body.model_dump(exclude_none=True))
    db.commit()
    return {"ok": True}


@router.post("/{cid}/portal-settings/test/{kind}")
def portal_settings_test(cid: int, kind: str, request: Request, db: Session = Depends(get_db), me=Depends(require("clients.edit"))):
    """Envia um exemplo do aviso SOMENTE para o e-mail de quem clicou (nunca para o cliente)."""
    from ..services import notice_service as N
    from datetime import date as _d
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    if kind == "mensal":
        today = _d.today()
        py, pm = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        subj, ctx = N.monthly_ctx(db, c, None, py, pm)
        from ..services import mailer
        mailer.send(db, "notice", me.email, "[TESTE] " + subj, ctx)
        res = {"sent": 1}
    elif kind == "boleto":
        from ..models import FinDoc
        from ..services import mailer
        d = db.scalar(select(FinDoc).where(FinDoc.client_id == cid, FinDoc.kind == "titulo", FinDoc.status.in_(["aberto", "vencido"])).order_by(FinDoc.due_date))
        if not d:
            raise HTTPException(422, "Este cliente não tem títulos em aberto para o exemplo")
        subj, ctx = N.boleto_mail(c, [("boleto_d3", d)], me.name)
        mailer.send(db, "notice", me.email, "[TESTE] " + subj, ctx)
        res = {"sent": 1}
    else:
        raise HTTPException(404)
    audit.log(db, request, "portal_notice_test", "client", cid, detail={"kind": kind, "to": me.email})
    db.commit()
    return {**res, "to": me.email}


@router.patch("/{cid}/portal-users/{uid}")
def patch_portal_user(cid: int, uid: int, body: PortalUserPatch, request: Request, db: Session = Depends(get_db), me=Depends(require("clients.edit"))):
    u = db.get(User, uid)
    if not u or not PA.belongs(db, u, cid):
        raise HTTPException(404)
    if body.min_sev is not None:
        u.portal_min_sev = body.min_sev
    if body.finance is not None:
        if not user_has(me, "finance.view"):
            raise HTTPException(403, "Você não tem permissão para alterar o acesso ao financeiro")
        perms = [p for p in (u.extra_perms or []) if p != "portal.finance"]
        u.extra_perms = perms + (["portal.finance"] if body.finance else [])
    if body.active is not None:
        u.active = body.active
    audit.log(db, request, "portal_user_update", "user", uid, detail={"finance": body.finance, "active": body.active, "min_sev": body.min_sev})
    db.commit()
    return {"ok": True}


@router.post("/{cid}/portal-users/{uid}/invite")
def resend_portal_invite(cid: int, uid: int, request: Request, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    from .users import send_invite
    u = db.get(User, uid)
    if not u or not PA.belongs(db, u, cid):
        raise HTTPException(404)
    audit.log(db, request, "portal_user_resend", "user", uid)
    db.commit()
    return {"email_status": send_invite(db, u, reset=not u.invite_pending)}


@router.delete("/{cid}/portal-users/{uid}")
def delete_portal_user(cid: int, uid: int, request: Request, db: Session = Depends(get_db), _=Depends(require("clients.edit"))):
    u = db.get(User, uid)
    if not u or not PA.belongs(db, u, cid):
        raise HTTPException(404)
    email = u.email
    PA.detach(db, u, cid)
    audit.log(db, request, "portal_user_delete", "user", uid, detail={"email": email})
    db.commit()
    return {"ok": True}
