"""CLI 엔트리포인트.

사용:
  python main.py collect                                 # 과거 데이터 수집 (멀티 TF)
  python main.py train                                   # 단일 시드 PPO 학습
  python main.py train-ensemble                          # ENSEMBLE_SEEDS로 다중 시드 학습
  python main.py walkforward                             # Walk-Forward 검증
  python main.py backtest --model <path>      --scaler <name> [--split val|test]
  python main.py backtest --ensemble <dir>    --scaler <name> [--split val|test]
  python main.py live     --model <path>      --scaler <name>
  python main.py live     --ensemble <dir>    --scaler <name>
"""
from __future__ import annotations

import argparse
import sys

# Windows cp949 터미널에서 유니코드(✓, ✗ 등) 출력이 깨지지 않도록 UTF-8 강제.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def cmd_collect(_args):
    from config import (
        TRADE_SYMBOL,
        BASE_INTERVAL, BASE_COUNT,
        CONTEXT_INTERVALS, CONTEXT_COUNT,
    )
    from data.collector import load_or_fetch_multi_tf
    from data.preprocessor import add_features_multi_tf, time_split

    intervals = [BASE_INTERVAL] + list(CONTEXT_INTERVALS)
    counts = {BASE_INTERVAL: BASE_COUNT}
    for itv in CONTEXT_INTERVALS:
        counts[itv] = CONTEXT_COUNT

    raw = load_or_fetch_multi_tf(TRADE_SYMBOL, intervals, counts=counts, refresh=True)
    base_raw = raw[BASE_INTERVAL]
    context = {itv: raw[itv] for itv in CONTEXT_INTERVALS}
    feat, feature_cols = add_features_multi_tf(
        base_raw, context=context, base_interval=BASE_INTERVAL,
    )
    tr, va, te = time_split(feat)
    print(f"✓ base={BASE_INTERVAL} raw={len(base_raw)}  context={list(context)}")
    print(f"  feat={len(feat)} ({len(feature_cols)} features)")
    print(f"  split: train={len(tr)} val={len(va)} test={len(te)}")


def cmd_train(_args):
    from agent.train import train
    train()


def cmd_train_ensemble(_args):
    from agent.ensemble import train_ensemble
    train_ensemble()


def cmd_walkforward(_args):
    from agent.walk_forward import walk_forward
    walk_forward()


def cmd_backtest(args):
    argv = ["backtest"]
    if args.model:
        argv += ["--model", args.model]
    if args.ensemble:
        argv += ["--ensemble", args.ensemble]
    argv += ["--scaler", args.scaler, "--split", args.split]
    sys.argv = argv
    from agent.backtest import main as backtest_main
    backtest_main()


def cmd_live(args):
    argv = []
    if args.model:
        argv += ["--model", args.model]
    if args.ensemble:
        argv += ["--ensemble", args.ensemble]
    argv += ["--scaler", args.scaler]
    if args.once:
        argv += ["--once"]
    sys.argv = ["live"] + argv
    from agent.live_trader import main as live_main
    live_main()


def build_parser():
    p = argparse.ArgumentParser(prog="please_coin")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("collect", help="과거 데이터 수집 (멀티 TF)")
    sub.add_parser("train", help="단일 시드 RecurrentPPO 학습")
    sub.add_parser("train-ensemble", help="ENSEMBLE_SEEDS로 다중 시드 학습")
    sub.add_parser("walkforward", help="Walk-Forward 검증 (K-fold)")

    bt = sub.add_parser("backtest", help="백테스트 평가 (단일 모델 or 앙상블)")
    grp = bt.add_mutually_exclusive_group(required=True)
    grp.add_argument("--model", help="단일 모델 .zip 경로")
    grp.add_argument("--ensemble", help="앙상블 디렉토리 (seed_*.zip 포함)")
    bt.add_argument("--scaler", required=True, help="학습 때 저장된 scaler 이름")
    bt.add_argument("--split", choices=["val", "test"], default="val")

    lv = sub.add_parser("live", help="모의/실전 실행")
    lv_grp = lv.add_mutually_exclusive_group(required=True)
    lv_grp.add_argument("--model", help="단일 모델 .zip 경로")
    lv_grp.add_argument("--ensemble", help="앙상블 디렉토리 (seed_*.zip 포함)")
    lv.add_argument("--scaler", required=True, help="학습 때 저장된 scaler 이름")
    lv.add_argument("--once", action="store_true",
                    help="스케줄러 없이 1 tick만 실행하는 스모크 모드")
    return p


HANDLERS = {
    "collect": cmd_collect,
    "train": cmd_train,
    "train-ensemble": cmd_train_ensemble,
    "walkforward": cmd_walkforward,
    "backtest": cmd_backtest,
    "live": cmd_live,
}


if __name__ == "__main__":
    args = build_parser().parse_args()
    HANDLERS[args.cmd](args)
