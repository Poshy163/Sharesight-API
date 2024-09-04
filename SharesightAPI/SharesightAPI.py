import aiofiles
import aiofiles.os
import os
import aiohttp
import json
import time
import logging
from typing import Optional, Tuple, Any, Dict, Union

logger = logging.getLogger(__name__)


class SharesightAPI:
    def __init__(self, client_id: str, client_secret: str, authorization_code: str,
                 redirect_uri: str, token_url: str, api_url_base: str,
                 token_file: Optional[str] = None, debugging: bool = False,
                 session: aiohttp.ClientSession | None = None) -> None:
        """
        Initializes the API client with the necessary credentials and settings.

        Parameters:
        - client_id: The client ID for the API.
        - client_secret: The client secret for the API.
        - authorization_code: The authorization code for OAuth2.
        - redirect_uri: The redirect URI registered with the API.
        - token_url: The URL to obtain the OAuth2 token.
        - api_url_base: The base URL for the API endpoints.
        - token_file: Optional; the filename to store the token. Defaults to 'sharesight_token_<client_id>.txt' if not provided.
        - debugging: Optional; enables debugging mode if set to True. Defaults to False.
        """
        self.__client_id = client_id
        self.__client_secret = client_secret
        self.__authorization_code = authorization_code
        self.__redirect_uri = redirect_uri
        self.__token_url = token_url
        self.__api_url_base = api_url_base
        self.__token_file = token_file if token_file != "HA.txt" else f"sharesight_token_{self.__client_id}.txt"
        self.__access_token: Optional[str] = None
        self.__refresh_token: Optional[str] = None
        self.__load_auth_code: Optional[str] = None
        self.__token_expiry: Optional[float] = None
        self.__debugging = debugging

        self.session = session or aiohttp.ClientSession()
        self._created_session = not session

    async def get_token_data(self) -> None:
        """
        Loads token data (access token, refresh token, token expiry, and authorization code)
        from the token file if it exists.
        """
        if self.__debugging:
            logging.basicConfig(level=logging.DEBUG)
        self.__access_token, self.__refresh_token, self.__token_expiry, self.__load_auth_code = await self.load_tokens()

    async def validate_token(self) -> Union[str, int]:
        """
        Validates the current access token. If the token is missing, invalid, or expired,
        it will attempt to refresh or obtain a new access token.

        Returns:
        - The valid access token or the HTTP status code if the token refresh fails.
        """
        if self.__authorization_code is None or self.__authorization_code == "":
            self.__authorization_code = self.__load_auth_code

        current_time = time.time()

        if self.__debugging:
            logger.info(f"CURRENT TIME: {current_time}")
            logger.info(f"TOKEN REFRESH TIME: {self.__token_expiry}\n")

        if self.__access_token is None:
            logger.info("NO TOKEN FILE FOUND - GENERATING NEW")
            return await self.get_access_token()
        elif not self.__access_token:
            logger.info("TOKEN FILE INVALID - GENERATING NEW")
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
                    logger.info(f"Refresh_access_token response: {token_data}")
                self.__access_token = token_data['access_token']
                self.__refresh_token = token_data['refresh_token']
                self.__token_expiry = time.time() + token_data.get('expires_in', 1800)
                await self.save_tokens()
                return self.__access_token
            else:
                logger.info(f"Failed to refresh access token: {response.status}")
                logger.info(await response.json())
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
                    logger.info(f"get_access_token response: {token_data}")
                self.__access_token = token_data['access_token']
                self.__refresh_token = token_data['refresh_token']
                self.__token_expiry = current_time + token_data.get('expires_in', 1800)
                await self.save_tokens()
                return self.__access_token
            elif response.status == 400:
                logger.info(f"Failed to obtain access token: {response.status}")
                logger.info(f"Did you fill out the correct information?")
                logger.info(await response.json())
                return response.status
            else:
                logger.info(f"Failed to obtain access token: {response.status}")
                logger.info(await response.json())
                return response.status

    async def get_api_request(self, endpoint: list,
                              access_token: Optional[str] = None,
                              params: Optional[dict] = None) -> Dict[str, Any]:
        """
        Sends a GET request to the specified API endpoint.

        Parameters:
        - endpoint: The specific API endpoint to request.
        - endpoint_list_version: The API version or list to use.
        - access_token: Optional; the access token to use for authentication. Defaults to the stored access token.

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

        async with self.session.get(f"{self.__api_url_base}{endpoint[0]}/{endpoint[1]}",
                                    headers=headers, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return data
            else:
                logger.info(f"API GET request failed: {response.status}")
                data = await response.json()
                logger.info(data)
                return data

    async def post_api_request(self, endpoint: list, payload: Dict[str, Any],
                               access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Sends a POST request to the specified API endpoint.

        Parameters:
        - endpoint: The specific API endpoint to request.
        - endpoint_list_version: The API version or list to use.
        - payload: The data to send in the POST request body.
        - access_token: Optional; the access token to use for authentication. Defaults to the stored access token.

        Returns:
        - The JSON response from the API as a dictionary.
        """
        if access_token is None:
            access_token = self.__access_token
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        async with self.session.post(f"{self.__api_url_base}{endpoint[0]}/{endpoint[1]}", headers=headers,
                                     json=payload) as response:
            if response.status == 200:
                data = await response.json()
                return data
            elif response.status == 401:
                logger.info(f"API POST request failed: {response.status}")
                data = await response.json()
                logger.info(data)
                return data
            else:
                logger.info(f"API request failed: {response.status}")
                data = await response.json()
                logger.info(data)
                return data

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
