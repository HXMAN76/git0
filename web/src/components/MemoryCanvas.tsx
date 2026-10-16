// Owner: Person D — see docs/team/person-d-ui.md
// Memory graph: wraps the <falkordb-canvas> web component (@falkordb/canvas 0.3.3).
// The component's default size is the window, not its CSS box, so the host box is measured
// and pushed in with setWidth/setHeight (ResizeObserver).
// TODO: feed real FalkorDB rows through lib/memory.ts instead of SAMPLE, and wire WhyPath highlighting.

import { useEffect, useRef } from 'react'
import '@falkordb/canvas'
import type { Data, FalkorDBCanvas } from '@falkordb/canvas'

const SAMPLE: Data = {
  nodes: [
    { id: 1, labels: ['Commit'], color: '#60a5fa', visible: true, data: { name: 'c1 init repo' } },
    { id: 2, labels: ['Commit'], color: '#60a5fa', visible: true, data: { name: 'c2 add chat panel' } },
    { id: 3, labels: ['Memory'], color: '#f472b6', visible: true, data: { name: 'decision: use SSE' } },
  ],
  links: [
    { id: 1, relationship: 'PARENT', color: '#9ca3af', source: 1, target: 2, visible: true, data: {} },
    { id: 2, relationship: 'INFORMS', color: '#9ca3af', source: 3, target: 2, visible: true, data: {} },
  ],
}

export function MemoryCanvas() {
  const hostRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<FalkorDBCanvas>(null)

  useEffect(() => {
    const host = hostRef.current
    const canvas = canvasRef.current
    if (!host || !canvas) throw new Error('MemoryCanvas: <falkordb-canvas> did not mount')

    canvas.setConfig({
      backgroundColor: '#0a0a0a',
      foregroundColor: '#e5e7eb',
      captionsKeys: ['name'], // which data property is drawn as the node label
    })
    canvas.setData(SAMPLE)

    const syncSize = () => {
      const { width, height } = host.getBoundingClientRect()
      canvas.setWidth(Math.floor(width))
      canvas.setHeight(Math.floor(height))
    }
    syncSize()
    const observer = new ResizeObserver(syncSize)
    observer.observe(host)
    return () => observer.disconnect()
  }, [])

  return (
    <div ref={hostRef} className="relative h-full w-full overflow-hidden">
      <falkordb-canvas ref={canvasRef} style={{ position: 'absolute', inset: 0, display: 'block' }} />
    </div>
  )
}
