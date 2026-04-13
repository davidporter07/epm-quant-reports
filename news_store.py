from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import timedelta
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlsplit, urlunsplit

import pandas as pd

DATA_DIR = "data"
NEWS_STORE_PATH = os.path.join(DATA_DIR, "news_store.parquet")
NEWS_STORE_CSV_PATH = os.path.join(DATA_DIR, "news_store.csv")
HEADLINES_PATH = os.path.join(DATA_DIR, "news_headlines.csv")
NEWS_SELECTION_STATE_PATH = os.path.join(DATA_DIR, "news_selection_state.json")
RETENTION_HOURS_DEFAULT = 168  # 7 days

_STORE_COLUMNS = [
    "Ticker",
    "Headline",
    "Summary",
    "Source",
    "PublishedAt",
    "URL",
    "ImageURL",
    "Provider",
    "CanonicalURL",
    "HeadlineKey",
    "SimilarityKey",
    "StoryID",
    "FirstSeenAt",
    "LastSeenAt",
    "FetchCount",
    "LastSelectedAt",
    "LastSelectedSlot",
    "SelectionCount",
]

_SOURCE_QUALITY = {
    "reuters": 6,
    "associated press": 6,
    "ap": 6,
    "bloomberg": 6,
    "financial times": 5,
    "wall street journal": 5,
    "the wall street journal": 5,
    "wsj": 5,
    "cnbc": 5,
    "barron's": 5,
    "fortune": 4,
    "marketwatch": 4,
    "yahoo finance": 4,
    "the information": 4,
    "seeking alpha": 3,
    "benzinga": 2,
    "investing.com": 2,
    "macrumors": 1,
    "9to5mac": 1,
}

_DROP_QUERY_PREFIXES = (
    "utm_",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "cmpid",
    "guccounter",
    "guce_referrer",
    "guce_referrer_sig",
    "ref",
    "refsrc",
    "src",
)


def utc_now_naive() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC").tz_convert(None)


def ensure_news_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

def load_news_selection_state(path: str = NEWS_SELECTION_STATE_PATH) -> Dict[str, Dict]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def save_news_selection_state(state: Dict[str, Dict], path: str = NEWS_SELECTION_STATE_PATH) -> None:
    ensure_news_data_dir()
    safe_state = state if isinstance(state, dict) else {}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(safe_state, fh, indent=2, sort_keys=True)



def canonicalize_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        scheme = (parts.scheme or "https").lower()
        netloc = parts.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = re.sub(r"/+", "/", parts.path or "").rstrip("/")
        kept_qs = []
        if parts.query:
            for piece in parts.query.split("&"):
                if not piece:
                    continue
                key = piece.split("=", 1)[0].lower()
                if any(key.startswith(prefix) for prefix in _DROP_QUERY_PREFIXES):
                    continue
                kept_qs.append(piece)
        query = "&".join(kept_qs)
        return urlunsplit((scheme, netloc, path, query, ""))
    except Exception:
        return raw


def normalize_text_key(text: str) -> str:
    txt = str(text or "").lower()
    txt = txt.replace("&", " and ")
    txt = re.sub(r"[^a-z0-9]+", " ", txt)
    txt = re.sub(r"\b(update|live|analysis|opinion|video|photos|podcast)\b", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def similarity_key(text: str) -> str:
    key = normalize_text_key(text)
    if not key:
        return ""
    tokens = [tok for tok in key.split() if len(tok) > 2]
    return " ".join(tokens[:12])


def story_id_for_row(row: pd.Series) -> str:
    base = str(row.get("CanonicalURL") or row.get("URL") or row.get("HeadlineKey") or row.get("SimilarityKey") or "")
    ticker = str(row.get("Ticker", "")).upper()
    published = row.get("PublishedAt")
    published_txt = ""
    if pd.notna(published):
        try:
            published_txt = pd.Timestamp(published).strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            published_txt = str(published)
    return hashlib.sha1(f"{ticker}|{base}|{published_txt}".encode("utf-8", errors="ignore")).hexdigest()[:20]


def _story_quality(row: pd.Series) -> float:
    source = str(row.get("Source", "")).strip().lower()
    summary = str(row.get("Summary", "")).strip()
    image_url = str(row.get("ImageURL", "")).strip()
    provider = str(row.get("Provider", "")).strip()
    quality = float(_SOURCE_QUALITY.get(source, 2 if source else 0))
    quality += min(len(summary), 240) / 120.0
    if image_url:
        quality += 0.75
    if provider:
        quality += 0.25
    published = row.get("PublishedAt")
    if pd.notna(published):
        age_hours = max((utc_now_naive() - pd.Timestamp(published)).total_seconds() / 3600.0, 0.0)
        quality += max(0.0, 1.5 - min(age_hours, 12.0) / 8.0)
    return quality


def _headline_similarity(left: str, right: str) -> float:
    a = normalize_text_key(left)
    b = normalize_text_key(right)
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    set_a = set(a.split())
    set_b = set(b.split())
    if not set_a or not set_b:
        return ratio
    jaccard = len(set_a & set_b) / max(len(set_a | set_b), 1)
    return max(ratio, jaccard)


def _same_story(existing: pd.Series, incoming: pd.Series, similarity_threshold: float = 0.9) -> bool:
    if str(existing.get("Ticker", "")).upper() != str(incoming.get("Ticker", "")).upper():
        return False
    ex_url = str(existing.get("CanonicalURL", "")).strip()
    in_url = str(incoming.get("CanonicalURL", "")).strip()
    if ex_url and in_url and ex_url == in_url:
        return True
    ex_head = str(existing.get("HeadlineKey", "")).strip()
    in_head = str(incoming.get("HeadlineKey", "")).strip()
    if ex_head and in_head and ex_head == in_head:
        return True
    ex_pub = existing.get("PublishedAt")
    in_pub = incoming.get("PublishedAt")
    if pd.notna(ex_pub) and pd.notna(in_pub):
        if abs((pd.Timestamp(ex_pub) - pd.Timestamp(in_pub)).total_seconds()) > 18 * 3600:
            return False
    sim = _headline_similarity(existing.get("Headline", ""), incoming.get("Headline", ""))
    return sim >= similarity_threshold


def _ensure_store_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy() if df is not None else pd.DataFrame()
    for col in _STORE_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA
    out = out[_STORE_COLUMNS].copy()
    out["Ticker"] = out["Ticker"].fillna("").astype(str).str.strip().str.upper()
    for col in ["Headline", "Summary", "Source", "URL", "ImageURL", "Provider", "CanonicalURL", "HeadlineKey", "SimilarityKey", "StoryID", "LastSelectedSlot"]:
        out[col] = out[col].fillna("").astype(str).str.strip()
    for col in ["PublishedAt", "FirstSeenAt", "LastSeenAt", "LastSelectedAt"]:
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_convert(None)
    for col in ["FetchCount", "SelectionCount"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    return out


def normalize_headline_rows(rows: Iterable[Dict]) -> pd.DataFrame:
    df = pd.DataFrame(list(rows) if not isinstance(rows, pd.DataFrame) else rows)
    if df.empty:
        return _ensure_store_columns(pd.DataFrame(columns=_STORE_COLUMNS))

    cols = {c.lower(): c for c in df.columns}
    ticker_col = cols.get("ticker") or cols.get("symbol")
    title_col = cols.get("title") or cols.get("headline")
    summary_col = cols.get("summary") or cols.get("description") or cols.get("snippet") or cols.get("content")
    source_col = cols.get("source") or cols.get("publisher")
    published_col = cols.get("publishedat") or cols.get("published_at") or cols.get("published") or cols.get("date")
    url_col = cols.get("url") or cols.get("link")
    image_col = cols.get("imageurl") or cols.get("image_url") or cols.get("image") or cols.get("urltoimage")
    provider_col = cols.get("provider")

    out = pd.DataFrame(
        {
            "Ticker": df[ticker_col] if ticker_col in df.columns else "",
            "Headline": df[title_col] if title_col in df.columns else "",
            "Summary": df[summary_col] if summary_col in df.columns else "",
            "Source": df[source_col] if source_col in df.columns else "",
            "PublishedAt": df[published_col] if published_col in df.columns else pd.NaT,
            "URL": df[url_col] if url_col in df.columns else "",
            "ImageURL": df[image_col] if image_col in df.columns else "",
            "Provider": df[provider_col] if provider_col in df.columns else "",
        }
    )
    out = _ensure_store_columns(out)
    out["Headline"] = out["Headline"].fillna("").astype(str).str.strip()
    out = out[out["Headline"] != ""].copy()
    out["CanonicalURL"] = out["URL"].map(canonicalize_url)
    out["HeadlineKey"] = out["Headline"].map(normalize_text_key)
    out["SimilarityKey"] = out["Headline"].map(similarity_key)
    now = utc_now_naive()
    out["FirstSeenAt"] = out["FirstSeenAt"].fillna(now)
    out["LastSeenAt"] = out["LastSeenAt"].fillna(now)
    out["FetchCount"] = out["FetchCount"].replace(0, 1)
    out["StoryID"] = out.apply(story_id_for_row, axis=1)
    out = out.drop_duplicates(subset=["Ticker", "CanonicalURL"], keep="first")
    out = out.drop_duplicates(subset=["Ticker", "HeadlineKey"], keep="first")
    return _ensure_store_columns(out)


def prune_news_store(df: pd.DataFrame, retention_hours: int = RETENTION_HOURS_DEFAULT) -> pd.DataFrame:
    out = _ensure_store_columns(df)
    if out.empty:
        return out
    cutoff = utc_now_naive() - timedelta(hours=retention_hours)
    mask = out["PublishedAt"].isna() | (out["PublishedAt"] >= cutoff)
    out = out[mask].copy()
    out = out.sort_values(["PublishedAt", "LastSeenAt"], ascending=[False, False], na_position="last")
    return out.reset_index(drop=True)


def load_news_store(path: str = NEWS_STORE_PATH, retention_hours: int = RETENTION_HOURS_DEFAULT) -> pd.DataFrame:
    csv_fallback = NEWS_STORE_CSV_PATH if path == NEWS_STORE_PATH else f"{os.path.splitext(path)[0]}.csv"
    if os.path.exists(path):
        try:
            df = pd.read_parquet(path)
            return prune_news_store(df, retention_hours=retention_hours)
        except Exception:
            pass
    if os.path.exists(csv_fallback):
        try:
            df = pd.read_csv(csv_fallback)
            return prune_news_store(df, retention_hours=retention_hours)
        except Exception:
            pass
    return _ensure_store_columns(pd.DataFrame(columns=_STORE_COLUMNS))


def save_news_store(df: pd.DataFrame, path: str = NEWS_STORE_PATH) -> None:
    ensure_news_data_dir()
    out = _ensure_store_columns(df)
    csv_fallback = NEWS_STORE_CSV_PATH if path == NEWS_STORE_PATH else f"{os.path.splitext(path)[0]}.csv"
    try:
        out.to_parquet(path, index=False)
    except Exception:
        out.to_csv(csv_fallback, index=False)


def _merge_story_rows(existing: pd.Series, incoming: pd.Series) -> pd.Series:
    keep_existing = _story_quality(existing) >= _story_quality(incoming)
    winner = existing.copy() if keep_existing else incoming.copy()
    loser = incoming if keep_existing else existing

    for field in ["Summary", "ImageURL", "Provider", "Source", "URL", "CanonicalURL"]:
        if not str(winner.get(field, "")).strip() and str(loser.get(field, "")).strip():
            winner[field] = loser[field]

    ex_pub = existing.get("PublishedAt")
    in_pub = incoming.get("PublishedAt")
    if pd.isna(winner.get("PublishedAt")):
        winner["PublishedAt"] = in_pub if keep_existing else ex_pub
    elif pd.notna(ex_pub) and pd.notna(in_pub):
        winner["PublishedAt"] = max(pd.Timestamp(ex_pub), pd.Timestamp(in_pub))

    first_seen_candidates = [x for x in [existing.get("FirstSeenAt"), incoming.get("FirstSeenAt")] if pd.notna(x)]
    if first_seen_candidates:
        winner["FirstSeenAt"] = min(pd.Timestamp(x) for x in first_seen_candidates)
    winner["LastSeenAt"] = utc_now_naive()
    winner["FetchCount"] = int(pd.to_numeric(existing.get("FetchCount"), errors="coerce") or 0) + int(pd.to_numeric(incoming.get("FetchCount"), errors="coerce") or 0)

    for field in ["LastSelectedAt", "LastSelectedSlot"]:
        if pd.notna(existing.get("LastSelectedAt")) or str(existing.get("LastSelectedSlot", "")).strip():
            winner[field] = existing.get(field)
        elif pd.notna(incoming.get("LastSelectedAt")) or str(incoming.get("LastSelectedSlot", "")).strip():
            winner[field] = incoming.get(field)

    winner["SelectionCount"] = max(
        int(pd.to_numeric(existing.get("SelectionCount"), errors="coerce") or 0),
        int(pd.to_numeric(incoming.get("SelectionCount"), errors="coerce") or 0),
    )
    winner["HeadlineKey"] = normalize_text_key(winner.get("Headline", ""))
    winner["SimilarityKey"] = similarity_key(winner.get("Headline", ""))
    winner["CanonicalURL"] = canonicalize_url(winner.get("URL", ""))
    winner["StoryID"] = story_id_for_row(winner)
    return winner


def collapse_near_duplicates(df: pd.DataFrame, similarity_threshold: float = 0.9) -> pd.DataFrame:
    out = _ensure_store_columns(df)
    if out.empty:
        return out
    survivors: List[pd.Series] = []
    for _, row in out.sort_values(["PublishedAt", "LastSeenAt"], ascending=[False, False], na_position="last").iterrows():
        merged = False
        for idx, survivor in enumerate(survivors):
            if _same_story(survivor, row, similarity_threshold=similarity_threshold):
                survivors[idx] = _merge_story_rows(survivor, row)
                merged = True
                break
        if not merged:
            survivors.append(row.copy())
    collapsed = pd.DataFrame(survivors)
    return _ensure_store_columns(collapsed).sort_values(["PublishedAt", "LastSeenAt"], ascending=[False, False], na_position="last").reset_index(drop=True)


def merge_news_store(existing_df: pd.DataFrame, new_rows: Iterable[Dict], retention_hours: int = RETENTION_HOURS_DEFAULT) -> pd.DataFrame:
    store = prune_news_store(existing_df, retention_hours=retention_hours)
    incoming = prune_news_store(normalize_headline_rows(new_rows), retention_hours=retention_hours)
    if incoming.empty:
        return collapse_near_duplicates(store)
    if store.empty:
        return collapse_near_duplicates(incoming)

    rows = [row.copy() for _, row in store.iterrows()]
    for _, incoming_row in incoming.iterrows():
        match_idx: Optional[int] = None
        for idx, existing_row in enumerate(rows):
            if _same_story(existing_row, incoming_row):
                match_idx = idx
                break
        if match_idx is None:
            rows.append(incoming_row.copy())
        else:
            rows[match_idx] = _merge_story_rows(rows[match_idx], incoming_row)

    merged = pd.DataFrame(rows)
    merged = prune_news_store(merged, retention_hours=retention_hours)
    merged = collapse_near_duplicates(merged)
    return prune_news_store(merged, retention_hours=retention_hours)


def export_news_snapshot(df: pd.DataFrame, csv_path: str = HEADLINES_PATH) -> None:
    ensure_news_data_dir()
    out = prune_news_store(df)
    cols = ["Ticker", "Headline", "Summary", "Source", "PublishedAt", "URL", "ImageURL", "Provider", "CanonicalURL", "HeadlineKey", "SimilarityKey", "StoryID", "LastSelectedAt", "LastSelectedSlot", "SelectionCount"]
    out = out.reindex(columns=cols)
    out.to_csv(csv_path, index=False)


def mark_selected_stories(df: pd.DataFrame, selections: Dict[str, str]) -> pd.DataFrame:
    out = _ensure_store_columns(df)
    now = utc_now_naive()
    for slot_name, story_id in selections.items():
        if not story_id:
            continue
        mask = out["StoryID"].astype(str) == str(story_id)
        if mask.any():
            out.loc[mask, "LastSelectedAt"] = now
            out.loc[mask, "LastSelectedSlot"] = slot_name
            out.loc[mask, "SelectionCount"] = pd.to_numeric(out.loc[mask, "SelectionCount"], errors="coerce").fillna(0).astype(int) + 1
    return _ensure_store_columns(out)
