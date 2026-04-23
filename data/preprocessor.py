"""기술적 지표 + 수익률 기반 피처 생성.

원칙:
1. 가격 자체보다 **로그수익률**·비율 피처를 우선 — 정상성(stationarity) 확보
2. 멀티호라이즌 수익률 (1, 5, 20)로 서로 다른 시간척도의 모멘텀 포착
3. 추세/모멘텀/변동성/거래량 네 카테고리를 고루 포함
4. 지표 계산 후 NaN은 전부 드롭 (look-ahead 차단)
5. 장기 TF 컨텍스트는 해당 캔들의 "종가 확정 이후"에만 짧은 TF로 병합
   — 실시간 매매 시 미래 정보 누수 금지
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.trend import MACD, ADXIndicator, EMAIndicator, SMAIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import OnBalanceVolumeIndicator, MFIIndicator

# 학습·환경·백테스트에서 공유하는 베이스 피처 목록. 순서 고정.
BASE_FEATURE_COLS = [
    # ─ 수익률 (로그) — 정상성 ─
    "log_ret_1", "log_ret_5", "log_ret_20",
    # ─ 추세 ─
    "ema_gap_5_20", "ema_gap_20_60",
    "macd", "macd_signal", "macd_hist",
    "adx",
    # ─ 모멘텀 ─
    "rsi_14", "stoch_rsi_k", "stoch_rsi_d",
    # ─ 변동성 ─
    "atr_ratio", "bb_width", "bb_pos",
    "realized_vol_20",
    # ─ 거래량 ─
    "obv_change", "volume_ratio", "mfi_14",
]

# 장기 TF에서 뽑을 컨텍스트 피처 접미사. 앞에 "ctx_<interval>_"가 붙는다.
CTX_FEATURE_SUFFIXES = [
    "log_ret_1",
    "ema_gap_20_60",
    "adx",
    "rsi_14",
    "realized_vol_20",
]

# 기본값 — 단일 TF 모드에서는 이게 곧 전체.
FEATURE_COLS = list(BASE_FEATURE_COLS)


def _safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    return a / b.replace(0, np.nan)


def _compute_base_features(df: pd.DataFrame) -> pd.DataFrame:
    """BASE_FEATURE_COLS에 해당하는 피처를 OHLCV에서 계산.

    반환: close + BASE_FEATURE_COLS 컬럼. NaN 미드롭 (상위에서 병합 후 드롭).
    인덱스는 원본 df의 인덱스를 유지 (멀티 TF 병합 시 asof join에 사용).
    """
    out = df.copy()
    close = out["close"]
    high = out["high"]
    low = out["low"]
    volume = out["volume"]
    log_close = np.log(close.clip(lower=1e-9))

    out["log_ret_1"] = log_close.diff()
    out["log_ret_5"] = log_close.diff(5)
    out["log_ret_20"] = log_close.diff(20)

    ema5 = EMAIndicator(close, window=5).ema_indicator()
    ema20 = EMAIndicator(close, window=20).ema_indicator()
    ema60 = EMAIndicator(close, window=60).ema_indicator()
    out["ema_gap_5_20"] = _safe_div(ema5 - ema20, close)
    out["ema_gap_20_60"] = _safe_div(ema20 - ema60, close)

    macd = MACD(close, window_slow=26, window_fast=12, window_sign=9)
    out["macd"] = _safe_div(macd.macd(), close)
    out["macd_signal"] = _safe_div(macd.macd_signal(), close)
    out["macd_hist"] = _safe_div(macd.macd_diff(), close)

    out["adx"] = ADXIndicator(high, low, close, window=14).adx() / 100.0

    out["rsi_14"] = RSIIndicator(close, window=14).rsi() / 100.0
    stoch = StochRSIIndicator(close, window=14, smooth1=3, smooth2=3)
    out["stoch_rsi_k"] = stoch.stochrsi_k()
    out["stoch_rsi_d"] = stoch.stochrsi_d()

    atr = AverageTrueRange(high, low, close, window=14).average_true_range()
    out["atr_ratio"] = _safe_div(atr, close)
    bb = BollingerBands(close, window=20, window_dev=2)
    bb_upper = bb.bollinger_hband()
    bb_lower = bb.bollinger_lband()
    bb_middle = bb.bollinger_mavg()
    out["bb_width"] = _safe_div(bb_upper - bb_lower, bb_middle)
    out["bb_pos"] = _safe_div(close - bb_lower, bb_upper - bb_lower)

    out["realized_vol_20"] = out["log_ret_1"].rolling(20).std()

    obv = OnBalanceVolumeIndicator(close, volume).on_balance_volume()
    out["obv_change"] = obv.pct_change().clip(-5, 5)
    out["volume_ratio"] = _safe_div(volume, volume.rolling(20).mean()) - 1.0
    out["mfi_14"] = MFIIndicator(high, low, close, volume, window=14).money_flow_index() / 100.0

    return out[["close"] + BASE_FEATURE_COLS]


def _interval_close_offset(interval: str) -> pd.Timedelta:
    """해당 interval 캔들의 시작 인덱스에서 "종가 확정 시각"까지의 오프셋."""
    m = {
        "minute1": pd.Timedelta(minutes=1),
        "minute3": pd.Timedelta(minutes=3),
        "minute5": pd.Timedelta(minutes=5),
        "minute10": pd.Timedelta(minutes=10),
        "minute15": pd.Timedelta(minutes=15),
        "minute30": pd.Timedelta(minutes=30),
        "minute60": pd.Timedelta(hours=1),
        "minute240": pd.Timedelta(hours=4),
        "day": pd.Timedelta(days=1),
        "week": pd.Timedelta(weeks=1),
    }
    return m.get(interval, pd.Timedelta(days=1))


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """단일 TF 피처 테이블. 하위호환을 위해 기존 시그니처 유지."""
    feats = _compute_base_features(df).reset_index(drop=True)
    feat = feats.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)
    return feat


def add_features_multi_tf(
    base_df: pd.DataFrame,
    context: dict[str, pd.DataFrame] | None = None,
    base_interval: str = "minute60",
) -> tuple[pd.DataFrame, list[str]]:
    """멀티 TF 피처 테이블을 생성.

    규칙 (look-ahead 금지):
      - 장기 TF 캔들 시각 ``ts``의 컨텍스트는 ``ts + interval_length`` 시점부터만 유효.
      - 이를 어기면 실시간 매매 시 아직 확정되지 않은 종가를 보게 됨.
      - merge_asof로 "closed time ≤ base_time"인 가장 최신 컨텍스트만 가져옴.

    반환: (feature_df, feature_cols) — feature_cols 순서는 BASE + 컨텍스트 접미사.
    feature_df에는 close + feature_cols 컬럼이 들어간다.
    """
    base_feat = _compute_base_features(base_df)

    if not context:
        out = base_feat.reset_index(drop=True)
        out = out.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)
        return out, list(BASE_FEATURE_COLS)

    base_feat = base_feat.reset_index().rename(columns={base_feat.index.name or "index": "ts"})
    base_feat["ts"] = pd.to_datetime(base_feat["ts"])
    base_feat = base_feat.sort_values("ts")

    extra_cols: list[str] = []
    for interval, raw_ctx in context.items():
        ctx_feat = _compute_base_features(raw_ctx)
        ctx_feat = ctx_feat[CTX_FEATURE_SUFFIXES].copy()
        ctx_feat.index = pd.to_datetime(ctx_feat.index)
        # 종가 확정 시각으로 인덱스 shift — look-ahead 차단의 핵심.
        closed_at = ctx_feat.index + _interval_close_offset(interval)
        ctx_feat = ctx_feat.set_index(closed_at).sort_index()

        prefix = f"ctx_{interval}_"
        ctx_feat.columns = [prefix + c for c in ctx_feat.columns]
        extra_cols.extend(ctx_feat.columns.tolist())

        ctx_feat = ctx_feat.reset_index().rename(columns={"index": "ts"})
        base_feat = pd.merge_asof(
            base_feat, ctx_feat, on="ts", direction="backward", allow_exact_matches=True,
        )

    feature_cols = list(BASE_FEATURE_COLS) + extra_cols
    keep = ["close"] + feature_cols
    out = base_feat[keep].replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)
    return out, feature_cols


def time_split(df: pd.DataFrame, train: float = 0.7, val: float = 0.15):
    """시간 순 분할. 랜덤 금지."""
    assert 0 < train < 1 and 0 < val < 1 and train + val < 1
    n = len(df)
    t_end = int(n * train)
    v_end = int(n * (train + val))
    return (
        df.iloc[:t_end].reset_index(drop=True),
        df.iloc[t_end:v_end].reset_index(drop=True),
        df.iloc[v_end:].reset_index(drop=True),
    )


if __name__ == "__main__":
    from data.collector import load_or_fetch

    raw = load_or_fetch("KRW-BTC", "day", 730)
    feat = add_features(raw)
    tr, va, te = time_split(feat)
    print(f"features: {FEATURE_COLS}")
    print(f"rows: raw={len(raw)} feat={len(feat)}")
    print(f"split: train={len(tr)} val={len(va)} test={len(te)}")
    print(feat.describe().T[["mean", "std", "min", "max"]])
