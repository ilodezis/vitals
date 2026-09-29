import { useEffect, useImperativeHandle, useRef, useState, type ReactNode, type Ref } from 'react'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { wait } from '@/lib/motion'

type Phase = 'idle' | 'loading' | 'done'

/** Press it from outside — the "Save anyway" of a conflict runs the same button. */
export interface PrimaryButtonHandle {
  press: (options?: { override?: boolean }) => void
}

interface PrimaryButtonProps {
  children: ReactNode
  /** Do the work. Resolve `true` when it was saved, `false` when it was held back (a
   *  conflict is on screen and the button goes straight back to its label). */
  onPress: (context: { override: boolean }) => Promise<boolean>
  /** Runs when "Saved" has been shown — close the sheet, say so in a toast. */
  onDone?: () => void
  /** How long "Saved" stays before the label returns. */
  resetMs?: number
  className?: string
  disabled?: boolean
  ref?: Ref<PrimaryButtonHandle>
}

/** The one main button of a screen: idle → spinner → "Saved" → idle. Its width is
 *  held while it changes so nothing around it moves. */
export function PrimaryButton({ children, onPress, onDone, resetMs = 900, className, disabled = false, ref }: PrimaryButtonProps) {
  const { t } = useT()
  const [phase, setPhase] = useState<Phase>('idle')
  const [width, setWidth] = useState<number | undefined>(undefined)
  const button = useRef<HTMLButtonElement>(null)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const run = async (override: boolean) => {
    if (phase !== 'idle' || disabled) return
    setWidth(button.current?.offsetWidth)
    setPhase('loading')
    const saved = await onPress({ override })
    if (!alive.current) return
    if (!saved) {
      setPhase('idle')
      setWidth(undefined)
      return
    }
    setPhase('done')
    await wait(520)
    onDone?.()
    await wait(resetMs)
    if (!alive.current) return
    setPhase('idle')
    setWidth(undefined)
  }

  useImperativeHandle(ref, () => ({ press: (options) => void run(options?.override ?? false) }))

  return (
    <button
      ref={button}
      type="button"
      className={cx('btn', className)}
      data-state={phase === 'done' ? 'done' : undefined}
      style={width === undefined ? undefined : { width }}
      disabled={disabled}
      aria-busy={phase === 'loading'}
      onClick={() => void run(false)}
    >
      {phase === 'loading' ? (
        <span className="spinner" />
      ) : phase === 'done' ? (
        <>
          <Icon name="check" />
          {t('app.recorded')}
        </>
      ) : (
        children
      )}
    </button>
  )
}
