import { useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, ok, failText } from '@/api/client'
import { Badge } from '@/components/controls/Marks'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { parseIsoDate, shortDate } from '@/lib/dates'
import { formatInt } from '@/lib/format'
import { signalTime, signalValue } from './signalText'
import type { SignalItem } from './types'
import { useSignalsView } from './useSignalsView'
import './signals.css'

const KIND_META: Record<string, [string, 'plain' | 'bad' | 'cool' | 'violet']> = {
  state: ['app.signal_kind.state', 'plain'],
  symptom: ['app.signal_kind.symptom', 'bad'],
  exposure: ['app.signal_kind.exposure', 'cool'],
}

export default function SignalsScreen() {
  const { t, tOr, lang } = useT()
  const view = useSignalsView()
  const queryClient = useQueryClient()

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['signals'] })
  }

  const formatSignalKey = (key: string) => tOr(`app.signal_key.${key}`, key.replaceAll('_', ' '))

  const maxFreq = useMemo(() => {
    if (!view.frequency.length) return 1
    return Math.max(...view.frequency.map((f) => f.count ?? f.n ?? 1))
  }, [view.frequency])

  // Group signals by day
  const groupedByDate = useMemo(() => {
    const map = new Map<string, SignalItem[]>()
    for (const s of view.signals) {
      if (!map.has(s.date)) map.set(s.date, [])
      map.get(s.date)!.push(s)
    }
    return map
  }, [view.signals])

  const handleDelete = async (signalId: number) => {
    try {
      await ok(api.DELETE('/api/v1/signals/{signal_id}', {
        params: { path: { signal_id: signalId } },
      }))
      toast(t('common.deleted'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.delete_failed')), { icon: 'warn' })
    }
  }

  const handleMarkMisparse = async (batchId: string) => {
    try {
      await ok(api.POST('/api/v1/signals/{batch_id}/misparse', {
        params: { path: { batch_id: batchId } },
      }))
      toast(t('app.signals.misparsed'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    }
  }

  return (
    <>
      <TopBar title={t('nav.signals')} />
      <Mast screen="signals" />
      <Headline title={t('nav.signals')}>
        <div className="figs inline">
          <div className="f">
            <div className="f-v">{view.totalCount || view.signals.length}</div>
            <div className="f-l">{t('app.signals.records')}</div>
          </div>
          <div className="f">
            <div className="f-v">{view.keysCount || view.frequency.length}</div>
            <div className="f-l">{t('app.signals.keys')}</div>
          </div>
          <div className="f">
            <div className="f-v">{view.misparseCount}</div>
            <div className="f-l">{t('app.signals.misparses')}</div>
          </div>
        </div>
      </Headline>

      <p className="sub lede">{t('app.signals.lede')}</p>

      {/* Key frequency section */}
      {view.frequency.length > 0 && (
        <section className="sec">
          <div className="sec-h">
            <h2>{t('app.signals.key_frequency')}</h2>
          </div>
          <p className="sub sig-desc">
            {t('app.signals.key_frequency_desc')}
          </p>
          <div className="rows">
            {view.frequency.map((f) => {
              const count = f.count ?? f.n ?? 0
              const aliases = f.variants?.length ? f.variants : f.alias || []
              const examples = f.examples?.length ? f.examples : f.ex || []
              const pct = (count / maxFreq) * 100
              return (
                <div key={f.key} className="row freq">
                  <div>
                    <div className="t sig-key">{formatSignalKey(f.key)}</div>
                    {aliases.length > 0 && (
                      <div className="m sig-key" title={t('app.signals.saved_under_key')}>
                        ← {aliases.map((a) => formatSignalKey(a)).join(', ')}
                      </div>
                    )}
                  </div>
                  <div className="fbar">
                    <i style={{ width: `${pct}%` }} />
                  </div>
                  <span className="v num">{formatInt(count, lang)}</span>
                  <div className="fex m">
                    {examples.length > 0 ? (
                      examples.map((e, idx) => <div key={idx}>{e}</div>)
                    ) : (
                      <span>—</span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* Feed Section */}
      <section className="sec">
        <div className="sec-h">
          <h2>{t('app.signals.feed')}</h2>
        </div>
        {view.signals.length > 0 ? (
          <div className="tl">
            {Array.from(groupedByDate.entries()).map(([date, signals]) => (
              <div key={date} className="tl-day">
                <div className="d num">{shortDate(parseIsoDate(date), lang)}</div>
                <div className="tl-list">
                  {signals.map((s) => {
                    const km = KIND_META[s.kind] || ['app.signal_kind.signal', 'plain']
                    return (
                      <div key={s.id} className="tl-ev" data-item>
                        <i className="tk violet" />
                        <div>
                          <div className="ev-h">
                            <Badge tone={km[1]}>{t(km[0])}</Badge>
                            <span className="t sig-key">{formatSignalKey(s.key)}</span>
                            {s.rawKey && s.rawKey !== s.key && (
                              <span className="m sig-key">← {s.rawKey.replaceAll('_', ' ')}</span>
                            )}
                            {s.value != null && (
                              <span className="m num">{signalValue(s.value, s.unit, lang)}</span>
                            )}
                            {s.time && <span className="m num">{signalTime(s.time)}</span>}
                            {s.misparse && <Badge tone="bad">{t('app.signals.misparse_badge')}</Badge>}
                          </div>
                          {s.note && <div className="m">{s.note}</div>}
                        </div>
                        <span className="acts">
                          {s.batchId && !s.misparse && (
                            <button
                              type="button"
                              className="ibtn"
                              title={t('app.signals.mark_misparse')}
                              onClick={() => handleMarkMisparse(s.batchId!)}
                            >
                              <Icon name="warn" />
                            </button>
                          )}
                          <button
                            type="button"
                            className="ibtn"
                            onClick={() => handleDelete(s.id)}
                            aria-label={t('common.delete')}
                          >
                            <Icon name="trash" />
                          </button>
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty">
            <Icon name="signals" />
            <p>{t('app.signals.empty')}</p>
          </div>
        )}
      </section>
    </>
  )
}
