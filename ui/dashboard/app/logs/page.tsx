"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

export default function LogsPage() {
  const [lines, setLines] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(() => {
    api.logs(100)
      .then((r) => setLines(r.lines))
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines, autoScroll]);

  function levelColor(line: string) {
    if (line.includes("ERROR") || line.includes("CRITICAL")) return "text-red-400";
    if (line.includes("WARNING")) return "text-yellow-400";
    if (line.includes("진입") || line.includes("청산")) return "text-green-400";
    return "text-gray-300";
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">로그</h1>
        <div className="flex gap-3 text-sm">
          <label className="flex items-center gap-1 text-gray-400 cursor-pointer">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="accent-blue-500"
            />
            자동 스크롤
          </label>
          <button onClick={refresh} className="text-gray-400 hover:text-gray-200">
            새로고침
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded bg-red-900/40 border border-red-700 px-4 py-2 text-red-300 text-sm">
          {error}
        </div>
      )}

      <div className="rounded-lg bg-gray-900 border border-gray-800 p-4 h-[70vh] overflow-y-auto font-mono text-xs">
        {lines.length === 0 ? (
          <p className="text-gray-500 text-center py-12">로그 없음</p>
        ) : (
          lines.map((line, i) => (
            <div key={i} className={`leading-5 ${levelColor(line)}`}>
              {line}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
