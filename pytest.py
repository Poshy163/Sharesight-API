import json
from Sharesight.Sharesight import Sharesight
import sys

sys.dont_write_bytecode = True


def main():
    client_id = ''
    client_secret = ''
    authorization_code = ''
    redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
    token_url = 'https://api.sharesight.com/oauth2/token'
    api_url_base = 'https://api.sharesight.com/api/v2/'
    portfolioID = "1020131"
    endpoint_list = ["portfolios", "groups", f"portfolios/{portfolioID}/performance",
                     f"portfolios/{portfolioID}/valuation", "memberships",
                     f"portfolios/{portfolioID}/trades", f"portfolios/{portfolioID}/payouts", "cash_accounts",
                     "user_instruments", "currencies", "my_user.json"]

    if (
            client_id == "" or client_secret == "" or redirect_uri == "" or token_url == "" or api_url_base == ""):
        print("EMPTY REQUIREMENT STRING, ABORTING")
        return

    sharesight = Sharesight(client_id, client_secret, authorization_code, redirect_uri, token_url, api_url_base,
                            "token.txt")

    sharesight.check_token()
    combined_dict = {}
    for endpoint in endpoint_list:
        print(f"\nCalling {endpoint}")
        response = sharesight.make_api_request(endpoint)

        combined_dict = merge_dicts(combined_dict, response)

    # Write the combined dictionary to an output.json file
    with open('output.json', 'w') as outfile:
        json.dump(combined_dict, outfile, indent=1)

    print(f"\nYour name is " + combined_dict.get("user", {}).get("name"))


def merge_dicts(d1, d2):
    for key in d2:
        if key in d1 and isinstance(d1[key], dict) and isinstance(d2[key], dict):
            merge_dicts(d1[key], d2[key])
        else:
            d1[key] = d2[key]
    return d1


if __name__ == "__main__":
    main()
