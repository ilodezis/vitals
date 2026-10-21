import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, failText, ok } from '@/api/client'
import { OptionGroup } from '@/components/controls/Choices'
import { ConfirmButton } from '@/components/controls/ConfirmButton'
import { Disclosure } from '@/components/controls/Disclosure'
import { TextButton } from '@/components/controls/Marks'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { longDate, parseIsoDate, shortDate, weekdayDate } from '@/lib/dates'
import { buildObservationScores } from './observationBody'
import { archivedLogs, dayProgress, SLOTS } from './plan'
import type { SkincareLogItem, SkincareView } from './types'

const ZONES = ['chin', 'cheeks', 'forehead', 'nose', 'back_shoulders'] as const
const SCORES = ['0', '1', '2', '3', '4', '5'] as const
const SLOT_ICON = { morning: 'today', evening: 'pulse' } as const

/** What was done, day by day, and how the skin looked. */
export function DiaryPane({ view }: { view: SkincareView }) {
  return (
    <>
      <History view={view} />
      <Observations view={view} />
      <Archive view={view} />
    </>
  )
}

function History({ view }: { view: SkincareView }) {
  const { t, lang } = useT()
  return (
    <Section title={t('app.skincare.history_title')} meta={t('app.skincare.history_sub')}>
      {view.history.length === 0 ? (
        <p className="m sk-none">{t('app.skincare.history_empty')}</p>
      ) : (
        <div className="rows">
          {view.history.map((day) => {
            const progress = dayProgress(day)
            return (
              <div key={day.date} className="sk-day">
                <div className="sk-day-h">
                  <span className="t">{weekdayDate(parseIsoDate(day.date), lang)}</span>
                  <span className={cx('m num', progress.done === progress.total && 'sk-all')}>
                    {t('app.skincare.progress', { done: progress.done, total: progress.total })}
                  </span>
                </div>
                {SLOTS.filter((slot) => day[slot].length > 0).map((slot) => (
                  <div key={slot} className="sk-day-slot">
                    <Icon name={SLOT_ICON[slot]} />
                    <span className="sk-pills">
                      {day[slot].map((item) => (
                        <span
                          key={`${item.productId ?? item.name}`}
                          className={cx('sk-pill', item.done ? 'on' : 'miss')}
                          title={item.done ? undefined : t('app.skincare.missed')}
                          aria-label={item.done ? undefined : `${item.name}, ${t('app.skincare.missed')}`}
                        >
                          {item.name}
                        </span>
                      ))}
                    </span>
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      )}
    </Section>
  )
}

function Observations({ view }: { view: SkincareView }) {
  const { t, tOr, lang } = useT()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [inflammation, setInflammation] = useState('')
  const [pih, setPih] = useState('')
  const [zone, setZone] = useState<string>('chin')
  const [note, setNote] = useState('')
  const scores = buildObservationScores({ inflammation, pih })

  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['skincare'] })

  const save = async (): Promise<boolean> => {
    if (scores === null) return false
    try {
      await ok(api.POST('/api/v1/skincare/observations', { body: { date: view.today, ...scores, zone, note: note.trim() || null } }))
      toast(t('app.skincare.toast_obs_saved'))
      setOpen(false)
      setInflammation('')
      setPih('')
      setNote('')
      refresh()
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  const remove = async (id: number) => {
    try {
      await ok(api.DELETE('/api/v1/skincare/observations/{obs_id}', { params: { path: { obs_id: id } } }))
      toast(t('common.deleted'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.delete_failed')), { icon: 'warn' })
    }
  }

  // A second tap on the chosen score takes it back: an empty score is "not rated".
  const score = (value: string, set: (v: string) => void) => (id: string) => set(id === value ? '' : id)

  return (
    <Section
      title={t('app.skincare.observations_title')}
      meta={
        !open && (
          <TextButton icon="plus" onClick={() => setOpen(true)}>
            {t('app.skincare.observation_add')}
          </TextButton>
        )
      }
    >
      {open && (
        <div className="panel fpanel mb-s4">
          <div className="panel-h">
            <h3>{t('app.skincare.state_score_today', { date: longDate(parseIsoDate(view.today), lang) })}</h3>
            <button type="button" className="ibtn" aria-label={t('app.close')} onClick={() => setOpen(false)}>
              <Icon name="x" />
            </button>
          </div>
          <div className="form sk-form">
            <div className="field">
              <span className="flabel">{t('app.skincare.face_zone')}</span>
              <OptionGroup
                label={t('app.skincare.face_zone')}
                value={zone}
                onChange={setZone}
                options={ZONES.map((z) => ({ id: z, label: t(`app.skincare.zone.${z}`) }))}
              />
            </div>
            <div className="field">
              <span className="flabel">{t('app.skincare.inflammation_scale')}</span>
              <OptionGroup
                label={t('app.skincare.inflammation_scale')}
                value={inflammation}
                onChange={score(inflammation, setInflammation)}
                options={SCORES.map((s) => ({ id: s, label: s }))}
              />
            </div>
            <div className="field">
              <span className="flabel">{t('app.skincare.pih_scale')}</span>
              <OptionGroup
                label={t('app.skincare.pih_scale')}
                value={pih}
                onChange={score(pih, setPih)}
                options={SCORES.map((s) => ({ id: s, label: s }))}
              />
            </div>
            <input className="input" placeholder={t('app.skincare.note_ph')} value={note} onChange={(e) => setNote(e.target.value)} />
            <div className="form-acts">
              <PrimaryButton className="btn grow" disabled={scores === null} onPress={save}>
                {t('common.save')}
              </PrimaryButton>
              <button type="button" className="ghost" onClick={() => setOpen(false)}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}
      {view.observations.length === 0 ? (
        !open && <p className="m sk-none">{t('app.empty')}</p>
      ) : (
        <div className="rows">
          {view.observations.map((o) => {
            const inf = o.inflammation ?? o.inf ?? '—'
            const p = o.pih ?? '—'
            const zoneLabel = o.zone ? tOr(`app.skincare.zone.${o.zone}`, o.zone) : '—'
            return (
              <div key={o.id} className="row sk-row" data-item>
                <div>
                  <div className="t num">{shortDate(parseIsoDate(o.date), lang)}</div>
                  <div className="m">
                    {t('app.skincare.obs_format', { inf, pih: p, zone: zoneLabel })}
                    {o.note && <> · {o.note}</>}
                  </div>
                </div>
                <span className="acts">
                  <ConfirmButton label={t('common.delete')} onConfirm={() => void remove(o.id)} />
                </span>
              </div>
            )
          })}
        </div>
      )}
    </Section>
  )
}

const LOG_FLAGS: readonly [keyof SkincareLogItem, string][] = [
  ['retinoid', 'retinoid'],
  ['azelaic', 'azelaic'],
  ['peel', 'peel'],
  ['niacinamideSpf', 'niacinamide_spf'],
  ['moisturizer', 'moisturizer'],
  ['vitaminC', 'vitamin_c'],
  ['benzoylPeroxide', 'benzoyl_peroxide'],
]

/** The hand-filled checklist from before the ticks: kept, read-only, out of the way. */
function Archive({ view }: { view: SkincareView }) {
  const { t, lang } = useT()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const logs = archivedLogs(view.logs, view.history, view.plan, view.today)
  if (logs.length === 0) return null

  const remove = async (id: number) => {
    try {
      await ok(api.DELETE('/api/v1/skincare/logs/{log_id}', { params: { path: { log_id: id } } }))
      toast(t('common.deleted'))
      void queryClient.invalidateQueries({ queryKey: ['skincare'] })
    } catch (err) {
      toast(failText(err, t('app.delete_failed')), { icon: 'warn' })
    }
  }

  return (
    <section className="sec">
      <Disclosure open={open} onToggle={() => setOpen(!open)} title={t('app.skincare.archive_title')} count={logs.length}>
        <div className="rows">
          {logs.map((l) => {
            const legacy = l as unknown as Record<string, unknown>
            const actives = LOG_FLAGS.filter(([camel, snake]) => Boolean(l[camel] ?? legacy[snake])).map(([, snake]) =>
              t(`app.skincare.act.${snake}`),
            )
            return (
              <div key={l.id} className="row sk-row" data-item>
                <div>
                  <div className="t num">{shortDate(parseIsoDate(l.date), lang)}</div>
                  <div className="m">
                    {actives.join(' · ') || '—'}
                    {l.note && <> · {l.note}</>}
                  </div>
                </div>
                <span className="acts">
                  <ConfirmButton label={t('common.delete')} onConfirm={() => void remove(l.id)} />
                </span>
              </div>
            )
          })}
        </div>
      </Disclosure>
    </section>
  )
}
