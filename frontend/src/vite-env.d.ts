declare global {
  interface ImportMetaEnv {
    /** Where the router lives: '/app' while the old UI still owns the root. */
    readonly VITE_ROUTER_BASE?: string
  }

  /** A hash of the committed OpenAPI schema: the persisted query cache's `buster`. */
  const __API_BUSTER__: string
}

export {}
