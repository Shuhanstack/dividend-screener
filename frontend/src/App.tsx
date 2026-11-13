import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, isStatic } from './api'
import { Drawer } from './components/Drawer'
import { Funnel } from './components/Funnel'
import { RuleCard } from './components/RuleCard'
import { StockTable } from './components/StockTable'
import { DEFAULT_THRESHOLDS, fmtDate, fmtInt, PRESETS, RULES, sameThresholds, toApi, useDebounced, useLocalStorage } from './lib'
import type { EliminatedResponse, Meta, ScreenResponse, StockRow, Thresholds, WatchItem } from './types'

type Tab = 'screen' | 'watchlist'

export default function App() {
  const [th, setTh] = useLocalStorage<Thresholds>('divscreen.thresholds', DEFAULT_THRESHOLDS)
  const [tab, setTab] = useLocalStorage<{ tab: Tab }>('divscreen.tab', { tab: 'screen' })
  const debounced = useDebounced(th, 300)
  const apiTh = useMemo(() => toApi(debounced), [debounced])

  const [meta, setMeta] = useState<Meta | null>(null)
  const [screen, setScreen] = useState<ScreenResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [selectedStep, setSelectedStep] = useState<number | null>(null)
  const [eliminated, setEliminated] = useState<EliminatedResponse | null>(null)
  const [watch, setWatch] = useState<WatchItem[]>([])
  const [drawer, setDrawer] = useState<string | null>(null)
  const [version, setVersion] = useState(0) // bump to refetch after watchlist edits

  useEffect(() => {
    api.meta().then(setMeta).catch(() => setMeta(null))
  }, [])

  useEffect(() => {
    const ac = new AbortController()
    setLoading(true)
    api
      .screen(apiTh, ac.signal)
      .then((r) => {
        setScreen(r)
        setError(null)
      })
      .catch((e: unknown) => !ac.signal.aborted && setError(`Could not reach the API (${String(e)}). Is the backend running?`))
      .finally(() => !ac.signal.aborted && setLoading(false))
    return () => ac.abort()
  }, [apiTh, version])

  useEffect(() => {
    if (selectedStep == null) return setEliminated(null)
    const ac = new AbortController()
    api.eliminated(apiTh, selectedStep, ac.signal).then(setEliminated).catch(() => undefined)
    return () => ac.abort()
  }, [apiTh, selectedStep, version])

  useEffect(() => {
    const ac = new AbortController()
    api.watchlist(apiTh, ac.signal).then((r) => setWatch(r.items)).catch(() => undefined)
    return () => ac.abort()
  }, [apiTh, version])

  const watched = useMemo(() => new Set(watch.map((w) => w.ticker)), [watch])
  const mark = <T extends StockRow>(rows: T[]): T[] => rows.map((r) => ({ ...r, watched: watched.has(r.ticker) }))

  const toggle = useCallback(async (ticker: string, on: boolean) => {
    await api.watch(ticker, on)
    setVersion((v) => v + 1)
  }, [])

  const preset = PRESETS.find((p) => sameThresholds(p.th, th))
  const funnel = screen?.funnel ?? []

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-6">
          <div>
            <h1 className="text-xl font-bold text-slate-900">
              <span className="mr-1">💰</span>Dividend Pocket-Money Screener
            </h1>
            <p className="text-xs text-slate-500">
              A personal, educational project. Not financial advice.
              {isStatic && ' Data refreshes weekly; your watchlist is saved in this browser only.'}
            </p>
          </div>
          <div className="text-right text-xs text-slate-500">
            {meta?.fixtures_mode && (
              <span className="mr-2 rounded-full bg-violet-100 px-2 py-0.5 font-medium text-violet-800">Fixture data (synthetic)</span>
            )}
            <div>
              Last refresh: <span className="text-slate-700">{fmtDate(meta?.last_refresh)}</span>
              {meta?.provider && <span> · {meta.provider}</span>}
            </div>
            {meta && (
              <div>
                {fmtInt(meta.screened)} screened of {fmtInt(meta.universe_size)} in universe
                {meta.fetch_errors > 0 && (
                  <span className="text-amber-700" title={meta.error_tickers.slice(0, 30).map((e) => `${e.ticker}: ${e.error}`).join('\n')}>
                    {' '}
                    · {fmtInt(meta.fetch_errors)} fetch errors
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
        <nav className="mx-auto flex max-w-7xl gap-1 px-4 sm:px-6">
          {(['screen', 'watchlist'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab({ tab: t })}
              className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${tab.tab === t ? 'border-emerald-600 text-emerald-700' : 'border-transparent text-slate-500 hover:text-slate-800'}`}
            >
              {t === 'screen' ? 'Screener' : `Watchlist (${watch.length})`}
            </button>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6">
        {error && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}

        <section className="flex flex-wrap items-center gap-3">
          <span className="text-sm font-medium text-slate-700">Preset:</span>
          {PRESETS.map((p) => (
            <button
              key={p.name}
              onClick={() => setTh({ ...p.th, ignore_specials: th.ignore_specials })}
              className={`rounded-full border px-3 py-1 text-sm ${preset?.name === p.name ? 'border-emerald-600 bg-emerald-600 text-white' : 'border-slate-300 bg-white hover:bg-slate-50'}`}
            >
              {p.name}
            </button>
          ))}
          {!preset && <span className="rounded-full bg-slate-200 px-3 py-1 text-sm text-slate-700">Custom</span>}
          <label className="ml-auto flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              className="h-4 w-4 accent-emerald-600"
              checked={th.ignore_specials}
              onChange={(e) => setTh({ ...th, ignore_specials: e.target.checked })}
            />
            Ignore one-off special dividends <span className="text-xs text-slate-500">(&gt; 3× median of nearby payments)</span>
          </label>
          {loading && <span className="text-xs text-slate-400">updating…</span>}
        </section>

        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {RULES.map((r) => (
            <RuleCard
              key={r.key}
              rule={r}
              value={th[r.key]}
              onChange={(v) => setTh({ ...th, [r.key]: v })}
              funnel={funnel[r.step]}
              before={funnel[r.step - 1]?.remaining}
            />
          ))}
        </section>

        {tab.tab === 'screen' ? (
          <>
            {screen && <Funnel funnel={funnel} selected={selectedStep} onSelect={setSelectedStep} />}

            {selectedStep != null && eliminated && (
              <StockTable
                rows={mark(eliminated.items)}
                title={
                  <span>
                    <span className="text-amber-700">Eliminated at rule {selectedStep}</span> · {RULES[selectedStep - 1]?.title}{' '}
                    <span className="text-sm font-normal text-slate-500">
                      ({fmtInt(eliminated.total)} stocks, {fmtInt(eliminated.missing_data)} for missing data
                      {eliminated.total > eliminated.items.length ? `; largest ${fmtInt(eliminated.items.length)} shown` : ''})
                    </span>
                    <button className="ml-3 text-sm font-normal text-slate-500 underline" onClick={() => setSelectedStep(null)}>
                      close
                    </button>
                  </span>
                }
                csvName={`eliminated-rule-${selectedStep}.csv`}
                onRowClick={setDrawer}
                onToggleStar={(r) => toggle(r.ticker, !r.watched)}
                extra={{ header: 'Why', render: (r) => (r.missing_data ? <Badge tone="amber">missing data</Badge> : <Badge tone="red">below threshold</Badge>) }}
                initialSort="market_cap"
              />
            )}

            <StockTable
              rows={mark(screen?.results ?? [])}
              title={
                <span>
                  Survivors <span className="text-sm font-normal text-slate-500">— passed all 5 rules</span>
                </span>
              }
              csvName="dividend-survivors.csv"
              onRowClick={setDrawer}
              onToggleStar={(r) => toggle(r.ticker, !r.watched)}
              empty="No stock passes every rule. Try the Relaxed preset."
            />
          </>
        ) : (
          <StockTable
            rows={watch}
            title="Watchlist"
            csvName="dividend-watchlist.csv"
            onRowClick={setDrawer}
            onToggleStar={(r) => toggle(r.ticker, false)}
            initialSort="ticker"
            empty="Star a stock in the screener to track it here."
            extra={{
              header: 'Status',
              render: (r) => (
                <span className="flex flex-wrap gap-1">
                  {!r.has_data && <Badge tone="amber">No data</Badge>}
                  {r.fails.map((s) => (
                    <Badge key={s} tone="red">Fails rule {s}</Badge>
                  ))}
                  {r.missing.map((s) => (
                    <Badge key={`m${s}`} tone="amber">No data rule {s}</Badge>
                  ))}
                  {r.has_data && r.fails.length === 0 && r.missing.length === 0 && <Badge tone="green">Passes all</Badge>}
                </span>
              ),
            }}
          />
        )}

        <footer className="pb-6 text-center text-xs text-slate-400">
          Data: {meta?.provider ?? 'yfinance'} (unofficial Yahoo Finance data; may be delayed, incomplete or wrong). A personal,
          educational project — not financial advice, not a recommendation to buy or sell any security.
        </footer>
      </main>

      {drawer && <Drawer ticker={drawer} th={apiTh} onClose={() => setDrawer(null)} onToggleStar={toggle} />}
    </div>
  )
}

function Badge({ tone, children }: { tone: 'red' | 'amber' | 'green'; children: React.ReactNode }) {
  const cls = { red: 'bg-red-100 text-red-700', amber: 'bg-amber-100 text-amber-800', green: 'bg-emerald-100 text-emerald-800' }[tone]
  return <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{children}</span>
}
