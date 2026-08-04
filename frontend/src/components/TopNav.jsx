import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchJsonWithAuth } from '../utils/api';

const TopNav = () => {
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const dropdownRef = useRef(null);

  // Deteksi Role
  const role = localStorage.getItem('role') || 'technician';
  const isAdminOrSuper = role === 'admin' || role === 'super_admin';

  // 1. Logout Logic
  const handleLogout = useCallback(() => {
    localStorage.removeItem('spms_token');
    localStorage.removeItem('role'); // Bersihkan memori jabatan saat logout
    navigate('/login');
  }, [navigate]);

  // 2. Fetch User Data on Mount
  useEffect(() => {
    const fetchUserData = async () => {
      const token = localStorage.getItem('spms_token');
      
      if (!token) {
        navigate('/login');
        return;
      }

      try {
        const userData = await fetchJsonWithAuth('/api/users/me');
        setUser(userData);
        localStorage.setItem('role', userData.role); // Sinkronisasi ulang role
      } catch (error) {
        console.error("Failed to fetch user data:", error);
        handleLogout();
      }
    };

    fetchUserData();
  }, [handleLogout, navigate]);

  // 3. Handle click outside to close dropdown
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
        <header className="flex justify-between items-center w-full px-4 sm:px-6 h-[72px] border-b border-[#c5c6cd]/15 bg-[#f7faf9] dark:bg-[#051125] relative z-50 gap-3">       
      {/* Left side: Branding */}
      <div className="flex min-w-0 items-center gap-3 sm:gap-4">
        <h1 className="truncate text-base sm:text-lg font-bold text-[#051125] dark:text-[#f1f4f3] tracking-tighter font-headline">SPMS Granulator 01</h1>
        <div className="hidden sm:block bg-[#f1f4f3] dark:bg-[#1b263b] h-6 w-[1px] mx-2"></div>
        <span className="hidden lg:inline text-[0.6875rem] font-medium font-label uppercase tracking-widest text-[#45474d]">Machine Health Dashboard</span>
      </div>

      {/* Right side: Actions & User Profile */}
      <div className="flex items-center gap-2 sm:gap-6">

        {/* User Profile & Dropdown Trigger */}
        <div className="relative" ref={dropdownRef}>
          <button 
            onClick={() => setIsDropdownOpen((prev) => !prev)}
            className="flex items-center gap-2 sm:gap-3 sm:pl-6 sm:border-l border-[#c5c6cd]/15 hover:opacity-70 transition-opacity text-left bg-transparent"
          >
            <div className="hidden sm:block text-right max-w-40">
              <p className="text-xs font-bold text-[#051125] dark:text-white leading-tight">
                {user ? user.full_name : 'Loading...'}
              </p>
              <p className="text-[10px] text-[#45474d] uppercase tracking-tighter truncate">
                {user ? user.email : 'Authenticating'}
              </p>
            </div>
            <div className="w-8 h-8 rounded-full bg-[#e0e3e2] flex items-center justify-center overflow-hidden">
               {/* Inisial Profil atau Icon */}
               {user ? (
                 <span className="text-xs font-black text-[#1b263b]">{user.full_name.substring(0, 2).toUpperCase()}</span>
               ) : (
                 <span className="material-symbols-outlined text-[#45474d]">person</span>
               )}
            </div>
          </button>

          {/* Dropdown Menu */}
          {isDropdownOpen && (
            <div className="absolute right-0 mt-4 w-56 bg-white dark:bg-[#1b263b] rounded-xl shadow-2xl border border-[#c5c6cd]/30 overflow-hidden z-[100] transform origin-top-right transition-all">
              <div className="py-2">
                <button 
                  onClick={() => {setIsDropdownOpen(false); navigate('/app/profile');}}
                  className="w-full text-left px-5 py-3 text-sm font-bold text-[#051125] dark:text-[#f1f4f3] hover:bg-[#f1f4f3] dark:hover:bg-[#051125] flex items-center gap-3 transition-colors"
                >
                  <span className="material-symbols-outlined text-[20px] text-[#45474d] dark:text-[#c5c6cd]">person</span>
                  My Profile
                </button>
                
                {/* Menu Admin hanya muncul untuk Super Admin / Admin dan mengarah ke /app/admin */}
                {isAdminOrSuper && (
                  <button 
                    onClick={() => {setIsDropdownOpen(false); navigate('/app/admin');}}
                    className="w-full text-left px-5 py-3 text-sm font-bold text-[#051125] dark:text-[#f1f4f3] hover:bg-[#f1f4f3] dark:hover:bg-[#051125] flex items-center gap-3 transition-colors"
                  >
                    <span className="material-symbols-outlined text-[20px] text-[#45474d] dark:text-[#c5c6cd]">admin_panel_settings</span>
                    Admin Panel
                  </button>
                )}
                
                <div className="h-[1px] w-full bg-[#c5c6cd]/20 my-1"></div>
                
                <button 
                  onClick={handleLogout}
                  className="w-full text-left px-5 py-3 text-sm font-bold text-[#ba1a1a] hover:bg-[#ba1a1a]/10 flex items-center gap-3 transition-colors"
                >
                  <span className="material-symbols-outlined text-[20px]">logout</span>
                  Sign Out
                </button>
              </div>
            </div>
          )}
        </div>

      </div>
    </header>
  );
};

export default TopNav;