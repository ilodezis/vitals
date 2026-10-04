import { formatCompact, type Lang } from '@/lib/format'
import type { EnvRange } from './types'

/** "Temperature   19,8–21,4 °C": a label and the span a reading moved across. Nothing when the
 *  station took no reading to span. */
export function RangeRow({ label, range, unit, digits, lang }: { label: string; range: EnvRange; unit: string; digits: number; lang: Lang }) {
  if (range.min == null || range.max == null) return null
  return (
    <div className="env-range">
      <span>{label}</span>
      <b className="num">
        {formatCompact(range.min, lang, digits)}–{formatCompact(range.max, lang, digits)} {unit}
      </b>
    </div>
  )
}
