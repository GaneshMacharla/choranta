from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.models.user import User
from app.services.finance import finance_summary, period_range

router = APIRouter(prefix="/finance", tags=["Finance"])


@router.get("/summary")
def get_finance_summary(
    period: str = Query("30d", description="7d, 30d, 90d, month (this month so far) or custom"),
    start: Optional[date] = Query(None, description="First day, for a custom period"),
    end: Optional[date] = Query(None, description="Last day (inclusive), for a custom period"),
    client_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Money in, revenue, cost and profit for a period, over time and per client (admin only)."""
    try:
        range_start, range_end = period_range(period, start, end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"period": period, **finance_summary(db, range_start, range_end, client_id=client_id)}
