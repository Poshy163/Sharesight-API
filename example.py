import asyncio
import itertools
import json
from typing import Dict, Any
from datetime import date

import aiofiles

from SharesightAPI import SharesightAPI


class MockConfigEntry:
    def __init__(self, data=None):
        self.data = data or {}

    def async_update_entry(self, new_data):
        self.data.update(new_data)
        print("Updated config entry:", self.data)


async def merge_dicts(d1: Dict[Any, Any], d2: Dict[Any, Any]) -> Dict[Any, Any]:
    for key in itertools.chain(d1.keys(), d2.keys()):
        if key in d1 and key in d2:
            if isinstance(d1[key], dict) and isinstance(d2[key], dict):
                d1[key] = await merge_dicts(d1[key], d2[key])
            else:
                d1[key] = d2[key]
        elif key in d2:
            d1[key] = d2[key]
    return d1


async def main():
    # User Customisable
    client_id = ''
    client_secret = ''
    authorization_code = ''
    portfolioID = ''
    useEdge = True
    use_token_file = False

    # Fixed
    redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
    token_url = 'https://api.sharesight.com/oauth2/token'
    api_url_base = 'https://api.sharesight.com/api/'
    edge_token_url = 'https://edge-api.sharesight.com/oauth2/token'
    edge_api_url_base = 'https://edge-api.sharesight.com/api/'

    if redirect_uri == "" or api_url_base == "" or token_url == "":
        print("EMPTY REQUIREMENT STRING, ABORTING")
        exit(1)

    selected_token_url = edge_token_url if useEdge else token_url
    selected_api_url = edge_api_url_base if useEdge else api_url_base

    # --- Example using context manager and convenience methods ---
    async with SharesightAPI.SharesightAPI(
        client_id, client_secret, authorization_code, redirect_uri,
        selected_token_url, selected_api_url, use_token_file, debugging=True
    ) as sharesight:

        access_token = await sharesight.validate_token()
        token_data = await sharesight.return_token()
        print("Token data:", token_data)

        # Convenience methods
        portfolios = await sharesight.list_portfolios()
        print("\nPortfolios:", portfolios)

        if portfolioID:
            performance = await sharesight.get_portfolio_performance(
                portfolioID, start_date=date.today(), end_date=date.today()
            )
            print(f"\nPerformance: {performance}")

            holdings = await sharesight.list_holdings(portfolioID)
            print(f"\nHoldings: {holdings}")

        # --- Alternative: endpoint list style (backward compatible) ---
        endpoint_list = [
            ["v2", f"portfolios/{portfolioID}/performance",
             {'start_date': f"{date.today()}", 'end_date': f"{date.today()}"}],
            ["v3", "portfolios", None],
            ["v3", f"portfolios/{portfolioID}/performance", None],
        ]

        combined_dict = {}

        for endpoint in endpoint_list:
            print(f"\nCalling {endpoint[1]}")
            response = await sharesight.get_api_request(endpoint, access_token)
            if endpoint[0] == "v2":
                response = {
                    'one-day': response
                }

            print(f"{response}")
            combined_dict = await merge_dicts(combined_dict, response)

        # Write the combined dictionary to an output.json file
        async with aiofiles.open('output.json', 'w') as outfile:
            await outfile.write(json.dumps(combined_dict, indent=1))

        print(f"\nYour name is " + combined_dict.get('portfolios', [{}])[0].get('owner_name', "Cannot retrieve"))

        value = combined_dict.get('report', "Cannot retrieve report").get('value', "Cannot retrieve value")

        if value == "Cannot retrieve report" or value == "Cannot retrieve value":
            print(value)
        else:
            print(f"\nPortfolio Value is ${value}")
            total_gain = combined_dict['one-day']['total_gain_percent']
            print(f"\nGain today is {total_gain}%")


asyncio.run(main())
