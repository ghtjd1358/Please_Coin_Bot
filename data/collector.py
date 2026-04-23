"""업비트 OHLCV 수집. 페이징 + 캐싱 + 멀티 타임프레임."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable

import pandas as pd
import pyupbit

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# pyupbit 한 번 호출에 최대 200개
CHUNK = 200
SLEEP_SEC = 0.15


def fetch_ohlcv(symbol: str, interval: str, count: int) -> pd.DataFrame:
    """과거 `count`개 캔들을 최신부터 거꾸로 페이징 수집."""
    frames: list[pd.DataFrame] = []
    remaining = count
    to = None

    while remaining > 0:
        size = min(CHUNK, remaining)
        chunk = pyupbit.get_ohlcv(symbol, interval=interval, count=size, to=to)
        if chunk is None or chunk.empty:
            break
        frames.append(chunk)
        # 다음 페이지: 현재 청크의 가장 오래된 시각 이전
        to = chunk.index[0].strftime("%Y-%m-%d %H:%M:%S")
        remaining -= len(chunk)
        time.sleep(SLEEP_SEC)

    if not frames:
        raise RuntimeError(f"No data returned for {symbol} {interval}")

    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df


def load_or_fetch(symbol: str, interval: str, count: int, refresh: bool = False) -> pd.DataFrame:
    cache = CACHE_DIR / f"{symbol}_{interval}_{count}.parquet"
    if cache.exists() and not refresh:
        return pd.read_parquet(cache)

    df = fetch_ohlcv(symbol, interval, count)
    df.to_parquet(cache)
    return df


def load_or_fetch_multi_tf(
    symbol: str,
    intervals: Iterable[str],
    counts: dict[str, int] | None = None,
    refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    """여러 타임프레임을 한 번에 수집/캐싱.

    `counts`는 {interval: count} 매핑. 없으면 각 interval마다 기본값(365)을 사용.
    반환: {interval: DataFrame}. DataFrame의 인덱스는 datetime, 컬럼은 OHLCV.
    """
    counts = counts or {}
    out: dict[str, pd.DataFrame] = {}
    for itv in intervals:
        n = counts.get(itv, 365)
        out[itv] = load_or_fetch(symbol, itv, n, refresh=refresh)
    return out


if __name__ == "__main__":
    df = load_or_fetch("KRW-BTC", "day", 365)
    print(df.tail())
    print(f"rows={len(df)}, range={df.index[0]} ~ {df.index[-1]}")
