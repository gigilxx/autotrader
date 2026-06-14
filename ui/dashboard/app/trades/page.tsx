"use client";

import { useEffect, useState } from "react";
import { api, type Trade } from "@/lib/api";

export default function TradesPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.trades()
      .then((r) => setTrades(r.trades))
      .catch((e) => setError(String(e)));
  }, []);

  const totalPnl = trades.reduce((sum, t) => sum + t.pnl, 0);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">오늘 거래 내역</h1>

      {error && (
        <div className="rounded bg-red-900/40 border border-red-700 px-4 py-2 text-red-300 text-sm">
          {error}
        </div>
      )}

      {trades.length === 0 ? (
        <p className="text-gray-500 text-center py-12">오늘 거래 없음</p>
      ) : (
        <>
          <div className="text-sm text-gray-400">
            총 {trades.length}건 |{" "}
            <span className={totalPnl >= 0 ? "text-green-400" : "text-red-400"}>
              {totalPnl >= 0 ? "+" : ""}{totalPnl.toLocaleString()}원
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500 border-b border-gray-800">
                  <th className="py-2 pr-4">시각</th>
                  <th className="py-2 pr-4">종목</th>
                  <th className="py-2 pr-4 text-right">진입가</th>
                  <th className="py-2 pr-4 text-right">청산가</th>
                  <th className="py-2 pr-4 text-right">수량</th>
                  <th className="py-2 pr-4 text-right">손익</th>
                  <th className="py-2">사유</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => (
                  <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="py-2 pr-4 text-gray-400">{t.exit_time}</td>
                    <td className="py-2 pr-4 font-medium">{t.symbol}</td>
                    <td className="py-2 pr-4 text-right">{t.entry_price.toLocaleString()}</td>
                    <td className="py-2 pr-4 text-right">{t.exit_price.toLocaleString()}</td>
                    <td className="py-2 pr-4 text-right">{t.qty}</td>
                    <td className={`py-2 pr-4 text-right font-semibold ${t.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {t.pnl >= 0 ? "+" : ""}{t.pnl.toLocaleString()}
                    </td>
                    <td className="py-2 text-gray-400 text-xs">{t.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
