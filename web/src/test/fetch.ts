import { vi } from 'vitest'

// Fetch stand-in for component tests: `route(request)` returns a body, or [body, status]. Requests are
// real `Request` objects (openapi-fetch builds them), so tests can assert on method, path and JSON body.
type Reply = unknown | [unknown, number]

export function respond(route: (req: Request, body: unknown) => Reply) {
  const fetch = vi.fn(async (req: Request) => {
    const text = req.method === 'GET' ? '' : await req.clone().text()
    const out = route(req, text ? JSON.parse(text) : undefined)
    const [body, status] = Array.isArray(out) && typeof out[1] === 'number' && out.length === 2 ? out : [out, 200]
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

export function urlOf(fetch: ReturnType<typeof respond>, call: number): URL {
  return new URL((fetch.mock.calls[call] as unknown as [Request])[0].url)
}

export async function bodyOf(fetch: ReturnType<typeof respond>, call: number): Promise<unknown> {
  return (fetch.mock.calls[call] as unknown as [Request])[0].clone().json()
}
