---
name: risk-guard
description: 자동매매 리스크 방어 로직 작성 시 사용. 손절, 1회 매수 상한, 연속 손실 중지, paper/live 스위치 구현 가이드.
---

# 리스크 방어 코드 패턴

모든 상수는 `config.py` 중앙 관리. 하드코딩 금지.

## 1. 손절(stop-loss)

```python
def should_stop_loss(avg_buy_price, current_price, max_loss_rate):
    if avg_buy_price == 0:
        return False
    loss_rate = (current_price - avg_buy_price) / avg_buy_price
    return loss_rate <= -max_loss_rate
```

`step()` 맨 앞에서 검사 — 에이전트 행동보다 먼저 강제 매도.

## 2. 1회 매수 상한

```python
buy_amount = min(balance * MAX_BUY_RATIO, balance - 5000)  # 최소주문금액 여유
```

## 3. 연속 손실 카운터

```python
class LossStreakGuard:
    def __init__(self, max_streak):
        self.max_streak = max_streak
        self.streak = 0
        self.paused = False

    def record(self, trade_pnl):
        if trade_pnl < 0:
            self.streak += 1
            if self.streak >= self.max_streak:
                self.paused = True
        else:
            self.streak = 0

    def resume(self):
        self.streak = 0
        self.paused = False
```

일시정지는 운영자가 명시적으로 resume 해야 풀린다.

## 4. paper / live 스위치

```python
# config.py
import os
TRADE_MODE = os.getenv("TRADE_MODE", "paper")
assert TRADE_MODE in ("paper", "live")

# live_trader.py 상단
if TRADE_MODE == "live":
    print("=" * 60)
    print("⚠️  LIVE MODE — 실계좌 매매가 집행됩니다")
    print("=" * 60)
    input("Enter로 계속: ")
```

## 5. 감사 로그
모든 매매 시도(성공/실패/차단)는 Supabase에 기록. 실패도 남겨야 사후 분석 가능.
