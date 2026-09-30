import { Fragment, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, failText, InvalidError, ok } from '@/api/client'
import { ConfirmButton } from '@/components/controls/ConfirmButton'
import { ConflictAlert } from '@/components/controls/ConflictAlert'
import { Badge } from '@/components/controls/Marks'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useToday } from '@/app/session'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { parseIsoDate, relativeDay } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { useConflictMutation } from '@/lib/useConflictMutation'
import type { WeightHistoryRow, WeightSource } from './types'
import { buildWeightPatch } from './weightEdit'
import { refetchAfterWeight } from './weightLog'

const SOURCE_TONE: Record<WeightSource, 'good' | 'violet' | 'cool'> = { manual: 'good', bia: 'violet', garmin: 'cool' }

/** The editor of one weigh-in, opened under its row: the date, the weight, the note. A change
 *  the conflict engine holds back shows its rule with "Fix it" and "Save anyway". */
function WeightEdit({ row, onClose }: { row: WeightHistoryRow; onClose: () => void }) {
  const { t } = useT()
  const queryClient = useQueryClient()
  const [date, setDate] = useState(row.date)
  const [kg, setKg] = useState(String(row.kg))
  const [note, setNote] = useState(row.note ?? '')
  const body = buildWeightPatch({ date, kg, note })

  const save = useConflictMutation({
    mutationFn: async ({ override }) => {
      if (body === null) throw new InvalidError('')
      await ok(api.PATCH('/api/v1/weight/logs/{log_id}', { params: { path: { log_id: row.id } }, body: { ...body, override } }))
    },
    fallbackErrorMessage: t('app.save_failed'),
    onSuccess: async () => {
      await refetchAfterWeight(queryClient)
      toast(t('app.saved'))
      onClose()
    },
    onError: (err) => toast(failText(err, t('app.save_failed')), { icon: 'warn' }),
  })

  return (
    <form
      className="row-edit"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      <div className="two">
        <label className="field">
          <span className="flabel">{t('common.date')}</span>
          <input type="date" className="input" value={date} onChange={(e) => setDate(e.target.value)} required />
        </label>
        <label className="field">
          <span className="flabel">{t('weight.weight_kg')}</span>
          <input
            className="input num"
            inputMode="decimal"
            value={kg}
            onChange={(e) => {
              setKg(e.target.value)
              save.clearConflict()
            }}
            required
          />
        </label>
      </div>
      <label className="field">
        <span className="flabel">{t('app.weight.note_optional')}</span>
        <input type="text" className="input" placeholder={t('app.weight.note_placeholder')} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      <ConflictAlert violations={save.violations} onFix={() => save.clearConflict()} onSaveAnyway={() => void save.retryWithOverride()} />
      <div className="edit-acts">
        <button type="submit" className="btn" disabled={body === null || save.isPending}>
          {t('weight.update_weight')}
        </button>
        <button type="button" className="ghost" onClick={onClose}>
          {t('app.cancel')}
        </button>
      </div>
    </form>
  )
}

export function filterVisibleHistoryRows(
  rows: readonly WeightHistoryRow[],
  showSuperseded: boolean,
): readonly WeightHistoryRow[] {
  return showSuperseded ? rows : rows.filter((r) => !r.superseded)
}

/** Every weigh-in, newest first. One the person entered can be corrected; any of them can be
 *  deleted — and if it was the day's reading, the one it had outranked takes its place. */
export function WeightHistory({ rows }: { rows: readonly WeightHistoryRow[] }) {
  const { t, lang } = useT()
  const today = useToday()
  const queryClient = useQueryClient()
  const [editingId, setEditingId] = useState<number | null>(null)
  const [showSuperseded, setShowSuperseded] = useState(false)
  const labels = { today: t('app.today_word'), yesterday: t('app.yesterday_word') }

  const supersededCount = rows.filter((r) => r.superseded).length
  const displayedRows = filterVisibleHistoryRows(rows, showSuperseded)

  const remove = useMutation({
    mutationFn: (id: number) => ok(api.DELETE('/api/v1/weight/logs/{log_id}', { params: { path: { log_id: id } } })),
    onSuccess: async () => {
      await refetchAfterWeight(queryClient)
      toast(t('common.deleted'))
    },
    onError: () => toast(t('app.delete_failed'), { icon: 'warn' }),
  })

  return (
    <>
      {displayedRows.map((h) => (
        <Fragment key={h.id}>
          <div className={cx('row', 'r-hist', h.superseded && 'dim')}>
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
            <div className="acts">
              {/* Only what the person entered can be corrected; an import is what the device said. */}
              {h.source === 'manual' ? (
                <button
                  type="button"
                  className="ibtn"
                  aria-label={t('common.edit')}
                  title={t('common.edit')}
                  aria-expanded={editingId === h.id}
                  onClick={() => setEditingId(editingId === h.id ? null : h.id)}
                >
                  <Icon name="edit" />
                </button>
              ) : null}
              <ConfirmButton label={t('common.delete')} onConfirm={() => remove.mutate(h.id)} />
            </div>
          </div>
          {editingId === h.id ? <WeightEdit row={h} onClose={() => setEditingId(null)} /> : null}
        </Fragment>
      ))}
      {supersededCount > 0 && (
        <button
          type="button"
          className="ghost more-btn superseded-toggle"
          onClick={() => setShowSuperseded((s) => !s)}
        >
          {showSuperseded
            ? t('app.weight.hide_superseded')
            : t('app.weight.show_superseded_n', { count: supersededCount })}
        </button>
      )}
    </>
  )
}
