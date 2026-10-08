from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog
from .security import client_ip


def log(db: Session, request: Request | None, action: str, resource: str | None = None, resource_id=None,
        result: str = "ok", user=None, detail: dict | None = None):
    u = user or (getattr(request.state, "user", None) if request else None)
    db.add(AuditLog(
        user_id=getattr(u, "id", None), user_email=getattr(u, "email", None), action=action, resource=resource,
        resource_id=str(resource_id) if resource_id is not None else None, result=result,
        ip=client_ip(request) if request else None, detail=detail))
    db.flush()
