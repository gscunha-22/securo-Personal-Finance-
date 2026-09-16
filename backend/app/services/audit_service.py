import json
import logging
import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AppNotification, AuditEvent

logger = logging.getLogger(__name__)


async def record(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | str | None,
    summary: str,
    extra: Optional[dict] = None,
) -> AuditEvent:
    event = AuditEvent(
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        summary=summary[:500],
        extra=_safe_extra(extra),
    )
    session.add(event)
    logger.info(
        "audit action=%s entity=%s id=%s workspace=%s",
        action,
        entity_type,
        event.entity_id,
        workspace_id,
    )
    return event


async def notify(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    kind: str,
    title: str,
    body: str,
    extra: Optional[dict] = None,
) -> AppNotification:
    item = AppNotification(
        workspace_id=workspace_id,
        user_id=user_id,
        kind=kind,
        title=title[:255],
        body=body,
        extra=_safe_extra(extra),
    )
    session.add(item)
    return item


def _safe_extra(extra: Optional[dict]) -> Optional[dict]:
    if not extra:
        return None
    dumped = json.dumps(extra, default=str)
    lowered = dumped.lower()
    if any(token in lowered for token in ("bearer ", "refresh_token", "client_secret", "password")):
        return {"redacted": True}
    return extra
