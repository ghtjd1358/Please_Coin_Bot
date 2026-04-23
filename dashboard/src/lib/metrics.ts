import { SnapshotRow, TradeRow } from './supabase';

// 1시간봉 기준 연환산. BASE_INTERVAL이 달라지면 조정.
const ANNUALIZATION = 24 * 365;

export interface RiskMetrics {
  mdd: number;
  sharpe: number;
  sortino: number;
  calmar: number;
  totalReturn: number;
  consecutiveLosses: number;
  winRate: number;
}

export function computeRiskMetrics(
  history: SnapshotRow[],
  trades: TradeRow[],
): RiskMetrics {
  if (history.length < 2) {
    return {
      mdd: 0, sharpe: 0, sortino: 0, calmar: 0,
      totalReturn: 0, consecutiveLosses: 0, winRate: 0,
    };
  }

  const values = history.map((h) => Number(h.total_value));
  const returns: number[] = [];
  for (let i = 1; i < values.length; i++) {
    returns.push((values[i] - values[i - 1]) / values[i - 1]);
  }

  // MDD
  let peak = values[0];
  let mdd = 0;
  for (const v of values) {
    peak = Math.max(peak, v);
    const dd = (peak - v) / peak;
    mdd = Math.max(mdd, dd);
  }

  const mean = returns.reduce((a, b) => a + b, 0) / (returns.length || 1);
  const variance =
    returns.reduce((a, b) => a + (b - mean) ** 2, 0) / (returns.length || 1);
  const std = Math.sqrt(variance);
  const sharpe = std > 0 ? (mean / std) * Math.sqrt(ANNUALIZATION) : 0;

  const downside = returns.filter((r) => r < 0);
  let sortino = 0;
  if (downside.length > 1) {
    const dMean = downside.reduce((a, b) => a + b, 0) / downside.length;
    const dVar = downside.reduce((a, b) => a + (b - dMean) ** 2, 0) / downside.length;
    const dStd = Math.sqrt(dVar);
    if (dStd > 0) sortino = (mean / dStd) * Math.sqrt(ANNUALIZATION);
  }

  const totalReturn = values[values.length - 1] / values[0] - 1;
  const years = returns.length / ANNUALIZATION;
  const cagr = years > 0 ? (values[values.length - 1] / values[0]) ** (1 / years) - 1 : 0;
  const calmar = mdd > 1e-9 ? cagr / mdd : 0;

  // 연속 손실 (최근부터 PnL 있는 trades만 역순으로 카운트)
  let consec = 0;
  for (const t of trades) {
    if (t.pnl == null) continue;
    if (t.pnl < 0) consec++;
    else break;
  }

  const closed = trades.filter((t) => t.pnl != null);
  const wins = closed.filter((t) => (t.pnl ?? 0) > 0);
  const winRate = closed.length > 0 ? wins.length / closed.length : 0;

  return { mdd, sharpe, sortino, calmar, totalReturn, consecutiveLosses: consec, winRate };
}
