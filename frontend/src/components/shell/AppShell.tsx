import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useRouter } from '@tanstack/react-router'
import { ToastHost } from '@/components/controls/ToastHost'
import { toast } from '@/components/controls/toast'
import { LogSheet } from '@/components/sheet/LogSheet'
import { closeLogSheet, toggleLogSheet, useLogSheet } from '@/components/sheet/logSheetStore'
import { I18nProvider } from '@/i18n/I18nProvider'
import { useT } from '@/i18n/useT'
import type { Dictionary } from '@/i18n/translate'
import { cx } from '@/lib/cx'
import type { Lang } from '@/lib/format'
import { BottomNav } from './BottomNav'
import { DESKTOP_MIN_WIDTH, LayoutContext } from './layout'
import { screenForPath, type ScreenId } from './nav'
import { Rail } from './Rail'
import { Stage, type StackInfo } from './Stage'

/** The frame around every screen: the rail (desktop), the stage, the bottom bar (phone), the log
 *  sheet and the toasts. The host is the container the layout rules ask about; the shell tells the
 *  few parts that are drawn in script whether it is a desktop yet. */
export function AppShell({ lang, dictionary }: { lang: Lang; dictionary: Dictionary }) {
  const router = useRouter()
  const host = useRef<HTMLDivElement>(null)
  const [desktop, setDesktop] = useState(() => window.innerWidth >= DESKTOP_MIN_WIDTH)
  const { open } = useLogSheet()
  const [stack, setStack] = useState<StackInfo>(() => {
    const first: ScreenId = screenForPath(router.state.location.pathname) ?? 'today'
    return { root: first, top: first, depth: 1 }
  })

  useLayoutEffect(() => {
    const el = host.current
    if (el === null) return
    const read = () => setDesktop(el.clientWidth >= DESKTOP_MIN_WIDTH)
    read()
    const observer = new ResizeObserver(read)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // N opens the log (from anywhere but a field), Esc closes it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as Element | null
      if (target?.closest('input, textarea, select, [contenteditable]')) return
      if ((e.key === 'n' || e.key === 'т') && !e.metaKey && !e.ctrlKey && !e.altKey) toggleLogSheet('weight')
      if (e.key === 'Escape') closeLogSheet()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  return (
    <I18nProvider lang={lang} dictionary={dictionary}>
      <OfflineWatcher />
      <LayoutContext value={{ desktop }}>
        <div ref={host} className="app-host">
          <div className={cx('vt', open && 'sheet-open')}>
            <Rail active={stack.top} />
            <Stage onStack={setStack} />
            <BottomNav root={stack.root} depth={stack.depth} />
            <LogSheet />
            <ToastHost />
          </div>
        </div>
      </LayoutContext>
    </I18nProvider>
  )
}

function OfflineWatcher() {
  const { t } = useT()
  useEffect(() => {
    const handleOffline = () => {
      toast(t('app.offline_toast'), { icon: 'wifiOff' })
    }
    window.addEventListener('offline', handleOffline)
    return () => window.removeEventListener('offline', handleOffline)
  }, [t])
  return null
}
