import { describe, expect, it } from 'vitest'
import { creationOptions, fromBase64url, registrationJSON, toBase64url } from './passkeys'

const bytes = (buffer: ArrayBuffer): number[] => [...new Uint8Array(buffer)]

describe('base64url', () => {
  it('round-trips every padding length', () => {
    for (const length of [0, 1, 2, 3, 4, 31, 32, 33]) {
      const data = Uint8Array.from({ length }, (_, i) => (i * 37 + 251) % 256)
      expect(bytes(fromBase64url(toBase64url(data.buffer)))).toEqual([...data])
    }
  })

  it('uses the URL alphabet and no padding, as the server writes it', () => {
    const text = toBase64url(Uint8Array.from([0xfb, 0xff, 0xfe]).buffer)
    expect(text).toBe('-__-')
    expect(bytes(fromBase64url('-__-'))).toEqual([0xfb, 0xff, 0xfe])
  })
})

describe('creationOptions', () => {
  it('turns the byte fields into buffers and leaves the rest alone', () => {
    const options = creationOptions({
      rp: { id: 'vitals.test', name: 'Vitals' },
      user: { id: 'AQID', name: 'tester', displayName: 'tester' },
      challenge: 'BAUG',
      pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
      excludeCredentials: [{ id: 'BwgJ', type: 'public-key', transports: ['internal'] }],
      authenticatorSelection: { residentKey: 'required', userVerification: 'required' },
    })
    expect(bytes(options.challenge as ArrayBuffer)).toEqual([4, 5, 6])
    expect(bytes(options.user.id as ArrayBuffer)).toEqual([1, 2, 3])
    expect(options.user.name).toBe('tester')
    expect(bytes(options.excludeCredentials?.[0]?.id as ArrayBuffer)).toEqual([7, 8, 9])
    expect(options.excludeCredentials?.[0]?.transports).toEqual(['internal'])
    expect(options.authenticatorSelection?.userVerification).toBe('required')
  })

  it('copes with no keys to exclude', () => {
    const options = creationOptions({
      rp: { id: 'vitals.test', name: 'Vitals' },
      user: { id: 'AQID', name: 'tester', displayName: 'tester' },
      challenge: 'BAUG',
      pubKeyCredParams: [],
    })
    expect(options.excludeCredentials).toEqual([])
  })
})

describe('registrationJSON', () => {
  it('spells the credential the way the server parses it', () => {
    const credential = {
      id: 'AQID',
      rawId: Uint8Array.from([1, 2, 3]).buffer,
      type: 'public-key',
      authenticatorAttachment: 'platform',
      getClientExtensionResults: () => ({ credProps: { rk: true } }),
      response: {
        clientDataJSON: Uint8Array.from([4]).buffer,
        attestationObject: Uint8Array.from([5]).buffer,
        getTransports: () => ['internal', 'hybrid'],
      },
    } as unknown as PublicKeyCredential
    expect(registrationJSON(credential)).toEqual({
      id: 'AQID',
      rawId: 'AQID',
      type: 'public-key',
      authenticatorAttachment: 'platform',
      clientExtensionResults: { credProps: { rk: true } },
      response: { clientDataJSON: 'BA', attestationObject: 'BQ', transports: ['internal', 'hybrid'] },
    })
  })
})
