"""피처 정규화. Train 구간만으로 fit, val/test/실매매에 동일 스케일 적용.

핵심 규칙:
- walk-forward/앙상블에서도 반드시 **해당 fold의 train 구간만으로 fit**.
- transform에 사용할 컬럼은 호출자가 명시적으로 전달 (멀티 TF로 개수가 달라지므로).
"""
from __future__ import annotations

import pickle
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler

from data.preprocessor import FEATURE_COLS as DEFAULT_FEATURE_COLS

SCALERS_DIR = Path(__file__).resolve().parents[1] / "models" / "scalers"
SCALERS_DIR.mkdir(parents=True, exist_ok=True)


def _resolve_cols(feature_cols: Sequence[str] | None) -> list[str]:
    return list(feature_cols) if feature_cols is not None else list(DEFAULT_FEATURE_COLS)


def fit_scaler(train_df: pd.DataFrame, feature_cols: Sequence[str] | None = None) -> RobustScaler:
    cols = _resolve_cols(feature_cols)
    scaler = RobustScaler()
    scaler.fit(train_df[cols].to_numpy(dtype=np.float64))
    # 어떤 컬럼으로 fit했는지 스케일러 객체에 부착해두면 transform 때 자가 검증 가능.
    scaler.feature_names_in_ = np.array(cols)
    return scaler


def transform(df: pd.DataFrame, scaler: RobustScaler, feature_cols: Sequence[str] | None = None) -> pd.DataFrame:
    """피처 컬럼만 정규화. close는 실행용으로 원본 유지."""
    cols = _resolve_cols(feature_cols)
    out = df.copy()
    arr = scaler.transform(out[cols].to_numpy(dtype=np.float64))
    # 극단값 클리핑 — 학습 안정화
    arr = np.clip(arr, -10.0, 10.0).astype(np.float32)
    out[cols] = arr
    return out


def save(scaler: RobustScaler, name: str) -> Path:
    path = SCALERS_DIR / f"{name}.pkl"
    with path.open("wb") as f:
        pickle.dump(scaler, f)
    return path


def load(name: str) -> RobustScaler:
    path = SCALERS_DIR / f"{name}.pkl"
    with path.open("rb") as f:
        return pickle.load(f)
