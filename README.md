# **Sharesight API** #

API to interface with Sharesight's v2 API

*currently only supports push requests

# **How to use** #
see the pytest.py file for an example

this whole thing is designed to be asynchronous 

# **How to install** #
do ```pip install SharesightAPI```

# **How to get API token** #

Read [here](https://portfolio.sharesight.com/api/) 

# **Input/Output** #

to start, call and assign (like this)

`sharesight = SharesightAPI.SharesightAPI(client_id, client_secret, authorization_code, redirect_uri, token_url, api_url_base, token_file)`

Sharesight has some recommendations for defaults as seen [here](https://portfolio.sharesight.com/api/2/authentication_flow):

+ redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
+ token_url = 'https://api.sharesight.com/oauth2/token'
+ api_url_base = 'https://api.sharesight.com/api/v2/'

I have assumed some things (if left blank):

+ token_file = 'token.txt'

then to check the token (and to import it), run the .check_token() call, if it will return if the token has passed, failed and why.

example:
`await sharesight.check_token()`

to make an API call, call .make_api_request(endpoint), making the endpoint being what part you want to call. it will return a dictionary with the response 

example: `await sharesight.make_api_request("portfolios")`

