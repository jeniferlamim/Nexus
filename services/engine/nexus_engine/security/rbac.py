"""Role-based access control. Mirrors ``nexus.role_has_permission`` in the SQL migration."""
from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    ADMIN = "admin"
    TAX_DIRECTOR = "tax_director"
    TAX_ANALYST = "tax_analyst"
    AUDITOR = "auditor"
    VIEWER = "viewer"


class Permission(str, Enum):
    VIEW = "view"
    INGEST = "ingest"
    RUN_ANALYSIS = "run_analysis"
    REVIEW = "review"            # triage + propose
    APPROVE = "approve"          # approve/return proposals (critical decisions)
    VIEW_AUDIT = "view_audit"
    EXPORT = "export"
    MANAGE_SETTINGS = "manage_settings"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: set(Permission),
    Role.TAX_DIRECTOR: {Permission.VIEW, Permission.INGEST, Permission.RUN_ANALYSIS, Permission.REVIEW,
                        Permission.APPROVE, Permission.VIEW_AUDIT, Permission.EXPORT},
    Role.TAX_ANALYST: {Permission.VIEW, Permission.INGEST, Permission.RUN_ANALYSIS, Permission.REVIEW,
                       Permission.EXPORT},
    Role.AUDITOR: {Permission.VIEW, Permission.VIEW_AUDIT, Permission.EXPORT},
    Role.VIEWER: {Permission.VIEW},
}

ROLE_LABELS = {
    Role.ADMIN: "Administrador",
    Role.TAX_DIRECTOR: "Diretor(a) Tributário(a)",
    Role.TAX_ANALYST: "Analista Tributário(a)",
    Role.AUDITOR: "Auditor(a)",
    Role.VIEWER: "Leitura",
}


def has_permission(role: str, perm: Permission) -> bool:
    try:
        return perm in ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return False
