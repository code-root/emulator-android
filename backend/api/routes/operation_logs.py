from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_current_user
from db.models import OperationLog, User, UserRole

router = APIRouter(prefix="/operation-logs", tags=["operation-logs"])


class OperationLogResponse(BaseModel):
    id: int
    device_id: Optional[int]
    user_id: Optional[int]
    action: str
    status: str
    detail: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/recent", response_model=List[OperationLogResponse])
async def recent_operation_logs(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")

    q = select(OperationLog).order_by(OperationLog.created_at.desc()).limit(limit)
    if current_user.role != UserRole.admin:
        q = q.where(OperationLog.user_id == current_user.id)
    result = await db.execute(q)
    return result.scalars().all()
