import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { Badge } from '@/components/controls/Marks'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import type { ConflictRuleItem } from './types'
import { useInteractionsView } from './useInteractionsView'
import './interactions.css'

const DOM_RU: Record<string, string> = {
  weight: 'Вес',
  glp1: 'GLP-1',
  workouts: 'Тренировки',
  garmin: 'Garmin',
  labs: 'Анализы',
  skincare: 'Кожа',
  supplements: 'Добавки',
  genetics: 'Генетика',
  nutrition: 'Питание',
  body_comp: 'Состав тела',
  hrt: 'ГЗТ',
  health: 'Здоровье',
  system: 'Система',
  timeline: 'Хронология',
  signals: 'Сигналы',
}

const CAT_RU: Record<string, string> = {
  supplements: 'Добавки и лекарства',
  skincare: 'Уход за кожей и активы',
  training: 'Нагрузка и восстановление',
  labs: 'Биомаркеры и риски',
  nutrition: 'Питание и метаболизм',
  lifestyle: 'Сон и привычки',
  general: 'Общие взаимодействия',
}

export default function InteractionsScreen() {
  const { t } = useT()
  const view = useInteractionsView()
  const queryClient = useQueryClient()

  const [domFilter, setDomFilter] = useState('all')
  const [sevFilter, setSevFilter] = useState('all')

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['interactions'] })
  }

  const handleToggle = async (rule: ConflictRuleItem) => {
    try {
      await api.POST('/api/v1/interactions/{rule_id}/toggle', {
        params: { path: { rule_id: rule.id } },
        body: { active: !rule.active },
      })
      toast(rule.active ? 'Правило выключено' : 'Правило включено')
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error toggling rule', { icon: 'warn' })
    }
  }

  const filteredRules = useMemo(() => {
    return view.rules.filter((r) => {
      if (domFilter !== 'all') {
        const da = r.domainA || r.a
        const db = r.domainB || r.b
        if (da !== domFilter && db !== domFilter) return false
      }
      if (sevFilter !== 'all') {
        const s = r.severity || r.sev
        if (s !== sevFilter) return false
      }
      return true
    })
  }, [view.rules, domFilter, sevFilter])

  const groupedByCategory = useMemo(() => {
    const map = new Map<string, ConflictRuleItem[]>()
    for (const r of filteredRules) {
      const cat = r.category || r.cat || 'general'
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

  const renderRule = (r: ConflictRuleItem) => {
    const sev = r.severity || r.sev
    const ruleType = r.ruleType || r.type
    const typeLabel =
      ruleType === 'hard'
        ? 'Жёсткий блок'
        : ruleType === 'timing'
          ? 'Разнесение по времени'
          : 'Мягкое предупреждение'
    const sevTone = sev === 'block' ? 'bad' : sev === 'warn' ? 'warn' : 'cool'
    const da = r.domainA || r.a
    const db = r.domainB || r.b
    const ev = r.evidence || r.ev
    const evTone = ev === 'A' ? 'good' : ev === 'B' ? 'cool' : undefined
    const hours = r.hours ?? r.h

    return (
      <div
        key={r.id}
        className={`row rule ${r.firing ? 'firing' : ''}`}
        data-item
      >
        <div>
          <div className="rl-h">
            <Badge tone={sevTone}>{typeLabel}</Badge>
            {ruleType === 'timing' && hours && (
              <span className="m">разнести на {hours} ч.</span>
            )}
            {r.firing && <Badge tone="bad">Срабатывает сейчас</Badge>}
          </div>
          <p className="rl-m">{r.message || r.msg}</p>
          <div className="rl-t">
            <span className="m">
              {DOM_RU[da] || da} ↔ {DOM_RU[db] || db}
            </span>
            {ev && <Badge tone={evTone}>{`Доказательность ${ev}`}</Badge>}
            {(r.source || r.src) && (
              <span className="m">Источник: {r.source || r.src}</span>
            )}
          </div>
        </div>
        <div className="opts tg">
          <button
            type="button"
            className={`opt ${r.active || r.on ? 'on' : ''}`}
            onClick={() => handleToggle(r)}
          >
            {r.active || r.on ? 'Включено' : 'Выключено'}
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
            <div className="f-l">Правил</div>
          </div>
          <div className="f">
            <div className="f-v bad">{view.firingCount}</div>
            <div className="f-l">Срабатывает сейчас</div>
          </div>
        </div>
      </Headline>

      {/* Domain Filters */}
      <div className="fgroup">
        <div className="flabel">Область</div>
        <div className="filters">
          <button
            type="button"
            className={`filter ${domFilter === 'all' ? 'on' : ''}`}
            onClick={() => setDomFilter('all')}
          >
            Все
          </button>
          {availableDomains.map((d) => (
            <button
              key={d}
              type="button"
              className={`filter ${domFilter === d ? 'on' : ''}`}
              onClick={() => setDomFilter(d)}
            >
              {DOM_RU[d] || d}
            </button>
          ))}
        </div>
      </div>

      {/* Severity Filters */}
      <div className="fgroup">
        <div className="flabel">Важность</div>
        <div className="filters">
          <button
            type="button"
            className={`filter ${sevFilter === 'all' ? 'on' : ''}`}
            onClick={() => setSevFilter('all')}
          >
            Все
          </button>
          <button
            type="button"
            className={`filter ${sevFilter === 'block' ? 'on' : ''}`}
            onClick={() => setSevFilter('block')}
          >
            Блок
          </button>
          <button
            type="button"
            className={`filter ${sevFilter === 'warn' ? 'on' : ''}`}
            onClick={() => setSevFilter('warn')}
          >
            Предупреждение
          </button>
          <button
            type="button"
            className={`filter ${sevFilter === 'info' ? 'on' : ''}`}
            onClick={() => setSevFilter('info')}
          >
            Инфо
          </button>
        </div>
      </div>

      {/* Categories with Rules */}
      {filteredRules.length > 0 ? (
        Array.from(groupedByCategory.entries()).map(([cat, rules]) => (
          <section key={cat} className="sec rgrp">
            <div className="sec-h">
              <h2>{CAT_RU[cat] || cat}</h2>
              <span className="meta num">{rules.length}</span>
            </div>
            <div className="rows">{rules.map(renderRule)}</div>
          </section>
        ))
      ) : (
        <div className="empty mt-6">
          <Icon name="info" />
          <p>Нет правил под этот фильтр.</p>
        </div>
      )}
    </>
  )
}
