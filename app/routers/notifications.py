from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import require_current_user
from ..database import get_db
from ..models import NotificationModel, UserModel
from ..serializers import serialize_notification


router = APIRouter()


@router.get("/api/notifications")
def list_notifications(
    limit: int = Query(default=12, ge=1, le=100),
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    notifications = (
        db.query(NotificationModel)
        .filter(NotificationModel.user_id == current_user.id)
        .order_by(NotificationModel.created_at.desc(), NotificationModel.id.desc())
        .limit(limit)
        .all()
    )
    unread_count = (
        db.query(NotificationModel)
        .filter(NotificationModel.user_id == current_user.id, NotificationModel.is_read.is_(False))
        .count()
    )
    return {
        "items": [serialize_notification(notification) for notification in notifications],
        "unread_count": unread_count,
    }


@router.post("/api/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    current_user: UserModel = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    notification = (
        db.query(NotificationModel)
        .filter(NotificationModel.id == notification_id, NotificationModel.user_id == current_user.id)
        .first()
    )
    if not notification:
        raise HTTPException(status_code=404, detail="Уведомление не найдено.")

    if not notification.is_read:
        notification.is_read = True
        db.add(notification)
        db.commit()
        db.refresh(notification)

    return {
        "message": "Уведомление отмечено как прочитанное.",
        "notification": serialize_notification(notification),
    }
