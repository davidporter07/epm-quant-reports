"""Quick diagnostic: send SYSTEM_PROMPT_RECAP and SYSTEM_PROMPT_SCENARIOS to qwen3.5:4b
and print the raw response to identify the JSON parse failure."""
import json, sys, requests
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = "http://100.101.63.65:11434"
MODEL = "qwen3.5:4b"

# Load real payload from latest_commentary.json
data = json.loads(Path("data/latest_commentary.json").read_text(encoding="utf-8"))
snap = data.get("market_snapshot", {})
bonds = data.get("bonds_table", {})
gm = dict(list(data.get("global_markets", {}).items())[:5])
econ_cal = json.loads(Path("data/economic_calendar.json").read_text(encoding="utf-8"))
econ = econ_cal.get("events", [])[:5]
headlines = [
    "S&P 500 falls 0.75% as gold slumps to one-week low on inflation worries",
    "Gold prices fall on fears of sustained high rates; weekly decline likely",
    "WTI crude slides 0.75% to $99.84 on softer Asian demand signals",
    "10-year Treasury yield rises 2bp to 4.47% after stronger-than-expected jobless claims",
    "Empire State Manufacturing survey due; consensus sees modest contraction",
    "DXY rises 0.66% to 99.28 as dollar demand picks up on rate differentials",
]

WRITING_RULES = """You are a senior market strategist writing for EPM Financial's daily Market Intelligence Report.
Rules: tight analytical prose; no filler; present tense; active voice.
NEVER use: "geopolitical tensions", "geopolitical risks", "global uncertainties", "amid uncertainty", "amid concerns".
Return ONLY valid JSON  no markdown fences, no explanation."""

SYSTEM_PROMPT_RECAP = WRITING_RULES + """

Return JSON with EXACTLY these 3 keys:

session_recap: Array of exactly 3 strings summarising the PREVIOUS trading session:
  [0] "S&P 500 [closed higher/lower] at {level}, [pct]%; [single specific catalyst from news]."
  [1] Fixed income/rates recap: 10-yr yield level and direction with one specific driver.
  [2] Top non-equity mover: the most notable commodity OR currency with exact level and driver.

watch_today: Array of exactly 3 strings — actionable items for TODAY's session:
  [0] Economic data: cite the most important event from upcoming_economic_events or "No major data today."
  [1] Earnings/corporate: cite from earnings_calendar or "No major earnings today."
  [2] Technical level or market structure: one specific price level or spread to monitor.

international_section: 3-4 sentences covering non-US market impact on US outlook.

JSON template:
{"session_recap":["...","...","..."],"watch_today":["...","...","..."],"international_section":"..."}"""

recap_payload = {
    "date": "2026-05-17",
    "market_levels": snap,
    "bonds": bonds,
    "global_markets_top5": gm,
    "upcoming_economic_events": econ,
    "recent_headlines": headlines,
    "earnings_calendar": [],
    "recent_earnings_actuals": [],
}

def call(system, payload, label):
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, default=str)},
        ],
        "stream": False,
        "format": "json",
        "think": False,
        "options": {"temperature": 0, "num_predict": 2048, "num_ctx": 8192},
    }
    resp = requests.post(f"{HOST}/api/chat", json=body, timeout=300)
    raw = resp.json()["message"]["content"]
    print(f"\n{'='*80}")
    print(f"  {label}  —  raw length: {len(raw)} chars")
    print(f"{'='*80}")
    print(raw[:2000])
    if len(raw) > 2000:
        print(f"\n... [truncated, total {len(raw)} chars] ...")
        print(raw[-200:])
    print()
    try:
        parsed = json.loads(raw)
        print(f"  [PARSED OK] keys: {list(parsed.keys())}")
    except Exception as e:
        # Find the bad character
        print(f"  [PARSE ERROR] {e}")
        pos = int(str(e).split("char ")[-1].rstrip(")")) if "char" in str(e) else -1
        if pos > 0:
            print(f"  Context around char {pos}: ...{repr(raw[max(0,pos-40):pos+40])}...")

call(SYSTEM_PROMPT_RECAP, recap_payload, "RECAP + WATCH_TODAY")
