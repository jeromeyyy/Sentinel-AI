export default async function handler(req, res) {
  // Simpler proxy: fetch a single JPEG frame from the backend
  // and return it. The frontend polls this endpoint frequently
  // to simulate a live feed.
  
  // ─── API Configuration ───────────────────────────────────────────────────────
  const apiBase = process.env.NEXT_PUBLIC_API_BASE;
  
  if (!apiBase) {
    res.status(500).json({ error: 'Backend URL not configured (NEXT_PUBLIC_API_BASE)' });
    return;
  }
  
  const backendUrl = `${apiBase}/camera_feed`;

  try {
    const response = await fetch(backendUrl);
    if (!response.ok) {
      res.status(response.status).send('Backend camera_feed error');
      return;
    }

    // We only care about the latest JPEG chunk, so just read it
    // as an ArrayBuffer and send it through.
    const buffer = Buffer.from(await response.arrayBuffer());
    res.setHeader('Content-Type', 'image/jpeg');
    res.send(buffer);
  } catch (err) {
    res.status(502).send('Unable to reach backend camera_feed');
  }
}
