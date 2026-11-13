import { useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import { PriceChart } from './PriceChart'
import { fieldLabel, fmtDate, fmtMoney, fmtPct, fmtPrice, fmtShortDate, RULES, staleText } from '../lib'
import type { Outcome, RuleCheck, StockDetail, Thresholds } from '../types'

interface Props {
  ticker: string
  th: Thresholds
  onClose: () => void
  onToggleStar: (ticker: string, on: boolean) => Promise<void>
}

const COLORS = { growth: '#047857', paid: '#6ee7b7', partial: '#cbd5e1', other: '#94a3b8' }

function fmtCheck(c: RuleCheck): string {
  if (c.value == null) return 'missing'
  switch (c.step) {
    case 1:
      return fmtPct(c.value)
    case 2:
      return fmtPct(c.value, 0)
    case 3:
      return fmtMoney(c.value)
    default:
      return `${c.value} yrs`
  }
}

function fmtThreshold(c: RuleCheck): string {
  const r = RULES[c.step - 1]
  if (!r) return ''
  const v = c.step === 3 ? fmtMoney(c.threshold) : c.step <= 2 ? `${c.threshold}%` : `${c.threshold} yrs`
  return `${r.op} ${v}`
}

const BADGE: Record<Outcome, string> = {
  pass: 'bg-emerald-100 text-emerald-800',
  fail: 'bg-red-100 text-red-700',
  missing: 'bg-amber-100 text-amber-800',
}

export function Drawer({ ticker, th, onClose, onToggleStar }: Props) {
  const [d, setD] = useState<StockDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    const ac = new AbortController()
    setErr(null)
    api.stock(ticker, th, ac.signal).then(setD).catch((e: unknown) => {
      if (!ac.signal.aborted) setErr(String(e))
    })
    return () => ac.abort()
  }, [ticker, th])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const ly = d?.last_completed_year ?? new Date().getFullYear() - 1
  const chart = (d?.annual_dividends ?? [])
    .filter((a) => a.year > ly - 15)
    .map((a) => {
      const inGrowth = d && d.growth_years != null && a.year <= ly && a.year > ly - d.growth_years
      const inPaid = d && d.paid_years != null && a.year <= ly && a.year > ly - d.paid_years
      const kind = a.year > ly ? 'partial' : inGrowth ? 'growth' : inPaid ? 'paid' : 'other'
      return { ...a, kind }
    })
  // fill gaps (years with no dividend) so missing years are visible
  const years = chart.map((c) => c.year)
  const filled = years.length
    ? Array.from({ length: Math.max(...years) - Math.min(ly - 14, ...years) + 1 }, (_, i) => Math.min(ly - 14, ...years) + i).map(
        (y) => chart.find((c) => c.year === y) ?? { year: y, total: 0, kind: 'other' },
      )
    : []

  const histYears = d ? [...new Set([...Object.keys(d.eps_history), ...Object.keys(d.fcf_history)])].sort() : []

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/30" onClick={onClose}>
      <aside
        className="h-full w-full max-w-2xl overflow-y-auto bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={`${ticker} details`}
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-slate-200 bg-white p-5">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-2xl font-bold text-slate-900">{ticker}</h2>
              {d && (
                <button
                  className={`text-xl ${d.watched ? 'text-amber-500' : 'text-slate-300 hover:text-amber-400'}`}
                  onClick={async () => {
                    await onToggleStar(ticker, !d.watched)
                    setD({ ...d, watched: !d.watched })
                  }}
                  aria-label="Toggle watchlist"
                >
                  {d.watched ? '★' : '☆'}
                </button>
              )}
            </div>
            <div className="text-sm text-slate-600">{d?.name ?? '…'}</div>
            <div className="text-xs text-slate-500">
              {[d?.sector, d?.industry].filter(Boolean).join(' · ')}
            </div>
          </div>
          <div className="flex items-center gap-3">
            {d && (
              <a href={d.yahoo_url} target="_blank" rel="noreferrer" className="text-sm text-emerald-700 underline hover:text-emerald-900">
                Yahoo Finance ↗
              </a>
            )}
            <button className="rounded-md px-2 text-2xl leading-none text-slate-400 hover:text-slate-700" onClick={onClose} aria-label="Close">
              ×
            </button>
          </div>
        </div>

        {err && <div className="m-5 rounded-md bg-red-50 p-3 text-sm text-red-700">Could not load {ticker}: {err}</div>}
        {!d && !err && <div className="p-5 text-sm text-slate-500">Loading…</div>}

        {d && (
          <div className="space-y-6 p-5">
            {staleText(d) && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                <span className="mr-1">⏱</span>
                {staleText(d)}
                {d.stale_since && Object.keys(d.stale_since).length > 0 && !d.stale?.includes('all') && (
                  <span className="block text-xs text-amber-800">
                    {Object.entries(d.stale_since).map(([f, at]) => `${fieldLabel(f)} as of ${fmtShortDate(at)}`).join(' · ')}
                  </span>
                )}
              </div>
            )}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                ['Price', fmtPrice(d.price)],
                ['TTM dividend', d.dps_ttm != null ? `$${d.dps_ttm.toFixed(3)}` : '—'],
                ['TTM EPS', d.eps_ttm != null ? `$${d.eps_ttm.toFixed(2)}` : '—'],
                ['Market cap', fmtMoney(d.market_cap)],
              ].map(([k, v]) => (
                <div key={k} className="rounded-lg bg-slate-50 p-3">
                  <div className="text-[11px] uppercase tracking-wide text-slate-500">{k}</div>
                  <div className="num font-semibold text-slate-900">{v}</div>
                </div>
              ))}
            </div>

            <PriceChart ticker={ticker} />

            <section>
              <h3 className="mb-2 font-semibold text-slate-900">Rule checks</h3>
              <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
                {d.checks.map((c) => (
                  <li key={c.step} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                    <span>
                      <span className="text-slate-500">Rule {c.step}</span> · {c.label}
                    </span>
                    <span className="flex items-center gap-3">
                      <span className="num text-slate-900">{fmtCheck(c)}</span>
                      <span className="num w-20 text-right text-xs text-slate-500">{fmtThreshold(c)}</span>
                      <span className={`w-16 rounded-full px-2 py-0.5 text-center text-xs font-medium ${BADGE[c.outcome]}`}>
                        {c.outcome === 'missing' ? 'no data' : c.outcome}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
              {d.fcf_source === 'fy' && <p className="mt-1 text-xs text-slate-500">FCF uses the latest fiscal year (TTM not available).</p>}
              {d.fundamentals_skipped && (
                <p className="mt-1 text-xs text-slate-500">No dividend in the last ~13 months, so fundamentals were not fetched.</p>
              )}
              {d.fetch_error && <p className="mt-1 text-xs text-red-600">Last fetch error: {d.fetch_error}</p>}
            </section>

            <section>
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-semibold text-slate-900">Annual dividends per share</h3>
                <div className="flex flex-wrap gap-3 text-xs text-slate-600">
                  <Legend color={COLORS.growth} label={`Growth streak (${d.growth_years ?? 0}y)`} />
                  <Legend color={COLORS.paid} label={`Paid streak (${d.paid_years ?? 0}y)`} />
                  <Legend color={COLORS.partial} label="Current year (partial)" />
                </div>
              </div>
              {filled.length === 0 ? (
                <div className="rounded-lg bg-slate-50 p-6 text-center text-sm text-slate-500">No dividend history.</div>
              ) : (
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={filled} margin={{ left: 0, right: 8, top: 8 }}>
                      <CartesianGrid vertical={false} stroke="#e2e8f0" />
                      <XAxis dataKey="year" tick={{ fontSize: 11 }} tickLine={false} />
                      <YAxis tick={{ fontSize: 11 }} tickFormatter={(v: number) => `$${v.toFixed(2)}`} width={52} axisLine={false} tickLine={false} />
                      <Tooltip formatter={(v: unknown) => [`$${Number(v).toFixed(4)}`, 'Dividends']} />
                      <Bar dataKey="total" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                        {filled.map((c) => (
                          <Cell key={c.year} fill={COLORS[c.kind as keyof typeof COLORS]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
              <p className="mt-1 text-xs text-slate-500">
                Split-adjusted. Streaks count back from {ly}
                {th.ignore_specials ? '; one-off special dividends are excluded.' : '; special dividends included.'}
              </p>
              {d.specials.length > 0 && (
                <p className="mt-1 text-xs text-amber-700">
                  Special dividends detected: {d.specials.map(([dt, a]) => `${dt} ($${a.toFixed(2)})`).join(', ')}
                </p>
              )}
              {d.splits.length > 0 && (
                <p className="mt-1 text-xs text-slate-500">Splits: {d.splits.slice(-4).map(([dt, r]) => `${dt} (${r}:1)`).join(', ')}</p>
              )}
            </section>

            {histYears.length > 0 && (
              <section>
                <h3 className="mb-2 font-semibold text-slate-900">Payout & FCF history (fiscal years)</h3>
                <table className="w-full text-sm">
                  <thead className="text-xs uppercase text-slate-500">
                    <tr>
                      <th className="py-1 text-left font-medium">Year</th>
                      <th className="py-1 text-right font-medium">Diluted EPS</th>
                      <th className="py-1 text-right font-medium">Dividends</th>
                      <th className="py-1 text-right font-medium">Payout</th>
                      <th className="py-1 text-right font-medium">Free cash flow</th>
                    </tr>
                  </thead>
                  <tbody className="num">
                    {histYears.map((y) => {
                      const eps = d.eps_history[y]
                      const div = d.annual_dividends.find((a) => String(a.year) === y)?.total
                      return (
                        <tr key={y} className="border-t border-slate-100">
                          <td className="py-1">{y}</td>
                          <td className="py-1 text-right">{eps != null ? `$${eps.toFixed(2)}` : '—'}</td>
                          <td className="py-1 text-right">{div != null ? `$${div.toFixed(2)}` : '—'}</td>
                          <td className="py-1 text-right">{eps != null && eps > 0 && div != null ? fmtPct((div / eps) * 100, 0) : '—'}</td>
                          <td className="py-1 text-right">{fmtMoney(d.fcf_history[y])}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                <p className="mt-1 text-xs text-slate-500">Fiscal-year payout uses calendar-year dividends, so it's approximate.</p>
              </section>
            )}

            <p className="text-xs text-slate-400">
              Data last fetched successfully {fmtDate(d.data_as_of)}
              {d.fetched_at && d.fetched_at !== d.data_as_of ? `; last attempt ${fmtDate(d.fetched_at)}` : ''}.
            </p>
          </div>
        )}
      </aside>
    </div>
  )
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
      {label}
    </span>
  )
}
