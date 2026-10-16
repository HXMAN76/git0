import createClient from 'openapi-fetch'
import type { paths } from './schema'

// Same-origin: in dev, Vite proxies /api to :8000; in prod, FastAPI serves the build.
// The origin is spelled out because fetch outside a browser (Vitest) cannot resolve a relative URL, and
// fetch is looked up per call so tests can stub it after this module loads.
// Regenerate `paths` with `pnpm gen:api` after backend route changes.
export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? '',
  fetch: (request) => globalThis.fetch(request),
})
