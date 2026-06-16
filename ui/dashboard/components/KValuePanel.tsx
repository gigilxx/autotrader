"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export function KValuePanel() {
  const [currentK, setCurrentK] = useState<number | null>(null);
  const [pendingK, setPendingK] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(false);

  async function load() {
    try {
      const cfg = await api.getK();
      setCurrentK(cfg.current_k);
      setPendingK(cfg.pending_k);
    } catch {}
  }

  useEffect(() => { load(); }, []);

  async function handleSet() {
    const k = parseFloat(input);
    if (isNaN(k) || k < 0.1 || k > 1.0) {
      setMsg("0.1~1.0 사이 값을 입력하세요");
      return;
    }
    setLoading(true);
    setMsg("");
    try {
      await api.setK(k);
      setMsg(`k값 → ${k} 변경 요청 완료 (5초 내 적용)`);
      setInput("");
      await load();
    } catch (e) {
      setMsg(String(e));
    }
    setLoading(false);
  }

  return (
    <div className="rounded-lg bg-gray-900 border border-gray-800 p-4 space-y-3">
      <p className="text-xs text-gray-500">돌파계수 (k값)</p>

      <div className="flex gap-4 text-sm">
        <div>
          <span className="text-gray-500 text-xs">현재 적용값</span>
          <p className="font-bold text-lg">{currentK !== null ? currentK : "—"}</p>
        </div>
        {pendingK !== null && (
          <div>
            <span className="text-yellow-500 text-xs">변경 대기중</span>
            <p className="font-bold text-lg text-yellow-400">{pendingK}</p>
          </div>
        )}
      </div>

      <div className="flex gap-2">
        <input
          type="number"
          min={0.1}
          max={1.0}
          step={0.05}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSet()}
          placeholder="0.1 ~ 1.0"
          className="w-28 bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        />
        <button
          onClick={handleSet}
          disabled={loading}
          className="px-3 py-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 rounded text-sm font-medium"
        >
          변경
        </button>
      </div>

      {msg && <p className="text-xs text-blue-300">{msg}</p>}
    </div>
  );
}
