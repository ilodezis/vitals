declare global {
  interface ImportMetaEnv {
    /** Where the router lives: '/app' while the old UI still owns the root. */
    readonly VITE_ROUTER_BASE?: string
  }
}

export {}
