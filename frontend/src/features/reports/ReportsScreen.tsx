import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { Badge } from '@/components/controls/Marks'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import type { MilestoneItem } from './types'
import { useReportsView } from './useReportsView'
import './reports.css'

const DOM_RU: Record<string, string> = {
  weight: 'Вес',
  labs: 'Анализы',
  garmin: 'Garmin',
  nutrition: 'Питание',
  workouts: 'Тренировки',
}

const DOM_TONE: Record<string, 'good' | 'cool' | 'violet'> = {
  weight: 'good',
  labs: 'cool',
  garmin: 'violet',
}

export default function ReportsScreen() {
  const { t } = useT()
  const view = useReportsView()
  const queryClient = useQueryClient()

  // Goal modal states
  const [goalFormOpen, setGoalFormOpen] = useState(false)
  const [goalName, setGoalName] = useState('')
  const [goalDom, setGoalDom] = useState('weight')
  const [goalTarget, setGoalTarget] = useState('82')
  const [goalUnit, setGoalUnit] = useState('кг')
  const [goalDeadline, setGoalDeadline] = useState('')
  const [isSubmittingGoal, setIsSubmittingGoal] = useState(false)

  // Digest states
  const [digestDays, setDigestDays] = useState(7)
  const [isGeneratingDigest, setIsGeneratingDigest] = useState(false)
  const [olderDigestsOpen, setOlderDigestsOpen] = useState(false)

  // Brief states
  const [briefStatus, setBriefStatus] = useState<string | null>(null)
  const [briefStatusTone, setBriefStatusTone] = useState<'info' | 'warn'>('info')
  const [isLoadingBrief, setIsLoadingBrief] = useState(false)

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['reports'] })
  }

  const handleCreateGoal = async (): Promise<boolean> => {
    if (!goalName.trim()) {
      toast(t('common.required_field') || 'Name is required', { icon: 'warn' })
      return false
    }
    setIsSubmittingGoal(true)
    try {
      await api.POST('/api/v1/reports/milestones', {
        body: {
          name: goalName.trim(),
          domain: goalDom,
          targetValue: parseFloat(goalTarget) || null,
          targetUnit: goalUnit.trim() || null,
          deadline: goalDeadline || null,
        },
      })
      toast('Цель создана')
      setGoalFormOpen(false)
      setGoalName('')
      refresh()
      return true
    } catch (err: any) {
      toast(err.message || 'Error creating goal', { icon: 'warn' })
      return false
    } finally {
      setIsSubmittingGoal(false)
    }
  }

  const handleGoalStatus = async (id: number, status: string) => {
    try {
      await api.PATCH('/api/v1/reports/milestones/{milestone_id}/status', {
        params: { path: { milestone_id: id } },
        body: { status },
      })
      toast('Статус обновлён')
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error updating status', { icon: 'warn' })
    }
  }

  const handleDeleteGoal = async (id: number) => {
    try {
      await api.DELETE('/api/v1/reports/milestones/{milestone_id}', {
        params: { path: { milestone_id: id } },
      })
      toast(t('common.deleted'))
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error deleting goal', { icon: 'warn' })
    }
  }

  const handleGenerateDigest = async () => {
    setIsGeneratingDigest(true)
    try {
      await api.POST('/api/v1/reports/digests', {
        body: { periodDays: digestDays },
      })
      toast('Разбор сгенерирован')
      refresh()
    } catch (err: any) {
      toast(err.message || 'Не удалось собрать дайджест', { icon: 'warn' })
    } finally {
      setIsGeneratingDigest(false)
    }
  }

  const handleBuildBrief = async () => {
    setIsLoadingBrief(true)
    setBriefStatus(null)
    try {
      await api.POST('/api/v1/reports/briefs/build', {})
      setBriefStatus('Бриф собран — ниже. Не отправлен.')
      setBriefStatusTone('info')
      refresh()
    } catch (err: any) {
      setBriefStatus(err.message || 'Не удалось собрать бриф. Проверьте баланс/ключ OpenRouter.')
      setBriefStatusTone('warn')
    } finally {
      setIsLoadingBrief(false)
    }
  }

  const handleTestBrief = async () => {
    setIsLoadingBrief(true)
    setBriefStatus(null)
    try {
      await api.POST('/api/v1/reports/briefs/test', {})
      setBriefStatus('Тестовое сообщение отправлено в Telegram.')
      setBriefStatusTone('info')
      refresh()
    } catch (err: any) {
      setBriefStatus(err.message || 'Не удалось отправить тестовое. Проверьте настройки Telegram.')
      setBriefStatusTone('warn')
    } finally {
      setIsLoadingBrief(false)
    }
  }

  return (
    <>
      <TopBar title={t('nav.reports')} />
      <Mast screen="reports" />
      <Headline title={t('nav.reports')}>
        <div className="figs inline">
          <div className="f">
            <div className="f-v">{view.activeGoalsCount}</div>
            <div className="f-l">Активные цели</div>
          </div>
          <div className="f">
            <div className="f-v">{view.digestsCount}</div>
            <div className="f-l">Дайджесты</div>
          </div>
          <div className="f">
            <div className="f-v">
              {view.latestDigest?.date || '—'}
            </div>
            <div className="f-l">Последний дайджест</div>
          </div>
        </div>
      </Headline>

      <p className="sub lede">
        ИИ-дайджесты по неделям и отслеживание долгосрочных целей по всем доменам.
      </p>

      <div className="grid mt-6">
        {/* Left Column: Goals */}
        <div className="c5">
          <section className="sec o1">
            <div className="sec-h">
              <h2>Цели</h2>
              <button
                type="button"
                className="ghost"
                onClick={() => setGoalFormOpen(true)}
              >
                <Icon name="plus" />
                <span>Цель</span>
              </button>
            </div>

            {/* Goal form modal */}
            {goalFormOpen && (
              <div className="panel fpanel mb-4">
                <div className="panel-h">
                  <h3>Новая цель</h3>
                  <button type="button" className="ibtn" onClick={() => setGoalFormOpen(false)}>
                    <Icon name="x" />
                  </button>
                </div>
                <div className="space-y-3">
                  <label className="field">
                    <span className="flabel">Название</span>
                    <input
                      className="input"
                      placeholder="Дойти до 82 кг"
                      value={goalName}
                      onChange={(e) => setGoalName(e.target.value)}
                    />
                  </label>
                  <div className="grid grid-cols-2 gap-3">
                    <label className="field">
                      <span className="flabel">Домен</span>
                      <select
                        className="input"
                        value={goalDom}
                        onChange={(e) => setGoalDom(e.target.value)}
                      >
                        {view.goalDomains.map((d) => (
                          <option key={d} value={d}>
                            {DOM_RU[d] || d}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field">
                      <span className="flabel">Дедлайн</span>
                      <input
                        type="date"
                        className="input"
                        value={goalDeadline}
                        onChange={(e) => setGoalDeadline(e.target.value)}
                      />
                    </label>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <label className="field">
                      <span className="flabel">Цель</span>
                      <input
                        className="input"
                        placeholder="82"
                        value={goalTarget}
                        onChange={(e) => setGoalTarget(e.target.value)}
                      />
                    </label>
                    <label className="field">
                      <span className="flabel">Ед.</span>
                      <input
                        className="input"
                        placeholder="кг"
                        value={goalUnit}
                        onChange={(e) => setGoalUnit(e.target.value)}
                      />
                    </label>
                  </div>
                  <div className="form-acts flex gap-2 pt-2">
                    <PrimaryButton
                      className="btn grow"
                      onPress={handleCreateGoal}
                      disabled={isSubmittingGoal}
                    >
                      Создать цель
                    </PrimaryButton>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setGoalFormOpen(false)}
                    >
                      {t('common.cancel')}
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Active Goals List */}
            {view.activeGoals.length > 0 ? (
              <div className="goals">
                {view.activeGoals.map((g: MilestoneItem) => {
                  const pct = Math.min(Math.max(g.pct ?? 0, 0), 100)
                  const tone = DOM_TONE[g.domain] || 'good'
                  return (
                    <div key={g.id} className="goal" data-item>
                      <div className="goal-h">
                        <div>
                          <div className="t">{g.name}</div>
                          <div className="m">
                            <Badge tone={tone}>{DOM_RU[g.domain] || g.domain}</Badge>
                            {g.deadline && (
                              <span className="num"> · дедлайн {g.deadline}</span>
                            )}
                            {g.daysLeft != null && (
                              <span className="num"> · {g.daysLeft} дн.</span>
                            )}
                          </div>
                        </div>
                        <div className="v">
                          {g.current != null ? g.current : '—'}
                          <span className="u">
                            / {g.targetValue} {g.targetUnit || ''}
                          </span>
                        </div>
                        <span className="acts">
                          <button
                            type="button"
                            className="ibtn"
                            title="Отметить достигнутой"
                            onClick={() => handleGoalStatus(g.id, 'achieved')}
                          >
                            <Icon name="check" />
                          </button>
                          <button
                            type="button"
                            className="ibtn"
                            onClick={() => handleDeleteGoal(g.id)}
                            aria-label={t('common.delete')}
                          >
                            <Icon name="trash" />
                          </button>
                        </span>
                      </div>
                      <div className="meter">
                        <i style={{ width: `${pct}%` }} />
                        <span className="tick" style={{ left: '25%' }} />
                        <span className="tick" style={{ left: '50%' }} />
                        <span className="tick" style={{ left: '75%' }} />
                      </div>
                      <div className="goal-scale">
                        <span>{pct.toFixed(0)}%</span>
                        <span>
                          {g.remaining != null ? `осталось ${g.remaining} ${g.targetUnit || ''}` : ''}
                        </span>
                        <span>{g.targetValue}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="empty">
                <Icon name="chart" />
                <p>Активных целей пока нет.</p>
              </div>
            )}
          </section>

          {/* Closed Goals List */}
          {view.closedGoals.length > 0 && (
            <section className="sec o2">
              <div className="sec-h">
                <h2>Архив целей</h2>
                <span className="meta">{view.closedGoals.length}</span>
              </div>
              <div className="rows">
                {view.closedGoals.map((g) => {
                  const ok = g.status === 'achieved'
                  return (
                    <div
                      key={g.id}
                      className={`row arch-g ${ok ? 'ok' : 'dim-soft'}`}
                      style={{ gridTemplateColumns: '22px minmax(0,1fr) auto' }}
                    >
                      <Icon name={ok ? 'check' : 'x'} />
                      <div>
                        <div className="t">{g.name}</div>
                        <div className="m num">
                          {ok
                            ? `взята ${g.closedOn || ''}`
                            : 'не взята'}
                        </div>
                      </div>
                      <span className="acts">
                        <button
                          type="button"
                          className="ibtn"
                          onClick={() => handleDeleteGoal(g.id)}
                          aria-label={t('common.delete')}
                        >
                          <Icon name="trash" />
                        </button>
                      </span>
                    </div>
                  )
                })}
              </div>
            </section>
          )}
        </div>

        {/* Right Column: Weekly Digest & Morning Brief */}
        <div className="c7">
          <section className="sec o3">
            <div className="sec-h">
              <h2>Еженедельный разбор</h2>
              {view.latestDigest && (
                <span className="meta num">
                  {view.latestDigest.date}
                  {view.latestDigest.model ? ` · ${view.latestDigest.model}` : ''}
                </span>
              )}
            </div>
            <div className="dg-bar">
              <div className="opts flex gap-1 flex-wrap">
                {[1, 3, 7, 30].map((d) => (
                  <button
                    key={d}
                    type="button"
                    className={`opt ${digestDays === d ? 'on' : ''}`}
                    onClick={() => setDigestDays(d)}
                  >
                    За {d} {d === 1 ? 'день' : d < 5 ? 'дня' : 'дней'}
                  </button>
                ))}
              </div>
              <button
                type="button"
                className="ghost"
                onClick={handleGenerateDigest}
                disabled={isGeneratingDigest}
              >
                <Icon name="sync" />
                <span>{isGeneratingDigest ? 'Генерация...' : 'Собрать сейчас'}</span>
              </button>
            </div>

            {view.latestDigest ? (
              <article className="digest">
                <div
                  dangerouslySetInnerHTML={{ __html: view.latestDigest.content }}
                />
              </article>
            ) : (
              <div className="empty">
                <Icon name="doc" />
                <p>
                  Разборов ещё нет. Они собираются раз в неделю или по кнопке «Собрать сейчас».
                </p>
              </div>
            )}

            {view.digestHistory.length > 0 && (
              <div className="acc dg-prev">
                <div
                  className="acc-h flex items-center justify-between cursor-pointer py-3"
                  role="button"
                  tabIndex={0}
                  onClick={() => setOlderDigestsOpen(!olderDigestsOpen)}
                >
                  <span>
                    Предыдущие разборы <span className="m num">({view.digestHistory.length})</span>
                  </span>
                  <Icon name="chevD" />
                </div>
                {olderDigestsOpen && (
                  <div className="rows">
                    {view.digestHistory.map((d) => (
                      <div
                        key={d.id}
                        className="row"
                        style={{ gridTemplateColumns: '84px minmax(0,1fr)' }}
                      >
                        <span className="m num">{d.date}</span>
                        <span className="dg-old text-sm line-clamp-1">
                          {d.content.slice(0, 100).replace(/<[^>]*>?/gm, '')}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>

          {/* Morning Brief Section */}
          <section className="sec o4">
            <div className="sec-h">
              <h2>Утренний бриф</h2>
              {view.latestBrief && (
                <span className="meta num">
                  {view.latestBrief.date}
                  {view.latestBrief.model ? ` · ${view.latestBrief.model}` : ''}
                </span>
              )}
            </div>
            <p className="sub" style={{ margin: '-4px 0 12px' }}>
              Бот присылает его в 11:00. «Собрать» — только показать здесь, ничего не отправляя.
            </p>
            <div className="row-acts flex gap-2">
              <button
                type="button"
                className="ghost"
                onClick={handleBuildBrief}
                disabled={isLoadingBrief}
              >
                <Icon name="sync" />
                <span>Собрать бриф</span>
              </button>
              <button
                type="button"
                className="ghost"
                onClick={handleTestBrief}
                disabled={isLoadingBrief}
              >
                <Icon name="signals" />
                <span>Отправить тестовое</span>
              </button>
            </div>

            {briefStatus && (
              <div className={`alert ${briefStatusTone} mt-3`}>
                <Icon name={briefStatusTone === 'info' ? 'check' : 'warn'} />
                <div>{briefStatus}</div>
              </div>
            )}

            {view.latestBrief ? (
              <div className="brief mt-3">
                {view.latestBrief.content.split('\n').map((line, idx) => (
                  <p key={idx}>{line}</p>
                ))}
              </div>
            ) : (
              <div className="empty">
                <Icon name="signals" />
                <p>
                  Брифов ещё нет. Они приходят в 11:00 или по кнопке «Собрать бриф».
                </p>
              </div>
            )}
          </section>
        </div>
      </div>
    </>
  )
}
