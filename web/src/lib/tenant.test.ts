import { describe, expect, it } from 'vitest'
import { resolveTenant, TENANT_KEY } from './tenant'

function memoryStorage(init: Record<string, string> = {}) {
  const m = new Map(Object.entries(init))
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    dump: () => Object.fromEntries(m),
  }
}

describe('resolveTenant', () => {
  it('uses ?team= so a room can be shared by link, and remembers it', () => {
    const s = memoryStorage()
    expect(resolveTenant('?team=launch_crew', s)).toBe('launch_crew')
    expect(s.dump()[TENANT_KEY]).toBe('launch_crew')
  })

  it('ignores an invalid ?team= and falls back to the remembered room', () => {
    const s = memoryStorage({ [TENANT_KEY]: 'vabc12345' })
    expect(resolveTenant('?team=Bad-Name!', s)).toBe('vabc12345')
  })

  it('creates a fresh valid room id for a first-time visitor and keeps it', () => {
    const s = memoryStorage()
    const t = resolveTenant('', s)
    expect(t).toMatch(/^v[0-9a-f]{8}$/)
    expect(resolveTenant('', s)).toBe(t)
  })

  it('still returns a room when storage throws (private mode)', () => {
    const broken = {
      getItem: () => {
        throw new Error('blocked')
      },
      setItem: () => {
        throw new Error('blocked')
      },
    }
    expect(resolveTenant('', broken)).toMatch(/^v[0-9a-f]{8}$/)
  })
})
