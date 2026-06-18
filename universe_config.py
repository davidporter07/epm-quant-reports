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


def get_mangos(path: str | Path = CONFIG_PATH) -> List[dict]:
    """Raw MANGOS member objects: {name, ticker, status}.

    MANGOS is the AI/space frontier group (SpaceX, Anthropic, OpenAI) tracked like
    mag7. Members carry a ``status`` ("active" once publicly traded, "pending_ipo"
    until they list) and a nullable ``ticker`` so pre-IPO names can be scaffolded
    without a symbol.
    """
    cfg = load_portfolio_config(path)
    members = cfg.get('mangos', [])
    return [dict(m) for m in members if isinstance(m, dict)]


def get_mangos_active_tickers(path: str | Path = CONFIG_PATH) -> List[str]:
    """Tickers for MANGOS members that are publicly traded (status == "active").

    Pending-IPO members (ticker is null) are excluded, so callers never see a
    ``None`` ticker. This is the only MANGOS accessor that should feed the scraper,
    panel build, or model inference.
    """
    active = []
    for m in get_mangos(path):
        ticker = m.get('ticker')
        if m.get('status') == 'active' and ticker:
            active.append(str(ticker))
    return _dedupe_preserve_order(active)


def get_tracking_only_tickers(path: str | Path = CONFIG_PATH) -> List[str]:
    """Tickers tracked for data collection / forecasting but NOT portfolio holdings.

    These are the MAG7 and any publicly-traded MANGOS members. They live in
    ``portfolio_ycharts_symbols`` (so they flow through the feature panel, charts,
    and forecasting) but must be EXCLUDED from every portfolio-fund display
    surface (website portfolio cards, report/email Portfolio Spotlight, PDF fund
    tables). The portfolio display is exactly the model funds from the EPM models
    workbook; tracking-only names are layered on top for the quant pages only.

    Use this — not ``get_mag7()`` alone — wherever the code subtracts a set from
    ``get_portfolio_tickers()`` to derive the displayed fund list. New MANGOS
    names auto-exclude on IPO once their ticker flips to "active".
    """
    return _dedupe_preserve_order(list(get_mag7(path)) + list(get_mangos_active_tickers(path)))


def get_ycharts_snapshot_symbols_extra(path: str | Path = CONFIG_PATH) -> List[str]:
    cfg = load_portfolio_config(path)
    return _dedupe_preserve_order(cfg.get('ycharts_snapshot_symbols_extra', []))


def get_ycharts_snapshot_symbols(path: str | Path = CONFIG_PATH) -> List[str]:
    return _dedupe_preserve_order(
        get_portfolio_ycharts_symbols(path)
        + get_ycharts_snapshot_symbols_extra(path)
        + get_mag7(path)
    )
