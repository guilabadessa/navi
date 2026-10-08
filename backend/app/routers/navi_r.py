from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..schemas import AskIn
from ..security import require
from ..services.navi_service import NaviService

router = APIRouter(prefix="/navi", tags=["navi"])


@router.post("/ask")
def ask(body: AskIn, request: Request, db: Session = Depends(get_db), _=Depends(require("navi.use"))):
    res = NaviService(db).ask(body.question)
    audit.log(db, request, "navi_ask", "navi", detail={"q": body.question[:200]})
    db.commit()
    return res
