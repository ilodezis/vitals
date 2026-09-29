import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { Badge } from '@/components/controls/Marks'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { toast } from '@/components/controls/toast'
import { Icon, type IconName } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import type { TimelineEventItem } from './types'
import { useTimelineView } from './useTimelineView'
import './timeline.css'

const DOM_RU: Record<string, string> = {
  weight: 'Вес',
  glp1: 'GLP-1',
  workouts: 'Тренировки',
  garmin: 'Garmin',
  labs: 'Анализы',
  skincare: 'Кожа',
  supplements: 'Добавки',
  genetics: 'Генетика',
  nutrition: 'Питание',
  timeline: 'Хронология',
}

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

const TL_KIND: Record<string, [string, string]> = {
  life_event: ['Событие', 'violet'],
  protocol_change: ['Смена протокола', 'cool'],
  injury: ['Травма', 'bad'],
  illness: ['Болезнь', 'bad'],
  trip: ['Поездка', 'warn'],
  note: ['Заметка', 'plain'],
  milestone: ['Цель', 'good'],
  photo: ['Фото', 'plain'],
  side_effect: ['Побочный эффект', 'bad'],
}

export default function TimelineScreen() {
  const { t } = useT()
  const [selectedDomain, setSelectedDomain] = useState('all')
  const view = useTimelineView(selectedDomain)
  const queryClient = useQueryClient()

  const [formOpen, setFormOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [date, setDate] = useState(() => view.today || new Date().toISOString().slice(0, 10))
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
      toast(t('common.required_field') || 'Title is required', { icon: 'warn' })
      return false
    }
    setIsSubmitting(true)
    try {
      await api.POST('/api/v1/timeline/annotations', {
        body: {
          title: title.trim(),
          date,
          endDate: endDate || null,
          kind,
          domain,
          note: note.trim() || null,
        },
      })
      toast(t('common.saved'))
      setFormOpen(false)
      setTitle('')
      setEndDate('')
      setNote('')
      refresh()
      return true
    } catch (err: any) {
      toast(err.message || 'Error saving event', { icon: 'warn' })
      return false
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDelete = async (item: TimelineEventItem) => {
    if (!item.id) return
    try {
      await api.DELETE('/api/v1/timeline/annotations/{annotation_id}', {
        params: { path: { annotation_id: item.id } },
      })
      toast(t('common.deleted'))
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error deleting event', { icon: 'warn' })
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

  const domainList = useMemo(() => {
    return Array.from(new Set(['weight', 'glp1', 'workouts', 'garmin', 'labs', 'skincare', 'supplements', 'timeline', ...view.domains]))
  }, [view.domains])

  return (
    <>
      <TopBar
        title={t('nav.timeline')}
        right={
          <button type="button" className="ibtn" onClick={() => setFormOpen(true)} aria-label="Добавить событие">
            <Icon name="plus" />
          </button>
        }
      />
      <Mast
        screen="timeline"
        actions={
          <button type="button" className="ghost" onClick={() => setFormOpen(true)}>
            <Icon name="plus" />
            <span>Добавить событие</span>
          </button>
        }
      />
      <Headline title={t('nav.timeline')}>
        <div className="figs inline">
          <div className="f">
            <div className="f-v">{view.totalCount || view.events.length}</div>
            <div className="f-l">Событий</div>
          </div>
          <div className="f">
            <div className="f-v">{view.manualCount}</div>
            <div className="f-l">Вручную</div>
          </div>
        </div>
      </Headline>

      <p className="sub lede">
        Все заметные события — залогированные автоматически или добавленные вручную — в одной
        ленте, и флажками на графиках.
      </p>

      {/* Add Event Form Modal */}
      {formOpen && (
        <div className="panel fpanel mb-6" style={{ marginTop: 'var(--s6)' }}>
          <div className="panel-h">
            <h3>Новое событие</h3>
            <button type="button" className="ibtn" onClick={() => setFormOpen(false)}>
              <Icon name="x" />
            </button>
          </div>
          <div className="form space-y-3">
            <label className="field">
              <span className="flabel">Название</span>
              <input
                className="input"
                placeholder="например, поездка в Грузию"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="field">
                <span className="flabel">Дата</span>
                <input
                  type="date"
                  className="input"
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="flabel">Дата окончания</span>
                <input
                  type="date"
                  className="input"
                  placeholder="Оставьте пустым для события в один день"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                />
              </label>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <label className="field">
                <span className="flabel">Тип</span>
                <select
                  className="input"
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                >
                  <option value="life_event">Событие</option>
                  <option value="protocol_change">Смена протокола</option>
                  <option value="injury">Травма</option>
                  <option value="illness">Болезнь</option>
                  <option value="trip">Поездка</option>
                  <option value="note">Заметка</option>
                </select>
              </label>
              <label className="field">
                <span className="flabel">Относится к</span>
                <select
                  className="input"
                  value={domain}
                  onChange={(e) => setDomain(e.target.value)}
                >
                  {domainList.map((d) => (
                    <option key={d} value={d}>
                      {DOM_RU[d] || d}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label className="field">
              <span className="flabel">Заметка</span>
              <textarea
                className="input"
                rows={2}
                placeholder="Детали, ощущения..."
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </label>
            <div className="form-acts flex gap-2 pt-2">
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
          Все
        </button>
        {domainList.map((d) => (
          <button
            key={d}
            type="button"
            className={`filter ${selectedDomain === d ? 'on' : ''}`}
            onClick={() => setSelectedDomain(d)}
          >
            {DOM_RU[d] || d}
          </button>
        ))}
      </div>

      {/* Timeline Feed */}
      <section className="sec tl-sec">
        {view.events.length > 0 ? (
          <div className="tl">
            {Array.from(groupedByDay.entries()).map(([dStr, events]) => (
              <div key={dStr} className="tl-day">
                <div className="d num">{dStr}</div>
                <div className="tl-list">
                  {events.map((e, idx) => {
                    const dom = e.domain || e.dom
                    const kindMeta = TL_KIND[e.kind] || ['Заметка', 'plain']
                    const tone = e.tone || kindMeta[1] || 'plain'
                    const domIcon = DOM_ICON[dom] || 'timeline'
                    return (
                      <div key={e.id ?? idx} className="tl-ev" data-item>
                        <i className={`tk ${tone}`} />
                        <div>
                          <div className="ev-h">
                            <Badge tone="plain">{kindMeta[0]}</Badge>
                            <span className="ev-dom">
                              <Icon name={domIcon} />
                              {DOM_RU[dom] || dom}
                            </span>
                            {e.endDate && (
                              <span className="m num">→ {e.endDate}</span>
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
                              aria-label="Удалить событие"
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
            <p>Пока нет событий в хронологии.</p>
          </div>
        )}
      </section>
    </>
  )
}
