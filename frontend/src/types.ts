export interface Thresholds {
  yield_min: number
  payout_max: number
  fcf_min: number
  paid_years_min: number
  growth_years_min: number
  ignore_specials: boolean
}

export interface FunnelStep {
  step: number
  label: string
  remaining: number
  failed: number
  failed_missing_data: number
}

export interface StockRow {
  ticker: string
  name: string | null
  sector: string | null
  industry: string | null
  price: number | null
  market_cap: number | null
  dps_ttm: number | null
  yield: number | null
  eps_ttm: number | null
  payout: number | null
  fcf: number | null
  fcf_source: string | null
  paid_years: number | null
  growth_years: number | null
  has_special: boolean
  has_data: boolean
  watched?: boolean
  missing_data?: boolean
  /** when this stock's data was last fetched successfully */
  data_as_of?: string | null
  /** ["all"] = not refreshed in the latest run; otherwise fields carried over from an older fetch */
  stale?: string[]
}

export interface ScreenResponse {
  funnel: FunnelStep[]
  results: StockRow[]
}

export interface EliminatedResponse {
  step: number
  total: number
  missing_data: number
  items: StockRow[]
}

export type Outcome = 'pass' | 'fail' | 'missing'

export interface RuleCheck {
  step: number
  label: string
  outcome: Outcome
  value: number | null
  threshold: number
}

export interface StockDetail extends StockRow {
  checks: RuleCheck[]
  annual_dividends: { year: number; total: number }[]
  annual_dividends_all: { year: number; total: number }[]
  specials: [string, number][]
  recent_payments: [string, number][]
  splits: [string, number][]
  eps_history: Record<string, number>
  fcf_history: Record<string, number>
  last_completed_year: number | null
  fundamentals_skipped: boolean
  stale_since?: Record<string, string>
  fetched_at: string | null
  fetch_error: string | null
  yahoo_url: string
}

export interface PriceHistory {
  ticker: string
  points: { date: string; close: number }[]
  source?: string
  error?: string | null
}

export interface WatchItem extends StockRow {
  added_at: string
  fails: number[]
  missing: number[]
  first_failure?: number | null
}

export interface Meta {
  last_refresh: string | null
  as_of: string | null
  provider: string | null
  fixtures_mode: boolean
  universe_size: number
  screened: number
  fetch_errors: number
  stale_count?: number
  not_refreshed_count?: number
  error_tickers: { ticker: string; error: string; fetched_at: string }[]
}
