"""Data access for the activity history. Every query is scoped to one user."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ActivityEvent, ActivityType


class ActivityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, **values: Any) -> ActivityEvent:
        event = ActivityEvent(**values)
        self.session.add(event)
        self.session.flush()
        return event

    def get(self, user_id: uuid.UUID, event_id: uuid.UUID) -> ActivityEvent | None:
        return self.session.scalar(
            select(ActivityEvent).where(ActivityEvent.user_id == user_id, ActivityEvent.id == event_id)
        )

    def list(
        self,
        user_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
        event_types: Sequence[ActivityType] = (),
        order: Literal["asc", "desc"] = "desc",
        limit: int,
        offset: int,
    ) -> tuple[Sequence[ActivityEvent], int]:
        conditions = [ActivityEvent.user_id == user_id]
        if project_id is not None:
            conditions.append(ActivityEvent.project_id == project_id)
        if event_types:
            conditions.append(ActivityEvent.event_type.in_(event_types))
        total = self.session.scalar(select(func.count()).select_from(ActivityEvent).where(*conditions)) or 0
        created = ActivityEvent.created_at.desc() if order == "desc" else ActivityEvent.created_at.asc()
        # Events written in one transaction share created_at (now()); the id breaks ties stably.
        items = self.session.scalars(
            select(ActivityEvent)
            .where(*conditions)
            .order_by(created, ActivityEvent.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return items, total
