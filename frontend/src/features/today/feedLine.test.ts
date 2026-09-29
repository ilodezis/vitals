import { describe, expect, it } from 'vitest'
import { translate } from '@/i18n/translate'
import type { FeedRow } from './types'
import { feedLine } from './feedLine'

const dictionary = {
  'today.src_meal': '{value} ккал',
  'nav.nutrition': 'Питание',
  'today.src_bot': 'из бота',
  'today.brief_sent': 'Утренний бриф отправлен',
  'today.src_proactive': 'проактивный слой',
  'app.feed.weight': 'Вес {value} кг',
  'app.source.manual': 'вручную',
}
const t = (key: string, params?: Record<string, string | number>) => translate(dictionary, key, params)

const row = (over: Partial<FeedRow>): FeedRow => ({ time: '', kind: 'event', dot: 'cool', text: '', detail: '', value: null, ...over })

describe('feedLine', () => {
  it('leaves the owner’s own words as they are', () => {
    expect(feedLine(row({ kind: 'event', text: 'Сауна', detail: '20 минут' }), t, 'ru')).toEqual({ text: 'Сауна', detail: '20 минут' })
  })

  it('names a meal with its calories', () => {
    expect(feedLine(row({ kind: 'meal', text: 'Овсянка', value: 2150 }), t, 'ru')).toEqual({ text: 'Овсянка', detail: '2 150 ккал' })
  })

  it('falls back to the section for a meal without calories', () => {
    expect(feedLine(row({ kind: 'meal', text: 'Кофе', value: null }), t, 'ru')).toEqual({ text: 'Кофе', detail: 'Питание' })
  })

  it('says where a signal came from', () => {
    expect(feedLine(row({ kind: 'signal', text: 'кофе в 22' }), t, 'ru')).toEqual({ text: 'кофе в 22', detail: 'из бота' })
  })

  it('writes the brief’s line itself', () => {
    expect(feedLine(row({ kind: 'brief' }), t, 'ru')).toEqual({ text: 'Утренний бриф отправлен', detail: 'проактивный слой' })
  })

  it('writes a weigh-in from its number, in the reader’s decimal mark', () => {
    expect(feedLine(row({ kind: 'weight', value: 86.1 }), t, 'ru')).toEqual({ text: 'Вес 86,1 кг', detail: 'вручную' })
  })
})
