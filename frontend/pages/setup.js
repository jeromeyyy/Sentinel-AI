'use client';

import { useState } from 'react';
import { useRouter } from 'next/router';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Camera,
  MapPin,
  Eye,
  CheckCircle,
  ChevronRight,
  ChevronLeft,
  AlertCircle,
  Loader2,
} from 'lucide-react';

import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Input, Select } from '../components/ui/Input';
import { useToast } from '../components/ui/Toast';

import { BACKEND_URL, ZONES } from '../lib/constants';
import { cn } from '../lib/utils';

const STEPS = [
  { id: 1, title: 'Camera Details', icon: Camera },
  { id: 2, title: 'Zone Assignment', icon: MapPin },
  { id: 3, title: 'Test Stream', icon: Eye },
  { id: 4, title: 'Confirm', icon: CheckCircle },
];

export default function SetupWizard() {
  const router = useRouter();
  const { showSuccess, showError } = useToast();
  
  const [currentStep, setCurrentStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [testingStream, setTestingStream] = useState(false);
  const [streamPreviewUrl, setStreamPreviewUrl] = useState('');

  // Form data
  const [formData, setFormData] = useState({
    name: '',
    source: '',
    zone: '',
    location: '',
    building: '',
    floor: '',
  });

  const [errors, setErrors] = useState({});

  // Handle input change
  const handleChange = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }));
    // Clear error for this field
    if (errors[field]) {
      setErrors(prev => ({ ...prev, [field]: '' }));
    }
  };

  // Validate step
  const validateStep = (step) => {
    const newErrors = {};

    if (step === 1) {
      if (!formData.name.trim()) {
        newErrors.name = 'Camera name is required';
      }
      if (!formData.source.trim()) {
        newErrors.source = 'RTSP URL or video path is required';
      } else if (!formData.source.startsWith('rtsp://') && !formData.source.includes('.mp4') && !formData.source.includes('.avi')) {
        newErrors.source = 'Must be an RTSP URL or video file path';
      }
    }

    if (step === 2) {
      if (!formData.zone) {
        newErrors.zone = 'Zone selection is required';
      }
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  // Test stream
  const testStream = async () => {
    setTestingStream(true);
    setStreamPreviewUrl('');

    try {
      // First, create camera temporarily to test
      const response = await fetch(`${BACKEND_URL}/api/camera`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: `${formData.name} (Test)`,
          video_path: formData.source,
          zone: formData.zone,
        }),
      });

      if (!response.ok) throw new Error('Failed to test stream');

      const data = await response.json();
      const cameraId = data.camera_id;

      // Set preview URL
      setStreamPreviewUrl(`${BACKEND_URL}/video/${cameraId}`);
      
      showSuccess('Stream test successful! Preview loaded.');
    } catch (error) {
      showError('Failed to test stream. Check RTSP URL or file path.');
      console.error('Stream test error:', error);
    } finally {
      setTestingStream(false);
    }
  };

  // Submit camera
  const handleSubmit = async () => {
    setLoading(true);

    try {
      const response = await fetch(`${BACKEND_URL}/api/camera`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: formData.name,
          video_path: formData.source,
          zone: formData.zone,
          metadata: {
            location: formData.location,
            building: formData.building,
            floor: formData.floor,
          },
        }),
      });

      if (!response.ok) throw new Error('Failed to create camera');

      const data = await response.json();

      showSuccess(`Camera "${formData.name}" added successfully!`);
      
      // Redirect to monitoring dashboard
      setTimeout(() => {
        router.push('/monitor?tab=cameras');
      }, 1500);
    } catch (error) {
      showError('Failed to add camera. Please try again.');
      console.error('Camera creation error:', error);
    } finally {
      setLoading(false);
    }
  };

  // Navigation
  const goNext = () => {
    if (validateStep(currentStep)) {
      if (currentStep < STEPS.length) {
        setCurrentStep(prev => prev + 1);
      } else {
        handleSubmit();
      }
    }
  };

  const goBack = () => {
    if (currentStep > 1) {
      setCurrentStep(prev => prev - 1);
    }
  };

  const canProceed = () => {
    if (currentStep === 1) return formData.name && formData.source;
    if (currentStep === 2) return formData.zone;
    if (currentStep === 3) return streamPreviewUrl; // Must test stream
    return true;
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-bg-primary via-bg-secondary to-bg-primary p-8">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-foreground mb-2">Camera Setup Wizard</h1>
          <p className="text-muted-foreground">Add a new camera to your surveillance system</p>
        </div>

        {/* Progress Steps */}
        <div className="flex items-center justify-between mb-12">
          {STEPS.map((step, index) => {
            const Icon = step.icon;
            const isActive = currentStep === step.id;
            const isCompleted = currentStep > step.id;

            return (
              <div key={step.id} className="flex items-center flex-1">
                <div className="flex flex-col items-center flex-1">
                  <div
                    className={cn(
                      'w-12 h-12 rounded-full flex items-center justify-center transition-all',
                      isCompleted && 'bg-green-500/20 border-2 border-green-500',
                      isActive && 'bg-primary/20 border-2 border-primary',
                      !isActive && !isCompleted && 'bg-muted border-2 border-border'
                    )}
                  >
                    <Icon
                      className={cn(
                        'w-6 h-6 transition-colors',
                        isCompleted && 'text-green-500',
                        isActive && 'text-primary',
                        !isActive && !isCompleted && 'text-muted-foreground'
                      )}
                    />
                  </div>
                  <span
                    className={cn(
                      'text-xs mt-2 font-medium transition-colors',
                      isActive && 'text-foreground',
                      !isActive && 'text-muted-foreground'
                    )}
                  >
                    {step.title}
                  </span>
                </div>

                {/* Connector Line */}
                {index < STEPS.length - 1 && (
                  <div
                    className={cn(
                      'h-0.5 flex-1 mx-2 transition-colors',
                      isCompleted ? 'bg-green-500' : 'bg-border'
                    )}
                  />
                )}
              </div>
            );
          })}
        </div>

        {/* Step Content */}
        <AnimatePresence mode="wait">
          <motion.div
            key={currentStep}
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.2 }}
          >
            <Card>
              <CardContent className="p-8">
                {/* Step 1: Camera Details */}
                {currentStep === 1 && (
                  <div className="space-y-6">
                    <div>
                      <h3 className="text-xl font-semibold mb-4">Camera Details</h3>
                      <p className="text-muted-foreground mb-6">
                        Enter the camera name and video source (RTSP URL or file path)
                      </p>
                    </div>

                    <div>
                      <label className="block text-sm font-medium mb-2">Camera Name *</label>
                      <Input
                        value={formData.name}
                        onChange={(e) => handleChange('name', e.target.value)}
                        placeholder="e.g., Main Corridor - East Wing"
                        error={errors.name}
                      />
                      {errors.name && (
                        <p className="text-red-500 text-xs mt-1 flex items-center gap-1">
                          <AlertCircle className="w-3 h-3" />
                          {errors.name}
                        </p>
                      )}
                    </div>

                    <div>
                      <label className="block text-sm font-medium mb-2">Video Source (RTSP or File Path) *</label>
                      <Input
                        value={formData.source}
                        onChange={(e) => handleChange('source', e.target.value)}
                        placeholder="rtsp://192.168.1.100:554/stream or C:/videos/test.mp4"
                        error={errors.source}
                      />
                      {errors.source && (
                        <p className="text-red-500 text-xs mt-1 flex items-center gap-1">
                          <AlertCircle className="w-3 h-3" />
                          {errors.source}
                        </p>
                      )}
                    </div>

                    <div className="grid grid-cols-3 gap-4">
                      <div>
                        <label className="block text-sm font-medium mb-2">Location</label>
                        <Input
                          value={formData.location}
                          onChange={(e) => handleChange('location', e.target.value)}
                          placeholder="East Wing"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium mb-2">Building</label>
                        <Input
                          value={formData.building}
                          onChange={(e) => handleChange('building', e.target.value)}
                          placeholder="Main Building"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium mb-2">Floor</label>
                        <Input
                          value={formData.floor}
                          onChange={(e) => handleChange('floor', e.target.value)}
                          placeholder="2nd Floor"
                        />
                      </div>
                    </div>
                  </div>
                )}

                {/* Step 2: Zone Assignment */}
                {currentStep === 2 && (
                  <div className="space-y-6">
                    <div>
                      <h3 className="text-xl font-semibold mb-4">Zone Assignment</h3>
                      <p className="text-muted-foreground mb-6">
                        Select the surveillance zone for this camera. Different zones use different AI detection models.
                      </p>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      {ZONES.map((zone) => {
                        const isSelected = formData.zone === zone.id;
                        return (
                          <button
                            key={zone.id}
                            onClick={() => handleChange('zone', zone.id)}
                            className={cn(
                              'p-6 rounded-xl border-2 transition-all text-left',
                              isSelected
                                ? 'border-primary bg-primary/10'
                                : 'border-border hover:border-primary/50 hover:bg-muted'
                            )}
                          >
                            <div className="flex items-start justify-between mb-3">
                              <h4 className="font-semibold text-foreground">{zone.label}</h4>
                              {isSelected && <CheckCircle className="w-5 h-5 text-primary" />}
                            </div>
                            <p className="text-sm text-muted-foreground">{zone.description}</p>
                          </button>
                        );
                      })}
                    </div>

                    {errors.zone && (
                      <p className="text-red-500 text-sm flex items-center gap-2">
                        <AlertCircle className="w-4 h-4" />
                        {errors.zone}
                      </p>
                    )}
                  </div>
                )}

                {/* Step 3: Test Stream */}
                {currentStep === 3 && (
                  <div className="space-y-6">
                    <div>
                      <h3 className="text-xl font-semibold mb-4">Test Stream</h3>
                      <p className="text-muted-foreground mb-6">
                        Preview the camera stream to ensure it's working correctly.
                      </p>
                    </div>

                    <div className="space-y-4">
                      <Button
                        onClick={testStream}
                        disabled={testingStream}
                        variant="secondary"
                        className="w-full"
                      >
                        {testingStream ? (
                          <>
                            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                            Testing Stream...
                          </>
                        ) : (
                          <>
                            <Eye className="w-4 h-4 mr-2" />
                            Test Stream
                          </>
                        )}
                      </Button>

                      {streamPreviewUrl && (
                        <div className="rounded-lg overflow-hidden border-2 border-border bg-black">
                          <img
                            src={streamPreviewUrl}
                            alt="Camera preview"
                            className="w-full h-auto"
                          />
                        </div>
                      )}

                      {!streamPreviewUrl && !testingStream && (
                        <div className="bg-muted rounded-lg p-12 text-center">
                          <Eye className="w-12 h-12 mx-auto mb-3 text-muted-foreground" />
                          <p className="text-muted-foreground">Click "Test Stream" to preview</p>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Step 4: Confirm */}
                {currentStep === 4 && (
                  <div className="space-y-6">
                    <div>
                      <h3 className="text-xl font-semibold mb-4">Confirm Setup</h3>
                      <p className="text-muted-foreground mb-6">
                        Review your camera configuration before adding it to the system.
                      </p>
                    </div>

                    <div className="space-y-4">
                      <div className="bg-muted rounded-lg p-4">
                        <div className="grid grid-cols-2 gap-4">
                          <div>
                            <span className="text-xs text-muted-foreground">Camera Name</span>
                            <p className="font-medium">{formData.name}</p>
                          </div>
                          <div>
                            <span className="text-xs text-muted-foreground">Zone</span>
                            <p className="font-medium">
                              {ZONES.find(z => z.id === formData.zone)?.label}
                            </p>
                          </div>
                          <div className="col-span-2">
                            <span className="text-xs text-muted-foreground">Source</span>
                            <p className="font-medium text-sm break-all">{formData.source}</p>
                          </div>
                          {formData.location && (
                            <div>
                              <span className="text-xs text-muted-foreground">Location</span>
                              <p className="font-medium">{formData.location}</p>
                            </div>
                          )}
                          {formData.building && (
                            <div>
                              <span className="text-xs text-muted-foreground">Building</span>
                              <p className="font-medium">{formData.building}</p>
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4">
                        <p className="text-sm text-blue-400 flex items-start gap-2">
                          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                          Once added, the AI worker will automatically start processing this camera feed.
                        </p>
                      </div>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </motion.div>
        </AnimatePresence>

        {/* Navigation Buttons */}
        <div className="flex items-center justify-between mt-8">
          <Button
            onClick={goBack}
            disabled={currentStep === 1}
            variant="ghost"
          >
            <ChevronLeft className="w-4 h-4 mr-2" />
            Back
          </Button>

          <div className="flex items-center gap-3">
            <Button
              onClick={() => router.push('/')}
              variant="ghost"
            >
              Cancel
            </Button>
            <Button
              onClick={goNext}
              disabled={!canProceed() || loading}
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Adding...
                </>
              ) : currentStep === STEPS.length ? (
                <>
                  <CheckCircle className="w-4 h-4 mr-2" />
                  Add Camera
                </>
              ) : (
                <>
                  Next
                  <ChevronRight className="w-4 h-4 ml-2" />
                </>
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
