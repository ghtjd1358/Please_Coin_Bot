import { createClient } from '@supabase/supabase-js';

// 대시보드는 **읽기 전용**. anon key 사용.
const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anon = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

if (!url || !anon) {
  // 개발 편의를 위해 경고만. 실제 배포 시 빌드 단계에서 필수.
  console.warn(
    '[dashboard] VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY 미설정. ' +
    '.env 를 채우세요.',
  );
}

export const supabase = createClient(url ?? '', anon ?? '');

export const TRADE_SYMBOL =
  (import.meta.env.VITE_TRADE_SYMBOL as string | undefined) ?? 'KRW-BTC';

// ─────────── DB row 타입 (schema.sql과 동기화) ───────────
export type TradeMode = 'paper' | 'live';
export type TradeAction = 'buy' | 'sell' | 'hold' | 'stop_loss';

export interface TradeRow {
  id: string;
  created_at: string;
  symbol: string;
  action: TradeAction;
  price: number;
  amount: number;
  fee: number;
  balance_after: number;
  coin_held_after: number;
  pnl: number | null;
  mode: TradeMode;
  note: string | null;
}

export interface SnapshotRow {
  id: string;
  created_at: string;
  symbol: string;
  total_value: number;
  balance: number;
  coin_held: number;
  avg_buy_price: number;
  unrealized_pnl: number;
  current_price: number;
  mode: TradeMode;
}

export interface AgentLogRow {
  id: string;
  created_at: string;
  symbol: string;
  obs_summary: Record<string, unknown>;
  action: 0 | 1 | 2;
  reward: number | null;
  confidence: number | null;
  mode: TradeMode;
}
