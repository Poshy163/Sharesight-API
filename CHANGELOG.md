# Changelog

All notable changes to this project are documented here. Versions follow
[Semantic Versioning](https://semver.org/).

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
