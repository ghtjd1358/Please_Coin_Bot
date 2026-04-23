import { useMemo } from 'react';
import { TRADE_SYMBOL } from './lib/supabase';
import { useRealtimeTrades } from './hooks/useRealtimeTrades';
import { usePortfolioHistory } from './hooks/usePortfolioHistory';
import { useLatestSnapshot } from './hooks/useLatestSnapshot';
import { computeRiskMetrics } from './lib/metrics';
import { PortfolioCard } from './components/PortfolioCard';
import { ReturnChart } from './components/ReturnChart';
import { RiskMetrics } from './components/RiskMetrics';
import { TradesTable } from './components/TradesTable';
import { AgentStatus } from './components/AgentStatus';

export default function App() {
  const symbol = TRADE_SYMBOL;
  const { trades, connected } = useRealtimeTrades(symbol, 100);
  const history = usePortfolioHistory(symbol, 24 * 30 * 3); // 3개월치 1h 캔들
  const latest = useLatestSnapshot(history);

  const metrics = useMemo(() => computeRiskMetrics(history, trades), [history, trades]);
  const lastTrade = trades[0] ?? null;
  const mode = latest?.mode ?? 'paper';

  return (
    <div className="min-h-screen px-5 py-6 max-w-7xl mx-auto">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">please_coin</h1>
          <p className="text-sm text-slate-400">
            RL 자동매매 모니터링 — {symbol}
          </p>
        </div>
        <span
          className={`px-3 py-1 rounded-full text-xs font-semibold tracking-wider uppercase ${
            mode === 'live'
              ? 'bg-sell/20 text-sell border border-sell/40'
              : 'bg-slate-800 text-slate-300 border border-slate-700'
          }`}
        >
          {mode}
        </span>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-1 space-y-5">
          <PortfolioCard snapshot={latest} />
          <AgentStatus snapshot={latest} lastTrade={lastTrade} connected={connected} />
        </div>
        <div className="lg:col-span-2 space-y-5">
          <ReturnChart history={history} />
          <RiskMetrics metrics={metrics} />
        </div>
      </div>

      <div className="mt-5">
        <TradesTable trades={trades} />
      </div>

      <footer className="mt-8 text-center text-xs text-slate-600">
        please_coin dashboard · Supabase Realtime · 기본 모드 paper
      </footer>
    </div>
  );
}
