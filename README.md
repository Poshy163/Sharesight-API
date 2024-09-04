# **Sharesight API** #

API to interface with Sharesight's v2 API

- Currently only supports push requests
- Currently only supports as single portfolio request per instance called

# **How to use** #
See the pytest.py file for an example

This whole thing is designed to be asynchronous 

Added support for refresh token, no need to feed in clientID, clientSecret or authCode if token file exists

This API was designed to handle all the tokens requirements, but you are able to manage it yourself, removing the need to use get_token_data() 
and validate_token(), by passing the access token into get_api_request().

# **How to install** #
Do ```pip install SharesightAPI```

# **How to test using pytest.py** #

To test the API, run the pytest.py file, with the variables in blank filled in, it will loop and gather data every 60s until stopped

# **How to get API token** #

Read [here](https://portfolio.sharesight.com/api/) (you may need to get in contact with them over live chat)

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
+ useEdge = False (Edge is the developer testing profile/account, it has a different root URL)

Setting token_file to be 'HA.txt' will append the client ID to sharesight_token. eg: sharesight_token_4123213214123.txt

Then; to get the existing data contained within the token file (optional), run this to get the values and store it within the constructor:

`await sharesight.get_token_data()`


To check the currently loaded token, run the .validate_token() call, if it will return if the token has passed, failed and why. and will store the token in a .txt file

This returns the current access_token, which can be passed in to use in API calls

`access_token = await sharesight.validate_token()`



To make an API call (get): call .get_api_request(endpoint, endpoint_list_version), making the endpoint being a list of both the API version, and the call. It will return a dictionary with the response. 
You are able to parse through the access_token, otherwise it will default to the current access token in the constructor

example: `await sharesight.get_api_request(["v2","portfolios"])`

or

example: `await sharesight.get_api_request(["v2","portfolios"], access_token)`

To make an API call (post): call .post_api_request, with the addition of parsing in a payload JSON to post

example: `await sharesight.post_api_request(["v2","portfolios"], "{ "portfolio": { "name": "My new Portfolio"}})`

you can see a full list of v2 endpoints [here](https://portfolio.sharesight.com/api/2/doc/index.html), and v3 endpoints [here](https://portfolio.sharesight.com/api/3/doc/index.html) (including examples)

Call `delete_token()` to remove the Token file from the instance (will cause a new auth_code to be needed)

To close the connection, call `close()`

# **Manual Token Handling** #

This is an alternative to saving the token in the current directory, this allows you to handle all the token functions.

To store your own token data elsewhere, call `return_token()` to gets the currently saved token information, which can be called after the token is validated (see pytest for more details)

(This removes the need for save_token and load_token methods, as you'll be handling it, but the token will still be refreshed)

Token data is returned like this: 

`{ 'auth_code': 12345, 'access_token': 12345, 'token_expiry': 12345, 'refresh_token': 12345 }`

To then inject your token into the API, you need to call `inject_token(token_data)` where token_data is the token, in the same format as above

