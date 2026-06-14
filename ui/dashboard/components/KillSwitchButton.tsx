"use client";

import { useState } from "react";
import { api } from "@/lib/api";

interface Props {
  isKilled: boolean;
  onDone: () => void;
}

export function KillSwitchButton({ isKilled, onDone }: Props) {
  const [confirming, setConfirming] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleKill() {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    setLoading(true);
    setError("");
    try {
      await api.kill();
      setConfirming(false);
      onDone();
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleResume() {
    setLoading(true);
    setError("");
    try {
      await api.resume();
      onDone();
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  if (isKilled) {
    return (
      <div className="flex flex-col gap-2">
        <button
          onClick={handleResume}
          disabled={loading}
          className="px-4 py-2 rounded bg-green-700 hover:bg-green-600 disabled:opacity-50 font-semibold text-sm"
        >
          {loading ? "처리 중..." : "✅ 킬스위치 해제"}
        </button>
        {error && <p className="text-red-400 text-xs">{error}</p>}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {confirming && (
        <p className="text-yellow-300 text-sm font-medium">
          ⚠️ 정말 킬스위치를 작동하시겠습니까? 한 번 더 누르면 실행됩니다.
        </p>
      )}
      <div className="flex gap-2">
        <button
          onClick={handleKill}
          disabled={loading}
          className={`px-4 py-2 rounded font-semibold text-sm disabled:opacity-50 ${
            confirming
              ? "bg-red-600 hover:bg-red-500 animate-pulse"
              : "bg-red-900 hover:bg-red-800"
          }`}
        >
          {loading ? "처리 중..." : confirming ? "⛔ 확인: 킬스위치 작동" : "⛔ 킬스위치"}
        </button>
        {confirming && (
          <button
            onClick={() => setConfirming(false)}
            className="px-4 py-2 rounded bg-gray-700 hover:bg-gray-600 text-sm"
          >
            취소
          </button>
        )}
      </div>
      {error && <p className="text-red-400 text-xs">{error}</p>}
    </div>
  );
}
