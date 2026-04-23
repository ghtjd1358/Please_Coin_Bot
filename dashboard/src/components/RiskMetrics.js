import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
const PCT = (n) => `${(n * 100).toFixed(2)}%`;
function Cell({ label, value, hint, tone = 'neutral' }) {
    const toneClass = tone === 'good' ? 'text-buy' : tone === 'bad' ? 'text-sell' : 'text-slate-100';
    return (_jsxs("div", { className: "rounded-lg bg-slate-900/40 border border-slate-800 p-3", children: [_jsx("div", { className: "text-[11px] uppercase tracking-wide text-slate-500", children: label }), _jsx("div", { className: `text-xl font-semibold mt-1 ${toneClass}`, children: value }), hint && _jsx("div", { className: "text-xs text-slate-500 mt-1", children: hint })] }));
}
export function RiskMetrics({ metrics }) {
    // CLAUDE.md 검증 기준 (Stage 3→4 진입): return>15%, MDD<20%, Sharpe>1.0
    const returnOk = metrics.totalReturn >= 0.15;
    const mddOk = metrics.mdd <= 0.20;
    const sharpeOk = metrics.sharpe >= 1.0;
    return (_jsxs("div", { className: "rounded-xl bg-slate-900/60 p-5 border border-slate-800", children: [_jsx("h2", { className: "text-sm font-semibold text-slate-300 tracking-wide mb-3", children: "\uB9AC\uC2A4\uD06C \uC9C0\uD45C" }), _jsxs("div", { className: "grid grid-cols-2 md:grid-cols-4 gap-3", children: [_jsx(Cell, { label: "\uCD1D \uC218\uC775\uB960", value: PCT(metrics.totalReturn), hint: "\uAE30\uC900 \u2265 15%", tone: returnOk ? 'good' : 'bad' }), _jsx(Cell, { label: "MDD", value: PCT(metrics.mdd), hint: "\uAE30\uC900 \u2264 20%", tone: mddOk ? 'good' : 'bad' }), _jsx(Cell, { label: "Sharpe", value: metrics.sharpe.toFixed(2), hint: "\uAE30\uC900 \u2265 1.00", tone: sharpeOk ? 'good' : 'bad' }), _jsx(Cell, { label: "Sortino", value: metrics.sortino.toFixed(2) }), _jsx(Cell, { label: "Calmar", value: metrics.calmar.toFixed(2) }), _jsx(Cell, { label: "\uC2B9\uB960", value: PCT(metrics.winRate) }), _jsx(Cell, { label: "\uC5F0\uC18D \uC190\uC2E4", value: `${metrics.consecutiveLosses}회`, tone: metrics.consecutiveLosses >= 3 ? 'bad' : 'neutral', hint: "5\uD68C\uC5D0\uC11C \uC790\uB3D9 \uC77C\uC2DC\uC815\uC9C0" })] })] }));
}
