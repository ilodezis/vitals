import { useLayoutEffect, useRef, useState, type PointerEvent } from 'react'
import { Alert } from '@/components/controls/Alert'
import { OptionGroup } from '@/components/controls/Choices'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { Segmented } from '@/components/controls/Segmented'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useLayout } from '@/components/shell/layout'
import { sheetCloses } from '@/components/shell/stageMotion'
import { useGlp1View } from '@/features/glp1/useGlp1View'
import { WeightForm } from '@/features/weight/WeightForm'
import { useT } from '@/i18n/useT'
import { EASE_SHEET, animate, settle } from '@/lib/motion'
import { parseIsoDate, weekdayLongDate } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { closeLogSheet, setLogTab, useLogSheet, type LogTab } from './logSheetStore'

const TABS: readonly LogTab[] = ['weight', 'meal', 'dose', 'measure']

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

/** Panes that only say "saved" — the meal, the dose and the measurement are wired in their own runs. */
function useFakeSave(messageKey: string, params?: Record<string, string | number>) {
  const { t } = useT()
  return async (): Promise<boolean> => {
    await new Promise((resolve) => setTimeout(resolve, 520))
    toast(t(messageKey, params))
    return true
  }
}

function MealPane({ enter }: { enter: boolean }) {
  const { t } = useT()
  const [kind, setKind] = useState('lunch')
  const save = useFakeSave('app.log.meal.saved')
  return (
    <div className={enter ? 'sheet-pane enter' : 'sheet-pane'} data-pane="meal">
      <label className="field">
        <span className="flabel">{t('app.log.meal.what')}</span>
        <input className="input" name="meal" placeholder={t('app.log.meal.placeholder')} />
      </label>
      <div className="two">
        <label className="field">
          <span className="flabel">{t('app.log.meal.kcal')}</span>
          <input className="input" name="kcal" inputMode="numeric" placeholder={t('app.unit.kcal')} />
        </label>
        <label className="field">
          <span className="flabel">{t('app.log.meal.protein')}</span>
          <input className="input" name="protein" inputMode="numeric" placeholder={t('app.unit.g')} />
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
      <PrimaryButton className="w" onPress={save} onDone={closeLogSheet} resetMs={420}>
        {t('app.log.meal.save')}
      </PrimaryButton>
    </div>
  )
}

const SITES = ['abdomen_left', 'abdomen_right', 'shoulder_left', 'thigh_left', 'thigh_right', 'shoulder_right'] as const

function DosePane({ enter }: { enter: boolean }) {
  const { t, lang } = useT()
  const { cycle } = useGlp1View()
  const [drug, setDrug] = useState('current')
  const [site, setSite] = useState<string>('shoulder_left')
  const save = useFakeSave('app.log.dose.saved', { site: t(`app.site.${site}`) })
  return (
    <div className={enter ? 'sheet-pane enter' : 'sheet-pane'} data-pane="dose">
      <div className="field">
        <span className="flabel">{t('app.log.dose.drug')}</span>
        <OptionGroup
          value={drug}
          onChange={setDrug}
          options={[
            { id: 'current', label: t('app.log.dose.current') },
            { id: 'other', label: t('app.log.dose.other') },
          ]}
        />
      </div>
      <div className="field">
        <span className="flabel">{t('app.log.dose.site')}</span>
        <OptionGroup
          value={site}
          onChange={setSite}
          options={SITES.map((id) => ({ id, label: t(`app.site.${id}`), hint: id === 'shoulder_left' ? t('app.glp1.least_used') : undefined }))}
        />
      </div>
      <Alert tone="warn" evidence={t('app.log.dose.unscheduled')}>
        {t('app.log.dose.early', { date: weekdayLongDate(parseIsoDate(cycle.nextIso), lang), days: cycle.daysToNext })}
      </Alert>
      <PrimaryButton className="w" onPress={save} onDone={closeLogSheet} resetMs={420}>
        {t('app.log.dose.save')}
      </PrimaryButton>
    </div>
  )
}

function MeasurePane({ enter }: { enter: boolean }) {
  const { t, lang } = useT()
  const save = useFakeSave('app.log.measure.saved')
  return (
    <div className={enter ? 'sheet-pane enter' : 'sheet-pane'} data-pane="measure">
      <div className="two">
        <label className="field">
          <span className="flabel">{t('app.log.measure.waist')}</span>
          <input className="input" name="waist" inputMode="decimal" placeholder={t('app.unit.cm')} defaultValue={formatNumber(84.5, lang)} />
        </label>
        <label className="field">
          <span className="flabel">{t('app.log.measure.neck')}</span>
          <input className="input" name="neck" inputMode="decimal" placeholder={t('app.unit.cm')} defaultValue={formatNumber(39, lang)} />
        </label>
      </div>
      <p className="sub" style={{ margin: 0 }}>
        {t('app.log.measure.navy', { value: formatNumber(17.8, lang) })}
      </p>
      <PrimaryButton className="w" onPress={save} onDone={closeLogSheet} resetMs={420}>
        {t('app.log.measure.save')}
      </PrimaryButton>
    </div>
  )
}
