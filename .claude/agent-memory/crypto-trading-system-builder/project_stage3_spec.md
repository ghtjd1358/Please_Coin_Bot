---
name: Stage 3 spec (paper trading + DB + dashboard)
description: Stage 3 goals, absolute rules, and interfaces agreed with the user
type: project
---

Stage 3 is paper-trading execution + Supabase logging + React dashboard on top of completed Stage 1/2.

**Why:** Stages 1-2 (data/env/train/ensemble/walk-forward/backtest) are frozen. Stage 3 must not touch them — any regression in the env/reward/sizing would invalidate prior validation results.

**How to apply:**
- `TRADE_MODE` default is always `"paper"`. Never hardcode `"live"` in source; it comes from `.env` or explicit CLI.
- Magic numbers forbidden — all risk constants live in `config.py`.
- Real-time feature pipeline must produce EXACT same columns/order/scale as training: verify against `scaler.feature_names_in_`.
- `SupabaseLogger` must be NoOp-safe when keys are missing; network errors must not kill the trader.
- Model loading supports both single `.zip` and `ensemble_*/` directory (via `EnsemblePolicy.from_dir`).
- Ensemble bot must keep per-model LSTM state lists (cannot share).
- Position state persisted via Supabase `portfolio_snapshots` — bot restores from latest snapshot on restart.
- Circuit breakers: `MAX_CONSECUTIVE_LOSS` → scheduler.pause(); cumulative loss > `MAX_LOSS_RATE` → force sell + shutdown.
