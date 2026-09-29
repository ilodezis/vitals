import { describe, expect, it } from 'vitest'
import { backTarget, initialStack, planGo, planPop, planPopToRoot, topOf } from './stack'

const ids = (s: { entries: { id: string }[] }) => s.entries.map((e) => e.id)

describe('screen stack', () => {
  it('starts with one screen and nowhere to go back to', () => {
    const s = initialStack('today')
    expect(ids(s)).toEqual(['today'])
    expect(backTarget(s)).toBeNull()
  })

  it('does nothing when asked for the screen already on top', () => {
    const plan = planGo(initialStack('today'), 'today', { mode: 'push', desktop: false })
    expect(plan.motion).toBe('none')
    expect(plan.from).toBeNull()
  })

  it('push slides a new screen over the current one and remembers where "back" goes', () => {
    const plan = planGo(initialStack('today'), 'weight', { mode: 'push', desktop: false })
    expect(plan.motion).toBe('push')
    expect(ids(plan.state)).toEqual(['today', 'weight'])
    expect(plan.drop).toEqual([])
    expect(backTarget(plan.state)).toBe('today')
    expect(topOf(plan.state).id).toBe('weight')
  })

  it('a tab starts the stack over with a cross-fade and drops what was there', () => {
    const deep = planGo(initialStack('today'), 'weight', { mode: 'push', desktop: false }).state
    const plan = planGo(deep, 'glp1', { mode: 'tab', desktop: false })
    expect(plan.motion).toBe('fade')
    expect(ids(plan.state)).toEqual(['glp1'])
    expect(plan.drop.map((e) => e.id)).toEqual(['today', 'weight'])
  })

  it('a section tab replaces the top screen and keeps what is below it', () => {
    const deep = planGo(initialStack('today'), 'weight', { mode: 'push', desktop: false }).state
    const plan = planGo(deep, 'recovery', { mode: 'replace', desktop: false })
    expect(plan.motion).toBe('fade')
    expect(ids(plan.state)).toEqual(['today', 'recovery'])
    expect(plan.drop.map((e) => e.id)).toEqual(['weight'])
    expect(backTarget(plan.state)).toBe('today')
  })

  it('going to a screen already under the top pops back to it instead of stacking a copy', () => {
    let s = initialStack('today')
    s = planGo(s, 'weight', { mode: 'push', desktop: false }).state
    s = planGo(s, 'measures', { mode: 'push', desktop: false }).state
    const plan = planGo(s, 'today', { mode: 'push', desktop: false })
    expect(plan.motion).toBe('pop')
    expect(ids(plan.state)).toEqual(['today'])
    expect(plan.drop.map((e) => e.id)).toEqual(['weight', 'measures'])
    expect(plan.to?.id).toBe('today')
  })

  it('the desktop shows one screen: every navigation cross-fades and keeps nothing', () => {
    const a = planGo(initialStack('today'), 'weight', { mode: 'push', desktop: true })
    expect(a.motion).toBe('fade')
    expect(ids(a.state)).toEqual(['weight'])
    const b = planGo(a.state, 'recovery', { mode: 'replace', desktop: true })
    expect(ids(b.state)).toEqual(['recovery'])
  })

  it('a screen opened again is a new entry with a new key, never the old one revived', () => {
    let s = initialStack('today')
    const first = topOf(s).key
    s = planGo(s, 'weight', { mode: 'tab', desktop: false }).state
    s = planGo(s, 'today', { mode: 'tab', desktop: false }).state
    expect(topOf(s).id).toBe('today')
    expect(topOf(s).key).not.toBe(first)
  })

  it('an entry remembers the screen it came from, so its back label never changes mid-motion', () => {
    const pushed = planGo(initialStack('today'), 'weight', { mode: 'push', desktop: false })
    expect(pushed.to?.back).toBe('today')
    const swapped = planGo(pushed.state, 'recovery', { mode: 'replace', desktop: false })
    expect(swapped.to?.back).toBe('today')
    const tab = planGo(swapped.state, 'glp1', { mode: 'tab', desktop: false })
    expect(tab.to?.back).toBeNull()
  })

  it('pop takes the top screen off and returns to the one below', () => {
    const s = planGo(initialStack('today'), 'weight', { mode: 'push', desktop: false }).state
    const plan = planPop(s)
    expect(plan.motion).toBe('pop')
    expect(ids(plan.state)).toEqual(['today'])
    expect(plan.from?.id).toBe('weight')
    expect(plan.to?.id).toBe('today')
    expect(planPop(plan.state).motion).toBe('none')
  })

  it('pop to root drops everything between the root and the top', () => {
    let s = initialStack('weight')
    s = planGo(s, 'measures', { mode: 'push', desktop: false }).state
    s = planGo(s, 'nights', { mode: 'push', desktop: false }).state
    const plan = planPopToRoot(s)
    expect(ids(plan.state)).toEqual(['weight'])
    expect(plan.drop.map((e) => e.id)).toEqual(['measures', 'nights'])
  })
})
