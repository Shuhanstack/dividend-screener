import type { RuleDef } from '../lib'
import { fmtInt } from '../lib'
import type { FunnelStep } from '../types'

interface Props {
  rule: RuleDef
  value: number
  onChange: (v: number) => void
  funnel?: FunnelStep
  before?: number
}

export function RuleCard({ rule, value, onChange, funnel, before }: Props) {
  const clamp = (v: number) => (Number.isFinite(v) ? v : 0)
  return (
    <div className="flex flex-col rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Rule {rule.step}</div>
          <div className="font-semibold leading-tight text-slate-900">{rule.title}</div>
        </div>
        <div className="text-right">
          <div className="num text-2xl font-bold text-slate-900">{funnel ? fmtInt(funnel.remaining) : '…'}</div>
          <div className="text-[11px] text-slate-500">survive</div>
        </div>
      </div>
      <p className="mt-2 text-xs leading-snug text-slate-600">{rule.explain}</p>
      <label className="mt-auto flex flex-col gap-1 pt-3 text-sm">
        <span className="text-xs font-medium text-slate-700">
          {rule.metric} {rule.op}
        </span>
        <span className="flex items-center gap-1">
          <input
            type="number"
            className="num w-full min-w-0 flex-1 rounded-md border border-slate-300 px-2 py-0.5 text-right text-sm focus:border-emerald-500 focus:outline-none"
            value={value}
            step={rule.stepSize}
            onChange={(e) => onChange(clamp(parseFloat(e.target.value)))}
            aria-label={`${rule.metric} threshold`}
          />
          <span className="w-8 shrink-0 text-xs text-slate-500">{rule.unit}</span>
        </span>
      </label>
      <input
        type="range"
        className="mt-2 w-full accent-emerald-600"
        min={rule.min}
        max={rule.max}
        step={rule.stepSize}
        value={Math.min(rule.max, Math.max(rule.min, value))}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        aria-label={`${rule.metric} slider`}
      />
      {funnel && before != null && (
        <div className="mt-2 text-[11px] text-slate-500">
          −{fmtInt(funnel.failed)} of {fmtInt(before)}
          {funnel.failed_missing_data > 0 && (
            <span className="ml-1 text-amber-700">({fmtInt(funnel.failed_missing_data)} missing data)</span>
          )}
        </div>
      )}
    </div>
  )
}
