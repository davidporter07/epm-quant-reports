/**
 * deep_analysis.js — Deep Analysis Lab UI logic
 * Handles job submission, polling, and progress display for search.html
 */

(function () {
  const POLL_INTERVAL = 10000;
  const STORAGE_KEY = 'epm_deep_jobs'; // {ticker: job_id}

  let _currentTicker = null;
  let _pollTimer = null;

  const STAGE_LABELS = [
    { key: 'seed_doc',           label: 'Data',      full: 'Building Analysis Document' },
    { key: 'ontology',           label: 'Ontology',  full: 'Generating Knowledge Ontology' },
    { key: 'graph',              label: 'Graph',     full: 'Building Knowledge Graph' },
    { key: 'simulation_create',  label: 'Create',    full: 'Creating Simulation' },
    { key: 'simulation_prepare', label: 'Agents',    full: 'Preparing Agents' },
    { key: 'simulation_running', label: 'Swarm',     full: 'Running Swarm Simulation' },
    { key: 'report_generate',    label: 'Report',    full: 'Generating Report' },
    { key: 'report_poll',        label: 'Writing',   full: 'Writing Report Sections' },
    { key: 'completed',          label: 'Done',      full: 'Complete' },
  ];

  const STAGE_DESCS = {
    seed_doc:           'Synthesizing Kronos forecasts, EPM models & recent news',
    ontology:           'Extracting entities and building knowledge structure',
    graph:              'Mapping relationships between market factors and entities',
    simulation_create:  'Initializing the multi-agent swarm environment',
    simulation_prepare: 'Spawning agents and loading their knowledge bases',
    simulation_running: 'Agents deliberating across 72 simulation rounds',
    report_generate:    'Synthesizing swarm consensus into structured analysis',
    report_poll:        'Writing report sections from simulation insights',
    completed:          'Analysis complete',
  };

  function _stageIndex(stage) {
    return STAGE_LABELS.findIndex(s => s.key === stage);
  }

  function _saveJob(ticker, jobId) {
    try {
      const jobs = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
      jobs[ticker.toUpperCase()] = jobId;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs));
    } catch (_) {}
  }

  function _loadJob(ticker) {
    try {
      const jobs = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
      return jobs[ticker.toUpperCase()] || null;
    } catch (_) { return null; }
  }

  function _clearJob(ticker) {
    try {
      const jobs = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
      delete jobs[ticker.toUpperCase()];
      localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs));
    } catch (_) {}
  }

  function _showLaunchCards() {
    const launch = document.getElementById('dalLaunchCards');
    const progress = document.getElementById('dalProgress');
    const done = document.getElementById('dalDone');
    if (launch) launch.style.display = '';
    if (progress) progress.style.display = 'none';
    if (done) done.style.display = 'none';
  }

  function _showProgress(status) {
    const launch = document.getElementById('dalLaunchCards');
    const progress = document.getElementById('dalProgress');
    const done = document.getElementById('dalDone');
    if (launch) launch.style.display = 'none';
    if (progress) progress.style.display = '';
    if (done) done.style.display = 'none';

    const pct = status.progress || 0;
    const stageIdx = _stageIndex(status.stage);
    const stageMeta = STAGE_LABELS[stageIdx] || STAGE_LABELS[0];

    // Current stage name + description
    const nameEl = document.getElementById('dalCurrentStage');
    const descEl = document.getElementById('dalCurrentDesc');
    if (nameEl) nameEl.textContent = stageMeta.full;
    if (descEl) descEl.textContent = STAGE_DESCS[status.stage] || '';

    // Progress bar + pct
    const bar = document.getElementById('dalProgressBar');
    if (bar) bar.style.width = pct + '%';
    const pctEl = document.getElementById('dalProgressPct');
    if (pctEl) pctEl.textContent = pct + '%';

    // Horizontal pipeline dots
    const pipeline = document.getElementById('dalPipeline');
    if (!pipeline) return;
    pipeline.innerHTML = STAGE_LABELS.map((s, i) => {
      let cls = '';
      if (i < stageIdx) cls = 'p-done';
      else if (i === stageIdx) cls = 'p-active';
      return `<div class="pip-step ${cls}"><div class="pip-dot"></div><div class="pip-label">${s.label}</div></div>`;
    }).join('');
  }

  function _showDone(status) {
    const launch = document.getElementById('dalLaunchCards');
    const progress = document.getElementById('dalProgress');
    const done = document.getElementById('dalDone');
    if (launch) launch.style.display = 'none';
    if (progress) progress.style.display = 'none';
    if (done) done.style.display = '';

    const viewBtn = document.getElementById('dalViewReportBtn');
    if (viewBtn && status.job_id) {
      viewBtn.onclick = () => {
        window.location.href = `/deep-report?job_id=${status.job_id}&ticker=${encodeURIComponent(status.ticker)}`;
      };
    }

    const newBtn = document.getElementById('dalNewAnalysisBtn');
    if (newBtn) {
      newBtn.onclick = () => {
        _clearJob(_currentTicker);
        _showLaunchCards();
        // Reset run button so it's not stuck disabled/stale from the prior run
        const runBtn = document.getElementById('dalRunBtn');
        if (runBtn) {
          runBtn.disabled = false;
          runBtn.textContent = 'Run Deep Swarm Analysis';
          runBtn.onclick = () => _runDeepAnalysis(_currentTicker);
        }
        const lab = document.getElementById('deepAnalysisLab');
        if (lab) lab.scrollIntoView({ behavior: 'smooth', block: 'start' });
      };
    }
  }

  function _stopPolling() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  }

  async function _fetchStatus(jobId) {
    const r = await fetch(`/api/deep/${jobId}/status`, { credentials: 'include' });
    if (!r.ok) return null;
    return r.json();
  }

  async function _pollOnce(jobId) {
    const data = await _fetchStatus(jobId);
    if (!data || !data.ok) return;
    const s = data;
    if (s.status === 'completed') {
      _stopPolling();
      _showDone(s);
    } else if (s.status === 'failed') {
      _stopPolling();
      _clearJob(_currentTicker);
      _showLaunchCards();
      const errEl = document.getElementById('dalError');
      if (errEl) { errEl.textContent = 'Analysis failed: ' + (s.error || 'unknown error'); errEl.style.display = ''; }
    } else {
      _showProgress(s);
    }
  }

  function _startPolling(jobId) {
    _stopPolling();
    _pollOnce(jobId);
    _pollTimer = setInterval(() => _pollOnce(jobId), POLL_INTERVAL);
  }

  async function _runDeepAnalysis(ticker) {
    const btn = document.getElementById('dalRunBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Starting…'; }

    try {
      const r = await fetch(`/api/deep/${encodeURIComponent(ticker)}`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      if (!data.ok) throw new Error(data.detail || 'Failed to start');
      _saveJob(ticker, data.job_id);
      _startPolling(data.job_id);
    } catch (err) {
      if (btn) { btn.disabled = false; btn.textContent = 'Run Deep Swarm Analysis'; }
      const errEl = document.getElementById('dalError');
      if (errEl) { errEl.textContent = 'Could not start: ' + err.message; errEl.style.display = ''; }
    }
  }

  // Called by search.js after each ticker loads
  window.initDeepAnalysis = function (ticker) {
    _stopPolling();
    _currentTicker = ticker.toUpperCase();

    const lab = document.getElementById('deepAnalysisLab');
    if (!lab) return;
    lab.style.display = '';

    // Update ticker badge
    const badge = document.getElementById('dalTickerBadge');
    if (badge) badge.textContent = _currentTicker;

    // Hide error
    const errEl = document.getElementById('dalError');
    if (errEl) errEl.style.display = 'none';

    // If redirected from report page "Run New Analysis", clear job and show launch cards
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('newAnalysis') === '1') {
      _clearJob(_currentTicker);
      // Clean URL so a refresh doesn't re-clear a new run
      const cleanUrl = window.location.pathname + '?q=' + encodeURIComponent(_currentTicker);
      history.replaceState(null, '', cleanUrl);
      _showLaunchCards();
      return;
    }

    // Check for existing job
    const existing = _loadJob(_currentTicker);
    if (existing) {
      _fetchStatus(existing).then(data => {
        if (!data) { _clearJob(_currentTicker); _showLaunchCards(); return; }
        if (data.status === 'completed') { _showDone(data); }
        else if (data.status === 'failed') { _clearJob(_currentTicker); _showLaunchCards(); }
        else { _showProgress(data); _startPolling(existing); }
      });
    } else {
      _showLaunchCards();
    }

    // Wire run button
    const btn = document.getElementById('dalRunBtn');
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Run Deep Swarm Analysis';
      btn.onclick = () => _runDeepAnalysis(_currentTicker);
    }
  };
})();
