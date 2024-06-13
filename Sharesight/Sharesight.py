import requests
import json
import os
import sys
sys.dont_write_bytecode = True

class Sharesight:
    def __init__(self, client_id, client_secret, authorization_code, redirect_uri, token_url, api_url, token_file='token.txt'):
        self.client_id = client_id
        self.client_secret = client_secret
        self.authorization_code = authorization_code
        self.redirect_uri = redirect_uri
        self.token_url = token_url
        self.api_url = api_url
        self.token_file = token_file
        self.access_token, self.refresh_token = self.load_tokens()

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

    def make_api_request(self):
        if not self.access_token:
            self.get_access_token()
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json'
        }
        response = requests.get(self.api_url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            print(data)
        else:
            print(f"API request failed: {response.status_code}")
            print(response.json())

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
