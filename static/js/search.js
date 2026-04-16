const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");
const searchForm = document.getElementById("globalSearchForm") || document.getElementById("searchForm");
// Prefer the page-level #tickerInput (search.html); fall back to the topbar
// #globalTickerInput on pages that embed the global search form without a dedicated bar.
const tickerInput = document.getElementById("tickerInput") || document.getElementById("globalTickerInput");
const includeNewsInput = document.getElementById("globalIncludeNews") || document.getElementById("includeNews");
const runBtn = document.getElementById("globalSearchBtn") || document.getElementById("runBtn");
const expandChartBtn = document.getElementById("expandChartBtn");
const chartModal = document.getElementById("chartModal");
const closeModalBtn = document.getElementById("closeModalBtn") || document.getElementById("closeModalX");
const periodSelect = document.getElementById("periodSelect");
const customStartDateInput = document.getElementById("customStartDate");
const customEndDateInput = document.getElementById("customEndDate");
const applyDateRangeBtn = document.getElementById("applyDateRangeBtn");
const clearDateRangeBtn = document.getElementById("clearDateRangeBtn");
const suggestionBox = document.getElementById("tickerSuggestions") || document.getElementById("globalTickerSuggestions");
const searchInputStack = document.querySelector(".global-search-input-stack") || document.querySelector(".search-input-stack");

const titleLine = document.getElementById("titleLine");
const summaryText = document.getElementById("summaryText");
const infoTicker = document.getElementById("infoTicker");
const infoName = document.getElementById("infoName");
const infoDescription = document.getElementById("infoDescription");
const topNewsCard = document.getElementById("topNewsCard");
const topNewsSection = document.getElementById("topNewsSection");
const recentNewsSection = document.getElementById("recentNewsSection");
const descriptionModal = document.getElementById("descriptionModal");
const closeDescriptionModalBtn = document.getElementById("closeDescriptionModalBtn");
const descriptionModalCopy = document.getElementById("descriptionModalCopy");
const descriptionModalTitle = document.getElementById("descriptionModalTitle");

const requiredSearchEls = [
  statusEl,
  resultsEl,
  tickerInput,
  includeNewsInput,
  runBtn,
  expandChartBtn,
  chartModal,
  closeModalBtn,
  periodSelect,
  titleLine,
  summaryText,
  infoTicker,
  infoName,
  infoDescription,
  descriptionModalTitle,
];

const searchPageReady = requiredSearchEls.every(Boolean);

let currentFullDescription = "";
let selectedPeriod = "ytd";
let currentChartData = null;
let currentBenchmarkChartData = null;
let currentDisplayChartData = null;
let currentCustomRange = { start: "", end: "" };
let currentSuggestionItems = [];
let activeSuggestionIndex = -1;
let suggestionTimer = null;
let suggestionController = null;
let overlayState = {
  ma20: true,
  ma50: true,
  ma200: true,
  resistance: true,
  support: true,
  volume: false,
};



let headerSummaryCard = null;
let currentSnapshotData = null;
let tickerDock = null;
let tickerDockButton = null;
let tickerDockSymbol = null;
let tickerDockName = null;
let tickerDockMeta = null;
let tickerDockTrendPill = null;
let tickerDockSparkline = null;
let tickerDockPeriodSelect = null;
let tickerDockControls = null;
let dockVisibilityRaf = null;
let tickerDockVisible = false;
let dockTransitionTarget = null;
let dockMorphEl = null;
let dockMorphTimeout = null;
let dockMorphVisibleTimeout = null;
let summaryPulseTimeout = null;
let pendingDockReturnFocus = false;
let dockReturnInFlight = false;
let dockSuppressUntil = 0;
let lastDockButtonRect = null;
let lastDockTargetRect = null;

function fmtNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}
function fmtPct(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
  return `${(Number(value) * 100).toFixed(digits)}%`;
}
function fmtInt(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
  return Number(value).toLocaleString();
}
function fmtMarketCap(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
  const n = Number(value);
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  return `$${n.toLocaleString()}`;
}
function shortText(value, maxLen = 220) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!text) return "No description available.";
  if (text.length <= maxLen) return text;
  return `${text.slice(0, maxLen - 1).trim()}…`;
}
function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
function normalizeTickerValue(value) {
  const raw = String(value ?? "").trim().toUpperCase().replace(/\s+/g, "");
  if (/^[A-Z]{1,5}-[A-Z]$/.test(raw)) return raw.replace("-", ".");
  return raw;
}


function prettifyTrendState(value) {
  if (!value) return "";
  return ({
    strong_uptrend: "Strong uptrend",
    uptrend: "Uptrend",
    mixed: "Mixed",
    downtrend: "Downtrend",
    strong_downtrend: "Strong downtrend",
    unknown: "Unknown",
  }[value] || String(value).replace(/_/g, " "));
}

function getStickyOffsetPx() {
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--search-sticky-top");
  const parsed = Number.parseFloat(raw);
  return Number.isFinite(parsed) ? parsed : 180;
}

function getDockMotionMode() {
  const setting = String(document.body?.dataset?.animations || "").toLowerCase();
  if (setting === "on") return "animated";
  if (setting === "reduced" || setting === "off") return "reduced";
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) return "reduced";
  return "animated";
}

function getTrendTone(value) {
  const trend = String(value || "").toLowerCase();
  if (trend.includes("uptrend")) return "up";
  if (trend.includes("downtrend")) return "down";
  return "flat";
}

function readSearchCache(key, maxAgeMs = 0) {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const ts = Number(parsed?.ts || 0);
    if (maxAgeMs > 0 && ts && (Date.now() - ts > maxAgeMs)) return null;
    return parsed?.value ?? null;
  } catch (_) {
    return null;
  }
}

function writeSearchCache(key, value) {
  try {
    sessionStorage.setItem(key, JSON.stringify({ ts: Date.now(), value }));
  } catch (_) {}
}

function buildSearchCacheKey(kind, ticker, period = '', includeNews = false) {
  return `search_cache_${kind}_${String(ticker || '').trim().toUpperCase()}_${String(period || '').toLowerCase()}_${includeNews ? 'news' : 'plain'}`;
}



function riskWindowKeyForPeriod(period) {
  const value = String(period || '').toLowerCase();
  if (value === '3y') return '3y';
  if (['5y', '10y', 'all'].includes(value)) return '5y';
  return '1y';
}


function labelForPeriod(period) {
  const value = String(period || '').toLowerCase();
  return ({ '5d': '5D', '1m': '1M', '3m': '3M', '6m': '6M', 'ytd': 'YTD', '1y': '1Y', '3y': '3Y', '5y': '5Y', '10y': '10Y', 'all': 'All' })[value] || String(period || '').toUpperCase();
}

function getLatestDefined(values) {
  if (!Array.isArray(values)) return null;
  for (let i = values.length - 1; i >= 0; i -= 1) {
    const num = Number(values[i]);
    if (Number.isFinite(num)) return num;
  }
  return null;
}

function computeSeriesReturn(values) {
  const nums = (values || []).map((v) => Number(v)).filter((v) => Number.isFinite(v));
  if (nums.length < 2 || nums[0] === 0) return null;
  return (nums[nums.length - 1] / nums[0]) - 1;
}

function computeYtdReturnFromChart(chartData) {
  const dates = Array.isArray(chartData?.dates) ? chartData.dates : [];
  const closes = Array.isArray(chartData?.close) ? chartData.close : [];
  if (!dates.length || !closes.length) return null;
  const currentYear = new Date().getFullYear();
  const pairs = [];
  for (let i = 0; i < Math.min(dates.length, closes.length); i += 1) {
    const dt = new Date(dates[i]);
    const close = Number(closes[i]);
    if (Number.isFinite(close) && !Number.isNaN(dt.getTime()) && dt.getFullYear() === currentYear) {
      pairs.push(close);
    }
  }
  return computeSeriesReturn(pairs);
}

function buildClosePairs(chartData) {
  const dates = Array.isArray(chartData?.dates) ? chartData.dates : [];
  const closes = Array.isArray(chartData?.close) ? chartData.close : [];
  const pairs = [];
  for (let i = 0; i < Math.min(dates.length, closes.length); i += 1) {
    const close = Number(closes[i]);
    if (Number.isFinite(close) && close > 0) pairs.push({ date: dates[i], close });
  }
  return pairs;
}

function computeAnnualizedVolatility(chartData) {
  const pairs = buildClosePairs(chartData);
  if (pairs.length < 20) return null;
  const rets = [];
  for (let i = 1; i < pairs.length; i += 1) {
    const prev = pairs[i - 1].close;
    const curr = pairs[i].close;
    if (Number.isFinite(prev) && prev > 0 && Number.isFinite(curr)) rets.push((curr / prev) - 1);
  }
  if (rets.length < 20) return null;
  const mean = rets.reduce((sum, v) => sum + v, 0) / rets.length;
  const variance = rets.reduce((sum, v) => sum + ((v - mean) ** 2), 0) / Math.max(rets.length - 1, 1);
  return Math.sqrt(variance) * Math.sqrt(252);
}

function computeMaxDrawdown(chartData) {
  const pairs = buildClosePairs(chartData);
  if (pairs.length < 2) return null;
  let runningMax = pairs[0].close;
  let maxDrawdown = 0;
  pairs.forEach((point) => {
    runningMax = Math.max(runningMax, point.close);
    if (runningMax > 0) maxDrawdown = Math.min(maxDrawdown, (point.close / runningMax) - 1);
  });
  return maxDrawdown;
}

function computeSharpeRatio(chartData, rfAnnual = 0) {
  const pairs = buildClosePairs(chartData);
  if (pairs.length < 20) return null;
  const rfDaily = rfAnnual / 252;
  const rets = [];
  for (let i = 1; i < pairs.length; i += 1) {
    const prev = pairs[i - 1].close;
    const curr = pairs[i].close;
    if (Number.isFinite(prev) && prev > 0 && Number.isFinite(curr)) rets.push(((curr / prev) - 1) - rfDaily);
  }
  if (rets.length < 20) return null;
  const mean = rets.reduce((sum, v) => sum + v, 0) / rets.length;
  const variance = rets.reduce((sum, v) => sum + ((v - mean) ** 2), 0) / Math.max(rets.length - 1, 1);
  const stdDev = Math.sqrt(variance);
  if (!Number.isFinite(stdDev) || stdDev === 0) return null;
  return (mean / stdDev) * Math.sqrt(252);
}

function computeBetaFromCharts(assetChart, benchmarkChart) {
  const assetPairs = buildClosePairs(assetChart);
  const benchPairs = buildClosePairs(benchmarkChart);
  if (assetPairs.length < 20 || benchPairs.length < 20) return null;

  const benchMap = new Map(benchPairs.map((row) => [row.date, row.close]));
  const aligned = [];
  for (let i = 1; i < assetPairs.length; i += 1) {
    const prevAsset = assetPairs[i - 1];
    const currAsset = assetPairs[i];
    const prevBench = benchMap.get(prevAsset.date);
    const currBench = benchMap.get(currAsset.date);
    if (!Number.isFinite(prevBench) || !Number.isFinite(currBench) || prevBench <= 0) continue;
    aligned.push({ asset: (currAsset.close / prevAsset.close) - 1, bench: (currBench / prevBench) - 1 });
  }
  if (aligned.length < 20) return null;
  const benchMean = aligned.reduce((sum, row) => sum + row.bench, 0) / aligned.length;
  const assetMean = aligned.reduce((sum, row) => sum + row.asset, 0) / aligned.length;
  let cov = 0;
  let varBench = 0;
  aligned.forEach((row) => {
    cov += (row.asset - assetMean) * (row.bench - benchMean);
    varBench += (row.bench - benchMean) ** 2;
  });
  if (aligned.length < 2) return null;
  cov /= (aligned.length - 1);
  varBench /= (aligned.length - 1);
  if (!Number.isFinite(varBench) || varBench === 0) return null;
  return cov / varBench;
}

function sliceChartData(chartData, startDate, endDate) {
  if (!chartData || !Array.isArray(chartData.dates)) return chartData;
  const start = startDate ? new Date(startDate) : null;
  const end = endDate ? new Date(endDate) : null;
  const keepIdx = [];
  chartData.dates.forEach((value, idx) => {
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return;
    if (start && dt < start) return;
    if (end) {
      const endInclusive = new Date(end);
      endInclusive.setHours(23, 59, 59, 999);
      if (dt > endInclusive) return;
    }
    keepIdx.push(idx);
  });
  if (keepIdx.length < 2) return chartData;
  const sliceField = (field) => {
    const arr = Array.isArray(chartData?.[field]) ? chartData[field] : [];
    return keepIdx.map((idx) => arr[idx] ?? null);
  };
  const sliced = {
    ...chartData,
    dates: keepIdx.map((idx) => chartData.dates[idx]),
    close: sliceField('close'),
    ma20: sliceField('ma20'),
    ma50: sliceField('ma50'),
    ma200: sliceField('ma200'),
    volume: sliceField('volume'),
  };
  const closeNums = sliced.close.map((v) => Number(v)).filter((v) => Number.isFinite(v));
  sliced.resistance = closeNums.length ? Math.max(...closeNums) : chartData.resistance;
  sliced.support = closeNums.length ? Math.min(...closeNums) : chartData.support;
  return sliced;
}

function buildTrendMetricsFromChart(chartData) {
  const lastPrice = getLatestDefined(chartData?.close);
  const ma50 = getLatestDefined(chartData?.ma50);
  const ma200 = getLatestDefined(chartData?.ma200);
  let trendState = 'unknown';
  if (Number.isFinite(lastPrice) && Number.isFinite(ma50) && Number.isFinite(ma200)) {
    if (lastPrice > ma50 && ma50 > ma200) trendState = 'strong_uptrend';
    else if (lastPrice > ma200 && ma50 > ma200) trendState = 'uptrend';
    else if (lastPrice < ma50 && ma50 < ma200) trendState = 'strong_downtrend';
    else if (lastPrice < ma200) trendState = 'downtrend';
    else trendState = 'mixed';
  }
  return {
    ma50,
    ma200,
    priceVsMa50: Number.isFinite(lastPrice) && Number.isFinite(ma50) && ma50 !== 0 ? (lastPrice / ma50) - 1 : null,
    priceVsMa200: Number.isFinite(lastPrice) && Number.isFinite(ma200) && ma200 !== 0 ? (lastPrice / ma200) - 1 : null,
    trendState,
  };
}

function syncDockPeriodSelect() {
  if (!tickerDockPeriodSelect || !periodSelect) return;
  tickerDockPeriodSelect.value = periodSelect.value;
}

function getActiveChartData() {
  return currentDisplayChartData || currentChartData;
}

function alignRangeToAvailableDates(dates, startDate, endDate) {
  const parsed = (dates || []).map((value) => ({ raw: value, dt: new Date(value) }))
    .filter((item) => !Number.isNaN(item.dt.getTime()));
  if (!parsed.length) return { start: startDate || '', end: endDate || '' };

  let start = startDate ? new Date(startDate) : null;
  let end = endDate ? new Date(endDate) : null;
  if (end) end.setHours(23, 59, 59, 999);

  let alignedStart = startDate || '';
  let alignedEnd = endDate || '';

  if (start) {
    const nextOpen = parsed.find((item) => item.dt >= start);
    alignedStart = (nextOpen || parsed[0]).raw;
  }
  if (end) {
    const reversed = [...parsed].reverse();
    const prevOpen = reversed.find((item) => item.dt <= end);
    alignedEnd = (prevOpen || parsed[parsed.length - 1]).raw;
  }

  if (alignedStart && alignedEnd && new Date(alignedStart) > new Date(alignedEnd)) {
    const firstValid = parsed.find((item) => item.dt >= new Date(alignedStart));
    alignedEnd = (firstValid || parsed[parsed.length - 1]).raw;
  }

  return { start: alignedStart, end: alignedEnd };
}

function shouldShowDockPeriodControl() {
  if (!tickerDockVisible || !tickerDockControls || !periodSelect || resultsEl?.classList.contains("hidden")) return false;
  const rect = periodSelect.getBoundingClientRect();
  const threshold = getStickyOffsetPx() + 8;
  return rect.bottom <= threshold;
}

function syncDockControlsVisibility() {
  if (!tickerDockControls) return;
  tickerDockControls.classList.toggle('is-hidden', !shouldShowDockPeriodControl());
}

function renderReturnsCard(snapshot, chartData) {
  const customActive = !!(currentCustomRange.start || currentCustomRange.end);
  const selectedLabel = customActive ? 'Custom Range Return' : `${labelForPeriod(selectedPeriod)} Return`;
  const selectedValue = computeSeriesReturn(chartData?.close || []);
  renderKV('returnsCard', [
    [selectedLabel, fmtPct(selectedValue)],
    ['YTD Return', fmtPct(snapshot?.returns?.return_ytd ?? computeYtdReturnFromChart(currentChartData))],
    ['1Y Return', fmtPct(snapshot?.returns?.return_1y)],
    ['3Y Return', fmtPct(snapshot?.returns?.return_3y)],
    ['5Y Return', fmtPct(snapshot?.returns?.return_5y)],
    ['All Return', fmtPct(snapshot?.returns?.return_all)],
  ]);
}

function renderTrendCard(chartData) {
  const metrics = buildTrendMetricsFromChart(chartData || currentChartData || {});
  renderKV('trendCard', [
    ['MA 50', Number.isFinite(metrics.ma50) ? `$${fmtNumber(metrics.ma50)}` : 'N/A'],
    ['MA 200', Number.isFinite(metrics.ma200) ? `$${fmtNumber(metrics.ma200)}` : 'N/A'],
    ['Price vs MA50', fmtPct(metrics.priceVsMa50)],
    ['Price vs MA200', fmtPct(metrics.priceVsMa200)],
    ['Trend State', prettifyTrendState(metrics.trendState) || 'Unknown'],
  ]);
}

function applyDateRangeView() {
  const aligned = alignRangeToAvailableDates(currentChartData?.dates || [], customStartDateInput?.value || '', customEndDateInput?.value || '');
  currentCustomRange = { start: aligned.start, end: aligned.end };
  if (customStartDateInput) customStartDateInput.value = aligned.start || '';
  if (customEndDateInput) customEndDateInput.value = aligned.end || '';
  currentDisplayChartData = sliceChartData(currentChartData, currentCustomRange.start, currentCustomRange.end);
  const chartForView = getActiveChartData();
  const benchmarkForView = sliceChartData(currentBenchmarkChartData, currentCustomRange.start, currentCustomRange.end);
  if (chartForView) {
    renderChart(chartForView, 'chart');
    renderTrendCard(chartForView);
    renderReturnsCard(currentSnapshotData, chartForView);
    renderRiskCard(currentSnapshotData, chartForView, benchmarkForView);
  }
}

function renderRiskCard(snapshot, chartData = null, benchmarkChart = null) {
  const key = riskWindowKeyForPeriod(selectedPeriod);
  const riskWindow = snapshot?.risk_windows?.[key] || snapshot?.risk || {};
  const suffix = (currentCustomRange.start || currentCustomRange.end) ? 'CUSTOM' : labelForPeriod(selectedPeriod);
  const viewChart = chartData || getActiveChartData() || currentChartData;
  const viewBenchmark = benchmarkChart || currentBenchmarkChartData;
  const computedVol = computeAnnualizedVolatility(viewChart);
  const computedDrawdown = computeMaxDrawdown(viewChart);
  const computedSharpe = computeSharpeRatio(viewChart);
  const computedBeta = computeBetaFromCharts(viewChart, viewBenchmark);
  renderKV('riskCard', [
    [`Volatility (${suffix})`, fmtPct(computedVol ?? riskWindow[`volatility_${key}`] ?? riskWindow.volatility_1y)],
    [`Max Drawdown (${suffix})`, fmtPct(computedDrawdown ?? riskWindow[`max_drawdown_${key}`] ?? riskWindow.max_drawdown_1y)],
    [`Sharpe (${suffix})`, fmtNumber(computedSharpe ?? riskWindow[`sharpe_${key}`] ?? riskWindow.sharpe_1y)],
    [`Beta (${suffix})`, fmtNumber(computedBeta ?? riskWindow[`beta_${key}`] ?? riskWindow.beta_1y)],
  ]);
}

function buildSparklineSvg(values, tone = "flat", width = 118, height = 44) {
  const points = values
    .map((n) => Number(n))
    .filter((n) => Number.isFinite(n));

  if (points.length < 2) return "";

  const min = Math.min(...points);
  const max = Math.max(...points);
  const pad = 3;
  const xDenom = Math.max(points.length - 1, 1);
  const yRange = max - min || 1;

  const coords = points.map((value, idx) => {
    const x = pad + ((width - pad * 2) * idx) / xDenom;
    const y = height - pad - ((height - pad * 2) * (value - min)) / yRange;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");

  return `
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" class="ticker-dock-spark ticker-dock-spark--${tone}">
      <polyline points="${coords}" fill="none" />
    </svg>
  `;
}

function renderDockSparkline(chartData, trendState = "") {
  if (!tickerDockSparkline) return;
  const closes = Array.isArray(chartData?.close) ? chartData.close : [];
  const numericCloses = closes.map((n) => Number(n)).filter((n) => Number.isFinite(n));
  if (numericCloses.length < 2) {
    tickerDockSparkline.classList.add("hidden");
    tickerDockSparkline.innerHTML = "";
    return;
  }

  const tone = getTrendTone(trendState) === "flat"
    ? (numericCloses[numericCloses.length - 1] >= numericCloses[0] ? "up" : "down")
    : getTrendTone(trendState);

  tickerDockSparkline.classList.remove("hidden");
  tickerDockSparkline.innerHTML = buildSparklineSvg(numericCloses, tone);
}

function ensureTickerDock() {
  if (tickerDock) return tickerDock;
  const pageShell = document.querySelector(".page-shell");
  if (!pageShell) return null;

  tickerDock = document.createElement("div");
  tickerDock.id = "tickerDock";
  tickerDock.className = "ticker-dock";
  tickerDock.setAttribute("aria-hidden", "true");

  tickerDockButton = document.createElement("button");
  tickerDockButton.type = "button";
  tickerDockButton.className = "ticker-dock-button";
  tickerDockButton.setAttribute("aria-label", "Jump back to ticker summary");

  tickerDockSymbol = document.createElement("span");
  tickerDockSymbol.className = "ticker-dock-symbol";
  tickerDockSymbol.textContent = "---";

  const copy = document.createElement("span");
  copy.className = "ticker-dock-copy";

  const topline = document.createElement("span");
  topline.className = "ticker-dock-topline";

  tickerDockName = document.createElement("span");
  tickerDockName.className = "ticker-dock-name";
  tickerDockName.textContent = "Ticker snapshot";

  tickerDockTrendPill = document.createElement("span");
  tickerDockTrendPill.className = "ticker-dock-trend-pill trend-pill trend-pill--flat";
  tickerDockTrendPill.textContent = "Trend";

  tickerDockMeta = document.createElement("span");
  tickerDockMeta.className = "ticker-dock-meta";
  tickerDockMeta.textContent = "Scroll to return to full header";

  tickerDockSparkline = document.createElement("span");
  tickerDockSparkline.className = "ticker-dock-sparkline hidden";
  tickerDockSparkline.setAttribute("aria-hidden", "true");

  topline.appendChild(tickerDockName);
  topline.appendChild(tickerDockTrendPill);
  copy.appendChild(topline);
  copy.appendChild(tickerDockMeta);

  tickerDockButton.appendChild(tickerDockSymbol);
  tickerDockButton.appendChild(copy);
  tickerDockButton.appendChild(tickerDockSparkline);

  tickerDockPeriodSelect = document.createElement('select');
  tickerDockPeriodSelect.className = 'ticker-dock-period-select';
  tickerDockPeriodSelect.innerHTML = periodSelect ? periodSelect.innerHTML : '';

  tickerDockControls = document.createElement('div');
  tickerDockControls.className = 'ticker-dock-controls is-hidden';
  tickerDockControls.appendChild(tickerDockPeriodSelect);

  tickerDock.appendChild(tickerDockButton);
  tickerDock.appendChild(tickerDockControls);
  pageShell.appendChild(tickerDock);

  tickerDockButton.addEventListener("click", () => {
    if (!headerSummaryCard) return;
    pendingDockReturnFocus = true;
    dockReturnInFlight = true;
    dockSuppressUntil = Date.now() + 520;
    setDockVisibleImmediate(false);

    const targetRect = headerSummaryCard.getBoundingClientRect();
    const absoluteTop = window.scrollY + targetRect.top;
    const targetY = Math.max(0, absoluteTop - getStickyOffsetPx() - 8);

    window.scrollTo({ top: targetY, behavior: getDockMotionMode() === 'animated' ? 'smooth' : 'auto' });
    window.setTimeout(() => {
      pendingDockReturnFocus = false;
      dockReturnInFlight = false;
      scheduleDockVisibilityCheck();
      flashSummaryReturn();
    }, getDockMotionMode() === "animated" ? 420 : 40);
  });

  return tickerDock;
}

function ensureDockMorph() {
  if (dockMorphEl) return dockMorphEl;
  dockMorphEl = document.createElement("div");
  dockMorphEl.className = "ticker-dock-morph hidden";
  dockMorphEl.setAttribute("aria-hidden", "true");
  document.body.appendChild(dockMorphEl);
  return dockMorphEl;
}

function isUsableRect(rect) {
  return !!rect && rect.width > 8 && rect.height > 8;
}

function getSummaryMorphTargetRect() {
  if (!headerSummaryCard) return null;
  const cardRect = headerSummaryCard.getBoundingClientRect();
  if (!isUsableRect(cardRect)) return null;
  return cardRect;
}

function getSummaryLandingRect() {
  if (!headerSummaryCard) return null;
  const rect = headerSummaryCard.getBoundingClientRect();
  if (!isUsableRect(rect)) return null;
  const top = Math.max(getStickyOffsetPx(), 24);
  return {
    left: rect.left,
    top,
    width: rect.width,
    height: rect.height,
    right: rect.left + rect.width,
    bottom: top + rect.height,
  };
}

function runReturnMorph(fromRect, toRect = null) {
  if (getDockMotionMode() === "reduced") {
    flashSummaryReturn();
    return;
  }
  const morph = ensureDockMorph();
  const targetRect = toRect || getSummaryLandingRect() || getSummaryMorphTargetRect();
  if (!isUsableRect(fromRect) || !isUsableRect(targetRect) || !morph) {
    flashSummaryReturn();
    return;
  }
  if (dockMorphTimeout) clearTimeout(dockMorphTimeout);
  if (dockMorphVisibleTimeout) clearTimeout(dockMorphVisibleTimeout);
  morph.classList.remove("hidden", "ticker-dock-morph--show", "ticker-dock-morph--hide");
  morph.dataset.direction = "hide";
  morph.style.opacity = "0.98";
  morph.style.left = `${fromRect.left}px`;
  morph.style.top = `${fromRect.top}px`;
  morph.style.width = `${fromRect.width}px`;
  morph.style.height = `${fromRect.height}px`;
  morph.style.borderRadius = "16px";
  void morph.offsetWidth;
  morph.classList.add("ticker-dock-morph--hide");
  requestAnimationFrame(() => {
    morph.style.left = `${targetRect.left}px`;
    morph.style.top = `${targetRect.top}px`;
    morph.style.width = `${targetRect.width}px`;
    morph.style.height = `${targetRect.height}px`;
    morph.style.borderRadius = "18px";
    morph.style.opacity = "0.24";
  });
  dockMorphTimeout = window.setTimeout(() => {
    morph.classList.add("hidden");
    morph.classList.remove("ticker-dock-morph--show", "ticker-dock-morph--hide");
    flashSummaryReturn();
    dockMorphTimeout = null;
    dockMorphVisibleTimeout = null;
  }, 360);
}

let dockAnimationTimeout = null;

function setDockVisibleImmediate(visible) {
  ensureTickerDock();
  const show = !!visible;
  tickerDockVisible = show;
  dockTransitionTarget = null;
  if (dockAnimationTimeout) {
    clearTimeout(dockAnimationTimeout);
    dockAnimationTimeout = null;
  }
  document.body.classList.toggle("ticker-dock-visible", show);
  if (tickerDock) {
    tickerDock.setAttribute("aria-hidden", show ? "false" : "true");
    tickerDock.classList.toggle("is-visible", show);
    tickerDock.classList.toggle("is-hidden", !show);
    tickerDock.classList.remove("is-entering", "is-leaving");
  }
  if (!show && tickerDockControls) tickerDockControls.classList.add('is-hidden');
  syncDockControlsVisibility();
}

function flashSummaryReturn() {
  if (!headerSummaryCard) return;
  if (summaryPulseTimeout) clearTimeout(summaryPulseTimeout);
  headerSummaryCard.classList.remove("summary-dock-target");
  void headerSummaryCard.offsetWidth;
  headerSummaryCard.classList.add("summary-dock-target");
  summaryPulseTimeout = window.setTimeout(() => {
    headerSummaryCard?.classList.remove("summary-dock-target");
    summaryPulseTimeout = null;
  }, 260);
}

function animateDockVisibility(show) {
  ensureTickerDock();
  if (!tickerDock) {
    setDockVisibleImmediate(show);
    return;
  }

  const next = !!show;
  const effective = dockTransitionTarget ?? tickerDockVisible;
  if (next === effective) {
    syncDockControlsVisibility();
    return;
  }

  if (dockAnimationTimeout) {
    clearTimeout(dockAnimationTimeout);
    dockAnimationTimeout = null;
  }

  dockTransitionTarget = next;
  const reduced = getDockMotionMode() === "reduced";
  if (reduced) {
    setDockVisibleImmediate(next);
    return;
  }

  if (next) {
    tickerDockVisible = true;
    document.body.classList.add("ticker-dock-visible");
    tickerDock.setAttribute("aria-hidden", "false");
    tickerDock.classList.remove("is-hidden", "is-leaving");
    void tickerDock.offsetWidth;
    tickerDock.classList.add("is-visible", "is-entering");
    syncDockControlsVisibility();
    dockAnimationTimeout = window.setTimeout(() => {
      tickerDock?.classList.remove("is-entering");
      dockTransitionTarget = null;
      syncDockControlsVisibility();
      dockAnimationTimeout = null;
    }, 420);
    return;
  }

  // Remove is-visible immediately so the CSS opacity transition (0→1 reverse) fires
  // at the same time as the leave slide animation, rather than after it.
  tickerDock.classList.remove("is-entering", "is-visible");
  tickerDock.classList.add("is-leaving");
  document.body.classList.remove("ticker-dock-visible");
  tickerDock.setAttribute("aria-hidden", "true");
  if (tickerDockControls) tickerDockControls.classList.add('is-hidden');
  dockAnimationTimeout = window.setTimeout(() => {
    tickerDockVisible = false;
    dockTransitionTarget = null;
    tickerDock?.classList.add("is-hidden");
    tickerDock?.classList.remove("is-leaving");
    if (pendingDockReturnFocus) {
      flashSummaryReturn();
      pendingDockReturnFocus = false;
    }
    dockAnimationTimeout = null;
  }, 320);
}

function updateTickerDockData(snapshot) {
  if (!snapshot) return;
  currentSnapshotData = snapshot;
  ensureTickerDock();
  if (!tickerDock) return;

  const ticker = snapshot.ticker || "---";
  const name = snapshot.name || "Unknown Name";
  const price = snapshot.price?.last_price != null ? `$${fmtNumber(snapshot.price.last_price)}` : "Price N/A";
  const trendLabel = prettifyTrendState(snapshot.trend?.trend_state) || "Trend N/A";
  const trendTone = getTrendTone(snapshot.trend?.trend_state);

  tickerDockSymbol.textContent = ticker;
  tickerDockName.textContent = name;
  tickerDockName.title = name;
  tickerDockMeta.textContent = `${price} • ${labelForPeriod(selectedPeriod)} • Click to expand`;
  tickerDockTrendPill.textContent = trendLabel;
  tickerDockTrendPill.className = `ticker-dock-trend-pill trend-pill trend-pill--${trendTone}`;
  tickerDockButton.title = `${ticker} — ${name}`;
  renderDockSparkline(currentChartData, snapshot.trend?.trend_state);
}

function shouldShowTickerDock() {
  if (!headerSummaryCard || !currentSnapshotData) return false;
  if (resultsEl?.classList.contains("hidden")) return false;
  if (dockReturnInFlight) return false;
  if (Date.now() < dockSuppressUntil) return false;
  const rect = headerSummaryCard.getBoundingClientRect();
  const stickyTop = getStickyOffsetPx();
  // Trigger on rect.bottom (card's bottom edge) rather than rect.top.
  // This fires the dock only once the entire summary card has scrolled past
  // the topbar boundary — much more reliable than checking the top edge,
  // which triggers too early and varies with topbar height changes.
  // stickyTop ≈ topbar.bottom + 8 (set by syncStickyHeaderOffset).
  const showThreshold = stickyTop - 8;   // show once card bottom clears topbar
  const hideThreshold = stickyTop + 52;  // hide with hysteresis (card back in view)
  if (tickerDockVisible) return rect.bottom <= hideThreshold;
  return rect.bottom <= showThreshold;
}

function shouldShowDockPeriodControl() {
  const effectiveDockVisible = dockTransitionTarget ?? tickerDockVisible;
  if (!effectiveDockVisible || !tickerDockControls || !periodSelect || resultsEl?.classList.contains("hidden")) return false;
  const rect = periodSelect.getBoundingClientRect();
  const threshold = getStickyOffsetPx() + 10;
  return rect.top <= threshold;
}

function syncDockControlsVisibility() {
  if (!tickerDockControls) return;
  tickerDockControls.classList.toggle('is-hidden', !shouldShowDockPeriodControl());
}

function updateTickerDockVisibility() {
  animateDockVisibility(shouldShowTickerDock());
}

function scheduleDockVisibilityCheck() {
  if (dockVisibilityRaf) cancelAnimationFrame(dockVisibilityRaf);
  dockVisibilityRaf = requestAnimationFrame(() => {
    updateTickerDockVisibility();
    syncDockControlsVisibility();
    dockVisibilityRaf = null;
  });
}

function toggleNewsSections(show) {

  topNewsSection?.classList.toggle("hidden", !show);
  recentNewsSection?.classList.toggle("hidden", !show);
}

function renderKV(containerId, items) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = items.map(([k, v]) => `<div class="k">${k}</div><div class="v">${v}</div>`).join("");
}

function renderNews(items) {
  const el = document.getElementById("newsCard");
  if (!el) return;

  if (!items || !items.length) {
    el.innerHTML = "<div class='news-item'>No recent news returned.</div>";
    return;
  }

  el.innerHTML = items.map(item => `
    <div class="news-item">
      <div class="news-item-title"><a href="${item.url || "#"}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title || "Untitled")}</a></div>
      <div class="news-meta">${escapeHtml(item.source || "Unknown source")}${item.date ? " • " + escapeHtml(item.date) : ""}</div>
      <div>${escapeHtml(shortText(item.summary || "No summary available.", 220))}</div>
    </div>
  `).join("");
}

function renderTopNews(items) {
  if (!topNewsCard) return;

  if (!items || !items.length) {
    topNewsCard.innerHTML = "<div class='top-news-item'>No recent news returned.</div>";
    return;
  }

  const topItems = items.slice(0, 3);
  topNewsCard.innerHTML = topItems.map(item => `
    <div class="top-news-item">
      <div><a href="${item.url || "#"}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title || "Untitled")}</a></div>
      <div class="top-news-meta">${escapeHtml(item.source || "Unknown source")}${item.date ? " • " + escapeHtml(item.date) : ""}</div>
      <div>${escapeHtml(shortText(item.summary || "No summary available.", 110))}</div>
    </div>
  `).join("");
}

function buildFlatLine(value, length) { return Array.from({ length }, () => value); }

function buildChartTraces(chartData) {
  const theme = document.body.dataset.theme || "dark";
  const closeColor = theme === "light" ? "#1d3963" : "#ffffff";
  const traces = [{ x: chartData.dates, y: chartData.close, type: "scatter", mode: "lines", name: "Close", line: { width: 3, color: closeColor } }];
  if (overlayState.ma20) traces.push({ x: chartData.dates, y: chartData.ma20, type: "scatter", mode: "lines", name: "MA 20", line: { width: 2, color: "#7fb3ff" } });
  if (overlayState.ma50) traces.push({ x: chartData.dates, y: chartData.ma50, type: "scatter", mode: "lines", name: "MA 50", line: { width: 2, color: "#d8b25a" } });
  if (overlayState.ma200) traces.push({ x: chartData.dates, y: chartData.ma200, type: "scatter", mode: "lines", name: "MA 200", line: { width: 2, color: "#7ad3a3" } });
  if (overlayState.resistance && chartData.resistance != null) traces.push({ x: chartData.dates, y: buildFlatLine(chartData.resistance, chartData.dates.length), type: "scatter", mode: "lines", name: "Resistance", line: { width: 2, dash: "dash", color: "#ff8c8c" } });
  if (overlayState.support && chartData.support != null) traces.push({ x: chartData.dates, y: buildFlatLine(chartData.support, chartData.dates.length), type: "scatter", mode: "lines", name: "Support", line: { width: 2, dash: "dot", color: "#78c98b" } });
  if (overlayState.volume) traces.push({ x: chartData.dates, y: chartData.volume, type: "bar", name: "Volume", yaxis: "y2", opacity: 0.22, marker: { color: "#3c76c9" } });
  return traces;
}

function isPhoneChartViewport() {
  return window.innerWidth <= 720;
}

function queuePlotResize(target) {
  if (!window.Plotly || !target) return;
  const run = () => { try { window.Plotly.Plots.resize(target); } catch (e) {} };
  requestAnimationFrame(run);
  setTimeout(run, 120);
  setTimeout(run, 320);
}

function buildChartLayout() {
  const theme = document.body.dataset.theme || "dark";
  const dark = theme !== "light";
  const compact = isPhoneChartViewport();
  const fontFamily = getComputedStyle(document.body).fontFamily || 'Inter, ui-sans-serif, system-ui, sans-serif';
  return {
    autosize: true,
    paper_bgcolor: dark ? "#0f1f3f" : "#ffffff",
    plot_bgcolor: dark ? "#0f1f3f" : "#ffffff",
    font: { family: fontFamily, color: dark ? "#e8eefc" : "#163157" },
    margin: compact ? { l: 38, r: 10, t: 10, b: 34 } : { l: 52, r: 24, t: 18, b: 42 },
    legend: compact ? { orientation: "h", y: 1.08, x: 0, font: { family: fontFamily, size: 10 } } : { orientation: "h", y: 1.12, x: 0, font: { family: fontFamily } },
    showlegend: !compact,
    xaxis: { gridcolor: dark ? "#233b66" : "#d9e3f2", zerolinecolor: dark ? "#233b66" : "#d9e3f2", rangeslider: { visible: false }, tickfont: compact ? { family: fontFamily, size: 10 } : { family: fontFamily }, nticks: compact ? 5 : undefined, automargin: true },
    yaxis: { gridcolor: dark ? "#233b66" : "#d9e3f2", zerolinecolor: dark ? "#233b66" : "#d9e3f2", tickfont: compact ? { family: fontFamily, size: 10 } : { family: fontFamily }, automargin: true },
    yaxis2: { overlaying: "y", side: "right", showgrid: false, visible: false, tickfont: compact ? { family: fontFamily, size: 10 } : { family: fontFamily } },
    hoverlabel: {
      bgcolor: dark ? '#17305c' : '#1d4e98',
      bordercolor: dark ? '#365b97' : '#153d7e',
      align: 'left',
      font: { family: fontFamily, size: compact ? 10 : 12, color: '#ffffff' },
      namelength: -1,
    },
    hovermode: compact ? 'closest' : 'x unified'
  };
}

function renderChart(chartData, targetId) {
  const target = typeof targetId === 'string' ? document.getElementById(targetId) : targetId;
  const compact = isPhoneChartViewport();
  Plotly.newPlot(targetId, buildChartTraces(chartData), buildChartLayout(), {
    responsive: true,
    displaylogo: false,
    displayModeBar: !compact,
    modeBarButtonsToRemove: ["lasso2d", "select2d"],
  }).then(() => queuePlotResize(target));
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, options);
  const data = await res.json();
  if (!res.ok || !data.ok) throw new Error(data.detail || "Request failed");
  return data;
}

async function loadSnapshot(ticker, includeNews) {
  const cacheKey = buildSearchCacheKey('snapshot', ticker, '', includeNews);
  const cached = readSearchCache(cacheKey, 180000);
  if (cached) return cached;
  const data = await fetchJson(`/api/snapshot?ticker=${encodeURIComponent(ticker)}&include_news=${includeNews}`);
  writeSearchCache(cacheKey, data.snapshot);
  return data.snapshot;
}
async function loadChart(ticker, period) {
  const cacheKey = buildSearchCacheKey('chart', ticker, period, false);
  const cached = readSearchCache(cacheKey, 180000);
  if (cached) return cached;
  const data = await fetchJson(`/api/chart?ticker=${encodeURIComponent(ticker)}&period=${encodeURIComponent(period)}`);
  writeSearchCache(cacheKey, data.chart);
  return data.chart;
}
async function loadBenchmarkChart(period) {
  try {
    return await loadChart('SPY', period);
  } catch (err) {
    return null;
  }
}
async function loadFundPage(ticker, period, includeNews) {
  const cacheKey = buildSearchCacheKey('fund_page', ticker, period, includeNews);
  const cached = readSearchCache(cacheKey, 180000);
  if (cached) return cached;
  const data = await fetchJson(`/api/fund-page?ticker=${encodeURIComponent(ticker)}&period=${encodeURIComponent(period)}&include_news=${includeNews}`);
  writeSearchCache(cacheKey, data.payload);
  return data.payload;
}
async function loadSuggestions(query, signal) {
  const data = await fetchJson(`/api/suggest-tickers?q=${encodeURIComponent(query)}&limit=15`, { signal });
  return sanitizeSuggestionResults(
    window.EPMTickerValidation?.filterValidSuggestions?.(data.suggestions || []) || data.suggestions || [],
    query,
  );
}

function sanitizeSuggestionResults(items, query = "") {
  const normalizedQuery = normalizeTickerValue(query).replace(/\./g, "");
  const seen = new Set();
  return [...(items || [])]
    .map((item) => ({
      ticker: normalizeTickerValue(item?.ticker || ""),
      name: String(item?.name || "").trim(),
    }))
    .filter((item) => {
      if (!item.ticker || seen.has(item.ticker)) return false;
      const upperName = item.name.toUpperCase();
      if (item.ticker.length <= 3 && (!item.name || upperName === item.ticker)) return false;
      if (normalizedQuery) {
        const comparableTicker = item.ticker.replace(/\./g, "");
        const comparableName = upperName.replace(/[^A-Z0-9]/g, "");
        if (!comparableTicker.includes(normalizedQuery) && !comparableName.includes(normalizedQuery)) return false;
      }
      seen.add(item.ticker);
      return true;
    });
}

function positionSuggestionOverlay() {
  return;
}

function hideSuggestions() {
  currentSuggestionItems = [];
  activeSuggestionIndex = -1;
  suggestionBox?.classList.add("hidden");
  if (suggestionBox) suggestionBox.innerHTML = "";
}

function updateActiveSuggestion() {
  suggestionBox?.querySelectorAll(".ticker-suggestion").forEach((node, idx) => {
    node.classList.toggle("active", idx === activeSuggestionIndex);
  });
}

function selectSuggestion(item, shouldRun = true) {
  if (!item) return;
  tickerInput.value = normalizeTickerValue(item.ticker);
  hideSuggestions();
  if (shouldRun) runAnalysis();
}

function renderSuggestions(items) {
  currentSuggestionItems = items;
  activeSuggestionIndex = items.length ? 0 : -1;

  if (!suggestionBox || !items.length) {
    hideSuggestions();
    return;
  }

  suggestionBox.innerHTML = items.map((item, idx) => `
    <button class="ticker-suggestion ${idx === 0 ? "active" : ""}" type="button" data-index="${idx}" data-ticker="${escapeHtml(item.ticker)}" data-name="${escapeHtml(item.name)}">
      <span class="ticker-suggestion-symbol">${escapeHtml(item.ticker)}</span>
      <span class="ticker-suggestion-name">${escapeHtml(item.name)}</span>
    </button>
  `).join("");
  suggestionBox.classList.remove("hidden");
}

function queueSuggestions(force = false) {
  if (suggestionTimer) clearTimeout(suggestionTimer);
  suggestionTimer = setTimeout(async () => {
    const query = tickerInput.value.trim();
    if (!force && query.length === 0 && document.activeElement !== tickerInput) {
      hideSuggestions();
      return;
    }
    if (suggestionController) suggestionController.abort();
    suggestionController = new AbortController();
    try {
      const items = await loadSuggestions(query, suggestionController.signal);
      renderSuggestions(items);
    } catch (err) {
      if (err?.name !== "AbortError") hideSuggestions();
    }
  }, force ? 0 : 120);
}

function syncSearchUrl(ticker, includeNews) {
  const params = new URLSearchParams(window.location.search);
  params.set("ticker", String(ticker || "").trim().toUpperCase());
  params.set("news", includeNews ? "1" : "0");
  history.replaceState({}, "", `/search?${params.toString()}`);
}

async function runAnalysis(event) {
  const ticker = tickerInput.value.trim().toUpperCase();
  if (!ticker) {
    statusEl.textContent = "Please enter a ticker.";
    return;
  }

  hideSuggestions();
  syncSearchUrl(ticker, includeNewsInput.checked);
  statusEl.textContent = `Loading ${ticker}...`;
  resultsEl.classList.add("hidden");
  setDockVisibleImmediate(false);

  try {
    const [snapshotResult, chartResult, benchmarkResult, pageResult] = await Promise.allSettled([
      loadSnapshot(ticker, includeNewsInput.checked),
      loadChart(ticker, selectedPeriod),
      loadBenchmarkChart(selectedPeriod),
      loadFundPage(ticker, selectedPeriod, includeNewsInput.checked),
    ]);

    if (snapshotResult.status !== "fulfilled") throw snapshotResult.reason;
    if (chartResult.status !== "fulfilled") throw chartResult.reason;

    const snapshot = snapshotResult.value;
    const chartData = chartResult.value;
    const benchmarkChart = benchmarkResult.status === 'fulfilled' ? benchmarkResult.value : null;
    const pagePayload = pageResult.status === "fulfilled" ? pageResult.value : null;

    currentChartData = chartData;
    currentBenchmarkChartData = benchmarkChart;
    currentDisplayChartData = chartData;
    if (customStartDateInput) customStartDateInput.value = '';
    if (customEndDateInput) customEndDateInput.value = '';
    currentCustomRange = { start: '', end: '' };
    updateTickerDockData(snapshot);
    syncDockPeriodSelect();
    const resolvedName = pagePayload?.security?.name || snapshot.name || snapshot.ticker || "Unknown Name";
    const resolvedDesc = pagePayload?.security?.short_description || pagePayload?.security?.description || pagePayload?.insight_panel?.about || snapshot.short_description || snapshot.description || snapshot.long_description || "No description available yet.";
    titleLine.textContent = `${snapshot.ticker} — ${resolvedName}`;
    summaryText.textContent = pagePayload?.insight_panel?.summary || snapshot.summary || "No summary available.";

    infoTicker.textContent = snapshot.ticker || "N/A";
    infoName.textContent = resolvedName;
    if (descriptionModalTitle) descriptionModalTitle.textContent = resolvedName || snapshot.ticker || "Description";
    const showNews = includeNewsInput.checked;
    toggleNewsSections(showNews);
    const desc = resolvedDesc;
    currentFullDescription = desc;
    infoDescription.textContent = shortText(desc, 220);
    infoDescription.classList.toggle("clickable-description", !!desc && desc.length > 220);

    if (showNews) {
      renderTopNews(pagePayload?.ranked_news || snapshot.news || []);
    } else {
      if (topNewsCard) topNewsCard.innerHTML = "";
    }

    renderKV("priceCard", [
      ["Last Price", snapshot.price?.last_price != null ? `$${fmtNumber(snapshot.price.last_price)}` : "N/A"],
      ["Prev Close", snapshot.price?.prev_close != null ? `$${fmtNumber(snapshot.price.prev_close)}` : "N/A"],
      ["Open", snapshot.price?.open != null ? `$${fmtNumber(snapshot.price.open)}` : "N/A"],
      ["Day High", snapshot.price?.high != null ? `$${fmtNumber(snapshot.price.high)}` : "N/A"],
      ["Day Low", snapshot.price?.low != null ? `$${fmtNumber(snapshot.price.low)}` : "N/A"],
      ["Volume", fmtInt(snapshot.price?.volume)],
      ["52W High", snapshot.price?.year_high != null ? `$${fmtNumber(snapshot.price.year_high)}` : "N/A"],
      ["52W Low", snapshot.price?.year_low != null ? `$${fmtNumber(snapshot.price.year_low)}` : "N/A"],
    ]);

    currentSnapshotData = snapshot;
    renderReturnsCard(snapshot, chartData);
    renderRiskCard(snapshot, chartData, benchmarkChart);
    renderTrendCard(chartData);

    renderKV("fundamentalsCard", [
      ["Sector", snapshot.fundamentals?.sector || "N/A"],
      ["Industry", snapshot.fundamentals?.industry || "N/A"],
      ["Market Cap", fmtMarketCap(snapshot.fundamentals?.market_cap)],
      ["Employees", fmtInt(snapshot.fundamentals?.employees)],
      ["Dividend Yield", snapshot.fundamentals?.dividend_yield != null ? fmtPct(Number(snapshot.fundamentals.dividend_yield)) : "N/A"],
      ["Shares Outstanding", fmtInt(snapshot.fundamentals?.shares_outstanding)],
    ]);

    renderKV("sentimentCard", [
      ["Status", snapshot.sentiment?.status || "N/A"],
      ["Label", snapshot.sentiment?.label || "N/A"],
      ["Score", snapshot.sentiment?.score ?? "N/A"],
    ]);

    if (showNews) {
      renderNews(pagePayload?.ranked_news || snapshot.news || []);
    } else {
      const newsEl = document.getElementById("newsCard");
      if (newsEl) newsEl.innerHTML = "";
    }
    renderChart(getActiveChartData(), "chart");
    window.EPMTickerValidation?.clearInvalidTicker?.(ticker);
    resultsEl.classList.remove("hidden");
    requestAnimationFrame(() => {
      syncStickyHeaderOffset();
      scheduleDockVisibilityCheck();
    });
    statusEl.textContent = `Loaded snapshot for ${ticker}.`;
    window.initDeepAnalysis?.(ticker);
  } catch (err) {
    window.EPMTickerValidation?.markTickerInvalid?.(ticker);
    setDockVisibleImmediate(false);
    statusEl.textContent = `Error: ${err.message}`;
  }
}

function syncStickyHeaderOffset() {
  const topbar = document.querySelector(".topbar");
  const fallback = 110;
  if (!topbar) {
    document.documentElement.style.setProperty("--search-sticky-top", `${fallback}px`);
    return;
  }
  const topCss = parseFloat(getComputedStyle(topbar).top);
  const topOffset = Number.isFinite(topCss) && topCss >= 0 ? topCss : 12;

  if (window.scrollY > 0) {
    // Once scrolled, use the topbar's live viewport bottom edge so the dock
    // sits flush under the sticky topbar. If the topbar has scrolled off-screen
    // (not sticky / not visible), fall back to 8px so the dock docks at the top
    // rather than leaving a gap where the header used to be.
    const bcrBottom = topbar.getBoundingClientRect().bottom;
    const offset = bcrBottom > 0 ? Math.ceil(bcrBottom + 8) : 8;
    document.documentElement.style.setProperty("--search-sticky-top", `${offset}px`);
    return;
  }

  // Before scrolling: BCR.bottom is unreliable because the ticker tape above the
  // topbar inflates it to a large pre-scroll offset. Use offsetHeight + CSS top instead.
  const offset = Math.ceil(topbar.offsetHeight + topOffset + 8);
  document.documentElement.style.setProperty("--search-sticky-top", `${offset}px`);
}

let topbarResizeObserver = null;

function watchTopbarForStickyOffset() {
  const topbar = document.querySelector(".topbar");
  if (!topbar || typeof ResizeObserver === "undefined") return;
  if (topbarResizeObserver) topbarResizeObserver.disconnect();
  topbarResizeObserver = new ResizeObserver(() => syncStickyHeaderOffset());
  topbarResizeObserver.observe(topbar);
}

function openDescriptionModal() {
  if (!descriptionModal || !descriptionModalCopy || !currentFullDescription) return;
  descriptionModalCopy.innerHTML = `<p>${escapeHtml(currentFullDescription)}</p>`;
  descriptionModal.classList.add("active");
}

function closeDescriptionModal() {
  descriptionModal?.classList.remove("active");
}

document.addEventListener("DOMContentLoaded", () => {
  if (!searchPageReady) {
    console.error("Search page DOM mismatch: one or more required elements were not found.");
    if (statusEl) {
      statusEl.textContent = "Search page is out of sync. Please refresh after updating static/search.html.";
    }
    return;
  }

  const initialNewsPref = new URLSearchParams(window.location.search).get("news");
  includeNewsInput.checked = initialNewsPref == null
    ? (localStorage.getItem("epm_include_news_pref") || "true") === "true"
    : initialNewsPref !== "0" && initialNewsPref !== "false";
  toggleNewsSections(includeNewsInput.checked);
  selectedPeriod = "ytd";
  periodSelect.value = selectedPeriod;

  const urlParams = new URLSearchParams(window.location.search);
  const tickerParam = urlParams.get("ticker") || urlParams.get("t");
  if (tickerParam) tickerInput.value = normalizeTickerValue(tickerParam);

  headerSummaryCard = document.getElementById("searchSummaryHeader") || document.querySelector(".sticky-search-header");
  ensureTickerDock();

  syncStickyHeaderOffset();
  watchTopbarForStickyOffset();

  window.addEventListener("load", () => {
    syncStickyHeaderOffset();
    scheduleDockVisibilityCheck();
  });
  window.addEventListener("resize", () => {
    syncStickyHeaderOffset();
    positionSuggestionOverlay();
    scheduleDockVisibilityCheck();
  });
  window.addEventListener("orientationchange", () => {
    syncStickyHeaderOffset();
    positionSuggestionOverlay();
    scheduleDockVisibilityCheck();
  });

  let scrollHideRaf = null;
  window.addEventListener(
    "scroll",
    () => {
      if (scrollHideRaf) cancelAnimationFrame(scrollHideRaf);
      scrollHideRaf = requestAnimationFrame(() => {
        hideSuggestions();
        syncStickyHeaderOffset();
        scheduleDockVisibilityCheck();
      });
    },
    { passive: true }
  );

  document.querySelectorAll(".toggle-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.toggle;
      overlayState[key] = !overlayState[key];
      btn.classList.toggle("active", !!overlayState[key]);
      if (getActiveChartData()) renderChart(getActiveChartData(), "chart");
    });
  });

  periodSelect.addEventListener("change", () => {
    selectedPeriod = periodSelect.value;
    syncDockPeriodSelect();
    if (!resultsEl.classList.contains("hidden")) runAnalysis();
  });

  includeNewsInput.addEventListener("change", () => {
    toggleNewsSections(includeNewsInput.checked);
    localStorage.setItem("epm_include_news_pref", String(includeNewsInput.checked));
    if (!resultsEl.classList.contains("hidden")) runAnalysis();
  });

  searchForm?.addEventListener("submit", runAnalysis);
  runBtn.addEventListener("click", (event) => {
    event.preventDefault();
    runAnalysis();
  });
  tickerInput.addEventListener("input", () => queueSuggestions());
  tickerInput.addEventListener("focus", () => queueSuggestions(true));
  tickerInput.addEventListener("keydown", (e) => {
    const hasSuggestions = currentSuggestionItems.length > 0 && !suggestionBox?.classList.contains("hidden");

    if (e.key === "ArrowDown" && hasSuggestions) {
      e.preventDefault();
      activeSuggestionIndex = (activeSuggestionIndex + 1) % currentSuggestionItems.length;
      updateActiveSuggestion();
      return;
    }

    if (e.key === "ArrowUp" && hasSuggestions) {
      e.preventDefault();
      activeSuggestionIndex = (activeSuggestionIndex - 1 + currentSuggestionItems.length) % currentSuggestionItems.length;
      updateActiveSuggestion();
      return;
    }

    if (e.key === "Escape") {
      hideSuggestions();
      return;
    }

    if (e.key === "Enter") {
      if (hasSuggestions && activeSuggestionIndex >= 0) {
        e.preventDefault();
        selectSuggestion(currentSuggestionItems[activeSuggestionIndex], true);
      } else {
        runAnalysis();
      }
    }
  });

  suggestionBox?.addEventListener("mousedown", (e) => {
    const target = e.target.closest(".ticker-suggestion");
    if (!target) return;
    e.preventDefault();
    const index = Number(target.dataset.index);
    if (Number.isInteger(index) && currentSuggestionItems[index]) {
      selectSuggestion(currentSuggestionItems[index], true);
    }
  });

  document.addEventListener("click", (e) => {
    if (!searchInputStack?.contains(e.target) && !suggestionBox?.contains(e.target)) hideSuggestions();
  });

  tickerDockPeriodSelect?.addEventListener('change', () => {
    selectedPeriod = tickerDockPeriodSelect.value;
    periodSelect.value = selectedPeriod;
    if (!resultsEl.classList.contains('hidden')) runAnalysis();
    scheduleDockVisibilityCheck();
  });

  applyDateRangeBtn?.addEventListener('click', () => {
    applyDateRangeView();
  });

  clearDateRangeBtn?.addEventListener('click', () => {
    if (customStartDateInput) customStartDateInput.value = '';
    if (customEndDateInput) customEndDateInput.value = '';
    currentCustomRange = { start: '', end: '' };
    currentDisplayChartData = currentChartData;
    if (currentChartData) {
      renderChart(currentChartData, 'chart');
      renderTrendCard(currentChartData);
      renderReturnsCard(currentSnapshotData, currentChartData);
      renderRiskCard(currentSnapshotData, currentChartData, currentBenchmarkChartData);
    }
  });

  expandChartBtn.addEventListener("click", () => {
    if (!getActiveChartData()) return;
    chartModal.classList.add("active");
    renderChart(getActiveChartData(), "modalChart");
  });

  closeModalBtn.addEventListener("click", () => {
    chartModal.classList.remove("active");
  });

  chartModal.addEventListener("click", (e) => {
    if (e.target === chartModal) chartModal.classList.remove("active");
  });

  infoDescription?.addEventListener("click", () => {
    if (infoDescription.classList.contains("clickable-description")) openDescriptionModal();
  });

  closeDescriptionModalBtn?.addEventListener("click", closeDescriptionModal);

  descriptionModal?.addEventListener("click", (e) => {
    if (e.target === descriptionModal) closeDescriptionModal();
  });

  window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => {
    if (getActiveChartData()) renderChart(getActiveChartData(), "chart");
  });

  const observer = new MutationObserver(() => {
    if (getActiveChartData()) {
      renderChart(getActiveChartData(), "chart");
      renderDockSparkline(currentChartData, currentSnapshotData?.trend?.trend_state);
    }
    scheduleDockVisibilityCheck();
  });
  observer.observe(document.body, { attributes: true, attributeFilter: ["data-theme", "data-animations"] });

  runAnalysis();
});
