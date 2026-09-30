import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { ConflictAlert } from '@/components/controls/ConflictAlert'
import { TextButton } from '@/components/controls/Marks'
import { Meter } from '@/components/controls/Meters'
import { Section } from '@/components/controls/Section'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { toast } from '@/components/controls/toast'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { longDate, parseIsoDate, toIsoDate } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { useConflictMutation } from '@/lib/useConflictMutation'
import type { components } from '@/api/schema'
import './nutrition.css'

type NutritionView = components['schemas']['NutritionView']

export default function NutritionScreen() {
  const { t, lang } = useT()
  const queryClient = useQueryClient()
  const todayStr = toIsoDate(new Date())

  const [selectedDate, setSelectedDate] = useState<string>(todayStr)
  const [formOpen, setFormOpen] = useState(false)
  const [editingMealId, setEditingMealId] = useState<number | null>(null)

  // Meal Form fields
  const [mealDate, setMealDate] = useState(todayStr)
  const [mealTime, setMealTime] = useState('13:00')
  const [mealName, setMealName] = useState('')
  const [mealCal, setMealCal] = useState('')
  const [mealP, setMealP] = useState('')
  const [mealF, setMealF] = useState('')
  const [mealC, setMealC] = useState('')
  const [mealNote, setMealNote] = useState('')

  const { data: view, isLoading } = useQuery({
    queryKey: ['nutrition', selectedDate],
    queryFn: async (): Promise<NutritionView> => {
      const res = await api.GET('/api/v1/nutrition', {
        params: { query: { date: selectedDate } },
      })
      if (!res.data) throw new Error('Nutrition data unavailable')
      return res.data
    },
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
        await api.PATCH('/api/v1/nutrition/meals/{meal_id}', {
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
        })
      } else {
        await api.POST('/api/v1/nutrition/meals', {
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
        })
      }
    },
    onSuccess: () => {
      invalidateNutrition()
      toast(editingMealId ? 'Приём обновлён' : 'Приём пищи записан')
      setFormOpen(false)
      setEditingMealId(null)
      setMealName('')
      setMealCal('')
      setMealP('')
      setMealF('')
      setMealC('')
      setMealNote('')
    },
    onError: (err) => toast(err.message),
  })

  // Delete Meal Mutation
  const deleteMealMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.DELETE('/api/v1/nutrition/meals/{meal_id}', {
        params: { path: { meal_id: id } },
      })
    },
    onSuccess: () => {
      invalidateNutrition()
      toast(t('app.saved'))
    },
    onError: (err) => toast(err.message),
  })

  const openEdit = (m: components['schemas']['MealItem']) => {
    setEditingMealId(m.id)
    setMealDate(m.date)
    setMealTime(m.time || '13:00')
    setMealName(m.name)
    setMealCal(m.calories != null ? String(m.calories) : '')
    setMealP(m.protein_g != null ? String(m.protein_g) : '')
    setMealF(m.fat_g != null ? String(m.fat_g) : '')
    setMealC(m.carbs_g != null ? String(m.carbs_g) : '')
    setMealNote(m.note || '')
    setFormOpen(true)
  }

  const totals = view?.totals
  const goals = view?.goals
  const cal = totals?.calories ?? 0
  const prot = totals?.protein_g ?? 0
  const fat = totals?.fat_g ?? 0
  const carbs = totals?.carbs_g ?? 0

  const calMax = goals?.calories_max ?? 2000
  const protTarget = goals?.protein_target_g ?? 150
  const calTone = cal > calMax ? 'bad' : cal < (goals?.calories_min ?? 1800) ? 'warn' : undefined
  const protTone = prot >= protTarget ? undefined : 'warn'

  const macroSplit = view?.macro_split ?? { protein_pct: 0, fat_pct: 0, carbs_pct: 0 }
  const meals = view?.meals ?? []
  const recentDays = view?.recent_days ?? []

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
              setMealName('')
              setMealCal('')
              setMealP('')
              setMealF('')
              setMealC('')
              setMealNote('')
              setFormOpen(true)
            }}
          >
            Добавить приём
          </TextButton>
        }
      />
      <Headline title={t('nav.nutrition')}>
        <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 'var(--t-title)', fontWeight: 600 }}>
              {formatNumber(cal, lang, 0)} <span className="unit">ккал</span>
            </div>
            <div className="sub">
              из {formatNumber(goals?.calories_min ?? 1800, lang, 0)}–{formatNumber(calMax, lang, 0)}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 'var(--t-title)', fontWeight: 600 }}>{meals.length}</div>
            <div className="sub">Приёмы пищи</div>
          </div>
        </div>
      </Headline>

      {/* Meal Form Panel */}
      {formOpen && (
        <Section title={editingMealId ? 'Редактировать приём' : 'Новый приём пищи'}>
          <div className="panel" style={{ padding: '16px' }}>
            <form onSubmit={(e) => { e.preventDefault(); saveMealMutation.mutate() }}>
              <div className="g2">
                <div className="fld">
                  <label>Дата</label>
                  <input
                    type="date"
                    className="input"
                    value={mealDate}
                    onChange={(e) => setMealDate(e.target.value)}
                    required
                  />
                </div>
                <div className="fld">
                  <label>Время приёма</label>
                  <input
                    type="time"
                    className="input"
                    value={mealTime}
                    onChange={(e) => setMealTime(e.target.value)}
                  />
                </div>
              </div>

              <div className="fld">
                <label>Название блюда / приёма</label>
                <input
                  type="text"
                  placeholder="2 яйца, тост, кофе..."
                  className="input"
                  value={mealName}
                  onChange={(e) => setMealName(e.target.value)}
                  required
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px' }}>
                <div className="fld">
                  <label>Калории</label>
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
                  <label>Белок (г)</label>
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
                  <label>Жиры (г)</label>
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
                  <label>Углеводы (г)</label>
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
                <label>Заметка (необязательно)</label>
                <input
                  type="text"
                  placeholder="Ощущения, детали..."
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
                  {editingMealId ? 'Сохранить изменения' : 'Записать приём'}
                </button>
                <button type="button" className="ghost" onClick={() => setFormOpen(false)}>
                  Отмена
                </button>
              </div>
            </form>
          </div>
        </Section>
      )}

      {/* KBJU Section */}
      <Section
        title="КБЖУ"
        meta={
          <div className="dnav">
            <button
              type="button"
              className="ibtn"
              onClick={() => {
                if (view?.prev_date) setSelectedDate(view.prev_date)
              }}
              aria-label="Предыдущий день"
            >
              <Icon name="chevL" />
            </button>
            <span className="dl">
              {selectedDate === todayStr ? 'Сегодня' : longDate(parseIsoDate(selectedDate), lang)}
            </span>
            <button
              type="button"
              className="ibtn"
              disabled={selectedDate === todayStr}
              onClick={() => {
                if (view?.next_date) setSelectedDate(view.next_date)
              }}
              aria-label="Следующий день"
            >
              <Icon name="chevR" />
            </button>
            {selectedDate !== todayStr && (
              <button
                type="button"
                className="ibtn"
                onClick={() => setSelectedDate(todayStr)}
                style={{ fontSize: 'var(--t-micro)', color: 'var(--violet)' }}
              >
                Сегодня
              </button>
            )}
          </div>
        }
      >
        <div className="intake">
          <div className="mrows">
            <div className="mrow">
              <div className="mrow-h">
                <span className="t">Калории</span>
                <span className="m num">
                  <b>{formatNumber(cal, lang, 0)}</b> / {formatNumber(goals?.calories_min ?? 1800, lang, 0)}–{formatNumber(calMax, lang, 0)} ккал
                </span>
              </div>
              <Meter value={(cal / calMax) * 100} tone={calTone} />
            </div>

            <div className="mrow">
              <div className="mrow-h">
                <span className="t">Белок</span>
                <span className="m num">
                  <b>{formatNumber(prot, lang, 1)}</b> / {formatNumber(protTarget, lang, 0)} г
                </span>
              </div>
              <Meter value={(prot / protTarget) * 100} tone={protTone} />
            </div>
          </div>

          <div className="mrow">
            <div className="mrow-h">
              <span className="t">Макросы</span>
              <span className="m">% от калорий</span>
            </div>
            <div className="compo">
              <i style={{ flex: macroSplit.protein_pct, background: 'var(--good)' }} />
              <i style={{ flex: macroSplit.fat_pct, background: 'var(--violet)' }} />
              <i style={{ flex: macroSplit.carbs_pct, background: 'var(--cool)' }} />
            </div>
            <div className="hyp-legend" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
              <div>
                <i style={{ background: 'var(--good)' }} />
                Белок
                <b>{formatNumber(prot, lang, 1)} г <em>({Math.round(macroSplit.protein_pct)} %)</em></b>
              </div>
              <div>
                <i style={{ background: 'var(--violet)' }} />
                Жиры
                <b>{formatNumber(fat, lang, 1)} г <em>({Math.round(macroSplit.fat_pct)} %)</em></b>
              </div>
              <div>
                <i style={{ background: 'var(--cool)' }} />
                Углеводы
                <b>{formatNumber(carbs, lang, 1)} г <em>({Math.round(macroSplit.carbs_pct)} %)</em></b>
              </div>
            </div>
          </div>
        </div>
      </Section>

      <div className="grid">
        {/* Left Column: Meals List */}
        <div className="c7">
          <Section
            title={selectedDate === todayStr ? 'Приёмы за сегодня' : 'Приёмы'}
            meta={`${meals.length} приёма`}
          >
            <div className="rows">
              {isLoading && <div className="row"><span className="m">Загрузка...</span></div>}
              {!isLoading && meals.length === 0 && (
                <div className="row"><span className="m">В этот день приёмов нет.</span></div>
              )}
              {meals.map((m) => (
                <div key={m.id} className="row r-meal">
                  <span className="m num tm">{m.time || '—'}</span>
                  <div>
                    <div className="t">{m.name}</div>
                    <div className="m hd num">
                      Б {m.protein_g ?? 0} · Ж {m.fat_g ?? 0} · У {m.carbs_g ?? 0}
                    </div>
                  </div>
                  <div className="v">
                    {formatNumber(m.calories ?? 0, lang, 0)}
                    <span className="u">ккал</span>
                  </div>
                  <div className="acts">
                    <button
                      type="button"
                      className="ibtn"
                      onClick={() => openEdit(m)}
                      aria-label="Редактировать"
                    >
                      <Icon name="edit" />
                    </button>
                    <button
                      type="button"
                      className="ibtn danger"
                      onClick={() => deleteMealMutation.mutate(m.id)}
                      aria-label="Удалить"
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
          <Section title="Последние 30 дней">
            <div className="rows">
              {recentDays.map((d) => {
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
                      <div className="m num">{d.meal_count} приёмов · {d.protein_g} г белка</div>
                    </div>
                    <div className="v num">
                      {formatNumber(d.calories, lang, 0)}
                      <span className="u">ккал</span>
                    </div>
                  </button>
                )
              })}
            </div>
          </Section>
        </div>
      </div>
    </>
  )
}
