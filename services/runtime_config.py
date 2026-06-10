"""Single source of truth for internal service endpoints + Ollama model names.

PR C (config centralization): modules previously carried divergent hardcoded
defaults for the same logical endpoint (four different Ollama defaults across
app.py / commentary / council / research), which caused laptop-vs-server
differences in production. All internal endpoints resolve here.

Policy:
  - REQUIRED (raises ConfigError when unset): values whose correct setting
    differs between laptop and server — LOCAL_OLLAMA_URL. A wrong silent
    default degrades the pipeline invisibly (seen 2026-06-01).
  - Allowed defaults: server-local sidecars (Kronos :8100, SearxNG :8080,
    both degrade gracefully when down) and the public domain.

Env var names are UNCHANGED from the pre-centralization code, so existing
.env files on both machines remain valid as-is.

Import-safe: no network calls, no subprocess. Loads .env on import
(override=False, same pattern as email_service) because laptop pipeline
processes (run_daily.py, generate_market_commentary.py) do not otherwise
load it — a required LOCAL_OLLAMA_URL would falsely fail there without this.
"""
from __future__ import annotations

import os
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_BASE_DIR / ".env", override=False)
except Exception:
    pass


class ConfigError(Exception):
    """A required runtime configuration value is missing."""


def _env(name: str, default: str | None = None) -> str | None:
    val = os.getenv(name, "").strip()
    return val or default


# --------------------------------------------------------------------------
# Service endpoints
# --------------------------------------------------------------------------

def ollama_url() -> str:
    """Base URL of the Ollama server. REQUIRED — no default.

    The correct value differs by machine, so a silent default is a trap:
      server: http://127.0.0.1:11434   (Ollama runs locally)
      laptop: http://100.101.63.65:11434   (server's Ollama over Tailscale)
    """
    val = _env("LOCAL_OLLAMA_URL")
    if not val:
        raise ConfigError(
            "LOCAL_OLLAMA_URL is not set. Add it to .env — "
            "server: http://127.0.0.1:11434, "
            "laptop: http://100.101.63.65:11434"
        )
    return val.rstrip("/")


def kronos_url() -> str:
    """Kronos OHLCV forecast sidecar (server-local, port 8100)."""
    return _env("KRONOS_URL", "http://127.0.0.1:8100").rstrip("/")


def searxng_url() -> str:
    """SearxNG JSON API (server-local container; research no-ops when down)."""
    return _env("SEARXNG_URL", "http://127.0.0.1:8080").rstrip("/")


def epm_server_url() -> str:
    """Public origin of the EPM web app (link building, recipient fetch)."""
    return _env("EPM_SERVER_URL", "https://epm-market-intelligence.com").rstrip("/")


def internal_recipients_url() -> str:
    """Endpoint the laptop pipeline polls for the confirmed-subscriber list."""
    return _env(
        "INTERNAL_RECIPIENTS_URL",
        f"{epm_server_url()}/api/internal/daily-recipients",
    )


# --------------------------------------------------------------------------
# Ollama model names (defaults were previously duplicated per file)
# --------------------------------------------------------------------------

def chat_model() -> str:
    """Site chat assistant + health model-presence check."""
    return _env("CHAT_OLLAMA_MODEL", "qwen3.5:4b")


def council_model() -> str:
    """Investment council deliberation model."""
    return _env("COUNCIL_OLLAMA_MODEL", "deepseek-r1:8b")


def commentary_model() -> str:
    """Daily market commentary narrative model."""
    return _env("COMMENTARY_OLLAMA_MODEL", "qwen3.5:9b")


def mag7_model() -> str:
    """Mag-7 commentary model (legacy env chain preserved)."""
    return os.getenv("MAG7_OLLAMA_MODEL") or os.getenv("LOCAL_OLLAMA_MODEL", "qwen3.5:9b")


def research_model() -> str:
    """Grounded-extraction model for web research (fast, not the council)."""
    return _env("RESEARCH_OLLAMA_MODEL") or chat_model()


# --------------------------------------------------------------------------
# Startup visibility
# --------------------------------------------------------------------------

def log_resolved(label: str = "") -> None:
    """Print a one-line summary of resolved endpoints/models.

    Called at app startup and pipeline entry so laptop-vs-server divergence
    is visible in logs instead of discovered during incidents. Never raises —
    a missing required value is reported inline, not thrown from a log call.
    """
    try:
        ollama = ollama_url()
    except ConfigError:
        ollama = "<UNSET — LOCAL_OLLAMA_URL required>"
    prefix = f"[config:{label}] " if label else "[config] "
    print(
        f"{prefix}ollama={ollama} kronos={kronos_url()} searxng={searxng_url()} "
        f"epm={epm_server_url()} models(chat={chat_model()}, council={council_model()}, "
        f"commentary={commentary_model()}, research={research_model()})"
    )
