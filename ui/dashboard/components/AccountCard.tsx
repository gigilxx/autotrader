"use client";

import { useEffect, useState } from "react";
import { api, type AccountInfo } from "@/lib/api";

export function AccountCard() {
  const [data, setData] = useState<AccountInfo | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    function load() {
      api.account().then(setData).catch((e) => setError(String(e)));
    }
    load();
    const timer = setInterval(load, 30_000);
    return () => clearInterval(timer);
  }, []);

  if (error) {
    return (
      <div className="rounded-lg bg-gray-900 border border-gray-800 p-4">
        <p className="text-xs text-gray-500 mb-1">계좌 정보 (KIS 실계좌)</p>
        <p className="text-sm text-red-400">{error}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg bg-gray-900 border border-gray-800 p-4">
        <p className="text-xs text-gray-500 mb-1">계좌 정보 (KIS 실계좌)</p>
        <p className="text-sm text-gray-500">조회 중...</p>
      </div>
    );
  }

  const pnlColor = data.total_pnl > 0 ? "text-green-400" : data.total_pnl < 0 ? "text-red-400" : "text-gray-100";

  return (
    <div className="rounded-lg bg-gray-900 border border-gray-800 p-4 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500">계좌 정보 (KIS 실계좌)</p>
        <p className="text-xs text-gray-600">갱신: {data.fetched_at}</p>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <p className="text-xs text-gray-500 mb-1">예수금</p>
          <p className="text-lg font-bold">{data.cash.toLocaleString()}원</p>
        </div>
        <div>
          <p className="text-xs text-gray-500 mb-1">총평가금액</p>
          <p className="text-lg font-bold">{data.total_eval_amount.toLocaleString()}원</p>
        </div>
        <div>
          <p className="text-xs text-gray-500 mb-1">평가손익</p>
          <p className={`text-lg font-bold ${pnlColor}`}>
            {data.total_pnl >= 0 ? "+" : ""}
            {data.total_pnl.toLocaleString()}원
          </p>
        </div>
      </div>

      {data.positions.length > 0 && (
        <div className="border-t border-gray-800 pt-3 space-y-2">
          {data.positions.map((p) => {
            const posPnlColor = p.eval_pnl > 0 ? "text-green-400" : p.eval_pnl < 0 ? "text-red-400" : "text-gray-300";
            return (
              <div key={p.symbol} className="flex items-center justify-between text-sm">
                <span className="text-gray-300">
                  {p.symbol} <span className="text-gray-500">{p.qty}주 @ {Math.round(p.avg_price).toLocaleString()}원</span>
                </span>
                <span className={posPnlColor}>
                  {p.eval_pnl >= 0 ? "+" : ""}
                  {p.eval_pnl.toLocaleString()}원 ({p.eval_pnl_rate >= 0 ? "+" : ""}{p.eval_pnl_rate.toFixed(2)}%)
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
