import { useMemo, useState, type ReactNode } from 'react'
import { downloadCsv, fmtInt, fmtMoney, fmtPct, fmtPrice, staleText } from '../lib'
import type { StockRow } from '../types'

type SortKey = 'ticker' | 'name' | 'sector' | 'price' | 'yield' | 'payout' | 'fcf' | 'paid_years' | 'growth_years' | 'market_cap'

interface Props<T extends StockRow> {
  rows: T[]
  title: ReactNode
  csvName: string
  onRowClick: (ticker: string) => void
  onToggleStar: (row: T) => void
  extra?: { header: string; render: (row: T) => ReactNode }
  empty?: ReactNode
  initialSort?: SortKey
}

const COLS: { key: SortKey; label: string; num?: boolean; render: (r: StockRow) => ReactNode }[] = [
  {
    key: 'ticker',
    label: 'Ticker',
    render: (r) => {
      const why = staleText(r)
      return (
        <span className="font-semibold text-slate-900">
          {r.ticker}
          {why && (
            <span className="ml-1 cursor-help text-xs text-amber-600" title={why} aria-label={why}>
              ⏱
            </span>
          )}
        </span>
      )
    },
  },
  { key: 'name', label: 'Name', render: (r) => <span className="line-clamp-1 max-w-[16rem]" title={r.name ?? ''}>{r.name ?? '—'}</span> },
  { key: 'sector', label: 'Sector', render: (r) => <span className="text-slate-600">{r.sector ?? '—'}</span> },
  { key: 'price', label: 'Price', num: true, render: (r) => fmtPrice(r.price) },
  { key: 'yield', label: 'Yield', num: true, render: (r) => fmtPct(r.yield) },
  { key: 'payout', label: 'Payout', num: true, render: (r) => fmtPct(r.payout, 0) },
  { key: 'fcf', label: 'FCF', num: true, render: (r) => <span className={r.fcf != null && r.fcf < 0 ? 'text-red-600' : ''}>{fmtMoney(r.fcf)}</span> },
  { key: 'paid_years', label: 'Paid yrs', num: true, render: (r) => fmtInt(r.paid_years) },
  { key: 'growth_years', label: 'Growth yrs', num: true, render: (r) => fmtInt(r.growth_years) },
  { key: 'market_cap', label: 'Mkt cap', num: true, render: (r) => fmtMoney(r.market_cap) },
]

export function StockTable<T extends StockRow>({ rows, title, csvName, onRowClick, onToggleStar, extra, empty, initialSort = 'yield' }: Props<T>) {
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: initialSort, desc: initialSort !== 'ticker' })

  const view = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const filtered = needle
      ? rows.filter((r) => [r.ticker, r.name, r.sector, r.industry].some((s) => s?.toLowerCase().includes(needle)))
      : rows
    const dir = sort.desc ? -1 : 1
    return [...filtered].sort((a, b) => {
      const av = a[sort.key]
      const bv = b[sort.key]
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      return (typeof av === 'string' ? av.localeCompare(String(bv)) : (av as number) - (bv as number)) * dir
    })
  }, [rows, q, sort])

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 p-4">
        <h2 className="font-semibold text-slate-900">{title}</h2>
        <div className="flex items-center gap-2">
          <input
            type="search"
            placeholder="Search ticker, name, sector…"
            className="w-56 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-emerald-500 focus:outline-none"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <button
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-40"
            onClick={() => downloadCsv(view, csvName)}
            disabled={view.length === 0}
          >
            Export CSV
          </button>
        </div>
      </div>
      <div className="max-h-[36rem] overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="w-8 px-2 py-2" aria-label="Watch" />
              {COLS.map((c) => (
                <th
                  key={c.key}
                  className={`cursor-pointer select-none whitespace-nowrap px-3 py-2 font-medium hover:text-slate-800 ${c.num ? 'text-right' : 'text-left'}`}
                  onClick={() => setSort((s) => ({ key: c.key, desc: s.key === c.key ? !s.desc : c.num === true }))}
                >
                  {c.label}
                  {sort.key === c.key && <span className="ml-0.5">{sort.desc ? '↓' : '↑'}</span>}
                </th>
              ))}
              {extra && <th className="px-3 py-2 text-left font-medium">{extra.header}</th>}
            </tr>
          </thead>
          <tbody>
            {view.map((r) => (
              <tr key={r.ticker} className="cursor-pointer border-t border-slate-100 hover:bg-emerald-50/50" onClick={() => onRowClick(r.ticker)}>
                <td className="px-2 py-2 text-center">
                  <button
                    className={`text-lg leading-none ${r.watched ? 'text-amber-500' : 'text-slate-300 hover:text-amber-400'}`}
                    title={r.watched ? 'Remove from watchlist' : 'Add to watchlist'}
                    aria-label={r.watched ? `Unwatch ${r.ticker}` : `Watch ${r.ticker}`}
                    onClick={(e) => {
                      e.stopPropagation()
                      onToggleStar(r)
                    }}
                  >
                    {r.watched ? '★' : '☆'}
                  </button>
                </td>
                {COLS.map((c) => (
                  <td key={c.key} className={`whitespace-nowrap px-3 py-2 ${c.num ? 'num text-right' : ''}`}>
                    {c.render(r)}
                  </td>
                ))}
                {extra && <td className="px-3 py-2">{extra.render(r)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
        {view.length === 0 && <div className="p-8 text-center text-sm text-slate-500">{empty ?? 'No stocks.'}</div>}
      </div>
      <div className="border-t border-slate-100 px-4 py-2 text-xs text-slate-500">
        {fmtInt(view.length)} of {fmtInt(rows.length)} shown
      </div>
    </div>
  )
}
