import React from 'react';
import { Link, useLocation } from 'react-router-dom';

const secondaryItems = [
  { path: '/app/status', icon: 'analytics', label: 'Status' },
];

const Sidebar = () => {
  const location = useLocation();

  // Susunan Navigasi dinamis tanpa menu Settings terpisah
  const navItems = [
    { path: '/app', icon: 'dashboard', label: 'Dashboard' },
    { path: '/app/pma', icon: 'trending_up', label: 'PMA' },
    { path: '/app/vibration', icon: 'vibration', label: 'Vibration' },
    { path: '/app/chat', icon: 'chat', label: 'Chatbot' },
    { path: '/app/alerts', icon: 'warning', label: 'Alerts' },
    { path: '/app/daily-summary', icon: 'summarize', label: 'Daily Summary' },
  ];

  const getMenuClasses = (path) => {
    const isActive = location.pathname.startsWith(path) && (path !== '/app' || location.pathname === '/app/');
    const baseClasses = "px-4 py-3 flex items-center gap-3 transition-all text-sm rounded-l-lg ml-2 font-medium";
    
    return isActive
      ? `${baseClasses} bg-white dark:bg-[#051125] text-[#051125] dark:text-[#6bfe9c] font-bold shadow-sm`
      : `${baseClasses} text-[#45474d] dark:text-[#c5c6cd] hover:bg-[#f1f4f3] dark:hover:bg-[#051125]/50`;
  };

  const isMobileActive = (path) => location.pathname === path || (path === '/app' && location.pathname === '/app/');

  return (
    <>
      <aside className="hidden md:flex flex-col h-screen w-64 border-r border-[#c5c6cd]/15 bg-[#ebeeed] dark:bg-[#1b263b] transition-all duration-200 ease-in-out">
        <div className="p-6">
          <div className="flex items-center gap-3 mb-8">
            <div className="w-10 h-10 rounded-lg bg-[#1b263b] flex items-center justify-center">
              <span className="material-symbols-outlined text-[#6bfe9c]">settings_input_component</span>
            </div>
            <div>
              <h2 className="font-headline text-sm font-bold text-[#051125] dark:text-[#6bfe9c] uppercase tracking-tight">Unit PMA-04</h2>
              <p className="font-label text-xs font-medium text-[#45474d]">Active Sentinel</p>
            </div>
          </div>
          
          <nav className="space-y-1">
            {navItems.map((item) => (
              <Link key={item.path} to={item.path} className={getMenuClasses(item.path)}>
                <span className="material-symbols-outlined">{item.icon}</span>
                <span>{item.label}</span>
              </Link>
            ))}
          </nav>
        </div>

        <div className="mt-auto p-6 space-y-6">
          <Link
            to="/app/maintenance"
            className="flex items-center justify-center gap-2 w-full py-3 bg-[#1b263b] hover:bg-[#051125] text-[#6bfe9c] dark:text-[#6bfe9c] font-bold rounded-lg text-xs uppercase tracking-widest shadow-md transition-all duration-200"
          >
            <span className="material-symbols-outlined text-base">assignment_add</span>
            Log Ticket
          </Link>
          <div className="space-y-1">
            {secondaryItems.map((item) => (
              <Link key={item.path} to={item.path} className={getMenuClasses(item.path) + " !py-2 text-xs"}>
                <span className="material-symbols-outlined text-sm">{item.icon}</span>
                <span>{item.label === 'Status' ? 'System Status' : item.label}</span>
              </Link>
            ))}
          </div>
        </div>
      </aside>

      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-40 border-t border-[#c5c6cd]/30 bg-white/95 backdrop-blur px-2 py-2 shadow-[0_-8px_20px_rgba(5,17,37,0.08)]">
        <div className="grid grid-cols-5 gap-1">
          {navItems.slice(0, 4).concat(secondaryItems[0]).map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`flex min-h-12 flex-col items-center justify-center rounded-lg px-1 text-[10px] font-bold ${
                isMobileActive(item.path) ? 'bg-[#1b263b] text-[#6bfe9c]' : 'text-[#45474d] hover:bg-[#f1f4f3]'
              }`}
            >
              <span className="material-symbols-outlined text-[20px]">{item.icon}</span>
              <span className="truncate">{item.label}</span>
            </Link>
          ))}
        </div>
      </nav>
    </>
  );
};

export default Sidebar;