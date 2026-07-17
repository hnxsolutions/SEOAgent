'use client';

import { useEffect, useRef, useState } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

export type StreamEvent = { type: string; data: Record<string, unknown> };

/**
 * Real-time Mission Control stream.
 *
 * Uses fetch() + ReadableStream (not EventSource) so the JWT travels in the
 * Authorization header rather than the URL. Parses the server's SSE frames and
 * fires `onEvent` for every real backend job/stage delta; reconnects when the
 * server closes the connection (it recycles every ~5 min).
 */
export function useMissionControlStream(onEvent: (_e: StreamEvent) => void) {
  const [connected, setConnected] = useState(false);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    let cancelled = false;
    let controller: AbortController | null = null;

    async function connect() {
      if (cancelled) return;
      const token = typeof window !== 'undefined' ? window.localStorage.getItem('access_token') : null;
      if (!token) return;
      controller = new AbortController();
      try {
        const res = await fetch(`${API_URL}/mission-control/stream`, {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        });
        if (!res.body) throw new Error('no stream body');
        setConnected(true);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { done, value } = await reader.read();
          if (done || cancelled) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split('\n\n');
          buffer = frames.pop() ?? '';
          for (const frame of frames) {
            let eventType = 'message';
            let dataStr = '';
            for (const line of frame.split('\n')) {
              if (line.startsWith('event:')) eventType = line.slice(6).trim();
              else if (line.startsWith('data:')) dataStr += line.slice(5).trim();
            }
            if (!dataStr) continue;
            try {
              onEventRef.current({ type: eventType, data: JSON.parse(dataStr) });
            } catch {
              /* ignore malformed frame */
            }
          }
        }
      } catch {
        /* network/abort — fall through to reconnect */
      } finally {
        if (!cancelled) {
          setConnected(false);
          setTimeout(connect, 2000); // reconnect after the server recycles/drops
        }
      }
    }

    connect();
    return () => {
      cancelled = true;
      controller?.abort();
    };
  }, []);

  return { connected };
}
