import { useRef, useState } from 'react'
import { ConflictError, type Violation } from '@/api/client'
import { Alert } from '@/components/controls/Alert'
import { Badge, TextButton } from '@/components/controls/Marks'
import { PrimaryButton, type PrimaryButtonHandle } from '@/components/controls/PrimaryButton'
import { Stepper } from '@/components/controls/Stepper'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { FIXTURE_NOW } from '@/fixtures/series'
import { useT } from '@/i18n/useT'
import { formatNumber, formatSigned } from '@/lib/format'
import { currentWeight, logWeight, useLoggedWeight } from './weightLog'

interface WeightFormProps {
  /** The caption under the stepper and the "today · manual" line: the sheet shows them, the
   *  panel on Today's desktop does not. */
  detailed?: boolean
  onDone?: () => void
  resetMs?: number
}

/** Weight entry: a stepper, the conflict ladder and the one main button. A jump the conflict
 *  engine holds back (1.5 kg or more from the morning reading) shows a block with "Fix it" and
 *  "Save anyway"; the second runs the same button again with the override on. */
export function WeightForm({ detailed = false, onDone, resetMs }: WeightFormProps) {
  const { t, lang } = useT()
  const logged = useLoggedWeight()
  const [kg, setKg] = useState(logged.kg)
  const [violations, setViolations] = useState<Violation[]>([])
  const button = useRef<PrimaryButtonHandle>(null)

  const change = (v: number) => {
    setKg(v)
    setViolations([])
  }

  const save = async ({ override }: { override: boolean }): Promise<boolean> => {
    try {
      const { undo } = await logWeight(kg, {
        override,
        at: FIXTURE_NOW,
        conflictMessage: (delta) => t('app.log.weight.conflict', { delta: formatSigned(delta, lang) }),
      })
      setViolations([])
      toast(t(override ? 'app.log.weight.saved_override' : 'app.log.weight.saved', { value: formatNumber(kg, lang) }), { undo })
      return true
    } catch (error) {
      if (error instanceof ConflictError) {
        setViolations(error.violations)
        return false
      }
      throw error
    }
  }

  return (
    <>
      <Stepper value={kg} onChange={change} unit={t('app.unit.kg')} />
      {detailed && (
        <>
          <div className="stepper-cap">
            <span>{t('app.log.weight.hint', { step: formatNumber(0.1, lang) })}</span>
            <span>{t('app.log.weight.morning', { value: formatNumber(logged.kg, lang) })}</span>
          </div>
          <div className="meta-line">
            <Badge tone="plain">
              <Icon name="cal" />
              {t('app.log.today_at', { time: FIXTURE_NOW })}
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
                <TextButton onClick={() => change(currentWeight())}>{t('app.fix')}</TextButton>
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
      <PrimaryButton ref={button} className="w" onPress={save} onDone={onDone} resetMs={resetMs}>
        {t('app.log.weight.save')}
      </PrimaryButton>
    </>
  )
}
