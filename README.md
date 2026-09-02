# Sharesight API

[![Tests](https://github.com/Poshy163/Sharesight-API/actions/workflows/test.yml/badge.svg)](https://github.com/Poshy163/Sharesight-API/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/SharesightAPI.svg)](https://pypi.org/project/SharesightAPI/)
[![Python](https://img.shields.io/pypi/pyversions/SharesightAPI.svg)](https://pypi.org/project/SharesightAPI/)

An asynchronous Python client for Sharesight's v2 and v3 APIs.

- Supports GET, POST, PUT, PATCH, and DELETE requests.
- Retries transient HTTP and connection failures with bounded exponential backoff.
- Preserves HTTP status, structured error bodies, and response headers.
- Provides custom exceptions, an async context manager, and common convenience methods.
- Supports either built-in token-file handling or caller-managed OAuth tokens.

See [CHANGELOG.md](CHANGELOG.md) for release details and [example.py](example.py)
for a complete example.

## Installation

```bash
python -m pip install SharesightAPI
```

Python 3.10 or newer is required. Runtime dependencies (`aiohttp` and
`aiofiles`) are installed automatically.

## Getting API access

Sharesight describes API availability and OAuth setup on its
[official API page](https://portfolio.sharesight.com/api/). You may need to
contact Sharesight to have API access enabled for your account.

The canonical production endpoints are:

```python
redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
token_url = "https://api.sharesight.com/oauth2/token"
api_url_base = "https://api.sharesight.com/api/"
```

Endpoint lists carry their own version (`v2` or `v3`), so the canonical base
ends at `/api/`. Versioned bases such as `/api/v2/` are also accepted for
backward compatibility when the endpoint version matches.

## Creating a client

```python
from SharesightAPI import SharesightAPI

sharesight = SharesightAPI(
    client_id,
    client_secret,
    authorization_code,
    redirect_uri,
    token_url,
    api_url_base,
)
```

Use the async context manager when the library owns its HTTP session:

```python
async with SharesightAPI(
    client_id,
    client_secret,
    authorization_code,
    redirect_uri,
    token_url,
    api_url_base,
) as sharesight:
    access_token = await sharesight.validate_token()
    portfolios = await sharesight.get_api_request(["v3", "portfolios", None], access_token)
```

The client never closes a caller-supplied `aiohttp.ClientSession`. Call
`close()` when not using the context manager and the client created its own
session.

## Caller-managed tokens

Applications that already manage OAuth can disable token files and pass an
access token into each request:

```python
sharesight = SharesightAPI(
    "",
    "",
    "",
    "",
    token_url,
    api_url_base,
    use_token_file=False,
    session=shared_aiohttp_session,
    raise_for_status=True,
)

result = await sharesight.get_api_request(["v3", "portfolios", None], access_token)
```

`inject_token()` and `return_token()` are available when the application wants
the client to refresh a caller-stored token. A refresh response that omits a
replacement refresh token retains the token that just succeeded.

## Typed convenience methods

The client prefers public v3 endpoints, as Sharesight recommends, and uses v2
where v3 has no equivalent public aggregate. Response annotations come from
the partial `TypedDict` models exported by `SharesightAPI`; fields remain
optional because Sharesight omits data for empty, sold, delisted and
plan-limited positions.

```python
portfolios = await sharesight.list_portfolios_v3()
portfolio = await sharesight.get_portfolio_v3(portfolio_id)
# Stable V2 helpers (the unsuffixed list/detail/performance methods preserve
# their pre-1.5 routes and response shapes):
portfolios_v2 = await sharesight.list_portfolios_v2()
portfolio_v2 = await sharesight.get_portfolio_v2(portfolio_id)
performance = await sharesight.get_portfolio_performance_v3(
    portfolio_id,
    start_date="2026-01-01",
    end_date="2026-08-27",
)
performance_v2 = await sharesight.get_portfolio_performance_v2(portfolio_id)
holdings = await sharesight.list_holdings(portfolio_id)
all_holdings = await sharesight.list_all_holdings()
holding = await sharesight.get_holding(holding_id)
trades = await sharesight.list_trades(portfolio_id)
payouts = await sharesight.list_portfolio_payouts(portfolio_id)
cash_accounts = await sharesight.list_cash_accounts()
cash_account = await sharesight.get_cash_account(cash_account_id)
cash_transactions = await sharesight.list_cash_account_transactions(cash_account_id)
benchmark = await sharesight.get_portfolio_benchmark(portfolio_id)
value_history = await sharesight.get_portfolio_value_data(portfolio_id)
capital_gains = await sharesight.get_capital_gains(portfolio_id)
unrealised_cgt = await sharesight.get_unrealised_cgt(portfolio_id)
user_setting = await sharesight.get_portfolio_user_setting(portfolio_id)
index_chart = await sharesight.get_portfolio_performance_index_chart(portfolio_id)
portfolio_value = await sharesight.get_portfolio_value(portfolio_id)
user_instruments = await sharesight.list_user_instruments()
me = await sharesight.get_my_user()  # contains name and e-mail: never log it
watchlist = await sharesight.get_watchlist()
sharechecker = await sharesight.get_sharechecker(instrument_id)
instrument_prices = await sharesight.list_instrument_prices(instrument_id)
average_price = await sharesight.get_holding_average_purchase_price(holding_id)
cost_base = await sharesight.get_holding_cost_base(holding_id)
holding_values = await sharesight.get_holding_value_data(holding_id)
groups = await sharesight.list_groups()
currencies = await sharesight.list_currencies()
countries = await sharesight.list_countries(supported=True)
custom_investments = await sharesight.list_custom_investments(portfolio_id=portfolio_id)
custom_investment = await sharesight.get_custom_investment(custom_investment_id)
custom_prices = await sharesight.list_custom_investment_prices(custom_investment_id)
custom_adjustments = await sharesight.list_custom_investment_adjustments(custom_investment_id)
coupon_rates = await sharesight.list_custom_investment_coupon_rates(custom_investment_id)
```

| Data | Preferred endpoint |
|---|---|
| Portfolio list/detail | V3 `portfolios`, `portfolios/{id}` |
| Performance/holdings | Public V3 portfolio routes |
| Trades and holding payouts | Public V2 routes (the V3 equivalents are internal-scoped) |
| Valuation/diversity/tax/payout aggregates | V2 portfolio routes |
| Cash accounts/transactions | V2 cash-account routes |
| Benchmark, user setting | V3 internal-tagged routes; entitlement-dependent |
| Value series (portfolio and holding), portfolio value, watchlist, sharechecker, official cost base / average purchase price | V3 mobile-tagged routes; entitlement-dependent |
| Instrument price history | V2 mobile-tagged route; entitlement-dependent |
| Performance index | Public V3 portfolio route |
| User instruments/account/groups/currencies | Public V2 routes |
| Countries/custom-investment reads | Public V3 routes |
| Single sign-on link | Public V2 route; the returned `login_url` is a one-minute credential, never log or store it |

Routes tagged `internal` or `mobile` in Sharesight's apiDoc are served to
standard production tokens today but are not part of the public contract.
Expect HTTP 403, 404 or 406 on some plans and degrade gracefully; the
`is_version_unsupported` exception property (below) identifies Sharesight's
explicit "version not supported" refusal so a caller can retry the V2 route.

`create_trade()` is intentionally separated from the read-only group because
it mutates financial records. Test it with mocks or a Sharesight developer
sandbox before any authorised live use.

## Pagination and monetary precision

The aggregate endpoints above return complete arrays. For the documented V3
custom-investment routes that paginate, the generic collector follows the
opaque cursor returned in `pagination.page`:

```python
all_prices = await sharesight.get_all_pages(
    ["v3", f"custom_investment/{custom_investment_id}/prices.json", None],
    item_key="prices",
    per_page=100,
)
```

Pagination is bounded by `max_pages` and rejects malformed or repeated cursors
with `SharesightResponseError`. You can also pass the returned
`pagination.page` string through each dedicated helper's `page=` argument.
The collector never guesses another page from array length, so using it with a
non-paginated aggregate endpoint cannot duplicate a large response.

To preserve fractional JSON numbers as decimal values rather than binary
floats:

```python
sharesight = SharesightAPI(..., preserve_decimal=True)
```

Date-only and datetime values remain the exact strings supplied by Sharesight
so applications can apply their own timezone policy without the client
inventing one. Most are ISO-8601; a few legacy V2 portfolio fields use display
formats such as `01 Jan 2009`.

## Raw requests

An endpoint is `[version, path, query_parameters]`:

```python
portfolios = await sharesight.get_api_request(["v3", "portfolios", None], access_token)

value_history = await sharesight.get_api_request(
    ["v3", f"portfolios/{portfolio_id}/portfolio_value_data.json", None],
    access_token,
)
```

The raw `POST`, `PUT`, `PATCH`, and `DELETE` helpers can mutate Sharesight
records. Keep those calls outside polling code and validate them with mocks or
an authorised developer sandbox.

The official endpoint references are available for
[v2](https://portfolio.sharesight.com/api/2/doc/index.html) and
[v3](https://portfolio.sharesight.com/api/3/doc/index.html).

## Response metadata

The original request helpers return only the parsed body for backward
compatibility. Use `get_api_response()` when status and headers are also
needed:

```python
response = await sharesight.get_api_response(["v3", "portfolios", None], access_token)
print(response.status)
print(response.headers.get("X-MinuteRate-Remaining"))
print(response.data)
```

`request_api_response()` provides the same metadata-preserving interface for
other HTTP methods. Metadata belongs to the returned `SharesightResponse`
rather than mutable client-wide state, so concurrent requests cannot overwrite
one another.

## Exceptions

```python
from SharesightAPI import (
    SharesightAPIError,
    SharesightAuthError,
    SharesightError,
    SharesightRateLimitError,
    SharesightResponseError,
)
```

- `SharesightError` is the base exception.
- `SharesightAuthError` retains authentication status and headers. Normal API
  errors retain their structured body; token-endpoint bodies are reduced to a
  safe OAuth error code because providers may echo credentials in free text.
- `SharesightAPIError` exposes `status_code`, `message`, `response_data`, and
  `response_headers`, plus the classification properties `is_unauthorised`,
  `is_forbidden`, `is_not_found`, `is_retryable` and `is_version_unsupported`
  (Sharesight's HTTP 406 "API version N is not supported" refusal, the signal
  to fall back from V3 to V2). `RETRYABLE_STATUS_CODES` is exported.
- `SharesightRateLimitError` represents HTTP 429 and Sharesight's rate-limit
  HTTP 403, and may expose `retry_after`.
- `SharesightResponseError` represents a successful response with a malformed
  or non-advancing shape.

By default, failures return a body for backward compatibility. JSON error
bodies gain `status_code` when the server omitted it. Opt into exceptions with
`raise_for_status=True`:

```python
sharesight = SharesightAPI(
    client_id,
    client_secret,
    authorization_code,
    redirect_uri,
    token_url,
    api_url_base,
    raise_for_status=True,
)
```

## Retries

The client retries HTTP 408, 425, 429, 500, 502, 503, and 504 responses,
Sharesight's rate-limit HTTP 403, and transport failures:

```python
sharesight = SharesightAPI(
    client_id,
    client_secret,
    authorization_code,
    redirect_uri,
    token_url,
    api_url_base,
    max_retries=3,
    retry_backoff=1.0,
    retry_jitter=0.25,
    max_retry_delay=300,
    request_timeout=30,
)
```

Backoff doubles after each failure, adds bounded positive jitter, and never
exceeds `max_retry_delay`. Numeric `Retry-After` values are respected and
capped by the same limit. Set `max_retries=0` when a host application owns
scheduling and rate-limit backoff; this surfaces the rejection immediately
instead of sleeping inside the request.

## Token safety

The default token file is `sharesight_token_<client_id>.txt`. Token files and
dictionaries returned by `return_token()` contain credentials. Do not log,
commit, or attach them to bug reports. Call `delete_token()` when the stored
grant should be removed.

## Development

```bash
python -m pip install -r requirements_test.txt
python -m pip install -e .
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy SharesightAPI tests/typecheck_models.py
python -m build
python -m twine check dist/*
python scripts/check_dist.py dist
```

See [RELEASING.md](RELEASING.md) for the release and trusted-publishing flow.
