import {
  LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { useMemo } from 'react';
import { SnapshotRow } from '@/lib/supabase';

interface Props {
  history: SnapshotRow[];
}

export function ReturnChart({ history }: Props) {
  const data = useMemo(() => {
    if (!history.length) return [];
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
    return (
      <div className="rounded-xl bg-slate-900/60 p-5 border border-slate-800 h-80 flex items-center justify-center text-slate-500 text-sm">
        스냅샷 수집 중…
      </div>
    );
  }

  return (
    <div className="rounded-xl bg-slate-900/60 p-5 border border-slate-800">
      <h2 className="text-sm font-semibold text-slate-300 tracking-wide mb-3">수익률 추이 (%)</h2>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis
              dataKey="t"
              type="number"
              domain={['dataMin', 'dataMax']}
              tickFormatter={(t) => new Date(t).toLocaleDateString('ko-KR', { month: 'numeric', day: 'numeric' })}
              stroke="#64748b"
              fontSize={11}
            />
            <YAxis stroke="#64748b" fontSize={11} tickFormatter={(v) => `${v.toFixed(1)}`} />
            <ReferenceLine y={0} stroke="#475569" strokeDasharray="3 3" />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8 }}
              labelFormatter={(t) => new Date(Number(t)).toLocaleString('ko-KR')}
              formatter={(value: number) => [`${value.toFixed(2)}%`, '수익률']}
            />
            <Line type="monotone" dataKey="ret" stroke="#38bdf8" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
