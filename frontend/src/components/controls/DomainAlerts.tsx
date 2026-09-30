import { useQuery } from '@tanstack/react-query'
import { useT } from '@/i18n/useT'
import { Alert } from './Alert'
import { alertsQuery, toneOf, useHideAlerts } from './alerts'
import { TextButton } from './Marks'

interface DomainAlertsProps {
  /** Whose alerts: a `Domain` value of the server ("weight", "garmin"). */
  domain: string
  /** The query key of the screen that shows them, when it is not the domain's name. */
  scope?: string
}

/** What the system has to say about one domain, at the top of that domain's screen: each
 *  alert with a way to hide it, and "Hide all" once there is more than one. Nothing is drawn
 *  while there is nothing to say — or while it is not known yet. */
export function DomainAlerts({ domain, scope = domain }: DomainAlertsProps) {
  const { t } = useT()
  const alerts = useQuery(alertsQuery(scope, domain)).data
  const { hide, hideAll } = useHideAlerts(scope)
  if (alerts === undefined || alerts.length === 0) return null

  return (
    <section className="sec alerts-sec">
      {alerts.length > 1 ? (
        <div className="alerts-h">
          <TextButton onClick={() => hideAll(domain)}>{t('alert.hide_all')}</TextButton>
        </div>
      ) : null}
      <div className="alerts">
        {alerts.map((a) => (
          <Alert
            key={a.id}
            tone={toneOf(a.severity)}
            evidence={a.overridden ? t('alert.overridden') : undefined}
            onDismiss={() => hide(a.id)}
            dismissLabel={t('alert.hide')}
          >
            {a.message}
          </Alert>
        ))}
      </div>
    </section>
  )
}
