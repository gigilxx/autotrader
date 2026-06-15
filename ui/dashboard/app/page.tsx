"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type BotStatus } from "@/lib/api";
import { KillSwitchButton } from "@/components/KillSwitchButton";
import { PositionCard } from "@/components/PositionCard";
import { StatusBadge } from "@/components/StatusBadge";

export default function DashboardPage() {
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [error, setError] = useState("");
  const wsRef = useRef<WebSocket | null>(null);

  const refresh = useCallback(async () => {
    try {
      const s = await api.status();
      setStatus(s);
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();

    // WebSocket 실시간 상태 수신
    function connect() {
      const ws = new WebSocket(api.wsUrl());
      wsRef.current = ws;
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as BotStatus;
          setStatus(data);
          setError("");
        } catch {}
      };
      ws.onerror = () => setError("WebSocket 연결 오류 — REST 폴링으로 전환");
      ws.onclose = () => {
        // 재연결
        setTimeout(connect, 5000);
      };
    }
    connect();

    return () => { wsRef.current?.close(); };
  }, [refresh]);

  const pnlColor = status && status.realized_pnl > 0
    ? "text-green-400"
    : status && status.realized_pnl < 0
    ? "text-red-400"
    : "text-gray-100";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">대시보드</h1>
        <button onClick={refresh} className="text-xs text-gray-400 hover:text-gray-200">
          새로고침
        </button>
      </div>

      {error && (
        <div className="rounded bg-red-900/40 border border-red-700 px-4 py-2 text-red-300 text-sm">
          {error}
        </div>
      )}

      {status ? (
        <>
          {/* 상태 + 킬스위치 */}
          <div className="rounded-xl bg-gray-900 border border-gray-800 p-5 flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div className="space-y-2">
              <StatusBadge isKilled={status.is_killed} />
              <p className="text-sm text-gray-400">{status.date}</p>
            </div>
            <KillSwitchButton isKilled={status.is_killed} onDone={refresh} />
          </div>

          {/* 손익 요약 */}
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <StatCard
              label="오늘 실현손익"
              value={`${status.realized_pnl >= 0 ? "+" : ""}${status.realized_pnl.toLocaleString()}원`}
              className={pnlColor}
            />
            <StatCard label="거래 횟수" value={`${status.trades_today}건`} />
            <StatCard label="보유 포지션" value={`${status.position_count}개`} />
          </div>

          {/* 포지션 카드 */}
          {status.positions.length > 0 && (
            <section>
              <h2 className="text-sm font-semibold text-gray-400 mb-2">보유 포지션</h2>
              <div className="grid gap-3 md:grid-cols-2">
                {status.positions.map((p) => (
                  <PositionCard key={p.symbol} position={p} onClose={refresh} />
                ))}
              </div>
            </section>
          )}
        </>
      ) : (
        <div className="text-gray-500 text-center py-12">데이터 로딩 중...</div>
      )}
    </div>
  );
}

function StatCard({ label, value, className = "" }: { label: string; value: string; className?: string }) {
  return (
    <div className="rounded-lg bg-gray-900 border border-gray-800 p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-xl font-bold ${className}`}>{value}</p>
    </div>
  );
}
