# **Sharesight API** #

API to interface with Sharesight's v2 API

- Currently only supports push requests
- Currently only supports as single portfolio request per instance called

# **How to use** #
See the pytest.py file for an example

This whole thing is designed to be asynchronous 

# **How to install** #
Do ```pip install SharesightAPI```

# **How to get API token** #

Read [here](https://portfolio.sharesight.com/api/) 

# **Input/Output** #

To start, call and assign (like this)

`sharesight = SharesightAPI.SharesightAPI(client_id, client_secret, authorization_code, redirect_uri, token_url, api_url_base, token_file)`

Sharesight has some recommendations for defaults as seen [here](https://portfolio.sharesight.com/api/2/authentication_flow):

+ redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
+ token_url = 'https://api.sharesight.com/oauth2/token'
+ api_url_base = 'https://api.sharesight.com/api/v2/'

I have assumed some things (if left blank):

+ token_file = 'token.txt'

Then to check the token (and to import it), run the .check_token() call, if it will return if the token has passed, failed and why.

example:
`await sharesight.check_token()`

To make an API call, call .make_api_request(endpoint, endpoint_list_version), making the endpoint being what part you want to call and the endpoint_list_version being ("v2" or "v3"). It will return a dictionary with the response

example: `await sharesight.make_api_request(endpoint, endpoint_list_version)`

