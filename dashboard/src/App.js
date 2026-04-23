import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
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
    return (_jsxs("div", { className: "min-h-screen px-5 py-6 max-w-7xl mx-auto", children: [_jsxs("header", { className: "flex items-center justify-between mb-6", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-2xl font-bold tracking-tight", children: "please_coin" }), _jsxs("p", { className: "text-sm text-slate-400", children: ["RL \uC790\uB3D9\uB9E4\uB9E4 \uBAA8\uB2C8\uD130\uB9C1 \u2014 ", symbol] })] }), _jsx("span", { className: `px-3 py-1 rounded-full text-xs font-semibold tracking-wider uppercase ${mode === 'live'
                            ? 'bg-sell/20 text-sell border border-sell/40'
                            : 'bg-slate-800 text-slate-300 border border-slate-700'}`, children: mode })] }), _jsxs("div", { className: "grid grid-cols-1 lg:grid-cols-3 gap-5", children: [_jsxs("div", { className: "lg:col-span-1 space-y-5", children: [_jsx(PortfolioCard, { snapshot: latest }), _jsx(AgentStatus, { snapshot: latest, lastTrade: lastTrade, connected: connected })] }), _jsxs("div", { className: "lg:col-span-2 space-y-5", children: [_jsx(ReturnChart, { history: history }), _jsx(RiskMetrics, { metrics: metrics })] })] }), _jsx("div", { className: "mt-5", children: _jsx(TradesTable, { trades: trades }) }), _jsx("footer", { className: "mt-8 text-center text-xs text-slate-600", children: "please_coin dashboard \u00B7 Supabase Realtime \u00B7 \uAE30\uBCF8 \uBAA8\uB4DC paper" })] }));
}
