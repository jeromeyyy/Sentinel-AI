'use client';

import { motion } from 'framer-motion';
import { Bell, Search, Menu, Zap } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/Badge';
import { StatusIndicator } from '@/components/ui/StatusIndicator';

export function TopBar({ 
  title,
  subtitle,
  stats = {},
  alertCount = 0,
  wsStatus = 'disconnected',
  onMenuClick,
  children,
  className,
}) {
  return (
    <header className={cn(
      'h-20 bg-gradient-to-r from-card/95 via-card/90 to-card/95 backdrop-blur-xl border-b border-border/50 px-6',
      'flex items-center justify-between',
      'sticky top-0 z-30',
      'shadow-xl shadow-black/10',
      className
    )}>
      {/* Background gradient accent */}
      <div className="absolute inset-0 bg-gradient-to-r from-blue-500/5 via-transparent to-purple-500/5" />
      
      {/* Left Section */}
      <div className="flex items-center gap-4 relative z-10">
        {onMenuClick && (
          <button
            onClick={onMenuClick}
            className="lg:hidden p-2 rounded-xl text-muted-foreground hover:text-foreground hover:bg-muted transition-all"
          >
            <Menu className="w-5 h-5" />
          </button>
        )}
        
        <div>
          <h1 className="text-xl font-bold text-foreground">{title}</h1>
          {subtitle && (
            <p className="text-sm text-muted-foreground">{subtitle}</p>
          )}
        </div>
      </div>

      {/* Center Section - Stats */}
      <div className="hidden md:flex items-center gap-8 bg-gradient-to-r from-blue-500/10 via-purple-500/5 to-blue-500/10 px-8 py-3 rounded-2xl border border-blue-500/20 shadow-lg shadow-blue-500/5 relative z-10">
        <StatItem 
          value={stats.activeCameras || 0} 
          label="Active Cameras" 
          color="blue"
        />
        <Divider />
        <StatItem 
          value={stats.totalIncidents || 0} 
          label="Total Incidents" 
          color="default"
        />
        <Divider />
        <StatItem 
          value={stats.criticalAlerts || 0} 
          label="Critical" 
          color="red"
        />
      </div>

      {/* Right Section */}
      <div className="flex items-center gap-4 relative z-10">
        {/* WebSocket Status */}
        <motion.div 
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className={cn(
            'hidden sm:flex items-center gap-2 px-4 py-2.5 rounded-xl border',
            wsStatus === 'connected' 
              ? 'bg-gradient-to-r from-green-500/10 to-emerald-500/10 border-green-500/30 shadow-lg shadow-green-500/10'
              : 'bg-muted/50 border-border/50'
          )}
        >
          <StatusIndicator status={wsStatus} size="sm" showLabel={false} glow />
          {wsStatus === 'connected' && (
            <div className="flex items-center gap-1.5">
              <Zap className="w-3.5 h-3.5 text-green-400" />
              <span className="text-xs text-green-400 font-semibold uppercase tracking-wide">LIVE</span>
            </div>
          )}
          {wsStatus !== 'connected' && (
            <span className="text-xs text-muted-foreground capitalize">{wsStatus}</span>
          )}
        </motion.div>

        {/* Alert Bell */}
        <motion.button 
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          className={cn(
            'relative p-3 rounded-xl transition-all',
            alertCount > 0 
              ? 'bg-gradient-to-br from-red-500/20 to-orange-500/10 text-red-400 border border-red-500/30 shadow-lg shadow-red-500/10'
              : 'text-muted-foreground hover:text-foreground hover:bg-muted'
          )}
        >
          <Bell className="w-5 h-5" />
          {alertCount > 0 && (
            <motion.span 
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              className="absolute -top-1 -right-1 w-6 h-6 bg-gradient-to-br from-red-500 to-orange-500 rounded-full text-white text-[10px] font-bold flex items-center justify-center shadow-lg shadow-red-500/50"
            >
              {alertCount > 99 ? '99+' : alertCount}
            </motion.span>
          )}
        </motion.button>

        {/* Custom Actions */}
        {children}
      </div>
    </header>
  );
}

function StatItem({ value, label, color = 'default' }) {
  const colorClasses = {
    default: 'text-foreground',
    blue: 'text-blue-400',
    red: 'text-red-400',
    green: 'text-green-400',
    orange: 'text-orange-400',
  };

  return (
    <div className="text-center">
      <motion.div 
        key={value}
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className={cn('text-2xl font-bold tabular-nums', colorClasses[color])}
      >
        {value}
      </motion.div>
      <div className="text-[11px] text-muted-foreground uppercase tracking-wider font-medium">
        {label}
      </div>
    </div>
  );
}

function Divider() {
  return <div className="w-px h-10 bg-gradient-to-b from-transparent via-border/50 to-transparent" />;
}
