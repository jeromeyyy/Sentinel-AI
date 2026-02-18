'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import { LogIn, Shield, AlertCircle } from 'lucide-react';

import { Card, CardContent } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { BACKEND_URL } from '../lib/constants';

export default function LoginPage() {
  const router = useRouter();
  const [authEnabled, setAuthEnabled] = useState(false);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    const enabled = process.env.NEXT_PUBLIC_AUTH_ENABLED === 'true';
    setAuthEnabled(enabled);

    async function checkAuth() {
      if (!enabled) {
        setChecking(false);
        return;
      }
      try {
        const res = await fetch(`${BACKEND_URL}/auth/me`, { credentials: 'include' });
        if (res.ok) {
          router.replace('/');
          return;
        }
      } catch {
        // Ignore
      }
      setChecking(false);
    }

    checkAuth();
  }, [router]);

  if (checking) {
    return <div className="min-h-screen bg-background" />;
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6">
      <Card className="max-w-md w-full">
        <CardContent className="p-8 space-y-6">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center">
              <Shield className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-foreground">SentinelAI</h1>
              <p className="text-sm text-muted-foreground">Sign in to continue</p>
            </div>
          </div>

          {!authEnabled && (
            <div className="p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/30 text-sm text-yellow-400 flex items-start gap-2">
              <AlertCircle className="w-4 h-4 mt-0.5" />
              Authentication is disabled. Set `NEXT_PUBLIC_AUTH_ENABLED=true` and backend OAuth env vars.
            </div>
          )}

          <Button
            onClick={() => window.location.href = `${BACKEND_URL}/auth/google/login`}
            className="w-full"
            disabled={!authEnabled}
          >
            <LogIn className="w-4 h-4 mr-2" />
            Sign in with Google
          </Button>

          <Button
            variant="ghost"
            onClick={() => router.push('/')}
            className="w-full"
          >
            Back to Landing
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
