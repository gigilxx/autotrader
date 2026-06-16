"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type RankingStock } from "@/lib/api";

type RankType = "volume" | "amount" | "surge";

const TABS: { id: RankType; label: string }[] = [
  { id: "volume", label: "거래량 상위" },
  { id: "amount", label: "거래대금 상위" },
  { id: "surge",  label: "급등주" },
];

function fmtAmount(val: number): string {
  if (val >= 1_000_000_000_000) return `${(val / 1_000_000_000_000).toFixed(1)}조`;
  if (val >= 100_000_000)       return `${(val / 100_000_000).toFixed(0)}억`;
  if (val >= 10_000)            return `${(val / 10_000).toFixed(0)}만`;
  return val.toLocaleString();
}

function ChangeRate({ rate }: { rate: number }) {
  const sign = rate > 0 ? "+" : "";
  const color = rate > 0 ? "text-red-400" : rate < 0 ? "text-blue-400" : "text-gray-400";
  return <span className={`tabular-nums ${color}`}>{sign}{rate.toFixed(2)}%</span>;
}

export default function RankingPage() {
  const [tab, setTab]       = useState<RankType>("volume");
  const [stocks, setStocks] = useState<RankingStock[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError]   = useState("");
  const [fetchedAt, setFetchedAt] = useState("");

  const load = useCallback(async (type: RankType) => {
    setLoading(true);
    setError("");
    try {
      const r = await api.ranking(type);
      setStocks(r.stocks);
      setFetchedAt(r.fetched_at ?? "");
    } catch (e) {
      setError(String(e));
      setStocks([]);
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(tab); }, [load, tab]);

  const colLabel = tab === "volume"
    ? "거래량"
    : tab === "amount"
    ? "거래대금"
    : "거래량";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">시장 순위</h1>
        <div className="flex items-center gap-3">
          {fetchedAt && (
            <span className="text-xs text-gray-500">기준: {fetchedAt}</span>
          )}
          <button
            onClick={() => load(tab)}
            disabled={loading}
            className="text-xs text-gray-400 hover:text-gray-200 disabled:opacity-40"
          >
            새로고침
          </button>
        </div>
      </div>

      {/* 탭 */}
      <div className="flex gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
              tab === t.id
                ? "bg-blue-700 text-white"
                : "bg-gray-800 text-gray-400 hover:bg-gray-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <p className="text-xs text-gray-600">
        장중(09:00~15:30) 기준 데이터 · 최대 30종목 · 60초 캐시
      </p>

      {error && (
        <div className="rounded bg-red-900/40 border border-red-700 px-4 py-2 text-red-300 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-gray-500 text-center py-12">불러오는 중…</p>
      ) : stocks.length === 0 && !error ? (
        <p className="text-gray-500 text-center py-12">데이터 없음</p>
      ) : (
        <div className="overflow-x-auto rounded-xl bg-gray-900 border border-gray-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-800">
                <th className="px-4 py-3 font-medium w-10">순위</th>
                <th className="px-4 py-3 font-medium">종목</th>
                <th className="px-4 py-3 font-medium text-right">현재가</th>
                <th className="px-4 py-3 font-medium text-right">등락률</th>
                <th className="px-4 py-3 font-medium text-right">{colLabel}</th>
                <th className="px-4 py-3 font-medium text-right">거래대금</th>
              </tr>
            </thead>
            <tbody>
              {stocks.map((s) => (
                <tr key={s.symbol} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="px-4 py-3 text-gray-500 tabular-nums text-center">{s.rank}</td>
                  <td className="px-4 py-3">
                    <span className="font-medium text-gray-100">{s.name}</span>
                    <span className="block text-xs text-gray-500 mt-0.5">{s.symbol}</span>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {s.price.toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <ChangeRate rate={s.change_rate} />
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-gray-300">
                    {s.volume.toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-gray-300">
                    {fmtAmount(s.trading_value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
