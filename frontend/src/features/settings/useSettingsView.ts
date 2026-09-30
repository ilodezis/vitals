import { queryOptions, useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { components } from '@/api/schema'

export type SettingsView = components['schemas']['SettingsView']

export const defaultSettings: SettingsView = {
  username: 'admin',
  profile: {
    height_cm: '190',
    sex: 'male',
    user_age: '18',
    timezone: 'Europe/Chisinau',
    user_program: '',
    user_goals: '',
  },
  nutrition_goals: {
    nutrition_protein_target_g: '150',
    nutrition_calories_min: '1300',
    nutrition_calories_max: '1700',
  },
  language: {
    language: 'ru',
  },
  modules: {
    enabled_modules: {},
  },
  ai: {
    openrouter_api_key_set: false,
    openrouter_base_url: 'https://openrouter.ai/api/v1',
    llm_model_digest: 'anthropic/claude-sonnet-4.6',
    llm_model_parser: 'google/gemini-2.5-flash',
    llm_model_brief: '',
  },
  hevy: {
    hevy_api_key_set: false,
  },
  garmin: {
    garmin_email: '',
    garmin_password_set: false,
    garmin_credentials_configured: false,
    garmin_weight_export_enabled: false,
    garmin_weight_status: null,
    breaker: null,
  },
  mcp: {
    mcp_client_id: 'vitals-claude-connector',
    mcp_client_secret_set: false,
  },
  security: {
    twofa_enabled: false,
    twofa_pending: false,
  },
  proactive: {
    brief_time: '11:00',
    evening_time: '21:30',
    quiet_start: '23:00',
    quiet_end: '08:00',
    daily_budget: 4,
    garmin_sync_hours: 4,
    garmin_weight_export_minutes: 30,
    garmin_weight_max_age_days: 2,
    pulse_seconds: 900,
    pulse_start_hour: 8,
    pulse_end_hour: 22,
    nudges: { n: true, d: true },
    week_template: {},
  },
}

export const settingsQuery = queryOptions({
  queryKey: ['settings'],
  queryFn: async (): Promise<SettingsView> => {
    const { data, error } = await api.GET('/api/v1/settings')
    if (error || !data) throw error ?? new Error('Failed to load settings')
    return data
  },
  staleTime: 30_000,
})

export function useSettingsView(): {
  data: SettingsView
  isLoading: boolean
  isError: boolean
  refetch: () => Promise<unknown>
} {
  const query = useQuery(settingsQuery)
  return {
    data: query.data ?? defaultSettings,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
  }
}
