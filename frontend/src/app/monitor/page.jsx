import { Suspense } from 'react';
import MonitorClient from './MonitorClient';

export const metadata = {
  title: 'Monitoring Dashboard - SentinelAI',
  description: 'Real-time AI-Powered School Safety Monitoring System',
};

export default function MonitorPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-sm text-muted-foreground">Loading monitoring dashboard...</div>
      </div>
    }>
      <MonitorClient />
    </Suspense>
  );
}
