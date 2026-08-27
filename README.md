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

## Convenience methods

```python
portfolios = await sharesight.list_portfolios()
portfolio = await sharesight.get_portfolio(portfolio_id)
performance = await sharesight.get_portfolio_performance(
    portfolio_id,
    start_date="2026-01-01",
    end_date="2026-08-27",
)
holdings = await sharesight.list_holdings(portfolio_id)
holding = await sharesight.get_holding(holding_id)
trades = await sharesight.list_trades(portfolio_id)
trade = await sharesight.create_trade(portfolio_id, trade_data)
cash_accounts = await sharesight.list_cash_accounts()
cash_account = await sharesight.get_cash_account(cash_account_id)
groups = await sharesight.list_groups()
```

## Raw requests

An endpoint is `[version, path, query_parameters]`:

```python
portfolios = await sharesight.get_api_request(["v3", "portfolios", None], access_token)

trade = await sharesight.post_api_request(
    ["v2", f"portfolios/{portfolio_id}/trades", {"dry_run": "true"}],
    {"trade": trade_data},
    access_token,
)
```

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
)
```

- `SharesightError` is the base exception.
- `SharesightAuthError` retains authentication status, body, and headers.
- `SharesightAPIError` exposes `status_code`, `message`, `response_data`, and
  `response_headers`.
- `SharesightRateLimitError` represents HTTP 429 and Sharesight's rate-limit
  HTTP 403, and may expose `retry_after`.

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
)
```

Backoff doubles after each failure. Numeric `Retry-After` values are respected
and capped at five minutes. Set `max_retries=0` when a host application owns
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
python -m build
python -m twine check dist/*
python scripts/check_dist.py dist
```

See [RELEASING.md](RELEASING.md) for the release and trusted-publishing flow.
