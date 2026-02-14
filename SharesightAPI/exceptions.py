class SharesightError(Exception):
    """Base exception for all Sharesight API errors."""


class SharesightAuthError(SharesightError):
    """Raised when authentication fails (invalid credentials, expired auth code, etc.)."""


class SharesightAPIError(SharesightError):
    """Raised when an API request fails with a non-success status code."""

    def __init__(self, status_code, message, response_data=None):
        self.status_code = status_code
        self.message = message
        self.response_data = response_data
        super().__init__(f"HTTP {status_code}: {message}")


class SharesightRateLimitError(SharesightAPIError):
    """Raised when the API returns a 429 Too Many Requests response."""

    def __init__(self, status_code=429, message="Rate limit exceeded", response_data=None, retry_after=None):
        self.retry_after = retry_after
        super().__init__(status_code, message, response_data)
