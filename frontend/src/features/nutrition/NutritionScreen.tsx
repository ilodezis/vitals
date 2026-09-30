import { useDeferredValue, useRef, useState } from 'react'
import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { api, failText, ok } from '@/api/client'
import { useTodayIso } from '@/app/session'
import { ConflictAlert } from '@/components/controls/ConflictAlert'
import { TextButton } from '@/components/controls/Marks'
import { Meter } from '@/components/controls/Meters'
import { Section } from '@/components/controls/Section'
import { Icon } from '@/components/icons/Icon'
import { DomainAlerts } from '@/components/controls/DomainAlerts'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { toast } from '@/components/controls/toast'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { clockLabel, longDate, parseIsoDate } from '@/lib/dates'
import { formatInt, formatNumber, formatPercent } from '@/lib/format'
import { useConflictMutation } from '@/lib/useConflictMutation'
import { mealsLabel } from './mealsLabel'
import type { components } from '@/api/schema'
import './nutrition.css'

type NutritionView = components['schemas']['NutritionView']

export default function NutritionScreen() {
  const { t, lang, plural } = useT()
  const queryClient = useQueryClient()
  const todayStr = useTodayIso()

  const [selectedDate, setSelectedDate] = useState<string>(todayStr)
  const pickerRef = useRef<HTMLInputElement>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [editingMealId, setEditingMealId] = useState<number | null>(null)

  // Meal Form fields
  const [mealDate, setMealDate] = useState(todayStr)
  const [mealTime, setMealTime] = useState('')
  const [mealName, setMealName] = useState('')
  const [mealCal, setMealCal] = useState('')
  const [mealP, setMealP] = useState('')
  const [mealF, setMealF] = useState('')
  const [mealC, setMealC] = useState('')
  const [mealNote, setMealNote] = useState('')

  // The day being read follows the selected one a beat later, so paging through days keeps the
  // previous one on screen instead of blanking it; a failed read goes to the screen's boundary.
  const shownDate = useDeferredValue(selectedDate)
  const { data: view } = useSuspenseQuery({
    queryKey: ['nutrition', shownDate],
    queryFn: async (): Promise<NutritionView> => ok(api.GET('/api/v1/nutrition', { params: { query: { date: shownDate } } })),
  })

  const invalidateNutrition = () => {
    void queryClient.invalidateQueries({ queryKey: ['nutrition'] })
    void queryClient.invalidateQueries({ queryKey: ['today'] })
  }

  // Create or Update Meal Mutation
  const saveMealMutation = useConflictMutation({
    mutationFn: async ({ override }) => {
      const cal = mealCal ? parseFloat(mealCal) : undefined
      const prot = mealP ? parseFloat(mealP) : undefined
      const fat = mealF ? parseFloat(mealF) : undefined
      const carbs = mealC ? parseFloat(mealC) : undefined

      if (editingMealId) {
        await ok(api.PATCH('/api/v1/nutrition/meals/{meal_id}', {
          params: { path: { meal_id: editingMealId } },
          body: {
            date: mealDate,
            time: mealTime || undefined,
            name: mealName.trim(),
            calories: cal,
            protein_g: prot,
            fat_g: fat,
            carbs_g: carbs,
            note: mealNote.trim() || undefined,
            override,
          },
        }))
      } else {
        await ok(api.POST('/api/v1/nutrition/meals', {
          body: {
            date: mealDate,
            time: mealTime || undefined,
            name: mealName.trim(),
            calories: cal,
            protein_g: prot,
            fat_g: fat,
            carbs_g: carbs,
            note: mealNote.trim() || undefined,
            override,
          },
        }))
      }
    },
    onSuccess: () => {
      invalidateNutrition()
      toast(editingMealId ? t('app.nutrition.meal_updated') : t('app.nutrition.meal_logged'))
      setFormOpen(false)
      setEditingMealId(null)
      setMealName('')
      setMealCal('')
      setMealP('')
      setMealF('')
      setMealC('')
      setMealNote('')
    },
    fallbackErrorMessage: t('app.save_failed'),
    onError: (err) => toast(failText(err, t('app.save_failed')), { icon: 'warn' }),
  })

  // Delete Meal Mutation
  const deleteMealMutation = useMutation({
    mutationFn: async (id: number) => {
      await ok(api.DELETE('/api/v1/nutrition/meals/{meal_id}', {
        params: { path: { meal_id: id } },
      }))
    },
    onSuccess: () => {
      invalidateNutrition()
      toast(t('app.saved'))
    },
    onError: (err) => toast(failText(err, t('app.delete_failed')), { icon: 'warn' }),
  })

  const openEdit = (m: components['schemas']['MealItem']) => {
    setEditingMealId(m.id)
    setMealDate(m.date)
    setMealTime(m.time ?? '')
    setMealName(m.name)
    setMealCal(m.calories != null ? String(m.calories) : '')
    setMealP(m.protein_g != null ? String(m.protein_g) : '')
    setMealF(m.fat_g != null ? String(m.fat_g) : '')
    setMealC(m.carbs_g != null ? String(m.carbs_g) : '')
    setMealNote(m.note || '')
    setFormOpen(true)
  }

  const { totals, goals } = view
  const cal = totals.calories
  const prot = totals.protein_g
  const fat = totals.fat_g
  const carbs = totals.carbs_g

  const calMin = goals.calories_min
  const calMax = goals.calories_max
  const protTarget = goals.protein_target_g
  const calTone = cal > calMax ? 'bad' : cal < calMin ? 'warn' : undefined
  const protTone = prot >= protTarget ? undefined : 'warn'

  const macroSplit = view.macro_split
  const meals = view.meals
  const recentDays = view.recent_days
  /** A figure the meal has no value for is a dash, not a zero. */
  const gramsOf = (v: number | null | undefined): string => (v == null ? '—' : formatNumber(v, lang, 1))

  // Active days for history (only days with data, newest first)
  const activeDays = recentDays.filter((d) => (d.meal_count && d.meal_count > 0) || (d.calories && d.calories > 0))
  const activeDaysDesc = [...activeDays].reverse()

  // 30-day mini bars data (chronological: newest on right)
  const chartHeight = 44
  const maxDayCal = Math.max(calMax * 1.15, ...recentDays.map((d) => d.calories || 0), 100)
  const yCorridorTop = chartHeight - (calMax / maxDayCal) * chartHeight
  const yCorridorBottom = chartHeight - (calMin / maxDayCal) * chartHeight
  const corridorHeight = Math.max(2, yCorridorBottom - yCorridorTop)

  return (
    <>
      <TopBar title={t('nav.nutrition')} />
      <Mast
        screen="nutrition"
        actions={
          <TextButton
            icon="plus"
            onClick={() => {
              setEditingMealId(null)
              setMealDate(selectedDate)
              setMealTime(clockLabel(new Date()))
              setMealName('')
              setMealCal('')
              setMealP('')
              setMealF('')
              setMealC('')
              setMealNote('')
              setFormOpen(true)
            }}
          >
            {t('app.nutrition.add_meal')}
          </TextButton>
        }
      />
      <Headline title={t('nav.nutrition')}>
        <div className="nutr-hero">
          <div>
            <div className="nutr-hero-v">
              {formatNumber(cal, lang, 0)} <span className="unit">{t('app.unit.kcal')}</span>
            </div>
            <div className="sub">
              {t('app.nutrition.from_range', {
                min: formatNumber(calMin, lang, 0),
                max: formatNumber(calMax, lang, 0),
              })}
            </div>
          </div>
          <div>
            <div className="nutr-hero-v">{meals.length}</div>
            <div className="sub">{t('app.nutrition.meals')}</div>
          </div>
        </div>
      </Headline>
      <DomainAlerts domain="nutrition" />

      {/* Meal Form Panel */}
      {formOpen && (
        <Section title={editingMealId ? t('app.nutrition.edit_meal') : t('app.nutrition.new_meal')}>
          <div className="panel nutr-form-panel">
            <form onSubmit={(e) => { e.preventDefault(); saveMealMutation.mutate() }}>
              <div className="g2">
                <div className="fld">
                  <label>{t('app.nutrition.date_label')}</label>
                  <input
                    type="date"
                    className="input"
                    value={mealDate}
                    onChange={(e) => setMealDate(e.target.value)}
                    required
                  />
                </div>
                <div className="fld">
                  <label>{t('app.nutrition.time_label')}</label>
                  <input
                    type="time"
                    className="input"
                    value={mealTime}
                    onChange={(e) => setMealTime(e.target.value)}
                  />
                </div>
              </div>

              <div className="fld">
                <label>{t('app.nutrition.dish_name')}</label>
                <input
                  type="text"
                  placeholder={t('app.nutrition.dish_ph')}
                  className="input"
                  value={mealName}
                  onChange={(e) => setMealName(e.target.value)}
                  required
                />
              </div>

              <div className="nutr-macro-grid">
                <div className="fld">
                  <label>{t('app.nutrition.calories')}</label>
                  <input
                    type="number"
                    step="1"
                    placeholder="0"
                    className="input"
                    value={mealCal}
                    onChange={(e) => setMealCal(e.target.value)}
                  />
                </div>
                <div className="fld">
                  <label>{t('app.nutrition.protein_g')}</label>
                  <input
                    type="number"
                    step="0.1"
                    placeholder="0"
                    className="input"
                    value={mealP}
                    onChange={(e) => setMealP(e.target.value)}
                  />
                </div>
                <div className="fld">
                  <label>{t('app.nutrition.fat_g')}</label>
                  <input
                    type="number"
                    step="0.1"
                    placeholder="0"
                    className="input"
                    value={mealF}
                    onChange={(e) => setMealF(e.target.value)}
                  />
                </div>
                <div className="fld">
                  <label>{t('app.nutrition.carbs_g')}</label>
                  <input
                    type="number"
                    step="0.1"
                    placeholder="0"
                    className="input"
                    value={mealC}
                    onChange={(e) => setMealC(e.target.value)}
                  />
                </div>
              </div>

              <div className="fld">
                <label>{t('app.nutrition.note_optional')}</label>
                <input
                  type="text"
                  placeholder={t('app.nutrition.note_ph')}
                  className="input"
                  value={mealNote}
                  onChange={(e) => setMealNote(e.target.value)}
                />
              </div>

              <ConflictAlert
                violations={saveMealMutation.violations}
                onFix={() => saveMealMutation.clearConflict()}
                onSaveAnyway={() => void saveMealMutation.retryWithOverride()}
              />
              <div className="form-acts">
                <button type="submit" className="btn grow" disabled={saveMealMutation.isPending}>
                  {editingMealId ? t('app.nutrition.save_changes') : t('app.nutrition.log_meal')}
                </button>
                <button type="button" className="ghost" onClick={() => setFormOpen(false)}>
                  {t('common.cancel')}
                </button>
              </div>
            </form>
          </div>
        </Section>
      )}

      {/* KBJU Section */}
      <Section
        title={t('app.nutrition.kbju')}
        meta={
          <div className="dnav">
            <button
              type="button"
              className="ibtn"
              onClick={() => {
                setSelectedDate(view.prev_date)
              }}
              aria-label={t('app.nutrition.prev_day')}
            >
              <Icon name="chevL" />
            </button>
            {/* The date itself opens a calendar: any day, not only the neighbours and the last 30. */}
            <span className="dl dpick">
              <button type="button" className="dpick-b" aria-label={t('app.nutrition.pick_date')} title={t('app.nutrition.pick_date')} onClick={() => pickerRef.current?.showPicker?.()}>
                {selectedDate === todayStr ? t('app.nutrition.today') : longDate(parseIsoDate(selectedDate), lang)}
              </button>
              <input
                ref={pickerRef}
                type="date"
                className="dpick-i"
                tabIndex={-1}
                aria-hidden="true"
                max={todayStr}
                value={selectedDate}
                onChange={(e) => {
                  const next = e.target.value
                  if (next !== '' && next <= todayStr) setSelectedDate(next)
                }}
              />
            </span>
            <button
              type="button"
              className="ibtn"
              disabled={selectedDate === todayStr}
              onClick={() => {
                setSelectedDate(view.next_date)
              }}
              aria-label={t('app.nutrition.next_day')}
            >
              <Icon name="chevR" />
            </button>
            {selectedDate !== todayStr && (
              <button
                type="button"
                className="ibtn nutr-today-btn"
                onClick={() => setSelectedDate(todayStr)}
              >
                {t('app.nutrition.today')}
              </button>
            )}
          </div>
        }
      >
        <div className="intake">
          <div className="mrows">
            <div className="mrow">
              <div className="mrow-h">
                <span className="t">{t('app.nutrition.calories')}</span>
                <span className="m num">
                  <b>{formatNumber(cal, lang, 0)}</b> / {formatNumber(calMin, lang, 0)}–{formatNumber(calMax, lang, 0)} {t('app.unit.kcal')}
                </span>
              </div>
              <Meter value={(cal / calMax) * 100} tone={calTone} />
            </div>

            <div className="mrow">
              <div className="mrow-h">
                <span className="t">{t('app.nutrition.protein')}</span>
                <span className="m num">
                  <b>{formatNumber(prot, lang, 1)}</b> / {formatNumber(protTarget, lang, 0)} {t('app.unit.g')}
                </span>
              </div>
              <Meter value={(prot / protTarget) * 100} tone={protTone} />
            </div>
          </div>

          <div className="mrow">
            <div className="mrow-h">
              <span className="t">{t('app.nutrition.macros')}</span>
              <span className="m">{t('app.nutrition.pct_calories')}</span>
            </div>
            <div className="compo">
              <i className="good" style={{ flex: macroSplit.protein_pct || 1 }} />
              <i className="violet" style={{ flex: macroSplit.fat_pct || 1 }} />
              <i className="cool" style={{ flex: macroSplit.carbs_pct || 1 }} />
            </div>
            <div className="hyp-legend three">
              <div>
                <i className="good" />
                {t('app.nutrition.protein')}
                <b>{formatNumber(prot, lang, 1)} {t('app.unit.g')} <em>({formatPercent(macroSplit.protein_pct, lang)})</em></b>
              </div>
              <div>
                <i className="violet" />
                {t('app.nutrition.fat')}
                <b>{formatNumber(fat, lang, 1)} {t('app.unit.g')} <em>({formatPercent(macroSplit.fat_pct, lang)})</em></b>
              </div>
              <div>
                <i className="cool" />
                {t('app.nutrition.carbs')}
                <b>{formatNumber(carbs, lang, 1)} {t('app.unit.g')} <em>({formatPercent(macroSplit.carbs_pct, lang)})</em></b>
              </div>
            </div>
          </div>
        </div>
      </Section>

      <div className="grid">
        {/* Left Column: Meals List */}
        <div className="c7">
          <Section
            title={selectedDate === todayStr ? t('app.nutrition.today_meals') : t('app.nutrition.meals')}
            meta={mealsLabel(meals.length, t, plural)}
          >
            <div className="rows">
              {meals.length === 0 && (
                <div className="row"><span className="m">{t('app.nutrition.no_meals_day')}</span></div>
              )}
              {meals.map((m) => (
                <div key={m.id} className="row r-meal">
                  <span className="m num tm">{m.time || '—'}</span>
                  <div>
                    <div className="t">{m.name}</div>
                    <div className="m hd num">
                      {t('app.nutrition.macro_short_p')} {gramsOf(m.protein_g)} · {t('app.nutrition.macro_short_f')} {gramsOf(m.fat_g)} · {t('app.nutrition.macro_short_c')} {gramsOf(m.carbs_g)}
                    </div>
                  </div>
                  <div className="v">
                    {m.calories == null ? '—' : t('app.unit.kcal_value', { value: formatInt(m.calories, lang) })}
                  </div>
                  <div className="acts">
                    <button
                      type="button"
                      className="ibtn"
                      onClick={() => openEdit(m)}
                      aria-label={t('common.edit')}
                    >
                      <Icon name="edit" />
                    </button>
                    <button
                      type="button"
                      className="ibtn danger"
                      onClick={() => deleteMealMutation.mutate(m.id)}
                      aria-label={t('common.delete')}
                    >
                      <Icon name="trash" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </Section>
        </div>

        {/* Right Column: 30-day History Mini */}
        <div className="c5">
          <Section title={t('app.nutrition.last_30_days')}>
            {recentDays.length > 0 && (
              <div className="nutr-bars-wrap">
                <div className="nutr-bars-head">
                  <span>{t('app.nutrition.goal_corridor')}</span>
                  <span className="num">{formatNumber(calMin, lang, 0)}–{formatNumber(calMax, lang, 0)} {t('app.unit.kcal')}</span>
                </div>
                <svg className="nutr-bars" viewBox={`0 0 ${recentDays.length * 10} ${chartHeight}`} preserveAspectRatio="none">
                  {/* Goal corridor band */}
                  <rect
                    x="0"
                    y={yCorridorTop}
                    width={recentDays.length * 10}
                    height={corridorHeight}
                    fill="var(--good)"
                    opacity="0.12"
                    rx="1"
                  />
                  {/* Daily bars */}
                  {recentDays.map((d, i) => {
                    const c = d.calories || 0
                    const barH = c > 0 ? Math.max(3, (c / maxDayCal) * chartHeight) : 1
                    const barY = chartHeight - barH
                    const isSel = d.date === selectedDate
                    const toneColor = c > calMax
                      ? 'var(--bad)'
                      : c >= calMin
                        ? 'var(--good)'
                        : c > 0
                          ? 'var(--warn)'
                          : 'var(--line)'
                    return (
                      <g key={d.date} className="nutr-bar" onClick={() => setSelectedDate(d.date)}>
                        <rect
                          x={i * 10 + 1.5}
                          y={barY}
                          width={7}
                          height={barH}
                          rx={1.5}
                          fill={toneColor}
                          opacity={isSel ? 1 : 0.75}
                        />
                        {isSel && (
                          <circle
                            cx={i * 10 + 5}
                            cy={chartHeight - 1}
                            r={1.5}
                            fill="var(--violet)"
                          />
                        )}
                      </g>
                    )
                  })}
                </svg>
              </div>
            )}
            <div className="rows">
              {activeDaysDesc.length === 0 ? (
                <div className="row"><span className="m">{t('app.nutrition.no_history_meals')}</span></div>
              ) : (
                activeDaysDesc.map((d) => {
                  const isSel = d.date === selectedDate
                  return (
                    <button
                      key={d.date}
                      type="button"
                      className={cx('r-day', isSel && 'sel')}
                      onClick={() => setSelectedDate(d.date)}
                    >
                      <div>
                        <div className="t num">{longDate(parseIsoDate(d.date), lang)}</div>
                        <div className="m num">
                          {t('app.nutrition.day_summary', {
                            meals: mealsLabel(d.meal_count, t, plural),
                            protein: formatNumber(d.protein_g, lang, 1),
                          })}
                        </div>
                      </div>
                      <div className="v num">
                        {t('app.unit.kcal_value', { value: formatInt(d.calories, lang) })}
                      </div>
                    </button>
                  )
                })
              )}
            </div>
          </Section>
        </div>
      </div>
    </>
  )
}
