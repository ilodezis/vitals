import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, ok, failText } from '@/api/client'
import { Disclosure } from '@/components/controls/Disclosure'
import { Badge } from '@/components/controls/Marks'
import { Meter } from '@/components/controls/Meters'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { parseIsoDate, shortDate } from '@/lib/dates'
import { formatCompact, formatNumber, formatPercent } from '@/lib/format'
import { Markdown } from '@/lib/markdown'
import type { MilestoneItem } from './types'
import { useReportsView } from './useReportsView'
import './reports.css'

const DOM_TONE: Record<string, 'good' | 'cool' | 'violet'> = {
  weight: 'good',
  labs: 'cool',
  garmin: 'violet',
}

export default function ReportsScreen() {
  const { t, tOr, lang } = useT()
  const view = useReportsView()
  const queryClient = useQueryClient()

  // Goal modal states
  const [goalFormOpen, setGoalFormOpen] = useState(false)
  const [goalName, setGoalName] = useState('')
  const [goalDom, setGoalDom] = useState('weight')
  const [goalTarget, setGoalTarget] = useState('')
  const [goalUnit, setGoalUnit] = useState(() => t('app.unit.kg'))
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

  const getDomainLabel = (d: string): string => tOr(`nav.${d}`, tOr(`app.domain.${d}`, d))

  const handleCreateGoal = async (): Promise<boolean> => {
    if (!goalName.trim()) {
      toast(t('app.name_required'), { icon: 'warn' })
      return false
    }
    setIsSubmittingGoal(true)
    try {
      await ok(api.POST('/api/v1/reports/milestones', {
        body: {
          name: goalName.trim(),
          domain: goalDom,
          targetValue: parseFloat(goalTarget) || null,
          targetUnit: goalUnit.trim() || null,
          deadline: goalDeadline || null,
        },
      }))
      toast(t('app.reports.toast_goal_created'))
      setGoalFormOpen(false)
      setGoalName('')
      refresh()
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    } finally {
      setIsSubmittingGoal(false)
    }
  }

  const handleGoalStatus = async (id: number, status: string) => {
    try {
      await ok(api.PATCH('/api/v1/reports/milestones/{milestone_id}/status', {
        params: { path: { milestone_id: id } },
        body: { status },
      }))
      toast(t('app.reports.toast_status_updated'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    }
  }

  const handleDeleteGoal = async (id: number) => {
    try {
      await ok(api.DELETE('/api/v1/reports/milestones/{milestone_id}', {
        params: { path: { milestone_id: id } },
      }))
      toast(t('common.deleted'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.delete_failed')), { icon: 'warn' })
    }
  }

  const handleGenerateDigest = async () => {
    setIsGeneratingDigest(true)
    try {
      await ok(api.POST('/api/v1/reports/digests', {
        body: { periodDays: digestDays },
      }))
      toast(t('app.reports.toast_digest_ready'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.reports.toast_digest_failed')), { icon: 'warn' })
    } finally {
      setIsGeneratingDigest(false)
    }
  }

  const handleBuildBrief = async () => {
    setIsLoadingBrief(true)
    setBriefStatus(null)
    try {
      await ok(api.POST('/api/v1/reports/briefs/build', {}))
      setBriefStatus(t('app.reports.brief_built'))
      setBriefStatusTone('info')
      refresh()
    } catch (err) {
      setBriefStatus(failText(err, t('app.action_failed')))
      setBriefStatusTone('warn')
    } finally {
      setIsLoadingBrief(false)
    }
  }

  const handleTestBrief = async () => {
    setIsLoadingBrief(true)
    setBriefStatus(null)
    try {
      await ok(api.POST('/api/v1/reports/briefs/test', {}))
      setBriefStatus(t('app.reports.brief_test_sent'))
      setBriefStatusTone('info')
      refresh()
    } catch (err) {
      setBriefStatus(failText(err, t('app.action_failed')))
      setBriefStatusTone('warn')
    } finally {
      setIsLoadingBrief(false)
    }
  }

  const formatDaysOpt = (d: number): string => {
    const key =
      d === 1
        ? 'app.reports.opt_1_d'
        : d === 3
          ? 'app.reports.opt_3_d'
          : d === 7
            ? 'app.reports.opt_7_d'
            : 'app.reports.opt_30_d'
    return t(key)
  }

  return (
    <>
      <TopBar title={t('nav.reports')} />
      <Mast screen="reports" />
      <Headline title={t('nav.reports')}>
        <div className="figs inline">
          <div className="f">
            <div className="f-v">{view.activeGoalsCount}</div>
            <div className="f-l">{t('app.reports.active_goals')}</div>
          </div>
          <div className="f">
            <div className="f-v">{view.digestsCount}</div>
            <div className="f-l">{t('app.reports.digests_count')}</div>
          </div>
          <div className="f">
            <div className="f-v">
              {view.latestDigest?.date ? shortDate(parseIsoDate(view.latestDigest.date), lang) : '—'}
            </div>
            <div className="f-l">{t('app.reports.latest_digest')}</div>
          </div>
        </div>
      </Headline>

      <p className="sub lede">
        {t('app.reports.lede')}
      </p>

      <div className="rep-grid">
        {/* Left Column: Goals */}
        <div className="c5">
          <section className="sec o1">
            <div className="sec-h">
              <h2>{t('app.reports.goals_title')}</h2>
              <button
                type="button"
                className="ghost"
                onClick={() => setGoalFormOpen(true)}
              >
                <Icon name="plus" />
                <span>{t('app.reports.add_goal')}</span>
              </button>
            </div>

            {/* Goal form modal */}
            {goalFormOpen && (
              <div className="panel fpanel rep-fpanel">
                <div className="panel-h">
                  <h3>{t('app.reports.new_goal')}</h3>
                  <button type="button" className="ibtn" onClick={() => setGoalFormOpen(false)}>
                    <Icon name="x" />
                  </button>
                </div>
                <div className="rep-form">
                  <label className="field">
                    <span className="flabel">{t('app.timeline.title_label')}</span>
                    <input
                      className="input"
                      placeholder={t('app.reports.goal_name_ph')}
                      value={goalName}
                      onChange={(e) => setGoalName(e.target.value)}
                    />
                  </label>
                  <div className="rep-grid-2">
                    <label className="field">
                      <span className="flabel">{t('app.reports.domain_label')}</span>
                      <select
                        className="input"
                        value={goalDom}
                        onChange={(e) => setGoalDom(e.target.value)}
                      >
                        {view.goalDomains.map((d) => (
                          <option key={d} value={d}>
                            {getDomainLabel(d)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field">
                      <span className="flabel">{t('app.reports.deadline_label')}</span>
                      <input
                        type="date"
                        className="input"
                        value={goalDeadline}
                        onChange={(e) => setGoalDeadline(e.target.value)}
                      />
                    </label>
                  </div>
                  <div className="rep-grid-2">
                    <label className="field">
                      <span className="flabel">{t('app.reports.target_label')}</span>
                      <input
                        className="input"
                        placeholder={t('app.reports.target_val_ph')}
                        value={goalTarget}
                        onChange={(e) => setGoalTarget(e.target.value)}
                      />
                    </label>
                    <label className="field">
                      <span className="flabel">{t('app.reports.unit_label')}</span>
                      <input
                        className="input"
                        placeholder={t('app.reports.unit_val_ph')}
                        value={goalUnit}
                        onChange={(e) => setGoalUnit(e.target.value)}
                      />
                    </label>
                  </div>
                  <div className="rep-acts">
                    <PrimaryButton
                      className="btn grow"
                      onPress={handleCreateGoal}
                      disabled={isSubmittingGoal}
                    >
                      {t('app.reports.create_goal_btn')}
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
                  const pct = g.pct != null ? Math.min(Math.max(g.pct, 0), 100) : null
                  const tone = DOM_TONE[g.domain] || 'good'
                  return (
                    <div key={g.id} className="goal" data-item>
                      <div className="goal-h">
                        <div>
                          <div className="t">{g.name}</div>
                          <div className="m">
                            <Badge tone={tone}>{getDomainLabel(g.domain)}</Badge>
                            {g.deadline && (
                              <span className="num"> · {t('app.reports.deadline_at', { date: shortDate(parseIsoDate(g.deadline), lang) })}</span>
                            )}
                            {g.daysLeft != null && (
                              <span className="num"> · {t('app.reports.days_left_n', { days: formatNumber(g.daysLeft, lang, 0) })}</span>
                            )}
                          </div>
                        </div>
                        <div className="v">
                          {g.current != null ? formatNumber(g.current, lang) : '—'}
                          <span className="u">
                            / {g.targetValue != null ? formatCompact(g.targetValue, lang) : '—'} {g.targetUnit || ''}
                          </span>
                        </div>
                        <span className="acts">
                          <button
                            type="button"
                            className="ibtn"
                            title={t('app.reports.mark_achieved')}
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
                      {pct != null && (
                        <>
                          <Meter value={pct} ticks={[25, 50, 75]} />
                          <div className="goal-scale">
                            <span>{formatPercent(pct, lang)}</span>
                            <span>
                              {g.remaining != null ? t('app.reports.remaining_val', { rem: formatNumber(g.remaining, lang), unit: g.targetUnit || '' }) : ''}
                            </span>
                            <span>{g.targetValue != null ? formatCompact(g.targetValue, lang) : ''}</span>
                          </div>
                        </>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="empty">
                <Icon name="chart" />
                <p>{t('app.reports.no_active_goals')}</p>
              </div>
            )}
          </section>

          {/* Closed Goals List */}
          {view.closedGoals.length > 0 && (
            <section className="sec o2">
              <div className="sec-h">
                <h2>{t('app.reports.archive_goals')}</h2>
                <span className="meta">{view.closedGoals.length}</span>
              </div>
              <div className="rows">
                {view.closedGoals.map((g) => {
                  const achieved = g.status === 'achieved'
                  return (
                    <div key={g.id} className={`row arch-g ${achieved ? 'ok' : 'dim-soft'}`}>
                      <Icon name={achieved ? 'check' : 'x'} />
                      <div>
                        <div className="t">{g.name}</div>
                        <div className="m num">
                          {achieved
                            ? t('app.reports.achieved_on', { date: g.closedOn ? shortDate(parseIsoDate(g.closedOn), lang) : '' })
                            : t('app.reports.not_achieved')}
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
              <h2>{t('app.reports.weekly_digest')}</h2>
              {view.latestDigest && (
                <span className="meta num">
                  {view.latestDigest.date ? shortDate(parseIsoDate(view.latestDigest.date), lang) : ''}
                  {view.latestDigest.model ? ` · ${view.latestDigest.model}` : ''}
                </span>
              )}
            </div>
            <div className="dg-bar">
              <div className="opts rep-opts">
                {[1, 3, 7, 30].map((d) => (
                  <button
                    key={d}
                    type="button"
                    className={`opt ${digestDays === d ? 'on' : ''}`}
                    onClick={() => setDigestDays(d)}
                  >
                    {formatDaysOpt(d)}
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
                <span>{isGeneratingDigest ? t('app.reports.generating') : t('app.reports.generate_now')}</span>
              </button>
            </div>

            {view.latestDigest ? (
              <article className="digest">
                <Markdown source={view.latestDigest.content} />
              </article>
            ) : (
              <div className="empty">
                <Icon name="doc" />
                <p>
                  {t('app.reports.no_digests')}
                </p>
              </div>
            )}

            {view.digestHistory.length > 0 && (
              <Disclosure
                className="dg-prev"
                open={olderDigestsOpen}
                onToggle={() => setOlderDigestsOpen(!olderDigestsOpen)}
                title={t('app.reports.previous_digests')}
                count={view.digestHistory.length}
              >
                <div className="rows">
                  {view.digestHistory.map((d) => (
                    <div key={d.id} className="row dg-row">
                      <span className="m num">{d.date ? shortDate(parseIsoDate(d.date), lang) : ''}</span>
                      <article className="digest dg-old">
                        <Markdown source={d.content} />
                      </article>
                    </div>
                  ))}
                </div>
              </Disclosure>
            )}
          </section>

          {/* Morning Brief Section */}
          <section className="sec o4">
            <div className="sec-h">
              <h2>{t('app.reports.morning_brief')}</h2>
              {view.latestBrief && (
                <span className="meta num">
                  {view.latestBrief.date ? shortDate(parseIsoDate(view.latestBrief.date), lang) : ''}
                  {view.latestBrief.model ? ` · ${view.latestBrief.model}` : ''}
                </span>
              )}
            </div>
            <p className="sub brief-sub">{t('app.reports.brief_sub')}</p>
            <div className="row-acts rep-acts">
              <button
                type="button"
                className="ghost"
                onClick={handleBuildBrief}
                disabled={isLoadingBrief}
              >
                <Icon name="sync" />
                <span>{t('app.reports.build_brief')}</span>
              </button>
              <button
                type="button"
                className="ghost"
                onClick={handleTestBrief}
                disabled={isLoadingBrief}
              >
                <Icon name="signals" />
                <span>{t('app.reports.test_brief')}</span>
              </button>
            </div>

            {briefStatus && (
              <div className={`alert ${briefStatusTone} rep-alert`}>
                <Icon name={briefStatusTone === 'info' ? 'check' : 'warn'} />
                <div>{briefStatus}</div>
              </div>
            )}

            {view.latestBrief ? (
              <div className="brief rep-alert">
                {view.latestBrief.content.split('\n').map((line, idx) => (
                  <p key={idx}>{line}</p>
                ))}
              </div>
            ) : (
              <div className="empty">
                <Icon name="signals" />
                <p>
                  {t('app.reports.no_briefs')}
                </p>
              </div>
            )}
          </section>
        </div>
      </div>
    </>
  )
}
