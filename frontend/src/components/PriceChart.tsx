import { useEffect, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import { fmtPct, fmtShortDate } from '../lib'
import type { PriceHistory } from '../types'

const fmtMonth = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-US', { month: 'short', year: '2-digit' })

export function PriceChart({ ticker }: { ticker: string }) {
  const [data, setData] = useState<PriceHistory | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    const ac = new AbortController()
    setData(null)
    setErr(null)
    api
      .prices(ticker, ac.signal)
      .then(setData)
      .catch((e: unknown) => {
        if (!ac.signal.aborted) setErr(String(e))
      })
    return () => ac.abort()
  }, [ticker])

  const pts = data?.points ?? []
  const first = pts[0]
  const last = pts[pts.length - 1]
  const change = first && last && first.close > 0 ? ((last.close - first.close) / first.close) * 100 : null
  const up = (change ?? 0) >= 0
  const color = up ? '#047857' : '#dc2626'
  const closes = pts.map((p) => p.close)
  const lo = closes.length ? Math.min(...closes) : 0
  const hi = closes.length ? Math.max(...closes) : 0

  return (
    <section>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold text-slate-900">Price, last 3 years</h3>
        {change != null && first && (
          <div className="text-xs text-slate-600">
            <span className={`num font-semibold ${up ? 'text-emerald-700' : 'text-red-600'}`}>
              {up ? '+' : ''}
              {fmtPct(change, 1)}
            </span>{' '}
            since {fmtShortDate(first.date)} · range{' '}
            <span className="num">
              ${lo.toFixed(2)}–${hi.toFixed(2)}
            </span>
          </div>
        )}
      </div>
      {!data && !err && <div className="h-48 animate-pulse rounded-lg bg-slate-50" />}
      {(err || data?.error || (data && pts.length === 0)) && (
        <div className="rounded-lg bg-slate-50 p-6 text-center text-sm text-slate-500">
          No price history available{data?.error ? ` (${data.error})` : ''}.
        </div>
      )}
      {pts.length > 0 && (
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={pts} margin={{ left: 0, right: 8, top: 8 }}>
              <defs>
                <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity={0.25} />
                  <stop offset="100%" stopColor={color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="#e2e8f0" />
              <XAxis dataKey="date" tickFormatter={fmtMonth} tick={{ fontSize: 11 }} tickLine={false} minTickGap={40} />
              <YAxis
                domain={['auto', 'auto']}
                tick={{ fontSize: 11 }}
                tickFormatter={(v: number) => `$${v >= 100 ? v.toFixed(0) : v.toFixed(2)}`}
                width={56}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                labelFormatter={(l: unknown) => `Week of ${fmtShortDate(String(l))}`}
                formatter={(v: unknown) => [`$${Number(v).toFixed(2)}`, 'Close']}
              />
              <Area type="monotone" dataKey="close" stroke={color} strokeWidth={1.75} fill="url(#priceFill)" isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="mt-1 text-xs text-slate-500">Weekly closing price (split-adjusted, not adjusted for dividends).</p>
    </section>
  )
}
