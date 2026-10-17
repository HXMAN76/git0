// Which team room (tenant graph) this browser uses. Every visitor gets their own room so judges never
// collide (M7); `?team=<id>` opens a shared room by link. Must match the API's tenant rule ([a-z0-9_]{1,40}).

export const TENANT_KEY = 'git0.tenant'
const VALID = /^[a-z0-9_]{1,40}$/

type KeyValueStore = Pick<Storage, 'getItem' | 'setItem'>

export function resolveTenant(search: string, storage: KeyValueStore): string {
  const fromLink = new URLSearchParams(search).get('team')
  let remembered: string | null = null
  try {
    remembered = storage.getItem(TENANT_KEY)
  } catch {
    // private mode / blocked storage: still give the visitor a room for this page view
  }
  const tenant =
    fromLink && VALID.test(fromLink)
      ? fromLink
      : remembered && VALID.test(remembered)
        ? remembered
        : `v${Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => b.toString(16).padStart(2, '0')).join('')}`
  try {
    storage.setItem(TENANT_KEY, tenant)
  } catch {
    // not remembered across visits; the room still works now
  }
  return tenant
}
