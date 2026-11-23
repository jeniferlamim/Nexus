"""Authentication → Principal (user + tenant + role).

AUTH_MODE=supabase (production): ``Authorization: Bearer <Supabase JWT>`` verified with
    SUPABASE_JWT_SECRET; the tenant comes from ``X-Nexus-Tenant`` and MUST match a membership.
AUTH_MODE=dev (local demo only): ``X-Nexus-User`` (user id) + ``X-Nexus-Tenant``. Refused when
    NEXUS_ENV=production.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..persistence.db import Membership
from .rbac import ROLE_PERMISSIONS, Permission, Role


@dataclass(frozen=True)
class Principal:
    user_id: str
    name: str
    email: str
    tenant_id: str
    role: str

    @property
    def permissions(self) -> set[Permission]:
        return ROLE_PERMISSIONS.get(Role(self.role), set())

    def can(self, perm: Permission) -> bool:
        return perm in self.permissions


def _auth_mode() -> str:
    mode = os.environ.get("AUTH_MODE", "dev")
    if mode == "dev" and os.environ.get("NEXUS_ENV") == "production":
        raise RuntimeError("AUTH_MODE=dev é proibido em produção")
    return mode


def _user_id_from_jwt(token: str) -> str:
    import jwt

    secret = os.environ.get("SUPABASE_JWT_SECRET")
    if not secret:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "SUPABASE_JWT_SECRET não configurado")
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido") from exc
    return claims["sub"]


def resolve_principal(session: Session, *, authorization: str | None, x_user: str | None,
                      x_tenant: str | None) -> Principal:
    if _auth_mode() == "supabase":
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Autenticação requerida")
        user_id = _user_id_from_jwt(authorization.split(" ", 1)[1])
    else:
        if not x_user:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Cabeçalho X-Nexus-User ausente (modo dev)")
        user_id = x_user

    stmt = select(Membership).where(Membership.user_id == user_id)
    if x_tenant:
        stmt = stmt.where(Membership.tenant_id == x_tenant)
    membership = session.execute(stmt.order_by(Membership.id).limit(1)).scalar_one_or_none()
    if membership is None:
        # Same response whether the tenant exists or not: no tenant enumeration.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sem acesso a esta empresa")
    u = membership.user
    return Principal(user_id=u.id, name=u.name, email=u.email, tenant_id=membership.tenant_id,
                     role=membership.role)


def require(principal: Principal, perm: Permission) -> None:
    if not principal.can(perm):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Permissão necessária: {perm.value}")


__all__ = ["Principal", "resolve_principal", "require", "Depends", "Header"]
