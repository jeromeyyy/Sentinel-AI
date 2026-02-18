'use client';

import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Settings as SettingsIcon,
  Database,
  Bell,
  Shield,
  Cpu,
  Activity,
  Trash2,
  Download,
  RefreshCw,
  CheckCircle,
  AlertCircle,
  Sun,
  Moon,
} from 'lucide-react';

import { Card, CardHeader, CardTitle, CardContent } from './ui/Card';
import { Button } from './ui/Button';
import { Badge } from './ui/Badge';
import { Input, Select, Checkbox } from './ui/Input';
import { StatusIndicator } from './ui/StatusIndicator';
import { useToast } from './ui/Toast';
import { useTheme } from '../contexts/ThemeContext';

import { BACKEND_URL, MODULES } from '../lib/constants';
import { cn, formatNumber } from '../lib/utils';

export default function SettingsPanel({ cameras = [], incidents = [], systemHealth = {} }) {
  const { theme, toggleTheme } = useTheme();
  const { showSuccess, showError, showInfo } = useToast();

  const [systemHealthState, setSystemHealthState] = useState(systemHealth);
  const [cameraHealth, setCameraHealth] = useState({});

  // Module settings
  const [selectedModule, setSelectedModule] = useState('school');
  const [alertThreshold, setAlertThreshold] = useState('medium');
  const [autoReconnect, setAutoReconnect] = useState(true);
  const [soundAlerts, setSoundAlerts] = useState(false);
  const [notificationEmail, setNotificationEmail] = useState('');

  // System stats
  const [stats, setStats] = useState({
    totalCameras: 0,
    activeCameras: 0,
    totalIncidents: 0,
    storageUsed: '0 MB',
  });

  // Load settings
  useEffect(() => {
    loadSettings();
    updateStats();
  }, [cameras, incidents]);

  useEffect(() => {
    let isActive = true;

    const fetchSystemHealth = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/api/system/health`);
        if (response.ok) {
          const data = await response.json();
          if (isActive) setSystemHealthState(data);
        }
      } catch {
        // Keep last known state
      }
    };

    fetchSystemHealth();
    const interval = setInterval(fetchSystemHealth, 30000);
    return () => {
      isActive = false;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    let isActive = true;

    const fetchCameraHealth = async () => {
      const nextHealth = {};
      for (const cam of cameras) {
        try {
          const response = await fetch(`${BACKEND_URL}/api/camera/${cam.id}/health`);
          nextHealth[cam.id] = response.ok ? (await response.json()) : { status: 'offline' };
        } catch {
          nextHealth[cam.id] = { status: 'offline' };
        }
      }
      if (isActive) setCameraHealth(nextHealth);
    };

    if (cameras.length) {
      fetchCameraHealth();
      const interval = setInterval(fetchCameraHealth, 30000);
      return () => {
        isActive = false;
        clearInterval(interval);
      };
    }
  }, [cameras]);

  const loadSettings = () => {
    // Load from localStorage
    const saved = localStorage.getItem('sentinel_settings');
    if (saved) {
      const settings = JSON.parse(saved);
      setSelectedModule(settings.module || 'school');
      setAlertThreshold(settings.alertThreshold || 'medium');
      setAutoReconnect(settings.autoReconnect !== false);
      setSoundAlerts(settings.soundAlerts || false);
      setNotificationEmail(settings.notificationEmail || '');
    }
  };

  const saveSettings = () => {
    const settings = {
      module: selectedModule,
      alertThreshold,
      autoReconnect,
      soundAlerts,
      notificationEmail,
    };
    localStorage.setItem('sentinel_settings', JSON.stringify(settings));
    showSuccess('Settings saved successfully');

    fetch(`${BACKEND_URL}/api/module`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ module: selectedModule }),
    }).catch(() => {
      showError('Failed to update module on backend');
    });
  };

  const updateStats = () => {
    setStats({
      totalCameras: cameras.length,
      activeCameras: cameras.filter(c => c.active !== false).length,
      totalIncidents: incidents.length,
      storageUsed: `${Math.round(incidents.length * 0.5)} MB`, // Estimated
    });
  };

  const clearAllIncidents = async () => {
    if (!confirm('Are you sure you want to clear all incidents? This cannot be undone.')) {
      return;
    }

    try {
      const response = await fetch(`${BACKEND_URL}/incidents`, {
        method: 'DELETE',
      });

      if (response.ok) {
        showSuccess('All incidents cleared');
        window.location.reload();
      } else {
        showError('Failed to clear incidents');
      }
    } catch (error) {
      showError('Error clearing incidents');
    }
  };

  const exportData = () => {
    const data = {
      cameras,
      incidents: incidents.slice(0, 100), // Limit to 100 most recent
      exportedAt: new Date().toISOString(),
    };

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `sentinelai-export-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);

    showSuccess('Data exported successfully');
  };

  const testWebSocket = () => {
    showInfo('WebSocket connection test initiated');
    // The useWebSocket hook in monitor.js should handle reconnection
  };

  return (
    <div className="space-y-6">
      {/* System Overview */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Total Cameras</p>
                <p className="text-2xl font-bold text-foreground">{stats.totalCameras}</p>
              </div>
              <div className="p-2 bg-blue-500/20 rounded-lg">
                <Activity className="w-5 h-5 text-blue-400" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Active</p>
                <p className="text-2xl font-bold text-green-400">{stats.activeCameras}</p>
              </div>
              <StatusIndicator status="online" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Incidents</p>
                <p className="text-2xl font-bold text-foreground">{formatNumber(stats.totalIncidents)}</p>
              </div>
              <div className="p-2 bg-orange-500/20 rounded-lg">
                <AlertCircle className="w-5 h-5 text-orange-400" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Storage</p>
                <p className="text-2xl font-bold text-foreground">{stats.storageUsed}</p>
              </div>
              <div className="p-2 bg-purple-500/20 rounded-lg">
                <Database className="w-5 h-5 text-purple-400" />
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* General Settings */}
        <Card>
          <CardHeader>
            <CardTitle icon={<SettingsIcon className="w-4 h-4" />}>
              General Settings
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2">Surveillance Module</label>
              <Select
                value={selectedModule}
                onChange={(e) => setSelectedModule(e.target.value)}
              >
                {MODULES.map(mod => (
                  <option key={mod.id} value={mod.id}>
                    {mod.label}
                  </option>
                ))}
              </Select>
              <p className="text-xs text-muted-foreground mt-1">
                Changes the default detection behaviors and zones
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Alert Threshold</label>
              <Select
                value={alertThreshold}
                onChange={(e) => setAlertThreshold(e.target.value)}
              >
                <option value="low">Low (All events)</option>
                <option value="medium">Medium (Important events)</option>
                <option value="high">High (Critical only)</option>
                <option value="critical">Critical (Emergencies)</option>
              </Select>
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Notification Email</label>
              <Input
                type="email"
                value={notificationEmail}
                onChange={(e) => setNotificationEmail(e.target.value)}
                placeholder="security@example.com"
              />
            </div>

            <div className="flex items-center justify-between py-2">
              <div>
                <p className="text-sm font-medium">Auto-reconnect WebSocket</p>
                <p className="text-xs text-muted-foreground">Automatically reconnect on disconnect</p>
              </div>
              <Checkbox
                checked={autoReconnect}
                onChange={(e) => setAutoReconnect(e.target.checked)}
              />
            </div>

            <div className="flex items-center justify-between py-2">
              <div>
                <p className="text-sm font-medium">Sound Alerts</p>
                <p className="text-xs text-muted-foreground">Play sound on new alert</p>
              </div>
              <Checkbox
                checked={soundAlerts}
                onChange={(e) => setSoundAlerts(e.target.checked)}
              />
            </div>

            <Button onClick={saveSettings} className="w-full">
              <CheckCircle className="w-4 h-4 mr-2" />
              Save Settings
            </Button>
          </CardContent>
        </Card>

        {/* Appearance */}
        <Card>
          <CardHeader>
            <CardTitle icon={<Sun className="w-4 h-4" />}>
              Appearance
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-3">Theme</label>
              <div className="grid grid-cols-2 gap-3">
                <button
                  onClick={() => theme === 'dark' && toggleTheme()}
                  className={cn(
                    'p-4 rounded-lg border-2 transition-all',
                    theme === 'light'
                      ? 'border-primary bg-primary/10'
                      : 'border-border hover:border-primary/50'
                  )}
                >
                  <Sun className="w-6 h-6 mx-auto mb-2" />
                  <p className="text-sm font-medium">Light</p>
                </button>
                <button
                  onClick={() => theme === 'light' && toggleTheme()}
                  className={cn(
                    'p-4 rounded-lg border-2 transition-all',
                    theme === 'dark'
                      ? 'border-primary bg-primary/10'
                      : 'border-border hover:border-primary/50'
                  )}
                >
                  <Moon className="w-6 h-6 mx-auto mb-2" />
                  <p className="text-sm font-medium">Dark</p>
                </button>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* System Health */}
        <Card>
          <CardHeader>
            <CardTitle icon={<Cpu className="w-4 h-4" />}>
              System Health
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm">Backend API</span>
                <Badge variant={systemHealthState.status === 'healthy' ? 'success' : 'error'}>
                  {systemHealthState.status || 'Unknown'}
                </Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm">WebSocket</span>
                <Badge variant={systemHealthState.websocket_clients > 0 ? 'success' : 'warning'}>
                  {systemHealthState.websocket_clients || 0} clients
                </Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm">Active Module</span>
                <Badge variant="info">{systemHealthState.module || 'school'}</Badge>
              </div>
            </div>

            <Button onClick={testWebSocket} variant="secondary" className="w-full">
              <RefreshCw className="w-4 h-4 mr-2" />
              Test WebSocket
            </Button>
          </CardContent>
        </Card>

        {/* Camera Worker Status */}
        <Card>
          <CardHeader>
            <CardTitle icon={<Activity className="w-4 h-4" />}>
              Camera Worker Status
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {cameras.length === 0 && (
              <div className="text-sm text-muted-foreground">No cameras configured.</div>
            )}
            {cameras.map((cam) => {
              const health = cameraHealth[cam.id] || { status: 'unknown' };
              return (
                <div key={cam.id} className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-foreground">{cam.name || cam.id}</div>
                    <div className="text-xs text-muted-foreground">{cam.zone}</div>
                  </div>
                  <Badge
                    variant={health.status === 'online' ? 'success' : health.status === 'offline' ? 'error' : 'warning'}
                  >
                    {health.status || 'unknown'}
                  </Badge>
                </div>
              );
            })}
          </CardContent>
        </Card>

        {/* Data Management */}
        <Card>
          <CardHeader>
            <CardTitle icon={<Database className="w-4 h-4" />}>
              Data Management
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="bg-muted rounded-lg p-4 space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Cameras</span>
                <span className="font-medium">{stats.totalCameras}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Incidents</span>
                <span className="font-medium">{formatNumber(stats.totalIncidents)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Estimated Storage</span>
                <span className="font-medium">{stats.storageUsed}</span>
              </div>
            </div>

            <div className="space-y-2">
              <Button onClick={exportData} variant="secondary" className="w-full">
                <Download className="w-4 h-4 mr-2" />
                Export Data
              </Button>
              <Button onClick={clearAllIncidents} variant="ghost" className="w-full text-red-400 hover:text-red-300 hover:bg-red-500/10">
                <Trash2 className="w-4 h-4 mr-2" />
                Clear All Incidents
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* About */}
      <Card>
        <CardHeader>
          <CardTitle icon={<Shield className="w-4 h-4" />}>
            About SentinelAI
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2 text-sm text-muted-foreground">
            <p><strong className="text-foreground">Version:</strong> 1.0.0</p>
            <p><strong className="text-foreground">Backend:</strong> FastAPI + YOLOv8</p>
            <p><strong className="text-foreground">Frontend:</strong> Next.js 14 + React 18</p>
            <p className="pt-4">
              AI-powered school safety monitoring system with real-time threat detection
              and automated alert generation.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
