import { useEffect, useState } from 'react'
import { cx } from '@/lib/cx'

const DIGITS = '0123456789'.split('')
const isDigit = (ch: string): boolean => ch >= '0' && ch <= '9'
/** "86,1" → "00,0": what a value looks like with its digits taken out. */
const shapeOf = (value: string): string => value.replace(/\d/g, '0')

interface OdometerProps {
  /** The figure as text: "86,1", "2 150". Digits roll; everything else is fixed. */
  value: string
  /** Held at zero and invisible — the figure arrives when this turns false. */
  hidden?: boolean
  /** Milliseconds between one digit starting to roll and the next. */
  stagger?: number
}

/** A figure whose digits are reels. A new value of the same shape rolls the reels; a value
 *  with more or fewer digits (9,9 → 10,0) is rebuilt at zero and rolls in. */
export function Odometer({ value, hidden = false, stagger = 0 }: OdometerProps) {
  const shape = shapeOf(value)
  const [settled, setSettled] = useState(shape)
  const rebuilding = settled !== shape

  useEffect(() => {
    if (!rebuilding) return
    let frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => setSettled(shape))
    })
    return () => cancelAnimationFrame(frame)
  }, [rebuilding, shape])

  const atZero = hidden || rebuilding
  let reel = 0
  return (
    <span key={shape} className={cx('odo', hidden && 'pre')} data-odo={value}>
      {[...value].map((ch, i) => {
        if (!isDigit(ch)) {
          return (
            <span key={i} className="odo-c">
              {ch}
            </span>
          )
        }
        const delay = stagger > 0 && !atZero ? `${reel++ * stagger}ms` : undefined
        return (
          <span key={i} className="odo-d" data-digit={ch}>
            <span
              className="odo-s"
              style={{ transform: `translateY(${atZero ? 0 : -Number(ch) * 1.1}em)`, transitionDelay: delay }}
            >
              {DIGITS.map((d) => (
                <span key={d}>{d}</span>
              ))}
            </span>
          </span>
        )
      })}
    </span>
  )
}
