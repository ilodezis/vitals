import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, failText, ok } from '@/api/client'
import { DoseChart } from '@/components/charts/DoseChart'
import { Badge, TextButton } from '@/components/controls/Marks'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { openLogSheet } from '@/components/sheet/logSheetStore'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useToday } from '@/app/session'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { addDays, daysBetween, longDate, parseIsoDate, relativeDay, shortDate, toIsoDate, weekdayLongDate, weekdayShort } from '@/lib/dates'
import { formatCompact, formatSigned } from '@/lib/format'
import { BodyMap } from './BodyMap'
import { drugName } from './doseLabel'
import { siteUsage } from './sites'
import type { SiteId } from './types'
import { useGlp1View } from './useGlp1View'
import './glp1.css'

const CYCLE_DAYS = 8

export default function Glp1Screen() {
  const { t, tOr, lang, plural } = useT()
  const today = useToday()
  const queryClient = useQueryClient()
  const view = useGlp1View()

  const [showAllInjections, setShowAllInjections] = useState(false)
  const [showSeForm, setShowSeForm] = useState(false)
  const [seDate, setSeDate] = useState(() => toIsoDate(today))
  const [seName, setSeName] = useState('')
  const [seSeverity, setSeSeverity] = useState(1)

  const sideEffectMutation = useMutation({
    mutationFn: () =>
      ok(
        api.POST('/api/v1/glp1/side-effects', {
          body: {
            date: seDate,
            effectType: seName.trim(),
            severity: seSeverity,
          },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['glp1'] })
      setShowSeForm(false)
      setSeName('')
      setSeSeverity(1)
      toast(t('app.saved'))
    },
    onError: (err) => {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    },
  })

  const usage = useMemo(() => siteUsage(view.injections, today, parseIsoDate), [view.injections, today])
  const phases = useMemo(() => view.dosePhases.map((p) => ({ from: parseIsoDate(p.fromIso), doseMg: p.doseMg })), [view.dosePhases])
  const trend = useMemo(() => view.trend.map((p) => ({ date: parseIsoDate(p.date), kg: p.kg })), [view.trend])
  const labels = { today: t('app.today_word'), yesterday: t('app.yesterday_word') }
  const siteName = (site: SiteId | null): string => (site === null ? '—' : tOr(`app.site.${site}`, view.siteLabels[site] ?? site))

  // Only what the weight really did on this dose; with a single weigh-in there is no phrase.
  const summaryText =
    view.deltaOnDoseKg !== null && view.doseMg !== null && view.sinceIso !== null
      ? t('app.glp1.summary_on_dose', {
          dose: formatCompact(view.doseMg, lang, 3),
          delta: formatSigned(view.deltaOnDoseKg, lang),
          date: longDate(parseIsoDate(view.sinceIso), lang),
        })
      : null

  // The cycle needs an injection to count from and a date to count to.
  const cycle =
    view.cycle.lastIso !== null && view.cycle.nextIso !== null && view.cycle.daysToNext !== null
      ? { first: parseIsoDate(view.cycle.lastIso), next: parseIsoDate(view.cycle.nextIso), daysToNext: view.cycle.daysToNext }
      : null

  // The days of one cycle as a line: the last injection, the days since, the next one.
  const days =
    cycle === null
      ? []
      : Array.from({ length: CYCLE_DAYS }, (_, i) => {
          const date = addDays(cycle.first, i)
          const k = daysBetween(today, date)
          const kind = i === 0 ? 'inj past' : i === CYCLE_DAYS - 1 ? 'next' : k === 0 ? 'now' : k < 0 ? 'past' : ''
          return { date, k, kind }
        })

  const isOverdue = cycle !== null && (view.cycle.overdue || cycle.daysToNext < 0)
  const cycleStatusText =
    cycle === null
      ? ''
      : isOverdue
        ? plural(
            Math.abs(cycle.daysToNext),
            t('app.glp1.overdue.one', { n: Math.abs(cycle.daysToNext) }),
            t('app.glp1.overdue.few', { n: Math.abs(cycle.daysToNext) }),
            t('app.glp1.overdue.many', { n: Math.abs(cycle.daysToNext) }),
          )
        : cycle.daysToNext === 0
          ? t('app.glp1.due_today')
          : plural(
              cycle.daysToNext,
              t('app.glp1.in_days.one', { n: cycle.daysToNext }),
              t('app.glp1.in_days.few', { n: cycle.daysToNext }),
              t('app.glp1.in_days.many', { n: cycle.daysToNext }),
            )

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
            {view.doseMg === null ? '—' : formatCompact(view.doseMg, lang, 3)}
            {view.doseMg !== null && <span className="unit">{t('app.unit.mg')}</span>}
          </div>
          <div className="side">
            {view.drug !== null && <Badge tone="violet">{drugName(view.drug, tOr)}</Badge>}
            {view.dayOnDose !== null && view.sinceIso !== null && (
              <span className="sub">{t('app.glp1.day_on_dose', { n: view.dayOnDose, date: longDate(parseIsoDate(view.sinceIso), lang) })}</span>
            )}
          </div>
        </div>
      </Headline>

      <div className="grid">
        <div className="c7">
          {cycle !== null && (
            <Section title={t('app.glp1.cycle_title')}>
              <div className="panel bare">
                <div className="cyc-cap">
                  <div className="big">
                    {t('app.glp1.next_is')} <span className="nw">{weekdayLongDate(cycle.next, lang)}</span>
                  </div>
                  <span className={cx('sub', isOverdue && 'warn')}>{cycleStatusText}</span>
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
          )}

          <Section title={t('app.glp1.dose_weight_title')} meta={t('app.glp1.dose_weight_meta')}>
            <div className="panel bare">
              <DoseChart phases={phases} trend={trend} start={trend[0]?.date ?? phases[0]?.from ?? today} end={today} />
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
              {summaryText !== null && <p className="sub glp1-summary">{summaryText}</p>}
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
                    <span>{siteName(u.site)}</span>
                    <span>{u.mark.kind === 'next' ? t('app.glp1.least_used') : u.last === null ? '—' : shortDate(u.last, lang)}</span>
                  </div>
                ))}
              </div>
            </div>
          </Section>

          <Section title={t('app.glp1.side_effects_title')}>
            <div className="rows">
              {view.sideEffects.length === 0 && !showSeForm && (
                <div className="row" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span className="m">{t('glp1.no_side_effects')}</span>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => setShowSeForm(true)}
                  >
                    {t('app.mark_action')}
                  </button>
                </div>
              )}
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
            {showSeForm && (
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  sideEffectMutation.mutate()
                }}
                className="panel"
                style={{ marginTop: '12px' }}
              >
                <div className="fld">
                  <label>{t('common.date')}</label>
                  <input
                    type="date"
                    className="input"
                    value={seDate}
                    onChange={(e) => setSeDate(e.target.value)}
                    required
                  />
                </div>
                <div className="fld">
                  <label>{t('app.glp1.side_effect_name')}</label>
                  <input
                    type="text"
                    className="input"
                    value={seName}
                    onChange={(e) => setSeName(e.target.value)}
                    placeholder={t('app.glp1.side_effect_placeholder')}
                    required
                  />
                </div>
                <div className="fld">
                  <label>
                    {t('app.glp1.severity_label')}: {seSeverity}/5
                  </label>
                  <input
                    type="range"
                    min="1"
                    max="5"
                    value={seSeverity}
                    onChange={(e) => setSeSeverity(Number(e.target.value))}
                  />
                </div>
                <div className="form-acts" style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
                  <button
                    type="submit"
                    className="btn grow"
                    disabled={sideEffectMutation.isPending || !seName.trim()}
                  >
                    {t('common.save')}
                  </button>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => setShowSeForm(false)}
                  >
                    {t('app.cancel')}
                  </button>
                </div>
              </form>
            )}
          </Section>

          <Section
            title={t('app.glp1.history_title')}
            meta={plural(view.injections.length, t('app.glp1.injections.one', { n: view.injections.length }), t('app.glp1.injections.few', { n: view.injections.length }), t('app.glp1.injections.many', { n: view.injections.length }))}
          >
            <div className="rows">
              {(showAllInjections ? view.injections : view.injections.slice(0, 5)).map((j, i) => (
                <div key={`${j.dateIso}-${i}`} className="row r-3">
                  <div className="t">{relativeDay(parseIsoDate(j.dateIso), today, lang, labels)}</div>
                  <span className="m">{siteName(j.site)}</span>
                  <div className="v">
                    {formatCompact(j.doseMg, lang, 3)}
                    <span className="u">{t('app.unit.mg')}</span>
                  </div>
                </div>
              ))}
            </div>
            {view.injections.length > 5 && !showAllInjections && (
              <button
                type="button"
                className="ghost more-btn"
                onClick={() => setShowAllInjections(true)}
              >
                {t('app.glp1.all_injections', { count: view.injections.length })}
              </button>
            )}
          </Section>
        </div>
      </div>
    </>
  )
}
