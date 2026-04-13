import os
from typing import Optional, Union, Tuple
import pandas as pd

DEFAULT_FEATURES_PATH = os.path.join("data", "features.parquet")


def _ensure_data_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def load_features(path: str = DEFAULT_FEATURES_PATH) -> pd.DataFrame:
    """Load features.parquet safely. Returns empty DataFrame if missing."""
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_parquet(path)


def save_features(df: pd.DataFrame, path: str = DEFAULT_FEATURES_PATH) -> None:
    """Save features to parquet."""
    _ensure_data_dir(path)
    df.to_parquet(path, index=False)


def _upsert_df(base_df: pd.DataFrame, updates_df: pd.DataFrame, key: str = "Ticker") -> pd.DataFrame:
    """Pure DataFrame upsert: merge updates into base on key."""
    if base_df is None or len(base_df) == 0:
        if key in updates_df.columns:
            return updates_df.drop_duplicates(subset=[key], keep="last").reset_index(drop=True)
        return updates_df.copy()

    if updates_df is None or len(updates_df) == 0:
        return base_df

    if key not in base_df.columns:
        return pd.merge(base_df, updates_df, how="left")

    if key not in updates_df.columns:
        raise ValueError(f"updates_df must contain key column '{key}'")

    base = base_df.copy().drop_duplicates(subset=[key], keep="last")
    upd = updates_df.copy().drop_duplicates(subset=[key], keep="last")

    base = base.set_index(key, drop=False)
    upd = upd.set_index(key, drop=False)

    # add missing cols
    for col in upd.columns:
        if col == key:
            continue
        if col not in base.columns:
            base[col] = pd.NA

    # overwrite using non-null values
    for col in upd.columns:
        if col == key:
            continue
        s = upd[col]
        base.loc[s.index, col] = s.combine_first(base.loc[s.index, col])

    return base.reset_index(drop=True)


def upsert_features(*args, **kwargs) -> pd.DataFrame:
    """Flexible upsert helper used across the project.

    Supported call patterns:
      1) upsert_features(base_df, updates_df, key="Ticker") -> returns merged df
      2) upsert_features(path, updates_df, key="Ticker") -> loads base from path, merges, saves, returns merged
      3) upsert_features(path=..., base_df=..., updates_df=..., key=...) -> returns merged df and saves if path given
    """
    key = kwargs.get("key", "Ticker")
    path = kwargs.get("path", None)

    base_df = kwargs.get("base_df", None)
    updates_df = kwargs.get("updates_df", None)

    if len(args) == 2 and base_df is None and updates_df is None:
        a0, a1 = args
        if isinstance(a0, str) and isinstance(a1, pd.DataFrame):
            path = a0
            updates_df = a1
            base_df = load_features(path)
            merged = _upsert_df(base_df, updates_df, key=key)
            save_features(merged, path)
            return merged
        if isinstance(a0, pd.DataFrame) and isinstance(a1, pd.DataFrame):
            return _upsert_df(a0, a1, key=key)

    if updates_df is None and len(args) == 1 and isinstance(args[0], pd.DataFrame):
        # treat as updates into DEFAULT_FEATURES_PATH
        updates_df = args[0]
        base_df = load_features(DEFAULT_FEATURES_PATH)
        merged = _upsert_df(base_df, updates_df, key=key)
        save_features(merged, DEFAULT_FEATURES_PATH)
        return merged

    if base_df is None:
        base_df = load_features(path or DEFAULT_FEATURES_PATH)
    if updates_df is None:
        raise ValueError("upsert_features requires updates_df")

    merged = _upsert_df(base_df, updates_df, key=key)
    if path is not None:
        save_features(merged, path)
    return merged
