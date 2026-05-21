"""gather_qlora_data.py

Downloads and assembles external training data for QLoRA fine-tuning of Qwen3.5:4b.
Targets a blend of formal institutional prose (FOMC) and accessible financial commentary
(finance-alpaca instruction pairs).

Output layout:
  data/qlora_training/
    raw/fomc/statements/     -- FOMC press release text files
    raw/fomc/minutes/        -- FOMC minutes text files
    raw/hf/                  -- HuggingFace dataset snapshots
    assembled/train.jsonl    -- merged instruction-format JSONL for QLoRA

Each assembled record:
  {"instruction": "...", "input": "...", "output": "..."}

Usage:
  python gather_qlora_data.py              # full run (all sources)
  python gather_qlora_data.py --fomc       # FOMC only
  python gather_qlora_data.py --hf         # HuggingFace only
  python gather_qlora_data.py --assemble   # reformat only (raw data must exist)
  python gather_qlora_data.py --status     # show counts without downloading
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR    = Path("data") / "qlora_training"
FOMC_STMT   = BASE_DIR / "raw" / "fomc" / "statements"
FOMC_MIN    = BASE_DIR / "raw" / "fomc" / "minutes"
HF_DIR      = BASE_DIR / "raw" / "hf"
ASSEMBLE_DIR = BASE_DIR / "assembled"

HEADERS = {"User-Agent": "Mozilla/5.0 (EPM Financial research pipeline)"}

# ── FOMC announcement dates 2020-2026 ────────────────────────────────────────
# Last day of each meeting (when statement + decision are released).
FOMC_ANNOUNCEMENT_DATES = [
    # 2020
    "2020-01-29", "2020-03-03", "2020-03-15", "2020-04-29",
    "2020-06-10", "2020-07-29", "2020-09-16", "2020-11-05", "2020-12-16",
    # 2021
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
    "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    # 2022
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
    "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    # 2023
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    # 2026
    "2026-01-28", "2026-03-18", "2026-04-29",
]

FOMC_STMT_URL  = "https://www.federalreserve.gov/newsevents/pressreleases/monetary{date}a.htm"
FOMC_MIN_URL   = "https://www.federalreserve.gov/monetarypolicy/fomcminutes{date}.htm"

# ── HuggingFace sources ───────────────────────────────────────────────────────
HF_SOURCES = {
    "finance_alpaca": {
        "parquet_url": (
            "https://huggingface.co/datasets/gbharti/finance-alpaca/resolve/"
            "refs%2Fconvert%2Fparquet/default/train/0000.parquet"
        ),
        "description": "51k instruction-following financial Q&A pairs",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _make_dirs():
    for d in [FOMC_STMT, FOMC_MIN, HF_DIR, ASSEMBLE_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def _fetch(url: str, retries: int = 3, delay: float = 2.0) -> requests.Response | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
            print(f"  [HTTP {r.status_code}] {url}")
        except Exception as e:
            print(f"  [ERR] {e} — {url}")
        if attempt < retries - 1:
            time.sleep(delay)
    return None


def _extract_fed_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # Minutes use id="article" (clean); statements use a column div or #content.
    # Try clean selectors first, then fallback to broader ones.
    for selector in [
        {"id": "article"},
        {"class": "col-xs-12 col-sm-8 col-md-8"},
        {"class": "contentidentifier"},
    ]:
        node = soup.find("div", selector)
        if node:
            return node.get_text(separator="\n", strip=True)
    # Fallback: strip all tags
    return soup.get_text(separator="\n", strip=True)


# ─────────────────────────────────────────────────────────────────────────────
# FOMC scraper
# ─────────────────────────────────────────────────────────────────────────────

def scrape_fomc(statements: bool = True, minutes: bool = True):
    _make_dirs()
    stmt_ok = stmt_skip = stmt_miss = 0
    min_ok  = min_skip  = min_miss  = 0

    for ann_str in FOMC_ANNOUNCEMENT_DATES:
        compact = ann_str.replace("-", "")  # YYYYMMDD

        # ── Statement ────────────────────────────────────────────────────────
        if statements:
            dest = FOMC_STMT / f"{ann_str}.txt"
            if dest.exists():
                stmt_skip += 1
            else:
                url = FOMC_STMT_URL.format(date=compact)
                r = _fetch(url)
                if r:
                    text = _extract_fed_text(r.text)
                    dest.write_text(text, encoding="utf-8")
                    print(f"  [STMT] {ann_str} ({len(text):,} chars)")
                    stmt_ok += 1
                else:
                    print(f"  [STMT] {ann_str} — not found (older/unscheduled)")
                    stmt_miss += 1
                time.sleep(0.5)

        # ── Minutes ──────────────────────────────────────────────────────────
        if minutes:
            min_d   = date.fromisoformat(ann_str) + timedelta(days=21)
            min_str = min_d.isoformat()
            min_compact = min_str.replace("-", "")
            dest = FOMC_MIN / f"{ann_str}_minutes.txt"
            if dest.exists():
                min_skip += 1
            elif min_d > date.today():
                # Minutes not released yet
                pass
            else:
                url = FOMC_MIN_URL.format(date=compact)
                r = _fetch(url)
                if r:
                    text = _extract_fed_text(r.text)
                    dest.write_text(text, encoding="utf-8")
                    print(f"  [MIN]  {ann_str} minutes ({len(text):,} chars)")
                    min_ok += 1
                else:
                    print(f"  [MIN]  {ann_str} minutes — not found")
                    min_miss += 1
                time.sleep(0.5)

    print(f"\n[FOMC] Statements:  {stmt_ok} downloaded, {stmt_skip} cached, {stmt_miss} missing")
    print(f"[FOMC] Minutes:     {min_ok} downloaded, {min_skip} cached, {min_miss} missing")


# ─────────────────────────────────────────────────────────────────────────────
# HuggingFace downloader
# ─────────────────────────────────────────────────────────────────────────────

def download_hf():
    _make_dirs()
    import pandas as pd

    for name, cfg in HF_SOURCES.items():
        dest_parquet = HF_DIR / f"{name}.parquet"
        dest_jsonl   = HF_DIR / f"{name}.jsonl"

        if dest_jsonl.exists():
            count = sum(1 for _ in dest_jsonl.open(encoding="utf-8"))
            print(f"[HF] {name}: already cached ({count:,} rows)")
            continue

        print(f"[HF] Downloading {name} — {cfg['description']}")
        if not dest_parquet.exists():
            r = _fetch(cfg["parquet_url"])
            if not r:
                print(f"[HF] {name}: download failed")
                continue
            dest_parquet.write_bytes(r.content)
            print(f"[HF] {name}: {len(r.content)/1e6:.1f} MB downloaded")

        df = pd.read_parquet(dest_parquet)
        print(f"[HF] {name}: {len(df):,} rows, columns: {list(df.columns)}")
        with dest_jsonl.open("w", encoding="utf-8") as f:
            for _, row in df.iterrows():
                rec = {k: str(v) for k, v in row.items() if pd.notna(v)}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[HF] {name}: saved {len(df):,} rows to {dest_jsonl.name}")


# ─────────────────────────────────────────────────────────────────────────────
# Assembly: convert raw data → instruction-format JSONL
# ─────────────────────────────────────────────────────────────────────────────

def assemble():
    _make_dirs()
    out_path = ASSEMBLE_DIR / "train.jsonl"
    count = 0

    with out_path.open("w", encoding="utf-8") as out:

        # ── FOMC statements ──────────────────────────────────────────────────
        stmt_files = sorted(FOMC_STMT.glob("*.txt"))
        for f in stmt_files:
            text = f.read_text(encoding="utf-8").strip()
            if len(text) < 100:
                continue
            rec = {
                "instruction": (
                    "You are a senior institutional macro analyst. "
                    "Write a concise, authoritative Federal Reserve policy statement "
                    "in the style of official FOMC communications."
                ),
                "input": "",
                "output": text,
            }
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            count += 1
        print(f"[ASSEMBLE] FOMC statements: {len(stmt_files)} records")

        # ── FOMC minutes ─────────────────────────────────────────────────────
        min_files = sorted(FOMC_MIN.glob("*.txt"))
        for f in min_files:
            text = f.read_text(encoding="utf-8").strip()
            if len(text) < 200:
                continue
            # Chunk minutes into ~1500-char segments (LLM context window)
            chunks = [text[i:i+1500] for i in range(0, min(len(text), 15000), 1500)]
            for chunk in chunks:
                rec = {
                    "instruction": (
                        "You are a senior institutional macro analyst. "
                        "Summarize or continue this excerpt from Federal Reserve FOMC minutes "
                        "with precise, formal analytical prose."
                    ),
                    "input": chunk,
                    "output": "",
                }
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                count += 1
        print(f"[ASSEMBLE] FOMC minutes: {len(min_files)} files → {count} records so far")

        # ── finance-alpaca ───────────────────────────────────────────────────
        alpaca_path = HF_DIR / "finance_alpaca.jsonl"
        if alpaca_path.exists():
            alpaca_count = 0
            with alpaca_path.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    instruction = row.get("instruction", "").strip()
                    inp         = row.get("input", "").strip()
                    output      = row.get("output", "").strip()
                    if not instruction or not output:
                        continue
                    rec = {"instruction": instruction, "input": inp, "output": output}
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    count += 1
                    alpaca_count += 1
            print(f"[ASSEMBLE] finance-alpaca: {alpaca_count:,} records")
        else:
            print("[ASSEMBLE] finance-alpaca: not downloaded yet, skipping")

        # ── EPM commentary archive ───────────────────────────────────────────
        archive_dir = Path("data") / "commentary_archive"
        epm_count = 0
        if archive_dir.exists():
            for f in sorted(archive_dir.glob("*.json")):
                try:
                    c = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
                date_label = c.get("report_date", f.stem)
                # Build instruction records for each narrative section
                sections = {
                    "equities_commentary":     "Write an equities market narrative for the daily institutional report.",
                    "fixed_income_commentary": "Write a fixed income and rates narrative for the daily institutional report.",
                    "commodities_commentary":  "Write a commodities market narrative for the daily institutional report.",
                    "currencies_commentary":   "Write a currencies and FX narrative for the daily institutional report.",
                    "economics_commentary":    "Write an economics narrative for the daily institutional report.",
                    "session_recap":           "Write a concise end-of-day market recap for an institutional audience.",
                    "cross_asset_synthesis":   "Write a cross-asset synthesis section for an institutional market report.",
                }
                for key, instruction in sections.items():
                    text = c.get(key, "")
                    if isinstance(text, str) and len(text.strip()) > 80:
                        rec = {
                            "instruction": instruction,
                            "input": f"Report date: {date_label}",
                            "output": text.strip(),
                        }
                        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        count += 1
                        epm_count += 1
            print(f"[ASSEMBLE] EPM commentary archive: {epm_count} records from {len(list(archive_dir.glob('*.json')))} days")
        else:
            print("[ASSEMBLE] EPM commentary archive: no data yet")

    print(f"\n[ASSEMBLE] Total: {count:,} training records -> {out_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Status
# ─────────────────────────────────────────────────────────────────────────────

def status():
    print("\n[STATUS] QLoRA training data inventory")
    print(f"  FOMC statements : {len(list(FOMC_STMT.glob('*.txt'))) if FOMC_STMT.exists() else 0}")
    print(f"  FOMC minutes    : {len(list(FOMC_MIN.glob('*.txt'))) if FOMC_MIN.exists() else 0}")
    for name in HF_SOURCES:
        p = HF_DIR / f"{name}.jsonl"
        if p.exists():
            n = sum(1 for _ in p.open(encoding="utf-8"))
            print(f"  {name:20s}: {n:,} rows")
        else:
            print(f"  {name:20s}: not downloaded")
    train = ASSEMBLE_DIR / "train.jsonl"
    if train.exists():
        n = sum(1 for _ in train.open(encoding="utf-8"))
        print(f"  assembled/train.jsonl   : {n:,} records")
    archive = Path("data") / "commentary_archive"
    epm_days = len(list(archive.glob("*.json"))) if archive.exists() else 0
    print(f"  EPM commentary archive  : {epm_days} day(s)")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Gather QLoRA training data")
    ap.add_argument("--fomc",     action="store_true", help="FOMC only")
    ap.add_argument("--hf",       action="store_true", help="HuggingFace only")
    ap.add_argument("--assemble", action="store_true", help="Assemble only")
    ap.add_argument("--status",   action="store_true", help="Show counts, no download")
    args = ap.parse_args()

    run_all = not any([args.fomc, args.hf, args.assemble, args.status])

    if args.status:
        status()
        return

    if run_all or args.fomc:
        print("\n[1/3] Scraping FOMC statements and minutes...")
        scrape_fomc()

    if run_all or args.hf:
        print("\n[2/3] Downloading HuggingFace datasets...")
        download_hf()

    if run_all or args.assemble:
        print("\n[3/3] Assembling training JSONL...")
        assemble()

    status()


if __name__ == "__main__":
    main()
