import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, ok, failText } from '@/api/client'
import { OptionGroup } from '@/components/controls/Choices'
import { Badge } from '@/components/controls/Marks'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { parseIsoDate, shortDate } from '@/lib/dates'
import type { CreatedShareResponse, SharedReportItem } from './types'
import { useShareView } from './useShareView'
import './share.css'

export default function ShareScreen() {
  const { t, tOr, lang } = useT()
  const view = useShareView()
  const queryClient = useQueryClient()

  // Form states
  const [selectedPreset, setSelectedPreset] = useState('gp')
  const [title, setTitle] = useState(() => t('share.preset_title.gp'))
  const [titleEdited, setTitleEdited] = useState(false)
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
    if (!titleEdited) {
      const localizedTitle = tOr(`share.preset_title.${presetKey}`, '')
      if (localizedTitle !== '') setTitle(localizedTitle)
    }
  }

  const toggleDomain = (dom: string) => {
    setSelectedDomains((prev) =>
      prev.includes(dom) ? prev.filter((d) => d !== dom) : [...prev, dom]
    )
  }

  const handleCreateShare = async (): Promise<boolean> => {
    if (!title.trim()) {
      toast(t('app.name_required'), { icon: 'warn' })
      return false
    }
    if (selectedDomains.length === 0) {
      toast(t('share.toast_select_domain'), { icon: 'warn' })
      return false
    }
    setIsCreating(true)
    try {
      const data = await ok(
        api.POST('/api/v1/share', {
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
        }),
      )
      setCreated(data)
      toast(t('share.toast_created'))
      refresh()
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    } finally {
      setIsCreating(false)
    }
  }

  const handleRevoke = async (id: number) => {
    try {
      await ok(api.POST('/api/v1/share/{report_id}/revoke', {
        params: { path: { report_id: id } },
      }))
      toast(t('share.toast_revoked'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.action_failed')), { icon: 'warn' })
    }
  }

  const handleDelete = async (id: number) => {
    try {
      await ok(api.DELETE('/api/v1/share/{report_id}', {
        params: { path: { report_id: id } },
      }))
      toast(t('common.deleted'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.delete_failed')), { icon: 'warn' })
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

  const domainLabel = (d: string) => tOr(`nav.${d}`, tOr(`enum.domain.${d}`, d))

  const presetLabel = (pKey: string) => tOr(`share.preset.${pKey}`, pKey)

  return (
    <>
      <TopBar title={t('share.title')} />
      <Mast screen="share" />
      <Headline title={t('share.title')} />

      <p className="sub lede">
        {t('share.lede')}
      </p>

      <div className="grid sec-grid">
        {/* Left Column: Generator & Created Banner */}
        <div className="c7">
          <section className="sec o1">
            {/* Created Banner */}
            {created && (
              <div className="panel made share-made">
                <div className="panel-h">
                  <h3>
                    <Icon name="check" />
                    {t('share.link_ready')}
                  </h3>
                </div>
                <div className="made-r">
                  <span className="flabel">{t('share.link_label')}</span>
                  <input
                    className="input"
                    readOnly
                    value={fullShareUrl}
                  />
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => copyToClipboard(fullShareUrl, t('share.copied_link'))}
                  >
                    <Icon name="copy" />
                    <span>{t('share.copied_link')}</span>
                  </button>
                </div>
                <div className="made-r">
                  <span className="flabel">{t('share.password_label')}</span>
                  <input
                    className="input"
                    readOnly
                    value={created.password}
                  />
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => copyToClipboard(created.password, t('share.copied_password'))}
                  >
                    <Icon name="copy" />
                    <span>{t('share.copied_password')}</span>
                  </button>
                </div>
                <p className="fhint">
                  {t('share.password_hint')}
                </p>
              </div>
            )}

            {/* Creation Form */}
            <div className="panel fpanel share-form">
              <div className="panel-h">
                <h3>{t('share.new_report')}</h3>
              </div>
              <div className="form">
                <label className="field">
                  <span className="flabel">{t('share.report_title')}</span>
                  <input
                    className="input"
                    placeholder={t('share.title_ph')}
                    value={title}
                    onChange={(e) => {
                      setTitleEdited(true)
                      setTitle(e.target.value)
                    }}
                  />
                </label>

                {/* Presets */}
                <div className="field">
                  <span className="flabel">{t('share.preset')}</span>
                  <div className="opts share-opts">
                    {Object.keys(view.presets).length > 0 ? (
                      Object.keys(view.presets).map((pKey) => (
                        <button
                          key={pKey}
                          type="button"
                          className={`opt ${selectedPreset === pKey ? 'on' : ''}`}
                          onClick={() => handlePresetSelect(pKey)}
                        >
                          {presetLabel(pKey)}
                        </button>
                      ))
                    ) : (
                      <>
                        <button
                          type="button"
                          className={`opt ${selectedPreset === 'gp' ? 'on' : ''}`}
                          onClick={() => handlePresetSelect('gp')}
                        >
                          {presetLabel('gp')}
                        </button>
                        <button
                          type="button"
                          className={`opt ${selectedPreset === 'endo' ? 'on' : ''}`}
                          onClick={() => handlePresetSelect('endo')}
                        >
                          {presetLabel('endo')}
                        </button>
                        <button
                          type="button"
                          className={`opt ${selectedPreset === 'custom' ? 'on' : ''}`}
                          onClick={() => handlePresetSelect('custom')}
                        >
                          {presetLabel('custom')}
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {/* What's included (domains) */}
                <div className="field">
                  <span className="flabel">{t('share.whats_included')}</span>
                  <div className="opts share-opts">
                    {view.availableDomains.map((d) => (
                      <button
                        key={d}
                        type="button"
                        className={`opt ${selectedDomains.includes(d) ? 'on' : ''}`}
                        onClick={() => toggleDomain(d)}
                      >
                        {domainLabel(d)}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="share-grid-2">
                  {/* Period */}
                  <div className="field">
                    <span className="flabel">{t('share.report_period')}</span>
                    <div className="opts share-opts">
                      {['30', '90', '180', '365', 'all', 'custom'].map((pChoice) => (
                        <button
                          key={pChoice}
                          type="button"
                          className={`opt ${period === pChoice ? 'on' : ''}`}
                          onClick={() => setPeriod(pChoice)}
                        >
                          {pChoice === 'all'
                            ? t('share.period_all')
                            : pChoice === 'custom'
                              ? t('share.period_custom')
                              : t('share.period_n_days', { n: pChoice })}
                        </button>
                      ))}
                    </div>

                    {/* Custom Range Picker */}
                    {period === 'custom' && (
                      <div className="share-custom-dates">
                        <label className="field">
                          <span className="flabel">{t('share.period_from')}</span>
                          <input
                            type="date"
                            className="input"
                            value={customStart}
                            onChange={(e) => setCustomStart(e.target.value)}
                          />
                        </label>
                        <label className="field">
                          <span className="flabel">{t('share.period_to')}</span>
                          <input
                            type="date"
                            className="input"
                            value={customEnd}
                            onChange={(e) => setCustomEnd(e.target.value)}
                          />
                        </label>
                      </div>
                    )}
                  </div>

                  <div>
                    {/* Expiration */}
                    <div className="field">
                      <span className="flabel">{t('share.link_expires')}</span>
                      <div className="opts share-opts">
                        {[7, 14, 30].map((days) => (
                          <button
                            key={days}
                            type="button"
                            className={`opt ${expiresDays === days ? 'on' : ''}`}
                            onClick={() => setExpiresDays(days)}
                          >
                            {t('share.expires_n_days', { n: days })}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Flagged labs toggle using OptionGroup */}
                    <div className="field share-labs-toggle">
                      <span className="flabel">{t('share.section.labs')}</span>
                      <OptionGroup
                        value={labsFlaggedOnly ? 'flagged' : 'all'}
                        onChange={(val) => setLabsFlaggedOnly(val === 'flagged')}
                        options={[
                          { id: 'all', label: t('share.labs_all') },
                          { id: 'flagged', label: t('share.labs_flagged_only') },
                        ]}
                      />
                    </div>
                  </div>
                </div>

                {/* Note */}
                <label className="field">
                  <span className="flabel">{t('share.note_from_me')}</span>
                  <textarea
                    className="input"
                    rows={3}
                    placeholder={t('share.note_ph')}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                  />
                </label>

                <PrimaryButton
                  className="btn share-btn-submit"
                  onPress={handleCreateShare}
                  disabled={isCreating}
                >
                  <Icon name="link" />
                  <span>{t('share.create_link')}</span>
                </PrimaryButton>
              </div>
            </div>
          </section>
        </div>

        {/* Right Column: Existing Reports */}
        <div className="c5">
          <section className="sec o2">
            <div className="sec-h">
              <h2>{t('share.created_reports')}</h2>
              {view.reports.length > 0 && (
                <span className="meta">{view.reports.length}</span>
              )}
            </div>

            {view.reports.length > 0 ? (
              <div className="rows">
                {view.reports.map((s: SharedReportItem) => {
                  const dead = s.state !== 'live'
                  const pStart = s.periodStart ? shortDate(parseIsoDate(s.periodStart), lang) : ''
                  const pEnd = s.periodEnd ? shortDate(parseIsoDate(s.periodEnd), lang) : ''
                  const expiresFormatted = s.expiresAt ? shortDate(parseIsoDate(s.expiresAt.slice(0, 10)), lang) : ''
                  return (
                    <div
                      key={s.id}
                      className={`row r-share ${dead ? 'dim-soft' : ''}`}
                      data-item
                    >
                      <div>
                        <div className="t">{s.title}</div>
                        <div className="m">
                          {s.domains.map((d) => domainLabel(d)).join(' · ')}
                        </div>
                      </div>
                      <div className="sh-meta">
                        <span className="m num">
                          {pStart && pEnd ? `${pStart} — ${pEnd}` : '—'}
                        </span>
                        {s.state === 'revoked' ? (
                          <Badge tone="plain">{t('share.revoked')}</Badge>
                        ) : s.state === 'expired' ? (
                          <Badge tone="plain">{t('share.expired')}</Badge>
                        ) : (
                          <span className="m num">{t('share.expires_until', { date: expiresFormatted })}</span>
                        )}
                        <span className="m num">
                          {s.openedCount
                            ? t('share.opened_n_times', { count: s.openedCount })
                            : t('share.never_opened')}
                        </span>
                      </div>
                      <span className="acts">
                        {s.hasSnapshot && (
                          <a
                            href={`/share/${s.id}/download`}
                            download
                            className="ibtn"
                            aria-label={t('share.download')}
                            title={t('share.download')}
                          >
                            <Icon name="download" />
                          </a>
                        )}
                        {dead ? (
                          <button
                            type="button"
                            className="ibtn"
                            onClick={() => handleDelete(s.id)}
                            aria-label={t('share.remove_from_list')}
                          >
                            <Icon name="trash" />
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="ghost danger"
                            onClick={() => handleRevoke(s.id)}
                          >
                            {t('share.revoke_action')}
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
                <p>{t('share.no_reports')}</p>
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
                <b>{t('share.how_doctor_sees')}</b>
                <small>{t('share.open_example')}</small>
              </span>
              <Icon name="chevR" className="chev" />
            </a>
          </section>
        </div>
      </div>
    </>
  )
}
