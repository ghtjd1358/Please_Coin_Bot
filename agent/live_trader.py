"""실시간 paper/live 트레이더.

흐름 (매 tick):
  1) 최근 N개 OHLCV (base + context) 조회
  2) add_features_multi_tf → transform(scaler) → 관측 윈도우 (W, F) 추출
  3) 포트폴리오 상태 + 관측을 모델에 입력 → action
  4) paper : 가상 잔고 시뮬레이션
     live  : pyupbit 실거래 (UPBIT_ACCESS_KEY/SECRET_KEY 필요)
  5) Supabase에 snapshot + trade + agent_log 기록
  6) 리스크 게이트 체크 → 필요 시 pause / shutdown

# DO NOT HARD-CODE TRADE_MODE to "live" — 반드시 .env 또는 명시적 인자로만.
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from config import (
    TRADE_MODE, TRADE_SYMBOL,
    INITIAL_BALANCE,
    UPBIT_FEE_RATE, UPBIT_MIN_ORDER_KRW,
    MAX_BUY_RATIO, MIN_BUY_RATIO, MAX_LOSS_RATE, MAX_CONSECUTIVE_LOSS,
    VOL_SIZING_WINDOW, VOL_SIZING_BASELINE, VOL_SCALE_FLOOR, VOL_SCALE_CEIL,
    BASE_INTERVAL, CONTEXT_INTERVALS, OBS_WINDOW,
    LIVE_BASE_CANDLE_LOOKBACK, LIVE_CONTEXT_CANDLE_LOOKBACK,
    LIVE_MODE_COUNTDOWN_SEC,
    UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY,
)
from data.collector import fetch_ohlcv
from data.normalizer import load as load_scaler
from data.preprocessor import add_features_multi_tf
from db.slack_notifier import build_notifier
from db.supabase_client import build_logger


ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

ACTION_HOLD, ACTION_BUY, ACTION_SELL = 0, 1, 2


# ─── 로깅 ─────────────────────────────────────────────
def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("live_trader")
    if logger.handlers:  # idempotent (재실행/테스트 대비)
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    fh = RotatingFileHandler(
        LOGS_DIR / "trader.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


log = _setup_logging()


# ─── 리스크 게이트 ─────────────────────────────────────
class LossStreakGuard:
    """연속 손실 카운터. `MAX_CONSECUTIVE_LOSS` 초과 시 paused=True."""

    def __init__(self, max_streak: int = MAX_CONSECUTIVE_LOSS):
        self.max_streak = max_streak
        self.streak = 0
        self.paused = False

    def record(self, trade_pnl: float) -> None:
        if trade_pnl < 0:
            self.streak += 1
            if self.streak >= self.max_streak:
                self.paused = True
        else:
            self.streak = 0

    def resume(self) -> None:
        self.streak = 0
        self.paused = False


# ─── 포지션 상태 ───────────────────────────────────────
class Position:
    """메모리 상 포트폴리오 상태. Supabase 스냅샷과 이중 소스 of truth.

    `apply_buy` / `apply_sell`는 수수료 차감 후 잔액을 반영. 에이전트 거래 결정이
    `_buy_ratio()` 통해 변동성 기반으로 자동 축소되므로 여기서는 비율만 받는다.
    """

    def __init__(self, initial_balance: float):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.coin_held = 0.0
        self.avg_buy_price = 0.0
        self._entry_value: Optional[float] = None  # 포지션 진입 시점 평가액 (PnL 계산용)

    def portfolio_value(self, price: float) -> float:
        return self.balance + self.coin_held * price

    def unrealized_pnl(self, price: float) -> float:
        if self.coin_held == 0 or self.avg_buy_price == 0:
            return 0.0
        return (price - self.avg_buy_price) / self.avg_buy_price

    def apply_buy(self, price: float, buy_ratio: float) -> dict:
        spend = self.balance * buy_ratio
        if spend < UPBIT_MIN_ORDER_KRW:
            return {"executed": False, "reason": "below_min_order"}
        qty = spend * (1 - UPBIT_FEE_RATE) / price
        fee = spend * UPBIT_FEE_RATE
        new_cost = self.avg_buy_price * self.coin_held + spend
        self.coin_held += qty
        self.avg_buy_price = new_cost / self.coin_held if self.coin_held else 0.0
        self.balance -= spend
        if self._entry_value is None:
            self._entry_value = self.portfolio_value(price)
        return {
            "executed": True, "price": price, "amount": qty, "fee": fee,
            "balance": self.balance, "coin_held": self.coin_held,
        }

    def apply_sell(self, price: float, reason: str = "sell") -> dict:
        if self.coin_held == 0:
            return {"executed": False, "reason": "no_position"}
        gross = self.coin_held * price
        if gross < UPBIT_MIN_ORDER_KRW:
            return {"executed": False, "reason": "below_min_order"}
        fee = gross * UPBIT_FEE_RATE
        amount = self.coin_held
        self.balance += gross * (1 - UPBIT_FEE_RATE)
        self.coin_held = 0.0
        self.avg_buy_price = 0.0
        # PnL = 이번 청산 후 평가액 - 진입 시점 평가액
        pnl = None
        if self._entry_value is not None:
            pnl = self.portfolio_value(price) - self._entry_value
            self._entry_value = None
        return {
            "executed": True, "price": price, "amount": amount, "fee": fee,
            "balance": self.balance, "coin_held": 0.0, "pnl": pnl,
            "reason": reason,
        }


# ─── 변동성 기반 buy_ratio (env와 동일 로직) ────────────
def compute_buy_ratio(log_returns: np.ndarray) -> float:
    if len(log_returns) < max(VOL_SIZING_WINDOW, 2):
        return MAX_BUY_RATIO
    recent = log_returns[-VOL_SIZING_WINDOW:]
    current_vol = float(recent.std(ddof=0)) if len(recent) > 1 else 0.0
    baseline_slice = log_returns[-VOL_SIZING_BASELINE:]
    baseline_vol = float(baseline_slice.std(ddof=0)) if len(baseline_slice) > 1 else 0.0
    if current_vol <= 1e-12 or baseline_vol <= 1e-12:
        return MAX_BUY_RATIO
    scale = float(np.clip(baseline_vol / current_vol, VOL_SCALE_FLOOR, VOL_SCALE_CEIL))
    return max(MAX_BUY_RATIO * scale, MIN_BUY_RATIO)


# ─── 실시간 피처 파이프라인 ─────────────────────────────
class LiveFeaturePipeline:
    """매 tick마다 pyupbit에서 캔들 → 피처 병합 → 정규화 → 최근 윈도우 반환.

    학습 때와 **완전히 같은** 컬럼·순서를 보장하기 위해
    `scaler.feature_names_in_`을 이 파이프라인의 `feature_cols`로 사용.
    """

    def __init__(
        self,
        symbol: str,
        scaler_name: str,
        base_interval: str = BASE_INTERVAL,
        context_intervals: list[str] | None = None,
        base_lookback: int = LIVE_BASE_CANDLE_LOOKBACK,
        context_lookback: int = LIVE_CONTEXT_CANDLE_LOOKBACK,
    ):
        self.symbol = symbol
        self.base_interval = base_interval
        self.context_intervals = list(context_intervals or CONTEXT_INTERVALS)
        self.base_lookback = base_lookback
        self.context_lookback = context_lookback

        self.scaler = load_scaler(scaler_name)
        if not hasattr(self.scaler, "feature_names_in_"):
            raise RuntimeError(
                f"scaler '{scaler_name}'에 feature_names_in_ 없음 — "
                "학습 파이프라인(fit_scaler)로 다시 저장할 것."
            )
        self.feature_cols: list[str] = list(self.scaler.feature_names_in_)

    def fetch(self) -> tuple[pd.DataFrame, np.ndarray, float]:
        """반환:
          feat_scaled : 정규화 완료된 (N, 1+F) DataFrame — close + feature_cols
          log_returns : 베이스 캔들의 log_ret_1 시계열 (buy_ratio 계산용)
          current_price: 가장 최근 종가 (실행가 근사)
        """
        base_raw = fetch_ohlcv(self.symbol, self.base_interval, self.base_lookback)
        context = {
            itv: fetch_ohlcv(self.symbol, itv, self.context_lookback)
            for itv in self.context_intervals
        }

        feat, cols_from_pipeline = add_features_multi_tf(
            base_raw, context=context, base_interval=self.base_interval,
        )
        # 학습 때와 컬럼/순서 완전 일치 검증 — look-ahead가 아니라 shape 일치 문제 방지.
        if cols_from_pipeline != self.feature_cols:
            missing = set(self.feature_cols) - set(cols_from_pipeline)
            extra = set(cols_from_pipeline) - set(self.feature_cols)
            raise RuntimeError(
                "실시간 피처 컬럼이 학습 때와 불일치. "
                f"missing={missing}, extra={extra}. "
                "BASE_INTERVAL / CONTEXT_INTERVALS / 지표 설정을 학습 때와 맞출 것."
            )

        from data.normalizer import transform as _tr
        feat_scaled = _tr(feat, self.scaler, feature_cols=self.feature_cols)

        log_close = np.log(np.clip(base_raw["close"].to_numpy(dtype=np.float64), 1e-9, None))
        log_returns = np.diff(log_close, prepend=log_close[0])

        current_price = float(base_raw["close"].iloc[-1])
        return feat_scaled, log_returns, current_price

    def build_observation(self, feat_scaled: pd.DataFrame, position: Position, price: float) -> np.ndarray:
        """학습 때 TradingEnv._obs와 동일한 구조로 관측 벡터 구성."""
        if len(feat_scaled) < OBS_WINDOW:
            raise RuntimeError(
                f"피처 샘플 부족: got={len(feat_scaled)} < OBS_WINDOW={OBS_WINDOW}. "
                f"LIVE_BASE_CANDLE_LOOKBACK 을 늘릴 것."
            )
        window = feat_scaled[self.feature_cols].to_numpy(dtype=np.float32)[-OBS_WINDOW:]

        unrealized = position.unrealized_pnl(price)
        portfolio = np.array([
            position.balance / position.initial_balance,
            position.coin_held * price / position.initial_balance,
            position.avg_buy_price / price if position.avg_buy_price else 0.0,
            unrealized,
        ], dtype=np.float32)

        return np.concatenate([window.flatten(), portfolio])


# ─── 모델 predictor (단일/앙상블 통일) ──────────────────
def _make_predictor(model_path: Optional[Path], ensemble_dir: Optional[Path]):
    """backtest._make_predictor와 시그니처 동일. 앙상블이면 state는 list."""
    from sb3_contrib import RecurrentPPO

    if ensemble_dir is not None:
        from agent.ensemble import EnsemblePolicy
        policy = EnsemblePolicy.from_dir(ensemble_dir)
        return policy.predict, policy.initial_state()

    model = RecurrentPPO.load(model_path)

    def _single_predict(obs, state, episode_start):
        action, new_state = model.predict(
            obs, state=state, episode_start=episode_start, deterministic=True,
        )
        return action, new_state

    return _single_predict, None


# ─── 업비트 실거래 브로커 ──────────────────────────────
class PaperBroker:
    """가상 매매 — Position에 직접 반영."""

    def __init__(self, position: Position):
        self.position = position

    def buy(self, price: float, buy_ratio: float) -> dict:
        return self.position.apply_buy(price, buy_ratio)

    def sell_all(self, price: float, reason: str = "sell") -> dict:
        return self.position.apply_sell(price, reason=reason)


class LiveBroker:
    """실계좌. UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY 필수.

    주의: 여기에서도 Position은 유지되며 정산은 Upbit 체결가 기준으로 업데이트.
    외부 계좌 잔액과 drift가 나면 매 tick 시작에 동기화(TODO).
    """

    def __init__(self, position: Position, symbol: str):
        import pyupbit
        if not UPBIT_ACCESS_KEY or not UPBIT_SECRET_KEY:
            raise RuntimeError("live 모드인데 UPBIT_ACCESS_KEY/SECRET_KEY가 비어있음")
        self.upbit = pyupbit.Upbit(UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY)
        self.position = position
        self.symbol = symbol

    def buy(self, price: float, buy_ratio: float) -> dict:
        spend = self.position.balance * buy_ratio
        if spend < UPBIT_MIN_ORDER_KRW:
            return {"executed": False, "reason": "below_min_order"}
        try:
            self.upbit.buy_market_order(self.symbol, spend)
        except Exception as e:
            log.warning("live buy 실패: %s", e)
            return {"executed": False, "reason": f"api_error: {e}"}
        return self.position.apply_buy(price, buy_ratio)

    def sell_all(self, price: float, reason: str = "sell") -> dict:
        if self.position.coin_held == 0:
            return {"executed": False, "reason": "no_position"}
        try:
            self.upbit.sell_market_order(self.symbol, self.position.coin_held)
        except Exception as e:
            log.warning("live sell 실패: %s", e)
            return {"executed": False, "reason": f"api_error: {e}"}
        return self.position.apply_sell(price, reason=reason)


# ─── 메인 트레이더 ─────────────────────────────────────
class LiveTrader:
    def __init__(
        self,
        model_path: Optional[Path],
        ensemble_dir: Optional[Path],
        scaler_name: str,
        symbol: str = TRADE_SYMBOL,
        mode: str = TRADE_MODE,
    ):
        self.symbol = symbol
        self.mode = mode
        assert mode in ("paper", "live"), f"invalid mode: {mode}"

        self.pipeline = LiveFeaturePipeline(symbol, scaler_name)
        self.predict, self.lstm_states = _make_predictor(model_path, ensemble_dir)
        self.episode_start = np.ones((1,), dtype=bool)

        # Supabase 로거 (NoOp fallback 포함)
        self.logger = build_logger(mode=mode)
        # Slack 알림기 (webhook 미설정이면 NullNotifier)
        self.notifier = build_notifier()

        # 포지션 복원: 최근 스냅샷이 있으면 그걸 초기값으로.
        self.position = self._restore_position_or_init()

        # 리스크 게이트
        self.loss_guard = LossStreakGuard()
        # 누적 손실 기준값은 "시작 자본". 복원한 포지션이더라도 기준은 항상 INITIAL_BALANCE.
        self.initial_value = float(INITIAL_BALANCE)
        # 차단 후 재시도 방지용 플래그
        self._shutdown_requested = False

        self.broker = (
            LiveBroker(self.position, symbol) if mode == "live" else PaperBroker(self.position)
        )

    def _restore_position_or_init(self) -> Position:
        snap = self.logger.get_latest_snapshot(self.symbol) if self.logger.enabled else None
        if snap and snap.get("mode") == self.mode:
            p = Position(initial_balance=INITIAL_BALANCE)
            p.balance = float(snap.get("balance", INITIAL_BALANCE))
            p.coin_held = float(snap.get("coin_held", 0.0))
            p.avg_buy_price = float(snap.get("avg_buy_price") or 0.0)
            log.info("포지션 복원: balance=%.0f coin=%.6f avg=%.0f",
                     p.balance, p.coin_held, p.avg_buy_price)
            return p
        return Position(initial_balance=INITIAL_BALANCE)

    # ─────────────── tick ───────────────
    def tick(self) -> None:
        if self._shutdown_requested:
            return

        try:
            feat_scaled, log_returns, price = self.pipeline.fetch()
        except Exception as e:
            log.warning("tick fetch 실패 — 스킵: %s", e)
            return

        obs = self.pipeline.build_observation(feat_scaled, self.position, price)

        action_arr, self.lstm_states = self.predict(
            obs, self.lstm_states, self.episode_start,
        )
        self.episode_start = np.zeros((1,), dtype=bool)
        action = int(np.asarray(action_arr).reshape(-1)[0])

        # 1) 강제 손절이 에이전트 행동보다 우선
        forced_result = self._check_forced_stop_loss(price)

        # 2) 에이전트 행동 집행 (강제 손절이 나갔으면 에이전트 행동은 무시)
        if forced_result is not None:
            result = forced_result
            action_name = "stop_loss"
        elif action == ACTION_BUY:
            buy_ratio = compute_buy_ratio(log_returns)
            result = self.broker.buy(price, buy_ratio)
            action_name = "buy"
        elif action == ACTION_SELL:
            result = self.broker.sell_all(price, reason="sell")
            action_name = "sell"
        else:
            result = {"executed": False, "reason": "hold"}
            action_name = "hold"

        # 3) 기록
        self._persist_tick(action, action_name, price, result, obs)

        # 4) 리스크 게이트 — 사이클 후 평가
        self._post_tick_risk_check(price, result)

    def _check_forced_stop_loss(self, price: float) -> Optional[dict]:
        """손절 조건 충족 시 broker를 통해 청산하고 trade payload dict를 반환."""
        if self.position.coin_held == 0 or self.position.avg_buy_price == 0:
            return None
        loss = (price - self.position.avg_buy_price) / self.position.avg_buy_price
        if loss <= -MAX_LOSS_RATE:
            log.warning("강제 손절 발동: price=%.0f avg=%.0f loss=%.2f%%",
                        price, self.position.avg_buy_price, loss * 100)
            return self.broker.sell_all(price, reason="stop_loss")
        return None

    def _persist_tick(self, action: int, action_name: str, price: float, result: dict, obs: np.ndarray):
        pv = self.position.portfolio_value(price)
        unrealized = self.position.unrealized_pnl(price)

        # snapshot은 매 tick
        self.logger.insert_snapshot(
            symbol=self.symbol,
            total_value=pv,
            balance=self.position.balance,
            coin_held=self.position.coin_held,
            avg_buy_price=self.position.avg_buy_price,
            unrealized_pnl=unrealized,
            current_price=price,
        )

        # trade는 실제 체결/손절 발생 시
        if result.get("executed"):
            pnl = result.get("pnl")
            self.logger.insert_trade(
                symbol=self.symbol,
                action=action_name,
                price=result.get("price", price),
                amount=result.get("amount", 0.0),
                fee=result.get("fee", 0.0),
                balance_after=self.position.balance,
                coin_held_after=self.position.coin_held,
                pnl=pnl,
                note=result.get("reason", ""),
            )
            trade_json = json.dumps({
                "action": action_name, "price": price,
                "amount": result.get("amount", 0.0),
                "pnl": pnl, "reason": result.get("reason"),
                "pv": pv,
            }, default=str)
            log.info("TRADE %s", trade_json)

            # Slack: 매매 체결 알림 (hold는 executed=False라 여긴 안 들어옴)
            trade_fields = {
                "symbol": self.symbol,
                "action": action_name,
                "price": float(result.get("price", price)),
                "amount": float(result.get("amount", 0.0)),
                "portfolio_value": pv,
                "mode": self.mode,
            }
            if pnl is not None:
                trade_fields["pnl"] = float(pnl)
            self.notifier.trade(f"체결: {action_name} · {self.symbol}", fields=trade_fields)
        else:
            log.info(
                "tick mode=%s action=%s price=%.0f pv=%.0f cash=%.0f coin=%.6f unreal=%.2f%%",
                self.mode, action_name, price, pv, self.position.balance,
                self.position.coin_held, unrealized * 100,
            )

        # agent_log — 관측은 요약만 (첫 4 피처 + 포트폴리오 4)
        obs_summary = {
            "first_features": obs[:4].astype(float).round(4).tolist(),
            "portfolio_tail": obs[-4:].astype(float).round(4).tolist(),
            "price": price,
        }
        self.logger.insert_agent_log(
            symbol=self.symbol,
            obs_summary=obs_summary,
            action=action,
        )

    def _post_tick_risk_check(self, price: float, result: dict):
        # 연속 손실 카운트
        pnl = result.get("pnl") if result.get("executed") else None
        if pnl is not None:
            was_paused = self.loss_guard.paused
            self.loss_guard.record(pnl)
            # paused로 막 전환된 시점에만 알림 — 같은 상태 반복 알림 금지
            if self.loss_guard.paused and not was_paused:
                log.warning(
                    "연속 손실 %d회 초과 — 스케줄러 일시정지.",
                    self.loss_guard.streak,
                )
                if self._scheduler is not None:
                    self._scheduler.pause()
                self.notifier.warn(
                    f"연속 손실 한계 도달 — 트레이더 일시정지 ({self.symbol})",
                    fields={
                        "streak": self.loss_guard.streak,
                        "max_streak": self.loss_guard.max_streak,
                        "mode": self.mode,
                        "action": "scheduler.pause() — 수동 재개 필요",
                    },
                )

        # 누적 손실 체크
        pv = self.position.portfolio_value(price)
        cum_loss = 1.0 - pv / max(self.initial_value, 1e-9)
        if cum_loss >= MAX_LOSS_RATE:
            log.error(
                "누적 손실 %.2f%% ≥ %.0f%% — 전량 매도 후 종료.",
                cum_loss * 100, MAX_LOSS_RATE * 100,
            )
            cum_result = self.broker.sell_all(price, reason="stop_loss")
            # trade 한 건 추가 기록 (강제 청산)
            self.logger.insert_trade(
                symbol=self.symbol,
                action="stop_loss",
                price=price,
                amount=cum_result.get("amount", 0.0),
                fee=cum_result.get("fee", 0.0),
                balance_after=self.position.balance,
                coin_held_after=self.position.coin_held,
                pnl=cum_result.get("pnl"),
                note="cumulative_stop",
            )
            self._shutdown_requested = True
            if self._scheduler is not None:
                self._scheduler.shutdown(wait=False)
            self.notifier.critical(
                f"누적 손실 한계 초과 — 트레이더 종료 ({self.symbol})",
                fields={
                    "cum_loss": f"{cum_loss * 100:.2f}%",
                    "threshold": f"{MAX_LOSS_RATE * 100:.0f}%",
                    "final_value": pv,
                    "initial_value": self.initial_value,
                    "mode": self.mode,
                },
            )

    # ─────────────── scheduler 실행 ───────────────
    _scheduler = None  # type: ignore[assignment]

    def run(self) -> None:
        from apscheduler.schedulers.blocking import BlockingScheduler

        trigger = self._cron_for_interval(BASE_INTERVAL)
        scheduler = BlockingScheduler()
        scheduler.add_job(self.tick, trigger, id="trader-tick", max_instances=1, coalesce=True)
        self._scheduler = scheduler

        # 기동 알림 (Slack)
        startup_level = "critical" if self.mode == "live" else "info"
        self.notifier.send(
            f"트레이더 기동 · {self.symbol}",
            level=startup_level,
            fields={
                "mode": self.mode,
                "base_interval": BASE_INTERVAL,
                "balance": self.position.balance,
                "coin_held": self.position.coin_held,
            },
        )

        # 기동 즉시 1회 실행 → 이후 cron 스케줄
        log.info("=== first tick (startup) ===")
        try:
            self.tick()
        except Exception as e:
            log.exception("startup tick 실패: %s", e)
            self.notifier.warn(
                f"startup tick 실패 — 다음 tick에서 재시도 ({self.symbol})",
                fields={"error": str(e), "mode": self.mode},
            )

        def _graceful(signum, frame):
            log.info("signal=%s — graceful shutdown", signum)
            try:
                scheduler.shutdown(wait=False)
            except Exception:
                pass
            # 마지막 snapshot 저장
            try:
                price = float(fetch_ohlcv(self.symbol, BASE_INTERVAL, 1)["close"].iloc[-1])
            except Exception:
                price = 0.0
            pv = self.position.portfolio_value(price)
            self.logger.insert_snapshot(
                symbol=self.symbol, total_value=pv,
                balance=self.position.balance, coin_held=self.position.coin_held,
                avg_buy_price=self.position.avg_buy_price,
                unrealized_pnl=self.position.unrealized_pnl(price),
                current_price=price,
            )
            sys.exit(0)

        signal.signal(signal.SIGINT, _graceful)
        # SIGTERM은 Windows에선 제한적이지만 걸어두면 VPS에서 유용.
        try:
            signal.signal(signal.SIGTERM, _graceful)
        except Exception:
            pass

        log.info("scheduler 시작 — trigger=%s", trigger)
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            _graceful("KB", None)

    @staticmethod
    def _cron_for_interval(interval: str) -> "object":
        """BASE_INTERVAL에 맞춘 CronTrigger. minute60이면 매시 정각."""
        from apscheduler.triggers.cron import CronTrigger

        m = {
            "minute1":  CronTrigger(second=5),
            "minute3":  CronTrigger(minute="*/3",  second=5),
            "minute5":  CronTrigger(minute="*/5",  second=5),
            "minute10": CronTrigger(minute="*/10", second=5),
            "minute15": CronTrigger(minute="*/15", second=5),
            "minute30": CronTrigger(minute="*/30", second=5),
            "minute60": CronTrigger(minute=0,      second=5),
            "minute240":CronTrigger(hour="*/4",    minute=0, second=5),
            "day":      CronTrigger(hour=0, minute=5),
        }
        if interval not in m:
            log.warning("알 수 없는 BASE_INTERVAL=%s — 1시간마다 fallback", interval)
            return CronTrigger(minute=0, second=5)
        return m[interval]


# ─── CLI ───────────────────────────────────────────────
def _warn_live_banner():
    if TRADE_MODE != "live":
        return
    banner = (
        "\n"
        "============================================================\n"
        "  ⚠  LIVE MODE  ⚠   실계좌에서 주문이 집행됩니다.\n"
        f"    SYMBOL = {TRADE_SYMBOL}\n"
        f"    UPBIT_ACCESS_KEY set = {bool(UPBIT_ACCESS_KEY)}\n"
        "============================================================\n"
    )
    print(banner)
    for i in range(LIVE_MODE_COUNTDOWN_SEC, 0, -1):
        print(f"  기동까지 {i}초... (Ctrl+C로 취소)")
        time.sleep(1)


def _parse_args(argv: list[str] | None = None):
    p = argparse.ArgumentParser(prog="live_trader")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--model", type=Path, help="단일 모델 .zip 경로")
    grp.add_argument("--ensemble", type=Path, help="앙상블 디렉토리 (seed_*.zip)")
    p.add_argument("--scaler", required=True, help="학습 때 저장된 scaler 이름")
    p.add_argument(
        "--once", action="store_true",
        help="스모크 테스트: 스케줄러 없이 1 tick만 실행하고 종료. "
             "학습·Supabase·Slack·실시간 피처 전 구간을 한 번에 검증.",
    )
    return p.parse_args(argv)


def main():
    args = _parse_args()
    log.info("TRADE_MODE=%s SYMBOL=%s BASE_INTERVAL=%s", TRADE_MODE, TRADE_SYMBOL, BASE_INTERVAL)
    _warn_live_banner()

    trader = LiveTrader(
        model_path=args.model,
        ensemble_dir=args.ensemble,
        scaler_name=args.scaler,
        symbol=TRADE_SYMBOL,
        mode=TRADE_MODE,
    )
    if args.once:
        log.info("=== --once smoke test: single tick, no scheduler ===")
        trader.notifier.info(
            f"스모크 테스트 시작 · {TRADE_SYMBOL}",
            fields={"mode": TRADE_MODE, "base_interval": BASE_INTERVAL, "kind": "--once"},
        )
        trader.tick()
        log.info("=== --once complete. 봇 정상 종료 ===")
        return
    trader.run()


if __name__ == "__main__":
    main()
