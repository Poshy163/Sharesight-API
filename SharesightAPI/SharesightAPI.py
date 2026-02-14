import asyncio
import aiofiles
import aiofiles.os
import os
import aiohttp
import json
import time
import logging
from typing import Optional, Tuple, Any, Dict, Union

from .exceptions import (
    SharesightAPIError,
    SharesightAuthError,
    SharesightRateLimitError,
)

logger = logging.getLogger(__name__)


def _redact_token_data(data: dict) -> dict:
    """Return a copy of token data with sensitive values redacted."""
    redacted = dict(data)
    for key in ('access_token', 'refresh_token'):
        if key in redacted and redacted[key]:
            value = str(redacted[key])
            redacted[key] = value[:4] + '...' + value[-4:] if len(value) > 8 else '***'
    return redacted


class SharesightAPI:
    def __init__(self, client_id: str, client_secret: str, authorization_code: str,
                 redirect_uri: str, token_url: str, api_url_base: str, use_token_file: bool = True,
                 debugging: bool = False, token_file_name: Optional[str] = None,
                 session: aiohttp.ClientSession | None = None,
                 max_retries: int = 3, retry_backoff: float = 1.0) -> None:
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
        """
        self.__client_id = client_id
        self.__client_secret = client_secret
        self.__authorization_code = authorization_code
        self.__redirect_uri = redirect_uri
        self.__token_url = token_url
        self.__api_url_base = api_url_base
        self.__use_token_file = use_token_file
        self.__token_file = token_file_name or f"sharesight_token_{self.__client_id}.txt"
        self.__access_token: Optional[str] = None
        self.__refresh_token: Optional[str] = None
        self.__load_auth_code: Optional[str] = None
        self.__token_expiry: Optional[float] = None
        self.__debugging = debugging
        self.__max_retries = max_retries
        self.__retry_backoff = retry_backoff
        self.__tokens_loaded = False

        self.session = session or aiohttp.ClientSession()
        self._created_session = not session

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def get_token_data(self) -> None:
        """
        Loads token data (access token, refresh token, token expiry, and authorization code)
        from the token file if it exists.
        """
        if self.__debugging:
            logging.basicConfig(level=logging.DEBUG)
        self.__access_token, self.__refresh_token, self.__token_expiry, self.__load_auth_code = await self.load_tokens()
        self.__tokens_loaded = True

    async def validate_token(self) -> Union[str, int]:
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

        current_time = time.time()

        if self.__debugging:
            logger.info(f"CURRENT TIME: {current_time}")
            logger.info(f"TOKEN REFRESH TIME: {self.__token_expiry}\n")

        if self.__access_token is None:
            logger.info("NO TOKEN FILE/CONFIG  FOUND - GENERATING NEW")
            return await self.get_access_token()
        elif not self.__access_token:
            logger.info("TOKEN TOKEN FILE/CONFIG INVALID - GENERATING NEW")
            return await self.refresh_access_token()
        elif current_time >= self.__token_expiry:
            logger.info("ACCESS TOKEN EXPIRED - GENERATING NEW")
            return await self.refresh_access_token()
        else:
            logger.info("ACCESS TOKEN VALID - PASSING")
            return self.__access_token

    async def refresh_access_token(self) -> Union[str, int]:
        """
        Refreshes the access token using the refresh token.

        Returns:
        - The new access token if successful or the HTTP status code if the refresh fails.
        """
        if self.__use_token_file:
            await self.get_token_data()

        payload = {
            'grant_type': 'refresh_token',
            'refresh_token': self.__refresh_token,
            'client_id': self.__client_id,
            'client_secret': self.__client_secret
        }
        headers = {
            'Content-Type': 'application/json'
        }

        async with self.session.post(self.__token_url, data=json.dumps(payload), headers=headers) as response:
            if response.status == 200:
                token_data = await response.json()
                if self.__debugging:
                    logger.info(f"Refresh_access_token response: {_redact_token_data(token_data)}")
                self.__access_token = token_data['access_token']
                self.__refresh_token = token_data['refresh_token']
                self.__token_expiry = time.time() + token_data.get('expires_in', 1800)
                if self.__use_token_file:
                    await self.save_tokens()
                return self.__access_token
            else:
                logger.info(f"Failed to refresh access token: {response.status}")
                try:
                    logger.info(await response.json())
                except Exception:
                    logger.info(await response.text())
                return response.status

    async def get_access_token(self) -> Union[str, int]:
        """
        Obtains a new access token using the authorization code.

        Returns:
        - The new access token if successful or the HTTP status code if the request fails.
        """
        current_time = time.time()
        payload = {
            'grant_type': 'authorization_code',
            'code': self.__authorization_code,
            'redirect_uri': self.__redirect_uri,
            'client_id': self.__client_id,
            'client_secret': self.__client_secret
        }
        headers = {
            'Content-Type': 'application/json'
        }

        async with self.session.post(self.__token_url, data=json.dumps(payload), headers=headers) as response:
            if response.status == 200:
                token_data = await response.json()
                if self.__debugging:
                    logger.info(f"get_access_token response: {_redact_token_data(token_data)}")
                self.__access_token = token_data['access_token']
                self.__refresh_token = token_data['refresh_token']
                self.__token_expiry = current_time + token_data.get('expires_in', 1800)

                if self.__use_token_file:
                    await self.save_tokens()
                return self.__access_token
            elif response.status == 400:
                logger.info(f"Failed to obtain access token: {response.status}")
                logger.info(f"Did you fill out the correct information?")
                try:
                    logger.info(await response.json())
                except Exception:
                    logger.info(await response.text())
                return response.status
            else:
                logger.info(f"Failed to obtain access token: {response.status}")
                try:
                    logger.info(await response.json())
                except Exception:
                    logger.info(await response.text())
                return response.status

    async def _request(self, method: str, endpoint: list, payload: Optional[Dict[str, Any]] = None,
                       access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Internal method that handles all API requests with common logic for headers,
        URL construction, response parsing, error handling, and retry with exponential backoff.

        Parameters:
        - method: HTTP method (GET, POST, PUT, DELETE, PATCH).
        - endpoint: A list of [version, path, params].
        - payload: Optional; the data to send in the request body.
        - access_token: Optional; the access token to use for authentication.

        Returns:
        - The JSON response from the API as a dictionary.
        """
        if access_token is None:
            access_token = self.__access_token

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }

        url = f"{self.__api_url_base}{endpoint[0]}/{endpoint[1]}"
        params = endpoint[2] if len(endpoint) > 2 else None

        retryable_statuses = {429, 500, 502, 503}

        for attempt in range(self.__max_retries + 1):
            kwargs = {'headers': headers}
            if method.upper() == 'GET':
                kwargs['params'] = params
            elif payload is not None:
                kwargs['json'] = payload

            async with self.session.request(method, url, **kwargs) as response:
                # Try to parse JSON response
                try:
                    data = await response.json()
                except Exception:
                    data = {'error': await response.text(), 'status_code': response.status}

                if response.status == 200:
                    return data

                # Handle retryable errors
                if response.status in retryable_statuses and attempt < self.__max_retries:
                    if response.status == 429:
                        retry_after = response.headers.get('Retry-After')
                        if retry_after:
                            wait_time = float(retry_after)
                        else:
                            wait_time = self.__retry_backoff * (2 ** attempt)
                        logger.info(f"Rate limited (429). Retrying in {wait_time}s (attempt {attempt + 1}/{self.__max_retries})")
                    else:
                        wait_time = self.__retry_backoff * (2 ** attempt)
                        logger.info(f"Server error ({response.status}). Retrying in {wait_time}s (attempt {attempt + 1}/{self.__max_retries})")
                    await asyncio.sleep(wait_time)
                    continue

                # Non-retryable or exhausted retries
                logger.info(f"API {method.upper()} request failed: {response.status}")
                logger.info(data)
                return data

        # Should not reach here, but just in case
        return data

    async def get_api_request(self, endpoint: list,
                              access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Sends a GET request to the specified API endpoint.

        Parameters:
        - endpoint: The specific API endpoint to request as [version, path, params].
        - access_token: Optional; the access token to use for authentication. Defaults to the stored access token.

        Returns:
        - The JSON response from the API as a dictionary.
        """
        return await self._request('GET', endpoint, access_token=access_token)

    async def post_api_request(self, endpoint: list, payload: Dict[str, Any],
                               access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Sends a POST request to the specified API endpoint.

        Parameters:
        - endpoint: The specific API endpoint to request as [version, path, params].
        - payload: The data to send in the POST request body.
        - access_token: Optional; the access token to use for authentication. Defaults to the stored access token.

        Returns:
        - The JSON response from the API as a dictionary.
        """
        return await self._request('POST', endpoint, payload=payload, access_token=access_token)

    async def put_api_request(self, endpoint: list, payload: Dict[str, Any],
                              access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Sends a PUT request to the specified API endpoint.

        Parameters:
        - endpoint: The specific API endpoint to request as [version, path, params].
        - payload: The data to send in the PUT request body.
        - access_token: Optional; the access token to use for authentication. Defaults to the stored access token.

        Returns:
        - The JSON response from the API as a dictionary.
        """
        return await self._request('PUT', endpoint, payload=payload, access_token=access_token)

    async def delete_api_request(self, endpoint: list, payload: Optional[Dict[str, Any]] = None,
                                 access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Sends a DELETE request to the specified API endpoint.

        Parameters:
        - endpoint: The specific API endpoint to request as [version, path, params].
        - payload: Optional; the data to send in the DELETE request body.
        - access_token: Optional; the access token to use for authentication. Defaults to the stored access token.

        Returns:
        - The JSON response from the API as a dictionary.
        """
        return await self._request('DELETE', endpoint, payload=payload, access_token=access_token)

    async def patch_api_request(self, endpoint: list, payload: Dict[str, Any],
                                access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Sends a PATCH request to the specified API endpoint.

        Parameters:
        - endpoint: The specific API endpoint to request as [version, path, params].
        - payload: The data to send in the PATCH request body.
        - access_token: Optional; the access token to use for authentication. Defaults to the stored access token.

        Returns:
        - The JSON response from the API as a dictionary.
        """
        return await self._request('PATCH', endpoint, payload=payload, access_token=access_token)

    # --- Convenience methods ---

    async def list_portfolios(self) -> dict:
        """List all portfolios accessible by the authenticated user."""
        return await self._request('GET', ['v2', 'portfolios', None])

    async def get_portfolio(self, portfolio_id) -> dict:
        """Get details of a specific portfolio."""
        return await self._request('GET', ['v2', f'portfolios/{portfolio_id}', None])

    async def get_portfolio_performance(self, portfolio_id, start_date=None, end_date=None) -> dict:
        """Get performance data for a portfolio, optionally filtered by date range."""
        params = {}
        if start_date:
            params['start_date'] = str(start_date)
        if end_date:
            params['end_date'] = str(end_date)
        return await self._request('GET', ['v2', f'portfolios/{portfolio_id}/performance', params or None])

    async def list_holdings(self, portfolio_id) -> dict:
        """List all holdings in a portfolio."""
        return await self._request('GET', ['v2', f'portfolios/{portfolio_id}/holdings', None])

    async def get_holding(self, holding_id) -> dict:
        """Get details of a specific holding."""
        return await self._request('GET', ['v2', f'holdings/{holding_id}', None])

    async def list_trades(self, portfolio_id) -> dict:
        """List all trades in a portfolio."""
        return await self._request('GET', ['v2', f'portfolios/{portfolio_id}/trades', None])

    async def create_trade(self, portfolio_id, trade_data: dict) -> dict:
        """Create a new trade in a portfolio."""
        return await self._request('POST', ['v2', f'portfolios/{portfolio_id}/trades', None], payload=trade_data)

    async def list_cash_accounts(self) -> dict:
        """List all cash accounts."""
        return await self._request('GET', ['v2', 'cash_accounts', None])

    async def get_cash_account(self, cash_account_id) -> dict:
        """Get details of a specific cash account."""
        return await self._request('GET', ['v2', f'cash_accounts/{cash_account_id}', None])

    async def list_groups(self) -> dict:
        """List all groups."""
        return await self._request('GET', ['v2', 'groups', None])

    # --- Token management ---

    async def inject_token(self, token_data: Dict[str, Any]) -> None:
        """
        Manually injects token data (access token, refresh token, etc.) into the API client.

        Parameters:
        - token_data: A dictionary containing the token data to inject.
        """
        if token_data:
            self.__authorization_code = token_data.get('auth_code')
            self.__access_token = token_data.get('access_token')
            self.__token_expiry = token_data.get('token_expiry')
            self.__refresh_token = token_data.get('refresh_token')
            if self.__use_token_file:
                await self.save_tokens()

    async def load_tokens(self) -> Tuple[Optional[str], Optional[str], Optional[float], Optional[str]]:
        """
        Loads token data from the token file if it exists.

        Returns:
        - A tuple containing the access token, refresh token, token expiry, and authorization code.
        """
        if not os.path.isfile(self.__token_file):
            logger.info(f"{self.__token_file} doesn't exist.")
            return None, None, None, None

        async with aiofiles.open(self.__token_file, mode='r') as file:
            data = await file.read()

        if not data:
            return None, None, None, None

        try:
            tokens = json.loads(data)
            access_token = tokens.get('access_token')
            refresh_token = tokens.get('refresh_token')
            token_expiry = tokens.get('token_expiry')
            load_auth_code = tokens.get('auth_code')
            return access_token, refresh_token, token_expiry, load_auth_code
        except json.JSONDecodeError:
            return None, None, None, None

    async def save_tokens(self) -> None:
        """
        Saves the current token data (access token, refresh token, etc.) to the token file.
        """
        token_data = {
            'access_token': self.__access_token,
            'refresh_token': self.__refresh_token,
            'token_expiry': self.__token_expiry,
            'auth_code': self.__authorization_code
        }

        async with aiofiles.open(self.__token_file, mode='w') as file:
            await file.write(json.dumps(token_data))

    async def return_token(self) -> Dict[str, Union[str, float]]:
        """
        Returns the current token data as a dictionary.

        Returns:
        - A dictionary containing the access token, refresh token, token expiry, and authorization code.
        """
        return {
            'access_token': self.__access_token,
            'refresh_token': self.__refresh_token,
            'token_expiry': self.__token_expiry,
            'auth_code': self.__authorization_code
        }

    async def delete_token(self):
        await aiofiles.os.remove(self.__token_file)

    async def close(self) -> None:
        if self._created_session:
            logger.info("Connection to SharesightAPI being closed")
            await self.session.close()
