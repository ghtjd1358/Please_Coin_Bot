"""다중 시드 앙상블 학습·추론.

철학:
- RL 학습은 시드 의존성이 크다. 서로 다른 시드로 같은 데이터·같은 HP로 학습하면
  각 모델이 다른 지역 최적해에 수렴 → 앙상블 투표로 개별 모델의 과적합을 완충.
- 행동이 이산 {0,1,2}이므로 **최빈값 (plurality vote)** 이 자연스럽다.
  연속 행동 공간이라면 평균이 맞지만, 이산 → 평균은 의미 없는 소수 action을 만든다.
"""
from __future__ import annotations

import gc
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Sequence

import numpy as np

from config import ENSEMBLE_SEEDS, TRADE_SYMBOL

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "models"
MODELS_DIR.mkdir(exist_ok=True)


def train_ensemble(
    seeds: Sequence[int] | None = None,
    timesteps: int = 500_000,
) -> Path:
    """각 시드로 순차 학습. VRAM 1장에서 병렬은 비효율이라 순차가 기본.

    반환: `models/ensemble_<stamp>/` 디렉토리. 내부에 seed_<N>.zip 들과
    공유 scaler/feature_cols 메타데이터.
    """
    from sb3_contrib import RecurrentPPO
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    # train.py에서 모델 설정·데이터 빌드 로직을 공유.
    from agent.train import HP, build_datasets, make_env_fn

    seeds = list(seeds) if seeds is not None else list(ENSEMBLE_SEEDS)

    data = build_datasets()
    feature_cols = data["feature_cols"]
    print(f"✓ ensemble data: features={len(feature_cols)} "
          f"train={len(data['train'])} val={len(data['val'])}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    ens_dir = MODELS_DIR / f"ensemble_{TRADE_SYMBOL}_{stamp}"
    ens_dir.mkdir(parents=True, exist_ok=True)

    # 각 모델은 같은 scaler를 사용하므로 이름만 기록.
    meta = {
        "scaler_name": data["scaler_name"],
        "feature_cols": feature_cols,
        "seeds": seeds,
        "timesteps": timesteps,
    }
    (ens_dir / "meta.txt").write_text(
        "\n".join([
            f"scaler={meta['scaler_name']}",
            f"timesteps={meta['timesteps']}",
            f"seeds={','.join(map(str, meta['seeds']))}",
            f"feature_cols={','.join(meta['feature_cols'])}",
        ]),
        encoding="utf-8",
    )

    for seed in seeds:
        print(f"\n── seed {seed} ────────────────────────────")
        train_env = VecNormalize(
            DummyVecEnv([make_env_fn(data["train"], seed, feature_cols)]),
            norm_obs=False, norm_reward=True, clip_reward=10.0, gamma=HP["gamma"],
        )

        model = RecurrentPPO("MlpLstmPolicy", train_env, seed=seed, **HP)
        model.learn(total_timesteps=timesteps)

        save_path = ens_dir / f"seed_{seed}.zip"
        model.save(save_path)
        train_env.save(str(ens_dir / f"vecnorm_seed_{seed}.pkl"))
        print(f"  ✓ saved: {save_path}")

        # ─── 메모리 강제 회수 (Windows 16GB에서 5번째 시드 OOM 재발 방지) ───
        # PyTorch는 GC가 돌기 전까지 텐서·그래프 캐시를 유지함. 시드 간 명시적
        # 정리 없으면 누적 누수로 5번째 ~ 6번째 시드에서 할당 실패.
        try:
            train_env.close()
        except Exception:
            pass
        del model, train_env
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    print(f"\n✓ ensemble complete: {ens_dir}")
    return ens_dir


class EnsemblePolicy:
    """여러 RecurrentPPO 모델의 action을 최빈값으로 결합.

    LSTM 상태는 모델마다 다르므로 **리스트로 분리 관리**. 공유 불가.
    """

    def __init__(self, model_paths: Sequence[Path]):
        from sb3_contrib import RecurrentPPO  # noqa: F401 — import 검증만

        from sb3_contrib import RecurrentPPO as _RPPO
        if not model_paths:
            raise ValueError("EnsemblePolicy requires at least one model path")
        self.models = [_RPPO.load(p) for p in model_paths]
        self.n = len(self.models)

    @classmethod
    def from_dir(cls, ensemble_dir: Path) -> "EnsemblePolicy":
        paths = sorted(Path(ensemble_dir).glob("seed_*.zip"))
        if not paths:
            raise FileNotFoundError(f"No seed_*.zip in {ensemble_dir}")
        return cls(paths)

    def initial_state(self) -> list:
        """각 모델에 대응하는 LSTM 상태 슬롯."""
        return [None] * self.n

    def predict(
        self,
        obs: np.ndarray,
        lstm_states_list: list | None,
        episode_starts: np.ndarray,
    ):
        """각 모델이 독립적으로 예측 → action 최빈값.

        인자:
          obs: 단일 env 관측 (batch=1)
          lstm_states_list: 모델별 이전 LSTM 상태 (None이면 초기화)
          episode_starts: shape (1,) bool
        반환:
          (action, new_lstm_states_list)
        """
        if lstm_states_list is None:
            lstm_states_list = self.initial_state()

        actions: list[int] = []
        new_states: list = []
        for model, state in zip(self.models, lstm_states_list):
            action, new_state = model.predict(
                obs, state=state, episode_start=episode_starts, deterministic=True,
            )
            actions.append(int(action))
            new_states.append(new_state)

        # 최빈값. 동률이면 Counter.most_common의 첫 번째 (insertion order) = 낮은 seed 우선.
        vote = Counter(actions).most_common(1)[0][0]
        # backtest 루프가 int(action)로 또 캐스팅하므로 scalar로 감싸 반환.
        return np.array([vote]), new_states


if __name__ == "__main__":
    train_ensemble()
