import { useDeferredValue, useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, ok, failText } from '@/api/client'
import { Badge } from '@/components/controls/Marks'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { toast } from '@/components/controls/toast'
import { Icon, type IconName } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { parseIsoDate, shortDate } from '@/lib/dates'
import type { TimelineEventItem } from './types'
import { useTimelineView } from './useTimelineView'
import './timeline.css'
import { hasNewEventRequest, onNewEventRequest, takeNewEventRequest } from './newEventIntent'

const DOM_ICON: Record<string, IconName> = {
  weight: 'scale',
  glp1: 'syringe',
  workouts: 'dumbbell',
  garmin: 'pulse',
  labs: 'flask',
  skincare: 'skincare',
  supplements: 'pill',
  genetics: 'dna',
  nutrition: 'bowl',
  timeline: 'timeline',
}

const TL_KIND_TONE: Record<string, string> = {
  life_event: 'violet',
  protocol_change: 'cool',
  injury: 'bad',
  illness: 'bad',
  trip: 'warn',
  travel: 'warn',
  note: 'plain',
  milestone: 'good',
  photo: 'plain',
  side_effect: 'bad',
}


export default function TimelineScreen() {
  const { t, tOr, lang } = useT()
  const [selectedDomain, setSelectedDomain] = useState('all')
  // The list follows the chosen filter a beat later: the previous one stays on screen until the
  // next is read, instead of the screen blinking on every tap.
  const shownDomain = useDeferredValue(selectedDomain)
  const view = useTimelineView(shownDomain)
  const queryClient = useQueryClient()

  // Opened at once when another screen asked for a new event (Today's quick chip).
  const [formOpen, setFormOpen] = useState(hasNewEventRequest)
  useEffect(() => {
    takeNewEventRequest()
    return onNewEventRequest(() => {
      if (takeNewEventRequest()) setFormOpen(true)
    })
  }, [])
  const [title, setTitle] = useState('')
  const [date, setDate] = useState(view.today)
  const [endDate, setEndDate] = useState('')
  const [kind, setKind] = useState('life_event')
  const [domain, setDomain] = useState('timeline')
  const [note, setNote] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['timeline'] })
  }

  const handleCreate = async (): Promise<boolean> => {
    if (!title.trim()) {
      toast(t('app.name_required'), { icon: 'warn' })
      return false
    }
    setIsSubmitting(true)
    try {
      await ok(api.POST('/api/v1/timeline/annotations', {
        body: {
          title: title.trim(),
          date,
          endDate: endDate || null,
          kind,
          domain,
          note: note.trim() || null,
        },
      }))
      toast(t('common.saved'))
      setFormOpen(false)
      setTitle('')
      setEndDate('')
      setNote('')
      refresh()
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDelete = async (item: TimelineEventItem) => {
    if (!item.id) return
    try {
      await ok(api.DELETE('/api/v1/timeline/annotations/{annotation_id}', {
        params: { path: { annotation_id: item.id } },
      }))
      toast(t('common.deleted'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.delete_failed')), { icon: 'warn' })
    }
  }

  // Group events by day
  const groupedByDay = useMemo(() => {
    const map = new Map<string, TimelineEventItem[]>()
    for (const e of view.events) {
      if (!map.has(e.date)) map.set(e.date, [])
      map.get(e.date)!.push(e)
    }
    return map
  }, [view.events])

  const domainList = view.domains

  const getDomainLabel = (d: string): string => tOr(`nav.${d}`, tOr(`app.domain.${d}`, d))

  return (
    <>
      <TopBar
        title={t('nav.timeline')}
        right={
          <button type="button" className="ibtn" onClick={() => setFormOpen(true)} aria-label={t('app.timeline.add_event')}>
            <Icon name="plus" />
          </button>
        }
      />
      <Mast
        screen="timeline"
        actions={
          <button type="button" className="ghost" onClick={() => setFormOpen(true)}>
            <Icon name="plus" />
            <span>{t('app.timeline.add_event')}</span>
          </button>
        }
      />
      <Headline title={t('nav.timeline')}>
        <div className="figs inline">
          <div className="f">
            <div className="f-v">{view.totalCount || view.events.length}</div>
            <div className="f-l">{t('app.timeline.events_count')}</div>
          </div>
          <div className="f">
            <div className="f-v">{view.manualCount}</div>
            <div className="f-l">{t('app.timeline.manual_count')}</div>
          </div>
        </div>
      </Headline>

      <p className="sub lede">
        {t('app.timeline.lede')}
      </p>

      {/* Add Event Form Modal */}
      {formOpen && (
        <div className="panel fpanel tl-fpanel">
          <div className="panel-h">
            <h3>{t('app.timeline.new_event')}</h3>
            <button type="button" className="ibtn" onClick={() => setFormOpen(false)}>
              <Icon name="x" />
            </button>
          </div>
          <div className="tl-form">
            <label className="field">
              <span className="flabel">{t('app.timeline.title_label')}</span>
              <input
                className="input"
                placeholder={t('app.timeline.title_ph')}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
            <div className="tl-grid-2">
              <label className="field">
                <span className="flabel">{t('app.timeline.date_label')}</span>
                <input
                  type="date"
                  className="input"
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="flabel">{t('app.timeline.end_date_label')}</span>
                <input
                  type="date"
                  className="input"
                  placeholder={t('app.timeline.end_date_ph')}
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                />
              </label>
            </div>
            <div className="tl-grid-2">
              <label className="field">
                <span className="flabel">{t('app.timeline.type_label')}</span>
                <select
                  className="input"
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                >
                  {view.kinds.map((k) => (
                    <option key={k} value={k}>
                      {tOr(`app.timeline.kind.${k}`, k)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="flabel">{t('app.timeline.relates_to')}</span>
                <select
                  className="input"
                  value={domain}
                  onChange={(e) => setDomain(e.target.value)}
                >
                  {domainList.map((d) => (
                    <option key={d} value={d}>
                      {getDomainLabel(d)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label className="field">
              <span className="flabel">{t('app.timeline.note_label')}</span>
              <textarea
                className="input"
                rows={2}
                placeholder={t('app.timeline.note_ph')}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </label>
            <div className="tl-acts">
              <PrimaryButton
                className="btn grow"
                onPress={handleCreate}
                disabled={isSubmitting}
              >
                {t('common.save')}
              </PrimaryButton>
              <button
                type="button"
                className="ghost"
                onClick={() => setFormOpen(false)}
              >
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Domain Filters */}
      <div className="filters">
        <button
          type="button"
          className={`filter ${selectedDomain === 'all' ? 'on' : ''}`}
          onClick={() => setSelectedDomain('all')}
        >
          {t('app.timeline.filter_all')}
        </button>
        {domainList.map((d) => (
          <button
            key={d}
            type="button"
            className={`filter ${selectedDomain === d ? 'on' : ''}`}
            onClick={() => setSelectedDomain(d)}
          >
            {getDomainLabel(d)}
          </button>
        ))}
      </div>

      {/* Timeline Feed */}
      <section className="sec tl-sec" aria-busy={selectedDomain !== shownDomain}>
        {view.events.length > 0 ? (
          <div className="tl">
            {Array.from(groupedByDay.entries()).map(([dStr, events]) => (
              <div key={dStr} className="tl-day">
                <div className="d num">{shortDate(parseIsoDate(dStr), lang)}</div>
                <div className="tl-list">
                  {events.map((e, idx) => {
                    const dom = e.domain || e.dom
                    const kindLabel = tOr(`app.timeline.kind.${e.kind}`, e.kind)
                    const tone = e.tone || TL_KIND_TONE[e.kind] || 'plain'
                    const domIcon = DOM_ICON[dom] || 'timeline'
                    return (
                      <div key={e.id ?? idx} className="tl-ev" data-item>
                        <i className={`tk ${tone}`} />
                        <div>
                          <div className="ev-h">
                            <Badge tone="plain">{kindLabel}</Badge>
                            <span className="ev-dom">
                              <Icon name={domIcon} />
                              {getDomainLabel(dom)}
                            </span>
                            {e.endDate && (
                              <span className="m num">→ {shortDate(parseIsoDate(e.endDate), lang)}</span>
                            )}
                          </div>
                          <div className="t">{e.title}</div>
                          {e.detail && <div className="m">{e.detail}</div>}
                        </div>
                        <span className="acts">
                          {e.manual && (
                            <button
                              type="button"
                              className="ibtn"
                              onClick={() => handleDelete(e)}
                              aria-label={t('app.timeline.delete_event')}
                            >
                              <Icon name="trash" />
                            </button>
                          )}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty">
            <Icon name="timeline" />
            <p>{t('app.timeline.empty')}</p>
          </div>
        )}
      </section>
    </>
  )
}
