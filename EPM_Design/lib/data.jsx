// Shared mock data for all three directions.
// Realistic-ish numbers; nothing live.

const INDICES = [
  { sym: 'S&P 500',    val: '5,247.18', chg: '+18.42',  pct: '+0.35%', up: true },
  { sym: 'NASDAQ',     val: '18,342.91',chg: '+92.11',  pct: '+0.51%', up: true },
  { sym: 'DOW',        val: '42,187.33',chg: '-44.07',  pct: '-0.10%', up: false },
  { sym: 'RUSSELL 2K', val: '2,198.55', chg: '+6.12',   pct: '+0.28%', up: true },
  { sym: 'VIX',        val: '14.22',    chg: '-0.38',   pct: '-2.60%', up: false },
  { sym: 'US 10Y',     val: '4.218%',   chg: '-0.021',  pct: '-0.50%', up: false },
  { sym: 'DXY',        val: '104.31',   chg: '+0.14',   pct: '+0.13%', up: true },
  { sym: 'GOLD',       val: '2,384.40', chg: '+11.20',  pct: '+0.47%', up: true },
  { sym: 'WTI',        val: '78.92',    chg: '-0.61',   pct: '-0.77%', up: false },
  { sym: 'BTC',        val: '68,412',   chg: '+1,284',  pct: '+1.91%', up: true },
];

const MOVERS_UP = [
  { sym: 'NVDA', name: 'NVIDIA Corp',          price: '918.42', pct: '+4.82%' },
  { sym: 'AVGO', name: 'Broadcom Inc',         price: '1,412.10', pct: '+3.91%' },
  { sym: 'AMD',  name: 'Advanced Micro',       price: '172.08', pct: '+3.44%' },
  { sym: 'SMCI', name: 'Super Micro',          price: '812.55', pct: '+3.12%' },
  { sym: 'MU',   name: 'Micron Technology',    price: '118.30', pct: '+2.88%' },
];
const MOVERS_DN = [
  { sym: 'TSLA', name: 'Tesla Inc',            price: '172.14', pct: '-3.21%' },
  { sym: 'BA',   name: 'Boeing Co',            price: '182.45', pct: '-2.74%' },
  { sym: 'PFE',  name: 'Pfizer Inc',           price: '26.18',  pct: '-2.11%' },
  { sym: 'INTC', name: 'Intel Corp',           price: '34.62',  pct: '-1.92%' },
  { sym: 'XOM',  name: 'Exxon Mobil',          price: '118.04', pct: '-1.44%' },
];

const HEADLINES = [
  { kicker: 'MACRO',     t: 'Fed minutes signal patience on cuts as services inflation stays sticky', src: 'EPM Research', time: '14m' },
  { kicker: 'EQUITIES',  t: 'Semiconductor rally broadens as hyperscaler capex guidance firms up',    src: 'Bloomberg',    time: '37m' },
  { kicker: 'FIXED INC', t: 'Ten-year yield retreats below 4.25% after softer retail sales',          src: 'Reuters',      time: '1h' },
  { kicker: 'COMMODITY', t: 'Gold pushes toward $2,400 on dollar weakness and ETF inflows',           src: 'WSJ',          time: '2h' },
  { kicker: 'CREDIT',    t: 'IG spreads tighten 4bps; issuers front-load supply ahead of CPI',        src: 'EPM Research', time: '3h' },
  { kicker: 'FX',        t: 'Yen firms as intervention chatter returns around 154 handle',            src: 'FT',           time: '4h' },
];

const FORECASTS = [
  { metric: 'US Real GDP, Q2 2026',   consensus: '2.10%',  epm: '2.35%', delta: '+25bp', conf: 'High' },
  { metric: 'Core PCE, YoY Dec 2026', consensus: '2.60%',  epm: '2.45%', delta: '-15bp', conf: 'High' },
  { metric: 'Fed Funds, YE 2026',     consensus: '4.25%',  epm: '4.00%', delta: '-25bp', conf: 'Med'  },
  { metric: 'S&P 500 EPS, 2026',      consensus: '$271',   epm: '$278',  delta: '+2.6%', conf: 'Med'  },
  { metric: 'Brent, Q4 2026 avg',     consensus: '$82',    epm: '$76',   delta: '-7.3%', conf: 'Low'  },
  { metric: 'EUR/USD, YE 2026',       consensus: '1.09',   epm: '1.12',  delta: '+2.8%', conf: 'Med'  },
];

const PORTFOLIOS = [
  { name: 'Core Balanced',         strat: '60/40 Global',      ytd: '+7.84%', oneYr: '+12.11%', risk: 'Moderate',     sharpe: '0.82' },
  { name: 'Strategic Growth',      strat: 'Equity Tilt',       ytd: '+11.42%',oneYr: '+18.30%', risk: 'Mod–Aggr',     sharpe: '0.91' },
  { name: 'Income & Preservation', strat: 'Fixed + Dividend',  ytd: '+3.92%', oneYr: '+6.44%',  risk: 'Conservative', sharpe: '0.74' },
  { name: 'Global Opportunities',  strat: 'Multi-Asset Intl',  ytd: '+9.10%', oneYr: '+14.82%', risk: 'Moderate',     sharpe: '0.86' },
  { name: 'Thematic: AI & Infra',  strat: 'Concentrated Eq',   ytd: '+18.72%',oneYr: '+31.04%', risk: 'Aggressive',   sharpe: '1.02' },
];

const FUNDS = [
  { ticker: 'VTSAX', name: 'Vanguard Total Stock Mkt Idx',   cat: 'Large Blend',    aum: '$1.6T', er: '0.04%', ytd: '+8.12%', oneYr: '+14.22%', stars: 5 },
  { ticker: 'FXAIX', name: 'Fidelity 500 Index',             cat: 'Large Blend',    aum: '$512B', er: '0.02%', ytd: '+8.05%', oneYr: '+14.18%', stars: 5 },
  { ticker: 'SWPPX', name: 'Schwab S&P 500 Index',           cat: 'Large Blend',    aum: '$94B',  er: '0.02%', ytd: '+8.03%', oneYr: '+14.15%', stars: 5 },
  { ticker: 'VWELX', name: 'Vanguard Wellington',            cat: 'Allocation 50-70',aum: '$115B', er: '0.26%', ytd: '+6.40%', oneYr: '+11.92%', stars: 4 },
  { ticker: 'PRGFX', name: 'T. Rowe Price Growth Stock',     cat: 'Large Growth',   aum: '$58B',  er: '0.65%', ytd: '+10.80%',oneYr: '+17.44%', stars: 3 },
  { ticker: 'DODGX', name: 'Dodge & Cox Stock',              cat: 'Large Value',    aum: '$101B', er: '0.51%', ytd: '+5.12%', oneYr: '+11.08%', stars: 4 },
  { ticker: 'AGTHX', name: 'American Funds Growth Fund',     cat: 'Large Growth',   aum: '$280B', er: '0.62%', ytd: '+9.94%', oneYr: '+16.12%', stars: 4 },
];

const SECTORS = [
  { name: 'Info Tech',      pct: '+1.82%', up: true  },
  { name: 'Comm Services',  pct: '+1.14%', up: true  },
  { name: 'Cons Discr',     pct: '+0.62%', up: true  },
  { name: 'Financials',     pct: '+0.18%', up: true  },
  { name: 'Industrials',    pct: '-0.04%', up: false },
  { name: 'Health Care',    pct: '-0.22%', up: false },
  { name: 'Cons Staples',   pct: '-0.41%', up: false },
  { name: 'Utilities',      pct: '-0.58%', up: false },
  { name: 'Real Estate',    pct: '-0.71%', up: false },
  { name: 'Materials',      pct: '-0.88%', up: false },
  { name: 'Energy',         pct: '-1.12%', up: false },
];

Object.assign(window, { INDICES, MOVERS_UP, MOVERS_DN, HEADLINES, FORECASTS, PORTFOLIOS, FUNDS, SECTORS });
