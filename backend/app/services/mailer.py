"""E-mails transacionais da NAVI: layout unico (identidade Orca TI), assinatura configuravel (texto ou imagem)
e logo embutido. Para clientes usa SOMENTE o nome fantasia."""
import base64
import html as _html
import io
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image
from sqlalchemy.orm import Session

from .. import settings_store as S
from ..config import get_settings
from . import factory
from .email_service import split_addrs

APP = Path(__file__).resolve().parent.parent
_env = Environment(loader=FileSystemLoader(str(APP / "templates")), autoescape=select_autoescape(["html"]))
LOGO_CID, SIG_CID = "logo@navi", "assinatura@navi"
MAX_SIG_BYTES = 1_500_000


@lru_cache(maxsize=1)
def logo_bytes() -> bytes:
    im = Image.open(APP / "assets" / "brand" / "azul.png").convert("RGBA")
    im.thumbnail((520, 200))
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def sig_dir() -> Path:
    d = Path(get_settings().NAVI_STORAGE) / "email"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_signature_image(data: bytes) -> str:
    """Valida e normaliza a imagem de assinatura (max 1.5MB, redimensiona para 640px de largura)."""
    if len(data) > MAX_SIG_BYTES:
        raise ValueError("Imagem muito grande (máx. 1,5 MB)")
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:  # noqa: BLE001
        raise ValueError("Arquivo de imagem inválido") from e
    im = im.convert("RGBA")
    if im.width > 640:
        im = im.resize((640, int(im.height * 640 / im.width)), Image.LANCZOS)
    path = sig_dir() / "assinatura.png"
    im.save(path, "PNG", optimize=True)
    return str(path)


def signature(db: Session) -> dict | None:
    if S.get(db, "smtp.sig_enabled") != "1":
        return None
    mode = S.get(db, "smtp.sig_mode") or "text"
    if mode == "image":
        p = S.get(db, "smtp.sig_image")
        if p and Path(p).exists():
            return {"mode": "image", "path": p}
        return None
    text = (S.get(db, "smtp.sig_text") or "").strip()
    if not text:
        return None
    lines = [_html.escape(l) for l in text.splitlines()]
    if lines:
        lines[0] = f'<b style="color:#071a5a;">{lines[0]}</b>'
    return {"mode": "text", "html": "<br>".join(lines), "plain": text}


def _plain(kind: str, ctx: dict, sig: dict | None) -> str:
    if kind == "report":
        t = (f"Prezados,\n\nSegue em anexo o relatório de disponibilidade e SLA de {ctx['client_name']}, "
             f"referente ao período {ctx['period']}.\n\nAtenciosamente,\nNOC Orca TI")
    elif kind == "new_user":
        t = (f"Olá, {ctx['name']}!\n\n{ctx['intro']}\n\nEndereço: {ctx['url']}\nUsuário: {ctx['email']}\n"
             f"Senha temporária: {ctx['password']}\nPerfil: {ctx['role']}\n\nAltere a senha no primeiro acesso.")
    else:
        t = "\n\n".join(([ctx["greeting"]] if ctx.get("greeting") else []) + list(ctx.get("paragraphs", [])) +
                        ([ctx["highlight"]] if ctx.get("highlight") else []))
    if sig and sig["mode"] == "text":
        t += "\n\n--\n" + sig["plain"]
    return t + "\n\n— NAVI · Orca TI"


def build(db: Session, kind: str, ctx: dict, preview: bool = False):
    """Retorna (html, texto, imagens_inline). preview=True embute as imagens como data URI (para iframe)."""
    sig = signature(db)
    logo = logo_bytes()
    sig_img = Path(sig["path"]).read_bytes() if sig and sig["mode"] == "image" else None
    if preview:
        logo_src = "data:image/png;base64," + base64.b64encode(logo).decode()
        sig_src = ("data:image/png;base64," + base64.b64encode(sig_img).decode()) if sig_img else None
    else:
        logo_src, sig_src = f"cid:{LOGO_CID}", (f"cid:{SIG_CID}" if sig_img else None)
    html = _env.get_template(f"email/{kind}.html").render(logo_src=logo_src, signature=sig, signature_src=sig_src, **ctx)
    inline = [(LOGO_CID, logo, "image/png")] + ([(SIG_CID, sig_img, "image/png")] if sig_img else [])
    return html, _plain(kind, ctx, sig), inline


def send(db: Session, kind: str, to: list[str] | str, subject: str, ctx: dict, cc=None, bcc=None, attachments=None):
    html, text, inline = build(db, kind, ctx)
    to = split_addrs(to) if isinstance(to, str) else to
    factory.email(db).send(to, subject, text, split_addrs(cc) if isinstance(cc, str) else cc,
                           split_addrs(bcc) if isinstance(bcc, str) else bcc, attachments, html=html, inline=inline)


# ---- contextos prontos ----
def report_ctx(client_name: str, period: str, report_name: str, filename: str, kpis: dict | None) -> dict:
    k = None
    if kpis:
        k = {"availability": f"{kpis['availability']:.3f}%".replace(".", ","), "incidents": kpis["incidents"], "sla_met": kpis.get("sla_met")}
    return {"title": "Relatório de Disponibilidade e SLA", "subtitle": f"{client_name} · {period}", "tag": "Relatório · NOC Orca TI",
            "preheader": f"Relatório de {client_name} — {period}", "client_name": client_name, "period": period,
            "report_name": report_name, "filename": filename, "kpis": k}


def new_user_ctx(name: str, email: str, password: str, role: str, reset: bool = False) -> dict:
    url = get_settings().NAVI_PUBLIC_URL
    intro = ("Sua senha de acesso à plataforma NAVI foi redefinida pela administração. Use os dados abaixo para entrar."
             if reset else "Sua conta na plataforma NAVI — o centro de inteligência do NOC da Orca TI — foi criada. Seguem os dados de acesso.")
    return {"title": "Redefinição de acesso" if reset else "Bem-vindo à NAVI", "subtitle": "Navegação, Orientação e Assistência",
            "tag": "Acesso · NAVI", "preheader": "Seus dados de acesso à NAVI", "name": name, "email": email, "password": password,
            "role": role, "url": url, "intro": intro}


def notice_ctx(title: str, paragraphs: list[str], highlight: str | None = None, greeting: str | None = None,
               button_url: str | None = None, button_label: str | None = None) -> dict:
    return {"title": title, "tag": "Aviso · NAVI", "paragraphs": paragraphs, "highlight": highlight, "greeting": greeting,
            "button_url": button_url, "button_label": button_label}
