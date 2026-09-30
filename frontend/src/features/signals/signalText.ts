import { clockTime, formatCompact, type Lang } from '@/lib/format'

/** The value of a logged signal as written by the person: "3", "0,25", "7,5 ч" — no padded ",0". */
export function signalValue(value: number, unit: string | null | undefined, lang: Lang): string {
  const number = formatCompact(value, lang, 2)
  return unit ? `${number} ${unit}` : number
}

/** The time a signal was logged, to the minute. */
export const signalTime = (time: string): string => clockTime(time)
