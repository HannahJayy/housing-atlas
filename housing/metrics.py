"""Catalog of every metric shown in the app (data sources, formats, transforms).

kind:
  base    - loaded directly from a data source
  stored  - computed by the pipeline (derive.py / scores.py) and saved
  virtual - computed on request from other series (respects Settings assumptions)
change:   'pct' -> changes shown as % growth;  'diff' -> changes shown as point differences
polarity: +1 higher is bullish for prices (green), -1 higher is bearish (red), 0 neutral
"""

ALL = ["us", "state", "metro", "county", "zip"]
NOZIP = ["us", "state", "metro", "county"]
METRO_ONLY = ["us", "metro"]

CATEGORIES = [
    ("prices", "Home Prices"),
    ("valuation", "Valuation & Forecast"),
    ("afford", "Affordability"),
    ("inventory", "Inventory & Supply"),
    ("market", "Market Speed & Competition"),
    ("rent", "Rent & Investing"),
    ("construction", "New Construction"),
    ("people", "Population & Migration"),
    ("economy", "Income & Jobs"),
    ("stock", "Housing Stock"),
    ("risk", "Natural Hazard Risk"),
]

T_PRICE = ["level", "mom", "yoy", "chg_5y", "chg_10y", "from_peak", "vs_pre"]
T_LIST = ["level", "mom", "yoy", "vs_pre"]
T_RATE = ["level", "yoy", "vs_pre"]
T_ANNUAL = ["level", "yoy", "chg_5y"]
T_LEVEL = ["level"]

SRC = {
    "zillow": "Zillow Research",
    "realtor": "Realtor.com",
    "redfin": "Redfin Data Center",
    "census_acs": "Census ACS 5-yr",
    "census_pep": "Census Population Estimates",
    "census_bps": "Census Building Permits",
    "bea": "BEA",
    "bls": "BLS",
    "fred": "FRED / Freddie Mac",
    "fhfa": "FHFA",
    "fema_nri": "FEMA NRI",
    "derived": "Housing Atlas calculation",
}


def M(id, name, cat, fmt, src, desc, kind="base", freq="M", change="pct", polarity=0,
      transforms=None, levels=None, deps=None, default_tf="level", short=None):
    return {
        "id": id, "name": name, "short": short or name, "cat": cat, "fmt": fmt, "src": src, "desc": desc,
        "kind": kind, "freq": freq, "change": change, "polarity": polarity,
        "transforms": transforms or (T_LIST if freq == "M" else T_ANNUAL), "levels": levels or ALL,
        "deps": deps or [], "default_tf": default_tf,
    }


METRICS = [
    # ------------------------------------------------------------------ prices
    M("zhvi", "Home Value", "prices", "usd", "zillow",
      "Zillow Home Value Index: the typical (35th-65th percentile) home value, seasonally adjusted.",
      polarity=1, transforms=T_PRICE, short="Home Value"),
    M("zhvi_sfr", "Home Value - Single-Family", "prices", "usd", "zillow",
      "ZHVI for single-family homes only.", polarity=1, transforms=T_PRICE, levels=NOZIP),
    M("zhvi_condo", "Home Value - Condo/Co-op", "prices", "usd", "zillow",
      "ZHVI for condos and co-ops only.", polarity=1, transforms=T_PRICE, levels=NOZIP),
    M("zhvi_bottom", "Home Value - Bottom Tier", "prices", "usd", "zillow",
      "ZHVI for the cheapest third of homes (5th-35th percentile).", polarity=1, transforms=T_PRICE, levels=NOZIP),
    M("zhvi_top", "Home Value - Top Tier", "prices", "usd", "zillow",
      "ZHVI for the most expensive third of homes (65th-95th percentile).", polarity=1, transforms=T_PRICE,
      levels=NOZIP),
    M("rf_median_sale_price", "Median Sale Price", "prices", "usd", "redfin",
      "Median price of homes sold (Redfin, all residential). ZIP figures are 3-month rolling.",
      polarity=1, transforms=T_PRICE),
    M("list_price", "Median List Price", "prices", "usd", "realtor",
      "Median asking price of active listings (Realtor.com).", polarity=1, transforms=T_PRICE),
    M("avg_list_price", "Average List Price", "prices", "usd", "realtor",
      "Average asking price of active listings (Realtor.com).", polarity=1, transforms=T_LIST),
    M("list_ppsf", "List Price per Sq Ft", "prices", "usd", "realtor",
      "Median listing price per square foot (Realtor.com).", polarity=1, transforms=T_PRICE),
    M("rf_median_ppsf", "Sale Price per Sq Ft", "prices", "usd", "redfin",
      "Median sale price per square foot (Redfin).", polarity=1, transforms=T_PRICE),
    M("rf_median_list_price", "Median New-Listing Price", "prices", "usd", "redfin",
      "Median asking price of homes newly listed during the month (Redfin).", polarity=1, transforms=T_LIST),
    M("z_list_price", "Median List Price (Zillow)", "prices", "usd", "zillow",
      "Median list price of for-sale listings on Zillow.", polarity=1, transforms=T_LIST, levels=METRO_ONLY),
    M("z_median_sale_price", "Median Sale Price (Zillow)", "prices", "usd", "zillow",
      "Median sale price (Zillow, seasonally adjusted).", polarity=1, transforms=T_PRICE, levels=METRO_ONLY),
    M("fhfa_hpi", "FHFA House Price Index", "prices", "num", "fhfa",
      "Repeat-sales index of single-family homes with conforming mortgages (monthly U.S.; quarterly "
      "states/metros).", polarity=1, transforms=["level", "yoy", "chg_5y", "from_peak"],
      levels=["us", "state", "metro"]),
    M("gfc_crash", "% Crash 2007-2012", "prices", "pct", "derived",
      "Peak-to-trough change in the Zillow Home Value Index during the Great Financial Crisis "
      "(highest value 2004-2008 vs lowest value 2008-2013).", kind="stored", freq="A", polarity=0,
      transforms=T_LEVEL),

    # ------------------------------------------------------------------ valuation & forecast
    M("overvalued", "Over/Under Valued %", "valuation", "pct", "derived",
      "How far home values sit above (+) or below (-) their long-term norm. Average of two measures: "
      "price-to-income vs its 2000-2019 average, and price vs its 2000-2019 log-linear trend.",
      kind="stored", change="diff", polarity=-1, transforms=["level", "yoy"]),
    M("overvalued_income", "Overvalued vs Income %", "valuation", "pct", "derived",
      "Home value / median household income compared with that region's 2000-2019 average ratio.",
      kind="stored", change="diff", polarity=-1, transforms=["level", "yoy"]),
    M("overvalued_trend", "Overvalued vs Long-Term Trend %", "valuation", "pct", "derived",
      "Home value compared with the extension of its 2000-2019 log-linear price trend.",
      kind="stored", change="diff", polarity=-1, transforms=["level", "yoy"]),
    M("value_to_income", "Value/Income Ratio", "valuation", "ratio", "derived",
      "Typical home value divided by median household income (income estimated for the same month).",
      kind="virtual", change="diff", polarity=-1, transforms=["level", "yoy", "chg_5y", "vs_pre"],
      deps=["zhvi", "income"]),
    M("forecast_score", "Price Forecast Score", "valuation", "score", "derived",
      "0-100 score of near-term price direction from momentum, inventory vs normal, inventory growth, "
      "price cuts, days on market, months of supply and overvaluation (higher = stronger).",
      kind="stored", change="diff", polarity=1, transforms=["level", "yoy"]),
    M("forecast_12m", "12-Month Price Forecast", "valuation", "pct", "derived",
      "Expected home value change over the next 12 months, from the Forecast Score calibrated on "
      "history (see Methodology).", kind="stored", change="diff", polarity=1, transforms=["level"]),
    M("zhvf_1y", "Zillow 1-Year Forecast", "valuation", "pct", "zillow",
      "Zillow's own forecast of ZHVI growth over the next 12 months.", change="diff", polarity=1,
      transforms=T_LEVEL),
    M("longterm_score", "Long-Term Growth Score", "valuation", "score", "derived",
      "0-100 score of long-run fundamentals: population growth, migration, job growth, income growth, "
      "10-year appreciation and affordability.", kind="stored", freq="A", polarity=1, transforms=T_LEVEL),
    M("investor_score", "Investor Score", "valuation", "score", "derived",
      "0-100 score for rental investors: gross yield, rent growth, valuation, price forecast, population "
      "growth, vacancy and property taxes.", kind="stored", freq="A", polarity=1, transforms=T_LEVEL),

    # ------------------------------------------------------------------ affordability
    M("payment", "Monthly House Payment", "afford", "usd", "derived",
      "Principal & interest + property tax + insurance for the typical home, using the Freddie Mac 30-year "
      "rate for that month and the down payment in Settings.", kind="virtual", polarity=-1,
      transforms=["level", "yoy", "chg_5y", "vs_pre"], deps=["zhvi", "property_tax_rate"]),
    M("payment_pi", "Mortgage Payment (P&I only)", "afford", "usd", "derived",
      "Principal & interest only on the typical home.", kind="virtual", polarity=-1,
      transforms=["level", "yoy", "chg_5y", "vs_pre"], deps=["zhvi"]),
    M("payment_to_income", "House Payment as % of Income", "afford", "pct", "derived",
      "Monthly house payment (incl. tax & insurance) as a share of median household income.",
      kind="virtual", change="diff", polarity=-1, transforms=["level", "yoy", "chg_5y", "vs_pre"],
      deps=["zhvi", "income", "property_tax_rate"]),
    M("income_needed", "Income Needed to Buy", "afford", "usd", "derived",
      "Household income needed so the house payment stays within the affordable share in Settings "
      "(default 30%).", kind="virtual", polarity=-1, transforms=["level", "yoy", "vs_pre"],
      deps=["zhvi", "property_tax_rate"]),
    M("z_income_needed", "Income Needed (Zillow, 20% down)", "afford", "usd", "zillow",
      "Zillow's estimate of income needed to afford the typical home with 20% down.", polarity=-1,
      levels=METRO_ONLY, transforms=T_RATE),
    M("property_tax_rate", "Property Tax Rate", "afford", "pct", "census_acs",
      "Median real estate taxes paid / median home value (ACS).", freq="A", change="diff", polarity=-1,
      transforms=T_LEVEL),
    M("acs_taxes", "Median Property Taxes Paid", "afford", "usd", "census_acs",
      "Median annual real estate taxes paid by homeowners (ACS).", freq="A", polarity=-1),
    M("mortgaged_pct", "Mortgaged Homes %", "afford", "pct", "census_acs",
      "Share of owner-occupied homes with a mortgage or similar debt (ACS).", freq="A", change="diff"),

    # ------------------------------------------------------------------ inventory & supply
    M("inventory", "For-Sale Inventory", "inventory", "num", "realtor",
      "Active listings for sale (Realtor.com, excludes pending).", polarity=-1,
      transforms=["level", "mom", "yoy", "vs_pre"], default_tf="level"),
    M("inventory_pct_houses", "Inventory as % of Houses", "inventory", "pct", "derived",
      "Active listings divided by total housing units (ACS).", kind="virtual", change="diff", polarity=-1,
      transforms=["level", "yoy", "vs_pre"], deps=["inventory", "housing_units"]),
    M("new_listings", "New Listings", "inventory", "num", "realtor",
      "Homes newly listed for sale during the month (Realtor.com).", polarity=-1, transforms=T_LIST),
    M("pending_listings", "Pending Listings", "inventory", "num", "realtor",
      "Listings under contract (Realtor.com).", polarity=1, transforms=T_LIST),
    M("pending_ratio", "Pending Ratio", "inventory", "pct", "realtor",
      "Pending listings as a % of active listings - a demand-vs-supply gauge (Realtor.com).",
      change="diff", polarity=1, transforms=T_RATE),
    M("total_listings", "Total Listings (Active + Pending)", "inventory", "num", "realtor",
      "All listings including pending (Realtor.com).", polarity=-1, transforms=T_LIST),
    M("rf_inventory", "Inventory (Redfin)", "inventory", "num", "redfin",
      "Homes for sale at the end of the month (Redfin).", polarity=-1, transforms=T_LIST),
    M("rf_new_listings", "New Listings (Redfin)", "inventory", "num", "redfin",
      "New listings during the month (Redfin).", polarity=-1, transforms=T_LIST),
    M("rf_months_supply", "Months of Supply", "inventory", "months", "redfin",
      "Months it would take to sell current inventory at the current sales pace (Redfin). Under 4 = "
      "seller's market, over 6 = buyer's market.", change="diff", polarity=-1, transforms=T_RATE),
    M("z_inventory", "For-Sale Inventory (Zillow)", "inventory", "num", "zillow",
      "For-sale listings on Zillow (smoothed).", polarity=-1, transforms=T_LIST, levels=METRO_ONLY),
    M("z_new_listings", "New Listings (Zillow)", "inventory", "num", "zillow",
      "New for-sale listings on Zillow (smoothed).", polarity=-1, transforms=T_LIST, levels=METRO_ONLY),
    M("z_new_pending", "Newly Pending (Zillow)", "inventory", "num", "zillow",
      "Listings that went pending during the month on Zillow.", polarity=1, transforms=T_LIST,
      levels=METRO_ONLY),
    M("shadow_inventory", "Shadow Inventory %", "inventory", "pct", "census_acs",
      "Vacant homes held off the market for 'other' reasons (not for sale, rent, or seasonal use) as a % of "
      "all housing units (ACS 'other vacant').", freq="A", change="diff", polarity=-1),

    # ------------------------------------------------------------------ market speed
    M("dom", "Days on Market", "market", "days", "realtor",
      "Median days active listings have been on the market (Realtor.com).", polarity=-1,
      transforms=["level", "yoy", "vs_pre"]),
    M("price_cut_share", "Price Cut Share %", "market", "pct", "realtor",
      "Share of active listings with a price reduction during the month (Realtor.com).", change="diff",
      polarity=-1, transforms=["level", "yoy", "vs_pre"]),
    M("price_increase_share", "Price Increase Share %", "market", "pct", "realtor",
      "Share of active listings with a price increase (Realtor.com).", change="diff", polarity=1,
      transforms=T_RATE),
    M("rf_dom", "Days on Market (Redfin)", "market", "days", "redfin",
      "Median days from listing to pending for homes sold (Redfin).", polarity=-1,
      transforms=["level", "yoy", "vs_pre"]),
    M("rf_sale_to_list", "Sale-to-List Ratio", "market", "pct", "redfin",
      "Average sale price as a % of final list price (Redfin). Above 100% = bidding wars.",
      change="diff", polarity=1, transforms=T_RATE),
    M("rf_sold_above_list", "Sold Above List %", "market", "pct", "redfin",
      "Share of homes that sold above their list price (Redfin).", change="diff", polarity=1,
      transforms=T_RATE),
    M("rf_price_drops", "Price Drops % (Redfin)", "market", "pct", "redfin",
      "Share of listings with a price drop (Redfin).", change="diff", polarity=-1, transforms=T_RATE),
    M("rf_off_market_2wk", "Off Market in 2 Weeks %", "market", "pct", "redfin",
      "Share of homes that went under contract within two weeks (Redfin).", change="diff", polarity=1,
      transforms=T_RATE),
    M("rf_homes_sold", "Homes Sold", "market", "num", "redfin",
      "Number of homes sold during the month (Redfin; ZIP = 3-month rolling).", polarity=1,
      transforms=T_LIST),
    M("rf_pending_sales", "Pending Sales", "market", "num", "redfin",
      "Homes that went under contract during the month (Redfin).", polarity=1, transforms=T_LIST),
    M("z_days_pending", "Days to Pending (Zillow)", "market", "days", "zillow",
      "Median days from listing to pending on Zillow.", polarity=-1, transforms=T_RATE, levels=METRO_ONLY),
    M("z_price_cut_share", "Price Cut Share % (Zillow)", "market", "pct", "zillow",
      "Share of Zillow listings with a price cut.", change="diff", polarity=-1, transforms=T_RATE,
      levels=METRO_ONLY),
    M("z_sale_to_list", "Sale-to-List Ratio (Zillow)", "market", "pct", "zillow",
      "Mean sale-to-list ratio (Zillow).", change="diff", polarity=1, transforms=T_RATE, levels=METRO_ONLY),
    M("z_pct_above_list", "Sold Above List % (Zillow)", "market", "pct", "zillow",
      "Share of sales above list price (Zillow).", change="diff", polarity=1, transforms=T_RATE,
      levels=METRO_ONLY),
    M("z_sales_count", "Sales Count (Zillow)", "market", "num", "zillow",
      "Estimated number of home sales (Zillow nowcast).", polarity=1, transforms=T_LIST, levels=METRO_ONLY),
    M("z_heat_index", "Market Heat Index (Zillow)", "market", "num", "zillow",
      "Zillow's market temperature (above 70 = hot seller's market, below 30 = cold buyer's market).",
      change="diff", polarity=1, transforms=T_RATE, levels=METRO_ONLY),
    M("hotness_score", "Market Hotness Score", "market", "score", "realtor",
      "Realtor.com market hotness (0-100) combining days on market and listing views.", change="diff",
      polarity=1, transforms=T_RATE, levels=["metro", "county", "zip"]),
    M("supply_score", "Supply Score (speed)", "market", "score", "realtor",
      "Realtor.com supply score - how fast inventory sells (higher = faster).", change="diff", polarity=1,
      transforms=T_RATE, levels=["metro", "county", "zip"]),
    M("demand_score", "Demand Score (views)", "market", "score", "realtor",
      "Realtor.com demand score based on listing page views.", change="diff", polarity=1,
      transforms=T_RATE, levels=["metro", "county", "zip"]),
    M("views_vs_us", "Listing Views vs U.S.", "market", "ratio", "realtor",
      "Listing page views per property relative to the U.S. average (1.0 = average).", change="diff",
      polarity=1, transforms=T_RATE, levels=["metro", "county", "zip"]),
    M("median_sqft", "Median Listing Size (sq ft)", "market", "num", "realtor",
      "Median square footage of active listings (Realtor.com).", transforms=T_RATE),

    # ------------------------------------------------------------------ rent & investing
    M("rent", "Rent (All Homes)", "rent", "usd", "zillow",
      "Zillow Observed Rent Index: typical asking rent across houses and apartments.", polarity=1,
      transforms=["level", "mom", "yoy", "chg_5y", "vs_pre"]),
    M("rent_houses", "Rent for Houses", "rent", "usd", "zillow",
      "ZORI for single-family rentals.", polarity=1, transforms=["level", "yoy", "chg_5y", "vs_pre"],
      levels=["us", "metro", "county", "zip"]),
    M("rent_apartments", "Rent for Apartments", "rent", "usd", "zillow",
      "ZORI for multi-family (apartment) rentals.", polarity=1, transforms=["level", "yoy", "chg_5y", "vs_pre"],
      levels=["us", "metro", "county", "zip"]),
    M("acs_rent", "Median Gross Rent (Census)", "rent", "usd", "census_acs",
      "Median contract rent plus utilities paid by renters (ACS 5-year; lags the market).", freq="A",
      polarity=1),
    M("rent_to_income", "Rent as % of Income", "rent", "pct", "derived",
      "Annual typical rent (ZORI) as a share of median household income.", kind="virtual", change="diff",
      polarity=-1, transforms=["level", "yoy", "vs_pre"], deps=["rent", "income"]),
    M("price_to_rent", "Price-to-Rent Ratio", "rent", "ratio", "derived",
      "Home value divided by a year of rent. Higher = renting is cheaper relative to buying.",
      kind="virtual", change="diff", polarity=-1, transforms=["level", "yoy", "vs_pre"], deps=["zhvi", "rent"]),
    M("gross_yield", "Gross Rental Yield", "rent", "pct", "derived",
      "Annual rent / home value.", kind="virtual", change="diff", polarity=1,
      transforms=["level", "yoy", "vs_pre"], deps=["zhvi", "rent"]),
    M("cap_rate", "Cap Rate (est.)", "rent", "pct", "derived",
      "Estimated net yield: annual rent minus operating costs (expense ratio in Settings, default 40%), "
      "divided by home value.", kind="virtual", change="diff", polarity=1,
      transforms=["level", "yoy", "vs_pre"], deps=["zhvi", "rent"]),
    M("buy_vs_rent", "Buy vs Rent Premium %", "rent", "pct", "derived",
      "How much more (+) or less (-) the monthly house payment costs than renting the typical home.",
      kind="virtual", change="diff", polarity=-1, transforms=["level", "yoy", "vs_pre"],
      deps=["zhvi", "rent", "property_tax_rate"]),
    M("rent_burden_acs", "Rent Burden (Census)", "rent", "pct", "census_acs",
      "Median gross rent as a % of household income for renters (ACS).", freq="A", change="diff",
      polarity=-1),
    M("rental_vacancy", "Rental Vacancy Rate", "rent", "pct", "census_acs",
      "Vacant for-rent units / rental stock (ACS 5-year).", freq="A", change="diff", polarity=-1),

    # ------------------------------------------------------------------ construction
    M("permits", "Building Permits (units)", "construction", "num", "census_bps",
      "New housing units authorized by building permits per year; the latest year is the trailing 12 "
      "months.", freq="A", polarity=-1),
    M("permits_pct", "Building Permits % of Housing", "construction", "pct", "derived",
      "Permitted units over the last 12 months as a % of existing housing units - the new-supply rate.",
      kind="virtual", freq="A", change="diff", polarity=-1, transforms=T_ANNUAL, deps=["permits", "housing_units"]),
    M("permits_sf", "Single-Family Permits", "construction", "num", "census_bps",
      "Single-family units authorized by permits (per year / trailing 12 months).", freq="A", polarity=-1),
    M("permits_mf", "Multi-Family Permits", "construction", "num", "census_bps",
      "Units in 2+ unit buildings authorized by permits.", freq="A", polarity=-1),
    M("z_new_con_sales", "New Construction Sales (Zillow)", "construction", "num", "zillow",
      "Newly built homes sold per month (Zillow).", transforms=T_LIST, levels=METRO_ONLY),
    M("z_new_con_price", "New Construction Median Price (Zillow)", "construction", "usd", "zillow",
      "Median sale price of newly built homes (Zillow).", polarity=1, transforms=T_LIST, levels=METRO_ONLY),
    M("median_year_built", "Median Year Built", "construction", "year", "census_acs",
      "Median construction year of the housing stock (ACS).", freq="A", change="diff", transforms=T_LEVEL),

    # ------------------------------------------------------------------ people
    M("population", "Population", "people", "num", "census_pep",
      "Resident population (Census estimates; ZIP codes use ACS 5-year).", freq="A", polarity=1,
      transforms=T_ANNUAL),
    M("net_migration", "Net Migration", "people", "num", "census_pep",
      "People moving in minus moving out (domestic + international) during the year ending July 1.",
      freq="A", change="diff", polarity=1, transforms=["level", "yoy"], levels=NOZIP),
    M("migration_rate", "Net Migration % of Population", "people", "pct", "census_pep",
      "Net migration as a % of population.", freq="A", change="diff", polarity=1,
      transforms=["level", "yoy"], levels=NOZIP),
    M("domestic_migration", "Domestic Migration", "people", "num", "census_pep",
      "Net moves from other U.S. areas.", freq="A", change="diff", polarity=1, transforms=["level", "yoy"],
      levels=NOZIP),
    M("intl_migration", "International Migration", "people", "num", "census_pep",
      "Net international migration.", freq="A", change="diff", polarity=1, transforms=["level", "yoy"],
      levels=NOZIP),
    M("natural_change", "Natural Change (births - deaths)", "people", "num", "census_pep",
      "Births minus deaths.", freq="A", change="diff", transforms=["level"], levels=NOZIP),
    M("pop_density", "Population Density", "people", "num", "derived",
      "Residents per square mile of land.", kind="virtual", freq="A", transforms=T_LEVEL, deps=["population"]),
    M("median_age", "Median Age", "people", "num", "census_acs", "Median age of residents (ACS).",
      freq="A", change="diff", transforms=T_LEVEL),
    M("homeownership", "Homeownership Rate", "people", "pct", "census_acs",
      "Owner-occupied homes / occupied homes (ACS).", freq="A", change="diff"),
    M("poverty_rate", "Poverty Rate", "people", "pct", "census_acs",
      "Share of residents below the poverty line (ACS).", freq="A", change="diff", polarity=-1),

    # ------------------------------------------------------------------ economy
    M("acs_income", "Median Household Income", "economy", "usd", "census_acs",
      "Median household income (ACS 5-year; dollars of the survey's final year).", freq="A", polarity=1),
    M("income", "Median Household Income (est. current)", "economy", "usd", "derived",
      "ACS median household income moved to the current year using BEA per-capita income growth "
      "(used for affordability and valuation).", kind="stored", freq="A", polarity=1),
    M("pcpi", "Per Capita Personal Income", "economy", "usd", "bea",
      "Total personal income / population (BEA).", freq="A", polarity=1, levels=NOZIP),
    M("unemployment", "Unemployment Rate", "economy", "pct", "bls",
      "Unemployment rate (BLS LAUS; states seasonally adjusted, metros & counties not).",
      change="diff", polarity=-1, transforms=["level", "yoy"], levels=NOZIP),
    M("payroll_jobs", "Payroll Jobs (nonfarm)", "economy", "num", "bls",
      "Total nonfarm payroll employment (BLS Current Employment Statistics; metros & states via the BLS API, "
      "U.S. from FRED).", polarity=1, transforms=["level", "yoy", "chg_5y"], levels=["us", "state", "metro"],
      default_tf="yoy"),
    M("employment", "Employment (residents with jobs)", "economy", "num", "bls",
      "Employed residents (BLS household survey).", polarity=1, transforms=["level", "yoy"], levels=NOZIP),
    M("labor_force", "Labor Force", "economy", "num", "bls", "Civilian labor force (BLS).", polarity=1,
      transforms=["level", "yoy"], levels=NOZIP),

    # ------------------------------------------------------------------ housing stock
    M("housing_units", "Housing Units", "stock", "num", "census_acs", "Total housing units (ACS).",
      freq="A"),
    M("housing_units_est", "Housing Units (annual estimate)", "stock", "num", "census_pep",
      "Census Bureau July 1 housing unit estimates; the 1-year change is the housing-stock growth rate.",
      freq="A", polarity=-1, transforms=["level", "yoy", "chg_5y"], levels=NOZIP, default_tf="yoy"),
    M("vacancy_rate", "Vacancy Rate", "stock", "pct", "census_acs", "Vacant units / all units (ACS).",
      freq="A", change="diff", polarity=-1),
    M("homeowner_vacancy", "Homeowner Vacancy Rate", "stock", "pct", "census_acs",
      "Vacant for-sale homes / owner housing stock (ACS).", freq="A", change="diff", polarity=-1),
    M("seasonal_pct", "Vacation/Seasonal Homes %", "stock", "pct", "census_acs",
      "Homes held for seasonal, recreational or occasional use as a % of all units (ACS) - a proxy for "
      "second-home / short-term-rental exposure.", freq="A", change="diff"),
    M("acs_value", "Median Home Value (Census)", "stock", "usd", "census_acs",
      "Owner-estimated median home value (ACS 5-year; lags the market).", freq="A", polarity=1),
    M("housing_costs", "Median Monthly Housing Cost", "stock", "usd", "census_acs",
      "Median monthly housing costs for all occupied homes (ACS).", freq="A", polarity=-1),

    # ------------------------------------------------------------------ risk
    M("nri_risk", "Natural Hazard Risk Score", "risk", "score", "fema_nri",
      "FEMA National Risk Index composite score (0-100).", freq="A", polarity=-1, transforms=T_LEVEL,
      levels=["county"]),
    M("nri_eal", "Expected Annual Loss ($)", "risk", "usd", "fema_nri",
      "Expected annual loss to buildings, population and agriculture from natural hazards.", freq="A",
      polarity=-1, transforms=T_LEVEL, levels=["county"]),
    M("nri_hurricane", "Hurricane Risk Score", "risk", "score", "fema_nri", "FEMA NRI hurricane risk.",
      freq="A", polarity=-1, transforms=T_LEVEL, levels=["county"]),
    M("nri_wildfire", "Wildfire Risk Score", "risk", "score", "fema_nri", "FEMA NRI wildfire risk.",
      freq="A", polarity=-1, transforms=T_LEVEL, levels=["county"]),
    M("nri_flood", "Riverine Flood Risk Score", "risk", "score", "fema_nri", "FEMA NRI riverine flooding risk.",
      freq="A", polarity=-1, transforms=T_LEVEL, levels=["county"]),
    M("nri_coastal_flood", "Coastal Flood Risk Score", "risk", "score", "fema_nri",
      "FEMA NRI coastal flooding risk.", freq="A", polarity=-1, transforms=T_LEVEL, levels=["county"]),
    M("nri_heat", "Heat Wave Risk Score", "risk", "score", "fema_nri", "FEMA NRI heat wave risk.",
      freq="A", polarity=-1, transforms=T_LEVEL, levels=["county"]),
    M("nri_tornado", "Tornado Risk Score", "risk", "score", "fema_nri", "FEMA NRI tornado risk.",
      freq="A", polarity=-1, transforms=T_LEVEL, levels=["county"]),
    M("nri_earthquake", "Earthquake Risk Score", "risk", "score", "fema_nri", "FEMA NRI earthquake risk.",
      freq="A", polarity=-1, transforms=T_LEVEL, levels=["county"]),
]

BY_ID = {m["id"]: m for m in METRICS}

TRANSFORMS = {
    "level": "Current value",
    "mom": "1-month change",
    "yoy": "1-year change",
    "chg_5y": "5-year change",
    "chg_10y": "10-year change",
    "from_peak": "vs. all-time high",
    "vs_pre": "vs. pre-pandemic (2017-19)",
}

# Shown first in pickers / region pages (Reventure-style core set)
FEATURED = ["zhvi", "overvalued", "forecast_12m", "forecast_score", "inventory", "price_cut_share", "dom",
            "payment", "payment_to_income", "value_to_income", "rent", "cap_rate", "population",
            "unemployment", "permits_pct", "rf_months_supply"]


def public_catalog():
    cats = [{"id": c, "name": n} for c, n in CATEGORIES]
    return {"categories": cats, "metrics": METRICS, "transforms": TRANSFORMS, "featured": FEATURED,
            "sources": SRC}
