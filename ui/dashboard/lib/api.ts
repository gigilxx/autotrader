const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const SECRET = process.env.NEXT_PUBLIC_API_SECRET ?? "";

export interface BotStatus {
  date: string;
  is_killed: boolean;
  trades_today: number;
  realized_pnl: number;
  position_count: number;
  positions: Position[];
  error?: string;
}

export interface Position {
  symbol: string;
  entry_price: number;
  qty: number;
}

export interface Trade {
  exit_time: string;
  symbol: string;
  entry_price: number;
  exit_price: number;
  qty: number;
  pnl: number;
  reason: string;
}

export interface PnlToday {
  date: string;
  trades_today: number;
  realized_pnl: number;
}

async function _get<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json() as Promise<T>;
}

async function _post(path: string): Promise<{ ok: boolean; message: string }> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (SECRET) headers["Authorization"] = `Bearer ${SECRET}`;
  const res = await fetch(`${API}${path}`, { method: "POST", headers });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

export const api = {
  status: ()   => _get<BotStatus>("/status"),
  positions: () => _get<{ positions: Position[] }>("/positions"),
  pnlToday: () => _get<PnlToday>("/pnl/today"),
  trades: ()   => _get<{ trades: Trade[] }>("/trades"),
  logs: (n = 50) => _get<{ lines: string[] }>(`/logs?n=${n}`),
  importantLogs: (n = 200) => _get<{ lines: string[]; note?: string }>(`/important-logs?n=${n}`),
  kill:   ()   => _post("/kill"),
  resume: ()   => _post("/resume"),
  closePosition: (symbol: string) => _post(`/positions/${symbol}/close`),
  wsUrl: ()    => `${API.replace(/^http/, "ws")}/ws/status`,
};
