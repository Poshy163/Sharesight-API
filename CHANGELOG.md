# Changelog

All notable changes to this project are documented here. Versions follow
[Semantic Versioning](https://semver.org/).

## [1.6.0] - 2026-09-02

### Added

- Reconciled the response models against live production payloads: holdings
  now model `instrument_currency`, `instrument_price`, `group_id`/`group_name`,
  label objects and `number_of_unconfirmed_transactions`; performance reports
  model `sub_totals`, embedded `cash_accounts`, the `currency` object,
  `portfolio_tz_name` and `percentages_annualised`; payouts model the full
  franking, withholding, capital-gain-distribution, AMIT and DRP fields;
  trades model `market_price`, `capital_return_value` and attachment fields.
- Added models for benchmarks (including the undocumented `maximum_drawdown`
  and `return_over_drawdown`), portfolio user settings, user instruments,
  account metadata, watchlists, realised and unrealised CGT reports,
  sharechecker, official average purchase price and cost base, portfolio
  value, instrument prices, the performance index chart and single sign-on.
- Added typed helpers `get_watchlist()`, `get_sharechecker()`,
  `get_holding_average_purchase_price()`, `get_holding_cost_base()`,
  `get_holding_value_data()`, `get_portfolio_value()`,
  `list_instrument_prices()` and `get_single_sign_on()`. All are read-only;
  the mobile-tagged routes are labelled entitlement-dependent.
- `get_capital_gains()`, `get_unrealised_cgt()`, `get_portfolio_user_setting()`,
  `get_portfolio_benchmark()`, `get_portfolio_performance_index_chart()`,
  `list_user_instruments()` and `get_my_user()` now return typed models.
- Added `SharesightAPIError.is_version_unsupported`, `is_unauthorised`,
  `is_forbidden`, `is_not_found` and `is_retryable`, plus the exported
  `RETRYABLE_STATUS_CODES` set, so hosts can detect Sharesight's explicit
  "version not supported" 406 for V3-to-V2 fallback without string matching.

### Changed

- The three POSIX token-file permission tests are skipped on Windows, where
  `chmod` cannot express owner-only modes; they still run on Linux and macOS.
- `ValueSeriesResponse` documents the live `chart.data[].timestamp` wrapper
  alongside the apiDoc `values`/`portfolio_value_data` spellings.

[1.6.0]: https://github.com/Poshy163/Sharesight-API/compare/v1.5.0...v1.6.0

## [1.5.0] - 2026-08-31

### Added

- Added partial `TypedDict` response models for portfolios, holdings,
  performance, trades, payouts, cash accounts, groups, currencies, countries,
  custom investments, prices, adjustments, coupon rates and value series.
  Missing and nullable API fields remain valid.
- Added typed read-only helpers for the public v2/v3 portfolio, performance,
  valuation, diversity, tax, holding, trade, payout, cash, instrument, user,
  group, currency, country and custom-investment endpoints, plus clearly
  labelled entitlement-dependent benchmark and value-series reads.
- Added bounded opaque-cursor pagination for Sharesight's documented paginated
  routes, with repeated-cursor protection and no unsafe page-count guessing.
- Added opt-in `Decimal` JSON decoding, per-request timeouts, bounded retry
  jitter and a typed malformed-response exception.

### Changed

- Added explicit preferred-V3 helpers while preserving the legacy V2 response
  contracts of `list_portfolios()`, `get_portfolio()` and
  `get_portfolio_performance()`; corrected official `.json` route spellings
  where required.
- Portfolio/holding trade lists and holding payouts now deliberately use the
  public V2 routes; Sharesight marks their V3 counterparts as internal-only.
- Added explicit public V2 portfolio list, detail and performance fallbacks;
  modelled the V2 portfolio/cash-account and V3 custom-investment detail routes
  as the bare objects they actually return.
- Custom-investment child reads accept and preserve Sharesight's opaque page
  cursors rather than assuming numeric pages.
- Corrected the bundled example's client construction and V2 route spelling;
  it no longer prints OAuth token data or writes portfolio payloads unless the
  user explicitly opts in.
- Corrected `create_trade()` to post to `v2/trades.json`, wrap the trade body,
  and inject the portfolio id. It remains explicitly isolated as a
  write-capable method and is covered only with mocks.
- Token-file existence, replacement, permissions and deletion are now
  asynchronous; unique atomic temporary files and legacy/new owner-only
  permissions prevent predictable-symlink and brief-readable-file windows.
- OAuth log redaction now recursively removes nested credentials and writes
  only allowlisted metadata; token exceptions never retain raw error bodies.

[1.5.0]: https://github.com/Poshy163/Sharesight-API/compare/v1.4.0...v1.5.0

## [1.4.0] - 2026-08-27

### Added

- Added `SharesightResponse`, `get_api_response()`, and
  `request_api_response()` so callers can consume HTTP status and response
  headers without shared mutable state.
- Added typed coverage for Sharesight's non-standard HTTP 403 rate-limit
  responses and retained response headers on all API exceptions.
- Added Python 3.10 through 3.14 CI coverage, distribution validation, and
  a trusted-publishing release workflow.

### Changed

- Treat every HTTP 2xx response as successful, including empty HTTP 204
  responses.
- Retry HTTP 408, 425, and 504 in addition to the existing transient statuses.
- Preserve the current refresh token when an OAuth refresh response does not
  rotate it.
- Accept both canonical `/api/` and matching versioned API base URLs.
- Add the HTTP status to JSON error bodies returned through legacy
  non-raising calls.
- Allow `aiofiles` 24.1.0 through 25.x so Home Assistant environments with an
  existing 24.1 constraint remain resolvable; unconstrained installs select
  the current 25.1.0 release.
- Raise the minimum `aiohttp` version to 3.14.3 for its security fixes and
  current Home Assistant compatibility.
- Raise the isolated-build requirements to `setuptools` 84.0.0 and `wheel`
  0.48.0.
- Update the SHA-pinned GitHub Actions used for testing and trusted publishing.
- Require Python 3.10 or newer.

### Fixed

- Declare `aiohttp` and `aiofiles` as package dependencies so a clean
  `pip install SharesightAPI` is importable.
- Preserve status, reason, transaction data, and headers on authentication and
  API failures.
- Distinguish ordinary entitlement HTTP 403 responses from exhausted
  request-budget and parallel-report rate limits.
- Accept query parameters on non-GET requests.
- Avoid closing a caller-owned `aiohttp.ClientSession`, serialise concurrent
  token refreshes, create and re-close owned sessions safely, and write token
  files atomically.
- Stop changing the host application's root logger configuration.

[1.4.0]: https://github.com/Poshy163/Sharesight-API/compare/v1.3.0...v1.4.0
