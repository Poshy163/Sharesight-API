import asyncio
import itertools
import json
from typing import Dict, Any

import aiofiles

from SharesightAPI import SharesightAPI


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
    useEdge = False
    endpoint_list_version = "v2"

    v2_endpoint_list = ["portfolios", "groups", f"portfolios/{portfolioID}/performance",
                        f"portfolios/{portfolioID}/valuation", "memberships",
                        f"portfolios/{portfolioID}/trades", f"portfolios/{portfolioID}/payouts", "cash_accounts",
                        "user_instruments", "currencies", "my_user.json"]
    v3_endpoint_list = ["portfolios"]
    token_file = "HA.txt"

    # Fixed
    redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
    token_url = 'https://api.sharesight.com/oauth2/token'
    api_url_base = 'https://api.sharesight.com/api/'
    edge_token_url = 'https://edge-api.sharesight.com/oauth2/token'
    edge_api_url_base = 'https://edge-api.sharesight.com/api/'

    if redirect_uri == "" or api_url_base == "" or token_url == "":
        print("EMPTY REQUIREMENT STRING, ABORTING")
        exit(1)

    if not useEdge:
        sharesight = SharesightAPI.SharesightAPI(client_id, client_secret, authorization_code, redirect_uri, token_url,
                                                 api_url_base, token_file, True)
    else:
        sharesight = SharesightAPI.SharesightAPI(client_id, client_secret, authorization_code, redirect_uri,
                                                 edge_token_url,
                                                 edge_api_url_base, token_file, True)
    while True:
        await sharesight.get_token_data()
        access_token = await sharesight.validate_token()

        combined_dict = {}

        if endpoint_list_version == "v2":
            for endpoint in v2_endpoint_list:
                print(f"\nCalling {endpoint}")
                response = await sharesight.get_api_request(endpoint, endpoint_list_version, access_token)
                combined_dict = await merge_dicts(combined_dict, response)
        elif endpoint_list_version == "v3":
            for endpoint in v3_endpoint_list:
                print(f"\nCalling {endpoint}")
                response = await sharesight.get_api_request(endpoint, endpoint_list_version, access_token)
                combined_dict = await merge_dicts(combined_dict, response)

        # Write the combined dictionary to an output.json file which is saved to the current directory
        async with aiofiles.open('output.json', 'w') as outfile:
            await outfile.write(json.dumps(combined_dict, indent=1))

        # Do something with the response json
        print(f"\nYour name is " + combined_dict.get("user", {}).get("name"))

        value = combined_dict.get("value")

        print(f"\nProfile Value is ${value} AUD")
        await asyncio.sleep(60)


asyncio.run(main())
