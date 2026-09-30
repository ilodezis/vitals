import type { Lang } from '@/lib/format'
import { formatCompact } from '@/lib/format'
import type { TFn } from '@/lib/units'

type TOrFn = (key: string, fallback: string) => string

/** A drug by its name in the user's language; one the dictionary does not know keeps its own. */
export const drugName = (drug: string, tOr: TOrFn): string => tOr(`enum.drug.${drug.toLowerCase()}`, drug)

/** A dose as it is written on the pen: "0,25 mg", never rounded to a tenth. */
export const doseText = (doseMg: number, lang: Lang, t: TFn): string => `${formatCompact(doseMg, lang, 3)} ${t('app.unit.mg')}`

/** "Semaglutide 0,25 mg". */
export const doseLabel = (drug: string, doseMg: number, lang: Lang, t: TFn, tOr: TOrFn): string =>
  `${drugName(drug, tOr)} ${doseText(doseMg, lang, t)}`
