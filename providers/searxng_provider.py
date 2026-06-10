"""searxng_provider.py — thin client for a self-hosted SearxNG JSON API.

SearxNG is a privacy-respecting metasearch engine. We run it locally on the
EPM server (Docker, bound to 127.0.0.1) as a reusable internal search backend
for analytical features such as the PM-discovery agent (see pm_research.py).

Design contract: this provider NEVER raises and NEVER blocks the pipeline.
Every failure mode — container not running, network error, malformed JSON,
non-200 — returns an empty list. Callers treat "no results" and "backend
absent" identically, so the feature degrades gracefully until the container
is stood up.

Env:
  SEARXNG_URL  base URL of the JSON API (default via services/runtime_config)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests

from services import runtime_config as _rc


class SearxNGProvider:
    def __init__(self, base_url: Optional[str] = None, timeout: float = 8.0):
        self.base_url = (base_url or _rc.searxng_url()).rstrip("/")
        self.timeout = timeout

    def available(self) -> bool:
        """Cheap reachability probe. True only if the JSON search endpoint answers."""
        try:
            r = requests.get(
                f"{self.base_url}/search",
                params={"q": "ping", "format": "json"},
                timeout=min(self.timeout, 4.0),
            )
            return r.status_code == 200
        except Exception:
            return False

    def search(
        self,
        query: str,
        categories: str = "general",
        max_results: int = 8,
        language: str = "en",
    ) -> List[Dict[str, Any]]:
        """Return [{title, url, content}] for a query, or [] on any failure."""
        if not query or not query.strip():
            return []
        try:
            r = requests.get(
                f"{self.base_url}/search",
                params={
                    "q": query,
                    "format": "json",
                    "categories": categories,
                    "language": language,
                },
                timeout=self.timeout,
            )
            if r.status_code != 200:
                return []
            data = r.json()
        except Exception:
            return []

        out: List[Dict[str, Any]] = []
        for item in (data.get("results") or [])[:max_results]:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not url:
                continue
            out.append({
                "title":   (item.get("title") or "").strip(),
                "url":     url,
                "content": (item.get("content") or "").strip(),
            })
        return out
