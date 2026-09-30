import { queryOptions, useQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import type { components } from '@/api/schema'
import { useT } from '@/i18n/useT'
import { formatInt, formatNumber } from '@/lib/format'

export interface MoreStatus {
  text: string
  tone?: 'good' | 'warn' | 'bad'
}

export interface MoreView {
  /** A short status per section, keyed by module key. */
  status: Record<string, MoreStatus>
  system: Record<'share' | 'settings', MoreStatus>
}

type RawMoreView = components['schemas']['MoreView']

export const moreQuery = queryOptions({
  queryKey: ['more'],
  queryFn: async (): Promise<RawMoreView> => ok(api.GET('/api/v1/more')),
  staleTime: 60_000,
})

/** The More screen's live statuses from `/api/v1/more`. Until they are read — or when the read
 *  fails — a section simply has no status line; nothing is made up. */
export function useMoreView(): MoreView {
  const { t, lang, plural } = useT()
  const { data } = useQuery(moreQuery)
  const stats = data?.stats ?? {}
  const status: Record<string, MoreStatus> = {}

  if (stats.weight?.weight_kg != null) {
    status.weight = {
      text: `${formatNumber(Number(stats.weight.weight_kg), lang)} ${t('app.unit.kg')}`,
      tone: 'good',
    }
  }
  if (stats.garmin?.sleep_score != null) {
    const score = Number(stats.garmin.sleep_score)
    status.garmin = {
      text: t('app.more.sleep', { score }),
      tone: score >= 75 ? 'good' : undefined,
    }
  }
  if (stats.hevy?.days_since != null) {
    const d = Number(stats.hevy.days_since)
    status.hevy = {
      text:
        d === 0
          ? t('app.today_word_lower')
          : d === 1
            ? t('app.yesterday_word_lower')
            : t('app.rail.days_ago', { n: d }),
    }
  }
  if (stats.nutrition?.calories != null) {
    status.nutrition = {
      text: t('app.unit.kcal_value', { value: formatInt(Number(stats.nutrition.calories), lang) }),
    }
  }
  if (stats.glp1?.days_to_next != null) {
    const d = Number(stats.glp1.days_to_next)
    if (d < 0) {
      const over = Math.abs(d)
      status.glp1 = {
        text: plural(
          over,
          t('app.glp1.overdue.one', { n: over }),
          t('app.glp1.overdue.few', { n: over }),
          t('app.glp1.overdue.many', { n: over }),
        ),
        tone: 'bad',
      }
    } else if (d === 0) {
      status.glp1 = { text: t('app.glp1.due_today'), tone: 'warn' }
    } else {
      status.glp1 = {
        text: plural(
          d,
          t('app.glp1.in_days.one', { n: d }),
          t('app.glp1.in_days.few', { n: d }),
          t('app.glp1.in_days.many', { n: d }),
        ),
      }
    }
  }
  if (stats.hrt?.week != null) {
    status.hrt = {
      text:
        stats.hrt.weeks != null
          ? t('app.hrt.week_of', { week: Number(stats.hrt.week), total: Number(stats.hrt.weeks) })
          : t('app.more.week', { week: Number(stats.hrt.week) }),
    }
  }
  if (stats.labs?.out_of_range != null) {
    const n = Number(stats.labs.out_of_range)
    status.labs =
      n > 0
        ? { text: t('app.labs.out_of_range_short', { n }), tone: 'bad' }
        : { text: t('app.more.in_norm'), tone: 'good' }
  }
  if (stats.supplements?.active != null && Number(stats.supplements.active) > 0) {
    const n = Number(stats.supplements.active)
    status.supplements = {
      text: plural(
        n,
        t('app.more.active.one', { n }),
        t('app.more.active.few', { n }),
        t('app.more.active.many', { n }),
      ),
    }
  }
  if (stats.interactions?.firing != null && Number(stats.interactions.firing) > 0) {
    const n = Number(stats.interactions.firing)
    status.interactions = {
      text: plural(
        n,
        t('app.more.firing.one', { n }),
        t('app.more.firing.few', { n }),
        t('app.more.firing.many', { n }),
      ),
      tone: 'bad',
    }
  }
  if (stats.charts?.count != null && Number(stats.charts.count) > 0) {
    const n = Number(stats.charts.count)
    status.charts = {
      text: plural(
        n,
        t('app.charts.count.one', { n }),
        t('app.charts.count.few', { n }),
        t('app.charts.count.many', { n }),
      ),
    }
  }

  const settingsStat = stats.settings
  return {
    status,
    system: {
      share: { text: t('app.more.share_sub') },
      settings: {
        text:
          settingsStat?.enabled != null && settingsStat?.total != null
            ? t('app.more.modules', { on: Number(settingsStat.enabled), total: Number(settingsStat.total) })
            : '',
      },
    },
  }
}
