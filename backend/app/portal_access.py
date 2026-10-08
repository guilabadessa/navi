"""Quais clientes um usuario do portal pode acompanhar: o principal (users.client_id) + os vinculos adicionais."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User, UserClient


def client_ids(db: Session, user: User) -> list[int]:
    ids = [user.client_id] if user.client_id else []
    ids += [c for c in db.scalars(select(UserClient.client_id).where(UserClient.user_id == user.id)) if c not in ids]
    return ids


def users_of(db: Session, cid: int) -> list[User]:
    extra = select(UserClient.user_id).where(UserClient.client_id == cid)
    return list(db.scalars(select(User).where(User.role == "CLIENTE", (User.client_id == cid) | User.id.in_(extra)).order_by(User.name)))


def belongs(db: Session, u: User, cid: int) -> bool:
    return u.role == "CLIENTE" and cid in client_ids(db, u)


def detach(db: Session, u: User, cid: int) -> bool:
    """Remove o acesso da pessoa a este cliente. Retorna True se o usuario inteiro foi excluido (nao tinha mais nenhum cliente)."""
    links = [c for c in db.scalars(select(UserClient).where(UserClient.user_id == u.id))]
    mine = next((x for x in links if x.client_id == cid), None)
    if mine:
        db.delete(mine)
        return False
    if u.client_id == cid:
        if links:
            u.client_id = links[0].client_id  # promove outro cliente a principal
            db.delete(links[0])
            return False
        db.delete(u)
        return True
    return False
