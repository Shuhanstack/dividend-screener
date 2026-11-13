import { staticApi } from './staticApi'
import type { EliminatedResponse, Meta, PriceHistory, ScreenResponse, StockDetail, Thresholds, WatchItem } from './types'

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

const serverApi = {
  screen: (th: Thresholds, signal?: AbortSignal) => get<ScreenResponse>(`/api/screen?${qs(th)}`, signal),
  eliminated: (th: Thresholds, step: number, signal?: AbortSignal) =>
    get<EliminatedResponse>(`/api/screen/eliminated?${qs(th, { step, limit: 1000 })}`, signal),
  stock: (ticker: string, th: Thresholds, signal?: AbortSignal) =>
    get<StockDetail>(`/api/stock/${encodeURIComponent(ticker)}?${qs(th)}`, signal),
  prices: (ticker: string, signal?: AbortSignal) =>
    get<PriceHistory>(`/api/stock/${encodeURIComponent(ticker)}/prices`, signal),
  meta: () => get<Meta>('/api/meta'),
  watchlist: (th: Thresholds, signal?: AbortSignal) => get<{ items: WatchItem[] }>(`/api/watchlist?${qs(th)}`, signal),
  watch: async (ticker: string, on: boolean): Promise<void> => {
    const r = await fetch(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: on ? 'POST' : 'DELETE' })
    if (!r.ok) throw new Error(`${r.status}`)
  },
}

/** VITE_STATIC=1 builds a browser-only app that reads the exported snapshot (GitHub Pages). */
export const isStatic = import.meta.env.VITE_STATIC === '1'
export const api: typeof serverApi = isStatic ? staticApi : serverApi
