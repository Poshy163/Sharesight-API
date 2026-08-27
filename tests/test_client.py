"""Regression tests for the public HTTP client contract."""

from __future__ import annotations

import json
from collections import deque
from typing import Any

import pytest

from SharesightAPI import (
    SharesightAPI,
    SharesightAPIError,
    SharesightAuthError,
    SharesightRateLimitError,
    SharesightResponse,
)
from SharesightAPI.SharesightAPI import _redact_token_data


class FakeResponse:
    """Small aiohttp response stand-in for deterministic unit tests."""

    def __init__(
        self,
        status: int,
        data: Any = None,
        *,
        headers: dict[str, str] | None = None,
        text: str = "",
    ) -> None:
        self.status = status
        self._data = data
        self._text = text
        self.headers = headers or {}
        self.url = "https://api.sharesight.com/api/v3/example"

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def json(self) -> Any:
        if self._data is _NOT_JSON:
            raise json.JSONDecodeError("not json", self._text, 0)
        return self._data

    async def text(self) -> str:
        return self._text


class FakeSession:
    """Queue responses for ``request`` and token ``post`` calls."""

    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = deque(responses)
        self.closed = False
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append((method, url, kwargs))
        return self.responses.popleft()

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self.request("POST", url, **kwargs)

    async def close(self) -> None:
        self.closed = True


_NOT_JSON = object()


def client(
    session: FakeSession,
    *,
    raise_for_status: bool = True,
    max_retries: int = 0,
) -> SharesightAPI:
    return SharesightAPI(
        "client",
        "secret",
        "code",
        "https://callback.invalid",
        "https://api.sharesight.com/oauth2/token",
        "https://api.sharesight.com/api/",
        use_token_file=False,
        session=session,  # type: ignore[arg-type]
        raise_for_status=raise_for_status,
        max_retries=max_retries,
        retry_backoff=0,
    )


def test_oauth_log_redaction_never_reproduces_credential_fragments() -> None:
    """Debug logging may retain metadata, but no part of a secret value."""
    redacted = _redact_token_data(
        {
            "access_token": "access-visible-prefix-and-suffix",
            "refresh_token": "refresh-visible-prefix-and-suffix",
            "id_token": "identity-token-value",
            "client_secret": "client-secret-value",
            "authorization_code": "authorization-code-value",
            "token_type": "Bearer",
            "expires_in": 1800,
            "scope": "read",
        }
    )

    assert redacted == {
        "access_token": "[redacted]",
        "refresh_token": "[redacted]",
        "id_token": "[redacted]",
        "client_secret": "[redacted]",
        "authorization_code": "[redacted]",
        "token_type": "Bearer",
        "expires_in": 1800,
        "scope": "read",
    }


@pytest.mark.asyncio
async def test_metadata_response_retains_rate_limit_headers() -> None:
    session = FakeSession(
        FakeResponse(
            200,
            {"portfolios": []},
            headers={
                "X-MinuteRate-Limit": "360",
                "X-MinuteRate-Remaining": "357",
            },
        )
    )

    response = await client(session).get_api_response(["v3", "portfolios", None], "token")

    assert isinstance(response, SharesightResponse)
    assert response.data == {"portfolios": []}
    assert response.status == 200
    assert response.headers["X-MinuteRate-Remaining"] == "357"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 201, 204])
async def test_every_2xx_status_is_success(status: int) -> None:
    payload = {} if status == 204 else {"ok": True}
    result = await client(FakeSession(FakeResponse(status, payload))).post_api_request(
        ["v3", "trades", None], {"trade": {}}, "token"
    )
    assert result == payload


@pytest.mark.asyncio
async def test_non_json_error_retains_status_in_legacy_mode() -> None:
    result = await client(
        FakeSession(FakeResponse(502, _NOT_JSON, text="upstream unavailable")),
        raise_for_status=False,
    ).get_api_request(["v3", "portfolios", None], "token")

    assert result == {"error": "upstream unavailable", "status_code": 502}


@pytest.mark.asyncio
async def test_json_error_gains_status_in_legacy_mode_without_mutating_body() -> None:
    body = {"error": 406, "reason": "Version not supported"}
    result = await client(
        FakeSession(FakeResponse(406, body)),
        raise_for_status=False,
    ).get_api_request(["v3", "markets", None], "token")

    assert result == {**body, "status_code": 406}
    assert "status_code" not in body


@pytest.mark.asyncio
async def test_api_error_retains_reason_transaction_and_headers() -> None:
    body = {
        "error": 406,
        "reason": "Version v3.0 not supported by endpoint",
        "transaction_id": 1234,
    }
    with pytest.raises(SharesightAPIError) as raised:
        await client(
            FakeSession(FakeResponse(406, body, headers={"X-Request-Id": "abc"}))
        ).get_api_request(["v3", "markets", None], "token")

    assert raised.value.status_code == 406
    assert raised.value.message == body["reason"]
    assert raised.value.response_data == body
    assert raised.value.response_headers["X-Request-Id"] == "abc"


@pytest.mark.asyncio
async def test_401_retains_body_for_lockout_detection() -> None:
    body = {
        "error": 10001,
        "reason": "Token incorrect, expired or locked out.",
    }
    with pytest.raises(SharesightAuthError) as raised:
        await client(FakeSession(FakeResponse(401, body))).get_api_request(
            ["v3", "portfolios", None], "token"
        )

    assert raised.value.status_code == 401
    assert raised.value.message == body["reason"]
    assert raised.value.response_data == body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body"),
    [
        (429, {"reason": "slow down"}),
        (403, {"reason": "Too many parallel requests. Currently 3 in process."}),
    ],
)
async def test_sharesight_rate_limit_variants_are_typed(status: int, body: dict[str, str]) -> None:
    with pytest.raises(SharesightRateLimitError) as raised:
        await client(
            FakeSession(FakeResponse(status, body, headers={"Retry-After": "12"}))
        ).get_api_request(["v3", "portfolios/1/performance", None], "token")

    assert raised.value.status_code == status
    assert raised.value.retry_after == 12
    assert raised.value.response_data == body


@pytest.mark.asyncio
async def test_exhausted_minute_budget_403_is_a_rate_limit() -> None:
    with pytest.raises(SharesightRateLimitError):
        await client(
            FakeSession(
                FakeResponse(
                    403,
                    {"reason": "request refused"},
                    headers={"x-minuterate-remaining": "0"},
                )
            )
        ).get_api_request(["v3", "portfolios", None], "token")


@pytest.mark.asyncio
async def test_entitlement_403_is_not_misclassified_as_rate_limit() -> None:
    """Budget headers can accompany a normal forbidden response."""
    with pytest.raises(SharesightAPIError) as raised:
        await client(
            FakeSession(
                FakeResponse(
                    403,
                    {"reason": "not entitled"},
                    headers={
                        "X-MinuteRate-Limit": "360",
                        "X-MinuteRate-Remaining": "359",
                    },
                )
            )
        ).get_api_request(["v3", "watchlist.json", None], "token")

    assert type(raised.value) is SharesightAPIError


@pytest.mark.asyncio
async def test_refresh_error_retains_real_status_and_oauth_body() -> None:
    body = {"error": "invalid_grant", "error_description": "revoked"}
    api = client(FakeSession(FakeResponse(400, body)))
    await api.inject_token(
        {
            "access_token": "expired",
            "refresh_token": "refresh",
            "token_expiry": 0,
        }
    )

    with pytest.raises(SharesightAuthError) as raised:
        await api.refresh_access_token()

    assert raised.value.status_code == 400
    assert raised.value.response_data == body


@pytest.mark.asyncio
async def test_refresh_token_is_retained_when_server_does_not_rotate_it() -> None:
    api = client(
        FakeSession(
            FakeResponse(
                200,
                {"access_token": "new-access", "expires_in": 1800},
            )
        )
    )
    await api.inject_token(
        {
            "access_token": "old-access",
            "refresh_token": "keep-me",
            "token_expiry": 0,
        }
    )

    assert await api.refresh_access_token() == "new-access"
    assert (await api.return_token())["refresh_token"] == "keep-me"


@pytest.mark.asyncio
async def test_transient_server_error_is_retried() -> None:
    session = FakeSession(
        FakeResponse(503, {"reason": "try again"}),
        FakeResponse(200, {"ok": True}),
    )

    assert await client(session, max_retries=1).get_api_request(
        ["v3", "portfolios", None], "token"
    ) == {"ok": True}
    assert len(session.requests) == 2


@pytest.mark.asyncio
async def test_reopened_owned_session_can_be_closed_again() -> None:
    api = SharesightAPI("", "", "", "", "", "https://api.invalid/api/")

    first_session = api._get_session()
    await api.close()
    assert first_session.closed

    second_session = api._get_session()
    assert second_session is not first_session
    assert not second_session.closed

    await api.close()
    assert second_session.closed


@pytest.mark.asyncio
async def test_non_get_request_keeps_endpoint_query_parameters() -> None:
    session = FakeSession(FakeResponse(201, {"ok": True}))
    await client(session).post_api_request(
        ["v3", "trades", {"dry_run": "true"}],
        {"trade": {}},
        "token",
    )

    _, _, kwargs = session.requests[0]
    assert kwargs["params"] == {"dry_run": "true"}
    assert kwargs["json"] == {"trade": {}}


@pytest.mark.asyncio
async def test_versioned_base_url_does_not_duplicate_version() -> None:
    session = FakeSession(FakeResponse(200, {"portfolios": []}))
    api = SharesightAPI(
        "client",
        "secret",
        "code",
        "https://callback.invalid",
        "https://api.sharesight.com/oauth2/token",
        "https://api.sharesight.com/api/v2/",
        use_token_file=False,
        session=session,  # type: ignore[arg-type]
        max_retries=0,
    )

    await api.get_api_request(["v2", "/portfolios", None], "token")
    assert session.requests[0][1] == "https://api.sharesight.com/api/v2/portfolios"


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("max_retries", -1),
        ("retry_backoff", -0.1),
        ("token_expiry_margin", -1),
    ],
)
def test_negative_retry_and_token_options_are_rejected(option: str, value: float) -> None:
    kwargs = {option: value}
    with pytest.raises(ValueError):
        SharesightAPI("", "", "", "", "", "https://api.invalid/api/", **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", [[], ["v3"], ["", "portfolios"], ["v3", ""]])
async def test_malformed_endpoint_is_rejected(endpoint: list[str]) -> None:
    with pytest.raises(ValueError):
        await client(FakeSession()).get_api_request(endpoint, "token")
