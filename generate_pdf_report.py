"""
generate_pdf_report.py

Generates the EPM Financial Market Intelligence Report PDF  a premium 5-page
institutional-grade daily publication competing with and surpassing the Sevens Report.

Layout (5 pages):
  Page 1  Pre-Market Brief (bullets) + U.S. Market Snapshot + Global Markets table
  Page 2  Equities & Fixed Income commentary with embedded data tables
  Page 3  Commodities, Currencies & Economics commentary with data tables
  Page 4  MAG7 Quantitative Intelligence: index chart + forecast table + model rankings
  Page 5  Technical Perspectives + Portfolio Intelligence + Market Outlook
"""

from __future__ import annotations

import base64
import html as _html_module
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from weasyprint import HTML as WeasyprintHTML
    WEASYPRINT_OK = True
except ImportError:
    WEASYPRINT_OK = False
    print("[WARN] WeasyPrint not available - PDF generation skipped.")

try:
    import yfinance as yf
except ImportError:
    yf = None

from features import load_ycharts_features
from universe_config import get_mag7, get_portfolio_tickers, get_tracking_only_tickers

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT       = Path(__file__).resolve().parent
DATA_DIR   = ROOT / "data"
CHART_DIR  = ROOT / "charts"
OUT_DIR    = ROOT / "epm-quant-reports"
ARCH_DIR   = ROOT / "archive"
LOGO_DIR   = ROOT / "epm_logos_extracted"

OUT_DIR.mkdir(exist_ok=True)
ARCH_DIR.mkdir(exist_ok=True)

TODAY      = datetime.today()
TODAY_STR  = TODAY.strftime("%Y-%m-%d")
TODAY_LONG = TODAY.strftime("%B %d, %Y")
DAY_OF_WEEK = TODAY.strftime("%A")

def _prev_business_day(d):
    from datetime import timedelta
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d = d - timedelta(days=1)
    return d

PRIOR_CLOSE_LONG = _prev_business_day(TODAY).strftime("%B %d, %Y")

REPORT_PDF       = OUT_DIR / "report.pdf"
ARCHIVE_PDF      = ARCH_DIR / f"EPM Market Report \u2014 {TODAY_STR}.pdf"
COMMENTARY_PATH  = DATA_DIR / "latest_commentary.json"
ARBITRATED_PATH  = DATA_DIR / "market_data_arbitrated.json"

# ---------------------------------------------------------------------------
# Brand palette
# ---------------------------------------------------------------------------
NAVY       = "#0d1f2d"
NAVY2      = "#1a3048"
NAVY_LIGHT = "#2c4a6e"
GOLD       = "#b8965a"
GOLD_LIGHT = "#d4b07a"
SILVER     = "#8a9bb0"
WHITE      = "#ffffff"
OFF_WHITE  = "#f8f9fb"
PAPER      = "#fdfcfa"
BORDER     = "#dde3ea"
TEXT       = "#1a1f27"
TEXT2      = "#4a5568"
TEXT3      = "#6b7280"
POS        = "#155e3a"
NEG        = "#991b1b"
POS_BG     = "#d1fae5"
NEG_BG     = "#fee2e2"
WARN_BG    = "#fef3c7"
WARN       = "#92400e"

MAG7             = get_mag7()
PORTFOLIO_TICKERS = get_portfolio_tickers()
# MAG7 + publicly-traded MANGOS (e.g. SPCX): tracked/forecasted but never shown
# as portfolio funds. Subtract this from PORTFOLIO_TICKERS for fund displays.
TRACKING_ONLY    = get_tracking_only_tickers()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def esc(s: Any) -> str:
    return _html_module.escape(str(s) if s is not None else "")


def img_b64(path: str | Path, mime: str = "image/png") -> str:
    p = Path(path)
    if not p.exists():
        return ""
    with open(p, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    ext = p.suffix.lower().lstrip(".")
    mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "webp": "image/webp", "svg": "image/svg+xml"}
    mime = mime_map.get(ext, "image/png")
    return f"data:{mime};base64,{data}"


def make_white_transparent_logo() -> str:
    """Return a white-on-transparent PNG (base64) from the black logo using Pillow.
    Removes the white background and inverts the logo marks to white so it renders
    cleanly against any dark header without a colour-mismatch rectangle."""
    try:
        import io
        from PIL import Image
        candidates = [
            LOGO_DIR / "EPM Financial MAIN LOGO_Black-01.png",
            LOGO_DIR / "EPM Financial MAIN LOGO_Black-01- Small.png",
        ]
        logo_path = next((p for p in candidates if p.exists()), None)
        if not logo_path:
            return ""
        img = Image.open(logo_path).convert("RGBA")
        pixels = img.getdata()
        new_pixels = []
        for r, g, b, a in pixels:
            brightness = (r + g + b) / 3
            if brightness > 200:
                # Near-white background  fully transparent
                new_pixels.append((255, 255, 255, 0))
            else:
                # Dark logo marks  white, fully opaque
                new_pixels.append((255, 255, 255, 255))
        img.putdata(new_pixels)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        encoded = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/png;base64,{encoded}"
    except Exception:
        return ""


def best_logo() -> str:
    white_logo = make_white_transparent_logo()
    if white_logo:
        return white_logo
    # Fallback to bundled logos
    candidates = [
        LOGO_DIR / "EPM Financial logo blue.png",
        LOGO_DIR / "EPM Financial logo white.jpg",
        LOGO_DIR / "EPM Financial logo white.webp",
        ROOT / "epm_logo_email.png",
        ROOT / "epm_logo.png",
    ]
    for c in candidates:
        if c.exists():
            return img_b64(c)
    return ""


def load_commentary() -> dict:
    if not COMMENTARY_PATH.exists():
        return {}
    try:
        with open(COMMENTARY_PATH, "r", encoding="utf-8") as f:
            commentary = json.load(f)
    except Exception:
        return {}

    # Overlay arbitrated YCharts data where available (yield curve is more authoritative)
    try:
        if ARBITRATED_PATH.exists():
            with open(ARBITRATED_PATH, "r", encoding="utf-8") as f:
                arb = json.load(f)
            yc_yields = arb.get("yield_curve", {})
            if yc_yields:
                # Build bonds_table entries from arbitrated yield curve
                bonds_overlay: dict = {}
                # Include all yield curve entries from arbitrated data
                for report_key, entry in yc_yields.items():
                    if entry and entry.get("level") is not None:
                        level = entry["level"]
                        change = entry.get("change")
                        # 10s-2s spread is stored as decimal fraction (0.0056 = 0.56%)
                        # while other yields are already in pct form (4.44)  normalise
                        if report_key == "10s-2s Spread" and isinstance(level, float) and abs(level) < 0.5:
                            level = round(level * 100, 4)
                            if change is not None:
                                change = round(float(change) * 100, 4)
                        bonds_overlay[report_key] = {
                            "level":      level,
                            "change":     change,
                            "pct_change": entry.get("pct_change"),
                        }
                if bonds_overlay:
                    # Merge: arbitrated YCharts fills gaps only — live Treasury.gov
                    # data fetched by generate_market_commentary.py is more current
                    # (end-of-day) than the intraday YCharts scrape, so existing keys win.
                    existing = commentary.get("bonds_table", {})
                    for k, v in bonds_overlay.items():
                        if k not in existing:
                            existing[k] = v
                    commentary["bonds_table"] = existing

            # Attach full economics payload for use in report sections
            econ = arb.get("economics", {})
            if econ:
                commentary["economics_data"] = econ

            # Attach full yield curve for potential curve page
            if yc_yields:
                commentary["full_yield_curve"] = yc_yields
    except Exception as e:
        print(f"[WARN] Arbitrated data merge failed: {e}")

    return commentary


def is_commentary_fresh(commentary: dict) -> bool:
    if commentary.get("report_date") != TODAY_STR:
        return False
    if commentary.get("narrative_source_date") != TODAY_STR:
        return False
    if not commentary.get("narrative_generated_at"):
        return False
    for _k in ("equities_commentary", "fixed_income_commentary",
               "commodities_commentary", "currencies_commentary",
               "economics_commentary", "pre_market_bullets"):
        if not commentary.get(_k):
            return False
    return True


def fmt_pct(val: Any, decimals: int = 2) -> str:
    try:
        v = float(val)
        return f"{v:+.{decimals}f}%"
    except Exception:
        return "N/A"


def fmt_num(val: Any, decimals: int = 2, suffix: str = "") -> str:
    try:
        v = float(val)
        return f"{v:,.{decimals}f}{suffix}"
    except Exception:
        return "N/A"


def color_cls(val: Any, threshold: float = 0.0) -> str:
    try:
        return "pos" if float(val) >= threshold else "neg"
    except Exception:
        return ""


def pct_display(val: Any) -> str:
    try:
        v = float(val)
        if abs(v) < 1:
            v *= 100
        return f"{v:+.2f}%"
    except Exception:
        return "N/A"


def _signed(val: Any, decimals: int = 2, suffix: str = "", thousands: bool = False) -> str:
    """Format a number with an explicit +/- sign, normalizing values that round to
    zero so a near-zero or negative-zero input never renders as '-0.00' or '+-0.00'.
    Each field derives its own sign (callers must NOT share one sign across change/pct).
    Returns the em-dash placeholder on non-numeric input.
    """
    try:
        r = round(float(val) + 0.0, decimals)
        if r == 0:
            r = 0.0  # collapse negative zero
        sign = "+" if r >= 0 else "-"
        body = f"{abs(r):,.{decimals}f}" if thousands else f"{abs(r):.{decimals}f}"
        return f"{sign}{body}{suffix}"
    except (TypeError, ValueError):
        return "—"


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
CSS = f"""
@page {{
  size: Letter;
  margin: 0.6in 0.75in 0.55in 0.75in;
  background: {PAPER};
  @bottom-left {{
    content: "EPM Financial  \u00b7  Market Intelligence Report  \u00b7  {TODAY_LONG}";
    font-family: 'Georgia', serif;
    font-size: 6.8pt;
    color: {SILVER};
  }}
  @bottom-right {{
    content: "Page " counter(page) " of " counter(pages) "  \u00b7  For Institutional Use Only";
    font-family: 'Georgia', serif;
    font-size: 6.8pt;
    color: {SILVER};
  }}
}}

* {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 9.5pt;
  color: {TEXT};
  line-height: 1.58;
  background: {PAPER};
}}

/* ======================= HEADER ======================= */
.report-header {{
  background: {NAVY};
  margin: -0.65in -0.8in 0.3in -0.8in;
  padding: 0.18in 0.8in;
}}
.header-inner {{
  display: table;
  width: 100%;
  table-layout: fixed;
}}
.header-logo-cell {{
  display: table-cell;
  vertical-align: middle;
  width: 220px;
}}
.header-logo-cell img {{ height: 48px; width: auto; }}
.header-wordmark {{
  color: {WHITE};
  font-size: 15pt;
  font-weight: bold;
  letter-spacing: 0.02em;
}}
.header-meta {{
  display: table-cell;
  vertical-align: middle;
  text-align: right;
}}
.header-report-title {{
  font-size: 13pt;
  font-weight: bold;
  color: {WHITE};
  letter-spacing: 0.01em;
}}
.header-subtitle {{
  font-size: 7.5pt;
  color: {GOLD_LIGHT};
  margin-top: 2px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}}
.header-date {{
  font-size: 9pt;
  color: {SILVER};
  margin-top: 4px;
  font-style: italic;
}}

/* ======================= SECTION HEADERS ======================= */
.sec-header {{
  background: {NAVY};
  color: {WHITE};
  font-family: Georgia, serif;
  font-size: 7.5pt;
  font-weight: bold;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  padding: 5px 10px 4px 10px;
  margin: 18px 0 8px 0;
  page-break-after: avoid;
}}
.sec-header.first {{ margin-top: 0; }}
.sec-header.gold-bar {{
  background: {GOLD};
  color: {WHITE};
}}

.sub-label {{
  font-size: 8pt;
  font-weight: bold;
  color: {NAVY2};
  text-transform: uppercase;
  letter-spacing: 0.08em;
  border-bottom: 1.5px solid {NAVY2};
  padding-bottom: 2px;
  margin: 12px 0 6px 0;
}}
.sub-label.gold {{
  color: {GOLD};
  border-bottom-color: {GOLD};
}}

/* ======================= PRE-MARKET BULLETS ======================= */
.premarket-box {{
  border: 1.5px solid {NAVY};
  padding: 10px 14px;
  margin-bottom: 14px;
  background: {OFF_WHITE};
}}
.premarket-title {{
  font-size: 9.5pt;
  font-weight: bold;
  color: {NAVY};
  text-decoration: underline;
  margin-bottom: 8px;
  text-align: center;
  letter-spacing: 0.02em;
}}
.premarket-bullets {{
  list-style: disc;
  padding-left: 16px;
}}
.premarket-bullets li {{
  font-size: 9pt;
  line-height: 1.55;
  margin-bottom: 4px;
  color: {TEXT};
}}

/* ======================= MARKET TABLES ======================= */
.market-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 9pt;
  margin-bottom: 8px;
}}
.market-table th {{
  background: {NAVY};
  color: {WHITE};
  font-weight: bold;
  font-size: 7.5pt;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 5px 8px;
  text-align: left;
}}
.market-table th.r {{ text-align: right; }}
.market-table td {{
  padding: 4.5px 8px;
  border-bottom: 1px solid {BORDER};
  font-size: 9pt;
}}
.market-table tr:nth-child(even) td {{ background: {OFF_WHITE}; }}
.market-table td.r {{ text-align: right; }}
.market-table td.market-name {{ font-weight: bold; color: {NAVY}; }}
.market-table tfoot td {{
  font-size: 7pt;
  color: {TEXT3};
  font-style: italic;
  border-top: 1px solid {BORDER};
  padding-top: 3px;
  background: transparent !important;
}}

/* ======================= SIDE-BY-SIDE TABLES ======================= */
.tables-row {{
  display: table;
  width: 100%;
  table-layout: fixed;
  margin-bottom: 8px;
}}
.tables-row-left {{
  display: table-cell;
  vertical-align: top;
  width: 50%;
  padding-right: 14px;
}}
.tables-row-right {{
  display: table-cell;
  vertical-align: top;
  width: 50%;
  padding-left: 14px;
  border-left: 1px solid {BORDER};
}}

/* ======================= COLOR CODING ======================= */
.pos {{ color: {POS}; font-weight: bold; }}
.neg {{ color: {NEG}; font-weight: bold; }}
.flat {{ color: {TEXT2}; }}
.badge {{
  display: inline-block;
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 7pt;
  font-weight: bold;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}}
.badge-high   {{ background: {POS_BG};  color: {POS};  }}
.badge-medium {{ background: {WARN_BG}; color: {WARN}; }}
.badge-low    {{ background: {NEG_BG};  color: {NEG};  }}
.badge-na     {{ background: {OFF_WHITE}; color: {TEXT2}; }}
.badge-bull   {{ background: {POS_BG};  color: {POS};  }}
.badge-caut   {{ background: {WARN_BG}; color: {WARN}; }}
.badge-neut   {{ background: {OFF_WHITE}; color: {TEXT2}; }}
.badge-bear   {{ background: {NEG_BG};  color: {NEG};  }}

/* ======================= COMMENTARY ======================= */
.commentary-p {{
  margin: 0 0 9px 0;
  text-align: justify;
  font-size: 9.5pt;
  line-height: 1.62;
  color: {TEXT};
}}
.synthesis-p {{
  border-left: 3px solid {NAVY_LIGHT};
  padding-left: 10px;
  background: {OFF_WHITE};
  border-radius: 2px;
}}
.commentary-unavailable {{
  font-style: italic;
  color: {TEXT2};
  padding: 10px;
  background: {OFF_WHITE};
  border-left: 3px solid {SILVER};
  margin: 8px 0;
  font-size: 9pt;
}}

/* ======================= TWO-COLUMN ======================= */
.two-col {{
  display: table;
  width: 100%;
  table-layout: fixed;
  margin-bottom: 4px;
}}
.two-col-l {{
  display: table-cell;
  vertical-align: top;
  width: 50%;
  padding-right: 16px;
}}
.two-col-r {{
  display: table-cell;
  vertical-align: top;
  width: 50%;
  padding-left: 16px;
  border-left: 1px solid {BORDER};
}}
.two-col .commentary-p {{
  font-size: 9.2pt;
  line-height: 1.6;
}}

/* ======================= DATA TABLES ======================= */
.data-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 8.5pt;
  margin-bottom: 10px;
}}
.data-table th {{
  background: {NAVY};
  color: {WHITE};
  padding: 4px 7px;
  font-weight: bold;
  text-align: right;
  font-size: 7pt;
  letter-spacing: 0.04em;
  white-space: nowrap;
}}
.data-table th.l {{ text-align: left; }}
.data-table td {{
  padding: 3.5px 7px;
  border-bottom: 1px solid {BORDER};
  text-align: right;
  white-space: nowrap;
  font-size: 8.5pt;
}}
.data-table td.l {{ text-align: left; font-weight: bold; color: {NAVY}; }}
.data-table tr:nth-child(even) td {{ background: {OFF_WHITE}; }}

/* ======================= FORECAST TABLE ======================= */
.forecast-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 8.5pt;
  margin-bottom: 10px;
}}
.forecast-table th {{
  background: {NAVY};
  color: {WHITE};
  padding: 5px 8px;
  text-align: center;
  font-size: 7.5pt;
  letter-spacing: 0.04em;
}}
.forecast-table th.l {{ text-align: left; }}
.forecast-table td {{
  padding: 4.5px 8px;
  border-bottom: 1px solid {BORDER};
  text-align: center;
  font-size: 8.5pt;
}}
.forecast-table td.l {{ text-align: left; font-weight: bold; color: {NAVY}; font-size: 9.5pt; }}
.forecast-table tr:nth-child(even) td {{ background: {OFF_WHITE}; }}

/* ======================= TECHNICAL LEVELS ======================= */
.tech-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 8.5pt;
  margin-bottom: 10px;
}}
.tech-table th {{
  background: {NAVY2};
  color: {WHITE};
  padding: 4px 8px;
  font-size: 7pt;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  font-weight: bold;
}}
.tech-table th.l {{ text-align: left; }}
.tech-table th.r {{ text-align: right; }}
.tech-table td {{
  padding: 4px 8px;
  border-bottom: 1px solid {BORDER};
  font-size: 8.5pt;
}}
.tech-table td.l {{ text-align: left; font-weight: bold; color: {NAVY}; }}
.tech-table td.r {{ text-align: right; }}
.tech-table tr:nth-child(even) td {{ background: {OFF_WHITE}; }}
.tech-label {{
  font-size: 7.5pt;
  font-weight: bold;
  color: {TEXT3};
}}
.tech-val {{
  font-size: 8.5pt;
  font-weight: bold;
}}

/* ======================= MARKET OUTLOOK BOX ======================= */
.outlook-box {{
  border: 2px solid {NAVY};
  margin-bottom: 14px;
}}
.outlook-header {{
  background: {NAVY};
  color: {WHITE};
  font-size: 8pt;
  font-weight: bold;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  padding: 5px 10px;
  text-align: center;
}}
.outlook-body {{
  padding: 10px 12px;
  background: {OFF_WHITE};
}}
.outlook-label-row {{
  display: table;
  width: 100%;
  margin-bottom: 8px;
}}
.outlook-label-cell {{
  display: table-cell;
  vertical-align: middle;
  width: 120px;
  font-weight: bold;
  font-size: 9pt;
  color: {NAVY};
}}
.outlook-label-big {{
  font-size: 14pt;
  font-weight: bold;
  line-height: 1.2;
}}
.outlook-rationale {{
  display: table-cell;
  vertical-align: middle;
  font-size: 8.5pt;
  line-height: 1.5;
  font-style: italic;
  color: {TEXT2};
  padding-left: 12px;
  border-left: 2px solid {BORDER};
}}
.outlook-tactical {{
  font-size: 8pt;
  color: {TEXT};
  margin-top: 6px;
}}
.outlook-tactical strong {{ color: {NAVY}; }}

/* ======================= ASSET CLASS OUTLOOK TABLE ======================= */
.outlook-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 8.5pt;
  margin-top: 10px;
}}
.outlook-table th {{
  background: {NAVY};
  color: {WHITE};
  padding: 4px 8px;
  font-size: 7pt;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}}
.outlook-table th.l {{ text-align: left; }}
.outlook-table td {{
  padding: 5px 8px;
  border-bottom: 1px solid {BORDER};
  vertical-align: top;
  font-size: 8.5pt;
}}
.outlook-table td.l {{
  text-align: left;
  font-weight: bold;
  color: {NAVY};
  font-size: 9pt;
  white-space: nowrap;
}}
.outlook-table td.rationale {{
  font-style: italic;
  color: {TEXT2};
  font-size: 8pt;
  line-height: 1.45;
}}
.outlook-table tr:nth-child(even) td {{ background: {OFF_WHITE}; }}
/* Allow the outlook table to flow between rows but never mid-row.
   Avoiding the table itself was too aggressive — pushed it onto its own page. */
.outlook-table tr {{ page-break-inside: avoid; }}

/* ======================= TWO-COLUMN COMMENTARY+TABLE BLOCKS ======================= */
/* Prevent Commodities / Currencies + Fixed Income narrative-plus-table sections
   from splitting across page boundaries — keeps the table rows attached to the
   narrative they belong to. Falls back gracefully if the block is taller than a page. */
.two-col {{ page-break-inside: avoid; }}

/* ======================= TOPIC SPOTLIGHT (DEEP-DIVE) ======================= */
/* Keep the Topic Spotlight (title + paragraphs + funds table) on a single page
   when possible. Prevents the headline from being orphaned at the bottom of one
   page with the body bleeding to the next. */
.topic-spotlight-wrap {{ page-break-inside: avoid; }}

/* ======================= PORTFOLIO SPOTLIGHT ======================= */
.spotlight-section {{
  page-break-inside: avoid;
}}
.spotlight-col {{
  page-break-inside: avoid;
}}
.spotlight-item {{
  padding: 7px 0;
  border-bottom: 1px solid {BORDER};
  page-break-inside: avoid;
}}
.spotlight-item:last-child {{ border-bottom: none; }}
.spotlight-row {{
  display: table;
  width: 100%;
}}
.spotlight-ticker {{
  display: table-cell;
  font-weight: bold;
  color: {NAVY};
  font-size: 10pt;
  vertical-align: middle;
  width: 75px;
}}
.spotlight-metric {{
  display: table-cell;
  font-size: 8pt;
  color: {TEXT2};
  vertical-align: middle;
  font-style: italic;
}}
.spotlight-text {{
  margin-top: 2px;
  font-size: 8.5pt;
  color: {TEXT};
  line-height: 1.5;
}}

/* ======================= CHARTS ======================= */
.chart-img {{
  width: 100%;
  max-width: 100%;
  margin: 6px 0 3px 0;
  display: block;
}}
.chart-img.constrained {{
  max-height: 2.8in;
  width: auto;
  display: block;
  margin: 6px auto 3px auto;
}}
.chart-caption {{
  font-size: 7pt;
  color: {TEXT3};
  font-style: italic;
  text-align: center;
  margin-bottom: 10px;
}}

/* ======================= MISC ======================= */
.page-break {{ page-break-before: always; }}
.rule {{ border: none; border-top: 1px solid {BORDER}; margin: 12px 0; }}
.footnote {{
  font-size: 7pt;
  color: {TEXT2};
  font-style: italic;
  margin-top: 8px;
  border-top: 1px solid {BORDER};
  padding-top: 5px;
}}
.prices-note {{
  font-size: 7pt;
  color: {TEXT3};
  font-style: italic;
  text-align: right;
  margin-top: 2px;
}}
.disclaimer {{
  font-size: 6.5pt;
  color: {TEXT3};
  margin-top: 14px;
  border-top: 1px solid {BORDER};
  padding-top: 6px;
  line-height: 1.4;
  page-break-inside: avoid;
  page-break-before: avoid;
}}
"""


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
def build_header_html(logo_b64: str, subtitle: str = "Daily Market Intelligence Report") -> str:
    if logo_b64:
        logo_tag = f'<img src="{logo_b64}" alt="EPM Financial">'
    else:
        logo_tag = f'<span class="header-wordmark">EPM Financial</span>'
    return f"""
<div class="report-header">
  <div class="header-inner">
    <div class="header-logo-cell">{logo_tag}</div>
    <div class="header-meta">
      <div class="header-subtitle">{esc(subtitle)}</div>
      <div class="header-date">{DAY_OF_WEEK}, {TODAY_LONG}</div>
    </div>
  </div>
</div>"""


# ---------------------------------------------------------------------------
# Page 1 helpers
# ---------------------------------------------------------------------------
def build_premarket_bullets_html(commentary: dict) -> str:
    bullets = commentary.get("pre_market_bullets") or []
    if not bullets:
        return '<p class="commentary-unavailable">Pre-market brief unavailable.</p>'
    items = "".join(f"<li>{esc(b)}</li>" for b in bullets)
    return f"""
<div class="premarket-box">
  <div class="premarket-title">Pre-Market Look  {DAY_OF_WEEK}, {TODAY_LONG}</div>
  <ul class="premarket-bullets">{items}</ul>
</div>"""


def build_snapshot_table(snapshot: dict, title: str = "U.S. Markets", show_dollar: bool = False) -> str:
    if not snapshot:
        return '<p class="commentary-unavailable">Market data unavailable.</p>'

    rows = ""
    for name, data in snapshot.items():
        if not isinstance(data, dict):
            continue
        level  = data.get("level")
        change = data.get("change")
        pct    = data.get("pct_change")

        is_yield = "Yield" in name or "Spread" in name or name.endswith("bp")
        is_pct_native = "Spread" in name
        # Add $ only for USD price-denominated assets — not yields, not index values like DXY
        use_dollar = show_dollar and not is_yield and "DXY" not in name

        try:
            lv  = float(level)
            if is_yield:
                lvs = f"{lv:.3f}"
            elif use_dollar:
                lvs = f"${lv:,.2f}"
            else:
                lvs = f"{lv:,.2f}"
        except Exception:
            lvs = "N/A"

        if change is not None and pct is not None:
            try:
                _cv     = round(float(change) + 0.0, 3 if is_yield else 2)
                chg_str = _signed(change, 3) if is_yield else _signed(change, 2, thousands=True)
                pct_str = _signed(pct, 2, suffix="%")
                cls     = "flat" if _cv == 0 else ("pos" if _cv > 0 else "neg")
            except Exception:
                chg_str = pct_str = "\u2014"
                cls = "flat"
        else:
            chg_str = pct_str = "\u2014"
            cls = "flat"

        _sub: list[str] = []
        try:
            if is_yield:
                _bpw = data.get("bp_change_1w"); _bpy = data.get("bp_change_ytd")
                if _bpw is not None:
                    _sub.append(f"1W: {_signed(_bpw, 0, suffix='bp')}")
                if _bpy is not None:
                    _sub.append(f"YTD: {_signed(_bpy, 0, suffix='bp')}")
            else:
                _pw = data.get("pct_change_1w"); _py = data.get("pct_change_ytd")
                if _pw is not None:
                    _sub.append(f"1W: {_signed(_pw, 1, suffix='%')}")
                if _py is not None:
                    _sub.append(f"YTD: {_signed(_py, 1, suffix='%')}")
        except Exception:
            pass
        sub_html = (
            '<div style="font-size:9px;color:#94a3b8;margin-top:1px;">'
            + "&nbsp;|&nbsp;".join(_sub) + "</div>"
        ) if _sub else ""

        rows += f"""
    <tr>
      <td class="market-name">{esc(name)}</td>
      <td class="r">{esc(lvs)}</td>
      <td class="r {cls}">{esc(chg_str)}</td>
      <td class="r {cls}">{esc(pct_str)}{sub_html}</td>
    </tr>"""

    return f"""
<table class="market-table">
  <thead>
    <tr>
      <th>{esc(title)}</th>
      <th class="r">Level</th>
      <th class="r">Change</th>
      <th class="r">% Chg</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
  <tfoot><tr><td colspan="4">Prices taken at previous day market close.</td></tr></tfoot>
</table>"""


def build_page1_html(logo_b64: str, commentary: dict) -> str:
    snapshot = commentary.get("market_snapshot") or {}
    global_m = commentary.get("global_markets")  or {}

    us_table     = build_snapshot_table(snapshot,  "U.S. Markets  Key Assets", show_dollar=True)
    global_table = build_snapshot_table(global_m,  "Global Equity Markets")

    return f"""
{build_header_html(logo_b64)}
{build_premarket_bullets_html(commentary)}
<div class="sec-header first">Market Snapshot</div>
<div class="tables-row">
  <div class="tables-row-left">
    {us_table}
  </div>
  <div class="tables-row-right">
    {global_table}
  </div>
</div>
<p class="prices-note">All data sourced from market close, {PRIOR_CLOSE_LONG}. Forecasts are model-generated estimates, not recommendations.</p>
"""


# ---------------------------------------------------------------------------
# Page 2  Equities & Fixed Income
# ---------------------------------------------------------------------------
def build_bonds_table_html(bonds: dict) -> str:
    if not bonds:
        return ""
    rows = ""
    for name, data in bonds.items():
        if not isinstance(data, dict):
            continue
        level  = data.get("level")
        change = data.get("change")
        pct    = data.get("pct_change")

        is_spread = "Spread" in name
        try:
            lv  = float(level)
            # Guard against stale/corrupt data: yields < 0.5% are clearly wrong
            if not is_spread and "Yield" in name and lv < 0.5:
                lvs = "N/A"
                level = None  # suppress change/pct display too
            elif is_spread:
                # level may be already in bps (e.g. 53.0) or decimal pct (e.g. 0.53);
                # values > 1.0 are already bps, smaller values need *100 conversion
                lv_bps = lv if abs(lv) > 1.0 else lv * 100
                lvs = f"{lv_bps:.1f} bp"
            else:
                lvs = f"{lv:.3f}%"
        except Exception:
            lvs = "N/A"

        if change is not None and not is_spread and level is not None:
            try:
                sign    = "+" if float(change) >= 0 else ""
                chg_str = f"{sign}{float(change):.3f}%"
                pct_str = f"{sign}{float(pct):.2f}%" if pct is not None else "\u2014"
                cls     = "pos" if float(change) >= 0 else "neg"
            except Exception:
                chg_str = pct_str = "\u2014"
                cls = "flat"
        elif is_spread and "10s-2s" in name:
            # Derive the spread change in basis points from underlying yield moves
            try:
                y10_chg = float(bonds.get("10-Year Yield", {}).get("change") or 0)
                y2_chg  = float(bonds.get("2-Year Yield",  {}).get("change") or 0)
                spread_chg_bp = (y10_chg - y2_chg) * 100
                sign    = "+" if spread_chg_bp >= 0 else ""
                chg_str = f"{sign}{spread_chg_bp:.1f} bp"
                pct_str = "\u2014"
                cls     = "pos" if spread_chg_bp >= 0 else "neg"
            except Exception:
                chg_str = pct_str = "\u2014"
                cls = "flat"
        else:
            chg_str = pct_str = "\u2014"
            cls = "flat"

        # Suppress the 10s-2s spread row if underlying 2Y data is stale
        if is_spread and "10s-2s" in name:
            y2_entry = bonds.get("2-Year Yield", {})
            try:
                y2_lv = float(y2_entry.get("level", 0))
                if y2_lv < 1.0:
                    continue  # skip stale spread
            except Exception:
                pass

        _sub: list[str] = []
        try:
            _bpw = data.get("bp_change_1w"); _bpy = data.get("bp_change_ytd")
            if _bpw is not None:
                _sgn = "+" if float(_bpw) >= 0 else ""
                _sub.append(f"1W: {_sgn}{float(_bpw):.0f}bp")
            if _bpy is not None:
                _sgn = "+" if float(_bpy) >= 0 else ""
                _sub.append(f"YTD: {_sgn}{float(_bpy):.0f}bp")
        except Exception:
            pass
        sub_html = (
            '<div style="font-size:9px;color:#94a3b8;margin-top:1px;">'
            + "<br>".join(_sub) + "</div>"
        ) if _sub else ""

        rows += f"""
    <tr>
      <td class="l">{esc(name)}</td>
      <td class="r">{esc(lvs)}</td>
      <td class="r {cls}">{esc(chg_str)}</td>
      <td class="r {cls}">{esc(pct_str)}{sub_html}</td>
    </tr>"""

    return f"""
<table class="data-table">
  <thead>
    <tr>
      <th class="l">Instrument</th>
      <th class="r">Level</th>
      <th class="r">Chg</th>
      <th class="r">% Chg</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>"""


def build_page2_html(logo_b64: str, commentary: dict) -> str:
    def para(key: str) -> str:
        text = str(commentary.get(key, "") or "").strip()
        if not text:
            return '<p class="commentary-unavailable">Commentary unavailable.</p>'
        return f'<p class="commentary-p">{esc(text)}</p>'

    bonds_tbl = build_bonds_table_html(commentary.get("bonds_table") or {})

    return f"""
<div class="page-break"></div>
{build_header_html(logo_b64, "Equities & Fixed Income")}

<div class="sec-header first">Equities</div>
<div class="sub-label">Market Recap</div>
{para("equities_commentary")}

<div class="sec-header">Fixed Income &amp; Credit</div>
<div class="two-col">
  <div class="two-col-l">
    <div class="sub-label">Treasury &amp; Rate Analysis</div>
    {para("fixed_income_commentary")}
  </div>
  <div class="two-col-r">
    <div class="sub-label">U.S. Treasury Yields</div>
    {bonds_tbl}
  </div>
</div>
"""


# ---------------------------------------------------------------------------
# Page 3  Commodities, Currencies, Economics
# ---------------------------------------------------------------------------
def build_simple_data_table(data: dict, title: str, is_currency: bool = False) -> str:
    if not data:
        return ""
    rows = ""
    for name, d in data.items():
        if not isinstance(d, dict):
            continue
        level  = d.get("level")
        change = d.get("change")
        pct    = d.get("pct_change")

        try:
            lv  = float(level)
            # For Bitcoin use no-comma formatting to save width
            if "Bitcoin" in name or "BTC" in name:
                lvs = f"{lv:,.0f}"
            elif is_currency and lv < 10:
                lvs = f"{lv:.4f}"
            else:
                lvs = f"{lv:,.2f}"
        except Exception:
            lvs = "N/A"

        if change is not None and pct is not None:
            try:
                sign    = "+" if float(change) >= 0 else ""
                if is_currency and abs(float(change)) < 10:
                    chg_str = f"{sign}{float(change):.4f}"
                else:
                    chg_str = f"{sign}{float(change):.2f}"
                pct_str = f"{sign}{float(pct):.2f}%"
                cls     = "pos" if float(change) >= 0 else "neg"
            except Exception:
                chg_str = pct_str = "\u2014"
                cls = "flat"
        else:
            chg_str = pct_str = "\u2014"
            cls = "flat"

        _sub: list[str] = []
        try:
            _pw = d.get("pct_change_1w"); _py = d.get("pct_change_ytd")
            if _pw is not None:
                _sgn = "+" if float(_pw) >= 0 else ""
                _sub.append(f"1W: {_sgn}{float(_pw):.1f}%")
            if _py is not None:
                _sgn = "+" if float(_py) >= 0 else ""
                _sub.append(f"YTD: {_sgn}{float(_py):.1f}%")
        except Exception:
            pass
        sub_html = (
            '<div style="font-size:9px;color:#94a3b8;margin-top:1px;">'
            + "<br>".join(_sub) + "</div>"
        ) if _sub else ""

        rows += f"""
    <tr>
      <td class="l">{esc(name)}</td>
      <td class="r">{esc(lvs)}</td>
      <td class="r {cls}">{esc(chg_str)}</td>
      <td class="r {cls}">{esc(pct_str)}{sub_html}</td>
    </tr>"""

    return f"""
<table class="data-table">
  <thead>
    <tr>
      <th class="l">{esc(title)}</th>
      <th class="r">Level</th>
      <th class="r">Change</th>
      <th class="r">% Chg</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
  <tfoot><tr><td colspan="4">Prices taken at previous day market close.</td></tr></tfoot>
</table>"""


def build_synthesis_html(commentary: dict) -> str:
    text = str(commentary.get("cross_asset_synthesis") or "").strip()
    if not text:
        return ""
    return f"""
<div class="sec-header">Market Synthesis</div>
<p class="commentary-p synthesis-p">{esc(text)}</p>"""


def build_topic_spotlight_html(commentary: dict) -> str:
    sp = commentary.get("topic_spotlight")
    if not sp or not sp.get("title") or not sp.get("body"):
        return ""
    title = esc(str(sp.get("title", "")))
    # Split paragraphs on double-newline; fall back to runs of 2+ spaces so the deep-dive
    # never collapses into one blob if the model used spaces instead of newlines.
    import re as _re
    _body = str(sp.get("body", ""))
    _parts = _re.split(r"\n\n+", _body)
    if len(_parts) < 2:
        _parts = _re.split(r" {2,}", _body)
    paras = "".join(
        f'<p class="commentary-p">{esc(p.strip())}</p>'
        for p in _parts
        if p.strip()
    )
    funds = sp.get("funds") or []
    fund_rows = "".join(
        f'<tr><td class="fund-ticker"><strong>{esc(str(f.get("ticker",""))).upper()}</strong></td>'
        f'<td>{esc(str(f.get("name","")) )}</td>'
        f'<td>{esc(str(f.get("type","")) )}</td>'
        f'<td>{esc(str(f.get("exposure_note","")) )}</td></tr>'
        for f in funds if isinstance(f, dict)
    )
    fund_block = f"""
<div class="sec-header" style="margin-top:1rem;">Related Funds &amp; Vehicles</div>
<table class="data-tbl"><thead><tr>
  <th>Ticker</th><th>Name</th><th>Type</th><th>Exposure</th>
</tr></thead><tbody>{fund_rows}</tbody></table>""" if fund_rows else ""
    return f"""
<div class="topic-spotlight-wrap">
<div class="sec-header">Market Spotlight</div>
<div class="sec-subheader">{title}</div>
{paras}{fund_block}
</div>"""


def build_page3_html(logo_b64: str, commentary: dict) -> str:
    def para(key: str) -> str:
        text = str(commentary.get(key, "") or "").strip()
        if not text:
            return '<p class="commentary-unavailable">Commentary unavailable.</p>'
        return f'<p class="commentary-p">{esc(text)}</p>'

    cmdty_tbl = build_simple_data_table(
        commentary.get("commodities_table") or {}, "Commodities")
    fx_tbl    = build_simple_data_table(
        commentary.get("currencies_table") or {}, "Currencies & Digital Assets",
        is_currency=True)

    return f"""
<div class="page-break"></div>
{build_header_html(logo_b64, "Commodities, Currencies & Economics")}

<div class="sec-header first">Commodities</div>
<div class="two-col">
  <div class="two-col-l">
    {para("commodities_commentary")}
  </div>
  <div class="two-col-r">
    {cmdty_tbl}
  </div>
</div>

<div class="sec-header">Currencies &amp; Fixed Income</div>
<div class="two-col">
  <div class="two-col-l">
    {para("currencies_commentary")}
  </div>
  <div class="two-col-r">
    {fx_tbl}
  </div>
</div>

<div class="sec-header">Economics</div>
{para("economics_commentary")}

{build_synthesis_html(commentary)}
{build_topic_spotlight_html(commentary)}
"""


# ---------------------------------------------------------------------------
# Page 4  MAG7 Quantitative Intelligence
# ---------------------------------------------------------------------------
def build_mag7_table_html(df: pd.DataFrame) -> str:
    mag7_df = df[df["Ticker"].isin(MAG7)].copy()
    if mag7_df.empty:
        return '<p class="commentary-unavailable">MAG7 forecast data unavailable.</p>'

    mag7_df["Ticker"] = pd.Categorical(mag7_df["Ticker"], categories=MAG7, ordered=True)
    mag7_df = mag7_df.sort_values("Ticker")

    rows = ""
    for _, row in mag7_df.iterrows():
        ticker = row["Ticker"]

        # Consensus
        consensus = None
        for col in ("Consensus_Forecast", "Consensus Forecast (%)"):
            if col in row.index and pd.notna(row[col]):
                v = float(row[col])
                consensus = v * 100 if abs(v) < 1 else v
                break
        consensus_str = fmt_pct(consensus) if consensus is not None else "N/A"
        cons_cls = color_cls(consensus) if consensus is not None else ""

        # Confidence badge
        conf = str(row.get("Confidence_Label", "")).strip().lower()
        badge_cls = {"high": "badge-high", "medium": "badge-medium", "low": "badge-low"}.get(conf, "badge-na")
        conf_badge = f'<span class="badge {badge_cls}">{esc(conf or "N/A")}</span>'

        # Agreement
        agree = row.get("Agreement_Ratio")
        try:
            agree_pct = f"{float(agree)*100:.0f}%"
        except Exception:
            agree_pct = "N/A"

        # Per-model forecasts
        model_cols = [
            ("Linear Model Forecast (%)", "Linear"),
            ("ML Forecast (%)",           "ML"),
            ("ARIMAX Forecast (%)",        "ARIMAX"),
            ("DL Forecast (%)",            "DL"),
            ("FF Forecast (%)",            "FF"),
        ]
        model_cells = ""
        for col, label in model_cols:
            if col in row.index and pd.notna(row[col]):
                v   = float(row[col])
                v   = v * 100 if abs(v) < 1 else v
                cls = "pos" if v >= 0 else "neg"
                model_cells += f'<td class="{cls}">{v:+.1f}%</td>'
            else:
                model_cells += "<td>\u2014</td>"

        # 1M Return
        ret = row.get("1M Return")
        try:
            rv      = float(ret)
            ret_str = fmt_pct(rv * 100 if abs(rv) < 1 else rv)
            ret_cls = color_cls(rv)
        except Exception:
            ret_str, ret_cls = "N/A", ""

        # Best model
        best = str(row.get("Winning_Model", "") or "").strip()

        rows += f"""
    <tr>
      <td class="l">{esc(ticker)}</td>
      <td class="{cons_cls}">{esc(consensus_str)}</td>
      <td>{conf_badge}</td>
      <td>{esc(agree_pct)}</td>
      {model_cells}
      <td class="{ret_cls}">{esc(ret_str)}</td>
      <td>{esc(best)}</td>
    </tr>"""

    return f"""
<table class="forecast-table">
  <thead>
    <tr>
      <th class="l">Ticker</th>
      <th>Consensus<br>21-Day Fcast</th>
      <th>Model<br>Agreement</th>
      <th>Agreement<br>Ratio</th>
      <th>Linear</th>
      <th>ML</th>
      <th>ARIMAX</th>
      <th>Deep&nbsp;L</th>
      <th>Fama-F</th>
      <th>1M<br>Actual</th>
      <th>Top<br>Model</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
<p class="footnote">Consensus = equally-weighted ensemble of Linear, ML (Gradient Boost), ARIMAX, Deep Learning, and Fama-French factor models.
Model Agreement (High/Medium/Low) reflects how strongly the models concur — directional alignment, forecast dispersion, and recent RMSE. It measures model consensus, NOT realized forecast accuracy. Agreement Ratio = fraction of models directionally aligned.
Forecasts represent 21-trading-day forward return estimates. They are not investment recommendations.
Past model performance does not guarantee future accuracy.</p>"""


def build_mag7_commentary_html(commentary: dict) -> str:
    overview = str(commentary.get("portfolio_overview") or "").strip()
    bullets  = commentary.get("top_bullets") or []
    reflect  = str(commentary.get("market_reflection") or "").strip()

    if not overview and not bullets:
        return ""

    bullet_html = ""
    if bullets:
        items = "".join(f"<li>{esc(b)}</li>" for b in bullets)
        bullet_html = f'<ul class="premarket-bullets" style="margin:6px 0 6px 0;">{items}</ul>'

    return f"""
<div class="premarket-box">
  <div class="premarket-title">MAG7 Quantitative Signal Summary</div>
  {'<p class="commentary-p" style="margin-bottom:6px;">' + esc(overview) + '</p>' if overview else ''}
  {bullet_html}
  {'<p class="commentary-p" style="margin-top:4px;font-style:italic;">' + esc(reflect) + '</p>' if reflect else ''}
</div>"""


def build_index_performance_table(commentary: dict) -> str:
    """Build a compact table of key index levels and daily moves from snapshot data."""
    snapshot  = commentary.get("market_snapshot")  or {}
    global_m  = commentary.get("global_markets")   or {}
    combined  = {**snapshot, **global_m}

    display = [
        "S&P 500", "Nasdaq 100", "Dow Jones", "Russell 2000",
        "Euro Stoxx 50", "Nikkei 225", "FTSE 100",
    ]
    rows = ""
    for name in display:
        d = combined.get(name)
        if not d or not isinstance(d, dict):
            continue
        level  = d.get("level")
        change = d.get("change")
        pct    = d.get("pct_change")
        try:
            lv  = float(level)
            lvs = f"{lv:,.2f}"
        except Exception:
            lvs = "N/A"
        try:
            sign    = "+" if float(change) >= 0 else ""
            chg_str = f"{sign}{float(change):,.2f}"
            pct_str = f"{sign}{float(pct):.2f}%"
            cls     = "pos" if float(change) >= 0 else "neg"
        except Exception:
            chg_str = pct_str = "\u2014"
            cls = "flat"
        rows += f"""
    <tr>
      <td class="l">{esc(name)}</td>
      <td class="r">{esc(lvs)}</td>
      <td class="r {cls}">{esc(chg_str)}</td>
      <td class="r {cls}">{esc(pct_str)}</td>
    </tr>"""

    if not rows:
        return ""
    return f"""
<table class="data-table" style="font-size:8.5pt;">
  <thead>
    <tr>
      <th class="l">Index</th>
      <th class="r">Level</th>
      <th class="r">Change</th>
      <th class="r">% Chg</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
  <tfoot><tr><td colspan="4">Levels as of previous market close.</td></tr></tfoot>
</table>"""


def build_page4_html(logo_b64: str, commentary: dict, features_df: pd.DataFrame) -> str:
    index_chart = ""
    chart_path  = CHART_DIR / "index_comparison.png"
    if chart_path.exists():
        b64 = img_b64(chart_path)
        if b64:
            index_chart = f"""
<img class="chart-img constrained" src="{b64}" alt="Index Comparison">
<div class="chart-caption">Global Index Performance  3-Year Normalized Returns through {TODAY_LONG}</div>"""

    idx_table  = build_index_performance_table(commentary)
    mag7_summ  = build_mag7_commentary_html(commentary)

    return f"""
<div class="page-break"></div>
{build_header_html(logo_b64, "Global Market Performance")}

<div class="sec-header first">Global Index Performance  3-Year Returns</div>
{index_chart}

<div class="tables-row">
  <div class="tables-row-left">
    <div class="sub-label">Index Snapshot</div>
    {idx_table}
  </div>
  <div class="tables-row-right">
    <div class="sub-label">Quantitative Signal Summary</div>
    {mag7_summ if mag7_summ else '<p class="commentary-unavailable">Signal summary unavailable.</p>'}
  </div>
</div>
"""


# ---------------------------------------------------------------------------
# Page 5  Technical Perspectives + Portfolio + Market Outlook
# ---------------------------------------------------------------------------
def build_technical_perspectives_html(commentary: dict) -> str:
    tech = commentary.get("technical_levels") or {}
    if not tech:
        return '<p class="commentary-unavailable">Technical data unavailable.</p>'

    trend_label = {
        True:  ('<span class="pos">Above</span>', "Above"),
        False: ('<span class="neg">Below</span>', "Below"),
    }

    rows = ""
    display_order = ["S&P 500", "Nasdaq 100", "Gold", "WTI Crude", "10-Yr Yield", "VIX"]
    for name in display_order:
        if name not in tech:
            continue
        d = tech[name]
        current = d.get("current")
        ma20    = d.get("ma20")
        ma50    = d.get("ma50")
        ma200   = d.get("ma200")
        hi52    = d.get("52w_high")
        lo52    = d.get("52w_low")

        try:
            cur     = float(current)
            cur_str = f"{cur:,.2f}"
        except Exception:
            cur_str = "N/A"
            cur     = None

        def vs_ma(ma_val):
            if cur is None or ma_val is None:
                return "\u2014"
            try:
                mv  = float(ma_val)
                pct = (cur - mv) / mv * 100
                cls = "pos" if pct >= 0 else "neg"
                sign = "+" if pct >= 0 else ""
                return f'<span class="{cls}">{sign}{pct:.1f}%</span>'
            except Exception:
                return "\u2014"

        try:
            hi_str  = f"{float(hi52):,.2f}" if hi52 else "\u2014"
            lo_str  = f"{float(lo52):,.2f}" if lo52 else "\u2014"
            ma20_str  = f"{float(ma20):,.2f}"  if ma20  else "\u2014"
            ma50_str  = f"{float(ma50):,.2f}"  if ma50  else "\u2014"
            ma200_str = f"{float(ma200):,.2f}" if ma200 else "\u2014"
        except Exception:
            hi_str = lo_str = ma20_str = ma50_str = ma200_str = "\u2014"

        rows += f"""
    <tr>
      <td class="l">{esc(name)}</td>
      <td class="r"><strong>{cur_str}</strong></td>
      <td class="r">{ma20_str}</td>
      <td class="r">{vs_ma(ma20)}</td>
      <td class="r">{ma50_str}</td>
      <td class="r">{vs_ma(ma50)}</td>
      <td class="r">{ma200_str}</td>
      <td class="r">{vs_ma(ma200)}</td>
      <td class="r">{hi_str}</td>
      <td class="r">{lo_str}</td>
    </tr>"""

    return f"""
<table class="tech-table">
  <thead>
    <tr>
      <th class="l">Asset</th>
      <th class="r">Current</th>
      <th class="r">20d MA</th>
      <th class="r">vs 20d</th>
      <th class="r">50d MA</th>
      <th class="r">vs 50d</th>
      <th class="r">200d MA</th>
      <th class="r">vs 200d</th>
      <th class="r">52w High</th>
      <th class="r">52w Low</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>"""


def build_support_resistance_html(commentary: dict) -> str:
    """Pillar 3 — render the deterministic key support/resistance table.

    Reads the `support` and `resistance` arrays populated by fetch_technical_levels.
    All-numeric, no LLM — matches Sevens-style "key support X / resistance Y" rigor.
    Returns empty string when the upstream compute is absent so the page just shows
    the MA table by itself if anything went wrong.
    """
    tech = commentary.get("technical_levels") or {}
    if not tech:
        return ""
    display_order = ["S&P 500", "Nasdaq 100", "Gold", "WTI Crude", "10-Yr Yield", "VIX"]
    rows = ""
    have_any = False
    for name in display_order:
        d = tech.get(name) or {}
        sup = d.get("support") or []
        res = d.get("resistance") or []
        if not sup and not res:
            continue
        have_any = True

        def _fmt(entry: dict) -> str:
            try:
                lvl = float(entry.get("level"))
                tag = str(entry.get("tag", ""))
                # 10-Yr Yield is a percent (e.g. 4.50); everything else gets thousands sep.
                if name == "10-Yr Yield":
                    return f"{lvl:.2f}% <span style='color:#6b7280;font-size:9pt;'>({esc(tag)})</span>"
                return f"{lvl:,.2f} <span style='color:#6b7280;font-size:9pt;'>({esc(tag)})</span>"
            except Exception:
                return "—"

        sup_cells = " · ".join(_fmt(s) for s in sup) or "—"
        res_cells = " · ".join(_fmt(r) for r in res) or "—"
        rows += f"""
    <tr>
      <td class="l">{esc(name)}</td>
      <td class="r" style="color:#16a34a;">{sup_cells}</td>
      <td class="r" style="color:#dc2626;">{res_cells}</td>
    </tr>"""

    if not have_any:
        return ""
    return f"""
<div class="sec-header" style="margin-top:8px;">Key Support &amp; Resistance Levels</div>
<table class="tech-table">
  <thead>
    <tr>
      <th class="l">Asset</th>
      <th class="r">Key Support (closest below)</th>
      <th class="r">Key Resistance (closest above)</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
<p class="footnote" style="margin-top:2px;">Levels computed from 90-day price action: swing extrema clustered with MAs and 52-week levels, then filtered to the closest 1-2 above/below the current price. Numeric, not LLM-derived.</p>"""


def build_market_outlook_html(commentary: dict) -> str:
    label       = str(commentary.get("market_outlook_label") or "Neutral").strip()
    rationale   = str(commentary.get("market_outlook_rationale") or "").strip()
    outperf     = str(commentary.get("tactical_outperforming")  or "").strip()
    underperf   = str(commentary.get("tactical_underperforming") or "").strip()
    acos        = commentary.get("asset_class_outlooks") or {}

    label_badge = {
        "Bullish":  "badge-bull",
        "Cautious": "badge-caut",
        "Neutral":  "badge-neut",
        "Bearish":  "badge-bear",
    }.get(label, "badge-neut")

    ac_rows = ""
    for asset_name in ["Equities", "Fixed Income", "Commodities", "US Dollar"]:
        entry = acos.get(asset_name) or {}
        ac_label = str(entry.get("label") or "Neutral").strip()
        ac_rat   = str(entry.get("rationale") or "").strip()
        bl = {
            "Bullish": "badge-bull", "Negative": "badge-bear",
            "Cautious": "badge-caut", "Neutral/Negative": "badge-caut",
            "Neutral": "badge-neut", "Bearish": "badge-bear",
        }.get(ac_label, "badge-neut")
        ac_rows += f"""
    <tr>
      <td class="l">{esc(asset_name)}</td>
      <td><span class="badge {bl}">{esc(ac_label)}</span></td>
      <td class="rationale">{esc(ac_rat)}</td>
    </tr>"""

    tact_html = ""
    if outperf or underperf:
        tact_html = f"""
<div class="outlook-tactical">
  <strong>Outperforming:</strong> {esc(outperf or "N/A")} &nbsp;&nbsp;
  <strong>Underperforming:</strong> {esc(underperf or "N/A")}
</div>"""

    return f"""
<div class="outlook-box">
  <div class="outlook-header">Near-Term Market Outlook (4\u20136 Weeks)</div>
  <div class="outlook-body">
    <div class="outlook-label-row">
      <div class="outlook-label-cell">
        <div class="tech-label">Market Stance</div>
        <div class="outlook-label-big">
          <span class="badge {label_badge}" style="font-size:12pt;padding:3px 12px;">{esc(label)}</span>
        </div>
      </div>
      <div class="outlook-rationale">{esc(rationale) if rationale else "Rationale unavailable."}</div>
    </div>
    {tact_html}
  </div>
</div>

<div class="sec-header" style="margin-top:10px;">Long-Term Fundamental Outlook  Asset Classes</div>
<table class="outlook-table">
  <thead>
    <tr>
      <th class="l" style="width:100px;">Asset Class</th>
      <th style="width:120px;">Fundamental Outlook</th>
      <th class="l">Market Intelligence</th>
    </tr>
  </thead>
  <tbody>{ac_rows}</tbody>
</table>
<p class="footnote">Outlook updated {TODAY_LONG}. Near-term outlook covers 4-6 weeks. Long-term outlook reflects 3-6 month fundamental view.
This page is for informational use and does not constitute investment advice.</p>"""


def build_tactical_positioning_html(commentary: dict) -> str:
    """Pillar 2 — render the deterministic tactical-positioning banner.

    Reads `tactical_positioning` (computed in generate_market_commentary.main from the
    30-fund book + sector tilt + VIX). Returns empty string if absent, so the section
    silently degrades if the upstream compute failed.

    Note: In the PDF this renders as a COMPACT BANNER (stance + sector tilt + factor
    read + takeaway) intended to sit ABOVE the Portfolio Spotlight. The fund list is
    deliberately omitted because the Portfolio Spotlight underneath shows the same
    top/bottom funds with full LLM commentary — duplicating the fund tickers here
    would be redundant. The email retains the full block (with funds) because the
    email does not include the Portfolio Spotlight.
    """
    tp = commentary.get("tactical_positioning") or {}
    stance = str(tp.get("stance") or "").strip()
    if not stance:
        return ""
    detail   = str(tp.get("stance_detail") or "").strip()
    factor   = str(tp.get("factor_read")   or "").strip()
    take     = str(tp.get("takeaway")      or "").strip()

    # Colour the stance badge from its lead word.
    low = stance.lower()
    if low.startswith("risk-on") or low.startswith("pro-cyclical"):
        badge_cls = "badge-bull"
    elif low.startswith("risk-off") or low.startswith("defensive"):
        badge_cls = "badge-caut"
    else:
        badge_cls = "badge-neut"

    factor_html = (
        f'<span style="font-size:9.5pt;color:#374151;font-style:italic;"> · {esc(factor)}</span>'
        if factor else ""
    )
    take_html = (
        f'<div style="margin-top:3px;font-size:10pt;color:#111827;">'
        f'<strong>Takeaway:</strong> {esc(take)}</div>'
        if take else ""
    )
    detail_html = (
        f'<div style="font-size:9.5pt;color:#374151;margin-top:2px;">{esc(detail)}{factor_html}</div>'
        if detail else (
            f'<div style="font-size:9.5pt;color:#374151;font-style:italic;margin-top:2px;">{esc(factor)}</div>'
            if factor else ""
        )
    )

    # Compact banner — single-row layout with stance badge + sector tilt + factor read,
    # then takeaway underneath. Total height roughly 3 lines — designed to sit cleanly
    # above the Portfolio Spotlight header without spanning a page break.
    return f"""
<div class="tactical-banner" style="border-left:3px solid #1e3a8a;background:#f8fafc;padding:7px 12px;margin:8px 0 4px 0;page-break-inside:avoid;page-break-after:avoid;">
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
    <span style="font-size:8.5pt;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:#6b7280;">Quant Tactical Read</span>
    <span class="badge {badge_cls}" style="font-size:10pt;padding:2px 9px;">{esc(stance)}</span>
  </div>
  {detail_html}
  {take_html}
</div>"""


def build_spotlight_html(commentary: dict) -> str:
    winners = commentary.get("portfolio_spotlight_winners") or []
    watch   = commentary.get("portfolio_spotlight_watch")   or []

    def items_html(items: list) -> str:
        if not items:
            return '<p class="commentary-unavailable" style="font-size:8pt;">No data available.</p>'
        out = ""
        for item in items:
            ticker  = esc(item.get("ticker", ""))
            metric  = esc(item.get("metric_label", ""))
            comment = esc(item.get("commentary", ""))
            out += f"""
<div class="spotlight-item">
  <div class="spotlight-row">
    <div class="spotlight-ticker">{ticker}</div>
    <div class="spotlight-metric">{metric}</div>
  </div>
  <div class="spotlight-text">{comment}</div>
</div>"""
        return out

    return f"""
<div class="sec-header first spotlight-section">Portfolio Spotlight</div>
<div class="two-col spotlight-section">
  <div class="two-col-l spotlight-col">
    <div class="sub-label">Top Performers</div>
    {items_html(winners)}
  </div>
  <div class="two-col-r spotlight-col">
    <div class="sub-label">Names to Watch</div>
    {items_html(watch)}
  </div>
</div>"""



def _render_metrics_half(rows_df: pd.DataFrame, col_map: dict) -> str:
    _cell_pad = "padding:2px 4px;"
    headers = ""
    for display, _ in col_map.values():
        align = "l" if display == "Ticker" else ""
        headers += f'<th class="{align}" style="{_cell_pad}">{esc(display)}</th>'

    rows_html = ""
    for _, row in rows_df.iterrows():
        cells = ""
        for src_col, (display, formatter) in col_map.items():
            candidates = [src_col, src_col.replace("(3Y)", "").strip(),
                          "3Y Sharpe" if "Sharpe" in src_col else None]
            val = None
            for c in candidates:
                if c and c in row.index and pd.notna(row[c]):
                    val = row[c]
                    break
            if display == "Ticker":
                cells += f'<td class="l" style="{_cell_pad}">{esc(val or row["Ticker"])}</td>'
            elif val is None or (isinstance(val, float) and val != val):
                cells += f'<td style="{_cell_pad}">\u2014</td>'
            else:
                try:
                    formatted = formatter(val) if formatter else str(val)
                    cls = ""
                    if display in ("1M Ret", "Alpha"):
                        cls = color_cls(
                            float(val) * 100 if abs(float(val)) < 1 and display == "1M Ret"
                            else float(val)
                        )
                    elif display == "MaxDD":
                        cls = "neg"  # max drawdown is always a loss  always red
                    cells += f'<td class="{cls}" style="{_cell_pad}">{esc(formatted)}</td>'
                except Exception:
                    cells += f'<td style="{_cell_pad}">{esc(str(val))}</td>'
        rows_html += f"<tr>{cells}</tr>"

    return f"""
<table class="data-table" style="font-size:6.5pt;width:100%;table-layout:auto;">
  <thead><tr>{headers}</tr></thead>
  <tbody>{rows_html}</tbody>
</table>"""


def _fill_missing_maxdd(funds: pd.DataFrame) -> pd.DataFrame:
    """Backfill Max Drawdown 3Y from yfinance price history for any ticker that lacks it."""
    if yf is None:
        return funds
    missing_mask = funds["Max Drawdown 3Y"].isna()
    if not missing_mask.any():
        return funds
    from datetime import timedelta
    start = (TODAY - timedelta(days=365 * 3 + 30)).strftime("%Y-%m-%d")
    end   = TODAY.strftime("%Y-%m-%d")
    for idx in funds[missing_mask].index:
        ticker = funds.at[idx, "Ticker"]
        try:
            hist = yf.download(ticker, start=start, end=end,
                               auto_adjust=True, progress=False)
            if hist.empty:
                continue
            closes = hist["Close"].squeeze().dropna()
            if len(closes) < 20:
                continue
            roll_max   = closes.cummax()
            drawdowns  = (closes - roll_max) / roll_max
            mdd        = float(drawdowns.min())          # negative decimal e.g. -0.151
            # Store as positive decimal to match the existing column convention
            funds.at[idx, "Max Drawdown 3Y"] = abs(mdd)
        except Exception:
            pass
    return funds


def build_metrics_table_html(df: pd.DataFrame) -> str:
    fund_tickers = [t for t in PORTFOLIO_TICKERS if t not in set(TRACKING_ONLY)]
    funds = df[df["Ticker"].isin(fund_tickers)].copy()
    if funds.empty:
        return '<p class="commentary-unavailable">Portfolio metrics unavailable.</p>'

    funds["Ticker"] = pd.Categorical(funds["Ticker"], categories=fund_tickers, ordered=True)
    funds = funds.sort_values("Ticker").reset_index(drop=True)

    # Backfill any missing MaxDD from live yfinance price history
    if "Max Drawdown 3Y" not in funds.columns:
        funds["Max Drawdown 3Y"] = float("nan")
    funds = _fill_missing_maxdd(funds)

    # Reduced column set  drop StdDev and Up/Down to keep each half-table narrow
    col_map = {
        "Ticker":          ("Ticker",  None),
        "Price":           ("Price",   lambda v: fmt_num(v, 2)),
        "1M Return":       ("1M Ret",  lambda v: fmt_pct(float(v)*100 if abs(float(v))<1 else float(v))),
        "Sharpe (3Y)":     ("Sharpe",  lambda v: fmt_num(v, 2)),
        "Alpha (3Y)":      ("Alpha",   lambda v: fmt_num(v, 3)),
        "Beta (3Y)":       ("Beta",    lambda v: fmt_num(v, 2)),
        "Max Drawdown 3Y": ("MaxDD",   lambda v: fmt_pct(-abs(float(v)) * 100)),
    }

    # Split into two halves for side-by-side layout
    mid = (len(funds) + 1) // 2
    left_half  = funds.iloc[:mid]
    right_half = funds.iloc[mid:]

    left_html  = _render_metrics_half(left_half,  col_map)
    right_html = _render_metrics_half(right_half, col_map)

    return f"""
<div class="tables-row">
  <div class="tables-row-left" style="width:50%;padding-right:6px;">
    {left_html}
  </div>
  <div class="tables-row-right" style="width:50%;padding-left:6px;border-left:none;">
    {right_html}
  </div>
</div>"""


def build_page5_html(logo_b64: str, commentary: dict, features_df: pd.DataFrame) -> str:
    fresh = is_commentary_fresh(commentary)

    mag7_charts = ""
    for ticker in MAG7:
        path = CHART_DIR / f"mag7_forecast_{ticker}.png"
        if path.exists():
            b64 = img_b64(path)
            if b64:
                mag7_charts += f'<img class="chart-img" style="width:48%;display:inline-block;margin:2px 1%;" src="{b64}" alt="{ticker} forecast">'

    return f"""
<div class="page-break"></div>
{build_header_html(logo_b64, "Technical Perspectives & Portfolio Intelligence")}

<div class="sec-header first">Technical Perspectives  Key Asset Moving Averages</div>
{build_technical_perspectives_html(commentary)}

{build_support_resistance_html(commentary)}

{build_market_outlook_html(commentary) if fresh else ""}

<div class="rule"></div>

<div class="spotlight-wrap" style="page-break-inside:avoid;">
{build_tactical_positioning_html(commentary)}
{build_spotlight_html(commentary) if fresh else ""}
</div>

<div class="sec-header">Portfolio Fund Metrics</div>
{build_metrics_table_html(features_df)}

<p class="disclaimer">
EPM Financial  Market Intelligence Report | {TODAY_LONG} | For institutional and professional use only.
The information contained herein is derived from sources believed to be reliable but is not guaranteed as to accuracy or completeness.
Quantitative model forecasts are statistical estimates and do not constitute investment advice.
Past model performance does not guarantee future results. EPM Financial does not provide individual investment advice.
Investors should consult with their financial advisor before making any investment decisions.
</p>"""


# ---------------------------------------------------------------------------
# Full HTML assembly
# ---------------------------------------------------------------------------
def build_html(commentary: dict, features_df: pd.DataFrame) -> str:
    logo_b64 = best_logo()

    p1 = build_page1_html(logo_b64, commentary)
    p2 = build_page2_html(logo_b64, commentary)
    p3 = build_page3_html(logo_b64, commentary)
    p4 = build_page4_html(logo_b64, commentary, features_df)
    p5 = build_page5_html(logo_b64, commentary, features_df)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>{CSS}</style>
</head>
<body>
{p1}
{p2}
{p3}
{p4}
{p5}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def load_features_df() -> pd.DataFrame:
    try:
        df = pd.read_parquet(DATA_DIR / "features.parquet")
        df["Ticker"] = df["Ticker"].astype(str).str.upper().str.strip()
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
            df = df.sort_values("Date").groupby("Ticker", as_index=False).tail(1)
        else:
            df = df.drop_duplicates(subset=["Ticker"], keep="last")
        # DISPLAY-ONLY reconcile: the bare "1M Return" carries the stale YCharts scrape;
        # the fresh yfinance trailing-1M return is in "1M Return_enrich" (merge-suffix
        # collision keeps it from overwriting). Prefer the fresh value for every PDF table
        # (forecast table + fund-metrics table). This df is the PDF's own copy — model
        # pipelines read features.parquet directly, so their "1M Return" feature is untouched.
        for _fresh in ("1M Return_enrich", "Forward Return"):
            if _fresh in df.columns:
                df["1M Return"] = pd.to_numeric(df[_fresh], errors="coerce").where(
                    pd.to_numeric(df[_fresh], errors="coerce").notna(),
                    df.get("1M Return"),
                )
                break
        return df
    except Exception as e:
        print(f"[WARN]  Could not load features.parquet: {e}")
        return pd.DataFrame()


def load_ycharts_df() -> pd.DataFrame:
    try:
        df = load_ycharts_features()
        df["Ticker"] = df["Ticker"].str.replace("M:", "", regex=False).str.upper().str.strip()
        return df
    except Exception as e:
        print(f"[WARN]  Could not load YCharts features: {e}")
        return pd.DataFrame()


def main() -> None:
    if not WEASYPRINT_OK:
        return

    commentary = load_commentary()
    fresh      = is_commentary_fresh(commentary)

    if not fresh and REPORT_PDF.exists():
        print("[INFO]  Commentary not generated today  keeping previous PDF.")
        return

    # Defense-in-depth: re-run the deterministic guard pass before rendering so the PDF is
    # sanitized even if the commentary was produced by older code or a bypassed gen-time
    # guard (dollar/Fed-hike/direction/foreign-macro/safe-haven/geopolitics). In-memory only.
    try:
        import generate_market_commentary as _gmc
        _n = _gmc.sanitize_commentary(
            commentary,
            commentary.get("market_snapshot") or {},
            source_text=str(commentary.get("_source_headlines") or ""),
        )
        if _n:
            print(f"[SANITIZE] Applied {_n} deterministic correction(s) to commentary before PDF render.")
    except Exception as _e:
        print(f"[WARN] Render-time sanitize skipped: {_e}")

    print(" Loading feature data...")
    features_df = load_features_df()
    if features_df.empty:
        features_df = load_ycharts_df()

    print("  Building HTML document...")
    html = build_html(commentary, features_df)

    print(f" Rendering PDF  {REPORT_PDF.name}...")
    try:
        WeasyprintHTML(string=html, base_url=str(ROOT)).write_pdf(str(REPORT_PDF))
    except Exception as e:
        print(f" WeasyPrint render failed: {e}")
        return

    # Archive copy (dated name in archive folder only; epm-quant-reports keeps only report.pdf)
    shutil.copy(REPORT_PDF, ARCHIVE_PDF)

    print(f" PDF saved  {REPORT_PDF}")
    print(f" Archived  {ARCHIVE_PDF}")


if __name__ == "__main__":
    main()
