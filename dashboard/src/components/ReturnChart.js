import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, ReferenceLine, } from 'recharts';
import { useMemo } from 'react';
export function ReturnChart({ history }) {
    const data = useMemo(() => {
        if (!history.length)
            return [];
        const base = Number(history[0].total_value);
        return history.map((h) => {
            const pv = Number(h.total_value);
            return {
                t: new Date(h.created_at).getTime(),
                pv,
                ret: (pv / base - 1) * 100,
            };
        });
    }, [history]);
    if (!data.length) {
        return (_jsx("div", { className: "rounded-xl bg-slate-900/60 p-5 border border-slate-800 h-80 flex items-center justify-center text-slate-500 text-sm", children: "\uC2A4\uB0C5\uC0F7 \uC218\uC9D1 \uC911\u2026" }));
    }
    return (_jsxs("div", { className: "rounded-xl bg-slate-900/60 p-5 border border-slate-800", children: [_jsx("h2", { className: "text-sm font-semibold text-slate-300 tracking-wide mb-3", children: "\uC218\uC775\uB960 \uCD94\uC774 (%)" }), _jsx("div", { className: "h-72", children: _jsx(ResponsiveContainer, { width: "100%", height: "100%", children: _jsxs(LineChart, { data: data, children: [_jsx(CartesianGrid, { strokeDasharray: "3 3", stroke: "#1e293b" }), _jsx(XAxis, { dataKey: "t", type: "number", domain: ['dataMin', 'dataMax'], tickFormatter: (t) => new Date(t).toLocaleDateString('ko-KR', { month: 'numeric', day: 'numeric' }), stroke: "#64748b", fontSize: 11 }), _jsx(YAxis, { stroke: "#64748b", fontSize: 11, tickFormatter: (v) => `${v.toFixed(1)}` }), _jsx(ReferenceLine, { y: 0, stroke: "#475569", strokeDasharray: "3 3" }), _jsx(Tooltip, { contentStyle: { background: '#0f172a', border: '1px solid #334155', borderRadius: 8 }, labelFormatter: (t) => new Date(Number(t)).toLocaleString('ko-KR'), formatter: (value) => [`${value.toFixed(2)}%`, '수익률'] }), _jsx(Line, { type: "monotone", dataKey: "ret", stroke: "#38bdf8", strokeWidth: 2, dot: false })] }) }) })] }));
}
