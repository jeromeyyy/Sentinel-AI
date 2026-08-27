import { redirect } from 'next/navigation';
import { BACKEND_URL } from '@/lib/constants';

export const dynamic = 'force-dynamic';

export async function GET() {
  const backendUrl = BACKEND_URL.replace('/event', '');
  redirect(`${backendUrl}/auth/google/login`);
}
