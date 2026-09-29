export interface SharedReportItem {
  id: number
  token: string
  title: string
  preset?: string | null
  domains: string[]
  periodStart: string
  periodEnd: string
  expiresAt: string
  createdAt?: string | null
  revokedAt?: string | null
  openedCount: number
  lastOpenedAt?: string | null
  state: 'live' | 'revoked' | 'expired' | string
  url: string
}

export interface SharePresetSpec {
  domains: string[]
  labsFlaggedOnly: boolean
}

export interface ShareView {
  reports: SharedReportItem[]
  availableDomains: string[]
  presets: Record<string, SharePresetSpec>
  periodChoices: number[]
  expiryChoices: number[]
  defaultExpiry: number
  defaultStart: string
  defaultEnd: string
  today: string
}

export interface CreateShareRequest {
  title: string
  preset?: string | null
  domains: string[]
  period: string
  periodStart?: string | null
  periodEnd?: string | null
  expiresDays: number
  labsFlaggedOnly: boolean
  note?: string | null
}

export interface CreatedShareResponse {
  id: number
  token: string
  password: string
  url: string
  expiresAt: string
}
