"""Regression tests for the public HTTP client contract."""

from __future__ import annotations

import json
import stat
import sys
from collections import deque
from decimal import Decimal
from typing import Any

import pytest

from SharesightAPI import (
    RETRYABLE_STATUS_CODES,
    SharesightAPI,
    SharesightAPIError,
    SharesightAuthError,
    SharesightRateLimitError,
    SharesightResponse,
    SharesightResponseError,
)
from SharesightAPI.SharesightAPI import _redact_token_data, _safe_token_log_data


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

    async def json(self, *, loads: Any = json.loads) -> Any:
        if self._data is _NOT_JSON:
            raise json.JSONDecodeError("not json", self._text, 0)
        if isinstance(self._data, str):
            return loads(self._data)
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
            "nested": {
                "token": "nested-token-value",
                "items": [[{"client_secret": "deep-secret-value"}]],
            },
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
        "nested": {
            "token": "[redacted]",
            "items": [[{"client_secret": "[redacted]"}]],
        },
    }


def test_non_object_oauth_response_is_omitted_from_logs() -> None:
    """A malformed token response may contain secrets in arbitrary text."""
    body = "upstream echoed client_secret=do-not-log-this"

    assert _safe_token_log_data(body) == "[non-object OAuth response omitted]"


def test_oauth_error_logs_are_allowlisted_not_pattern_scrubbed() -> None:
    body = {
        "error": "invalid_grant",
        "error_description": "upstream echoed client_secret=do-not-log-this",
        "access_token": "also-do-not-log",
        "nested": {"token": "nor-this"},
    }

    assert _safe_token_log_data(body) == {
        "error": "invalid_grant",
        "error_description": "[omitted]",
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
        ["v2", "trades.json", None], {"trade": {}}, "token"
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
async def test_refresh_error_retains_status_but_sanitizes_oauth_body() -> None:
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
    assert raised.value.response_data == {
        "error": "invalid_grant",
        "error_description": "[omitted]",
    }
    assert str(raised.value) == "HTTP 400: invalid_grant"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "secret",
    [
        "client_secret=must-never-escape",
        "authorizationcode123",
        "eyJhbGciOiJIUzI1NiJ9.payload_signature",
    ],
)
async def test_non_object_oauth_error_is_not_exposed_by_exception(secret: str) -> None:
    api = client(FakeSession(FakeResponse(400, _NOT_JSON, text=secret)))
    await api.inject_token(
        {
            "access_token": "expired",
            "refresh_token": "refresh",
            "token_expiry": 0,
        }
    )

    with pytest.raises(SharesightAuthError) as raised:
        await api.refresh_access_token()

    assert raised.value.response_data == {"error": "[omitted]"}
    assert secret not in str(raised.value)
    assert secret not in repr(raised.value.response_data)


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
        ["v2", "trades.json", {"dry_run": "true"}],
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

    await api.get_api_request(["v2", "/portfolios.json", None], "token")
    assert session.requests[0][1] == "https://api.sharesight.com/api/v2/portfolios.json"


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
async def test_typed_convenience_methods_use_documented_preferred_routes() -> None:
    session = FakeSession(*(FakeResponse(200, {}) for _ in range(24)))
    api = client(session)

    await api.list_portfolios_v3(
        consolidated=False,
        instrument_id=8,
        subscription_status=True,
        access_token="token",
    )
    await api.get_portfolio_v3(
        7, consolidated=False, subscription_status=True, access_token="token"
    )
    await api.get_portfolio_performance_v3(
        7,
        "2026-01-01",
        "2026-08-31",
        grouping="market",
        consolidated=False,
        include_sales=True,
        include_limited=True,
        report_combined=True,
        labels=["growth", "income"],
        custom_group_id=4,
        benchmark_code="XJO",
        access_token="token",
    )
    await api.get_portfolio_valuation(
        7,
        balance_date="2026-08-31",
        grouping="market",
        consolidated=False,
        include_sales=True,
        custom_group_id=4,
        access_token="token",
    )
    await api.get_portfolio_diversity(
        7,
        date="2026-08-31",
        grouping="currency",
        consolidated=False,
        custom_group_id=4,
        access_token="token",
    )
    await api.get_capital_gains(
        7, start_date="2026-07-01", end_date="2026-08-31", access_token="token"
    )
    await api.get_unrealised_cgt(7, balance_date="2026-08-31", access_token="token")
    await api.list_holdings(7, consolidated=False, access_token="token")
    await api.get_holding(
        8,
        average_purchase_price=True,
        cost_base=True,
        values_over_time="2026-01-01",
        access_token="token",
    )
    await api.list_holding_trades(8, unique_identifier="holding-ref", access_token="token")
    await api.list_trades(
        7,
        start_date="2026-01-01",
        end_date="2026-08-31",
        unique_identifier="portfolio-ref",
        access_token="token",
    )
    await api.list_portfolio_payouts(
        7,
        start_date="2026-01-01",
        end_date="2026-08-31",
        use_date="paid_on",
        access_token="token",
    )
    await api.list_holding_payouts(
        8,
        start_date="2026-01-01",
        end_date="2026-08-31",
        use_date="paid_on",
        access_token="token",
    )
    await api.list_cash_accounts(date="2026-08-31", access_token="token")
    await api.get_cash_account(9, date="2026-08-31", access_token="token")
    await api.list_cash_account_transactions(
        9,
        from_date="2026-01-01",
        to_date="2026-08-31",
        description="deposit",
        foreign_identifier="cash-ref",
        access_token="token",
    )
    await api.get_portfolio_user_setting(7, consolidated=False, access_token="token")
    await api.get_portfolio_benchmark(
        7,
        start_date="2026-01-01",
        end_date="2026-08-31",
        instrument_id=8,
        consolidated=False,
        interest_method="simple",
        access_token="token",
    )
    await api.get_portfolio_value_data(
        7, start_date="2026-01-01", consolidated=True, access_token="token"
    )
    await api.get_portfolio_performance_index_chart(
        7,
        start_date="2026-01-01",
        end_date="2026-08-31",
        grouping="market",
        consolidated=False,
        custom_group_id=4,
        benchmark_code="XJO",
        access_token="token",
    )
    await api.list_user_instruments(access_token="token")
    await api.get_my_user(access_token="token")
    await api.list_groups(access_token="token")
    await api.list_currencies(access_token="token")

    assert [(request[1], request[2].get("params")) for request in session.requests] == [
        (
            "https://api.sharesight.com/api/v3/portfolios",
            {
                "consolidated": "false",
                "instrument_id": "8",
                "subscription_status": "true",
            },
        ),
        (
            "https://api.sharesight.com/api/v3/portfolios/7",
            {"consolidated": "false", "subscription_status": "true"},
        ),
        (
            "https://api.sharesight.com/api/v3/portfolios/7/performance",
            {
                "start_date": "2026-01-01",
                "end_date": "2026-08-31",
                "grouping": "market",
                "consolidated": "false",
                "include_sales": "true",
                "include_limited": "true",
                "report_combined": "true",
                "labels[]": ["growth", "income"],
                "custom_group_id": "4",
                "benchmark_code": "XJO",
            },
        ),
        (
            "https://api.sharesight.com/api/v2/portfolios/7/valuation.json",
            {
                "balance_date": "2026-08-31",
                "grouping": "market",
                "consolidated": "false",
                "include_sales": "true",
                "custom_group_id": "4",
            },
        ),
        (
            "https://api.sharesight.com/api/v2/portfolios/7/diversity.json",
            {
                "date": "2026-08-31",
                "grouping": "currency",
                "consolidated": "false",
                "custom_group_id": "4",
            },
        ),
        (
            "https://api.sharesight.com/api/v2/portfolios/7/capital_gains.json",
            {"start_date": "2026-07-01", "end_date": "2026-08-31"},
        ),
        (
            "https://api.sharesight.com/api/v2/portfolios/7/unrealised_cgt.json",
            {"balance_date": "2026-08-31"},
        ),
        (
            "https://api.sharesight.com/api/v3/portfolios/7/holdings",
            {"consolidated": "false"},
        ),
        (
            "https://api.sharesight.com/api/v3/holdings/8",
            {
                "average_purchase_price": "true",
                "cost_base": "true",
                "values_over_time": "2026-01-01",
            },
        ),
        (
            "https://api.sharesight.com/api/v2/holdings/8/trades.json",
            {"unique_identifier": "holding-ref"},
        ),
        (
            "https://api.sharesight.com/api/v2/portfolios/7/trades.json",
            {
                "start_date": "2026-01-01",
                "end_date": "2026-08-31",
                "unique_identifier": "portfolio-ref",
            },
        ),
        (
            "https://api.sharesight.com/api/v2/portfolios/7/payouts.json",
            {
                "start_date": "2026-01-01",
                "end_date": "2026-08-31",
                "use_date": "paid_on",
            },
        ),
        (
            "https://api.sharesight.com/api/v2/holdings/8/payouts.json",
            {
                "start_date": "2026-01-01",
                "end_date": "2026-08-31",
                "use_date": "paid_on",
            },
        ),
        (
            "https://api.sharesight.com/api/v2/cash_accounts.json",
            {"date": "2026-08-31"},
        ),
        (
            "https://api.sharesight.com/api/v2/cash_accounts/9.json",
            {"date": "2026-08-31"},
        ),
        (
            "https://api.sharesight.com/api/v2/cash_accounts/9/cash_account_transactions.json",
            {
                "from": "2026-01-01",
                "to": "2026-08-31",
                "description": "deposit",
                "foreign_identifier": "cash-ref",
            },
        ),
        (
            "https://api.sharesight.com/api/v3/portfolios/7/user_setting",
            {"consolidated": "false"},
        ),
        (
            "https://api.sharesight.com/api/v3/portfolios/7/benchmark.json",
            {
                "start_date": "2026-01-01",
                "end_date": "2026-08-31",
                "instrument_id": "8",
                "consolidated": "false",
                "interest_method": "simple",
            },
        ),
        (
            "https://api.sharesight.com/api/v3/portfolios/7/portfolio_value_data.json",
            {"start_date": "2026-01-01", "consolidated": "true"},
        ),
        (
            "https://api.sharesight.com/api/v3/portfolios/7/performance_index_chart",
            {
                "start_date": "2026-01-01",
                "end_date": "2026-08-31",
                "grouping": "market",
                "consolidated": "false",
                "custom_group_id": "4",
                "benchmark_code": "XJO",
            },
        ),
        ("https://api.sharesight.com/api/v2/user_instruments.json", None),
        ("https://api.sharesight.com/api/v2/my_user.json", None),
        ("https://api.sharesight.com/api/v2/groups.json", None),
        ("https://api.sharesight.com/api/v2/currencies.json", None),
    ]


@pytest.mark.asyncio
async def test_legacy_portfolio_helpers_keep_v2_response_contracts() -> None:
    portfolios = {"portfolios": [{"id": 7, "name": "Legacy shape"}]}
    portfolio = {"id": 7, "name": "Legacy shape"}
    performance = {"portfolio_id": 7, "value": 123.45}
    session = FakeSession(
        FakeResponse(200, portfolios),
        FakeResponse(200, portfolio),
        FakeResponse(200, performance),
    )
    api = client(session)

    assert await api.list_portfolios(access_token="token") == portfolios
    assert await api.get_portfolio(7, access_token="token") == portfolio
    assert (
        await api.get_portfolio_performance(
            7,
            "2026-01-01",
            "2026-08-31",
            access_token="token",
        )
        == performance
    )
    assert [request[1] for request in session.requests] == [
        "https://api.sharesight.com/api/v2/portfolios.json",
        "https://api.sharesight.com/api/v2/portfolios/7.json",
        "https://api.sharesight.com/api/v2/portfolios/7/performance.json",
    ]


@pytest.mark.asyncio
async def test_public_fallback_and_custom_investment_helpers_match_wire_shapes() -> None:
    """Exercise routes whose bare objects/cursors differ from common envelopes."""
    portfolio = {"id": 7, "name": "V2 Portfolio", "inception_date": "01 Jan 2009"}
    cash_account = {"id": 9, "name": "Broker Cash", "currency": "AUD"}
    custom_investment = {
        "id": 21,
        "portfolio_id": 7,
        "code": "MYBOND",
        "currency_code": "NZD",
    }
    price_page = {
        "id": 21,
        "prices": [
            {
                "id": 22,
                "lastTradedPrice": 10.5,
                "lastTradedOn": "2026-08-30",
                "lastTradedAt": "2026-08-30T00:00:00Z",
            }
        ],
        "pagination": {"page": "next-cursor==", "per_page": 100},
    }
    adjustment = {
        "id": 23,
        "amount_per_share": "1.25",
        "announced_on": "2026-08-01",
        "goes_ex_on": "2026-08-10",
        "paid_on": "2026-08-31",
        "currency_code": "NZD",
    }
    session = FakeSession(
        FakeResponse(200, {"portfolios": [portfolio]}),
        FakeResponse(200, portfolio),
        FakeResponse(200, {"portfolio_id": 7, "total_gain": 123.45}),
        FakeResponse(200, cash_account),
        FakeResponse(200, {"holdings": [{"id": 8}]}),
        FakeResponse(200, {"countries": [{"id": 1, "code": "NZ", "supported": True}]}),
        FakeResponse(200, {"custom_investments": [custom_investment]}),
        FakeResponse(200, custom_investment),
        FakeResponse(200, price_page),
        FakeResponse(
            200,
            {
                "adjustments": [adjustment],
                "pagination": {"page": "adjustment-cursor==", "per_page": 50},
            },
        ),
        FakeResponse(200, {"adjustment": adjustment, **adjustment}),
        FakeResponse(
            200,
            {
                "coupon_rates": [{"id": 24, "interest_rate": 8.25, "date": "2026-08-01"}],
                "pagination": {"page": None, "per_page": 50},
            },
        ),
    )
    api = client(session)

    portfolios = await api.list_portfolios_v2(access_token="token")
    portfolio_detail = await api.get_portfolio_v2(7, access_token="token")
    performance = await api.get_portfolio_performance_v2(
        7,
        "2026-01-01",
        "2026-08-31",
        grouping="market",
        consolidated=False,
        include_sales=True,
        custom_group_id=4,
        access_token="token",
    )
    returned_cash = await api.get_cash_account(9, access_token="token")
    holdings = await api.list_all_holdings(access_token="token")
    countries = await api.list_countries(supported=True, access_token="token")
    investments = await api.list_custom_investments(portfolio_id=7, access_token="token")
    investment = await api.get_custom_investment(21, access_token="token")
    prices = await api.list_custom_investment_prices(
        21,
        start_date="2026-01-01",
        end_date="2026-08-31",
        page="price-cursor==",
        per_page=100,
        access_token="token",
    )
    adjustments = await api.list_custom_investment_adjustments(
        21, page="adjustment-cursor==", access_token="token"
    )
    adjustment_detail = await api.get_adjustment(23, access_token="token")
    coupon_rates = await api.list_custom_investment_coupon_rates(
        21, start_date="2026-01-01", per_page=50, access_token="token"
    )

    assert portfolios["portfolios"][0]["id"] == 7
    assert portfolio_detail["id"] == 7
    assert performance["total_gain"] == 123.45
    assert returned_cash["id"] == 9
    assert holdings["holdings"][0]["id"] == 8
    assert countries["countries"][0]["code"] == "NZ"
    assert investments["custom_investments"][0]["code"] == "MYBOND"
    assert investment["id"] == 21
    assert prices["prices"][0]["lastTradedPrice"] == 10.5
    assert adjustments["adjustments"][0]["amount_per_share"] == "1.25"
    assert adjustment_detail["adjustment"]["id"] == 23
    assert coupon_rates["coupon_rates"][0]["interest_rate"] == 8.25

    assert [(request[1], request[2].get("params")) for request in session.requests] == [
        ("https://api.sharesight.com/api/v2/portfolios.json", None),
        ("https://api.sharesight.com/api/v2/portfolios/7.json", None),
        (
            "https://api.sharesight.com/api/v2/portfolios/7/performance.json",
            {
                "start_date": "2026-01-01",
                "end_date": "2026-08-31",
                "grouping": "market",
                "consolidated": "false",
                "include_sales": "true",
                "custom_group_id": "4",
            },
        ),
        ("https://api.sharesight.com/api/v2/cash_accounts/9.json", None),
        ("https://api.sharesight.com/api/v3/holdings", None),
        ("https://api.sharesight.com/api/v3/countries", {"supported": "true"}),
        (
            "https://api.sharesight.com/api/v3/custom_investments",
            {"portfolio_id": "7"},
        ),
        ("https://api.sharesight.com/api/v3/custom_investments/21", None),
        (
            "https://api.sharesight.com/api/v3/custom_investment/21/prices.json",
            {
                "start_date": "2026-01-01",
                "end_date": "2026-08-31",
                "page": "price-cursor==",
                "per_page": "100",
            },
        ),
        (
            "https://api.sharesight.com/api/v3/custom_investments/21/adjustments",
            {"page": "adjustment-cursor=="},
        ),
        ("https://api.sharesight.com/api/v3/adjustments/23", None),
        (
            "https://api.sharesight.com/api/v3/custom_investments/21/coupon_rates",
            {"start_date": "2026-01-01", "per_page": "50"},
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("page", "per_page"),
    [(0, None), ("", None), (None, 0), (None, 101)],
)
async def test_custom_investment_pagination_rejects_invalid_controls(
    page: int | str | None, per_page: int | None
) -> None:
    with pytest.raises(ValueError):
        await client(FakeSession()).list_custom_investment_prices(
            21, page=page, per_page=per_page, access_token="token"
        )


@pytest.mark.asyncio
async def test_documented_model_wire_shapes_are_preserved() -> None:
    holding = {
        "holding": {
            "id": 8,
            "cost_base": {"total_value": 100.0, "value_per_share": 10.0},
        }
    }
    adjustments = {
        "adjustments": [
            {
                "id": 23,
                "amount_per_share": "1.25",
                "tax_credit": "0.10",
                "franked_percent": None,
                "drp_price": "9.95",
            }
        ],
        "pagination": {"page": None, "per_page": 50},
    }
    currencies = {
        "currencies": [
            {"code": "AUD", "source_feeds": {"ecb": None}},
            {"code": "NZD", "source_feeds": "legacy-feed"},
        ]
    }
    api = client(
        FakeSession(
            FakeResponse(200, holding),
            FakeResponse(200, adjustments),
            FakeResponse(200, currencies),
        )
    )

    returned_holding = await api.get_holding(8, cost_base=True, access_token="token")
    returned_adjustments = await api.list_custom_investment_adjustments(21, access_token="token")
    returned_currencies = await api.list_currencies(access_token="token")

    assert returned_holding["holding"]["cost_base"] == {
        "total_value": 100.0,
        "value_per_share": 10.0,
    }
    assert returned_adjustments["adjustments"][0]["amount_per_share"] == "1.25"
    assert returned_adjustments["adjustments"][0]["drp_price"] == "9.95"
    assert returned_currencies["currencies"][0]["source_feeds"] == {"ecb": None}
    assert returned_currencies["currencies"][1]["source_feeds"] == "legacy-feed"


@pytest.mark.asyncio
async def test_account_and_mobile_helpers_use_documented_routes() -> None:
    """The 1.6 helpers must call the exact routes the apiDoc publishes."""
    session = FakeSession(*(FakeResponse(200, {}) for _ in range(9)))
    api = client(session)

    await api.get_single_sign_on(access_token="token")
    await api.get_watchlist(start_date="2026-08-01", access_token="token")
    await api.get_sharechecker(4321, access_token="token")
    await api.get_holding_average_purchase_price(55, access_token="token")
    await api.get_holding_cost_base(55, access_token="token")
    await api.get_holding_value_data(55, start_date="2026-01-01", access_token="token")
    await api.get_portfolio_value(7, consolidated=False, access_token="token")
    await api.list_instrument_prices(
        4321, start_date="2026-01-01", end_date="2026-08-31", access_token="token"
    )
    await api.get_watchlist(access_token="token")

    assert [request[1] for request in session.requests] == [
        "https://api.sharesight.com/api/v2/single_sign_on.json",
        "https://api.sharesight.com/api/v3/watchlist.json",
        "https://api.sharesight.com/api/v3/instruments/4321/sharechecker",
        "https://api.sharesight.com/api/v3/holdings/55/average_purchase_price.json",
        "https://api.sharesight.com/api/v3/holdings/55/cost_base.json",
        "https://api.sharesight.com/api/v3/holdings/55/holding_value_data.json",
        "https://api.sharesight.com/api/v3/portfolios/7/value",
        "https://api.sharesight.com/api/v2/instruments/4321/prices.json",
        "https://api.sharesight.com/api/v3/watchlist.json",
    ]
    assert session.requests[1][2]["params"] == {"start_date": "2026-08-01"}
    assert session.requests[5][2]["params"] == {"start_date": "2026-01-01"}
    assert session.requests[6][2]["params"] == {"consolidated": "false"}
    assert session.requests[7][2]["params"] == {
        "start_date": "2026-01-01",
        "end_date": "2026-08-31",
    }
    assert session.requests[8][2].get("params") is None


@pytest.mark.asyncio
async def test_live_report_and_account_wire_shapes_are_preserved() -> None:
    """Fields observed on production payloads must survive the typed helpers.

    The shapes mirror live 2026-09 responses (synthetic values): grouped
    ``sub_totals``, embedded cash accounts, per-holding ``instrument_currency``
    and label objects, the undocumented benchmark drawdown pair, the
    ``chart.data`` value-series wrapper and watchlist price diffs.
    """
    performance = {
        "report": {
            "id": "7_2026-01-01_2026-08-31",
            "portfolio_tz_name": "Australia/Sydney",
            "currency": {"id": 1, "code": "AUD", "symbol": "$", "qualified_symbol": "A$"},
            "value": 1000.0,
            "percentages_annualised": False,
            "holdings": [
                {
                    "id": 11,
                    "symbol": "AAA",
                    "instrument_currency": {"code": "USD", "symbol": "$"},
                    "instrument_price": 12.5,
                    "group_id": 2,
                    "group_name": "NASDAQ",
                    "labels": [{"id": 9, "name": "Growth", "color": "#ff0000"}],
                    "number_of_unconfirmed_transactions": 1,
                }
            ],
            "sub_totals": [
                {"group_id": 2, "group_name": "NASDAQ", "value": 600.0, "total_gain": 60.0}
            ],
            "cash_accounts": [
                {"id": 5, "key": 5, "name": "Cash", "value": 400.0, "currency": {"code": "AUD"}}
            ],
        }
    }
    benchmark = {
        "benchmark": {
            "instrument": {"code": "A200", "market_code": "ASX"},
            "capital_gain_percent": 12.5,
            "maximum_drawdown": 8.4,
            "return_over_drawdown": 1.5,
        }
    }
    value_series = {"chart": {"data": [{"timestamp": "2026-08-30", "value": 1000.0}]}}
    watchlist = {
        "watchlist": [
            {
                "instrument": {"code": "AAPL", "market_code": "NASDAQ"},
                "price": {"value": 1.0, "diff_value": -0.5, "diff_percent": -0.25},
            }
        ]
    }
    payouts = {
        "payouts": [
            {
                "id": None,
                "currency": "AUD",
                "franking_credits": 1.5,
                "drp_trade_attributes": {"dividend_reinvested": False, "price": "0.0"},
            }
        ]
    }
    api = client(
        FakeSession(
            FakeResponse(200, performance),
            FakeResponse(200, benchmark),
            FakeResponse(200, value_series),
            FakeResponse(200, watchlist),
            FakeResponse(200, payouts),
        )
    )

    report = (await api.get_portfolio_performance_v3(7, access_token="token"))["report"]
    returned_benchmark = (await api.get_portfolio_benchmark(7, access_token="token"))["benchmark"]
    returned_series = await api.get_portfolio_value_data(7, access_token="token")
    returned_watchlist = (await api.get_watchlist(access_token="token"))["watchlist"]
    returned_payouts = (await api.list_portfolio_payouts(7, access_token="token"))["payouts"]

    assert report["holdings"][0]["instrument_currency"]["code"] == "USD"
    assert report["holdings"][0]["labels"][0]["name"] == "Growth"
    assert report["sub_totals"][0]["group_name"] == "NASDAQ"
    assert report["cash_accounts"][0]["value"] == 400.0
    assert report["currency"]["qualified_symbol"] == "A$"
    assert returned_benchmark["maximum_drawdown"] == 8.4
    assert returned_benchmark["return_over_drawdown"] == 1.5
    assert isinstance(returned_series, dict)
    assert returned_series["chart"]["data"][0]["timestamp"] == "2026-08-30"
    assert returned_watchlist[0]["price"]["diff_percent"] == -0.25
    assert returned_payouts[0]["id"] is None
    assert returned_payouts[0]["drp_trade_attributes"]["dividend_reinvested"] is False


@pytest.mark.asyncio
async def test_version_unsupported_and_status_classification_properties() -> None:
    """Hosts fall back from V3 to V2 only on Sharesight's explicit 406 reason."""
    session = FakeSession(
        FakeResponse(406, {"reason": "API version 3 is not supported for this endpoint"}),
        FakeResponse(406, {"reason": "Not Acceptable"}),
        FakeResponse(404, {"reason": "Portfolio not found"}),
        FakeResponse(403, {"reason": "This feature requires a plan upgrade"}),
        FakeResponse(503, {"reason": "Maintenance"}),
    )
    api = client(session)

    with pytest.raises(SharesightAPIError) as unsupported:
        await api.get_api_request(["v3", "portfolios/7/benchmark.json", None], "token")
    with pytest.raises(SharesightAPIError) as plain_406:
        await api.get_api_request(["v3", "portfolios/7/benchmark.json", None], "token")
    with pytest.raises(SharesightAPIError) as missing:
        await api.get_api_request(["v3", "portfolios/7", None], "token")
    with pytest.raises(SharesightAPIError) as forbidden:
        await api.get_api_request(["v3", "portfolios/7", None], "token")
    with pytest.raises(SharesightAPIError) as outage:
        await api.get_api_request(["v3", "portfolios/7", None], "token")

    assert unsupported.value.is_version_unsupported is True
    assert plain_406.value.is_version_unsupported is False
    assert missing.value.is_not_found is True
    assert missing.value.is_version_unsupported is False
    assert forbidden.value.is_forbidden is True
    assert forbidden.value.is_retryable is False
    assert outage.value.is_retryable is True
    assert outage.value.is_unauthorised is False
    assert SharesightAuthError().is_unauthorised is True
    assert 429 in RETRYABLE_STATUS_CODES


@pytest.mark.asyncio
async def test_create_trade_uses_documented_route_and_injects_portfolio_id() -> None:
    session = FakeSession(FakeResponse(201, {"trade": {"id": 1}}))

    await client(session).create_trade(
        7,
        {"transaction_date": "2026-08-31", "quantity": "1.25"},
        access_token="token",
    )

    _, url, kwargs = session.requests[0]
    assert url == "https://api.sharesight.com/api/v2/trades.json"
    assert kwargs["json"] == {
        "trade": {
            "portfolio_id": 7,
            "transaction_date": "2026-08-31",
            "quantity": "1.25",
        }
    }


@pytest.mark.asyncio
async def test_generic_pagination_follows_opaque_cursor_and_preserves_metadata() -> None:
    session = FakeSession(
        FakeResponse(
            200,
            {"prices": [{"id": 1}, {"id": 2}], "pagination": {"page": "next=="}},
        ),
        FakeResponse(
            200,
            {
                "prices": [{"id": 3}],
                "id": 21,
                "pagination": {"page": None},
            },
        ),
    )

    result = await client(session).get_all_pages(
        ["v3", "custom_investment/21/prices.json", {"start_date": "2026-01-01"}],
        item_key="prices",
        per_page=2,
        access_token="token",
    )

    assert result["prices"] == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert "pagination" not in result
    assert session.requests[0][2]["params"] == {
        "start_date": "2026-01-01",
        "per_page": 2,
    }
    assert session.requests[1][2]["params"]["page"] == "next=="


@pytest.mark.asyncio
async def test_generic_pagination_stops_without_cursor_even_for_full_array() -> None:
    session = FakeSession(FakeResponse(200, {"trades": [{"id": index} for index in range(100)]}))

    result = await client(session).get_all_pages(
        ["v2", "portfolios/7/trades.json", None],
        item_key="trades",
        access_token="token",
    )

    assert len(result["trades"]) == 100
    assert len(session.requests) == 1


@pytest.mark.asyncio
async def test_generic_pagination_rejects_repeated_cursor() -> None:
    session = FakeSession(
        FakeResponse(200, {"prices": [{"id": 1}], "pagination": {"page": "same=="}}),
        FakeResponse(200, {"prices": [{"id": 2}], "pagination": {"page": "same=="}}),
    )

    with pytest.raises(SharesightResponseError, match="repeated cursor"):
        await client(session).get_all_pages(
            ["v3", "custom_investment/21/prices.json", None],
            item_key="prices",
            access_token="token",
        )


@pytest.mark.asyncio
async def test_pagination_rejects_an_invalid_response_shape() -> None:
    with pytest.raises(SharesightResponseError):
        await client(FakeSession(FakeResponse(200, {"trades": None}))).get_all_pages(
            ["v2", "portfolios/7/trades.json", None],
            item_key="trades",
            access_token="token",
        )


@pytest.mark.asyncio
async def test_decimal_json_decoding_is_opt_in() -> None:
    session = FakeSession(FakeResponse(200, '{"value": 0.1}'))
    api = SharesightAPI(
        "client",
        "secret",
        "code",
        "https://callback.invalid",
        "https://api.sharesight.com/oauth2/token",
        "https://api.sharesight.com/api/",
        use_token_file=False,
        session=session,  # type: ignore[arg-type]
        max_retries=0,
        preserve_decimal=True,
    )

    result = await api.get_api_request(["v3", "portfolios/7/value", None], "token")
    assert result["value"] == Decimal("0.1")


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("request_timeout", 0),
        ("retry_jitter", -0.1),
        ("max_retry_delay", -0.1),
    ],
)
def test_invalid_request_policy_options_are_rejected(option: str, value: float) -> None:
    with pytest.raises(ValueError):
        SharesightAPI("", "", "", "", "", "https://api.invalid/api/", **{option: value})


@pytest.mark.asyncio
async def test_none_timeout_inherits_session_default_for_api_requests() -> None:
    session = FakeSession(FakeResponse(200, {"portfolios": []}))
    api = SharesightAPI(
        "client",
        "secret",
        "code",
        "https://callback.invalid",
        "https://api.sharesight.com/oauth2/token",
        "https://api.sharesight.com/api/",
        use_token_file=False,
        session=session,  # type: ignore[arg-type]
        request_timeout=None,
    )

    await api.get_api_request(["v3", "portfolios", None], "token")

    assert "timeout" not in session.requests[0][2]


@pytest.mark.asyncio
async def test_none_timeout_inherits_session_default_for_token_requests() -> None:
    session = FakeSession(FakeResponse(200, {"access_token": "new", "expires_in": 1800}))
    api = SharesightAPI(
        "client",
        "secret",
        "code",
        "https://callback.invalid",
        "https://api.sharesight.com/oauth2/token",
        "https://api.sharesight.com/api/",
        use_token_file=False,
        session=session,  # type: ignore[arg-type]
        request_timeout=None,
    )
    await api.inject_token({"refresh_token": "refresh"})

    await api.refresh_access_token()

    assert "timeout" not in session.requests[0][2]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX file-permission semantics are not available on Windows",
)
@pytest.mark.asyncio
async def test_token_file_is_private_atomic_and_delete_is_idempotent(tmp_path) -> None:
    token_file = tmp_path / "sharesight-token.json"
    api = SharesightAPI(
        "client",
        "secret",
        "code",
        "https://callback.invalid",
        "https://api.sharesight.com/oauth2/token",
        "https://api.sharesight.com/api/",
        token_file_name=str(token_file),
        session=FakeSession(),  # type: ignore[arg-type]
    )

    await api.inject_token(
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "token_expiry": 1234,
        }
    )

    assert token_file.exists()
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert not token_file.with_suffix(".json.tmp").exists()
    await api.delete_token()
    await api.delete_token()
    assert not token_file.exists()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX file-permission semantics are not available on Windows",
)
@pytest.mark.asyncio
async def test_loading_legacy_token_file_repairs_permissions(tmp_path) -> None:
    token_file = tmp_path / "legacy-token.json"
    token_file.write_text(
        json.dumps(
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "token_expiry": 1234,
                "auth_code": None,
            }
        )
    )
    token_file.chmod(0o644)
    api = SharesightAPI(
        "client",
        "secret",
        "code",
        "https://callback.invalid",
        "https://api.sharesight.com/oauth2/token",
        "https://api.sharesight.com/api/",
        token_file_name=str(token_file),
        session=FakeSession(),  # type: ignore[arg-type]
    )

    assert (await api.load_tokens())[0] == "access"
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX file-permission semantics are not available on Windows",
)
@pytest.mark.asyncio
async def test_token_save_does_not_follow_predictable_temp_symlink(tmp_path) -> None:
    token_file = tmp_path / "sharesight-token.json"
    trap_file = tmp_path / "trap.txt"
    trap_file.write_text("unchanged")
    predictable_temp = token_file.with_suffix(".json.tmp")
    predictable_temp.symlink_to(trap_file)
    api = SharesightAPI(
        "client",
        "secret",
        "code",
        "https://callback.invalid",
        "https://api.sharesight.com/oauth2/token",
        "https://api.sharesight.com/api/",
        token_file_name=str(token_file),
        session=FakeSession(),  # type: ignore[arg-type]
    )

    await api.inject_token({"access_token": "access", "refresh_token": "refresh"})

    assert trap_file.read_text() == "unchanged"
    assert predictable_temp.is_symlink()
    assert not list(tmp_path.glob(".sharesight-token.json.*.tmp"))


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", [[], ["v3"], ["", "portfolios"], ["v3", ""]])
async def test_malformed_endpoint_is_rejected(endpoint: list[str]) -> None:
    with pytest.raises(ValueError):
        await client(FakeSession()).get_api_request(endpoint, "token")
