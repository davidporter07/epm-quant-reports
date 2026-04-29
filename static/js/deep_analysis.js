/**
 * deep_analysis.js — Deep Analysis Lab UI logic
 * Handles job submission, polling, and progress display for search.html
 */

(function () {
  const POLL_INTERVAL = 10000;
  const STORAGE_KEY = 'epm_deep_jobs'; // {ticker: job_id}

  let _currentTicker = null;
  let _currentJobId = null;
  let _pollTimer = null;
  let _etaTimer = null;
  let _jobStartedAt = null;
  let _queueWaitMin = 0;
  let _queueWaitSetAt = null;
  const TOTAL_EST_MIN = 30;

  const STAGE_LABELS = [
    { key: 'seed_doc',          label: 'Data',      full: 'Building Analysis Document' },
    { key: 'council_personas',  label: 'Council',   full: 'Analyst Council Deliberating' },
    { key: 'council_synthesis', label: 'Synthesis', full: 'Synthesizing Report' },
    { key: 'completed',         label: 'Done',      full: 'Complete' },
  ];

  const STAGE_DESCS = {
    seed_doc:          'Synthesizing Kronos forecasts, EPM models, technicals & news',
    council_personas:  'Seven specialist analysts writing grounded perspectives',
    council_synthesis: 'Chief Analyst writing the final institutional research note',
    completed:         'Analysis complete',
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

  function _updateEta() {
    const etaEl   = document.getElementById('dalEta');
    const queueEl = document.getElementById('dalQueueInfo');
    if (etaEl && etaEl.style.display !== 'none' && _jobStartedAt) {
      const elapsedMin  = (Date.now() - _jobStartedAt) / 60000;
      const remaining   = Math.max(1, Math.round(TOTAL_EST_MIN - elapsedMin));
      etaEl.textContent = `~${remaining} min remaining · You can leave this page`;
    }
    if (queueEl && queueEl.style.display !== 'none' && _queueWaitSetAt) {
      const elapsedMin = (Date.now() - _queueWaitSetAt) / 60000;
      const remaining  = Math.max(0, Math.round(_queueWaitMin - elapsedMin));
      const pos        = queueEl.dataset.queuePos || '1';
      queueEl.textContent = remaining > 0
        ? `Position ${pos} in queue — est. ~${remaining} min`
        : `Position ${pos} in queue — starting soon`;
    }
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

    const isQueued = status.status === 'queued';
    const pct = status.progress || 0;
    const stageIdx = _stageIndex(status.stage);
    const stageMeta = STAGE_LABELS[stageIdx] || STAGE_LABELS[0];

    // Current stage name + description — special case for queued state
    const nameEl = document.getElementById('dalCurrentStage');
    const descEl = document.getElementById('dalCurrentDesc');
    const queueAhead = status.queue_ahead || 0;
    if (nameEl) nameEl.textContent = isQueued ? (queueAhead > 0 ? 'Waiting in Queue' : 'Starting…') : stageMeta.full;
    if (descEl) descEl.textContent = isQueued ? (queueAhead > 0 ? 'Another analysis is running — yours will start automatically' : 'Picked up by worker shortly') : (STAGE_DESCS[status.stage] || '');

    // Progress bar + pct
    const bar = document.getElementById('dalProgressBar');
    if (bar) bar.style.width = pct + '%';
    const pctEl = document.getElementById('dalProgressPct');
    if (pctEl) pctEl.textContent = pct + '%';

    // Capture timing state for countdown
    if (!isQueued && status.started_at) {
      _jobStartedAt = new Date(status.started_at).getTime();
    }
    if (isQueued && status.queue_wait_min !== undefined) {
      _queueWaitMin   = status.queue_wait_min;
      _queueWaitSetAt = _queueWaitSetAt || Date.now();
    }

    // ETA label — hide for queued jobs (queue info replaces it)
    const etaEl = document.getElementById('dalEta');
    if (etaEl) {
      if (isQueued) {
        etaEl.style.display = 'none';
      } else {
        etaEl.style.display = '';
        if (_jobStartedAt) {
          const elapsedMin  = (Date.now() - _jobStartedAt) / 60000;
          const remaining   = Math.max(1, Math.round(TOTAL_EST_MIN - elapsedMin));
          etaEl.textContent = `~${remaining} min remaining · You can leave this page`;
        }
      }
    }

    // Queue position info
    const queueEl = document.getElementById('dalQueueInfo');
    if (queueEl) {
      if (isQueued && status.queue_position) {
        queueEl.dataset.queuePos = status.queue_position;
        const elapsedMin = _queueWaitSetAt ? (Date.now() - _queueWaitSetAt) / 60000 : 0;
        const remaining  = Math.max(0, Math.round(_queueWaitMin - elapsedMin));
        queueEl.textContent = remaining > 0
          ? `Position ${status.queue_position} in queue — est. ~${remaining} min`
          : `Position ${status.queue_position} in queue — starting soon`;
        queueEl.style.display = '';
      } else {
        queueEl.style.display = 'none';
      }
    }

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
          runBtn.textContent = 'Run Analyst Council';
          runBtn.onclick = () => _runDeepAnalysis(_currentTicker);
        }
        const lab = document.getElementById('deepAnalysisLab');
        if (lab) lab.scrollIntoView({ behavior: 'smooth', block: 'start' });
      };
    }
  }

  function _stopPolling() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    if (_etaTimer)  { clearInterval(_etaTimer);  _etaTimer  = null; }
  }

  async function _cancelJob() {
    const jobId = _currentJobId;
    if (!jobId) return;
    const btn = document.getElementById('dalCancelBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Cancelling…'; }
    try {
      await fetch(`/api/deep/${encodeURIComponent(jobId)}`, {
        method: 'DELETE',
        credentials: 'include',
      });
    } catch (_) {}
    _stopPolling();
    _clearJob(_currentTicker);
    _currentJobId = null;
    _showLaunchCards();
    const runBtn = document.getElementById('dalRunBtn');
    if (runBtn) {
      runBtn.disabled = false;
      runBtn.textContent = 'Run Analyst Council';
      runBtn.onclick = () => _runDeepAnalysis(_currentTicker);
    }
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
      _currentJobId = null;
      _showLaunchCards();
      const errEl = document.getElementById('dalError');
      if (errEl) { errEl.textContent = 'Analysis failed: ' + (s.error || 'unknown error'); errEl.style.display = ''; }
    } else if (s.status === 'cancelled') {
      _stopPolling();
      _clearJob(_currentTicker);
      _currentJobId = null;
      _showLaunchCards();
    } else {
      _showProgress(s);
    }
  }

  function _startPolling(jobId) {
    _currentJobId = jobId;
    _stopPolling();
    _pollOnce(jobId);
    _pollTimer = setInterval(() => _pollOnce(jobId), POLL_INTERVAL);
    _etaTimer  = setInterval(_updateEta, 180000); // tick every 3 min
    const cancelBtn = document.getElementById('dalCancelBtn');
    if (cancelBtn) { cancelBtn.disabled = false; cancelBtn.textContent = 'Cancel Analysis'; cancelBtn.onclick = _cancelJob; }
  }

  async function _runDeepAnalysis(ticker) {
    _jobStartedAt   = null;
    _queueWaitMin   = 0;
    _queueWaitSetAt = null;
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
      if (btn) { btn.disabled = false; btn.textContent = 'Run Analyst Council'; }
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
      const cleanUrl = window.location.pathname + '?ticker=' + encodeURIComponent(_currentTicker);
      history.replaceState(null, '', cleanUrl);
      _showLaunchCards();
      // Wire run button before returning — without this the button appears but has no handler
      const runBtn = document.getElementById('dalRunBtn');
      if (runBtn) {
        runBtn.disabled = false;
        runBtn.textContent = 'Run Analyst Council';
        runBtn.onclick = () => _runDeepAnalysis(_currentTicker);
      }
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
      btn.textContent = 'Run Analyst Council';
      btn.onclick = () => _runDeepAnalysis(_currentTicker);
    }
  };
})();
