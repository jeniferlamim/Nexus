from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ErrorSeverity(str, Enum):
    BLOCKING = "BLOCKING"  # record is discarded
    WARNING = "WARNING"    # record kept, issue reported


@dataclass
class RecordError:
    source: str
    locator: str
    field: str
    value: str
    message: str
    severity: ErrorSeverity = ErrorSeverity.BLOCKING

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "locator": self.locator,
            "field": self.field,
            "value": self.value[:200],
            "message": self.message,
            "severity": self.severity.value,
        }


class IngestionError(Exception):
    """File-level failure (unreadable, wrong format, missing mandatory columns)."""
