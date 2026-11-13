import type { EliminatedResponse, Meta, ScreenResponse, StockDetail, Thresholds, WatchItem } from './types'

function qs(th: Thresholds, extra: Record<string, string | number> = {}): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries({ ...th, ...extra })) p.set(k, String(v))
  return p.toString()
}

async function get<T>(url: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(url, { signal })
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return (await r.json()) as T
}

export const api = {
  screen: (th: Thresholds, signal?: AbortSignal) => get<ScreenResponse>(`/api/screen?${qs(th)}`, signal),
  eliminated: (th: Thresholds, step: number, signal?: AbortSignal) =>
    get<EliminatedResponse>(`/api/screen/eliminated?${qs(th, { step, limit: 1000 })}`, signal),
  stock: (ticker: string, th: Thresholds, signal?: AbortSignal) =>
    get<StockDetail>(`/api/stock/${encodeURIComponent(ticker)}?${qs(th)}`, signal),
  meta: () => get<Meta>('/api/meta'),
  watchlist: (th: Thresholds, signal?: AbortSignal) => get<{ items: WatchItem[] }>(`/api/watchlist?${qs(th)}`, signal),
  watch: async (ticker: string, on: boolean): Promise<void> => {
    const r = await fetch(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: on ? 'POST' : 'DELETE' })
    if (!r.ok) throw new Error(`${r.status}`)
  },
}
