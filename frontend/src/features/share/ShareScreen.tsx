import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { Badge } from '@/components/controls/Marks'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import type { CreatedShareResponse, SharedReportItem } from './types'
import { useShareView } from './useShareView'
import './share.css'

const DOM_RU: Record<string, string> = {
  weight: 'Вес',
  body_comp: 'Состав тела',
  labs: 'Анализы',
  glp1: 'GLP-1',
  hrt: 'ГЗТ',
  supplements: 'Добавки',
  signals: 'Сигналы',
}

export default function ShareScreen() {
  const { t } = useT()
  const view = useShareView()
  const queryClient = useQueryClient()

  // Form states
  const [title, setTitle] = useState('Эндокринолог, осмотр')
  const [selectedPreset, setSelectedPreset] = useState('gp')
  const [selectedDomains, setSelectedDomains] = useState<string[]>([
    'weight',
    'labs',
    'glp1',
    'supplements',
  ])
  const [period, setPeriod] = useState('90')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')
  const [expiresDays, setExpiresDays] = useState(14)
  const [labsFlaggedOnly, setLabsFlaggedOnly] = useState(false)
  const [note, setNote] = useState('')
  const [isCreating, setIsCreating] = useState(false)

  // Newly created share
  const [created, setCreated] = useState<CreatedShareResponse | null>(null)

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['share'] })
  }

  const handlePresetSelect = (presetKey: string) => {
    setSelectedPreset(presetKey)
    const preset = view.presets[presetKey]
    if (preset) {
      setSelectedDomains(preset.domains)
      setLabsFlaggedOnly(preset.labsFlaggedOnly)
    }
  }

  const toggleDomain = (dom: string) => {
    setSelectedDomains((prev) =>
      prev.includes(dom) ? prev.filter((d) => d !== dom) : [...prev, dom]
    )
  }

  const handleCreateShare = async (): Promise<boolean> => {
    if (!title.trim()) {
      toast(t('common.required_field') || 'Title is required', { icon: 'warn' })
      return false
    }
    if (selectedDomains.length === 0) {
      toast('Выберите хотя бы один раздел', { icon: 'warn' })
      return false
    }
    setIsCreating(true)
    try {
      const res = await api.POST('/api/v1/share', {
        body: {
          title: title.trim(),
          preset: selectedPreset || null,
          domains: selectedDomains,
          period,
          periodStart: period === 'custom' ? customStart : null,
          periodEnd: period === 'custom' ? customEnd : null,
          expiresDays,
          labsFlaggedOnly,
          note: note.trim() || null,
        },
      })
      if (res.data) {
        setCreated(res.data)
        toast('Ссылка создана')
        refresh()
        return true
      }
      return false
    } catch (err: any) {
      toast(err.message || 'Ошибка создания отчёта', { icon: 'warn' })
      return false
    } finally {
      setIsCreating(false)
    }
  }

  const handleRevoke = async (id: number) => {
    try {
      await api.POST('/api/v1/share/{report_id}/revoke', {
        params: { path: { report_id: id } },
      })
      toast('Отчёт отозван')
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error revoking report', { icon: 'warn' })
    }
  }

  const handleDelete = async (id: number) => {
    try {
      await api.DELETE('/api/v1/share/{report_id}', {
        params: { path: { report_id: id } },
      })
      toast(t('common.deleted'))
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error deleting report', { icon: 'warn' })
    }
  }

  const copyToClipboard = (text: string, msg: string) => {
    void navigator.clipboard.writeText(text)
    toast(msg)
  }

  const fullShareUrl = useMemo(() => {
    if (!created) return ''
    if (typeof window !== 'undefined') {
      return `${window.location.origin}${created.url}`
    }
    return created.url
  }, [created])

  return (
    <>
      <TopBar title={t('app.nav.share') || 'Для врача'} />
      <Mast screen="share" />
      <Headline title="Для врача">
        <span className="crumb">Система</span>
      </Headline>

      <p className="sub lede">
        Отчёт — снимок: после создания он не меняется.
      </p>

      <div className="grid mt-6">
        {/* Left Column: Generator & Created Banner */}
        <div className="c7">
          <section className="sec o1">
            {/* Created Banner */}
            {created && (
              <div className="panel made mb-6">
                <div className="panel-h">
                  <h3>
                    <Icon name="check" />
                    Ссылка готова
                  </h3>
                </div>
                <div className="made-r">
                  <span className="flabel">Ссылка</span>
                  <input
                    className="input mono"
                    readOnly
                    value={fullShareUrl}
                  />
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => copyToClipboard(fullShareUrl, 'Ссылка скопирована')}
                  >
                    <Icon name="copy" />
                    <span>Копировать</span>
                  </button>
                </div>
                <div className="made-r">
                  <span className="flabel">Пароль</span>
                  <input
                    className="input mono"
                    readOnly
                    value={created.password}
                  />
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => copyToClipboard(created.password, 'Пароль скопирован')}
                  >
                    <Icon name="copy" />
                    <span>Копировать</span>
                  </button>
                </div>
                <p className="fhint">
                  Пароль показывается один раз и не восстанавливается — скопируй сейчас.
                </p>
              </div>
            )}

            {/* Creation Form */}
            <div className="panel fpanel share-form">
              <div className="panel-h">
                <h3>Новый отчёт</h3>
              </div>
              <div className="form space-y-4">
                <label className="field">
                  <span className="flabel">Название</span>
                  <input
                    className="input"
                    placeholder="например, Эндокринолог, август"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                </label>

                {/* Presets */}
                <div className="field">
                  <span className="flabel">Пресет</span>
                  <div className="opts flex gap-1 flex-wrap">
                    {Object.keys(view.presets).length > 0 ? (
                      Object.keys(view.presets).map((pKey) => (
                        <button
                          key={pKey}
                          type="button"
                          className={`opt ${selectedPreset === pKey ? 'on' : ''}`}
                          onClick={() => handlePresetSelect(pKey)}
                        >
                          {pKey === 'gp' ? 'Терапевт' : pKey === 'endo' ? 'Эндокринолог' : pKey === 'trainer' ? 'Тренер' : pKey}
                        </button>
                      ))
                    ) : (
                      <>
                        <button
                          type="button"
                          className={`opt ${selectedPreset === 'gp' ? 'on' : ''}`}
                          onClick={() => setSelectedPreset('gp')}
                        >
                          Терапевт
                        </button>
                        <button
                          type="button"
                          className={`opt ${selectedPreset === 'endo' ? 'on' : ''}`}
                          onClick={() => setSelectedPreset('endo')}
                        >
                          Эндокринолог
                        </button>
                        <button
                          type="button"
                          className={`opt ${selectedPreset === 'custom' ? 'on' : ''}`}
                          onClick={() => setSelectedPreset('custom')}
                        >
                          Свой выбор
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {/* What's included (domains) */}
                <div className="field">
                  <span className="flabel">Что войдёт</span>
                  <div className="opts flex gap-1 flex-wrap">
                    {view.availableDomains.map((d) => (
                      <button
                        key={d}
                        type="button"
                        className={`opt ${selectedDomains.includes(d) ? 'on' : ''}`}
                        onClick={() => toggleDomain(d)}
                      >
                        {DOM_RU[d] || d}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Period */}
                <div className="field">
                  <span className="flabel">Период отчёта</span>
                  <div className="opts flex gap-1 flex-wrap">
                    {['30', '90', '180', '365', 'all', 'custom'].map((pChoice) => (
                      <button
                        key={pChoice}
                        type="button"
                        className={`opt ${period === pChoice ? 'on' : ''}`}
                        onClick={() => setPeriod(pChoice)}
                      >
                        {pChoice === 'all'
                          ? 'Всё время'
                          : pChoice === 'custom'
                            ? 'Точный диапазон'
                            : `${pChoice} дней`}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Custom Range Picker */}
                {period === 'custom' && (
                  <div className="grid grid-cols-2 gap-3">
                    <label className="field">
                      <span className="flabel">С</span>
                      <input
                        type="date"
                        className="input"
                        value={customStart}
                        onChange={(e) => setCustomStart(e.target.value)}
                      />
                    </label>
                    <label className="field">
                      <span className="flabel">По</span>
                      <input
                        type="date"
                        className="input"
                        value={customEnd}
                        onChange={(e) => setCustomEnd(e.target.value)}
                      />
                    </label>
                  </div>
                )}

                {/* Expiration */}
                <div className="field">
                  <span className="flabel">Ссылка живёт</span>
                  <div className="opts flex gap-1 flex-wrap">
                    {[7, 14, 30].map((days) => (
                      <button
                        key={days}
                        type="button"
                        className={`opt ${expiresDays === days ? 'on' : ''}`}
                        onClick={() => setExpiresDays(days)}
                      >
                        {days} дней
                      </button>
                    ))}
                  </div>
                </div>

                {/* Flagged labs toggle */}
                <label className="flex items-center gap-2 cursor-pointer pt-1">
                  <input
                    type="checkbox"
                    checked={labsFlaggedOnly}
                    onChange={(e) => setLabsFlaggedOnly(e.target.checked)}
                  />
                  <span className="text-sm">Только маркеры вне нормы</span>
                </label>

                {/* Note */}
                <label className="field">
                  <span className="flabel">От меня</span>
                  <textarea
                    className="input"
                    rows={3}
                    placeholder="О чём хочу спросить..."
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                  />
                </label>

                <PrimaryButton
                  className="btn w mt-2"
                  onPress={handleCreateShare}
                  disabled={isCreating}
                >
                  <Icon name="link" />
                  <span>Создать ссылку</span>
                </PrimaryButton>
              </div>
            </div>
          </section>
        </div>

        {/* Right Column: Existing Reports */}
        <div className="c5">
          <section className="sec o2">
            <div className="sec-h">
              <h2>Созданные отчёты</h2>
              {view.reports.length > 0 && (
                <span className="meta">{view.reports.length}</span>
              )}
            </div>

            {view.reports.length > 0 ? (
              <div className="rows">
                {view.reports.map((s: SharedReportItem) => {
                  const dead = s.state !== 'live'
                  return (
                    <div
                      key={s.id}
                      className={`row r-share ${dead ? 'dim-soft' : ''}`}
                      data-item
                    >
                      <div>
                        <div className="t">{s.title}</div>
                        <div className="m">
                          {s.domains.map((d) => DOM_RU[d] || d).join(' · ')}
                        </div>
                      </div>
                      <div className="sh-meta">
                        <span className="m num">
                          {s.periodStart} — {s.periodEnd}
                        </span>
                        {s.state === 'revoked' ? (
                          <Badge tone="plain">отозван</Badge>
                        ) : s.state === 'expired' ? (
                          <Badge tone="plain">истёк</Badge>
                        ) : (
                          <span className="m num">до {s.expiresAt.slice(0, 10)}</span>
                        )}
                        <span className="m num">
                          {s.openedCount
                            ? `открывали ${s.openedCount}×`
                            : 'ещё не открывали'}
                        </span>
                      </div>
                      <span className="acts">
                        {dead ? (
                          <button
                            type="button"
                            className="ibtn"
                            onClick={() => handleDelete(s.id)}
                            aria-label="Убрать из списка"
                          >
                            <Icon name="trash" />
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="ghost danger"
                            onClick={() => handleRevoke(s.id)}
                          >
                            Отозвать
                          </button>
                        )}
                      </span>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="empty">
                <Icon name="clipboard" />
                <p>Отчётов пока нет.</p>
              </div>
            )}

            <a
              href="/r/example"
              target="_blank"
              rel="noreferrer"
              className="link-row"
            >
              <Icon name="doc" />
              <span>
                <b>Как отчёт видит врач</b>
                <small>открыть пример документа</small>
              </span>
              <Icon name="chevR" className="chev" />
            </a>
          </section>
        </div>
      </div>
    </>
  )
}
