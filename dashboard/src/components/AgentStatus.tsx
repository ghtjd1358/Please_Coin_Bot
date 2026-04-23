import { SnapshotRow, TradeRow } from '@/lib/supabase';

interface Props {
  snapshot: SnapshotRow | null;
  lastTrade: TradeRow | null;
  connected: boolean;
}

export function AgentStatus({ snapshot, lastTrade, connected }: Props) {
  const holding = Number(snapshot?.coin_held ?? 0) > 0;

  return (
    <div className="rounded-xl bg-slate-900/60 p-5 border border-slate-800">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-300 tracking-wide">에이전트 상태</h2>
        <span className="flex items-center gap-1 text-xs">
          <span className={`inline-block w-2 h-2 rounded-full ${
            connected ? 'bg-buy animate-pulse' : 'bg-sell'
          }`} />
          <span className="text-slate-400">{connected ? 'Realtime 연결' : '연결 대기'}</span>
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-slate-500">포지션</div>
          <div className={`text-lg font-semibold ${holding ? 'text-buy' : 'text-slate-400'}`}>
            {holding ? 'HOLDING' : 'CASH'}
          </div>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wide text-slate-500">마지막 액션</div>
          <div className="text-lg font-semibold">
            {lastTrade ? lastTrade.action.toUpperCase() : '—'}
          </div>
          {lastTrade && (
            <div className="text-xs text-slate-500">
              {new Date(lastTrade.created_at).toLocaleString('ko-KR')}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
