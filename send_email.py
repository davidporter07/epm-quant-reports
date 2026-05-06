import os
import sys
import smtplib
import json
import ssl
import subprocess
import logging
import html as html_lib
from datetime import date, datetime
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


def build_commentary_email_blocks(commentary):
    c = commentary or {}
    prev_day = (date.today() - __import__('datetime').timedelta(days=1)).strftime('%A, %B %d')
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

    # ── Market snapshot table ───────────────────────────────────────────────
    snapshot = c.get('market_snapshot', {})
    snap_rows_html = ''
    snap_lines = []
    label_order = ['S&P 500', 'Nasdaq 100', '10-Yr Yield', 'Gold', 'WTI Crude', 'U.S. Dollar (DXY)']
    for label in label_order:
        d = snapshot.get(label)
        if not d:
            continue
        level = d.get('level', '')
        pct   = d.get('pct_change', '')
        arrow = _arrow(pct)
        color = _pct_color(pct)
        sign  = '+' if isinstance(pct, (int, float)) and pct >= 0 else ''
        pct_str = f'{sign}{pct}%' if pct != '' else ''
        _is_yield = 'Yield' in label or 'Spread' in label
        _is_dxy   = 'DXY' in label
        try:
            _lv = float(level)
            if _is_yield:
                level_fmt = f"{_lv:.3f}"
            elif _is_dxy:
                level_fmt = f"{_lv:,.2f}"
            else:
                level_fmt = f"${_lv:,.2f}"
        except Exception:
            level_fmt = str(level)
        snap_rows_html += (
            f'<tr>'
            f'<td style="padding:5px 12px 5px 0;color:#374151;font-size:13px;">{html_lib.escape(label)}</td>'
            f'<td style="padding:5px 12px 5px 0;color:#111827;font-size:13px;font-weight:600;">{html_lib.escape(level_fmt)}</td>'
            f'<td style="padding:5px 0;color:{color};font-size:13px;font-weight:600;">{arrow} {html_lib.escape(pct_str)}</td>'
            f'</tr>'
        )
        snap_lines.append(f'{label}: {level_fmt}  {arrow} {pct_str}')

    snapshot_html = ''
    if snap_rows_html:
        snapshot_html = (
            '<div style="margin:14px 0;">'
            '<p style="margin:0 0 8px 0;font-weight:700;color:#1e2a44;font-size:12px;text-transform:uppercase;letter-spacing:0.05em;">Market Snapshot</p>'
            f'<table style="border-collapse:collapse;">{snap_rows_html}</table>'
            '</div>'
        )

    # ── What Happened Yesterday ─────────────────────────────────────────────
    recap_items  = c.get('session_recap', [])
    recap_html   = _bullet_list(recap_items, '#111827')
    recap_text   = [f'  • {_clean(str(i))}' for i in recap_items if _clean(str(i))]

    # ── What to Watch Today ─────────────────────────────────────────────────
    watch_items  = c.get('watch_today', [])
    watch_html   = _bullet_list(watch_items, '#111827')
    watch_text   = [f'  • {_clean(str(i))}' for i in watch_items if _clean(str(i))]

    # ── Market Analysis (deep-dive sections) ────────────────────────────────
    _pm_raw = c.get('pre_market_summary') or c.get('pre_market_bullets', '')
    pre_market   = _clean(' '.join(_pm_raw) if isinstance(_pm_raw, list) else _pm_raw)
    equities     = _clean(c.get('equities_commentary', ''))
    fixed_income = _clean(c.get('fixed_income_commentary', ''))
    commodities  = _clean(c.get('commodities_commentary', ''))
    currencies   = _clean(c.get('currencies_commentary', ''))
    economics    = _clean(c.get('economics_commentary', ''))
    synthesis    = _clean(c.get('cross_asset_synthesis', ''))

    analysis_html = ''
    analysis_text = []
    for label, text in [
        ('Overview', pre_market),
        ('Equities', equities),
        ('Fixed Income', fixed_income),
        ('Commodities', commodities),
        ('Currencies', currencies),
        ('Economics', economics),
    ]:
        if not text:
            continue
        analysis_html += (
            f'<p style="margin:10px 0 0 0;font-size:13px;line-height:1.6;">'
            f'<span style="font-weight:700;color:#1e2a44;">{label}:</span> '
            f'{html_lib.escape(text)}</p>'
        )
        analysis_text.append(f'{label}: {text}')

    synthesis_html = ''
    if synthesis:
        synthesis_html = (
            f'<div style="margin:14px 0 0 0;padding:10px 14px;'
            f'border-left:3px solid #2c4a6e;background:#f8f9fb;border-radius:2px;">'
            f'<p style="margin:0 0 4px 0;font-size:11px;font-weight:700;color:#2c4a6e;'
            f'text-transform:uppercase;letter-spacing:0.06em;">Market Take</p>'
            f'<p style="margin:0;font-size:13px;line-height:1.65;color:#1a1f27;">'
            f'{html_lib.escape(synthesis)}</p>'
            f'</div>'
        )
        analysis_text.append(f'Market Take: {synthesis}')

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

    if recap_html:
        hp.append(_section_header(f'What Happened {prev_day}'))
        hp.append(recap_html)

    if watch_html:
        hp.append(_section_header(f'What to Watch — {today_str}'))
        hp.append(watch_html)

    if analysis_html:
        hp.append(_section_header('Market Analysis'))
        hp.append(analysis_html)

    if synthesis_html:
        hp.append(synthesis_html)

    if snapshot_html:
        hp.append(snapshot_html)

    if intl_html:
        hp.append(_section_header('Global Context'))
        hp.append(intl_html)

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
    if recap_text:
        tp += [f'WHAT HAPPENED {prev_day.upper()}', ''] + recap_text + ['']
    if watch_text:
        tp += [f'WHAT TO WATCH — {today_str.upper()}', ''] + watch_text + ['']
    if analysis_text:
        tp += ['MARKET ANALYSIS', ''] + analysis_text + ['']
    if snap_lines:
        tp += ['MARKET SNAPSHOT', ''] + snap_lines + ['']
    if intl:
        tp += ['GLOBAL CONTEXT', '', intl, '']
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
    if already_sent_today():
        print(" Email already sent today. Skipping.")
        logging.info(" Email already sent today. Skipping.")
    elif not is_market_open():
        print(" Market closed today. No email sent.")
        logging.info(" Market closed today. No email sent.")
    else:
        try:
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
