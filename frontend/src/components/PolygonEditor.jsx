'use client';

import { useContext, useEffect, useRef, useState } from 'react';
import { BACKEND_URL } from '@/lib/constants';
import { StreamStatusContext } from '@/components/StreamTile';

/**
 * Draw / edit the detection zone for a camera. Click to add corners, "Save zone" posts the polygon as
 * 0..1 fractions of the video frame (POST /api/camera/{id}/polygon). Empty zone = whole frame.
 * Sits on top of a video shown with object-fit: contain, so clicks are mapped into the visible video rect.
 */
export default function PolygonEditor({ cameraId }) {
  const ctx = useContext(StreamStatusContext);
  const frame = ctx.metrics?.[cameraId]?.frame_size || [16, 9];
  const [editing, setEditing] = useState(false);
  const [pts, setPts] = useState([]);   // normalised
  const [saved, setSaved] = useState([]);
  const [msg, setMsg] = useState('');
  const ref = useRef(null);
  const legacy = !!ctx.backend?.legacy;

  useEffect(() => {
    if (legacy) return;
    fetch(`${BACKEND_URL}/api/camera/${cameraId}/polygon`).then((r) => r.json()).then((j) => { setSaved(j.polygon || []); setPts(j.polygon || []); }).catch(() => {});
  }, [cameraId, legacy]);

  const rect = () => {
    const el = ref.current; if (!el) return null;
    const w = el.clientWidth, h = el.clientHeight, [fw, fh] = frame;
    const s = Math.min(w / fw, h / fh), vw = fw * s, vh = fh * s;
    return { w, h, vw, vh, ox: (w - vw) / 2, oy: (h - vh) / 2 };
  };

  useEffect(() => {
    const c = ref.current; const r = rect(); if (!c || !r) return;
    c.width = r.w; c.height = r.h;
    const g = c.getContext('2d'); g.clearRect(0, 0, r.w, r.h);
    const list = editing ? pts : saved;
    if (!list.length) return;
    g.beginPath();
    list.forEach(([x, y], i) => { const px = r.ox + x * r.vw, py = r.oy + y * r.vh; i ? g.lineTo(px, py) : g.moveTo(px, py); });
    if (list.length > 2) g.closePath();
    g.strokeStyle = editing ? '#facc15' : '#34d399'; g.lineWidth = 2; g.stroke();
    if (list.length > 2) { g.fillStyle = editing ? 'rgba(250,204,21,0.15)' : 'rgba(52,211,153,0.10)'; g.fill(); }
    if (editing) list.forEach(([x, y]) => { g.beginPath(); g.arc(r.ox + x * r.vw, r.oy + y * r.vh, 5, 0, 7); g.fillStyle = '#facc15'; g.fill(); });
  });

  const onClick = (e) => {
    if (!editing) return;
    const r = rect(); const b = ref.current.getBoundingClientRect();
    const x = (e.clientX - b.left - r.ox) / r.vw, y = (e.clientY - b.top - r.oy) / r.vh;
    if (x < 0 || x > 1 || y < 0 || y > 1) return;
    setPts((p) => [...p, [Math.round(x * 1e4) / 1e4, Math.round(y * 1e4) / 1e4]]);
  };

  const save = async (list) => {
    setMsg('Saving...');
    try {
      const res = await fetch(`${BACKEND_URL}/api/camera/${cameraId}/polygon`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ polygon: list }) });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error || res.status);
      setSaved(list); setPts(list); setEditing(false); setMsg(list.length ? 'Zone saved' : 'Zone cleared (whole frame)');
    } catch (err) { setMsg(`Save failed: ${err.message}`); }
  };

  if (legacy) {
    return <div className="absolute bottom-4 left-4 rounded bg-black/70 px-3 py-1.5 text-xs text-amber-200">Zone editing needs the updated backend (this server is an older build).</div>;
  }

  return (
    <>
      <canvas ref={ref} onClick={onClick} className={`absolute inset-0 w-full h-full ${editing ? 'cursor-crosshair' : 'pointer-events-none'}`} />
      <div className="absolute bottom-4 left-4 flex items-center gap-2 text-xs">
        {!editing ? (
          <button className="px-3 py-1.5 rounded bg-black/70 text-white hover:bg-black" onClick={() => { setEditing(true); setPts(saved); setMsg('Click the video to add corners (3 or more)'); }}>Edit zone</button>
        ) : (
          <>
            <button className="px-3 py-1.5 rounded bg-emerald-600 text-white disabled:opacity-40" disabled={pts.length < 3} onClick={() => save(pts)}>Save zone</button>
            <button className="px-3 py-1.5 rounded bg-black/70 text-white" onClick={() => setPts((p) => p.slice(0, -1))}>Undo</button>
            <button className="px-3 py-1.5 rounded bg-black/70 text-white" onClick={() => save([])}>Whole frame</button>
            <button className="px-3 py-1.5 rounded bg-black/70 text-white" onClick={() => { setEditing(false); setPts(saved); setMsg(''); }}>Cancel</button>
          </>
        )}
        {msg && <span className="px-2 py-1 rounded bg-black/70 text-white">{msg}</span>}
      </div>
    </>
  );
}
