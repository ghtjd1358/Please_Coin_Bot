import { SnapshotRow } from '@/lib/supabase';

interface Props {
  snapshot: SnapshotRow | null;
}

const KRW = (n: number | string) =>
  new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 }).format(Number(n)) + '원';

const PCT = (n: number | string) => `${(Number(n) * 100).toFixed(2)}%`;

export function PortfolioCard({ snapshot }: Props) {
  if (!snapshot) {
    return (
      <div className="rounded-xl bg-slate-900/60 p-5 border border-slate-800">
        <div className="text-slate-400 text-sm">포트폴리오 데이터 대기 중…</div>
      </div>
    );
  }

  const positive = Number(snapshot.unrealized_pnl) >= 0;

  return (
    <div className="rounded-xl bg-slate-900/60 p-5 border border-slate-800">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-slate-300 tracking-wide">포트폴리오</h2>
        <span className="text-xs text-slate-500 uppercase">{snapshot.mode}</span>
      </div>

      <div className="text-3xl font-bold mb-1">{KRW(snapshot.total_value)}</div>
      <div className={`text-sm mb-5 ${positive ? 'text-buy' : 'text-sell'}`}>
        미실현 {positive ? '+' : ''}{PCT(snapshot.unrealized_pnl)}
      </div>

      <dl className="grid grid-cols-2 gap-y-2 text-sm">
        <dt className="text-slate-400">현금 잔고</dt>
        <dd className="text-right">{KRW(snapshot.balance)}</dd>

        <dt className="text-slate-400">코인 보유</dt>
        <dd className="text-right font-mono">{Number(snapshot.coin_held).toFixed(6)}</dd>

        <dt className="text-slate-400">평균 매수가</dt>
        <dd className="text-right">
          {Number(snapshot.avg_buy_price) > 0 ? KRW(snapshot.avg_buy_price) : '—'}
        </dd>

        <dt className="text-slate-400">현재가</dt>
        <dd className="text-right">{KRW(snapshot.current_price)}</dd>
      </dl>
    </div>
  );
}
