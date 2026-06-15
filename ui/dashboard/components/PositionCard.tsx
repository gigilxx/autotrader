"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Position } from "@/lib/api";

interface Props {
  position: Position;
  onClose?: () => void;
}

export function PositionCard({ position, onClose }: Props) {
  const [step, setStep] = useState<"idle" | "confirm" | "loading">("idle");

  async function handleClose() {
    if (step === "idle") { setStep("confirm"); return; }
    setStep("loading");
    try {
      await api.closePosition(position.symbol);
      onClose?.();
    } catch (e) {
      alert(String(e));
    } finally {
      setStep("idle");
    }
  }

  return (
    <div className="rounded-lg bg-gray-800 border border-gray-700 p-4">
      <div className="flex justify-between items-start">
        <div>
          <p className="font-bold text-lg">{position.symbol}</p>
          <p className="text-sm text-gray-400">{position.qty}주</p>
        </div>
        <div className="text-right">
          <p className="text-sm text-gray-400">진입가</p>
          <p className="font-semibold">{position.entry_price.toLocaleString()}원</p>
        </div>
      </div>

      <div className="mt-3 flex justify-end gap-2">
        {step === "confirm" && (
          <button
            onClick={() => setStep("idle")}
            className="text-xs px-3 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
          >
            취소
          </button>
        )}
        <button
          onClick={handleClose}
          disabled={step === "loading"}
          className={`text-xs px-3 py-1 rounded font-semibold transition-colors ${
            step === "confirm"
              ? "bg-red-600 hover:bg-red-700 text-white"
              : "bg-gray-700 hover:bg-gray-600 text-gray-200"
          }`}
        >
          {step === "loading" ? "처리중…" : step === "confirm" ? "정말 청산?" : "청산"}
        </button>
      </div>
    </div>
  );
}
