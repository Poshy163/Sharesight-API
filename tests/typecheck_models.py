"""Static fixtures that pin response-model wire types for mypy."""

from decimal import Decimal

from SharesightAPI.models import Adjustment, Currency, Holding

holding: Holding = {
    "cost_base": {
        "total_value": Decimal("100.00"),
        "value_per_share": 10.0,
    }
}

adjustment: Adjustment = {
    "amount_per_share": "10.50",
    "tax_credit": "1.05",
    "franked_percent": None,
    "drp_price": None,
}

currency_object: Currency = {
    "source_feeds": {
        "openexchangerates": None,
        "ecb": None,
    }
}
currency_legacy_string: Currency = {"source_feeds": "legacy-feed"}
