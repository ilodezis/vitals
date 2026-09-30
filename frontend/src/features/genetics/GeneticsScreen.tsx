import { useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, failText, ok, RequestError } from '@/api/client'
import { FilterRow } from '@/components/controls/Choices'
import { Badge, Dot, TextButton } from '@/components/controls/Marks'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { DomainAlerts } from '@/components/controls/DomainAlerts'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { useGeneticsView } from './useGeneticsView'
import './genetics.css'

/** The modules a variant can bear on — the domain is free text, these are only suggestions. */
const GENE_DOMAINS = ['supplements', 'workouts', 'weight', 'glp1', 'labs', 'skincare', 'system', 'health'] as const

export default function GeneticsScreen() {
  const { t, tOr } = useT()
  const view = useGeneticsView()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [tab, setTab] = useState('all')
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [isUploading, setIsUploading] = useState(false)

  // Add form fields
  const [gene, setGene] = useState('')
  const [rsid, setRsid] = useState('')
  const [genotype, setGenotype] = useState('')
  const [impact, setImpact] = useState('')
  const [impactDomain, setImpactDomain] = useState('health')
  const [marker, setMarker] = useState('')
  // Import only the variants the catalog has an interpretation for.
  const [onlySignificant, setOnlySignificant] = useState(false)
  const [interpretation, setInterpretation] = useState('')
  const [actionNotes, setActionNotes] = useState('')

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['genetics'] })
  }

  // Filter variants
  const filtered = useMemo(() => {
    if (tab === 'all') return view.variants
    if (tab === 'supplements') return view.variants.filter((v) => v.impactDomain === 'supplements')
    if (tab === 'workouts') return view.variants.filter((v) => ['workouts', 'weight', 'glp1'].includes(v.impactDomain ?? ''))
    if (tab === 'health') return view.variants.filter((v) => ['system', 'labs', 'skincare', 'health'].includes(v.impactDomain ?? ''))
    return view.variants
  }, [view.variants, tab])

  // VCF upload
  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setIsUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(`/api/v1/genetics/upload?only_interpreted=${onlySignificant}`, {
        method: 'POST',
        body: fd,
        credentials: 'same-origin',
      })
      if (!res.ok) throw new RequestError(res.status)
      const data = await res.json()
      toast(t('genetics.toast_imported', { imported: data.imported, markers: data.markers }), { icon: 'pulse' })
      refresh()
    } catch (err) {
      toast(failText(err, t('genetics.error_upload')), { icon: 'warn' })
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  // Add manual variant
  const handleAddVariant = async (): Promise<boolean> => {
    if (!gene.trim()) {
      toast(t('genetics.gene_required'), { icon: 'warn' })
      return false
    }
    try {
      await ok(api.POST('/api/v1/genetics/variants', {
        body: {
          gene: gene.trim(),
          rsid: rsid.trim() || null,
          genotype: genotype.trim() || null,
          marker: marker.trim() || null,
          impact: impact.trim() || null,
          impactDomain: impactDomain.trim() || null,
          interpretation: interpretation.trim() || null,
          actionNotes: actionNotes.trim() || null,
        },
      }))
      toast(t('common.saved'))
      setAddModalOpen(false)
      setGene('')
      setRsid('')
      setGenotype('')
      setImpact('')
      setMarker('')
      setInterpretation('')
      setActionNotes('')
      refresh()
      return true
    } catch (err) {
      toast(failText(err, t('genetics.error_save')), { icon: 'warn' })
      return false
    }
  }

  // Delete variant
  const handleDeleteVariant = async (id: number) => {
    try {
      await ok(api.DELETE('/api/v1/genetics/variants/{variant_id}', { params: { path: { variant_id: id } } }))
      toast(t('common.deleted'))
      refresh()
    } catch (err) {
      toast(failText(err, t('genetics.error_delete')), { icon: 'warn' })
    }
  }

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept=".vcf,.txt"
        hidden
        onChange={handleFileChange}
      />

      <TopBar title={t('nav.genetics')} />
      <Mast
        screen="genetics"
        actions={
          <div className="gen-acts">
            <button type="button" className={cx('tgl', onlySignificant && 'on')} aria-pressed={onlySignificant} onClick={() => setOnlySignificant(!onlySignificant)}>
              <i />
              {t('app.genetics.only_significant')}
            </button>
            <TextButton icon="upload" onClick={() => fileInputRef.current?.click()} disabled={isUploading}>
              {isUploading ? t('genetics.uploading') : t('genetics.import_vcf')}
            </TextButton>
            <TextButton icon="plus" onClick={() => setAddModalOpen(true)}>
              {t('common.add')}
            </TextButton>
          </div>
        }
      />

      <Headline title={t('nav.genetics')}>
        <div className="genetics-hero">
          <div className="big">{view.count}</div>
          <div className="side">
            <Badge tone="violet">{t('genetics.interpreted')}</Badge>
            <span className="sub">{t('genetics.profile_summary', { n: view.count })}</span>
          </div>
        </div>
      </Headline>
      {/* On a phone the masthead's actions are hidden: the same actions sit under the title. */}
      {!view.empty && (
        <div className="gen-acts-m">
          <button type="button" className={cx('tgl', onlySignificant && 'on')} aria-pressed={onlySignificant} onClick={() => setOnlySignificant(!onlySignificant)}>
            <i />
            {t('app.genetics.only_significant')}
          </button>
          <TextButton icon="upload" onClick={() => fileInputRef.current?.click()} disabled={isUploading}>
            {isUploading ? t('genetics.uploading') : t('genetics.import_vcf')}
          </TextButton>
          <TextButton icon="plus" onClick={() => setAddModalOpen(true)}>
            {t('common.add')}
          </TextButton>
        </div>
      )}
      <DomainAlerts domain="genetics" />

      {view.empty ? (
        <div className="gen-empty-box">
          <div className="gen-empty-icon">
            <Icon name="dna" />
          </div>
          <div>
            <h3 className="gen-empty-title">{t('genetics.empty_title')}</h3>
            <p className="gen-empty-sub">{t('genetics.empty_sub')}</p>
          </div>
          <div className="gen-empty-acts">
            <button type="button" className={cx('tgl', onlySignificant && 'on')} aria-pressed={onlySignificant} onClick={() => setOnlySignificant(!onlySignificant)}>
              <i />
              {t('app.genetics.only_significant')}
            </button>
            <PrimaryButton onPress={async () => { fileInputRef.current?.click(); return true }}>
              {t('genetics.import_vcf')}
            </PrimaryButton>
            <TextButton onClick={() => setAddModalOpen(true)}>
              {t('genetics.add_variant')}
            </TextButton>
          </div>
        </div>
      ) : (
        <>
          <div className="gen-filter-wrap">
            <FilterRow
              value={tab}
              onChange={setTab}
              options={[
                { id: 'all', label: `${t('genetics.tab_all')} ${view.variants.length}` },
                { id: 'supplements', label: t('genetics.tab_supplements') },
                { id: 'workouts', label: t('genetics.tab_workouts') },
                { id: 'health', label: t('genetics.tab_health') },
              ]}
            />
          </div>

          <div className="rows gen-list">
            {filtered.map((v) => {
              const hasRisk = v.hasRisk || Boolean(v.marker)
              const sourceText = v.source ? tOr(`app.source.${v.source}`, v.source) : ''
              return (
                <div key={v.id} className="row gen-row">
                  <div className="gen-head">
                    <span className="gen-gene">{v.gene}</span>
                    {v.rsid && <span className="gen-rsid">{v.rsid}</span>}
                    <span className="gen-gt">{v.genotype || '—'}</span>
                    <span className="gen-sig">
                      <Dot tone={hasRisk ? 'bad' : 'cool'} />
                      {hasRisk ? t('genetics.conflict_marker') : t('genetics.info_tag')}
                    </span>
                    <button
                      type="button"
                      className="ibtn danger"
                      onClick={() => handleDeleteVariant(v.id)}
                      aria-label={t('common.delete')}
                    >
                      <Icon name="x" />
                    </button>
                  </div>

                  <div className="gen-body">
                    {v.impact && <div className="gen-impact">{v.impact}</div>}
                    {v.interpretation && <div className="gen-interp">{v.interpretation}</div>}
                    {v.actionNotes && (
                      <div className="gen-rec">
                        <b>{t('genetics.recommendation')}:</b> {v.actionNotes}
                      </div>
                    )}
                  </div>

                  {sourceText !== '' && (
                    <div className="gen-meta">
                      <Dot tone="violet" />
                      <span>{sourceText}</span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </>
      )}

      {/* Modal: Add Variant */}
      {addModalOpen && (
        <div className="hrt-form-modal">
          <div className="hrt-form-box">
            <div className="hrt-form-head">
              <h3 className="lab-modal-title">{t('genetics.add_variant')}</h3>
              <button type="button" className="ibtn" onClick={() => setAddModalOpen(false)}>
                <Icon name="x" />
              </button>
            </div>
            <div className="gen-modal-form">
              <label className="field">
                <span className="flabel">{t('genetics.gene_label')}</span>
                <input className="input" placeholder={t('genetics.gene_ph')} value={gene} onChange={(e) => setGene(e.target.value)} />
              </label>
              <div className="gen-modal-grid2">
                <label className="field">
                  <span className="flabel">{t('genetics.rsid_label')}</span>
                  <input className="input" placeholder={t('genetics.rsid_ph')} value={rsid} onChange={(e) => setRsid(e.target.value)} />
                </label>
                <label className="field">
                  <span className="flabel">{t('genetics.genotype')}</span>
                  <input className="input" placeholder={t('genetics.genotype_ph')} value={genotype} onChange={(e) => setGenotype(e.target.value)} />
                </label>
              </div>
              <label className="field">
                <span className="flabel">{t('genetics.impact_domain')}</span>
                <input className="input" list="gen-domains" value={impactDomain} onChange={(e) => setImpactDomain(e.target.value)} />
                <datalist id="gen-domains">
                  {GENE_DOMAINS.map((d) => (
                    <option key={d} value={d} />
                  ))}
                </datalist>
                <span className="gen-hint">{t('app.genetics.domain_hint')}</span>
              </label>
              <label className="field">
                <span className="flabel">{t('app.genetics.marker')}</span>
                <input className="input" placeholder="hemochromatosis_carrier" value={marker} onChange={(e) => setMarker(e.target.value)} />
                <span className="gen-hint">{t('app.genetics.marker_hint')}</span>
              </label>
              <label className="field">
                <span className="flabel">{t('genetics.impact_summary')}</span>
                <input className="input" placeholder={t('genetics.impact_ph')} value={impact} onChange={(e) => setImpact(e.target.value)} />
              </label>
              <label className="field">
                <span className="flabel">{t('genetics.interpretation_label')}</span>
                <textarea className="input" rows={2} placeholder={t('genetics.interpretation_ph')} value={interpretation} onChange={(e) => setInterpretation(e.target.value)} />
              </label>
              <label className="field">
                <span className="flabel">{t('genetics.action_notes_label')}</span>
                <input className="input" placeholder={t('genetics.action_notes_ph')} value={actionNotes} onChange={(e) => setActionNotes(e.target.value)} />
              </label>
              <PrimaryButton className="btn grow" onPress={handleAddVariant}>
                {t('common.save')}
              </PrimaryButton>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
