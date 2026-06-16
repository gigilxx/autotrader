const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
// POST 요청은 /api/proxy 를 경유 (서버 사이드에서 API_SECRET 처리)
const PROXY = "/api/proxy";

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

export interface MarketFilter {
  available: boolean;
  summary: string | null;
  ok: boolean | null;
  updated_at: string | null;
}

export interface KConfig {
  current_k: number | null;
  pending_k: number | null;
}

export interface EnvConfig {
  env: string;
  max_watchlist: number;
}

export interface StockInfo {
  code: string;
  name: string;
  market: string;
}

async function _get<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json() as Promise<T>;
}

async function _throwFromResponse(res: Response, path: string): Promise<never> {
  const body = await res.json().catch(() => ({}));
  throw new Error(body.detail ?? body.message ?? `${res.status} ${path}`);
}

async function _post(path: string): Promise<{ ok: boolean; message: string }> {
  const res = await fetch(`${PROXY}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) await _throwFromResponse(res, path);
  return res.json();
}

async function _postBody<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${PROXY}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) await _throwFromResponse(res, path);
  return res.json() as Promise<T>;
}

export const api = {
  status:        () => _get<BotStatus>("/status"),
  positions:     () => _get<{ positions: Position[] }>("/positions"),
  pnlToday:      () => _get<PnlToday>("/pnl/today"),
  trades:        () => _get<{ trades: Trade[] }>("/trades"),
  logs:          (n = 50) => _get<{ lines: string[] }>(`/logs?n=${n}`),
  importantLogs: (n = 200) => _get<{ lines: string[]; note?: string }>(`/important-logs?n=${n}`),
  kill:          () => _post("/kill"),
  resume:        () => _post("/resume"),
  closePosition: (symbol: string) => _post(`/positions/${symbol}/close`),
  forceEntry:    (symbol: string) => _post(`/positions/${symbol}/enter`),
  watchlist:     () => _get<{ symbols: string[] }>("/watchlist"),
  setWatchlist:  (symbols: string[]) => _postBody<{ ok: boolean; symbols: string[] }>("/watchlist", { symbols }),
  marketFilter:  () => _get<MarketFilter>("/market-filter"),
  getK:          () => _get<KConfig>("/config/k"),
  setK:          (k: number) => _postBody<{ ok: boolean; k: number }>("/config/k", { k }),
  envConfig:     () => _get<EnvConfig>("/config/env"),
  searchStocks:  (q: string) => _get<{ stocks: StockInfo[] }>(`/stocks/search?q=${encodeURIComponent(q)}`),
  stocksInfo:    (codes: string[]) => _get<{ info: Record<string, { name: string; market: string }> }>(`/stocks/info?codes=${codes.join(",")}`),
  wsUrl:         () => `${API.replace(/^http/, "ws")}/ws/status`,
};
