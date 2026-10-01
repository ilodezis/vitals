import { useState } from 'react'
import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { Disclosure } from '@/components/controls/Disclosure'
import { Badge, TextButton } from '@/components/controls/Marks'
import { Icon } from '@/components/icons/Icon'
import { FigureBody, Section } from '@/components/controls/Section'
import { DomainAlerts } from '@/components/controls/DomainAlerts'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { toast } from '@/components/controls/toast'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { longDate, parseIsoDate, shortDate } from '@/lib/dates'
import { formatCompact } from '@/lib/format'
import { workoutsQuery } from './workoutsQuery'
import './workouts.css'

export default function WorkoutsScreen() {
  const { t, lang } = useT()
  const queryClient = useQueryClient()

  const { data: view } = useSuspenseQuery(workoutsQuery)

  const [openWorkoutId, setOpenWorkoutId] = useState<string | null>(null)
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null)

  const syncMutation = useMutation({
    mutationFn: async () => {
      const res = await api.POST('/api/v1/workouts/sync')
      if (!res.data?.ok) throw new Error('Workout sync failed')
      return res.data
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ['workouts'] })
      // The rail's workouts row.
      void queryClient.invalidateQueries({ queryKey: ['session'] })
      toast(t('app.workouts.synced', { count: data.synced }))
    },
    onError: () => toast(t('hevy.sync_error'), { icon: 'warn' }),
  })

  const workouts = view.workouts ?? []
  const catalog = view.catalog ?? []
  const activeExId = selectedTemplateId || (catalog[0]?.exercise_template_id ?? null)
  const selectedEx = catalog.find((c) => c.exercise_template_id === activeExId)

  return (
    <>
      <TopBar
        title={t('nav.hevy')}
        right={
          <button
            type="button"
            className={cx('ibtn', syncMutation.isPending && 'spin')}
            onClick={() => !syncMutation.isPending && syncMutation.mutate()}
            aria-label={t('app.sync')}
          >
            <Icon name="sync" />
          </button>
        }
      />
      <Mast
        screen="workouts"
        actions={
          <TextButton
            icon="sync"
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
          >
            {syncMutation.isPending ? t('app.syncing') : t('app.sync')}
          </TextButton>
        }
      />
      <Headline title={t('nav.hevy')}>
        <div className="figs inline n3">
          <div className="f">
            <FigureBody value={view.workout_count} label={t('app.workouts.total')} />
          </div>
          <div className="f">
            <FigureBody
              value={view.last_workout_date ? shortDate(parseIsoDate(view.last_workout_date), lang) : '—'}
              label={t('app.workouts.latest')}
            />
          </div>
          <div className="f">
            <FigureBody value={view.exercise_count} label={t('app.workouts.in_catalog')} />
          </div>
        </div>
      </Headline>
      <DomainAlerts domain="workouts" />

      <div className="grid">
        {/* Left Column: Workouts List */}
        <div className="c7">
          <Section title={t('app.workouts.recent')}>
            <div className="rows">
              {workouts.length === 0 && (
                <div className="row"><span className="m">{t('app.empty')}</span></div>
              )}
              {workouts.map((w) => {
                const isOpen = openWorkoutId === w.id
                return (
                  <Disclosure
                    key={w.id}
                    open={isOpen}
                    onToggle={() => setOpenWorkoutId(isOpen ? null : w.id)}
                    title={w.title}
                    sub={[w.program ? t('app.workouts.program', { program: w.program }) : null, longDate(parseIsoDate(w.date), lang)].filter(Boolean).join(' · ')}
                    count={w.duration_min ? t('app.duration.min', { m: w.duration_min }) : undefined}
                  >
                    <div className="disc-body">
                      {w.exercises.map((ex, eIdx) => (
                        <div key={eIdx} className="ex">
                          <button
                            type="button"
                            className="ex-t"
                            onClick={() => setSelectedTemplateId(ex.exercise_template_id ?? null)}
                          >
                            {ex.title}
                          </button>
                          <div className="sets">
                            {ex.sets.map((s, sIdx) => (
                              <span key={sIdx} className="set num">
                                {s.set_type === 'warmup' && <i>W</i>}
                                {s.weight_kg != null ? t('app.unit.kg_value', { value: formatCompact(s.weight_kg, lang, 2) }) : ''}
                                {s.reps != null ? ` × ${s.reps}` : ''}
                              </span>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </Disclosure>
                )
              })}
            </div>
          </Section>
        </div>

        {/* Right Column: Exercise Catalog */}
        <div className="c5">
          <Section title={t('app.workouts.exercises')}>
            <div className="rows">
              {catalog.map((c) => {
                const isSel = c.exercise_template_id === activeExId
                return (
                  <button
                    key={c.exercise_template_id}
                    type="button"
                    className={cx('pick', isSel && 'sel')}
                    onClick={() => setSelectedTemplateId(c.exercise_template_id)}
                  >
                    <div>
                      <div className="t">{c.title}</div>
                      <div className="m num">{t('app.workouts.sessions_count', { count: c.sessions_count })}</div>
                    </div>
                    {c.last_date && (
                      <span className="m num">{longDate(parseIsoDate(c.last_date), lang)}</span>
                    )}
                  </button>
                )
              })}
            </div>
          </Section>
        </div>
      </div>

      {/* Selected Exercise Progression Section */}
      {selectedEx && (
        <Section
          title={t('app.workouts.working_weight', { title: selectedEx.title })}
          meta={
            selectedEx.progression_verdict === 'advance' ? (
              <Badge tone="good">{t('app.workouts.verdict_advance')}</Badge>
            ) : selectedEx.progression_verdict === 'hold' ? (
              <Badge tone="warn">{t('app.workouts.verdict_hold')}</Badge>
            ) : selectedEx.progression_verdict === 'deload' ? (
              <Badge tone="bad">{t('app.workouts.verdict_deload')}</Badge>
            ) : undefined
          }
        >
          <div className="panel bare wk-chart">
            {selectedEx.working_weight_series.length > 0 ? (() => {
              const pts = selectedEx.working_weight_series
              const weights = pts.map((p) => p.weight_kg)
              const minW = Math.min(...weights)
              const maxW = Math.max(...weights)
              const midW = (minW + maxW) / 2
              const rangeW = maxW - minW || 1
              const path = pts
                .map((p, idx) => {
                  const x = (idx / (pts.length - 1 || 1)) * 400
                  const y = 140 - ((p.weight_kg - minW) / rangeW) * 120
                  return `${idx === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
                })
                .join(' ')
              const firstPt = pts[0]
              const lastPt = pts[pts.length - 1]
              return (
                <div>
                  <div className="wk-plot">
                    <div className="wk-y num">
                      <span>{formatCompact(maxW, lang)}</span>
                      <span>{formatCompact(midW, lang)}</span>
                      <span>{formatCompact(minW, lang)}</span>
                    </div>
                    <div className="wk-svg">
                      <svg width="100%" height="100%" viewBox="0 0 400 160" preserveAspectRatio="none">
                        <line x1="0" y1="80" x2="400" y2="80" stroke="var(--line)" strokeDasharray="3 3" />
                        <path
                          d={path}
                          fill="none"
                          stroke="var(--violet)"
                          strokeWidth="2.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </div>
                  </div>
                  <div className="wk-x">
                    <span className="m num">{firstPt?.date ? shortDate(parseIsoDate(firstPt.date), lang) : ''}</span>
                    <span className="m num">
                      {lastPt?.date ? shortDate(parseIsoDate(lastPt.date), lang) : ''}
                      {lastPt?.weight_kg != null ? ` · ${t('app.unit.kg_value', { value: formatCompact(lastPt.weight_kg, lang, 2) })}` : ''}
                    </span>
                  </div>
                </div>
              )
            })() : (
              <p className="sub wk-none">{t('app.workouts.no_data')}</p>
            )}

            {selectedEx.latest_notes && (
              <div className="tech">
                <b>{t('app.workouts.technique')}</b>
                {selectedEx.latest_notes}
              </div>
            )}
          </div>
        </Section>
      )}
    </>
  )
}
