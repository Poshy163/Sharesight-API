# **Sharesight API** #

API to interface with Sharesight's v2 API

- Supports POST, PUT, PATCH, DELETE and GET requests
- Automatic retry with exponential backoff for transient errors (429, 500, 502, 503)
- Custom exception classes for structured error handling
- Async context manager support (`async with`)
- Convenience methods for common API operations

# **How to use** #
See the example.py file for an example

This whole thing is designed to be asynchronous

Added support for refresh token, no need to feed in clientID, clientSecret or authCode if token file exists

This API was designed to handle all the tokens requirements, but you are able to manage it yourself, removing the need to use get_token_data()
and validate_token(), by passing the access token into get_api_request().

# **How to install** #
Do ```pip install SharesightAPI```

# **How to test using example.py** #

To test the API, run the example.py file, with the variables in blank filled in, it will update specific post specific
data points to the console, and a json file with the output will be made

# **How to get API token** #

Read [here](https://portfolio.sharesight.com/api/) (you may need to get in contact with them over live chat)

# **Input/Output** #

To start, call and assign (like this)

```python
sharesight = SharesightAPI.SharesightAPI(client_id, client_secret, authorization_code, redirect_uri, token_url, api_url_base)
```

Or use the async context manager:

```python
async with SharesightAPI.SharesightAPI(client_id, client_secret, authorization_code, redirect_uri, token_url, api_url_base) as sharesight:
    access_token = await sharesight.validate_token()
    # ... use the API
```

Sharesight has some recommendations for defaults as seen [here](https://portfolio.sharesight.com/api/2/authentication_flow):

+ redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
+ token_url = 'https://api.sharesight.com/oauth2/token'
+ api_url_base = 'https://api.sharesight.com/api/v2/'

I have assumed some things (if left blank):

+ token_file = 'sharesight_token_<client_id>.txt'
+ debugging = False

Then; to get the existing data contained within the token file (optional), run this to get the values and store it within the constructor:

`await sharesight.get_token_data()`


To check the currently loaded token, run the .validate_token() call, if it will return if the token has passed, failed and why. and will store the token in a .txt file

This returns the current access_token, which can be passed in to use in API calls

`access_token = await sharesight.validate_token()`

# **Convenience Methods** #

Instead of constructing endpoint lists manually, you can use built-in convenience methods:

```python
# List all portfolios
portfolios = await sharesight.list_portfolios()

# Get a specific portfolio
portfolio = await sharesight.get_portfolio(portfolio_id)

# Get portfolio performance (with optional date range)
performance = await sharesight.get_portfolio_performance(portfolio_id, start_date="2024-01-01", end_date="2024-12-31")

# List holdings in a portfolio
holdings = await sharesight.list_holdings(portfolio_id)

# Get a specific holding
holding = await sharesight.get_holding(holding_id)

# List trades
trades = await sharesight.list_trades(portfolio_id)

# Create a trade
trade = await sharesight.create_trade(portfolio_id, trade_data)

# Cash accounts
cash_accounts = await sharesight.list_cash_accounts()
cash_account = await sharesight.get_cash_account(cash_account_id)

# Groups
groups = await sharesight.list_groups()
```

# **Raw API Requests** #

To make an API call (get): call .get_api_request(endpoint), making the endpoint being a list of the API version, the call URL, and the params if applicable. It will return a dictionary with the response.
You are able to parse through the access_token, otherwise it will default to the current access token in the constructor.

example: `await sharesight.get_api_request(["v2","portfolios", None])`

or

example: `await sharesight.get_api_request(["v2","portfolios", None], access_token)`

To make an API call (post): call .post_api_request, with the addition of parsing in a payload JSON to post

example: `await sharesight.post_api_request(["v2","portfolios"], "{ "portfolio": { "name": "My new Portfolio"}})`

you can see a full list of v2 endpoints [here](https://portfolio.sharesight.com/api/2/doc/index.html), and v3 endpoints [here](https://portfolio.sharesight.com/api/3/doc/index.html) (including examples)

Call `delete_token()` to remove the Token file from the instance (will cause a new auth_code to be needed)

To close the connection, call `close()` (or use the `async with` context manager for automatic cleanup)

# **Custom Exceptions** #

The library provides custom exception classes for structured error handling:

```python
from SharesightAPI import SharesightError, SharesightAuthError, SharesightAPIError, SharesightRateLimitError
```

- `SharesightError` - Base exception for all Sharesight API errors
- `SharesightAuthError` - Authentication failures
- `SharesightAPIError` - API request failures (has `status_code`, `message`, `response_data` attributes)
- `SharesightRateLimitError` - Rate limiting (429) with optional `retry_after` attribute

# **Retry Configuration** #

The client automatically retries on transient errors (429, 500, 502, 503) with exponential backoff:

```python
sharesight = SharesightAPI.SharesightAPI(
    client_id, client_secret, authorization_code, redirect_uri, token_url, api_url_base,
    max_retries=3,       # Maximum retry attempts (default: 3)
    retry_backoff=1.0    # Base backoff time in seconds (default: 1.0)
)
```

For 429 responses, the `Retry-After` header is respected when present.

# **Manual Token Handling** #

This is an alternative to saving the token in the current directory, this allows you to handle all the token functions.

To store your own token data elsewhere, call `return_token()` to gets the currently saved token information, which can be called after the token is validated (see example.py for more details)

(This removes the need for save_token and load_token methods, as you'll be handling it, but the token will still be refreshed)

Token data is returned like this:

`{ 'auth_code': 12345, 'access_token': 12345, 'token_expiry': 12345, 'refresh_token': 12345 }`

To then inject your token into the API, you need to call `inject_token(token_data)` where token_data is the token, in the same format as above
