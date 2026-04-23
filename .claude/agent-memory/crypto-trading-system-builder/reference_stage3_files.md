---
name: Stage 3 file map
description: Where Stage 3 components live (client/schema/trader/dashboard)
type: reference
---

Stage 3 artifacts added on top of Stages 1-2:

- `db/supabase_client.py` — `SupabaseLogger` + `NullLogger` + `build_logger()` factory (NoOp when keys missing).
- `supabase/schema.sql` — trades / portfolio_snapshots / agent_logs + indexes + RLS + Realtime publication.
- `agent/live_trader.py` — `LiveTrader` class (single-model or ensemble), `LiveFeaturePipeline`, `PaperBroker`/`LiveBroker`, APScheduler cron loop.
- `dashboard/` — Vite + React + TS + Tailwind + Recharts. Env vars: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_TRADE_SYMBOL`. Vercel-ready (`vercel.json`).
- `config.py` additions: `LIVE_BASE_CANDLE_LOOKBACK`, `LIVE_CONTEXT_CANDLE_LOOKBACK`, `LIVE_MODE_COUNTDOWN_SEC`, `SUPABASE_MAX_RETRIES`.

Feature consistency contract: `LiveFeaturePipeline` compares `add_features_multi_tf` output columns against `scaler.feature_names_in_` and raises if mismatched.
