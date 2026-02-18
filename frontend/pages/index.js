
import { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import AddCameraForm from '../components/AddCameraForm';
import ModuleSelector from '../components/ModuleSelector';

const ZONES = [
  { id: 'all', label: 'All Zones (Multi-Detection)', icon: '🔍', model: 'ALL' },
  { id: 'outgate', label: 'Outgate / Gate Area', icon: '🚗', model: 'yolov8n.pt' },
  { id: 'corridor', label: 'Corridor / Hallway', icon: '🚶', model: 'yolov8s.pt' },
  { id: 'school_ground', label: 'School Ground', icon: '🏃', model: 'yolov8s.pt' },
  { id: 'classroom', label: 'Classroom', icon: '📚', model: 'yolov8m.pt' },
];

const DEFAULT_CAMERAS = [
  { id: 'cam_outgate', name: 'Outgate Camera', zone: 'outgate', active: true },
  { id: 'cam_corridor', name: 'Corridor Camera', zone: 'corridor', active: true },
  { id: 'cam_ground', name: 'School Ground Camera', zone: 'school_ground', active: true },
  { id: 'cam_classroom', name: 'Classroom Camera', zone: 'classroom', active: true },
];

// ─── API Configuration ───────────────────────────────────────────────────────
// For local development, uncomment the line below:
// const BACKEND_URL = 'http://localhost:8000';

// For production (Vercel + Render), use environment variable:
const BACKEND_URL = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';

export default function Landing() {
  const router = useRouter();
  const [cameras, setCameras] = useState(DEFAULT_CAMERAS);
  const [selectedModule, setSelectedModule] = useState('school');
  const [loading, setLoading] = useState(false);
  const [showAddCamera, setShowAddCamera] = useState(false);

  useEffect(() => {
    let mounted = true;

    async function loadCurrentModule() {
      try {
        const res = await fetch(`${BACKEND_URL}/api/module/current`);
        if (!res.ok) {
          return;
        }
        const data = await res.json();
        if (mounted && data?.module) {
          setSelectedModule(data.module);
        }
      } catch {
        // ignore
      }
    }

    loadCurrentModule();

    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    let mounted = true;

    async function loadCamerasForModule() {
      try {
        const res = await fetch(`${BACKEND_URL}/api/cameras?module=${encodeURIComponent(selectedModule)}`);
        if (!res.ok) {
          throw new Error('Failed to load cameras');
        }
        const data = await res.json();
        if (mounted) {
          setCameras(data.cameras?.length ? data.cameras : DEFAULT_CAMERAS);
        }
      } catch {
        if (mounted) {
          setCameras(DEFAULT_CAMERAS);
        }
      }
    }

    loadCamerasForModule();

    return () => {
      mounted = false;
    };
  }, [selectedModule]);

  const handleCameraChange = (idx, field, value) => {
    setCameras((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], [field]: value };
      return next;
    });
  };

  const handleStartMonitoring = async () => {
    setLoading(true);
    const config = { module: selectedModule, cameras };
    window.localStorage.setItem('sentinel_config', JSON.stringify(config));

    try {
      await fetch(`${BACKEND_URL}/api/module`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ module: selectedModule }),
      });
    } catch (e) {
      console.error('Failed to set module:', selectedModule);
    }
    
    // Sync cameras to backend
    for (const cam of cameras) {
      try {
        await fetch(`${BACKEND_URL}/api/camera/${cam.id}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(cam),
        });
      } catch (e) {
        console.error('Failed to sync camera:', cam.id);
      }
    }
    
    router.push('/monitor');
  };

  const handleCameraAdded = (newCamera) => {
    setCameras(prev => [...prev, newCamera]);
    setShowAddCamera(false);
  };

  const handleDeleteCamera = async (cameraId) => {
    try {
      await fetch(`${BACKEND_URL}/api/camera/${cameraId}`, { method: 'DELETE' });
    } catch (e) {
      console.error('Failed to delete camera:', cameraId);
    }
    setCameras(prev => prev.filter(c => c.id !== cameraId));
  };

  return (
    <div className="min-h-screen bg-[#0f1419] flex items-center justify-center p-4">
      <div className="w-full max-w-4xl">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-3 mb-4">
            <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center">
              <svg className="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
            </div>
            <div className="text-left">
              <h1 className="text-2xl font-bold text-white">SentinelAI</h1>
              <p className="text-sm text-gray-400">School Safety Monitoring System</p>
            </div>
          </div>
        </div>

        {/* Main Card */}
        <div className="bg-[#1a1f2e] rounded-2xl border border-[#2f3542] p-6 shadow-2xl">
          <div className="mb-6">
            <h2 className="text-xl font-semibold text-white mb-2">Configure Cameras & Zones</h2>
            <p className="text-sm text-gray-400">
              Assign each camera to a specific zone for targeted detection. Each zone has specialized detection capabilities.
            </p>
            <div className="mt-4">
              <div className="text-xs text-gray-400 mb-2">Choose Video Module Folder</div>
              <ModuleSelector selected={selectedModule} onChange={setSelectedModule} />
              <div className="text-[11px] text-gray-500 mt-2">
                Loading videos from test_videos/{selectedModule}
              </div>
            </div>
          </div>

          {/* Zone Legend */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            {ZONES.map((zone) => (
              <div key={zone.id} className="bg-[#242b3d] rounded-lg p-3 border border-[#2f3542]">
                <div className="text-2xl mb-1">{zone.icon}</div>
                <div className="text-xs font-medium text-white">{zone.label}</div>
                <div className="text-[10px] text-gray-500 mt-1">
                  {zone.id === 'outgate' && 'Vehicle & accident detection'}
                  {zone.id === 'corridor' && 'Crowd & fight detection'}
                  {zone.id === 'school_ground' && 'Crowd & fight detection'}
                  {zone.id === 'classroom' && 'Mobile phone detection'}
                </div>
                <div className="text-[9px] text-purple-400 mt-1">Model: {zone.model}</div>
              </div>
            ))}
          </div>

          {/* Add Camera Button / Form */}
          {showAddCamera ? (
            <div className="mb-6">
              <AddCameraForm 
                onCameraAdded={handleCameraAdded}
                onCancel={() => setShowAddCamera(false)}
              />
            </div>
          ) : (
            <button
              onClick={() => setShowAddCamera(true)}
              className="mb-6 w-full py-3 border-2 border-dashed border-[#2f3542] rounded-lg text-gray-400 hover:border-cyan-500 hover:text-cyan-400 transition-colors flex items-center justify-center gap-2"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Add New Camera
            </button>
          )}

          {/* Camera Configuration */}
          <div className="space-y-3 mb-6">
            <div className="text-sm font-medium text-gray-300 mb-2">Camera Configuration</div>
            {cameras.map((cam, idx) => (
              <div
                key={cam.id}
                className="bg-[#242b3d] rounded-lg p-4 border border-[#2f3542] grid grid-cols-1 md:grid-cols-4 gap-4"
              >
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">Camera Name</label>
                  <input
                    className="w-full bg-[#1a1f2e] border border-[#2f3542] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                    placeholder="Camera name"
                    value={cam.name}
                    onChange={(e) => handleCameraChange(idx, 'name', e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">Zone Assignment</label>
                  <select
                    className="w-full bg-[#1a1f2e] border border-[#2f3542] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                    value={cam.zone}
                    onChange={(e) => handleCameraChange(idx, 'zone', e.target.value)}
                  >
                    {ZONES.map((z) => (
                      <option key={z.id} value={z.id}>{z.label}</option>
                    ))}
                  </select>
                </div>
                <div className="flex items-end">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={cam.active}
                      onChange={(e) => handleCameraChange(idx, 'active', e.target.checked)}
                      className="w-4 h-4 rounded border-[#2f3542] bg-[#1a1f2e] text-blue-500 focus:ring-blue-500"
                    />
                    <span className="text-sm text-gray-300">Active</span>
                  </label>
                </div>
                <div className="flex items-end justify-end">
                  <button
                    onClick={() => handleDeleteCamera(cam.id)}
                    className="text-xs text-red-400 hover:text-red-300 transition-colors"
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* Start Button */}
          <div className="flex items-center justify-between">
            <div className="text-xs text-gray-500">
              Videos are loaded from the selected module folder and auto-mapped to zones by folder/file names.
            </div>
            <button
              type="button"
              onClick={handleStartMonitoring}
              disabled={loading}
              className="inline-flex items-center gap-2 px-6 py-3 rounded-lg bg-gradient-to-r from-blue-500 to-purple-600 text-white text-sm font-semibold hover:opacity-90 disabled:opacity-50 transition-all"
            >
              {loading ? (
                <>
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Starting...
                </>
              ) : (
                <>
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  Start Monitoring
                </>
              )}
            </button>
          </div>
        </div>

        {/* Footer */}
        <div className="text-center mt-6 text-xs text-gray-500">
          SentinelAI School Safety System v1.0 - Powered by YOLOv8
        </div>
      </div>
    </div>
  );
}


