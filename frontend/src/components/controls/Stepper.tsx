import { useEffect, useRef, useState } from 'react'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { formatNumber } from '@/lib/format'
import { Odometer } from './Odometer'
import { clampStep, HOLD_START, repeatDelay, STEP, WEIGHT_MAX, WEIGHT_MIN } from './stepperMath'

interface StepperProps {
  value: number
  onChange: (value: number) => void
  unit: string
  min?: number
  max?: number
}

/** A number between two round keys. Hold a key to run; tap the number to type it. */
export function Stepper({ value, onChange, unit, min = WEIGHT_MIN, max = WEIGHT_MAX }: StepperProps) {
  const { t, lang } = useT()
  const latest = useRef(value)
  const timer = useRef<number | undefined>(undefined)
  const [held, setHeld] = useState<-1 | 1 | null>(null)
  const [typing, setTyping] = useState<string | null>(null)

  useEffect(() => {
    latest.current = value
  }, [value])
  useEffect(() => () => window.clearTimeout(timer.current), [])

  const tick = (dir: -1 | 1) => {
    const next = clampStep(latest.current + dir * STEP, min, max)
    latest.current = next
    onChange(next)
  }

  const start = (dir: -1 | 1) => {
    tick(dir)
    setHeld(dir)
    let repeats = 0
    const run = () => {
      tick(dir)
      repeats += 1
      timer.current = window.setTimeout(run, repeatDelay(repeats))
    }
    timer.current = window.setTimeout(run, HOLD_START)
  }
  const stop = () => {
    window.clearTimeout(timer.current)
    setHeld(null)
  }

  const commit = (text: string) => {
    setTyping(null)
    const parsed = Number.parseFloat(text.replace(',', '.').replace('−', '-'))
    if (!Number.isNaN(parsed)) {
      const next = clampStep(parsed, min, max)
      latest.current = next
      onChange(next)
    }
  }

  const key = (dir: -1 | 1, label: string) => (
    <button
      type="button"
      className={held === dir ? 'k held' : 'k'}
      aria-label={label}
      onPointerDown={(e) => {
        e.preventDefault()
        start(dir)
      }}
      onPointerUp={stop}
      onPointerCancel={stop}
      onPointerLeave={stop}
      // A pointer press is handled above. A click without one (Enter, Space, a screen reader's
      // activation) has detail 0 and steps once.
      onClick={(e) => {
        if (e.detail === 0) tick(dir)
      }}
    >
      <Icon name={dir < 0 ? 'minus' : 'plus'} />
    </button>
  )

  return (
    <div className="stepper">
      {key(-1, t('app.stepper.minus', { value: formatNumber(STEP, lang), unit }))}
      <div
        className="val"
        role="spinbutton"
        tabIndex={0}
        aria-valuenow={value}
        aria-valuemin={min}
        aria-valuemax={max}
        onClick={() => setTyping(formatNumber(value, lang))}
        onKeyDown={(e) => {
          if (e.key === 'ArrowUp') tick(1)
          else if (e.key === 'ArrowDown') tick(-1)
        }}
      >
        <Odometer value={formatNumber(value, lang)} />
        <span className="u">{unit}</span>
        {typing !== null && (
          <input
            autoFocus
            inputMode="decimal"
            defaultValue={typing}
            aria-label={unit}
            onFocus={(e) => e.currentTarget.select()}
            onBlur={(e) => commit(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') e.currentTarget.blur()
              if (e.key === 'Escape') {
                e.currentTarget.value = ''
                e.currentTarget.blur()
              }
            }}
          />
        )}
      </div>
      {key(1, t('app.stepper.plus', { value: formatNumber(STEP, lang), unit }))}
    </div>
  )
}
