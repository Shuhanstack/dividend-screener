import { fmtInt } from '../lib'
import type { FunnelStep, Thresholds } from '../types'

interface Props {
  th: Thresholds
  setTh: (th: Thresholds) => void
  funnel: FunnelStep[]
}

/** Optional rule 6: drop anything whose price fell more than N% over the last 3 years. */
export function PriceFilter({ th, setTh, funnel }: Props) {
  const step = funnel[6]
  const before = funnel[5]?.remaining
  return (
    <section
      className={`flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border p-4 shadow-sm ${th.price_filter ? 'border-emerald-300 bg-white' : 'border-slate-200 bg-white/60'}`}
    >
      <label className="flex items-center gap-2 text-sm font-medium text-slate-800">
        <input
          type="checkbox"
          className="h-4 w-4 accent-emerald-600"
          checked={th.price_filter}
          onChange={(e) => setTh({ ...th, price_filter: e.target.checked })}
        />
        <span>
          <span className="mr-1 text-xs font-semibold uppercase tracking-wide text-emerald-700">Rule 6 · optional</span>
          Exclude big price drops
        </span>
      </label>
      <label className="flex items-center gap-2 text-sm text-slate-700">
        Price fell more than
        <input
          type="number"
          min={0}
          max={100}
          step={5}
          disabled={!th.price_filter}
          className="num w-16 rounded-md border border-slate-300 px-2 py-0.5 text-right text-sm focus:border-emerald-500 focus:outline-none disabled:bg-slate-100 disabled:text-slate-400"
          value={th.price_drop_max}
          onChange={(e) => {
            const v = parseFloat(e.target.value)
            setTh({ ...th, price_drop_max: Number.isFinite(v) ? Math.max(0, v) : 0 })
          }}
          aria-label="Maximum 3-year price drop in percent"
        />
        % over the last 3 years
      </label>
      <span className="text-xs text-slate-500">Applies to stocks, funds and ETFs alike. Less than 3 years of price history counts as missing data.</span>
      {th.price_filter && step && before != null && (
        <span className="ml-auto text-sm">
          <span className="num text-lg font-bold text-slate-900">{fmtInt(step.remaining)}</span>{' '}
          <span className="text-slate-500">
            survive (−{fmtInt(step.failed)} of {fmtInt(before)}
            {step.failed_missing_data > 0 && <span className="text-amber-700">, {fmtInt(step.failed_missing_data)} missing data</span>})
          </span>
        </span>
      )}
    </section>
  )
}
