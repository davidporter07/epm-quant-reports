from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / 'config' / 'portfolio_funds.json'


def _dedupe_preserve_order(values: Iterable[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for raw in values:
        value = str(raw).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def load_portfolio_config(path: str | Path = CONFIG_PATH) -> dict:
    cfg_path = Path(path)
    if not cfg_path.is_absolute():
        cfg_path = (BASE_DIR / cfg_path).resolve()
    with cfg_path.open('r', encoding='utf-8') as f:
        return json.load(f)


def strip_ycharts_prefix(symbol: str) -> str:
    return str(symbol).replace('M:', '').strip().upper()


def get_portfolio_ycharts_symbols(path: str | Path = CONFIG_PATH) -> List[str]:
    cfg = load_portfolio_config(path)
    return _dedupe_preserve_order(cfg.get('portfolio_ycharts_symbols', []))


def get_portfolio_tickers(path: str | Path = CONFIG_PATH) -> List[str]:
    return _dedupe_preserve_order(strip_ycharts_prefix(s) for s in get_portfolio_ycharts_symbols(path))


def get_mag7(path: str | Path = CONFIG_PATH) -> List[str]:
    cfg = load_portfolio_config(path)
    return _dedupe_preserve_order(cfg.get('mag7', []))


def get_index_comparison_tickers(path: str | Path = CONFIG_PATH) -> List[str]:
    cfg = load_portfolio_config(path)
    return _dedupe_preserve_order(cfg.get('index_comparison', []))


def get_ycharts_snapshot_symbols_extra(path: str | Path = CONFIG_PATH) -> List[str]:
    cfg = load_portfolio_config(path)
    return _dedupe_preserve_order(cfg.get('ycharts_snapshot_symbols_extra', []))


def get_ycharts_snapshot_symbols(path: str | Path = CONFIG_PATH) -> List[str]:
    return _dedupe_preserve_order(
        get_portfolio_ycharts_symbols(path)
        + get_ycharts_snapshot_symbols_extra(path)
        + get_mag7(path)
    )
