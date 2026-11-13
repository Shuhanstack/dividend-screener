import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmtInt } from '../lib'
import type { FunnelStep } from '../types'

interface Props {
  funnel: FunnelStep[]
  selected: number | null
  onSelect: (step: number | null) => void
}

const NAMES = ['Universe', '1 · Pays', '2 · Affords', '3 · Cash', '4 · Reliable', '5 · Grows', '6 · Price']

export function Funnel({ funnel, selected, onSelect }: Props) {
  const data = funnel.map((f, i) => ({ ...f, name: NAMES[i] ?? f.label }))
  const lastStep = funnel.length - 1
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-semibold text-slate-900">Funnel</h2>
        <div className="num text-sm text-slate-600">{funnel.map((f) => fmtInt(f.remaining)).join(' → ')}</div>
      </div>
      <p className="mt-1 text-xs text-slate-500">Click a rule's bar to see the stocks it eliminated.</p>
      <div className="mt-2 h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 64, top: 4, bottom: 4 }}>
            <XAxis type="number" hide domain={[0, 'dataMax']} />
            <YAxis type="category" dataKey="name" width={92} tick={{ fontSize: 12, fill: '#475569' }} axisLine={false} tickLine={false} />
            <Tooltip
              cursor={{ fill: '#f1f5f9' }}
              content={({ active, payload }) => {
                const p = payload?.[0]?.payload as (FunnelStep & { name: string }) | undefined
                if (!active || !p) return null
                return (
                  <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow">
                    <div className="font-semibold">{p.step === 0 ? 'Universe' : `Rule ${p.step}: ${p.label}`}</div>
                    <div>{fmtInt(p.remaining)} remaining</div>
                    {p.step > 0 && (
                      <div className="text-slate-500">
                        {fmtInt(p.failed)} eliminated ({fmtInt(p.failed_missing_data)} missing data)
                      </div>
                    )}
                  </div>
                )
              }}
            />
            <Bar
              dataKey="remaining"
              radius={[0, 4, 4, 0]}
              isAnimationActive={false}
              onClick={(d: unknown) => {
                const step = (d as { step?: number; payload?: { step: number } }).payload?.step ?? (d as { step?: number }).step
                if (step == null || step === 0) return onSelect(null)
                onSelect(step === selected ? null : step)
              }}
              className="cursor-pointer"
            >
              {data.map((d) => (
                <Cell key={d.step} fill={d.step === selected ? '#b45309' : d.step === lastStep ? '#047857' : '#10b981'} fillOpacity={selected != null && d.step !== selected ? 0.55 : 1} />
              ))}
              <LabelList dataKey="remaining" position="right" formatter={(v: unknown) => fmtInt(Number(v))} style={{ fontSize: 12, fill: '#0f172a' }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
