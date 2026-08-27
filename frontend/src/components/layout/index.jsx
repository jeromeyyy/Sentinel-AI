'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

export function DashboardLayout({ 
  children,
  activeTab,
  onTabChange,
  title,
  subtitle,
  stats,
  alertCount,
  wsStatus,
  topBarActions,
}) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <div className="min-h-screen bg-background">
      {/* Desktop Sidebar */}
      <div className="hidden lg:block">
        <Sidebar
          activeTab={activeTab}
          onTabChange={onTabChange}
          wsStatus={wsStatus}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        />
      </div>

      {/* Mobile Sidebar Overlay */}
      {mobileMenuOpen && (
        <>
          <div 
            className="fixed inset-0 bg-black/50 z-40 lg:hidden"
            onClick={() => setMobileMenuOpen(false)}
          />
          <div className="fixed inset-y-0 left-0 z-50 lg:hidden">
            <Sidebar
              activeTab={activeTab}
              onTabChange={(tab) => {
                onTabChange(tab);
                setMobileMenuOpen(false);
              }}
              wsStatus={wsStatus}
            />
          </div>
        </>
      )}

      {/* Main Content Area */}
      <div className={cn(
        'min-h-screen transition-all duration-300 relative',
        sidebarCollapsed ? 'lg:ml-16' : 'lg:ml-64'
      )}>
        {/* Gradient Background Effects */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-blue-500/5 rounded-full blur-3xl" />
          <div className="absolute bottom-0 left-0 w-[400px] h-[400px] bg-purple-500/5 rounded-full blur-3xl" />
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-gradient-to-br from-blue-500/3 via-transparent to-purple-500/3 rounded-full blur-3xl" />
        </div>

        <TopBar
          title={title}
          subtitle={subtitle}
          stats={stats}
          alertCount={alertCount}
          wsStatus={wsStatus}
          onMenuClick={() => setMobileMenuOpen(true)}
        >
          {topBarActions}
        </TopBar>

        <main className="relative z-10 p-6">
          {children}
        </main>
      </div>
    </div>
  );
}

export { Sidebar } from './Sidebar';
export { TopBar } from './TopBar';
