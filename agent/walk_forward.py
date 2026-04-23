"""Walk-Forward 검증.

설계:
- 전체 피처 테이블을 K개 폴드로 롤링 분할.
- 각 폴드에서 과거 WF_TRAIN_RATIO(=70%)를 학습, 나머지 30%를 평가.
- 각 폴드의 scaler는 해당 폴드의 train 구간만으로 fit — look-ahead 차단.
- 폴드당 timesteps는 비교적 짧게 (150k) — K번 반복이라 누적 비용 고려.

리포트: 폴드별 Total Return / MDD / Sharpe / Sortino / Calmar + 평균±표준편차.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sb3_contrib import RecurrentPPO
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

from config import (
    TRADE_SYMBOL,
    BASE_INTERVAL, BASE_COUNT,
    CONTEXT_INTERVALS, CONTEXT_COUNT,
    WF_N_FOLDS, WF_TRAIN_RATIO, WF_MIN_FOLD_ROWS,
    ENSEMBLE_SEEDS,
)
from data.collector import load_or_fetch_multi_tf
from data.normalizer import fit_scaler, transform
from data.preprocessor import add_features_multi_tf
from env.trading_env import TradingEnv
from agent.backtest import run_backtest, compute_metrics, buy_and_hold_metrics
from agent.train import HP, make_env_fn

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)
WF_TIMESTEPS_PER_FOLD = 150_000


def _build_features():
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
    return feat, feature_cols


def _fold_slices(n_rows: int, n_folds: int) -> list[tuple[int, int]]:
    """롤링 윈도우. 각 폴드는 시작점이 다른 연속 구간.

    반환: [(start, end), ...]. 폴드 길이는 전체 / n_folds 기준으로 균등.
    마지막 폴드는 잔여 포함.
    """
    fold_len = n_rows // n_folds
    slices = []
    for i in range(n_folds):
        start = i * fold_len
        end = n_rows if i == n_folds - 1 else (i + 1) * fold_len
        slices.append((start, end))
    return slices


def _train_one_fold(
    train_df: pd.DataFrame,
    feature_cols: list[str],
    seed: int,
    timesteps: int,
) -> RecurrentPPO:
    env = VecNormalize(
        DummyVecEnv([make_env_fn(train_df, seed, feature_cols)]),
        norm_obs=False, norm_reward=True, clip_reward=10.0, gamma=HP["gamma"],
    )
    model = RecurrentPPO("MlpLstmPolicy", env, seed=seed, **HP)
    model.learn(total_timesteps=timesteps)
    return model


def walk_forward(
    n_folds: int = WF_N_FOLDS,
    timesteps_per_fold: int = WF_TIMESTEPS_PER_FOLD,
    seed: int = ENSEMBLE_SEEDS[0],
) -> Path:
    feat, feature_cols = _build_features()
    n = len(feat)
    slices = _fold_slices(n, n_folds)

    fold_results: list[dict] = []
    bh_results: list[dict] = []

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    tmp_model_dir = ROOT / "models" / f"walkforward_{stamp}"
    tmp_model_dir.mkdir(parents=True, exist_ok=True)

    for i, (start, end) in enumerate(slices):
        fold = feat.iloc[start:end].reset_index(drop=True)
        if len(fold) < WF_MIN_FOLD_ROWS:
            print(f"  fold {i}: skipped (rows={len(fold)} < {WF_MIN_FOLD_ROWS})")
            continue

        split_at = int(len(fold) * WF_TRAIN_RATIO)
        train_df = fold.iloc[:split_at].reset_index(drop=True)
        eval_df = fold.iloc[split_at:].reset_index(drop=True)

        # 각 폴드 고유 scaler — train 구간만으로 fit (look-ahead 차단).
        scaler = fit_scaler(train_df, feature_cols=feature_cols)
        train_scaled = transform(train_df, scaler, feature_cols=feature_cols)
        eval_scaled = transform(eval_df, scaler, feature_cols=feature_cols)

        print(f"\n── fold {i+1}/{len(slices)} (train={len(train_scaled)}, eval={len(eval_scaled)}) ──")
        model = _train_one_fold(train_scaled, feature_cols, seed, timesteps_per_fold)

        model_path = tmp_model_dir / f"fold_{i}.zip"
        model.save(model_path)

        metrics = run_backtest(eval_scaled, feature_cols, model_path=model_path)
        bh = buy_and_hold_metrics(eval_scaled)
        metrics["fold"] = i
        metrics["train_rows"] = len(train_scaled)
        metrics["eval_rows"] = len(eval_scaled)
        fold_results.append(metrics)
        bh_results.append(bh)
        print(f"  return={metrics['total_return']:+.2%}  MDD={metrics['mdd']:.2%}  "
              f"Sharpe={metrics['sharpe']:.3f}  Sortino={metrics['sortino']:.3f}  "
              f"Calmar={metrics['calmar']:.3f}")

    report_path = _write_report(stamp, fold_results, bh_results, n_folds, timesteps_per_fold, seed)
    print(f"\n✓ walk-forward report: {report_path}")
    return report_path


def _summarize(values: Iterable[float]) -> tuple[float, float]:
    arr = np.array(list(values), dtype=float)
    if arr.size == 0:
        return 0.0, 0.0
    return float(arr.mean()), float(arr.std(ddof=0))


def _write_report(
    stamp: str,
    fold_results: list[dict],
    bh_results: list[dict],
    n_folds: int,
    timesteps_per_fold: int,
    seed: int,
) -> Path:
    path = REPORTS_DIR / f"walkforward_{stamp}.md"
    if not fold_results:
        path.write_text("# Walk-Forward\n\n모든 폴드가 최소 행수 미달로 스킵됨.\n", encoding="utf-8")
        return path

    metrics_keys = ["total_return", "mdd", "sharpe", "sortino", "calmar"]
    labels = {
        "total_return": "Total Return",
        "mdd": "MDD",
        "sharpe": "Sharpe",
        "sortino": "Sortino",
        "calmar": "Calmar",
    }

    lines = [
        f"# Walk-Forward Report — {stamp}",
        "",
        f"- **Folds**: {n_folds} (executed: {len(fold_results)})",
        f"- **Train ratio per fold**: {WF_TRAIN_RATIO:.0%}",
        f"- **Timesteps per fold**: {timesteps_per_fold:,}",
        f"- **Seed**: {seed}",
        f"- **Base interval**: {BASE_INTERVAL}",
        "",
        "## 폴드별 지표",
        "",
        "| Fold | Train | Eval | Return | MDD | Sharpe | Sortino | Calmar | B&H Return |",
        "|-----|------|------|-------|-----|--------|---------|--------|-----------|",
    ]
    for m, bh in zip(fold_results, bh_results):
        lines.append(
            f"| {m['fold']} | {m['train_rows']} | {m['eval_rows']} | "
            f"{m['total_return']:+.2%} | {m['mdd']:.2%} | {m['sharpe']:.3f} | "
            f"{m['sortino']:.3f} | {m['calmar']:.3f} | {bh['total_return']:+.2%} |"
        )

    lines += [
        "",
        "## 평균 ± 표준편차",
        "",
        "| 지표 | 평균 | 표준편차 |",
        "|-----|-----|---------|",
    ]
    for k in metrics_keys:
        mean, std = _summarize(m[k] for m in fold_results)
        if k in ("total_return", "mdd"):
            lines.append(f"| {labels[k]} | {mean:+.2%} | {std:.2%} |")
        else:
            lines.append(f"| {labels[k]} | {mean:.3f} | {std:.3f} |")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


if __name__ == "__main__":
    walk_forward()
