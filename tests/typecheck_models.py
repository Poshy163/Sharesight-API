"""Static fixtures that pin response-model wire types for mypy."""

from decimal import Decimal

from SharesightAPI.models import (
    Adjustment,
    Benchmark,
    Currency,
    Holding,
    Label,
    Payout,
    PerformanceReport,
    SubTotal,
    WatchlistItem,
)

growth_label: Label = {"id": 9, "name": "Growth", "color": "#ff0000"}

holding: Holding = {
    "cost_base": {
        "total_value": Decimal("100.00"),
        "value_per_share": 10.0,
    },
    "instrument_currency": {"id": 1, "code": "USD", "symbol": "$", "qualified_symbol": "US$"},
    "instrument_price": 12.5,
    "group_id": 3,
    "group_name": "NASDAQ",
    "labels": [growth_label],
    "number_of_unconfirmed_transactions": 0,
}

report: PerformanceReport = {
    "portfolio_tz_name": "Australia/Sydney",
    "percentages_annualised": True,
    "currency": {"code": "AUD", "symbol": "$"},
    "sub_totals": [{"group_id": 1, "group_name": "ASX", "value": 10.0, "total_gain": 1.0}],
    "cash_accounts": [{"id": 5, "name": "Cash", "value": 3.0, "currency": {"code": "AUD"}}],
}

sub_total: SubTotal = {"group_name": "NYSE", "capital_gain_percent": Decimal("1.25")}

benchmark: Benchmark = {
    "capital_gain_percent": 12.5,
    "maximum_drawdown": 8.4,
    "return_over_drawdown": 1.5,
    "instrument": {"code": "A200", "market_code": "ASX"},
}

payout: Payout = {
    "id": None,
    "currency": "AUD",
    "franking_credits": 1.5,
    "drp_trade_attributes": {"dividend_reinvested": False, "quantity": None, "price": "0.0"},
}

watch_item: WatchlistItem = {
    "instrument": {"code": "AAPL", "market_code": "NASDAQ"},
    "price": {"value": 1.0, "diff_percent": -0.5, "currency": {"code": "USD"}},
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
