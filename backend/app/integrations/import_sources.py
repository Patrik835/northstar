from dataclasses import dataclass

from app.models.enums import Broker


@dataclass(frozen=True, slots=True)
class ImportSourceDefinition:
    """Discovery and upload behavior for a provider-native statement connector."""

    broker: Broker
    display_name: str
    short_mark: str
    category: str
    description: str
    security_notice: str
    setup_steps: tuple[str, ...]
    tutorial_url: str
    endpoint: str
    accept: str
    multiple: bool
    prompt: str
    help_text: str
    empty_file_message: str
    holding_label: str


IMPORT_SOURCES = (
    ImportSourceDefinition(
        broker=Broker.BYBIT,
        display_name="Bybit",
        short_mark="BY",
        category="Crypto exchange",
        description=(
            "Import balances, Spot trades, transfers, income, and fees from Bybit's "
            "native account-data exports."
        ),
        security_notice=(
            "Northstar reads only the files you select. No Bybit API key, password, "
            "or third-party approval is required."
        ),
        setup_steps=(
            "On the Bybit website, open Account → Data Export.",
            "Export Unified Trading Account Change Details for the full available period.",
            "Also export Spot Trade History so buys, sells, prices, and fees are included.",
            "Upload the CSV files together. XLSX versions and overlapping yearly exports "
            "are also accepted.",
        ),
        tutorial_url=(
            "https://www.bybit.com/en/help-center/article/How-to-Self-Export-Account-Data"
        ),
        endpoint="/connections/imports/bybit",
        accept=(
            ".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        multiple=True,
        prompt="Select Bybit exports",
        help_text=(
            "CSV or XLSX · select Account Change Details and Spot Trade History together"
        ),
        empty_file_message="Choose at least one Bybit CSV or XLSX export first.",
        holding_label="crypto holding",
    ),
    ImportSourceDefinition(
        broker=Broker.TRADING212_CRYPTO,
        display_name="Trading 212 Crypto",
        short_mark="2C",
        category="Crypto broker",
        description=(
            "Import Trading 212 Crypto history safely from its official CSV export. "
            "Re-import later files without duplicating transactions."
        ),
        security_notice=(
            "Trading 212 does not expose Crypto accounts through its Public API. "
            "Northstar reads only the CSV you choose and never asks for login credentials."
        ),
        setup_steps=(
            "Open the Crypto account in Trading 212.",
            "Go to Menu, then History, and select Export.",
            "Include completed Buy, Sell, Deposit, and Withdrawal activity.",
            "Choose the full available date range for the first import.",
            "Download the CSV and upload it below. Later overlapping exports are safe.",
        ),
        tutorial_url=(
            "https://helpcentre.trading212.com/hc/en-us/articles/"
            "30721201341213-What-are-the-Crypto-account-views"
        ),
        endpoint="/connections/imports/trading212-crypto",
        accept=".csv,text/csv",
        multiple=False,
        prompt="Select Trading 212 Crypto CSV",
        help_text="CSV only · maximum 10 MB · overlapping exports are safe",
        empty_file_message="Choose the Trading 212 Crypto CSV export first.",
        holding_label="crypto holding",
    ),
    ImportSourceDefinition(
        broker=Broker.XTB,
        display_name="XTB",
        short_mark="XT",
        category="Broker",
        description=(
            "Import XTB stock and ETF positions, P/L, and account activity from "
            "xStation CSV or Excel reports. Overlapping reports are safe."
        ),
        security_notice=(
            "XTB discontinued its public API. Northstar reads only the reports you "
            "select and never asks for XTB login credentials."
        ),
        setup_steps=(
            "Sign in to xStation on the web.",
            "Export the current Open positions report from the Orders view.",
            "Export Closed positions and Cash operations for the full available history.",
            "Upload the CSV or XLSX reports together. Later overlapping reports are safe.",
        ),
        tutorial_url=(
            "https://www.xtb.com/int/help-center/our-platforms-5-1/"
            "open-positions-and-pending-orders-1"
        ),
        endpoint="/connections/imports/xtb",
        accept=(
            ".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        multiple=True,
        prompt="Select XTB reports",
        help_text=(
            "CSV or XLSX · select current positions and history together · "
            "overlapping reports are safe"
        ),
        empty_file_message="Choose at least one XTB CSV or Excel report first.",
        holding_label="holding",
    ),
    ImportSourceDefinition(
        broker=Broker.TRADE_REPUBLIC,
        display_name="Trade Republic",
        short_mark="TR",
        category="Broker",
        description=(
            "Import stocks, ETFs, crypto trades, dividends, fees, and estimated "
            "holdings from Trade Republic's native transaction CSV."
        ),
        security_notice=(
            "Northstar reads only the CSV you select. Your Trade Republic login and PIN "
            "are never requested."
        ),
        setup_steps=(
            "Open Trade Republic and go to Profile → Statements → Transaction export.",
            "Select the full available date range and create the CSV.",
            "Upload the CSV below. Re-importing an overlapping export is safe.",
        ),
        tutorial_url=(
            "https://intercom.help/blockpit/en/articles/"
            "15452549-how-to-import-data-via-trade-republic-csv-file"
        ),
        endpoint="/connections/imports/trade-republic",
        accept=".csv,text/csv",
        multiple=False,
        prompt="Select Trade Republic transaction CSV",
        help_text="Native CSV · full history recommended · overlapping exports are safe",
        empty_file_message="Choose the Trade Republic transaction CSV first.",
        holding_label="estimated holding",
    ),
    ImportSourceDefinition(
        broker=Broker.SCALABLE_CAPITAL,
        display_name="Scalable Capital",
        short_mark="SC",
        category="Broker",
        description=(
            "Import Scalable Capital trades, distributions, fees, and estimated holdings "
            "from its native transaction CSV."
        ),
        security_notice=(
            "Northstar reads only the CSV you select and never asks for your Scalable "
            "Capital password or 2FA approval."
        ),
        setup_steps=(
            "Sign in to Scalable Capital on the web and open Broker → Transactions.",
            "Select all transactions and choose Export CSV.",
            "Upload the CSV below. Re-importing an overlapping export is safe.",
        ),
        tutorial_url=(
            "https://help.scalable.capital/en/account-management-f3197dc7/"
            "how-can-i-view-and-export-my-transactions-b0b78717"
        ),
        endpoint="/connections/imports/scalable-capital",
        accept=".csv,text/csv",
        multiple=False,
        prompt="Select Scalable Capital transaction CSV",
        help_text="Native CSV · full history recommended · overlapping exports are safe",
        empty_file_message="Choose the Scalable Capital transaction CSV first.",
        holding_label="estimated holding",
    ),
)
