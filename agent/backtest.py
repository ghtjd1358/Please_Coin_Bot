"""학습된 RecurrentPPO 모델(또는 앙상블)을 val/test 구간에서 평가.

단일 모델:
  python -m agent.backtest --model models/ppo_KRW-BTC_YYYYMMDD_HHMM.zip \
                           --scaler KRW-BTC_YYYYMMDD_HHMM \
                           --split val

앙상블 (디렉토리에 seed_*.zip 들이 들어 있을 때):
  python -m agent.backtest --ensemble models/ensemble_YYYYMMDD_HHMM/ \
                           --scaler KRW-BTC_YYYYMMDD_HHMM \
                           --split test

확장 지표: Sortino, Calmar, Profit Factor, Win Rate, Avg Win/Loss Ratio.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    INITIAL_BALANCE, TRADE_SYMBOL,
    BASE_INTERVAL, BASE_COUNT,
    CONTEXT_INTERVALS, CONTEXT_COUNT,
)
from data.collector import load_or_fetch_multi_tf
from data.normalizer import load as load_scaler, transform
from data.preprocessor import add_features_multi_tf, time_split
from env.trading_env import TradingEnv

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# 실전 투입 검증 기준
THRESHOLD_RETURN = 0.15
THRESHOLD_MDD = 0.20
THRESHOLD_SHARPE = 1.0

# 연환산 상수 — BASE_INTERVAL에 의존. 1시간봉 기준 24*365.
ANNUALIZATION_BY_INTERVAL = {
    "minute1": 60 * 24 * 365,
    "minute3": 20 * 24 * 365,
    "minute5": 12 * 24 * 365,
    "minute10": 6 * 24 * 365,
    "minute15": 4 * 24 * 365,
    "minute30": 2 * 24 * 365,
    "minute60": 24 * 365,
    "minute240": 6 * 365,
    "day": 365,
    "week": 52,
}


def _annualization_factor() -> float:
    return float(ANNUALIZATION_BY_INTERVAL.get(BASE_INTERVAL, 252))


def compute_metrics(portfolio_curve: np.ndarray, trade_pnls: list[float]) -> dict:
    """확장 지표 세트.

    - Sharpe: 수익률 평균/표준편차 × √annualization
    - Sortino: 평균/하방편차 × √annualization (하방 리스크만 고려)
    - Calmar: 연환산 수익률 / MDD
    - Profit Factor: Σ이익 / |Σ손실|
    - Win Rate: 이익 거래 / 전체 거래
    - Avg Win/Loss Ratio: 평균 이익 / |평균 손실|
    """
    returns = np.diff(portfolio_curve) / portfolio_curve[:-1]
    total_return = portfolio_curve[-1] / portfolio_curve[0] - 1.0

    running_max = np.maximum.accumulate(portfolio_curve)
    drawdown = (portfolio_curve - running_max) / running_max
    mdd = float(-drawdown.min()) if len(drawdown) else 0.0

    ann = _annualization_factor()

    sharpe = float(returns.mean() / returns.std() * np.sqrt(ann)) if returns.std() > 0 else 0.0

    downside = returns[returns < 0]
    sortino = 0.0
    if len(downside) > 1 and downside.std() > 0:
        sortino = float(returns.mean() / downside.std() * np.sqrt(ann))

    # CAGR 추정 — 스텝 수를 연 단위로 환산
    n_steps = max(len(portfolio_curve) - 1, 1)
    years = n_steps / ann
    cagr = (portfolio_curve[-1] / portfolio_curve[0]) ** (1 / years) - 1.0 if years > 0 else 0.0
    calmar = float(cagr / mdd) if mdd > 1e-9 else 0.0

    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    n_trades_closed = len(trade_pnls)
    win_rate = (len(wins) / n_trades_closed) if n_trades_closed else 0.0
    profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else 0.0
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    wl_ratio = (avg_win / abs(avg_loss)) if avg_loss != 0 else 0.0

    return {
        "total_return": float(total_return),
        "mdd": mdd,
        "sharpe": sharpe,
        "sortino": float(sortino),
        "calmar": float(calmar),
        "profit_factor": float(profit_factor),
        "win_rate": float(win_rate),
        "avg_win_loss": float(wl_ratio),
        "trades": n_trades_closed,
        "n_steps": len(portfolio_curve),
        "final_value": float(portfolio_curve[-1]),
        "initial_value": float(portfolio_curve[0]),
    }


def _make_predictor(model_path: Path | None, ensemble_dir: Path | None):
    """단일 또는 앙상블 predictor를 통일된 인터페이스로 반환.

    반환 predictor는 (obs, state, episode_start) → (action, new_state).
    state는 단일이면 sb3 tuple, 앙상블이면 list[state].
    """
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


def run_backtest(
    df: pd.DataFrame,
    feature_cols: list[str],
    model_path: Path | None = None,
    ensemble_dir: Path | None = None,
) -> dict:
    env = TradingEnv(df, feature_cols=feature_cols)
    predict, lstm_states = _make_predictor(model_path, ensemble_dir)

    obs, _ = env.reset()
    curve = [env._portfolio_value()]

    # LSTM 상태. VecEnv를 사용하지 않아 배치 차원 1로 수동 관리.
    episode_start = np.ones((1,), dtype=bool)

    # 포지션 진입/청산을 묶어 거래별 PnL 기록 (Profit Factor·Win Rate용).
    trade_pnls: list[float] = []
    entry_value: float | None = None
    was_holding = False

    done = False
    while not done:
        action, lstm_states = predict(obs, lstm_states, episode_start)
        episode_start = np.zeros((1,), dtype=bool)

        # Python 3.14는 int(1-D ndarray)를 거부 — 명시적으로 스칼라 추출.
        action_int = int(np.asarray(action).reshape(-1)[0])
        obs, _reward, terminated, truncated, info = env.step(action_int)
        done = terminated or truncated
        curve.append(info["portfolio_value"])

        holding_now = info["coin_held"] > 0
        if not was_holding and holding_now:
            entry_value = info["portfolio_value"]
        elif was_holding and not holding_now and entry_value is not None:
            trade_pnls.append(info["portfolio_value"] - entry_value)
            entry_value = None
        was_holding = holding_now

    return compute_metrics(np.array(curve), trade_pnls)


def verdict(m: dict) -> str:
    ok = (
        m["total_return"] >= THRESHOLD_RETURN
        and m["mdd"] <= THRESHOLD_MDD
        and m["sharpe"] >= THRESHOLD_SHARPE
    )
    return "✓ PASS — 실전 투입 기준 충족" if ok else "✗ FAIL — 추가 학습/튜닝 필요"


def buy_and_hold_metrics(df: pd.DataFrame) -> dict:
    """비교군: 단순 Buy & Hold."""
    closes = df["close"].to_numpy()
    curve = INITIAL_BALANCE * (closes / closes[0])
    # B&H는 시작에 1회 매수·종료 시 평가 → trade PnL 1건
    bh_pnl = [curve[-1] - curve[0]]
    return compute_metrics(curve, bh_pnl)


def write_report(
    source_label: str, scaler_name: str, split: str,
    metrics: dict, bh: dict,
) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    path = REPORTS_DIR / f"backtest_{stamp}.md"
    lines = [
        f"# Backtest Report — {stamp}",
        "",
        f"- **Source**: `{source_label}`",
        f"- **Scaler**: `{scaler_name}`",
        f"- **Split**: {split}",
        f"- **Base interval**: {BASE_INTERVAL}",
        "",
        "## 결과",
        "",
        "| 지표 | 에이전트 | Buy & Hold | 기준 |",
        "|-----|---------|-----------|-----|",
        f"| Total Return   | {metrics['total_return']:+.2%} | {bh['total_return']:+.2%} | ≥ {THRESHOLD_RETURN:.0%} |",
        f"| MDD            | {metrics['mdd']:.2%} | {bh['mdd']:.2%} | ≤ {THRESHOLD_MDD:.0%} |",
        f"| Sharpe         | {metrics['sharpe']:.3f} | {bh['sharpe']:.3f} | ≥ {THRESHOLD_SHARPE} |",
        f"| Sortino        | {metrics['sortino']:.3f} | {bh['sortino']:.3f} | — |",
        f"| Calmar         | {metrics['calmar']:.3f} | {bh['calmar']:.3f} | — |",
        f"| Profit Factor  | {metrics['profit_factor']:.2f} | — | — |",
        f"| Win Rate       | {metrics['win_rate']:.1%} | — | — |",
        f"| Avg W/L Ratio  | {metrics['avg_win_loss']:.2f} | — | — |",
        f"| Trades         | {metrics['trades']} | 1 | — |",
        f"| Final Value    | {metrics['final_value']:,.0f}원 | {bh['final_value']:,.0f}원 | — |",
        "",
        f"**결론**: {verdict(metrics)}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _load_and_split():
    """멀티 TF 데이터 수집 → 피처 → time_split. 학습 시와 동일한 파이프라인."""
    intervals = [BASE_INTERVAL] + list(CONTEXT_INTERVALS)
    counts = {BASE_INTERVAL: BASE_COUNT}
    for itv in CONTEXT_INTERVALS:
        counts[itv] = CONTEXT_COUNT

    raw = load_or_fetch_multi_tf(TRADE_SYMBOL, intervals, counts=counts)
    base_raw = raw[BASE_INTERVAL]
    context = {itv: raw[itv] for itv in CONTEXT_INTERVALS}

    feat, feature_cols = add_features_multi_tf(
        base_raw, context=context, base_interval=BASE_INTERVAL,
    )
    tr, va, te = time_split(feat)
    return tr, va, te, feature_cols


def main():
    parser = argparse.ArgumentParser()
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--model", type=Path, help="단일 모델 .zip 경로")
    grp.add_argument("--ensemble", type=Path, help="앙상블 디렉토리 (seed_*.zip 포함)")
    parser.add_argument("--scaler", required=True, help="학습 시 저장한 scaler 이름")
    parser.add_argument("--split", choices=["val", "test"], default="val")
    args = parser.parse_args()

    _tr, val_df, test_df, feature_cols = _load_and_split()
    df = val_df if args.split == "val" else test_df

    scaler = load_scaler(args.scaler)
    df_scaled = transform(df, scaler, feature_cols=feature_cols)

    metrics = run_backtest(
        df_scaled, feature_cols,
        model_path=args.model, ensemble_dir=args.ensemble,
    )
    bh = buy_and_hold_metrics(df_scaled)

    source_label = args.ensemble.name if args.ensemble else args.model.name
    report = write_report(source_label, args.scaler, args.split, metrics, bh)
    print(f"✓ report: {report}")
    print(f"  Agent:   return={metrics['total_return']:+.2%}  MDD={metrics['mdd']:.2%}  "
          f"Sharpe={metrics['sharpe']:.3f}  Sortino={metrics['sortino']:.3f}  "
          f"Calmar={metrics['calmar']:.3f}  PF={metrics['profit_factor']:.2f}  "
          f"WinRate={metrics['win_rate']:.1%}")
    print(f"  B&H:     return={bh['total_return']:+.2%}  MDD={bh['mdd']:.2%}  Sharpe={bh['sharpe']:.3f}")
    print(verdict(metrics))


if __name__ == "__main__":
    main()
