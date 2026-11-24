// Methodology: how every derived metric and score is calculated.

import { api } from '../api.js';
import { h } from '../ui.js';
import { STATE, SRC_NAMES } from '../fmt.js';

const FACTOR_NAMES = {
  mom3: 'Price momentum (3-month annualized change in home value)', inv_vs_pre: 'Inventory vs. 2017-19 same-month average',
  inv_yoy: 'Inventory 1-year change', cut_yoy: 'Price-cut share 1-year change', dom_yoy: 'Days on market 1-year change',
  overval: 'Overvaluation %', mos: 'Months of supply (Redfin)', pop5: '5-year population growth', mig: 'Net migration rate',
  jobs: '1-year job growth (payroll jobs for metros & states, employed residents elsewhere)', inc5: '5-year per-capita income growth', app10: '10-year home value growth',
  vti: 'Value-to-income ratio', yield: 'Gross rental yield', rentg: '1-year rent growth', fscore: 'Price Forecast Score',
  vac: 'Rental vacancy rate', tax: 'Property tax rate',
};

function factorTable(f) {
  return h('table', { class: 'data', style: { maxWidth: '640px' } }, h('thead', null, h('tr', null, h('th', null, 'Factor'), h('th', { class: 'num' }, 'Weight'), h('th', null, 'Direction'))),
    h('tbody', null, Object.entries(f).map(([k, [w, d]]) => h('tr', null, h('td', null, FACTOR_NAMES[k] || k),
      h('td', { class: 'num' }, Math.round(w * 1000) / 10 + '%'), h('td', null, d > 0 ? 'Higher = better' : 'Lower = better')))));
}

export async function render(root) {
  const page = h('div', { class: 'page prose' });
  root.appendChild(page);
  let m = {};
  try { m = await api('/api/methodology', { cache: true }); } catch (e) { /* ignore */ }
  const cal = m.calibration || {};
  const a = m.affordability || {};
  page.append(
    h('h1', null, 'Methodology'),
    h('p', { class: 'secondary' }, 'Housing Atlas combines free public datasets. Raw metrics are shown exactly as each provider publishes them; the calculated metrics below are transparent formulas you can audit (and tweak in Settings).'),

    h('h2', null, 'Geographies'),
    h('ul', null,
      h('li', null, h('b', null, 'Metros'), ' are Census Core-Based Statistical Areas (metropolitan + micropolitan). Zillow and Redfin metro names are matched to CBSA codes; where Redfin only reports metropolitan divisions (e.g. New York, Los Angeles, Miami, Dallas) the divisions are combined: counts are summed and medians/ratios weighted by homes sold or inventory (an approximation).'),
      h('li', null, h('b', null, 'ZIP codes'), ' are Census ZIP Code Tabulation Areas, assigned to the county with the largest land overlap.'),
      h('li', null, 'Redfin ZIP-level figures are rolling 3-month values; Realtor.com ZIP data can be noisy for small ZIPs.')),

    h('h2', null, 'Transforms'),
    h('ul', null,
      h('li', null, h('b', null, '1-year / 5-year / 10-year change'), ': percent change for prices, counts and days; percentage-point difference for rates and shares.'),
      h('li', null, h('b', null, 'vs. pre-pandemic'), ': compares the latest month with the average of the same calendar month in 2017, 2018 and 2019 (removes seasonality). This is the “inventory surplus/deficit vs normal” view.'),
      h('li', null, h('b', null, 'vs. all-time high'), ': distance below the highest value ever recorded (price drawdown from peak).')),

    h('h2', null, 'Affordability'),
    h('ul', null,
      h('li', null, h('b', null, 'Monthly House Payment'), ' = principal & interest on the Zillow typical home value with ', String(a.down_payment_pct), '% down over ', String(a.loan_years), ' years at the Freddie Mac 30-year rate for that month (monthly average of the weekly survey', a.rate_override_pct ? '; currently overridden to ' + a.rate_override_pct + '%' : '', '), plus property tax (ACS effective rate) and insurance (', String(a.insurance_rate_pct), '% of value per year)', a.pmi_rate_pct ? ', plus PMI' : '', '.'),
      h('li', null, h('b', null, 'House Payment as % of Income'), ' = monthly payment ÷ (median household income ÷ 12).'),
      h('li', null, h('b', null, 'Income Needed to Buy'), ' = payment × 12 ÷ ', String(a.affordable_dti_pct), '%.'),
      h('li', null, h('b', null, 'Median household income (est. current)'), ': the latest ACS 5-year median household income is carried backward and forward in time using BEA per-capita personal income growth for the same county/metro/state (ZIP codes use their county). After the last BEA year, the 3-year average growth rate is extended.'),
      h('li', null, h('b', null, 'Property Tax Rate'), ' = ACS median real estate taxes paid ÷ ACS median home value.')),

    h('h2', null, 'Valuation'),
    h('ul', null,
      h('li', null, h('b', null, 'Overvalued vs Income'), ': each year 2000-2019, annual average home value ÷ estimated median household income gives a price-to-income ratio. Its 2000-2019 average is the region’s “normal”. Today’s ratio vs that normal is the over/under-valuation.'),
      h('li', null, h('b', null, 'Overvalued vs Long-Term Trend'), ': a log-linear trend is fitted to monthly home values from 2000-2019 and extended to today; the gap between today’s value and the trend line.'),
      h('li', null, h('b', null, 'Over/Under Valued %'), ' (headline) = the average of the two measures when both are available.'),
      h('li', null, h('b', null, 'Value/Income'), ' = home value ÷ median household income. ', h('b', null, '% Crash 2007-2012'), ' = lowest value 2008-2013 vs highest value 2004-2008.')),

    h('h2', null, 'Price Forecast Score & 12-month forecast'),
    h('p', null, 'Each factor is converted to a percentile against its own history across all regions of the same type since 2018 (so a nationwide shift – like inventory rising everywhere – moves every score). The score is the weighted average percentile (0-100, higher = stronger price outlook). Factors with no data for a region are skipped and the weights re-normalized (at least three are required).'),
    factorTable(m.forecast_factors || {}),
    h('p', { style: { marginTop: '10px' } }, 'The ', h('b', null, '12-month forecast'), ' maps the score to an expected price change with a regression fitted on history (county & metro scores vs. the actual next-12-month change in home value): ',
      h('span', { class: 'formula' }, 'forecast = ' + (cal.intercept !== undefined ? cal.intercept.toFixed(2) : 'a') + '% + ' + (cal.slope !== undefined ? cal.slope.toFixed(3) : 'b') + ' × (score − 50)'),
      cal.n ? ' (fitted on ' + cal.n.toLocaleString() + ' region-months' + (cal.r2 !== null && cal.r2 !== undefined ? ', R² = ' + cal.r2.toFixed(2) : '') + '). ' : '. ',
      'Forecasts are capped at ±25%. This is a simple statistical model, not investment advice – compare it with Zillow’s own 1-year forecast, shown alongside.'),

    h('h2', null, 'Long-Term Growth Score'),
    h('p', null, 'Percentile rank versus all regions of the same type today (ZIP codes use their county’s demographic data):'),
    factorTable(m.longterm_factors || {}),
    h('h2', null, 'Investor Score'),
    factorTable(m.investor_factors || {}),
    h('p', { style: { marginTop: '10px' } }, h('b', null, 'Cap rate (est.)'), ' = annual Zillow rent × (1 − ', String(a.expense_ratio_pct), '% expenses) ÷ home value. ',
      h('b', null, 'Gross yield'), ' = annual rent ÷ value. ', h('b', null, 'Buy vs Rent Premium'), ' = (house payment − rent) ÷ rent.'),

    h('h2', null, 'Supply'),
    h('ul', null,
      h('li', null, h('b', null, 'Building permits'), ' are county totals from the Census Building Permits Survey, summed to metros/states. The latest year is a trailing-12-month total' + (m.permits_label ? ' (' + m.permits_label + ')' : '') + '.'),
      h('li', null, h('b', null, 'Inventory as % of Houses'), ' = Realtor.com active listings ÷ ACS housing units.'),
      h('li', null, h('b', null, 'Shadow inventory %'), ' = ACS “other vacant” homes (vacant but not for sale, rent or seasonal use) ÷ housing units.')),

    h('h2', null, 'Map colors'),
    h('p', null, 'Levels use 7 quantile classes on a single-hue ramp (red ramp when higher is a warning sign, like price cuts). Changes use a diverging blue ↔ red scale centered on zero; blue means “supportive of prices” and red “pressure on prices” for that metric. Gray = no data.'),

    h('h2', null, 'Attribution'),
    h('p', null, 'Data: Zillow Research (ZHVI, ZORI, ZHVF and market metrics), Realtor.com Economic Research, Redfin Data Center (a national real estate brokerage), U.S. Census Bureau (ACS, Population Estimates, Building Permits, boundaries), Bureau of Economic Analysis, Bureau of Labor Statistics, Federal Housing Finance Agency, FRED (Federal Reserve Bank of St. Louis) and Freddie Mac. Basemap © OpenStreetMap contributors © CARTO. Each provider’s terms apply; this app is for personal research.'));
  return null;
}
