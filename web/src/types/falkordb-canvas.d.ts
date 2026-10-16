// React 19 types no longer expose a global JSX namespace, so the intrinsic element declared by
// @falkordb/canvas (inside `declare global`) is not picked up. Register it on React's JSX namespace.
import type { DetailedHTMLProps, HTMLAttributes } from 'react'
import type { FalkorDBCanvas } from '@falkordb/canvas'

declare module 'react' {
  namespace JSX {
    interface IntrinsicElements {
      'falkordb-canvas': DetailedHTMLProps<HTMLAttributes<FalkorDBCanvas>, FalkorDBCanvas>
    }
  }
}
