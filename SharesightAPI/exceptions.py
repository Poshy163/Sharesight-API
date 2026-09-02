"""Typed exceptions raised by :mod:`SharesightAPI`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Statuses that :class:`SharesightAPI.SharesightAPI` retries with backoff.
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})


class SharesightError(Exception):
    """Base exception for all Sharesight API errors."""


class SharesightAPIError(SharesightError):
    """Raised when an API request fails with a non-success status code.

    ``response_data`` and ``response_headers`` intentionally preserve the
    server's structured error information.  Sharesight error bodies often
    carry the useful ``reason`` and transaction id while the status lives only
    on the HTTP response; callers need both to distinguish authentication,
    entitlement, version and rate-limit failures reliably.
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        response_data: Any = None,
        response_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.message = message
        self.response_data = response_data
        self.response_headers = dict(response_headers or {})
        super().__init__(f"HTTP {status_code}: {message}")

    @property
    def is_unauthorised(self) -> bool:
        """True for HTTP 401 (expired, revoked or locked-out credentials)."""
        return self.status_code == 401

    @property
    def is_forbidden(self) -> bool:
        """True for HTTP 403 (entitlement, plan or scope refusals)."""
        return self.status_code == 403

    @property
    def is_not_found(self) -> bool:
        """True for HTTP 404 (unknown or inaccessible resource)."""
        return self.status_code == 404

    @property
    def is_version_unsupported(self) -> bool:
        """True when Sharesight rejects the API version for this route.

        Sharesight answers ``406 Not Acceptable`` with a reason such as
        ``"API version 3 is not supported for this endpoint"`` when a route
        exists only in another generation.  Hosts use this to fall back from
        V3 to V2 (or park the endpoint) without string-matching themselves.
        """
        if self.status_code != 406:
            return False
        text = self.message.lower()
        return "version" in text and "not supported" in text

    @property
    def is_retryable(self) -> bool:
        """True for transient statuses the client would retry on its own."""
        return self.status_code in RETRYABLE_STATUS_CODES


class SharesightAuthError(SharesightAPIError):
    """Raised when authentication or token exchange fails.

    The default keeps direct construction backward compatible while allowing
    token-endpoint failures such as HTTP 400 ``invalid_grant`` to retain their
    real status and safe OAuth error code. Raw token-endpoint bodies are not
    retained because a provider may echo submitted credentials in free text.
    """

    def __init__(
        self,
        message: str = "Authentication failed",
        *,
        status_code: int = 401,
        response_data: Any = None,
        response_headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code,
            message,
            response_data=response_data,
            response_headers=response_headers,
        )


class SharesightRateLimitError(SharesightAPIError):
    """Raised when Sharesight refuses a request because of a rate limit."""

    def __init__(
        self,
        status_code: int = 429,
        message: str = "Rate limit exceeded",
        response_data: Any = None,
        retry_after: float | None = None,
        response_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(
            status_code,
            message,
            response_data=response_data,
            response_headers=response_headers,
        )


class SharesightResponseError(SharesightError):
    """Sharesight returned a successful HTTP response with an invalid shape."""

    def __init__(self, message: str, *, response_data: object = None) -> None:
        super().__init__(message)
        self.response_data = response_data
