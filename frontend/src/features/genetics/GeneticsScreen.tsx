import { useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { FilterRow } from '@/components/controls/Choices'
import { Badge, TextButton } from '@/components/controls/Marks'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { useGeneticsView } from './useGeneticsView'
import './genetics.css'

export default function GeneticsScreen() {
  const { t } = useT()
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
      const res = await fetch('/api/v1/genetics/upload', {
        method: 'POST',
        body: fd,
        credentials: 'same-origin',
      })
      if (!res.ok) throw new Error('Failed to upload VCF')
      const data = await res.json()
      toast(`Imported ${data.imported} variants (${data.markers} conflict markers)`, { icon: 'pulse' })
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error uploading VCF', { icon: 'warn' })
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  // Add manual variant
  const handleAddVariant = async (): Promise<boolean> => {
    if (!gene.trim()) {
      toast('Gene name is required', { icon: 'warn' })
      return false
    }
    try {
      await api.POST('/api/v1/genetics/variants', {
        body: {
          gene: gene.trim(),
          rsid: rsid.trim() || null,
          genotype: genotype.trim() || null,
          impact: impact.trim() || null,
          impactDomain: impactDomain || null,
          interpretation: interpretation.trim() || null,
          actionNotes: actionNotes.trim() || null,
        },
      })
      toast(t('common.saved'))
      setAddModalOpen(false)
      setGene('')
      setRsid('')
      setGenotype('')
      setImpact('')
      setInterpretation('')
      setActionNotes('')
      refresh()
      return true
    } catch (err: any) {
      toast(err.message || 'Error saving variant', { icon: 'warn' })
      return false
    }
  }

  // Delete variant
  const handleDeleteVariant = async (id: number) => {
    try {
      await api.DELETE('/api/v1/genetics/variants/{variant_id}', { params: { path: { variant_id: id } } })
      toast(t('common.deleted'))
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error deleting variant', { icon: 'warn' })
    }
  }

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept=".vcf,.txt"
        style={{ display: 'none' }}
        onChange={handleFileChange}
      />

      <TopBar title={t('nav.genetics')} />
      <Mast
        screen="genetics"
        actions={
          <div className="flex gap-2">
            <TextButton icon="upload" onClick={() => fileInputRef.current?.click()} disabled={isUploading}>
              {isUploading ? 'Uploading...' : t('genetics.import_vcf')}
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

      {view.empty ? (
        <div className="mt-8 p-10 border border-dashed border-[var(--line-2)] rounded-2xl text-center space-y-4">
          <div className="mx-auto w-12 h-12 rounded-full bg-[var(--surface)] flex items-center justify-center text-[var(--violet)]">
            <Icon name="dna" />
          </div>
          <div>
            <h3 className="font-semibold text-lg">{t('genetics.empty_title')}</h3>
            <p className="text-sm text-[var(--muted)] max-w-md mx-auto mt-1">
              {t('genetics.empty_sub')}
            </p>
          </div>
          <div className="flex justify-center gap-3 pt-2">
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
          <div className="mt-6">
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

          <div className="genetics-grid">
            {filtered.map((v) => {
              const hasRisk = v.hasRisk || Boolean(v.marker)
              return (
                <div key={v.id} className={cx('gen-card', hasRisk && 'risk')}>
                  <div className={cx('gen-card-top-bar', hasRisk && 'risk')} />
                  <div className="gen-head">
                    <div className="gen-title-grp">
                      <span className="gen-gene">{v.gene}</span>
                      {v.rsid && <span className="gen-rsid">{v.rsid}</span>}
                      <div>
                        {hasRisk ? (
                          <Badge tone="warn">{t('genetics.conflict_marker')}</Badge>
                        ) : (
                          <Badge tone="plain">{t('genetics.info_tag')}</Badge>
                        )}
                      </div>
                    </div>
                    <div className="gen-gt-box">
                      <span className="text-xs text-[var(--faint)] block mb-1">{t('genetics.genotype')}</span>
                      <span className={cx('gen-gt-badge', hasRisk && 'risk')}>
                        {v.genotype || '—'}
                      </span>
                    </div>
                  </div>

                  <div className="gen-body">
                    {v.impact && <div className="gen-impact">{v.impact}</div>}
                    {v.interpretation && <div className="gen-interp">{v.interpretation}</div>}
                    {v.actionNotes && (
                      <div className="gen-action">
                        <b>Action: </b>
                        {v.actionNotes}
                      </div>
                    )}
                  </div>

                  <div className="gen-card-foot">
                    <span className="text-xs text-[var(--muted)]">{v.source || 'vcf'}</span>
                    <button
                      type="button"
                      className="ibtn danger"
                      onClick={() => handleDeleteVariant(v.id)}
                      aria-label={t('common.delete')}
                    >
                      <Icon name="x" />
                    </button>
                  </div>
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
              <h3 className="font-bold text-lg">{t('genetics.add_variant')}</h3>
              <button type="button" className="ibtn" onClick={() => setAddModalOpen(false)}>
                <Icon name="x" />
              </button>
            </div>
            <div className="space-y-3">
              <label className="field">
                <span className="flabel">Gene *</span>
                <input className="input" placeholder="e.g. MTHFR, HFE, ACTN3" value={gene} onChange={(e) => setGene(e.target.value)} />
              </label>
              <div className="grid grid-cols-2 gap-2">
                <label className="field">
                  <span className="flabel">rsID (Optional)</span>
                  <input className="input" placeholder="e.g. rs1801133" value={rsid} onChange={(e) => setRsid(e.target.value)} />
                </label>
                <label className="field">
                  <span className="flabel">Genotype</span>
                  <input className="input" placeholder="e.g. C/T" value={genotype} onChange={(e) => setGenotype(e.target.value)} />
                </label>
              </div>
              <label className="field">
                <span className="flabel">Impact Domain</span>
                <select className="input" value={impactDomain} onChange={(e) => setImpactDomain(e.target.value)}>
                  <option value="health">Health & Systems</option>
                  <option value="supplements">Supplements</option>
                  <option value="workouts">Workouts & Muscle</option>
                  <option value="metabolism">Metabolism</option>
                </select>
              </label>
              <label className="field">
                <span className="flabel">Impact Summary</span>
                <input className="input" placeholder="e.g. Reduced folate conversion efficiency" value={impact} onChange={(e) => setImpact(e.target.value)} />
              </label>
              <label className="field">
                <span className="flabel">Interpretation</span>
                <textarea className="input" rows={2} placeholder="Clinical or physiological meaning..." value={interpretation} onChange={(e) => setInterpretation(e.target.value)} />
              </label>
              <label className="field">
                <span className="flabel">Action Notes</span>
                <input className="input" placeholder="e.g. Take L-methylfolate instead of folic acid" value={actionNotes} onChange={(e) => setActionNotes(e.target.value)} />
              </label>
              <PrimaryButton className="w mt-4" onPress={handleAddVariant}>
                {t('common.save')}
              </PrimaryButton>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
