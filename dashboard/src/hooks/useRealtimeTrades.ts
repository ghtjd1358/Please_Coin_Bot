import { useEffect, useState } from 'react';
import { supabase, TradeRow } from '@/lib/supabase';

/**
 * trades 테이블 최근 N건 + postgres_changes INSERT 구독.
 * - 초기 로드: 심볼 필터 + created_at DESC
 * - 실시간: INSERT 이벤트를 앞에 prepend, limit을 넘으면 뒤를 잘라냄.
 */
export function useRealtimeTrades(symbol: string, limit = 50) {
  const [trades, setTrades] = useState<TradeRow[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let active = true;

    (async () => {
      const { data, error } = await supabase
        .from('trades')
        .select('*')
        .eq('symbol', symbol)
        .order('created_at', { ascending: false })
        .limit(limit);
      if (!active) return;
      if (error) {
        console.warn('[trades] initial fetch failed', error);
        return;
      }
      setTrades((data ?? []) as TradeRow[]);
    })();

    const channel = supabase
      .channel(`trades-${symbol}`)
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'trades',
          filter: `symbol=eq.${symbol}`,
        },
        (payload) => {
          const row = payload.new as TradeRow;
          setTrades((prev) => [row, ...prev].slice(0, limit));
        },
      )
      .subscribe((status) => {
        setConnected(status === 'SUBSCRIBED');
      });

    return () => {
      active = false;
      supabase.removeChannel(channel);
    };
  }, [symbol, limit]);

  return { trades, connected };
}
