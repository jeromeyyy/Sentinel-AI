'use client';

import { cn } from '@/lib/utils';

const STATUS_CONFIGS = {
  connected: { color: 'bg-green-500', glowColor: 'shadow-green-500/50', label: 'Connected', pulse: false },
  connecting: { color: 'bg-yellow-500', glowColor: 'shadow-yellow-500/50', label: 'Connecting', pulse: true },
  disconnected: { color: 'bg-red-500', glowColor: 'shadow-red-500/50', label: 'Disconnected', pulse: false },
  error: { color: 'bg-red-500', glowColor: 'shadow-red-500/50', label: 'Error', pulse: false },
  online: { color: 'bg-green-500', glowColor: 'shadow-green-500/50', label: 'Online', pulse: false },
  offline: { color: 'bg-gray-500', glowColor: 'shadow-gray-500/50', label: 'Offline', pulse: false },
  live: { color: 'bg-red-500', glowColor: 'shadow-red-500/50', label: 'LIVE', pulse: true },
};

export function StatusIndicator({ 
  status = 'offline', 
  showLabel = true,
  size = 'md',
  glow = false,
  className,
  ...props 
}) {
  const config = STATUS_CONFIGS[status] || STATUS_CONFIGS.offline;
  
  const sizeClasses = {
    sm: { dot: 'w-1.5 h-1.5', text: 'text-[10px]' },
    md: { dot: 'w-2.5 h-2.5', text: 'text-xs' },
    lg: { dot: 'w-3.5 h-3.5', text: 'text-sm' },
  };

  return (
    <div className={cn('flex items-center gap-2', className)} {...props}>
      <span 
        className={cn(
          'rounded-full transition-all duration-300',
          config.color,
          sizeClasses[size].dot,
          config.pulse && 'animate-pulse',
          glow && `shadow-lg ${config.glowColor}`
        )} 
      />
      {showLabel && (
        <span className={cn('text-muted-foreground capitalize font-medium', sizeClasses[size].text)}>
          {config.label}
        </span>
      )}
    </div>
  );
}

export function LiveIndicator({ className, glowing = true, ...props }) {
  return (
    <div className={cn('flex items-center gap-2', className)} {...props}>
      <span 
        className={cn(
          'relative w-2.5 h-2.5 rounded-full bg-red-500',
          glowing && 'shadow-lg shadow-red-500/50'
        )}
      >
        {/* Pulse ring animation */}
        <span className="absolute inset-0 rounded-full bg-red-500 animate-ping opacity-75" />
      </span>
      <span className="text-[10px] font-bold text-red-400 uppercase tracking-wider">LIVE</span>
    </div>
  );
}
