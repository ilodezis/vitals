import type { ReactNode } from 'react'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import type { SettingsView } from './useSettingsView'

/** Whether a section is on: a core one always is, the rest follow their switch. */
export function moduleOn(settings: SettingsView, key: string): boolean {
  const info = settings.modules.registry?.find((m) => m.key === key)
  if (info === undefined) return false
  return info.core || settings.modules.enabled_modules?.[key] === true
}

/** A connection's state in its heading, so the tab reads at a glance. */
export function ConnectedBadge({ ok }: { ok: boolean }) {
  const { t } = useT()
  return <span className={cx('badge', ok && 'good')}>{ok ? t('settings.status.connected') : t('settings.status.not_set')}</span>
}

/** The save of one block. It only lights up once something in the block has changed, so the
 *  screen shows where an edit is still unsaved. */
export function SaveRow({ dirty, onSave, children }: { dirty: boolean; onSave: () => Promise<boolean>; children: ReactNode }) {
  return (
    <div className="set-save">
      <PrimaryButton disabled={!dirty} onPress={onSave}>
        {children}
      </PrimaryButton>
    </div>
  )
}
