import aiofiles
import aiofiles.os
import os
import aiohttp
import json
import time
import logging

logger = logging.getLogger(__name__)


class SharesightAPI:
    def __init__(self, client_id, client_secret, authorization_code, redirect_uri, token_url, api_url_base,
                 token_file, debugging=False):
        self.__client_id = client_id
        self.__client_secret = client_secret
        self.__authorization_code = authorization_code
        self.__redirect_uri = redirect_uri
        self.__token_url = token_url
        self.__api_url_base = api_url_base
        if token_file == "HA.txt":
            self.__token_file = f"sharesight_token_{self.__client_id}.txt"
        else:
            self.__token_file = token_file
        self.__access_token = None
        self.__refresh_token = None
        self.__load_auth_code = None
        self.__token_expiry = None
        self.__debugging = debugging

    async def get_token_data(self):
        if self.__debugging:
            logging.basicConfig(level=logging.DEBUG)
        self.__access_token, self.__refresh_token, self.__token_expiry, self.__load_auth_code = await self.load_tokens()

    async def validate_token(self):

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

    async def refresh_access_token(self):
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
        async with aiohttp.ClientSession() as session:
            async with session.post(self.__token_url, data=json.dumps(payload), headers=headers) as response:
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

    async def get_access_token(self):
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

        async with aiohttp.ClientSession() as session:
            async with session.post(self.__token_url, data=json.dumps(payload), headers=headers) as response:
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

    async def get_api_request(self, endpoint, endpoint_list_version, access_token=None):

        if access_token is None:
            access_token = self.__access_token

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.__api_url_base}{endpoint_list_version}/{endpoint}",
                                   headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.info(f"API GET request failed: {response.status}")
                    data = await response.json()
                    logger.info(data)
                    return data

    async def post_api_request(self, endpoint, endpoint_list_version, payload, access_token=None):
        if access_token is None:
            access_token = self.__access_token
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.__api_url_base}{endpoint_list_version}/{endpoint}", headers=headers,
                                    json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                elif response.status == 401:
                    logger.info(f"API POST request failed: {response.status}")
                    data = await response.json()
                    logger.info(data)
                    return response.status
                else:
                    logger.info(f"API request failed: {response.status}")
                    data = await response.json()
                    logger.info(data)
                    return data

    async def inject_token(self, token_data):
        if token_data:
            self.__authorization_code = token_data.get('auth_code')
            self.__access_token = token_data.get('access_token')
            self.__token_expiry = token_data.get('token_expiry')
            self.__refresh_token = token_data.get('refresh_token')
            logger.info("Token Data Injected")

    async def load_tokens(self):
        if os.path.exists(self.__token_file):
            async with aiofiles.open(self.__token_file, 'r') as file:
                content = await file.read()
                tokens = json.loads(content)
                return tokens['access_token'], tokens['refresh_token'], tokens['token_expiry'], tokens['auth_code']
        return None, None, None, None

    async def save_tokens(self):
        tokens = {
            'auth_code': self.__authorization_code,
            'access_token': self.__access_token,
            'token_expiry': self.__token_expiry,
            'refresh_token': self.__refresh_token
        }
        async with aiofiles.open(self.__token_file, 'w') as file:
            await file.write(json.dumps(tokens))

    async def return_token(self):
        tokens = {
            'auth_code': self.__authorization_code,
            'access_token': self.__access_token,
            'token_expiry': self.__token_expiry,
            'refresh_token': self.__refresh_token
        }
        return tokens

    async def delete_token(self):
        await aiofiles.os.remove(self.__token_file)
