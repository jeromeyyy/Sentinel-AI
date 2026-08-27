import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export async function GET() {
  const apiBase = process.env.NEXT_PUBLIC_API_BASE;
  
  if (!apiBase) {
    return NextResponse.json({ error: 'Backend URL not configured (NEXT_PUBLIC_API_BASE)' }, { status: 500 });
  }
  
  const backendUrl = `${apiBase}/camera_feed`;

  try {
    const response = await fetch(backendUrl, {
      headers: {
        'ngrok-skip-browser-warning': 'true',
      },
    });
    if (!response.ok) {
      return new Response('Backend camera_feed error', { status: response.status });
    }

    const arrayBuffer = await response.arrayBuffer();
    return new Response(arrayBuffer, {
      headers: {
        'Content-Type': 'image/jpeg',
      },
    });
  } catch (err) {
    return new Response('Unable to reach backend camera_feed', { status: 502 });
  }
}
