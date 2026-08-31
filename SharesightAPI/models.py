"""Typed response shapes for Sharesight's stable read-only API surfaces.

Sharesight's v3 API remains a closed beta and both API generations sometimes
omit fields for empty, sold, delisted, or plan-limited positions.  These
``TypedDict`` models are therefore deliberately partial: they improve editor
and type-checker support without rejecting a valid response merely because an
optional field is absent or null.

Dates and datetimes remain strings exactly as supplied by Sharesight.  Most
routes use ISO-8601, while a few legacy v2 responses use display-formatted
dates.  Keeping the wire value avoids silently assigning a timezone or losing
format information and lets host applications apply their own policy.
Monetary JSON numbers can be decoded as :class:`decimal.Decimal` by
constructing :class:`SharesightAPI` with ``preserve_decimal=True``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, TypeAlias, TypedDict

JsonNumber: TypeAlias = int | float | Decimal


class Portfolio(TypedDict, total=False):
    """Portfolio metadata returned by v3 portfolio endpoints."""

    id: int | str
    name: str
    currency_code: str
    country_code: str
    inception_date: str | None
    financial_year_end: str | None
    timezone: str | None
    tz_name: str | None
    user_id: int | str
    owner_name: str
    consolidated: bool
    interest_method: str


class PortfoliosResponse(TypedDict, total=False):
    """Envelope returned by ``GET v3/portfolios``."""

    portfolios: list[Portfolio]


class PortfolioResponse(TypedDict, total=False):
    """Envelope returned by ``GET v3/portfolios/{portfolio_id}``."""

    portfolio: Portfolio


class Instrument(TypedDict, total=False):
    """Instrument metadata embedded in holdings and reports."""

    id: int | str
    code: str
    symbol: str
    name: str
    market: str | dict[str, Any] | None
    currency_code: str
    instrument_type: str | dict[str, Any] | None
    last_traded_price: JsonNumber | None
    last_traded_on: str | None


class HoldingCostBase(TypedDict, total=False):
    """Cost-base object returned by the public V3 holding detail route."""

    total_value: JsonNumber | None
    value_per_share: JsonNumber | None


class Holding(TypedDict, total=False):
    """Holding row returned by v3 or a performance report."""

    id: int | str
    portfolio_id: int | str
    instrument_id: int | str
    symbol: str
    name: str
    market: str
    grouping: str | dict[str, Any] | None
    instrument: Instrument | dict[str, Any]
    quantity: JsonNumber | None
    value: JsonNumber | None
    cost_base: HoldingCostBase | None
    average_purchase_price: JsonNumber | None
    capital_gain: JsonNumber | None
    capital_gain_percent: JsonNumber | None
    currency_gain: JsonNumber | None
    currency_gain_percent: JsonNumber | None
    payout_gain: JsonNumber | None
    payout_gain_percent: JsonNumber | None
    total_gain: JsonNumber | None
    total_gain_percent: JsonNumber | None
    annualised_return_percent: JsonNumber | None
    inception_date: str | None
    labels: list[str] | list[dict[str, Any]]
    limited: bool
    valid_position: bool


class HoldingsResponse(TypedDict, total=False):
    """Envelope returned by portfolio holding endpoints."""

    holdings: list[Holding]


class HoldingResponse(TypedDict, total=False):
    """Envelope returned by ``GET v3/holdings/{holding_id}``."""

    holding: Holding


class PerformanceReport(TypedDict, total=False):
    """Core v2/v3 performance report fields."""

    id: int | str
    portfolio_id: int | str
    start_date: str
    end_date: str
    grouping: str
    custom_group_id: int | str | None
    include_sales: bool
    currency_code: str
    value: JsonNumber | None
    cost_base: JsonNumber | None
    capital_gain: JsonNumber | None
    capital_gain_percent: JsonNumber | None
    currency_gain: JsonNumber | None
    currency_gain_percent: JsonNumber | None
    payout_gain: JsonNumber | None
    payout_gain_percent: JsonNumber | None
    total_gain: JsonNumber | None
    total_gain_percent: JsonNumber | None
    annualised_return_percent: JsonNumber | None
    holdings: list[Holding]
    sub_totals: list[dict[str, Any]]
    cash_accounts: list[dict[str, Any]]


class PerformanceResponse(TypedDict, total=False):
    """Envelope used by the v3 performance endpoint."""

    report: PerformanceReport


class Trade(TypedDict, total=False):
    """Trade record returned by portfolio and holding endpoints."""

    id: int | str
    portfolio_id: int | str
    holding_id: int | str
    instrument_id: int | str
    unique_identifier: str | None
    symbol: str
    market: str
    transaction_date: str
    transaction_type: str
    quantity: JsonNumber | None
    price: JsonNumber | None
    exchange_rate: JsonNumber | None
    brokerage: JsonNumber | None
    price_currency_code: str
    brokerage_currency_code: str
    value: JsonNumber | None
    state: str
    confirmed: bool
    comments: str | None


class TradesResponse(TypedDict, total=False):
    """Envelope returned by trade list endpoints."""

    trades: list[Trade]


class Payout(TypedDict, total=False):
    """Dividend or distribution payout."""

    id: int | str
    portfolio_id: int | str
    holding_id: int | str
    instrument_id: int | str
    symbol: str
    market: str
    currency: str
    paid_on: str | None
    goes_ex_on: str | None
    amount: JsonNumber | None
    gross_amount: JsonNumber | None
    exchange_rate: JsonNumber | None
    state: str
    confirmed: bool


class PayoutsResponse(TypedDict, total=False):
    """Envelope returned by payout list endpoints."""

    payouts: list[Payout]


class CashAccount(TypedDict, total=False):
    """Cash account balance."""

    id: int | str
    portfolio_id: int | str
    name: str
    currency: str
    portfolio_currency: str
    date: str | None
    balance: JsonNumber | None
    balance_in_portfolio_currency: JsonNumber | None
    links: dict[str, Any]


class CashAccountsResponse(TypedDict, total=False):
    """Envelope returned by ``GET v2/cash_accounts.json``."""

    cash_accounts: list[CashAccount]


# The v2 show route returns a bare cash-account object rather than an envelope.
# Retain this public name as an alias for callers that imported the 1.5 models
# during development.
CashAccountResponse: TypeAlias = CashAccount


class CashAccountTransaction(TypedDict, total=False):
    """Cash account contribution, withdrawal, or linked transaction."""

    id: int | str
    cash_account_id: int | str
    holding_id: int | str | None
    trade_id: int | str | None
    payout_id: int | str | None
    date_time: str
    amount: JsonNumber | None
    balance: JsonNumber | None
    description: str | None
    foreign_identifier: str | None
    cash_account_transaction_type: str | dict[str, Any] | None
    links: dict[str, Any]


class CashAccountTransactionsResponse(TypedDict, total=False):
    """Envelope returned by a cash-account transaction list."""

    cash_account_transactions: list[CashAccountTransaction]


class Group(TypedDict, total=False):
    """Sharesight grouping definition."""

    id: int | str
    name: str
    custom: bool | str
    portfolio_ids: list[int | str]


class GroupsResponse(TypedDict, total=False):
    """Envelope returned by ``GET v2/groups.json``."""

    groups: list[Group]


class Currency(TypedDict, total=False):
    """Supported currency definition."""

    id: int | str
    code: str
    description: str
    in_use_from: str | None
    in_use_until: str | None
    source_feeds: str | dict[str, Any] | None
    # Some older payloads expose these presentation fields as well.
    name: str
    symbol: str


class CurrenciesResponse(TypedDict, total=False):
    """Envelope returned by ``GET v2/currencies.json``."""

    currencies: list[Currency]


class Country(TypedDict, total=False):
    """Country definition returned by the public v3 metadata route."""

    id: int | str
    code: str
    name: str
    currency_id: int | str
    currency_code: str
    financial_year_end: str
    financial_end_of_year: str
    supported: bool
    tz_name: str


class CountriesResponse(TypedDict, total=False):
    """Envelope returned by ``GET v3/countries``."""

    countries: list[Country]


class CustomInvestment(TypedDict, total=False):
    """Read-only metadata for a Sharesight custom investment."""

    id: int | str
    portfolio_id: int | str
    portfolio: dict[str, Any]
    code: str
    market_code: str
    name: str
    country_code: str
    country_id: int | str
    currency_code: str
    investment_type: str
    tz_name: str
    face_value: JsonNumber | None
    interest_rate: JsonNumber | None
    income_type: str | None
    payment_frequency: str | None
    first_payment_date: str | None
    maturity_date: str | None
    auto_calc_income: bool
    quantity: JsonNumber | None
    value: JsonNumber | None


class CustomInvestmentsResponse(TypedDict, total=False):
    """Envelope returned by ``GET v3/custom_investments``."""

    custom_investments: list[CustomInvestment]


# The documented example for the v3 show route is a bare object.  Keep the
# response name as a compatibility alias rather than claiming an envelope.
CustomInvestmentResponse: TypeAlias = CustomInvestment


class CursorPagination(TypedDict, total=False):
    """Opaque-cursor pagination returned by custom-investment child routes."""

    page: str | None
    per_page: int


class CustomInvestmentPrice(TypedDict, total=False):
    """One historical custom-investment price."""

    id: int | str
    lastTradedPrice: JsonNumber | None
    lastTradedOn: str | None
    lastTradedAt: str | None


class CustomInvestmentPricesResponse(TypedDict, total=False):
    """One page of custom-investment prices."""

    id: int | str
    prices: list[CustomInvestmentPrice]
    pagination: CursorPagination
    api_transaction: dict[str, Any]


class Adjustment(TypedDict, total=False):
    """A custom-investment quantity or value adjustment."""

    id: int | str
    amount_per_share: str | None
    announced_on: str | None
    goes_ex_on: str | None
    paid_on: str | None
    currency_code: str
    tax_credit: str | None
    drp_indicator: int | None
    franked_percent: str | None
    drp_price: str | None


class AdjustmentsResponse(TypedDict, total=False):
    """One page of custom-investment adjustments."""

    adjustments: list[Adjustment]
    pagination: CursorPagination
    api_transaction: dict[str, Any]


class AdjustmentResponse(Adjustment, total=False):
    """Adjustment detail, including Sharesight's duplicated envelope fields."""

    adjustment: Adjustment
    api_transaction: dict[str, Any]


class CouponRate(TypedDict, total=False):
    """A dated custom-investment coupon rate."""

    id: int | str
    date: str
    interest_rate: JsonNumber | None


class CouponRatesResponse(TypedDict, total=False):
    """One page of custom-investment coupon rates."""

    coupon_rates: list[CouponRate]
    pagination: CursorPagination
    api_transaction: dict[str, Any]


class ValuePoint(TypedDict, total=False):
    """One portfolio or holding value-series observation."""

    date: str
    value: JsonNumber | None


class ValueSeriesResponse(TypedDict, total=False):
    """A value series may be wrapped or returned as a bare list by Sharesight."""

    values: list[ValuePoint]
    portfolio_value_data: list[ValuePoint]
