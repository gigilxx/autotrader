"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

type CategoryId = "진입" | "청산" | "강제청산" | "에러" | "경고" | "시장필터" | "리포트" | "기타";

const CATEGORIES: {
  id: CategoryId;
  label: string;
  lineColor: string;
  activeClass: string;
}[] = [
  { id: "진입",     label: "진입",          lineColor: "text-green-400",  activeClass: "bg-green-900/40 border-green-600 text-green-300" },
  { id: "청산",     label: "청산",          lineColor: "text-blue-400",   activeClass: "bg-blue-900/40 border-blue-600 text-blue-300" },
  { id: "강제청산", label: "손절/강제청산",  lineColor: "text-orange-400", activeClass: "bg-orange-900/40 border-orange-600 text-orange-300" },
  { id: "에러",     label: "킬스위치/에러",  lineColor: "text-red-400",    activeClass: "bg-red-900/40 border-red-600 text-red-300" },
  { id: "경고",     label: "경고",          lineColor: "text-yellow-400", activeClass: "bg-yellow-900/40 border-yellow-600 text-yellow-300" },
  { id: "시장필터", label: "시장필터",       lineColor: "text-purple-400", activeClass: "bg-purple-900/40 border-purple-600 text-purple-300" },
  { id: "리포트",   label: "리포트",         lineColor: "text-cyan-400",   activeClass: "bg-cyan-900/40 border-cyan-600 text-cyan-300" },
  { id: "기타",     label: "기타",           lineColor: "text-gray-400",   activeClass: "bg-gray-800 border-gray-600 text-gray-300" },
];

const CAT_MAP = Object.fromEntries(CATEGORIES.map((c) => [c.id, c]));

function categorize(line: string): CategoryId {
  if (line.includes("ERROR") || line.includes("CRITICAL") || line.includes("킬스위치")) return "에러";
  if (line.includes("WARNING")) return "경고";
  if (line.includes("trailing_stop") || line.includes("force_close") || line.includes("manual_close")) return "강제청산";
  if (line.includes("청산")) return "청산";
  if (line.includes("진입")) return "진입";
  if (line.includes("시장 필터")) return "시장필터";
  if (line.includes("리포트")) return "리포트";
  return "기타";
}

export default function EventsPage() {
  const [lines, setLines] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);
  const [selected, setSelected] = useState<Set<CategoryId>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(() => {
    api.importantLogs()
      .then((r) => { setLines(r.lines); setNote(r.note ?? ""); setError(""); })
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

  function toggleCategory(id: CategoryId) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  const filtered = lines.filter(
    (line) => selected.size === 0 || selected.has(categorize(line))
  );

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">주요 이벤트</h1>
          <p className="text-xs text-gray-500 mt-0.5">당일 · 10초 자동 갱신</p>
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

      {/* 카테고리 필터 */}
      <div className="flex flex-wrap gap-2 items-center">
        {CATEGORIES.map((cat) => {
          const active = selected.has(cat.id);
          return (
            <button
              key={cat.id}
              onClick={() => toggleCategory(cat.id)}
              className={`px-3 py-1 rounded border text-xs font-medium transition-colors ${
                active
                  ? cat.activeClass
                  : "bg-gray-900 border-gray-700 text-gray-500 hover:border-gray-500 hover:text-gray-400"
              }`}
            >
              {cat.label}
            </button>
          );
        })}
        {selected.size > 0 && (
          <button
            onClick={() => setSelected(new Set())}
            className="px-3 py-1 rounded border border-gray-700 text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            전체 보기
          </button>
        )}
      </div>

      {error && (
        <div className="rounded bg-red-900/40 border border-red-700 px-4 py-2 text-red-300 text-sm">
          {error}
        </div>
      )}

      <div className="rounded-lg bg-gray-900 border border-gray-800 p-4 h-[70vh] overflow-y-auto font-mono text-xs">
        {note && filtered.length === 0 ? (
          <p className="text-gray-500 text-center py-12">{note}</p>
        ) : filtered.length === 0 ? (
          <p className="text-gray-500 text-center py-12">이벤트 없음</p>
        ) : (
          filtered.map((line, i) => {
            const cat = categorize(line);
            return (
              <div key={i} className={`leading-5 ${CAT_MAP[cat].lineColor}`}>
                {line}
              </div>
            );
          })
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
