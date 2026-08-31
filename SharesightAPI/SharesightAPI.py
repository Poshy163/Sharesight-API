import asyncio
import json
import logging
import os
import random
import tempfile
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

import aiofiles
import aiofiles.os
import aiohttp

from .exceptions import (
    SharesightAPIError,
    SharesightAuthError,
    SharesightRateLimitError,
    SharesightResponseError,
)
from .models import (
    AdjustmentResponse,
    AdjustmentsResponse,
    CashAccount,
    CashAccountsResponse,
    CashAccountTransactionsResponse,
    CountriesResponse,
    CouponRatesResponse,
    CurrenciesResponse,
    CustomInvestment,
    CustomInvestmentPricesResponse,
    CustomInvestmentsResponse,
    GroupsResponse,
    HoldingResponse,
    HoldingsResponse,
    PayoutsResponse,
    PerformanceReport,
    PerformanceResponse,
    Portfolio,
    PortfolioResponse,
    PortfoliosResponse,
    TradesResponse,
    ValueSeriesResponse,
)

logger = logging.getLogger(__name__)

_SAFE_OAUTH_ERROR_CODES = frozenset(
    {
        "access_denied",
        "invalid_client",
        "invalid_grant",
        "invalid_request",
        "invalid_scope",
        "server_error",
        "temporarily_unavailable",
        "unauthorized_client",
        "unsupported_grant_type",
        "unsupported_response_type",
    }
)


@dataclass(frozen=True, slots=True)
class SharesightResponse:
    """A parsed response together with the HTTP metadata callers need.

    The original request helpers continue returning only ``data`` for backward
    compatibility.  ``get_api_response`` opts into this richer result so host
    applications can observe Sharesight's rate-limit headers without relying
    on mutable client-wide "last response" state, which would be racy when
    requests run concurrently.
    """

    data: Any
    status: int
    headers: Mapping[str, str]
    url: str


def _redact_token_data(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of OAuth data with every credential fully redacted.

    Even a token prefix/suffix is unnecessary in logs and can help correlate a
    credential across systems. Keep useful expiry/scope metadata, but never
    reproduce bearer, refresh, identity, or client-secret values.
    """

    def redact_nested(value: Any) -> Any:
        if isinstance(value, Mapping):
            return _redact_token_data(value)
        if isinstance(value, (list, tuple)):
            return [redact_nested(item) for item in value]
        return value

    redacted: dict[str, Any] = {}
    for key, value in data.items():
        normalised = str(key).lower()
        if value and (
            normalised.endswith("_token")
            or normalised == "token"
            or "secret" in normalised
            or normalised == "authorization_code"
        ):
            redacted[key] = "[redacted]"
        else:
            redacted[key] = redact_nested(value)
    return redacted


def _safe_oauth_error_data(data: Any) -> dict[str, Any]:
    """Retain only non-secret OAuth error structure for exceptions and logs."""
    if not isinstance(data, Mapping):
        return {}
    safe: dict[str, Any] = {}
    error = data.get("error")
    if isinstance(error, str) and error in _SAFE_OAUTH_ERROR_CODES:
        safe["error"] = error
    elif error is not None:
        safe["error"] = "[omitted]"
    if "error_description" in data:
        # Descriptions are free text and some providers echo request details.
        # Their contents therefore cannot be made reliably safe by pattern
        # matching; preserve only the fact that one was supplied.
        safe["error_description"] = "[omitted]"
    return safe


def _safe_token_log_data(data: Any) -> dict[str, Any] | str:
    """Return an allowlist of OAuth metadata that is safe to log."""
    if isinstance(data, Mapping):
        safe = _safe_oauth_error_data(data)
        for key in ("token_type", "expires_in", "scope"):
            value = data.get(key)
            if isinstance(value, (str, int, float, bool)):
                safe[key] = value
        return safe
    return "[non-object OAuth response omitted]"


class SharesightAPI:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        authorization_code: str,
        redirect_uri: str,
        token_url: str,
        api_url_base: str,
        use_token_file: bool = True,
        debugging: bool = False,
        token_file_name: str | None = None,
        session: aiohttp.ClientSession | None = None,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        raise_for_status: bool = False,
        token_expiry_margin: float = 60.0,
        request_timeout: float | aiohttp.ClientTimeout | None = 30.0,
        retry_jitter: float = 0.25,
        max_retry_delay: float = 300.0,
        preserve_decimal: bool = False,
    ) -> None:
        """
        Initializes the API client with the necessary credentials and settings.

        Parameters:
        - client_id: The client ID for the API.
        - client_secret: The client secret for the API.
        - authorization_code: The authorization code for OAuth2.
        - redirect_uri: The redirect URI registered with the API.
        - token_url: The URL to obtain the OAuth2 token.
        - api_url_base: The base URL for the API endpoints.
        - use_token_file: Make a default token file, or not. True by default, set false to manage the token data yourself
        - debugging: Optional; enables debugging mode if set to True. Defaults to False.
        - token_file_name: Optional; the filename to store the token. Defaults to 'sharesight_token_<client_id>.txt' if not provided.
        - session: Optional; an existing aiohttp.ClientSession to reuse.
        - max_retries: Maximum number of retries for transient errors (429, 500, 502, 503). Defaults to 3.
        - retry_backoff: Base backoff time in seconds for retries (exponential). Defaults to 1.0.
        - raise_for_status: When True, non-success responses raise the Sharesight* exceptions
          instead of returning the raw error dict. Defaults to False (backward compatible).
        - token_expiry_margin: Refresh the access token this many seconds before it actually
          expires, to avoid a request starting with a token that dies mid-flight. Defaults to 60.
        - request_timeout: Total timeout for each HTTP request. Pass None to inherit the
          caller-supplied session default. Defaults to 30 seconds.
        - retry_jitter: Maximum random fraction added to exponential retry delays to avoid
          synchronised retry storms. Defaults to 0.25 (25 percent).
        - max_retry_delay: Upper bound for retry delays, including Retry-After. Defaults to 300.
        - preserve_decimal: Decode JSON fractional numbers as Decimal instead of float.
          Defaults to False for backward compatibility.
        """
        self.__client_id = client_id
        self.__client_secret = client_secret
        self.__authorization_code: str | None = authorization_code
        self.__redirect_uri = redirect_uri
        self.__token_url = token_url
        self.__api_url_base = api_url_base
        self.__use_token_file = use_token_file
        self.__token_file = token_file_name or f"sharesight_token_{self.__client_id}.txt"
        self.__access_token: str | None = None
        self.__refresh_token: str | None = None
        self.__load_auth_code: str | None = None
        self.__token_expiry: float | None = None
        self.__debugging = debugging
        if max_retries < 0:
            raise ValueError("max_retries must be zero or greater")
        if retry_backoff < 0:
            raise ValueError("retry_backoff must be zero or greater")
        if token_expiry_margin < 0:
            raise ValueError("token_expiry_margin must be zero or greater")
        if isinstance(request_timeout, (int, float)) and request_timeout <= 0:
            raise ValueError("request_timeout must be greater than zero or None")
        if retry_jitter < 0:
            raise ValueError("retry_jitter must be zero or greater")
        if max_retry_delay < 0:
            raise ValueError("max_retry_delay must be zero or greater")
        self.__max_retries = max_retries
        self.__retry_backoff = retry_backoff
        self.__retry_jitter = retry_jitter
        self.__max_retry_delay = max_retry_delay
        self.__request_timeout = (
            aiohttp.ClientTimeout(total=request_timeout)
            if isinstance(request_timeout, (int, float))
            else request_timeout
        )
        self.__preserve_decimal = preserve_decimal
        self.__tokens_loaded = False
        self.__raise_for_status = raise_for_status
        self.__token_expiry_margin = token_expiry_margin
        # Serialise token refreshes so concurrent callers don't all hit the
        # OAuth endpoint simultaneously (which can trip Sharesight's lockout).
        self.__token_lock = asyncio.Lock()

        # A library must not reconfigure the host application's root logging;
        # only adjust our own logger's level.
        if debugging:
            logger.setLevel(logging.DEBUG)

        # Defer creating our own ClientSession until first use so it is created
        # inside the running event loop — creating one in __init__ (outside a
        # coroutine) is deprecated in modern aiohttp.
        self.session = session
        self._created_session = session is None
        self._closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    def _get_session(self) -> aiohttp.ClientSession:
        """Return the aiohttp session, creating one lazily inside the loop."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
            self._created_session = True
            # A closed client has historically been reusable.  If a request
            # reopens it, clear the lifecycle guard so the replacement owned
            # session is closed by the next close() call as well.
            self._closed = False
        return self.session

    def _json_loads(self, value: str) -> Any:
        """Decode a JSON string using the configured numeric precision policy."""
        if self.__preserve_decimal:
            return json.loads(value, parse_float=Decimal)
        return json.loads(value)

    async def _read_response_data(self, response: aiohttp.ClientResponse) -> Any:
        """Parse a response body without turning an empty 2xx into an error.

        Sharesight's write endpoints may legitimately answer with 201 or 204.
        The old parser treated every status except exactly 200 as a failure and
        synthesised an ``error`` dict for an empty 204 body.  Empty successful
        bodies now normalise to ``{}``; non-JSON error bodies retain the status
        for callers that use the legacy non-raising mode.
        """
        if response.status == 204:
            return {}
        try:
            return await response.json(loads=self._json_loads)
        except (aiohttp.ContentTypeError, json.JSONDecodeError, ValueError):
            text = await response.text()
            if not text and 200 <= response.status < 300:
                return {}
            return {"error": text, "status_code": response.status}

    async def get_token_data(self) -> None:
        """
        Loads token data (access token, refresh token, token expiry, and authorization code)
        from the token file if it exists.
        """
        (
            self.__access_token,
            self.__refresh_token,
            self.__token_expiry,
            self.__load_auth_code,
        ) = await self.load_tokens()
        self.__tokens_loaded = True

    async def validate_token(self) -> str | int:
        """
        Validates the current access token. If the token is missing, invalid, or expired,
        it will attempt to refresh or obtain a new access token.

        Returns:
        - The valid access token or the HTTP status code if the token refresh fails.
        """
        if self.__use_token_file and not self.__tokens_loaded:
            await self.get_token_data()

        if self.__authorization_code is None or self.__authorization_code == "":
            self.__authorization_code = self.__load_auth_code

        # Serialise the check-and-refresh so that if several coroutines call
        # validate_token() concurrently only one refresh actually happens.
        async with self.__token_lock:
            current_time = time.time()
            logger.debug("Current time: %s, token expiry: %s", current_time, self.__token_expiry)

            if self.__access_token is None:
                logger.debug("No access token found - generating new")
                return await self.get_access_token()
            elif not self.__access_token:
                logger.debug("Access token invalid - refreshing")
                return await self.refresh_access_token()
            elif self.__token_expiry is None or current_time >= (
                self.__token_expiry - self.__token_expiry_margin
            ):
                logger.debug("Access token expired/expiring - refreshing")
                return await self.refresh_access_token()
            else:
                logger.debug("Access token valid - passing")
                return self.__access_token

    async def refresh_access_token(self) -> str | int:
        """
        Refreshes the access token using the refresh token.

        Returns:
        - The new access token if successful or the HTTP status code if the refresh fails.
        """
        if self.__use_token_file:
            await self.get_token_data()

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.__refresh_token,
            "client_id": self.__client_id,
            "client_secret": self.__client_secret,
        }
        headers = {"Content-Type": "application/json"}

        request_kwargs: dict[str, Any] = {
            "data": json.dumps(payload),
            "headers": headers,
        }
        if self.__request_timeout is not None:
            request_kwargs["timeout"] = self.__request_timeout

        async with self._get_session().post(
            self.__token_url,
            **request_kwargs,
        ) as response:
            token_data = await self._read_response_data(response)
            if 200 <= response.status < 300 and isinstance(token_data, dict):
                logger.debug("refresh_access_token metadata: %s", _safe_token_log_data(token_data))
                self.__access_token = token_data["access_token"]
                # OAuth servers are allowed to omit a replacement refresh
                # token; retain the one that just worked in that case.
                self.__refresh_token = token_data.get("refresh_token", self.__refresh_token)
                self.__token_expiry = time.time() + token_data.get("expires_in", 1800)
                if self.__use_token_file:
                    await self.save_tokens()
                return self.__access_token
            else:
                logger.warning("Failed to refresh access token: %s", response.status)
                logger.debug(
                    "Token refresh error body: %s",
                    _safe_token_log_data(token_data),
                )
                if self.__raise_for_status:
                    safe_error = _safe_oauth_error_data(token_data)
                    error_code = safe_error.get("error")
                    raise SharesightAuthError(
                        error_code
                        if isinstance(error_code, str) and error_code != "[omitted]"
                        else "Token refresh failed",
                        status_code=response.status,
                        response_data=safe_error,
                        response_headers=response.headers,
                    )
                return response.status

    async def get_access_token(self) -> str | int:
        """
        Obtains a new access token using the authorization code.

        Returns:
        - The new access token if successful or the HTTP status code if the request fails.
        """
        current_time = time.time()
        payload = {
            "grant_type": "authorization_code",
            "code": self.__authorization_code,
            "redirect_uri": self.__redirect_uri,
            "client_id": self.__client_id,
            "client_secret": self.__client_secret,
        }
        headers = {"Content-Type": "application/json"}

        request_kwargs: dict[str, Any] = {
            "data": json.dumps(payload),
            "headers": headers,
        }
        if self.__request_timeout is not None:
            request_kwargs["timeout"] = self.__request_timeout

        async with self._get_session().post(
            self.__token_url,
            **request_kwargs,
        ) as response:
            token_data = await self._read_response_data(response)
            if 200 <= response.status < 300 and isinstance(token_data, dict):
                logger.debug("get_access_token metadata: %s", _safe_token_log_data(token_data))
                self.__access_token = token_data["access_token"]
                self.__refresh_token = token_data.get("refresh_token")
                self.__token_expiry = current_time + token_data.get("expires_in", 1800)

                if self.__use_token_file:
                    await self.save_tokens()
                return self.__access_token
            else:
                logger.warning("Failed to obtain access token: %s", response.status)
                if response.status == 400:
                    logger.warning(
                        "Did you fill out the correct information (client id/secret/auth code)?"
                    )
                logger.debug(
                    "Access token error body: %s",
                    _safe_token_log_data(token_data),
                )
                if self.__raise_for_status:
                    safe_error = _safe_oauth_error_data(token_data)
                    error_code = safe_error.get("error")
                    raise SharesightAuthError(
                        error_code
                        if isinstance(error_code, str) and error_code != "[omitted]"
                        else "Failed to obtain access token",
                        status_code=response.status,
                        response_data=safe_error,
                        response_headers=response.headers,
                    )
                return response.status

    def _retry_after_seconds(self, retry_after: str | None, attempt: int) -> float:
        """Seconds to wait for a 429, honouring Retry-After but tolerating a
        non-numeric (HTTP-date) value and capping the wait."""
        wait_time = self.__retry_backoff * (2**attempt)
        if retry_after:
            try:
                wait_time = float(retry_after)
            except (TypeError, ValueError):
                # Retry-After can be an HTTP-date rather than a number; fall
                # back to exponential backoff instead of crashing.
                logger.debug("Non-numeric Retry-After header: %r", retry_after)
        return min(wait_time, self.__max_retry_delay)

    def _backoff_seconds(self, attempt: int) -> float:
        """Return bounded exponential backoff with optional positive jitter."""
        base = min(self.__retry_backoff * (2**attempt), self.__max_retry_delay)
        if not base or not self.__retry_jitter:
            return base
        return min(
            self.__max_retry_delay,
            base + random.uniform(0, base * self.__retry_jitter),
        )

    @staticmethod
    def _error_message(data: Any, fallback: str = "Request failed") -> str:
        """Extract Sharesight's human-readable reason from an error body."""
        if isinstance(data, dict):
            value = data.get("reason") or data.get("message") or data.get("error")
            if value is not None:
                return str(value)
        if data not in (None, "", {}):
            return str(data)
        return fallback

    @staticmethod
    def _header_value(headers: Mapping[str, str] | None, name: str) -> str | None:
        """Read an HTTP header from either aiohttp or a plain mapping.

        ``CIMultiDictProxy`` is case-insensitive, but converting it to ``dict``
        loses that behaviour.  Error metadata deliberately uses an ordinary
        dict so it remains serialisable, therefore all internal header reads
        normalise the name explicitly.
        """
        wanted = name.lower()
        for key, value in (headers or {}).items():
            if str(key).lower() == wanted:
                return str(value)
        return None

    @classmethod
    def _is_rate_limit_response(
        cls, status: int, data: Any, headers: Mapping[str, str] | None
    ) -> bool:
        """Recognise Sharesight's 429 and non-standard 403 rate limits."""
        if status == 429:
            return True
        if status != 403:
            return False
        message = cls._error_message(data, "").lower()
        remaining = cls._header_value(headers, "X-MinuteRate-Remaining")
        exhausted = False
        if remaining is not None:
            with suppress(ValueError):
                exhausted = int(remaining) <= 0
        return "too many parallel requests" in message or "rate limit" in message or exhausted

    def _raise_for_response(
        self,
        status: int,
        data: Any,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """Raise the appropriate Sharesight exception with full metadata."""
        message = self._error_message(data)
        if status == 401:
            raise SharesightAuthError(
                message,
                status_code=status,
                response_data=data,
                response_headers=headers,
            )
        if self._is_rate_limit_response(status, data, headers):
            retry_after = None
            raw = self._header_value(headers, "Retry-After")
            if raw:
                with suppress(TypeError, ValueError):
                    retry_after = float(raw)
            raise SharesightRateLimitError(
                status_code=status,
                message=message,
                response_data=data,
                retry_after=retry_after,
                response_headers=headers,
            )
        raise SharesightAPIError(
            status,
            message,
            response_data=data,
            response_headers=headers,
        )

    async def _request(
        self,
        method: str,
        endpoint: list,
        payload: dict[str, Any] | None = None,
        access_token: str | None = None,
        *,
        with_metadata: bool = False,
    ) -> Any:
        """
        Internal method that handles all API requests with common logic for headers,
        URL construction, response parsing, error handling, and retry with exponential backoff.

        Parameters:
        - method: HTTP method (GET, POST, PUT, DELETE, PATCH).
        - endpoint: A list of [version, path, params].
        - payload: Optional; the data to send in the request body.
        - access_token: Optional; the access token to use for authentication.

        Returns the parsed JSON response.  When ``with_metadata`` is true a
        :class:`SharesightResponse` wraps the data, status and response headers.
        """
        if not isinstance(endpoint, (list, tuple)) or len(endpoint) < 2:
            raise ValueError("endpoint must contain at least [version, path]")

        version = str(endpoint[0]).strip("/")
        path = str(endpoint[1]).lstrip("/")
        if not version or not path:
            raise ValueError("endpoint version and path must be non-empty")

        if access_token is None:
            access_token = self.__access_token

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        base_url = self.__api_url_base.rstrip("/")
        # Older README versions advertised a base ending in ``/api/v2/`` even
        # though endpoint lists also carry ``v2``.  Accept both that spelling
        # and the canonical ``.../api/`` without producing ``/v2/v2/``.
        url = (
            f"{base_url}/{path}"
            if base_url.endswith(f"/{version}")
            else f"{base_url}/{version}/{path}"
        )
        params = endpoint[2] if len(endpoint) > 2 else None

        retryable_statuses = {408, 425, 429, 500, 502, 503, 504}
        data = None

        for attempt in range(self.__max_retries + 1):
            try:
                method = method.upper()
                kwargs: dict[str, Any] = {"headers": headers}
                if self.__request_timeout is not None:
                    kwargs["timeout"] = self.__request_timeout
                if params is not None:
                    kwargs["params"] = params
                if method != "GET" and payload is not None:
                    kwargs["json"] = payload

                async with self._get_session().request(method, url, **kwargs) as response:
                    data = await self._read_response_data(response)
                    response_headers = dict(response.headers)

                    if 200 <= response.status < 300:
                        if with_metadata:
                            return SharesightResponse(
                                data=data,
                                status=response.status,
                                headers=response_headers,
                                url=str(getattr(response, "url", url)),
                            )
                        return data

                    # Handle retryable errors
                    rate_limited = self._is_rate_limit_response(
                        response.status, data, response_headers
                    )
                    if (
                        response.status in retryable_statuses or rate_limited
                    ) and attempt < self.__max_retries:
                        if rate_limited:
                            wait_time = self._retry_after_seconds(
                                self._header_value(response.headers, "Retry-After"), attempt
                            )
                            logger.info(
                                "Rate limited (HTTP %s). Retrying in %ss (attempt %s/%s)",
                                response.status,
                                wait_time,
                                attempt + 1,
                                self.__max_retries,
                            )
                        else:
                            wait_time = self._backoff_seconds(attempt)
                            logger.info(
                                "Transient HTTP %s. Retrying in %ss (attempt %s/%s)",
                                response.status,
                                wait_time,
                                attempt + 1,
                                self.__max_retries,
                            )
                        await asyncio.sleep(wait_time)
                        continue

                    # Non-retryable or exhausted retries
                    logger.info(
                        "API %s request failed: HTTP %s (%s)",
                        method.upper(),
                        response.status,
                        self._error_message(data),
                    )
                    if self.__raise_for_status:
                        self._raise_for_response(response.status, data, response_headers)
                    if with_metadata:
                        return SharesightResponse(
                            data=data,
                            status=response.status,
                            headers=response_headers,
                            url=str(getattr(response, "url", url)),
                        )
                    if isinstance(data, dict):
                        # The legacy non-raising API still returns the server's
                        # body, but add the status the Sharesight JSON envelope
                        # omits.  ``setdefault`` never overwrites a server field.
                        legacy_error = dict(data)
                        legacy_error.setdefault("status_code", response.status)
                        return legacy_error
                    return data

            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as conn_err:
                if attempt < self.__max_retries:
                    wait_time = self._backoff_seconds(attempt)
                    logger.info(
                        "Connection error (%s: %s). Retrying in %ss (attempt %s/%s)",
                        type(conn_err).__name__,
                        conn_err,
                        wait_time,
                        attempt + 1,
                        self.__max_retries,
                    )
                    await asyncio.sleep(wait_time)
                    continue
                logger.warning(
                    "Connection error after %s retries: %s: %s",
                    self.__max_retries,
                    type(conn_err).__name__,
                    conn_err,
                )
                raise

        # Should not reach here, but just in case
        return data

    async def get_api_request(self, endpoint: list, access_token: str | None = None) -> Any:
        """
        Sends a GET request to the specified API endpoint.

        Parameters:
        - endpoint: The specific API endpoint to request as [version, path, params].
        - access_token: Optional; the access token to use for authentication. Defaults to the stored access token.

        Returns:
        - The JSON response from the API as a dictionary.
        """
        return await self._request("GET", endpoint, access_token=access_token)

    async def get_api_response(
        self,
        endpoint: list,
        access_token: str | None = None,
    ) -> SharesightResponse:
        """Send a GET request and retain status and response headers.

        This is the concurrency-safe alternative to a mutable
        ``last_response_headers`` attribute.  Existing callers can continue to
        use :meth:`get_api_request` and receive only the parsed body.
        """
        return await self._request("GET", endpoint, access_token=access_token, with_metadata=True)

    async def request_api_response(
        self,
        method: str,
        endpoint: list,
        payload: dict[str, Any] | None = None,
        access_token: str | None = None,
    ) -> SharesightResponse:
        """Send any supported HTTP method and retain response metadata."""
        return await self._request(
            method,
            endpoint,
            payload=payload,
            access_token=access_token,
            with_metadata=True,
        )

    async def post_api_request(
        self, endpoint: list, payload: dict[str, Any], access_token: str | None = None
    ) -> Any:
        """
        Sends a POST request to the specified API endpoint.

        Parameters:
        - endpoint: The specific API endpoint to request as [version, path, params].
        - payload: The data to send in the POST request body.
        - access_token: Optional; the access token to use for authentication. Defaults to the stored access token.

        Returns:
        - The JSON response from the API as a dictionary.
        """
        return await self._request("POST", endpoint, payload=payload, access_token=access_token)

    async def put_api_request(
        self, endpoint: list, payload: dict[str, Any], access_token: str | None = None
    ) -> Any:
        """
        Sends a PUT request to the specified API endpoint.

        Parameters:
        - endpoint: The specific API endpoint to request as [version, path, params].
        - payload: The data to send in the PUT request body.
        - access_token: Optional; the access token to use for authentication. Defaults to the stored access token.

        Returns:
        - The JSON response from the API as a dictionary.
        """
        return await self._request("PUT", endpoint, payload=payload, access_token=access_token)

    async def delete_api_request(
        self, endpoint: list, payload: dict[str, Any] | None = None, access_token: str | None = None
    ) -> Any:
        """
        Sends a DELETE request to the specified API endpoint.

        Parameters:
        - endpoint: The specific API endpoint to request as [version, path, params].
        - payload: Optional; the data to send in the DELETE request body.
        - access_token: Optional; the access token to use for authentication. Defaults to the stored access token.

        Returns:
        - The JSON response from the API as a dictionary.
        """
        return await self._request("DELETE", endpoint, payload=payload, access_token=access_token)

    async def patch_api_request(
        self, endpoint: list, payload: dict[str, Any], access_token: str | None = None
    ) -> Any:
        """
        Sends a PATCH request to the specified API endpoint.

        Parameters:
        - endpoint: The specific API endpoint to request as [version, path, params].
        - payload: The data to send in the PATCH request body.
        - access_token: Optional; the access token to use for authentication. Defaults to the stored access token.

        Returns:
        - The JSON response from the API as a dictionary.
        """
        return await self._request("PATCH", endpoint, payload=payload, access_token=access_token)

    # --- Typed read-only convenience methods ---

    @staticmethod
    def _mapping(data: Any, operation: str) -> dict[str, Any]:
        """Validate the common object response shape used by typed helpers."""
        if not isinstance(data, dict):
            raise SharesightResponseError(
                f"{operation} returned {type(data).__name__}, expected an object",
                response_data=data,
            )
        return data

    async def list_portfolios(self, *, access_token: str | None = None) -> PortfoliosResponse:
        """List portfolios through the V2 route used by releases through 1.4."""
        data = await self._request(
            "GET", ["v2", "portfolios.json", None], access_token=access_token
        )
        return cast(PortfoliosResponse, self._mapping(data, "list_portfolios"))

    async def list_portfolios_v3(
        self,
        *,
        consolidated: bool | None = None,
        instrument_id: int | str | None = None,
        subscription_status: bool | None = None,
        access_token: str | None = None,
    ) -> PortfoliosResponse:
        """List portfolios through the preferred public v3 endpoint."""
        params: dict[str, str] = {}
        if consolidated is not None:
            params["consolidated"] = str(consolidated).lower()
        if instrument_id is not None:
            params["instrument_id"] = str(instrument_id)
        if subscription_status is not None:
            params["subscription_status"] = str(subscription_status).lower()
        data = await self._request(
            "GET", ["v3", "portfolios", params or None], access_token=access_token
        )
        return cast(PortfoliosResponse, self._mapping(data, "list_portfolios_v3"))

    async def list_portfolios_v2(self, *, access_token: str | None = None) -> PortfoliosResponse:
        """Explicit alias for the legacy public V2 portfolio-list helper."""
        return await self.list_portfolios(access_token=access_token)

    async def get_portfolio(
        self, portfolio_id: int | str, *, access_token: str | None = None
    ) -> Portfolio:
        """Get a portfolio through the stable v2 route.

        This preserves the bare-object response returned by releases through
        1.4. Use :meth:`get_portfolio_v3` for the preferred V3 envelope and
        its additional controls.
        """
        data = await self._request(
            "GET",
            ["v2", f"portfolios/{portfolio_id}.json", None],
            access_token=access_token,
        )
        return cast(Portfolio, self._mapping(data, "get_portfolio"))

    async def get_portfolio_v3(
        self,
        portfolio_id: int | str,
        *,
        consolidated: bool | None = None,
        subscription_status: bool | None = None,
        access_token: str | None = None,
    ) -> PortfolioResponse:
        """Get portfolio metadata through the preferred public v3 endpoint."""
        params: dict[str, str] = {}
        if consolidated is not None:
            params["consolidated"] = str(consolidated).lower()
        if subscription_status is not None:
            params["subscription_status"] = str(subscription_status).lower()
        data = await self._request(
            "GET",
            ["v3", f"portfolios/{portfolio_id}", params or None],
            access_token=access_token,
        )
        return cast(PortfolioResponse, self._mapping(data, "get_portfolio_v3"))

    async def get_portfolio_v2(
        self, portfolio_id: int | str, *, access_token: str | None = None
    ) -> Portfolio:
        """Explicit alias for the legacy public v2 portfolio helper."""
        return await self.get_portfolio(portfolio_id, access_token=access_token)

    async def get_portfolio_performance(
        self,
        portfolio_id: int | str,
        start_date: object = None,
        end_date: object = None,
        *,
        grouping: str | None = None,
        consolidated: bool | None = None,
        include_sales: bool | None = None,
        custom_group_id: int | str | None = None,
        access_token: str | None = None,
    ) -> PerformanceReport:
        """Get the flat v2 performance report used by releases through 1.4."""
        params: dict[str, str] = {}
        if start_date is not None:
            params["start_date"] = str(start_date)
        if end_date is not None:
            params["end_date"] = str(end_date)
        if grouping is not None:
            params["grouping"] = grouping
        if consolidated is not None:
            params["consolidated"] = str(consolidated).lower()
        if include_sales is not None:
            params["include_sales"] = str(include_sales).lower()
        if custom_group_id is not None:
            params["custom_group_id"] = str(custom_group_id)
        data = await self._request(
            "GET",
            ["v2", f"portfolios/{portfolio_id}/performance.json", params or None],
            access_token=access_token,
        )
        return cast(
            PerformanceReport,
            self._mapping(data, "get_portfolio_performance"),
        )

    async def get_portfolio_performance_v3(
        self,
        portfolio_id: int | str,
        start_date: object = None,
        end_date: object = None,
        *,
        grouping: str | None = None,
        consolidated: bool | None = None,
        include_sales: bool | None = None,
        include_limited: bool | None = None,
        report_combined: bool | None = None,
        labels: list[str] | tuple[str, ...] | None = None,
        custom_group_id: int | str | None = None,
        benchmark_code: str | None = None,
        access_token: str | None = None,
    ) -> PerformanceResponse:
        """Get a public v3 performance report with optional report controls."""
        params: dict[str, Any] = {}
        if start_date is not None:
            params["start_date"] = str(start_date)
        if end_date is not None:
            params["end_date"] = str(end_date)
        if grouping is not None:
            params["grouping"] = grouping
        if consolidated is not None:
            params["consolidated"] = str(consolidated).lower()
        if include_sales is not None:
            params["include_sales"] = str(include_sales).lower()
        if include_limited is not None:
            params["include_limited"] = str(include_limited).lower()
        if report_combined is not None:
            params["report_combined"] = str(report_combined).lower()
        if labels is not None:
            params["labels[]"] = list(labels)
        if custom_group_id is not None:
            params["custom_group_id"] = str(custom_group_id)
        if benchmark_code is not None:
            params["benchmark_code"] = benchmark_code
        data = await self._request(
            "GET",
            ["v3", f"portfolios/{portfolio_id}/performance", params or None],
            access_token=access_token,
        )
        return cast(
            PerformanceResponse,
            self._mapping(data, "get_portfolio_performance_v3"),
        )

    async def get_portfolio_performance_v2(
        self,
        portfolio_id: int | str,
        start_date: object = None,
        end_date: object = None,
        *,
        grouping: str | None = None,
        consolidated: bool | None = None,
        include_sales: bool | None = None,
        custom_group_id: int | str | None = None,
        access_token: str | None = None,
    ) -> PerformanceReport:
        """Explicit alias for the legacy public v2 performance helper."""
        return await self.get_portfolio_performance(
            portfolio_id,
            start_date,
            end_date,
            grouping=grouping,
            consolidated=consolidated,
            include_sales=include_sales,
            custom_group_id=custom_group_id,
            access_token=access_token,
        )

    async def get_portfolio_valuation(
        self,
        portfolio_id: int | str,
        *,
        balance_date: object = None,
        grouping: str | None = None,
        consolidated: bool | None = None,
        include_sales: bool | None = None,
        custom_group_id: int | str | None = None,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        """Get the v2 valuation report (no equivalent public v3 route)."""
        params: dict[str, str] = {}
        if balance_date is not None:
            params["balance_date"] = str(balance_date)
        if grouping is not None:
            params["grouping"] = grouping
        if consolidated is not None:
            params["consolidated"] = str(consolidated).lower()
        if include_sales is not None:
            params["include_sales"] = str(include_sales).lower()
        if custom_group_id is not None:
            params["custom_group_id"] = str(custom_group_id)
        data = await self._request(
            "GET",
            ["v2", f"portfolios/{portfolio_id}/valuation.json", params or None],
            access_token=access_token,
        )
        return self._mapping(data, "get_portfolio_valuation")

    async def get_portfolio_diversity(
        self,
        portfolio_id: int | str,
        *,
        date: object = None,
        grouping: str | None = None,
        consolidated: bool | None = None,
        custom_group_id: int | str | None = None,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        """Get the v2 diversity report (no equivalent public v3 route)."""
        params: dict[str, str] = {}
        if date is not None:
            params["date"] = str(date)
        if grouping is not None:
            params["grouping"] = grouping
        if consolidated is not None:
            params["consolidated"] = str(consolidated).lower()
        if custom_group_id is not None:
            params["custom_group_id"] = str(custom_group_id)
        data = await self._request(
            "GET",
            ["v2", f"portfolios/{portfolio_id}/diversity.json", params or None],
            access_token=access_token,
        )
        return self._mapping(data, "get_portfolio_diversity")

    async def get_capital_gains(
        self,
        portfolio_id: int | str,
        *,
        start_date: object = None,
        end_date: object = None,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        """Get the v2 capital-gains report for a supported tax portfolio."""
        params: dict[str, str] = {}
        if start_date is not None:
            params["start_date"] = str(start_date)
        if end_date is not None:
            params["end_date"] = str(end_date)
        data = await self._request(
            "GET",
            ["v2", f"portfolios/{portfolio_id}/capital_gains.json", params or None],
            access_token=access_token,
        )
        return self._mapping(data, "get_capital_gains")

    async def get_unrealised_cgt(
        self,
        portfolio_id: int | str,
        *,
        balance_date: object = None,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        """Get the v2 unrealised-CGT report for a supported tax portfolio."""
        params = {"balance_date": str(balance_date)} if balance_date is not None else None
        data = await self._request(
            "GET",
            ["v2", f"portfolios/{portfolio_id}/unrealised_cgt.json", params],
            access_token=access_token,
        )
        return self._mapping(data, "get_unrealised_cgt")

    async def list_holdings(
        self,
        portfolio_id: int | str,
        *,
        consolidated: bool | None = None,
        access_token: str | None = None,
    ) -> HoldingsResponse:
        """List holdings through the preferred public v3 portfolio route."""
        params = {"consolidated": str(consolidated).lower()} if consolidated is not None else None
        data = await self._request(
            "GET",
            ["v3", f"portfolios/{portfolio_id}/holdings", params],
            access_token=access_token,
        )
        return cast(HoldingsResponse, self._mapping(data, "list_holdings"))

    async def list_all_holdings(self, *, access_token: str | None = None) -> HoldingsResponse:
        """List holdings across accessible portfolios through public v3."""
        data = await self._request("GET", ["v3", "holdings", None], access_token=access_token)
        return cast(HoldingsResponse, self._mapping(data, "list_all_holdings"))

    async def get_holding(
        self,
        holding_id: int | str,
        *,
        average_purchase_price: bool | None = None,
        cost_base: bool | None = None,
        values_over_time: object = None,
        access_token: str | None = None,
    ) -> HoldingResponse:
        """Get one holding with optional v3 cost and value details."""
        params: dict[str, str] = {}
        if average_purchase_price is not None:
            params["average_purchase_price"] = str(average_purchase_price).lower()
        if cost_base is not None:
            params["cost_base"] = str(cost_base).lower()
        if values_over_time is not None:
            params["values_over_time"] = str(values_over_time)
        data = await self._request(
            "GET", ["v3", f"holdings/{holding_id}", params or None], access_token=access_token
        )
        return cast(HoldingResponse, self._mapping(data, "get_holding"))

    async def list_holding_trades(
        self,
        holding_id: int | str,
        *,
        unique_identifier: str | None = None,
        access_token: str | None = None,
    ) -> TradesResponse:
        """List trades for one holding through the public v2 route.

        The similarly named v3 endpoint is marked ``3.0.0-internal`` in
        Sharesight's endpoint catalogue, so it is not a safe default for an
        external OAuth application.
        """
        params = {"unique_identifier": unique_identifier} if unique_identifier is not None else None
        data = await self._request(
            "GET",
            ["v2", f"holdings/{holding_id}/trades.json", params],
            access_token=access_token,
        )
        return cast(TradesResponse, self._mapping(data, "list_holding_trades"))

    async def list_trades(
        self,
        portfolio_id: int | str,
        *,
        start_date: object = None,
        end_date: object = None,
        unique_identifier: str | None = None,
        access_token: str | None = None,
    ) -> TradesResponse:
        """List portfolio trades through the public v2 route.

        V3 advertises this route for Sharesight's internal application only.
        """
        params: dict[str, str] = {}
        if start_date is not None:
            params["start_date"] = str(start_date)
        if end_date is not None:
            params["end_date"] = str(end_date)
        if unique_identifier is not None:
            params["unique_identifier"] = unique_identifier
        data = await self._request(
            "GET",
            ["v2", f"portfolios/{portfolio_id}/trades.json", params or None],
            access_token=access_token,
        )
        return cast(TradesResponse, self._mapping(data, "list_trades"))

    async def list_portfolio_payouts(
        self,
        portfolio_id: int | str,
        *,
        start_date: object = None,
        end_date: object = None,
        use_date: str | None = None,
        access_token: str | None = None,
    ) -> PayoutsResponse:
        """List portfolio payouts through the v2 aggregate endpoint."""
        params: dict[str, str] = {}
        if start_date is not None:
            params["start_date"] = str(start_date)
        if end_date is not None:
            params["end_date"] = str(end_date)
        if use_date is not None:
            params["use_date"] = use_date
        data = await self._request(
            "GET",
            ["v2", f"portfolios/{portfolio_id}/payouts.json", params or None],
            access_token=access_token,
        )
        return cast(PayoutsResponse, self._mapping(data, "list_portfolio_payouts"))

    async def list_holding_payouts(
        self,
        holding_id: int | str,
        *,
        start_date: object = None,
        end_date: object = None,
        use_date: str | None = None,
        access_token: str | None = None,
    ) -> PayoutsResponse:
        """List payouts for one holding through the public v2 route.

        The v3 holding-payout route is internal-scoped.
        """
        params: dict[str, str] = {}
        if start_date is not None:
            params["start_date"] = str(start_date)
        if end_date is not None:
            params["end_date"] = str(end_date)
        if use_date is not None:
            params["use_date"] = use_date
        data = await self._request(
            "GET",
            ["v2", f"holdings/{holding_id}/payouts.json", params or None],
            access_token=access_token,
        )
        return cast(PayoutsResponse, self._mapping(data, "list_holding_payouts"))

    async def list_cash_accounts(
        self, *, date: object = None, access_token: str | None = None
    ) -> CashAccountsResponse:
        """List cash accounts through the public v2 route."""
        params = {"date": str(date)} if date is not None else None
        data = await self._request(
            "GET", ["v2", "cash_accounts.json", params], access_token=access_token
        )
        return cast(CashAccountsResponse, self._mapping(data, "list_cash_accounts"))

    async def get_cash_account(
        self,
        cash_account_id: int | str,
        *,
        date: object = None,
        access_token: str | None = None,
    ) -> CashAccount:
        """Get the bare cash-account object returned by the public v2 route."""
        params = {"date": str(date)} if date is not None else None
        data = await self._request(
            "GET",
            ["v2", f"cash_accounts/{cash_account_id}.json", params],
            access_token=access_token,
        )
        return cast(CashAccount, self._mapping(data, "get_cash_account"))

    async def list_cash_account_transactions(
        self,
        cash_account_id: int | str,
        *,
        from_date: object = None,
        to_date: object = None,
        description: str | None = None,
        foreign_identifier: str | None = None,
        access_token: str | None = None,
    ) -> CashAccountTransactionsResponse:
        """List contributions and withdrawals for one cash account."""
        params: dict[str, str] = {}
        if from_date is not None:
            params["from"] = str(from_date)
        if to_date is not None:
            params["to"] = str(to_date)
        if description is not None:
            params["description"] = description
        if foreign_identifier is not None:
            params["foreign_identifier"] = foreign_identifier
        data = await self._request(
            "GET",
            [
                "v2",
                f"cash_accounts/{cash_account_id}/cash_account_transactions.json",
                params or None,
            ],
            access_token=access_token,
        )
        return cast(
            CashAccountTransactionsResponse,
            self._mapping(data, "list_cash_account_transactions"),
        )

    async def get_portfolio_user_setting(
        self,
        portfolio_id: int | str,
        *,
        consolidated: bool | None = None,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        """Get the authenticated user's settings for a portfolio."""
        params = {"consolidated": str(consolidated).lower()} if consolidated is not None else None
        data = await self._request(
            "GET",
            ["v3", f"portfolios/{portfolio_id}/user_setting", params],
            access_token=access_token,
        )
        return self._mapping(data, "get_portfolio_user_setting")

    async def get_portfolio_benchmark(
        self,
        portfolio_id: int | str,
        *,
        start_date: object = None,
        end_date: object = None,
        instrument_id: int | str | None = None,
        consolidated: bool | None = None,
        interest_method: str | None = None,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        """Get configured benchmark performance (internal, entitlement-dependent)."""
        params: dict[str, str] = {}
        if start_date is not None:
            params["start_date"] = str(start_date)
        if end_date is not None:
            params["end_date"] = str(end_date)
        if instrument_id is not None:
            params["instrument_id"] = str(instrument_id)
        if consolidated is not None:
            params["consolidated"] = str(consolidated).lower()
        if interest_method is not None:
            params["interest_method"] = interest_method
        data = await self._request(
            "GET",
            ["v3", f"portfolios/{portfolio_id}/benchmark.json", params or None],
            access_token=access_token,
        )
        return self._mapping(data, "get_portfolio_benchmark")

    async def get_portfolio_value_data(
        self,
        portfolio_id: int | str,
        *,
        start_date: object = None,
        consolidated: bool | None = None,
        access_token: str | None = None,
    ) -> ValueSeriesResponse | list[dict[str, Any]]:
        """Get portfolio daily values from the entitlement-dependent mobile route."""
        params: dict[str, str] = {}
        if start_date is not None:
            params["start_date"] = str(start_date)
        if consolidated is not None:
            params["consolidated"] = str(consolidated).lower()
        data = await self._request(
            "GET",
            ["v3", f"portfolios/{portfolio_id}/portfolio_value_data.json", params or None],
            access_token=access_token,
        )
        if isinstance(data, list):
            return cast(list[dict[str, Any]], data)
        return cast(
            ValueSeriesResponse,
            self._mapping(data, "get_portfolio_value_data"),
        )

    async def get_portfolio_performance_index_chart(
        self,
        portfolio_id: int | str,
        *,
        start_date: object = None,
        end_date: object = None,
        grouping: str | None = None,
        consolidated: bool | None = None,
        custom_group_id: int | str | None = None,
        benchmark_code: str | None = None,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        """Get growth-index series for a portfolio and benchmark."""
        params: dict[str, str] = {}
        if start_date is not None:
            params["start_date"] = str(start_date)
        if end_date is not None:
            params["end_date"] = str(end_date)
        if grouping is not None:
            params["grouping"] = grouping
        if consolidated is not None:
            params["consolidated"] = str(consolidated).lower()
        if custom_group_id is not None:
            params["custom_group_id"] = str(custom_group_id)
        if benchmark_code is not None:
            params["benchmark_code"] = benchmark_code
        data = await self._request(
            "GET",
            ["v3", f"portfolios/{portfolio_id}/performance_index_chart", params or None],
            access_token=access_token,
        )
        return self._mapping(data, "get_portfolio_performance_index_chart")

    async def list_user_instruments(self, *, access_token: str | None = None) -> dict[str, Any]:
        """List instruments held across the authenticated user's portfolios."""
        data = await self._request(
            "GET", ["v2", "user_instruments.json", None], access_token=access_token
        )
        return self._mapping(data, "list_user_instruments")

    async def get_my_user(self, *, access_token: str | None = None) -> dict[str, Any]:
        """Get non-secret account and subscription metadata."""
        data = await self._request("GET", ["v2", "my_user.json", None], access_token=access_token)
        return self._mapping(data, "get_my_user")

    async def list_groups(self, *, access_token: str | None = None) -> GroupsResponse:
        """List standard and custom report groups through public v2."""
        data = await self._request("GET", ["v2", "groups.json", None], access_token=access_token)
        return cast(GroupsResponse, self._mapping(data, "list_groups"))

    async def list_currencies(self, *, access_token: str | None = None) -> CurrenciesResponse:
        """List supported currency definitions through public v2."""
        data = await self._request(
            "GET", ["v2", "currencies.json", None], access_token=access_token
        )
        return cast(CurrenciesResponse, self._mapping(data, "list_currencies"))

    async def list_countries(
        self, *, supported: bool | None = None, access_token: str | None = None
    ) -> CountriesResponse:
        """List public v3 country definitions."""
        params = {"supported": str(supported).lower()} if supported is not None else None
        data = await self._request("GET", ["v3", "countries", params], access_token=access_token)
        return cast(CountriesResponse, self._mapping(data, "list_countries"))

    async def list_custom_investments(
        self,
        *,
        portfolio_id: int | str | None = None,
        access_token: str | None = None,
    ) -> CustomInvestmentsResponse:
        """List custom investments, optionally restricted to one portfolio."""
        params = {"portfolio_id": str(portfolio_id)} if portfolio_id is not None else None
        data = await self._request(
            "GET", ["v3", "custom_investments", params], access_token=access_token
        )
        return cast(
            CustomInvestmentsResponse,
            self._mapping(data, "list_custom_investments"),
        )

    async def get_custom_investment(
        self, custom_investment_id: int | str, *, access_token: str | None = None
    ) -> CustomInvestment:
        """Get the bare custom-investment object returned by public v3."""
        data = await self._request(
            "GET",
            ["v3", f"custom_investments/{custom_investment_id}", None],
            access_token=access_token,
        )
        return cast(CustomInvestment, self._mapping(data, "get_custom_investment"))

    @staticmethod
    def _dated_page_params(
        *,
        start_date: object = None,
        end_date: object = None,
        page: int | str | None = None,
        per_page: int | None = None,
    ) -> dict[str, str]:
        """Build the common date and page query used by custom investments."""
        if isinstance(page, int) and page < 1:
            raise ValueError("page must be greater than zero")
        if isinstance(page, str) and not page:
            raise ValueError("page cursor must not be empty")
        if per_page is not None and not 1 <= per_page <= 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, str] = {}
        if start_date is not None:
            params["start_date"] = str(start_date)
        if end_date is not None:
            params["end_date"] = str(end_date)
        if page is not None:
            params["page"] = str(page)
        if per_page is not None:
            params["per_page"] = str(per_page)
        return params

    async def list_custom_investment_prices(
        self,
        custom_investment_id: int | str,
        *,
        start_date: object = None,
        end_date: object = None,
        page: int | str | None = None,
        per_page: int | None = None,
        access_token: str | None = None,
    ) -> CustomInvestmentPricesResponse:
        """Get one page of public v3 custom-investment prices."""
        params = self._dated_page_params(
            start_date=start_date,
            end_date=end_date,
            page=page,
            per_page=per_page,
        )
        data = await self._request(
            "GET",
            ["v3", f"custom_investment/{custom_investment_id}/prices.json", params or None],
            access_token=access_token,
        )
        return cast(
            CustomInvestmentPricesResponse,
            self._mapping(data, "list_custom_investment_prices"),
        )

    async def list_custom_investment_adjustments(
        self,
        instrument_id: int | str,
        *,
        start_date: object = None,
        end_date: object = None,
        page: int | str | None = None,
        per_page: int | None = None,
        access_token: str | None = None,
    ) -> AdjustmentsResponse:
        """Get one page of public v3 custom-investment adjustments."""
        params = self._dated_page_params(
            start_date=start_date,
            end_date=end_date,
            page=page,
            per_page=per_page,
        )
        data = await self._request(
            "GET",
            ["v3", f"custom_investments/{instrument_id}/adjustments", params or None],
            access_token=access_token,
        )
        return cast(
            AdjustmentsResponse,
            self._mapping(data, "list_custom_investment_adjustments"),
        )

    async def get_adjustment(
        self, adjustment_id: int | str, *, access_token: str | None = None
    ) -> AdjustmentResponse:
        """Get one public v3 custom-investment adjustment."""
        data = await self._request(
            "GET",
            ["v3", f"adjustments/{adjustment_id}", None],
            access_token=access_token,
        )
        return cast(AdjustmentResponse, self._mapping(data, "get_adjustment"))

    async def list_custom_investment_coupon_rates(
        self,
        instrument_id: int | str,
        *,
        start_date: object = None,
        end_date: object = None,
        page: int | str | None = None,
        per_page: int | None = None,
        access_token: str | None = None,
    ) -> CouponRatesResponse:
        """Get one page of public v3 custom-investment coupon rates."""
        params = self._dated_page_params(
            start_date=start_date,
            end_date=end_date,
            page=page,
            per_page=per_page,
        )
        data = await self._request(
            "GET",
            ["v3", f"custom_investments/{instrument_id}/coupon_rates", params or None],
            access_token=access_token,
        )
        return cast(
            CouponRatesResponse,
            self._mapping(data, "list_custom_investment_coupon_rates"),
        )

    async def iter_api_pages(
        self,
        endpoint: list[Any],
        *,
        item_key: str,
        access_token: str | None = None,
        page_parameter: str = "page",
        per_page_parameter: str = "per_page",
        per_page: int = 100,
        max_pages: int = 1000,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield Sharesight cursor pages without losing envelope metadata.

        Documented paginated routes return the opaque pointer for the next
        request in ``pagination.page``. The first request omits ``page`` unless
        the caller supplied a resume cursor. Never infer another request from
        item count: non-paginated aggregate endpoints may legitimately return
        100 or more rows without any pagination metadata.
        """
        if not 1 <= per_page <= 100:
            raise ValueError("per_page must be between 1 and 100")
        if max_pages < 1:
            raise ValueError("max_pages must be greater than zero")
        if len(endpoint) < 2:
            raise ValueError("endpoint must contain at least [version, path]")

        params = dict(endpoint[2] or {}) if len(endpoint) > 2 else {}
        raw_cursor = params.pop(page_parameter, None)
        cursor: str | None = None
        if raw_cursor is not None:
            if isinstance(raw_cursor, int) and raw_cursor <= 0:
                raise ValueError(f"{page_parameter} cursor must be positive")
            cursor = str(raw_cursor)
            if not cursor:
                raise ValueError(f"{page_parameter} cursor must not be empty")
        params[per_page_parameter] = per_page
        seen_cursors: set[str] = set()
        if cursor is not None:
            seen_cursors.add(cursor)

        for _ in range(max_pages):
            request_params = dict(params)
            if cursor is not None:
                request_params[page_parameter] = cursor
            data = await self._request(
                "GET",
                [endpoint[0], endpoint[1], request_params],
                access_token=access_token,
            )
            mapping = self._mapping(data, "iter_api_pages")
            items = mapping.get(item_key)
            if not isinstance(items, list):
                raise SharesightResponseError(
                    f"iter_api_pages response has no list field {item_key!r}",
                    response_data=data,
                )
            yield mapping

            pagination = mapping.get("pagination")
            if not isinstance(pagination, dict):
                return
            next_value = pagination.get("page")
            if next_value in (None, False, ""):
                return
            next_cursor = str(next_value)
            if next_cursor in seen_cursors:
                raise SharesightResponseError(
                    "Pagination returned a repeated cursor",
                    response_data=data,
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        raise SharesightResponseError(f"Pagination exceeded max_pages={max_pages}")

    async def get_all_pages(
        self,
        endpoint: list[Any],
        *,
        item_key: str,
        access_token: str | None = None,
        page_parameter: str = "page",
        per_page_parameter: str = "per_page",
        per_page: int = 100,
        max_pages: int = 1000,
    ) -> dict[str, Any]:
        """Collect :meth:`iter_api_pages` into one response envelope."""
        combined: dict[str, Any] | None = None
        items: list[Any] = []
        async for page in self.iter_api_pages(
            endpoint,
            item_key=item_key,
            access_token=access_token,
            page_parameter=page_parameter,
            per_page_parameter=per_page_parameter,
            per_page=per_page,
            max_pages=max_pages,
        ):
            if combined is None:
                combined = dict(page)
            items.extend(page[item_key])
        if combined is None:
            combined = {item_key: []}
        combined[item_key] = items
        combined.pop("pagination", None)
        return combined

    # --- Explicitly write-capable convenience methods ---

    async def create_trade(
        self,
        portfolio_id: int | str,
        trade_data: dict[str, Any],
        *,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        """Create a trade through v2 ``trades.json``.

        This method mutates financial records.  Callers should validate with
        mocks or a Sharesight developer sandbox and must not use it as part of
        a polling or discovery workflow.
        """
        if isinstance(trade_data.get("trade"), dict):
            payload = dict(trade_data)
            payload["trade"] = dict(cast(dict[str, Any], payload["trade"]))
        else:
            payload = {"trade": dict(trade_data)}
        payload["trade"].setdefault("portfolio_id", portfolio_id)
        data = await self._request(
            "POST",
            ["v2", "trades.json", None],
            payload=payload,
            access_token=access_token,
        )
        return self._mapping(data, "create_trade")

    # --- Token management ---

    async def inject_token(self, token_data: dict[str, Any]) -> None:
        """
        Manually injects token data (access token, refresh token, etc.) into the API client.

        Parameters:
        - token_data: A dictionary containing the token data to inject.
        """
        if token_data:
            auth_code = token_data.get("auth_code")
            access_token = token_data.get("access_token")
            token_expiry = token_data.get("token_expiry")
            refresh_token = token_data.get("refresh_token")
            self.__authorization_code = str(auth_code) if auth_code is not None else None
            self.__access_token = str(access_token) if access_token is not None else None
            self.__token_expiry = float(token_expiry) if token_expiry is not None else None
            self.__refresh_token = str(refresh_token) if refresh_token is not None else None
            if self.__use_token_file:
                await self.save_tokens()

    async def load_tokens(self) -> tuple[str | None, str | None, float | None, str | None]:
        """
        Loads token data from the token file if it exists.

        Returns:
        - A tuple containing the access token, refresh token, token expiry, and authorization code.
        """
        if not await aiofiles.os.path.isfile(self.__token_file):
            logger.info("%s doesn't exist.", self.__token_file)
            return None, None, None, None

        # Upgrade token files created by older releases before reading their
        # contents. If permissions cannot be made private, fail closed rather
        # than continuing to use a credential readable by other users.
        await asyncio.to_thread(os.chmod, self.__token_file, 0o600)

        async with aiofiles.open(self.__token_file) as file:
            data = await file.read()

        if not data:
            return None, None, None, None

        try:
            tokens = json.loads(data)
            access_token = tokens.get("access_token")
            refresh_token = tokens.get("refresh_token")
            token_expiry = tokens.get("token_expiry")
            load_auth_code = tokens.get("auth_code")
            return access_token, refresh_token, token_expiry, load_auth_code
        except json.JSONDecodeError:
            return None, None, None, None

    async def save_tokens(self) -> None:
        """
        Saves the current token data (access token, refresh token, etc.) to the token file.
        """
        token_data = {
            "access_token": self.__access_token,
            "refresh_token": self.__refresh_token,
            "token_expiry": self.__token_expiry,
            "auth_code": self.__authorization_code,
        }

        # Create a private, unpredictable temporary file in the destination
        # directory, then atomically replace the token file. O_EXCL semantics
        # from mkstemp prevent a pre-created symlink from being followed.
        target = os.path.abspath(self.__token_file)
        target_directory = os.path.dirname(target)
        prefix = f".{os.path.basename(target)}."
        fd, tmp_file = await asyncio.to_thread(
            tempfile.mkstemp,
            prefix=prefix,
            suffix=".tmp",
            dir=target_directory,
            text=True,
        )
        try:
            async with aiofiles.open(fd, mode="w") as file:
                await file.write(json.dumps(token_data))
            fd = -1
            await aiofiles.os.replace(tmp_file, target)
        finally:
            if fd >= 0:
                with suppress(OSError):
                    await asyncio.to_thread(os.close, fd)
            with suppress(FileNotFoundError):
                await aiofiles.os.remove(tmp_file)

    async def return_token(self) -> dict[str, str | float | None]:
        """
        Returns the current token data as a dictionary.

        Returns:
        - A dictionary containing the access token, refresh token, token expiry, and authorization code.
        """
        return {
            "access_token": self.__access_token,
            "refresh_token": self.__refresh_token,
            "token_expiry": self.__token_expiry,
            "auth_code": self.__authorization_code,
        }

    async def delete_token(self) -> None:
        """Delete the token file if present."""
        with suppress(FileNotFoundError):
            await aiofiles.os.remove(self.__token_file)

    async def close(self) -> None:
        # Only close a session we created ourselves — never close a session
        # that was passed in (e.g. Home Assistant's shared client session).
        if (
            not self._closed
            and self._created_session
            and self.session is not None
            and not self.session.closed
        ):
            logger.debug("Closing SharesightAPI-owned aiohttp session")
            await self.session.close()
        self._closed = True
