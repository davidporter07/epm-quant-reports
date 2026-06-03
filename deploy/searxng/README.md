# SearxNG — internal search backend (EPM)

Self-hosted metasearch used by the PM-discovery agent (`pm_research.py`) and any
future internal-search feature. **Localhost-only**, alongside Ollama/Kronos on
`epm-server`. Until this is running, the PM-discovery feature simply no-ops —
funds still get the Phase 1 holdings/mandate analysis.

## One-time stand-up (on the server)

```bash
cd ~/fund_monitor/deploy/searxng   # adjust to the deployed path

# 1. Generate a real secret key into settings.yml (replaces the placeholder)
sed -i "s|CHANGE_ME_RUN_OPENSSL_RAND_HEX_32|$(openssl rand -hex 32)|" settings.yml

# 2. Launch (Docker must be installed)
docker compose up -d

# 3. Verify the JSON API answers
curl 'http://127.0.0.1:8080/search?q=ARK+Innovation+portfolio+manager&format=json' | head -c 400
```

If step 3 returns JSON with a `results` array, the app will pick it up
automatically — no app restart needed (the provider probes per request).

## Config the app reads

- `SEARXNG_URL` (default `http://127.0.0.1:8080`) — only set in the server
  `.env` if you change the host/port.
- `PM_RESEARCH_TIMEOUT_SEC` (default `75`) — join timeout for the concurrent
  PM-discovery thread in `deep_analysis.build_seed_doc`.

## Operations

```bash
docker compose logs -f searxng      # tail logs
docker compose restart searxng      # restart
docker compose down                 # stop
```

## Notes

- The `ports` binding is `127.0.0.1:8080` on purpose — do **not** change it to
  `0.0.0.0`. This service must not be reachable from the public internet.
- `limiter: false` is safe only because access is loopback-only.
- Provider contract: `searxng_provider.py` never raises and returns `[]` on any
  error, so a stopped container degrades gracefully.
