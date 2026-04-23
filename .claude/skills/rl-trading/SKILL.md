---
name: rl-trading
description: gymnasium 환경 정의와 stable-baselines3 PPO 학습/평가 시 사용. 상태 정규화, 보상함수 설계, check_env 검증, 벡터 환경, 체크포인트 관리 가이드.
---

# 강화학습 트레이딩 환경 & PPO 학습

## 1. gymnasium 환경 필수 요소

```python
import gymnasium as gym
from gymnasium import spaces
import numpy as np

class TradingEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, df, window_size=20, initial_balance=1_000_000):
        super().__init__()
        self.df = df.reset_index(drop=True)
        self.window_size = window_size
        self.initial_balance = initial_balance

        # 행동: 0=홀드, 1=매수, 2=매도
        self.action_space = spaces.Discrete(3)

        # 관측: 윈도우 시세(N*4) + 지표(5) + 포트폴리오(4)
        obs_dim = window_size * 4 + 5 + 4
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32
        )

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.t = self.window_size
        self.balance = self.initial_balance
        self.coin_held = 0.0
        self.avg_buy_price = 0.0
        return self._obs(), {}

    def step(self, action):
        prev_portfolio = self._portfolio_value()
        self._apply_action(action)
        self.t += 1
        curr_portfolio = self._portfolio_value()

        reward = (curr_portfolio - prev_portfolio) / prev_portfolio
        if action != 0:
            reward -= 0.0005  # 수수료 패널티

        terminated = self.t >= len(self.df) - 1
        truncated = False
        return self._obs(), reward, terminated, truncated, {
            "portfolio": curr_portfolio
        }
```

## 2. 환경 검증

```python
from stable_baselines3.common.env_checker import check_env
check_env(TradingEnv(df))  # 통과하지 못하면 SB3 학습 불가
```

## 3. 관측 정규화
가격대가 천 단위~억 단위로 크면 학습이 불안정. 윈도우 내 mean/std로 **런타임에 정규화**하거나, 사전에 `VecNormalize`를 씌운다.

```python
from stable_baselines3.common.vec_env import VecNormalize, DummyVecEnv
env = DummyVecEnv([lambda: TradingEnv(df)])
env = VecNormalize(env, norm_obs=True, norm_reward=False)
```

`norm_reward=False` — 보상을 정규화하면 수익률 해석이 뒤틀린다.

## 4. PPO 학습

```python
from stable_baselines3 import PPO

model = PPO(
    "MlpPolicy", env,
    learning_rate=3e-4,
    n_steps=2048,
    batch_size=64,
    n_epochs=10,
    gamma=0.99,
    gae_lambda=0.95,
    clip_range=0.2,
    verbose=1,
)
model.learn(total_timesteps=500_000)
model.save("models/ppo_btc_20260422.zip")
```

## 5. 평가 지표 (백테스트)
- **수익률**: `(final - initial) / initial`
- **MDD (최대 낙폭)**: 각 시점까지 누적 최고가 대비 현재가의 최대 낙폭
- **샤프 비율**: `mean(returns) / std(returns) * sqrt(252)` — 일간 수익률 기준 연율화

## 6. 흔한 함정
- **Look-ahead 누수**: `t` 시점 관측에 `t+1` 이후 정보가 새지 않는지. `df.iloc[:self.t]`만 접근.
- **보상 스케일링 불일치**: 수수료 패널티가 수익률보다 훨씬 크면 "항상 홀드"로 수렴.
- **탐험 부족**: PPO의 엔트로피 보너스(`ent_coef`)가 0이면 일찍 수렴. 0.01~0.001 사이 권장.
- **데이터 리샘플링**: 학습/검증/테스트 split은 **시간 순**으로 분할 (랜덤 금지).
