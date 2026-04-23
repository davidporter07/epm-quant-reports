/**
 * chrome.js — Shared EPM chrome renderer
 * Injects the settings overlay + drawer + topbar into <div id="epmChrome">.
 * Must be loaded synchronously (no defer) BEFORE site.js so all expected
 * DOM nodes exist when site.js runs its event-wiring and auth setup.
 *
 * DOM contract preserved for site.js compatibility:
 *   #settingsOverlay .settings-overlay
 *   #settingsDrawer  .settings-drawer
 *   #openSettingsBtn .settings-gear-btn  (wired by setupSettingsDrawer)
 *   #closeSettingsBtn                    (wired by setupSettingsDrawer)
 *   [data-pref-theme]  [data-pref-animations]  [data-pref-range]  [data-pref-news]
 *   .topbar                              (queried by setupChromeEffects, mountGlobalHeaderSearch)
 *   .topbar .brand-block                 (queried by mountGlobalHeaderSearch)
 *   .topbar .main-nav  .nav-link         (queried by setActiveNav, mountGlobalHeaderSearch)
 *   .topbar .topbar-nav                  (queried by mountGlobalHeaderSearch — kept hidden via CSS)
 *   .topbar .top-actions  #openSettingsBtn  (queried by mountAuthActions)
 *   #menuToggleBtn  .menu-toggle         (pre-created here so site.js finds it, not duplicated)
 */
(function () {
  'use strict';

  // ── Density pref bootstrap (runs synchronously before paint) ──────────────
  (function bootstrapDensity() {
    try {
      var pref = localStorage.getItem('epm_density_pref') || 'comfortable';
      document.documentElement.dataset.density = pref;
      document.body.dataset.density = pref;
    } catch (_) {}
  })();

  // ── Nav link definitions ──────────────────────────────────────────────────
  var NAV_LINKS = [
    { href: '/',            label: 'Home' },
    { href: '/markets',     label: 'Markets' },
    { href: '/forecasting', label: 'Forecasting' },
    { href: '/portfolios',  label: 'Portfolios' },
    { href: '/search',      label: 'Fund Search' },
  ];

  var PAGE_META = {
    home: {
      eyebrow: 'Platform Overview',
      title: 'Home',
      subtitle: 'Start with a market snapshot, then move into macro, forecasts, portfolios, or search.'
    },
    markets: {
      eyebrow: 'Macro Dashboard',
      title: 'Markets',
      subtitle: 'Follow cross-market posture, major charts, and live macro context.'
    },
    forecasting: {
      eyebrow: 'Model Output',
      title: 'Forecasting',
      subtitle: 'Review MAG7 consensus forecasts, model commentary, and leaderboard history.'
    },
    portfolios: {
      eyebrow: 'Strategy Monitor',
      title: 'Portfolios',
      subtitle: 'Track leaders, laggards, and the full monitored holdings universe.'
    },
    search: {
      eyebrow: 'Research Tool',
      title: 'Fund Search',
      subtitle: 'Search any ticker or fund for chart, risk, fundamentals, sentiment, and deeper analysis.'
    }
  };

  // ── Bottom-nav icon SVGs (20×20 viewBox) ─────────────────────────────────
  var BOTTOM_NAV_ICONS = {
    home: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l7-6 7 6v8a1 1 0 01-1 1H4a1 1 0 01-1-1z"/><path d="M7 18v-5h6v5"/></svg>',
    markets: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="2,14 7,9 11,13 18,4"/><polyline points="14,4 18,4 18,8"/></svg>',
    forecasting: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="10" width="4" height="8"/><rect x="8" y="6" width="4" height="12"/><rect x="14" y="2" width="4" height="16"/></svg>',
    portfolios: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="16" height="11" rx="2"/><path d="M7 7V5a2 2 0 016 0v2"/></svg>',
    search: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="9" r="6"/><line x1="14" y1="14" x2="17.5" y2="17.5"/></svg>',
  };

  // ── Helpers ───────────────────────────────────────────────────────────────

  function _activePage() {
    return document.body.dataset.page || '';
  }

  function _activeHref() {
    var map = {
      home:         '/',
      markets:      '/markets',
      forecasting:  '/forecasting',
      portfolios:   '/portfolios',
      search:       '/search',
    };
    return map[_activePage()] || window.location.pathname;
  }

  function _buildNavLinks(cls) {
    var active = _activeHref();
    return NAV_LINKS.map(function (item) {
      var isActive = (item.href === '/' && active === '/') ||
                     (item.href !== '/' && active.startsWith(item.href));
      return '<a class="' + cls + (isActive ? ' active' : '') + '" href="' + item.href + '">' + item.label + '</a>';
    }).join('');
  }

  function _buildBottomNav() {
    var active = _activeHref();
    var items = [
      { href: '/',            label: 'Home',       icon: BOTTOM_NAV_ICONS.home },
      { href: '/markets',     label: 'Markets',    icon: BOTTOM_NAV_ICONS.markets },
      { href: '/forecasting', label: 'Forecast',   icon: BOTTOM_NAV_ICONS.forecasting },
      { href: '/portfolios',  label: 'Portfolios', icon: BOTTOM_NAV_ICONS.portfolios },
      { href: '/search',      label: 'Search',     icon: BOTTOM_NAV_ICONS.search },
    ];
    return items.map(function (item) {
      var isActive = (item.href === '/' && active === '/') ||
                     (item.href !== '/' && active.startsWith(item.href));
      return '<a class="ds-bottom-nav-item' + (isActive ? ' active' : '') + '" href="' + item.href + '" aria-label="' + item.label + '">' +
               '<span class="ds-bottom-nav-icon">' + item.icon + '</span>' +
               '<span class="ds-bottom-nav-label">' + item.label + '</span>' +
             '</a>';
    }).join('');
  }

  function _buildPageContext() {
    var page = _activePage();
    var meta = PAGE_META[page];
    if (!meta) return '';

    return '' +
      '<div class="page-context-strip">' +
        '<div class="page-context-main">' +
          '<div class="page-context-eyebrow">' + meta.eyebrow + '</div>' +
          '<div class="page-context-title-row">' +
            '<h2 class="page-context-title">' + meta.title + '</h2>' +
            '<span class="page-context-active">Current Page</span>' +
          '</div>' +
          '<p class="page-context-subtitle">' + meta.subtitle + '</p>' +
        '</div>' +
      '</div>';
  }

  // ── Main render ───────────────────────────────────────────────────────────

  function render() {
    var mount = document.getElementById('epmChrome');
    if (!mount) return;

    mount.innerHTML =
      // Settings overlay
      '<div id="settingsOverlay" class="settings-overlay"></div>' +

      // Settings drawer — must contain all [data-pref-*] chips for site.js
      '<aside id="settingsDrawer" class="settings-drawer">' +
        '<div class="section-title-row">' +
          '<h3>Settings</h3>' +
          '<button id="closeSettingsBtn" class="btn btn-ghost">Close</button>' +
        '</div>' +
        '<div class="settings-group">' +
          '<h4>Theme</h4>' +
          '<div class="radio-row">' +
            '<div class="radio-chip" data-pref-theme="dark">Dark</div>' +
            '<div class="radio-chip" data-pref-theme="light">Light</div>' +
            '<div class="radio-chip" data-pref-theme="system">System</div>' +
          '</div>' +
        '</div>' +
        '<div class="settings-group">' +
          '<h4>Animations</h4>' +
          '<div class="radio-row">' +
            '<div class="radio-chip" data-pref-animations="on">On</div>' +
            '<div class="radio-chip" data-pref-animations="off">Reduced</div>' +
          '</div>' +
        '</div>' +
        '<div class="settings-group">' +
          '<h4>Default chart range</h4>' +
          '<div class="radio-row">' +
            '<div class="radio-chip" data-pref-range="6m">6M</div>' +
            '<div class="radio-chip" data-pref-range="1y">1Y</div>' +
            '<div class="radio-chip" data-pref-range="3y">3Y</div>' +
            '<div class="radio-chip" data-pref-range="all">ALL</div>' +
          '</div>' +
        '</div>' +
        '<div class="settings-group">' +
          '<h4>News on search by default</h4>' +
          '<div class="radio-row">' +
            '<div class="radio-chip" data-pref-news="true">On</div>' +
            '<div class="radio-chip" data-pref-news="false">Off</div>' +
          '</div>' +
        '</div>' +
      '</aside>' +

      // Topbar — new layout: nav LEFT, brand-block RIGHT, top-actions far-right
      // main-nav comes before brand-block in DOM so CSS margin-right:auto works naturally
      '<header class="topbar fade-in">' +
        // Nav links (desktop inline, left side)
        '<nav class="main-nav">' +
          _buildNavLinks('nav-link') +
        '</nav>' +
        // Legacy dup nav — kept hidden, required by mountGlobalHeaderSearch
        '<nav class="topbar-nav">' +
          _buildNavLinks('topbar-nav-link nav-link') +
        '</nav>' +
        // Brand block (right side): hamburger (mobile) | search (desktop) | logo | name
        // #menuToggleBtn pre-created here so site.js finds it and skips creating a duplicate
        '<div class="brand-block">' +
          '<button id="menuToggleBtn" type="button" class="menu-toggle" ' +
            'aria-label="Open site navigation" aria-expanded="false">' +
            '<span></span><span></span><span></span>' +
          '</button>' +
          '<img class="brand-logo" src="/static/epm_logo.png?v=20260322f" alt="EPM Financial" />' +
          '<div class="brand-copy">' +
            '<h1>EPM Market Intelligence</h1>' +
          '</div>' +
        '</div>' +
        // Top actions far-right (density, settings, user badge)
        '<div class="top-actions">' +
          '<button class="ds-density-btn" id="dsDensityBtn" type="button" ' +
            'aria-label="Toggle density" title="Toggle compact mode">&#9783;</button>' +
          '<button id="openSettingsBtn" class="btn btn-icon settings-gear-btn" ' +
            'type="button" aria-label="Open settings" title="Settings"></button>' +
        '</div>' +
      '</header>' +

      // Mobile bottom nav (hidden on desktop via CSS)
      '<nav class="ds-bottom-nav" aria-label="Site navigation">' +
        _buildBottomNav() +
      '</nav>' +

      _buildPageContext();

    // Apply current density to body (in case bootstrap ran before body existed)
    _syncDensityToBody();
  }

  // ── Density toggle ────────────────────────────────────────────────────────

  function getDensity() {
    try { return localStorage.getItem('epm_density_pref') || 'comfortable'; } catch (_) { return 'comfortable'; }
  }

  function setDensity(val) {
    try { localStorage.setItem('epm_density_pref', val); } catch (_) {}
    _syncDensityToBody();
  }

  function _syncDensityToBody() {
    var pref = getDensity();
    document.body.dataset.density = pref;
    document.documentElement.dataset.density = pref;
  }

  function _wireDensityToggle() {
    var btn = document.getElementById('dsDensityBtn');
    if (!btn) return;
    btn.addEventListener('click', function () {
      var next = getDensity() === 'dense' ? 'comfortable' : 'dense';
      setDensity(next);
    });
  }

  // ── Active nav helper (called after render or on route change) ────────────

  function setActive(pageKey) {
    document.body.dataset.page = pageKey;
    var active = _activeHref();
    document.querySelectorAll('.nav-link, .topbar-nav-link').forEach(function (link) {
      var href = link.getAttribute('href');
      var isActive = (href === '/' && active === '/') ||
                     (href !== '/' && active.startsWith(href));
      link.classList.toggle('active', isActive);
    });
    // Also update bottom nav active state
    document.querySelectorAll('.ds-bottom-nav-item').forEach(function (link) {
      var href = link.getAttribute('href');
      var isActive = (href === '/' && active === '/') ||
                     (href !== '/' && active.startsWith(href));
      link.classList.toggle('active', isActive);
    });
  }

  // ── DOMContentLoaded: wire density toggle after DOM is ready ─────────────
  document.addEventListener('DOMContentLoaded', function () {
    _wireDensityToggle();
    _syncDensityToBody();
  });

  // ── Public API ────────────────────────────────────────────────────────────
  window.EPMChrome = {
    render:     render,
    setActive:  setActive,
    getDensity: getDensity,
    setDensity: setDensity,
  };

  // Auto-render if mount exists at parse time
  if (document.getElementById('epmChrome')) {
    render();
  }
})();
