from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.rbac import Role


class Principal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    user_id: uuid.UUID
    login: str
    role: Role
    persisted: bool = True


class DevLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9-]+$")
    role: Role = Role.OPERATOR


class PrincipalResponse(BaseModel):
    user_id: uuid.UUID
    login: str
    role: Role
