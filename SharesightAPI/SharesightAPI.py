import os
import aiohttp
import json


class SharesightAPI:
    def __init__(self, client_id, client_secret, authorization_code, redirect_uri, token_url, api_url_base,
                 token_file='token.txt'):
        self.client_id = client_id
        self.client_secret = client_secret
        self.authorization_code = authorization_code
        self.redirect_uri = redirect_uri
        self.token_url = token_url
        self.api_url_base = api_url_base
        self.token_file = token_file
        self.access_token, self.refresh_token, self.load_auth_code = self.load_tokens()

    async def check_token(self):

        if not self.access_token:
            print("TOKEN INVALID - GENERATING NEW (ACCESS TOKEN WRONG)")
            await self.get_access_token()
        elif self.authorization_code != self.load_auth_code:
            print("TOKEN INVALID - GENERATING NEW (DIFFERENT AUTH CODE)")
            await self.get_access_token()
        else:
            print("TOKEN VALID - PASSING")

    async def get_access_token(self):
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
                    self.access_token = token_data['access_token']
                    self.refresh_token = token_data['refresh_token']
                    self.save_tokens()
                    return self.access_token
                else:
                    print(f"Failed to obtain access token: {response.status}")
                    print(await response.json())
                    exit(1)

    async def make_api_request(self, endpoint, endpoint_list_version):
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json'
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.api_url_base}{endpoint_list_version}/{endpoint}", headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    print(f"API request failed: {response.status}")
                    data = await response.json()
                    print(data)
                    return data

    def load_tokens(self):
        if os.path.exists(self.token_file):
            with open(self.token_file, 'r') as file:
                tokens = json.load(file)
                return tokens['access_token'], tokens['refresh_token'], tokens['auth_code']
        return None, None, None

    def save_tokens(self):
        tokens = {
            'auth_code': self.authorization_code,
            'access_token': self.access_token,
            'refresh_token': self.refresh_token
        }
        with open(self.token_file, 'w') as file:
            json.dump(tokens, file)
