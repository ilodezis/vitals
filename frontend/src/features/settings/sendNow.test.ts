import { describe, expect, it } from 'vitest'
import { sendNowOutcome } from './ConnectionsSection'

const key = (name: string) => `settings.garmin_weight_action.${name}`

describe('Garmin weight "send now" outcome', () => {
  it('names what happened instead of always claiming the weight was sent', () => {
    expect(sendNowOutcome('sent')).toEqual({ key: key('sent'), warn: false })
    expect(sendNowOutcome('matched')).toEqual({ key: key('matched'), warn: false })
    expect(sendNowOutcome('deleted')).toEqual({ key: key('deleted'), warn: false })
    expect(sendNowOutcome('empty')).toEqual({ key: key('empty'), warn: false })
  })

  it('warns when nothing could be sent', () => {
    expect(sendNowOutcome('disabled')).toEqual({ key: key('disabled'), warn: true })
    expect(sendNowOutcome('unconfigured')).toEqual({ key: key('unconfigured'), warn: true })
    expect(sendNowOutcome('busy')).toEqual({ key: key('busy'), warn: true })
    expect(sendNowOutcome('error')).toEqual({ key: key('error'), warn: true })
  })

  it('points at the status card for an outcome without wording of its own', () => {
    expect(sendNowOutcome('pending')).toEqual({ key: key('done'), warn: false })
    expect(sendNowOutcome('failed')).toEqual({ key: key('done'), warn: true })
    expect(sendNowOutcome('conflict')).toEqual({ key: key('done'), warn: true })
  })
})
