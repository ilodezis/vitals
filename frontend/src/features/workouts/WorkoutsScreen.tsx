import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { Badge, TextButton } from '@/components/controls/Marks'
import { Section } from '@/components/controls/Section'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { toast } from '@/components/controls/toast'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { longDate, parseIsoDate } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import type { components } from '@/api/schema'
import './workouts.css'

type WorkoutsView = components['schemas']['WorkoutsView']

export default function WorkoutsScreen() {
  const { t, lang } = useT()
  const queryClient = useQueryClient()

  const { data: view, isLoading } = useQuery({
    queryKey: ['workouts'],
    queryFn: async (): Promise<WorkoutsView> => {
      const { data } = await api.GET('/api/v1/workouts')
      if (!data) throw new Error('Workouts unavailable')
      return data
    },
  })

  const [openWorkoutId, setOpenWorkoutId] = useState<string | null>(null)
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null)

  const syncMutation = useMutation({
    mutationFn: async () => {
      const res = await api.POST('/api/v1/workouts/sync')
      if (!res.data?.ok) throw new Error(res.data?.error || 'Sync failed')
      return res.data
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ['workouts'] })
      toast(`Синхронизировано: ${data.synced} тренировок`)
    },
    onError: (err) => toast(err.message),
  })

  const workouts = view?.workouts ?? []
  const catalog = view?.catalog ?? []
  const activeExId = selectedTemplateId || (catalog[0]?.exercise_template_id ?? null)
  const selectedEx = catalog.find((c) => c.exercise_template_id === activeExId)

  return (
    <>
      <TopBar title={t('nav.hevy')} />
      <Mast
        screen="workouts"
        actions={
          <TextButton
            icon="sync"
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
          >
            {syncMutation.isPending ? 'Синхронизация...' : 'Синхронизировать'}
          </TextButton>
        }
      />
      <Headline title={t('nav.hevy')}>
        <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 'var(--t-title)', fontWeight: 600 }}>{view?.workout_count ?? 0}</div>
            <div className="sub">Всего тренировок</div>
          </div>
          <div>
            <div style={{ fontSize: 'var(--t-title)', fontWeight: 600 }}>
              {view?.last_workout_date ? longDate(parseIsoDate(view.last_workout_date), lang) : '—'}
            </div>
            <div className="sub">Последняя</div>
          </div>
          <div>
            <div style={{ fontSize: 'var(--t-title)', fontWeight: 600 }}>{view?.exercise_count ?? 0}</div>
            <div className="sub">Упражнений в базе</div>
          </div>
        </div>
      </Headline>

      <div className="grid">
        {/* Left Column: Workouts List */}
        <div className="c7">
          <Section title="Недавние тренировки">
            <div className="rows">
              {isLoading && <div className="row"><span className="m">Загрузка...</span></div>}
              {!isLoading && workouts.length === 0 && (
                <div className="row"><span className="m">{t('app.empty')}</span></div>
              )}
              {workouts.map((w) => {
                const isOpen = openWorkoutId === w.id
                return (
                  <div key={w.id} className={cx('acc', isOpen && 'open')}>
                    <div
                      className="row acc-h r-wk"
                      onClick={() => setOpenWorkoutId(isOpen ? null : w.id)}
                      role="button"
                      tabIndex={0}
                    >
                      <Icon name={isOpen ? 'chevD' : 'chevR'} />
                      <div>
                        <div className="t">{w.title}</div>
                        <div className="m">
                          {w.program && <Badge tone="violet">Программа {w.program}</Badge>}
                          <span className="num"> · {longDate(parseIsoDate(w.date), lang)}</span>
                        </div>
                      </div>
                      <span className="m num">{w.duration_min ? `${w.duration_min} мин` : ''}</span>
                    </div>

                    {isOpen && (
                      <div className="acc-b">
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
                                  {s.weight_kg != null ? `${formatNumber(s.weight_kg, lang)} кг` : ''}
                                  {s.reps != null ? ` × ${s.reps}` : ''}
                                </span>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </Section>
        </div>

        {/* Right Column: Exercise Catalog */}
        <div className="c5">
          <Section title="Упражнения">
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
                      <div className="t" style={{ fontWeight: 500 }}>{c.title}</div>
                      <div className="m num">Сессий: <b>{c.sessions_count}</b></div>
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
          title={`Рабочий вес: ${selectedEx.title}`}
          meta={
            selectedEx.progression_verdict === 'advance' ? (
              <Badge tone="good">🟢 Готов прибавить вес</Badge>
            ) : selectedEx.progression_verdict === 'hold' ? (
              <Badge tone="warn">🟡 Держим вес</Badge>
            ) : selectedEx.progression_verdict === 'deload' ? (
              <Badge tone="bad">🔴 Сбросить вес (deload)</Badge>
            ) : undefined
          }
        >
          <div className="panel bare" style={{ padding: '16px' }}>
            {selectedEx.working_weight_series.length > 0 ? (
              <div>
                <div style={{ height: 160, width: '100%', position: 'relative' }}>
                  <svg width="100%" height="100%" viewBox="0 0 400 160" preserveAspectRatio="none">
                    <line x1="0" y1="80" x2="400" y2="80" stroke="var(--line)" strokeDasharray="3 3" />
                    {(() => {
                      const pts = selectedEx.working_weight_series
                      const weights = pts.map((p) => p.weight_kg)
                      const minW = Math.min(...weights)
                      const maxW = Math.max(...weights)
                      const rangeW = maxW - minW || 1
                      const path = pts
                        .map((p, idx) => {
                          const x = (idx / (pts.length - 1 || 1)) * 400
                          const y = 140 - ((p.weight_kg - minW) / rangeW) * 120
                          return `${idx === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
                        })
                        .join(' ')
                      return (
                        <path
                          d={path}
                          fill="none"
                          stroke="var(--violet)"
                          strokeWidth="2.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      )
                    })()}
                  </svg>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '8px' }}>
                  <span className="m num">{selectedEx.working_weight_series[0]?.date}</span>
                  <span className="m num">
                    {selectedEx.working_weight_series[selectedEx.working_weight_series.length - 1]?.weight_kg} кг
                  </span>
                </div>
              </div>
            ) : (
              <div className="m" style={{ textAlign: 'center', padding: '24px 0' }}>
                Нет данных по этому упражнению
              </div>
            )}

            {selectedEx.latest_notes && (
              <div className="tech">
                <b>Техника</b>
                {selectedEx.latest_notes}
              </div>
            )}
          </div>
        </Section>
      )}
    </>
  )
}
