import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './contexts/AuthContext';
import { ProtectedRoute } from './components/auth/ProtectedRoute';
import Layout from './components/layout/Layout';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import BrowsePage from './pages/BrowsePage';
import EntityDetailPage from './pages/EntityDetailPage';
import ComingSoonPage from './pages/ComingSoonPage';

export default function App() {
  const { isAuthenticated } = useAuth();

  return (
    <Routes>
      <Route
        path="/login"
        element={isAuthenticated ? <Navigate to="/" replace /> : <LoginPage />}
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
        <Route path="/entity/:id" element={<EntityDetailPage />} />
        <Route path="/search" element={<ComingSoonPage title="Search" />} />
        <Route path="/house-map" element={<ComingSoonPage title="House Map" />} />
        <Route path="/labels" element={<ComingSoonPage title="Labels" />} />
        <Route path="/drive" element={<ComingSoonPage title="Drive" />} />
        <Route path="/admin" element={<ComingSoonPage title="Admin" />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
