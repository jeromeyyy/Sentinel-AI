'use client';

import { useEffect, useState, useMemo } from 'react';
import { useRouter } from 'next/router';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Maximize2,
  Minimize2,
  Camera,
  AlertTriangle,
  Activity,
  Clock,
  Filter,
  Search,
  Download,
  RefreshCw,
  X,
} from 'lucide-react';

import { DashboardLayout } from '../components/layout';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { StatBox } from '../components/ui/StatBox';
import { StatusIndicator, LiveIndicator } from '../components/ui/StatusIndicator';
import { Input, Select } from '../components/ui/Input';
import { SkeletonCameraGrid, SkeletonTable } from '../components/ui/Skeleton';
import { NoIncidents, NoAlerts, NoCameras, NoSearchResults } from '../components/ui/EmptyState';

import { useWebSocket } from '../hooks/useWebSocket';
import { BACKEND_URL, ZONES, PRIORITY_COLORS, EVENT_LABELS } from '@/lib/constants';
import { cn, formatTimestamp, formatRelativeTime, formatEventType, getAlertKey, getCameraId, getEventType, fetchBackend } from '../lib/utils';

// Import chart components
import AnalyticsCharts from '../components/AnalyticsCharts';
import AlertPopupNew from '../components/AlertPopupNew';
import IncidentTimeline from '../components/IncidentTimeline';

const TAB_TITLES = {
  monitoring: { title: 'Live Monitoring', subtitle: 'Real-time surveillance and threat detection' },
  cameras: { title: 'Camera Management', subtitle: 'Configure and monitor camera feeds' },
  incidents: { title: 'Incident History', subtitle: 'View and filter past security events' },
  analytics: { title: 'Analytics Dashboard', subtitle: 'Insights and trends analysis' },
  settings: { title: 'System Settings', subtitle: 'Configure system preferences' },
};

export default function MonitorPage() {
  const router = useRouter();
  const { tab } = router.query;
  
  const [activeTab, setActiveTab] = useState('monitoring');
  const [cameras, setCameras] = useState([]);
  const [stats, setStats] = useState({ active_cameras: 0, total_incidents: 0 });
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expandedCamera, setExpandedCamera] = useState(null);
  const [highlightedCamera, setHighlightedCamera] = useState(null);

  // WebSocket hook for real-time alerts
  const { 
    status: wsStatus, 
    alerts, 
    incidents, 
    alertCount,
    dismissAlert, 
    markResolved,
    setIncidents,
  } = useWebSocket();

  // Update active tab from URL
  useEffect(() => {
    if (tab && TAB_TITLES[tab]) {
      setActiveTab(tab);
    }
  }, [tab]);

  // Handle tab change
  const handleTabChange = (newTab) => {
    setActiveTab(newTab);
    router.push(`/monitor?tab=${newTab}`, undefined, { shallow: true });
  };

  // Load initial data
  useEffect(() => {
    async function loadData() {
      setLoading(true);
      try {
        const [camerasRes, statsRes, incidentsRes] = await Promise.all([
          fetchBackend(`${BACKEND_URL}/api/cameras`),
          fetchBackend(`${BACKEND_URL}/api/stats`),
          fetchBackend(`${BACKEND_URL}/incidents`),
        ]);

        if (camerasRes.ok) {
          const data = await camerasRes.json();
          setCameras(data.cameras || []);
        }

        if (statsRes.ok) {
          const data = await statsRes.json();
          setStats(data);
        }

        if (incidentsRes.ok) {
          const data = await incidentsRes.json();
          setAnalytics({ 
            totals: data.totals, 
            by_type: data.by_type, 
            by_zone: data.by_zone 
          });
          
          // Set initial incidents sorted by timestamp
          const sortedIncidents = (data.incidents || []).sort((a, b) => {
            const aTs = a.event?.timestamp || 0;
            const bTs = b.event?.timestamp || 0;
            return bTs - aTs;
          });
          setIncidents(sortedIncidents);
        }
      } catch (e) {
        console.error('Failed to load data:', e);
      } finally {
        setLoading(false);
      }
    }

    loadData();
  }, [setIncidents]);

  // Periodic stats refresh
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await fetchBackend(`${BACKEND_URL}/api/stats`);
        if (res.ok) {
          const data = await res.json();
          setStats(data);
        }
      } catch {}
    }, 10000);

    return () => clearInterval(interval);
  }, []);

  // Highlight camera when alert received
  useEffect(() => {
    Object.keys(alerts).forEach(cameraId => {
      setHighlightedCamera(cameraId);
      setTimeout(() => setHighlightedCamera(null), 3000);
    });
  }, [alerts]);

  const tabConfig = TAB_TITLES[activeTab] || TAB_TITLES.monitoring;
  const activeAlertCount = Object.keys(alerts).length;
  const criticalCount = Object.values(alerts).filter(a => a?.priority === 'critical').length;

  return (
    <DashboardLayout
      activeTab={activeTab}
      onTabChange={handleTabChange}
      title={tabConfig.title}
      subtitle={tabConfig.subtitle}
      stats={{
        activeCameras: stats.active_cameras || cameras.length,
        totalIncidents: stats.total_incidents || incidents.length,
        criticalAlerts: criticalCount,
      }}
      alertCount={activeAlertCount}
      wsStatus={wsStatus}
    >
      <AnimatePresence mode="wait">
        {activeTab === 'monitoring' && (
          <MonitoringView
            key="monitoring"
            cameras={cameras}
            alerts={alerts}
            incidents={incidents}
            analytics={analytics}
            loading={loading}
            wsStatus={wsStatus}
            expandedCamera={expandedCamera}
            setExpandedCamera={setExpandedCamera}
            highlightedCamera={highlightedCamera}
            dismissAlert={dismissAlert}
          />
        )}

        {activeTab === 'cameras' && (
          <CamerasView
            key="cameras"
            cameras={cameras}
            loading={loading}
            expandedCamera={expandedCamera}
            setExpandedCamera={setExpandedCamera}
          />
        )}

        {activeTab === 'incidents' && (
          <IncidentsView
            key="incidents"
            incidents={incidents}
            loading={loading}
            markResolved={markResolved}
          />
        )}

        {activeTab === 'analytics' && (
          <AnalyticsView
            key="analytics"
            analytics={analytics}
            incidents={incidents}
            loading={loading}
          />
        )}

        {activeTab === 'settings' && (
          <SettingsView
            key="settings"
            wsStatus={wsStatus}
          />
        )}
      </AnimatePresence>
    </DashboardLayout>
  );
}

// ─── Monitoring View ─────────────────────────────────────────────────────────
function MonitoringView({ 
  cameras, 
  alerts, 
  incidents, 
  analytics,
  loading, 
  wsStatus,
  expandedCamera,
  setExpandedCamera,
  highlightedCamera,
  dismissAlert
}) {
  if (loading) {
    return (
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2">
          <SkeletonCameraGrid count={4} />
        </div>
        <div className="space-y-4">
          <Card className="h-64" />
          <Card className="h-48" />
        </div>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="grid grid-cols-1 xl:grid-cols-3 gap-6"
    >
      {/* Camera Grid */}
      <div className="xl:col-span-2">
        <CameraGrid
          cameras={cameras}
          alerts={alerts}
          expandedCamera={expandedCamera}
          setExpandedCamera={setExpandedCamera}
          highlightedCamera={highlightedCamera}
        />
      </div>

      {/* Right Panel - Alerts & Quick Analytics */}
      <div className="space-y-6">
        {/* Active Alerts Panel */}
        <Card className="overflow-hidden">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between bg-gradient-to-r from-red-500/10 via-transparent to-transparent">
            <CardTitle icon={<span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />}>
              Active Alerts
            </CardTitle>
            <Badge variant={Object.keys(alerts).length > 0 ? 'destructive' : 'outline'} size="sm">
              {Object.keys(alerts).length} live
            </Badge>
          </div>
          <CardContent className="max-h-[50vh] overflow-y-auto p-4">
            {Object.keys(alerts).length > 0 ? (
              <div className="space-y-3">
                {Object.entries(alerts).map(([cameraId, alert]) => (
                  <AlertPopupNew
                    key={getAlertKey(alert)}
                    alert={alert}
                    onDismiss={() => dismissAlert(cameraId)}
                  />
                ))}
              </div>
            ) : (
              <NoAlerts />
            )}
          </CardContent>
        </Card>

        {/* Quick Stats */}
        <div className="grid grid-cols-2 gap-3">
          <StatBox
            label="Active Cameras"
            value={cameras.filter(c => c.active).length}
            icon={<Camera className="w-5 h-5" />}
            color="blue"
            size="sm"
            className="bg-gradient-to-br from-blue-500/10 via-transparent to-transparent"
          />
          <StatBox
            label="Incidents Today"
            value={incidents.length}
            icon={<AlertTriangle className="w-5 h-5" />}
            color="orange"
            size="sm"
            className="bg-gradient-to-br from-orange-500/10 via-transparent to-transparent"
          />
        </div>

        {/* Mini Analytics */}
        {analytics && (
          <Card className="overflow-hidden">
            <CardHeader className="relative">
              <div className="absolute inset-0 bg-gradient-to-br from-purple-500/10 via-pink-500/5 to-transparent" />
              <CardTitle icon={<Activity className="w-4 h-4 text-purple-400" />} className="relative">
                Quick Stats
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {Object.entries(analytics.by_type || {}).slice(0, 4).map(([type, count]) => (
                  <div key={type} className="flex items-center justify-between p-2 rounded-lg hover:bg-muted/50 transition-colors">
                    <span className="text-sm text-muted-foreground">
                      {formatEventType(type)}
                    </span>
                    <Badge variant="outline" size="sm" className="border-purple-500/30 text-purple-400">{count}</Badge>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Fullscreen Camera Modal */}
      <AnimatePresence>
        {expandedCamera && (
          <FullscreenCamera
            camera={cameras.find(c => c.id === expandedCamera)}
            onClose={() => setExpandedCamera(null)}
          />
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ─── Camera Grid ─────────────────────────────────────────────────────────────
function CameraGrid({ cameras, alerts, expandedCamera, setExpandedCamera, highlightedCamera }) {
  if (cameras.length === 0) {
    return (
      <Card>
        <CardContent>
          <NoCameras onAdd={() => window.location.href = '/'} />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {cameras.map((camera) => {
        const hasAlert = !!alerts[camera.id];
        const isHighlighted = highlightedCamera === camera.id;
        const zone = ZONES.find(z => z.id === camera.zone);
        
        return (
          <motion.div
            key={camera.id}
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className={cn(
              'camera-feed group relative aspect-video rounded-xl overflow-hidden',
              'border border-border bg-card',
              hasAlert && 'camera-feed alert border-red-500',
              isHighlighted && 'ring-2 ring-red-500 ring-offset-2 ring-offset-background'
            )}
          >
            {/* Video Feed */}
            <img
              src={`${BACKEND_URL}/video/${camera.id}`}
              alt={camera.name}
              className="w-full h-full object-cover"
              onError={(e) => {
                e.target.src = '/placeholder-camera.svg';
              }}
            />

            {/* Top Overlay */}
            <div className="camera-overlay">
              <div className="flex items-center gap-2">
                <LiveIndicator />
                <Badge variant={camera.active ? 'online' : 'offline'} size="sm" dot>
                  {camera.active ? 'Online' : 'Offline'}
                </Badge>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="outline" size="sm">
                  {zone?.label || camera.zone}
                </Badge>
                <button
                  onClick={() => setExpandedCamera(camera.id)}
                  className="p-1.5 rounded-lg bg-black/50 text-white hover:bg-black/70 transition-colors opacity-0 group-hover:opacity-100"
                >
                  <Maximize2 className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Bottom Overlay */}
            <div className="camera-overlay-bottom">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-white">{camera.name}</span>
                {zone?.model && (
                  <span className="text-[10px] text-white/70">Model: {zone.model}</span>
                )}
              </div>
            </div>

            {/* Alert Badge */}
            {hasAlert && (
              <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2">
                <div className="px-4 py-2 bg-red-500/90 rounded-lg text-white font-medium text-sm animate-pulse">
                  {formatEventType(getEventType(alerts[camera.id]))}
                </div>
              </div>
            )}
          </motion.div>
        );
      })}
    </div>
  );
}

// ─── Fullscreen Camera ───────────────────────────────────────────────────────
function FullscreenCamera({ camera, onClose }) {
  if (!camera) return null;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.9 }}
        animate={{ scale: 1 }}
        exit={{ scale: 0.9 }}
        className="relative max-w-6xl w-full aspect-video rounded-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <img
          src={`${BACKEND_URL}/video/${camera.id}`}
          alt={camera.name}
          className="w-full h-full object-contain bg-black"
        />
        
        <div className="absolute top-4 left-4 flex items-center gap-3">
          <LiveIndicator />
          <span className="text-white font-medium">{camera.name}</span>
        </div>
        
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-2 rounded-lg bg-white/10 text-white hover:bg-white/20 transition-colors"
        >
          <Minimize2 className="w-5 h-5" />
        </button>
      </motion.div>
    </motion.div>
  );
}

// ─── Cameras View ────────────────────────────────────────────────────────────
function CamerasView({ cameras, loading, expandedCamera, setExpandedCamera }) {
  if (loading) {
    return <SkeletonCameraGrid count={6} />;
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="space-y-6"
    >
      {/* Header */}
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-2xl flex items-center justify-center shadow-lg shadow-blue-500/25">
          <Camera className="w-6 h-6 text-white" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-foreground">Camera Management</h2>
          <p className="text-sm text-muted-foreground">{cameras.length} cameras configured</p>
        </div>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {cameras.map((camera) => {
          const zone = ZONES.find(z => z.id === camera.zone);
          
          return (
            <Card key={camera.id} hover className="overflow-hidden">
              <div className="aspect-video relative">
                <img
                  src={`${BACKEND_URL}/video/${camera.id}`}
                  alt={camera.name}
                  className="w-full h-full object-cover"
                />
                <div className="absolute top-2 right-2">
                  <Badge variant={camera.active ? 'online' : 'offline'} size="sm" dot>
                    {camera.active ? 'Online' : 'Offline'}
                  </Badge>
                </div>
              </div>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-medium text-foreground">{camera.name}</h3>
                    <p className="text-sm text-muted-foreground">{zone?.label || camera.zone}</p>
                  </div>
                  <Button 
                    variant="ghost" 
                    size="icon"
                    onClick={() => setExpandedCamera(camera.id)}
                  >
                    <Maximize2 className="w-4 h-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <AnimatePresence>
        {expandedCamera && (
          <FullscreenCamera
            camera={cameras.find(c => c.id === expandedCamera)}
            onClose={() => setExpandedCamera(null)}
          />
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ─── Incidents View ──────────────────────────────────────────────────────────
function IncidentsView({ incidents, loading, markResolved }) {
  if (loading) {
    return <SkeletonTable rows={10} cols={5} />;
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="space-y-6"
    >
      {/* Header */}
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 bg-gradient-to-br from-orange-500 to-red-600 rounded-2xl flex items-center justify-center shadow-lg shadow-orange-500/25">
          <AlertTriangle className="w-6 h-6 text-white" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-foreground">Incident Timeline</h2>
          <p className="text-sm text-muted-foreground">Review and manage security events</p>
        </div>
        <div className="ml-auto">
          <Badge variant="outline" className="text-base px-4 py-2">{incidents.length} Total</Badge>
        </div>
      </div>

      <Card className="overflow-hidden">
        <CardContent className="p-0">
          <IncidentTimeline 
            incidents={incidents} 
            onResolve={markResolved}
          />
        </CardContent>
      </Card>
    </motion.div>
  );
}

// ─── Analytics View ──────────────────────────────────────────────────────────
function AnalyticsView({ analytics, incidents, loading }) {
  if (loading) {
    return (
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="h-80" />
        <Card className="h-80" />
        <Card className="h-64 lg:col-span-2" />
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="space-y-6"
    >
      {/* Header */}
      <div className="flex items-center gap-4 mb-2">
        <div className="w-12 h-12 bg-gradient-to-br from-cyan-500 to-blue-600 rounded-2xl flex items-center justify-center shadow-lg shadow-cyan-500/25">
          <Activity className="w-6 h-6 text-white" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-foreground">Analytics Dashboard</h2>
          <p className="text-sm text-muted-foreground">Insights and performance metrics</p>
        </div>
      </div>

      <AnalyticsCharts 
        analytics={analytics} 
        incidents={incidents}
      />
    </motion.div>
  );
}

// ─── Settings View ───────────────────────────────────────────────────────────
function SettingsView({ wsStatus }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="max-w-3xl space-y-6"
    >
      {/* Header */}
      <div className="flex items-center gap-4 mb-8">
        <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl flex items-center justify-center shadow-lg shadow-blue-500/25">
          <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </div>
        <div>
          <h2 className="text-xl font-bold text-foreground">System Settings</h2>
          <p className="text-sm text-muted-foreground">Configure your security monitoring system</p>
        </div>
      </div>

      {/* Connection Status Card */}
      <Card className="overflow-hidden">
        <div className="p-6 bg-gradient-to-r from-green-500/10 via-transparent to-transparent border-b border-border">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 bg-green-500/20 rounded-xl flex items-center justify-center">
                <Activity className="w-5 h-5 text-green-400" />
              </div>
              <div>
                <h3 className="font-semibold text-foreground">Connection Status</h3>
                <p className="text-sm text-muted-foreground">Real-time system connectivity</p>
              </div>
            </div>
            <StatusIndicator status={wsStatus} size="lg" glow />
          </div>
        </div>
        <CardContent className="p-0 divide-y divide-border">
          <SettingRow
            icon={<Activity className="w-4 h-4" />}
            label="WebSocket"
            description="Live event streaming"
            value={<Badge variant={wsStatus === 'connected' ? 'online' : 'offline'} size="sm" dot>{wsStatus}</Badge>}
          />
          <SettingRow
            icon={<Clock className="w-4 h-4" />}
            label="Polling Interval"
            description="Stats refresh rate"
            value={<Badge variant="outline" size="sm">10 seconds</Badge>}
          />
        </CardContent>
      </Card>

      {/* API Configuration Card */}
      <Card className="overflow-hidden">
        <div className="p-6 bg-gradient-to-r from-blue-500/10 via-transparent to-transparent border-b border-border">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 bg-blue-500/20 rounded-xl flex items-center justify-center">
              <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2" />
              </svg>
            </div>
            <div>
              <h3 className="font-semibold text-foreground">API Configuration</h3>
              <p className="text-sm text-muted-foreground">Backend connection settings</p>
            </div>
          </div>
        </div>
        <CardContent className="p-0 divide-y divide-border">
          <SettingRow
            icon={<svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9" /></svg>}
            label="Backend URL"
            description="API endpoint for all requests"
            value={<code className="text-xs bg-blue-500/10 text-blue-400 px-3 py-1.5 rounded-lg font-mono">{BACKEND_URL}</code>}
          />
          <SettingRow
            icon={<svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>}
            label="Version"
            description="Current system version"
            value={<Badge variant="outline" size="sm">v1.0.0</Badge>}
          />
        </CardContent>
      </Card>

      {/* Theme Card */}
      <Card className="overflow-hidden">
        <div className="p-6 bg-gradient-to-r from-purple-500/10 via-transparent to-transparent border-b border-border">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 bg-purple-500/20 rounded-xl flex items-center justify-center">
              <svg className="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
              </svg>
            </div>
            <div>
              <h3 className="font-semibold text-foreground">Appearance</h3>
              <p className="text-sm text-muted-foreground">Customize the look and feel</p>
            </div>
          </div>
        </div>
        <CardContent className="p-0 divide-y divide-border">
          <SettingRow
            icon={<svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" /></svg>}
            label="Theme"
            description="Interface color scheme"
            value={<Badge className="bg-purple-500/10 text-purple-400 border-purple-500/20" size="sm">Dark Mode</Badge>}
          />
        </CardContent>
      </Card>

      {/* Footer */}
      <div className="text-center pt-6">
        <p className="text-xs text-muted-foreground">
          SentinelAI School Safety System — Powered by YOLOv8
        </p>
      </div>
    </motion.div>
  );
}

function SettingRow({ icon, label, description, value }) {
  return (
    <div className="flex items-center justify-between px-6 py-4 hover:bg-muted/30 transition-colors">
      <div className="flex items-center gap-4">
        {icon && <span className="text-muted-foreground">{icon}</span>}
        <div>
          <div className="text-sm font-medium text-foreground">{label}</div>
          <div className="text-xs text-muted-foreground">{description}</div>
        </div>
      </div>
      {value}
    </div>
  );
}

