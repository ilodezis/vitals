import { useMemo, useState } from 'react'
import { MarkerChart } from '@/components/charts/MarkerChart'
import { FilterRow } from '@/components/controls/Choices'
import { RangeBar } from '@/components/controls/Meters'
import { Delta, TextButton } from '@/components/controls/Marks'
import { FigureBody } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useLayout } from '@/components/shell/layout'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { longDate, monthLong, parseIsoDate, shortDate } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { markerTrend, rangeText } from './notes'
import { statusOf, type LabMarker } from './types'
import { useLabsView } from './useLabsView'
import './labs.css'

const lowerFirst = (text: string): string => text.charAt(0).toLowerCase() + text.slice(1)

/** The order the group filters come in. */
const GROUP_ORDER = ['metabolism', 'hormones', 'vitamins']

/** A stretch of the scale that reads better than the whole range for markers whose reference range
 *  is very wide next to where the results sit. The server will send this with the marker. */
const FOCUS: Record<string, readonly [number, number]> = { vitd: [10, 60], tg: [60, 190], fer: [20, 160] }

export default function LabsScreen() {
  const { t, lang } = useT()
  const view = useLabsView()
  const { desktop } = useLayout()
  const [filter, setFilter] = useState('all')
  const [filtered, setFiltered] = useState(false)
  // Phone: the row that is open (or none). Desktop: the row the side panel shows.
  const [selected, setSelected] = useState<string | null>(() => view.markers.find((m) => statusOf(m) !== 'ok')?.id ?? view.markers[0]?.id ?? null)

  const out = view.markers.filter((m) => statusOf(m) !== 'ok')
  const groups = useMemo(() => {
    const seen = new Map<string, string>()
    for (const m of view.markers) if (!seen.has(m.groupKey)) seen.set(m.groupKey, m.group)
    // A fixed order for the known groups, so the filter row does not reshuffle when a
    // different marker happens to come first; anything new follows in the order it appears.
    const rank = (key: string) => {
      const i = GROUP_ORDER.indexOf(key)
      return i === -1 ? GROUP_ORDER.length : i
    }
    return [...seen].sort(([a], [b]) => rank(a) - rank(b))
  }, [view.markers])

  const visible = view.markers.filter((m) => (filter === 'all' ? true : filter === 'out' ? statusOf(m) !== 'ok' : m.groupKey === filter))
  const shown = view.markers.find((m) => m.id === selected) ?? view.markers[0]
  const num = (m: LabMarker, v: number) => formatNumber(v, lang, m.decimals)
  const collected = parseIsoDate(view.collectedIso)

  const pick = (id: string) => setSelected((prev) => (desktop ? id : prev === id ? null : id))
  const statusText = (m: LabMarker) => t(`app.labs.status.${statusOf(m)}`)
  const noteFor = (m: LabMarker) => {
    const trend = markerTrend(m)
    const since = monthLong(parseIsoDate(m.history[0]?.dateIso ?? view.collectedIso), lang)
    const start = t(trend.direction === 'up' ? 'app.labs.note.up' : 'app.labs.note.down', { date: since, from: num(m, trend.first), to: num(m, trend.last), unit: m.unit })
    const low = trend.status === 'low'
    const verdict =
      trend.status === 'ok'
        ? t('app.labs.note.ok')
        : trend.improving
          ? t(low ? 'app.labs.note.improving_low' : 'app.labs.note.improving_high')
          : t(low ? 'app.labs.note.worsening_low' : 'app.labs.note.worsening_high')
    return `${start} ${verdict}`
  }
  const historyOf = (m: LabMarker) => m.history.map((h) => ({ date: parseIsoDate(h.dateIso), value: h.value }))

  return (
    <>
      <TopBar title={t('nav.labs')} />
      <Mast
        screen="labs"
        actions={
          <TextButton icon="upload" onClick={() => toast(t('app.labs.upload_soon'), { icon: 'info' })}>
            {t('app.labs.upload_action')}
          </TextButton>
        }
      />
      <Headline title={t('nav.labs')}>
        <div className="figs inline n3">
          <div className="f">
            <FigureBody value={view.markers.length} label={t('app.labs.fig_markers')} sub={t('app.labs.fig_markers_sub')} />
          </div>
          <div className="f">
            <FigureBody
              value={out.length}
              label={t('app.labs.fig_out')}
              sub={out.map((m) => lowerFirst(m.name.replace(/\s*\(.*\)$/, ''))).join(', ') || undefined}
              tone={out.length > 0 ? 'bad' : undefined}
              subBad={false}
            />
          </div>
          <div className="f">
            <FigureBody value={shortDate(collected, lang)} label={t('app.labs.fig_date')} sub={`${view.lab} · ${view.source}`} />
          </div>
        </div>
      </Headline>

      <button type="button" className="drop sec drop-first" onClick={() => toast(t('app.labs.upload_soon'), { icon: 'info' })}>
        <span className="ico">
          <Icon name="upload" />
        </span>
        <span>
          <b>{t('app.labs.drop_title')}</b>
          <small>{t('app.labs.drop_sub')}</small>
        </span>
      </button>

      <FilterRow
        value={filter}
        onChange={(id) => {
          setFilter(id)
          setFiltered(true)
        }}
        options={[
          { id: 'all', label: `${t('app.labs.filter_all')} ${view.markers.length}` },
          { id: 'out', label: t('app.labs.filter_out'), count: out.length },
          ...groups.map(([id, label]) => ({ id, label })),
        ]}
      />

      <div className="grid labs-grid">
        <div className="c7">
          <div className="rows mk-list">
            {visible.map((m, i) => {
              const status = statusOf(m)
              const bad = status !== 'ok'
              const open = selected === m.id
              return (
                <div
                  key={m.id}
                  className={cx('row', 'mk', open && 'sel', filtered && 'enter')}
                  style={filtered ? { animationDelay: `${i * 25}ms` } : undefined}
                  role="button"
                  tabIndex={0}
                  aria-expanded={desktop ? undefined : open}
                  onClick={() => pick(m.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      pick(m.id)
                    }
                  }}
                >
                  <div>
                    <div className="t">{m.name}</div>
                    <div className="m">{m.group}</div>
                  </div>
                  <div className="mk-value">
                    <div className={cx('v', bad && 'bad')}>
                      {num(m, m.value)}
                      <span className="u">{m.unit}</span>
                    </div>
                    <div className={cx('st', bad ? 'bad' : 'fine')}>{statusText(m)}</div>
                  </div>
                  <RangeBar value={m.value} lo={m.lo} hi={m.hi} min={m.min} max={m.max} tone={bad ? 'bad' : ''} />
                  <div className="scale">
                    <span>{num(m, m.min)}</span>
                    <span>{t('app.labs.norm', { range: rangeText(m, (v, d) => formatNumber(v, lang, d)) })}</span>
                    <span>{num(m, m.max)}</span>
                  </div>
                  <div className={cx('mk-detail', 'collapse', open && 'open')}>
                    <div>
                      <div className="mk-detail-in">
                        {open && !desktop && (
                          <MarkerChart lo={m.lo} hi={m.hi} min={m.min} max={m.max} decimals={m.decimals} history={historyOf(m)} focus={FOCUS[m.id]} />
                        )}
                        <p className="mk-note">{noteFor(m)}</p>
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        <div className="c5">
          <div className="lab-side sticky">
            {shown !== undefined && (
              <div className="panel" key={shown.id}>
                <div className="panel-h">
                  <h3>{shown.name}</h3>
                  <span className="sub">{longDate(collected, lang)}</span>
                </div>
                <div className="fig-hero lab-hero">
                  <div className={cx('big', statusOf(shown) !== 'ok' && 'bad')}>
                    {num(shown, shown.value)}
                    <span className="unit">{shown.unit}</span>
                  </div>
                  <div className="side">
                    <Delta tone={statusOf(shown) !== 'ok' ? 'bad' : undefined}>{statusText(shown)}</Delta>
                    <span className="sub">{t('app.labs.norm', { range: rangeText(shown, (v, d) => formatNumber(v, lang, d)) })}</span>
                  </div>
                </div>
                {desktop && (
                  <div className="lab-chart">
                    <MarkerChart lo={shown.lo} hi={shown.hi} min={shown.min} max={shown.max} decimals={shown.decimals} history={historyOf(shown)} focus={FOCUS[shown.id]} />
                  </div>
                )}
                <p className="mk-note">{noteFor(shown)}</p>
                <div className="rows lab-history">
                  {[...shown.history].reverse().map((h) => {
                    const out = h.value < shown.lo || h.value > shown.hi
                    return (
                      <div key={h.dateIso} className="row r-kv lab-past">
                        <span className="m">{longDate(parseIsoDate(h.dateIso), lang)}</span>
                        <div className={cx('v', out && 'bad')}>
                          {num(shown, h.value)}
                          <span className="u">{shown.unit}</span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
