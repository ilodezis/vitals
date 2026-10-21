import { useMemo, useState } from 'react'
import { Disclosure } from '@/components/controls/Disclosure'
import { Section } from '@/components/controls/Section'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import type { SkincareRuleItem, SkincareView } from './types'

/** The safety rules: the ones firing now in the open, the catalog folded by category. */
export function RulesPane({ view }: { view: SkincareView }) {
  const { t, tOr } = useT()
  const [openCats, setOpenCats] = useState<Set<string>>(() => new Set())

  // A rule that fired raised an alert keyed by its id (`conflict:<id>`) — that is what "firing" is.
  const firing = useMemo(() => {
    const alertKeys = new Set(view.alerts.map((a) => a.alertKey))
    return view.rules.filter((r) => alertKeys.has(`conflict:${r.id}`) || (r.code && alertKeys.has(r.code)))
  }, [view.rules, view.alerts])

  const grouped = useMemo(() => {
    const map = new Map<string, SkincareRuleItem[]>()
    for (const r of view.rules) {
      const cat = r.kind || 'dermatology'
      map.set(cat, [...(map.get(cat) ?? []), r])
    }
    return map
  }, [view.rules])

  const toggle = (cat: string) =>
    setOpenCats((prev) => {
      const next = new Set(prev)
      if (next.has(cat)) next.delete(cat)
      else next.add(cat)
      return next
    })

  return (
    <>
      <Section title={t('app.skincare.safety_rules')} meta={t('app.skincare.safety_sub')}>
        {firing.length > 0 ? (
          <div className="alerts">
            {firing.map((r) => (
              <div key={r.id} className={r.hard ? 'alert block' : 'alert warn'}>
                <Icon name={r.hard ? 'block' : 'warn'} />
                <div>
                  <b>{tOr(`app.rule_cat.${r.kind}`, r.kind)}</b>
                  <br />
                  {r.msg}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="m sk-none">{t('app.skincare.no_firing')}</p>
        )}
        <div className="sk-cats">
          {Array.from(grouped.entries()).map(([cat, rules]) => (
            <Disclosure key={cat} open={openCats.has(cat)} onToggle={() => toggle(cat)} title={tOr(`app.rule_cat.${cat}`, cat)} count={rules.length}>
              <div className="rows">
                {rules.map((r) => (
                  <div key={r.id} className="row sk-rule">
                    <div>
                      <div className="t plain">{r.msg}</div>
                      <div className="m">{r.hard ? t('app.severity.block') : t('app.severity.warn')}</div>
                    </div>
                  </div>
                ))}
              </div>
            </Disclosure>
          ))}
        </div>
      </Section>
      <div className="alert info sk-note">
        <Icon name="drop" />
        <div>
          <b>{t('app.skincare.barrier_note_title')}</b>
          <br />
          {t('app.skincare.barrier_note_body')}
        </div>
      </div>
    </>
  )
}
