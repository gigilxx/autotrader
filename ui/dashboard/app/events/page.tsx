"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

const LEVEL_COLOR: Record<string, string> = {
  ERROR:    "text-red-400",
  CRITICAL: "text-red-400",
  WARNING:  "text-yellow-400",
};

const KEYWORD_COLOR: Array<[string, string]> = [
  ["진입",          "text-green-400"],
  ["청산",          "text-blue-400"],
  ["trailing_stop", "text-orange-400"],
  ["force_close",   "text-orange-400"],
  ["manual_close",  "text-orange-400"],
  ["킬스위치",       "text-red-400"],
  ["시장 필터",      "text-purple-400"],
  ["리포트",        "text-cyan-400"],
];

function lineColor(line: string): string {
  for (const [lvl, cls] of Object.entries(LEVEL_COLOR)) {
    if (line.includes(lvl)) return cls;
  }
  for (const [kw, cls] of KEYWORD_COLOR) {
    if (line.includes(kw)) return cls;
  }
  return "text-gray-300";
}

export default function EventsPage() {
  const [lines, setLines] = useState<string[]>([]);
  const [note, setNote]   = useState("");
  const [error, setError] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(() => {
    api.importantLogs(200)
      .then((r) => {
        setLines(r.lines);
        setNote(r.note ?? "");
        setError("");
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines, autoScroll]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">주요 이벤트</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            WARNING 이상 · 진입/청산/킬스위치/리포트 등 — 10초 자동 갱신
          </p>
        </div>
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

      {/* 색상 범례 */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
        <span className="text-green-400">● 진입</span>
        <span className="text-blue-400">● 청산</span>
        <span className="text-orange-400">● 손절/강제청산</span>
        <span className="text-red-400">● 킬스위치/에러</span>
        <span className="text-yellow-400">● 경고</span>
        <span className="text-purple-400">● 시장필터</span>
        <span className="text-cyan-400">● 리포트</span>
      </div>

      {error && (
        <div className="rounded bg-red-900/40 border border-red-700 px-4 py-2 text-red-300 text-sm">
          {error}
        </div>
      )}

      <div className="rounded-lg bg-gray-900 border border-gray-800 p-4 h-[70vh] overflow-y-auto font-mono text-xs">
        {note && lines.length === 0 ? (
          <p className="text-gray-500 text-center py-12">{note}</p>
        ) : lines.length === 0 ? (
          <p className="text-gray-500 text-center py-12">이벤트 없음</p>
        ) : (
          lines.map((line, i) => (
            <div key={i} className={`leading-5 ${lineColor(line)}`}>
              {line}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
