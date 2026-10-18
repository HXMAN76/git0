// Per-browser UI memory (localStorage). Every access is guarded: private windows can throw.

const TOUR_KEY = 'git0-ide-tour-seen'

/** True once the welcome tour has started on this browser. The tour then only restarts from the title bar. */
export function readTourSeen(): boolean {
  try {
    return window.localStorage.getItem(TOUR_KEY) === '1'
  } catch {
    // Private windows can throw on storage access; then the tour simply auto-starts again.
    return false
  }
}

export function markTourSeen() {
  try {
    window.localStorage.setItem(TOUR_KEY, '1')
  } catch {
    // Nothing to do: the tour will auto-start on the next load.
  }
}

const NARRATOR_KEY = 'git0-ide-narrator'

/** Coach marks during the live run. On unless the viewer turned them off. */
export function readNarrator(): boolean {
  try {
    return window.localStorage.getItem(NARRATOR_KEY) !== '0'
  } catch {
    return true
  }
}

export function writeNarrator(on: boolean) {
  try {
    window.localStorage.setItem(NARRATOR_KEY, on ? '1' : '0')
  } catch {
    // Not persisted: the narrator goes back to on after a reload.
  }
}

const PANEL_KEY = 'git0-ide-panel-height'

/** The bottom panel height the user last dragged to, or null when unset or unreadable. */
export function readPanelHeight(): number | null {
  try {
    const raw = window.localStorage.getItem(PANEL_KEY)
    if (raw === null) return null
    const value = Number(raw)
    return Number.isFinite(value) ? value : null
  } catch {
    // Storage can throw in private windows; the panel then uses the default height.
    return null
  }
}

export function writePanelHeight(height: number) {
  try {
    window.localStorage.setItem(PANEL_KEY, String(Math.round(height)))
  } catch {
    // Not persisted: the next load uses the default height.
  }
}
