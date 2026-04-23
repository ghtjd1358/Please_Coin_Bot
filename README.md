# please_coin

업비트 기반 강화학습(PPO) 자동매매 시스템.

자세한 설계는 [ARCHITECTURE.md](./ARCHITECTURE.md), 작업 규칙은 [CLAUDE.md](./CLAUDE.md) 참조.

## 빠른 시작

```bash
# 1) 가상환경
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# 2) 의존성
pip install -r requirements.txt

# 3) 환경 변수
copy .env.example .env        # 값은 본인 키로 채울 것

# 4) 데이터 수집 (멀티 TF: base=minute60 + context=[day])
python main.py collect

# 5) 학습 — 두 경로 중 하나
#   a) 빠른 단일 시드
python main.py train
#   b) 다중 시드 앙상블 (권장 — 시드 운에 덜 의존)
python main.py train-ensemble

# 6) Walk-Forward 검증 — 시간 레짐 강건성 확인
python main.py walkforward

# 7) 백테스트
#   단일 모델
python main.py backtest \
  --model models/ppo_KRW-BTC_YYYYMMDD_HHMM.zip \
  --scaler KRW-BTC_YYYYMMDD_HHMM \
  --split val

#   앙상블 (seed_*.zip 디렉토리)
python main.py backtest \
  --ensemble models/ensemble_KRW-BTC_YYYYMMDD_HHMM/ \
  --scaler KRW-BTC_YYYYMMDD_HHMM \
  --split test
```

## Stage 3 — 모의투자 실행 + 대시보드

```bash
# 1) Supabase 스키마 적용 (최초 1회)
#    Dashboard → SQL Editor 에 supabase/schema.sql 내용 붙여넣기
#    또는:
psql "$SUPABASE_DB_URL" < supabase/schema.sql

# 2) .env 에 키 채우기 (SUPABASE_URL / SUPABASE_KEY = service role key)
#    live 모드일 때만 UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY 도 필수

# 3) 페이퍼 트레이더 기동 — 매 시 정각(BASE_INTERVAL=minute60 기준) 실행
python main.py live \
  --ensemble models/ensemble_KRW-BTC_YYYYMMDD_HHMM/ \
  --scaler KRW-BTC_YYYYMMDD_HHMM

#    또는 단일 모델
python main.py live \
  --model models/ppo_KRW-BTC_YYYYMMDD_HHMM.zip \
  --scaler KRW-BTC_YYYYMMDD_HHMM

# 4) 대시보드 기동 (별도 셸) — Supabase anon key 사용
cd dashboard
cp .env.example .env   # VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY 채우기
npm install
npm run dev
```

실전(`live`) 전환은 `.env`의 `TRADE_MODE=live`로만 변경. 기동 시 5초 카운트다운 배너 출력.

## 단계별 로드맵

| 단계 | 상태 | 산출물 |
|-----|------|-------|
| 1. 데이터·환경 구축 | ✅ 멀티 TF + 변동성 사이징 | `data/`, `env/trading_env.py` |
| 2. 백테스트 학습 | ✅ 단일/앙상블 + Walk-Forward | `agent/train.py`, `agent/ensemble.py`, `agent/walk_forward.py`, `agent/backtest.py` |
| 3. 모의투자 | ✅ paper 루프 + Supabase + 대시보드 | `agent/live_trader.py`, `db/supabase_client.py`, `supabase/schema.sql`, `dashboard/` |
| 4. 실전 투입 | 🔲 검증 기준 충족 시 | 수익률 >15%, MDD <20%, 샤프 >1.0, Sortino/Calmar 양호 |

## 안전 스위치

- 기본 모드는 **항상** `TRADE_MODE=paper`
- 실전 전환 전 반드시 `config.py`와 `.env` 모두 확인
- 주요 상수는 `config.py` 중앙 관리 (매직넘버 금지)

## 프로젝트 구조

```
please_coin/
├── config.py              # 리스크/모드 상수
├── main.py                # CLI 엔트리
├── data/                  # 수집 + 전처리
├── env/                   # gymnasium 환경
├── agent/                 # 학습/백테스트/실매매
├── db/                    # Supabase 로깅
├── dashboard/             # React 대시보드 (예정)
├── .claude/
│   ├── agents/            # data-pipeline / rl-trainer / backtest-analyst
│   └── skills/            # upbit-api / rl-trading / risk-guard
├── ARCHITECTURE.md
└── CLAUDE.md
```
