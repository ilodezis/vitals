import { Fragment, useState } from 'react'
import { useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { api, failText, InvalidError, ok } from '@/api/client'
import { useToday, useTodayIso } from '@/app/session'
import { OptionGroup } from '@/components/controls/Choices'
import { ConfirmButton } from '@/components/controls/ConfirmButton'
import { ConflictAlert } from '@/components/controls/ConflictAlert'
import { TextButton } from '@/components/controls/Marks'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { longDate, parseIsoDate, relativeDay } from '@/lib/dates'
import { formatCompact } from '@/lib/format'
import { useConflictMutation } from '@/lib/useConflictMutation'
import { doseLabel, drugName } from './doseLabel'
import { buildInjectionPatch, buildPhaseBody, drugOptions } from './glp1Forms'
import { SITE_IDS } from './sites'
import type { DosePhase, Injection, SiteId } from './types'

/** Everything a GLP-1 record changes: the screen, the day, the rail, and the weight chart's
 *  dose bands. */
export const refetchAfterGlp1 = (queryClient: QueryClient) =>
  Promise.all(['glp1', 'today', 'session', 'weight'].map((key) => queryClient.invalidateQueries({ queryKey: [key] })))

/** What every delete on the screen does once the server has answered. */
export function useGlp1Delete(remove: (id: number) => Promise<unknown>) {
  const { t } = useT()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: remove,
    onSuccess: async () => {
      await refetchAfterGlp1(queryClient)
      toast(t('common.deleted'))
    },
    onError: () => toast(t('app.delete_failed'), { icon: 'warn' }),
  })
}

function DrugSelect({ value, onChange }: { value: string; onChange: (drug: string) => void }) {
  const { t, tOr } = useT()
  return (
    <label className="field">
      <span className="flabel">{t('glp1.drug_label')}</span>
      <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
        {drugOptions(value).map((drug) => (
          <option key={drug} value={drug}>
            {drugName(drug, tOr)}
          </option>
        ))}
      </select>
    </label>
  )
}

/* ---------- Injections ---------- */

type SavedInjection = Injection & { id: number }

function InjectionEdit({ injection, siteName, onClose }: { injection: SavedInjection; siteName: (site: SiteId) => string; onClose: () => void }) {
  const { t } = useT()
  const queryClient = useQueryClient()
  const [date, setDate] = useState(injection.dateIso)
  const [dose, setDose] = useState(String(injection.doseMg))
  const [drug, setDrug] = useState(injection.drug ?? drugOptions(null)[0] ?? '')
  const [site, setSite] = useState<SiteId | null>(injection.site)
  const [note, setNote] = useState(injection.note ?? '')
  const body = buildInjectionPatch({ date, dose, drug, site, note })

  const save = useConflictMutation({
    mutationFn: async ({ override }) => {
      if (body === null) throw new InvalidError('')
      await ok(api.PATCH('/api/v1/glp1/injections/{injection_id}', { params: { path: { injection_id: injection.id } }, body: { ...body, override } }))
    },
    fallbackErrorMessage: t('app.save_failed'),
    onSuccess: async () => {
      await refetchAfterGlp1(queryClient)
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
          <span className="flabel">{t('glp1.dose_mg')}</span>
          <input
            className="input num"
            inputMode="decimal"
            value={dose}
            onChange={(e) => {
              setDose(e.target.value)
              save.clearConflict()
            }}
            required
          />
        </label>
      </div>
      <DrugSelect
        value={drug}
        onChange={(next) => {
          setDrug(next)
          save.clearConflict()
        }}
      />
      <div className="field">
        <span className="flabel">{t('glp1.site_header')}</span>
        {/* A second tap on the chosen site takes it off: an injection may have none. */}
        <OptionGroup
          label={t('glp1.site_header')}
          value={site ?? ''}
          onChange={(id) => setSite(id === site ? null : (id as SiteId))}
          options={SITE_IDS.map((id) => ({ id, label: siteName(id) }))}
        />
      </div>
      <label className="field">
        <span className="flabel">{t('common.note_optional')}</span>
        <input type="text" className="input" placeholder={t('glp1.note_placeholder')} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      <ConflictAlert violations={save.violations} onFix={() => save.clearConflict()} onSaveAnyway={() => void save.retryWithOverride()} />
      <div className="edit-acts">
        <button type="submit" className="btn" disabled={body === null || save.isPending}>
          {t('glp1.update_injection')}
        </button>
        <button type="button" className="ghost" onClick={onClose}>
          {t('app.cancel')}
        </button>
      </div>
    </form>
  )
}

/** The injections, newest first: each can be corrected or deleted. */
export function InjectionHistory({ injections, siteName }: { injections: readonly Injection[]; siteName: (site: SiteId | null) => string }) {
  const { t, lang } = useT()
  const today = useToday()
  const [editingId, setEditingId] = useState<number | null>(null)
  const labels = { today: t('app.today_word'), yesterday: t('app.yesterday_word') }
  const remove = useGlp1Delete((id) => ok(api.DELETE('/api/v1/glp1/injections/{injection_id}', { params: { path: { injection_id: id } } })))

  return (
    <div className="rows">
      {injections.map((j, i) => (
        <Fragment key={j.id ?? `${j.dateIso}-${i}`}>
          <div className="row r-inj">
            <div className="t">{relativeDay(parseIsoDate(j.dateIso), today, lang, labels)}</div>
            <span className="m">{siteName(j.site)}</span>
            <div className="v">
              {formatCompact(j.doseMg, lang, 3)}
              <span className="u">{t('app.unit.mg')}</span>
            </div>
            <div className="acts">
              {j.id !== undefined ? (
                <>
                  <button
                    type="button"
                    className="ibtn"
                    aria-label={t('common.edit')}
                    title={t('common.edit')}
                    aria-expanded={editingId === j.id}
                    onClick={() => setEditingId(editingId === j.id ? null : (j.id as number))}
                  >
                    <Icon name="edit" />
                  </button>
                  <ConfirmButton label={t('common.delete')} onConfirm={() => remove.mutate(j.id as number)} />
                </>
              ) : null}
            </div>
          </div>
          {j.id !== undefined && editingId === j.id ? <InjectionEdit injection={j as SavedInjection} siteName={siteName} onClose={() => setEditingId(null)} /> : null}
        </Fragment>
      ))}
    </div>
  )
}

/* ---------- Dose phases ---------- */

function PhaseForm({ drug: currentDrug, onClose }: { drug: string | null; onClose: () => void }) {
  const { t, lang } = useT()
  const queryClient = useQueryClient()
  const todayIso = useTodayIso()
  const [start, setStart] = useState(todayIso)
  const [end, setEnd] = useState('')
  const [drug, setDrug] = useState(currentDrug ?? drugOptions(null)[0] ?? '')
  const [dose, setDose] = useState('')
  const body = buildPhaseBody({ start, end, drug, dose })

  const save = useMutation({
    mutationFn: async () => {
      if (body === null) throw new InvalidError('')
      await ok(api.POST('/api/v1/glp1/cycles', { body }))
    },
    onSuccess: async () => {
      await refetchAfterGlp1(queryClient)
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
          <span className="flabel">{t('glp1.phase_start')}</span>
          <input type="date" className="input" value={start} onChange={(e) => setStart(e.target.value)} required />
        </label>
        <label className="field">
          <span className="flabel">{t('glp1.phase_end')}</span>
          <input type="date" className="input" value={end} min={start} onChange={(e) => setEnd(e.target.value)} />
        </label>
      </div>
      <div className="two">
        <DrugSelect value={drug} onChange={setDrug} />
        <label className="field">
          <span className="flabel">{t('glp1.dose_mg')}</span>
          <input className="input num" inputMode="decimal" placeholder={formatCompact(0.25, lang, 2)} value={dose} onChange={(e) => setDose(e.target.value)} required />
        </label>
      </div>
      <p className="sub flush">{t('glp1.phase_hint')}</p>
      <div className="edit-acts">
        <button type="submit" className="btn" disabled={body === null || save.isPending}>
          {t('glp1.save_phase')}
        </button>
        <button type="button" className="ghost" onClick={onClose}>
          {t('app.cancel')}
        </button>
      </div>
    </form>
  )
}

/** The dose over time, newest phase first: start a new one, end the running one, delete one. */
export function DosePhases({ phases, drug }: { phases: readonly DosePhase[]; drug: string | null }) {
  const { t, tOr, lang } = useT()
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)
  const remove = useGlp1Delete((id) => ok(api.DELETE('/api/v1/glp1/cycles/{cycle_id}', { params: { path: { cycle_id: id } } })))
  const close = useMutation({
    mutationFn: (id: number) => ok(api.POST('/api/v1/glp1/cycles', { body: { action: 'close', cycleId: id } })),
    onSuccess: async () => {
      await refetchAfterGlp1(queryClient)
      toast(t('app.glp1.phase_closed'))
    },
    onError: (err) => toast(failText(err, t('app.action_failed')), { icon: 'warn' }),
  })
  const newestFirst = [...phases].reverse()

  return (
    <Section
      title={t('glp1.phases_title')}
      meta={
        adding ? undefined : (
          <TextButton icon="plus" onClick={() => setAdding(true)}>
            {t('app.glp1.new_phase')}
          </TextButton>
        )
      }
    >
      <div className="rows">
        {adding ? <PhaseForm drug={drug} onClose={() => setAdding(false)} /> : null}
        {newestFirst.length === 0 ? (
          <div className="row">
            <span className="m">{t('glp1.no_phases')}</span>
          </div>
        ) : (
          newestFirst.map((p) => (
            <div key={p.id ?? p.fromIso} className="row r-kv">
              <div>
                <div className="t">{p.drug == null ? `${formatCompact(p.doseMg, lang, 3)} ${t('app.unit.mg')}` : doseLabel(p.drug, p.doseMg, lang, t, tOr)}</div>
                <div className="m">
                  {longDate(parseIsoDate(p.fromIso), lang)} — {p.open === true ? t('app.glp1.phase_current') : longDate(parseIsoDate(p.toIso), lang)}
                </div>
              </div>
              {p.id !== undefined ? (
                <div className="acts">
                  {p.open === true ? (
                    <TextButton disabled={close.isPending} onClick={() => close.mutate(p.id as number)}>
                      {t('app.glp1.close_phase')}
                    </TextButton>
                  ) : null}
                  <ConfirmButton label={t('common.delete')} onConfirm={() => remove.mutate(p.id as number)} />
                </div>
              ) : null}
            </div>
          ))
        )}
      </div>
    </Section>
  )
}
