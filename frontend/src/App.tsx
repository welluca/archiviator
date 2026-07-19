import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './contexts/AuthContext';
import { ProtectedRoute } from './components/auth/ProtectedRoute';
import Layout from './components/layout/Layout';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import BrowsePage from './pages/BrowsePage';
import IntakePage from './pages/IntakePage';
import EntityDetailPage from './pages/EntityDetailPage';
import SearchPage from './pages/SearchPage';
import LabelsPage from './pages/LabelsPage';
import ScanLandingPage from './pages/ScanLandingPage';
import AdminPage from './pages/AdminPage';
import ComingSoonPage from './pages/ComingSoonPage';

export default function App() {
  const { isAuthenticated } = useAuth();

  return (
    <Routes>
      <Route
        path="/login"
        element={isAuthenticated ? <Navigate to="/" replace /> : <LoginPage />}
      />

      {/* M5: QR-scan landing — protected but outside Layout (mobile-first,
          opened from the phone camera; ProtectedRoute carries it through login). */}
      <Route
        path="/a/:tag"
        element={
          <ProtectedRoute>
            <ScanLandingPage />
          </ProtectedRoute>
        }
      />

      <Route
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/browse" element={<BrowsePage />} />
        <Route path="/intake" element={<IntakePage />} />
        <Route path="/entity/:id" element={<EntityDetailPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/house-map" element={<ComingSoonPage title="House Map" />} />
        <Route path="/labels" element={<LabelsPage />} />
        <Route path="/drive" element={<ComingSoonPage title="Drive" />} />
        <Route path="/admin" element={<AdminPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
