export interface SignalItem {
  id: number
  date: string
  time?: string | null
  kind: string
  key: string
  rawKey: string
  value?: number | null
  unit?: string | null
  note?: string | null
  misparse: boolean
  batchId?: string | null
}

export interface KeyFrequencyItem {
  key: string
  count: number
  n: number
  variants: string[]
  alias: string[]
  examples: string[]
  ex: string[]
}

export interface SignalsView {
  signals: SignalItem[]
  frequency: listKeyFrequencyItem[]
  kinds: string[]
  misparseCount: number
  totalCount: number
  keysCount: number
}

type listKeyFrequencyItem = KeyFrequencyItem
