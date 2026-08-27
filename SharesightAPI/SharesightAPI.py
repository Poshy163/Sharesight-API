import asyncio
import json
import logging
import os
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import aiofiles
import aiofiles.os
import aiohttp

from .exceptions import (
    SharesightAPIError,
    SharesightAuthError,
    SharesightRateLimitError,
)

logger = logging.getLogger(__name__)


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


def _redact_token_data(data: dict) -> dict:
    """Return a copy of OAuth data with every credential fully redacted.

    Even a token prefix/suffix is unnecessary in logs and can help correlate a
    credential across systems. Keep useful expiry/scope metadata, but never
    reproduce bearer, refresh, identity, or client-secret values.
    """
    redacted = dict(data)
    for key, value in redacted.items():
        normalised = str(key).lower()
        if value and (
            normalised.endswith("_token")
            or "secret" in normalised
            or normalised == "authorization_code"
        ):
            redacted[key] = "[redacted]"
    return redacted


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
        """
        self.__client_id = client_id
        self.__client_secret = client_secret
        self.__authorization_code = authorization_code
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
        self.__max_retries = max_retries
        self.__retry_backoff = retry_backoff
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

    @staticmethod
    async def _read_response_data(response: aiohttp.ClientResponse) -> Any:
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
            return await response.json()
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

        async with self._get_session().post(
            self.__token_url, data=json.dumps(payload), headers=headers
        ) as response:
            token_data = await self._read_response_data(response)
            if 200 <= response.status < 300 and isinstance(token_data, dict):
                logger.debug("refresh_access_token response: %s", _redact_token_data(token_data))
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
                    _redact_token_data(token_data) if isinstance(token_data, dict) else token_data,
                )
                if self.__raise_for_status:
                    raise SharesightAuthError(
                        self._error_message(token_data, "Token refresh failed"),
                        status_code=response.status,
                        response_data=token_data,
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

        async with self._get_session().post(
            self.__token_url, data=json.dumps(payload), headers=headers
        ) as response:
            token_data = await self._read_response_data(response)
            if 200 <= response.status < 300 and isinstance(token_data, dict):
                logger.debug("get_access_token response: %s", _redact_token_data(token_data))
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
                    _redact_token_data(token_data) if isinstance(token_data, dict) else token_data,
                )
                if self.__raise_for_status:
                    raise SharesightAuthError(
                        self._error_message(token_data, "Failed to obtain access token"),
                        status_code=response.status,
                        response_data=token_data,
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
        return min(wait_time, 300.0)

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
                kwargs = {"headers": headers}
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
                            wait_time = self.__retry_backoff * (2**attempt)
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
                    wait_time = self.__retry_backoff * (2**attempt)
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

    # --- Convenience methods ---

    async def list_portfolios(self) -> dict:
        """List all portfolios accessible by the authenticated user."""
        return await self._request("GET", ["v2", "portfolios", None])

    async def get_portfolio(self, portfolio_id) -> dict:
        """Get details of a specific portfolio."""
        return await self._request("GET", ["v2", f"portfolios/{portfolio_id}", None])

    async def get_portfolio_performance(self, portfolio_id, start_date=None, end_date=None) -> dict:
        """Get performance data for a portfolio, optionally filtered by date range."""
        params = {}
        if start_date:
            params["start_date"] = str(start_date)
        if end_date:
            params["end_date"] = str(end_date)
        return await self._request(
            "GET", ["v2", f"portfolios/{portfolio_id}/performance", params or None]
        )

    async def list_holdings(self, portfolio_id) -> dict:
        """List all holdings in a portfolio."""
        return await self._request("GET", ["v2", f"portfolios/{portfolio_id}/holdings", None])

    async def get_holding(self, holding_id) -> dict:
        """Get details of a specific holding."""
        return await self._request("GET", ["v2", f"holdings/{holding_id}", None])

    async def list_trades(self, portfolio_id) -> dict:
        """List all trades in a portfolio."""
        return await self._request("GET", ["v2", f"portfolios/{portfolio_id}/trades", None])

    async def create_trade(self, portfolio_id, trade_data: dict) -> dict:
        """Create a new trade in a portfolio."""
        return await self._request(
            "POST", ["v2", f"portfolios/{portfolio_id}/trades", None], payload=trade_data
        )

    async def list_cash_accounts(self) -> dict:
        """List all cash accounts."""
        return await self._request("GET", ["v2", "cash_accounts", None])

    async def get_cash_account(self, cash_account_id) -> dict:
        """Get details of a specific cash account."""
        return await self._request("GET", ["v2", f"cash_accounts/{cash_account_id}", None])

    async def list_groups(self) -> dict:
        """List all groups."""
        return await self._request("GET", ["v2", "groups", None])

    # --- Token management ---

    async def inject_token(self, token_data: dict[str, Any]) -> None:
        """
        Manually injects token data (access token, refresh token, etc.) into the API client.

        Parameters:
        - token_data: A dictionary containing the token data to inject.
        """
        if token_data:
            self.__authorization_code = token_data.get("auth_code")
            self.__access_token = token_data.get("access_token")
            self.__token_expiry = token_data.get("token_expiry")
            self.__refresh_token = token_data.get("refresh_token")
            if self.__use_token_file:
                await self.save_tokens()

    async def load_tokens(self) -> tuple[str | None, str | None, float | None, str | None]:
        """
        Loads token data from the token file if it exists.

        Returns:
        - A tuple containing the access token, refresh token, token expiry, and authorization code.
        """
        if not os.path.isfile(self.__token_file):
            logger.info(f"{self.__token_file} doesn't exist.")
            return None, None, None, None

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

        # Write to a temp file then atomically replace, so a crash mid-write
        # can't leave a truncated/corrupt token file behind.
        tmp_file = f"{self.__token_file}.tmp"
        async with aiofiles.open(tmp_file, mode="w") as file:
            await file.write(json.dumps(token_data))
        os.replace(tmp_file, self.__token_file)

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

    async def delete_token(self):
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
