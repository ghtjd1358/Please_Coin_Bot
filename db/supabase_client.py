"""Supabase 로깅·조회 래퍼.

원칙:
- insert 실패(네트워크/인증)로 트레이더 루프가 죽지 않는다 → try/except + warn.
- SUPABASE_URL / SUPABASE_KEY 미설정 시 `build_logger()`가 NoOp 로거를 반환.
- `mode`는 인스턴스 속성으로 고정 — 매 호출마다 넘기지 않게.
- 모든 insert는 공용 헬퍼 `_insert`를 통해 재시도·로깅 경로를 일원화.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from config import (
    SUPABASE_KEY, SUPABASE_URL,
    SUPABASE_MAX_RETRIES, TRADE_MODE,
)

log = logging.getLogger(__name__)


class NullLogger:
    """Supabase 키가 없을 때 사용하는 NoOp. 모든 insert는 무시, read는 빈 값."""

    def __init__(self, mode: str = "paper"):
        self.mode = mode
        self.enabled = False

    def insert_trade(self, **kwargs) -> Optional[str]:
        log.debug("NullLogger.insert_trade skipped (%s)", kwargs.get("action"))
        return None

    def insert_snapshot(self, **kwargs) -> Optional[str]:
        return None

    def insert_agent_log(self, **kwargs) -> Optional[str]:
        return None

    def get_recent_trades(self, symbol: str, limit: int = 50) -> list[dict]:
        return []

    def get_latest_snapshot(self, symbol: str) -> Optional[dict]:
        return None

    def get_portfolio_curve(self, symbol: str, hours: int = 24 * 30) -> list[dict]:
        return []


class SupabaseLogger:
    """트레이더에서 쓰는 전용 래퍼.

    `create_client`는 생성자에서 1회만. `mode`는 `TRADE_MODE`에서 자동 주입되며
    명시적으로 override 가능 (테스트용).
    """

    def __init__(self, url: str, key: str, mode: str):
        from supabase import create_client

        self.mode = mode
        self.enabled = True
        self._client = create_client(url, key)

    # ─────────────── 내부 공용 ───────────────
    def _insert(self, table: str, payload: dict) -> Optional[str]:
        """insert 한 번. 실패하면 경고 로그 후 None 반환 — 트레이더 계속 진행."""
        attempt = 0
        while attempt <= SUPABASE_MAX_RETRIES:
            try:
                res = self._client.table(table).insert(payload).execute()
                rows = getattr(res, "data", None) or []
                if rows and isinstance(rows, list):
                    return rows[0].get("id")
                return None
            except Exception as e:  # 네트워크/인증/검증 실패 모두 흡수
                attempt += 1
                if attempt > SUPABASE_MAX_RETRIES:
                    log.warning("Supabase insert failed (%s): %s", table, e)
                    return None
                time.sleep(0.3 * attempt)
        return None

    def _select(self, table: str, builder) -> list[dict]:
        try:
            res = builder.execute()
            return getattr(res, "data", None) or []
        except Exception as e:
            log.warning("Supabase select failed (%s): %s", table, e)
            return []

    # ─────────────── inserts ───────────────
    def insert_trade(
        self,
        symbol: str,
        action: str,            # 'buy' | 'sell' | 'hold' | 'stop_loss'
        price: float,
        amount: float,
        fee: float,
        balance_after: float,
        coin_held_after: float,
        pnl: Optional[float] = None,
        note: str = "",
    ) -> Optional[str]:
        payload: dict[str, Any] = {
            "symbol": symbol,
            "action": action,
            "price": float(price),
            "amount": float(amount),
            "fee": float(fee),
            "balance_after": float(balance_after),
            "coin_held_after": float(coin_held_after),
            "mode": self.mode,
            "note": note or None,
        }
        if pnl is not None:
            payload["pnl"] = float(pnl)
        return self._insert("trades", payload)

    def insert_snapshot(
        self,
        symbol: str,
        total_value: float,
        balance: float,
        coin_held: float,
        avg_buy_price: float,
        unrealized_pnl: float,
        current_price: float,
    ) -> Optional[str]:
        payload = {
            "symbol": symbol,
            "total_value": float(total_value),
            "balance": float(balance),
            "coin_held": float(coin_held),
            "avg_buy_price": float(avg_buy_price),
            "unrealized_pnl": float(unrealized_pnl),
            "current_price": float(current_price),
            "mode": self.mode,
        }
        return self._insert("portfolio_snapshots", payload)

    def insert_agent_log(
        self,
        symbol: str,
        obs_summary: dict,
        action: int,
        reward: Optional[float] = None,
        confidence: Optional[float] = None,
    ) -> Optional[str]:
        payload = {
            "symbol": symbol,
            # jsonb 컬럼 — dict를 그대로 넘겨도 되나, 직렬화 안정성을 위해 한번 거름.
            "obs_summary": json.loads(json.dumps(obs_summary, default=str)),
            "action": int(action),
            "mode": self.mode,
        }
        if reward is not None:
            payload["reward"] = float(reward)
        if confidence is not None:
            payload["confidence"] = float(confidence)
        return self._insert("agent_logs", payload)

    # ─────────────── selects ───────────────
    def get_recent_trades(self, symbol: str, limit: int = 50) -> list[dict]:
        builder = (
            self._client.table("trades")
            .select("*")
            .eq("symbol", symbol)
            .order("created_at", desc=True)
            .limit(limit)
        )
        return self._select("trades", builder)

    def get_latest_snapshot(self, symbol: str) -> Optional[dict]:
        builder = (
            self._client.table("portfolio_snapshots")
            .select("*")
            .eq("symbol", symbol)
            .order("created_at", desc=True)
            .limit(1)
        )
        rows = self._select("portfolio_snapshots", builder)
        return rows[0] if rows else None

    def get_portfolio_curve(self, symbol: str, hours: int = 24 * 30) -> list[dict]:
        """최근 N시간 스냅샷. 대시보드 차트용.

        hours 파라미터는 참고값 — 실제 필터는 timestamp 기반이 아니라
        최근 `hours * 2` 행까지로 단순화 (BASE_INTERVAL=minute60 기준 약 2배 여유).
        """
        limit = max(hours * 2, 100)
        builder = (
            self._client.table("portfolio_snapshots")
            .select("*")
            .eq("symbol", symbol)
            .order("created_at", desc=True)
            .limit(limit)
        )
        rows = self._select("portfolio_snapshots", builder)
        # 오래된 → 최신 순으로 반환 (차트가 그리기 쉽게).
        return list(reversed(rows))


def build_logger(mode: str | None = None) -> SupabaseLogger | NullLogger:
    """Factory — 키 없으면 NullLogger, 있으면 SupabaseLogger.

    `mode`를 명시하지 않으면 `config.TRADE_MODE`를 사용.
    """
    mode = mode or TRADE_MODE
    if not SUPABASE_URL or not SUPABASE_KEY:
        log.warning("SUPABASE_URL/KEY 미설정 — NullLogger 사용 (기록 비활성화)")
        return NullLogger(mode=mode)
    try:
        return SupabaseLogger(SUPABASE_URL, SUPABASE_KEY, mode=mode)
    except Exception as e:
        log.warning("SupabaseLogger 초기화 실패 — NullLogger로 fallback: %s", e)
        return NullLogger(mode=mode)


# ─── 하위 호환 (기존 log_trade 호출부가 있다면) ───────────
def log_trade(
    symbol: str, action: str, price: float, amount: float,
    balance: float, portfolio_value: float, mode: str, note: str = "",
) -> None:
    """Deprecated: 새 코드는 `build_logger()`를 사용할 것."""
    logger = build_logger(mode=mode)
    logger.insert_trade(
        symbol=symbol, action=action, price=price, amount=amount, fee=0.0,
        balance_after=balance, coin_held_after=0.0, note=note or f"pv={portfolio_value:.0f}",
    )
