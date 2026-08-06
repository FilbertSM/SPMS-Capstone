import React, { useState, useEffect } from 'react';
import AuditLogs from './AuditLogs'; 
import Settings from './Settings'; 
import { fetchJsonWithAuth } from '../utils/api';

const AdminDashboard = () => {
  const [activeTab, setActiveTab] = useState('users');
  const [users, setUsers] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  // --- STATE UNTUK EDIT MODAL ---
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [createFormData, setCreateFormData] = useState({ full_name: '', email: '', password: '', role: 'technician' });
  const [isCreating, setIsCreating] = useState(false);
  const [modalError, setModalError] = useState(null);
  const [selectedUser, setSelectedUser] = useState(null);
  const [editFormData, setEditFormData] = useState({ role: '', is_active: true });
  const [isSaving, setIsSaving] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(null);
  const currentUserRole = localStorage.getItem('role') || 'technician';
  const isSuperAdmin = currentUserRole.toLowerCase() === 'super_admin';

  useEffect(() => {
    if (activeTab === 'users') {
      loadUsers();
    }
  }, [activeTab]);

  const loadUsers = async () => {
    setIsLoading(true);
    try {
      const data = await fetchJsonWithAuth('/api/users');
      setUsers(data);
    } catch (err) {
      setError(err.message || 'Failed to load users. Backend endpoint missing?');
    } finally {
      setIsLoading(false);
    }
  };

  // --- HANDLERS FOR EDIT USER ---
  const openEditModal = (user) => {
    setSelectedUser(user);
    setEditFormData({ role: user.role, is_active: user.is_active });
    setIsEditModalOpen(true);
  };

  const closeEditModal = () => {
    setIsEditModalOpen(false);
    setSelectedUser(null);
  };

  const handleSaveUser = async () => {
  setIsSaving(true);
  try {
    await fetchJsonWithAuth(`/api/users/${selectedUser.id}`, {
      method: 'PATCH', 
      body: JSON.stringify(editFormData),
    });
    
    loadUsers(); 
    closeEditModal();
  } catch (err) {
    alert("Failed to update user: " + err.message);
  } finally {
    setIsSaving(false);
  }
};

  const handleDeleteUser = (user) => {
    setDeleteConfirm(user); 
  };

    const confirmDelete = async () => {
    try {
        await fetchJsonWithAuth(`/api/users/${deleteConfirm.id}`, { method: 'DELETE' });
        loadUsers();
        setDeleteConfirm(null);
    } catch (err) {
        alert("Failed: " + err.message);
    }
    };

  const handleCreateUser = async () => {
    setIsCreating(true);
    setModalError(null); 
    try {
      await fetchJsonWithAuth('/api/users', {
        method: 'POST',
        body: JSON.stringify(createFormData),
      });
      
      loadUsers(); 
      setIsCreateModalOpen(false);
      setCreateFormData({ full_name: '', email: '', password: '', role: 'technician' }); 
    } catch (err) {
      setModalError(err.message);
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-[#f1f4f3] font-body relative">
      
      {/* --- HEADER & TAB NAVIGATION --- */}
      <div className="bg-white px-8 pt-8 shrink-0 shadow-sm z-10">
        <div className="mb-6">
          <h1 className="text-2xl font-black text-[#1b263b] font-headline">Admin Control Panel</h1>
          <p className="text-sm text-[#45474d] mt-1">Manage system users, security audit trails, and threshold settings.</p>
        </div>

        <div className="flex gap-6 border-b border-[#c5c6cd]/30">
          <button
            onClick={() => setActiveTab('users')}
            className={`pb-4 text-sm font-bold flex items-center gap-2 transition-all border-b-2 ${
              activeTab === 'users' ? 'text-[#1b263b] border-[#1b263b]' : 'text-[#75777d] border-transparent hover:text-[#1b263b]'
            }`}
          >
            <span className="material-symbols-outlined text-[18px]">manage_accounts</span>
            User Management
          </button>
          <button
            onClick={() => setActiveTab('audit')}
            className={`pb-4 text-sm font-bold flex items-center gap-2 transition-all border-b-2 ${
              activeTab === 'audit' ? 'text-[#1b263b] border-[#1b263b]' : 'text-[#75777d] border-transparent hover:text-[#1b263b]'
            }`}
          >
            <span className="material-symbols-outlined text-[18px]">security</span>
            Security Audit Logs
          </button>
          <button
            onClick={() => setActiveTab('settings')}
            className={`pb-4 text-sm font-bold flex items-center gap-2 transition-all border-b-2 ${
              activeTab === 'settings' ? 'text-[#1b263b] border-[#1b263b]' : 'text-[#75777d] border-transparent hover:text-[#1b263b]'
            }`}
          >
            <span className="material-symbols-outlined text-[18px]">tune</span>
            System Settings
          </button>
        </div>
      </div>

      {/* --- TAB CONTENT --- */}
      <div className="flex-1 overflow-hidden flex flex-col">
        {activeTab === 'users' ? (
          <div className="p-8 h-full overflow-y-auto">
            <div className="mb-8 flex justify-between items-end">
              <div>
                <h2 className="heading-primary text-xl flex items-center gap-3 text-[#1b263b]">
                  <span className="material-symbols-outlined text-2xl">groups</span>
                  Registered Personnel
                </h2>
                <p className="text-subtitle mt-1">Overview of all active and inactive accounts.</p>
              </div>
              
              {/* --- TOMBOL ADD USER DITAMBAHKAN DI SINI --- */}
              {isSuperAdmin && (
                <button 
                  onClick={() => setIsCreateModalOpen(true)}
                  className="px-4 py-2 bg-[#1b263b] text-white text-sm font-bold rounded-lg flex items-center gap-2 hover:bg-[#1b263b]/90 transition-colors shadow-sm"
                >
                  <span className="material-symbols-outlined text-[18px]">person_add</span>
                  Add New User
                </button>
              )}
              {/* ------------------------------------------- */}
              
            </div>

            {error && (
              <div className="p-4 mb-6 bg-[#ba1a1a]/10 border border-[#ba1a1a]/20 text-[#ba1a1a] rounded-lg text-sm font-bold flex items-center gap-3">
                <span className="material-symbols-outlined">report</span> {error}
              </div>
            )}

            <div className="bg-white rounded-xl shadow-sm border border-[#c5c6cd]/20 overflow-x-auto">
              <table className="min-w-full w-full text-left border-collapse">
               <thead>
                 <tr className="bg-[#f8faf9] border-b border-[#c5c6cd]/30">
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-[#75777d]">Personnel Name</th>
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-[#75777d]">Email Address</th>
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-[#75777d]">Access Role</th>
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-[#75777d]">Status</th>
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-[#75777d]">Join Date</th>
                    
                    {/* Kolom Action hanya muncul untuk Super Admin */}
                    {isSuperAdmin && (
                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-[#75777d] text-right">Actions</th>
                    )}
                 </tr>
                </thead>
                <tbody className="divide-y divide-[#ebeeed]">
                  {isLoading ? (
                    <tr><td colSpan="6" className="text-center py-20 text-sm text-[#75777d] italic flex items-center justify-center gap-2"><span className="material-symbols-outlined animate-spin">sync</span> Loading users...</td></tr>
                  ) : users.length === 0 ? (
                    <tr><td colSpan="6" className="text-center py-20 text-sm text-[#75777d]">No users found.</td></tr>
                  ) : (
                    users.map((user) => (
                      <tr key={user.id} className="hover:bg-[#f9fafb] transition-colors">
                        <td className="px-6 py-4">
                          <p className="text-xs font-bold text-[#1b263b]">{user.full_name}</p>
                        </td>
                        <td className="px-6 py-4 text-xs font-medium text-[#45474d]">{user.email}</td>
                        <td className="px-6 py-4">
                          <span className={`inline-flex items-center px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-widest ${
                            user.role === 'admin' ? 'bg-[#1b263b] text-[#6bfe9c]' : 'bg-[#e0e3e2] text-[#45474d]'
                          }`}>
                            {user.role}
                          </span>
                        </td>
                        <td className="px-6 py-4">
                          <span className={`inline-flex items-center px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-widest ${
                            user.is_active ? 'bg-[#2ecc71]/10 text-[#00743a]' : 'bg-[#ba1a1a]/10 text-[#ba1a1a]'
                          }`}>
                            {user.is_active ? 'Active' : 'Disabled'}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-xs font-medium text-[#75777d]">
                          {user.created_at ? new Date(user.created_at).toLocaleDateString('en-GB') : '-'}
                        </td>
                       <td className="px-6 py-4 text-right flex justify-end gap-2">
                           {isSuperAdmin && (
                             <td className="px-6 py-4 text-right flex justify-end gap-2">
                                <button 
                                    onClick={() => openEditModal(user)}
                                    className="p-1.5 text-[#75777d] hover:text-[#1b263b] hover:bg-[#e0e3e2] rounded-md transition-all"
                                    title="Edit User"
                                >
                                    <span className="material-symbols-outlined text-[18px]">edit</span>
                                </button>

                                <button 
                                    onClick={() => handleDeleteUser(user)}
                                    className="p-1.5 text-[#ba1a1a] hover:bg-[#ffdad6] rounded-md transition-all"
                                    title="Permanently Delete User"
                                >
                                    <span className="material-symbols-outlined text-[18px]">delete</span>
                                </button>
                             </td>
                            )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        ) : activeTab === 'audit' ? (
          <AuditLogs />
        ) : (
          <div className="h-full overflow-y-auto">
            <Settings />
          </div>
        )}
      </div>
      
       {deleteConfirm && (
         <div className="fixed inset-0 z-[100] flex items-center justify-center bg-[#1b263b]/40 backdrop-blur-sm p-4">
           <div className="bg-white rounded-xl shadow-2xl p-6 w-full max-w-sm">
             <h3 className="font-bold text-lg text-[#ba1a1a] mb-2">Delete User?</h3>
               <p className="text-sm text-[#45474d] mb-6">Are you sure you want to PERMANENTLY delete <strong>{deleteConfirm.full_name}</strong>? This cannot be undone.</p>
                <div className="flex gap-3">
                  <button onClick={() => setDeleteConfirm(null)} className="flex-1 px-4 py-2 text-sm font-bold text-[#75777d] bg-[#ebeeed] rounded-lg">Cancel</button>
                  <button onClick={confirmDelete} className="flex-1 px-4 py-2 text-sm font-bold text-white bg-[#ba1a1a] rounded-lg">Delete</button>
                </div>
           </div>
         </div>
        )}

      {/* --- EDIT USER MODAL --- */}
      {isEditModalOpen && selectedUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#1b263b]/40 backdrop-blur-sm p-4 animate-fade-in">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-md overflow-hidden">
            <div className="px-6 py-4 border-b border-[#c5c6cd]/30 flex justify-between items-center bg-[#f8faf9]">
              <h3 className="font-bold text-[#1b263b] flex items-center gap-2">
                <span className="material-symbols-outlined">edit_square</span>
                Edit User Access
              </h3>
              <button onClick={closeEditModal} className="text-[#75777d] hover:text-[#ba1a1a]">
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>
            
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-[10px] font-bold text-[#75777d] uppercase tracking-widest mb-1">Personnel</label>
                <div className="text-sm font-bold text-[#1b263b]">{selectedUser.full_name}</div>
                <div className="text-xs text-[#45474d]">{selectedUser.email}</div>
              </div>

              <div>
                <label className="block text-[10px] font-bold text-[#75777d] uppercase tracking-widest mb-2">Access Role</label>
                <select 
                  value={editFormData.role}
                  onChange={(e) => setEditFormData({...editFormData, role: e.target.value})}
                  className="w-full border border-[#c5c6cd] rounded-lg px-3 py-2 text-sm text-[#1b263b] focus:outline-none focus:border-[#1b263b]"
                >
                  <option value="technician">Technician</option>
                  <option value="admin">Admin</option>
                  <option value="super_admin">Super Admin</option>
                </select>
              </div>

              <div>
                <label className="block text-[10px] font-bold text-[#75777d] uppercase tracking-widest mb-2">Account Status</label>
                <select 
                  value={editFormData.is_active ? 'true' : 'false'}
                  onChange={(e) => setEditFormData({...editFormData, is_active: e.target.value === 'true'})}
                  className="w-full border border-[#c5c6cd] rounded-lg px-3 py-2 text-sm text-[#1b263b] focus:outline-none focus:border-[#1b263b]"
                >
                  <option value="true">Active</option>
                  <option value="false">Disabled</option>
                </select>
              </div>
            </div>

            <div className="px-6 py-4 border-t border-[#c5c6cd]/30 bg-[#f8faf9] flex justify-end gap-3">
              <button onClick={closeEditModal} className="px-4 py-2 text-sm font-bold text-[#45474d] hover:bg-[#e0e3e2] rounded-lg transition-colors">
                Cancel
              </button>
              <button onClick={handleSaveUser} disabled={isSaving} className="px-4 py-2 text-sm font-bold bg-[#1b263b] text-white rounded-lg hover:bg-[#1b263b]/90 transition-colors flex items-center gap-2">
                {isSaving ? <span className="material-symbols-outlined animate-spin text-[16px]">sync</span> : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}
      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#1b263b]/40 backdrop-blur-sm p-4 animate-fade-in">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-md overflow-hidden">
           <div className="px-6 py-4 border-b border-[#c5c6cd]/30 flex justify-between items-center bg-[#f8faf9]">
              <h3 className="font-bold text-[#1b263b] flex items-center gap-2">
                <span className="material-symbols-outlined">person_add</span>
                Create New User
              </h3>
              <button 
                onClick={() => {
                  setIsCreateModalOpen(false);
                  setModalError(null); // Hapus error jika modal ditutup
                }} 
                className="text-[#75777d] hover:text-[#ba1a1a]"
              >
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>
            
            {modalError && (
              <div className="mx-6 mt-4 p-3 bg-[#ba1a1a]/10 border border-[#ba1a1a]/20 text-[#ba1a1a] rounded-lg text-xs font-bold flex items-start gap-2 animate-fade-in">
                <span className="material-symbols-outlined text-[16px]">error</span>
                <span className="flex-1 leading-relaxed">{modalError}</span>
              </div>
            )}

            <div className="p-6 space-y-4">
              <div>
                <label className="block text-[10px] font-bold text-[#75777d] uppercase tracking-widest mb-2">Full Name</label>
                <input 
                  type="text"
                  value={createFormData.full_name}
                  onChange={(e) => setCreateFormData({...createFormData, full_name: e.target.value})}
                  className="w-full border border-[#c5c6cd] rounded-lg px-3 py-2 text-sm text-[#1b263b] focus:outline-none focus:border-[#1b263b]"
                  placeholder="e.g. budi.p@kalbecomsumerhealth.co.id"
                />
              </div>

              <div>
                <label className="block text-[10px] font-bold text-[#75777d] uppercase tracking-widest mb-2">Email Address</label>
                <input 
                  type="email"
                  value={createFormData.email}
                  onChange={(e) => setCreateFormData({...createFormData, email: e.target.value})}
                  className="w-full border border-[#c5c6cd] rounded-lg px-3 py-2 text-sm text-[#1b263b] focus:outline-none focus:border-[#1b263b]"
                  placeholder="e.g. budi.p@kalbeconsumerhealth.co.id"
                />
              </div>

              <div>
                <label className="block text-[10px] font-bold text-[#75777d] uppercase tracking-widest mb-2">Temporary Password</label>
                <input 
                  type="password"
                  value={createFormData.password}
                  onChange={(e) => setCreateFormData({...createFormData, password: e.target.value})}
                  className="w-full border border-[#c5c6cd] rounded-lg px-3 py-2 text-sm text-[#1b263b] focus:outline-none focus:border-[#1b263b]"
                  placeholder="Must contain 8 chars, uppercase, number & symbol"
                />
              </div>

              <div>
                <label className="block text-[10px] font-bold text-[#75777d] uppercase tracking-widest mb-2">Access Role</label>
                <select 
                  value={createFormData.role}
                  onChange={(e) => setCreateFormData({...createFormData, role: e.target.value})}
                  className="w-full border border-[#c5c6cd] rounded-lg px-3 py-2 text-sm text-[#1b263b] focus:outline-none focus:border-[#1b263b]"
                >
                  <option value="technician">Technician</option>
                  <option value="admin">Admin</option>
                  <option value="super_admin">Super Admin</option>
                </select>
              </div>
            </div>

            <div className="px-6 py-4 border-t border-[#c5c6cd]/30 bg-[#f8faf9] flex justify-end gap-3">
              <button onClick={() => setIsCreateModalOpen(false)} className="px-4 py-2 text-sm font-bold text-[#45474d] hover:bg-[#e0e3e2] rounded-lg transition-colors">
                Cancel
              </button>
              <button onClick={handleCreateUser} disabled={isCreating || !createFormData.email || !createFormData.password} className="px-4 py-2 text-sm font-bold bg-[#1b263b] text-white rounded-lg hover:bg-[#1b263b]/90 transition-colors flex items-center gap-2 disabled:opacity-50">
                {isCreating ? <span className="material-symbols-outlined animate-spin text-[16px]">sync</span> : 'Create User'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminDashboard;  