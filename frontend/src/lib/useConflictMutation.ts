import { useRef, useState } from 'react'
import { MutationObserver, type QueryClient, useMutation } from '@tanstack/react-query'
import { ConflictError, InvalidError, type Violation } from '@/api/client'

export type ConflictVars<TVars> = TVars extends void
  ? { override: boolean }
  : TVars & { override: boolean }

export interface UseConflictMutationOptions<TData = unknown, TVars = void> {
  mutationFn: (vars: ConflictVars<TVars>, context: { override: boolean }) => Promise<TData>
  onSuccess?: (data: TData, vars: ConflictVars<TVars>, context: { override: boolean }) => void | Promise<void>
  onError?: (error: Error, vars: ConflictVars<TVars>, context: { override: boolean }) => void
  fallbackErrorMessage?: string
}

interface InternalPayload<TVars> {
  vars: TVars
  override: boolean
}

function isOverrideOnlyOption(arg: unknown): arg is { override: boolean } {
  if (typeof arg !== 'object' || arg === null) return false
  const keys = Object.keys(arg)
  return keys.length === 1 && keys[0] === 'override' && typeof (arg as { override?: unknown }).override === 'boolean'
}

function buildConflictVars<TVars>(vars: TVars, override: boolean): ConflictVars<TVars> {
  if (typeof vars === 'object' && vars !== null) {
    return { ...(vars as Record<string, unknown>), override } as ConflictVars<TVars>
  }
  return { override } as ConflictVars<TVars>
}

/** Headless conflict-aware mutation controller backed by TanStack Query's MutationObserver. */
export function createConflictMutation<TData = unknown, TVars = void>(
  queryClient: QueryClient,
  options: UseConflictMutationOptions<TData, TVars>,
) {
  let violations: Violation[] = []
  let problem: string | null = null
  let lastVars: TVars | undefined = undefined

  const observer = new MutationObserver<TData, Error, InternalPayload<TVars>>(queryClient, {
    mutationFn: async ({ vars, override }) => {
      const merged = buildConflictVars(vars, override)
      return options.mutationFn(merged, { override })
    },
    onSuccess: async (data, { vars, override }) => {
      violations = []
      problem = null
      const merged = buildConflictVars(vars, override)
      await options.onSuccess?.(data, merged, { override })
    },
    onError: (error, { vars, override }) => {
      if (error instanceof ConflictError) {
        violations = error.violations
        problem = null
        return
      }
      violations = []
      problem =
        error instanceof InvalidError
          ? error.message
          : options.fallbackErrorMessage ?? (error instanceof Error ? error.message : 'Request failed')
      const merged = buildConflictVars(vars, override)
      options.onError?.(error, merged, { override })
    },
  })

  const execute = async (vars: TVars, override: boolean): Promise<TData> => {
    lastVars = vars
    return observer.mutate({ vars, override })
  }

  const submit = async (
    varsOrOpts?: TVars | { override: boolean },
    opts?: { override?: boolean },
  ): Promise<boolean> => {
    let vars: TVars
    let override = opts?.override ?? false
    if (isOverrideOnlyOption(varsOrOpts) && opts === undefined) {
      vars = lastVars as TVars
      override = varsOrOpts.override
    } else {
      vars = varsOrOpts as TVars
      lastVars = vars
    }
    try {
      await execute(vars, override)
      return true
    } catch {
      return false
    }
  }

  const retryWithOverride = async (): Promise<boolean> => {
    return submit(lastVars as TVars, { override: true })
  }

  const clearConflict = () => {
    violations = []
    problem = null
  }

  return {
    get violations() {
      return violations
    },
    get problem() {
      return problem
    },
    submit,
    retryWithOverride,
    clearConflict,
  }
}

export function useConflictMutation<TData = unknown, TVars = void>(
  options: UseConflictMutationOptions<TData, TVars>,
) {
  const [violations, setViolations] = useState<Violation[]>([])
  const [problem, setProblem] = useState<string | null>(null)
  const lastVarsRef = useRef<TVars | undefined>(undefined)

  const clearConflict = () => {
    setViolations([])
    setProblem(null)
  }

  const mutation = useMutation<TData, Error, InternalPayload<TVars>>({
    mutationFn: async ({ vars, override }) => {
      const merged = buildConflictVars(vars, override)
      return options.mutationFn(merged, { override })
    },
    onSuccess: async (data, { vars, override }) => {
      setViolations([])
      setProblem(null)
      const merged = buildConflictVars(vars, override)
      await options.onSuccess?.(data, merged, { override })
    },
    onError: (error, { vars, override }) => {
      if (error instanceof ConflictError) {
        setViolations(error.violations)
        setProblem(null)
        return
      }
      setViolations([])
      const msg =
        error instanceof InvalidError
          ? error.message
          : options.fallbackErrorMessage ?? (error instanceof Error ? error.message : 'Request failed')
      setProblem(msg)
      const merged = buildConflictVars(vars, override)
      options.onError?.(error, merged, { override })
    },
  })

  const execute = async (vars: TVars, override: boolean): Promise<TData> => {
    lastVarsRef.current = vars
    return mutation.mutateAsync({ vars, override })
  }

  const submit = async (
    varsOrOpts?: TVars | { override: boolean },
    opts?: { override?: boolean },
  ): Promise<boolean> => {
    let vars: TVars
    let override = opts?.override ?? false
    if (isOverrideOnlyOption(varsOrOpts) && opts === undefined) {
      vars = lastVarsRef.current as TVars
      override = varsOrOpts.override
    } else {
      vars = varsOrOpts as TVars
      lastVarsRef.current = vars
    }
    try {
      await execute(vars, override)
      return true
    } catch {
      return false
    }
  }

  const mutate = (vars?: TVars, opts?: { override?: boolean }) => {
    const actualVars = (vars ?? lastVarsRef.current) as TVars
    lastVarsRef.current = actualVars
    mutation.mutate({ vars: actualVars, override: opts?.override ?? false })
  }

  const mutateAsync = (vars?: TVars, opts?: { override?: boolean }): Promise<TData> => {
    const actualVars = (vars ?? lastVarsRef.current) as TVars
    return execute(actualVars, opts?.override ?? false)
  }

  const retryWithOverride = async (): Promise<boolean> => {
    return submit(lastVarsRef.current as TVars, { override: true })
  }

  return {
    ...mutation,
    violations,
    problem,
    clearConflict,
    submit,
    mutate,
    mutateAsync,
    retryWithOverride,
  }
}
