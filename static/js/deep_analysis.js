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
  let _countdownTimer = null;
  let _notBeforeTarget = null;
  const TOTAL_EST_MIN = 30;

  const STAGE_LABELS = [
    { key: 'waiting_earnings',  label: 'Earnings',  full: 'Waiting for Earnings Release' },
    { key: 'earnings_refresh',  label: 'Refresh',   full: 'Refreshing Earnings & News' },
    { key: 'seed_doc',          label: 'Data',      full: 'Building Analysis Document' },
    { key: 'council_personas',  label: 'Council',   full: 'Analyst Council Deliberating' },
    { key: 'council_synthesis', label: 'Synthesis', full: 'Synthesizing Report' },
    { key: 'completed',         label: 'Done',      full: 'Complete' },
  ];

  const STAGE_DESCS = {
    waiting_earnings:  'Analysis will start after the projected earnings release window',
    earnings_refresh:  'Fetching same-day earnings actuals and current headlines',
    seed_doc:          'Synthesizing Kronos forecasts, EPM models, technicals & news',
    council_personas:  'Specialist analysts deliberating across four rounds',
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

  function _formatCountdown(ms) {
    const totalSec = Math.max(0, Math.floor(ms / 1000));
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function _tickCountdown() {
    const queueEl = document.getElementById('dalQueueInfo');
    if (!queueEl || !_notBeforeTarget) return;
    const remaining = _notBeforeTarget - Date.now();
    if (remaining > 0) {
      queueEl.textContent = `Waiting for earnings release — ${_formatCountdown(remaining)} remaining`;
    } else {
      queueEl.textContent = 'Earnings window reached — fetching actuals…';
      clearInterval(_countdownTimer);
      _countdownTimer = null;
      _notBeforeTarget = null;
    }
    queueEl.style.display = '';
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

    const isWaitingEarnings = status.stage === 'waiting_earnings';
    if (isWaitingEarnings) {
      if (nameEl) nameEl.textContent = stageMeta.full;
      if (descEl) descEl.textContent = STAGE_DESCS.waiting_earnings;
    }
    if (isWaitingEarnings && status.not_before) {
      _notBeforeTarget = new Date(status.not_before).getTime();
      _tickCountdown();
      if (!_countdownTimer) _countdownTimer = setInterval(_tickCountdown, 1000);
    } else if (!isWaitingEarnings && _countdownTimer) {
      clearInterval(_countdownTimer);
      _countdownTimer = null;
      _notBeforeTarget = null;
    }

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
      if (isQueued && status.not_before) {
        const target = new Date(status.not_before).getTime();
        const remaining = Math.max(0, Math.round((target - Date.now()) / 60000));
        queueEl.textContent = remaining > 0
          ? `Waiting for earnings window - starts in ~${remaining} min`
          : 'Earnings window reached - starting soon';
        queueEl.style.display = '';
      } else if (isQueued && status.queue_position) {
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
          runBtn.onclick = () => _runDeepAnalysis(_currentTicker, true);
        }
        const lab = document.getElementById('deepAnalysisLab');
        if (lab) lab.scrollIntoView({ behavior: 'smooth', block: 'start' });
      };
    }
  }

  function _stopPolling() {
    if (_pollTimer)      { clearInterval(_pollTimer);      _pollTimer      = null; }
    if (_etaTimer)       { clearInterval(_etaTimer);       _etaTimer       = null; }
    if (_countdownTimer) { clearInterval(_countdownTimer); _countdownTimer = null; }
    _notBeforeTarget = null;
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

  async function _runDeepAnalysis(ticker, forceFresh = false) {
    _jobStartedAt   = null;
    _queueWaitMin   = 0;
    _queueWaitSetAt = null;
    const btn = document.getElementById('dalRunBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Starting…'; }

    try {
      const url = `/api/deep/${encodeURIComponent(ticker)}` + (forceFresh ? '?force_fresh=1' : '');
      const body = (_roster && _roster.length) ? JSON.stringify({ roster: _roster }) : '{}';
      const r = await fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body,
      });
      if (!r.ok) {
        let detail = `HTTP ${r.status}`;
        try { const e = await r.json(); if (e.detail) detail = e.detail; } catch (_) {}
        throw new Error(detail);
      }
      const data = await r.json();
      if (!data.ok) throw new Error(data.detail || 'Failed to start');
      _saveJob(ticker, data.job_id);
      if (data.earnings_triggered) {
        const errEl = document.getElementById('dalError');
        if (errEl) {
          errEl.textContent = 'New earnings data detected — running fresh analysis.';
          errEl.style.display = '';
          errEl.style.color = 'var(--ds-amber, #d4a017)';
        }
      }
      _startPolling(data.job_id);
    } catch (err) {
      if (btn) { btn.disabled = false; btn.textContent = 'Run Analyst Council'; }
      const errEl = document.getElementById('dalError');
      if (errEl) { errEl.textContent = 'Could not start: ' + err.message; errEl.style.display = ''; }
    }
  }

  // ── Council Builder ──────────────────────────────────────────────────
  let _library = null;          // {members, trait_axes, default_roster, max_council, min_council}
  let _roster = null;           // [{id, traits:{}, custom_text}]
  let _activeCustomizeId = null;
  const PER_MEMBER_MIN = 2.7;   // rough runtime per analyst

  async function _loadLibrary() {
    if (_library) return _library;
    try {
      const r = await fetch('/api/council/library', { credentials: 'include' });
      if (!r.ok) return null;
      const d = await r.json();
      if (d && d.ok) _library = d;
      return _library;
    } catch (_) { return null; }
  }

  function _memberById(id) {
    return (_library && _library.members.find(m => m.id === id)) || null;
  }
  function _rosterEntry(id) { return _roster && _roster.find(e => e.id === id); }
  function _kindCount(kind) {
    return (_roster || []).filter(e => { const m = _memberById(e.id); return m && m.kind === kind; }).length;
  }
  function _rosterValid() {
    if (!_roster) return false;
    const n = _roster.length;
    return n >= (_library.min_council || 3) && n <= (_library.max_council || 8)
      && _kindCount('bull') >= 1 && _kindCount('bear') >= 1;
  }

  function _initRoster() {
    if (_roster || !_library) return;
    _roster = (_library.default_roster || []).map(id => ({ id, traits: {}, custom_text: '' }));
  }

  function _kindTag(kind) {
    const cls = kind === 'bull' ? 'dal-tag-bull' : kind === 'bear' ? 'dal-tag-bear' : 'dal-tag-neutral';
    const label = kind === 'bull' ? 'Bull' : kind === 'bear' ? 'Bear' : 'Neutral';
    return `<span class="dal-kind-tag ${cls}">${label}</span>`;
  }

  function _renderBuilder() {
    if (!_library) return;
    _initRoster();
    const grid = document.getElementById('dalMemberGrid');
    const summary = document.getElementById('dalRosterSummary');
    const warn = document.getElementById('dalBuilderWarn');
    const runBtn = document.getElementById('dalRunBtn');
    const poweredCount = document.getElementById('dalPoweredCount');
    if (!grid) return;

    const n = _roster.length;
    const est = Math.max(1, Math.round(n * PER_MEMBER_MIN));
    const bulls = _kindCount('bull'), bears = _kindCount('bear');
    if (summary) {
      const ok = _rosterValid();
      summary.innerHTML =
        `<span class="dal-count">${n}/${_library.max_council}</span>` +
        `<span class="dal-balance ${bulls >= 1 && bears >= 1 ? 'ok' : 'bad'}">⚖ ${bulls} bull · ${bears} bear ${ok ? '✓' : ''}</span>` +
        `<span class="dal-est">~${est} min</span>`;
    }
    if (poweredCount) poweredCount.textContent = `${n} Analyst${n === 1 ? '' : 's'}`;

    grid.innerHTML = _library.members.map(m => {
      const sel = !!_rosterEntry(m.id);
      const customized = sel && _isCustomized(m.id);
      return `<div class="dal-member ${sel ? 'is-selected' : ''}" data-id="${m.id}">
        <div class="dal-member-top">
          <span class="dal-member-name">${m.title}</span>
          ${_kindTag(m.kind)}
        </div>
        <div class="dal-member-blurb">${m.blurb || ''}</div>
        <div class="dal-member-chips">
          ${m.style_label ? `<span class="dal-chip">${m.style_label}</span>` : ''}
          ${m.econ_label ? `<span class="dal-chip">${m.econ_label}</span>` : ''}
        </div>
        <div class="dal-member-actions">
          <button type="button" class="dal-toggle-btn" data-act="toggle" data-id="${m.id}">${sel ? '✓ Selected' : '+ Add'}</button>
          ${sel ? `<button type="button" class="dal-gear-btn ${customized ? 'is-on' : ''}" data-act="customize" data-id="${m.id}" title="Customize personality">⚙</button>` : ''}
        </div>
      </div>`;
    }).join('');

    grid.querySelectorAll('[data-act]').forEach(b => {
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = b.getAttribute('data-id');
        if (b.getAttribute('data-act') === 'toggle') _toggleMember(id);
        else _openCustomize(id);
      });
    });

    if (warn) warn.textContent = _rosterValid() ? '' :
      (n > _library.max_council ? `Max ${_library.max_council} members.`
        : _kindCount('bull') < 1 ? 'Add at least one bullish analyst.'
        : _kindCount('bear') < 1 ? 'Add at least one bearish analyst.'
        : `Pick at least ${_library.min_council} analysts.`);

    // Gate the run button on a valid roster (only while builder governs the launch view).
    if (runBtn && !runBtn.dataset.running) {
      runBtn.disabled = !_rosterValid();
      runBtn.title = _rosterValid() ? '' : 'Council needs 1 bull + 1 bear and 3-8 members';
    }
    if (_activeCustomizeId && !_rosterEntry(_activeCustomizeId)) {
      _activeCustomizeId = null;
      const panel = document.getElementById('dalCustomizePanel');
      if (panel) panel.style.display = 'none';
    } else if (_activeCustomizeId) {
      _renderCustomize(_activeCustomizeId);
    }
  }

  function _isCustomized(id) {
    const e = _rosterEntry(id);
    if (!e) return false;
    return (e.custom_text && e.custom_text.trim()) || Object.values(e.traits || {}).some(v => v);
  }

  function _toggleMember(id) {
    const i = _roster.findIndex(e => e.id === id);
    if (i >= 0) {
      _roster.splice(i, 1);
      if (_activeCustomizeId === id) _activeCustomizeId = null;
    } else {
      if (_roster.length >= (_library.max_council || 8)) { _renderBuilder(); return; }
      _roster.push({ id, traits: {}, custom_text: '' });
    }
    _renderBuilder();
  }

  function _openCustomize(id) {
    _activeCustomizeId = (_activeCustomizeId === id) ? null : id;
    const panel = document.getElementById('dalCustomizePanel');
    if (!panel) return;
    if (!_activeCustomizeId) { panel.style.display = 'none'; return; }
    _renderCustomize(id);
  }

  function _renderCustomize(id) {
    const panel = document.getElementById('dalCustomizePanel');
    const m = _memberById(id);
    const entry = _rosterEntry(id);
    if (!panel || !m || !entry) return;
    panel.style.display = '';
    const axes = _library.trait_axes;
    const selects = Object.keys(axes).map(axisKey => {
      const axis = axes[axisKey];
      const cur = (entry.traits || {})[axisKey] || '';
      const opts = ['<option value="">Default</option>'].concat(
        axis.options.map(o => `<option value="${o}" ${o === cur ? 'selected' : ''}>${o}</option>`)
      ).join('');
      return `<label class="dal-trait"><span>${axis.label}</span><select data-axis="${axisKey}">${opts}</select></label>`;
    }).join('');
    const max = _library.custom_text_max || 600;
    panel.innerHTML = `
      <div class="dal-customize-head">Customize <strong>${m.title}</strong> ${_kindTag(m.kind)}
        <button type="button" class="dal-customize-close" data-close="1">✕</button></div>
      <div class="dal-trait-row">${selects}</div>
      <div class="dal-custom-guide">Write a custom personality (optional). Describe their <em>investing philosophy, what evidence they weight most, temperament, and economic worldview</em>.<br>
        <span class="dal-custom-eg">e.g. "A contrarian deep-value investor in the Graham tradition who distrusts momentum, demands a margin of safety, and reads the current rate regime as restrictive."</span></div>
      <textarea class="dal-custom-text" maxlength="${max}" placeholder="Leave blank to use the default personality…">${(entry.custom_text || '').replace(/</g, '&lt;')}</textarea>
      <div class="dal-custom-foot"><span class="dal-custom-count">0/${max}</span>
        <span class="dal-custom-note">Style only — analysts always stay grounded in the data.</span></div>`;

    panel.querySelectorAll('select[data-axis]').forEach(sel => {
      sel.addEventListener('change', () => {
        entry.traits = entry.traits || {};
        if (sel.value) entry.traits[sel.getAttribute('data-axis')] = sel.value;
        else delete entry.traits[sel.getAttribute('data-axis')];
        _renderBuilderGearOnly();
      });
    });
    const ta = panel.querySelector('.dal-custom-text');
    const cnt = panel.querySelector('.dal-custom-count');
    const _upd = () => { if (cnt) cnt.textContent = `${ta.value.length}/${max}`; };
    _upd();
    ta.addEventListener('input', () => { entry.custom_text = ta.value; _upd(); _renderBuilderGearOnly(); });
    panel.querySelector('[data-close]')?.addEventListener('click', () => { _activeCustomizeId = null; panel.style.display = 'none'; _renderBuilderGearOnly(); });
  }

  // Light refresh of just the gear "customized" state + summary, without
  // re-rendering the whole grid (keeps focus in the textarea).
  function _renderBuilderGearOnly() {
    const grid = document.getElementById('dalMemberGrid');
    if (!grid) return;
    (_roster || []).forEach(e => {
      const gear = grid.querySelector(`.dal-gear-btn[data-id="${e.id}"]`);
      if (gear) gear.classList.toggle('is-on', _isCustomized(e.id));
    });
  }

  async function _initBuilder() {
    const lib = await _loadLibrary();
    if (!lib) return;
    _initRoster();
    _renderBuilder();
    const toggle = document.getElementById('dalBuilderToggle');
    const builder = document.getElementById('dalCouncilBuilder');
    const chev = document.getElementById('dalBuilderChevron');
    if (toggle && builder && !toggle.dataset.wired) {
      toggle.dataset.wired = '1';
      toggle.addEventListener('click', () => {
        const open = builder.style.display === 'none';
        builder.style.display = open ? '' : 'none';
        if (chev) chev.textContent = open ? '▴' : '▾';
        if (open) _renderBuilder();
      });
    }
    const reset = document.getElementById('dalResetRoster');
    if (reset && !reset.dataset.wired) {
      reset.dataset.wired = '1';
      reset.addEventListener('click', () => {
        _roster = (_library.default_roster || []).map(id => ({ id, traits: {}, custom_text: '' }));
        _activeCustomizeId = null;
        const panel = document.getElementById('dalCustomizePanel');
        if (panel) panel.style.display = 'none';
        _renderBuilder();
      });
    }
  }

  // Called by search.js after each ticker loads
  window.initDeepAnalysis = function (ticker) {
    _stopPolling();
    _currentTicker = ticker.toUpperCase();

    const lab = document.getElementById('deepAnalysisLab');
    if (!lab) return;
    lab.style.display = '';

    // Load the council library + render the builder (collapsed by default).
    _initBuilder();

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
        runBtn.onclick = () => _runDeepAnalysis(_currentTicker, true);
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
