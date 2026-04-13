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
      'Processes a 60-trading-day window of 11 price/volume features (returns, volatility, MA gaps, RSI) as a sequence.',
      'A FeatureGate layer (learnable sigmoid weights) lets the network discover which of the 11 inputs are most predictive — and these weights strengthen with each training run.',
      'Four dilated TCN blocks with residual connections capture patterns at multiple time scales (days, weeks, months).',
      'A TemporalAttentionPool then learns which specific days within the 60-day window are most informative for the prediction, replacing a naive average.',
      'Outputs both a mean forecast (μ) and an uncertainty estimate (σ) trained via Gaussian negative log-likelihood — so confidence intervals come from the model\'s own learned uncertainty, not a fixed rule.',
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
        <span class="badge ${confClass}">${d.confidence_label || '—'} Confidence</span>
        ${d.winning_model ? `<span class="agree-badge">★ ${d.winning_model}</span>` : ''}
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
    traces.push({ x: d, y: fan.band_3_upper, fill: 'tonexty', fillcolor: 'rgba(59,130,246,0.06)', mode: 'lines', line: { width: 0 }, name: '±3σ', hoverinfo: 'skip' });

    // Band 2 (±2σ)
    traces.push({ x: d, y: fan.band_2_lower, mode: 'lines', line: { width: 0 }, showlegend: false, hoverinfo: 'skip' });
    traces.push({ x: d, y: fan.band_2_upper, fill: 'tonexty', fillcolor: 'rgba(99,102,241,0.10)', mode: 'lines', line: { width: 0 }, name: '±2σ', hoverinfo: 'skip' });

    // Band 1 (±1σ) — narrowest, most visible
    traces.push({ x: d, y: fan.band_1_lower, mode: 'lines', line: { width: 0 }, showlegend: false, hoverinfo: 'skip' });
    traces.push({ x: d, y: fan.band_1_upper, fill: 'tonexty', fillcolor: 'rgba(52,211,153,0.18)', mode: 'lines', line: { width: 0 }, name: '±1σ', hoverinfo: 'skip' });

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

function renderPodiumLeaderboard(forecastTickers, chartDataMap) {
  const container = document.getElementById('rankingsContainer');
  if (!container) return;

  const ordered = MAG7_ORDER.filter(t => forecastTickers[t]);
  if (!ordered.length) {
    container.innerHTML = '<p style="color:var(--text-muted);padding:12px;">No ranking data available.</p>';
    return;
  }

  const MEDALS = ['🥇', '🥈', '🥉'];
  const MEDAL_CLASSES = ['gold', 'silver', 'bronze'];
  const PLATFORM_ORDER = [1, 0, 2]; // silver left, gold center, bronze right

  const cards = ordered.map(ticker => {
    const d = forecastTickers[ticker];
    const rankings = (d.rankings || []).slice(0, 3);
    const chartItem = chartDataMap && chartDataMap[ticker];
    const lookback = chartItem && chartItem.lookback_21d;

    // Podium slots: reorder to [2nd, 1st, 3rd] for visual podium
    const slots = PLATFORM_ORDER.map(i => rankings[i]).filter(Boolean);

    const slotsHTML = slots.map(r => {
      const podiumIdx = PLATFORM_ORDER.findIndex(i => rankings[i] === r);
      const rank0 = rankings.indexOf(r); // 0=gold,1=silver,2=bronze
      const mClass = MEDAL_CLASSES[rank0] || '';
      const dirAcc = r.Directional_Accuracy != null ? (r.Directional_Accuracy * 100).toFixed(0) + '%' : '—';
      const rmse = r.RMSE != null ? (r.RMSE * 100).toFixed(2) + '%' : '—';
      const modelLabel = MODEL_LABELS[r.Model] || r.Model || '—';
      const modelColor = MODEL_COLORS[r.Model] || '#aaa';

      // Find this model's lookback prediction
      let lookbackHTML = '';
      if (lookback && lookback.predictions) {
        const pred = lookback.predictions[r.Model];
        const actual = lookback.actual_pct;
        if (pred !== undefined && actual !== undefined) {
          const predDir = pred >= 0;
          const actualDir = actual >= 0;
          const correct = predDir === actualDir;
          lookbackHTML = `
            <div class="podium-lookback-model">
              <span style="color:${modelColor};font-weight:600;">${r.Model}</span>
              <span>Pred: <span class="${signClass(pred)}">${pct(pred)}</span></span>
              <span class="lookback-verdict ${correct ? 'correct' : 'wrong'}">${correct ? '✓' : '✗'}</span>
            </div>`;
        }
      }

      return `
        <div class="podium-slot ${mClass}">
          <div class="podium-medal">${MEDALS[rank0]}</div>
          <div class="podium-model-name" style="color:${modelColor}">${modelLabel}</div>
          <div class="podium-model-stats">RMSE ${rmse} · Dir ${dirAcc}</div>
          <div class="podium-platform ${mClass}"></div>
        </div>`;
    }).join('');

    // 21-day lookback section
    let lookbackSection = '';
    if (lookback && lookback.run_date) {
      const actual = lookback.actual_pct;
      const actualStr = actual != null ? pct(actual) : '—';
      const actualDir = actual != null && actual >= 0;
      const predsHTML = (rankings).map(r => {
        const pred = lookback.predictions && lookback.predictions[r.Model];
        if (pred === undefined) return '';
        const correct = actual != null && (pred >= 0) === (actual >= 0);
        const modelLabel = MODEL_LABELS[r.Model] || r.Model;
        return `
          <div class="lookback-row">
            <span style="color:${MODEL_COLORS[r.Model] || '#aaa'}">${modelLabel}</span>
            <span class="${signClass(pred)}">${pct(pred)}</span>
            <span class="lookback-verdict ${correct ? 'correct' : 'wrong'}">${correct ? '✓ Hit' : '✗ Miss'}</span>
          </div>`;
      }).join('');

      lookbackSection = `
        <div class="podium-lookback">
          <div class="podium-lookback-title">21-Day Lookback · From ${lookback.run_date}</div>
          <div class="lookback-actual-row">
            <span>Actual move</span>
            <span class="lookback-actual ${signClass(actual)}">${actualStr}</span>
            ${lookback.start_price && lookback.end_price ? `<span class="lookback-prices">$${lookback.start_price} → $${lookback.end_price}</span>` : ''}
          </div>
          <div class="lookback-predictions">${predsHTML}</div>
        </div>`;
    }

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
        ${lookbackSection}
      </div>`;
  }).join('');

  container.innerHTML = `<div class="podium-grid">${cards}</div>`;
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
    traces.push({ x: d, y: fan.band_3_upper, fill: 'tonexty', fillcolor: 'rgba(59,130,246,0.07)', mode: 'lines', line: { width: 0 }, name: '±3σ', hoverinfo: 'skip' });
    traces.push({ x: d, y: fan.band_2_lower, mode: 'lines', line: { width: 0 }, showlegend: false, hoverinfo: 'skip' });
    traces.push({ x: d, y: fan.band_2_upper, fill: 'tonexty', fillcolor: 'rgba(99,102,241,0.12)', mode: 'lines', line: { width: 0 }, name: '±2σ', hoverinfo: 'skip' });
    traces.push({ x: d, y: fan.band_1_lower, mode: 'lines', line: { width: 0 }, showlegend: false, hoverinfo: 'skip' });
    traces.push({ x: d, y: fan.band_1_upper, fill: 'tonexty', fillcolor: 'rgba(52,211,153,0.2)', mode: 'lines', line: { width: 0 }, name: '±1σ', hoverinfo: 'skip' });
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
  const token = (typeof epmGetToken === 'function') ? epmGetToken() : null;
  const headers = token ? { 'Authorization': 'Bearer ' + token } : {};
  const chartAbort = new AbortController();
  const chartTimeout = setTimeout(() => chartAbort.abort(), 25000);
  Promise.all([
    fetch('/api/forecasts', { headers }).catch(() => null),
    fetch('/api/forecast-chart-data', { signal: chartAbort.signal, headers }).catch(() => null),
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

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      if (infoModal?.classList.contains('is-open')) closeModelsInfo();
      else if (modal?.classList.contains('is-open')) closeChartModal();
    }
  });

  // Open modal when clicking a mini chart (delegated, cards are rendered after load)
  document.addEventListener('click', e => {
    const chartEl = e.target.closest('.card-chart');
    if (!chartEl) return;
    const ticker = chartEl.id.replace('chart-', '');
    if (!ticker || !_chartDataCache || !_forecastDataCache) return;
    openChartModal(ticker, _forecastDataCache[ticker], _chartDataCache[ticker]);
  });
});
