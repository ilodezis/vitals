import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { Badge } from '@/components/controls/Marks'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import type { SupplementItem } from './types'
import { useSupplementsView } from './useSupplementsView'
import './supplements.css'

export default function SupplementsScreen() {
  const { t } = useT()
  const view = useSupplementsView()
  const queryClient = useQueryClient()

  const [formOpen, setFormOpen] = useState(false)
  const [editingItem, setEditingItem] = useState<SupplementItem | null>(null)
  const [archOpen, setArchOpen] = useState(false)

  // Form states
  const [name, setName] = useState('')
  const [dose, setDose] = useState('')
  const [timing, setTiming] = useState('morning')
  const [evidence, setEvidence] = useState('')
  const [active, setActive] = useState(true)
  const [contra, setContra] = useState('')
  const [note, setNote] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['supplements'] })
    void queryClient.invalidateQueries({ queryKey: ['today'] })
  }

  const openCreate = () => {
    setEditingItem(null)
    setName('')
    setDose('')
    setTiming('morning')
    setEvidence('')
    setActive(true)
    setContra('')
    setNote('')
    setFormOpen(true)
  }

  const openEdit = (item: SupplementItem) => {
    setEditingItem(item)
    setName(item.name)
    setDose(item.dose || '')
    setTiming(item.timing || 'morning')
    setEvidence(item.evidence || '')
    setActive(item.active)
    setContra(item.contraindications || item.contra || '')
    setNote(item.note || '')
    setFormOpen(true)
  }

  const handleSave = async (): Promise<boolean> => {
    if (!name.trim()) {
      toast(t('common.required_field') || 'Name is required', { icon: 'warn' })
      return false
    }
    setIsSubmitting(true)
    try {
      if (editingItem) {
        await api.PATCH('/api/v1/supplements/{supplement_id}', {
          params: { path: { supplement_id: editingItem.id } },
          body: {
            name: name.trim(),
            dose: dose.trim() || null,
            timing,
            evidence: evidence || null,
            active,
            contraindications: contra.trim() || null,
            note: note.trim() || null,
            override: false,
          },
        })
        toast(t('common.saved'))
      } else {
        await api.POST('/api/v1/supplements', {
          body: {
            name: name.trim(),
            dose: dose.trim() || null,
            timing,
            evidence: evidence || null,
            active,
            contraindications: contra.trim() || null,
            note: note.trim() || null,
            override: false,
          },
        })
        toast(t('common.saved'))
      }
      setFormOpen(false)
      refresh()
      return true
    } catch (err: any) {
      toast(err.message || 'Error saving supplement', { icon: 'warn' })
      return false
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleToggle = async (item: SupplementItem) => {
    try {
      await api.POST('/api/v1/supplements/{supplement_id}/toggle', {
        params: { path: { supplement_id: item.id } },
        body: { active: !item.active, override: false },
      })
      toast(item.active ? 'Перемещено в архив' : 'Восстановлено из архива')
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error toggling supplement', { icon: 'warn' })
    }
  }

  const handleDelete = async (item: SupplementItem) => {
    try {
      await api.DELETE('/api/v1/supplements/{supplement_id}', {
        params: { path: { supplement_id: item.id } },
      })
      toast(t('common.deleted'))
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error deleting supplement', { icon: 'warn' })
    }
  }

  const renderRow = (s: SupplementItem, archived = false) => {
    const evTone = s.evidence === 'A' ? 'good' : s.evidence === 'B' ? 'cool' : undefined
    const contraText = s.contraindications || s.contra
    return (
      <div key={s.id} className="row r-supp" data-item>
        <div>
          <div className="t">{s.name}</div>
          {contraText && !archived && (
            <div className="flag">
              <Icon name="warn" />
              <span>{contraText}</span>
            </div>
          )}
          {s.note && !archived && <div className="m">{s.note}</div>}
        </div>
        <span className="v">{s.dose || '—'}</span>
        {s.evidence ? (
          <Badge tone={evTone}>{`Tier ${s.evidence}`}</Badge>
        ) : (
          <span />
        )}
        <span className="acts">
          <button
            type="button"
            className="ibtn"
            onClick={() => openEdit(s)}
            aria-label={t('common.edit') || 'Редактировать'}
          >
            <Icon name="edit" />
          </button>
          <button
            type="button"
            className="ibtn"
            onClick={() => handleToggle(s)}
            aria-label={archived ? 'Восстановить' : 'В архив'}
          >
            <Icon name={archived ? 'sync' : 'archive'} />
          </button>
          <button
            type="button"
            className="ibtn"
            onClick={() => handleDelete(s)}
            aria-label={t('common.delete') || 'Удалить'}
          >
            <Icon name="trash" />
          </button>
        </span>
      </div>
    )
  }

  return (
    <>
      <TopBar
        title={t('nav.supplements')}
        right={
          <button type="button" className="ibtn" onClick={openCreate} aria-label="Новая добавка">
            <Icon name="plus" />
          </button>
        }
      />
      <Mast
        screen="supplements"
        actions={
          <button type="button" className="ghost" onClick={openCreate}>
            <Icon name="plus" />
            <span>Новая добавка</span>
          </button>
        }
      />
      <Headline title={t('nav.supplements')}>
        <div className="figs inline">
          <div className="f">
            <div className="f-v">{view.activeCount}</div>
            <div className="f-l">Активные</div>
          </div>
          <div className="f">
            <div className="f-v">{view.totalCount}</div>
            <div className="f-l">Всего</div>
          </div>
        </div>
      </Headline>

      {/* Form modal */}
      {formOpen && (
        <div className="panel fpanel mb-6" style={{ marginTop: 'var(--s6)' }}>
          <div className="panel-h">
            <h3>{editingItem ? 'Редактировать добавку' : 'Новая добавка'}</h3>
            <button type="button" className="ibtn" onClick={() => setFormOpen(false)}>
              <Icon name="x" />
            </button>
          </div>
          <div className="form space-y-3">
            <label className="field">
              <span className="flabel">Название</span>
              <input
                className="input"
                placeholder="например, Креатин моногидрат"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="field">
                <span className="flabel">Доза</span>
                <input
                  className="input"
                  placeholder="например, 5 г или 1 капсула"
                  value={dose}
                  onChange={(e) => setDose(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="flabel">Тайминг</span>
                <select
                  className="input"
                  value={timing}
                  onChange={(e) => setTiming(e.target.value)}
                >
                  <option value="morning">Утро</option>
                  <option value="day">День</option>
                  <option value="evening">Вечер</option>
                </select>
              </label>
            </div>
            <label className="field">
              <span className="flabel">Доказательность</span>
              <select
                className="input"
                value={evidence}
                onChange={(e) => setEvidence(e.target.value)}
              >
                <option value="">—</option>
                <option value="A">Tier A</option>
                <option value="B">Tier B</option>
                <option value="C">Tier C</option>
              </select>
            </label>
            <label className="field">
              <span className="flabel">Противопоказания</span>
              <textarea
                className="input"
                placeholder="например, не сочетать с..."
                value={contra}
                onChange={(e) => setContra(e.target.value)}
              />
            </label>
            <label className="field">
              <span className="flabel">Заметка</span>
              <input
                className="input"
                placeholder="..."
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </label>
            <div className="form-acts flex gap-2 pt-2">
              <PrimaryButton
                className="btn grow"
                onPress={handleSave}
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

      {/* Timing Groups */}
      {view.groups.map((g) => (
        <section key={g.key} className="sec tgrp">
          <div className="sec-h">
            <h2>
              <span className={`dot ${g.tone}`} />
              {g.label}
            </h2>
            {g.sub && <span className="meta">{g.sub}</span>}
          </div>
          <div className="rows">
            {g.items.length ? (
              g.items.map((s) => renderRow(s))
            ) : (
              <div className="row">
                <span className="m">Нет активных добавок на этот тайминг</span>
              </div>
            )}
          </div>
        </section>
      ))}

      {/* Archive Accordion */}
      <section className="sec">
        <div className="acc">
          <div
            className={`acc-h arch-h ${archOpen ? 'open' : ''}`}
            role="button"
            tabIndex={0}
            onClick={() => setArchOpen(!archOpen)}
          >
            <Icon name="archive" />
            <h2>
              Архив <span className="m num">({view.archived.length})</span>
            </h2>
            <Icon name="chevD" className="caret" />
          </div>
          {archOpen && (
            <div className="rows arch">
              {view.archived.length ? (
                view.archived.map((s) => renderRow(s, true))
              ) : (
                <div className="row">
                  <span className="m">Архив пуст</span>
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </>
  )
}
