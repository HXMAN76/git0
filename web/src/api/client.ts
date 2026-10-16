import createClient from 'openapi-fetch'
import type { paths } from './schema'

// Same-origin: in dev, Vite proxies /api to :8000; in prod, FastAPI serves the build.
// Regenerate `paths` with `pnpm gen:api` after backend route changes.
export const api = createClient<paths>({ baseUrl: '' })
