'use client';

import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { BACKEND_URL } from '@/lib/constants';
import { useBackendStatus, useStreamMetrics } from '@/hooks/useBackendStatus';

export const StreamStatusContext = createContext({ backend: { state: 'ready' }, metrics: {} });

/** Polls /api/health and /api/metrics once and shares them with every StreamTile below. */
export function StreamStatusProvider({ children }) {
  const backend = useBackendStatus();
  const metrics = useStreamMetrics(backend.state !== 'waking');
  return <StreamStatusContext.Provider value={{ backend, metrics }}>{children}</StreamStatusContext.Provider>;
}

/**
 * MJPEG tile with an explicit status (connecting / live / reconnecting / error), auto-reconnect with
 * exponential backoff, a skeleton while connecting, and a measured FPS / latency badge.
 * `metrics` is this camera's entry from /api/metrics (see useStreamMetrics).
 * Use `clean` to get plain video and let the browser draw boxes from /ws/detections/{id} on a canvas.
 */
export default function StreamTile({ cameraId, alt, className = '', fit = 'cover', clean = false }) {
  const ctx = useContext(StreamStatusContext);
  const metrics = ctx.metrics?.[cameraId];
  const serverState = ctx.backend?.state;
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState('connecting');
  const timer = useRef(null);
  const canvasRef = useRef(null);
  const imgRef = useRef(null);

  const src = `${BACKEND_URL}/video/${cameraId}?${clean ? 'clean=1&' : ''}r=${attempt}`;

  useEffect(() => () => clearTimeout(timer.current), []);

  const onError = () => {
    setState('reconnecting');
    clearTimeout(timer.current);
    const delay = Math.min(1000 * 2 ** Math.min(attempt, 5), 15000);
    timer.current = setTimeout(() => setAttempt((a) => a + 1), delay);
  };

  // canvas overlay (clean mode only)
  useEffect(() => {
    if (!clean) return;
    const wsBase = BACKEND_URL.replace(/^http/, 'ws');
    let ws, closed = false, retry;
    const draw = (msg) => {
      const c = canvasRef.current, img = imgRef.current;
      if (!c || !img) return;
      const w = (c.width = img.clientWidth), h = (c.height = img.clientHeight);
      const ctx = c.getContext('2d');
      ctx.clearRect(0, 0, w, h);
      // object-fit: contain letterboxes the video; map normalised boxes into the visible video rect
      const [fw, fh] = msg.frame_size || [0, 0];
      if (!fw || !fh) return;
      const scale = Math.min(w / fw, h / fh);
      const vw = fw * scale, vh = fh * scale, ox = (w - vw) / 2, oy = (h - vh) / 2;
      ctx.lineWidth = 2; ctx.font = '12px sans-serif';
      for (const t of msg.tracks || []) {
        const [x1, y1, x2, y2] = t.box;
        ctx.strokeStyle = '#22d3ee';
        ctx.strokeRect(ox + x1 * vw, oy + y1 * vh, (x2 - x1) * vw, (y2 - y1) * vh);
        ctx.fillStyle = '#22d3ee';
        ctx.fillText(`${t.class}${t.id >= 0 ? ' #' + t.id : ''} ${Math.round(t.conf * 100)}%`, ox + x1 * vw + 3, oy + y1 * vh - 4);
      }
    };
    const open = () => {
      ws = new WebSocket(`${wsBase}/ws/detections/${cameraId}`);
      ws.onmessage = (e) => { try { draw(JSON.parse(e.data)); } catch {} };
      ws.onclose = () => { if (!closed) retry = setTimeout(open, 2000); };
    };
    open();
    return () => { closed = true; clearTimeout(retry); ws && ws.close(); };
  }, [clean, cameraId]);

  const live = state === 'live' && (!metrics || metrics.state === 'live' || metrics.state === undefined);
  let label = 'Connecting...';
  if (serverState === 'waking') label = 'Waking server (free hosting can take about a minute)...';
  else if (serverState === 'loading-model') label = 'Loading detection model...';
  else if (state === 'reconnecting') label = 'Reconnecting...';
  else if (metrics?.state === 'error') label = 'Cannot open video source';
  else if (metrics?.state === 'reconnecting') label = 'Source dropped, reconnecting...';

  return (
    <div className={`relative w-full h-full bg-black ${className}`}>
      {serverState === 'waking' ? null : (
        <img
          ref={imgRef}
          key={attempt}
          src={src}
          alt={alt}
          onLoad={() => setState('live')}
          onError={onError}
          className={`w-full h-full ${fit === 'contain' ? 'object-contain' : 'object-cover'}`}
        />
      )}
      {clean && <canvas ref={canvasRef} className="absolute inset-0 w-full h-full pointer-events-none" />}
      {!live && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-neutral-900/80 animate-pulse text-xs text-neutral-300">
          <div className="h-6 w-6 rounded-full border-2 border-neutral-500 border-t-white animate-spin" />
          <span>{label}</span>
        </div>
      )}
      {live && metrics && (
        <div className="absolute top-11 left-2 rounded bg-black/60 px-2 py-0.5 text-[11px] text-white tabular-nums">
          {metrics.stream_fps} fps video | {metrics.inference_fps} fps detect{metrics.overlay_age_ms != null ? ` | overlay ${Math.round(metrics.overlay_age_ms)} ms old` : ''}
        </div>
      )}
    </div>
  );
}
