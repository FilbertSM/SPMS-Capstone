import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import TopNav from './TopNav';

const Layout = () => {
  return (
    <div className="bg-[#f7faf9] text-[#181c1c] selection:bg-[#6bfe9c] selection:text-[#00210c] min-h-screen flex overflow-hidden font-body">
      <Sidebar />
      <main className="flex-1 flex flex-col h-screen overflow-hidden">
        <TopNav />
        <div className="flex-1 min-h-0 overflow-y-auto">
          <Outlet />
        </div>
        
        {/* Status bar */}
        <footer className="bg-[#051125] text-white px-4 sm:px-6 py-2 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-1 z-10 mb-[64px] md:mb-0">
          <div className="flex flex-wrap items-center gap-2 sm:gap-4">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 bg-[#6bfe9c] rounded-full"></span>
              <span className="text-[10px] font-bold uppercase tracking-widest text-[#6bfe9c]">Predictive Monitoring Only</span>
            </div>
            <div className="hidden sm:block h-3 w-[1px] bg-white/20"></div>
            <p className="hidden sm:block text-[10px] font-medium text-white/60">No machine control commands are issued by this dashboard.</p>
          </div>
          <div className="hidden sm:flex items-center gap-4">
            <p className="text-[10px] font-bold uppercase tracking-widest text-white/80 flex items-center gap-2">
              <span className="material-symbols-outlined text-[14px]">verified_user</span>
              Authenticated App Shell
            </p>
          </div>
        </footer>
      </main>
    </div>
  );
};

export default Layout;
