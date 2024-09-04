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
    token_file = "HA.txt"

    endpoint_list_full = [
        ["v3", "portfolios"],
        ["v2", "groups"],
        ["v3", f"portfolios/{portfolioID}/performance"],
        ["v3", f"portfolios/{portfolioID}/valuation"],
        ["v2", f"portfolios/{portfolioID}/trades"],
        ["v2", f"portfolios/{portfolioID}/payouts"],
        ["v2", "cash_accounts"],
        ["v2", "user_instruments"],
        ["v2", "currencies"],
        ["v2", "my_user.json"]
    ]

    endpoint_list = [
        ["v3", "portfolios"],
        ["v3", f"portfolios/{portfolioID}/performance"],
    ]

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
        await sharesight.get_token_data()
        access_token = await sharesight.validate_token()
        token_data = await sharesight.return_token()
        print("Passed token data is: ", token_data)
        await sharesight.inject_token(token_data)

        combined_dict = {}

        for endpoint in endpoint_list:
            print(f"\nCalling {endpoint[1]}")
            response = await sharesight.get_api_request(endpoint, access_token)
            combined_dict = await merge_dicts(combined_dict, response)

        # Write the combined dictionary to an output.json file which is saved to the current directory
        async with aiofiles.open('output.json', 'w') as outfile:
            await outfile.write(json.dumps(combined_dict, indent=1))

        # Do something with the response json in this case, the name from the V3 API call
        print(f"\nYour name is " + combined_dict.get('portfolios', [{}])[0].get('owner_name', "Cannot retrieve"))

        value = combined_dict.get('report', "Cannot retrieve").get('value', "Cannot retrieve")

        print(f"\nProfile Value is ${value} AUD")

    await sharesight.close()


asyncio.run(main())
