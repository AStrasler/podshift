"""Exceptions for eight sleep.

Podshift drops the Home Assistant base class so this snapshot imports outside
Home Assistant. status and error_details are unchanged from the vendored copy.
"""

from typing import Any


class BaseEightSleepError(Exception):
    """Base exception for eight sleep."""


class RequestError(BaseEightSleepError):
    """Exception for eight sleep request failures."""

    def __init__(
        self,
        message: str,
        status: int | None = None,
        error_details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error_details = error_details


class NotAuthenticatedError(BaseEightSleepError):
    """Exception for eight sleep authentication errors.."""
