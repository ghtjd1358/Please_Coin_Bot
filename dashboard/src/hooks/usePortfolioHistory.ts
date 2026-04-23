import { useEffect, useState } from 'react';
import { supabase, SnapshotRow } from '@/lib/supabase';

/**
 * portfolio_snapshots 최근 N 행 + 실시간 INSERT 스트림.
 * 내부 배열은 오래된 → 최신 순(차트가 바로 소비 가능).
 */
export function usePortfolioHistory(symbol: string, limit = 24 * 30) {
  const [history, setHistory] = useState<SnapshotRow[]>([]);

  useEffect(() => {
    let active = true;

    (async () => {
      const { data, error } = await supabase
        .from('portfolio_snapshots')
        .select('*')
        .eq('symbol', symbol)
        .order('created_at', { ascending: false })
        .limit(limit);
      if (!active) return;
      if (error) {
        console.warn('[snapshots] initial fetch failed', error);
        return;
      }
      // desc로 받아서 reverse → 시간 오름차순.
      setHistory(((data ?? []) as SnapshotRow[]).slice().reverse());
    })();

    const channel = supabase
      .channel(`snapshots-${symbol}`)
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'portfolio_snapshots',
          filter: `symbol=eq.${symbol}`,
        },
        (payload) => {
          const row = payload.new as SnapshotRow;
          setHistory((prev) => {
            const next = [...prev, row];
            return next.length > limit ? next.slice(next.length - limit) : next;
          });
        },
      )
      .subscribe();

    return () => {
      active = false;
      supabase.removeChannel(channel);
    };
  }, [symbol, limit]);

  return history;
}
