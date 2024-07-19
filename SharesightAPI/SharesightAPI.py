import aiofiles
import os
import aiohttp
import json
import time
import logging

logger = logging.getLogger(__name__)


class SharesightAPI:
    def __init__(self, client_id, client_secret, authorization_code, redirect_uri, token_url, api_url_base,
                 token_file="sharesight_token.txt", debugging=False):
        self.client_id = client_id
        self.client_secret = client_secret
        self.authorization_code = authorization_code
        self.redirect_uri = redirect_uri
        self.token_url = token_url
        self.api_url_base = api_url_base
        if token_file == "sharesight_token.txt":
            self.token_file = "sharesight_token.txt"
        elif token_file == "HA.txt":
            self.token_file = f"sharesight_token_{self.client_id}.txt"
        else:
            self.token_file = token_file
        self.token_expiry = 1800
        self.access_token = None
        self.refresh_token = None
        self.load_auth_code = None
        self.token_expiry = None
        self.debugging = debugging

    async def get_token_data(self):
        if self.debugging:
            logging.basicConfig(level=logging.DEBUG)
        self.access_token, self.refresh_token, self.token_expiry, self.load_auth_code = await self.load_tokens()

    async def validate_token(self):

        if self.authorization_code is None or self.authorization_code == "":
            self.authorization_code = self.load_auth_code

        current_time = time.time()

        if self.debugging:
            logger.info(f"CURRENT TIME: {current_time}")
            logger.info(f"REFRESH TOKEN TIME: {self.token_expiry}\n")

        if self.access_token is None:
            logger.info("NO TOKEN FILE - GENERATING NEW")
            return await self.get_access_token()
        elif not self.access_token or current_time >= self.token_expiry:
            logger.info("TOKEN INVALID OR EXPIRED - GENERATING NEW")
            return await self.refresh_access_token()
        else:
            logger.info("TOKEN VALID - PASSING")
            return self.access_token

    async def refresh_access_token(self):
        await self.get_token_data()
        payload = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }
        headers = {
            'Content-Type': 'application/json'
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(self.token_url, data=json.dumps(payload), headers=headers) as response:
                if response.status == 200:
                    token_data = await response.json()
                    if self.debugging:
                        logger.info(f"Refresh_access_token response: {token_data}")
                    self.access_token = token_data['access_token']
                    self.refresh_token = token_data['refresh_token']
                    self.token_expiry = time.time() + token_data.get('expires_in', 1800)
                    await self.save_tokens()
                    return self.access_token
                else:
                    logger.info(f"Failed to refresh access token: {response.status}")
                    logger.info(await response.json())
                    return None

    async def get_access_token(self):
        current_time = time.time()
        payload = {
            'grant_type': 'authorization_code',
            'code': self.authorization_code,
            'redirect_uri': self.redirect_uri,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }
        headers = {
            'Content-Type': 'application/json'
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(self.token_url, data=json.dumps(payload), headers=headers) as response:
                if response.status == 200:
                    token_data = await response.json()
                    if self.debugging:
                        logger.info(f"get_access_token response: {token_data}")
                    self.access_token = token_data['access_token']
                    self.refresh_token = token_data['refresh_token']
                    self.token_expiry = current_time + token_data.get('expires_in', 1800)
                    await self.save_tokens()
                    return self.access_token
                elif response.status == 400:
                    logger.info(f"Failed to obtain access token: {response.status}")
                    logger.info(f"Are you sure you filled out correct constructor information?")
                    logger.info(await response.json())
                    return None
                else:
                    logger.info(f"Failed to obtain access token: {response.status}")
                    logger.info(await response.json())
                    return None

    async def get_api_request(self, endpoint, endpoint_list_version, access_token=None):

        if access_token is None:
            access_token = self.access_token

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.api_url_base}{endpoint_list_version}/{endpoint}",
                                   headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                elif response.status == 401:
                    logger.info(f"API request failed: {response.status}")
                    data = await response.json()
                    logger.info(data)
                    return None
                else:
                    logger.info(f"API request failed: {response.status}")
                    data = await response.json()
                    logger.info(data)
                    return data

    async def post_api_request(self, endpoint, endpoint_list_version, payload, access_token=None):
        if access_token is None:
            access_token = self.access_token
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.api_url_base}{endpoint_list_version}/{endpoint}", headers=headers,
                                    json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.info(f"API request failed: {response.status}")
                    data = await response.json()
                    logger.info(data)
                    return data

    async def load_tokens(self):
        if os.path.exists(self.token_file):
            async with aiofiles.open(self.token_file, 'r') as file:
                content = await file.read()
                tokens = json.loads(content)
                return tokens['access_token'], tokens['refresh_token'], tokens['token_expiry'], tokens['auth_code']
        return None, None, None, None

    async def save_tokens(self):
        tokens = {
            'auth_code': self.authorization_code,
            'access_token': self.access_token,
            'token_expiry': self.token_expiry,
            'refresh_token': self.refresh_token
        }
        async with aiofiles.open(self.token_file, 'w') as file:
            await file.write(json.dumps(tokens))
