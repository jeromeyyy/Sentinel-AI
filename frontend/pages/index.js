'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import { motion } from 'framer-motion';
import { 
  Camera, 
  Play, 
  Plus, 
  Trash2, 
  Edit2, 
  CheckCircle,
  Home,
  GraduationCap,
  Building,
  Car,
  Users,
  MapPin,
  BookOpen,
  Flame,
  Server,
  DoorOpen,
  SquareParking,
  Landmark,
  Search,
  ChevronRight,
  Shield,
  Zap,
  Eye,
  Loader2
} from 'lucide-react';

import { Card, CardContent } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Modal } from '../components/ui/Modal';
import { Input, Select, Checkbox } from '../components/ui/Input';
import { StatusIndicator } from '../components/ui/StatusIndicator';
import { EmptyState } from '../components/ui/EmptyState';
import SetupWizard from '../components/SetupWizard';
import GoogleLoginButton, { AuthStatus, useAuth } from '../components/GoogleLogin';

import { BACKEND_URL, ZONES, MODULES, DEFAULT_CAMERAS, getZonesForModule } from '@/lib/constants';
import { cn, fetchBackend } from '../lib/utils';

// Zone icons mapping
const ZONE_ICONS = {
  all: Search,
  outgate: Car,
  corridor: Users,
  school_ground: MapPin,
  classroom: BookOpen,
  workspace: Flame,
  hallway: Flame,
  meeting_hall: Landmark,
  server_room: Server,
  door: DoorOpen,
  parking: SquareParking,
  main_gate: Car,
  living_room: Flame,
};

// Module icons mapping
const MODULE_ICONS = {
  home: Home,
  school: GraduationCap,
  office: Building,
};

export default function LandingPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [cameras, setCameras] = useState([]);
  const [selectedModule, setSelectedModule] = useState('school');
  const [loading, setLoading] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingCamera, setEditingCamera] = useState(null);
  const [showSetupWizard, setShowSetupWizard] = useState(false);
  const [wizardCamera, setWizardCamera] = useState(null);

  const handleWizardComplete = (cameraData) => {
    if (wizardCamera) {
      // Editing existing camera
      setCameras(prev => prev.map(c => c.id === cameraData.id ? cameraData : c));
    } else {
      // Adding new camera
      setCameras(prev => [...prev, cameraData]);
    }
    setShowSetupWizard(false);
    setWizardCamera(null);
  };

  const openWizardForNew = () => {
    setWizardCamera(null);
    setShowSetupWizard(true);
  };

  const openWizardForEdit = (camera) => {
    setWizardCamera(camera);
    setShowSetupWizard(true);
  };
  const [cameraHealth, setCameraHealth] = useState({});

  // Load current module
  useEffect(() => {
    async function loadCurrentModule() {
      try {
        const res = await fetchBackend(`${BACKEND_URL}/api/module/current`);
        if (res.ok) {
          const data = await res.json();
          if (data?.module) setSelectedModule(data.module);
        }
      } catch {}
    }
    loadCurrentModule();
  }, []);

  // Load cameras for selected module
  useEffect(() => {
    async function loadCameras() {
      try {
        const res = await fetchBackend(`${BACKEND_URL}/api/cameras?module=${selectedModule}`);
        if (res.ok) {
          const data = await res.json();
          setCameras(Array.isArray(data.cameras) ? data.cameras : []);
        }
      } catch {
        setCameras([]);
      }
    }
    loadCameras();
  }, [selectedModule]);

  // Check camera health
  useEffect(() => {
    async function checkHealth() {
      const healthMap = {};
      for (const cam of cameras) {
        try {
          const res = await fetchBackend(`${BACKEND_URL}/api/camera/${cam.id}/health`, {
            method: 'GET',
          });
          healthMap[cam.id] = res.ok ? 'online' : 'offline';
        } catch {
          healthMap[cam.id] = 'offline';
        }
      }
      setCameraHealth(healthMap);
    }
    if (cameras.length > 0) {
      checkHealth();
      const interval = setInterval(checkHealth, 30000);
      return () => clearInterval(interval);
    }
  }, [cameras]);

  const handleModuleSelect = (moduleId) => {
    setSelectedModule(moduleId);
  };

  const handleAddCamera = async (cameraData) => {
    const newCamera = {
      id: `cam_${Date.now()}`,
      ...cameraData,
      active: true,
      status: 'online',
    };
    
    try {
      await fetchBackend(`${BACKEND_URL}/api/camera/${newCamera.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newCamera),
      });
    } catch (e) {
      console.error('Failed to add camera:', e);
    }
    
    setCameras(prev => [...prev, newCamera]);
    setShowAddModal(false);
  };

  const handleEditCamera = async (cameraData) => {
    const updatedCamera = { ...editingCamera, ...cameraData };
    
    try {
      await fetchBackend(`${BACKEND_URL}/api/camera/${updatedCamera.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatedCamera),
      });
    } catch (e) {
      console.error('Failed to update camera:', e);
    }
    
    setCameras(prev => prev.map(c => c.id === updatedCamera.id ? updatedCamera : c));
    setEditingCamera(null);
  };

  const handleDeleteCamera = async (cameraId) => {
    try {
      await fetchBackend(`${BACKEND_URL}/api/camera/${cameraId}`, { method: 'DELETE' });
    } catch (e) {
      console.error('Failed to delete camera:', e);
    }
    setCameras(prev => prev.filter(c => c.id !== cameraId));
  };

  const handleToggleActive = (cameraId) => {
    setCameras(prev => prev.map(c => 
      c.id === cameraId ? { ...c, active: !c.active } : c
    ));
  };

  const handleStartMonitoring = async () => {
    setLoading(true);
    
    // Save config
    const config = { module: selectedModule, cameras };
    window.localStorage.setItem('sentinel_config', JSON.stringify(config));

    // Set module
    try {
      await fetchBackend(`${BACKEND_URL}/api/module`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ module: selectedModule }),
      });
    } catch (e) {
      console.error('Failed to set module:', selectedModule);
    }
    
    // Sync cameras
    for (const cam of cameras) {
      try {
        await fetchBackend(`${BACKEND_URL}/api/camera/${cam.id}`, {
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

  const activeCount = cameras.filter(c => c.active).length;
  const onlineCount = Object.values(cameraHealth).filter(s => s === 'online').length;
  const moduleZones = getZonesForModule(selectedModule);

  // Loading state
  if (authLoading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="absolute inset-0 bg-gradient-to-br from-blue-500/10 via-purple-500/5 to-transparent" />
        <div className="flex flex-col items-center gap-4">
          <div className="w-16 h-16 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl flex items-center justify-center shadow-lg shadow-blue-500/25">
            <Eye className="w-8 h-8 text-white" />
          </div>
          <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
          <p className="text-sm text-muted-foreground">Loading...</p>
        </div>
      </div>
    );
  }

  // Auth Gate - Show login page if not authenticated
  if (!user) {
    return <PublicLanding />;
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Hero Section */}
      <div className="relative overflow-hidden min-h-[600px] flex flex-col justify-center">
        {/* Animated Grid Background */}
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:24px_24px] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)]" />
        
        {/* Animated Gradient Orbs */}
        <motion.div
          animate={{ 
            scale: [1, 1.2, 1], 
            opacity: [0.3, 0.5, 0.3],
            x: [0, 50, 0],
            y: [0, -50, 0]
          }}
          transition={{ duration: 15, repeat: Infinity, ease: "easeInOut" }}
          className="absolute top-[-10%] right-[-5%] w-[600px] h-[600px] bg-blue-500/20 rounded-full blur-[120px]"
        />
        <motion.div
          animate={{ 
            scale: [1, 1.3, 1], 
            opacity: [0.2, 0.4, 0.2],
            x: [0, -50, 0],
            y: [0, 50, 0]
          }}
          transition={{ duration: 18, repeat: Infinity, ease: "easeInOut", delay: 2 }}
          className="absolute bottom-[-10%] left-[-5%] w-[700px] h-[700px] bg-purple-500/20 rounded-full blur-[120px]"
        />
        
        <div className="relative max-w-7xl mx-auto px-6 pt-24 pb-16 w-full z-10">
          {/* Logo & Header */}
          <motion.div 
            initial={{ opacity: 0, y: -30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, ease: "easeOut" }}
            className="flex flex-col md:flex-row md:items-center justify-between mb-20 gap-8"
          >
            <div className="flex items-center gap-6">
              <motion.div 
                whileHover={{ scale: 1.1, rotate: 10 }}
                animate={{ boxShadow: ["0 0 20px rgba(59,130,246,0.2)", "0 0 60px rgba(147,51,234,0.4)", "0 0 20px rgba(59,130,246,0.2)"] }}
                transition={{ boxShadow: { duration: 3, repeat: Infinity } }}
                className="w-20 h-20 bg-gradient-to-br from-blue-500 via-indigo-500 to-purple-600 rounded-2xl flex items-center justify-center border border-white/20 backdrop-blur-xl"
              >
                <Eye className="w-10 h-10 text-white" />
              </motion.div>
              <div>
                <motion.h1 
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.2 }}
                  className="text-5xl md:text-6xl font-extrabold text-foreground tracking-tighter mb-2 bg-clip-text text-transparent bg-gradient-to-r from-white via-blue-100 to-white/50"
                >
                  SentinelAI
                </motion.h1>
                <motion.p 
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.4 }}
                  className="text-blue-400 font-bold tracking-[0.2em] text-sm uppercase"
                >
                  Next-Gen Security System
                </motion.p>
              </div>
            </div>
            
            {/* Auth, Stats & Setup Wizard */}
            <div className="hidden md:flex items-center gap-6">
              {/* Quick Stats */}
              <div className="flex items-center gap-6 border-r border-border pr-6">
                <div className="text-center">
                  <div className="text-2xl font-bold text-foreground">{cameras.length}</div>
                  <div className="text-xs text-muted-foreground">Cameras</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-green-400">{activeCount}</div>
                  <div className="text-xs text-muted-foreground">Active</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-blue-400">{onlineCount}</div>
                  <div className="text-xs text-muted-foreground">Online</div>
                </div>
              </div>
              
              {/* Setup Wizard Button */}
              <Button onClick={openWizardForNew} size="sm" className="gap-2">
                <Plus className="w-4 h-4" />
                Setup Camera
              </Button>
              
              {/* User Auth */}
              <AuthStatus />
            </div>
          </motion.div>

          {/* Feature Pills */}
          <motion.div 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="flex flex-wrap gap-3"
          >
            <FeaturePill icon={Zap} text="Real-time Detection" />
            <FeaturePill icon={Shield} text="YOLOv8 AI Models" />
            <FeaturePill icon={Camera} text="Multi-Zone Monitoring" />
          </motion.div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 pb-12 space-y-12 relative z-10">
        {/* Module Selection */}
        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
        >
          <div className="flex items-center gap-2 mb-6">
            <div className="w-1 h-6 bg-blue-500 rounded-full" />
            <h2 className="text-xl font-bold text-foreground">Select Environment</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {MODULES.map((module) => {
              const Icon = MODULE_ICONS[module.id];
              const isSelected = selectedModule === module.id;
              
              return (
                <motion.button
                  key={module.id}
                  onClick={() => handleModuleSelect(module.id)}
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  className={cn(
                    'relative p-6 rounded-2xl border-2 transition-all text-left',
                    isSelected
                      ? 'bg-blue-500/10 border-blue-500 shadow-lg shadow-blue-500/10'
                      : 'bg-card border-border hover:border-border-hover'
                  )}
                >
                  {isSelected && (
                    <div className="absolute top-3 right-3">
                      <CheckCircle className="w-5 h-5 text-blue-400" />
                    </div>
                  )}
                  
                  <div className={cn(
                    'w-12 h-12 rounded-xl flex items-center justify-center mb-3',
                    isSelected ? 'bg-blue-500/20' : 'bg-muted'
                  )}>
                    <Icon className={cn('w-6 h-6', isSelected ? 'text-blue-400' : 'text-muted-foreground')} />
                  </div>
                  
                  <h3 className={cn(
                    'text-lg font-semibold mb-1',
                    isSelected ? 'text-blue-400' : 'text-foreground'
                  )}>
                    {module.label}
                  </h3>
                  <p className="text-sm text-muted-foreground">{module.description}</p>
                  <p className="text-xs text-muted-foreground mt-2">
                    Videos from: test_videos/{module.id}
                  </p>
                </motion.button>
              );
            })}
          </div>
        </motion.section>

        {/* Zone Capabilities */}
        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
        >
          <div className="flex items-center gap-2 mb-6">
            <div className="w-1 h-6 bg-purple-500 rounded-full" />
            <h2 className="text-xl font-bold text-foreground">Detection Zones</h2>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {moduleZones.map((zone, i) => {
              const Icon = ZONE_ICONS[zone.id];
              
              return (
                <motion.div
                  key={zone.id}
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ delay: 0.4 + i * 0.05 }}
                >
                  <Card className="h-full relative overflow-hidden group bg-card/40 backdrop-blur-md border-white/10 hover:border-blue-500/50 transition-all duration-500">
                    <div className="absolute inset-0 bg-gradient-to-br from-blue-500/5 via-transparent to-purple-500/5 opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
                    
                    <CardContent className="p-6 relative z-10">
                      <div className="flex items-center gap-4 mb-4">
                        <div className={cn(
                          'w-14 h-14 rounded-2xl flex items-center justify-center shadow-inner transition-transform duration-500 group-hover:scale-110',
                          zone.color === 'blue' && 'bg-blue-500/10 text-blue-400 border border-blue-500/30',
                          zone.color === 'green' && 'bg-green-500/10 text-green-400 border border-green-500/30',
                          zone.color === 'orange' && 'bg-orange-500/10 text-orange-400 border border-orange-500/30',
                          zone.color === 'cyan' && 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/30',
                        )}>
                          <Icon className="w-7 h-7" />
                        </div>
                        <div>
                          <h3 className="font-bold text-foreground text-base tracking-tight">{zone.label}</h3>
                          <Badge variant="outline" size="sm" className="mt-2 border-white/20 text-xs bg-background/50 backdrop-blur-sm">
                            {zone.model}
                          </Badge>
                        </div>
                      </div>
                      <p className="text-sm text-muted-foreground leading-relaxed">{zone.description}</p>
                    </CardContent>
                  </Card>
                </motion.div>
              );
            })}
          </div>
        </motion.section>

        {/* Camera Configuration */}
        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
        >
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-2">
              <div className="w-1 h-6 bg-green-500 rounded-full" />
              <h2 className="text-xl font-bold text-foreground">Camera Configuration</h2>
            </div>
            <Button onClick={openWizardForNew} size="sm" className="bg-white text-black hover:bg-white/90">
              <Plus className="w-4 h-4 mr-1" />
              Add Camera
            </Button>
          </div>

          {cameras.length === 0 ? (
            <Card className="border-dashed border-2 border-border/50 bg-transparent">
              <CardContent className="pt-6">
                <EmptyState
                  icon="camera"
                  title="No cameras configured"
                  description="Add your first camera to start monitoring"
                  action={openWizardForNew}
                  actionLabel="Add Camera"
                />
              </CardContent>
            </Card>
          ) : (
            <Card className="overflow-hidden bg-card/50 backdrop-blur-sm border-white/5">
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-border bg-muted/20">
                      <th className="py-4 px-6 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Camera Name</th>
                      <th className="py-4 px-6 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Zone</th>
                      <th className="py-4 px-6 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Status</th>
                      <th className="py-4 px-6 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Active</th>
                      <th className="py-4 px-6 text-xs font-semibold text-muted-foreground uppercase tracking-wider text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/50">
                    {cameras.map((camera) => {
                      const zone = ZONES.find(z => z.id === camera.zone);
                      const health = cameraHealth[camera.id] || 'offline';
                      
                      return (
                        <tr key={camera.id} className="hover:bg-muted/10 transition-colors">
                          <td className="py-4 px-6">
                            <div className="flex items-center gap-3">
                              <div className="w-8 h-8 rounded-full bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
                                <Camera className="w-4 h-4 text-blue-400" />
                              </div>
                              <span className="font-semibold text-sm">{camera.name}</span>
                            </div>
                          </td>
                          <td className="py-4 px-6">
                            <Badge variant="outline" className="border-white/10 bg-background/50">
                              {zone?.label || camera.zone}
                            </Badge>
                          </td>
                          <td className="py-4 px-6">
                            <Badge variant={health === 'online' ? 'success' : 'destructive'} dot>
                              {health}
                            </Badge>
                          </td>
                          <td className="py-4 px-6">
                            <Checkbox
                              checked={camera.active}
                              onChange={() => handleToggleActive(camera.id)}
                            />
                          </td>
                          <td className="py-4 px-6">
                            <div className="flex items-center justify-end gap-2">
                              <Button
                                onClick={() => openWizardForEdit(camera)}
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 text-muted-foreground hover:text-white"
                              >
                                <Edit2 className="w-4 h-4" />
                              </Button>
                              <Button
                                onClick={() => handleDeleteCamera(camera.id)}
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 text-muted-foreground hover:text-red-400 hover:bg-red-500/10"
                              >
                                <Trash2 className="w-4 h-4" />
                              </Button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </motion.section>

        {/* Start Monitoring CTA */}
        <motion.div 
          initial={{ opacity: 0, y: 30, scale: 0.95 }}
          whileInView={{ opacity: 1, y: 0, scale: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6, ease: "easeOut" }}
          className="relative overflow-hidden flex flex-col md:flex-row items-center justify-between p-10 rounded-3xl border border-white/10 shadow-[0_0_50px_rgba(59,130,246,0.15)] gap-8 bg-card/40 backdrop-blur-xl"
        >
          {/* Animated Background for CTA */}
          <div className="absolute inset-0 bg-gradient-to-r from-blue-600/20 via-purple-600/10 to-transparent animate-gradient-x" />
          
          <div className="relative z-10">
            <h3 className="text-3xl font-extrabold text-foreground mb-3 flex items-center gap-4 tracking-tight">
              Ready to Secure? 
              <motion.div 
                animate={{ rotate: [0, 15, -15, 0] }} 
                transition={{ duration: 2, repeat: Infinity, ease: "easeInOut", delay: 1 }}
              >
                <Shield className="w-8 h-8 text-blue-400 drop-shadow-[0_0_10px_rgba(59,130,246,0.8)]" />
              </motion.div>
            </h3>
            <p className="text-base text-muted-foreground max-w-lg leading-relaxed">
              {activeCount} camera{activeCount !== 1 ? 's' : ''} configured and ready for real-time monitoring. Our YOLOv8 models are primed for threat detection.
            </p>
          </div>
          <motion.div whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }} className="relative z-10 w-full md:w-auto">
            <Button 
              onClick={handleStartMonitoring} 
              loading={loading}
              size="lg"
              className="w-full md:w-auto gap-3 bg-gradient-to-r from-white to-blue-50 text-black hover:opacity-90 font-extrabold px-10 py-7 text-lg rounded-2xl shadow-[0_0_30px_rgba(255,255,255,0.4)] transition-all"
            >
              <Play className="w-6 h-6 fill-current" />
              INITIALIZE SYSTEM
              <ChevronRight className="w-5 h-5 ml-2" />
            </Button>
          </motion.div>
        </motion.div>
      </div>

      {/* Add Camera Modal (Legacy - keep for backward compat) */}
      <CameraFormModal
        isOpen={showAddModal}
        onClose={() => setShowAddModal(false)}
        onSubmit={handleAddCamera}
        selectedModule={selectedModule}
        title="Add New Camera"
      />

      {/* Edit Camera Modal (Legacy - keep for backward compat) */}
      <CameraFormModal
        isOpen={!!editingCamera}
        onClose={() => setEditingCamera(null)}
        onSubmit={handleEditCamera}
        camera={editingCamera}
        selectedModule={selectedModule}
        title="Edit Camera"
      />

      {/* Setup Wizard */}
      <SetupWizard
        isOpen={showSetupWizard}
        onClose={() => {
          setShowSetupWizard(false);
          setWizardCamera(null);
        }}
        onComplete={handleWizardComplete}
        existingCamera={wizardCamera}
        selectedModule={selectedModule}
      />

      {/* Footer */}
      <footer className="text-center py-6 border-t border-border">
        <p className="text-sm text-muted-foreground">
          SentinelAI School Safety System v1.0 — Powered by YOLOv8
        </p>
      </footer>
    </div>
  );
}

// Feature Pill Component
function FeaturePill({ icon: Icon, text }) {
  return (
    <motion.div 
      whileHover={{ scale: 1.05, y: -2 }}
      className="inline-flex items-center gap-3 px-5 py-2.5 bg-card/60 backdrop-blur-md border border-white/10 rounded-full shadow-lg hover:border-blue-500/50 hover:shadow-[0_0_20px_rgba(59,130,246,0.2)] transition-all cursor-default"
    >
      <Icon className="w-4 h-4 text-blue-400" />
      <span className="text-sm font-bold tracking-wide text-foreground">{text}</span>
    </motion.div>
  );
}

// Camera Form Modal
function CameraFormModal({ isOpen, onClose, onSubmit, camera, title, selectedModule = 'school' }) {
  const moduleZones = getZonesForModule(selectedModule);
  const defaultZoneId = moduleZones[0]?.id || 'outgate';
  const [name, setName] = useState('');
  const [zone, setZone] = useState(defaultZoneId);

  useEffect(() => {
    if (camera) {
      setName(camera.name || '');
      setZone(camera.zone || defaultZoneId);
    } else {
      setName('');
      setZone(defaultZoneId);
    }
  }, [camera, isOpen, defaultZoneId]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    onSubmit({ name: name.trim(), zone });
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={title} size="sm">
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input
          label="Camera Name"
          placeholder="Enter camera name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        
        <Select
          label="Zone Assignment"
          value={zone}
          onChange={(e) => setZone(e.target.value)}
          options={moduleZones.map(z => ({
            value: z.id,
            label: z.label
          }))}
        />

        <div className="flex justify-end gap-3 pt-4">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit">
            {camera ? 'Save Changes' : 'Add Camera'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

// Public Landing Page Component
function PublicLanding() {
  const scrollToTop = () => window.scrollTo({ top: 0, behavior: 'smooth' });

  return (
    <div className="min-h-screen bg-background text-foreground overflow-x-hidden selection:bg-blue-500/30">
      {/* Navbar */}
      <nav className="absolute top-0 left-0 right-0 z-50 flex items-center justify-between p-6 max-w-7xl mx-auto">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center shadow-[0_0_20px_rgba(59,130,246,0.5)] border border-blue-400/30">
            <Eye className="w-7 h-7 text-white" />
          </div>
          <span className="font-extrabold text-3xl tracking-tighter bg-clip-text text-transparent bg-gradient-to-r from-white to-white/70">
            Sentinel AI
          </span>
        </div>
      </nav>

      {/* Section 1: Hero */}
      <section className="relative min-h-screen flex items-center pt-20 overflow-hidden">
        {/* Animated Grid Background */}
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:24px_24px] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)]" />
        
        {/* Animated Gradient Orbs */}
        <motion.div
          animate={{ scale: [1, 1.2, 1], opacity: [0.3, 0.5, 0.3], x: [0, 50, 0], y: [0, -50, 0] }}
          transition={{ duration: 15, repeat: Infinity, ease: "easeInOut" }}
          className="absolute top-[10%] right-[10%] w-[500px] h-[500px] bg-blue-500/20 rounded-full blur-[120px]"
        />
        <motion.div
          animate={{ scale: [1, 1.3, 1], opacity: [0.2, 0.4, 0.2], x: [0, -50, 0], y: [0, 50, 0] }}
          transition={{ duration: 18, repeat: Infinity, ease: "easeInOut", delay: 2 }}
          className="absolute bottom-[10%] left-[10%] w-[600px] h-[600px] bg-purple-500/20 rounded-full blur-[120px]"
        />

        <div className="relative max-w-7xl mx-auto px-6 w-full z-10 flex flex-col items-center text-center">
          <motion.div 
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8 }}
            className="max-w-4xl flex flex-col items-center"
          >
            <h1 className="text-5xl md:text-7xl font-extrabold tracking-tighter mb-6 bg-clip-text text-transparent bg-gradient-to-r from-white via-blue-100 to-white/60">
              Smarter Surveillance Starts Here
            </h1>
            <p className="text-lg md:text-xl text-muted-foreground mb-10 max-w-2xl mx-auto leading-relaxed">
              Turn your existing CCTV cameras into an intelligent security platform that detects incidents, notifies the right people, and helps you respond faster.
            </p>
            
            <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
              {/* Only ONE Google login button */}
              <GoogleLoginButton size="lg" />
              <Button variant="outline" size="lg" className="h-[52px] px-8 text-base rounded-2xl border-white/10 hover:bg-white/5">
                Watch Demo
              </Button>
            </div>
          </motion.div>
        </div>
      </section>

      {/* Section 2: Why SentinelAI (Problem/Solution) */}
      <section className="py-32 relative bg-card/30 border-y border-white/5">
        <div className="max-w-7xl mx-auto px-6">
          <div className="grid md:grid-cols-2 gap-16 items-center">
            <motion.div 
              initial={{ opacity: 0, x: -30 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              className="space-y-6"
            >
              <h2 className="text-3xl md:text-5xl font-bold tracking-tight leading-tight">
                Security Shouldn't Depend on Someone Watching Screens All Day.
              </h2>
              <p className="text-muted-foreground leading-relaxed text-lg">
                Traditional surveillance records everything but reacts to nothing. 
                <br /><br />
                SentinelAI continuously monitors your cameras, identifies critical events in real time, and delivers instant alerts—so your team can focus on responding instead of watching.
              </p>
            </motion.div>
            <motion.div 
              initial={{ opacity: 0, x: 30 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              className="space-y-4"
            >
              <h3 className="text-xl font-bold mb-6">Every Second Matters.</h3>
              {[
                { title: 'Detect threats instantly', icon: Shield },
                { title: 'Reduce response time', icon: Zap },
                { title: 'Minimize false alarms', icon: CheckCircle },
              ].map((item, i) => (
                <div key={i} className="flex items-center gap-4 p-4 rounded-2xl bg-card/40 border border-white/5 backdrop-blur-sm">
                  <div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center border border-blue-500/20">
                    <item.icon className="w-5 h-5 text-blue-400" />
                  </div>
                  <span className="font-semibold text-lg">{item.title}</span>
                </div>
              ))}
            </motion.div>
          </div>
        </div>
      </section>

      {/* Section 3: One Platform. Every Environment */}
      <section className="py-32 relative">
        <div className="max-w-7xl mx-auto px-6 text-center">
          <h2 className="text-3xl md:text-5xl font-bold mb-4">One Platform. Every Environment.</h2>
          <p className="text-muted-foreground max-w-2xl mx-auto mb-16 text-lg">
            SentinelAI is designed with specific models trained for different environmental contexts.
          </p>
          
          <div className="grid md:grid-cols-3 gap-8">
            {[
              { id: 'school', title: 'Schools & Colleges', icon: GraduationCap, desc: 'Protect students, staff, and campus facilities with proactive monitoring for fights, unauthorized access, emergencies, and suspicious activity.', color: 'blue' },
              { id: 'office', title: 'Offices', icon: Building, desc: 'Secure workplaces with intelligent monitoring, restricted-area protection, visitor tracking, and incident management.', color: 'purple' },
              { id: 'home', title: 'Homes', icon: Home, desc: 'Receive instant notifications for intrusions, unexpected visitors, vehicle activity, and emergency situations—even when you\'re away.', color: 'green' }
            ].map((module, i) => (
              <motion.div
                key={module.id}
                initial={{ opacity: 0, y: 30 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.1 }}
              >
                <Card className="h-full bg-card/40 backdrop-blur-xl border-white/5 hover:border-white/20 transition-all text-left p-8 shadow-2xl">
                  <div className={`w-14 h-14 rounded-2xl flex items-center justify-center mb-6 bg-${module.color}-500/10 border border-${module.color}-500/20 text-${module.color}-400 shadow-inner`}>
                    <module.icon className="w-7 h-7" />
                  </div>
                  <h3 className="text-2xl font-bold mb-3">{module.title}</h3>
                  <p className="text-muted-foreground leading-relaxed">{module.desc}</p>
                </Card>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Section 4: How it Works & Final CTA */}
      <section className="py-32 relative bg-card/30 border-t border-white/5">
        <div className="max-w-7xl mx-auto px-6 text-center">
          <motion.div 
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="mb-24"
          >
            <h2 className="text-3xl md:text-5xl font-bold mb-4">Simple Setup. Intelligent Protection.</h2>
            <div className="grid md:grid-cols-4 gap-8 mt-16 text-left">
              {[
                { step: '1', title: 'Connect Cameras', desc: 'Add your existing CCTV cameras in minutes.' },
                { step: '2', title: 'AI Monitors Continuously', desc: 'Every camera is monitored around the clock without human intervention.' },
                { step: '3', title: 'Instant Threat Detection', desc: 'Potential incidents are identified as they happen.' },
                { step: '4', title: 'Smart Notifications', desc: 'Receive alerts through your dashboard and escalation when needed.' }
              ].map((step, i) => (
                <div key={i} className="relative">
                  <div className="text-6xl font-extrabold text-white/5 absolute -top-8 -left-4 z-0">{step.step}</div>
                  <div className="relative z-10">
                    <h4 className="text-xl font-bold mb-2 text-blue-400">{step.title}</h4>
                    <p className="text-muted-foreground text-sm">{step.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </motion.div>

          <motion.div 
            initial={{ opacity: 0, scale: 0.95 }}
            whileInView={{ opacity: 1, scale: 1 }}
            viewport={{ once: true }}
            className="relative overflow-hidden p-12 rounded-3xl border border-white/10 shadow-[0_0_50px_rgba(59,130,246,0.15)] bg-card/60 backdrop-blur-xl max-w-4xl mx-auto"
          >
            <div className="absolute inset-0 bg-gradient-to-br from-blue-600/10 via-purple-600/5 to-transparent" />
            <div className="relative z-10">
              <h2 className="text-4xl font-extrabold mb-4 tracking-tight">Ready to Modernize Your Security?</h2>
              <p className="text-lg text-muted-foreground mb-8 max-w-2xl mx-auto">
                Transform your existing surveillance system into an intelligent platform that helps you detect incidents, respond faster, and keep your environment safer.
              </p>
              <Button onClick={scrollToTop} size="lg" className="px-10 py-7 text-lg rounded-2xl bg-white text-black hover:opacity-90 font-bold shadow-[0_0_30px_rgba(255,255,255,0.3)]">
                Get Started
              </Button>
            </div>
          </motion.div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-8 text-center border-t border-white/5 text-muted-foreground/60 text-sm">
        <p>SentinelAI — AI-powered surveillance built for modern organizations.</p>
      </footer>
    </div>
  );
}


