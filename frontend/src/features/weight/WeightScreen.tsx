import { useMemo, useState } from 'react'
import { Badge, Delta, TextButton } from '@/components/controls/Marks'
import { Odometer } from '@/components/controls/Odometer'
import { Segmented } from '@/components/controls/Segmented'
import { Section } from '@/components/controls/Section'
import { TrendChart, type TrendRange } from '@/components/charts/TrendChart'
import { Icon } from '@/components/icons/Icon'
import { openLogSheet } from '@/components/sheet/logSheetStore'
import { ScreenLink } from '@/components/shell/navigation'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { FIXTURE_TODAY, latestWeight } from '@/fixtures/series'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { longDate, parseIsoDate, relativeDay } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { useLatestWeight } from './weightLog'
import type { WeightSource } from './types'
import { useWeightView } from './useWeightView'
import './weight.css'

const SOURCE_TONE: Record<WeightSource, 'good' | 'violet' | 'cool'> = { manual: 'good', bia: 'violet', garmin: 'cool' }

export default function WeightScreen() {
  const { t, lang, plural } = useT()
  const view = useWeightView()
  const doseSince = { date: longDate(parseIsoDate(view.pace.dose.sinceIso), lang), n: view.pace.dose.days }
  const latest = useLatestWeight()
  const [range, setRange] = useState<TrendRange>('3m')

  const series = useMemo(
    () => ({
      weighings: view.weighings.map((p) => ({ date: parseIsoDate(p.date), kg: p.kg })),
      trend: view.trend.map((p) => ({ date: parseIsoDate(p.date), kg: p.kg })),
      phases: view.dosePhases.map((p) => ({ from: parseIsoDate(p.from), to: parseIsoDate(p.to), label: p.label })),
    }),
    [view],
  )
  const labels = { today: t('app.today_word'), yesterday: t('app.yesterday_word') }
  const drop = view.weekDeltaKg <= 0

  return (
    <>
      <TopBar title={t('nav.weight')} />
      <Mast
        screen="weight"
        actions={
          <TextButton icon="plus" onClick={() => openLogSheet('weight')}>
            {t('app.log')}
          </TextButton>
        }
      />
      <Headline title={t('nav.weight')}>
        <div className="fig-hero">
          <div className="big" data-fig="weight" data-shared-target>
            <Odometer value={formatNumber(latest.kg ?? latestWeight, lang)} />
            <span className="unit">{t('app.unit.kg')}</span>
          </div>
          <div className="side">
            <Delta tone={drop ? 'good' : undefined} icon={drop ? 'down' : 'up'}>
              {t('app.weight.week_delta', { value: formatNumber(Math.abs(view.weekDeltaKg), lang) })}
            </Delta>
            <span className="sub">
              {t('app.weight.avg_line', { avg: formatNumber(view.average7, lang), fat: formatNumber(view.bodyFatPct, lang) })}
            </span>
          </div>
        </div>
      </Headline>

      <Section>
        <div className="panel bare">
          <div className="panel-h">
            <h3>{t('app.weight.chart_title')}</h3>
            <Segmented
              value={range}
              onChange={setRange}
              label={t('app.weight.chart_title')}
              options={[
                { id: '1m', label: t('app.range.1m') },
                { id: '3m', label: t('app.range.3m') },
                { id: 'all', label: t('app.range.all') },
              ]}
            />
          </div>
          <TrendChart weighings={series.weighings} trend={series.trend} phases={series.phases} range={range} end={FIXTURE_TODAY} />
          <div className="legend">
            <span>
              <i />
              {t('app.weight.legend_trend')}
            </span>
            <span>
              <i className="dots" />
              {t('app.weight.legend_weighings')}
            </span>
            <span>
              <i className="band" />
              {view.drug}
            </span>
            <span>
              <i className="now" />
              {t('app.now')}
            </span>
          </div>
        </div>
      </Section>

      <div className="grid">
        <div className="c7">
          <Section title={t('app.weight.history_title')} meta={t('app.weight.history_meta')}>
            <div className="rows">
              {view.history.map((h, i) => (
                <div key={i} className={cx('row', 'r-hist', h.superseded && 'dim')}>
                  <div>
                    <div className="t">
                      {relativeDay(parseIsoDate(h.date), FIXTURE_TODAY, lang, labels)} <span className="m num time-gap">{h.time}</span>
                    </div>
                    {h.superseded ? <div className="m">{t('app.weight.superseded')}</div> : h.note !== undefined ? <div className="m">{h.note}</div> : null}
                  </div>
                  <Badge tone={SOURCE_TONE[h.source]}>{t(`app.source.${h.source}`)}</Badge>
                  <div className="v">
                    {formatNumber(h.kg, lang)}
                    <span className="u">{t('app.unit.kg')}</span>
                  </div>
                </div>
              ))}
            </div>
          </Section>
        </div>

        <div className="c5">
          <Section title={t('app.weight.pace_title')}>
            <div className="rows">
              <div className="row r-kv">
                <div>
                  <div className="t">{t('app.weight.pace_trend')}</div>
                  <div className="m">{t('app.weight.pace_trend_sub')}</div>
                </div>
                <div className={cx('v', view.pace.perWeekKg <= 0 && 'good')}>
                  {formatNumber(view.pace.perWeekKg, lang)}
                  <span className="u">{t('app.unit.kg_week')}</span>
                </div>
              </div>
              <div className="row r-kv">
                <div>
                  <div className="t">{t('app.weight.pace_dose', { label: view.pace.dose.label })}</div>
                  <div className="m">
                    {plural(
                      view.pace.dose.days,
                      t('app.weight.pace_dose_sub.one', doseSince),
                      t('app.weight.pace_dose_sub.few', doseSince),
                      t('app.weight.pace_dose_sub.many', doseSince),
                    )}
                  </div>
                </div>
                <div className="v">
                  {formatNumber(view.pace.dose.deltaKg, lang)}
                  <span className="u">{t('app.unit.kg')}</span>
                </div>
              </div>
              <div className="row r-kv">
                <div>
                  <div className="t">{t('app.weight.pace_goal', { kg: formatNumber(view.pace.goal.targetKg, lang, 0) })}</div>
                  <div className="m">{t('app.weight.pace_goal_sub')}</div>
                </div>
                <div className="v">
                  ≈{view.pace.goal.weeks}
                  <span className="u">{t('app.unit.week')}</span>
                </div>
              </div>
            </div>
          </Section>

          <Section
            title={t('app.weight.scan_title')}
            meta={
              <ScreenLink screen="measures" mode="push" className="link">
                {t('app.weight.all_measures')}
                <Icon name="chevR" />
              </ScreenLink>
            }
          >
            <p className="sub scan-sub">
              {view.lastScan.device} · {longDate(parseIsoDate(view.lastScan.dateIso), lang)}
            </p>
            <div className="rows">
              {view.lastScan.rows.map((row) => (
                <div key={row.label} className="row r-kv tight">
                  <div className="t plain">{row.label}</div>
                  <div className="v">
                    {row.value}
                    <span className="u">{row.unit}</span>
                  </div>
                </div>
              ))}
            </div>
          </Section>
        </div>
      </div>
    </>
  )
}
