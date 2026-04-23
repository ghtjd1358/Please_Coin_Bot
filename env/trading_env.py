"""gymnasium 기반 단일 자산 트레이딩 환경 (DSR 보상 + 정규화 피처 입력).

설계 포인트
────────────
1. 관측 = [정규화된 피처 윈도우] + [포트폴리오 상태 4개]
   · 피처는 외부(normalizer)에서 이미 정규화된 상태로 들어옴
   · 윈도우는 시퀀스 그대로 LSTM 정책에 입력 가능한 형태로 flatten
   · 피처 컬럼은 생성자에서 주입받음 — 멀티 TF로 개수가 달라질 수 있으므로.
2. 행동 = {0:홀드, 1:매수, 2:매도}
3. 보상 = Differential Sharpe Ratio (Moody & Saffell 1998)
   · 단순 수익률이 아니라 "이번 스텝이 전체 샤프비율에 얼마나 기여했나"
   · 지수이동 평균·분산을 온라인으로 추정하며 변동성까지 같이 페널티
4. 리스크 장치:
   · 강제 손절 (config.MAX_LOSS_RATE)
   · 최소 주문금액 미달 시 거래 거부 (업비트 5000원)
   · 변동성 기반 동적 포지션 사이징:
       baseline_vol / current_vol 비율로 MAX_BUY_RATIO를 축소.
       고변동성 구간에서는 매수량을 줄이고, 저변동성에서는 상한까지 허용.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces

from config import (
    INITIAL_BALANCE, OBS_WINDOW,
    UPBIT_FEE_RATE, UPBIT_MIN_ORDER_KRW,
    MAX_BUY_RATIO, MIN_BUY_RATIO, MAX_LOSS_RATE,
    VOL_SIZING_WINDOW, VOL_SIZING_BASELINE,
    VOL_SCALE_FLOOR, VOL_SCALE_CEIL,
)
from data.preprocessor import FEATURE_COLS as DEFAULT_FEATURE_COLS

ACTION_HOLD, ACTION_BUY, ACTION_SELL = 0, 1, 2

# Differential Sharpe EMA 학습률. 작을수록 기억이 길다.
DSR_ETA = 0.04


class TradingEnv(gym.Env):
    """Differential Sharpe Ratio 보상 + 롤링 피처 윈도우 관측."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        df: pd.DataFrame,
        window_size: int = OBS_WINDOW,
        initial_balance: float = INITIAL_BALANCE,
        feature_cols: list[str] | None = None,
    ):
        super().__init__()
        # 피처 컬럼은 외부에서 주입 가능. 멀티 TF에서 컬럼 수가 바뀌므로
        # 하드코딩된 import 상수 대신 데이터와 함께 들어오는 목록을 사용.
        if feature_cols is None:
            feature_cols = list(DEFAULT_FEATURE_COLS)
        self.feature_cols = list(feature_cols)

        self._validate(df, self.feature_cols)
        self.df = df.reset_index(drop=True)
        self.window_size = window_size
        self.initial_balance = float(initial_balance)

        self._close = self.df["close"].to_numpy(dtype=np.float64)
        self._features = self.df[self.feature_cols].to_numpy(dtype=np.float32)
        self._n_features = len(self.feature_cols)

        # 변동성 사이징에 사용할 로그수익률 시계열. close 기준으로 에피소드 전역
        # 한 번만 계산해두고 인덱스로 슬라이싱.
        log_close = np.log(np.clip(self._close, 1e-9, None))
        self._log_ret = np.concatenate([[0.0], np.diff(log_close)])

        self.action_space = spaces.Discrete(3)
        obs_dim = window_size * self._n_features + 4  # +포트폴리오 상태 4
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32,
        )

    # ─────────────── gym API ───────────────
    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.t = self.window_size
        self.balance = self.initial_balance
        self.coin_held = 0.0
        self.avg_buy_price = 0.0
        self._last_portfolio = self._portfolio_value()

        # Differential Sharpe 상태 (1차·2차 모멘트의 EMA)
        self._dsr_A = 0.0
        self._dsr_B = 0.0

        return self._obs(), {}

    def step(self, action: int):
        # 1) 강제 손절이 에이전트 행동보다 먼저
        forced_sl = self._enforce_stop_loss()

        # 2) 에이전트 행동 집행
        prev_value = self._last_portfolio
        executed = self._apply_action(action) or forced_sl

        # 3) 다음 스텝으로 이동
        self.t += 1
        curr_value = self._portfolio_value()
        self._last_portfolio = curr_value

        # 4) 스텝 수익률 (이미 수수료 차감된 포트폴리오 값으로 계산)
        step_return = (curr_value - prev_value) / max(prev_value, 1e-9)

        # 5) 보상 = Differential Sharpe Ratio
        reward = self._differential_sharpe(step_return)

        terminated = self.t >= len(self.df) - 1
        info = {
            "portfolio_value": curr_value,
            "balance": self.balance,
            "coin_held": self.coin_held,
            "avg_buy_price": self.avg_buy_price,
            "executed": executed,
            "step_return": step_return,
            "forced_stop_loss": forced_sl,
        }
        return self._obs(), float(reward), terminated, False, info

    # ─────────────── 내부 로직 ───────────────
    def _current_price(self) -> float:
        return float(self._close[self.t])

    def _portfolio_value(self) -> float:
        return self.balance + self.coin_held * self._current_price()

    def _buy_ratio(self) -> float:
        """변동성 기반 동적 포지션 사이징.

        current_vol  = 최근 VOL_SIZING_WINDOW 스텝의 로그수익률 표준편차
        baseline_vol = 최근 VOL_SIZING_BASELINE 스텝의 로그수익률 표준편차
        scale        = clip(baseline / current, VOL_SCALE_FLOOR, VOL_SCALE_CEIL)
        buy_ratio    = max(MAX_BUY_RATIO * scale, MIN_BUY_RATIO)

        고변동성 = current > baseline → scale < 1 → 매수 비중 축소.
        저변동성 = current < baseline → scale = 1 (상한 clip) → MAX_BUY_RATIO 유지.
        데이터 부족하면 MAX_BUY_RATIO 그대로 (보수적 fallback 아님 — 초기에 매수를 막지 않도록).
        """
        t = self.t
        win = VOL_SIZING_WINDOW
        base = VOL_SIZING_BASELINE

        if t < max(win, 2):
            return MAX_BUY_RATIO

        recent = self._log_ret[max(0, t - win):t]
        current_vol = float(recent.std(ddof=0)) if len(recent) > 1 else 0.0

        base_start = max(0, t - base)
        baseline_slice = self._log_ret[base_start:t]
        baseline_vol = float(baseline_slice.std(ddof=0)) if len(baseline_slice) > 1 else 0.0

        if current_vol <= 1e-12 or baseline_vol <= 1e-12:
            return MAX_BUY_RATIO

        scale = baseline_vol / current_vol
        scale = float(np.clip(scale, VOL_SCALE_FLOOR, VOL_SCALE_CEIL))
        return max(MAX_BUY_RATIO * scale, MIN_BUY_RATIO)

    def _apply_action(self, action: int) -> bool:
        price = self._current_price()

        if action == ACTION_BUY:
            buy_ratio = self._buy_ratio()
            spend = self.balance * buy_ratio
            if spend < UPBIT_MIN_ORDER_KRW:
                return False
            qty = spend * (1 - UPBIT_FEE_RATE) / price
            new_cost = self.avg_buy_price * self.coin_held + spend
            self.coin_held += qty
            self.avg_buy_price = new_cost / self.coin_held if self.coin_held else 0.0
            self.balance -= spend
            return True

        if action == ACTION_SELL:
            if self.coin_held == 0:
                return False
            gross = self.coin_held * price
            if gross < UPBIT_MIN_ORDER_KRW:
                return False
            self.balance += gross * (1 - UPBIT_FEE_RATE)
            self.coin_held = 0.0
            self.avg_buy_price = 0.0
            return True

        return False

    def _enforce_stop_loss(self) -> bool:
        if self.coin_held == 0 or self.avg_buy_price == 0:
            return False
        loss = (self._current_price() - self.avg_buy_price) / self.avg_buy_price
        if loss <= -MAX_LOSS_RATE:
            return self._apply_action(ACTION_SELL)
        return False

    # ─────────── Differential Sharpe Ratio ───────────
    def _differential_sharpe(self, R: float) -> float:
        """Moody & Saffell (1998).
        D_t = (B_{t-1}·ΔA - 0.5·A_{t-1}·ΔB) / (B_{t-1} - A_{t-1}^2)^{3/2}
        분모가 0에 가까우면 raw return으로 fallback.
        """
        A, B = self._dsr_A, self._dsr_B
        delta_A = R - A
        delta_B = R * R - B

        var = B - A * A
        if var > 1e-10:
            D = (B * delta_A - 0.5 * A * delta_B) / (var ** 1.5)
            # 학습 초반 몇 스텝은 극단값이 나올 수 있어 클리핑
            D = float(np.clip(D, -5.0, 5.0))
        else:
            D = R  # 변동성 데이터가 부족한 초반

        # 상태 업데이트
        self._dsr_A = A + DSR_ETA * delta_A
        self._dsr_B = B + DSR_ETA * delta_B
        return D

    # ─────────────── 관측 ───────────────
    def _obs(self) -> np.ndarray:
        window = self._features[self.t - self.window_size : self.t]  # (W, F)

        price_now = self._current_price()
        unrealized = 0.0
        if self.coin_held > 0 and self.avg_buy_price > 0:
            unrealized = (price_now - self.avg_buy_price) / self.avg_buy_price

        portfolio = np.array([
            self.balance / self.initial_balance,                    # 현금 비중
            self.coin_held * price_now / self.initial_balance,      # 코인 평가액 비중
            self.avg_buy_price / price_now if self.avg_buy_price else 0.0,
            unrealized,                                              # 미실현 손익률
        ], dtype=np.float32)

        return np.concatenate([window.flatten(), portfolio])

    # ─────────────── 검증 ───────────────
    @staticmethod
    def _validate(df: pd.DataFrame, feature_cols: list[str]):
        required = {"close", *feature_cols}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"df missing columns: {missing}")
        if df[list(required)].isna().any().any():
            raise ValueError("df contains NaN — run add_features/normalize first")
