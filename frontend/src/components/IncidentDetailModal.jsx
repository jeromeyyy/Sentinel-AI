'use client';

import { useState } from 'react';
import { BACKEND_URL } from '@/lib/constants';

/** Signed links expire. On a load error, ask the backend for a fresh link once, then retry. */
export function useSnapshotSrc(event) {
  const initial = snapshotUrl(event);
  const [src, setSrc] = useState(initial);
  const [tried, setTried] = useState(false);
  const [failed, setFailed] = useState(false);
  const onError = async () => {
    const m = /\/snapshot\/([^?]+)/.exec(event?.snapshot_url || '');
    if (tried || !m) { setFailed(true); return; }
    setTried(true);
    try {
      const r = await fetch(`${BACKEND_URL}/api/snapshot-link/${m[1]}`);
      if (!r.ok) throw new Error('gone');
      setSrc(`${BACKEND_URL}${(await r.json()).snapshot_url}`);
    } catch { setFailed(true); }
  };
  return { src: failed ? null : src, onError };
}

export function snapshotUrl(event) {
  if (!event) return null;
  // snapshot_url is a short-lived signed path issued by the backend; unsigned paths are rejected (403).
  if (event.snapshot_url) return event.snapshot_url.startsWith('data:') ? event.snapshot_url : `${BACKEND_URL}${event.snapshot_url}`;
  return null;
}

/** Thumbnail that opens the incident detail modal. Renders nothing when the event has no snapshot. */
export function SnapshotThumb({ event, onOpen }) {
  const { src: url, onError } = useSnapshotSrc(event);
  if (!url) return null;
  return (
    <button type="button" onClick={onOpen} className="block w-full overflow-hidden rounded-lg border border-border bg-black" title="Open incident details">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={url} alt="Incident snapshot" loading="lazy" className="w-full h-28 object-cover" onError={onError} />
    </button>
  );
}

export default function IncidentDetailModal({ alert, onClose }) {
  const event = alert?.event || alert || {};
  const meta = event.metadata || {};
  const { src: url, onError } = useSnapshotSrc(event);
  const when = event.timestamp ? new Date((event.timestamp < 1e12 ? event.timestamp * 1000 : event.timestamp)).toLocaleString() : 'unknown';
  const heuristic = meta.method || meta.is_trained_classifier === false;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div className="max-w-3xl w-full rounded-xl bg-card border border-border overflow-hidden" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Incident details">
        {url && /* eslint-disable-next-line @next/next/no-img-element */ <img src={url} alt="Incident snapshot" onError={onError} className="w-full max-h-[55vh] object-contain bg-black" />}
        <div className="p-4 space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold">{String(event.event_type || 'incident').replace(/_/g, ' ')}</h3>
            <button onClick={onClose} className="px-3 py-1 rounded bg-muted">Close</button>
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-muted-foreground">
            <span>Camera: <b className="text-foreground">{event.camera_id}</b></span>
            <span>Zone: <b className="text-foreground">{event.zone}</b></span>
            <span>Time: <b className="text-foreground">{when}</b></span>
            <span>Confidence: <b className="text-foreground">{Math.round((event.confidence || 0) * 100)}%</b></span>
          </div>
          {heuristic && <p className="text-xs rounded bg-yellow-500/10 text-yellow-300 p-2">This alert comes from a rule on tracked boxes ({meta.method || 'heuristic'}), not a trained classifier. Review the footage before acting.</p>}
          {Object.keys(meta).length > 0 && <pre className="text-[11px] bg-muted rounded p-2 overflow-auto max-h-32">{JSON.stringify(meta, null, 1)}</pre>}
        </div>
      </div>
    </div>
  );
}
