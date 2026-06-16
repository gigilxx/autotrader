"use client";

import { useEffect, useState } from "react";
import { api, type MarketFilter } from "@/lib/api";

export function MarketFilterCard() {
  const [data, setData] = useState<MarketFilter | null>(null);

  useEffect(() => {
    api.marketFilter().then(setData).catch(() => {});
  }, []);

  if (!data || !data.available) {
    return (
      <div className="rounded-lg bg-gray-900 border border-gray-800 p-4">
        <p className="text-xs text-gray-500 mb-1">시장 필터 (KODEX200)</p>
        <p className="text-sm text-gray-500">데이터 없음 — 장 시작(08:55) 이후 표시</p>
      </div>
    );
  }

  const isOk = data.ok === true;
  const isBlocked = data.ok === false;

  return (
    <div className={`rounded-lg border p-4 ${isOk ? "bg-green-950/40 border-green-800" : isBlocked ? "bg-red-950/40 border-red-800" : "bg-gray-900 border-gray-800"}`}>
      <p className="text-xs text-gray-500 mb-2">시장 필터 (KODEX200)</p>
      <p className={`text-sm font-semibold mb-2 ${isOk ? "text-green-400" : isBlocked ? "text-red-400" : "text-gray-400"}`}>
        {isOk ? "상승 추세 — 진입 허용" : isBlocked ? "하락/횡보 — 진입 차단" : "상태 불명"}
      </p>
      {data.summary && (
        <pre className="text-xs text-gray-400 whitespace-pre-wrap font-sans">{data.summary}</pre>
      )}
      {data.updated_at && (
        <p className="text-xs text-gray-600 mt-2">갱신: {data.updated_at}</p>
      )}
    </div>
  );
}
