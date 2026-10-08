"""Normalizacao/validacao de CNPJ e telefones (armazenados sempre formatados)."""
import re


def digits(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


def cnpj_valid(d: str) -> bool:
    if len(d) != 14 or d == d[0] * 14:
        return False
    def dv(base):
        w = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2] if len(base) == 13 else [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        r = sum(int(a) * b for a, b in zip(base, w)) % 11
        return "0" if r < 2 else str(11 - r)
    return d[12] == dv(d[:12]) and d[13] == dv(d[:13])


def fmt_cnpj(v: str | None) -> str | None:
    d = digits(v)
    if not d:
        return None
    if len(d) != 14:  # o digito verificador e apenas avisado na tela (nao bloqueia o cadastro)
        raise ValueError("CNPJ deve ter 14 dígitos")
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def fmt_phone(v: str | None) -> str | None:
    d = digits(v)
    if not d:
        return None
    if len(d) in (12, 13) and d.startswith("55"):
        d = d[2:]
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    raise ValueError("Telefone inválido (use DDD + número)")


def try_phone(v):
    try:
        return fmt_phone(v)
    except ValueError:
        return v
