export interface SseEvent {
  type: string
  data: unknown
}

export interface SubscribeOptions {
  /** Named SSE events to listen for. Unnamed events arrive as "message". */
  events?: string[]
  /**
   * Called on connection errors and on malformed JSON payloads.
   * Defaults to console.error. Nothing is swallowed silently.
   */
  onError?: (error: Error | Event) => void
}

/**
 * Subscribe to a Server-Sent Events endpoint. Each payload is parsed as JSON and
 * delivered with its event name. Returns a function that closes the stream.
 *
 * Note: EventSource reconnects by itself on transient failures. onError fires on every
 * failure, so the caller decides what to do with it.
 */
export function subscribe(
  url: string,
  onEvent: (event: SseEvent) => void,
  options: SubscribeOptions = {},
): () => void {
  const { events = ['message'], onError = (e) => console.error(`[sse] ${url}`, e) } = options

  const source = new EventSource(url)

  for (const type of events) {
    source.addEventListener(type, (raw) => {
      const payload = (raw as MessageEvent<string>).data
      let data: unknown
      try {
        data = JSON.parse(payload)
      } catch (cause) {
        onError(new Error(`[sse] ${url}: malformed JSON on "${type}"`, { cause }))
        return
      }
      onEvent({ type, data })
    })
  }

  source.onerror = (e) => onError(e)

  return () => source.close()
}
