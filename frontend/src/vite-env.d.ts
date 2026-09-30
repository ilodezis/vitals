declare global {
  /** A hash of the committed OpenAPI schema: the persisted query cache's `buster`. */
  const __API_BUSTER__: string
}

export {}
