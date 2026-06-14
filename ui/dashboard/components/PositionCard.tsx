"use client";

import type { Position } from "@/lib/api";

interface Props {
  position: Position;
}

export function PositionCard({ position }: Props) {
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
    </div>
  );
}
