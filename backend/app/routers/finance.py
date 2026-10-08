"""Financeiro (Conta Azul): configuracao, vinculo cliente x cadastro por CNPJ e visao do financeiro do cliente."""
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, settings_store as S
from ..db import get_db
from ..models import Client, ExtTenant, FinDoc, User
from ..security import current_user, require, user_has
from ..services import finance_service as F
from ..services.contaazul_service import ContaAzul, ContaAzulError, DEFAULT_REDIRECT, digits
from .portal import _client_for

router = APIRouter(tags=["finance"])


def _cfg(db: Session) -> dict:
    ca = ContaAzul(db)
    return {"client_id": ca.cid, "secret_set": bool(ca.secret), "redirect_uri": ca.redirect, "enabled": S.get(db, "contaazul.enabled") == "1",
            "authorized": ca.authorized, "auth_error": bool(S.get(db, "contaazul.auth_error")), "last_sync": S.get(db, "contaazul.last_sync") or None,
            "authorize_url": ca.authorize_url() if ca.configured else None}


class CfgIn(BaseModel):
    client_id: str = Field(min_length=5, max_length=200)
    client_secret: str | None = Field(default=None, max_length=300)
    redirect_uri: str = Field(default=DEFAULT_REDIRECT, max_length=300)
    enabled: bool = True


class CodeIn(BaseModel):
    code: str = Field(min_length=3, max_length=2000)  # o codigo ou a URL inteira para a qual o Conta Azul redirecionou


class LinkIn(BaseModel):
    person_id: str | None = Field(default=None, max_length=64)


@router.get("/finance/config")
def config(db: Session = Depends(get_db), _=Depends(require("settings.view"))):
    return _cfg(db)


@router.put("/finance/config")
def config_put(body: CfgIn, request: Request, db: Session = Depends(get_db), me=Depends(require("settings.edit"))):
    S.put(db, "contaazul.client_id", body.client_id.strip(), me.email)
    S.put(db, "contaazul.redirect_uri", body.redirect_uri.strip(), me.email)
    S.put(db, "contaazul.enabled", "1" if body.enabled else "0", me.email)
    if body.client_secret:
        S.put(db, "contaazul.client_secret", body.client_secret.strip(), me.email)
    audit.log(db, request, "settings_contaazul", "settings", detail={"client_id": body.client_id, "secret_changed": bool(body.client_secret), "enabled": body.enabled})
    db.commit()
    return _cfg(db)


@router.post("/finance/authorize")
def authorize(body: CodeIn, request: Request, db: Session = Depends(get_db), me=Depends(require("settings.edit"))):
    raw = body.code.strip()
    m = re.search(r"[?&]code=([^&#\s]+)", raw)
    code = m.group(1) if m else raw
    try:
        ContaAzul(db).exchange_code(code)
        res = {"ok": True, "detail": "Conta Azul autorizado. A renovação do acesso passa a ser automática."}
    except ContaAzulError as e:
        res = {"ok": False, "detail": f"{e} O código vale por 3 minutos e só pode ser usado uma vez."}
    audit.log(db, request, "contaazul_authorize", "settings", result="ok" if res["ok"] else "falha")
    db.commit()
    return res


@router.get("/finance/callback")
def callback(request: Request, code: str = "", error: str = "", db: Session = Depends(get_db), me=Depends(require("settings.edit"))):
    """Retorno do login do Conta Azul (URL de redirecionamento do aplicativo): troca o codigo pelos tokens."""
    ok = False
    if code and not error:
        try:
            ContaAzul(db).exchange_code(code)
            ok = True
        except ContaAzulError:
            ok = False
    audit.log(db, request, "contaazul_authorize", "settings", result="ok" if ok else "falha", detail={"via": "callback"})
    db.commit()
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=\"1;url=/cliente/configuracoes?ca={'ok' if ok else 'erro'}\">"
                        f"<body style=\"font-family:sans-serif;padding:40px\">{'Conta Azul autorizado. Redirecionando…' if ok else 'Não foi possível autorizar. Redirecionando…'}</body>")


@router.post("/finance/test")
def test(request: Request, db: Session = Depends(get_db), _=Depends(require("settings.edit"))):
    try:
        res = ContaAzul(db).test()
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "detail": str(e)[:300]}
    audit.log(db, request, "contaazul_test", "settings", result="ok" if res["ok"] else "falha")
    db.commit()
    return res


@router.post("/finance/sync")
def sync(request: Request, db: Session = Depends(get_db), _=Depends(require("finance.view"))):
    try:
        res = F.sync_all(db, ContaAzul(db))
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(502, str(e)[:300])
    audit.log(db, request, "contaazul_sync", "settings", detail=res)
    db.commit()
    return res


@router.get("/finance/links")
def links(db: Session = Depends(get_db), _=Depends(require("finance.view"))):
    """Clientes da NAVI x cadastros do Conta Azul (vinculo por CNPJ; sugestoes por nome precisam de confirmacao)."""
    sug = F.suggestions(db)
    people = {t.ext_id: t for t in db.scalars(select(ExtTenant).where(ExtTenant.source == "contaazul"))}
    rows = []
    for c in db.scalars(select(Client).where(Client.status == "ativo").order_by(Client.trade_name)):
        p = people.get(c.ca_person_id) if c.ca_person_id else None
        rows.append({"client_id": c.id, "name": c.trade_name, "cnpj": c.cnpj, "person_id": c.ca_person_id, "match": c.ca_match,
                     "person_name": p.name if p else None, "person_doc": p.kind if p else None,
                     "suggestions": sug.get(c.id, []), "has_cnpj": len(digits(c.cnpj)) >= 11})
    return {"clients": rows, "people": [{"id": t.ext_id, "name": t.name, "doc": t.kind} for t in sorted(people.values(), key=lambda x: x.name.lower()) if t.active]}


@router.put("/finance/clients/{cid}/link")
def link(cid: int, body: LinkIn, request: Request, db: Session = Depends(get_db), me=Depends(require("finance.view"))):
    if not user_has(me, "clients.edit"):
        raise HTTPException(403, "Sem permissão")
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    if body.person_id:
        if not db.scalar(select(ExtTenant.id).where(ExtTenant.source == "contaazul", ExtTenant.ext_id == body.person_id)):
            raise HTTPException(404, "Cadastro não encontrado no Conta Azul. Sincronize e tente novamente.")
        c.ca_person_id, c.ca_match = body.person_id, "manual"
    else:
        c.ca_person_id, c.ca_match = None, "manual"  # desvinculado manualmente: a busca por CNPJ nao refaz o vinculo
    # titulos do vinculo anterior saem do cliente
    for d in db.scalars(select(FinDoc).where(FinDoc.client_id == cid)):
        db.delete(d)
    audit.log(db, request, "contaazul_link", "client", cid, detail={"person_id": body.person_id})
    db.commit()
    return {"ok": True}


def _finance_client(db: Session, user: User, client_id: int | None) -> Client:
    need = "portal.finance" if user.role == "CLIENTE" else "finance.view"
    if not user_has(user, need):
        raise HTTPException(403, "Você não tem permissão para acessar o financeiro")
    return _client_for(db, user, client_id)


@router.get("/portal/finance")
def portal_finance(client_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = _finance_client(db, user, client_id)
    out = F.client_finance(db, c.id)
    out["linked"] = bool(c.ca_person_id)
    return out


@router.get("/portal/finance/{doc_id}/{tag}")
def portal_finance_link(doc_id: int, tag: str, request: Request, client_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = _finance_client(db, user, client_id)
    d = db.get(FinDoc, doc_id)
    if not d or d.client_id != c.id or tag not in (d.links or {}):
        raise HTTPException(404)
    audit.log(db, request, "finance_doc_open", "finance", doc_id, detail={"tag": tag, "client_id": c.id})
    db.commit()
    return RedirectResponse(d.links[tag], status_code=302)
