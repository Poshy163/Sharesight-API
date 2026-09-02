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

Field lists were reconciled against live production payloads on 2026-09-02.
Where the live API differs from the published apiDoc the live spelling is the
one modelled (for example ``benchmark.capital_gain_percent`` rather than the
documented ``capital_gain_percentage``, and the undocumented
``benchmark.maximum_drawdown`` / ``return_over_drawdown`` pair).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, TypeAlias, TypedDict

JsonNumber: TypeAlias = int | float | Decimal


class ApiTransaction(TypedDict, total=False):
    """Request audit block that v3 responses append to every envelope."""

    id: int | str
    version: int
    action: str
    timestamp: str


class Currency(TypedDict, total=False):
    """Supported currency definition, or the compact block embedded in reports.

    ``GET v2/currencies.json`` returns the full definition; performance reports,
    holdings and watchlist prices embed the compact ``{id, code, symbol,
    qualified_symbol}`` form.  Both are modelled here because Sharesight uses
    the same ``currency`` key for each.
    """

    id: int | str
    code: str
    description: str
    in_use_from: str | None
    in_use_until: str | None
    source_feeds: str | dict[str, Any] | None
    # Presentation fields carried by the embedded report form.
    name: str
    symbol: str
    qualified_symbol: str


class CurrenciesResponse(TypedDict, total=False):
    """Envelope returned by ``GET v2/currencies.json``."""

    currencies: list[Currency]


class PortfolioReference(TypedDict, total=False):
    """Compact portfolio block embedded in holdings and cash accounts."""

    id: int | str
    consolidated: bool
    name: str
    external_identifier: str | None


class Portfolio(TypedDict, total=False):
    """Portfolio metadata returned by the v2 and v3 portfolio endpoints."""

    id: int | str
    name: str
    consolidated: bool
    external_identifier: str | None
    holding_id: int | str | None
    currency_code: str
    country_code: str
    inception_date: str | None
    financial_year_end: str | None
    timezone: str | None
    tz_name: str | None
    user_id: int | str
    owner_name: str
    access_level: str
    interest_method: str
    default_sale_allocation_method: str
    cg_discount: str | None
    rwtr_rate: JsonNumber | None
    trader: bool
    disable_automatic_transactions: bool
    tax_entity_type: str | None
    has_investments: bool
    trade_sync_cash_account_id: int | str | None
    payout_sync_cash_account_id: int | str | None


class PortfoliosResponse(TypedDict, total=False):
    """Envelope returned by ``GET v3/portfolios`` and ``GET v2/portfolios.json``."""

    portfolios: list[Portfolio]
    api_transaction: ApiTransaction
    links: dict[str, Any]


class PortfolioResponse(TypedDict, total=False):
    """Envelope returned by ``GET v3/portfolios/{portfolio_id}``."""

    portfolio: Portfolio
    api_transaction: ApiTransaction
    links: dict[str, Any]


class InstrumentLogo(TypedDict, total=False):
    """Light/dark logo pair embedded on every v3 instrument block."""

    light_url: str | None
    dark_url: str | None


class Instrument(TypedDict, total=False):
    """Instrument metadata embedded in holdings, benchmarks and watchlists."""

    id: int | str
    code: str
    symbol: str
    name: str
    market: str | dict[str, Any] | None
    market_code: str
    country_id: int | str | None
    crypto: bool
    currency_code: str
    instrument_type: str | dict[str, Any] | None
    expires_on: str | None
    expired: bool
    supported_denominations: Any
    tz_name: str | None
    industry_classification_name: str | None
    sector_classification_name: str | None
    friendly_instrument_description: str | None
    friendly_instrument_description_code: str | None
    registry_name: str | None
    logo: InstrumentLogo | None
    last_traded_price: JsonNumber | None
    last_traded_on: str | None


class Label(TypedDict, total=False):
    """Label attached to a holding inside a v3 performance report."""

    id: int | str
    name: str
    color: str | None
    holding_ids: list[int | str]
    portfolio_ids: list[int | str]


class HoldingCostBase(TypedDict, total=False):
    """Cost-base object returned by the public V3 holding detail route."""

    total_value: JsonNumber | None
    value_per_share: JsonNumber | None
    currency: Currency | str | None


class GainFields(TypedDict, total=False):
    """The gain family shared by reports, holdings and market sub-totals."""

    capital_gain: JsonNumber | None
    capital_gain_percent: JsonNumber | None
    currency_gain: JsonNumber | None
    currency_gain_percent: JsonNumber | None
    payout_gain: JsonNumber | None
    payout_gain_percent: JsonNumber | None
    total_gain: JsonNumber | None
    total_gain_percent: JsonNumber | None


class Holding(GainFields, total=False):
    """Holding row returned by v3 or a performance report.

    The report row carries no ``cost_base``; derive it as ``value -
    capital_gain`` when needed, or request ``GET v3/holdings/{id}`` with
    ``cost_base=true`` for the official figure.
    """

    id: int | str
    portfolio_id: int | str
    portfolio: PortfolioReference
    instrument_id: int | str
    symbol: str
    name: str
    market: str
    grouping: str | dict[str, Any] | None
    group_id: int | str | None
    group_name: str | None
    instrument: Instrument | dict[str, Any]
    instrument_currency: Currency | None
    instrument_price: JsonNumber | None
    quantity: JsonNumber | None
    value: JsonNumber | None
    cost_base: HoldingCostBase | None
    average_purchase_price: JsonNumber | None
    annualised_return_percent: JsonNumber | None
    inception_date: str | None
    labels: list[Label] | list[str]
    limited: bool
    valid_position: bool
    number_of_unconfirmed_transactions: int | None


class HoldingsResponse(TypedDict, total=False):
    """Envelope returned by portfolio holding endpoints."""

    holdings: list[Holding]
    api_transaction: ApiTransaction


class HoldingResponse(TypedDict, total=False):
    """Envelope returned by ``GET v3/holdings/{holding_id}``."""

    holding: Holding
    api_transaction: ApiTransaction


class SubTotal(GainFields, total=False):
    """One grouped sub-total row of a performance report."""

    value: JsonNumber | None
    group_id: int | str | None
    group_name: str | None


class ReportCashAccount(TypedDict, total=False):
    """Cash-account balance as embedded in a performance report.

    ``value`` is already converted to the report currency; use the v2
    cash-account routes for the native-currency balance.
    """

    id: int | str
    key: int | str | None
    name: str
    source: str | None
    value: JsonNumber | None
    currency: Currency | None
    portfolio: PortfolioReference


class PerformanceReport(GainFields, total=False):
    """Core v2/v3 performance report fields."""

    id: int | str
    portfolio_id: int | str
    portfolio_tz_name: str | None
    start_date: str
    end_date: str
    grouping: str
    custom_group_id: int | str | None
    include_sales: bool
    currency_code: str
    currency: Currency
    value: JsonNumber | None
    cost_base: JsonNumber | None
    annualised_return_percent: JsonNumber | None
    percentages_annualised: bool
    holdings: list[Holding]
    sub_totals: list[SubTotal]
    combined_holdings: list[dict[str, Any]]
    cash_accounts: list[ReportCashAccount]
    links: dict[str, Any]


class PerformanceResponse(TypedDict, total=False):
    """Envelope used by the v3 performance endpoint."""

    report: PerformanceReport
    api_transaction: ApiTransaction
    links: dict[str, Any]


class Trade(TypedDict, total=False):
    """Trade record returned by portfolio and holding endpoints.

    ``value`` is signed: Sharesight returns a SELL's value as a negative
    number.  ``price`` and ``brokerage`` are in their own declared currencies.
    """

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
    price_currency_code: str | None
    market_price: JsonNumber | None
    market_price_exchange_rate: JsonNumber | None
    cost_base: JsonNumber | None
    exchange_rate: JsonNumber | None
    brokerage: JsonNumber | None
    brokerage_currency_code: str | None
    value: JsonNumber | None
    paid_on: str | None
    capital_return_value: JsonNumber | None
    company_event_id: int | str | None
    state: str
    confirmed: bool
    comments: str | None
    attachment_filename: str | None
    attachment_id: int | str | None
    links: dict[str, Any]


class TradesResponse(TypedDict, total=False):
    """Envelope returned by trade list endpoints."""

    trades: list[Trade]
    api_transaction: ApiTransaction
    links: dict[str, Any]


class DrpTradeAttributes(TypedDict, total=False):
    """Dividend-reinvestment details attached to a reinvested payout."""

    dividend_reinvested: bool
    quantity: JsonNumber | None
    price: str | JsonNumber | None
    source_adjustment_id: int | str | None


class Payout(TypedDict, total=False):
    """Dividend or distribution payout.

    ``amount`` and ``gross_amount`` are in the payout ``currency``; divide by
    ``exchange_rate`` to convert into the portfolio currency.  The tax
    breakdown fields (franking, withholding, capital-gain distributions and
    AMIT adjustments) are documented as already being in portfolio currency.
    An announced-but-unconfirmed payout carries a ``null`` ``id``.
    """

    id: int | str | None
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
    non_taxable: bool
    comments: str | None
    company_event_id: int | str | None
    state: str
    confirmed: bool
    trust: bool
    franking_credits: JsonNumber | None
    franked_amount: JsonNumber | None
    unfranked_amount: JsonNumber | None
    resident_withholding_tax: JsonNumber | None
    non_resident_withholding_tax: JsonNumber | None
    foreign_source_income: JsonNumber | None
    other_net_fsi: JsonNumber | None
    lic_capital_gain: JsonNumber | None
    interest_payment: JsonNumber | None
    discounted_capital_gains: JsonNumber | None
    non_discounted_capital_gains: JsonNumber | None
    cgt_concession_amount: JsonNumber | None
    amit_decrease_amount: JsonNumber | None
    amit_increase_amount: JsonNumber | None
    deferred_income: JsonNumber | None
    non_assessable: JsonNumber | None
    drp_trade_attributes: DrpTradeAttributes | None
    attachment_filename: str | None
    attachment_id: int | str | None
    links: dict[str, Any]


class PayoutsResponse(TypedDict, total=False):
    """Envelope returned by payout list endpoints."""

    payouts: list[Payout]
    links: dict[str, Any]


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
    links: dict[str, Any]


# The v2 show route returns a bare cash-account object rather than an envelope.
# Retain this public name as an alias for callers that imported the 1.5 models
# during development.
CashAccountResponse: TypeAlias = CashAccount


class CashAccountTransactionType(TypedDict, total=False):
    """Nested transaction-type block; ``name`` can be null on synced rows."""

    name: str | None


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
    cash_account_transaction_type: CashAccountTransactionType | str | None
    links: dict[str, Any]


class CashAccountTransactionsResponse(TypedDict, total=False):
    """Envelope returned by a cash-account transaction list."""

    cash_account_transactions: list[CashAccountTransaction]
    links: dict[str, Any]


class Group(TypedDict, total=False):
    """Sharesight grouping definition."""

    id: int | str
    name: str
    custom: bool | str
    portfolio_ids: list[int | str]


class GroupsResponse(TypedDict, total=False):
    """Envelope returned by ``GET v2/groups.json``."""

    groups: list[Group]


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
    """One portfolio or holding value-series observation.

    The live ``portfolio_value_data.json`` route names the day ``timestamp``
    (a bare ``YYYY-MM-DD`` date in the portfolio calendar); the apiDoc example
    uses ``date``.  Both spellings are modelled.
    """

    date: str
    timestamp: str
    value: JsonNumber | None


class ValueSeriesChart(TypedDict, total=False):
    """The ``chart`` wrapper the live value-series routes actually return."""

    data: list[ValuePoint]


class ValueSeriesResponse(TypedDict, total=False):
    """A value series may be wrapped or returned as a bare list by Sharesight.

    Live production responses use ``{"chart": {"data": [...]}}``; the apiDoc
    describes ``values`` / ``portfolio_value_data`` wrappers.  Consumers should
    peel whichever container is present rather than assuming one shape.
    """

    chart: ValueSeriesChart
    data: list[ValuePoint]
    values: list[ValuePoint]
    portfolio_value_data: list[ValuePoint] | dict[str, Any]
    links: dict[str, Any]
    api_transaction: ApiTransaction


class PortfolioValue(TypedDict, total=False):
    """Point-in-time portfolio balance from the mobile-tagged ``/value`` route."""

    value: JsonNumber | None
    currency_code: str
    currency: Currency
    as_at: str | None


class PortfolioValueResponse(TypedDict, total=False):
    """Envelope returned by ``GET v3/portfolios/{id}/value``.

    The apiDoc example is loose; the balance may be wrapped or bare.
    """

    value: JsonNumber | dict[str, Any] | None
    portfolio_value: PortfolioValue
    currency_code: str
    api_transaction: ApiTransaction


class Benchmark(TypedDict, total=False):
    """Benchmark performance for a portfolio's configured benchmark.

    ``maximum_drawdown`` and ``return_over_drawdown`` are undocumented but
    present on every live response.  The live field is ``capital_gain_percent``
    even though the apiDoc documents ``capital_gain_percentage``.
    """

    start_date: str
    end_date: str
    portfolio_tz_name: str | None
    instrument: Instrument
    capital_gain_percent: JsonNumber | None
    capital_gain_percentage: JsonNumber | None
    payout_gain_percent: JsonNumber | None
    currency_gain_percent: JsonNumber | None
    total_gain_percent: JsonNumber | None
    percentages_annualised: bool
    maximum_drawdown: JsonNumber | None
    return_over_drawdown: JsonNumber | None


class BenchmarkResponse(TypedDict, total=False):
    """Envelope returned by ``GET v3/portfolios/{id}/benchmark.json``."""

    benchmark: Benchmark
    api_transaction: ApiTransaction


class PortfolioUserSetting(TypedDict, total=False):
    """The authenticated user's saved report preferences for a portfolio."""

    portfolio_chart: str | None
    portfolio_chart_range: str | None
    holding_chart: str | None
    holding_chart_range: str | None
    combined: str | bool | None
    report_combined: bool
    grouping: str | None
    report_grouping: str | None
    report_currency: str | None
    include_sold_shares: bool
    report_include_sold_shares: bool
    benchmark_instrument_id: int | str | None
    taxable_show_comments: bool
    taxable_grouped_by_holding: bool
    overview_show_as_percentage: bool
    overview_table_columns: list[dict[str, Any]]
    overview_sort_column: str | None
    overview_sort_direction: str | None
    overview_start_date: str | None
    overview_end_date: str | None
    overview_gains_losses_view: str | None


class UserSettingResponse(TypedDict, total=False):
    """Envelope returned by ``GET v3/portfolios/{id}/user_setting``."""

    portfolio_user_setting: PortfolioUserSetting
    api_transaction: ApiTransaction


class UserInstrument(TypedDict, total=False):
    """One instrument held across the user's portfolios (``user_instruments``).

    Fundamentals (``pe_ratio``, ``eps``, ``nta``) are routinely null or zero
    for funds, ETFs and foreign listings.
    """

    id: int | str
    code: str
    market_code: str
    name: str
    currency_code: str
    pe_ratio: JsonNumber | None
    nta: JsonNumber | None
    eps: JsonNumber | None
    current_price: JsonNumber | None
    current_price_updated_at: str | None
    sector_classification_name: str | None
    industry_classification_name: str | None
    security_type: str | None
    friendly_instrument_description: str | None
    registry_name: str | None


class UserInstrumentsResponse(TypedDict, total=False):
    """Envelope returned by ``GET v2/user_instruments.json``."""

    instruments: list[UserInstrument]
    links: dict[str, Any]


class User(TypedDict, total=False):
    """Non-secret account and subscription metadata (``my_user.json``)."""

    id: int | str
    name: str
    first_name: str
    last_name: str
    email: str
    plan_code: str | None
    plan_label: str | None
    is_activated: bool
    is_free: bool
    is_beta: bool
    is_ai: bool
    is_guest: bool
    is_staff: bool
    is_professional: bool
    is_cancelled: bool
    is_expired: bool
    signed_up_at: str | None
    signup_via_your_integration: bool


class MyUserResponse(TypedDict, total=False):
    """Envelope returned by ``GET v2/my_user.json``."""

    user: User


class WatchlistPrice(TypedDict, total=False):
    """Latest price block on a watchlist item."""

    value: JsonNumber | None
    timestamp: str | None
    diff_value: JsonNumber | None
    diff_percent: JsonNumber | None
    currency: Currency


class WatchlistItem(TypedDict, total=False):
    """One watched instrument with its latest price."""

    instrument: Instrument
    price: WatchlistPrice


class WatchlistResponse(TypedDict, total=False):
    """Envelope returned by the mobile-tagged ``GET v3/watchlist.json``."""

    watchlist: list[WatchlistItem]
    links: dict[str, Any]
    api_transaction: ApiTransaction


class CgtParcel(TypedDict, total=False):
    """A realised parcel in the v2 capital-gains report."""

    market: str
    symbol: str
    name: str
    allocation_method: str | None
    purchase_date: str | None
    quantity: JsonNumber | None
    cost_base: JsonNumber | None
    market_value: JsonNumber | None
    gain: JsonNumber | None
    gain_date: str | None


class CapitalGainsReport(TypedDict, total=False):
    """The v2 realised capital-gains report (Australian portfolios only).

    ``cgt_concession_rate`` is a ratio (``0.5`` for the 50% discount), not a
    percentage.
    """

    short_term_gains: JsonNumber | None
    long_term_gains: JsonNumber | None
    losses: JsonNumber | None
    short_term_losses: JsonNumber | None
    long_term_losses: JsonNumber | None
    total_discounted_capital_gain_distributions: JsonNumber | None
    total_non_discounted_capital_gain_distributions: JsonNumber | None
    cgt_concession_rate: JsonNumber | None
    cgt_concession_amount: JsonNumber | None
    market_value: JsonNumber | None
    tax_gain_loss: JsonNumber | None
    claimable_loss: JsonNumber | None
    total_exemptions: JsonNumber | None
    discounted_capital_gain_distributions: list[dict[str, Any]]
    non_discounted_capital_gain_distributions: list[dict[str, Any]]
    short_term_parcels: list[CgtParcel]
    long_term_parcels: list[CgtParcel]
    loss_parcels: list[CgtParcel]
    exempt_parcels: list[CgtParcel]
    start_date: str
    end_date: str
    portfolio_id: int | str
    links: dict[str, Any]


class UnrealisedCgtParcel(TypedDict, total=False):
    """An open parcel in the v2 unrealised-CGT report."""

    market: str
    symbol: str
    name: str
    allocation_method: str | None
    purchase_date: str | None
    quantity: JsonNumber | None
    cost_base: JsonNumber | None
    market_value: JsonNumber | None
    unrealised_gain: JsonNumber | None


class UnrealisedCgtReport(TypedDict, total=False):
    """The v2 unrealised capital-gains report (Australian portfolios only)."""

    unrealised_short_term_gains: JsonNumber | None
    unrealised_long_term_gains: JsonNumber | None
    unrealised_losses: JsonNumber | None
    cgt_concession_rate: JsonNumber | None
    unrealised_cgt_concession_amount: JsonNumber | None
    market_value: JsonNumber | None
    unrealised_tax_gain_loss: JsonNumber | None
    total_exemptions: JsonNumber | None
    short_term_parcels: list[UnrealisedCgtParcel]
    long_term_parcels: list[UnrealisedCgtParcel]
    losses: list[UnrealisedCgtParcel]
    exempt_parcels: list[UnrealisedCgtParcel]
    balance_date: str
    portfolio_id: int | str
    links: dict[str, Any]


class SharecheckerInstrument(TypedDict, total=False):
    """Instrument block of the mobile-tagged sharechecker payload."""

    id: int | str
    code: str
    market_code: str
    name: str
    country_name: str | None
    sector_name: str | None


class SharecheckerPerformance(TypedDict, total=False):
    """Performance block of the sharechecker payload."""

    start_date: str | None
    capital_gain: JsonNumber | None
    capital_gain_percent: JsonNumber | None
    payout_gain: JsonNumber | None
    payout_gain_percent: JsonNumber | None
    currency_gain: JsonNumber | None
    currency_gain_percent: JsonNumber | None
    total_return_gain: JsonNumber | None
    total_return_gain_percent: JsonNumber | None


class SharecheckerPrice(TypedDict, total=False):
    """Latest price block of the sharechecker payload."""

    value: JsonNumber | None
    timestamp: str | None
    currency: Currency | str | None


class Sharechecker(TypedDict, total=False):
    """Instrument fundamentals from ``GET v3/instruments/{id}/sharechecker``."""

    instrument: SharecheckerInstrument
    amount_invested: JsonNumber | None
    start_date: str | None
    interest_method: str | None
    performance: SharecheckerPerformance
    price: SharecheckerPrice
    chart: dict[str, Any]


class SharecheckerResponse(TypedDict, total=False):
    """Envelope returned by the mobile-tagged sharechecker route."""

    sharechecker: Sharechecker
    api_transaction: ApiTransaction


class AveragePurchasePrice(TypedDict, total=False):
    """Official average purchase price in the instrument currency."""

    value: JsonNumber | None
    currency: Currency | str | None


class AveragePurchasePriceResponse(TypedDict, total=False):
    """Envelope returned by ``GET v3/holdings/{id}/average_purchase_price.json``."""

    average_purchase_price: AveragePurchasePrice
    api_transaction: ApiTransaction


class CostBaseResponse(TypedDict, total=False):
    """Envelope returned by ``GET v3/holdings/{id}/cost_base.json``."""

    cost_base: HoldingCostBase
    api_transaction: ApiTransaction


class InstrumentPrice(TypedDict, total=False):
    """One historical price from the mobile-tagged v2 instrument prices route."""

    id: int | str
    date: str | None
    last_traded_on: str | None
    last_traded_value: JsonNumber | None
    open: JsonNumber | None
    high: JsonNumber | None
    low: JsonNumber | None
    close: JsonNumber | None
    volume: JsonNumber | None


class InstrumentPricesResponse(TypedDict, total=False):
    """Envelope returned by ``GET v2/instruments/{id}/prices.json``."""

    prices: list[InstrumentPrice]
    links: dict[str, Any]


class PerformanceIndexLine(TypedDict, total=False):
    """One growth-index line of the performance index chart.

    The apiDoc names the discriminator ``type`` while the example uses
    ``line_type``; both are modelled so callers can parse defensively.
    """

    type: str | None
    line_type: str | None
    name: str | None
    values: list[JsonNumber | None]


class PerformanceIndexChart(TypedDict, total=False):
    """Growth-of-index series for a portfolio and its benchmark."""

    dates: list[str]
    lines: list[PerformanceIndexLine]


class PerformanceIndexChartResponse(PerformanceIndexChart, total=False):
    """Envelope for ``GET v3/portfolios/{id}/performance_index_chart``.

    The apiDoc field list wraps the chart in ``performance_index_chart`` while
    its example does not; the flat fields are inherited so either parses.
    """

    performance_index_chart: PerformanceIndexChart
    api_transaction: ApiTransaction


class SingleSignOnResponse(TypedDict, total=False):
    """Envelope returned by ``GET v2/single_sign_on.json``.

    ``login_url`` grants a logged-in Sharesight session for about one minute.
    Treat it like a password: never log it or persist it.
    """

    login_url: str
