import { useEffect, useState } from 'react'
import type { StockRow, Thresholds } from './types'

// ---------------------------------------------------------------- rules & presets
export interface RuleDef {
  step: number
  key: keyof Omit<Thresholds, 'ignore_specials'>
  title: string
  metric: string
  explain: string
  op: '≥' | '≤' | '>'
  min: number
  max: number
  stepSize: number
  unit: string
}

export const RULES: RuleDef[] = [
  { step: 1, key: 'yield_min', title: 'Pays a dividend', metric: 'Dividend yield', explain: 'Trailing-12-month dividends per share ÷ current price.', op: '≥', min: 0, max: 12, stepSize: 0.25, unit: '%' },
  { step: 2, key: 'payout_max', title: 'Can afford it', metric: 'Payout ratio', explain: 'TTM dividends per share ÷ TTM diluted EPS. Stocks with EPS ≤ 0 fail.', op: '≤', min: 10, max: 200, stepSize: 5, unit: '%' },
  { step: 3, key: 'fcf_min', title: 'Has the cash', metric: 'Free cash flow', explain: 'Operating cash flow − capital expenditures (TTM; falls back to latest fiscal year).', op: '>', min: -1000, max: 10000, stepSize: 50, unit: '$M' },
  { step: 4, key: 'paid_years_min', title: 'Pays reliably', metric: 'Years paid in a row', explain: 'Consecutive calendar years with dividends > 0, counting back from the last completed year.', op: '≥', min: 0, max: 40, stepSize: 1, unit: 'yrs' },
  { step: 5, key: 'growth_years_min', title: 'Pays more each year', metric: 'Years of growth in a row', explain: "Consecutive calendar years where the annual dividend total beats the prior year's.", op: '≥', min: 0, max: 40, stepSize: 1, unit: 'yrs' },
]

export const DEFAULT_THRESHOLDS: Thresholds = {
  yield_min: 3, payout_max: 70, fcf_min: 0, paid_years_min: 5, growth_years_min: 5, ignore_specials: true,
}

export const PRESETS: { name: string; th: Thresholds }[] = [
  { name: 'Default (video)', th: DEFAULT_THRESHOLDS },
  { name: 'Relaxed', th: { ...DEFAULT_THRESHOLDS, yield_min: 2, payout_max: 80, paid_years_min: 3, growth_years_min: 3 } },
]

export function sameThresholds(a: Thresholds, b: Thresholds): boolean {
  return (Object.keys(a) as (keyof Thresholds)[]).every((k) => a[k] === b[k])
}

/** The UI edits FCF in $M; the API takes dollars. */
export function toApi(th: Thresholds): Thresholds {
  return { ...th, fcf_min: th.fcf_min * 1e6 }
}

// ---------------------------------------------------------------- hooks
export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}

export function useLocalStorage<T>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key)
      return raw ? ({ ...initial, ...JSON.parse(raw) } as T) : initial
    } catch {
      return initial
    }
  })
  const set = (nv: T) => {
    setV(nv)
    try {
      localStorage.setItem(key, JSON.stringify(nv))
    } catch {
      /* storage unavailable */
    }
  }
  return [v, set]
}

// ---------------------------------------------------------------- formatting
export const fmtInt = (n: number | null | undefined) => (n == null ? '—' : n.toLocaleString('en-US'))
export const fmtPct = (n: number | null | undefined, d = 2) => (n == null ? '—' : `${n.toFixed(d)}%`)
export const fmtPrice = (n: number | null | undefined) => (n == null ? '—' : `$${n.toFixed(2)}`)

export function fmtMoney(n: number | null | undefined): string {
  if (n == null) return '—'
  const a = Math.abs(n)
  const s = n < 0 ? '−' : ''
  if (a >= 1e12) return `${s}$${(a / 1e12).toFixed(2)}T`
  if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(1)}B`
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(0)}M`
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(0)}K`
  return `${s}$${a.toFixed(0)}`
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const d = new Date(iso)
  return d.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })
}

// ---------------------------------------------------------------- CSV
export function downloadCsv(rows: StockRow[], filename: string): void {
  const cols: (keyof StockRow)[] = ['ticker', 'name', 'sector', 'industry', 'price', 'yield', 'payout', 'fcf', 'paid_years', 'growth_years', 'market_cap', 'dps_ttm', 'eps_ttm']
  const esc = (v: unknown) => {
    if (v == null) return ''
    const s = String(v)
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const csv = [cols.join(','), ...rows.map((r) => cols.map((c) => esc(r[c])).join(','))].join('\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
