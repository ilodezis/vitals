import { describe, expect, it } from 'vitest'
import { placeInk } from './SectionTabs'

function fakeInk() {
  const writes: string[] = []
  const style = {
    _transform: '',
    _transition: '',
    get transform() { return this._transform },
    set transform(v: string) { writes.push(`transform=${v}`); this._transform = v },
    get transition() { return this._transition },
    set transition(v: string) { writes.push(`transition=${v}`); this._transition = v },
  }
  return {
    style,
    writes,
    get offsetWidth() { writes.push('reflow'); return 100 },
  }
}

describe('placeInk', () => {
  const on = { offsetLeft: 120, offsetWidth: 50 }

  it('jumps on the first placement instead of sliding from the first tab', () => {
    const ink = fakeInk()
    expect(placeInk(ink, on, true)).toBe(true)
    expect(ink.writes).toEqual(['transition=none', 'transform=translateX(120px) scaleX(0.5)', 'reflow', 'transition='])
  })

  it('slides on later moves', () => {
    const ink = fakeInk()
    expect(placeInk(ink, on, false)).toBe(true)
    expect(ink.writes).toEqual(['transform=translateX(120px) scaleX(0.5)'])
  })

  it('waits while the row has no layout', () => {
    const ink = fakeInk()
    expect(placeInk(ink, { offsetLeft: 0, offsetWidth: 0 }, true)).toBe(false)
    expect(ink.writes).toEqual([])
  })
})
