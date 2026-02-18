import { useEffect, useState } from 'react';
import AlertPopup from '../components/AlertPopup';
import AnalyticsPanel from '../components/AnalyticsPanel';
import IncidentList from '../components/IncidentList';
import MultiCameraGrid from '../components/MultiCameraGrid';

// ─── API Configuration ───────────────────────────────────────────────────────
// For local development, uncomment the line below:
// const BACKEND_URL = 'http://localhost:8000';

// For production (Vercel + Render), use environment variable:
const BACKEND_URL = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';

// WebSocket URL (derived from API base)
const getWsUrl = () => {
  const base = BACKEND_URL;
  // For local development, uncomment: return 'ws://localhost:8000/ws/alerts';
  if (base.startsWith('https://')) {
    return base.replace('https://', 'wss://') + '/ws/alerts';
  }
  return base.replace('http://', 'ws://') + '/ws/alerts';
};

export default function Monitor() {
  const [activeAlertsByCamera, setActiveAlertsByCamera] = useState({});
  const [analytics, setAnalytics] = useState(null);
  const [incidentList, setIncidentList] = useState([]);
  const [stats, setStats] = useState({});
  const [activeTab, setActiveTab] = useState('monitoring');
  const [wsStatus, setWsStatus] = useState('connecting');
  const [alertCount, setAlertCount] = useState(0);

  const getAlertKey = (alertObj) => {
    const event = alertObj?.event || alertObj || {};
    return event.event_id || `${event.camera_id || 'cam'}_${event.event_type || 'event'}_${event.timestamp || Date.now()}`;
  };

  const getCameraId = (alertObj) => {
    const event = alertObj?.event || alertObj || {};
    return event.camera_id || alertObj?.camera_id || 'unknown_camera';
  };

  const getEventType = (alertObj) => {
    const event = alertObj?.event || alertObj || {};
    return event.event_type || alertObj?.event_type || 'unknown_event';
  };

  const dismissAlert = (cameraId) => {
    setActiveAlertsByCamera((prev) => {
      const next = { ...prev };
      delete next[cameraId];
      return next;
    });
  };

  // WebSocket subscription - PRIMARY real-time source for incidents
  // Connects once, handles reconnection, appends new incidents to timeline
  useEffect(() => {
    let ws;
    let reconnectTimeout;

    const connect = () => {
      const wsUrl = getWsUrl();
      console.log('[WS_CONNECT_ATTEMPT] url=' + wsUrl);
      ws = new WebSocket(wsUrl);
      
      ws.onopen = () => {
        console.log('[WS_CONNECTED] ready for alerts');
        setWsStatus('connected');
      };

      ws.onmessage = (event) => {
        try {
          // STEP 2: RAW PAYLOAD LOGGING before parsing
          console.log('[WS_RAW_MESSAGE]', event.data?.substring?.(0, 200));
          
          const data = JSON.parse(event.data);
          
          // STEP 3: FULL SCHEMA INSPECTION
          console.log('[WS_PAYLOAD_STRUCTURE]', {
            has_id: !!data.id,
            has_alert: !!data.alert,
            has_event: !!data.event,
            keys: Object.keys(data),
            event_type: data.event?.event_type || 'unknown',
            event_id: data.event?.event_id || data.id || data.msg,
            camera_id: data.event?.camera_id,
            timestamp: data.event?.timestamp,
            timestamp_ms: data.event?.timestamp && data.event.timestamp < 1e12 ? data.event.timestamp * 1000 : data.event?.timestamp,
          });
          
          console.log('[WS_MESSAGE_RX]', {
            has_alert: !!data.alert,
            has_event: !!data.event,
            has_id: !!data.id,
            event_type: data.event?.event_type || data.alert?.event?.event_type || 'unknown',
            event_id: data.event?.event_id || data.alert?.event?.event_id || data.id || data.msg,
            camera_id: data.event?.camera_id || data.alert?.event?.camera_id,
          });

          if (data.alert || data.event) {
            // STEP 4: SCHEMA VALIDATION - ensure expected fields exist
            const nextAlert = data.alert || data;
            const eventObj = data.event || {};
            const incident_id = data.id || data.event?.event_id || 'unknown';
            
            const cameraId = getCameraId(nextAlert);
            const nextEventType = getEventType(nextAlert);
            const nextEventId = getAlertKey(nextAlert);
            
            console.log('[WS_EXTRACTED_FIELDS]', {
              incident_id,
              cameraId,
              nextEventType,
              nextEventId,
              has_timestamp: !!eventObj.timestamp,
              timestamp_value: eventObj.timestamp,
            });

            console.log('[ALERT_PROCESS]', {
              camera_id: cameraId,
              event_type: nextEventType,
              event_id: nextEventId,
            });

            setActiveAlertsByCamera((prev) => {
              const current = prev[cameraId];
              if (current) {
                const currentEventType = getEventType(current);
                const currentEventId = getAlertKey(current);

                // Ignore duplicates: same camera + same event type (or exact same event id)
                if (currentEventType === nextEventType || currentEventId === nextEventId) {
                  console.log('[ALERT_DUPLICATE_SUPPRESSED]', {
                    reason: currentEventType === nextEventType ? 'same_type' : 'same_id',
                    camera_id: cameraId,
                    event_type: nextEventType,
                  });
                  return prev;
                }
              }

              // Replace alert for this camera only when event changes
              console.log('[ALERT_DISPLAYED]', {
                camera_id: cameraId,
                event_type: nextEventType,
                priority: nextAlert.priority || 'medium',
              });
              return {
                ...prev,
                [cameraId]: nextAlert,
              };
            });
            
            // STEP 7: MERGE INTO INCIDENTS TIMELINE (REAL-TIME UPDATE)
            // Build incident object matching backend /incidents API format
            const incident_obj = {
              id: incident_id,
              event: eventObj,
              alert: nextAlert
            };
            
            console.log('[INCIDENT_MERGE]', {
              incident_id,
              event_type: nextEventType,
              will_add_to_timeline: true,
            });
            
            // Add to incidents list at the top (most recent first)
            setIncidentList((prev) => {
              // Use event_id as primary deduplication key
              const eventId = eventObj.event_id || incident_id;
              
              // Check if this incident already exists (by event_id or id)
              const exists = prev.some(inc => 
                inc.event?.event_id === eventId || 
                inc.id === incident_id
              );
              
              if (exists) {
                console.log('[INCIDENT_DUPLICATE_PREVENTED]', {
                  event_id: eventId,
                  incident_id,
                  reason: 'already_in_timeline'
                });
                return prev;
              }
              
              console.log('[INCIDENT_REALTIME_ADDED]', {
                event_id: eventId,
                incident_id,
                event_type: nextEventType,
                total_incidents: prev.length + 1
              });
              
              // Add new incident to the beginning of array (most recent first)
              const updated = [incident_obj, ...prev];
              
              // Keep only last 1000 incidents to prevent memory issues
              if (updated.length > 1000) {
                return updated.slice(0, 1000);
              }
              
              return updated;
            });
            
            setAlertCount((c) => c + 1);
          }
        } catch (e) {
          console.error('[WS_PARSE_ERROR]', {
            error: e.message,
            raw_data: event.data?.substring?.(0, 100),
          });
        }
      };

      ws.onerror = (error) => {
        console.error('[WS_ERROR]', {
          error: error?.message || 'unknown',
          readyState: ws?.readyState,
        });
        setWsStatus('error');
      };

      ws.onclose = () => {
        console.log('[WS_CLOSED] reconnecting in 3s');
        setWsStatus('disconnected');
        reconnectTimeout = setTimeout(connect, 3000);
      };
    };

    connect();
    return () => {
      ws?.close();
      clearTimeout(reconnectTimeout);
    };
  }, []);

  // Initial data load (incidents only loaded once)
  useEffect(() => {
    async function initialLoad() {
      try {
        console.log('[INITIAL_LOAD] Fetching incidents and stats');
        const [incidentsRes, statsRes] = await Promise.all([
          fetch(`${BACKEND_URL}/incidents`),
          fetch(`${BACKEND_URL}/api/stats`),
        ]);
        
        if (incidentsRes.ok) {
          const data = await incidentsRes.json();
          setAnalytics({ totals: data.totals, by_type: data.by_type, by_zone: data.by_zone });
          
          // INITIAL LOAD ONLY - set initial incidents from API
          let apiIncidents = data.incidents || [];
          
          // Sort by timestamp descending (most recent first)
          apiIncidents = apiIncidents.sort((a, b) => {
            const aTs = a.event?.timestamp || 0;
            const bTs = b.event?.timestamp || 0;
            return bTs - aTs;
          });
          
          console.log('[INITIAL_INCIDENTS_LOADED]', {
            count: apiIncidents.length,
            source: 'API initial load (sorted by timestamp)'
          });
          setIncidentList(apiIncidents);
        }
        
        if (statsRes.ok) {
          const statsData = await statsRes.json();
          setStats(statsData);
        }
      } catch (e) {
        console.error('[INITIAL_LOAD_ERROR]', e);
      }
    }
    
    initialLoad();
  }, []);
  
  // Periodic stats updates only (no incidents polling)
  useEffect(() => {
    async function updateStats() {
      try {
        const statsRes = await fetch(`${BACKEND_URL}/api/stats`);
        if (statsRes.ok) {
          const statsData = await statsRes.json();
          setStats(statsData);
          console.log('[STATS_UPDATED]', 'periodic update');
        }
      } catch (e) {
        console.error('[STATS_UPDATE_ERROR]', e);
      }
    }
    
    // Update stats every 10 seconds (less aggressive)
    const statsInterval = setInterval(updateStats, 10000);
    return () => clearInterval(statsInterval);
  }, []);

  const sidebarItems = [
    { id: 'monitoring', icon: '📹', label: 'Live Monitoring' },
    { id: 'incidents', icon: '⚠️', label: 'Incidents' },
    { id: 'analytics', icon: '📊', label: 'Analytics' },
    { id: 'settings', icon: '⚙️', label: 'Settings' },
  ];

  return (
    <div className="min-h-screen bg-[#0f1419] flex">
      {/* Sidebar */}
      <aside className="w-64 bg-[#1a1f2e] border-r border-[#2f3542] flex flex-col">
        {/* Logo */}
        <div className="p-4 border-b border-[#2f3542]">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center">
              <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
            </div>
            <div>
              <div className="text-white font-semibold">SentinelAI</div>
              <div className="text-xs text-gray-400">School Safety</div>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 py-4">
          {sidebarItems.map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-all ${
                activeTab === item.id
                  ? 'bg-[#242b3d] text-blue-400 border-l-3 border-blue-500'
                  : 'text-gray-400 hover:bg-[#242b3d] hover:text-white'
              }`}
            >
              <span className="text-xl">{item.icon}</span>
              <span className="text-sm font-medium">{item.label}</span>
            </button>
          ))}
        </nav>

        {/* Connection Status */}
        <div className="p-4 border-t border-[#2f3542]">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${
              wsStatus === 'connected' ? 'bg-green-500' : 
              wsStatus === 'connecting' ? 'bg-yellow-500 animate-pulse' : 'bg-red-500'
            }`} />
            <span className="text-xs text-gray-400 capitalize">{wsStatus}</span>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col">
        {/* Top Bar */}
        <header className="bg-[#1a1f2e] border-b border-[#2f3542] px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-semibold text-white">
                {activeTab === 'monitoring' && 'Live Monitoring'}
                {activeTab === 'incidents' && 'Incident History'}
                {activeTab === 'analytics' && 'Analytics Dashboard'}
                {activeTab === 'settings' && 'Settings'}
              </h1>
              <p className="text-sm text-gray-400">Real-time surveillance and threat detection</p>
            </div>
            
            <div className="flex items-center gap-6">
              {/* Quick Stats */}
              <div className="flex items-center gap-4">
                <div className="text-center">
                  <div className="text-2xl font-bold text-white">{stats.active_cameras || 0}</div>
                  <div className="text-[10px] text-gray-400 uppercase">Active Cameras</div>
                </div>
                <div className="w-px h-10 bg-[#2f3542]" />
                <div className="text-center">
                  <div className="text-2xl font-bold text-red-400">{stats.total_incidents || 0}</div>
                  <div className="text-[10px] text-gray-400 uppercase">Incidents</div>
                </div>
                <div className="w-px h-10 bg-[#2f3542]" />
                <div className="text-center">
                  <div className="text-2xl font-bold text-orange-400">{alertCount}</div>
                  <div className="text-[10px] text-gray-400 uppercase">Alerts</div>
                </div>
              </div>

              {/* Alert Indicator */}
              {Object.keys(activeAlertsByCamera).length > 0 && (
                <div className="flex items-center gap-2 px-3 py-2 bg-red-500/20 border border-red-500/50 rounded-lg">
                  <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
                  <span className="text-sm text-red-400 font-medium">{Object.keys(activeAlertsByCamera).length} Active Alerts</span>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Content Area */}
        <div className="flex-1 overflow-auto p-6 bg-[#0f1419]">
          {activeTab === 'monitoring' && (
            <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
              {/* Camera Grid - Takes 2 columns on xl screens */}
              <div className="xl:col-span-2 space-y-6">
                <MultiCameraGrid />
              </div>

              {/* Alert Panel - Takes 1 column */}
              <div className="space-y-6">
                {/* Current Alert */}
                <div className="panel">
                  <div className="panel-header">
                    <span className="panel-title flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
                      Active Alerts
                    </span>
                    <span className="text-xs text-gray-500">{Object.keys(activeAlertsByCamera).length} live</span>
                  </div>
                  <div className="panel-body">
                    {Object.keys(activeAlertsByCamera).length > 0 ? (
                      <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
                        {Object.values(activeAlertsByCamera).map((alertItem) => {
                          const alertKey = getAlertKey(alertItem);
                          const cameraId = getCameraId(alertItem);
                          return (
                            <AlertPopup
                              key={alertKey}
                              alert={alertItem}
                              onDismiss={() => dismissAlert(cameraId)}
                            />
                          );
                        })}
                      </div>
                    ) : (
                      <div className="text-center py-8 text-gray-500">
                        <div className="text-4xl mb-2">✓</div>
                        <div className="text-sm">No active alerts</div>
                        <div className="text-xs text-gray-600">System is monitoring</div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Quick Analytics */}
                <AnalyticsPanel analytics={analytics} />
              </div>
            </div>
          )}

          {activeTab === 'incidents' && (
            <div className="panel">
              <div className="panel-header">
                <span className="panel-title">Incident History</span>
                <span className="text-xs text-gray-500">{incidentList.length} total</span>
              </div>
              <div className="panel-body">
                <IncidentList incidents={incidentList} />
                
                {/* STEP 8: DEBUG VISUALIZATION - Raw incident data */}
                <div className="mt-6 pt-6 border-t border-[#2f3542]">
                  <details className="text-xs">
                    <summary className="cursor-pointer text-gray-400 hover:text-gray-300 font-mono">
                      🔧 DEBUG: Raw Incident JSON ({incidentList.length} items)
                    </summary>
                    <pre className="mt-2 bg-[#1a1f2e] p-2 rounded overflow-x-auto text-[9px] text-gray-300 max-h-64 overflow-y-auto">
{JSON.stringify(incidentList.map(inc => ({
  id: inc.id,
  event_type: inc.event?.event_type,
  camera_id: inc.event?.camera_id,
  zone: inc.event?.zone,
  timestamp: inc.event?.timestamp,
  priority: inc.alert?.priority,
  summary_preview: inc.alert?.summary?.substring?.(0, 50)
})), null, 2)}
                    </pre>
                  </details>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'analytics' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <AnalyticsPanel analytics={analytics} expanded />
              <div className="panel">
                <div className="panel-header">
                  <span className="panel-title">Recent Incidents</span>
                </div>
                <div className="panel-body">
                  {/* Show only 5 most recent incidents in analytics summary (full list available in Incidents tab) */}
                  <IncidentList incidents={incidentList.slice(0, 5)} compact />
                </div>
              </div>
            </div>
          )}

          {activeTab === 'settings' && (
            <div className="panel max-w-2xl">
              <div className="panel-header">
                <span className="panel-title">System Settings</span>
              </div>
              <div className="panel-body space-y-4">
                <div className="flex items-center justify-between py-3 border-b border-[#2f3542]">
                  <div>
                    <div className="text-sm text-white">Backend URL</div>
                    <div className="text-xs text-gray-500">API endpoint for data</div>
                  </div>
                  <code className="text-xs bg-[#242b3d] px-3 py-1 rounded text-gray-300">{BACKEND_URL}</code>
                </div>
                <div className="flex items-center justify-between py-3 border-b border-[#2f3542]">
                  <div>
                    <div className="text-sm text-white">WebSocket Status</div>
                    <div className="text-xs text-gray-500">Real-time connection</div>
                  </div>
                  <span className={`text-xs px-2 py-1 rounded ${
                    wsStatus === 'connected' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                  }`}>
                    {wsStatus}
                  </span>
                </div>
                <div className="flex items-center justify-between py-3">
                  <div>
                    <div className="text-sm text-white">Refresh Rate</div>
                    <div className="text-xs text-gray-500">Data polling interval</div>
                  </div>
                  <span className="text-xs text-gray-300">5 seconds</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

