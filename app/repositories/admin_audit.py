"""Append-only administration audit log persistence and queries."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AdminAuditLog


class AdminAuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        actor_username: str,
        actor_role: str,
        action: str,
        resource_type: str,
        resource_id: str | None,
        outcome: str,
        request_id: str,
        http_method: str,
        route: str,
    ) -> AdminAuditLog:
        entry = AdminAuditLog(
            actor_username=actor_username,
            actor_role=actor_role,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            request_id=request_id,
            http_method=http_method,
            route=route,
        )
        self.session.add(entry)
        return entry

    def list_entries(
        self,
        *,
        page: int,
        page_size: int,
        actor: str | None = None,
        action: str | None = None,
    ) -> tuple[list[AdminAuditLog], int]:
        filters = []
        if actor:
            filters.append(AdminAuditLog.actor_username == actor.strip().casefold())
        if action:
            filters.append(AdminAuditLog.action == action.strip())
        base = select(AdminAuditLog).where(*filters)
        total = self.session.scalar(
            select(func.count()).select_from(AdminAuditLog).where(*filters)
        )
        entries = list(
            self.session.scalars(
                base.order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return entries, int(total or 0)
