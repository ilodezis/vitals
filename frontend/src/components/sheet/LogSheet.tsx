import { useLayoutEffect, useMemo, useRef, useState, type PointerEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useToday, useTodayIso } from '@/app/session'
import { Alert } from '@/components/controls/Alert'
import { OptionGroup } from '@/components/controls/Choices'
import { ConflictAlert } from '@/components/controls/ConflictAlert'
import { PrimaryButton, type PrimaryButtonHandle } from '@/components/controls/PrimaryButton'
import { Segmented } from '@/components/controls/Segmented'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useLayout } from '@/components/shell/layout'
import { sheetCloses } from '@/components/shell/stageMotion'
import { siteUsage } from '@/features/glp1/sites'
import { useGlp1View } from '@/features/glp1/useGlp1View'
import { WeightForm } from '@/features/weight/WeightForm'
import { computeNavyFatPct } from '@/features/weight/navy'
import { measuresQuery } from '@/features/weight/WeightMeasuresScreen'
import { useT } from '@/i18n/useT'
import { parseIsoDate, weekdayLongDate } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { EASE_SHEET, animate, settle } from '@/lib/motion'
import { useClock } from '@/lib/useClock'
import { useConflictMutation } from '@/lib/useConflictMutation'
import { closeLogSheet, setLogTab, useLogSheet, type LogTab } from './logSheetStore'

const TABS: readonly LogTab[] = ['weight', 'meal', 'dose', 'measure']

/** Parse a user-typed decimal string that may use either comma or dot as decimal separator. */
export function parseLocaleNumber(raw: string): number | undefined {
  const cleaned = raw.trim().replace(',', '.')
  if (cleaned === '') return undefined
  const n = Number(cleaned)
  return Number.isFinite(n) ? n : undefined
}

export interface MealInput {
  date: string
  time: string
  name: string
  kcalRaw?: string
  proteinRaw?: string
  override?: boolean
}

export function buildMealBody(input: MealInput) {
  return {
    date: input.date,
    time: input.time || undefined,
    name: input.name.trim(),
    calories: parseLocaleNumber(input.kcalRaw ?? ''),
    protein_g: parseLocaleNumber(input.proteinRaw ?? ''),
    override: input.override ?? false,
  }
}

export interface InjectionInput {
  date: string
  mode: 'current' | 'other'
  currentDoseMg: number
  customDoseRaw?: string
  drug: string
  site: string
  override?: boolean
}

export function buildInjectionBody(input: InjectionInput) {
  const parsedCustom = parseLocaleNumber(input.customDoseRaw ?? '')
  const fallbackDose = input.currentDoseMg > 0 ? input.currentDoseMg : 0.5
  const doseMg = input.mode === 'other' && parsedCustom !== undefined && parsedCustom > 0 ? parsedCustom : fallbackDose
  return {
    date: input.date,
    doseMg,
    drug: input.drug || undefined,
    site: input.site,
    override: input.override ?? false,
  }
}

export interface MeasureInput {
  date: string
  waistRaw?: string
  neckRaw?: string
  override?: boolean
}

export function buildMeasureBody(input: MeasureInput) {
  return {
    date: input.date,
    waist_cm: parseLocaleNumber(input.waistRaw ?? ''),
    neck_cm: parseLocaleNumber(input.neckRaw ?? ''),
    override: input.override ?? false,
  }
}

export interface DoseAlertInfo {
  tone: 'warn' | 'info'
  textKey: 'app.log.dose.overdue' | 'app.log.dose.early'
  days: number
  evidenceKey?: 'app.log.dose.unscheduled'
}

export function selectDoseAlert(cycle: { daysToNext: number; overdue?: boolean }): DoseAlertInfo | null {
  const isOverdue = Boolean(cycle.overdue) || cycle.daysToNext < 0
  if (isOverdue) {
    return {
      tone: 'warn',
      textKey: 'app.log.dose.overdue',
      days: Math.abs(cycle.daysToNext),
    }
  }
  if (cycle.daysToNext > 0) {
    return {
      tone: 'warn',
      textKey: 'app.log.dose.early',
      days: cycle.daysToNext,
      evidenceKey: 'app.log.dose.unscheduled',
    }
  }
  return null
}

/** The closed position: below the screen on a phone, off to the right on a desktop. */
const closedTransform = (desktop: boolean): string => (desktop ? 'translateX(calc(100% + 24px))' : 'translateY(105%)')

export function LogSheet() {
  const { t } = useT()
  const { desktop } = useLayout()
  const { open, tab, opening, switched } = useLogSheet()
  const sheet = useRef<HTMLDivElement>(null)
  const scrim = useRef<HTMLDivElement>(null)
  const drag = useRef<{ pointer: number; y0: number; t0: number; dy: number } | null>(null)
  // The sheet stays drawn while it slides shut.
  const [visible, setVisible] = useState(false)
  const [entered, setEntered] = useState(false)

  useLayoutEffect(() => {
    const el = sheet.current
    if (el === null) return
    if (open) {
      setVisible(true)
      setEntered(true)
      // Held open by the inline style once the slide has finished; the class holds it shut.
      el.style.transform = 'none'
      animate(el, [{ transform: closedTransform(desktop) }, { transform: 'none' }], { duration: 520 })
        .finished.then(() => settle(el))
        .catch(() => undefined)
    } else if (entered) {
      animate(el, [{ transform: 'none' }, { transform: closedTransform(desktop) }], { duration: 380 })
        .finished.then(() => {
          el.style.transform = ''
          settle(el)
          setVisible(false)
        })
        .catch(() => undefined)
    }
  }, [open])

  /* ---------- Drag the sheet down to close it (phone) ---------- */
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    const el = sheet.current
    if (desktop || el === null) return
    if (!(e.target as Element).closest('[data-grab]') || (e.target as Element).closest('button')) return
    drag.current = { pointer: e.pointerId, y0: e.clientY, t0: performance.now(), dy: 0 }
    el.getAnimations().forEach((a) => a.cancel())
    try {
      el.setPointerCapture(e.pointerId)
    } catch {
      /* the pointer is already gone */
    }
  }
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    const el = sheet.current
    if (d === null || el === null || e.pointerId !== d.pointer) return
    const raw = e.clientY - d.y0
    // Downward follows the finger; upward resists.
    d.dy = raw > 0 ? raw : -Math.sqrt(-raw) * 2
    el.style.transform = `translateY(${d.dy}px)`
    if (scrim.current !== null) scrim.current.style.opacity = String(Math.min(1, Math.max(0, 1 - d.dy / el.offsetHeight)))
  }
  const onPointerUp = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    const el = sheet.current
    if (d === null || el === null || e.pointerId !== d.pointer) return
    drag.current = null
    if (scrim.current !== null) scrim.current.style.opacity = ''
    const velocity = d.dy / Math.max(1, performance.now() - d.t0)
    if (sheetCloses(d.dy, el.offsetHeight, velocity)) {
      const from = d.dy
      animate(el, [{ transform: `translateY(${from}px)` }, { transform: closedTransform(false) }], { duration: 300 })
        .finished.then(() => {
          el.style.transform = ''
          settle(el)
          setVisible(false)
          closeLogSheet()
        })
        .catch(() => undefined)
    } else {
      el.style.transition = `transform 420ms ${EASE_SHEET}`
      el.style.transform = 'none'
      window.setTimeout(() => {
        el.style.transition = ''
      }, 430)
    }
  }

  return (
    <>
      <div ref={scrim} className="scrim" onClick={closeLogSheet} />
      <div
        ref={sheet}
        className={visible ? 'sheet vis' : 'sheet'}
        role="dialog"
        aria-modal="true"
        aria-label={t('app.log')}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <div className="sheet-grab" data-grab>
          <i />
        </div>
        <div className="sheet-head" data-grab>
          <h3>{t('app.log')}</h3>
          <button type="button" className="ibtn" aria-label={t('app.close')} onClick={closeLogSheet}>
            <Icon name="x" />
          </button>
        </div>
        <div className="sheet-body">
          <Segmented
            options={TABS.map((id) => ({ id, label: t(`app.log.tab.${id}`) }))}
            value={tab}
            onChange={setLogTab}
            label={t('app.log')}
          />
          {/* Every opening starts the forms fresh: a reading typed and abandoned is not still there. */}
          <div key={opening}>
            {tab === 'weight' && <WeightPane enter={switched} />}
            {tab === 'meal' && <MealPane enter={switched} />}
            {tab === 'dose' && <DosePane enter={switched} />}
            {tab === 'measure' && <MeasurePane enter={switched} />}
          </div>
          <div style={{ height: 6 }} />
        </div>
      </div>
    </>
  )
}

/* ---------- Weight: the stepper, and the conflict ladder ---------- */
function WeightPane({ enter }: { enter: boolean }) {
  return (
    <div className={enter ? 'sheet-pane enter' : 'sheet-pane'} data-pane="weight">
      <WeightForm detailed onDone={closeLogSheet} resetMs={420} />
    </div>
  )
}

function MealPane({ enter }: { enter: boolean }) {
  const { t } = useT()
  const queryClient = useQueryClient()
  const todayIso = useTodayIso()
  const clock = useClock()
  const [name, setName] = useState('')
  const [kcal, setKcal] = useState('')
  const [protein, setProtein] = useState('')
  const [kind, setKind] = useState('lunch')
  const button = useRef<PrimaryButtonHandle>(null)

  const invalidateMealQueries = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['today'] }),
      queryClient.invalidateQueries({ queryKey: ['nutrition'] }),
      queryClient.invalidateQueries({ queryKey: ['session'] }),
    ])

  const conflict = useConflictMutation({
    mutationFn: async ({ override }) => {
      const body = buildMealBody({
        date: todayIso,
        time: clock,
        name,
        kcalRaw: kcal,
        proteinRaw: protein,
        override,
      })
      const { data } = await api.POST('/api/v1/nutrition/meals', { body })
      if (data === undefined) throw new Error(t('app.log.weight.failed'))
      toast(t('app.log.meal.saved'), {
        undo: () =>
          void api
            .DELETE('/api/v1/nutrition/meals/{meal_id}', { params: { path: { meal_id: data.id } } })
            .then(() => invalidateMealQueries()),
      })
      await invalidateMealQueries()
      return data
    },
    onError: (err) => {
      toast(err.message || t('app.log.weight.failed'), { icon: 'warn' })
    },
  })

  return (
    <div className={enter ? 'sheet-pane enter' : 'sheet-pane'} data-pane="meal">
      <label className="field">
        <span className="flabel">{t('app.log.meal.what')}</span>
        <input
          className="input"
          name="meal"
          placeholder={t('app.log.meal.placeholder')}
          value={name}
          onChange={(e) => {
            setName(e.target.value)
            conflict.clearConflict()
          }}
        />
      </label>
      <div className="two">
        <label className="field">
          <span className="flabel">{t('app.log.meal.kcal')}</span>
          <input
            className="input"
            name="kcal"
            inputMode="decimal"
            placeholder={t('app.unit.kcal')}
            value={kcal}
            onChange={(e) => {
              setKcal(e.target.value)
              conflict.clearConflict()
            }}
          />
        </label>
        <label className="field">
          <span className="flabel">{t('app.log.meal.protein')}</span>
          <input
            className="input"
            name="protein"
            inputMode="decimal"
            placeholder={t('app.unit.g')}
            value={protein}
            onChange={(e) => {
              setProtein(e.target.value)
              conflict.clearConflict()
            }}
          />
        </label>
      </div>
      <div className="field">
        <span className="flabel">{t('app.log.meal.kind')}</span>
        <OptionGroup
          value={kind}
          onChange={setKind}
          options={['breakfast', 'lunch', 'dinner', 'snack'].map((id) => ({ id, label: t(`app.log.meal.${id}`) }))}
        />
      </div>
      <ConflictAlert
        violations={conflict.violations}
        onFix={() => conflict.clearConflict()}
        onSaveAnyway={() => button.current?.press({ override: true })}
      />
      <div className={conflict.problem === null ? 'collapse' : 'collapse open'}>
        <div>
          <Alert tone="warn">{conflict.problem}</Alert>
        </div>
      </div>
      <PrimaryButton
        ref={button}
        className="w"
        disabled={name.trim() === ''}
        onPress={conflict.submit}
        onDone={closeLogSheet}
        resetMs={420}
      >
        {t('app.log.meal.save')}
      </PrimaryButton>
    </div>
  )
}

const SITES = ['abdomen_left', 'abdomen_right', 'shoulder_left', 'thigh_left', 'thigh_right', 'shoulder_right'] as const

function DosePane({ enter }: { enter: boolean }) {
  const { t, lang } = useT()
  const queryClient = useQueryClient()
  const today = useToday()
  const todayIso = useTodayIso()
  const view = useGlp1View()
  const usage = useMemo(() => siteUsage(view.injections, today, parseIsoDate), [view.injections, today])
  const leastUsedSite = usage[0]?.site ?? 'abdomen_left'

  const [drugMode, setDrugMode] = useState<'current' | 'other'>('current')
  const [customDose, setCustomDose] = useState('')
  const [selectedSite, setSelectedSite] = useState<string | null>(null)
  const site = selectedSite ?? leastUsedSite
  const button = useRef<PrimaryButtonHandle>(null)

  const invalidateGlp1Queries = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['glp1'] }),
      queryClient.invalidateQueries({ queryKey: ['today'] }),
      queryClient.invalidateQueries({ queryKey: ['session'] }),
    ])

  const conflict = useConflictMutation({
    mutationFn: async ({ override }) => {
      const body = buildInjectionBody({
        date: todayIso,
        mode: drugMode,
        currentDoseMg: view.doseMg,
        customDoseRaw: customDose,
        drug: view.drug,
        site,
        override,
      })
      const { data } = await api.POST('/api/v1/glp1/injections', { body })
      if (data === undefined) throw new Error(t('app.log.weight.failed'))
      toast(t('app.log.dose.saved', { site: t(`app.site.${site}`) }), {
        undo: () =>
          void api
            .DELETE('/api/v1/glp1/injections/{injection_id}', { params: { path: { injection_id: data.id } } })
            .then(() => invalidateGlp1Queries()),
      })
      await invalidateGlp1Queries()
      return data
    },
    onError: (err) => {
      toast(err.message || t('app.log.weight.failed'), { icon: 'warn' })
    },
  })

  const alertInfo = view.cycle.nextIso ? selectDoseAlert(view.cycle) : null

  return (
    <div className={enter ? 'sheet-pane enter' : 'sheet-pane'} data-pane="dose">
      <div className="field">
        <span className="flabel">{t('app.log.dose.drug')}</span>
        <OptionGroup
          value={drugMode}
          onChange={(id) => {
            setDrugMode(id as 'current' | 'other')
            conflict.clearConflict()
          }}
          options={[
            { id: 'current', label: t('app.log.dose.current') },
            { id: 'other', label: t('app.log.dose.other') },
          ]}
        />
      </div>
      {drugMode === 'other' && (
        <label className="field">
          <span className="flabel">{t('app.unit.mg')}</span>
          <input
            className="input"
            name="dose_mg"
            inputMode="decimal"
            placeholder={formatNumber(view.doseMg > 0 ? view.doseMg : 0.5, lang)}
            value={customDose}
            onChange={(e) => {
              setCustomDose(e.target.value)
              conflict.clearConflict()
            }}
          />
        </label>
      )}
      <div className="field">
        <span className="flabel">{t('app.log.dose.site')}</span>
        <OptionGroup
          value={site}
          onChange={(id) => {
            setSelectedSite(id)
            conflict.clearConflict()
          }}
          options={SITES.map((id) => ({
            id,
            label: t(`app.site.${id}`),
            hint: id === leastUsedSite ? t('app.glp1.least_used') : undefined,
          }))}
        />
      </div>
      {alertInfo !== null && (
        <Alert
          tone={alertInfo.tone}
          evidence={alertInfo.evidenceKey ? t(alertInfo.evidenceKey) : undefined}
        >
          {t(alertInfo.textKey, {
            date: weekdayLongDate(parseIsoDate(view.cycle.nextIso), lang),
            days: alertInfo.days,
          })}
        </Alert>
      )}
      <ConflictAlert
        violations={conflict.violations}
        onFix={() => conflict.clearConflict()}
        onSaveAnyway={() => button.current?.press({ override: true })}
      />
      <div className={conflict.problem === null ? 'collapse' : 'collapse open'}>
        <div>
          <Alert tone="warn">{conflict.problem}</Alert>
        </div>
      </div>
      <PrimaryButton ref={button} className="w" onPress={conflict.submit} onDone={closeLogSheet} resetMs={420}>
        {t('app.log.dose.save')}
      </PrimaryButton>
    </div>
  )
}

function MeasurePane({ enter }: { enter: boolean }) {
  const { t, lang } = useT()
  const queryClient = useQueryClient()
  const todayIso = useTodayIso()
  const { data: measuresView } = useQuery(measuresQuery)
  const latestMeasure = measuresView?.measurements?.[0]

  const [waistRaw, setWaistRaw] = useState('')
  const [neckRaw, setNeckRaw] = useState('')
  const button = useRef<PrimaryButtonHandle>(null)

  const liveNavy = useMemo(() => {
    const waist = parseLocaleNumber(waistRaw) ?? latestMeasure?.waist_cm ?? undefined
    const neck = parseLocaleNumber(neckRaw) ?? latestMeasure?.neck_cm ?? undefined
    const height = measuresView?.height_cm ?? 190
    const sex = measuresView?.sex ?? 'male'
    if (waist === undefined || neck === undefined || waist <= 0 || neck <= 0) {
      return measuresView?.body_fat_pct ?? null
    }
    return computeNavyFatPct(waist, neck, height, sex)
  }, [waistRaw, neckRaw, latestMeasure?.waist_cm, latestMeasure?.neck_cm, measuresView?.height_cm, measuresView?.sex, measuresView?.body_fat_pct])

  const invalidateMeasureQueries = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['weight'] }),
      queryClient.invalidateQueries({ queryKey: ['weight-measures'] }),
      queryClient.invalidateQueries({ queryKey: ['today'] }),
      queryClient.invalidateQueries({ queryKey: ['session'] }),
    ])

  const conflict = useConflictMutation({
    mutationFn: async ({ override }) => {
      const body = buildMeasureBody({
        date: todayIso,
        waistRaw,
        neckRaw,
        override,
      })
      const { data } = await api.POST('/api/v1/weight/measures', { body })
      if (data === undefined) throw new Error(t('app.log.weight.failed'))
      toast(t('app.log.measure.saved'), {
        undo: () =>
          void api
            .DELETE('/api/v1/weight/measures/{measurement_id}', { params: { path: { measurement_id: data.id } } })
            .then(() => invalidateMeasureQueries()),
      })
      await invalidateMeasureQueries()
      return data
    },
    onError: (err) => {
      toast(err.message || t('app.log.weight.failed'), { icon: 'warn' })
    },
  })

  const waistPlaceholder =
    latestMeasure?.waist_cm != null ? formatNumber(latestMeasure.waist_cm, lang) : t('app.unit.cm')
  const neckPlaceholder =
    latestMeasure?.neck_cm != null ? formatNumber(latestMeasure.neck_cm, lang) : t('app.unit.cm')

  return (
    <div className={enter ? 'sheet-pane enter' : 'sheet-pane'} data-pane="measure">
      <div className="two">
        <label className="field">
          <span className="flabel">{t('app.log.measure.waist')}</span>
          <input
            className="input"
            name="waist"
            inputMode="decimal"
            placeholder={waistPlaceholder}
            value={waistRaw}
            onChange={(e) => {
              setWaistRaw(e.target.value)
              conflict.clearConflict()
            }}
          />
        </label>
        <label className="field">
          <span className="flabel">{t('app.log.measure.neck')}</span>
          <input
            className="input"
            name="neck"
            inputMode="decimal"
            placeholder={neckPlaceholder}
            value={neckRaw}
            onChange={(e) => {
              setNeckRaw(e.target.value)
              conflict.clearConflict()
            }}
          />
        </label>
      </div>
      <p className="sub" style={{ margin: 0 }}>
        {t('app.log.measure.navy', { value: liveNavy !== null ? formatNumber(liveNavy, lang) : '—' })}
      </p>
      <ConflictAlert
        violations={conflict.violations}
        onFix={() => conflict.clearConflict()}
        onSaveAnyway={() => button.current?.press({ override: true })}
      />
      <div className={conflict.problem === null ? 'collapse' : 'collapse open'}>
        <div>
          <Alert tone="warn">{conflict.problem}</Alert>
        </div>
      </div>
      <PrimaryButton ref={button} className="w" onPress={conflict.submit} onDone={closeLogSheet} resetMs={420}>
        {t('app.log.measure.save')}
      </PrimaryButton>
    </div>
  )
}
