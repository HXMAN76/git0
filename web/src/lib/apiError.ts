// Turns an openapi-fetch `error` body into the text we show. FastAPI sends `{detail: string}` for our own
// errors (404/409/502) and `{detail: [...]}` for validation (422); anything else is shown raw. Never a
// generic "something went wrong": the visitor (and we) need the real reason (M12).
export function apiErrorText(error: unknown): string {
  const detail = (error as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  return JSON.stringify(detail ?? error)
}

export class ApiError extends Error {
  constructor(error: unknown) {
    super(apiErrorText(error))
    this.name = 'ApiError'
  }
}
