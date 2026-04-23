"""자동 재시작 래퍼.

핵심 동작:
1. `models/ensemble_*/` 중 가장 최근 디렉토리 자동 선택
2. `models/scalers/*.pkl` 중 가장 최근 스케일러 자동 선택
3. `main.py live --ensemble ... --scaler ...` 실행
4. 비정상 종료(exit != 0) 시 10초 후 재시작 — 무한 루프
5. 정상 종료(exit == 0) 시 루프 탈출 (Ctrl-C로 사용자가 끔)
6. 연속 크래시 5회 시 일시정지(1분) → 무한 재시작 폭주 방지

사용:
    python scripts/run_bot.py          # 일반 모드 (스케줄러 가동)
    python scripts/run_bot.py --once   # 1 tick만 (스모크)
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "models"
SCALERS_DIR = MODELS_DIR / "scalers"

RESTART_DELAY = 10         # 정상이 아닐 때 재시작 간격 (초)
CRASH_THRESHOLD = 5        # 연속 크래시 임계치
COOLDOWN_SEC = 60          # 임계치 도달 후 대기


def _latest_ensemble() -> Path | None:
    dirs = [p for p in MODELS_DIR.glob("ensemble_*") if p.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime)


def _latest_scaler_name() -> str | None:
    scalers = list(SCALERS_DIR.glob("*.pkl"))
    if not scalers:
        return None
    return max(scalers, key=lambda p: p.stat().st_mtime).stem


def _build_command(once: bool) -> list[str]:
    ens = _latest_ensemble()
    sc = _latest_scaler_name()
    if not ens:
        sys.exit("✗ 앙상블 디렉토리 없음 — 먼저 `python main.py train-ensemble` 실행")
    if not sc:
        sys.exit("✗ 스케일러 없음 — 먼저 `python main.py train-ensemble` 실행")

    cmd = [
        sys.executable, "-u", "main.py", "live",
        "--ensemble", str(ens),
        "--scaler", sc,
    ]
    if once:
        cmd.append("--once")
    return cmd


def main() -> None:
    once = "--once" in sys.argv[1:]
    cmd = _build_command(once)
    print("── run_bot ──")
    for k, v in [("root", ROOT), ("cwd", ROOT), ("once", once), ("cmd", " ".join(cmd))]:
        print(f"  {k}: {v}")

    crash_streak = 0
    while True:
        rc = subprocess.call(cmd, cwd=str(ROOT))
        if rc == 0:
            print("✓ 봇 정상 종료 — 루프 탈출")
            break

        crash_streak += 1
        print(f"✗ exit={rc}, crash_streak={crash_streak}")

        if once:
            # once 모드는 한 번만. 실패해도 재시작 안 함.
            sys.exit(rc)

        if crash_streak >= CRASH_THRESHOLD:
            print(f"⚠ 연속 {crash_streak}회 크래시 — {COOLDOWN_SEC}초 대기")
            time.sleep(COOLDOWN_SEC)
            crash_streak = 0
        else:
            time.sleep(RESTART_DELAY)


if __name__ == "__main__":
    main()
