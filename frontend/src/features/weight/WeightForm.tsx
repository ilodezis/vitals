import { useRef, useState } from 'react'
import { Alert } from '@/components/controls/Alert'
import { ConflictAlert } from '@/components/controls/ConflictAlert'
import { Badge } from '@/components/controls/Marks'
import { PrimaryButton, type PrimaryButtonHandle } from '@/components/controls/PrimaryButton'
import { Stepper } from '@/components/controls/Stepper'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { formatNumber } from '@/lib/format'
import { useClock } from '@/lib/useClock'
import { useConflictMutation } from '@/lib/useConflictMutation'
import { useLastWeighed } from './useLastWeighed'
import { useLatestWeight, useSaveWeight } from './weightLog'

/** Where the stepper starts when nothing has ever been weighed. */
const FIRST_WEIGHT_KG = 80

interface WeightFormProps {
  /** The caption under the stepper and the "today · manual" line: the sheet shows them, the
   *  panel on Today's desktop does not. */
  detailed?: boolean
  onDone?: () => void
  resetMs?: number
}

/** Weight entry: a stepper, the conflict ladder and the one main button. A jump the conflict
 *  engine holds back shows its rule with "Fix it" and "Save anyway"; the second runs the same
 *  button again with the override on. */
export function WeightForm({ detailed = false, onDone, resetMs }: WeightFormProps) {
  const { t, lang } = useT()
  const latest = useLatestWeight()
  const lastWeighed = useLastWeighed()
  const saveWeight = useSaveWeight()
  const clock = useClock()
  // What was typed; until then the stepper stands on the latest reading, whenever it arrives.
  const [typed, setTyped] = useState<number | null>(null)
  const kg = typed ?? latest.kg ?? FIRST_WEIGHT_KG
  const button = useRef<PrimaryButtonHandle>(null)

  const conflict = useConflictMutation({
    mutationFn: async ({ override }) => {
      const { undo } = await saveWeight(kg, { override })
      setTyped(kg)
      toast(t(override ? 'app.log.weight.saved_override' : 'app.log.weight.saved', { value: formatNumber(kg, lang) }), {
        undo: undo === undefined ? undefined : () => void undo().catch(() => toast(t('app.log.weight.failed'), { icon: 'warn' })),
      })
    },
    fallbackErrorMessage: t('app.log.weight.failed'),
  })

  const change = (v: number | null) => {
    setTyped(v)
    conflict.clearConflict()
  }

  return (
    <>
      <Stepper value={kg} onChange={change} unit={t('app.unit.kg')} />
      {detailed && (
        <>
          <div className="stepper-cap">
            <span>{t('app.log.weight.hint', { step: formatNumber(0.1, lang) })}</span>
            <span>{lastWeighed}</span>
          </div>
          <div className="meta-line">
            <Badge tone="plain">
              <Icon name="cal" />
              {t('app.log.today_at', { time: clock })}
            </Badge>
            <Badge tone="good">{t('app.log.weight.manual_priority')}</Badge>
          </div>
        </>
      )}
      <ConflictAlert
        violations={conflict.violations}
        onFix={() => change(null)}
        onSaveAnyway={() => button.current?.press({ override: true })}
        evidence={t('app.log.weight.conflict_rule')}
      />
      <div className={conflict.problem === null ? 'collapse' : 'collapse open'}>
        <div>
          <Alert tone="warn">{conflict.problem}</Alert>
        </div>
      </div>
      <PrimaryButton ref={button} className="w" onPress={conflict.submit} onDone={onDone} resetMs={resetMs}>
        {t('app.log.weight.save')}
      </PrimaryButton>
    </>
  )
}
