import { Component, type ReactNode } from 'react'
import { QueryErrorResetBoundary } from '@tanstack/react-query'
import { TextButton } from '@/components/controls/Marks'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { SCREEN_TITLE_KEY, type ScreenId } from './nav'
import { Headline, Mast, TopBar } from './PageHead'

export interface CatchProps {
  /** Lets the failed queries run again before the screen is drawn anew. */
  onReset: () => void
  fallback: (retry: () => void) => ReactNode
  children: ReactNode
}

export class Catch extends Component<CatchProps, { failed: boolean }> {
  override state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  retry = () => {
    this.props.onReset()
    this.setState({ failed: false })
  }

  override render() {
    return this.state.failed ? this.props.fallback(this.retry) : this.props.children
  }
}

/** The message a failed screen shows in place of its content: what happened, and the one action. */
export function FailedNotice({ onRetry }: { onRetry: () => void }) {
  const { t } = useT()
  return (
    <div className="st-body st-fail" role="alert">
      <div className="empty warn">
        <Icon name="warn" />
        <p>
          {t('app.load_failed')}
          <small>{t('app.load_failed_sub')}</small>
        </p>
        <TextButton icon="sync" onClick={onRetry}>
          {t('app.retry')}
        </TextButton>
      </div>
    </div>
  )
}

/** What a screen shows when its data could not be read: its own name, one line saying so and
 *  one action. Never a screen of zeros. */
export function ScreenFailed({ id, onRetry }: { id: ScreenId; onRetry: () => void }) {
  const { t } = useT()
  const title = t(SCREEN_TITLE_KEY[id])
  return (
    <>
      <TopBar title={title} />
      <Mast screen={id} />
      <Headline title={title} />
      <FailedNotice onRetry={onRetry} />
    </>
  )
}

/** Keeps a failure inside the screen it happened on: the shell, the navigation and the other
 *  screens of the stack stay as they are. */
export function ScreenBoundary({ id, children }: { id: ScreenId; children: ReactNode }) {
  return (
    <QueryErrorResetBoundary>
      {({ reset }) => (
        <Catch onReset={reset} fallback={(retry) => <ScreenFailed id={id} onRetry={retry} />}>
          {children}
        </Catch>
      )}
    </QueryErrorResetBoundary>
  )
}
