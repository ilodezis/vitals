import type { ReactNode } from 'react'
import type { Violation } from '@/api/client'
import { Alert } from '@/components/controls/Alert'
import { TextButton } from '@/components/controls/Marks'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'

export interface ConflictAlertProps {
  violations: readonly Violation[]
  onFix: () => void
  onSaveAnyway: () => void
  evidence?: ReactNode
  className?: string
}

export function ConflictAlert({
  violations,
  onFix,
  onSaveAnyway,
  evidence,
  className,
}: ConflictAlertProps) {
  const { t } = useT()

  return (
    // Folded away it must not take the keyboard either: its buttons would be reachable unseen.
    <div className={violations.length > 0 ? 'collapse open' : 'collapse'} inert={violations.length === 0}>
      <div>
        <Alert
          tone="block"
          className={cx('alert-conflict', className)}
          evidence={evidence ?? t('app.log.weight.conflict_rule')}
          actions={
            <>
              <TextButton onClick={onFix}>{t('app.fix')}</TextButton>
              <TextButton danger onClick={onSaveAnyway}>
                {t('app.save_anyway')}
              </TextButton>
            </>
          }
        >
          {violations.length <= 1
            ? violations[0]?.message
            : violations.map((v, i) => <div key={v.rule_id || i}>{v.message}</div>)}
        </Alert>
      </div>
    </div>
  )
}
