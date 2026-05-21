from json_repair import repair_json
import json, requests, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Fetch the actual bad output from the model
HOST = "http://100.101.63.65:11434"
MODEL = "qwen3.5:4b"

WRITING_RULES = """You are a senior market strategist writing for EPM Financial.
Rules: tight analytical prose; no filler; present tense; active voice.
Return ONLY valid JSON no markdown fences, no explanation, no trailing text."""

SYSTEM_PROMPT_RECAP = WRITING_RULES + """

Return JSON with EXACTLY these 3 keys:

session_recap: Array of exactly 3 strings.
watch_today: Array of exactly 3 strings.
international_section: A single string of 3-4 sentences.

JSON template:
{"session_recap":["...","...","..."],"watch_today":["...","...","..."],"international_section":"..."}"""

payload = {
    "date": "2026-05-17",
    "market_levels": {"S&P 500": {"level": 7408.5, "pct_change": -0.13},
                      "Nasdaq 100": {"level": 29097.0, "pct_change": -1.35}},
    "bonds": {"10-Yr": {"yield": 4.59, "change_bp": 2}},
    "recent_headlines": ["S&P 500 falls on inflation fears", "WTI jumps 3.42% to $103.25"],
    "upcoming_economic_events": [{"name": "Initial Jobless Claims", "date": "2026-05-21", "importance": "high"}],
    "earnings_calendar": [],
}

body = {
    "model": MODEL,
    "messages": [
        {"role": "system", "content": SYSTEM_PROMPT_RECAP},
        {"role": "user", "content": json.dumps(payload)},
    ],
    "stream": False,
    "format": "json",
    "think": False,
    "options": {"temperature": 0, "num_predict": 2048, "num_ctx": 8192},
}
resp = requests.post(f"{HOST}/api/chat", json=body, timeout=120)
raw = resp.json()["message"]["content"]
print("RAW:", raw[:800])
print()

repaired = repair_json(raw)
print("REPAIRED:", repaired[:800])
print()

try:
    parsed = json.loads(repaired)
    print("PARSED OK — keys:", list(parsed.keys()))
    for k, v in parsed.items():
        print(f"  {k}: {str(v)[:120]}")
except Exception as e:
    print("STILL FAILED:", e)
