import { useLayoutEffect, useRef } from 'react'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { animate } from '@/lib/motion'
import { dismissToast, useToasts, type ToastItem } from './toast'

function ToastView({ item }: { item: ToastItem }) {
  const { t } = useT()
  const node = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    if (node.current === null) return
    const a = animate(node.current, [{ opacity: 0, transform: 'translateY(16px) scale(.97)' }, { opacity: 1, transform: 'none' }], { duration: 420 })
    return () => a.cancel()
  }, [])
  useLayoutEffect(() => {
    if (!item.leaving || node.current === null) return
    animate(node.current, [{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateY(8px)' }], { duration: 220, easing: 'ease-in' })
  }, [item.leaving])

  return (
    <div ref={node} className="toast" role="status">
      <Icon name={item.icon} className={item.icon === 'info' ? 'toast-muted' : undefined} />
      <span>{item.text}</span>
      {item.undo !== undefined ? (
        <button
          type="button"
          className="tb"
          onClick={() => {
            item.undo?.()
            dismissToast(item.id)
          }}
        >
          {t('app.undo')}
        </button>
      ) : (
        <span style={{ width: 6 }} />
      )}
    </div>
  )
}

/** Where toasts appear: above the bottom bar on a phone, bottom right on a desktop. */
export function ToastHost() {
  const items = useToasts()
  return (
    <div className="toasts" aria-live="polite">
      {items.map((item) => (
        <ToastView key={item.id} item={item} />
      ))}
    </div>
  )
}
