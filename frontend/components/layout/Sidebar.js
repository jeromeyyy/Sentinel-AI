'use client';

import { useRouter } from 'next/router';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  LayoutDashboard, 
  Camera, 
  AlertTriangle, 
  BarChart3, 
  Settings,
  Home,
  ChevronLeft,
  ChevronRight,
  Moon,
  Sun,
  LogOut,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { useTheme } from '../../contexts/ThemeContext';
import { StatusIndicator } from '../ui/StatusIndicator';
import { useAuth } from '../GoogleLogin';

const NAV_ITEMS = [
  { id: 'monitoring', href: '/monitor', icon: LayoutDashboard, label: 'Dashboard' },
  { id: 'cameras', href: '/monitor?tab=cameras', icon: Camera, label: 'Cameras' },
  { id: 'incidents', href: '/monitor?tab=incidents', icon: AlertTriangle, label: 'Incidents' },
  { id: 'analytics', href: '/monitor?tab=analytics', icon: BarChart3, label: 'Analytics' },
  { id: 'settings', href: '/monitor?tab=settings', icon: Settings, label: 'Settings' },
];

export function Sidebar({ 
  activeTab, 
  onTabChange,
  wsStatus = 'disconnected',
  collapsed = false,
  onToggleCollapse,
}) {
  const router = useRouter();
  const { theme, toggleTheme } = useTheme();
  const { user, signOut } = useAuth();

  const handleSignOut = () => {
    signOut();
    router.replace('/login');
  };

  return (
    <motion.aside 
      initial={false}
      animate={{ width: collapsed ? 72 : 256 }}
      transition={{ duration: 0.3, ease: 'easeInOut' }}
      className={cn(
        'fixed left-0 top-0 bottom-0 z-40',
        'bg-gradient-to-b from-card/90 via-card/80 to-card/90 backdrop-blur-xl border-r border-border/50',
        'flex flex-col',
        'shadow-2xl shadow-black/10'
      )}
    >
      {/* Logo */}
      <div className="h-20 px-4 flex items-center justify-between border-b border-border/50 bg-gradient-to-r from-blue-500/5 via-transparent to-purple-500/5">
        <Link href="/" className="flex items-center gap-3 overflow-hidden">
          <motion.div 
            whileHover={{ rotate: 10, scale: 1.05 }}
            className="w-12 h-12 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl flex items-center justify-center flex-shrink-0 shadow-xl shadow-blue-500/30"
          >
            <svg className="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
          </motion.div>
          <AnimatePresence>
            {!collapsed && (
              <motion.div 
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -10 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <div className="text-foreground font-bold text-xl bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">SentinelAI</div>
                <div className="text-muted-foreground text-xs">AI-Powered Safety</div>
              </motion.div>
            )}
          </AnimatePresence>
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-4 px-3 space-y-2 overflow-y-auto">
        {NAV_ITEMS.map((item, index) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          
          return (
            <motion.button
              key={item.id}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.05 }}
              onClick={() => onTabChange(item.id)}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              className={cn(
                'w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200',
                'text-sm font-medium relative overflow-hidden',
                isActive 
                  ? 'bg-gradient-to-r from-blue-500/20 via-blue-500/10 to-purple-500/10 text-blue-400 shadow-lg shadow-blue-500/10 border border-blue-500/20' 
                  : 'text-muted-foreground hover:bg-gradient-to-r hover:from-muted/80 hover:to-muted/40 hover:text-foreground border border-transparent',
                collapsed && 'justify-center px-2'
              )}
              title={collapsed ? item.label : undefined}
            >
              {/* Active indicator */}
              {isActive && (
                <motion.div
                  layoutId="activeTab"
                  className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-blue-400 to-purple-500 rounded-r-full"
                />
              )}
              <Icon className={cn('w-5 h-5 flex-shrink-0 relative z-10', isActive && 'text-blue-400')} />
              <AnimatePresence>
                {!collapsed && (
                  <motion.span
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="relative z-10"
                  >
                    {item.label}
                  </motion.span>
                )}
              </AnimatePresence>
            </motion.button>
          );
        })}
      </nav>

      {/* Bottom Section */}
      <div className="p-3 space-y-2 border-t border-border/50">
        {/* User Profile (if exists) */}
        {user && !collapsed && (
          <div className="flex items-center gap-3 px-3 py-2 mb-2">
            {user.picture && (
              <img
                src={user.picture}
                alt={user.name}
                className="w-8 h-8 rounded-full border border-border"
              />
            )}
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-foreground truncate">{user.name}</p>
              <p className="text-xs text-muted-foreground truncate">{user.email}</p>
            </div>
          </div>
        )}

        {/* Theme Toggle */}
        <button
          onClick={toggleTheme}
          className={cn(
            'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl',
            'text-muted-foreground hover:bg-muted hover:text-foreground transition-all',
            collapsed && 'justify-center px-2'
          )}
          title={collapsed ? `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode` : undefined}
        >
          {theme === 'dark' ? (
            <Sun className="w-5 h-5" />
          ) : (
            <Moon className="w-5 h-5" />
          )}
          <AnimatePresence>
            {!collapsed && (
              <motion.span 
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="text-sm"
              >
                {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
              </motion.span>
            )}
          </AnimatePresence>
        </button>

        {/* Connection Status */}
        <div className={cn(
          'flex items-center gap-3 px-3 py-2.5 rounded-xl bg-muted/50',
          collapsed && 'justify-center px-2'
        )}>
          <StatusIndicator status={wsStatus} showLabel={!collapsed} size="md" glow />
        </div>

        {/* Sign Out */}
        {user && (
          <button
            onClick={handleSignOut}
            className={cn(
              'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl',
              'text-red-400/70 hover:bg-red-500/10 hover:text-red-400 transition-all',
              collapsed && 'justify-center px-2'
            )}
            title={collapsed ? 'Sign Out' : undefined}
          >
            <LogOut className="w-5 h-5" />
            <AnimatePresence>
              {!collapsed && (
                <motion.span 
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="text-sm"
                >
                  Sign Out
                </motion.span>
              )}
            </AnimatePresence>
          </button>
        )}

        {/* Collapse Toggle */}
        {onToggleCollapse && (
          <button
            onClick={onToggleCollapse}
            className={cn(
              'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl',
              'text-muted-foreground hover:bg-muted hover:text-foreground transition-all',
              collapsed && 'justify-center px-2'
            )}
          >
            {collapsed ? (
              <ChevronRight className="w-5 h-5" />
            ) : (
              <>
                <ChevronLeft className="w-5 h-5" />
                <span className="text-sm">Collapse</span>
              </>
            )}
          </button>
        )}
      </div>
    </motion.aside>
  );
}
