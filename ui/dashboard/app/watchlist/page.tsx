"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Position } from "@/lib/api";

export default function WatchlistPage() {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<{ text: string; type: "info" | "error" } | null>(null);

  const load = useCallback(async () => {
    try {
      const [wl, pos] = await Promise.all([api.watchlist(), api.positions()]);
      setSymbols(wl.symbols);
      setPositions(pos.positions);
    } catch (e) {
      setMsg({ text: String(e), type: "error" });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function showMsg(text: string, type: "info" | "error" = "info") {
    setMsg({ text, type });
    setTimeout(() => setMsg(null), 4000);
  }

  async function add() {
    const sym = input.trim();
    if (!/^\d{6}$/.test(sym)) {
      showMsg("6자리 숫자 종목코드를 입력하세요 (예: 000660)", "error");
      return;
    }
    if (symbols.includes(sym)) {
      showMsg("이미 추가된 종목입니다", "error");
      return;
    }
    setLoading(true);
    try {
      await api.setWatchlist([...symbols, sym]);
      setInput("");
      showMsg(`${sym} 추가됨 — 봇이 5초 내 목표가를 계산합니다`);
      await load();
    } catch (e) {
      showMsg(String(e), "error");
    }
    setLoading(false);
  }

  async function remove(sym: string) {
    const posHeld = positions.some((p) => p.symbol === sym);
    if (posHeld && !confirm(`${sym}을 제거하면 보유 포지션이 즉시 청산됩니다. 계속하시겠습니까?`)) return;
    setLoading(true);
    try {
      await api.setWatchlist(symbols.filter((s) => s !== sym));
      showMsg(`${sym} 제거됨`);
      await load();
    } catch (e) {
      showMsg(String(e), "error");
    }
    setLoading(false);
  }

  async function enter(sym: string) {
    if (!confirm(`${sym}을 현재가로 즉시 매수하시겠습니까?\n(킬스위치가 활성화된 경우 거부됩니다)`)) return;
    setLoading(true);
    try {
      await api.forceEntry(sym);
      showMsg(`${sym} 강제 진입 요청 완료 — 5초 내 처리됩니다`);
    } catch (e) {
      showMsg(String(e), "error");
    }
    setLoading(false);
  }

  async function close(sym: string) {
    if (!confirm(`${sym} 포지션을 즉시 청산하시겠습니까?`)) return;
    setLoading(true);
    try {
      await api.closePosition(sym);
      showMsg(`${sym} 청산 요청 완료`);
      await load();
    } catch (e) {
      showMsg(String(e), "error");
    }
    setLoading(false);
  }

  const posMap = new Map(positions.map((p) => [p.symbol, p]));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">관심종목</h1>
        <button onClick={load} className="text-xs text-gray-400 hover:text-gray-200">
          새로고침
        </button>
      </div>

      {msg && (
        <div className={`rounded px-4 py-2 text-sm border ${
          msg.type === "error"
            ? "bg-red-900/40 border-red-700 text-red-300"
            : "bg-blue-900/40 border-blue-700 text-blue-300"
        }`}>
          {msg.text}
        </div>
      )}

      {/* 종목 추가 */}
      <div className="rounded-xl bg-gray-900 border border-gray-800 p-5 space-y-3">
        <h2 className="text-sm font-semibold text-gray-400">종목 추가</h2>
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()}
            placeholder="종목코드 6자리 (예: 000660)"
            maxLength={6}
            className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm font-mono focus:outline-none focus:border-blue-500"
          />
          <button
            onClick={add}
            disabled={loading}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded text-sm font-medium transition-colors"
          >
            추가
          </button>
        </div>
        <p className="text-xs text-gray-600">
          추가 후 봇이 5초 내 해당 종목의 목표가를 계산합니다.
        </p>
      </div>

      {/* 관심종목 목록 */}
      <div className="rounded-xl bg-gray-900 border border-gray-800 p-5 space-y-3">
        <h2 className="text-sm font-semibold text-gray-400">
          목록 ({symbols.length}개)
        </h2>

        {symbols.length === 0 ? (
          <p className="text-gray-500 text-sm py-4 text-center">관심종목이 없습니다</p>
        ) : (
          <div className="space-y-2">
            {symbols.map((sym) => {
              const pos = posMap.get(sym);
              return (
                <div
                  key={sym}
                  className="flex items-center justify-between rounded-lg bg-gray-800 border border-gray-700 px-4 py-3"
                >
                  <div>
                    <span className="font-mono font-semibold text-base">{sym}</span>
                    {pos && (
                      <span className="ml-3 text-xs text-yellow-400">
                        보유 {pos.qty}주 @ {pos.entry_price.toLocaleString()}원
                      </span>
                    )}
                  </div>

                  <div className="flex gap-2">
                    {pos ? (
                      <button
                        onClick={() => close(sym)}
                        disabled={loading}
                        className="px-3 py-1 bg-orange-800 hover:bg-orange-700 disabled:opacity-50 rounded text-xs font-medium transition-colors"
                      >
                        청산
                      </button>
                    ) : (
                      <button
                        onClick={() => enter(sym)}
                        disabled={loading}
                        className="px-3 py-1 bg-green-800 hover:bg-green-700 disabled:opacity-50 rounded text-xs font-medium transition-colors"
                      >
                        강제 진입
                      </button>
                    )}
                    <button
                      onClick={() => remove(sym)}
                      disabled={loading}
                      className="px-3 py-1 bg-gray-700 hover:bg-red-900 disabled:opacity-50 rounded text-xs font-medium transition-colors"
                    >
                      제거
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="rounded bg-gray-900/60 border border-gray-800 px-4 py-3 text-xs text-gray-500 space-y-1">
        <p><strong className="text-gray-400">강제 진입</strong>: 브레이크아웃 조건 무시하고 현재가 즉시 매수. 킬스위치 활성화 시 거부됩니다.</p>
        <p><strong className="text-gray-400">제거</strong>: 보유 포지션이 있으면 즉시 청산 후 제거합니다.</p>
      </div>
    </div>
  );
}
