import { lazy, Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Login from './pages/Login';       
import Register from './pages/Register';
import ResetPassword from './pages/ResetPassword';
import ProtectedRoute from './components/Routes'; 
import ForgotPassword from './pages/ForgotPassword';
import SPMSChatDashboard from './pages/SPMSChatbot';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const Alerts = lazy(() => import('./pages/Alerts'));
// Kita ubah lazy import ini menjadi AdminDashboard
const AdminDashboard = lazy(() => import('./pages/AdminDashboard')); 
const Settings = lazy(() => import('./pages/Settings'));
const Profile = lazy(() => import('./pages/Profile'));
const PmaDashboard = lazy(() => import('./pages/PMAChart'));
const MotorChart = lazy(() => import('./pages/VibrationChart'));
const Support = lazy(() => import('./pages/Support'));
const SystemStatus = lazy(() => import('./pages/SystemStatus'));
const MaintenanceTicket = lazy(() => import('./pages/MaintenanceTicket'));

const PageFallback = () => (
  <div className="page-container flex items-center justify-center">
    <div className="flex items-center gap-3 text-sm font-bold text-[#45474d]">
      <span className="material-symbols-outlined animate-spin">sync</span>
      Loading page...
    </div>
  </div>
);

function App() {
  return (
    <Router>
      <Routes>
        {/* Public Routes */}
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/profile" element={<Navigate to="/app/profile" replace />} />
        <Route path="/pma-dashboard" element={<Navigate to="/app/pma" replace />} />
        <Route path="/vibration-chart" element={<Navigate to="/app/vibration" replace />} />
        <Route path="/chat" element={<Navigate to="/app/chat" />} />

        <Route element={<ProtectedRoute />}>
          {/* Redirect root ke /app */}
          <Route path="/" element={<Navigate to="/app" replace />} />

          {/* Internal Routes - PROTECTED */}
          <Route path="/app" element={<Layout />}>
            <Route
              index
              element={<Suspense fallback={<PageFallback />}><Dashboard /></Suspense>}
            />
            <Route path="alerts" element={<Suspense fallback={<PageFallback />}><Alerts /></Suspense>} />
            
            {/* Ubah path ini dari 'audit' ke 'admin' */}
            <Route path="admin" element={<Suspense fallback={<PageFallback />}><AdminDashboard /></Suspense>} />
            
            <Route path="profile" element={<Suspense fallback={<PageFallback />}><Profile /></Suspense>} />
            <Route path="pma" element={<Suspense fallback={<PageFallback />}><PmaDashboard /></Suspense>} />
            <Route path="vibration" element={<Suspense fallback={<PageFallback />}><MotorChart /></Suspense>} />
            <Route path="status" element={<Suspense fallback={<PageFallback />}><SystemStatus /></Suspense>} />
            <Route path="maintenance" element={<Suspense fallback={<PageFallback />}><MaintenanceTicket /></Suspense>} />
            <Route path="chat" element={<Suspense fallback={<PageFallback />}><SPMSChatDashboard /></Suspense>} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Router>
  );
}

export default App;