import { Alert } from '@/components/controls/Alert'
import { FigureBody, Section } from '@/components/controls/Section'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { clockLabel, syncedLabel } from '@/lib/dates'
import { formatCompact, formatInt, formatSigned, joinKnown } from '@/lib/format'
import { useToday } from '@/app/session'
import { agoText, co2ZoneOf, FRESH_S, humidityVerdict, stationAgeS, tempVerdict, trendOf } from './readings'
import type { EnvLive } from './types'

interface NowSectionProps {
  live: EnvLive
  /** When the answer arrived on this device, ms. */
  answeredAt: number
  nowMs: number
  /** The last read failed or is long past: what is on screen is old news. */
  vitalsAway: boolean
}

/** The air right now: CO₂ large in the colour of its zone, the trend, temperature and humidity,
 *  and a quiet line about the station itself. */
export function NowSection({ live, answeredAt, nowMs, vitalsAway }: NowSectionProps) {
  const { t, lang } = useT()
  const today = useToday()
  const { station, now: reading, thresholds } = live

  const ageS = stationAgeS(station, answeredAt, nowMs)
  const silent = station.status === 'stale' || station.status === 'offline'
  // A reading from a station that has stopped, or from a Vitals that cannot be reached, is shown
  // as what it was: no zone colour on a number nobody is measuring any more.
  const dim = station.status === 'offline' || vitalsAway
  const zone = dim || reading.co2_ppm === null ? 'none' : reading.co2_zone !== 'none' ? reading.co2_zone : co2ZoneOf(reading.co2_ppm, thresholds)

  const trend = dim ? null : trendOf(reading.co2_trend_ppm_per_h)
  const trendText =
    trend === null
      ? ''
      : joinKnown([
          t(`app.env.trend.${trend}`),
          trend !== 'flat' && reading.co2_trend_ppm_per_h !== null
            ? t('app.env.trend.rate', { rate: formatSigned(reading.co2_trend_ppm_per_h, lang, 0) })
            : null,
        ])

  const temp = reading.temperature_c
  const rh = reading.humidity_pct
  const tv = dim ? null : tempVerdict(temp, thresholds)
  const hv = dim ? null : humidityVerdict(rh, thresholds)

  const updated =
    ageS === null ? '' : ageS < FRESH_S ? t('app.env.updated_now') : t('app.env.updated', { ago: agoText(ageS, t) })
  const lastSeenAt = station.last_seen_at === null ? null : syncedLabel(station.last_seen_at, today, lang)

  return (
    <Section title={t('app.env.now')}>
      <div className={cx('env-now', dim && 'dim')} data-zone={zone}>
        <div className="fig-hero">
          <div className="big env-co2" data-fig="co2">
            <span className="num">{reading.co2_ppm === null ? '—' : formatInt(reading.co2_ppm, lang)}</span>
            <span className="unit">{t('app.env.ppm')}</span>
          </div>
          <div className="side">
            {dim ? (
              <span className="sub">{t('app.env.last_value')}</span>
            ) : (
              <span className="env-zone" data-zone={zone}>
                <i />
                {t(`app.env.zone.${zone}`)}
              </span>
            )}
            {trendText !== '' && (
              <span className="sub env-trend">
                {trend !== 'flat' && trend !== null && <Icon name={trend === 'up' ? 'up' : 'down'} />}
                {trendText}
              </span>
            )}
          </div>
        </div>

        <div className="figs">
          <div className="f">
            <FigureBody
              value={temp === null ? '—' : formatCompact(temp, lang, 1)}
              unit={temp === null ? '' : '°C'}
              label={t('app.env.temperature')}
              sub={tv === null ? undefined : t(`app.env.verdict.${tv}`)}
            />
          </div>
          <div className="f">
            <FigureBody
              value={rh === null ? '—' : formatCompact(rh, lang, 0)}
              unit={rh === null ? '' : '%'}
              label={t('app.env.humidity')}
              sub={hv === null ? undefined : t(`app.env.verdict.${hv}`)}
            />
          </div>
        </div>
      </div>

      <p className="env-station sub">
        <span className={cx('badge', badgeTone(station.status, vitalsAway))}>{t(`app.env.station.${station.status}`)}</span>
        {updated !== '' && <span className="num">{updated}</span>}
        {station.rssi !== null && <span className="num">{t('app.env.signal', { rssi: formatInt(station.rssi, lang) })}</span>}
      </p>

      {station.status === 'stale' && ageS !== null && (
        <Alert tone="warn" className="env-alert">
          {t('app.env.alert.stale', { ago: agoText(ageS, t) })}
        </Alert>
      )}
      {station.status === 'offline' && (
        <Alert tone="warn" className="env-alert">
          {lastSeenAt === null ? t('app.env.alert.offline_unknown') : t('app.env.alert.offline', { at: lastSeenAt })}
        </Alert>
      )}
      {vitalsAway && !silent && (
        <Alert tone="info" icon="wifiOff" className="env-alert">
          {t('app.env.alert.vitals_away', { at: clockLabel(new Date(answeredAt)) })}
        </Alert>
      )}
    </Section>
  )
}

function badgeTone(status: EnvLive['station']['status'], vitalsAway: boolean): string {
  if (vitalsAway) return 'plain'
  if (status === 'online') return 'good'
  if (status === 'stale') return 'warn'
  return status === 'offline' ? 'bad' : 'plain'
}
