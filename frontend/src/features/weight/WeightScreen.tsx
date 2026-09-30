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
import { useToday } from '@/app/session'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { longDate, parseIsoDate, relativeDay } from '@/lib/dates'
import { formatCompact, formatNumber, formatPercent, formatSigned } from '@/lib/format'
import { doseLabel, drugName } from '@/features/glp1/doseLabel'
import type { WeightSource } from './types'
import { useWeightView } from './useWeightView'
import './weight.css'

const SOURCE_TONE: Record<WeightSource, 'good' | 'violet' | 'cool'> = { manual: 'good', bia: 'violet', garmin: 'cool' }

export default function WeightScreen() {
  const { t, tOr, lang, plural } = useT()
  const today = useToday()
  const view = useWeightView()
  const { dose, goal } = view.pace
  const scan = view.lastScan
  const [range, setRange] = useState<TrendRange>('3m')
  const [historyLimit, setHistoryLimit] = useState(14)

  const series = useMemo(
    () => ({
      weighings: view.weighings.map((p) => ({ date: parseIsoDate(p.date), kg: p.kg })),
      trend: view.trend.map((p) => ({ date: parseIsoDate(p.date), kg: p.kg })),
      phases: view.dosePhases.map((p) => ({
        from: parseIsoDate(p.from),
        to: p.to === null ? today : parseIsoDate(p.to),
        label: doseLabel(p.drug, p.doseMg, lang, t, tOr),
      })),
    }),
    [view, today, lang, t, tOr],
  )
  const labels = { today: t('app.today_word'), yesterday: t('app.yesterday_word') }
  const drop = view.weekDeltaKg !== null && view.weekDeltaKg <= 0
  const visibleHistory = view.history.slice(0, historyLimit)
  const remainingHistory = view.history.length - historyLimit
  const doseSince = dose === null ? null : { date: longDate(parseIsoDate(dose.sinceIso), lang), n: dose.days }
  // What stands under the hero figure: the average and the body fat, each only when there is one.
  const underHero = [
    view.average7 === null ? null : t('app.weight.avg7', { avg: formatNumber(view.average7, lang) }),
    view.bodyFatPct === null
      ? null
      : view.bodyFatSource === null
        ? t('app.weight.fat', { fat: formatPercent(view.bodyFatPct, lang, 1) })
        : t('app.weight.fat_from', { fat: formatPercent(view.bodyFatPct, lang, 1), source: view.bodyFatSource }),
  ].filter((line): line is string => line !== null)

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
            {view.kg === null ? '—' : <Odometer value={formatNumber(view.kg, lang)} />}
            <span className="unit">{t('app.unit.kg')}</span>
          </div>
          <div className="side">
            {view.weekDeltaKg !== null && (
              <Delta tone={drop ? 'good' : undefined} icon={drop ? 'down' : 'up'}>
                {t('app.weight.week_delta', { value: formatNumber(Math.abs(view.weekDeltaKg), lang) })}
              </Delta>
            )}
            {underHero.length > 0 && <span className="sub">{underHero.join(' · ')}</span>}
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
          <TrendChart weighings={series.weighings} trend={series.trend} phases={series.phases} range={range} end={today} />
          <div className="legend">
            <span>
              <i />
              {t('app.weight.legend_trend')}
            </span>
            <span>
              <i className="dots" />
              {t('app.weight.legend_weighings')}
            </span>
            {view.dosePhases.length > 0 && (
              <span>
                <i className="band" />
                {drugName(view.drug, tOr)}
              </span>
            )}
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
              {visibleHistory.map((h, i) => (
                <div key={i} className={cx('row', 'r-hist', h.superseded && 'dim')}>
                  <div>
                    <div className="t">
                      {relativeDay(parseIsoDate(h.date), today, lang, labels)} <span className="m num time-gap">{h.time}</span>
                    </div>
                    {h.superseded ? (
                      <div className="m">
                        {h.supersededBy === 'body_scan'
                          ? t('app.weight.superseded_by_scan')
                          : h.supersededBy === 'manual'
                            ? t('app.weight.superseded_by_manual')
                            : t('app.weight.superseded')}
                      </div>
                    ) : h.note !== undefined ? (
                      <div className="m">{h.note}</div>
                    ) : null}
                  </div>
                  <Badge tone={SOURCE_TONE[h.source]}>{t(`app.source.${h.source}`)}</Badge>
                  <div className="v">
                    {formatNumber(h.kg, lang)}
                    <span className="u">{t('app.unit.kg')}</span>
                  </div>
                </div>
              ))}
              {remainingHistory > 0 && (
                <button type="button" className="ghost more-btn" onClick={() => setHistoryLimit((n) => n + 50)}>
                  {t('app.show_more_n', { n: Math.min(50, remainingHistory) })}
                </button>
              )}
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
                {view.pace.perWeekKg === null ? (
                  <div className="v empty">—</div>
                ) : (
                  <div className={cx('v', view.pace.perWeekKg <= 0 && 'good')}>
                    {formatNumber(view.pace.perWeekKg, lang)}
                    <span className="u">{t('app.unit.kg_week')}</span>
                  </div>
                )}
              </div>
              {dose !== null && doseSince !== null && (
                <div className="row r-kv">
                  <div>
                    <div className="t">
                      {dose.drug === null || dose.doseMg === null
                        ? t('app.weight.pace_dose_bare')
                        : t('app.weight.pace_dose', { label: doseLabel(dose.drug, dose.doseMg, lang, t, tOr) })}
                    </div>
                    <div className="m">
                      {plural(
                        dose.days,
                        t('app.weight.pace_dose_sub.one', doseSince),
                        t('app.weight.pace_dose_sub.few', doseSince),
                        t('app.weight.pace_dose_sub.many', doseSince),
                      )}
                    </div>
                  </div>
                  {dose.deltaKg === null ? (
                    <div className="v empty">—</div>
                  ) : (
                    <div className="v">
                      {formatSigned(dose.deltaKg, lang)}
                      <span className="u">{t('app.unit.kg')}</span>
                    </div>
                  )}
                </div>
              )}
              {goal !== null && (
                <div className="row r-kv">
                  <div>
                    <div className="t">{t('app.weight.pace_goal', { kg: formatCompact(goal.targetKg, lang) })}</div>
                    <div className="m">{t('app.weight.pace_goal_sub')}</div>
                  </div>
                  {goal.weeks === null ? (
                    <div className="v empty">—</div>
                  ) : (
                    <div className="v">
                      ≈{goal.weeks}
                      <span className="u">{t('app.unit.week')}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          </Section>

          {scan !== null && (
            <Section
              title={t('app.weight.scan_title')}
              meta={
                <ScreenLink screen="measures" mode="push" className="link">
                  {t('app.weight.all_measures')}
                  <Icon name="chevR" />
                </ScreenLink>
              }
            >
              <p className="sub scan-sub">{[scan.device, longDate(parseIsoDate(scan.dateIso), lang)].filter(Boolean).join(' · ')}</p>
              <div className="rows">
                {scan.rows.map((row) => (
                  <div key={row.label} className="row r-kv tight">
                    <div className="t plain">{row.label}</div>
                    <div className="v">
                      {formatCompact(row.value, lang, 3)}
                      {row.unit !== '' && <span className="u">{row.unit}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </Section>
          )}
        </div>
      </div>
    </>
  )
}
