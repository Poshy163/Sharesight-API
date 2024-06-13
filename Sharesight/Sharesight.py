import requests
import json
import os


class Sharesight:
    def __init__(self, client_id, client_secret, authorization_code, redirect_uri, token_url, api_url_base,
                 token_file='token.txt'):
        self.client_id = client_id
        self.client_secret = client_secret
        self.authorization_code = authorization_code
        self.redirect_uri = redirect_uri
        self.token_url = token_url
        self.api_url_base = api_url_base
        self.token_file = token_file
        self.access_token, self.refresh_token = self.load_tokens()
    def fixjson(badjson):
        s = badjson
        idx = 0
        while True:
            try:
                start = s.index('": "', idx) + 4
                end1 = s.index('",\n', idx)
                end2 = s.index('"\n', idx)
                if end1 < end2:
                    end = end1
                else:
                    end = end2
                content = s[start:end]
                content = content.replace('"', '\\"')
                s = s[:start] + content + s[end:]
                idx = start + len(content) + 6
            except:
                return s
    def check_token(self):
        if not self.access_token:
            print("TOKEN INVALID - GENERATING NEW")
            self.get_access_token()
        else:
            print("TOKEN VALID")
    def get_access_token(self):
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
        response = requests.post(self.token_url, data=json.dumps(payload), headers=headers)
        if response.status_code == 200:
            token_data = response.json()
            self.access_token = token_data['access_token']
            self.refresh_token = token_data['refresh_token']
            self.save_tokens()
            return self.access_token
        else:
            print(f"Failed to obtain access token: {response.status_code}")
            print(response.json())
            return None
    def make_api_request(self, endpoint):
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json'
        }
        response = requests.get(f"{self.api_url_base}{endpoint}", headers=headers)
        if response.status_code == 200:
            data = response.json()
            return data
        else:
            print(f"API request failed: {response.status_code}")
            date = response.json()
            print(date)
            return self.fixjson()
    def load_tokens(self):
        if os.path.exists(self.token_file):
            with open(self.token_file, 'r') as file:
                tokens = json.load(file)
                return tokens['access_token'], tokens['refresh_token']
        return None, None
    def save_tokens(self):
        tokens = {
            'access_token': self.access_token,
            'refresh_token': self.refresh_token
        }
        with open(self.token_file, 'w') as file:
            json.dump(tokens, file)