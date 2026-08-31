import asyncio
import itertools
import json
from datetime import date
from typing import Any

import aiofiles

from SharesightAPI import SharesightAPI


async def merge_dicts(d1: dict[Any, Any], d2: dict[Any, Any]) -> dict[Any, Any]:
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
    client_id = ""
    client_secret = ""
    authorization_code = ""
    portfolio_id = ""
    use_edge = True
    use_token_file = False
    write_sensitive_output = False

    # Fixed
    redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
    token_url = "https://api.sharesight.com/oauth2/token"
    api_url_base = "https://api.sharesight.com/api/"
    edge_token_url = "https://edge-api.sharesight.com/oauth2/token"
    edge_api_url_base = "https://edge-api.sharesight.com/api/"

    if redirect_uri == "" or api_url_base == "" or token_url == "":
        print("EMPTY REQUIREMENT STRING, ABORTING")
        exit(1)

    selected_token_url = edge_token_url if use_edge else token_url
    selected_api_url = edge_api_url_base if use_edge else api_url_base

    # --- Example using context manager and convenience methods ---
    async with SharesightAPI(
        client_id,
        client_secret,
        authorization_code,
        redirect_uri,
        selected_token_url,
        selected_api_url,
        use_token_file,
        debugging=True,
    ) as sharesight:
        access_token = await sharesight.validate_token()
        print("OAuth token validated; credential values are intentionally not displayed.")

        # Convenience methods
        portfolios = await sharesight.list_portfolios_v3()
        print(f"\nAccessible portfolios: {len(portfolios.get('portfolios', []))}")

        if portfolio_id:
            performance = await sharesight.get_portfolio_performance_v3(
                portfolio_id, start_date=date.today(), end_date=date.today()
            )
            print(f"\nToday's portfolio value: {performance.get('report', {}).get('value')}")

            holdings = await sharesight.list_holdings(portfolio_id)
            print(f"Holdings returned: {len(holdings.get('holdings', []))}")

        # --- Alternative: endpoint list style (backward compatible) ---
        endpoint_list = [["v3", "portfolios", None]]
        if portfolio_id:
            endpoint_list.extend(
                [
                    [
                        "v2",
                        f"portfolios/{portfolio_id}/performance.json",
                        {
                            "start_date": f"{date.today()}",
                            "end_date": f"{date.today()}",
                        },
                    ],
                    ["v3", f"portfolios/{portfolio_id}/performance", None],
                ]
            )

        combined_dict: dict[str, Any] = {}

        for endpoint in endpoint_list:
            print(f"\nCalling {endpoint[0]}/{endpoint[1]}")
            response = await sharesight.get_api_request(endpoint, access_token)
            if endpoint[0] == "v2":
                response = {"one-day": response}

            if isinstance(response, dict):
                combined_dict = await merge_dicts(combined_dict, response)

        # API responses contain private portfolio information. Persist them
        # only when explicitly opted in, and never write OAuth token data.
        if write_sensitive_output:
            async with aiofiles.open("output.json", "w") as outfile:
                await outfile.write(json.dumps(combined_dict, indent=1))
            print("\nWrote private portfolio data to output.json")

        if portfolio_id:
            report = combined_dict.get("report")
            value = report.get("value") if isinstance(report, dict) else None
            if value is not None:
                print(f"\nPortfolio Value is ${value}")
            one_day = combined_dict.get("one-day")
            if isinstance(one_day, dict) and one_day.get("total_gain_percent") is not None:
                print(f"Gain today is {one_day['total_gain_percent']}%")


asyncio.run(main())
