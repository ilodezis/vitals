import { useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { Badge } from '@/components/controls/Marks'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import type { SignalItem } from './types'
import { useSignalsView } from './useSignalsView'
import './signals.css'

const KIND_META: Record<string, [string, 'plain' | 'bad' | 'cool' | 'violet']> = {
  state: ['Состояние', 'plain'],
  symptom: ['Симптом', 'bad'],
  exposure: ['Воздействие', 'cool'],
}

export default function SignalsScreen() {
  const { t } = useT()
  const view = useSignalsView()
  const queryClient = useQueryClient()

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['signals'] })
  }

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
      await api.DELETE('/api/v1/signals/{signal_id}', {
        params: { path: { signal_id: signalId } },
      })
      toast(t('common.deleted'))
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error deleting signal', { icon: 'warn' })
    }
  }

  const handleMarkMisparse = async (batchId: string) => {
    try {
      await api.POST('/api/v1/signals/{batch_id}/misparse', {
        params: { path: { batch_id: batchId } },
      })
      toast('Отмечено как не то')
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error marking misparse', { icon: 'warn' })
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
            <div className="f-l">Записей</div>
          </div>
          <div className="f">
            <div className="f-v">{view.keysCount || view.frequency.length}</div>
            <div className="f-l">Ключей</div>
          </div>
          <div className="f">
            <div className="f-v">{view.misparseCount}</div>
            <div className="f-l">Промахи</div>
          </div>
        </div>
      </Headline>

      <p className="sub lede">
        Всё, что сказано боту мимоходом — сонливость, голова, кофе в 22 — разобрано в строки.
        Это тот слой, который объясняет цифры Garmin.
      </p>

      {/* Key frequency section */}
      {view.frequency.length > 0 && (
        <section className="sec">
          <div className="sec-h">
            <h2>Частота ключей</h2>
          </div>
          <p className="sub" style={{ margin: '-4px 0 12px', maxWidth: '64ch' }}>
            Что модель пишет на самом деле, вместе с ошибками — материал, по которому потом
            собирается реестр ключей.
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
                    <div className="t key font-mono font-semibold">{f.key}</div>
                    {aliases.length > 0 && (
                      <div className="m key" title="Сохранено под этим ключом">
                        ← {aliases.join(', ')}
                      </div>
                    )}
                  </div>
                  <div className="fbar">
                    <i style={{ width: `${pct}%` }} />
                  </div>
                  <span className="v num">{count}</span>
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
          <h2>Лента</h2>
        </div>
        {view.signals.length > 0 ? (
          <div className="tl">
            {Array.from(groupedByDate.entries()).map(([date, signals]) => (
              <div key={date} className="tl-day">
                <div className="d num">{date}</div>
                <div className="tl-list">
                  {signals.map((s) => {
                    const km = KIND_META[s.kind] || ['Сигнал', 'plain']
                    return (
                      <div key={s.id} className="tl-ev" data-item>
                        <i className="tk violet" />
                        <div>
                          <div className="ev-h">
                            <Badge tone={km[1]}>{km[0]}</Badge>
                            <span className="t key font-mono">{s.key}</span>
                            {s.rawKey && s.rawKey !== s.key && (
                              <span className="m key">← {s.rawKey}</span>
                            )}
                            {s.value != null && (
                              <span className="m num">
                                {s.value}
                                {s.unit ? ` ${s.unit}` : ''}
                              </span>
                            )}
                            {s.time && <span className="m num">{s.time}</span>}
                            {s.misparse && <Badge tone="bad">не то</Badge>}
                          </div>
                          {s.note && <div className="m">{s.note}</div>}
                        </div>
                        <span className="acts">
                          {s.batchId && !s.misparse && (
                            <button
                              type="button"
                              className="ibtn"
                              title="Отметить не то"
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
            <p>Сигналов пока нет. Отправляйте боту сообщения о самочувствии и симптомах.</p>
          </div>
        )}
      </section>
    </>
  )
}
