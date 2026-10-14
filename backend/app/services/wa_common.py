"""Utilitarios comuns do WhatsApp: normalizacao de destino e a variacao do 9o digito (usados pelo gateway e pelos alertas)."""
import re


class WhatsAppError(Exception):
    pass


def normalize_target(v: str) -> str:
    """Grupo (JID/ID longo) permanece; telefone brasileiro (10/11 digitos) ganha o codigo do pais 55."""
    v = (v or "").strip()
    if "@" in v:
        return v
    if re.fullmatch(r"\d+-\d+", v):  # id de grupo antigo
        return v + "@g.us"
    d = re.sub(r"\D", "", v)
    if len(d) >= 15:  # ids de grupo (ex.: 120363...)
        return d + "@g.us"
    if len(d) in (10, 11):
        d = "55" + d
    return d


def _br_alternative(number: str) -> str | None:
    """Variacao do 9o digito (celulares BR): 55+DDD+9+8 digitos <-> 55+DDD+8 digitos."""
    if "@" in number or not number.startswith("55"):
        return None
    if len(number) == 13:
        return number[:4] + number[5:]
    if len(number) == 12:
        return number[:4] + "9" + number[4:]
    return None
