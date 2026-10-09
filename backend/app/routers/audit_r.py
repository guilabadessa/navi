from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditLog
from ..security import require
from ..util import to_dict, like

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def list_audit(q: str | None = None, action: str | None = None, user: str | None = None, page: int = 1,
               size: int = 50, db: Session = Depends(get_db), _=Depends(require("audit.view"))):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if user:
        stmt = stmt.where(AuditLog.user_email.ilike(like(user), escape="\\"))
    if q:
        stmt = stmt.where(AuditLog.resource.ilike(like(q), escape="\\") | AuditLog.action.ilike(like(q), escape="\\"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(AuditLog.ts.desc()).offset((page - 1) * size).limit(min(size, 200)))
    return {"total": total, "items": [to_dict(r) for r in rows],
            "actions": [a for a in db.scalars(select(AuditLog.action).distinct().order_by(AuditLog.action))]}
