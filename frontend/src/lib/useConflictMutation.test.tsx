import { QueryClient } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { ConflictError, InvalidError, type Violation } from '@/api/client'
import { ConflictAlert } from '@/components/controls/ConflictAlert'
import { I18nProvider } from '@/i18n/I18nProvider'
import { createConflictMutation } from './useConflictMutation'

const SAMPLE_VIOLATION: Violation = {
  rule_id: 42,
  rule_type: 'conflict',
  severity: 'block',
  message: 'Retinoid and peel on the same day.',
  domain_a: 'skincare',
  domain_b: 'skincare',
  params: {},
  category: 'dermatology',
  source: null,
  evidence: null,
}

describe('useConflictMutation', () => {
  it('stores violations on 409 ConflictError and sends override: true on retryWithOverride', async () => {
    const queryClient = new QueryClient()
    const calls: Array<{ dose: number; override: boolean }> = []

    const mutationFn = vi.fn(async ({ dose, override }: { dose: number; override: boolean }) => {
      calls.push({ dose, override })
      if (!override) {
        throw new ConflictError([SAMPLE_VIOLATION])
      }
      return { id: 10 }
    })

    const m = createConflictMutation<unknown, { dose: number }>(queryClient, {
      mutationFn,
    })

    const firstOk = await m.submit({ dose: 2.5 })
    expect(firstOk).toBe(false)
    expect(m.violations).toEqual([SAMPLE_VIOLATION])
    expect(m.problem).toBeNull()
    expect(calls).toEqual([{ dose: 2.5, override: false }])

    const retryOk = await m.retryWithOverride()
    expect(retryOk).toBe(true)
    expect(m.violations).toEqual([])
    expect(calls).toEqual([
      { dose: 2.5, override: false },
      { dose: 2.5, override: true },
    ])
  })

  it('captures InvalidError message in problem and clears violations', async () => {
    const queryClient = new QueryClient()
    const m = createConflictMutation(queryClient, {
      mutationFn: async () => {
        throw new InvalidError('Value out of bounds')
      },
    })

    const ok = await m.submit()
    expect(ok).toBe(false)
    expect(m.violations).toEqual([])
    expect(m.problem).toBe('Value out of bounds')

    m.clearConflict()
    expect(m.problem).toBeNull()
  })

  it('renders ConflictAlert with violation messages and Fix / Save anyway actions', () => {
    const html = renderToStaticMarkup(
      <I18nProvider
        lang="ru"
        dictionary={{
          'app.fix': 'Исправить',
          'app.save_anyway': 'Сохранить всё равно',
          'app.log.weight.conflict_rule': 'Правило конфликтов',
        }}
      >
        <ConflictAlert
          violations={[SAMPLE_VIOLATION]}
          onFix={() => undefined}
          onSaveAnyway={() => undefined}
        />
      </I18nProvider>,
    )

    expect(html).toContain('Retinoid and peel on the same day.')
    expect(html).toContain('Исправить')
    expect(html).toContain('Сохранить всё равно')
  })
})
