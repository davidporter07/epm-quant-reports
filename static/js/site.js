// ==========================================================================
// FIRST-VISIT SPLASH — shown once per browser session, self-dismisses
// ==========================================================================
(function initFirstVisitSplash() {
  try {
    if (sessionStorage.getItem('epm_splash_shown')) return;
    if (/^\/(login|reset-password)/.test(window.location.pathname)) return;
    sessionStorage.setItem('epm_splash_shown', '1');
    const el = document.createElement('div');
    el.id = 'firstVisitSplash';
    el.className = 'fvs';
    el.innerHTML = `
      <div class="fvs-inner">
        <div class="fvs-logo-wrap">
          <img src="/static/epm_logo_sq.png" class="fvs-logo" alt="EPM" draggable="false" />
          <div class="fvs-logo-ring"></div>
        </div>
        <div class="fvs-name">EPM Market Intelligence</div>
        <div class="fvs-tagline">Loading dashboard&hellip;</div>
        <div class="fvs-bar-shell"><div class="fvs-bar" id="fvsBar"></div></div>
      </div>`;
    document.body.appendChild(el);
    // Remove the synchronous shield now that the proper splash is mounted
    var _shield = document.getElementById('fvsShield');
    if (_shield) _shield.remove();
    // Start progress bar — 3.2s matches CSS transition
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const bar = document.getElementById('fvsBar');
      if (bar) bar.style.width = '100%';
    }));
    // Dismiss after minimum 3.5s OR when page data fires, whichever is later
    const MIN_MS = 3500;
    const shown = Date.now();
    window._fvsDismiss = function () {
      const remaining = MIN_MS - (Date.now() - shown);
      setTimeout(() => {
        // Cross-fade: page fades in as splash fades out (no opacity snap/glitch)
        const shell = document.querySelector('.page-shell');
        if (shell?.animate) {
          shell.animate(
            [{ opacity: 0 }, { opacity: 1 }],
            { duration: 600, delay: 150, easing: 'ease-out', fill: 'both' }
          );
        }
        el.classList.add('fvs-leaving');
        setTimeout(() => el.remove(), 700);
      }, Math.max(0, remaining));
    };
    // Hard fallback: always dismiss after 5s even if data never signals
    setTimeout(() => { if (document.contains(el)) window._fvsDismiss(); }, 5000);
  } catch (_) {}
})();

// ==========================================================================
// AUTH — cookie-based auth state and topbar actions
// Session tokens are stored in an HttpOnly Secure cookie set by the server.
// JS never sees the raw token; cookies are sent automatically by the browser.
// ==========================================================================

// Stubs kept for compatibility with callers that guard on typeof/null checks.
function epmGetToken() { return null; }
function epmAuthHeaders() { return {}; }

async function epmClearToken() {
  // Ask the server to clear the HttpOnly cookie, then wipe cached display data.
  try { await fetch('/api/auth/logout', { method: 'POST' }); } catch (_) {}
  try {
    localStorage.removeItem('epm_username');
    localStorage.removeItem('epm_user_prefs');
  } catch (_) {}
}

/**
 * Non-blocking auth check. Calls /api/auth/me — the HttpOnly cookie is sent
 * automatically by the browser. Uses cached username for optimistic display
 * so gated pages don't flash the sign-in gate during the round-trip.
 */
async function epmCheckAuthState() {
  const cached = localStorage.getItem('epm_username');
  if (cached) _applyAuthState('member', cached);
  try {
    const res = await fetch('/api/auth/me');
    if (res.ok) {
      const data = await res.json();
      if (data?.user?.username) {
        try { localStorage.setItem('epm_username', data.user.username); } catch (_) {}
        try { localStorage.setItem('epm_user_prefs', JSON.stringify(data.prefs || {})); } catch (_) {}
      }
      _applyAuthState('member', data?.user?.username);
    } else {
      await epmClearToken();
      _applyAuthState('guest');
    }
  } catch (_) {
    // Network error — keep optimistic member state if we had a cached username
    if (!cached) _applyAuthState('guest');
  }
}

function _applyAuthState(state, username) {
  document.body.dataset.authState = state;
  // Directly toggle the home-page portfolio watchlist gate
  document.querySelectorAll('.pw-guest-prompt').forEach(el => {
    el.style.display = state === 'member' ? 'none' : '';
  });
  // Update topbar sign-in button vs user badge
  mountAuthActions(state, username || localStorage.getItem('epm_username') || '');
  // On gated pages, trigger data load now that auth state is known
  const page = document.body.dataset.page;
  if (state === 'member' && (page === 'forecasting' || page === 'portfolios')) {
    initPageData();
  }
}

function epmGetCachedPrefs() {
  try {
    const raw = localStorage.getItem('epm_user_prefs');
    return raw ? JSON.parse(raw) : null;
  } catch (_) { return null; }
}

async function epmFetchPrefs() {
  try {
    const res = await fetch('/api/user/prefs');
    if (!res.ok) return null;
    const data = await res.json();
    if (data?.prefs) {
      try { localStorage.setItem('epm_user_prefs', JSON.stringify(data.prefs)); } catch (_) {}
    }
    return data?.prefs || null;
  } catch (_) { return null; }
}

async function epmSavePrefs(prefs) {
  try {
    const res = await fetch('/api/user/prefs', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(prefs),
    });
    if (!res.ok) return false;
    const data = await res.json();
    if (data?.prefs) {
      try { localStorage.setItem('epm_user_prefs', JSON.stringify(data.prefs)); } catch (_) {}
    }
    return true;
  } catch (_) { return false; }
}

// ==========================================================================

const THEME_CHROME = {
  dark: { background: "#061326", themeColor: "#061326" },
  light: { background: "#f5f8fd", themeColor: "#f5f8fd" },
};

function syncThemeChrome(theme) {
  const resolved = theme === "light" ? "light" : "dark";
  const chrome = THEME_CHROME[resolved];
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.backgroundColor = chrome.background;
  if (document.body) document.body.style.backgroundColor = chrome.background;
  const themeMeta = document.getElementById("themeColorMeta") || document.querySelector('meta[name="theme-color"]');
  if (themeMeta) themeMeta.setAttribute("content", chrome.themeColor);
  const statusMeta = document.getElementById("appleStatusBarMeta");
  if (statusMeta) statusMeta.setAttribute("content", resolved === "light" ? "default" : "black-translucent");
}

function mountSafeGlass() {
  document.querySelectorAll('.safe-glass').forEach((node) => node.remove());
}


function mountSettingsGearIcon() {
  document.querySelectorAll('.settings-gear-btn').forEach((btn) => {
    if (btn.dataset.enhanced === 'true') return;
    btn.dataset.enhanced = 'true';
    btn.innerHTML = `
      <span class="settings-gear-wrap" aria-hidden="true">
        <span class="settings-bar settings-bar1"></span>
        <span class="settings-bar settings-bar2"></span>
      </span>
      <span class="sr-only">Settings</span>`;
  });
}

const PREF_KEYS = {
  theme: "epm_theme_pref",
  animations: "epm_animations_pref",
  defaultRange: "epm_default_chart_range",
  includeNews: "epm_include_news_pref",
};

function getPref(key, fallback) { return localStorage.getItem(key) ?? fallback; }
function setPref(key, value) { localStorage.setItem(key, value); }
function getResolvedTheme(themePref) { return themePref === "system" ? (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : themePref; }

function applyPreferences() {
  const themePref = getPref(PREF_KEYS.theme, "dark");
  const resolvedTheme = getResolvedTheme(themePref);
  const animations = getPref(PREF_KEYS.animations, "on");

  syncThemeChrome(resolvedTheme);
  document.body.dataset.theme = resolvedTheme;
  document.body.dataset.themePref = themePref;
  document.body.dataset.animations = animations;

  document.querySelectorAll("[data-pref-theme]").forEach((el) => el.classList.toggle("active", el.dataset.prefTheme === themePref));
  document.querySelectorAll("[data-pref-animations]").forEach((el) => el.classList.toggle("active", el.dataset.prefAnimations === animations));
  const range = getPref(PREF_KEYS.defaultRange, "ytd");
  document.querySelectorAll("[data-pref-range]").forEach((el) => el.classList.toggle("active", el.dataset.prefRange === range));
  const news = getPref(PREF_KEYS.includeNews, "true");
  document.querySelectorAll("[data-pref-news]").forEach((el) => el.classList.toggle("active", el.dataset.prefNews === news));
}

function inferPageKey() {
  const path = window.location.pathname;
  if (path === "/") return "home";
  if (path.startsWith("/markets")) return "markets";
  if (path.startsWith("/forecasting")) return "forecasting";
  if (path.startsWith("/portfolios")) return "portfolios";
  if (path.startsWith("/search")) return "search";
  return "";
}

function setActiveNav() {
  const path = window.location.pathname;
  document.querySelectorAll(".nav-link, .menu-link").forEach((link) => {
    const href = link.getAttribute("href");
    const active = (href === "/" && path === "/") || (href !== "/" && path.startsWith(href));
    link.classList.toggle("active", active);
  });
}

function setupSettingsDrawer() {
  const openBtn = document.getElementById("openSettingsBtn");
  const closeBtn = document.getElementById("closeSettingsBtn");
  const drawer = document.getElementById("settingsDrawer");
  const overlay = document.getElementById("settingsOverlay");
  if (!drawer || !overlay) return;

  const setDrawerState = (open) => {
    drawer.classList.toggle("open", !!open);
    overlay.classList.toggle("show", !!open);
    document.body.classList.toggle('settings-open', !!open);
    openBtn?.classList.toggle('is-active', !!open);
    openBtn?.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) _renderSettingsProfile();
  };

  const close = () => setDrawerState(false);

  openBtn?.setAttribute('aria-expanded', 'false');
  openBtn?.addEventListener("click", () => setDrawerState(!drawer.classList.contains('open')));
  closeBtn?.addEventListener("click", close);
  overlay?.addEventListener("click", close);

  document.querySelectorAll("[data-pref-theme]").forEach((el) => el.addEventListener("click", () => { setPref(PREF_KEYS.theme, el.dataset.prefTheme); applyPreferences(); }));
  document.querySelectorAll("[data-pref-animations]").forEach((el) => el.addEventListener("click", () => { setPref(PREF_KEYS.animations, el.dataset.prefAnimations); applyPreferences(); }));
  document.querySelectorAll("[data-pref-range]").forEach((el) => el.addEventListener("click", () => { setPref(PREF_KEYS.defaultRange, el.dataset.prefRange); applyPreferences(); }));
  document.querySelectorAll("[data-pref-news]").forEach((el) => el.addEventListener("click", () => { setPref(PREF_KEYS.includeNews, el.dataset.prefNews); applyPreferences(); }));
}

function setupSystemThemeListener() {
  window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => {
    if (getPref(PREF_KEYS.theme, "dark") === "system") applyPreferences();
  });
}

function setupChromeEffects() {
  const topbar = document.querySelector('.topbar');
  const page = inferPageKey();
  if (page) document.body.classList.add(`page-${page}`);
  if (!topbar) {
    document.body.classList.add('ui-ready');
    return;
  }

  let rafId = 0;
  const applyState = () => {
    rafId = 0;
    const scrolled = window.scrollY > 18;
    topbar.classList.toggle('is-scrolled', scrolled);
    document.body.classList.toggle('page-scrolled', scrolled);
  };

  const handleScroll = () => {
    if (rafId) return;
    rafId = window.requestAnimationFrame(applyState);
  };

  applyState();
  window.addEventListener('scroll', handleScroll, { passive: true });
  document.body.classList.add('ui-ready');
}

function fmtNumber(value, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return "N/A";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}
function fmtPrice(value) {
  if (value == null || Number.isNaN(Number(value))) return "N/A";
  return `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;
}
function fmtPct(value) {
  if (value == null || Number.isNaN(Number(value))) return "N/A";
  const num = Number(value) * 100;
  return `${num >= 0 ? "+" : ""}${num.toFixed(2)}%`;
}
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
function normalizeTickerValue(value) {
  const raw = String(value ?? "").trim().toUpperCase().replace(/\s+/g, "");
  if (/^[A-Z]{1,5}-[A-Z]$/.test(raw)) return raw.replace("-", ".");
  return raw;
}
function shortText(value, maxLen = 120) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!text) return "Live market card";
  if (text.length <= maxLen) return text;
  return `${text.slice(0, maxLen - 1).trim()}…`;
}
function trendLabel(value) {
  return ({
    strong_uptrend: "Strong uptrend",
    uptrend: "Uptrend",
    mixed: "Mixed",
    downtrend: "Downtrend",
    strong_downtrend: "Strong downtrend",
    unknown: "Unknown",
  })[value] || "Unknown";
}
function trendStateClass(value) {
  return ({ strong_uptrend: "trend-strong-up", uptrend: "trend-up", mixed: "trend-mixed",
            downtrend: "trend-dn", strong_downtrend: "trend-strong-dn" })[value] || "trend-mixed";
}
function deltaClass(value) {
  if (value == null || Number.isNaN(Number(value))) return "flat";
  return Number(value) >= 0 ? "up" : "down";
}
function sparklineClass(card) {
  const visible = card?.sparkline?.close || [];
  if (Array.isArray(visible) && visible.length >= 2) {
    const first = Number(visible[0]);
    const last = Number(visible[visible.length - 1]);
    if (Number.isFinite(first) && first !== 0 && Number.isFinite(last)) {
      return deltaClass((last / first) - 1);
    }
  }
  const basis = card?.return_1m ?? card?.day_change_pct;
  return deltaClass(basis);
}

async function fetchApi(url) {
  const res = await fetch(url);
  const ct = res.headers.get('content-type') || '';
  if (!ct.includes('application/json')) {
    throw new Error(`Server unavailable (${res.status}). Is the backend running?`);
  }
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error(data.detail || "Request failed");
  return data.payload ?? data;
}

function readSessionJson(key, maxAgeMs = 0) {
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

function writeSessionJson(key, value) {
  try {
    sessionStorage.setItem(key, JSON.stringify({ ts: Date.now(), value }));
  } catch (_) {}
}

const INVALID_TICKER_KEY = "epm_invalid_tickers";

function readInvalidTickerSet() {
  try {
    const raw = localStorage.getItem(INVALID_TICKER_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return new Set((Array.isArray(parsed) ? parsed : []).map((value) => String(value || '').trim().toUpperCase()).filter(Boolean));
  } catch (_) {
    return new Set();
  }
}
function writeInvalidTickerSet(values) {
  try {
    localStorage.setItem(INVALID_TICKER_KEY, JSON.stringify(Array.from(values).sort()));
  } catch (_) {}
}
function isInvalidTicker(ticker) {
  return readInvalidTickerSet().has(String(ticker || '').trim().toUpperCase());
}
function markTickerInvalid(ticker) {
  const symbol = String(ticker || '').trim().toUpperCase();
  if (!symbol) return;
  const values = readInvalidTickerSet();
  values.add(symbol);
  writeInvalidTickerSet(values);
}
function clearInvalidTicker(ticker) {
  const symbol = String(ticker || '').trim().toUpperCase();
  if (!symbol) return;
  const values = readInvalidTickerSet();
  if (values.delete(symbol)) writeInvalidTickerSet(values);
}
function filterValidSuggestions(items) {
  const invalid = readInvalidTickerSet();
  return [...(items || [])].filter((item) => item && item.ticker && !invalid.has(String(item.ticker).trim().toUpperCase()));
}
window.EPMTickerValidation = { isInvalidTicker, markTickerInvalid, clearInvalidTicker, filterValidSuggestions };

async function fetchApiCached(url, cacheKey, maxAgeMs = 120000) {
  const cached = readSessionJson(cacheKey, maxAgeMs);
  if (cached) return cached;
  const payload = await fetchApi(url);
  writeSessionJson(cacheKey, payload);
  return payload;
}

function refreshCachedApi(url, cacheKey) {
  return fetchApi(url).then((payload) => {
    writeSessionJson(cacheKey, payload);
    return payload;
  });
}

function renderSparkline(card) {
  const values = (card?.sparkline?.close || []).map((v) => Number(v)).filter((v) => Number.isFinite(v));
  if (values.length < 2) return '<div class="sparkline-empty">No trend data</div>';
  const min = Math.min(...values);
  const max = Math.max(...values);
  const padding = Math.max((max - min) * 0.08, Math.abs(max || 1) * 0.002);
  const low = min - padding;
  const high = max + padding;
  const range = high - low || 1;
  const coords = values.map((value, index) => ({
    x: (index / Math.max(values.length - 1, 1)) * 100,
    y: 100 - ((value - low) / range) * 100,
  }));
  const points = coords.map(p => `${p.x},${p.y}`).join(" ");
  const cls = sparklineClass(card);
  // Gradient color by trend — inline attrs avoid CSS cascade issues on dynamic SVGs
  const color = cls === 'up' ? '#35b86a' : cls === 'down' ? '#ef4444' : '#5a91dc';
  const gid = `sg${Math.random().toString(36).slice(2, 8)}`;
  // Anchor gradient from line's actual peak down to 80% of remaining chart height
  const peakY = Math.min(...coords.map(p => p.y));
  const fadeY = (peakY + (100 - peakY) * 0.8).toFixed(1);
  const areaPoints = `0,100 ${points} 100,100`;
  return `
    <svg class="sparkline ${cls}" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true" overflow="hidden">
      <defs>
        <linearGradient id="${gid}" x1="0" y1="${peakY.toFixed(1)}" x2="0" y2="${fadeY}" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stop-color="${color}" stop-opacity="0.22"/>
          <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <polygon class="sparkline-area" fill="url(#${gid})" points="${areaPoints}"/>
      <polyline fill="none" stroke-width="1.5" vector-effect="non-scaling-stroke" points="${points}"/>
    </svg>
  `;
}

function buildMetricPill(card) {
  const tickerLabel = Object.prototype.hasOwnProperty.call(card || {}, "ticker_label") ? (card.ticker_label || "") : (card.ticker || "");
  return `
    <div class="metric-pill live-pill">
      <div class="label">${escapeHtml(card.name || card.ticker)}</div>
      ${tickerLabel ? `<div class="pill-symbol">${escapeHtml(tickerLabel)}</div>` : ''}
      <div class="value">${fmtPrice(card.last_price)}</div>
      <div class="delta ${deltaClass(card.day_change_pct)}">${fmtPct(card.day_change_pct)}</div>
    </div>
  `;
}

function buildSymbolCard(card, compact = false, clickable = true) {
  if (card.error) {
    return `
      <article class="live-card live-card--error">
        <div class="card-header">
          <div class="card-header-top">
            <h4>${escapeHtml(card.ticker || "Symbol")}</h4>
          </div>
        </div>
        <p class="card-subtitle">${escapeHtml(card.error)}</p>
      </article>
    `;
  }

  const description = shortText(card.description || card.industry || card.sector || "Live market card", 100);

  const inner = `
    <article class="live-card">
      <div class="card-header">
        <div class="card-header-top">
          <h4>${escapeHtml(card.ticker || "")}</h4>
          <div class="card-header-line"></div>
          <span class="trend-pill trend-${escapeHtml(card.trend_state || "unknown")}" title="Long-term trend from price vs 50D and 200D moving averages">${escapeHtml(trendLabel(card.trend_state))}</span>
        </div>
        <div class="card-symbol-name">${escapeHtml(card.name || "")}</div>
      </div>

      <div class="live-card-price-row">
        <div class="live-card-price">${fmtPrice(card.last_price)}</div>
        <div class="price-change-block">
          <div class="delta-label">Today</div>
          <div class="delta ${deltaClass(card.day_change_pct)}">${fmtPct(card.day_change_pct)}</div>
        </div>
      </div>

      <div class="live-card-sparkline-wrap">
        <div class="live-card-sparkline">${renderSparkline(card)}</div>
        <div class="sparkline-caption">${escapeHtml(card.sparkline_label || "1M Price Path")}</div>
      </div>

      <div class="mini-stat-row">
        <div class="mini-stat"><span>1M</span><strong>${fmtPct(card.return_1m)}</strong></div>
        <div class="mini-stat"><span>YTD</span><strong>${fmtPct(card.return_ytd)}</strong></div>
        <div class="mini-stat"><span>Beta</span><strong>${fmtNumber(card.beta_1y)}</strong></div>
      </div>

      <p class="live-card-copy">${escapeHtml(description)}</p>
    </article>
  `;

  return clickable ? `<a class="live-card-link" href="/search?ticker=${encodeURIComponent(card.ticker || "")}">${inner}</a>` : inner;
}

function buildNewsItem(item) {
  const sourceBits = [item.ticker, item.source].filter(Boolean).join(" • ");
  const title = escapeHtml(item.title || "Untitled story");
  const summary = escapeHtml(shortText(item.summary || "No summary available.", 150));
  const linkOpen = item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">` : "";
  const linkClose = item.url ? "</a>" : "";
  return `
    <div class="news-item">
      <div class="news-item-title">${linkOpen}${title}${linkClose}</div>
      <div class="news-meta">${escapeHtml(sourceBits)}</div>
      <div>${summary}</div>
    </div>
  `;
}

function renderInto(selector, html) {
  const el = document.querySelector(selector);
  if (el) el.innerHTML = html;
}

function renderCardGrid(selector, cards, compact = false, clickable = true) {
  const html = (cards || []).length
    ? cards.map((card) => buildSymbolCard(card, compact, clickable)).join("")
    : '<div class="placeholder-item">No symbols available.</div>';
  renderInto(selector, html);
}

function renderHomePayload(payload) {
  renderInto("#homeMarketStrip", (payload.market_strip || []).map(buildMetricPill).join("") || '<div class="placeholder-item">No market strip data.</div>');
  renderCardGrid("#homeFeaturedCards", payload.featured_cards || [], false, true);
  renderCardGrid("#homePortfolioCards", payload.portfolio_watchlist || [], false, true);
  renderInto("#homeTopNews", (payload.top_news || []).map(buildNewsItem).join("") || '<div class="placeholder-item">No ranked headlines available.</div>');
  const generatedEl = document.getElementById("homeGeneratedAt");
  if (generatedEl && payload.generated_at) generatedEl.textContent = `Updated ${payload.generated_at}`;
  if (typeof window._fvsDismiss === 'function') { window._fvsDismiss(); window._fvsDismiss = null; }
}

function buildTrendTable(rows) {
  if (!rows || !rows.length) return '<div class="placeholder-item">No trend data available.</div>';
  const buildRow = (row) => `
    <div class="tt-row">
      <div class="tt-row__left">
        <a class="tt-ticker" href="/search?ticker=${encodeURIComponent(row.ticker || '')}">${escapeHtml(row.ticker || '')}</a>
        <span class="tt-name">${escapeHtml(row.name || '')}</span>
      </div>
      <div class="tt-row__stats">
        <span class="tt-price">${fmtPrice(row.last_price)}</span>
        <span class="tt-stat ${deltaClass(row.day_change_pct)}">${fmtPct(row.day_change_pct)}</span>
        <span class="tt-stat ${deltaClass(row.return_1m)}">${fmtPct(row.return_1m)}</span>
        <span class="tt-stat ${deltaClass(row.return_ytd)}">${fmtPct(row.return_ytd)}</span>
      </div>
      <div class="tt-row__trend ${trendStateClass(row.trend_state)}">${escapeHtml(trendLabel(row.trend_state))}</div>
    </div>`;
  const half = Math.ceil(rows.length / 2);
  const leftRows = rows.slice(0, half);
  const rightRows = rows.slice(half);
  return `
    <div class="tt-header-row">
      <span>Ticker / Name</span>
      <span class="tt-header-stats"><span>Last</span><span>Day</span><span>1M</span><span>YTD</span></span>
      <span>Trend</span>
    </div>
    <div class="tt-dual-col">
      <div class="tt-col">${leftRows.map(buildRow).join('')}</div>
      <div class="tt-col">${rightRows.map(buildRow).join('')}</div>
    </div>`;
}


function ensurePlotly() {
  return typeof window.Plotly !== "undefined";
}

function normalizeSeriesToPct(chart) {
  const dates = Array.isArray(chart?.dates) ? chart.dates : [];
  const closes = Array.isArray(chart?.close) ? chart.close : [];
  const usable = [];
  for (let i = 0; i < Math.min(dates.length, closes.length); i += 1) {
    const close = Number(closes[i]);
    if (Number.isFinite(close) && close > 0) usable.push({ date: dates[i], close });
  }
  if (usable.length < 2) return null;
  const base = usable[0].close || 1;
  return {
    x: usable.map((row) => row.date),
    y: usable.map((row) => ((row.close / base) - 1) * 100),
  };
}

function getThemeColor(name, fallback) {
  const value = getComputedStyle(document.body).getPropertyValue(name).trim() || getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}


function isCompactViewport() {
  return window.innerWidth <= 820;
}

function queueResponsivePlotResize(target) {
  if (!window.Plotly || !target) return;
  const run = () => { try { window.Plotly.Plots.resize(target); } catch (e) {} };
  requestAnimationFrame(run);
  setTimeout(run, 120);
  setTimeout(run, 320);
}

function setInlineLegend(targetId, items, palette, extraClass = '') {
  const el = document.getElementById(targetId);
  if (!el) return;
  const host = el.parentElement;
  if (!host) return;
  let legend = host.querySelector(`.plot-legend-inline[data-for="${targetId}"]`);
  if (!items || !items.length) {
    legend?.remove();
    return;
  }
  if (!legend) {
    legend = document.createElement('div');
    legend.className = 'plot-legend-inline plot-legend-inline--below';
    legend.dataset.for = targetId;
    el.insertAdjacentElement('afterend', legend);
  }
  legend.className = `plot-legend-inline plot-legend-inline--below ${extraClass}`.trim();
  legend.innerHTML = items.map((label, idx) => `
    <span class="plot-legend-item">
      <span class="plot-legend-swatch" style="background:${palette[idx % palette.length]}"></span>
      <span>${escapeHtml(label)}</span>
    </span>
  `).join('');
}

function makeMarketPlotLayout(title, extra = {}) {
  const textColor = getThemeColor('--text', '#eef3ff');
  const muted = getThemeColor('--muted', '#b5c4e2');
  const border = getThemeColor('--border', '#2c4675');
  const paper = 'rgba(0,0,0,0)';
  const plot = document.body.dataset.theme === 'light' ? 'rgba(27,78,152,0.03)' : 'rgba(255,255,255,0.02)';
  return {
    title: { text: title, x: 0.02, xanchor: 'left', font: { color: textColor, size: 19 } },
    paper_bgcolor: paper,
    plot_bgcolor: plot,
    font: { color: textColor, family: 'Arial, Helvetica, sans-serif', size: 13 },
    margin: { l: 58, r: 22, t: 24, b: 56 },
    legend: { orientation: 'h', y: -0.18, x: 0.02, font: { color: muted, size: 11 } },
    xaxis: { gridcolor: border, zeroline: false, tickfont: { color: muted } },
    yaxis: { gridcolor: border, zeroline: false, tickfont: { color: muted } },
    ...extra,
  };
}

function makeMarketPlotConfig() {
  return { displayModeBar: false, responsive: true, scrollZoom: false, staticPlot: false };
}

function renderMarketComparisonChart(targetId, charts) {
  const el = document.getElementById(targetId);
  if (!el) return;
  if (!ensurePlotly()) {
    el.innerHTML = '<div class="placeholder-item">Chart library unavailable.</div>';
    return;
  }
  const compact = isCompactViewport();
  const palette = ['#3aa5ff', '#ff9f1c', '#35b86a', '#ef4444', '#8b5cf6', '#8b7355', '#ec4899'];
  const legendLabels = [];
  const traces = (charts || []).map((item, idx) => {
    const series = item?.chart ? normalizeSeriesToPct(item.chart) : normalizeSeriesToPct({ dates: item?.dates || [], close: item?.close || [] });
    if (!series) return null;
    const label = item.label || item.ticker;
    legendLabels.push(label);
    return {
      type: 'scatter',
      mode: 'lines',
      name: label,
      x: series.x,
      y: series.y,
      line: { width: compact ? 2.1 : 2.5, color: palette[idx % palette.length] },
      hovertemplate: '%{fullData.name}<br>%{x}<br>%{y:.1f}%<extra></extra>',
    };
  }).filter(Boolean);
  if (!traces.length) {
    el.innerHTML = '<div class="placeholder-item">No comparison history available.</div>';
    return;
  }
  setInlineLegend(targetId, legendLabels, palette, compact ? 'plot-legend-inline--compact' : '');
  window.Plotly.newPlot(el, traces, makeMarketPlotLayout('', {
    height: compact ? 300 : 520,
    margin: compact ? { l: 42, r: 12, t: 10, b: 34 } : { l: 58, r: 20, t: 12, b: 38 },
    yaxis: { title: compact ? '' : 'Return (%)', gridcolor: getThemeColor('--border', '#2c4675'), zeroline: false, tickfont: { size: compact ? 10 : 12, color: getThemeColor('--muted', '#b5c4e2') } },
    xaxis: { gridcolor: getThemeColor('--border', '#2c4675'), zeroline: false, tickfont: { size: compact ? 10 : 12, color: getThemeColor('--muted', '#b5c4e2') }, nticks: compact ? 5 : undefined },
    showlegend: false,
  }), makeMarketPlotConfig()).then(() => queueResponsivePlotResize(el));
}

function renderHorizontalBarChart(targetId, title, rows, { metricLabel = "Return", direction = "leaders", height = 270, showText = true, valueColors = null, yLabelField = "ticker" } = {}) {
  const el = document.getElementById(targetId);
  if (!el) return;
  if (!ensurePlotly()) {
    el.innerHTML = '<div class="placeholder-item">Chart library unavailable.</div>';
    return;
  }
  const items = (rows || []).filter((row) => row && row[yLabelField] && Number.isFinite(Number(row.value)));
  if (!items.length) {
    el.innerHTML = '<div class="placeholder-item">No relative performance data available.</div>';
    return;
  }
  const ordered = direction === "laggards" ? [...items].sort((a, b) => a.value - b.value) : [...items].sort((a, b) => b.value - a.value);
  const labels = ordered.map((row) => row[yLabelField]);
  const values = ordered.map((row) => row.value);
  const texts = ordered.map((row) => `${row.ticker || row[yLabelField]} ${row.value >= 0 ? '+' : ''}${row.value.toFixed(1)}%`);
  const markerColor = typeof valueColors === 'function' ? ordered.map((row) => valueColors(row.value, row)) : undefined;
  window.Plotly.newPlot(el, [{
    type: "bar",
    orientation: "h",
    y: labels,
    x: values,
    text: showText ? texts : undefined,
    textposition: showText ? "outside" : undefined,
    textfont: { size: 12 },
    cliponaxis: false,
    marker: markerColor ? { color: markerColor } : undefined,
    hovertemplate: "%{y}<br>%{x:.1f}%<extra></extra>",
  }], makeMarketPlotLayout(title, {
    height,
    margin: { l: 140, r: 32, t: 44, b: 42 },
    xaxis: { title: `${metricLabel} (%)`, gridcolor: "rgba(127, 164, 231, 0.10)", zeroline: true, zerolinecolor: "rgba(255,255,255,0.18)" },
    yaxis: { automargin: true, tickfont: { size: 12 }, gridcolor: "rgba(0,0,0,0)" },
    showlegend: false,
  }), makeMarketPlotConfig()).then(() => queueResponsivePlotResize(el));
}

function renderSectorRotationChart(targetId, rows) {
  const el = document.getElementById(targetId);
  if (!el) return;
  if (!ensurePlotly()) {
    el.innerHTML = '<div class="placeholder-item">Chart library unavailable.</div>';
    return;
  }
  const compact = isCompactViewport();
  const items = (rows || []).filter((row) => row && row.name && Number.isFinite(Number(row.value)));
  if (!items.length) {
    el.innerHTML = '<div class="placeholder-item">No sector rotation data available.</div>';
    return;
  }
  const ordered = [...items].sort((a, b) => a.value - b.value);
  const labels = ordered.map((row) => row.name);
  const values = ordered.map((row) => row.value);
  const colors = ordered.map((row) => row.value >= 0 ? '#35b86a' : '#ef4444');
  const minVal = Math.min(...values, 0);
  const maxVal = Math.max(...values, 0);
  const negativeLabelPad = Math.max(compact ? 8.5 : 10.5, Math.abs(minVal) * (compact ? 0.92 : 1.05));
  const positiveLabelPad = Math.max(compact ? 3.4 : 4.4, Math.abs(maxVal) * (compact ? 0.16 : 0.24));
  const height = Math.max(compact ? 286 : 304, ordered.length * (compact ? 20 : 22) + (compact ? 56 : 74));
  const textColor = getThemeColor('--text', '#eef3ff');
  const annotations = ordered.map((row) => ({
    x: row.value >= 0 ? row.value + Math.max(0.35, Math.abs(maxVal) * 0.012) : row.value - Math.max(0.35, Math.abs(minVal) * 0.018),
    y: row.name,
    xref: 'x',
    yref: 'y',
    text: `${row.value >= 0 ? '+' : ''}${row.value.toFixed(1)}%`,
    showarrow: false,
    xanchor: row.value >= 0 ? 'left' : 'right',
    align: row.value >= 0 ? 'left' : 'right',
    font: { size: compact ? 10 : 11, color: textColor },
  }));
  window.Plotly.newPlot(el, [{
    type: 'bar',
    orientation: 'h',
    y: labels,
    x: values,
    marker: { color: colors },
    width: compact ? 0.52 : 0.56,
    hovertemplate: '%{y}<br>%{x:.1f}%<extra></extra>',
  }], makeMarketPlotLayout('', {
    height,
    margin: compact ? { l: 136, r: 76, t: 4, b: 28 } : { l: 236, r: 124, t: 8, b: 36 },
    xaxis: {
      title: compact ? '' : 'YTD return (%)',
      gridcolor: 'rgba(127, 164, 231, 0.10)',
      zeroline: true,
      zerolinecolor: 'rgba(255,255,255,0.22)',
      range: [minVal - negativeLabelPad, maxVal + positiveLabelPad],
      tickfont: { size: compact ? 10 : 11, color: getThemeColor('--muted', '#b5c4e2') },
    },
    yaxis: { automargin: true, tickfont: { size: compact ? 10 : 12 }, gridcolor: 'rgba(0,0,0,0)' },
    showlegend: false,
    annotations,
  }), makeMarketPlotConfig()).then(() => queueResponsivePlotResize(el));
}

function renderMacroLensChart(targetId, title, seriesMap, { rightAxisKeys = [], leftTitle = '', rightTitle = '' } = {}) {
  const el = document.getElementById(targetId);
  if (!el) return;
  if (!ensurePlotly()) {
    el.innerHTML = '<div class="placeholder-item">Chart library unavailable.</div>';
    return;
  }
  const compact = isCompactViewport();
  const entries = Object.entries(seriesMap || {}).filter(([, series]) => Array.isArray(series?.dates) && Array.isArray(series?.close) && series.dates.length > 1 && series.close.length > 1);
  if (!entries.length) {
    el.innerHTML = '<div class="placeholder-item">No macro lens data available.</div>';
    return;
  }
  const palette = ['#3aa5ff', '#ff9f1c', '#35b86a', '#ef4444', '#8b5cf6', '#8b7355', '#14b8a6'];
  setInlineLegend(targetId, entries.map(([label]) => label), palette, compact ? 'plot-legend-inline--compact' : '');
  const traces = entries.map(([label, series], idx) => ({
    type: 'scatter',
    mode: 'lines',
    name: label,
    x: series.dates,
    y: series.close,
    line: { width: compact ? 2 : 2.3, color: palette[idx % palette.length] },
    yaxis: rightAxisKeys.includes(label) ? 'y2' : 'y',
    hovertemplate: `${label}<br>%{x}<br>%{y:.2f}<extra></extra>`,
  }));
  window.Plotly.newPlot(el, traces, makeMarketPlotLayout('', {
    height: compact ? 250 : 334,
    margin: compact ? { l: 40, r: 40, t: 6, b: 22 } : { l: 54, r: 54, t: 8, b: 28 },
    xaxis: { gridcolor: getThemeColor('--border', '#2c4675'), zeroline: false, tickfont: { size: compact ? 10 : 12, color: getThemeColor('--muted', '#b5c4e2') }, nticks: compact ? 4 : undefined },
    yaxis: { title: compact ? undefined : (leftTitle || undefined), gridcolor: getThemeColor('--border', '#2c4675'), zeroline: false, tickfont: { size: compact ? 10 : 12, color: getThemeColor('--muted', '#b5c4e2') } },
    yaxis2: { title: compact ? undefined : (rightTitle || undefined), overlaying: 'y', side: 'right', showgrid: false, tickfont: { size: compact ? 10 : 12, color: getThemeColor('--muted', '#b5c4e2') } },
    showlegend: false,
  }), makeMarketPlotConfig()).then(() => queueResponsivePlotResize(el));
}

function renderMoversBox(targetId, movers) {
  const el = document.getElementById(targetId);
  if (!el) return;
  const gainers = (movers?.gainers || []).slice(0, 7);
  const losers  = (movers?.losers  || []).slice(0, 7);
  const buildRow = (row, loser = false) => `
    <a class="mover-compact-row ${loser ? 'mover-row--down' : 'mover-row--up'}" href="/search?ticker=${encodeURIComponent(row.ticker || '')}" title="${escapeHtml(row.name || '')}">
      <span class="mover-compact__ticker">${escapeHtml(row.ticker || '')}</span>
      <span class="mover-compact__name">${escapeHtml(row.name || '')}</span>
      <span class="mover-compact__delta ${deltaClass(row.day_change_pct)}">${fmtPct(row.day_change_pct)}</span>
    </a>`;
  const renderList = (side) => side === 'gainers'
    ? (gainers.length ? gainers.map(r => buildRow(r, false)).join('') : '<div class="mover-empty">No data</div>')
    : (losers.length  ? losers.map(r => buildRow(r, true)).join('')  : '<div class="mover-empty">No data</div>');
  el.innerHTML = `
    <div class="movers-toggle-bar">
      <button class="movers-toggle-btn movers-toggle-btn--active" data-side="gainers">&#9650; Gainers</button>
      <button class="movers-toggle-btn" data-side="losers">&#9660; Losers</button>
    </div>
    <div class="movers-toggle-list" data-active="gainers">
      ${renderList('gainers')}
    </div>`;
  el.querySelectorAll('.movers-toggle-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const side = btn.dataset.side;
      el.querySelectorAll('.movers-toggle-btn').forEach(b => b.classList.toggle('movers-toggle-btn--active', b === btn));
      const list = el.querySelector('.movers-toggle-list');
      list.dataset.active = side;
      list.innerHTML = renderList(side);
    });
  });
}

function renderMarketSummary(payload) {
  const summaryEl = document.getElementById("marketsReadSummary");
  const riskEl = document.getElementById("marketsRiskDashboard");
  if (summaryEl) {
    const read = payload.market_read || {};
    summaryEl.innerHTML = `
      <p><strong>Current regime:</strong> ${escapeHtml(read.regime || 'Mixed backdrop')}.</p>
      <p><strong>Index tape:</strong> ${escapeHtml(read.indices || 'Unavailable')}.</p>
      <p><strong>Today's leaders:</strong> ${escapeHtml(read.leaders || 'N/A')}.</p>
      <p><strong>Today's laggards:</strong> ${escapeHtml(read.laggards || 'N/A')}.</p>
      <p><strong>Sector leaders YTD:</strong> ${escapeHtml(read.sector_leaders || 'N/A')}.</p>
      <p><strong>Sector laggards YTD:</strong> ${escapeHtml(read.sector_laggards || 'N/A')}.</p>
      <p><strong>Breadth:</strong> ${escapeHtml(read.breadth || 'Unavailable')}.</p>
      <p><strong>Risk on vs risk off:</strong> ${escapeHtml(read.risk_on_vs_off || 'Unavailable')}.</p>
    `;
  }
  if (riskEl) {
    const cards = payload.risk_dashboard || [];
    riskEl.innerHTML = cards.length ? cards.map((card) => `
      <div class="metric-pill market-kpi-pill">
        <div class="label">${escapeHtml(card.label || '')}</div>
        <div class="value">${escapeHtml(card.value || 'N/A')}</div>
        <div class="tiny-note">${escapeHtml(card.note || '')}</div>
      </div>
    `).join('') : '<div class="placeholder-item">No risk dashboard available.</div>';
  }
}

async function renderMarketsVisuals(payload) {
  const comparison = payload.index_comparison || [];
  if (comparison.length) {
    renderMarketComparisonChart('marketsIndexComparisonChart', comparison);
  } else {
    const chartTickers = (payload.indexes || []).map((card) => card.ticker).filter(Boolean).slice(0, 5);
    if (chartTickers.length) {
      const results = await Promise.allSettled(chartTickers.map((ticker) => fetchApi(`/api/chart?ticker=${encodeURIComponent(ticker)}&period=3y`).then((chart) => ({ ticker, chart }))));
      const charts = results.filter((result) => result.status === 'fulfilled').map((result) => result.value).map((item) => {
        const match = (payload.indexes || []).find((row) => row.ticker === item.ticker);
        return { ...item, label: match?.name || item.ticker };
      });
      renderMarketComparisonChart('marketsIndexComparisonChart', charts);
    }
  }
  renderMoversBox('marketsMoversBox', payload.movers_box || { gainers: payload.leaders || [], losers: payload.laggards || [] });
  renderSectorRotationChart('marketsSectorRotationChart', payload.sector_rotation || []);
  const lenses = payload.macro_lens_charts || {};
  renderMacroLensChart('marketsEquityRiskChart', '', lenses.equity_risk || {}, { rightAxisKeys: ['VIX'], leftTitle: 'SPY', rightTitle: 'VIX' });
  renderMacroLensChart('marketsRatesCreditChart', '', lenses.rates_credit || {}, { rightAxisKeys: ['HYG', 'IEF', 'LQD'], leftTitle: '10Y yield', rightTitle: 'Rebased credit' });
  renderMacroLensChart('marketsDollarCommoditiesChart', '', lenses.dollar_commodities || {}, { leftTitle: 'Rebased move (%)', rightTitle: '' });
  renderMarketSummary(payload);
}

function renderMarketsPayload(payload) {
  renderInto("#marketsIndexes", (payload.indexes || []).map(buildMetricPill).join("") || '<div class="placeholder-item">No index data.</div>');
  renderCardGrid("#marketsRiskOn", payload.risk_board?.risk_on || [], true, true);
  renderCardGrid("#marketsRiskOff", payload.risk_board?.risk_off || [], true, true);
  renderInto("#marketsTrendTable", buildTrendTable(payload.trend_table || []));
  renderWorldNews(payload.world_news || []);
  renderEconCalendar(payload.economic_calendar || []);
  const generatedEl = document.getElementById("marketsGeneratedAt");
  if (generatedEl && payload.generated_at) generatedEl.textContent = `Updated ${payload.generated_at}`;
}

function renderWorldNews(articles) {
  const el = document.getElementById("marketsWorldNews");
  if (!el) return;
  if (!articles.length) {
    el.innerHTML = '<div class="econ-empty">No news available — run the daily pipeline to populate.</div>';
    return;
  }
  const CAT_LABELS = { commodities: "Commodities", fixed_income: "Rates", equities: "Equities", currencies: "FX", macro: "Macro", world: "Global" };
  el.innerHTML = articles.map(a => {
    const cat   = a.category || "world";
    const label = CAT_LABELS[cat] || cat;
    const href  = a.url ? `href="${escapeHtml(a.url)}" target="_blank" rel="noopener"` : "";
    const title = `<a ${href}>${escapeHtml(a.title || "")}</a>`;
    const summary = a.summary ? `<div class="wn-summary">${escapeHtml(a.summary)}</div>` : "";
    const source  = a.source ? `<span class="wn-source">${escapeHtml(a.source)}</span>` : "";
    const catBadge = `<span class="wn-cat ${escapeHtml(cat)}">${escapeHtml(label)}</span>`;
    return `<div class="world-news-item">${title}${summary}<div class="wn-meta">${catBadge}${source}</div></div>`;
  }).join("");
}

function renderEconCalendar(events) {
  const el = document.getElementById("marketsEconCalendar");
  const panel = document.getElementById("marketsEconDayPanel");
  if (!el) return;
  if (!events || !events.length) {
    el.innerHTML = '<div class="econ-empty">No upcoming events — run pipeline to populate.</div>';
    return;
  }

  // Build a map: dateStr → [event, ...]
  const byDay = {};
  events.forEach(ev => {
    const d = (ev.date || "").slice(0, 10);
    if (!d) return;
    if (!byDay[d]) byDay[d] = [];
    byDay[d].push(ev);
  });

  // Build 4-week grid starting from today's Monday
  const today = new Date(); today.setHours(0,0,0,0);
  const dow = today.getDay(); // 0=Sun
  const monday = new Date(today); monday.setDate(today.getDate() - (dow === 0 ? 6 : dow - 1));

  const DAY_LABELS = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  let gridHtml = '<div class="econ-cal-header">' + DAY_LABELS.map(d => `<span>${d}</span>`).join('') + '</div>';

  for (let week = 0; week < 4; week++) {
    gridHtml += '<div class="econ-cal-week">';
    for (let d = 0; d < 7; d++) {
      const cell = new Date(monday); cell.setDate(monday.getDate() + week * 7 + d);
      const iso = cell.toISOString().slice(0, 10);
      const dayEvs = byDay[iso] || [];
      const isToday = iso === today.toISOString().slice(0, 10);
      const isPast  = cell < today;
      const dots = dayEvs.map(ev => {
        const hi = (ev.importance || "").toLowerCase().includes("high");
        return `<span class="econ-dot econ-dot--${hi ? 'high' : 'med'}" title="${escapeHtml(ev.event || '')}"></span>`;
      }).join('');
      gridHtml += `<button class="econ-cal-day${isToday ? ' econ-cal-today' : ''}${isPast ? ' econ-cal-past' : ''}${dayEvs.length ? ' econ-cal-has-events' : ''}" data-iso="${iso}">
        <span class="econ-cal-num">${cell.getDate()}</span>
        <span class="econ-cal-dots">${dots}</span>
      </button>`;
    }
    gridHtml += '</div>';
  }
  el.innerHTML = gridHtml;

  // Day click → show event list panel
  el.querySelectorAll('.econ-cal-day[data-iso]').forEach(btn => {
    btn.addEventListener('click', () => {
      const iso = btn.dataset.iso;
      const dayEvs = byDay[iso] || [];
      el.querySelectorAll('.econ-cal-day').forEach(b => b.classList.remove('econ-cal-selected'));
      if (panel.dataset.open === iso) {
        panel.classList.add('hidden'); panel.dataset.open = ''; return;
      }
      btn.classList.add('econ-cal-selected');
      if (!dayEvs.length) { panel.classList.add('hidden'); panel.dataset.open = ''; return; }
      const fmt = new Date(iso + 'T12:00:00').toLocaleDateString('en-US', {weekday:'long', month:'short', day:'numeric'});
      panel.innerHTML = `<div class="econ-day-title">${fmt}</div>` + dayEvs.map(ev => {
        const hi = (ev.importance || "").toLowerCase().includes("high");
        const vals = [ev.actual != null ? `Act: ${ev.actual}` : '', ev.consensus != null ? `Est: ${ev.consensus}` : '', ev.previous != null ? `Prev: ${ev.previous}` : ''].filter(Boolean).join(' · ');
        return `<div class="econ-day-event"><span class="econ-dot econ-dot--${hi ? 'high' : 'med'}"></span><div><div class="econ-day-name">${escapeHtml(ev.event || '')}</div>${vals ? `<div class="econ-day-vals">${escapeHtml(vals)}</div>` : ''}</div></div>`;
      }).join('');
      panel.classList.remove('hidden');
      panel.dataset.open = iso;
    });
  });
}

// ---------------------------------------------------------------------------
// EPM Composite Sentiment Gauge
// ---------------------------------------------------------------------------
function renderEPMGauge(enrichment) {
  const el = document.getElementById('marketsEPMGauge');
  if (!el) return;

  const epm   = enrichment.epm_sentiment || {};
  const score = epm.score;
  const label = epm.label || 'N/A';
  const comps = epm.components || {};
  const updated = enrichment.updated || '';

  if (score == null) {
    el.innerHTML = '<div class="econ-empty">EPM Sentiment data unavailable &mdash; run daily pipeline to populate.</div>';
    return;
  }

  const scoreColor = s =>
    s < 25 ? '#ef4444' : s < 45 ? '#f97316' : s < 55 ? '#9ca3af' : s < 75 ? '#22c55e' : '#16a34a';
  const color = scoreColor(score);

  // SVG semicircle gauge
  const W = 220, H = 124, CX = W / 2, CY = H - 10, R = 88, THICK = 14;
  const s2a  = s => Math.PI - (s / 100) * Math.PI;
  const pxy  = (a, r) => ({ x: CX + r * Math.cos(a), y: CY - r * Math.sin(a) });
  const arc  = (f, t) => {
    const [a1, a2] = [s2a(f), s2a(t)];
    const [o1, o2] = [pxy(a1, R), pxy(a2, R)];
    const [i1, i2] = [pxy(a1, R - THICK), pxy(a2, R - THICK)];
    const lg = (t - f) > 50 ? 1 : 0;
    return `M${o1.x},${o1.y} A${R},${R},0,${lg},0,${o2.x},${o2.y} L${i2.x},${i2.y} A${R-THICK},${R-THICK},0,${lg},1,${i1.x},${i1.y} Z`;
  };
  const segs = [
    [0,25,'#ef4444'],[25,45,'#f97316'],[45,55,'#9ca3af'],[55,75,'#22c55e'],[75,100,'#16a34a']
  ];
  const na  = s2a(Math.max(2, Math.min(98, score)));
  const ne  = pxy(na, R - 4);
  const nb1 = { x: CX + 5 * Math.cos(na + Math.PI/2), y: CY - 5 * Math.sin(na + Math.PI/2) };
  const nb2 = { x: CX + 5 * Math.cos(na - Math.PI/2), y: CY - 5 * Math.sin(na - Math.PI/2) };

  const svgHtml = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:220px;display:block;margin:0 auto" aria-hidden="true">
    <path d="${arc(0,100)}" fill="rgba(255,255,255,0.04)"/>
    ${segs.map(([f,t,c]) => `<path d="${arc(f,t)}" fill="${c}" opacity="0.82"/>`).join('')}
    <polygon points="${ne.x},${ne.y} ${nb1.x},${nb1.y} ${nb2.x},${nb2.y}" fill="${color}"/>
    <circle cx="${CX}" cy="${CY}" r="6" fill="${color}"/>
    <circle cx="${CX}" cy="${CY}" r="3" fill="var(--bg,#061326)"/>
  </svg>`;

  // Component bars
  const compOrder = ['cnn_fear_greed','news_sentiment','reddit_wsb','crypto_fear_greed','rsi_spy','own_news'];
  const compBars = compOrder.filter(k => comps[k]).map(k => {
    const c = comps[k];
    const cc = scoreColor(c.score);
    return `<div class="epm-comp-row">
      <span class="epm-comp-name">${escapeHtml(c.label)}</span>
      <div class="epm-comp-track"><div class="epm-comp-fill" style="width:${Math.round(c.score)}%;background:${cc}"></div></div>
      <span class="epm-comp-val" style="color:${cc}">${Math.round(c.score)}</span>
    </div>`;
  }).join('');

  // Detail rows (expanded panel)
  const detailRows = compOrder.filter(k => comps[k]).map(k => {
    const c = comps[k];
    const cc = scoreColor(c.score);
    return `<div class="epm-detail-row">
      <div>
        <div class="epm-detail-name">${escapeHtml(c.label)}</div>
        <div class="epm-detail-sub">${escapeHtml(c.detail || '')} &middot; weight ${c.weight}%</div>
      </div>
      <div class="epm-detail-score" style="color:${cc}">${Math.round(c.score)}</div>
    </div>`;
  }).join('');

  el.innerHTML = `
    <div class="epm-gauge-wrap epm-gauge-clickable" id="epmGaugeTrigger" role="button" tabindex="0" aria-label="View signal breakdown">
      ${svgHtml}
      <div class="epm-gauge-score" style="color:${color}">${Math.round(score)}</div>
      <div class="epm-gauge-label" style="color:${color}">${escapeHtml(label)}</div>
      ${updated ? `<div class="epm-gauge-updated">As of ${escapeHtml(updated)}</div>` : ''}
      <div class="epm-gauge-hint">&#9432; Signal Breakdown</div>
    </div>
    <div class="epm-gauge-overlay" id="epmGaugeOverlay">
      <div class="epm-gauge-overlay-inner" id="epmGaugeOverlayInner">
        <div class="epm-gauge-overlay-header">
          <span>EPM Market Sentiment &mdash; Signal Breakdown</span>
          <button class="epm-gauge-overlay-close" id="epmGaugeOverlayClose" aria-label="Close">&times;</button>
        </div>
        <div style="font-size:11.5px;color:var(--muted);margin:0 0 14px;line-height:1.55;display:flex;flex-direction:column;gap:5px;">
          <p style="margin:0;">Composite of 6 independent signals, each normalized to a 0&ndash;100 scale.</p>
          <p style="margin:0;"><span style="color:var(--text);font-weight:600;">Signals &mdash;</span> CNN Fear &amp; Greed &middot; News Sentiment &middot; Reddit WSB &middot; Crypto Fear &amp; Greed &middot; SPY RSI(14) &middot; EPM News Feed</p>
          <p style="margin:0;"><span style="color:var(--text);font-weight:600;">Scale &mdash;</span> 0&nbsp;= extreme fear &nbsp;&middot;&nbsp; 100&nbsp;= extreme greed</p>
          <p style="margin:0;font-size:10.5px;">Absent signals auto-rebalance weights to preserve the full scale.</p>
        </div>
        <div class="epm-components" style="margin-top:0;">${compBars}</div>
        <div style="margin-top:14px;">${detailRows}</div>
      </div>
    </div>`;

  const trigger = document.getElementById('epmGaugeTrigger');
  const overlay = document.getElementById('epmGaugeOverlay');
  const closeBtn = document.getElementById('epmGaugeOverlayClose');
  const inner = document.getElementById('epmGaugeOverlayInner');

  // Move overlay to <body> so position:fixed is never trapped inside a
  // transformed/animated ancestor (fade-in etc. create new stacking contexts).
  if (overlay && overlay.parentNode !== document.body) {
    document.body.appendChild(overlay);
  }

  function openOverlay() { overlay && overlay.classList.add('open'); }
  function closeOverlay() { overlay && overlay.classList.remove('open'); }

  if (trigger) {
    trigger.addEventListener('click', openOverlay);
    trigger.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') openOverlay(); });
  }
  if (closeBtn) closeBtn.addEventListener('click', e => { e.stopPropagation(); closeOverlay(); });
  if (overlay) overlay.addEventListener('click', e => { if (e.target === overlay) closeOverlay(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeOverlay(); }, { once: false });
}

// ---------------------------------------------------------------------------
// OECD CLI grid
// ---------------------------------------------------------------------------
function renderOECDCLI(cliData) {
  const el = document.getElementById('marketsOECDCLI');
  if (!el) return;
  const entries = Object.entries(cliData || {});
  if (!entries.length) {
    el.innerHTML = '<div class="econ-empty">OECD CLI data unavailable &mdash; run daily pipeline to populate.</div>';
    return;
  }
  el.innerHTML = entries.map(([country, d]) => {
    const trendClass = d.trend === 'improving' ? 'oecd-cli-trend-up' : d.trend === 'deteriorating' ? 'oecd-cli-trend-dn' : '';
    const arrow      = d.trend === 'improving' ? '&#9650;' : d.trend === 'deteriorating' ? '&#9660;' : '&mdash;';
    const posLabel   = parseFloat(d.value) > 100 ? 'Expansionary' : 'Contractionary';
    const mom        = parseFloat(d.mom || 0);
    return `<div class="oecd-cli-item">
      <div class="oecd-cli-country">${escapeHtml(country)}</div>
      <div class="oecd-cli-value ${trendClass}">${d.value} <small>${arrow}</small></div>
      <div class="oecd-cli-meta">${escapeHtml(posLabel)} &middot; ${mom >= 0 ? '+' : ''}${mom} MoM &middot; ${escapeHtml(d.date || '')}</div>
    </div>`;
  }).join('');
}

function renderSecInsider(insiderData) {
  const summaryEl = document.getElementById('marketsInsiderSummary');
  const listEl    = document.getElementById('marketsInsiderActivity');
  const data      = insiderData || {};
  const summary   = data.summary || {};
  const trades    = data.transactions || [];

  // ── Summary bar ────────────────────────────────────────────────────────
  if (summaryEl) {
    if (!summary.buy_count && !summary.sell_count) {
      summaryEl.innerHTML = '<div class="econ-empty">No insider data available — run daily pipeline to populate.</div>';
    } else {
      const ratio    = summary.buy_ratio != null ? (summary.buy_ratio * 100).toFixed(0) : '—';
      const netVal   = summary.net_value != null ? (summary.net_value >= 0 ? `+$${summary.net_value.toFixed(1)}M` : `-$${Math.abs(summary.net_value).toFixed(1)}M`) : '—';
      const netClass = (summary.net_value || 0) >= 0 ? 'insider-buy' : 'insider-sell';
      summaryEl.innerHTML = `
        <div class="insider-summary-grid">
          <div class="insider-stat">
            <div class="insider-stat-val insider-buy">&#9650; ${summary.buy_count ?? 0}</div>
            <div class="insider-stat-label">Open-Market Buys</div>
          </div>
          <div class="insider-stat">
            <div class="insider-stat-val insider-sell">&#9660; ${summary.sell_count ?? 0}</div>
            <div class="insider-stat-label">Open-Market Sells</div>
          </div>
          <div class="insider-stat">
            <div class="insider-stat-val">${ratio}%</div>
            <div class="insider-stat-label">Buy Ratio</div>
          </div>
          <div class="insider-stat">
            <div class="insider-stat-val ${netClass}">${netVal}</div>
            <div class="insider-stat-label">Net Value (30d)</div>
          </div>
          <div class="insider-stat">
            <div class="insider-stat-val">$${(summary.total_buy_value || 0).toFixed(1)}M</div>
            <div class="insider-stat-label">Total Buy Value</div>
          </div>
          <div class="insider-stat">
            <div class="insider-stat-val">$${(summary.total_sell_value || 0).toFixed(1)}M</div>
            <div class="insider-stat-label">Total Sell Value</div>
          </div>
        </div>`;
    }
  }

  // ── Transaction list ───────────────────────────────────────────────────
  if (listEl) {
    if (!trades.length) {
      listEl.innerHTML = '<div class="econ-empty">No open-market transactions found in the scan window.</div>';
      return;
    }
    listEl.innerHTML = trades.slice(0, 40).map(t => {
      const dirClass = t.direction === 'Buy' ? 'insider-buy' : 'insider-sell';
      const dirLabel = t.direction === 'Buy' ? '&#9650; Buy' : '&#9660; Sell';
      const val   = t.value  ? ` &middot; $${(t.value / 1000).toFixed(0)}K` : '';
      const price = t.price  ? ` @ $${t.price}` : '';
      const link  = t.filing_url ? ` <a href="${escapeHtml(t.filing_url)}" target="_blank" rel="noopener" class="insider-link">SEC&#8599;</a>` : '';
      return `<div class="insider-row">
        <span class="insider-dir ${dirClass}">${dirLabel}</span>
        <span class="insider-ticker">${escapeHtml(t.symbol)}</span>
        <span class="insider-owner">${escapeHtml(t.owner || '')}</span>
        <span class="insider-meta">${escapeHtml(t.shares ? t.shares.toLocaleString() + ' sh' : '')}${price}${val} &middot; ${escapeHtml(t.date || '')}${link}</span>
      </div>`;
    }).join('');
  }
}

function renderPortfoliosPayload(payload) {
  renderCardGrid("#portfolioUniverseGrid", payload.portfolio_universe || [], false, true);
  renderCardGrid("#portfolioLeaders", payload.leaders || [], true, true);
  renderCardGrid("#portfolioLaggards", payload.laggards || [], true, true);
  const generatedEl = document.getElementById("portfoliosGeneratedAt");
  if (generatedEl && payload.generated_at) generatedEl.textContent = `Updated ${payload.generated_at}`;
}

function renderLoadError(selector, message) { renderInto(selector, `<div class="placeholder-item">${escapeHtml(message)}</div>`); }


function fetchNoThrow(url) {
  return fetch(url, { credentials: "same-origin" }).catch(() => null);
}

function warmBackgroundRoutes() {
  const page = document.body.dataset.page;
  const pageQueue = [];   // HTML page prefetches (browser cache for instant nav)
  const apiQueue  = [];   // API data prefetches (sessionStorage cache for instant render)

  if (page === "home") {
    pageQueue.push("/markets", "/portfolios", "/forecasting");
  } else if (page === "markets") {
    pageQueue.push("/", "/portfolios", "/forecasting");
  } else if (page === "portfolios") {
    pageQueue.push("/", "/markets", "/forecasting");
  } else if (page === "forecasting") {
    pageQueue.push("/", "/markets", "/portfolios");
  }

  // Pre-warm API payloads for auth-gated pages if already authenticated.
  // Cookies are sent automatically; use cached username as a proxy for auth state.
  const isAuthenticated = !!localStorage.getItem('epm_username');
  if (isAuthenticated && page !== "forecasting") {
    apiQueue.push(
      { url: '/api/forecasts',           key: 'api_cache_forecasts',    ttl: 300000 },
      { url: '/api/forecast-chart-data', key: 'api_cache_forecast_chart', ttl: 300000 },
    );
  }
  if (isAuthenticated && page !== "portfolios") {
    apiQueue.push({ url: '/api/portfolios', key: 'api_cache_portfolios', ttl: 180000 });
  }
  if (page !== "markets") {
    apiQueue.push({ url: '/api/markets', key: 'api_cache_markets', ttl: 180000 });
  }

  const run = () => {
    pageQueue.forEach((url, i) => setTimeout(() => { void fetchNoThrow(url); }, i * 300));
    apiQueue.forEach(({ url, key, ttl }, i) => {
      // Skip if already cached and fresh
      if (readSessionJson(key, ttl)) return;
      setTimeout(() => {
        fetch(url).then(r => r.ok ? r.json() : null).then(data => {
          if (data && data.ok !== false) writeSessionJson(key, data.payload ?? data);
        }).catch(() => {});
      }, pageQueue.length * 300 + i * 400);
    });
  };

  if ("requestIdleCallback" in window) {
    window.requestIdleCallback(run, { timeout: 3000 });
  } else {
    setTimeout(run, 1500);
  }
}

function buildHomeUrl(featuredTickers) {
  if (!featuredTickers || !featuredTickers.length) return '/api/home';
  return '/api/home?featured=' + encodeURIComponent(featuredTickers.join(','));
}

async function initHomePage() {
  // Load user prefs to see if they have a custom featured watchlist
  const prefs = epmGetCachedPrefs();
  const customTickers = (prefs?.featured_tickers?.length) ? prefs.featured_tickers : null;
  const homeUrl = buildHomeUrl(customTickers);
  const cacheKey = customTickers ? 'api_cache_home_custom' : 'api_cache_home';

  // Wire up watchlist editor — refreshes data when saved
  const reloadWithTickers = async (newTickers) => {
    const url = buildHomeUrl(newTickers.length ? newTickers : null);
    try {
      const res = await fetch(url);
      const data = await res.json();
      if (data?.payload) {
        renderCardGrid('#homeFeaturedCards', data.payload.featured_cards || [], false, true);
      }
    } catch (_) {}
    // Re-mount edit button with new ticker list
    document.querySelector('.wl-edit-btn')?.remove();
    mountWatchlistEditBtn(newTickers.length ? newTickers : (customTickers || []), reloadWithTickers);
  };

  try {
    const cached = readSessionJson(cacheKey, 180000);
    if (cached) {
      renderHomePayload(cached);
      const shownTickers = customTickers || cached?.universe?.featured || [];
      mountWatchlistEditBtn(shownTickers, reloadWithTickers);
    }
    const payload = cached || await fetchApiCached(homeUrl, cacheKey, 180000);
    renderHomePayload(payload);
    if (!cached) {
      const shownTickers = customTickers || payload?.universe?.featured || [];
      mountWatchlistEditBtn(shownTickers, reloadWithTickers);
    }
    if (cached) {
      refreshCachedApi(homeUrl, cacheKey).then((fresh) => {
        renderHomePayload(fresh);
      }).catch(() => {});
    }
    // Fetch fresh prefs in background to keep cache warm
    epmFetchPrefs().then((freshPrefs) => {
      if (freshPrefs?.featured_tickers?.length && !customTickers) {
        // User has prefs but we rendered defaults — reload featured section
        reloadWithTickers(freshPrefs.featured_tickers);
      }
    }).catch(() => {});
  }
  catch (error) {
    const message = error?.message || 'Unable to load home dashboard.';
    ['#homeMarketStrip', '#homeFeaturedCards', '#homePortfolioCards', '#homeTopNews'].forEach((selector) => renderLoadError(selector, message));
  }

  startQuotesPoller('#homeMarketStrip', '#homeGeneratedAt');
}

function renderMarketsBriefing(commentary) {
  const el = document.getElementById('marketsMorningBriefing');
  if (!el || !commentary) return;

  const fgScore  = commentary.fear_greed_score;
  const fgRating = (commentary.fear_greed_rating || '').replace(/_/g, ' ');
  const recap    = Array.isArray(commentary.session_recap)  ? commentary.session_recap  : [];
  const watch    = Array.isArray(commentary.watch_today)    ? commentary.watch_today    : [];
  const intl     = commentary.international_section || '';

  // Fear & Greed color bands
  let fgColor = '#6b7280';
  if (fgScore != null) {
    if      (fgScore < 25) fgColor = '#ef4444';
    else if (fgScore < 45) fgColor = '#f97316';
    else if (fgScore < 55) fgColor = '#9ca3af';
    else if (fgScore < 75) fgColor = '#22c55e';
    else                   fgColor = '#16a34a';
  }

  const fgBadge = fgScore != null ? `
    <div class="briefing-fg-badge" style="border-color:${fgColor}20;background:${fgColor}12;">
      <span class="briefing-fg-label">CNN Fear &amp; Greed</span>
      <span class="briefing-fg-score" style="color:${fgColor}">${Math.round(fgScore)}</span>
      <span class="briefing-fg-rating" style="color:${fgColor}">${escapeHtml(fgRating)}</span>
    </div>` : '';

  const recapHtml = recap.length ? `
    <div class="briefing-col">
      <div class="briefing-col-title">What Happened Yesterday</div>
      <ul class="briefing-list">${recap.map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ul>
    </div>` : '';

  const watchHtml = watch.length ? `
    <div class="briefing-col">
      <div class="briefing-col-title">What to Watch Today</div>
      <ul class="briefing-list">${watch.map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ul>
    </div>` : '';

  el.innerHTML = `
    <div class="briefing-header">
      <h3 class="briefing-title">Morning Brief</h3>
      ${fgBadge}
    </div>
    <div class="briefing-cols">${recapHtml}${watchHtml}</div>`;

  // International section — inject into Market Read card
  const intlEl = document.getElementById('marketsInternational');
  if (intlEl && intl) {
    intlEl.innerHTML = `
      <div class="briefing-intl-section">
        <div class="briefing-col-title">Global Context</div>
        <p class="market-copy">${escapeHtml(intl)}</p>
      </div>`;
  }
}

// ---------------------------------------------------------------------------
// Live quotes poller — updates only the index strip every 60 s.
// Only polls while at least one tracked exchange is in its trading session.
// Uses Intl.DateTimeFormat so DST is handled automatically per timezone.
// ---------------------------------------------------------------------------

function isAnyMarketOpen() {
  const now = new Date();

  // Returns { hm: minutes-since-midnight, isWeekday } in the given IANA timezone.
  function localInfo(tz) {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: tz,
      weekday: 'short',
      hour: 'numeric',
      minute: 'numeric',
      hour12: false,
    }).formatToParts(now);
    const weekday = parts.find(p => p.type === 'weekday').value;
    const h = parseInt(parts.find(p => p.type === 'hour').value, 10);
    const m = parseInt(parts.find(p => p.type === 'minute').value, 10);
    return { hm: h * 60 + m, isWeekday: weekday !== 'Sat' && weekday !== 'Sun' };
  }

  // NYSE / NASDAQ  (^SPX ^NDX ^DJI)  09:30–16:00 ET
  const et = localInfo('America/New_York');
  if (et.isWeekday && et.hm >= 570 && et.hm < 960) return true;

  // Euronext / Xetra  (^STOXX50E)  09:00–17:30 CET/CEST
  const de = localInfo('Europe/Berlin');
  if (de.isWeekday && de.hm >= 540 && de.hm < 1050) return true;

  // Tokyo  (^N225)  09:00–15:30 JST
  const jp = localInfo('Asia/Tokyo');
  if (jp.isWeekday && jp.hm >= 540 && jp.hm < 930) return true;

  // Seoul  (^KS11)  09:00–15:30 KST
  const kr = localInfo('Asia/Seoul');
  if (kr.isWeekday && kr.hm >= 540 && kr.hm < 930) return true;

  // Shanghai  (000001.SS)  09:30–15:00 CST
  const cn = localInfo('Asia/Shanghai');
  if (cn.isWeekday && cn.hm >= 570 && cn.hm < 900) return true;

  return false;
}

function startQuotesPoller(stripSelector, badgeSelector) {
  const INTERVAL_MS = 60_000;

  async function tick() {
    if (document.visibilityState === 'hidden') return;
    if (!isAnyMarketOpen()) return;
    try {
      const res = await fetch('/api/quotes');
      if (!res.ok) return;
      const data = await res.json();
      if (!data?.ok || !data?.payload?.cards?.length) return;
      const strip = document.querySelector(stripSelector);
      if (strip) strip.innerHTML = data.payload.cards.map(buildMetricPill).join('');
      const badge = document.querySelector(badgeSelector);
      if (badge && data.payload.generated_at) badge.textContent = `Updated ${data.payload.generated_at}`;
    } catch (_) {}
  }

  // Start after a short delay so initial full-payload render settles first
  setTimeout(() => {
    tick();
    setInterval(tick, INTERVAL_MS);
  }, 5_000);

  // Fire immediately when the user returns to the tab (if markets are open)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') tick();
  });
}

async function initMarketsPage() {
  const cacheKey = 'api_cache_markets';
  try {
    const cached = readSessionJson(cacheKey, 180000);
    if (cached) {
      renderMarketsPayload(cached);
      await renderMarketsVisuals(cached);
    }
    const payload = cached || await fetchApiCached('/api/markets', cacheKey, 180000);
    renderMarketsPayload(payload);
    await renderMarketsVisuals(payload);
    if (cached) {
      refreshCachedApi('/api/markets', cacheKey).then(async (fresh) => {
        renderMarketsPayload(fresh);
        await renderMarketsVisuals(fresh);
      }).catch(() => {});
    }
  }
  catch (error) {
    const message = error?.message || 'Unable to load markets dashboard.';
    ['#marketsIndexes', '#marketsRiskOn', '#marketsRiskOff', '#marketsTrendTable', '#marketsIndexComparisonChart', '#marketsMoversBox', '#marketsSectorLeaderChart', '#marketsSectorLaggardChart', '#marketsRiskDashboard', '#marketsReadSummary'].forEach((selector) => renderLoadError(selector, message));
  }

  // Fetch enrichment data → EPM Sentiment gauge + OECD CLI
  try {
    const enrichRes = await fetch('/api/enrichment');
    if (enrichRes.ok) {
      const enrichData = await enrichRes.json();
      if (enrichData.ok) {
        renderEPMGauge(enrichData);
        renderOECDCLI(enrichData.oecd_cli || {});
        renderSecInsider(enrichData.sec_insider || []);
      }
    }
  } catch (_) {}

  // Fetch commentary for the international section (Market Read card)
  try {
    const res = await fetch('/api/commentary');
    if (res.ok) {
      const data = await res.json();
      if (data.ok && data.commentary?.international_section) {
        const intlEl = document.getElementById('marketsInternational');
        if (intlEl) {
          intlEl.innerHTML = `
            <div class="briefing-intl-section">
              <div class="briefing-col-title">Global Context</div>
              <p class="market-copy">${escapeHtml(data.commentary.international_section)}</p>
            </div>`;
        }
      }
    }
  } catch (_) {}

  startQuotesPoller('#marketsIndexes', '#marketsGeneratedAt');
}

async function initPortfoliosPage() {
  const cacheKey = 'api_cache_portfolios';
  try {
    const cached = readSessionJson(cacheKey, 180000);
    if (cached) renderPortfoliosPayload(cached);
    const payload = cached || await fetchApiCached('/api/portfolios', cacheKey, 180000);
    renderPortfoliosPayload(payload);
    if (cached) {
      refreshCachedApi('/api/portfolios', cacheKey).then(renderPortfoliosPayload).catch(() => {});
    }
  }
  catch (error) {
    const message = error?.message || 'Unable to load portfolio dashboard.';
    ['#portfolioUniverseGrid', '#portfolioLeaders', '#portfolioLaggards'].forEach((selector) => renderLoadError(selector, message));
  }
}

function initPageData() {
  const page = document.body.dataset.page;
  if (page === "home") initHomePage();
  else if (page === "markets") initMarketsPage();
  else if (page === "portfolios") initPortfoliosPage();
}


function buildSearchUrl(ticker, includeNews = true) {
  const symbol = normalizeTickerValue(ticker);
  const params = new URLSearchParams();
  if (symbol) params.set("ticker", symbol);
  params.set("news", includeNews ? "1" : "0");
  const query = params.toString();
  return query ? `/search?${query}` : "/search";
}

async function fetchTickerSuggestions(query, limit = 15, signal) {
  const q = String(query || "").trim();
  const url = `/api/suggest-tickers?q=${encodeURIComponent(q)}&limit=${limit}`;
  const res = await fetch(url, { signal });
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error(data.detail || "Suggestion lookup failed");
  return sanitizeSuggestionResults(filterValidSuggestions(data.suggestions || []), q);
}

function sanitizeSuggestionResults(items, query = '') {
  const normalizedQuery = normalizeTickerValue(query).replace(/\./g, '');
  const seen = new Set();
  return [...(items || [])]
    .map((item) => ({
      ticker: normalizeTickerValue(item?.ticker || ''),
      name: String(item?.name || '').trim(),
    }))
    .filter((item) => {
      if (!item.ticker || seen.has(item.ticker)) return false;
      const upperName = item.name.toUpperCase();
      if (item.ticker.length <= 3 && (!item.name || upperName === item.ticker)) return false;
      if (normalizedQuery) {
        const comparableTicker = item.ticker.replace(/\./g, '');
        const comparableName = upperName.replace(/[^A-Z0-9]/g, '');
        if (!comparableTicker.includes(normalizedQuery) && !comparableName.includes(normalizedQuery)) return false;
      }
      seen.add(item.ticker);
      return true;
    });
}

// ==========================================================================
// PROFILE CONSTANTS
// ==========================================================================

const PROFILE_COLORS = [
  '#2563eb', '#0ea5e9', '#10b981', '#7c3aed',
  '#e11d48', '#f97316', '#d97706', '#0d9488',
  '#9333ea', '#475569', '#b45309', '#0f766e',
];

const AVATAR_OPTIONS = [
  // Emoji
  '🦁','🔥','⭐','💎','🚀','🌊','⚡','🎯',
  '🦅','🐉','🌙','☀️','🏔️','🌿','🎭','💫',
  '🦊','🐺','🎲','🔮',
  // Geometric symbols
  '◆','▲','●','★','✦','⬡','◉','✿',
];

// ==========================================================================
// SETTINGS PROFILE SECTION
// ==========================================================================

function _renderSettingsProfile() {
  const drawer = document.getElementById('settingsDrawer');
  if (!drawer) return;
  drawer.querySelector('.sp-profile-section')?.remove();

  const state = document.body.dataset.authState;
  const section = document.createElement('div');
  section.className = 'sp-profile-section settings-group';

  if (state !== 'member') {
    return; // guests: drawer shows only Theme + Animations, no auth prompt
  } else {
    const prefs   = epmGetCachedPrefs() || {};
    const username = localStorage.getItem('epm_username') || '';
    const color   = prefs.profile_color  || '#2563eb';
    const avatar  = prefs.profile_avatar || '';
    const initial = (username || 'U')[0].toUpperCase();
    const display = avatar || initial;

    section.innerHTML = `
      <h4>Profile</h4>
      <div class="sp-avatar-row">
        <div class="sp-avatar" id="spAvatarPreview" style="background:${escapeHtml(color)}">${escapeHtml(display)}</div>
        <div class="sp-user-info">
          <span class="sp-username-text" id="spUsernameDisplay">${escapeHtml(username)}</span>
        </div>
      </div>

      <button class="sp-customize-btn" id="spCustomizeBtn" type="button">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        Customize Profile
      </button>

      <div class="sp-customize-panel" id="spCustomizePanel">
        <div class="sp-section-label">Color</div>
        <div class="sp-color-grid" id="spColorGrid">
          ${PROFILE_COLORS.map(c => `<button class="sp-color-swatch${c === color ? ' active' : ''}" style="background:${c}" data-color="${c}" type="button" aria-label="Profile color ${c}"></button>`).join('')}
        </div>

        <div class="sp-section-label">Avatar</div>
        <div class="sp-char-grid" id="spCharGrid">
          <button class="sp-char-btn${!avatar ? ' active' : ''}" data-char="" type="button" title="Your initial">${escapeHtml(initial)}</button>
          ${AVATAR_OPTIONS.map(ch => `<button class="sp-char-btn${avatar === ch ? ' active' : ''}" data-char="${ch}" type="button">${ch}</button>`).join('')}
        </div>

        <div class="sp-section-label">Username</div>
        <div class="sp-username-form" id="spUsernameForm">
          <input class="sp-input" id="spNewUsername" placeholder="New username" maxlength="40" autocomplete="off" />
          <input class="sp-input" id="spCurrentPassword" type="password" placeholder="Current password" autocomplete="current-password" />
          <div class="sp-form-row">
            <button class="sp-btn-primary" id="spUsernameSubmit" type="button">Save</button>
          </div>
          <div class="sp-form-msg" id="spUsernameMsg"></div>
        </div>
      </div>

      <button class="sp-signout-btn" id="spSignOutBtn" type="button">Sign Out</button>`;

    _wireProfileEvents(section, color, avatar);
  }

  // Insert after the drawer's title row
  const titleRow = drawer.querySelector('.section-title-row');
  if (titleRow) titleRow.insertAdjacentElement('afterend', section);
  else drawer.prepend(section);
}

function _wireProfileEvents(section, currentColor, currentAvatar) {
  let activeColor  = currentColor;
  let activeAvatar = currentAvatar;
  let saveTimer    = null;

  function saveProfile(color, avatar) {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      try {
        const res = await fetch('/api/user/prefs', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ profile_color: color, profile_avatar: avatar }),
        });
        if (res.ok) {
          const data = await res.json();
          try { localStorage.setItem('epm_user_prefs', JSON.stringify(data.prefs || {})); } catch (_) {}
        }
      } catch (_) {}
    }, 400);
  }

  function updateAvatarPreview(color, avatar) {
    const preview = section.querySelector('#spAvatarPreview');
    if (!preview) return;
    const username = localStorage.getItem('epm_username') || 'U';
    const initial  = username[0].toUpperCase();
    preview.style.background = color;
    preview.textContent = avatar || initial;
    // Also update the topbar badge live
    const badgeAvatar = document.querySelector('.user-badge-avatar');
    if (badgeAvatar) {
      badgeAvatar.style.background = color;
      badgeAvatar.textContent = avatar || initial;
    }
  }

  // Color swatches
  section.querySelector('#spColorGrid')?.addEventListener('click', e => {
    const swatch = e.target.closest('.sp-color-swatch');
    if (!swatch) return;
    activeColor = swatch.dataset.color;
    section.querySelectorAll('.sp-color-swatch').forEach(s => s.classList.toggle('active', s === swatch));
    updateAvatarPreview(activeColor, activeAvatar);
    saveProfile(activeColor, activeAvatar);
  });

  // Avatar chars
  section.querySelector('#spCharGrid')?.addEventListener('click', e => {
    const btn = e.target.closest('.sp-char-btn');
    if (!btn) return;
    activeAvatar = btn.dataset.char;
    section.querySelectorAll('.sp-char-btn').forEach(b => b.classList.toggle('active', b === btn));
    updateAvatarPreview(activeColor, activeAvatar);
    saveProfile(activeColor, activeAvatar);
  });

  // Customize Profile panel toggle
  section.querySelector('#spCustomizeBtn')?.addEventListener('click', () => {
    const panel = section.querySelector('#spCustomizePanel');
    const btn   = section.querySelector('#spCustomizeBtn');
    const isOpen = panel.classList.contains('open');
    panel.classList.toggle('open', !isOpen);
    btn.classList.toggle('active', !isOpen);
  });

  section.querySelector('#spUsernameSubmit')?.addEventListener('click', async () => {
    const newUsername = section.querySelector('#spNewUsername').value.trim();
    const password    = section.querySelector('#spCurrentPassword').value;
    const msgEl       = section.querySelector('#spUsernameMsg');
    msgEl.className   = 'sp-form-msg';
    msgEl.textContent = '';

    if (!newUsername) { msgEl.className = 'sp-form-msg err'; msgEl.textContent = 'Enter a new username.'; return; }
    if (!password)    { msgEl.className = 'sp-form-msg err'; msgEl.textContent = 'Enter your current password.'; return; }

    const submitBtn = section.querySelector('#spUsernameSubmit');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Saving…';

    try {
      const res = await fetch('/api/user/username', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_username: newUsername, password }),
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        // Server sets a refreshed HttpOnly cookie; just update cached display data.
        try { localStorage.setItem('epm_username', data.user.username); } catch (_) {}
        // Update topbar badge name
        const badgeName = document.querySelector('.user-badge-name');
        if (badgeName) badgeName.textContent = data.user.username;
        section.querySelector('#spUsernameDisplay').textContent = data.user.username;
        msgEl.className = 'sp-form-msg ok';
        msgEl.textContent = 'Username updated!';
        section.querySelector('#spNewUsername').value = '';
        section.querySelector('#spCurrentPassword').value = '';
        setTimeout(() => { msgEl.textContent = ''; }, 1800);
      } else {
        msgEl.className = 'sp-form-msg err';
        msgEl.textContent = data.detail || 'Could not update username.';
      }
    } catch (_) {
      msgEl.className = 'sp-form-msg err';
      msgEl.textContent = 'Network error. Try again.';
    }
    submitBtn.disabled = false;
    submitBtn.textContent = 'Save';
  });

  // Enter key on username form
  section.querySelector('#spCurrentPassword')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') section.querySelector('#spUsernameSubmit').click();
  });

  // Sign out
  section.querySelector('#spSignOutBtn')?.addEventListener('click', async () => {
    await epmClearToken();
    document.body.dataset.authState = 'guest';
    mountAuthActions('guest', '');
    document.getElementById('settingsDrawer').classList.remove('open');
    document.getElementById('settingsOverlay').classList.remove('show');
    document.body.classList.remove('settings-open');
    const page = document.body.dataset.page;
    if (page === 'forecasting' || page === 'portfolios') {
      document.body.dataset.authState = 'guest';
    }
  });
}

// ==========================================================================
// AUTH ACTIONS — Sign In button (guest) or user badge (member) in topbar
// ==========================================================================

function mountAuthActions(state, username) {
  const topActions = document.querySelector('.topbar .top-actions');
  if (!topActions) return;

  // Remove both the injected sign-in button and user badge before re-mounting
  topActions.querySelector('.user-badge')?.remove();
  topActions.querySelector('.topbar-signin-btn')?.remove();

  const settingsBtn = topActions.querySelector('#openSettingsBtn');

  if (state === 'member') {
    const badge = document.createElement('div');
    badge.className = 'user-badge';
    const prefs   = epmGetCachedPrefs() || {};
    const color   = prefs.profile_color  || '#2563eb';
    const avatar  = prefs.profile_avatar || '';
    const initial = (username || 'U')[0].toUpperCase();
    const display = avatar || initial;
    badge.innerHTML = `
      <span class="user-badge-avatar" style="background:${escapeHtml(color)}">${escapeHtml(display)}</span>
      <span class="user-badge-name">${escapeHtml(username || 'User')}</span>
      <button class="user-badge-logout btn btn-ghost" type="button" title="Sign out" aria-label="Sign out">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
          <polyline points="16 17 21 12 16 7"/>
          <line x1="21" y1="12" x2="9" y2="12"/>
        </svg>
      </button>`;
    if (settingsBtn) topActions.insertBefore(badge, settingsBtn);
    else topActions.prepend(badge);
    badge.querySelector('.user-badge-logout').addEventListener('click', async () => {
      await epmClearToken();
      document.body.dataset.authState = 'guest';
      mountAuthActions('guest', '');
      const page = document.body.dataset.page;
      if (page === 'forecasting' || page === 'portfolios') {
        document.body.dataset.authState = 'guest';
      }
    });
  } else {
    // guest: inject Sign In button that opens the auth drawer
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'topbar-signin-btn';
    btn.textContent = 'Sign In';
    btn.addEventListener('click', openAuthDrawer);
    if (settingsBtn) topActions.insertBefore(btn, settingsBtn);
    else topActions.appendChild(btn);
  }
}

// ==========================================================================
// AUTH DRAWER — slide-in modal with Login / Register / Forgot tabs
// ==========================================================================

function openAuthDrawer() {
  document.getElementById('authDrawer')?.remove();
  document.getElementById('authDrawerOverlay')?.remove();

  const overlay = document.createElement('div');
  overlay.id = 'authDrawerOverlay';
  overlay.className = 'epm-signin-overlay';

  const drawer = document.createElement('div');
  drawer.id = 'authDrawer';
  drawer.className = 'epm-signin-drawer';
  drawer.setAttribute('role', 'dialog');
  drawer.setAttribute('aria-modal', 'true');
  drawer.setAttribute('aria-label', 'Sign in or create account');

  drawer.innerHTML = `
    <div class="epm-signin-header">
      <div class="epm-signin-tabs">
        <button class="epm-signin-tab active" data-tab="login">Sign In</button>
        <button class="epm-signin-tab" data-tab="register">Create Account</button>
      </div>
      <button class="epm-signin-close" type="button" aria-label="Close">&times;</button>
    </div>

    <div class="epm-signin-msg" id="adMsg"></div>

    <!-- Login panel -->
    <div class="epm-signin-panel" id="adPanelLogin">
      <form id="adLoginForm" autocomplete="on" novalidate>
        <div class="epm-signin-field">
          <label class="epm-signin-label">Username</label>
          <input class="epm-signin-input" type="text" id="adLoginUser" placeholder="Your username" autocomplete="username" />
        </div>
        <div class="epm-signin-field">
          <label class="epm-signin-label">Password</label>
          <input class="epm-signin-input" type="password" id="adLoginPass" placeholder="Your password" autocomplete="current-password" />
        </div>
        <label class="epm-signin-remember">
          <input type="checkbox" id="adRemember" />
          <span>Remember me on this device</span>
          <span class="epm-signin-remember-hint" id="adRememberHint">30 days</span>
        </label>
        <button class="epm-signin-btn-primary" type="submit" id="adLoginBtn">Sign In</button>
        <div class="epm-signin-forgot-row">
          <a class="epm-signin-forgot-link" id="adForgotLink">Forgot password?</a>
        </div>
      </form>
    </div>

    <!-- Register panel -->
    <div class="epm-signin-panel hidden" id="adPanelRegister">
      <form id="adRegForm" autocomplete="on" novalidate>
        <div class="epm-signin-field">
          <label class="epm-signin-label">Username</label>
          <input class="epm-signin-input" type="text" id="adRegUser" placeholder="Choose a username" autocomplete="username" />
        </div>
        <div class="epm-signin-field">
          <label class="epm-signin-label">Email Address</label>
          <input class="epm-signin-input" type="email" id="adRegEmail" placeholder="you@example.com" autocomplete="email" />
          <div class="epm-signin-hint">Required for password recovery. Never shared.</div>
        </div>
        <div class="epm-signin-field">
          <label class="epm-signin-label">Password</label>
          <input class="epm-signin-input" type="password" id="adRegPass" placeholder="Min. 6 characters" autocomplete="new-password" />
        </div>
        <button class="epm-signin-btn-primary" type="submit" id="adRegBtn">Create Account</button>
      </form>
    </div>

    <!-- Forgot password panel -->
    <div class="epm-signin-panel hidden" id="adPanelForgot">
      <p class="epm-signin-forgot-desc">Enter your email and we&rsquo;ll send a reset link if an account exists.</p>
      <form id="adForgotForm" novalidate>
        <div class="epm-signin-field">
          <label class="epm-signin-label">Email Address</label>
          <input class="epm-signin-input" type="email" id="adForgotEmail" placeholder="your@email.com" autocomplete="email" />
        </div>
        <button class="epm-signin-btn-primary" type="submit" id="adForgotBtn">Send Reset Link</button>
        <div class="epm-signin-forgot-row">
          <a class="epm-signin-forgot-link" id="adBackToLogin">Back to Sign In</a>
        </div>
      </form>
    </div>`;

  document.body.appendChild(overlay);
  document.body.appendChild(drawer);
  document.body.classList.add('epm-signin-open');
  requestAnimationFrame(() => requestAnimationFrame(() => drawer.classList.add('epm-signin-drawer--visible')));

  const close = () => {
    drawer.classList.remove('epm-signin-drawer--visible');
    setTimeout(() => { drawer.remove(); overlay.remove(); document.body.classList.remove('epm-signin-open'); }, 280);
  };
  drawer.querySelector('.epm-signin-close').addEventListener('click', close);
  overlay.addEventListener('click', close);

  // Tab switching
  drawer.querySelectorAll('.epm-signin-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      drawer.querySelectorAll('.epm-signin-tab').forEach((t) => t.classList.remove('active'));
      tab.classList.add('active');
      const which = tab.dataset.tab;
      drawer.querySelector('#adPanelLogin').classList.toggle('hidden', which !== 'login');
      drawer.querySelector('#adPanelRegister').classList.toggle('hidden', which !== 'register');
      drawer.querySelector('#adPanelForgot').classList.add('hidden');
      document.getElementById('adMsg').className = 'epm-signin-msg';
      document.getElementById('adMsg').textContent = '';
    });
  });

  // Remember me hint
  const rememberBox = drawer.querySelector('#adRemember');
  const rememberHint = drawer.querySelector('#adRememberHint');
  rememberBox.addEventListener('change', () => {
    rememberHint.textContent = rememberBox.checked ? '30 days' : '3 days';
  });

  // Forgot password toggle
  drawer.querySelector('#adForgotLink').addEventListener('click', () => {
    drawer.querySelector('#adPanelLogin').classList.add('hidden');
    drawer.querySelector('#adPanelForgot').classList.remove('hidden');
    drawer.querySelectorAll('.epm-signin-tab').forEach((t) => t.classList.remove('active'));
  });
  drawer.querySelector('#adBackToLogin').addEventListener('click', () => {
    drawer.querySelector('#adPanelForgot').classList.add('hidden');
    drawer.querySelector('#adPanelLogin').classList.remove('hidden');
    const loginTab = drawer.querySelector('[data-tab="login"]');
    if (loginTab) loginTab.classList.add('active');
  });

  function showMsg(text, type) {
    const el = document.getElementById('adMsg');
    el.textContent = text;
    el.className = 'epm-signin-msg epm-signin-msg--' + type;
  }

  function onAuthSuccess(data) {
    // Server sets the HttpOnly cookie; we only cache display data locally.
    try { localStorage.setItem('epm_username', data.user.username); } catch (_) {}
    try { localStorage.setItem('epm_user_prefs', JSON.stringify(data.prefs || {})); } catch (_) {}
    close();
    _applyAuthState('member', data.user.username);
    // If on a gated page, trigger data load
    const page = document.body.dataset.page;
    if (page === 'forecasting' || page === 'portfolios') initPageData();
  }

  // Login submit
  drawer.querySelector('#adLoginForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const username   = document.getElementById('adLoginUser').value.trim();
    const password   = document.getElementById('adLoginPass').value;
    const rememberMe = rememberBox.checked;
    if (!username || !password) { showMsg('Please enter username and password.', 'error'); return; }
    const btn = document.getElementById('adLoginBtn');
    btn.disabled = true; btn.textContent = 'Signing in\u2026';
    try {
      const res  = await fetch('/api/auth/login', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ username, password, remember_me: rememberMe }) });
      const data = await res.json();
      if (!res.ok || !data.ok) { showMsg(data.detail || 'Sign in failed.', 'error'); btn.disabled=false; btn.textContent='Sign In'; return; }
      onAuthSuccess(data);
    } catch (_) { showMsg('Network error.', 'error'); btn.disabled=false; btn.textContent='Sign In'; }
  });

  // Register submit
  drawer.querySelector('#adRegForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('adRegUser').value.trim();
    const email    = document.getElementById('adRegEmail').value.trim();
    const password = document.getElementById('adRegPass').value;
    if (!username || !email || !password) { showMsg('All fields are required.', 'error'); return; }
    const btn = document.getElementById('adRegBtn');
    btn.disabled = true; btn.textContent = 'Creating\u2026';
    try {
      const res  = await fetch('/api/auth/register', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ username, email, password }) });
      const data = await res.json();
      if (!res.ok || !data.ok) { showMsg(data.detail || 'Registration failed.', 'error'); btn.disabled=false; btn.textContent='Create Account'; return; }
      onAuthSuccess(data);
    } catch (_) { showMsg('Network error.', 'error'); btn.disabled=false; btn.textContent='Create Account'; }
  });

  // Forgot password submit
  drawer.querySelector('#adForgotForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('adForgotEmail').value.trim();
    if (!email) { showMsg('Please enter your email.', 'error'); return; }
    const btn = document.getElementById('adForgotBtn');
    btn.disabled = true; btn.textContent = 'Sending\u2026';
    try {
      const res  = await fetch('/api/auth/forgot-password', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ email }) });
      const data = await res.json();
      showMsg(data.message || 'If that email is registered, a reset link has been sent.', 'info');
    } catch (_) { showMsg('Network error.', 'error'); }
    btn.disabled = false; btn.textContent = 'Send Reset Link';
  });

  // Focus first field
  setTimeout(() => drawer.querySelector('#adLoginUser')?.focus(), 80);
}

// storeToken removed — tokens are now set as HttpOnly cookies by the server.

// ==========================================================================
// WATCHLIST EDITOR MODAL — home page featured watchlist customization
// ==========================================================================

function mountWatchlistEditor(currentTickers, onSave) {
  // Remove any existing modal
  document.getElementById('watchlistModal')?.remove();
  document.getElementById('watchlistOverlay')?.remove();

  const overlay = document.createElement('div');
  overlay.id = 'watchlistOverlay';
  overlay.className = 'wl-overlay';

  const modal = document.createElement('div');
  modal.id = 'watchlistModal';
  modal.className = 'wl-modal';
  modal.innerHTML = `
    <div class="wl-header">
      <div>
        <h3 class="wl-title">Edit Featured Watchlist</h3>
        <p class="wl-subtitle">Up to 8 tickers displayed on your home dashboard.</p>
      </div>
      <button class="wl-close btn btn-ghost" type="button" aria-label="Close">&times;</button>
    </div>
    <div class="wl-chips" id="wlChips"></div>
    <form class="wl-add-row" id="wlAddForm" autocomplete="off">
      <div class="search-input-stack wl-search-stack">
        <div class="search-input-shell wl-search-shell">
          <span class="search-input-icon" aria-hidden="true">⌕</span>
          <input id="wlTickerInput" type="text" placeholder="Add ticker, e.g. AAPL" maxlength="12" />
        </div>
        <div id="wlSuggestions" class="ticker-suggestions hidden"></div>
      </div>
      <button class="btn btn-primary wl-add-btn" type="submit">Add</button>
    </form>
    <div class="wl-actions">
      <button class="btn btn-ghost wl-cancel" type="button">Cancel</button>
      <button class="btn btn-primary wl-save" type="button" id="wlSaveBtn">Save Watchlist</button>
    </div>
    <div class="wl-status" id="wlStatus"></div>`;

  document.body.appendChild(overlay);
  document.body.appendChild(modal);
  document.body.classList.add('wl-open');

  // ---- ticker chips ----
  let tickers = [...currentTickers];

  function renderChips() {
    const el = document.getElementById('wlChips');
    if (!el) return;
    if (!tickers.length) {
      el.innerHTML = '<span class="wl-empty">No tickers added yet.</span>';
      return;
    }
    el.innerHTML = tickers.map((t, i) => `
      <span class="wl-chip">
        <span class="wl-chip-label">${escapeHtml(t)}</span>
        <button class="wl-chip-remove" type="button" data-index="${i}" aria-label="Remove ${escapeHtml(t)}">&times;</button>
      </span>`).join('');
    el.querySelectorAll('.wl-chip-remove').forEach((btn) => {
      btn.addEventListener('click', () => {
        tickers.splice(Number(btn.dataset.index), 1);
        renderChips();
      });
    });
  }
  renderChips();

  // ---- add via form ----
  const addForm   = document.getElementById('wlAddForm');
  const addInput  = document.getElementById('wlTickerInput');
  const sugBox    = document.getElementById('wlSuggestions');
  let sugItems    = [];
  let sugActive   = -1;
  let sugTimer    = null;
  let sugCtrl     = null;

  function hideSug() { sugItems = []; sugActive = -1; sugBox.innerHTML = ''; sugBox.classList.add('hidden'); }
  function updateSugActive() {
    sugBox.querySelectorAll('.ticker-suggestion').forEach((n, i) => n.classList.toggle('active', i === sugActive));
  }
  function addTicker(raw) {
    const t = normalizeTickerValue(raw || addInput.value);
    if (!t || tickers.includes(t) || tickers.length >= 8) return;
    tickers.push(t);
    addInput.value = '';
    hideSug();
    renderChips();
  }

  addForm.addEventListener('submit', (e) => { e.preventDefault(); addTicker(); });
  addInput.addEventListener('input', () => {
    if (sugTimer) clearTimeout(sugTimer);
    sugTimer = setTimeout(async () => {
      const q = addInput.value.trim();
      if (!q) return hideSug();
      if (sugCtrl) sugCtrl.abort();
      sugCtrl = new AbortController();
      try {
        const results = await fetchTickerSuggestions(q, 6, sugCtrl.signal);
        sugItems = results;
        sugActive = results.length ? 0 : -1;
        if (!results.length) return hideSug();
        sugBox.innerHTML = results.map((item, idx) => `
          <button class="ticker-suggestion ${idx === 0 ? 'active' : ''}" type="button" data-index="${idx}">
            <span class="ticker-suggestion-symbol">${escapeHtml(item.ticker)}</span>
            <span class="ticker-suggestion-name">${escapeHtml(item.name)}</span>
          </button>`).join('');
        sugBox.classList.remove('hidden');
      } catch (_) { hideSug(); }
    }, 120);
  });
  addInput.addEventListener('keydown', (e) => {
    const open = sugItems.length && !sugBox.classList.contains('hidden');
    if (e.key === 'ArrowDown' && open) { e.preventDefault(); sugActive = (sugActive + 1) % sugItems.length; updateSugActive(); return; }
    if (e.key === 'ArrowUp'   && open) { e.preventDefault(); sugActive = (sugActive - 1 + sugItems.length) % sugItems.length; updateSugActive(); return; }
    if (e.key === 'Escape') return hideSug();
    if (e.key === 'Enter' && open && sugActive >= 0) { e.preventDefault(); addTicker(sugItems[sugActive].ticker); }
  });
  sugBox.addEventListener('mousedown', (e) => {
    const btn = e.target.closest('.ticker-suggestion');
    if (!btn) return;
    e.preventDefault();
    addTicker(sugItems[Number(btn.dataset.index)]?.ticker);
  });
  document.addEventListener('click', (e) => {
    if (!addForm.contains(e.target)) hideSug();
  }, { once: false, capture: false });

  // ---- close ----
  const close = () => {
    modal.remove(); overlay.remove();
    document.body.classList.remove('wl-open');
  };
  modal.querySelector('.wl-close').addEventListener('click', close);
  modal.querySelector('.wl-cancel').addEventListener('click', close);
  overlay.addEventListener('click', close);

  // ---- save ----
  document.getElementById('wlSaveBtn').addEventListener('click', async () => {
    const saveBtn = document.getElementById('wlSaveBtn');
    const statusEl = document.getElementById('wlStatus');
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving\u2026';
    const ok = await epmSavePrefs({ featured_tickers: tickers });
    if (ok) {
      statusEl.textContent = 'Saved!';
      statusEl.className = 'wl-status wl-status--ok';
      setTimeout(() => { close(); onSave(tickers); }, 600);
    } else {
      statusEl.textContent = 'Failed to save. Are you logged in?';
      statusEl.className = 'wl-status wl-status--err';
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save Watchlist';
    }
  });
}

function mountWatchlistEditBtn(currentTickers, onSave) {
  const section = document.querySelector('#homeFeaturedCards')?.closest('.card');
  if (!section || section.querySelector('.wl-edit-btn')) return;
  const titleRow = section.querySelector('.section-title-row');
  if (!titleRow) return;
  const btn = document.createElement('button');
  btn.className = 'btn btn-ghost wl-edit-btn';
  btn.type = 'button';
  btn.textContent = 'Edit';
  btn.title = 'Customize your featured watchlist';
  btn.addEventListener('click', () => {
    const isGuest = document.body.dataset.authState !== 'member';
    if (isGuest) {
      // Show a friendly sign-in nudge instead of the editor
      showWatchlistSignInNudge(section);
    } else {
      mountWatchlistEditor(currentTickers, onSave);
    }
  });
  titleRow.appendChild(btn);
}

function showWatchlistSignInNudge(section) {
  if (section.querySelector('.wl-signin-nudge')) return;
  const nudge = document.createElement('div');
  nudge.className = 'wl-signin-nudge';
  nudge.innerHTML = `
    <span class="wl-nudge-icon">&#128274;</span>
    <span>Sign in to personalize your watchlist with any tickers you want.</span>
    <button class="wl-nudge-signin" type="button">Sign In</button>
    <button class="wl-nudge-dismiss" type="button" aria-label="Dismiss">&times;</button>`;
  nudge.querySelector('.wl-nudge-signin').addEventListener('click', () => { openAuthDrawer(); });
  nudge.querySelector('.wl-nudge-dismiss').addEventListener('click', () => nudge.remove());
  section.querySelector('.section-title-row').insertAdjacentElement('afterend', nudge);
  setTimeout(() => nudge.remove(), 8000);
}

// ==========================================================================

function mountGlobalHeaderSearch() {
  const topbar = document.querySelector('.topbar');
  if (!topbar) return;

  const brandBlock = topbar.querySelector('.brand-block');
  const topActions = topbar.querySelector('.top-actions');
  const mainNav = topbar.querySelector('.main-nav');
  if (!brandBlock || !topActions) return;
  topActions.querySelector('a[href="/download/current-report"]')?.remove();

  const page = inferPageKey();
  if (!document.body.dataset.page) document.body.dataset.page = page;

  const linkRecords = [];
  (mainNav ? [...mainNav.querySelectorAll('a')] : []).forEach((link) => {
    const href = link.getAttribute('href') || '#';
    const label = (link.textContent || '').trim();
    if (!label || href === '#') return;
    if (!linkRecords.some((record) => record.href === href)) linkRecords.push({ href, label });
  });
  [
    { href: '/', label: 'Home' },
    { href: '/markets', label: 'Markets' },
    { href: '/forecasting', label: 'Forecasting' },
    { href: '/portfolios', label: 'Model Portfolios' },
    { href: '/search', label: 'Fund Search' },
  ].forEach((record) => {
    if (!linkRecords.some((item) => item.href === record.href)) linkRecords.push(record);
  });
  const menuLinksMarkup = linkRecords.map((record) => `<a class="menu-link" href="${record.href}">${escapeHtml(record.label)}</a>`).join('');

  let menuToggle = brandBlock.querySelector('#menuToggleBtn');
  let menuPopover = document.getElementById('headerMenuPopover') || brandBlock.querySelector('#headerMenuPopover');
  let menuBackdrop = document.getElementById('headerMenuBackdrop');
  if (!menuToggle) {
    menuToggle = document.createElement('button');
    menuToggle.type = 'button';
    menuToggle.id = 'menuToggleBtn';
    menuToggle.className = 'menu-toggle';
    menuToggle.setAttribute('aria-label', 'Open site navigation');
    menuToggle.setAttribute('aria-expanded', 'false');
    menuToggle.innerHTML = '<span></span><span></span><span></span>';
    brandBlock.prepend(menuToggle);
  }
  if (!menuBackdrop) {
    menuBackdrop = document.createElement('button');
    menuBackdrop.type = 'button';
    menuBackdrop.id = 'headerMenuBackdrop';
    menuBackdrop.className = 'header-menu-backdrop hidden';
    menuBackdrop.setAttribute('aria-hidden', 'true');
    document.body.appendChild(menuBackdrop);
  }
  if (!menuPopover) {
    menuPopover = document.createElement('div');
    menuPopover.id = 'headerMenuPopover';
    menuPopover.className = 'header-menu-popover hidden';
    menuPopover.innerHTML = `
      <div class="header-menu-panel">
        <div class="header-menu-label">Navigate</div>
        <div class="header-menu-links">${menuLinksMarkup}</div>
      </div>`;
    document.body.appendChild(menuPopover);
  } else if (!menuPopover.parentElement || menuPopover.parentElement !== document.body) {
    document.body.appendChild(menuPopover);
  }
  const menuLinks = menuPopover.querySelector('.header-menu-links');
  if (menuLinks) menuLinks.innerHTML = menuLinksMarkup;
  // Keep .main-nav in DOM for Direction C inline desktop nav; hamburger still works via popover
  // mainNav?.remove();

  const params = new URLSearchParams(window.location.search);
  const startTicker = normalizeTickerValue(params.get('ticker') || params.get('t') || '');
  const rawNews = params.get('news') ?? localStorage.getItem('epm_include_news_pref') ?? 'true';
  const startNews = rawNews !== '0' && rawNews !== 'false';

  let searchSlot = brandBlock.querySelector('.header-search-slot');
  if (!searchSlot) {
    searchSlot = document.createElement('div');
    searchSlot.className = 'header-search-slot';
    searchSlot.innerHTML = `
      <form id="globalSearchForm" class="global-search-form" autocomplete="off">
        <div class="search-input-stack global-search-input-stack">
          <div class="search-input-shell header-search-shell">
            <span class="search-input-icon" aria-hidden="true">⌕</span>
            <input id="globalTickerInput" type="text" placeholder="Search ticker or fund, e.g. AAPL or CGDV" value="${escapeHtml(startTicker)}" />
          </div>
          <div id="globalTickerSuggestions" class="ticker-suggestions hidden"></div>
        </div>
        <label class="inline global-search-inline">
          <input id="globalIncludeNews" type="checkbox" ${startNews ? 'checked' : ''} />
          Include news
        </label>
        <button id="globalSearchBtn" class="btn btn-primary" type="submit">Search</button>
      </form>`;
    brandBlock.appendChild(searchSlot);
  }

  const form = document.getElementById('globalSearchForm');
  const input = document.getElementById('globalTickerInput');
  const includeNews = document.getElementById('globalIncludeNews');
  const suggestionBox = document.getElementById('globalTickerSuggestions');
  const stack = brandBlock.querySelector('.global-search-input-stack');
  if (!form || !input || !includeNews || !suggestionBox || !stack) return;

  const syncSearchFocusState = () => {
    const hasFocus = form.contains(document.activeElement);
    form.classList.toggle('is-focused', hasFocus);
    form.classList.toggle('has-value', !!input.value.trim());
  };
  syncSearchFocusState();
  form.addEventListener('focusin', syncSearchFocusState);
  form.addEventListener('focusout', () => window.setTimeout(syncSearchFocusState, 0));
  input.addEventListener('input', syncSearchFocusState);

  let menuOpen = false;
  const positionMenu = () => {
    if (!menuPopover || !menuToggle) return;
    const rect = menuToggle.getBoundingClientRect();
    const panelWidth = Math.min(300, Math.max(248, window.innerWidth - 32));
    const left = Math.min(Math.max(16, rect.left), Math.max(16, window.innerWidth - panelWidth - 16));
    menuPopover.style.top = `${Math.round(rect.bottom + 12)}px`;
    menuPopover.style.left = `${Math.round(left)}px`;
    menuPopover.style.width = `${Math.round(panelWidth)}px`;
  };
  const setMenuState = (open) => {
    menuOpen = !!open;
    document.body.classList.toggle('menu-open', menuOpen);
    menuToggle.classList.toggle('is-open', menuOpen);
    menuToggle.setAttribute('aria-expanded', menuOpen ? 'true' : 'false');
    menuToggle.setAttribute('aria-label', menuOpen ? 'Close site navigation' : 'Open site navigation');
    menuPopover.setAttribute('aria-hidden', menuOpen ? 'false' : 'true');
    if (menuOpen) {
      positionMenu();
      menuBackdrop?.classList.remove('hidden');
      menuPopover.classList.remove('hidden');
      requestAnimationFrame(() => {
        menuBackdrop?.classList.add('show');
        menuPopover.classList.add('show');
      });
      return;
    }
    menuPopover.classList.remove('show');
    menuBackdrop?.classList.remove('show');
    window.setTimeout(() => {
      if (menuOpen) return;
      menuPopover.classList.add('hidden');
      menuBackdrop?.classList.add('hidden');
    }, 220);
  };
  const closeMenu = () => setMenuState(false);
  const openMenu = () => setMenuState(true);
  menuToggle.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    setMenuState(!menuOpen);
  });
  menuBackdrop?.addEventListener('click', closeMenu);
  menuPopover.addEventListener('click', (event) => event.stopPropagation());
  document.addEventListener('click', (event) => {
    if (!menuOpen) return;
    if (!brandBlock.contains(event.target) && !menuPopover.contains(event.target)) closeMenu();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeMenu();
  });
  window.addEventListener('resize', () => { if (menuOpen) positionMenu(); }, { passive: true });
  window.addEventListener('scroll', () => { if (menuOpen) positionMenu(); }, { passive: true });

  if (page === 'home') document.querySelector('.hero-card')?.remove();
  if (page === 'search') {
    // search.js owns the .search-bar on this page — do not remove it.
    return;
  }

  let items = [];
  let activeIndex = -1;
  let timer = null;
  let controller = null;

  const positionSuggestionOverlay = () => {};
  const hideSuggestions = () => {
    items = [];
    activeIndex = -1;
    suggestionBox.innerHTML = '';
    suggestionBox.classList.add('hidden');
  };
  const updateActive = () => {
    suggestionBox.querySelectorAll('.ticker-suggestion').forEach((node, idx) => {
      node.classList.toggle('active', idx === activeIndex);
    });
  };
  const goToTicker = (ticker) => {
    const symbol = normalizeTickerValue(ticker || input.value || '');
    if (!symbol) return;
    window.location.href = buildSearchUrl(symbol, includeNews.checked);
  };
  const renderSuggestions = (nextItems) => {
    items = sanitizeSuggestionResults(nextItems || [], input.value);
    activeIndex = items.length ? 0 : -1;
    if (!items.length) return hideSuggestions();
    suggestionBox.innerHTML = items.map((item, idx) => `
      <button class="ticker-suggestion ${idx === 0 ? 'active' : ''}" type="button" data-index="${idx}">
        <span class="ticker-suggestion-symbol">${escapeHtml(item.ticker || '')}</span>
        <span class="ticker-suggestion-name">${escapeHtml(item.name || '')}</span>
      </button>`).join('');
    suggestionBox.classList.remove('hidden');
  };
  const queue = (force = false) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(async () => {
      const query = input.value.trim();
      if (!force && query.length === 0 && document.activeElement !== input) return hideSuggestions();
      if (controller) controller.abort();
      controller = new AbortController();
      try {
        renderSuggestions(await fetchTickerSuggestions(query, 8, controller.signal));
      } catch (error) {
        if (error?.name !== 'AbortError') hideSuggestions();
      }
    }, force ? 0 : 120);
  };

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    goToTicker();
  });
  input.addEventListener('input', () => queue());
  input.addEventListener('focus', () => queue(true));
  input.addEventListener('keydown', (event) => {
    const hasSuggestions = items.length > 0 && !suggestionBox.classList.contains('hidden');
    if (event.key === 'ArrowDown' && hasSuggestions) {
      event.preventDefault();
      activeIndex = (activeIndex + 1) % items.length;
      updateActive();
      return;
    }
    if (event.key === 'ArrowUp' && hasSuggestions) {
      event.preventDefault();
      activeIndex = (activeIndex - 1 + items.length) % items.length;
      updateActive();
      return;
    }
    if (event.key === 'Escape') return hideSuggestions();
    if (event.key === 'Enter' && hasSuggestions && activeIndex >= 0) {
      event.preventDefault();
      goToTicker(items[activeIndex].ticker);
    }
  });
  suggestionBox.addEventListener('mousedown', (event) => {
    const btn = event.target.closest('.ticker-suggestion');
    if (!btn) return;
    event.preventDefault();
    const index = Number(btn.dataset.index);
    if (Number.isInteger(index) && items[index]) goToTicker(items[index].ticker);
  });
  window.addEventListener('scroll', hideSuggestions, { passive: true });
  document.addEventListener('click', (event) => {
    if (!stack.contains(event.target) && !suggestionBox.contains(event.target)) hideSuggestions();
  });
}

function mountTickerTape() {
  const shell = document.querySelector('.page-shell');
  const header = shell?.querySelector('.topbar');
  if (!shell || !header || shell.querySelector('#tickerTapeShell')) return;

  const tapeShell = document.createElement('section');
  tapeShell.id = 'tickerTapeShell';
  tapeShell.className = 'ticker-tape-shell fade-in';
  tapeShell.style.visibility = 'hidden';
  tapeShell.style.height = '0';
  tapeShell.style.overflow = 'hidden';
  tapeShell.innerHTML = `
    <div class="ticker-tape-viewport" aria-label="Live S&amp;P 500 ticker tape">
      <canvas id="tickerTapeCanvas" class="ticker-tape-canvas" aria-hidden="true"></canvas>
    </div>`;
  shell.insertBefore(tapeShell, header);

  const cacheKey = 'ticker_tape_items_v3';
  const metaKey = 'ticker_tape_meta_v3';
  const targetTotal = 100;
  const batchSize = 100;

  const sanitizeItems = (rawItems) => [...(rawItems || [])]
    .filter((item) => item && item.ticker)
    .sort((a, b) => String(a.ticker).localeCompare(String(b.ticker)));

  let cleanupCanvas = null;

  const renderCanvas = (rawItems) => {
    const items = sanitizeItems(rawItems).slice(0, targetTotal);
    if (!items.length) { tapeShell.remove(); return; }
    if (cleanupCanvas) cleanupCanvas();
    cleanupCanvas = mountTickerCanvas(items, tapeShell.querySelector('.ticker-tape-viewport'));
    // Reveal shell only once content is ready — prevents blank box flash
    tapeShell.style.visibility = '';
    tapeShell.style.height = '';
    tapeShell.style.overflow = '';
  };

  const mergeItems = (baseItems, newItems) => {
    const merged = new Map();
    sanitizeItems(baseItems).forEach((item) => merged.set(String(item.ticker), item));
    sanitizeItems(newItems).forEach((item) => merged.set(String(item.ticker), item));
    return sanitizeItems(Array.from(merged.values()));
  };

  const cached = readSessionJson(cacheKey, 300000);
  const cachedMeta = readSessionJson(metaKey, 300000) || { loaded: 0, total: targetTotal };
  let loaded = Number(cachedMeta.loaded || (Array.isArray(cached) ? cached.length : 0));
  let total = Number(cachedMeta.total || targetTotal);
  const cachedReady = Array.isArray(cached) && cached.length >= Math.min(total, targetTotal);
  if (cachedReady) renderCanvas(cached);

  const loadBatch = async (offset) => {
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => ctrl.abort(), 15000);
    try {
      const res = await fetch(`/api/ticker-tape?offset=${offset}&limit=${batchSize}&total=${targetTotal}`, { signal: ctrl.signal });
      window.clearTimeout(timer);
      const payload = res.ok ? await res.json() : null;
      const items = (payload && payload.items) || [];
      total = Number((payload && payload.total) || total || targetTotal);
      const merged = mergeItems(readSessionJson(cacheKey, 300000) || [], items).slice(0, targetTotal);
      if (items.length) {
        writeSessionJson(cacheKey, merged);
        loaded = Math.max(loaded, offset + items.length);
        writeSessionJson(metaKey, { loaded, total });
        renderCanvas(merged);
      } else if (!readSessionJson(cacheKey, 300000)) {
        tapeShell.remove();
      }
    } catch (_) {
      window.clearTimeout(timer);
      if (!readSessionJson(cacheKey, 300000)) tapeShell.remove();
    }
  };

  if (!cachedReady) {
    loadBatch(0);
  } else {
    window.setTimeout(() => loadBatch(0), 1200);
  }
}

function mountTickerCanvas(items, container) {
  const canvas = container.querySelector('#tickerTapeCanvas');
  if (!canvas) return null;

  const TAPE_H = 36;
  const ITEM_PAD = 18;
  const SEP_W = 1;
  const FONT_SYM = 'bold 11px Inter, system-ui, -apple-system, sans-serif';
  const FONT_DEL = 'bold 12px Inter, system-ui, -apple-system, sans-serif';

  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  let cssWidth = Math.max(container.clientWidth, 1);

  canvas.style.display = 'block';
  canvas.style.width = '100%';
  canvas.style.height = TAPE_H + 'px';
  canvas.width = cssWidth * dpr;
  canvas.height = TAPE_H * dpr;

  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  // Measure item widths using canvas text API for exact match
  const measured = items.map((item) => {
    ctx.font = FONT_SYM;
    const sw = ctx.measureText(item.ticker || '').width;
    ctx.font = FONT_DEL;
    const dw = ctx.measureText(fmtPct(item.day_change_pct)).width;
    return { item, sw, dw, w: SEP_W + ITEM_PAD + sw + 6 + dw + ITEM_PAD };
  });

  let totalWidth = 0;
  measured.forEach((m) => { m.x = totalWidth; totalWidth += m.w; });
  if (totalWidth < 1) return null;

  const durationSec = Math.max(180, Math.round(items.length * 1.8));
  const speed = totalWidth / durationSec; // px per second

  // Sync to persistent wall-clock start so all pages/tabs stay in phase
  const startKey = 'ticker_tape_started_at_v3';
  const existingStart = Number(localStorage.getItem(startKey) || 0);
  const startTime = existingStart > 0 ? existingStart : Date.now();
  if (!existingStart) localStorage.setItem(startKey, String(startTime));

  let offset = ((Date.now() - startTime) / 1000 * speed) % totalWidth;
  let lastTs = null;
  let rafId = null;
  const hitItems = [];

  const getColors = () => {
    const light = document.documentElement.dataset.theme === 'light';
    return {
      sym:  light ? '#163157' : '#eef3ff',
      up:   light ? '#298a58' : '#6ad29a',
      down: light ? '#c45454' : '#ff8a8a',
      mut:  light ? '#5f7397' : '#b5c4e2',
      sep:  light ? 'rgba(0,0,0,0.12)' : 'rgba(255,255,255,0.12)',
    };
  };

  const draw = (ts) => {
    if (lastTs !== null) {
      const dt = Math.min(ts - lastTs, 100) / 1000;
      offset = (offset + speed * dt) % totalWidth;
    }
    lastTs = ts;

    ctx.clearRect(0, 0, cssWidth, TAPE_H);
    hitItems.length = 0;
    const c = getColors();
    const cy = TAPE_H / 2;

    // Two passes for seamless loop (same as the old double-copy DOM approach)
    for (let pass = 0; pass < 2; pass++) {
      const base = pass * totalWidth;
      for (const m of measured) {
        const sx = m.x + base - offset;
        if (sx + m.w < -1 || sx > cssWidth + 1) continue;

        // Separator line
        ctx.fillStyle = c.sep;
        ctx.fillRect(sx, cy - 8, SEP_W, 16);

        let cx = sx + SEP_W + ITEM_PAD;

        // Ticker symbol
        ctx.font = FONT_SYM;
        ctx.fillStyle = c.sym;
        ctx.fillText(m.item.ticker || '', cx, cy + 4);
        cx += m.sw + 6;

        // Day change %
        ctx.font = FONT_DEL;
        const val = Number(m.item.day_change_pct);
        ctx.fillStyle = isNaN(val) ? c.mut : (val >= 0 ? c.up : c.down);
        ctx.fillText(fmtPct(m.item.day_change_pct), cx, cy + 4);

        hitItems.push({ x: sx, w: m.w, ticker: m.item.ticker || '' });
      }
    }

    rafId = requestAnimationFrame(draw);
  };

  rafId = requestAnimationFrame(draw);

  const onClick = (e) => {
    const rect = canvas.getBoundingClientRect();
    const scale = rect.width > 0 ? cssWidth / rect.width : 1;
    const cx = (e.clientX - rect.left) * scale;
    for (const h of hitItems) {
      if (cx >= h.x && cx < h.x + h.w) {
        window.location.href = `/search?ticker=${encodeURIComponent(h.ticker)}`;
        return;
      }
    }
  };

  const onMouseMove = (e) => {
    const rect = canvas.getBoundingClientRect();
    const scale = rect.width > 0 ? cssWidth / rect.width : 1;
    const cx = (e.clientX - rect.left) * scale;
    canvas.style.cursor = hitItems.some((h) => cx >= h.x && cx < h.x + h.w) ? 'pointer' : 'default';
  };

  canvas.addEventListener('click', onClick);
  canvas.addEventListener('mousemove', onMouseMove);

  const ro = new ResizeObserver(() => {
    const w = Math.max(container.clientWidth, 1);
    if (w === cssWidth) return;
    cssWidth = w;
    canvas.width = cssWidth * dpr;
    canvas.height = TAPE_H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  });
  ro.observe(container);

  return () => {
    if (rafId) cancelAnimationFrame(rafId);
    canvas.removeEventListener('click', onClick);
    canvas.removeEventListener('mousemove', onMouseMove);
    ro.disconnect();
  };
}

function setupHomeHeroSearch() {}

// ==========================================================================
// AI CHAT — floating market assistant powered by local Ollama
// ==========================================================================

function mountAIChat() {
  if (document.getElementById('aiChatBtn')) return; // already mounted

  // --- Floating trigger button ---
  const btn = document.createElement('button');
  btn.id = 'aiChatBtn';
  btn.className = 'ai-chat-btn';
  btn.type = 'button';
  btn.setAttribute('aria-label', 'Open AI market assistant');
  btn.title = 'AI Market Assistant';
  btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="22" height="22"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`;
  document.body.appendChild(btn);

  // --- Panel ---
  const panel = document.createElement('div');
  panel.id = 'aiChatPanel';
  panel.className = 'ai-chat-panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'false');
  panel.setAttribute('aria-label', 'AI Market Assistant');
  panel.innerHTML = `
    <div class="ai-chat-header">
      <div class="ai-chat-title">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        <span>Market Assistant</span>
        <span class="ai-chat-badge">AI</span>
      </div>
      <div class="ai-chat-header-actions">
        <button class="ai-chat-expand" type="button" aria-label="Expand chat" title="Expand">
          <svg class="icon-expand" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="13" height="13"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>
          <svg class="icon-collapse" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="13" height="13" style="display:none"><polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="10" y1="14" x2="3" y2="21"/><line x1="21" y1="3" x2="14" y2="10"/></svg>
        </button>
        <button class="ai-chat-close" type="button" aria-label="Close">&times;</button>
      </div>
    </div>
    <div class="ai-chat-messages" id="aiChatMessages">
      <div class="ai-chat-msg ai-chat-msg--assistant">
        <div class="ai-chat-bubble">Ask me about market conditions, forecasts, fund metrics, or portfolio strategy.</div>
      </div>
    </div>
    <form class="ai-chat-input-row" id="aiChatForm" autocomplete="off">
      <textarea class="ai-chat-input" id="aiChatInput" placeholder="Ask about markets, forecasts, funds…" autocomplete="off" maxlength="1000" rows="1"></textarea>
      <button class="ai-chat-send" type="submit" aria-label="Send" title="Send">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" width="17" height="17"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
      </button>
    </form>`;
  document.body.appendChild(panel);

  const messages = panel.querySelector('#aiChatMessages');
  const form = panel.querySelector('#aiChatForm');
  const input = panel.querySelector('#aiChatInput');
  const expandBtn = panel.querySelector('.ai-chat-expand');
  let history = [];
  let isOpen = false;
  let isExpanded = false;

  // Auto-resize textarea as user types
  function resizeInput() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 110) + 'px';
  }
  input.addEventListener('input', resizeInput);

  // Enter submits (Shift+Enter for newline)
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  // Prevent background page scroll while pointer is inside the panel
  panel.addEventListener('wheel', (e) => { e.stopPropagation(); }, { passive: false });

  // Expand / collapse toggle
  expandBtn.addEventListener('click', () => {
    isExpanded = !isExpanded;
    panel.classList.toggle('ai-chat-panel--expanded', isExpanded);
    expandBtn.querySelector('.icon-expand').style.display  = isExpanded ? 'none' : '';
    expandBtn.querySelector('.icon-collapse').style.display = isExpanded ? ''     : 'none';
    expandBtn.title = isExpanded ? 'Collapse' : 'Expand';
    messages.scrollTop = messages.scrollHeight;
  });

  function openPanel() {
    isOpen = true;
    panel.classList.add('ai-chat-panel--open');
    btn.classList.add('ai-chat-btn--active');
    setTimeout(() => input.focus(), 80);
  }

  function closePanel() {
    isOpen = false;
    isExpanded = false;
    panel.classList.remove('ai-chat-panel--open', 'ai-chat-panel--expanded');
    btn.classList.remove('ai-chat-btn--active');
    expandBtn.querySelector('.icon-expand').style.display  = '';
    expandBtn.querySelector('.icon-collapse').style.display = 'none';
    expandBtn.title = 'Expand';
  }

  btn.addEventListener('click', () => isOpen ? closePanel() : openPanel());
  panel.querySelector('.ai-chat-close').addEventListener('click', closePanel);

  function appendMsg(role, text) {
    const div = document.createElement('div');
    div.className = `ai-chat-msg ai-chat-msg--${role}`;
    const bubble = document.createElement('div');
    bubble.className = 'ai-chat-bubble';
    bubble.textContent = text;
    div.appendChild(bubble);
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return bubble;
  }

  function appendTyping() {
    const phases = [
      'Reading market data',
      'Processing your question',
      'Writing response',
    ];
    let phaseIdx = 0;

    const div = document.createElement('div');
    div.className = 'ai-chat-msg ai-chat-msg--assistant ai-chat-msg--typing';
    div.innerHTML = `
      <div class="ai-chat-bubble">
        <div class="ai-thinking-wrap">
          <span class="ai-thinking-label">${phases[0]}\u2026</span>
          <div class="ai-thinking-bar"></div>
          <div class="ai-thinking-dots">
            <span class="ai-typing-dot"></span>
            <span class="ai-typing-dot"></span>
            <span class="ai-typing-dot"></span>
          </div>
        </div>
      </div>`;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;

    const label = div.querySelector('.ai-thinking-label');
    const interval = setInterval(() => {
      phaseIdx = Math.min(phaseIdx + 1, phases.length - 1);
      label.textContent = phases[phaseIdx] + '\u2026';
    }, 2500);

    div._clearPhase = () => clearInterval(interval);
    return div;
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    input.disabled = true;

    appendMsg('user', text);
    const typing = appendTyping();

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history }),
      });
      const data = await res.json();
      typing._clearPhase && typing._clearPhase();
      typing.remove();
      if (!res.ok || !data.ok) {
        appendMsg('assistant', data.detail || 'Sorry, something went wrong. Please try again.');
      } else {
        appendMsg('assistant', data.reply);
        history.push({ role: 'user', content: text });
        history.push({ role: 'assistant', content: data.reply });
        if (history.length > 20) history = history.slice(-20);
      }
    } catch (_) {
      typing._clearPhase && typing._clearPhase();
      typing.remove();
      appendMsg('assistant', 'Network error. Please check your connection and try again.');
    }

    input.disabled = false;
    input.focus();
  });
}

mountGlobalHeaderSearch();

document.addEventListener("DOMContentLoaded", () => {
  mountSafeGlass();
  mountSettingsGearIcon();
  applyPreferences();
  setActiveNav();
  setupSettingsDrawer();
  setupSystemThemeListener();
  setupHomeHeroSearch();
  setupChromeEffects();

  // Set initial display state from cached username (sync), then validate cookie async.
  // Cookies are HttpOnly so JS can't read them — localStorage.epm_username is our proxy.
  const page = document.body.dataset.page;
  const hasCachedUser = !!localStorage.getItem('epm_username');
  const isGatedPage = page === 'forecasting' || page === 'portfolios';

  if (hasCachedUser) {
    // Optimistically show member UI — avoids Sign In button flash for returning users
    document.body.dataset.authState = 'member';
    document.querySelectorAll('.pw-guest-prompt').forEach(el => { el.style.display = 'none'; });
    mountAuthActions('member', localStorage.getItem('epm_username') || '');
    if (!isGatedPage) {
      // Public pages: start data load immediately, validate cookie in background
      initPageData();
    }
  } else {
    mountAuthActions('guest', '');
    if (!isGatedPage) {
      // Public pages load for everyone
      initPageData();
    } else {
      // Gated page with no cached user — show gate, don't load data yet
      document.body.dataset.authState = 'guest';
    }
  }
  // Always validate the cookie async — confirms or revokes optimistic state,
  // and triggers gated-page data load on member confirmation.
  epmCheckAuthState();

  mountTickerTape();
  warmBackgroundRoutes();
  mountAIChat();
});
