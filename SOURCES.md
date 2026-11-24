# Data sources

Every number in Housing Atlas comes from the free, public files below. The app downloads them for you (button on the **Data & Sources** page, `python app.py update`, or the weekly schedule) and shows the status, latest period and exact file URLs of each source on that page. If a provider ever moves a file, paste the new link under **Settings > Advanced: download URL overrides** using the key shown in brackets.

| Source | What Housing Atlas uses | Published | License / terms |
|---|---|---|---|
| [U.S. Census Bureau - Cartographic Boundary Files](https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html) | State, county, metro (CBSA) and ZIP code (ZCTA) shapes used to draw the map, plus the official ZCTA-to-county relationship file used to place each ZIP inside a county/metro. | Yearly (new vintage each spring) | Public domain (U.S. Government work) |
| [U.S. Census Bureau - Population Estimates (PEP)](https://www.census.gov/programs-surveys/popest/data/data-sets.html) | Annual July 1 population estimates and the components of change (net, domestic and international migration) for every state, county and metro area, plus annual county housing-unit estimates (the housing-stock growth rate); also provides the official list of counties that make up each metro area. | Yearly (population each March; housing units each May) | Public domain (U.S. Government work) |
| [Zillow Research (Zillow Economic Data)](https://www.zillow.com/research/data/) | Zillow Home Value Index (typical home value), Zillow Observed Rent Index, 1-year home value forecasts, and listing/sales metrics (inventory, new listings, price cuts, days to pending, sale-to-list, market heat, new construction). | Monthly (around the middle of each month) | Free for public use with attribution to Zillow |
| [Realtor.com Economic Research - Housing Inventory Data](https://www.realtor.com/research/data/) | Monthly MLS-based listing data: active inventory, new and pending listings, median list price and price/sq ft, days on market, share of listings with price cuts/increases, plus the Market Hotness index (supply, demand and listing views). | Monthly (first week of each month) | Free to use with attribution to Realtor.com |
| [Redfin Data Center - Housing Market Tracker](https://www.redfin.com/news/data-center/) | MLS-based monthly sales data: median sale price, homes sold, pending sales, new listings, inventory, months of supply, median days on market, sale-to-list ratio, share sold above list, price drops and share off market in two weeks. ZIP-level figures are 3-month rolling. | Monthly (mid-month) + weekly national tracker (Thursdays) | Free to use with attribution to Redfin (Redfin Data Center) |
| [U.S. Census Bureau - American Community Survey 5-Year Estimates](https://www.census.gov/programs-surveys/acs/data/summary-file.html) | Median household income, median home value & rent, housing units, vacancy (rental, homeowner, seasonal, 'other vacant'), homeownership, share of homes with a mortgage, property taxes, median age, poverty, year built and rent burden for every state, county, metro and ZIP code (ZCTA). | Yearly (each December) | Public domain (U.S. Government work) |
| [U.S. Census Bureau - Building Permits Survey](https://www.census.gov/construction/bps/) | New privately-owned housing units authorized by building permits, by county (summed to metros, states and the nation). The latest year is a trailing-12-month total built from the newest monthly year-to-date file. | Monthly (county year-to-date files) + annual | Public domain (U.S. Government work) |
| [U.S. Bureau of Economic Analysis - Personal Income (CAINC1)](https://apps.bea.gov/regional/downloadzip.htm) | Per-capita personal income for every county, metro and state since 1969. Its growth rate extends Census median household income back (and forward) in time, which powers the income-based overvaluation and affordability history. | Yearly (counties/metros each November; states quarterly) | Public domain (U.S. Government work) |
| [U.S. Bureau of Labor Statistics - Unemployment (LAUS) & Payroll Jobs (CES)](https://www.bls.gov/lau/) | Monthly unemployment rate, number employed and labor force for every state (seasonally adjusted), metro area and county (not seasonally adjusted), plus total nonfarm payroll jobs for every state and metro area from the BLS API (no key needed; a free key raises the daily limit). BLS asks automated downloaders to include a contact e-mail - set one in Settings if downloads are refused. | Monthly | Public domain (U.S. Government work) |
| [FRED - Federal Reserve Bank of St. Louis](https://fred.stlouisfed.org/) | National series: Freddie Mac 30/15-year mortgage rates, Treasury & Fed funds rates, Case-Shiller index, new/existing home sales, housing starts & permits, vacancy and homeownership rates, mortgage delinquencies, CPI shelter, payrolls and unemployment. | Weekly (mortgage rates every Thursday) to quarterly | Varies by series; FRED data is free for personal use (see each series' notes) |
| [FHFA House Price Index (HPI)](https://www.fhfa.gov/data/hpi/datasets) | Repeat-sales house price index (Fannie Mae / Freddie Mac mortgages): monthly purchase-only index for the U.S., and quarterly indexes for states and ~400 metro areas. | Monthly (last Tuesday) / quarterly | Public domain (U.S. Government work) |
| [FEMA National Risk Index (optional)](https://hazards.fema.gov/nri/data-resources) | County natural-hazard risk scores (overall, hurricane, wildfire, flooding, heat, tornado, earthquake) and expected annual losses - useful context for insurance costs. Disabled by default; enable it in Settings. | Roughly yearly | Public domain (U.S. Government work) |

## Exact files downloaded

Years in some URLs are examples - the app automatically finds the newest published vintage.

### U.S. Census Bureau - Cartographic Boundary Files

- `tiger_state` - State shapes (newest vintage found)  
  <https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_state_20m.zip>
- `tiger_county` - County shapes  
  <https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_county_5m.zip>
- `tiger_cbsa` - Metro/micro area (CBSA) shapes  
  <https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_cbsa_5m.zip>
- `tiger_zcta` - ZIP code (ZCTA) shapes  
  <https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_zcta520_500k.zip>
- `zcta_county_rel` - ZCTA-to-county relationship file  
  <https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt>

### U.S. Census Bureau - Population Estimates (PEP)

- `pep_county` - County & state totals (newest vintage found)  
  <https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/totals/co-est2025-alldata.csv>
- `pep_metro` - Metro/micro totals + county membership  
  <https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/metro/totals/cbsa-est2025-alldata.csv>
- `pep_county_2019` - 2010-2019 county history  
  <https://www2.census.gov/programs-surveys/popest/datasets/2010-2019/counties/totals/co-est2019-alldata.csv>
- `pep_metro_2019` - 2010-2019 metro history  
  <https://www2.census.gov/programs-surveys/popest/datasets/2010-2019/metro/totals/cbsa-est2019-alldata.csv>
- `pep_housing_units` - County housing unit estimates (XLSX)  
  <https://www2.census.gov/programs-surveys/popest/tables/2020-2025/housing/totals/CO-EST2025-HU.xlsx>

### Zillow Research (Zillow Economic Data)

- `zillow_zhvi_county` - zhvi (county)  
  <https://files.zillowstatic.com/research/public_csvs/zhvi/County_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv>
- `zillow_zhvi_metro` - zhvi (metro)  
  <https://files.zillowstatic.com/research/public_csvs/zhvi/Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv>
- `zillow_zhvi_state` - zhvi (state)  
  <https://files.zillowstatic.com/research/public_csvs/zhvi/State_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv>
- `zillow_zhvi_zip` - zhvi (zip)  
  <https://files.zillowstatic.com/research/public_csvs/zhvi/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv>
- `zillow_rent_metro` - rent (metro)  
  <https://files.zillowstatic.com/research/public_csvs/zori/Metro_zori_uc_sfrcondomfr_sm_month.csv>
- `zillow_rent_county` - rent (county)  
  <https://files.zillowstatic.com/research/public_csvs/zori/County_zori_uc_sfrcondomfr_sm_month.csv>
- `zillow_rent_zip` - rent (zip)  
  <https://files.zillowstatic.com/research/public_csvs/zori/Zip_zori_uc_sfrcondomfr_sm_month.csv>
- `zillow_rent_state` - rent (state)  
  <https://files.zillowstatic.com/research/public_csvs/zori/State_zori_uc_sfrcondomfr_sm_month.csv>
- `zillow_rent_houses_metro` - rent_houses (metro)  
  <https://files.zillowstatic.com/research/public_csvs/zori/Metro_zori_uc_sfr_sm_month.csv>
- `zillow_rent_houses_county` - rent_houses (county)  
  <https://files.zillowstatic.com/research/public_csvs/zori/County_zori_uc_sfr_sm_month.csv>
- `zillow_rent_houses_zip` - rent_houses (zip)  
  <https://files.zillowstatic.com/research/public_csvs/zori/Zip_zori_uc_sfr_sm_month.csv>
- `zillow_rent_apartments_metro` - rent_apartments (metro)  
  <https://files.zillowstatic.com/research/public_csvs/zori/Metro_zori_uc_mfr_sm_month.csv>
- `zillow_rent_apartments_county` - rent_apartments (county)  
  <https://files.zillowstatic.com/research/public_csvs/zori/County_zori_uc_mfr_sm_month.csv>
- `zillow_rent_apartments_zip` - rent_apartments (zip)  
  <https://files.zillowstatic.com/research/public_csvs/zori/Zip_zori_uc_mfr_sm_month.csv>
- ...and 30 more files following the same pattern (see the Sources page for the full list)

### Realtor.com Economic Research - Housing Inventory Data

- `realtor_core_us` - Inventory core metrics (us)  
  <https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/RDC_Inventory_Core_Metrics_Country_History.csv>
- `realtor_core_state` - Inventory core metrics (state)  
  <https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/RDC_Inventory_Core_Metrics_State_History.csv>
- `realtor_core_metro` - Inventory core metrics (metro)  
  <https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/RDC_Inventory_Core_Metrics_Metro_History.csv>
- `realtor_core_county` - Inventory core metrics (county)  
  <https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/RDC_Inventory_Core_Metrics_County_History.csv>
- `realtor_core_zip` - Inventory core metrics (zip)  
  <https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/RDC_Inventory_Core_Metrics_Zip_History.csv>
- `realtor_hot_metro` - Market hotness (metro)  
  <https://econdata.s3-us-west-2.amazonaws.com/Reports/Hotness/RDC_Inventory_Hotness_Metrics_Metro_History.csv>
- `realtor_hot_county` - Market hotness (county)  
  <https://econdata.s3-us-west-2.amazonaws.com/Reports/Hotness/RDC_Inventory_Hotness_Metrics_County_History.csv>
- `realtor_hot_zip` - Market hotness (zip)  
  <https://econdata.s3-us-west-2.amazonaws.com/Reports/Hotness/RDC_Inventory_Hotness_Metrics_Zip_History.csv>

### Redfin Data Center - Housing Market Tracker

- `redfin_us` - Market tracker (us)  
  <https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/us_national_market_tracker.tsv000.gz>
- `redfin_state` - Market tracker (state)  
  <https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/state_market_tracker.tsv000.gz>
- `redfin_metro` - Market tracker (metro)  
  <https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/redfin_metro_market_tracker.tsv000.gz>
- `redfin_county` - Market tracker (county)  
  <https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/county_market_tracker.tsv000.gz>
- `redfin_zip` - Market tracker (zip)  
  <https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/zip_code_market_tracker.tsv000.gz>
- `redfin_weekly` - Weekly tracker (national & metro)  
  <https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_covid19/weekly_housing_market_data_most_recent.tsv000.gz>

### U.S. Census Bureau - American Community Survey 5-Year Estimates

- `acs_sf_b01003` - ACS table B01003  
  <https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b01003.dat>
- `acs_sf_b19013` - ACS table B19013  
  <https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b19013.dat>
- `acs_sf_b25077` - ACS table B25077  
  <https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b25077.dat>
- `acs_sf_b25064` - ACS table B25064  
  <https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b25064.dat>
- `acs_sf_b25001` - ACS table B25001  
  <https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b25001.dat>
- `acs_sf_b25002` - ACS table B25002  
  <https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b25002.dat>
- `acs_sf_b25003` - ACS table B25003  
  <https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b25003.dat>
- `acs_sf_b25004` - ACS table B25004  
  <https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b25004.dat>
- `acs_sf_b25081` - ACS table B25081  
  <https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b25081.dat>
- `acs_sf_b25103` - ACS table B25103  
  <https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b25103.dat>
- `acs_sf_b01002` - ACS table B01002  
  <https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b01002.dat>
- `acs_sf_b17001` - ACS table B17001  
  <https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b17001.dat>
- `acs_sf_b25035` - ACS table B25035  
  <https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b25035.dat>
- `acs_sf_b25071` - ACS table B25071  
  <https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b25071.dat>
- ...and 1 more files following the same pattern (see the Sources page for the full list)

### U.S. Census Bureau - Building Permits Survey

- `bps_annual` - Annual county permits (each year)  
  <https://www2.census.gov/econ/bps/County/co2025a.txt>
- `bps_ytd` - Monthly year-to-date county permits (newest month found)  
  <https://www2.census.gov/econ/bps/County/co2609y.txt>

### U.S. Bureau of Economic Analysis - Personal Income (CAINC1)

- `bea_cainc1` - CAINC1 all areas (zipped CSV)  
  <https://apps.bea.gov/regional/zip/CAINC1.zip>

### U.S. Bureau of Labor Statistics - Unemployment (LAUS) & Payroll Jobs (CES)

- `bls_county14` - Counties, latest 14 months  
  <https://www.bls.gov/web/metro/laucntycur14.txt>
- `bls_metro` - Metro areas, full history  
  <https://download.bls.gov/pub/time.series/la/la.data.60.Metro>
- `bls_states` - States (seasonally adjusted), full history  
  <https://download.bls.gov/pub/time.series/la/la.data.3.AllStatesS>
- `bls_ces_api` - Payroll jobs (CES) for metros & states via the BLS API (replies cached 6 days; ~18 of the 25 requests/day allowed without a free key)  
  <https://api.bls.gov/publicAPI/v1/timeseries/data/>

### FRED - Federal Reserve Bank of St. Louis

- `fred_MORTGAGE30US` - 30-Year Fixed Mortgage Rate (Freddie Mac PMMS)  
  <https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US>
- `fred_MORTGAGE15US` - 15-Year Fixed Mortgage Rate (Freddie Mac PMMS)  
  <https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE15US>
- `fred_DGS10` - 10-Year Treasury Yield (monthly avg)  
  <https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10>
- `fred_FEDFUNDS` - Effective Federal Funds Rate  
  <https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS>
- `fred_DRSFRMACBS` - Delinquency Rate on Single-Family Mortgages (banks)  
  <https://fred.stlouisfed.org/graph/fredgraph.csv?id=DRSFRMACBS>
- `fred_MDSP` - Mortgage Debt Service Payments (% of disposable income)  
  <https://fred.stlouisfed.org/graph/fredgraph.csv?id=MDSP>
- `fred_CSUSHPINSA` - Case-Shiller U.S. National Home Price Index (NSA)  
  <https://fred.stlouisfed.org/graph/fredgraph.csv?id=CSUSHPINSA>
- `fred_CSUSHPISA` - Case-Shiller U.S. National Home Price Index (SA)  
  <https://fred.stlouisfed.org/graph/fredgraph.csv?id=CSUSHPISA>
- `fred_MSPUS` - Median Sales Price of Houses Sold (Census/HUD)  
  <https://fred.stlouisfed.org/graph/fredgraph.csv?id=MSPUS>
- `fred_MSPNHSUS` - Median Sales Price of New Houses Sold  
  <https://fred.stlouisfed.org/graph/fredgraph.csv?id=MSPNHSUS>
- `fred_ACTLISCOUUS` - Active Listings - U.S. (Realtor.com)  
  <https://fred.stlouisfed.org/graph/fredgraph.csv?id=ACTLISCOUUS>
- `fred_NEWLISCOUUS` - New Listings - U.S. (Realtor.com)  
  <https://fred.stlouisfed.org/graph/fredgraph.csv?id=NEWLISCOUUS>
- `fred_PENLISCOUUS` - Pending Listings - U.S. (Realtor.com)  
  <https://fred.stlouisfed.org/graph/fredgraph.csv?id=PENLISCOUUS>
- `fred_PRIREDCOUUS` - Listings with Price Reductions - U.S. (Realtor.com)  
  <https://fred.stlouisfed.org/graph/fredgraph.csv?id=PRIREDCOUUS>
- ...and 19 more files following the same pattern (see the Sources page for the full list)

### FHFA House Price Index (HPI)

- `fhfa_master` - HPI master file (all indexes)  
  <https://www.fhfa.gov/hpi/download/monthly/hpi_master.csv>

### FEMA National Risk Index (optional)

- `fema_nri_counties` - NRI county table (zipped CSV)  
  <https://hazards.fema.gov/nri/Content/StaticDocuments/DataDownload//NRI_Table_Counties/NRI_Table_Counties.zip>

## Other sources reviewed

| Source | Status |
|---|---|
| [Orchard](https://orchard.com/blog) | Publishes market analyses (e.g. cities with the most new-construction permits) but no downloadable dataset. The permit data behind those posts is the Census Building Permits Survey, which Housing Atlas downloads directly. |
| [Apartment List rent estimates](https://www.apartmentlist.com/research/category/data-rent-estimates) | Free monthly CSV (rents, vacancy, time on market by metro/city). The download link changes every month, so it isn't automated yet; Zillow ZORI covers rents. |
| [HUD Fair Market Rents](https://www.huduser.gov/portal/datasets/fmr.html) | Free with a HUD API token; useful for Section 8 benchmarks. Not automated. |
| [FEMA National Risk Index](https://hazards.fema.gov/nri/data-resources) | Included as an optional source (off by default) - enable it in Settings. |
| NAR, ICE Mortgage Monitor, CoreLogic, ATTOM, Black Knight, John Burns, Parcl Labs, Altos | Paid or license-restricted. Not included. |

## Notes on the data

- **Zillow** ZHVI/ZORI are smoothed, seasonally adjusted indexes of typical values/rents, not medians of sales.
- **Redfin** ZIP-level numbers are rolling 3-month figures; metros that Redfin only publishes as metropolitan divisions (New York, Los Angeles, Miami, Dallas, ...) are combined into the full metro (approximation).
- **Realtor.com** inventory counts active listings (pending excluded); small ZIPs can be noisy.
- **Census ACS** 5-year estimates average five years of surveys and lag the market by 2-3 years.
- **Building permits**: the newest year is a trailing-12-month total built from the latest monthly year-to-date file.
- **BLS** asks automated downloaders to identify themselves - add a contact e-mail in Settings if BLS downloads are refused.
