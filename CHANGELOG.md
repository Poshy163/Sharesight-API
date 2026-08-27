# Changelog

All notable changes to this project are documented here. Versions follow
[Semantic Versioning](https://semver.org/).

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
- Raise the minimum runtime dependencies to `aiofiles` 25.1.0 for current
  Python support and `aiohttp` 3.14.3 for its security fixes.
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
