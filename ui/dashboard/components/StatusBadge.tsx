"use client";

interface Props {
  isKilled: boolean;
}

export function StatusBadge({ isKilled }: Props) {
  return isKilled ? (
    <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-red-900 text-red-300 text-sm font-semibold">
      ⛔ 킬스위치 ON
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-green-900 text-green-300 text-sm font-semibold">
      🟢 실행 중
    </span>
  );
}
