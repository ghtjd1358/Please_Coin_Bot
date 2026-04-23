"""프로젝트 전역 상수. 매직넘버는 여기서만 정의."""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── 거래 모드 ───────────────────────────────────────────
TRADE_MODE = os.getenv("TRADE_MODE", "paper")
assert TRADE_MODE in ("paper", "live"), f"TRADE_MODE must be paper|live, got {TRADE_MODE}"

TRADE_SYMBOL = os.getenv("TRADE_SYMBOL", "KRW-BTC")

# ─── 리스크 방어 ─────────────────────────────────────────
MAX_LOSS_RATE = 0.15          # 평가 손실 15%에서 강제 매도
MAX_BUY_RATIO = 0.30          # 1회 매수 상한 (변동성 사이징 전 기준치)
MIN_BUY_RATIO = 0.10          # 고변동성 구간에서도 이 비율까지는 매수 허용
MAX_CONSECUTIVE_LOSS = 5      # 연속 손실 5회면 일시정지

# ─── 변동성 기반 동적 포지션 사이징 ──────────────────────
# buy_ratio = MAX_BUY_RATIO * clip(baseline_vol / current_vol, VOL_SCALE_FLOOR, 1.0)
VOL_SIZING_WINDOW = 20        # 현재 변동성 측정 기간 (스텝)
VOL_SIZING_BASELINE = 120     # 장기 baseline 변동성 기간 (스텝)
VOL_SCALE_FLOOR = 0.3         # 축소 최저 한계 — 0 방지
VOL_SCALE_CEIL = 1.0          # 확대 상한 — 리스크 상수 초과 금지

# ─── 거래소 제약 ─────────────────────────────────────────
UPBIT_FEE_RATE = 0.0005       # 업비트 원화마켓 0.05%
UPBIT_MIN_ORDER_KRW = 5_000   # 최소 주문 금액

# ─── 환경/학습 ───────────────────────────────────────────
OBS_WINDOW = 20               # 관측 윈도우 캔들 수
INITIAL_BALANCE = 1_000_000   # 모의투자 시작 자본 (원)

# ─── 멀티 타임프레임 ─────────────────────────────────────
# BASE_INTERVAL은 샘플 밀도를 결정. CONTEXT_INTERVALS는 추세 컨텍스트 병합용.
BASE_INTERVAL = "minute60"
BASE_COUNT = 17_000           # 1시간봉 ~ 2년치
CONTEXT_INTERVALS = ["day"]   # 병합할 장기 TF (종가 확정 이후 forward-fill)
CONTEXT_COUNT = 800           # 일봉 ~ 2년 + 여유

# ─── Walk-Forward ────────────────────────────────────────
WF_N_FOLDS = 5                # K-fold
WF_TRAIN_RATIO = 0.7          # 각 fold 내부에서 학습 구간 비율
WF_MIN_FOLD_ROWS = 2_000      # fold 당 최소 행 — 너무 적으면 스킵

# ─── 앙상블 ──────────────────────────────────────────────
ENSEMBLE_SEEDS = [42, 1337, 2024, 7, 100]

# ─── 실시간(paper/live) 실행 ─────────────────────────────
# 매 tick에 끌어올 베이스/컨텍스트 캔들 수. 관측 윈도우 + 지표 워밍업 여유치.
LIVE_BASE_CANDLE_LOOKBACK = 300
LIVE_CONTEXT_CANDLE_LOOKBACK = 200
# live 모드 진입 시 사용자 확인을 기다리는 카운트다운(초).
LIVE_MODE_COUNTDOWN_SEC = 5
# Supabase 네트워크 에러 재시도 — 실패해도 트레이더는 진행.
SUPABASE_MAX_RETRIES = 2

# ─── API 키 (live에서만 필요) ────────────────────────────
UPBIT_ACCESS_KEY = os.getenv("UPBIT_ACCESS_KEY", "")
UPBIT_SECRET_KEY = os.getenv("UPBIT_SECRET_KEY", "")

# ─── Supabase ────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ─── Slack 알림 (선택) ───────────────────────────────────
# Incoming Webhook URL. 비어 있으면 NullNotifier로 fallback — 봇은 Slack 없이 구동 가능.
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SLACK_USERNAME = os.getenv("SLACK_USERNAME", "please_coin-bot")
# 일일 요약 전송 여부. apscheduler가 별도 job으로 매일 자정에 실행.
SLACK_DAILY_DIGEST = os.getenv("SLACK_DAILY_DIGEST", "true").lower() == "true"
SLACK_TIMEOUT_SEC = 4.0        # POST 타임아웃. 트레이더 tick을 지연시키지 않도록 짧게.
