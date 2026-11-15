'use client';

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { BACKEND_URL } from '@/lib/constants';
import { useBackendStatus, useStreamMetrics } from '@/hooks/useBackendStatus';

export const StreamStatusContext = createContext({ backend: { state: 'ready' }, metrics: {}, health: {}, reportHealth: () => {} });

/** Polls /api/health and /api/metrics once and shares them with every StreamTile below. */
export function StreamStatusProvider({ children }) {
  const backend = useBackendStatus();
  const metrics = useStreamMetrics(backend.state !== 'waking' && !backend.legacy);
  const [health, setHealth] = useState({});   // cameraId -> { status, reason } from /api/camera/{id}/health
  const reportHealth = useCallback((id, h) => setHealth((m) => (m[id]?.status === h.status && m[id]?.reason === h.reason ? m : { ...m, [id]: h })), []);
  return <StreamStatusContext.Provider value={{ backend, metrics, health, reportHealth }}>{children}</StreamStatusContext.Provider>;
}

export const UPLOAD_PERSISTENCE_NOTE =
  'Uploaded videos are stored on the server disk. On free hosting that disk is wiped on every restart or redeploy, so re-upload the video (or use a camera URL) if a camera stops showing video.';

/** Real status per camera: the configured flag AND the server's own source check. */
export function useCameraStatus() {
  const ctx = useContext(StreamStatusContext);
  const isOnline = (camera) => !!camera?.active && ctx.health?.[camera.id]?.status !== 'offline';
  return { isOnline, health: ctx.health, backend: ctx.backend };
}

/** Banner shown when the backend predates /api/health (older build): lists what is unavailable. */
export function LegacyBackendBanner() {
  const { backend } = useContext(StreamStatusContext);
  if (!backend?.legacy) return null;
  return (
    <div role="status" className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
      <strong>Older backend detected (degraded mode).</strong> This server has no /api/health or /api/metrics, so the FPS badge,
      the browser-drawn detection overlay, zone editing and signed snapshot links are unavailable until the updated backend is deployed.
      Video, cameras and incidents still use the old server's endpoints.
    </div>
  );
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
  const legacy = !!ctx.backend?.legacy;
  const health = ctx.health?.[cameraId];
  const sourceOffline = health?.status === 'offline';
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState('connecting');
  const timer = useRef(null);
  const canvasRef = useRef(null);
  const imgRef = useRef(null);

  const useOverlay = clean && !legacy;   // older backends burn boxes into the video and have no /ws/detections
  const src = `${BACKEND_URL}/video/${cameraId}?${useOverlay ? 'clean=1&' : ''}r=${attempt}`;

  useEffect(() => () => clearTimeout(timer.current), []);

  // ask the server whether this camera really has a source; MJPEG placeholder frames also load as "video"
  useEffect(() => {
    let stop = false, t;
    const tick = async () => {
      try {
        const r = await fetch(`${BACKEND_URL}/api/camera/${cameraId}/health`, { cache: 'no-store' });
        const j = await r.json().catch(() => ({}));
        if (!stop && (r.ok || r.status === 404)) ctx.reportHealth(cameraId, { status: r.ok ? j.status : 'offline', reason: j.reason || j.error || '' });
      } catch {}
      if (!stop) t = setTimeout(tick, 10000);
    };
    tick();
    return () => { stop = true; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraId]);

  const onError = () => {
    setState('reconnecting');
    clearTimeout(timer.current);
    const delay = Math.min(1000 * 2 ** Math.min(attempt, 5), 15000);
    timer.current = setTimeout(() => setAttempt((a) => a + 1), delay);
  };

  // canvas overlay (clean mode only)
  useEffect(() => {
    if (!useOverlay) return;
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
  }, [useOverlay, cameraId]);

  const live = state === 'live' && !sourceOffline && (!metrics || metrics.state === 'live' || metrics.state === undefined);
  let label = 'Connecting...';
  if (sourceOffline) label = null;
  else if (serverState === 'waking') label = 'Waking server (free hosting can take about a minute)...';
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
      {useOverlay && <canvas ref={canvasRef} className="absolute inset-0 w-full h-full pointer-events-none" />}
      {sourceOffline && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-neutral-900/95 px-4 text-center text-xs text-neutral-200">
          <span className="text-sm font-medium text-amber-300">Video source unavailable</span>
          <span>{health.reason || 'The server cannot open this camera\'s source.'}</span>
          <span className="text-neutral-400">{UPLOAD_PERSISTENCE_NOTE}</span>
        </div>
      )}
      {!live && !sourceOffline && (
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
