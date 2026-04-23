import { TradeRow, TradeAction } from '@/lib/supabase';

interface Props {
  trades: TradeRow[];
}

const rowClass: Record<TradeAction, string> = {
  buy: 'text-buy',
  sell: 'text-sell',
  stop_loss: 'text-stop',
  hold: 'text-hold',
};

const KRW = (n: number) =>
  new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 }).format(n);

export function TradesTable({ trades }: Props) {
  return (
    <div className="rounded-xl bg-slate-900/60 p-5 border border-slate-800">
      <h2 className="text-sm font-semibold text-slate-300 tracking-wide mb-3">최근 매매</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-slate-500 text-[11px] uppercase tracking-wide border-b border-slate-800">
              <th className="text-left py-2 pr-3">시각</th>
              <th className="text-left py-2 pr-3">Action</th>
              <th className="text-right py-2 pr-3">가격</th>
              <th className="text-right py-2 pr-3">수량</th>
              <th className="text-right py-2 pr-3">PnL</th>
              <th className="text-left py-2 pr-3">Note</th>
            </tr>
          </thead>
          <tbody>
            {trades.length === 0 && (
              <tr>
                <td colSpan={6} className="py-6 text-center text-slate-500">
                  매매 기록 없음
                </td>
              </tr>
            )}
            {trades.map((t) => (
              <tr key={t.id} className="border-b border-slate-900 hover:bg-slate-900/40">
                <td className="py-2 pr-3 text-slate-400 whitespace-nowrap">
                  {new Date(t.created_at).toLocaleString('ko-KR')}
                </td>
                <td className={`py-2 pr-3 font-semibold ${rowClass[t.action]}`}>
                  {t.action.toUpperCase()}
                </td>
                <td className="py-2 pr-3 text-right font-mono">{KRW(Number(t.price))}</td>
                <td className="py-2 pr-3 text-right font-mono">{Number(t.amount).toFixed(6)}</td>
                <td className={`py-2 pr-3 text-right font-mono ${
                  t.pnl == null ? 'text-slate-500' : t.pnl >= 0 ? 'text-buy' : 'text-sell'
                }`}>
                  {t.pnl == null ? '—' : `${t.pnl >= 0 ? '+' : ''}${KRW(Number(t.pnl))}`}
                </td>
                <td className="py-2 pr-3 text-slate-400">{t.note ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
