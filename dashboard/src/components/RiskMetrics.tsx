import { RiskMetrics as RM } from '@/lib/metrics';

interface Props {
  metrics: RM;
}

const PCT = (n: number) => `${(n * 100).toFixed(2)}%`;

function Cell({ label, value, hint, tone = 'neutral' }: {
  label: string; value: string; hint?: string;
  tone?: 'good' | 'bad' | 'neutral';
}) {
  const toneClass =
    tone === 'good' ? 'text-buy' : tone === 'bad' ? 'text-sell' : 'text-slate-100';
  return (
    <div className="rounded-lg bg-slate-900/40 border border-slate-800 p-3">
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`text-xl font-semibold mt-1 ${toneClass}`}>{value}</div>
      {hint && <div className="text-xs text-slate-500 mt-1">{hint}</div>}
    </div>
  );
}

export function RiskMetrics({ metrics }: Props) {
  // CLAUDE.md 검증 기준 (Stage 3→4 진입): return>15%, MDD<20%, Sharpe>1.0
  const returnOk = metrics.totalReturn >= 0.15;
  const mddOk = metrics.mdd <= 0.20;
  const sharpeOk = metrics.sharpe >= 1.0;

  return (
    <div className="rounded-xl bg-slate-900/60 p-5 border border-slate-800">
      <h2 className="text-sm font-semibold text-slate-300 tracking-wide mb-3">리스크 지표</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Cell
          label="총 수익률"
          value={PCT(metrics.totalReturn)}
          hint="기준 ≥ 15%"
          tone={returnOk ? 'good' : 'bad'}
        />
        <Cell
          label="MDD"
          value={PCT(metrics.mdd)}
          hint="기준 ≤ 20%"
          tone={mddOk ? 'good' : 'bad'}
        />
        <Cell
          label="Sharpe"
          value={metrics.sharpe.toFixed(2)}
          hint="기준 ≥ 1.00"
          tone={sharpeOk ? 'good' : 'bad'}
        />
        <Cell label="Sortino" value={metrics.sortino.toFixed(2)} />
        <Cell label="Calmar" value={metrics.calmar.toFixed(2)} />
        <Cell label="승률" value={PCT(metrics.winRate)} />
        <Cell
          label="연속 손실"
          value={`${metrics.consecutiveLosses}회`}
          tone={metrics.consecutiveLosses >= 3 ? 'bad' : 'neutral'}
          hint="5회에서 자동 일시정지"
        />
      </div>
    </div>
  );
}
