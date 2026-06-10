"""PR C: services/runtime_config.py — single source of truth for internal
service endpoints and Ollama model names.

Policy under test:
  - LOCAL_OLLAMA_URL is REQUIRED (clear ConfigError when unset/blank).
  - Sidecars (Kronos, SearxNG) and the public domain keep allowed defaults.
  - Env var names are unchanged; env always wins over defaults.
"""
import pytest

import services.runtime_config as rc


# ---------------------------------------------------------------------------
# ollama_url — required, no silent default
# ---------------------------------------------------------------------------

def test_ollama_url_returns_env_value(monkeypatch):
    monkeypatch.setenv("LOCAL_OLLAMA_URL", "http://100.101.63.65:11434")
    assert rc.ollama_url() == "http://100.101.63.65:11434"


def test_ollama_url_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("LOCAL_OLLAMA_URL", "http://127.0.0.1:11434/")
    assert rc.ollama_url() == "http://127.0.0.1:11434"


def test_ollama_url_unset_raises_config_error(monkeypatch):
    monkeypatch.delenv("LOCAL_OLLAMA_URL", raising=False)
    with pytest.raises(rc.ConfigError, match="LOCAL_OLLAMA_URL"):
        rc.ollama_url()


def test_ollama_url_blank_raises_config_error(monkeypatch):
    monkeypatch.setenv("LOCAL_OLLAMA_URL", "   ")
    with pytest.raises(rc.ConfigError, match="LOCAL_OLLAMA_URL"):
        rc.ollama_url()


def test_ollama_url_error_names_both_machine_values(monkeypatch):
    """The error must tell the operator what to set on each machine."""
    monkeypatch.delenv("LOCAL_OLLAMA_URL", raising=False)
    with pytest.raises(rc.ConfigError) as exc:
        rc.ollama_url()
    msg = str(exc.value)
    assert "127.0.0.1:11434" in msg      # server value
    assert "100.101.63.65:11434" in msg  # laptop (Tailscale) value


# ---------------------------------------------------------------------------
# Sidecars + public origin — allowed defaults, env wins
# ---------------------------------------------------------------------------

def test_kronos_url_default_and_override(monkeypatch):
    monkeypatch.delenv("KRONOS_URL", raising=False)
    assert rc.kronos_url() == "http://127.0.0.1:8100"
    monkeypatch.setenv("KRONOS_URL", "http://127.0.0.1:9100/")
    assert rc.kronos_url() == "http://127.0.0.1:9100"


def test_searxng_url_default_and_override(monkeypatch):
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    assert rc.searxng_url() == "http://127.0.0.1:8080"
    monkeypatch.setenv("SEARXNG_URL", "http://127.0.0.1:9090")
    assert rc.searxng_url() == "http://127.0.0.1:9090"


def test_epm_server_url_default_and_override(monkeypatch):
    monkeypatch.delenv("EPM_SERVER_URL", raising=False)
    assert rc.epm_server_url() == "https://epm-market-intelligence.com"
    monkeypatch.setenv("EPM_SERVER_URL", "http://100.101.63.65:8000/")
    assert rc.epm_server_url() == "http://100.101.63.65:8000"


def test_internal_recipients_url_derives_from_server_url(monkeypatch):
    monkeypatch.delenv("INTERNAL_RECIPIENTS_URL", raising=False)
    monkeypatch.setenv("EPM_SERVER_URL", "http://100.101.63.65:8000")
    assert rc.internal_recipients_url() == (
        "http://100.101.63.65:8000/api/internal/daily-recipients"
    )


def test_internal_recipients_url_explicit_override_wins(monkeypatch):
    monkeypatch.setenv("INTERNAL_RECIPIENTS_URL", "http://x/custom")
    assert rc.internal_recipients_url() == "http://x/custom"


# ---------------------------------------------------------------------------
# Model names — defaults centralized, env wins, legacy chains preserved
# ---------------------------------------------------------------------------

def test_model_defaults(monkeypatch):
    for var in ("CHAT_OLLAMA_MODEL", "COUNCIL_OLLAMA_MODEL",
                "COMMENTARY_OLLAMA_MODEL", "RESEARCH_OLLAMA_MODEL",
                "MAG7_OLLAMA_MODEL", "LOCAL_OLLAMA_MODEL"):
        monkeypatch.delenv(var, raising=False)
    assert rc.chat_model() == "qwen3.5:4b"
    assert rc.council_model() == "deepseek-r1:8b"
    assert rc.commentary_model() == "qwen3.5:9b"
    assert rc.mag7_model() == "qwen3.5:9b"
    assert rc.research_model() == "qwen3.5:4b"  # falls back to chat model


def test_model_env_overrides(monkeypatch):
    monkeypatch.setenv("CHAT_OLLAMA_MODEL", "chat-x")
    monkeypatch.setenv("COUNCIL_OLLAMA_MODEL", "council-x")
    monkeypatch.setenv("COMMENTARY_OLLAMA_MODEL", "comm-x")
    monkeypatch.setenv("RESEARCH_OLLAMA_MODEL", "res-x")
    assert rc.chat_model() == "chat-x"
    assert rc.council_model() == "council-x"
    assert rc.commentary_model() == "comm-x"
    assert rc.research_model() == "res-x"


def test_research_model_falls_back_to_chat_model(monkeypatch):
    monkeypatch.delenv("RESEARCH_OLLAMA_MODEL", raising=False)
    monkeypatch.setenv("CHAT_OLLAMA_MODEL", "chat-y")
    assert rc.research_model() == "chat-y"


def test_mag7_model_legacy_chain(monkeypatch):
    monkeypatch.setenv("LOCAL_OLLAMA_MODEL", "legacy-m")
    monkeypatch.delenv("MAG7_OLLAMA_MODEL", raising=False)
    assert rc.mag7_model() == "legacy-m"
    monkeypatch.setenv("MAG7_OLLAMA_MODEL", "mag7-m")
    assert rc.mag7_model() == "mag7-m"


# ---------------------------------------------------------------------------
# log_resolved — startup visibility, never raises
# ---------------------------------------------------------------------------

def test_log_resolved_with_ollama_set(monkeypatch, capsys):
    monkeypatch.setenv("LOCAL_OLLAMA_URL", "http://127.0.0.1:11434")
    rc.log_resolved("test")
    out = capsys.readouterr().out
    assert "[config:test]" in out
    assert "ollama=http://127.0.0.1:11434" in out
    assert "kronos=" in out and "searxng=" in out


def test_log_resolved_never_raises_when_ollama_unset(monkeypatch, capsys):
    monkeypatch.delenv("LOCAL_OLLAMA_URL", raising=False)
    rc.log_resolved()
    out = capsys.readouterr().out
    assert "UNSET" in out
    assert "LOCAL_OLLAMA_URL" in out
