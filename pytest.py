from Sharesight.Sharesight import Sharesight
import sys
sys.dont_write_bytecode = True


def main():
    client_id = ''
    client_secret = ''
    authorization_code = ''
    redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
    token_url = 'https://api.sharesight.com/oauth2/token'
    api_url = 'https://api.sharesight.com/api/v2/portfolios'

    sharesight = Sharesight(client_id, client_secret, authorization_code, redirect_uri, token_url, api_url)
    sharesight.make_api_request()

if __name__ == "__main__":
    main()