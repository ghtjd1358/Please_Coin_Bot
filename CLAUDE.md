# please_coin — Claude 작업 지침

업비트 기반 강화학습(RL) 자동매매 프로젝트. 설계 원본은 `ARCHITECTURE.md` 참조.

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
