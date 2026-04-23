"""RecurrentPPO (LSTM 정책) 학습 엔트리.

  python -m agent.train

흐름:
  멀티TF 수집 (base=BASE_INTERVAL, context=CONTEXT_INTERVALS)
  → 피처 병합 (add_features_multi_tf, look-ahead 차단)
  → time_split → scaler fit(train만) → transform
  → Recurrent TradingEnv → VecNormalize(reward) → RecurrentPPO 학습
  → EvalCallback으로 val 최고 성능 모델 자동 저장
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sb3_contrib import RecurrentPPO
from stable_baselines3.common.callbacks import EvalCallback
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

from config import (
    TRADE_SYMBOL,
    BASE_INTERVAL, BASE_COUNT,
    CONTEXT_INTERVALS, CONTEXT_COUNT,
)
from data.collector import load_or_fetch_multi_tf
from data.normalizer import fit_scaler, save as save_scaler, transform
from data.preprocessor import add_features_multi_tf, time_split
from env.trading_env import TradingEnv

# ─── 학습 설정 ────────────────────────────────
# 멀티 TF로 시간당 샘플이 크게 늘었으므로 timesteps 상향.
HP_TOTAL_TIMESTEPS = 1_000_000

# RecurrentPPO
HP = dict(
    learning_rate=3e-4,
    n_steps=1024,         # 메모리 절약 (이전 2048 → 절반). PPO 표준 범위 내, 학습 품질 영향 미미
    batch_size=64,        # n_steps 줄임에 따라 비례 축소 (16 미니배치/롤아웃 유지)
    n_epochs=10,
    gamma=0.995,           # 장기 보상에 가중 (트레이딩은 long-horizon)
    gae_lambda=0.95,
    clip_range=0.2,
    ent_coef=0.01,
    vf_coef=0.5,
    max_grad_norm=0.5,
    target_kl=0.02,        # PPO 발산 방지
    policy_kwargs=dict(
        net_arch=dict(pi=[128, 128], vf=[128, 128]),
        lstm_hidden_size=128,
        n_lstm_layers=1,
        shared_lstm=False,
        enable_critic_lstm=True,
    ),
    verbose=1,
)

SEED = 42

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "models"
MODELS_DIR.mkdir(exist_ok=True)


def build_datasets():
    """멀티 TF 수집 + 피처 병합 + time_split + scaler fit(train만).

    반환 dict 키:
      train/val/test — 정규화 완료된 피처 DataFrame
      feature_cols   — 환경·백테스트에 그대로 전달할 컬럼 순서
      scaler_name    — 파일명(확장자 제외)
    """
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
    train_df, val_df, test_df = time_split(feat)

    scaler = fit_scaler(train_df, feature_cols=feature_cols)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    scaler_name = f"{TRADE_SYMBOL}_{stamp}"
    save_scaler(scaler, scaler_name)

    return {
        "train": transform(train_df, scaler, feature_cols=feature_cols),
        "val": transform(val_df, scaler, feature_cols=feature_cols),
        "test": transform(test_df, scaler, feature_cols=feature_cols),
        "scaler_name": scaler_name,
        "feature_cols": feature_cols,
    }


def make_env_fn(df, seed: int, feature_cols: list[str]):
    def _init():
        env = TradingEnv(df, feature_cols=feature_cols)
        env.reset(seed=seed)
        return env
    return _init


def train():
    data = build_datasets()
    feature_cols = data["feature_cols"]
    print(f"✓ scaler: {data['scaler_name']}")
    print(f"  features: {len(feature_cols)}")
    print(f"  rows: train={len(data['train'])} val={len(data['val'])} test={len(data['test'])}")

    check_env(TradingEnv(data["train"], feature_cols=feature_cols))  # SB3 호환 검증

    train_env = VecNormalize(
        DummyVecEnv([make_env_fn(data["train"], SEED, feature_cols)]),
        norm_obs=False,       # 피처는 이미 RobustScaler로 정규화됨
        norm_reward=True,     # 보상만 정규화 (DSR 스케일 안정화)
        clip_reward=10.0,
        gamma=HP["gamma"],
    )
    val_env = VecNormalize(
        DummyVecEnv([make_env_fn(data["val"], SEED + 1, feature_cols)]),
        norm_obs=False, norm_reward=False, training=False,
    )
    # val_env는 train_env의 running stats를 공유해야 일관됨
    val_env.obs_rms = train_env.obs_rms
    val_env.ret_rms = train_env.ret_rms

    model = RecurrentPPO("MlpLstmPolicy", train_env, seed=SEED, **HP)

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    best_dir = MODELS_DIR / f"best_{TRADE_SYMBOL}_{stamp}"
    eval_cb = EvalCallback(
        val_env,
        best_model_save_path=str(best_dir),
        log_path=str(best_dir / "logs"),
        eval_freq=max(HP["n_steps"] // 1, 5000),
        n_eval_episodes=3,
        deterministic=True,
        render=False,
    )

    model.learn(total_timesteps=HP_TOTAL_TIMESTEPS, callback=eval_cb)

    final_path = MODELS_DIR / f"ppo_{TRADE_SYMBOL}_{stamp}.zip"
    model.save(final_path)
    train_env.save(str(MODELS_DIR / f"vecnorm_{TRADE_SYMBOL}_{stamp}.pkl"))

    print(f"✓ final model:  {final_path}")
    print(f"✓ best model:   {best_dir}/best_model.zip")
    print(f"✓ scaler:       models/scalers/{data['scaler_name']}.pkl")
    return final_path


if __name__ == "__main__":
    train()
