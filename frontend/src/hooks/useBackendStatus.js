'use client';

import { useEffect, useState } from 'react';
import { BACKEND_URL } from '@/lib/constants';

/**
 * Polls /api/health. States: 'waking' (no answer yet: free hosting cold start),
 * 'loading-model' (server up, detection model still loading), 'ready'.
 */
export function useBackendStatus() {
  const [status, setStatus] = useState({ state: 'waking', since: Date.now() });
  useEffect(() => {
    let stop = false;
    let timer;
    const tick = async () => {
      const ctrl = new AbortController();
      const to = setTimeout(() => ctrl.abort(), 8000);
      let next = 'waking';
      try {
        const r = await fetch(`${BACKEND_URL}/api/health`, { signal: ctrl.signal, cache: 'no-store' });
        if (r.ok) {
          const j = await r.json();
          next = j.model_loaded || j.model_error ? 'ready' : 'loading-model';
        }
      } catch {}
      clearTimeout(to);
      if (stop) return;
      setStatus((s) => (s.state === next ? s : { state: next, since: Date.now() }));
      timer = setTimeout(tick, next === 'ready' ? 15000 : 3000);
    };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, []);
  return status;
}

/** One poll of /api/metrics shared by all tiles: { [cameraId]: metrics } */
export function useStreamMetrics(enabled = true) {
  const [metrics, setMetrics] = useState({});
  useEffect(() => {
    if (!enabled) return;
    let stop = false;
    let timer;
    const tick = async () => {
      try {
        const r = await fetch(`${BACKEND_URL}/api/metrics`, { cache: 'no-store' });
        if (r.ok) { const j = await r.json(); if (!stop) setMetrics(j.cameras || {}); }
      } catch {}
      if (!stop) timer = setTimeout(tick, 2000);
    };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, [enabled]);
  return metrics;
}
