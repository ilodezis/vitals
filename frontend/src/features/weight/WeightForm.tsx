import { useRef, useState } from 'react'
import { ConflictError, InvalidError, type Violation } from '@/api/client'
import { Alert } from '@/components/controls/Alert'
import { Badge, TextButton } from '@/components/controls/Marks'
import { PrimaryButton, type PrimaryButtonHandle } from '@/components/controls/PrimaryButton'
import { Stepper } from '@/components/controls/Stepper'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { formatNumber } from '@/lib/format'
import { useClock } from '@/lib/useClock'
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
  const [violations, setViolations] = useState<Violation[]>([])
  const [problem, setProblem] = useState<string | null>(null)
  const button = useRef<PrimaryButtonHandle>(null)

  const change = (v: number | null) => {
    setTyped(v)
    setViolations([])
    setProblem(null)
  }

  const save = async ({ override }: { override: boolean }): Promise<boolean> => {
    try {
      const { undo } = await saveWeight(kg, { override })
      change(kg)
      toast(t(override ? 'app.log.weight.saved_override' : 'app.log.weight.saved', { value: formatNumber(kg, lang) }), {
        undo: undo === undefined ? undefined : () => void undo().catch(() => toast(t('app.log.weight.failed'), { icon: 'warn' })),
      })
      return true
    } catch (error) {
      if (error instanceof ConflictError) {
        setViolations(error.violations)
        setProblem(null)
      } else {
        // The service's own words when it refused the number; ours when the network did.
        setViolations([])
        setProblem(error instanceof InvalidError ? error.message : t('app.log.weight.failed'))
      }
      return false
    }
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
      <div className={violations.length > 0 ? 'collapse open' : 'collapse'}>
        <div>
          <Alert
            tone="block"
            className="alert-conflict"
            evidence={t('app.log.weight.conflict_rule')}
            actions={
              <>
                <TextButton onClick={() => change(null)}>{t('app.fix')}</TextButton>
                <TextButton danger onClick={() => button.current?.press({ override: true })}>
                  {t('app.save_anyway')}
                </TextButton>
              </>
            }
          >
            {violations[0]?.message}
          </Alert>
        </div>
      </div>
      <div className={problem === null ? 'collapse' : 'collapse open'}>
        <div>
          <Alert tone="warn">{problem}</Alert>
        </div>
      </div>
      <PrimaryButton ref={button} className="w" onPress={save} onDone={onDone} resetMs={resetMs}>
        {t('app.log.weight.save')}
      </PrimaryButton>
    </>
  )
}
