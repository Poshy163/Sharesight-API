# **Sharesight API** #

API to interface with Sharesight's v2 API

- Currently only supports push requests
- Currently only supports as single portfolio request per instance called

# **How to use** #
See the pytest.py file for an example

This whole thing is designed to be asynchronous 

Added support for refresh token, no need to feed in clientID, clientSecret or authCode if token file exists

# **How to install** #
Do ```pip install SharesightAPI```

# **How to get API token** #

Read [here](https://portfolio.sharesight.com/api/) 

# **Input/Output** #

To start, call and assign (like this)

`sharesight = SharesightAPI.SharesightAPI(client_id, client_secret, authorization_code, redirect_uri, token_url, api_url_base, token_file, True)`

Sharesight has some recommendations for defaults as seen [here](https://portfolio.sharesight.com/api/2/authentication_flow):




+ redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
+ token_url = 'https://api.sharesight.com/oauth2/token'
+ api_url_base = 'https://api.sharesight.com/api/v2/'

I have assumed some things (if left blank):

+ token_file = 'sharesight_token.txt'
+ debugging = False

Setting token_file to be 'HA.txt' will append the client ID to sharesight_token. eg: sharesight_token_4123213214123.txt

Then; to get the existing data contained within the token file (optional), run this to get the values and store it within the constructor:

`await sharesight.get_token_data()`


To check the currently loaded token, run the .validate_token() call, if it will return if the token has passed, failed and why. and will store the token in a .txt file

This returns the current access_token, which can be passed in to use in API calls

`access_token = await sharesight.validate_token()`



To make an API call (get): call .get_api_request(endpoint, endpoint_list_version), making the endpoint being what part you want to call and the endpoint_list_version being ("v2" or "v3"). It will return a dictionary with the response. 
You are able to parse through the access_token, otherwise it will default to the current access token in the constructor

example: `await sharesight.get_api_request("portfolios", "v2")`

or

example: `await sharesight.get_api_request("portfolios", "v2", access_token)`

To make an API call (post): call .post_api_request, with the addition of parsing in a payload JSON to post

example: `await sharesight.post_api_request("portfolios", "v2", "{ "portfolio": { "name": "My new Portfolio"}}")`

you can see a full list of v2 endpoints [here](https://portfolio.sharesight.com/api/2/doc/index.html), and v3 endpoints [here](https://portfolio.sharesight.com/api/3/doc/index.html) (including examples)

