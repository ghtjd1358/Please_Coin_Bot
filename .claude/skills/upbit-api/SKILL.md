---
name: upbit-api
description: pyupbit를 이용해 업비트 시세 수집, 잔고 조회, 주문 실행을 할 때 사용. 캔들 수집, 수수료 계산, 레이트리밋 회피, 페이징 조회 가이드 포함.
---

# pyupbit 사용 가이드

## 1. 시세 조회 (인증 불필요)

```python
import pyupbit

# 일봉 200개
df = pyupbit.get_ohlcv("KRW-BTC", interval="day", count=200)
# interval: "minute1", "minute3", "minute5", "minute15", "minute30",
#           "minute60", "minute240", "day", "week", "month"

# 특정 시점 이전 캔들 (페이징)
df = pyupbit.get_ohlcv("KRW-BTC", interval="minute60",
                        to="2024-01-01 00:00:00", count=200)

# 현재가
price = pyupbit.get_current_price("KRW-BTC")
```

**반환 컬럼**: `open, high, low, close, volume, value` (index는 pandas DatetimeIndex).

## 2. 레이트리밋
업비트 공개 API는 초당 10회 / 분당 600회 수준. 대량 수집 시:
- 200개씩 끊어 불러오되 `time.sleep(0.1)` 이상 간격을 둘 것.
- 실패 시 지수 백오프 재시도.

## 3. 인증 (주문/잔고)

```python
import pyupbit, os
from dotenv import load_dotenv
load_dotenv()

upbit = pyupbit.Upbit(os.getenv("UPBIT_ACCESS_KEY"),
                       os.getenv("UPBIT_SECRET_KEY"))

balance_krw = upbit.get_balance("KRW")
balance_btc = upbit.get_balance("KRW-BTC")

# 시장가 매수 (원화 금액 지정)
upbit.buy_market_order("KRW-BTC", 10_000)
# 시장가 매도 (코인 수량 지정)
upbit.sell_market_order("KRW-BTC", 0.001)
```

## 4. 수수료
- 업비트 원화마켓 수수료: **0.05%** (양방향)
- 백테스트/보상함수에는 0.0005 상수로 반영.

## 5. 주의사항
- 최소 주문금액: **5,000원**. 그 미만이면 주문이 실패한다 → `coin_held * price < 5000` 매도 차단 로직 필요.
- `get_ohlcv`는 UTC가 아니라 KST(Asia/Seoul) 기준. 시계열 결합 시 통일 필요.
- `to` 파라미터는 해당 시각 **이전** 데이터를 반환. 경계 중복에 주의.
