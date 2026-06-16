"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Trade } from "@/lib/api";

const PAGE_SIZE = 20;

const PERIODS = [
  { label: "1일",   days: 1 },
  { label: "1주일", days: 7 },
  { label: "1달",   days: 30 },
  { label: "3개월", days: 90 },
  { label: "6개월", days: 180 },
  { label: "1년",   days: 365 },
];

function fmtDateTime(dateStr: string, timeStr: string) {
  return `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)} ${timeStr.slice(0, 5)}`;
}

export default function TradesPage() {
  const [days, setDays] = useState(1);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [nameMap, setNameMap] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(0);

  const load = useCallback(async (d: number) => {
    setLoading(true);
    setError("");
    setPage(0);
    try {
      const r = await api.trades(d);
      setTrades(r.trades);
      const symbols = [...new Set(r.trades.map((t) => t.symbol))];
      if (symbols.length > 0) {
        try {
          const info = await api.stocksInfo(symbols);
          setNameMap(Object.fromEntries(
            Object.entries(info.info).map(([code, v]) => [code, v.name])
          ));
        } catch {
          // 종목명 조회 실패 시 코드만 표시
        }
      } else {
        setNameMap({});
      }
    } catch (e) {
      setError(String(e));
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(days); }, [load, days]);

  function handlePeriod(d: number) {
    setDays(d);
  }

  const totalPnl = trades.reduce((sum, t) => sum + t.pnl, 0);
  const totalPages = Math.ceil(trades.length / PAGE_SIZE);
  const paginated = trades.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">거래 내역</h1>

      {/* 기간 선택 */}
      <div className="flex gap-2 flex-wrap">
        {PERIODS.map((p) => (
          <button
            key={p.days}
            onClick={() => handlePeriod(p.days)}
            className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
              days === p.days
                ? "bg-blue-700 text-white"
                : "bg-gray-800 text-gray-400 hover:bg-gray-700"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded bg-red-900/40 border border-red-700 px-4 py-2 text-red-300 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-gray-500 text-center py-12">불러오는 중…</p>
      ) : trades.length === 0 ? (
        <p className="text-gray-500 text-center py-12">거래 내역 없음</p>
      ) : (
        <>
          <div className="text-sm text-gray-400">
            총 {trades.length}건 |{" "}
            <span className={totalPnl >= 0 ? "text-green-400" : "text-red-400"}>
              {totalPnl >= 0 ? "+" : ""}{totalPnl.toLocaleString()}원
            </span>
          </div>

          <div className="overflow-x-auto rounded-xl bg-gray-900 border border-gray-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500 border-b border-gray-800">
                  <th className="px-4 py-3 font-medium">시각</th>
                  <th className="px-4 py-3 font-medium">종목</th>
                  <th className="px-4 py-3 font-medium text-right">진입가</th>
                  <th className="px-4 py-3 font-medium text-right">청산가</th>
                  <th className="px-4 py-3 font-medium text-right">수량</th>
                  <th className="px-4 py-3 font-medium text-right">손익</th>
                  <th className="px-4 py-3 font-medium">사유</th>
                </tr>
              </thead>
              <tbody>
                {paginated.map((t, i) => (
                  <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="px-4 py-3 text-gray-400 whitespace-nowrap tabular-nums">
                      {fmtDateTime(t.date, t.exit_time)}
                    </td>
                    <td className="px-4 py-3">
                      <span className="font-medium text-gray-100">
                        {nameMap[t.symbol] ?? t.symbol}
                      </span>
                      {nameMap[t.symbol] && (
                        <span className="block text-xs text-gray-500 mt-0.5">{t.symbol}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {t.entry_price.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {t.exit_price.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">{t.qty}</td>
                    <td className={`px-4 py-3 text-right font-semibold tabular-nums ${
                      t.pnl >= 0 ? "text-green-400" : "text-red-400"
                    }`}>
                      {t.pnl >= 0 ? "+" : ""}{t.pnl.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-gray-400 text-xs">{t.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-4 text-sm">
              <button
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="px-3 py-1 rounded bg-gray-800 text-gray-400 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                이전
              </button>
              <span className="text-gray-400 tabular-nums">
                {page + 1} / {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page === totalPages - 1}
                className="px-3 py-1 rounded bg-gray-800 text-gray-400 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                다음
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
