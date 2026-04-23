# please_coin — 아키텍처

## 1. 시스템 흐름

```
 ┌───────────────┐   과거 OHLCV    ┌──────────────┐
 │  업비트 API   │ ───────────────▶│ data/collector│  ← 멀티 TF 수집
 └───────────────┘                 └──────┬───────┘
                                          │
                                          ▼
                                   ┌──────────────┐
                                   │preprocessor  │  ← 멀티 TF 병합 (merge_asof)
                                   └──────┬───────┘
                                          ▼
                                   ┌──────────────┐
                                   │ TradingEnv   │  gymnasium.Env + 변동성 사이징
                                   └──────┬───────┘
                                          ▼
         ┌───────────┬───────────────┴────────────────┬──────────────┐
         ▼           ▼                                 ▼              ▼
   agent/train   agent/ensemble   agent/walk_forward   agent/backtest  agent/live_trader
    (단일 학습)  (다중 시드 학습)    (K-fold 검증)        (평가)        paper | live
                                                                          │
                                                                          ▼
                                                                   ┌──────────────┐
                                                                   │db/supabase   │ 매매 기록
                                                                   └──────┬───────┘
                                                                          ▼
                                                                   ┌──────────────┐
                                                                   │dashboard (R) │ Vercel
                                                                   └──────────────┘
```

## 2. 강화학습 설계

### 2-1. 상태 (Observation)
에이전트가 매 스텝 관찰하는 벡터. 최근 N=`OBS_WINDOW` 캔들 윈도우.

- **시세 파생 피처**: 베이스 TF 19개 + 컨텍스트 TF 당 5개 (§2-6)
- **포트폴리오**: 현금 비중 / 코인 평가액 비중 / 평균매수가 상대비 / 미실현 손익률

피처 컬럼 목록은 **데이터 파이프라인이 결정**하고 환경·스케일러·학습 루프는 이를 그대로 전달받는다 (매직 컬럼 하드코딩 금지).

### 2-2. 행동 (Action)
이산 공간 3개. 추후 연속 공간 확장 가능.

| 코드 | 의미 |
|-----|------|
| 0 | 홀드 |
| 1 | 매수 (**변동성 기반 동적 비율**) |
| 2 | 매도 (보유 전량) |

### 2-3. 보상 — Differential Sharpe Ratio

Moody & Saffell (1998) DSR. 수수료 차감된 포트폴리오 수익률 `R_t`에 대해:

```
A_t = A_{t-1} + η (R_t - A_{t-1})
B_t = B_{t-1} + η (R_t² - B_{t-1})
D_t = (B·ΔA - ½·A·ΔB) / (B - A²)^{3/2}
```

DSR 자체에 거래비용 · 변동성 페널티가 내재 → **낮은 드로다운을 지향**하는 학습.

### 2-4. 정책 네트워크 — RecurrentPPO (LSTM)

- `MlpLstmPolicy`, pi/vf `[128,128]` MLP + `lstm_hidden_size=128`.
- LSTM이 윈도우 너머의 장기 컨텍스트(트렌드·레짐)를 숨은 상태에 압축.
- `ent_coef=0.005`, `target_kl=0.02`.

### 2-5. 멀티 타임프레임 피처

- **베이스 TF** = `config.BASE_INTERVAL` (기본: `minute60`). 에이전트 결정 주기.
- **컨텍스트 TF** = `config.CONTEXT_INTERVALS` (기본: `["day"]`). 베이스 피처에 **merge_asof**로 병합.
- **Look-ahead 차단**: 컨텍스트 캔들 인덱스를 "종가 확정 시각"(`ts + interval_length`)으로 shift한 뒤 `direction="backward"`로 병합. 실시간 매매에서 아직 확정되지 않은 종가를 보는 일이 원천적으로 불가.
- 베이스 피처 19개 + 컨텍스트 TF 당 5개 (`log_ret_1`, `ema_gap_20_60`, `adx`, `rsi_14`, `realized_vol_20`).

### 2-6. 피처 세트

**Base (19)**:

| 카테고리 | 피처 |
|---------|-----|
| 수익률(로그) | `log_ret_1/5/20` |
| 추세 | `ema_gap_5_20/20_60`, `macd/signal/hist`, `adx` |
| 모멘텀 | `rsi_14`, `stoch_rsi_k/d` |
| 변동성 | `atr_ratio`, `bb_width`, `bb_pos`, `realized_vol_20` |
| 거래량 | `obv_change`, `volume_ratio`, `mfi_14` |

**Context** (TF당, 접두사 `ctx_<interval>_`): `log_ret_1`, `ema_gap_20_60`, `adx`, `rsi_14`, `realized_vol_20`.

모두 **정상성 있는 비율/수익률**. `RobustScaler`로 fit — train 구간만.

### 2-7. 변동성 기반 동적 포지션 사이징

매수 시 `MAX_BUY_RATIO`를 고정 적용하는 대신, 직전 구간의 실현변동성을 반영해 크기를 조절.

```
current_vol  = std(log_ret, window = VOL_SIZING_WINDOW)
baseline_vol = std(log_ret, window = VOL_SIZING_BASELINE)
scale        = clip(baseline_vol / current_vol, VOL_SCALE_FLOOR, VOL_SCALE_CEIL)
buy_ratio    = max(MAX_BUY_RATIO * scale, MIN_BUY_RATIO)
```

- **고변동성 구간**(current > baseline) → scale < 1 → 매수량 축소.
- **저변동성 구간**(current < baseline) → scale = 1로 clip → `MAX_BUY_RATIO` 유지 (상한 초과 금지).
- `MIN_BUY_RATIO` 하한으로 완전 관망 방지. 초기 데이터 부족 구간은 `MAX_BUY_RATIO` fallback.

### 2-8. Walk-Forward 검증

`agent/walk_forward.py`. 랜덤 분할·단일 train/test로는 **시간 의존 레짐 변화**를 포착할 수 없다.

- `WF_N_FOLDS` 폴드로 롤링 분할. 각 폴드 내에서 앞쪽 `WF_TRAIN_RATIO`로 학습, 뒤쪽을 평가.
- **각 폴드의 scaler는 해당 폴드의 train 구간만으로 fit** (look-ahead 방지).
- 폴드당 timesteps는 `WF_TIMESTEPS_PER_FOLD=150,000`으로 제한 (K배 누적 비용 고려).
- 리포트: 폴드별 Total Return / MDD / Sharpe / Sortino / Calmar + 평균 ± 표준편차.

### 2-9. 앙상블

`agent/ensemble.py`. 단일 시드 PPO는 **같은 하이퍼파라미터로도 결과가 크게 요동**.

- `ENSEMBLE_SEEDS`의 각 시드로 순차 학습, 시드별 모델을 `models/ensemble_*/seed_<N>.zip`에 저장.
- 추론 시 `EnsemblePolicy`가 각 모델의 action을 수집, **최빈값**(plurality vote)으로 결정. 이산 공간이라 평균 대신 최빈값.
- LSTM 상태는 모델별로 분리 관리 (공유 불가).

## 3. 안전장치 (`config.py`)

| 상수 | 기본값 | 역할 |
|-----|-------|-----|
| `MAX_LOSS_RATE` | 0.15 | 평가손실 15% 도달 시 강제 매도 |
| `MAX_BUY_RATIO` | 0.30 | 변동성 사이징의 상한 기준치 |
| `MIN_BUY_RATIO` | 0.10 | 고변동성 구간에서도 이 비율까지는 매수 허용 |
| `MAX_CONSECUTIVE_LOSS` | 5 | 5연속 손절 시 에이전트 일시정지 |
| `VOL_SIZING_WINDOW` / `_BASELINE` | 20 / 120 | 변동성 사이징 창 |
| `VOL_SCALE_FLOOR` / `_CEIL` | 0.3 / 1.0 | 사이징 스케일 clip 경계 |
| `WF_N_FOLDS` / `_TRAIN_RATIO` | 5 / 0.7 | Walk-Forward 설정 |
| `ENSEMBLE_SEEDS` | [42, 1337, 2024, 7, 100] | 앙상블 시드 |
| `TRADE_MODE` | `"paper"` | 기본 모의. `"live"`는 명시적 요청 시에만 |

## 4. 개발 단계

1. **데이터·환경 구축** — collector/preprocessor/TradingEnv + `check_env()` 통과 ✅
2. **백테스트 학습** — Walk-Forward + 앙상블 학습으로 강건성 검증 (수익률/MDD/샤프/Sortino/Calmar)
3. **모의투자** — 실시간 시세 연결, 가상 잔고 100만원, Supabase 로깅
4. **실전 투입** — 검증 기준 충족 시

## 5. Stage 3 — 모의투자 실행 계층

### 5-1. 실시간 트레이더 (`agent/live_trader.py`)

매 tick 흐름 (APScheduler `BlockingScheduler` + `BASE_INTERVAL` 기반 CronTrigger):

```
pyupbit fetch_ohlcv(base + context)
   → add_features_multi_tf (merge_asof, look-ahead 차단)
   → normalizer.transform (학습 때 저장된 scaler 재사용)
   → 컬럼/순서 검증 (scaler.feature_names_in_ 와 동일해야 통과)
   → window[-OBS_WINDOW:] + 포트폴리오 4 ─▶ RecurrentPPO / EnsemblePolicy
   → PaperBroker | LiveBroker 집행
   → Supabase: insert_snapshot + insert_trade + insert_agent_log
   → LossStreakGuard / 누적 손실 체크
```

- **모델 로딩**은 단일 `.zip` 또는 `ensemble_*/seed_*.zip` 디렉토리 둘 다 지원
  (`_make_predictor` 가 `backtest.py`와 동일 시그니처).
- **LSTM 상태**는 앙상블이면 `EnsemblePolicy.initial_state()`로 모델당 독립.
- **포지션 복원**: 기동 시 `portfolio_snapshots`의 최신 행(같은 symbol + mode)으로
  `Position`을 초기화 → 중단/재기동 간 잔고 연속성 유지.
- **리스크 게이트**
  - `LossStreakGuard` : `MAX_CONSECUTIVE_LOSS` 초과 → `scheduler.pause()` + TODO Slack 훅.
  - 누적 손실 ≥ `MAX_LOSS_RATE` → 전량 매도 + `scheduler.shutdown()`.
  - Tick 내 `_check_forced_stop_loss` : 보유 포지션 손실이 `MAX_LOSS_RATE` 이상이면
    에이전트 행동 무시하고 즉시 청산.
- **graceful shutdown**: `SIGINT/SIGTERM` 핸들러가 마지막 snapshot을 1회 더 기록.

### 5-2. DB 스키마 (`supabase/schema.sql`)

| 테이블 | 역할 | 핵심 컬럼 |
|-------|-----|----------|
| `trades` | 매매 이벤트 | `action(buy/sell/hold/stop_loss)`, `price`, `amount`, `fee`, `pnl`, `mode(paper/live)` |
| `portfolio_snapshots` | 매 tick 상태 | `total_value`, `balance`, `coin_held`, `avg_buy_price`, `unrealized_pnl` |
| `agent_logs` | 관측·행동 요약 | `obs_summary jsonb`, `action`, `reward`, `confidence` |

- 모든 테이블에 `(symbol, created_at DESC)` 복합 인덱스 — 대시보드 조회 핫 패스.
- RLS: anon/authenticated 는 SELECT만, service role만 INSERT. 봇은 service key, 대시보드는 anon.
- `supabase_realtime` publication에 세 테이블 전부 추가 (Realtime 스트리밍).
- **append-only** — 삭제·수정 없음. 테이블 간 FK 없이 독립이라 대시보드는 조인 불필요.

### 5-3. Supabase 클라이언트 (`db/supabase_client.py`)

- `build_logger()` factory: 키가 없으면 `NullLogger` (NoOp) 반환 → 봇이 키 없이도 동작.
- 모든 insert는 `try/except + retry(SUPABASE_MAX_RETRIES)` 후 실패 시 `logging.warning`.
  → 네트워크 에러로 트레이더 루프가 죽지 않는다.
- `mode`는 인스턴스 속성으로 자동 주입 (호출부에서 매번 넘기지 않음).

### 5-4. 대시보드 (`dashboard/` — Vite + React + TS + Tailwind + Recharts)

```
src/
├── App.tsx
├── lib/supabase.ts          # 클라이언트 + DB row 타입
├── lib/metrics.ts           # MDD/Sharpe/Sortino/Calmar (클라이언트 계산)
├── hooks/
│   ├── useRealtimeTrades.ts   # trades INSERT 스트림
│   ├── usePortfolioHistory.ts # snapshots INSERT 스트림 + 초기 로드
│   └── useLatestSnapshot.ts   # history tail 파생
└── components/
    ├── PortfolioCard.tsx    # 잔고·보유·평가·미실현 PnL
    ├── ReturnChart.tsx      # 수익률 라인 (Recharts)
    ├── RiskMetrics.tsx      # 검증 기준치(15% / 20% / 1.0)와 톤 매핑
    ├── TradesTable.tsx      # 색상: buy=green, sell=red, stop_loss=orange, hold=gray
    └── AgentStatus.tsx      # 포지션 + 마지막 액션 + Realtime 연결 상태
```

- 채널: `trades-<symbol>`, `snapshots-<symbol>` 각각 `postgres_changes INSERT` 구독.
- 계산 지표는 1시간봉 기준 연환산 상수(`ANNUALIZATION = 24*365`). `BASE_INTERVAL` 바뀌면 조정.
- 환경변수: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_TRADE_SYMBOL`.
- 배포: Vercel, `dashboard/`를 루트로 설정 (`vercel.json` 포함). `framework: vite`.

## 6. 기술 스택 요약
**Python**: pyupbit, gymnasium, stable-baselines3 + sb3-contrib, pandas, numpy, ta, supabase-py, apscheduler
**Frontend**: React + TypeScript + Recharts + Supabase JS
**Infra**: Supabase (DB), Vercel (대시보드), 로컬/VPS (학습·매매 봇)
