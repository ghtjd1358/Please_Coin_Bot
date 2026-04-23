# please_coin — Claude 작업 지침

업비트 기반 강화학습(RL) 자동매매 프로젝트. 설계 원본은 `ARCHITECTURE.md` 참조.

## 🔴 인수인계 (Handoff) — 2026-04-23 21:00 KST 기준

> **새 세션에서 이 파일만 읽고도 즉시 이어가야 할 때 이 섹션부터 본다.**

### 현재 상황 한 줄 요약
노트북에서 집 PC로 옮기는 중. 페이퍼 봇은 정지된 상태. 재학습(hyperparameter 재튜닝)이 다음 최우선 과제.

### 지금까지 완료된 것

| 항목 | 상태 | 비고 |
|------|-----|------|
| Stage 1 (데이터·환경) | ✅ | 16,186행 × 24 피처, 멀티TF(minute60+day) |
| Stage 2 (학습·백테스트) | ✅ | 앙상블 5시드 + Walk-Forward |
| Stage 3 (실시간·대시보드) | ✅ | Supabase + Slack + Vercel 대시보드 |
| 외부 연결 | ✅ | Supabase, Slack Webhook, Vercel 전부 검증됨 |

### 핵심 문제 인식 (중요)

**현 모델(`ensemble_KRW-BTC_20260423_0013`)은 "매도 신호만 내는" 기형적 정책에 고착**:
- 백테스트: Return -7.58%, Sharpe -0.709 (FAIL)
- 페이퍼 라이브 3 tick 연속 `action=sell` 그러나 `coin_held=0`이라 전부 no-op
- 원인 추정: `ent_coef=0.005`가 한쪽 액션으로 조기 수렴 유도
- 재학습 시 `ent_coef=0.01`(이전 시도)은 오히려 악화됨 → **0.005 원복 또는 0.007 절충 필요**

### 집 PC 세팅 절차 (총 ~15분)

```bash
# 1. 프로젝트 가져오기
git clone https://github.com/ghtjd1358/Please_Coin_Bot.git
cd Please_Coin_Bot

# 2. Python 3.14 설치 확인 (안 됐으면 python.org에서)
python --version

# 3. 가상환경 + 의존성
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pyarrow          # 의존성 목록엔 들어있지만 재확인

# 4. 대시보드 의존성 (선택)
cd dashboard && npm install && cd ..

# 5. .env 파일 생성 — 사용자가 별도 보관한 값으로 채워야 함
#    (이 CLAUDE.md엔 시크릿 없음, 사용자 메모/USB에서 복사)
#    필수 키: SUPABASE_URL, SUPABASE_KEY(service_role),
#              SLACK_WEBHOOK_URL, TRADE_MODE=paper, TRADE_SYMBOL=KRW-BTC

# 6. 데이터 수집 (재시도) — 캐시가 노트북에 있으니 새로 받아야 함
python main.py collect

# 7. 재학습 (최우선) — ent_coef 원복 후
# agent/train.py의 HP 딕셔너리에서 ent_coef=0.005로 수정
python main.py train-ensemble

# 8. 백테스트로 구 모델 대비 개선 확인
python main.py backtest --ensemble models/ensemble_KRW-BTC_<신규stamp>/ \
    --scaler KRW-BTC_<신규stamp> --split test

# 9. 만족스러우면 paper 봇 재기동
scripts\run_bot.bat     # Windows 더블클릭 OK
```

### 외부 리소스 (시크릿 아님)

| 리소스 | 값 |
|-------|-----|
| GitHub repo | https://github.com/ghtjd1358/Please_Coin_Bot |
| Supabase project ID | `iqihalicaojqrqqlmtun` |
| Supabase URL | `https://iqihalicaojqrqqlmtun.supabase.co` |
| Vercel 대시보드 | `https://dashboard-8x150o3wr-sonhoseongs-projects.vercel.app` |
| Supabase 테이블 | `trades`, `portfolio_snapshots`, `agent_logs` (RLS: anon read / service write) |
| Slack 채널 | `#trading-alerts` (workspace `coin_up`) |

### `.env` 템플릿 (사용자가 값 채움)

```env
# 업비트 (live 전환 시에만 필요, 지금은 비워둠)
UPBIT_ACCESS_KEY=
UPBIT_SECRET_KEY=

# Supabase — 사용자 메모에서 복사
SUPABASE_URL=https://iqihalicaojqrqqlmtun.supabase.co
SUPABASE_KEY=<service_role JWT — 사용자가 보관한 값>

# 매매 모드 (절대 live로 바꾸지 말 것 — 사용자 명시 요청 있어야만)
TRADE_MODE=paper
TRADE_SYMBOL=KRW-BTC

# Slack Webhook — 사용자 메모에서 복사
SLACK_WEBHOOK_URL=<사용자가 보관한 Webhook URL>
SLACK_USERNAME=please_coin-bot
SLACK_DAILY_DIGEST=true
```

### 사용자가 "재학습 해줘" 요청 시 실행 순서

1. `agent/train.py`의 HP dict에서 `ent_coef`를 **0.005**(원복) 또는 **0.007**(절충)로 변경
2. `main` 세션에서 background 실행: `python main.py train-ensemble`
   - 서브에이전트가 띄운 background 프로세스는 에이전트 종료와 함께 죽음 (알려진 이슈) → **메인 세션에서 직접**
3. Monitor 걸어 seed 전환/완료/에러 감시
4. 완료 후 자동으로 `backtest --split test` 실행해 구 모델 대비 비교
5. Sharpe > 구 모델(-0.709) + Win Rate 유지(≥55%)면 페이퍼 봇 새 모델로 스왑

### 메모리 이슈 (Windows 16GB 환경)

5-seed 학습 시 5번째 시드에서 OOM 재발 위험:
- `agent/ensemble.py`에 `gc.collect() + train_env.close()` 이미 적용
- `agent/train.py` HP: `n_steps=1024` (메모리 절반), `batch_size=64`
- 그래도 부족하면: 페이퍼 봇 일시정지 + IntelliJ/브라우저 닫기

### 사용자가 이미 선택한 방향

- **옵션 A** (재학습 없이 paper만 축적) → 매도 고착으로 무의미하다고 판단, 집 PC에서 재학습 우선으로 전환
- 10만원 실전 투입은 **거절** (검증 기준 미통과 상태에서 실돈 금지 — CLAUDE.md 원칙)
- Vercel 배포는 **대시보드만** (Python 봇은 PC/VPS, Fluid Compute 부적합)

### 주의 사항

- `.env`는 **절대 커밋 금지** (`.gitignore` 등록됨)
- Supabase 데이터는 재부팅 무관하게 생존 (Vercel도 마찬가지)
- Monitor/BashOutput 이벤트는 사용자 응답이 아님
- 서브에이전트에게 장시간 background 작업 맡기지 말 것 — 서브에이전트 종료 시 프로세스도 죽음

## 프로젝트 본질
- **1차 목표**: 모의투자(paper) 수익 검증. **2차 목표**: 실전(live) 투입.
- **검증 기준**(2차 진입 전제): 3개월 수익률 > 15%, MDD < 20%, 샤프비율 > 1.0.
- **대상 자산**: BTC 단일로 시작. 안정화 후 ETH 추가.

## 작업 시 절대 규칙

### 1. 리스크 상수는 `config.py`에서만 정의
- `MAX_LOSS_RATE`, `MAX_BUY_RATIO`, `MAX_CONSECUTIVE_LOSS`, `TRADE_MODE` 등은 매직넘버 금지.
- 수정 시 변경 이유를 커밋 메시지에 반드시 남길 것.

### 2. 기본 모드는 항상 `TRADE_MODE="paper"`
- 실전 전환(`"live"`)은 사용자가 명시적으로 요청했을 때만 변경.
- `live_trader.py`는 기동 시 `TRADE_MODE`를 재확인하고, `live`일 경우 콘솔에 경고 배너 출력.

### 3. gymnasium 표준 인터페이스 엄수
- `TradingEnv`는 반드시 `reset()`, `step()`, `observation_space`, `action_space`를 제공.
- stable-baselines3 호환성 깨는 변경은 금지 — 변경 시 `check_env()` 통과 확인.
- 정책은 **RecurrentPPO + MlpLstmPolicy** (sb3-contrib). 메모리 없는 MLP 정책으로 회귀 금지 — 트렌드/레짐 인식 불가.
- 보상은 **Differential Sharpe Ratio** (Moody & Saffell 1998). 단순 수익률 보상으로 회귀하지 말 것 — 변동성 페널티가 빠져 드로다운이 폭주함.
- 매수 크기는 **변동성 기반 동적 사이징** (`TradingEnv._buy_ratio`). 고정 `MAX_BUY_RATIO`로 회귀 금지 — 고변동성 구간에서 포지션 과다가 MDD를 폭주시킨다.

### 4. 데이터 누수(look-ahead) 방지
- 현재 스텝 `t`의 관측에는 **절대로 `t` 이후 캔들의 정보**가 들어가면 안 됨.
- 기술적 지표 계산 후 NaN 구간은 반드시 드롭 또는 마스킹.
- **정규화 스케일러는 train 구간만으로 fit**. val/test/실매매는 같은 스케일러를 `transform`만 — fit 금지.
- Walk-Forward에서도 **각 fold의 scaler는 그 fold의 train 구간만으로 fit**.
- 멀티 TF 컨텍스트 병합은 반드시 `add_features_multi_tf` 경로를 사용. 캔들 인덱스를 "종가 확정 시각"으로 shift한 뒤 `merge_asof(direction="backward")` — 직접 컨텍스트 컬럼을 덧붙이지 말 것.
- 피처는 가격 절대값이 아니라 **로그수익률·비율**을 우선 (정상성 확보).

### 5. 검증·학습 파이프라인
- 모델 품질은 **Walk-Forward 검증**(`agent.walk_forward`)으로 판단. 단일 train/test 평가만으로는 실전 투입 불가 — 레짐 변화 취약성 검출 못 함.
- 본격 학습은 **앙상블**(`agent.ensemble.train_ensemble`)을 기본 경로로. 단일 시드 PPO는 시드 운에 결과가 요동치므로 최종 모델 선택은 항상 다중 시드 최빈값 투표.
- 지표 리포트에는 Sharpe만이 아니라 **Sortino · Calmar · Profit Factor · Win Rate · Avg W/L**를 함께 기록.
- 멀티 TF로 샘플 밀도가 바뀌면 `BASE_INTERVAL` 기반 연환산 상수(`ANNUALIZATION_BY_INTERVAL`)가 자동 적용되는지 확인.

### 6. 피처 컬럼 일관성
- `FEATURE_COLS`를 import로 하드코딩하지 말 것 — 멀티 TF에서 피처 개수가 동적으로 변함.
- `add_features_multi_tf`가 반환하는 `feature_cols`를 **TradingEnv · fit_scaler · transform 모두에 동일하게 전달**. 어긋나면 관측 shape · 스케일 불일치.

### 7. API 키는 `.env`로만 관리
- `UPBIT_ACCESS_KEY`, `UPBIT_SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`는 `.env`에서 읽기.
- `.env`는 절대 커밋 금지. `.env.example`에 키 이름만 적어둘 것.

## 파일 구조 규약

```
please_coin/
├── config.py              # 리스크/모드 상수. 매직넘버 중앙화.
├── data/
│   ├── collector.py       # 업비트 OHLCV 수집 (pyupbit, 멀티 TF)
│   ├── preprocessor.py    # 기술적 지표 + 멀티 TF 병합 (add_features_multi_tf)
│   └── normalizer.py      # RobustScaler fit/transform (train 구간 only)
├── env/
│   └── trading_env.py     # gymnasium.Env, 변동성 사이징 내장
├── agent/
│   ├── train.py           # 단일 시드 RecurrentPPO 학습
│   ├── ensemble.py        # 다중 시드 앙상블 학습·추론 (EnsemblePolicy)
│   ├── walk_forward.py    # K-fold 롤링 Walk-Forward 검증
│   ├── backtest.py        # 백테스트 + 확장 지표 (Sortino/Calmar/PF/Win Rate)
│   └── live_trader.py     # paper/live 실행
├── db/
│   ├── supabase_client.py # 매매 로그 저장
│   └── slack_notifier.py  # 리스크 이벤트 Slack 알림 (Webhook, Null fallback)
├── dashboard/             # React + TS + Recharts
└── main.py                # 엔트리포인트 (collect/train/train-ensemble/walkforward/backtest/live)
```

신규 파일은 위 구조에 맞게 배치. 새 최상위 디렉토리 추가는 먼저 제안 후 합의.

## 개발 원칙
- **YAGNI**: 설계 문서에 없는 기능은 미리 만들지 않는다.
- **주석 최소화**: 이름으로 의도가 드러나면 주석 불필요. 예외는 비직관적 수식(보상함수, 지표 계산)의 "왜".
- **테스트 가능성**: 환경/에이전트/브로커는 의존성 주입 형태로 작성 — `TradingEnv(data_source=...)` 식.

## 하이퍼파라미터 관리
- 학습 하이퍼파라미터는 `agent/train.py` 상단 `HP_*` 상수로. 향후 YAML 분리 가능성 염두.
- 모델 체크포인트는 `models/` 디렉토리 (gitignore). 파일명에 `YYYYMMDD_HHMM_<return>_<mdd>.zip` 패턴.

## 배포
- 대시보드만 Vercel 배포. 학습/매매 봇은 로컬/VPS에서 실행 (Fluid Compute의 300s 타임아웃은 학습 워크로드에 부적합).
- Supabase를 경유해 봇 ↔ 대시보드 실시간 연동.
