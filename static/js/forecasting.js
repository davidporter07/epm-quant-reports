/**
 * forecasting.js — MAG7 Forecast Dashboard
 * Fetches /api/forecasts + /api/forecast-chart-data and renders all sections.
 */

const MAG7_ORDER = ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'META', 'GOOG', 'TSLA'];
const CONFIDENCE_RANK = { High: 3, Medium: 2, Low: 1 };
const MODEL_LABELS = {
  ML: 'ML (Gradient Boost)',
  Linear: 'Linear Panel',
  ARIMAX: 'ARIMAX',
  DL: 'Deep Learning',
  Institutional: 'Institutional',
  QuantConnect: 'QuantConnect',
  FamaFrench: 'Fama-French',
};
const MODEL_COLORS = {
  ML:           '#60a5fa',
  Linear:       '#a78bfa',
  ARIMAX:       '#34d399',
  DL:           '#f472b6',
  Institutional:'#fb923c',
  QuantConnect: '#facc15',
  FamaFrench:   '#94a3b8',
};

// Per-ticker toggle state: true = model lines visible
const _showModelLines = {};

// ── Model Descriptions ───────────────────────────────────────────────────────
const MODEL_DESCRIPTIONS = [
  {
    key: 'ML',
    label: 'ML — Gradient Boosting',
    color: '#60a5fa',
    summary: 'A scikit-learn GradientBoostingRegressor trained on a cross-sectional feature table.',
    howItWorks: [
      'Uses 24 features per ticker: momentum returns (5/21/63/252-day), moving-average gaps, volatility, lagged returns, risk metrics (alpha, beta, Sharpe, max drawdown), factor z-scores (momentum, value, quality), and a 3-day sentiment score.',
      'For each daily run it selects the best candidate algorithm via a held-out validation window, then re-trains on the full history.',
      'Confidence intervals are ±1.96 × validation RMSE — a fixed-width band around each point estimate.',
      'Feature importances (which inputs the model weighted most heavily) are saved and can be inspected after each run.',
    ],
    bestAt: 'Picking up on composite factor signals and sentiment shifts over a 21-trading-day horizon.',
  },
  {
    key: 'Linear',
    label: 'Linear — Panel Regression',
    color: '#a78bfa',
    summary: 'A regularized linear model (Ridge/Lasso) fit to the same cross-sectional feature panel.',
    howItWorks: [
      'Estimates a single set of linear coefficients across all tickers and dates, treating the panel as a pooled regression.',
      'Regularization (L2 penalty) prevents any single feature from dominating when signals are correlated.',
      'Outputs a point estimate plus a simple analytical confidence interval derived from in-sample residual variance.',
    ],
    bestAt: 'Stable, interpretable baselines. Tends to outperform tree models during calm, mean-reverting markets.',
  },
  {
    key: 'ARIMAX',
    label: 'ARIMAX — Time-Series with Exogenous Inputs',
    color: '#34d399',
    summary: 'A per-ticker autoregressive model that adds exogenous (external) factor inputs to classic ARIMA.',
    howItWorks: [
      'Fits a separate ARIMA process for each ticker\'s return series, augmented with macro/factor inputs as exogenous regressors.',
      'Captures serial autocorrelation in returns — patterns like momentum persistence or mean reversion that repeat over time.',
      'Produces both a forecast and a prediction interval directly from the model\'s estimated noise structure.',
    ],
    bestAt: 'Tickers with strong autocorrelation in their return series (e.g., trending stocks or momentum-driven names).',
  },
  {
    key: 'DL',
    label: 'Deep Learning — TCN with Attention',
    color: '#f472b6',
    summary: 'A PyTorch Temporal Convolutional Network that learns directly from 60-day price sequences.',
    howItWorks: [
      'Processes a 60-trading-day window of approved price-sequence features (returns, volatility, and moving-average gaps) as a sequence.',
      'A FeatureGate layer (learnable sigmoid weights) lets the network discover which approved inputs are most predictive — and these weights are preserved across warm-start training runs.',
      'Four dilated TCN blocks with residual connections capture patterns at multiple time scales (days, weeks, months).',
      'A TemporalAttentionPool then learns which specific days within the 60-day window are most informative for the prediction, replacing a naive average.',
      'Outputs both a mean forecast (μ) and an uncertainty estimate (σ) trained via Gaussian negative log-likelihood — the per-ticker σ comes from the model\'s own learned uncertainty, not a fixed rule.',
      'The 95% band is then split-conformal calibrated: a multiplier measured on held-out matured forecasts replaces the textbook 1.96, so the interval has an honest empirical ~95% coverage instead of trusting the raw σ (which had been overconfident).',
      'Supports --warm-start: each training run loads the previous checkpoint and fine-tunes, so the model\'s knowledge compounds over time rather than resetting.',
    ],
    bestAt: 'Capturing non-linear temporal patterns and providing calibrated uncertainty estimates that vary per ticker.',
  },
  {
    key: 'Institutional',
    label: 'Institutional — Factor Model',
    color: '#fb923c',
    summary: 'A model built around institutional-grade risk factors: quality, value, momentum, and size.',
    howItWorks: [
      'Constructs composite factor scores (momentum_z, value_z, quality_z) normalized within the universe at each date.',
      'Combines factor exposures using a linear combination optimized on historical factor returns.',
      'Incorporates alpha and beta estimates relative to the S&P 500 to adjust raw factor signals for systematic risk.',
    ],
    bestAt: 'Tickers where fundamental quality or valuation signals dominate over short-term price momentum.',
  },
  {
    key: 'QuantConnect',
    label: 'QuantConnect — Algorithmic Strategy',
    color: '#facc15',
    summary: 'A rule-based quant strategy model inspired by systematic trading algorithms.',
    howItWorks: [
      'Combines technical signals (RSI, Bollinger Band position, moving average crossovers) with momentum filters.',
      'Applies position sizing logic: signals are weighted by their recent hit rate in backtests.',
      'Designed to mimic the output of a live algorithmic trading strategy that would be run in a real portfolio context.',
    ],
    bestAt: 'Identifying short-term technical setups with defined risk/reward characteristics.',
  },
  {
    key: 'FamaFrench',
    label: 'Fama-French — Academic Factor Model',
    color: '#94a3b8',
    summary: 'A three-to-five factor academic model adapted from the Fama-French research framework.',
    howItWorks: [
      'Regresses each ticker\'s returns against the classic Fama-French factors: Market (Mkt-RF), Size (SMB), Value (HML), Profitability (RMW), and Investment (CMA).',
      'Uses the fitted factor loadings (betas) combined with forward factor forecasts to project expected returns.',
      'Daily factor data is sourced from the Kenneth French Data Library and updated with each pipeline run.',
    ],
    bestAt: 'Long-horizon expected return estimates grounded in decades of academic research. Most reliable for value and size tilts.',
  },
];

function openModelsInfo() {
  const modal = document.getElementById('modelsInfoModal');
  const content = document.getElementById('modelsInfoContent');
  if (!modal || !content) return;

  const isDark = document.documentElement.dataset.theme !== 'light';
  const dividerColor = isDark ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.08)';
  const subtitleColor = 'var(--text-muted)';

  content.innerHTML = MODEL_DESCRIPTIONS.map((m, i) => `
    <div style="padding-bottom:20px;${i < MODEL_DESCRIPTIONS.length - 1 ? `border-bottom:1px solid ${dividerColor};margin-bottom:20px;` : ''}">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
        <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${m.color};flex-shrink:0;"></span>
        <span style="font-weight:700;font-size:13px;color:var(--text-primary);">${m.label}</span>
      </div>
      <p style="margin:0 0 10px;font-size:12px;color:${subtitleColor};line-height:1.55;">${m.summary}</p>
      <ul style="margin:0 0 8px;padding-left:18px;font-size:12px;color:var(--text-primary);line-height:1.6;">
        ${m.howItWorks.map(pt => `<li style="margin-bottom:4px;">${pt}</li>`).join('')}
      </ul>
      <div style="font-size:11px;color:${subtitleColor};"><strong style="color:${m.color};">Best at:</strong> ${m.bestAt}</div>
    </div>
  `).join('');

  modal.setAttribute('aria-hidden', 'false');
  modal.classList.add('is-open');
  document.body.style.overflow = 'hidden';
}

function closeModelsInfo() {
  const modal = document.getElementById('modelsInfoModal');
  if (!modal) return;
  modal.classList.remove('is-open');
  modal.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
}

function pct(v, digits = 2) {
  if (v === null || v === undefined) return '—';
  return (v >= 0 ? '+' : '') + (v * 100).toFixed(digits) + '%';
}

function metricPct(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  const pctValue = Math.abs(n) > 1 ? n : n * 100;
  return pctValue.toFixed(digits) + '%';
}

function confidenceClass(label) {
  if (!label) return '';
  const l = label.toLowerCase();
  if (l === 'high') return 'conf-high';
  if (l === 'medium') return 'conf-medium';
  return 'conf-low';
}

function signClass(v) {
  if (v === null || v === undefined) return '';
  return v >= 0 ? 'pos' : 'neg';
}

function renderCommentary(commentary) {
  const section = document.getElementById('commentarySection');
  if (!section || !commentary) return;

  const overview = commentary.portfolio_overview || '';
  const reflection = commentary.market_reflection || '';
  const bullets = commentary.top_bullets || [];

  section.innerHTML = `
    <div class="commentary-card fade-in">
      <div class="section-title-row">
        <h3>Daily Commentary</h3>
        <span class="badge">Model Pipeline</span>
      </div>
      ${overview ? `<p class="card-subtitle" style="margin-bottom:14px;">${overview}</p>` : ''}
      ${bullets.length ? `
        <ul class="commentary-bullets">
          ${bullets.map(b => `<li>${b}</li>`).join('')}
        </ul>
      ` : ''}
      ${reflection ? `<p class="commentary-reflection">${reflection}</p>` : ''}
    </div>
  `;
}

function renderForecastCards(tickers, asOf, chartDataMap) {
  const grid = document.getElementById('forecastGrid');
  if (!grid) return;

  const ordered = MAG7_ORDER.filter(t => tickers[t]).concat(
    Object.keys(tickers).filter(t => !MAG7_ORDER.includes(t))
  );

  grid.innerHTML = '';
  for (const ticker of ordered) {
    const d = tickers[ticker];
    const consensus = d.consensus;
    const dirClass = signClass(consensus);
    const confClass = confidenceClass(d.confidence_label);
    const agreePct = d.agreement_ratio !== null ? Math.round(d.agreement_ratio * 100) : null;
    const models = d.models || {};

    const modelRows = Object.entries(models)
      .map(([key, m]) => ({ key, label: MODEL_LABELS[key] || key, forecast: m.forecast }))
      .sort((a, b) => (b.forecast ?? -Infinity) - (a.forecast ?? -Infinity));

    const maxAbs = Math.max(...modelRows.map(r => Math.abs(r.forecast ?? 0)), 0.001);

    const modelRowsHTML = modelRows.map(({ key, label, forecast }) => {
      const isWinner = key === d.winning_model;
      const barPct = Math.min(100, Math.round((Math.abs(forecast ?? 0) / maxAbs) * 100));
      const barDir = (forecast ?? 0) >= 0 ? 'pos' : 'neg';
      return `
        <div class="model-row${isWinner ? ' model-row--winner' : ''}">
          <div class="model-row-bar ${barDir}" style="width:${barPct}%"></div>
          <span class="model-row-name">${label}${isWinner ? '<span class="winner-crown">★</span>' : ''}</span>
          <span class="model-row-val ${signClass(forecast)}">${pct(forecast)}</span>
        </div>
      `;
    }).join('');

    const card = document.createElement('div');
    card.className = `forecast-card fade-in card-${dirClass || 'neutral'}`;
    card.innerHTML = `
      <div class="forecast-card-header">
        <div class="forecast-card-id">
          <div class="forecast-card-ticker">${ticker}</div>
          <div class="forecast-card-name">${d.name || ticker}</div>
        </div>
        <div class="forecast-consensus-block">
          <div class="forecast-consensus ${dirClass}">${pct(consensus, 2)}</div>
          <div class="forecast-consensus-label">Consensus</div>
        </div>
      </div>
      <div class="forecast-card-meta">
        <span class="badge ${confClass}" title="Model consensus level — not realized forecast accuracy">${d.confidence_label || '—'} Agreement</span>
        ${d.winning_model ? `<span class="agree-badge" title="Best recent fit — the model with the lowest recent forecast error. A recency measure, not a recommendation.">★ ${d.winning_model}</span>` : ''}
      </div>
      ${agreePct !== null ? `
        <div class="forecast-agree-bar">
          <div class="forecast-agree-bar-label">
            <span>Model Agreement</span><span>${agreePct}%</span>
          </div>
          <div class="forecast-agree-bar-track">
            <div class="forecast-agree-bar-fill" style="width:${agreePct}%"></div>
          </div>
        </div>
      ` : ''}
      ${d.std_dev !== null ? `
        <div class="forecast-stddev">
          <span class="kv-label">Model Spread</span>
          <span class="kv-val">&plusmn;${(d.std_dev * 100).toFixed(2)}%</span>
        </div>
      ` : ''}
      <div class="model-breakdown">
        <div class="model-breakdown-title">Model Breakdown</div>
        ${modelRowsHTML || '<div style="color:var(--text-muted);font-size:11px;padding:4px 6px;">No model data</div>'}
      </div>
      <div class="card-chart-wrap">
        <div class="card-chart-header">
          <span class="card-chart-label">21-Day Price Projection</span>
          <button class="chart-toggle-btn" data-ticker="${ticker}">Show All Models</button>
        </div>
        <div class="card-chart" id="chart-${ticker}"></div>
      </div>
    `;
    grid.appendChild(card);

    // Wire toggle button
    const btn = card.querySelector('.chart-toggle-btn');
    if (btn) btn.addEventListener('click', () => toggleModelLines(ticker));
  }

  const asOfEl = document.getElementById('forecastAsOf');
  if (asOfEl && asOf) asOfEl.textContent = `As of ${asOf}`;

  // Init charts after DOM is painted; hide the chart wrap for tickers with no data
  requestAnimationFrame(() => {
    for (const ticker of ordered) {
      const item = chartDataMap && chartDataMap[ticker];
      if (item) {
        initFanChart(ticker, tickers[ticker], item);
      } else {
        // No chart data — collapse the reserved space so the card doesn't show a blank gap
        const chartEl = document.getElementById(`chart-${ticker}`);
        const wrap = chartEl && chartEl.closest('.card-chart-wrap');
        if (wrap) wrap.style.display = 'none';
      }
    }
  });
}

function initFanChart(ticker, forecastItem, chartItem) {
  const el = document.getElementById(`chart-${ticker}`);
  if (!el || typeof Plotly === 'undefined') return;

  const fan = chartItem.fan;
  const history = chartItem.history || [];
  const isDark = document.documentElement.dataset.theme !== 'light';

  const axisColor    = isDark ? '#4a6080' : '#7a8fa8';
  const gridColor    = isDark ? 'rgba(55,85,140,0.18)' : 'rgba(100,140,200,0.15)';
  const histColor    = isDark ? 'rgba(148,163,184,0.65)' : 'rgba(80,110,160,0.55)';
  const consensusClr = '#d4a84b';

  const traces = [];

  // Historical price
  if (history.length) {
    traces.push({
      x: history.map(h => h.date),
      y: history.map(h => h.price),
      mode: 'lines',
      name: 'History',
      line: { color: histColor, width: 1.5, dash: 'solid' },
      hovertemplate: '$%{y:.2f}<extra>Historical</extra>',
    });
  }

  if (fan) {
    const d = fan.dates;

    // Band 3 (±3σ) — widest, most transparent
    traces.push({ x: d, y: fan.band_3_lower, mode: 'lines', line: { width: 0 }, showlegend: false, hoverinfo: 'skip' });
    traces.push({ x: d, y: fan.band_3_upper, fill: 'tonexty', fillcolor: 'rgba(59,130,246,0.06)', mode: 'lines', line: { width: 0 }, name: 'Model spread ±3σ', hoverinfo: 'skip' });

    // Band 2 (±2σ)
    traces.push({ x: d, y: fan.band_2_lower, mode: 'lines', line: { width: 0 }, showlegend: false, hoverinfo: 'skip' });
    traces.push({ x: d, y: fan.band_2_upper, fill: 'tonexty', fillcolor: 'rgba(99,102,241,0.10)', mode: 'lines', line: { width: 0 }, name: 'Model spread ±2σ', hoverinfo: 'skip' });

    // Band 1 (±1σ) — narrowest, most visible
    traces.push({ x: d, y: fan.band_1_lower, mode: 'lines', line: { width: 0 }, showlegend: false, hoverinfo: 'skip' });
    traces.push({ x: d, y: fan.band_1_upper, fill: 'tonexty', fillcolor: 'rgba(52,211,153,0.18)', mode: 'lines', line: { width: 0 }, name: 'Model spread ±1σ', hoverinfo: 'skip' });

    // Consensus line
    traces.push({
      x: d,
      y: fan.consensus,
      mode: 'lines',
      name: 'Consensus',
      line: { color: consensusClr, width: 2.5 },
      hovertemplate: '$%{y:.2f}<extra>Consensus</extra>',
    });

    // Individual model lines (hidden by default)
    const modelPaths = fan.model_paths || {};
    for (const [key, prices] of Object.entries(modelPaths)) {
      traces.push({
        x: d,
        y: prices,
        mode: 'lines',
        name: MODEL_LABELS[key] || key,
        line: { color: MODEL_COLORS[key] || '#aaa', width: 1, dash: 'dot' },
        visible: _showModelLines[ticker] ? true : 'legendonly',
        hovertemplate: `$%{y:.2f}<extra>${MODEL_LABELS[key] || key}</extra>`,
      });
    }
  }

  // Today's date as vertical reference line
  const todayStr = new Date().toISOString().slice(0, 10);

  const layout = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    margin: { t: 4, r: 10, b: 30, l: 56 },
    height: 210,
    xaxis: {
      type: 'date',
      showgrid: false,
      color: axisColor,
      tickfont: { size: 9, color: axisColor },
      tickformat: '%b %d',
      nticks: 6,
    },
    yaxis: {
      showgrid: true,
      gridcolor: gridColor,
      color: axisColor,
      tickfont: { size: 9, color: axisColor },
      tickprefix: '$',
      tickformat: '.0f',
    },
    showlegend: false,
    hovermode: 'x unified',
    hoverlabel: { bgcolor: isDark ? '#0b1c38' : '#fff', bordercolor: 'rgba(212,168,75,0.4)', font: { size: 11 } },
    shapes: [{
      type: 'line',
      x0: todayStr, x1: todayStr,
      y0: 0, y1: 1,
      yref: 'paper',
      line: { color: 'rgba(212,168,75,0.5)', width: 1, dash: 'dot' },
    }],
    annotations: [{
      x: todayStr, y: 1, yref: 'paper',
      text: 'Today', showarrow: false,
      font: { size: 9, color: 'rgba(212,168,75,0.7)' },
      xanchor: 'left', yanchor: 'top',
      xshift: 4,
    }],
  };

  const config = {
    displayModeBar: false,
    responsive: true,
    staticPlot: false,
  };

  Plotly.newPlot(el, traces, layout, config);
  el._plotlyTraceCount = traces.length;
}

function toggleModelLines(ticker) {
  _showModelLines[ticker] = !_showModelLines[ticker];
  const el = document.getElementById(`chart-${ticker}`);
  const btn = document.querySelector(`.chart-toggle-btn[data-ticker="${ticker}"]`);
  if (!el || typeof Plotly === 'undefined') return;

  // Update visibility of model traces (all traces after the consensus trace)
  const gd = el;
  if (!gd.data) return;

  const updates = { visible: [] };
  for (let i = 0; i < gd.data.length; i++) {
    const t = gd.data[i];
    const isModelLine = t.line && t.line.dash === 'dot';
    if (isModelLine) {
      updates.visible.push(_showModelLines[ticker] ? true : 'legendonly');
    } else {
      updates.visible.push(t.visible !== undefined ? t.visible : true);
    }
  }
  Plotly.restyle(el, { visible: updates.visible });

  if (btn) {
    btn.textContent = _showModelLines[ticker] ? 'Hide Models' : 'Show All Models';
    btn.classList.toggle('active', _showModelLines[ticker]);
  }
}

// Walk-forward reality check: the production DL model retrained at each 21-trading-day
// step on past-only data, scored over hundreds of INDEPENDENT non-overlapping windows.
// This is the honest out-of-sample answer the short live log can't give yet.
function renderWalkforward(wf) {
  const section = document.getElementById('walkforwardSection');
  if (!section) return;
  if (!wf || !wf.n_independent_pooled || !Array.isArray(wf.per_ticker)) {
    section.style.display = 'none';
    return;
  }
  const muted = 'var(--text-muted)';
  const border = 'var(--border-subtle, rgba(255,255,255,.10))';
  const dir = (wf.pooled_directional_accuracy * 100).toFixed(1) + '%';
  const ciLo = (wf.pooled_dir_ci[0] * 100).toFixed(0);
  const ciHi = (wf.pooled_dir_ci[1] * 100).toFixed(0);
  const sig = wf.pooled_significant;
  const verdictColor = sig ? 'var(--accent-positive, #2ecc71)' : muted;
  const verdictWord = sig ? 'a statistically significant edge' : 'no significant directional edge';

  const rowsHTML = wf.per_ticker.map(r => {
    const d = (Number(r.Directional_Accuracy) * 100).toFixed(0) + '%';
    const lo = (Number(r.Dir_CI_Lower) * 100).toFixed(0);
    const hi = (Number(r.Dir_CI_Upper) * 100).toFixed(0);
    const corr = Number(r.Corr).toFixed(2);
    const mark = Number(r.Significant) === 1 ? ' ✓' : ' ~';
    return `<tr style="border-bottom:1px solid ${border};">
      <td style="padding:5px 6px;font-weight:600;">${r.Ticker}</td>
      <td style="text-align:right;padding:5px 6px;">${Number(r.N_Independent).toFixed(0)}</td>
      <td style="text-align:right;padding:5px 6px;">${d}<small style="opacity:.55;">${mark}</small></td>
      <td style="text-align:right;padding:5px 6px;color:${muted};">${lo}–${hi}%</td>
      <td style="text-align:right;padding:5px 6px;">${corr}</td>
    </tr>`;
  }).join('');

  section.innerHTML = `
    <div class="ds-eyebrow">Reality Check</div>
    <div class="ds-section-header" style="margin-top:var(--s-1);">
      <h3 class="ds-title is-h3">Deep Learning — Walk-Forward Backtest</h3>
      <span class="badge">${wf.n_independent_pooled} independent windows</span>
    </div>
    <p class="ds-subtitle">
      The production Deep Learning model retrained at each 21-trading-day step on
      <strong>only the data available at the time</strong>, then scored over hundreds of
      <strong>independent, non-overlapping</strong> windows (2021–2026). Unlike the leaderboard
      above — which ranks on recent error over a handful of overlapping windows — this is the
      honest out-of-sample test of whether the direction calls are real.
    </p>
    <p style="font-size:15px;margin:10px 0 14px;color:var(--text-primary);">
      Over <strong>${wf.n_independent_pooled}</strong> independent windows the model is
      <strong>${dir}</strong> directional (95% CI ${ciLo}–${ciHi}%) —
      <strong style="color:${verdictColor};">${verdictWord}</strong>.
      A coin flip is 50%. Its leaderboard wins above come from low <em>magnitude</em> error
      (cautious, small forecasts), not from calling direction.
    </p>
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:12px;color:var(--text-primary);">
        <thead><tr style="color:${muted};border-bottom:1px solid ${border};">
          <th style="text-align:left;padding:5px 6px;">Ticker</th>
          <th style="text-align:right;padding:5px 6px;">Indep. N</th>
          <th style="text-align:right;padding:5px 6px;">Directional</th>
          <th style="text-align:right;padding:5px 6px;">95% CI</th>
          <th style="text-align:right;padding:5px 6px;">Corr</th>
        </tr></thead>
        <tbody>${rowsHTML}</tbody>
      </table>
      <div style="font-size:11px;color:${muted};margin-top:6px;line-height:1.5;">
        ✓ = CI excludes 50% (real edge); ~ = straddles 50% (coin flip). Corr = correlation of
        forecast vs realized return (≈0 means no linear signal). Offline research backtest —
        does not change the live consensus. Computed ${wf.computed || ''}.
      </div>
    </div>`;
  section.style.display = '';
}

function renderPodiumLeaderboard(forecastTickers, chartDataMap) {
  const container = document.getElementById('rankingsContainer');
  if (!container) return;

  const ordered = MAG7_ORDER.filter(t => forecastTickers[t]);
  if (!ordered.length) {
    container.innerHTML = '<p style="color:var(--text-muted);padding:12px;">No ranking data available.</p>';
    return;
  }

  const MEDALS = ['#1', '#2', '#3'];
  const MEDAL_CLASSES = ['gold', 'silver', 'bronze'];
  const PLATFORM_ORDER = [1, 0, 2]; // silver left, gold center, bronze right

  const cards = ordered.map(ticker => {
    const d = forecastTickers[ticker];
    const rankings = (d.rankings || []);
    const chartItem = chartDataMap && chartDataMap[ticker];
    const lookback = chartItem && chartItem.lookback_21d;

    // Podium slots: reorder to [2nd, 1st, 3rd] for visual podium
    const topRankings = rankings.slice(0, 3);
    const slots = PLATFORM_ORDER.map(i => topRankings[i]).filter(Boolean);

    // Podium: medal + model name only — the numbers now live in the Data Points popup.
    const slotsHTML = slots.map(r => {
      const rank0 = topRankings.indexOf(r); // 0=gold,1=silver,2=bronze
      const mClass = MEDAL_CLASSES[rank0] || '';
      const modelLabel = MODEL_LABELS[r.Model] || r.Model || '—';
      const modelColor = MODEL_COLORS[r.Model] || '#aaa';
      return `
        <div class="podium-slot ${mClass}">
          <div class="podium-medal">${MEDALS[rank0]}</div>
          <div class="podium-model-name" style="color:${modelColor}">${modelLabel}</div>
          <div class="podium-platform ${mClass}"></div>
        </div>`;
    }).join('');

    // Bare ranking rows — rank + model + winner star. Every metric lives in the Data Points popup.
    const winnerModel = (rankings[0] && rankings[0].Model) || d.winning_model;
    const rankingRowsHTML = rankings.map((r, idx) => {
      const rank = Number(r.Rank || idx + 1);
      const modelLabel = MODEL_LABELS[r.Model] || r.Model || '—';
      const modelColor = MODEL_COLORS[r.Model] || '#aaa';
      const isWinner = r.Model === winnerModel;
      return `
        <div class="leaderboard-model-row leaderboard-model-row--bare${rank <= 3 ? ' is-top-three' : ''}">
          <span class="leaderboard-rank">#${rank}</span>
          <span class="leaderboard-model" style="color:${modelColor}">${modelLabel}${isWinner ? '<span class="winner-crown" title="Best-ranked model (lowest 21-day forecast error)">★</span>' : ''}</span>
        </div>`;
    }).join('');

    // Compact lookback summary — the full actual-vs-prediction chart opens in a modal.
    let lookbackSummary = '';
    if (lookback && lookback.run_date && lookback.actual_pct != null) {
      lookbackSummary = `
        <div class="lookback-actual-row">
          <span>Actual 21-day move</span>
          <span class="lookback-actual ${signClass(lookback.actual_pct)}">${pct(lookback.actual_pct)}</span>
          <span class="lookback-prices">since ${lookback.run_date}</span>
        </div>`;
    }
    const hasLookback = !!(lookback && lookback.run_date && lookback.predictions);

    const consensus = d.consensus;
    const dirClass = signClass(consensus);

    return `
      <div class="podium-card fade-in">
        <div class="podium-card-header">
          <div>
            <div class="podium-ticker">${ticker}</div>
            <div class="podium-name">${d.name || ticker}</div>
          </div>
          <div class="podium-consensus ${dirClass}">${pct(consensus, 2)}</div>
        </div>
        <div class="podium-stage">${slotsHTML}</div>
        <div class="leaderboard-full-list">
          <div class="podium-lookback-title">Model Ranking · by 21-day forecast error</div>
          ${rankingRowsHTML || '<div style="color:var(--text-muted);font-size:11px;padding:8px 0;">No ranked model history available.</div>'}
        </div>
        ${lookbackSummary}
        <div class="leaderboard-actions">
          <button class="btn btn-ghost dp-btn" data-ticker="${ticker}" type="button">&#9432; Data points</button>
          ${hasLookback ? `<button class="btn btn-ghost lookback-btn" data-ticker="${ticker}" type="button">View lookback chart &rarr;</button>` : ''}
        </div>
      </div>`;
  }).join('');

  container.innerHTML = `<div class="podium-grid">${cards}</div>`;
}

// ── Data Points popup (per-ticker metrics table + glossary) ──────────────────
const DATA_POINT_DEFS = [
  ['Rank', 'Models ordered by lowest MAE (RMSE breaks ties). #1 is the best fit on the matured backtest — a measure of past accuracy, not a buy signal.'],
  ['MAE — Mean Absolute Error', 'Average gap between the predicted and the actual 21-day return, in percentage points. Lower is better; this is the primary ranking key. Caveat: on noisy returns a model that forecasts small, cautious numbers can win MAE without real skill.'],
  ['RMSE', 'Like MAE but squares the errors first, so a few big misses are punished harder. Used as the tiebreaker.'],
  ['Dir — Directional Accuracy', 'Share of forecasts that got the direction (up vs down) right, across ALL logged forecasts. Consecutive 21-day windows overlap ~95%, so treat this as the optimistic read.'],
  ['Dir·ind — Independent hit-rate', 'The same direction test, but counted only over independent, non-overlapping windows (n shown beside it). This is the honest hit-rate. The marker shows a Wilson 95% confidence interval: ✓ means the interval excludes 50% (a real directional edge), ~ means it still straddles 50% (not yet distinguishable from a coin flip). Hover the cell for the interval. With today\'s small n almost everything reads ~ — that is the honest state until the independent sample grows.'],
  ['Corr', 'Correlation between predicted and actual returns. Positive = the model moves with reality; near zero = no signal; negative = systematically wrong-signed.'],
  ['CI — Confidence-interval coverage', "How often the actual return landed inside the model's stated confidence band (only models that emit one). ~90% is well-calibrated; far below = overconfident, far above = bands too wide."],
  ['N', 'Number of matured forecasts scored for this model.'],
];

function _dpFmtPct(v) {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  return (Math.abs(n) > 1 ? n : n * 100).toFixed(2) + '%';
}

function openDataPointsModal(ticker) {
  const modal = document.getElementById('dataPointsModal');
  const content = document.getElementById('dataPointsContent');
  if (!modal || !content) return;
  const d = (_forecastDataCache && _forecastDataCache[ticker]) || {};
  const rankings = d.rankings || [];
  const tickerEl = document.getElementById('dataPointsTicker');
  if (tickerEl) tickerEl.textContent = `${ticker} · Data Points`;

  const isDark = document.documentElement.dataset.theme !== 'light';
  const border = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)';
  const muted = 'var(--text-muted)';

  const rowsHTML = rankings.map(r => {
    const color = MODEL_COLORS[r.Model] || '#aaa';
    const label = MODEL_LABELS[r.Model] || r.Model;
    const dir = r.Directional_Accuracy != null ? (r.Directional_Accuracy * 100).toFixed(0) + '%' : '—';
    const dirNO = (r.Directional_Accuracy_NO != null && !Number.isNaN(Number(r.Directional_Accuracy_NO)))
      ? (Number(r.Directional_Accuracy_NO) * 100).toFixed(0) + '%' : '—';
    const nNO = r.N_NonOverlap != null ? Number(r.N_NonOverlap).toFixed(0) : '—';
    // Wilson 95% CI + significance marker: ✓ = CI excludes 50% (real edge),
    // ~ = CI straddles 50% (not yet distinguishable from a coin flip).
    const ciLoNO = Number(r.Dir_NO_CI_Lower), ciHiNO = Number(r.Dir_NO_CI_Upper);
    const hasDirCI = !Number.isNaN(ciLoNO) && !Number.isNaN(ciHiNO);
    const dirSig = Number(r.Dir_NO_Significant);
    const dirCItext = hasDirCI ? `95% CI ${(ciLoNO * 100).toFixed(0)}–${(ciHiNO * 100).toFixed(0)}%` : '';
    const dirSigMark = hasDirCI ? (dirSig === 1 ? ' ✓' : ' ~') : '';
    const dirSigTitle = hasDirCI
      ? `${dirCItext} — ${dirSig === 1 ? 'distinguishable from a coin flip' : 'NOT yet distinguishable from a coin flip'}`
      : '';
    const corr = (r.Corr != null && !Number.isNaN(Number(r.Corr))) ? Number(r.Corr).toFixed(2) : '—';
    const ci = (r.CI_Coverage != null && !Number.isNaN(Number(r.CI_Coverage))) ? (Number(r.CI_Coverage) * 100).toFixed(0) + '%' : '—';
    const obs = r.N != null ? Number(r.N).toFixed(0) : '—';
    return `<tr style="border-bottom:1px solid ${border};">
      <td style="text-align:center;color:${muted};padding:5px 6px;">#${Number(r.Rank || 0)}</td>
      <td style="font-weight:600;color:${color};white-space:nowrap;padding:5px 6px;">${label}</td>
      <td style="text-align:right;padding:5px 6px;">${_dpFmtPct(r.MAE)}</td>
      <td style="text-align:right;padding:5px 6px;">${_dpFmtPct(r.RMSE)}</td>
      <td style="text-align:right;padding:5px 6px;">${dir}</td>
      <td style="text-align:right;padding:5px 6px;" title="${dirSigTitle}">${dirNO}<small style="opacity:.55;"> n${nNO}${dirSigMark}</small></td>
      <td style="text-align:right;padding:5px 6px;">${corr}</td>
      <td style="text-align:right;padding:5px 6px;">${ci}</td>
      <td style="text-align:right;color:${muted};padding:5px 6px;">${obs}</td>
    </tr>`;
  }).join('');

  const tableHTML = rankings.length ? `
    <div style="overflow-x:auto;margin-bottom:22px;">
      <table style="width:100%;border-collapse:collapse;font-size:12px;color:var(--text-primary);">
        <thead><tr style="color:${muted};border-bottom:1px solid ${border};">
          <th style="text-align:center;padding:5px 6px;">#</th>
          <th style="text-align:left;padding:5px 6px;">Model</th>
          <th style="text-align:right;padding:5px 6px;">MAE</th>
          <th style="text-align:right;padding:5px 6px;">RMSE</th>
          <th style="text-align:right;padding:5px 6px;">Dir</th>
          <th style="text-align:right;padding:5px 6px;">Dir&middot;ind</th>
          <th style="text-align:right;padding:5px 6px;">Corr</th>
          <th style="text-align:right;padding:5px 6px;">CI</th>
          <th style="text-align:right;padding:5px 6px;">N</th>
        </tr></thead>
        <tbody>${rowsHTML}</tbody>
      </table>
      <div style="font-size:11px;color:${muted};margin-top:6px;line-height:1.5;">
        Dir&middot;ind marker — <strong>&#10003;</strong> the Wilson 95% CI excludes 50% (a real directional edge);
        <strong>~</strong> the CI still straddles 50% (not yet distinguishable from a coin flip). Hover for the interval.
        With today&rsquo;s short independent history almost every model reads <strong>~</strong> — read Dir&middot;ind as a lean, not a verdict.
      </div>
    </div>` : '';

  const defsHTML = DATA_POINT_DEFS.map(([term, def], i) => `
    <div style="padding:10px 0;${i < DATA_POINT_DEFS.length - 1 ? `border-bottom:1px solid ${border};` : ''}">
      <div style="font-weight:700;font-size:12px;color:var(--text-primary);margin-bottom:3px;">${term}</div>
      <div style="font-size:12px;color:${muted};line-height:1.55;">${def}</div>
    </div>`).join('');

  content.innerHTML = tableHTML + `
    <div style="font-weight:700;font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:${muted};margin-bottom:4px;">What each number means</div>
    ${defsHTML}
    <div style="margin-top:14px;padding:12px 14px;border-radius:8px;background:rgba(96,165,250,0.08);font-size:12px;color:var(--text-primary);line-height:1.55;">
      <strong>How to read it:</strong> trust DIRECTION over LEVEL. A low MAE alone can just mean a model bets small. Confirm real skill by pairing it with a positive <em>Corr</em> and a decent <em>Dir&middot;ind</em> — and remember the independent sample is still small, so today's ranking is a lean, not a verdict.
    </div>`;

  modal.setAttribute('aria-hidden', 'false');
  modal.classList.add('is-open');
  document.body.style.overflow = 'hidden';
}

function closeDataPointsModal() {
  const modal = document.getElementById('dataPointsModal');
  if (!modal) return;
  modal.classList.remove('is-open');
  modal.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
}

// ── 21-Day Lookback chart modal (actual path vs each model's prediction) ──────
let _lookbackTicker = null;
let _lookbackShowAll = false;

function openLookbackModal(ticker) {
  const modal = document.getElementById('lookbackModal');
  if (!modal) return;
  const chartItem = _chartDataCache && _chartDataCache[ticker];
  const forecastItem = _forecastDataCache && _forecastDataCache[ticker];
  if (!chartItem || !chartItem.lookback_21d) return;

  _lookbackTicker = ticker;
  _lookbackShowAll = false;
  const lb = chartItem.lookback_21d;
  const tEl = document.getElementById('lookbackModalTicker');
  const nEl = document.getElementById('lookbackModalName');
  if (tEl) tEl.textContent = `${ticker} · 21-Day Lookback`;
  if (nEl) nEl.textContent = `Prediction made ${lb.run_date} vs the actual path`;
  const toggleBtn = document.getElementById('lookbackModalToggle');
  if (toggleBtn) { toggleBtn.textContent = 'Show All Models'; toggleBtn.classList.remove('active'); }

  modal.setAttribute('aria-hidden', 'false');
  modal.classList.add('is-open');
  document.body.style.overflow = 'hidden';
  requestAnimationFrame(() => renderLookbackChart(ticker, forecastItem, chartItem));
}

function closeLookbackModal() {
  const modal = document.getElementById('lookbackModal');
  if (!modal) return;
  modal.classList.remove('is-open');
  modal.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
  const plotEl = document.getElementById('lookbackModalPlot');
  if (plotEl && typeof Plotly !== 'undefined') Plotly.purge(plotEl);
  _lookbackTicker = null;
}

function renderLookbackChart(ticker, forecastItem, chartItem) {
  const el = document.getElementById('lookbackModalPlot');
  if (!el || typeof Plotly === 'undefined') return;

  const lb = chartItem.lookback_21d || {};
  const history = chartItem.history || [];
  const runDate = lb.run_date;
  const startPrice = lb.start_price;
  const preds = lb.predictions || {};
  const isDark = document.documentElement.dataset.theme !== 'light';

  const axisColor   = isDark ? '#4a6080' : '#7a8fa8';
  const gridColor   = isDark ? 'rgba(55,85,140,0.18)' : 'rgba(100,140,200,0.15)';
  const actualColor = isDark ? '#e2e8f0' : '#1e293b';

  // Actual daily price path from the prediction date forward.
  const path = history.filter(h => h.date >= runDate);
  const endDate = path.length ? path[path.length - 1].date : runDate;
  const winner = (forecastItem && forecastItem.winning_model) ||
    (forecastItem && forecastItem.rankings && forecastItem.rankings[0] && forecastItem.rankings[0].Model);

  const traces = [];
  if (path.length) {
    traces.push({
      x: path.map(h => h.date), y: path.map(h => h.price),
      mode: 'lines', name: 'Actual',
      line: { color: actualColor, width: 3 },
      hovertemplate: '$%{y:.2f}<extra>Actual</extra>',
    });
  }
  // Each model's predicted endpoint: a straight line from (runDate, startPrice) to the
  // predicted target at the end of the window. Winner is shown solid/dashed by default;
  // the rest are dotted + hidden behind the toggle.
  if (startPrice) {
    Object.entries(preds).forEach(([key, p]) => {
      const target = startPrice * (1 + p);
      const isWinner = key === winner;
      traces.push({
        x: [runDate, endDate], y: [startPrice, target],
        mode: 'lines+markers',
        name: (MODEL_LABELS[key] || key) + ' (pred)',
        line: { color: MODEL_COLORS[key] || '#aaa', width: isWinner ? 2.6 : 1.4, dash: isWinner ? 'dash' : 'dot' },
        marker: { size: isWinner ? 8 : 5, color: MODEL_COLORS[key] || '#aaa' },
        visible: isWinner ? true : 'legendonly',
        hovertemplate: `$%{y:.2f} · ${(p * 100 >= 0 ? '+' : '') + (p * 100).toFixed(2)}%<extra>${MODEL_LABELS[key] || key} predicted</extra>`,
      });
    });
  }

  const actualPct = lb.actual_pct != null ? (lb.actual_pct * 100) : null;
  const layout = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    margin: { t: 8, r: 24, b: 80, l: 72 },
    height: 460,
    xaxis: { type: 'date', showgrid: false, color: axisColor, tickfont: { size: 11, color: axisColor }, tickformat: '%b %d', nticks: 8 },
    yaxis: { showgrid: true, gridcolor: gridColor, color: axisColor, tickfont: { size: 11, color: axisColor }, tickprefix: '$', tickformat: '.2f' },
    legend: { orientation: 'h', font: { size: 11, color: isDark ? '#8facc8' : '#5a7090' }, bgcolor: 'transparent', borderwidth: 0, x: 0.5, y: -0.18, xanchor: 'center', yanchor: 'top' },
    showlegend: true,
    hovermode: 'x unified',
    hoverlabel: { bgcolor: isDark ? '#0b1c38' : '#fff', bordercolor: 'rgba(212,168,75,0.4)', font: { size: 12 } },
    annotations: actualPct != null ? [{
      x: endDate, y: lb.end_price, xanchor: 'right', yanchor: actualPct >= 0 ? 'bottom' : 'top',
      text: `Actual ${actualPct >= 0 ? '+' : ''}${actualPct.toFixed(1)}%`, showarrow: false,
      font: { size: 11, color: actualColor }, yshift: actualPct >= 0 ? 8 : -8,
    }] : [],
  };

  Plotly.newPlot(el, traces, layout, { displayModeBar: false, responsive: true, scrollZoom: true });
}

function toggleLookbackModels() {
  if (!_lookbackTicker) return;
  _lookbackShowAll = !_lookbackShowAll;
  const btn = document.getElementById('lookbackModalToggle');
  if (btn) { btn.textContent = _lookbackShowAll ? 'Hide Models' : 'Show All Models'; btn.classList.toggle('active', _lookbackShowAll); }
  const el = document.getElementById('lookbackModalPlot');
  if (!el || !el.data) return;
  // Flip the dotted (non-winner) prediction lines; the actual path and the winner's dashed line stay.
  const visible = el.data.map(t => (t.line && t.line.dash === 'dot') ? (_lookbackShowAll ? true : 'legendonly') : (t.visible ?? true));
  Plotly.restyle(el, { visible });
}

// ── Chart Modal ─────────────────────────────────────────────────────────────
let _modalTicker = null;
let _modalShowModels = false;
let _chartDataCache = null; // set after loadForecasts resolves
let _forecastDataCache = null;

function openChartModal(ticker, forecastItem, chartItem) {
  const modal = document.getElementById('chartModal');
  if (!modal) return;

  _modalTicker = ticker;
  _modalShowModels = false;

  document.getElementById('chartModalTicker').textContent = ticker;
  document.getElementById('chartModalName').textContent = forecastItem?.name || '';
  const toggleBtn = document.getElementById('chartModalToggle');
  if (toggleBtn) { toggleBtn.textContent = 'Show All Models'; toggleBtn.classList.remove('active'); }

  modal.setAttribute('aria-hidden', 'false');
  modal.classList.add('is-open');
  document.body.style.overflow = 'hidden';

  // Render expanded chart after transition starts
  requestAnimationFrame(() => renderModalChart(ticker, forecastItem, chartItem, false));
}

function closeChartModal() {
  const modal = document.getElementById('chartModal');
  if (!modal) return;
  modal.classList.remove('is-open');
  modal.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
  // Purge Plotly chart to free memory
  const plotEl = document.getElementById('chartModalPlot');
  if (plotEl && typeof Plotly !== 'undefined') Plotly.purge(plotEl);
  _modalTicker = null;
}

function renderModalChart(ticker, forecastItem, chartItem, showModels) {
  const el = document.getElementById('chartModalPlot');
  if (!el || typeof Plotly === 'undefined') return;

  const fan = chartItem?.fan;
  const history = chartItem?.history || [];
  const isDark = document.documentElement.dataset.theme !== 'light';

  const axisColor    = isDark ? '#4a6080' : '#7a8fa8';
  const gridColor    = isDark ? 'rgba(55,85,140,0.18)' : 'rgba(100,140,200,0.15)';
  const histColor    = isDark ? '#c0cfe8' : '#3a5a8a';

  const traces = [];

  if (history.length) {
    traces.push({
      x: history.map(h => h.date),
      y: history.map(h => h.price),
      mode: 'lines',
      name: 'History',
      line: { color: histColor, width: 2, dash: 'solid' },
      hovertemplate: '$%{y:.2f}<extra>Historical</extra>',
    });
  }

  if (fan) {
    const d = fan.dates;
    traces.push({ x: d, y: fan.band_3_lower, mode: 'lines', line: { width: 0 }, showlegend: false, hoverinfo: 'skip' });
    traces.push({ x: d, y: fan.band_3_upper, fill: 'tonexty', fillcolor: 'rgba(59,130,246,0.07)', mode: 'lines', line: { width: 0 }, name: 'Model spread ±3σ', hoverinfo: 'skip' });
    traces.push({ x: d, y: fan.band_2_lower, mode: 'lines', line: { width: 0 }, showlegend: false, hoverinfo: 'skip' });
    traces.push({ x: d, y: fan.band_2_upper, fill: 'tonexty', fillcolor: 'rgba(99,102,241,0.12)', mode: 'lines', line: { width: 0 }, name: 'Model spread ±2σ', hoverinfo: 'skip' });
    traces.push({ x: d, y: fan.band_1_lower, mode: 'lines', line: { width: 0 }, showlegend: false, hoverinfo: 'skip' });
    traces.push({ x: d, y: fan.band_1_upper, fill: 'tonexty', fillcolor: 'rgba(52,211,153,0.2)', mode: 'lines', line: { width: 0 }, name: 'Model spread ±1σ', hoverinfo: 'skip' });
    traces.push({
      x: d, y: fan.consensus, mode: 'lines', name: 'Consensus',
      line: { color: '#d4a84b', width: 3 },
      hovertemplate: '$%{y:.2f}<extra>Consensus</extra>',
    });
    const modelPaths = fan.model_paths || {};
    for (const [key, prices] of Object.entries(modelPaths)) {
      traces.push({
        x: d, y: prices, mode: 'lines',
        name: MODEL_LABELS[key] || key,
        line: { color: MODEL_COLORS[key] || '#aaa', width: 1.5, dash: 'dot' },
        visible: showModels ? true : 'legendonly',
        hovertemplate: `$%{y:.2f}<extra>${MODEL_LABELS[key] || key}</extra>`,
      });
    }
  }

  const todayStr = new Date().toISOString().slice(0, 10);

  const layout = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    margin: { t: 8, r: 24, b: 80, l: 72 },
    height: 460,
    xaxis: {
      type: 'date',
      showgrid: false,
      color: axisColor,
      tickfont: { size: 11, color: axisColor },
      tickformat: '%b %d',
      nticks: 10,
    },
    yaxis: {
      showgrid: true,
      gridcolor: gridColor,
      color: axisColor,
      tickfont: { size: 11, color: axisColor },
      tickprefix: '$',
      tickformat: '.2f',
    },
    legend: {
      orientation: 'h',
      font: { size: 11, color: isDark ? '#8facc8' : '#5a7090' },
      bgcolor: 'transparent',
      borderwidth: 0,
      x: 0.5, y: -0.18,
      xanchor: 'center', yanchor: 'top',
    },
    showlegend: true,
    hovermode: 'x unified',
    hoverlabel: { bgcolor: isDark ? '#0b1c38' : '#fff', bordercolor: 'rgba(212,168,75,0.4)', font: { size: 12 } },
    shapes: [{
      type: 'line', x0: todayStr, x1: todayStr, y0: 0, y1: 1, yref: 'paper',
      line: { color: 'rgba(212,168,75,0.55)', width: 1.5, dash: 'dot' },
    }],
    annotations: [{
      x: todayStr, y: 1, yref: 'paper',
      text: 'Today', showarrow: false,
      font: { size: 11, color: 'rgba(212,168,75,0.8)' },
      xanchor: 'left', yanchor: 'top', xshift: 6,
    }],
  };

  const config = {
    displayModeBar: false,
    responsive: true,
    scrollZoom: true,
  };

  Plotly.newPlot(el, traces, layout, config);
}

function toggleModalModels() {
  if (!_modalTicker || !_chartDataCache || !_forecastDataCache) return;
  _modalShowModels = !_modalShowModels;
  const btn = document.getElementById('chartModalToggle');
  if (btn) {
    btn.textContent = _modalShowModels ? 'Hide Models' : 'Show All Models';
    btn.classList.toggle('active', _modalShowModels);
  }
  const el = document.getElementById('chartModalPlot');
  if (!el || !el.data) return;
  const updates = { visible: el.data.map(t => (t.line?.dash === 'dot') ? (_modalShowModels ? true : 'legendonly') : (t.visible ?? true)) };
  Plotly.restyle(el, { visible: updates.visible });
}

function setStatus(msg, isError) {
  const el = document.getElementById('forecastStatus');
  if (!el) return;
  el.textContent = msg;
  el.style.display = msg ? '' : 'none';
  el.style.color = isError ? 'var(--danger)' : 'var(--text-muted)';
}

function _refreshForecastsInBackground() {
  const chartAbort = new AbortController();
  const chartTimeout = setTimeout(() => chartAbort.abort(), 25000);
  Promise.all([
    fetch('/api/forecasts').catch(() => null),
    fetch('/api/forecast-chart-data', { signal: chartAbort.signal }).catch(() => null),
  ]).then(([forecastResp, chartResp]) => {
    clearTimeout(chartTimeout);
    if (!forecastResp || !forecastResp.ok) return;
    return forecastResp.json().then(data => {
      if (!data || !data.ok) return;
      let chartData = null;
      const chartJson = chartResp && chartResp.ok ? chartResp.json() : Promise.resolve(null);
      return chartJson.then(cd => {
        if (cd && cd.ok) chartData = cd.tickers;
        _forecastDataCache = data.tickers || {};
        _chartDataCache = chartData;
        renderCommentary(data.commentary);
        renderForecastCards(data.tickers || {}, data.as_of || '', chartData);
        renderPodiumLeaderboard(data.tickers || {}, chartData);
        renderWalkforward(data.walkforward);
        if (typeof writeSessionJson === 'function') {
          writeSessionJson('api_cache_forecasts', data);
          if (chartData) writeSessionJson('api_cache_forecast_chart', { ok: true, tickers: chartData });
        }
      });
    });
  }).catch(() => {});
}

async function loadForecasts() {
  // Read from sessionStorage pre-warmed by background prefetch on other pages
  const cachedForecast = (typeof readSessionJson === 'function') ? readSessionJson('api_cache_forecasts', 300000) : null;
  const cachedChart    = (typeof readSessionJson === 'function') ? readSessionJson('api_cache_forecast_chart', 300000) : null;

  if (cachedForecast && cachedForecast.tickers) {
    const chartData = cachedChart && cachedChart.tickers ? cachedChart.tickers : null;
    setStatus('');
    _forecastDataCache = cachedForecast.tickers || {};
    _chartDataCache = chartData;
    renderCommentary(cachedForecast.commentary);
    renderForecastCards(cachedForecast.tickers || {}, cachedForecast.as_of || '', chartData);
    renderPodiumLeaderboard(cachedForecast.tickers || {}, chartData);
    renderWalkforward(cachedForecast.walkforward);
    // Refresh in background so data stays current
    _refreshForecastsInBackground();
    return;
  }

  setStatus('Loading forecast data…');
  try {
    // Fetch forecasts and chart data in parallel; chart data has a generous timeout
    // since it runs a live yfinance call that can be slow on cold cache
    const chartAbort = new AbortController();
    const chartTimeout = setTimeout(() => chartAbort.abort(), 25000);
    const [forecastResp, chartResp] = await Promise.all([
      fetch('/api/forecasts'),
      fetch('/api/forecast-chart-data', { signal: chartAbort.signal }).catch(() => null),
    ]);
    clearTimeout(chartTimeout);

    if (!forecastResp.ok) throw new Error(`HTTP ${forecastResp.status}`);
    const data = await forecastResp.json();
    if (!data.ok) throw new Error('API returned error');

    let chartData = null;
    if (chartResp && chartResp.ok) {
      const cd = await chartResp.json();
      if (cd.ok) chartData = cd.tickers;
    }

    setStatus('');
    _forecastDataCache = data.tickers || {};
    _chartDataCache = chartData;
    renderCommentary(data.commentary);
    renderForecastCards(data.tickers || {}, data.as_of || '', chartData);
    renderPodiumLeaderboard(data.tickers || {}, chartData);
    renderWalkforward(data.walkforward);
    // Cache for next visit / other tabs
    if (typeof writeSessionJson === 'function') {
      writeSessionJson('api_cache_forecasts', data);
      if (chartData) writeSessionJson('api_cache_forecast_chart', { ok: true, tickers: chartData });
    }
  } catch (err) {
    setStatus('Failed to load forecast data. ' + err.message, true);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  loadForecasts();

  // Models info modal
  const openBtn = document.getElementById('openModelsInfoBtn');
  const infoModal = document.getElementById('modelsInfoModal');
  const infoClose = document.getElementById('modelsInfoClose');
  const infoBackdrop = infoModal?.querySelector('.chart-modal-backdrop');
  if (openBtn) openBtn.addEventListener('click', openModelsInfo);
  if (infoClose) infoClose.addEventListener('click', closeModelsInfo);
  if (infoBackdrop) infoBackdrop.addEventListener('click', closeModelsInfo);

  // Modal close handlers
  const modal = document.getElementById('chartModal');
  const closeBtn = document.getElementById('chartModalClose');
  const backdrop = modal?.querySelector('.chart-modal-backdrop');
  const toggleBtn = document.getElementById('chartModalToggle');

  if (closeBtn) closeBtn.addEventListener('click', closeChartModal);
  if (backdrop) backdrop.addEventListener('click', closeChartModal);
  if (toggleBtn) toggleBtn.addEventListener('click', toggleModalModels);

  // Data Points popup
  const dpModal = document.getElementById('dataPointsModal');
  const dpClose = document.getElementById('dataPointsClose');
  const dpBackdrop = dpModal?.querySelector('.chart-modal-backdrop');
  if (dpClose) dpClose.addEventListener('click', closeDataPointsModal);
  if (dpBackdrop) dpBackdrop.addEventListener('click', closeDataPointsModal);

  // Lookback chart modal
  const lbModal = document.getElementById('lookbackModal');
  const lbClose = document.getElementById('lookbackModalClose');
  const lbBackdrop = lbModal?.querySelector('.chart-modal-backdrop');
  const lbToggle = document.getElementById('lookbackModalToggle');
  if (lbClose) lbClose.addEventListener('click', closeLookbackModal);
  if (lbBackdrop) lbBackdrop.addEventListener('click', closeLookbackModal);
  if (lbToggle) lbToggle.addEventListener('click', toggleLookbackModels);

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      if (infoModal?.classList.contains('is-open')) closeModelsInfo();
      else if (dpModal?.classList.contains('is-open')) closeDataPointsModal();
      else if (lbModal?.classList.contains('is-open')) closeLookbackModal();
      else if (modal?.classList.contains('is-open')) closeChartModal();
    }
  });

  // Delegated clicks (cards are rendered after load)
  document.addEventListener('click', e => {
    const dpBtn = e.target.closest('.dp-btn');
    if (dpBtn) { openDataPointsModal(dpBtn.dataset.ticker); return; }
    const lbBtn = e.target.closest('.lookback-btn');
    if (lbBtn) { openLookbackModal(lbBtn.dataset.ticker); return; }
    const chartEl = e.target.closest('.card-chart');
    if (!chartEl) return;
    const ticker = chartEl.id.replace('chart-', '');
    if (!ticker || !_chartDataCache || !_forecastDataCache) return;
    openChartModal(ticker, _forecastDataCache[ticker], _chartDataCache[ticker]);
  });
});
