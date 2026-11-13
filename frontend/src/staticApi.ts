/**
 * Browser-only backend used by the static (GitHub Pages) build.
 * Mirrors backend/app/screen.py over the exported snapshot in /data.
 * Watchlist lives in localStorage.
 */
import type {
  EliminatedResponse, FunnelStep, Meta, Outcome, PriceHistory, RuleCheck, ScreenResponse, StockDetail, StockRow, Thresholds, WatchItem,
} from './types'

export type Raw = Record<string, number | string | null>

interface Snapshot {
  meta: Meta
  columns: string[]
  rows: (number | string | null)[][]
}

interface Detail {
  last_completed_year?: number
  annual_all?: Record<string, number>
  annual_reg?: Record<string, number>
  specials?: [string, number][]
  splits?: [string, number][]
  eps_history?: Record<string, number>
  fcf_history?: Record<string, number>
  fundamentals_skipped?: boolean
  stale_since?: Record<string, string>
  fetched_at?: string | null
  fetch_error?: string | null
}

// ------------------------------------------------------------------ rules (pure)
const v = (r: Raw, base: string, th: Thresholds) => r[`${base}_${th.ignore_specials ? 'reg' : 'all'}`] as number | null

type RuleFn = (r: Raw, th: Thresholds) => Outcome
const PRICE_RULE: [number, string, RuleFn] = [6, 'Price held up', (r, th) => {
  const ch = r.price_change_3y as number | null
  return ch == null ? 'missing' : ch >= -th.price_drop_max ? 'pass' : 'fail'
}]

const BASE_RULES: [number, string, RuleFn][] = [
  [1, 'Pays a dividend', (r, th) => {
    if (!r.has_data) return 'missing'
    const y = v(r, 'yield', th)
    return y == null ? 'missing' : y >= th.yield_min ? 'pass' : 'fail'
  }],
  [2, 'Can afford it', (r, th) => {
    const eps = r.eps_ttm as number | null
    if (eps == null) return 'missing'
    if (eps <= 0) return 'fail'
    const p = v(r, 'payout', th)
    return p == null ? 'missing' : p <= th.payout_max ? 'pass' : 'fail'
  }],
  [3, 'Has the cash', (r, th) => {
    const f = r.fcf as number | null
    return f == null ? 'missing' : f > th.fcf_min ? 'pass' : 'fail'
  }],
  [4, 'Pays reliably', (r, th) => {
    const n = v(r, 'paid_years', th)
    return !r.has_data || n == null ? 'missing' : n >= th.paid_years_min ? 'pass' : 'fail'
  }],
  [5, 'Pays more each year', (r, th) => {
    const n = v(r, 'growth_years', th)
    return !r.has_data || n == null ? 'missing' : n >= th.growth_years_min ? 'pass' : 'fail'
  }],
]

/** The 5 dividend rules, plus rule 6 when the price filter is on (mirrors screen.active_rules). */
const rulesFor = (th: Thresholds): [number, string, RuleFn][] => (th.price_filter ? [...BASE_RULES, PRICE_RULE] : BASE_RULES)

function firstFailure(r: Raw, th: Thresholds): [number, Outcome] | null {
  for (const [step, , fn] of rulesFor(th)) {
    const o = fn(r, th)
    if (o !== 'pass') return [step, o]
  }
  return null
}

export function publicRow(r: Raw, th: Thresholds): StockRow {
  return {
    ticker: r.ticker as string,
    name: r.name as string | null,
    sector: r.sector as string | null,
    industry: r.industry as string | null,
    price: r.price as number | null,
    market_cap: r.market_cap as number | null,
    dps_ttm: v(r, 'dps_ttm', th),
    yield: v(r, 'yield', th),
    eps_ttm: r.eps_ttm as number | null,
    payout: v(r, 'payout', th),
    fcf: r.fcf as number | null,
    fcf_source: r.fcf_source as string | null,
    paid_years: v(r, 'paid_years', th),
    growth_years: v(r, 'growth_years', th),
    price_change_3y: r.price_change_3y as number | null,
    has_special: Boolean(r.has_special),
    has_data: Boolean(r.has_data),
    data_as_of: r.data_as_of as string | null,
    stale: r.stale ? (JSON.parse(r.stale as string) as string[]) : [],
  }
}

export function runScreen(rows: Raw[], th: Thresholds): ScreenResponse {
  const funnel: FunnelStep[] = [{ step: 0, label: 'Universe', remaining: rows.length, failed: 0, failed_missing_data: 0 }]
  let survivors = rows
  for (const [step, label, fn] of rulesFor(th)) {
    const next: Raw[] = []
    let missing = 0
    let failed = 0
    for (const r of survivors) {
      const o = fn(r, th)
      if (o === 'pass') next.push(r)
      else if (o === 'missing') missing++
      else failed++
    }
    funnel.push({ step, label, remaining: next.length, failed: failed + missing, failed_missing_data: missing })
    survivors = next
  }
  const results = survivors.map((r) => publicRow(r, th)).sort((a, b) => (b.yield ?? 0) - (a.yield ?? 0))
  return { funnel, results }
}

function checks(r: Raw, th: Thresholds): RuleCheck[] {
  const values: Record<number, number | null> = {
    1: v(r, 'yield', th), 2: v(r, 'payout', th), 3: r.fcf as number | null, 4: v(r, 'paid_years', th), 5: v(r, 'growth_years', th),
    6: r.price_change_3y as number | null,
  }
  const thr: Record<number, number> = {
    1: th.yield_min, 2: th.payout_max, 3: th.fcf_min, 4: th.paid_years_min, 5: th.growth_years_min, 6: -th.price_drop_max,
  }
  return rulesFor(th).map(([step, label, fn]) => ({ step, label, outcome: fn(r, th), value: values[step] ?? null, threshold: thr[step] ?? 0 }))
}

// ------------------------------------------------------------------ data loading
const base = () => import.meta.env.BASE_URL
let snapshot: Promise<{ meta: Meta; rows: Raw[] }> | null = null
let details: Promise<Record<string, Detail>> | null = null

export function rowsFromSnapshot(s: Snapshot): Raw[] {
  return s.rows.map((arr) => Object.fromEntries(s.columns.map((c, i) => [c, arr[i] ?? null])))
}

function load() {
  snapshot ??= fetch(`${base()}data/screen.json`).then(async (r) => {
    if (!r.ok) throw new Error(`snapshot ${r.status}`)
    const s = (await r.json()) as Snapshot
    return { meta: s.meta, rows: rowsFromSnapshot(s) }
  })
  return snapshot
}

function loadDetails() {
  details ??= fetch(`${base()}data/details.json`).then((r) => r.json() as Promise<Record<string, Detail>>)
  return details
}

// ------------------------------------------------------------------ watchlist (localStorage)
const WKEY = 'divscreen.watchlist'
function readWatch(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(WKEY) ?? '{}') as Record<string, string>
  } catch {
    return {}
  }
}
function writeWatch(w: Record<string, string>) {
  try {
    localStorage.setItem(WKEY, JSON.stringify(w))
  } catch {
    /* storage unavailable */
  }
}

// ------------------------------------------------------------------ API surface
export const staticApi = {
  async screen(th: Thresholds): Promise<ScreenResponse> {
    const { rows } = await load()
    const out = runScreen(rows, th)
    const w = readWatch()
    for (const r of out.results) r.watched = r.ticker in w
    return out
  },
  async eliminated(th: Thresholds, step: number): Promise<EliminatedResponse> {
    const { rows } = await load()
    const items: StockRow[] = []
    for (const r of rows) {
      const ff = firstFailure(r, th)
      if (ff && ff[0] === step) items.push({ ...publicRow(r, th), missing_data: ff[1] === 'missing' })
    }
    items.sort((a, b) => (b.market_cap ?? 0) - (a.market_cap ?? 0))
    return { step, total: items.length, missing_data: items.filter((i) => i.missing_data).length, items: items.slice(0, 1000) }
  },
  async stock(ticker: string, th: Thresholds): Promise<StockDetail> {
    const [{ rows }, det] = await Promise.all([load(), loadDetails()])
    const t = ticker.toUpperCase()
    const r = rows.find((x) => x.ticker === t)
    if (!r) throw new Error(`${t} not found`)
    const d = det[t] ?? {}
    const toList = (o?: Record<string, number>) =>
      Object.entries(o ?? {}).map(([y, total]) => ({ year: Number(y), total })).sort((a, b) => a.year - b.year)
    return {
      ...publicRow(r, th),
      checks: checks(r, th),
      annual_dividends: toList(th.ignore_specials ? d.annual_reg : d.annual_all),
      annual_dividends_all: toList(d.annual_all),
      specials: d.specials ?? [],
      recent_payments: [],
      splits: d.splits ?? [],
      eps_history: d.eps_history ?? {},
      fcf_history: d.fcf_history ?? {},
      last_completed_year: d.last_completed_year ?? null,
      fundamentals_skipped: d.fundamentals_skipped ?? false,
      stale_since: d.stale_since ?? {},
      fetched_at: d.fetched_at ?? null,
      fetch_error: d.fetch_error ?? null,
      watched: t in readWatch(),
      yahoo_url: `https://finance.yahoo.com/quote/${t}`,
    }
  },
  async prices(ticker: string): Promise<PriceHistory> {
    const t = ticker.toUpperCase()
    const r = await fetch(`${base()}data/prices/${encodeURIComponent(t)}.json`)
    if (!r.ok) return { ticker: t, points: [] }
    const pts = (await r.json()) as [string, number][]
    return { ticker: t, points: pts.map(([date, close]) => ({ date, close })) }
  },
  async meta(): Promise<Meta> {
    return (await load()).meta
  },
  async watchlist(th: Thresholds): Promise<{ items: WatchItem[] }> {
    const { rows } = await load()
    const w = readWatch()
    const byT = new Map(rows.filter((r) => (r.ticker as string) in w).map((r) => [r.ticker as string, r]))
    const items: WatchItem[] = Object.keys(w).sort().map((t) => {
      const r = byT.get(t)
      if (!r) {
        return { ticker: t, name: null, sector: null, industry: null, price: null, market_cap: null, dps_ttm: null, yield: null, eps_ttm: null, payout: null, fcf: null, fcf_source: null, paid_years: null, growth_years: null, has_special: false, has_data: false, watched: true, added_at: w[t] ?? '', fails: [], missing: [] }
      }
      const res = rulesFor(th).map(([s, , fn]) => [s, fn(r, th)] as const)
      return {
        ...publicRow(r, th), watched: true, added_at: w[t] ?? '',
        fails: res.filter(([, o]) => o === 'fail').map(([s]) => s),
        missing: res.filter(([, o]) => o === 'missing').map(([s]) => s),
        first_failure: firstFailure(r, th)?.[0] ?? null,
      }
    })
    return { items }
  },
  async watch(ticker: string, on: boolean): Promise<void> {
    const w = readWatch()
    if (on) w[ticker.toUpperCase()] = new Date().toISOString()
    else delete w[ticker.toUpperCase()]
    writeWatch(w)
  },
}
