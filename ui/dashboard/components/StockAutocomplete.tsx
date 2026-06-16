"use client";

import { useEffect, useRef, useState } from "react";
import { api, type StockInfo } from "@/lib/api";

interface Props {
  onSelect: (stock: StockInfo) => void;
  disabled?: boolean;
  placeholder?: string;
}

export default function StockAutocomplete({ onSelect, disabled, placeholder }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<StockInfo[]>([]);
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!query.trim()) {
      setResults([]);
      setOpen(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const data = await api.searchStocks(query);
        setResults(data.stocks);
        setOpen(data.stocks.length > 0);
        setActiveIdx(-1);
      } catch {
        setResults([]);
        setOpen(false);
      }
    }, 200);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function selectItem(stock: StockInfo) {
    setQuery("");
    setResults([]);
    setOpen(false);
    onSelect(stock);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && activeIdx >= 0) {
      e.preventDefault();
      selectItem(results[activeIdx]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div ref={containerRef} className="relative flex-1">
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        onFocus={() => results.length > 0 && setOpen(true)}
        placeholder={placeholder ?? "종목코드 또는 종목명 검색 (예: 삼성전자, 005930)"}
        disabled={disabled}
        className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm font-mono focus:outline-none focus:border-blue-500 disabled:opacity-40 disabled:cursor-not-allowed"
      />
      {open && (
        <ul className="absolute z-50 top-full left-0 right-0 mt-1 bg-gray-800 border border-gray-700 rounded-lg shadow-xl max-h-56 overflow-y-auto">
          {results.map((s, i) => (
            <li
              key={s.code}
              onMouseDown={() => selectItem(s)}
              onMouseEnter={() => setActiveIdx(i)}
              className={`flex items-center justify-between px-3 py-2 cursor-pointer text-sm ${
                i === activeIdx ? "bg-blue-700/50" : "hover:bg-gray-700"
              }`}
            >
              <span className="font-mono font-semibold">{s.code}</span>
              <span className="text-gray-300 ml-3 truncate">{s.name}</span>
              <span className="text-xs text-gray-500 ml-2 shrink-0">{s.market}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
