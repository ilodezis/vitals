import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { Badge } from '@/components/controls/Marks'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import type { ConflictRuleItem } from './types'
import { useInteractionsView } from './useInteractionsView'
import './interactions.css'

export default function InteractionsScreen() {
  const { t } = useT()
  const view = useInteractionsView()
  const queryClient = useQueryClient()

  const [domFilter, setDomFilter] = useState('all')
  const [sevFilter, setSevFilter] = useState('all')
  const [openCats, setOpenCats] = useState<Record<string, boolean>>({})

  const toggleCat = (cat: string) => {
    setOpenCats((prev) => ({ ...prev, [cat]: !prev[cat] }))
  }

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['interactions'] })
  }

  const handleToggle = async (rule: ConflictRuleItem) => {
    try {
      await api.POST('/api/v1/interactions/{rule_id}/toggle', {
        params: { path: { rule_id: rule.id } },
        body: { active: !rule.active },
      })
      toast(rule.active ? t('app.interactions.rule_disabled') : t('app.interactions.rule_enabled'))
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error toggling rule', { icon: 'warn' })
    }
  }

  const filteredRules = useMemo(() => {
    return view.rules.filter((r) => {
      if (domFilter !== 'all') {
        if (r.domainA !== domFilter && r.domainB !== domFilter) return false
      }
      if (sevFilter !== 'all') {
        if (r.severity !== sevFilter) return false
      }
      return true
    })
  }, [view.rules, domFilter, sevFilter])

  const firingRules = useMemo(() => {
    return view.rules.filter((r) => r.firing)
  }, [view.rules])

  const groupedByCategory = useMemo(() => {
    const map = new Map<string, ConflictRuleItem[]>()
    for (const r of filteredRules) {
      const cat = r.category || 'general'
      if (!map.has(cat)) map.set(cat, [])
      map.get(cat)!.push(r)
    }
    return map
  }, [filteredRules])

  const availableDomains = useMemo(() => {
    return [
      'weight',
      'glp1',
      'workouts',
      'garmin',
      'labs',
      'skincare',
      'supplements',
      'genetics',
      'nutrition',
    ]
  }, [])

  const domainLabel = (d: string) => t(('app.domain.' + d) as any) || d

  const renderRule = (r: ConflictRuleItem) => {
    const sev = r.severity
    const ruleType = r.ruleType
    const typeLabel =
      ruleType === 'hard'
        ? t('app.interactions.type_hard')
        : ruleType === 'timing'
          ? t('app.interactions.type_timing')
          : t('app.interactions.type_soft')
    const sevTone = sev === 'block' ? 'bad' : sev === 'warn' ? 'warn' : 'cool'
    const ev = r.evidence
    const evTone = ev === 'A' ? 'good' : ev === 'B' ? 'cool' : undefined
    const hours = r.hours

    return (
      <div
        key={r.id}
        className={cx('row rule', r.firing && 'firing')}
        data-item
      >
        <div>
          <div className="rl-h">
            <Badge tone={sevTone}>{typeLabel}</Badge>
            {ruleType === 'timing' && hours && (
              <span className="m">{t('app.interactions.separate_hours', { hours })}</span>
            )}
            {r.firing && <Badge tone="bad">{t('app.interactions.firing_now')}</Badge>}
          </div>
          <p className="rl-m">{r.message}</p>
          <div className="rl-t">
            <span className="m">
              {domainLabel(r.domainA)} ↔ {domainLabel(r.domainB)}
            </span>
            {ev && <Badge tone={evTone}>{t('app.interactions.evidence', { ev })}</Badge>}
            {r.source && (
              <span className="m">{t('app.interactions.source', { source: r.source })}</span>
            )}
          </div>
        </div>
        <div className="opts tg">
          <button
            type="button"
            className="toggle-text-btn"
            onClick={() => handleToggle(r)}
            style={{
              background: 'none',
              border: 'none',
              padding: '4px 8px',
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: 'var(--t-label)',
              color: r.active ? 'var(--fg)' : 'var(--muted)',
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: r.active ? 'var(--good)' : 'var(--muted)',
                display: 'inline-block',
              }}
            />
            {r.active ? t('app.on_short') : t('app.off_short')}
          </button>
        </div>
      </div>
    )
  }

  return (
    <>
      <TopBar title={t('nav.interactions')} />
      <Mast screen="interactions" />
      <Headline title={t('nav.interactions')}>
        <div className="figs inline">
          <div className="f">
            <div className="f-v">{view.totalCount || view.rules.length}</div>
            <div className="f-l">{t('app.interactions.rules_count')}</div>
          </div>
          <div className="f">
            <div className={cx('f-v', view.firingCount > 0 && 'bad')}>{view.firingCount}</div>
            <div className="f-l">{t('app.interactions.firing_now')}</div>
          </div>
        </div>
      </Headline>

      {/* Firing Now Section */}
      <Section title={t('app.interactions.firing_now')}>
        <div className="rows">
          {firingRules.length === 0 ? (
            <div className="row"><span className="m">{t('app.interactions.none_firing')}</span></div>
          ) : (
            firingRules.map(renderRule)
          )}
        </div>
      </Section>

      {/* Domain Filters */}
      <div className="fgroup">
        <div className="flabel">{t('app.interactions.filter_domain')}</div>
        <div className="filters">
          <button
            type="button"
            className={cx('filter', domFilter === 'all' && 'on')}
            onClick={() => setDomFilter('all')}
          >
            {t('app.all')}
          </button>
          {availableDomains.map((d) => (
            <button
              key={d}
              type="button"
              className={cx('filter', domFilter === d && 'on')}
              onClick={() => setDomFilter(d)}
            >
              {domainLabel(d)}
            </button>
          ))}
        </div>
      </div>

      {/* Severity Filters */}
      <div className="fgroup">
        <div className="flabel">{t('app.interactions.filter_severity')}</div>
        <div className="filters">
          <button
            type="button"
            className={cx('filter', sevFilter === 'all' && 'on')}
            onClick={() => setSevFilter('all')}
          >
            {t('app.all')}
          </button>
          <button
            type="button"
            className={cx('filter', sevFilter === 'block' && 'on')}
            onClick={() => setSevFilter('block')}
          >
            {t('app.interactions.sev_block')}
          </button>
          <button
            type="button"
            className={cx('filter', sevFilter === 'warn' && 'on')}
            onClick={() => setSevFilter('warn')}
          >
            {t('app.interactions.sev_warn')}
          </button>
          <button
            type="button"
            className={cx('filter', sevFilter === 'info' && 'on')}
            onClick={() => setSevFilter('info')}
          >
            {t('app.interactions.sev_info')}
          </button>
        </div>
      </div>

      {/* Categories with Rules (Collapsible catalog) */}
      {filteredRules.length > 0 ? (
        Array.from(groupedByCategory.entries()).map(([cat, rules]) => {
          const isOpen = Boolean(openCats[cat])
          return (
            <section key={cat} className="sec rgrp">
              <div
                className="sec-h"
                onClick={() => toggleCat(cat)}
                style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
                role="button"
                tabIndex={0}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Icon name={isOpen ? 'chevD' : 'chevR'} />
                  <h2>{t(('app.rule_cat.' + cat) as any) || cat}</h2>
                </div>
                <span className="meta num">{rules.length}</span>
              </div>
              {isOpen && <div className="rows">{rules.map(renderRule)}</div>}
            </section>
          )
        })
      ) : (
        <div className="empty">
          <Icon name="info" />
          <p>{t('app.interactions.no_rules_filtered')}</p>
        </div>
      )}
    </>
  )
}
