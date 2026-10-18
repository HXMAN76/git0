// Per-browser UI memory (localStorage). Every access is guarded: private windows can throw.

const SEEN_KEY = 'git0-ide-howto-seen'

export function readHowToSeen(): boolean {
  try {
    return window.localStorage.getItem(SEEN_KEY) === '1'
  } catch {
    // Private windows can throw on storage access; then the overlay simply shows again.
    return false
  }
}

export function markHowToSeen() {
  try {
    window.localStorage.setItem(SEEN_KEY, '1')
  } catch {
    // Nothing to do: the overlay will show on the next load.
  }
}
