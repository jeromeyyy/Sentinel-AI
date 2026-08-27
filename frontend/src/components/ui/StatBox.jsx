'use client';

import { useEffect, useRef, useState } from 'react';
import { cn } from '@/lib/utils';

export function StatBox({ 
  label, 
  value, 
  icon, 
  trend, 
  trendValue, 
  color = 'default', 
  size = 'md', 
  animate = true, 
  glass = false, 
  className, 
  ...props 
}) {
  const [displayValue, setDisplayValue] = useState(0);
  const prevValue = useRef(0);

  // Animated counter
  useEffect(() => {
    if (!animate || typeof value !== 'number') {
      setDisplayValue(value);
      return;
    }

    const start = prevValue.current;
    const end = value;
    const duration = 600;
    const startTime = Date.now();

    const animateCount = () => {
      const elapsed = Date.now() - startTime;
      const progress = Math.min(elapsed / duration, 1);
      
      // Easing function (ease-out cubic)
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = Math.round(start + (end - start) * eased);
      
      setDisplayValue(current);
      
      if (progress < 1) {
        requestAnimationFrame(animateCount);
      }
    };

    requestAnimationFrame(animateCount);
    prevValue.current = value;
  }, [value, animate]);

  const colorConfig = {
    default: { text: 'text-foreground', bg: 'bg-muted', glow: '' },
    blue: { text: 'text-blue-400', bg: 'bg-blue-500/10', glow: 'shadow-blue-500/20' },
    green: { text: 'text-green-400', bg: 'bg-green-500/10', glow: 'shadow-green-500/20' },
    red: { text: 'text-red-400', bg: 'bg-red-500/10', glow: 'shadow-red-500/20' },
    orange: { text: 'text-orange-400', bg: 'bg-orange-500/10', glow: 'shadow-orange-500/20' },
    yellow: { text: 'text-yellow-400', bg: 'bg-yellow-500/10', glow: 'shadow-yellow-500/20' },
    purple: { text: 'text-purple-400', bg: 'bg-purple-500/10', glow: 'shadow-purple-500/20' },
  };

  const sizeClasses = {
    sm: { value: 'text-xl', label: 'text-[10px]', icon: 'p-2' },
    md: { value: 'text-2xl', label: 'text-xs', icon: 'p-2.5' },
    lg: { value: 'text-3xl', label: 'text-sm', icon: 'p-3' },
  };

  const colorClass = colorConfig[color] || colorConfig.default;

  return (
    <div 
      className={cn(
        'rounded-2xl p-5 flex flex-col transition-all duration-300',
        glass 
          ? 'bg-card/60 backdrop-blur-xl border border-white/10' 
          : 'bg-card border border-border',
        'hover:shadow-lg hover:-translate-y-0.5',
        glass && colorClass.glow && `shadow-lg ${colorClass.glow}`,
        className
      )}
      {...props}
    >
      <div className="flex items-start justify-between mb-3">
        {icon && (
          <div className={cn(
            'rounded-xl',
            sizeClasses[size].icon,
            colorClass.bg,
            colorClass.text
          )}>
            {icon}
          </div>
        )}
        {trend && (
          <div className={cn(
            'flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-lg',
            trend === 'up' ? 'text-green-400 bg-green-500/10' : 'text-red-400 bg-red-500/10'
          )}>
            <span className="text-sm">{trend === 'up' ? '↑' : '↓'}</span>
            <span>{trendValue}</span>
          </div>
        )}
      </div>
      <div className={cn('font-bold tabular-nums tracking-tight', sizeClasses[size].value, colorClass.text)}>
        {displayValue}
      </div>
      <div className={cn('text-muted-foreground uppercase tracking-wider mt-1 font-medium', sizeClasses[size].label)}>
        {label}
      </div>
    </div>
  );
}
