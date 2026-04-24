from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    github_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    login: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    workspaces: Mapped[list["WorkspaceMember"]] = relationship(back_populates="user")


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    schema_name: Mapped[str] = mapped_column(String, unique=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    memberships: Mapped[list["WorkspaceMember"]] = relationship(back_populates="workspace")
    invites: Mapped[list["WorkspaceInvite"]] = relationship(back_populates="workspace")
    api_keys: Mapped[list["WorkspaceApiKey"]] = relationship(back_populates="workspace")
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="workspace")
    api_events: Mapped[list["WorkspaceApiEvent"]] = relationship(back_populates="workspace")
    ingest_runs: Mapped[list["WorkspaceIngestRun"]] = relationship(back_populates="workspace")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String, default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="workspaces")


class WorkspaceInvite(Base):
    __tablename__ = "workspace_invites"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_workspace_invite_token_hash"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    invited_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String, default="member")
    token_hash: Mapped[str] = mapped_column(String, index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    workspace: Mapped[Workspace] = relationship(back_populates="invites")


class WorkspaceApiKey(Base):
    __tablename__ = "workspace_api_keys"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_workspace_api_key_token_hash"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    label: Mapped[str] = mapped_column(String)
    token_prefix: Mapped[str] = mapped_column(String, index=True)
    token_hash: Mapped[str] = mapped_column(String, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    workspace: Mapped[Workspace] = relationship(back_populates="api_keys")
    events: Mapped[list["WorkspaceApiEvent"]] = relationship(back_populates="api_key")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    summary: Mapped[str] = mapped_column(String)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)

    workspace: Mapped[Workspace] = relationship(back_populates="audit_events")


class WorkspaceApiEvent(Base):
    __tablename__ = "workspace_api_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    api_key_id: Mapped[str | None] = mapped_column(ForeignKey("workspace_api_keys.id"), nullable=True, index=True)
    route: Mapped[str] = mapped_column(String, index=True)
    method: Mapped[str] = mapped_column(String, default="GET")
    status_code: Mapped[int] = mapped_column(default=200)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)

    workspace: Mapped[Workspace] = relationship(back_populates="api_events")
    api_key: Mapped[WorkspaceApiKey | None] = relationship(back_populates="events")


class WorkspaceIngestRun(Base):
    __tablename__ = "workspace_ingest_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    api_key_id: Mapped[str | None] = mapped_column(ForeignKey("workspace_api_keys.id"), nullable=True)
    source_name: Mapped[str] = mapped_column(String, default="manual import")
    source_type: Mapped[str] = mapped_column(String, default="text")
    layer: Mapped[str] = mapped_column(String, default="episodic")
    memory_type: Mapped[str] = mapped_column(String, default="narrative")
    item_count: Mapped[int] = mapped_column(default=0)
    character_count: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String, default="completed")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)

    workspace: Mapped[Workspace] = relationship(back_populates="ingest_runs")
