import os
import sys
import smtplib
import json
import ssl
import subprocess
import logging
import html as html_lib
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import holidays
except Exception:
    holidays = None
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication

# Always resolve paths relative to this file (critical for Task Scheduler)
ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo('America/Chicago')

# --- Configuration ---
FROM = "davidporter0731@gmail.com"
TO = "dporter@epmfinancial.com"
def _build_subject():
    """Dynamic subject line: EPM Markets Recap with S&P direction.

    Set SUBJECT_PREFIX env var to prepend a tag (e.g. '[Corrected] ') for one-off resends.
    """
    prefix = os.getenv("SUBJECT_PREFIX", "")
    base = f"EPM Markets Recap  {date.today().strftime('%B %d, %Y')}"
    try:
        if COMMENTARY_JSON.exists():
            with open(COMMENTARY_JSON, 'r', encoding='utf-8') as _f:
                _d = json.load(_f)
            sp = _d.get('market_snapshot', {}).get('S&P 500', {})
            pct = sp.get('pct_change')
            if pct is not None:
                sign  = '+' if float(pct) >= 0 else ''
                arrow = '' if float(pct) >= 0 else ''
                subject = f"{base}  |  S&P {arrow} {sign}{pct}%"
                return f"{prefix}{subject}" if prefix else subject
    except Exception:
        pass
    return f"{prefix}{base}" if prefix else base

SUBJECT = _build_subject()

# Prefer a dedicated email-sized logo if present
_logo1 = ROOT / 'epm_logo_email.png'
_logo2 = ROOT / 'epm_logo.png'
LOGO_PATH = str(_logo1 if _logo1.exists() else _logo2)
LOG_FILE = str(ROOT / 'email_log.txt')
SENT_LOG = str(ROOT / 'email_sent.log')
COMMENTARY_JSON = ROOT / 'data' / 'latest_commentary.json'
# PDF is written into the GitHub Pages repo (epm-quant-reports)
_PDF1 = ROOT / 'epm-quant-reports' / 'report.pdf'
_PDF2 = ROOT / 'report.pdf'
PDF_REPORT = str(_PDF1 if _PDF1.exists() else _PDF2)
GITHUB_LINK = "https://epm-market-intelligence.com"

# Prefer venv python if present; fall back to current interpreter
_VENV_PY = ROOT / '.venv' / 'Scripts' / 'python.exe'
if not _VENV_PY.exists():
    _VENV_PY = ROOT / '.venv' / 'bin' / 'python'
PY = str(_VENV_PY) if _VENV_PY.exists() else sys.executable

# --- Logging setup ---
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s:%(levelname)s:%(message)s")

# --- Market open check ---
def is_market_open():
    today = date.today()
    us_holidays = holidays.US() if holidays is not None else set()
    return today.weekday() < 5 and today not in us_holidays

# --- Already sent today? ---
today_tag = datetime.now(TZ).strftime('%Y-%m-%d')

def already_sent_today():
    if not os.path.exists(SENT_LOG):
        return False
    try:
        with open(SENT_LOG, 'r', encoding='utf-8') as f:
            lines = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
        return any(ln.startswith(today_tag) for ln in lines)
    except Exception:
        return False

def mark_sent_today():
    stamp = datetime.now(TZ).isoformat(timespec='seconds')
    with open(SENT_LOG, 'a', encoding='utf-8') as f:
        f.write(stamp + '\n')

# --- Attach logo ---
def attach_image(path, cid_name):
    if not os.path.exists(path):
        logging.warning(f" Missing image: {path}")
        return None
    with open(path, "rb") as img:
        mime = MIMEImage(img.read(), _subtype="png")
        mime.add_header("Content-ID", f"<{cid_name}>")
        mime.add_header("Content-Disposition", "inline", filename=os.path.basename(path))
        return mime


def load_commentary_snapshot():
    if not COMMENTARY_JSON.exists():
        return None
    try:
        with open(COMMENTARY_JSON, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logging.warning(f" Could not load commentary snapshot: {e}")
        return None


def _clean(value):
    return ' '.join(str(value or '').strip().split())


def _arrow(pct):
    """Return  or  based on sign."""
    try:
        return '' if float(pct) >= 0 else ''
    except Exception:
        return ''


def _pct_color(pct):
    try:
        return '#16a34a' if float(pct) >= 0 else '#dc2626'
    except Exception:
        return '#374151'


def _section_header(title: str) -> str:
    return (
        f'<p style="margin:22px 0 8px 0;font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:#6b7280;border-bottom:1px solid #e5e7eb;padding-bottom:5px;">'
        f'{html_lib.escape(title)}</p>'
    )


def _bullet_list(items: list, color: str = '#374151') -> str:
    if not items:
        return ''
    rows = ''
    for item in items:
        text = _clean(str(item))
        if not text:
            continue
        rows += (
            f'<p style="margin:5px 0;padding-left:14px;color:{color};font-size:13px;line-height:1.5;">'
            f'<span style="margin-left:-14px;margin-right:6px;">&#8226;</span>'
            f'{html_lib.escape(text)}</p>'
        )
    return rows


def _asset_table_html(title: str, data_dict: dict) -> tuple[str, list]:
    """Render a cross-asset data table matching the email snapshot style.
    Returns (html_string, text_lines). Handles yields, FX, spread (bps), and $ assets.
    """
    if not data_dict:
        return '', []
    rows_html = ''
    text_lines = []
    for label, d in data_dict.items():
        if not isinstance(d, dict):
            continue
        level = d.get('level', '')
        pct   = d.get('pct_change', '')
        chg   = d.get('change', '')
        is_spread = 'Spread' in label
        is_yield  = 'Yield' in label or 'Rate' in label
        is_fx     = '/' in label and 'Bitcoin' not in label
        is_btc    = 'Bitcoin' in label
        is_dxy    = 'Index' in label and 'Dollar' in label
        try:
            lv = float(level)
            if is_spread:
                level_fmt = f'{lv:.0f} bps'
            elif is_yield:
                level_fmt = f'{lv:.3f}'
            elif is_fx:
                level_fmt = f'{lv:.4f}'
            elif is_dxy:
                level_fmt = f'{lv:,.2f}'
            else:
                level_fmt = f'${lv:,.2f}'
        except Exception:
            level_fmt = str(level)
        if is_spread:
            try:
                c_val = float(chg)
                pct_str = f'{c_val:+.0f} bps'
                color = '#16a34a' if c_val >= 0 else '#dc2626'
            except Exception:
                pct_str, color = '', '#6b7280'
            arrow = ''
        else:
            arrow = _arrow(pct)
            color = _pct_color(pct)
            try:
                pct_str = f'{float(pct):+.2f}%'
            except Exception:
                pct_str = ''
        rows_html += (
            f'<tr>'
            f'<td style="padding:5px 12px 5px 0;color:#374151;font-size:13px;">{html_lib.escape(label)}</td>'
            f'<td style="padding:5px 12px 5px 0;color:#111827;font-size:13px;font-weight:600;">{html_lib.escape(level_fmt)}</td>'
            f'<td style="padding:5px 0;color:{color};font-size:13px;font-weight:600;">{arrow} {html_lib.escape(pct_str)}</td>'
            f'</tr>'
        )
        text_lines.append(f'{label}: {level_fmt}  {arrow} {pct_str}')
    if not rows_html:
        return '', []
    html_out = (
        '<div style="margin:14px 0;">'
        f'<p style="margin:0 0 8px 0;font-weight:700;color:#1e2a44;font-size:12px;'
        f'text-transform:uppercase;letter-spacing:0.05em;">{html_lib.escape(title)}</p>'
        f'<table style="border-collapse:collapse;">{rows_html}</table>'
        '</div>'
    )
    return html_out, text_lines


def _build_premarket_block(c: dict) -> tuple[str, list]:
    """Build the Pre-Market Look block: futures, earnings, Fed speakers, key data.
    Returns (html_string, text_lines). Returns empty strings if nothing to show.
    """
    today_iso = date.today().isoformat()

    # ── Futures ─────────────────────────────────────────────────────────────
    futures_raw = c.get('futures_table') or {}
    fut_rows = ''
    fut_txt  = []
    for name, d in futures_raw.items():
        if not isinstance(d, dict):
            continue
        try:
            lv  = float(d.get('level', 0))
            pct = float(d.get('pct_change', 0))
            lv_fmt  = f'{lv:,.0f}'
            pct_str = f'{pct:+.2f}%'
            clr = '#16a34a' if pct >= 0 else '#dc2626'
            short = name.replace(' Futures', '')
            fut_rows += (
                f'<tr>'
                f'<td style="padding:3px 12px 3px 0;color:#374151;font-size:12px;">{html_lib.escape(short)}</td>'
                f'<td style="padding:3px 12px 3px 0;color:#111827;font-size:12px;font-weight:600;">{lv_fmt}</td>'
                f'<td style="padding:3px 0;color:{clr};font-size:12px;font-weight:600;">{html_lib.escape(pct_str)}</td>'
                f'</tr>'
            )
            fut_txt.append(f'  {short}: {lv_fmt}  {pct_str}')
        except Exception:
            continue

    # ── Today's Earnings ────────────────────────────────────────────────────
    earnings_today = [
        e for e in (c.get('today_earnings') or [])
        if str(e.get('date', ''))[:10] == today_iso and e.get('symbol')
    ]
    earn_parts = []
    earn_txt   = []
    _earn_with_est = [e for e in earnings_today[:8] if e.get('eps_estimate') is not None]
    for idx, e in enumerate(_earn_with_est):
        sym  = html_lib.escape(str(e.get('symbol', '')))
        hour = str(e.get('hour') or '').upper() or '?'
        est  = e.get('eps_estimate')
        est_str = f'${est:.2f}E'
        is_last = idx == len(_earn_with_est) - 1
        sep = '' if is_last else 'padding-right:14px;border-right:1px solid #e5e7eb;'
        earn_parts.append(
            f'<span style="display:inline-block;margin:0 14px 4px 0;{sep}white-space:nowrap;">'
            f'<b>{sym}</b> <span style="color:#6b7280;font-size:11px;">{hour}</span>'
            f' <span style="color:#374151;">{html_lib.escape(est_str)}</span></span>'
        )
        earn_txt.append(f'{e.get("symbol","")} {hour} {est_str}')

    # ── Fed Speakers ────────────────────────────────────────────────────────
    fed_items = c.get('fed_speakers') or []
    fed_parts = []
    fed_txt   = []
    for sp in fed_items[:4]:
        name_txt  = html_lib.escape(str(sp.get('speaker', '')))
        time_et   = html_lib.escape(str(sp.get('time_et', '')))
        topic     = html_lib.escape(str(sp.get('topic', ''))[:80])
        line = f'<b>{name_txt}</b>'
        if time_et:
            line += f' <span style="color:#6b7280;font-size:11px;">{time_et} ET</span>'
        if topic:
            line += f' — <span style="color:#374151;">{topic}</span>'
        fed_parts.append(f'<span style="display:block;margin:2px 0;">{line}</span>')
        fed_txt.append(f'{sp.get("speaker","")} {time_et}: {sp.get("topic","")}')

    # ── This Week's Key Economic Events (next 5 trading days) ───────────────
    _week_days = _next_n_trading_days(date.today(), 5)
    _week_iso  = {d.isoformat(): d for d in _week_days}

    econ_by_day: dict[str, list] = {}
    try:
        _cal_path = ROOT / 'data' / 'economic_calendar.json'
        if _cal_path.exists():
            with open(_cal_path, 'r', encoding='utf-8') as _cf:
                _cal = json.load(_cf)
            for ev in (_cal.get('events') or []):
                d_iso = str(ev.get('date', ''))[:10]
                if d_iso in _week_iso and ev.get('importance') in ('high', 'medium'):
                    econ_by_day.setdefault(d_iso, []).append(ev)
    except Exception:
        pass

    econ_parts = []
    econ_txt   = []
    _total_shown = 0
    for d_iso in sorted(econ_by_day.keys()):
        if _total_shown >= 6:
            break
        day_obj  = _week_iso[d_iso]
        day_label = 'Today' if d_iso == today_iso else day_obj.strftime('%a')
        label_style = 'font-weight:700;color:#1e3a8a;' if d_iso == today_iso else 'font-weight:600;color:#374151;'
        for ev in econ_by_day[d_iso][:2]:
            if _total_shown >= 6:
                break
            evname    = html_lib.escape(str(ev.get('event', '')))
            cons      = ev.get('consensus')
            prev      = ev.get('previous')
            imp       = str(ev.get('importance', '')).lower()
            imp_color = '#dc2626' if imp == 'high' else '#ea580c'
            suffix    = ''
            suf_txt   = ''
            if cons is not None:
                suffix  += f' &nbsp;<span style="color:#374151;">Cons: <b>{html_lib.escape(str(cons))}</b></span>'
                suf_txt += f'  Cons: {cons}'
            if prev is not None:
                suffix  += f' &nbsp;<span style="color:#6b7280;">Prev: {html_lib.escape(str(prev))}</span>'
                suf_txt += f'  Prev: {prev}'
            econ_parts.append(
                f'<span style="display:block;margin:2px 0;">'
                f'<span style="{label_style}font-size:11px;margin-right:5px;">{day_label}</span>'
                f'<span style="color:{imp_color};font-size:10px;font-weight:700;text-transform:uppercase;'
                f'margin-right:5px;">{html_lib.escape(imp)}</span>'
                f'{evname}{suffix}</span>'
            )
            econ_txt.append(f'{day_label} [{imp.upper()}] {ev.get("event","")} {suf_txt}')
            _total_shown += 1

    # ── Bail if nothing to show ──────────────────────────────────────────────
    has_content = fut_rows or earn_parts or fed_parts or econ_parts
    if not has_content:
        return '', []

    # ── Assemble HTML ────────────────────────────────────────────────────────
    inner = ''
    if fut_rows:
        inner += (
            '<div style="display:inline-block;vertical-align:top;margin-right:24px;">'
            f'<p style="margin:0 0 5px 0;font-size:10px;font-weight:700;text-transform:uppercase;'
            f'color:#6b7280;letter-spacing:0.06em;">Futures</p>'
            f'<table style="border-collapse:collapse;">{fut_rows}</table>'
            '</div>'
        )

    right_col = ''
    if earn_parts:
        right_col += (
            f'<p style="margin:0 0 3px 0;font-size:10px;font-weight:700;text-transform:uppercase;'
            f'color:#6b7280;letter-spacing:0.06em;">Today\'s Earnings</p>'
            f'<p style="margin:0 0 8px 0;font-size:12px;line-height:1.6;">{"".join(earn_parts)}</p>'
        )
    if fed_parts:
        right_col += (
            f'<p style="margin:0 0 3px 0;font-size:10px;font-weight:700;text-transform:uppercase;'
            f'color:#6b7280;letter-spacing:0.06em;">Fed Speak</p>'
            f'<p style="margin:0 0 8px 0;font-size:12px;line-height:1.7;">{"".join(fed_parts)}</p>'
        )
    elif not fed_parts:
        right_col += (
            f'<p style="margin:0 0 8px 0;font-size:11px;color:#9ca3af;">No scheduled Fed speakers today.</p>'
        )
    if econ_parts:
        right_col += (
            f'<p style="margin:0 0 3px 0;font-size:10px;font-weight:700;text-transform:uppercase;'
            f'color:#6b7280;letter-spacing:0.06em;">Key Data This Week</p>'
            f'<p style="margin:0;font-size:12px;line-height:1.7;">{"".join(econ_parts)}</p>'
        )

    if right_col:
        inner += (
            f'<div style="display:inline-block;vertical-align:top;max-width:340px;">'
            f'{right_col}'
            f'</div>'
        )

    html_out = (
        '<div style="margin:0 0 16px 0;padding:12px 14px;background:#f0f4ff;'
        'border:1px solid #c7d7f5;border-radius:10px;">'
        f'<p style="margin:0 0 10px 0;font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:#1e3a8a;">Pre-Market Look</p>'
        f'{inner}'
        f'</div>'
    )

    txt_lines = ['PRE-MARKET LOOK', '']
    if fut_txt:
        txt_lines += ['Futures:'] + fut_txt + ['']
    if earn_txt:
        txt_lines += ["Today's Earnings:  " + '  |  '.join(earn_txt), '']
    if fed_txt:
        txt_lines += ['Fed Speak:'] + [f'  {t}' for t in fed_txt] + ['']
    elif not fed_txt:
        txt_lines += ['Fed Speak: No scheduled Fed speakers today.', '']
    if econ_txt:
        txt_lines += ['Key Data This Week:'] + [f'  {t}' for t in econ_txt] + ['']

    return html_out, txt_lines


def _build_scenarios_block(c: dict) -> tuple[str, list]:
    """Build the Today's Scenarios block: Too Hot / In Line / Too Cold.
    Returns (html_string, text_lines). Returns empty if scenarios data absent.
    """
    scenarios    = c.get('scenarios') or []
    levels_watch = c.get('levels_to_watch') or []
    event_name   = c.get('scenario_event', '')
    consensus    = c.get('scenario_consensus', '')
    if not scenarios or len(scenarios) < 3:
        return '', []

    _LABEL_COLORS = {0: '#dc2626', 1: '#2563eb', 2: '#16a34a'}   # Hot=red, In-Line=blue, Cold=green
    _LABEL_BG    = {0: '#fef2f2', 1: '#eff6ff', 2: '#f0fdf4'}
    _LABEL_BORDER = {0: '#fca5a5', 1: '#93c5fd', 2: '#86efac'}

    scenario_html = ''
    txt_lines: list[str] = []

    header = event_name
    if consensus:
        header += f' — Consensus: {consensus}'

    for i, sc in enumerate(scenarios[:3]):
        label      = html_lib.escape(str(sc.get('label', '')))
        thesis     = html_lib.escape(str(sc.get('thesis', '')))
        rates      = html_lib.escape(str(sc.get('rates', '')))
        equities   = html_lib.escape(str(sc.get('equities', '')))
        commodities = html_lib.escape(str(sc.get('commodities', '')))
        tickers    = [str(t).upper() for t in (sc.get('tickers') or [])]

        ticker_chips = ''
        for t in tickers[:5]:
            ticker_chips += (
                f'<span style="display:inline-block;margin:2px 3px 2px 0;'
                f'padding:2px 7px;background:#e5e7eb;border-radius:10px;'
                f'font-size:11px;font-weight:700;color:#374151;">{html_lib.escape(t)}</span>'
            )

        clr    = _LABEL_COLORS.get(i, '#6b7280')
        bg     = _LABEL_BG.get(i, '#f9fafb')
        border = _LABEL_BORDER.get(i, '#d1d5db')

        scenario_html += (
            f'<div style="margin-bottom:10px;padding:10px 12px;border:1px solid {border};'
            f'border-left:4px solid {clr};background:{bg};border-radius:6px;">'
            f'<p style="margin:0 0 4px 0;font-size:13px;font-weight:700;color:{clr};">{label}</p>'
            f'<p style="margin:0 0 6px 0;font-size:12px;color:#374151;line-height:1.5;">{thesis}</p>'
            f'<table style="border-collapse:collapse;width:100%;margin-bottom:6px;">'
            f'<tr><td style="padding:2px 8px 2px 0;font-size:11px;color:#6b7280;width:80px;">Rates</td>'
            f'<td style="padding:2px 0;font-size:11px;color:#111827;">{rates}</td></tr>'
            f'<tr><td style="padding:2px 8px 2px 0;font-size:11px;color:#6b7280;">Equities</td>'
            f'<td style="padding:2px 0;font-size:11px;color:#111827;">{equities}</td></tr>'
            f'<tr><td style="padding:2px 8px 2px 0;font-size:11px;color:#6b7280;">Commodities</td>'
            f'<td style="padding:2px 0;font-size:11px;color:#111827;">{commodities}</td></tr>'
            f'</table>'
            f'{ticker_chips}'
            f'</div>'
        )
        txt_lines.append(f'{sc.get("label","")}: {sc.get("thesis","")}')
        txt_lines.append(f'  Rates: {sc.get("rates","")}')
        txt_lines.append(f'  Equities: {sc.get("equities","")}')
        txt_lines.append(f'  ETFs: {", ".join(tickers)}')
        txt_lines.append('')

    # Levels to watch
    levels_html = ''
    if levels_watch:
        lvl_rows = ''
        for lv in levels_watch[:3]:
            asset = html_lib.escape(str(lv.get('asset', '')))
            level = lv.get('level', '')
            sig   = html_lib.escape(str(lv.get('significance', '')))
            try:
                level_fmt = f'{float(level):,.2f}'
            except Exception:
                level_fmt = str(level)
            lvl_rows += (
                f'<tr>'
                f'<td style="padding:4px 10px 4px 0;font-size:12px;font-weight:600;color:#111827;white-space:nowrap;">{asset}</td>'
                f'<td style="padding:4px 10px 4px 0;font-size:12px;color:#1d4ed8;font-weight:700;white-space:nowrap;">{html_lib.escape(level_fmt)}</td>'
                f'<td style="padding:4px 0;font-size:11px;color:#374151;">{sig}</td>'
                f'</tr>'
            )
            txt_lines.append(f'  {lv.get("asset","")} @ {level_fmt}: {lv.get("significance","")}')
        levels_html = (
            f'<p style="margin:10px 0 5px 0;font-size:10px;font-weight:700;text-transform:uppercase;'
            f'color:#6b7280;letter-spacing:0.06em;">Levels to Watch</p>'
            f'<table style="border-collapse:collapse;width:100%;">{lvl_rows}</table>'
        )

    if not scenario_html:
        return '', []

    event_header_html = ''
    if header:
        event_header_html = (
            f'<p style="margin:0 0 10px 0;font-size:12px;color:#374151;">'
            f'<b>Primary event:</b> {html_lib.escape(header)}</p>'
        )

    html_out = (
        '<div style="margin:16px 0;">'
        f'<p style="margin:0 0 8px 0;font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:#6b7280;border-bottom:1px solid #e5e7eb;padding-bottom:5px;">'
        f'Today&#39;s Scenarios</p>'
        f'{event_header_html}'
        f'{scenario_html}'
        f'{levels_html}'
        f'</div>'
    )

    all_txt = ['TODAY\'S SCENARIOS', '']
    if header:
        all_txt += [f'Event: {header}', '']
    all_txt += txt_lines
    if levels_watch:
        all_txt = all_txt[:all_txt.index('')*3 or -1] + ['Levels to Watch:'] + all_txt[-len(levels_watch)*2:]

    return html_out, all_txt


def _last_trading_day(d: date) -> date:
    us_holidays_set = holidays.US() if holidays is not None else set()
    walk = d - timedelta(days=1)
    while walk.weekday() >= 5 or walk in us_holidays_set:
        walk -= timedelta(days=1)
    return walk


def _next_n_trading_days(start: date, n: int) -> list[date]:
    """Return the next n trading days starting from (and including) start."""
    us_h = holidays.US() if holidays is not None else set()
    days: list[date] = []
    walk = start
    while len(days) < n:
        if walk.weekday() < 5 and walk not in us_h:
            days.append(walk)
        walk += timedelta(days=1)
    return days


def build_commentary_email_blocks(commentary):
    c = commentary or {}
    prev_day = _last_trading_day(date.today()).strftime('%A, %B %d')
    today_str = date.today().strftime('%A, %B %d')

    # ── Fear & Greed badge ──────────────────────────────────────────────────
    fg_html = ''
    fg_score  = c.get('fear_greed_score')
    fg_rating = c.get('fear_greed_rating', '')
    if fg_score is not None:
        try:
            score_f = float(fg_score)
            fg_color = (
                '#dc2626' if score_f < 25 else
                '#ea580c' if score_f < 45 else
                '#6b7280' if score_f < 55 else
                '#16a34a' if score_f < 75 else
                '#15803d'
            )
            fg_html = (
                f'<p style="margin:0 0 18px 0;">'
                f'<span style="background:#f3f4f6;border:1px solid #e5e7eb;border-radius:20px;'
                f'padding:5px 14px;font-size:12px;font-weight:700;color:{fg_color};">'
                f'Market Sentiment: {html_lib.escape(str(fg_rating).title())} &nbsp;{score_f:.0f}/100'
                f'</span></p>'
            )
        except Exception:
            pass

    # ── Market snapshot tables ──────────────────────────────────────────────
    _snap_raw = c.get('market_snapshot') or {}
    _snap_core_order = ['S&P 500', 'Nasdaq 100', '10-Yr Yield', 'Gold', 'WTI Crude', 'U.S. Dollar (DXY)']
    _snap_core = {k: _snap_raw[k] for k in _snap_core_order if _snap_raw.get(k)}
    snapshot_html, snap_lines = _asset_table_html('Market Snapshot', _snap_core)


    # ── Pre-Market Look block ────────────────────────────────────────────────
    premarket_html, premarket_txt = _build_premarket_block(c)

    # ── Scenarios block ──────────────────────────────────────────────────────
    scenarios_html, scenarios_txt = _build_scenarios_block(c)

    # ── What Happened Yesterday ─────────────────────────────────────────────
    recap_items  = c.get('session_recap', [])
    recap_html   = _bullet_list(recap_items, '#111827')
    recap_text   = [f'  • {_clean(str(i))}' for i in recap_items if _clean(str(i))]

    # ── What to Watch Today ─────────────────────────────────────────────────
    watch_items  = c.get('watch_today', [])
    watch_html   = _bullet_list(watch_items, '#111827')
    watch_text   = [f'  • {_clean(str(i))}' for i in watch_items if _clean(str(i))]

    # ── Today's Take (synthesis only — full narrative prose lives in the PDF) ─
    synthesis = _clean(c.get('cross_asset_synthesis', ''))

    synthesis_html = ''
    synthesis_text = []
    if synthesis:
        synthesis_html = (
            f'<div style="margin:14px 0 0 0;padding:12px 14px;'
            f'border-left:3px solid #2c4a6e;background:#f8f9fb;border-radius:2px;">'
            f'<p style="margin:0 0 4px 0;font-size:11px;font-weight:700;color:#2c4a6e;'
            f'text-transform:uppercase;letter-spacing:0.06em;">Today\'s Take</p>'
            f'<p style="margin:0;font-size:14px;line-height:1.65;color:#1a1f27;">'
            f'{html_lib.escape(synthesis)}</p>'
            f'</div>'
        )
        synthesis_text = ["TODAY'S TAKE", '', synthesis, '']

    # ── International Context ───────────────────────────────────────────────
    intl = _clean(c.get('international_section', ''))
    intl_html = ''
    if intl:
        intl_html = (
            f'<p style="margin:6px 0 0 0;font-size:13px;color:#374151;line-height:1.6;">'
            f'{html_lib.escape(intl)}</p>'
        )

    # ── Portfolio Spotlight ─────────────────────────────────────────────────
    winners = c.get('portfolio_spotlight_winners', [])
    watch   = c.get('portfolio_spotlight_watch', [])

    def _spot_rows(items, color):
        rows = ''
        lines = []
        for item in items:
            if not isinstance(item, dict):
                continue
            ticker = html_lib.escape(str(item.get('ticker', '')))
            metric = html_lib.escape(str(item.get('metric_label', '')))
            note   = html_lib.escape(_clean(item.get('commentary', '')))
            rows += (
                f'<tr>'
                f'<td style="padding:5px 10px 5px 0;font-weight:700;color:{color};font-size:13px;">{ticker}</td>'
                f'<td style="padding:5px 10px 5px 0;color:#374151;font-size:13px;">{metric}</td>'
                f'<td style="padding:5px 0;color:#374151;font-size:12px;">{note}</td>'
                f'</tr>'
            )
            lines.append(f'  {item.get("ticker","")}  {item.get("metric_label","")}  {_clean(item.get("commentary",""))}')
        return rows, lines

    spotlight_html = ''
    spotlight_text = []
    w_rows, w_lines = _spot_rows(winners, '#16a34a')
    v_rows, v_lines = _spot_rows(watch,   '#dc2626')

    if w_rows or v_rows:
        spotlight_html = '<div style="margin:10px 0;">'
        if w_rows:
            spotlight_html += (
                '<p style="margin:0 0 6px 0;font-weight:700;color:#1e2a44;font-size:12px;text-transform:uppercase;letter-spacing:0.05em;">Portfolio Leaders</p>'
                f'<table style="border-collapse:collapse;width:100%;">{w_rows}</table>'
            )
            spotlight_text += ['Portfolio Leaders:'] + w_lines
        if v_rows:
            spotlight_html += (
                '<p style="margin:14px 0 6px 0;font-weight:700;color:#1e2a44;font-size:12px;text-transform:uppercase;letter-spacing:0.05em;">Names to Watch</p>'
                f'<table style="border-collapse:collapse;width:100%;">{v_rows}</table>'
            )
            spotlight_text += ['Names to Watch:'] + v_lines
        spotlight_html += '</div>'

    # ── Assemble HTML ───────────────────────────────────────────────────────
    hp = [
        '<div style="margin:18px 0;padding:20px 22px;border:1px solid #dfe3eb;border-radius:14px;'
        'background:#f8fbff;font-family:\'Helvetica Neue\',Arial,sans-serif;line-height:1.6;">',
    ]

    if premarket_html:
        hp.append(premarket_html)

    if recap_html:
        hp.append(_section_header(f'What Happened {prev_day}'))
        hp.append(recap_html)

    if watch_html:
        hp.append(_section_header(f'What to Watch — {today_str}'))
        hp.append(watch_html)

    if synthesis_html:
        hp.append(synthesis_html)

    if scenarios_html:
        hp.append(scenarios_html)

    if snapshot_html:
        hp.append(snapshot_html)
        hp.append(
            f'<p style="margin:10px 0 0 0;font-size:12px;color:#6b7280;">'
            f'Full cross-asset data (Treasury curve, global equity, commodities, currencies &amp; crypto) '
            f'&#8212; <a href="{GITHUB_LINK}" style="color:#1d4ed8;font-weight:600;">'
            f'view today&#39;s report &rarr;</a></p>'
        )

    if spotlight_html:
        hp.append(_section_header('Portfolio Spotlight'))
        hp.append(spotlight_html)

    hp.append(
        '<p style="margin:16px 0 0 0;color:#9ca3af;font-size:11px;border-top:1px solid #e5e7eb;padding-top:10px;">'
        'AI-generated market intelligence for informational purposes only. Not investment advice. '
        'All forecasts are model outputs subject to error. Full data, methodology, and disclosures available on the report site.'
        '</p>'
    )
    hp.append('</div>')

    # ── Assemble plain text ─────────────────────────────────────────────────
    tp = ['EPM Markets Recap', '']
    if premarket_txt:
        tp += premarket_txt
    if recap_text:
        tp += [f'WHAT HAPPENED {prev_day.upper()}', ''] + recap_text + ['']
    if watch_text:
        tp += [f'WHAT TO WATCH — {today_str.upper()}', ''] + watch_text + ['']
    if synthesis_text:
        tp += synthesis_text
    if scenarios_txt:
        tp += scenarios_txt
    if snap_lines:
        tp += ['MARKET SNAPSHOT', ''] + snap_lines + ['']
    tp += [f'Full cross-asset data (Treasury curve, global equity, commodities, currencies & crypto): {GITHUB_LINK}', '']
    if spotlight_text:
        tp += ['PORTFOLIO SPOTLIGHT', ''] + spotlight_text + ['']
    tp += ['Full data and disclosures: see report site.', '']

    return ''.join(hp), '\n'.join(tp) + '\n\n'


# --- Build HTML email ---
def build_email():
    commentary = load_commentary_snapshot()
    commentary_html, commentary_text = build_commentary_email_blocks(commentary)

    html = f"""
    <html>
      <body>
        <img src=\"cid:epm_logo_png_cid\" alt=\"EPM Logo\" style=\"height:60px;\"/><br><br>

        <div style="font-family:'Helvetica Neue',Arial,sans-serif;max-width:620px;">
          <h2 style="margin:0 0 4px 0;color:#1e2a44;font-size:22px;font-weight:700;">EPM Markets Recap</h2>
          <p style="margin:0 0 18px 0;color:#6b7280;font-size:13px;">{date.today().strftime('%A, %B %d, %Y')} &nbsp;&middot;&nbsp; Morning Briefing &nbsp;&middot;&nbsp; 9:00 AM CST</p>

          <p style="margin:0 0 18px 0;color:#374151;line-height:1.6;">Good morning. Here is your daily market intelligence briefing — a recap of yesterday's session and key catalysts to watch today. Full cross-asset data, MAG7 model forecasts, and portfolio metrics are available on the report site.</p>

          {commentary_html}

          <p style="margin:20px 0 6px 0;">
            <a href="{GITHUB_LINK}" style="display:inline-block;padding:11px 24px;background:#1d4ed8;color:#fff;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;">Open Today's Report</a>
          </p>
        </div>
      </body>
    </html>
    """

    plain_text = (
        "The daily quant report is available on GitHub Pages.\n\n"
        + commentary_text
        + f"View today's report: {GITHUB_LINK}"
    )

    msg = MIMEMultipart("related")
    msg["From"] = FROM
    msg["To"] = TO
    msg["Subject"] = SUBJECT

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(plain_text, "plain"))
    alt.attach(MIMEText(html, "html"))
    msg.attach(alt)

    logo_mime = attach_image(LOGO_PATH, "epm_logo_png_cid")
    if logo_mime:
        msg.attach(logo_mime)

    if os.path.exists(PDF_REPORT):
        with open(PDF_REPORT, "rb") as f:
            pdf = MIMEApplication(f.read(), _subtype="pdf")
            pdf.add_header("Content-Disposition", "attachment", filename="Quant_Report.pdf")
            msg.attach(pdf)

    return msg

# --- Main send flow ---
if __name__ == "__main__":
    import argparse as _ap
    _parser = _ap.ArgumentParser()
    _parser.add_argument("--send-only", action="store_true",
                         help="Skip monitor.py re-run and send with existing data (requires fresh commentary)")
    _args, _ = _parser.parse_known_args()

    if already_sent_today():
        print(" Email already sent today. Skipping.")
        logging.info(" Email already sent today. Skipping.")
    elif not is_market_open():
        print(" Market closed today. No email sent.")
        logging.info(" Market closed today. No email sent.")
    else:
        try:
            if _args.send_only:
                logging.info(" --send-only: skipping monitor.py, using existing commentary.")
                print(" --send-only: skipping monitor.py re-run.")
            else:
                logging.info(" Running monitor.py to generate new report...")
                subprocess.run([PY, 'monitor.py'], cwd=str(ROOT), env={**os.environ, 'PDF_MODE': 'true'}, check=True)
                logging.info(" Report updated.")

            # Freshness gate — block send if narrative is stale or missing.
            _today = datetime.now(TZ).strftime('%Y-%m-%d')
            try:
                with open(COMMENTARY_JSON, 'r', encoding='utf-8') as _f:
                    _c = json.load(_f)
                _narrative_date = _c.get('narrative_source_date', '')
                _narrative_ts   = _c.get('narrative_generated_at', '')
                _narrative_fields = [
                    "equities_commentary", "fixed_income_commentary",
                    "commodities_commentary", "currencies_commentary",
                    "economics_commentary", "pre_market_bullets",
                ]
                _stale = (
                    _c.get('report_date') != _today
                    or _narrative_date != _today
                    or not _narrative_ts
                    or any(not _c.get(k) for k in _narrative_fields)
                )
                if _stale:
                    _msg = (
                        f"[BLOCK] Narrative stale or missing "
                        f"(report_date={_c.get('report_date')!r}, "
                        f"narrative_source_date={_narrative_date!r}, "
                        f"narrative_generated_at={_narrative_ts!r}). "
                        f"Email send blocked."
                    )
                    print(_msg)
                    logging.error(_msg)
                    sys.exit(1)
                _source = _c.get('narrative_source', '')
                if _source != 'llm':
                    _msg = (
                        f"[BLOCK] Narrative source is {_source!r} (expected 'llm') — "
                        f"deterministic fallback was used. Email send blocked. "
                        f"Investigate logs/generate_market_commentary.log."
                    )
                    print(_msg)
                    logging.error(_msg)
                    sys.exit(1)
            except Exception as _gate_err:
                _msg = f"[BLOCK] Could not verify commentary freshness ({_gate_err}). Email send blocked."
                print(_msg)
                logging.error(_msg)
                sys.exit(1)

            logging.info(" Preparing and sending email...")
            msg = build_email()
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
                server.login(FROM, os.getenv("GMAIL_APP_PASSWORD"))
                server.sendmail(FROM, TO, msg.as_string())

            logging.info(" Email sent successfully.")
            mark_sent_today()
            print(" Email sent successfully.")
        except Exception as e:
            logging.error(f" Error in workflow: {e}")
            print(f" Error in workflow: {e}")
