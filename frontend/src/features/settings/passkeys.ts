/** The browser half of adding a passkey: the server's options in, the new credential out, both
 *  as JSON with base64url bytes. Spelled out rather than left to
 *  `PublicKeyCredential.parseCreationOptionsFromJSON()` / `toJSON()`, which not every Safari the
 *  app is opened in has yet. */

export function fromBase64url(value: string): ArrayBuffer {
  const base64 = value.replace(/-/g, '+').replace(/_/g, '/')
  const binary = atob(base64 + '==='.slice((base64.length + 3) % 4))
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes.buffer
}

export function toBase64url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export function passkeysSupported(): boolean {
  return typeof window !== 'undefined' && 'PublicKeyCredential' in window && navigator.credentials !== undefined
}

interface JsonDescriptor {
  id: string
  type: PublicKeyCredentialType
  transports?: AuthenticatorTransport[]
}

interface JsonCreationOptions extends Omit<PublicKeyCredentialCreationOptions, 'challenge' | 'user' | 'excludeCredentials'> {
  challenge: string
  user: { id: string; name: string; displayName: string }
  excludeCredentials?: JsonDescriptor[]
}

/** `POST /settings/passkeys/register/options` → what `navigator.credentials.create()` takes. */
export function creationOptions(json: Record<string, unknown>): PublicKeyCredentialCreationOptions {
  const options = json as unknown as JsonCreationOptions
  return {
    ...options,
    challenge: fromBase64url(options.challenge),
    user: { ...options.user, id: fromBase64url(options.user.id) },
    excludeCredentials: (options.excludeCredentials ?? []).map((c) => ({ ...c, id: fromBase64url(c.id) })),
  }
}

/** The new credential as `POST /settings/passkeys/register/verify` reads it. */
export function registrationJSON(credential: PublicKeyCredential): Record<string, unknown> {
  const response = credential.response as AuthenticatorAttestationResponse
  return {
    id: credential.id,
    rawId: toBase64url(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
    clientExtensionResults: credential.getClientExtensionResults(),
    response: {
      clientDataJSON: toBase64url(response.clientDataJSON),
      attestationObject: toBase64url(response.attestationObject),
      transports: typeof response.getTransports === 'function' ? response.getTransports() : [],
    },
  }
}

interface SignalApi {
  signalAllAcceptedCredentials?: (options: { rpId: string; userId: string; allAcceptedCredentialIds: string[] }) => Promise<void>
}

/** Tell the device's keychain which Vitals passkeys still work, so one removed here stops being
 *  offered at sign-in. Only where the browser has the Signal API; elsewhere a no-op. */
export function signalAccepted(rpId: string, userId: string, credentialIds: string[]): void {
  const api = (typeof window === 'undefined' ? undefined : window.PublicKeyCredential) as SignalApi | undefined
  if (typeof api?.signalAllAcceptedCredentials !== 'function') return
  api.signalAllAcceptedCredentials({ rpId, userId, allAcceptedCredentialIds: credentialIds }).catch(() => {})
}
