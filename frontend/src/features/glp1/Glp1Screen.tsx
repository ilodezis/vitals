import { useMemo } from 'react'
import { DoseChart } from '@/components/charts/DoseChart'
import { Badge, TextButton } from '@/components/controls/Marks'
import { Section } from '@/components/controls/Section'
import { openLogSheet } from '@/components/sheet/logSheetStore'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { FIXTURE_TODAY } from '@/fixtures/series'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { addDays, daysBetween, longDate, parseIsoDate, relativeDay, shortDate, weekdayLongDate, weekdayShort } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { BodyMap } from './BodyMap'
import { siteUsage } from './sites'
import { useGlp1View } from './useGlp1View'
import './glp1.css'

const CYCLE_DAYS = 8

export default function Glp1Screen() {
  const { t, lang, plural } = useT()
  const view = useGlp1View()

  const usage = useMemo(() => siteUsage(view.injections, FIXTURE_TODAY, parseIsoDate), [view.injections])
  const phases = useMemo(() => view.dosePhases.map((p) => ({ from: parseIsoDate(p.fromIso), doseMg: p.doseMg })), [view.dosePhases])
  const trend = useMemo(() => view.trend.map((p) => ({ date: parseIsoDate(p.date), kg: p.kg })), [view.trend])
  const first = parseIsoDate(view.cycle.lastIso)
  const next = parseIsoDate(view.cycle.nextIso)
  const labels = { today: t('app.today_word'), yesterday: t('app.yesterday_word') }

  // The days of one cycle as a line: the last injection, the days since, the next one.
  const days = Array.from({ length: CYCLE_DAYS }, (_, i) => {
    const date = addDays(first, i)
    const k = daysBetween(FIXTURE_TODAY, date)
    const kind = i === 0 ? 'inj past' : i === CYCLE_DAYS - 1 ? 'next' : k === 0 ? 'now' : k < 0 ? 'past' : ''
    return { date, k, kind }
  })

  return (
    <>
      <TopBar title={t('nav.glp1')} />
      <Mast
        screen="glp1"
        actions={
          <TextButton icon="syringe" onClick={() => openLogSheet('dose')}>
            {t('app.glp1.injection')}
          </TextButton>
        }
      />
      <Headline title={t('nav.glp1')}>
        <div className="fig-hero">
          <div className="big">
            {formatNumber(view.doseMg, lang)}
            <span className="unit">{t('app.unit.mg')}</span>
          </div>
          <div className="side">
            <Badge tone="violet">{view.drug}</Badge>
            <span className="sub">{t('app.glp1.day_on_dose', { n: view.dayOnDose, date: longDate(parseIsoDate(view.sinceIso), lang) })}</span>
          </div>
        </div>
      </Headline>

      <div className="grid">
        <div className="c7">
          <Section title={t('app.glp1.cycle_title')}>
            <div className="panel bare">
              <div className="cyc-cap">
                <div className="big">
                  {t('app.glp1.next_is')} <span className="nw">{weekdayLongDate(next, lang)}</span>
                </div>
                <span className="sub">
                  {plural(view.cycle.daysToNext, t('app.glp1.in_days.one', { n: view.cycle.daysToNext }), t('app.glp1.in_days.few', { n: view.cycle.daysToNext }), t('app.glp1.in_days.many', { n: view.cycle.daysToNext }))}
                </span>
              </div>
              <div className="cycle">
                <span className="prog" />
                {days.map(({ date, k, kind }) => (
                  <div key={date.getTime()} className={cx('cyc', kind)}>
                    <i />
                    <b>{date.getDate()}</b>
                    <span>{k === 0 ? t('app.today_word_lower') : weekdayShort(date, lang)}</span>
                  </div>
                ))}
              </div>
            </div>
          </Section>

          <Section title={t('app.glp1.dose_weight_title')} meta={t('app.glp1.dose_weight_meta')}>
            <div className="panel bare">
              <DoseChart phases={phases} trend={trend} start={trend[0]?.date ?? phases[0]?.from ?? FIXTURE_TODAY} end={FIXTURE_TODAY} />
              <div className="legend">
                <span>
                  <i style={{ background: 'var(--violet)' }} />
                  {t('app.glp1.legend_dose')}
                </span>
                <span>
                  <i style={{ opacity: 0.75 }} />
                  {t('app.glp1.legend_weight')}
                </span>
              </div>
              <p className="sub glp1-summary">{view.summary}</p>
            </div>
          </Section>
        </div>

        <div className="c5">
          <Section title={t('app.glp1.sites_title')} meta={t('app.glp1.sites_meta')}>
            <div className="sites">
              <div>
                <BodyMap usage={usage} label={t('app.glp1.sites_title')} />
              </div>
              <div className="site-list">
                {[...usage].reverse().map((u) => (
                  <div key={u.site} className={u.mark.kind === 'next' ? 'sug' : undefined}>
                    <span>{view.siteLabels[u.site]}</span>
                    <span>{u.mark.kind === 'next' ? t('app.glp1.least_used') : u.last === null ? '—' : shortDate(u.last, lang)}</span>
                  </div>
                ))}
              </div>
            </div>
          </Section>

          <Section title={t('app.glp1.side_effects_title')}>
            <div className="rows">
              {view.sideEffects.map((e) => (
                <div key={e.dateIso + e.name} className="row r-kv">
                  <div>
                    <div className="t">{e.name}</div>
                    <div className="m">{longDate(parseIsoDate(e.dateIso), lang)}</div>
                  </div>
                  <span className={cx('pips', e.severity < 3 && 'l2')} title={t('app.glp1.severity', { n: e.severity })}>
                    {[1, 2, 3, 4, 5].map((k) => (
                      <i key={k} className={k <= e.severity ? 'on' : undefined} />
                    ))}
                  </span>
                </div>
              ))}
            </div>
          </Section>

          <Section
            title={t('app.glp1.history_title')}
            meta={plural(view.injections.length, t('app.glp1.injections.one', { n: view.injections.length }), t('app.glp1.injections.few', { n: view.injections.length }), t('app.glp1.injections.many', { n: view.injections.length }))}
          >
            <div className="rows">
              {view.injections.slice(0, 5).map((j) => (
                <div key={j.dateIso} className="row r-3">
                  <div className="t">{relativeDay(parseIsoDate(j.dateIso), FIXTURE_TODAY, lang, labels)}</div>
                  <span className="m">{view.siteLabels[j.site]}</span>
                  <div className="v">
                    {formatNumber(j.doseMg, lang, j.doseMg < 0.5 ? 2 : 1)}
                    <span className="u">{t('app.unit.mg')}</span>
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
