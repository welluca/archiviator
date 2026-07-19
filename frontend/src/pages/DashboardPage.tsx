import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Activity, CheckCircle2, XCircle, Loader2, Hammer, FolderOpen, ArrowRight } from 'lucide-react';
import apiClient from '../api/client';
import type { HealthResponse } from '../types';

export default function DashboardPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const fetchHealth = async () => {
      try {
        const { data } = await apiClient.get<HealthResponse>('/health');
        if (!cancelled) setHealth(data);
      } catch (err: any) {
        if (!cancelled) setHealthError(err.message || 'Backend unreachable');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchHealth();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-bold text-white mb-1">Archiviator</h1>
      <p className="text-gray-500 text-sm mb-6">Self-hosted home catalog</p>

      {/* Backend health card */}
      <div className="bg-space-900 border border-space-700 rounded-xl p-6 mb-4">
        <div className="flex items-center gap-2 mb-4">
          <Activity className="w-5 h-5 text-blue-400" />
          <h2 className="text-lg font-semibold text-white">Backend status</h2>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 text-gray-400 text-sm">
            <Loader2 className="w-4 h-4 animate-spin" />
            Checking /api/v1/health...
          </div>
        ) : health ? (
          <div className="flex items-center gap-3">
            <CheckCircle2 className="w-6 h-6 text-green-400" />
            <div>
              <p className="text-white text-sm">
                Status: <span className="text-green-400 font-medium">{health.status}</span>
              </p>
              <p className="text-gray-500 text-xs mt-0.5">
                {health.app} v{health.version}
              </p>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <XCircle className="w-6 h-6 text-red-400" />
            <div>
              <p className="text-white text-sm">Backend unreachable</p>
              <p className="text-gray-500 text-xs mt-0.5">{healthError}</p>
            </div>
          </div>
        )}
      </div>

      {/* Browse card (M2) */}
      <Link
        to="/browse"
        className="group flex items-center gap-4 bg-space-900 border border-space-700 hover:border-blue-500/50 rounded-xl p-6 mb-4 transition-colors"
      >
        <div className="w-10 h-10 rounded-lg bg-blue-500/10 border border-blue-500/30 flex items-center justify-center shrink-0">
          <FolderOpen className="w-5 h-5 text-blue-400" />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-lg font-semibold text-white">Browse</h2>
          <p className="text-gray-400 text-sm">
            Explore your spaces, furniture, containers, and items.
          </p>
        </div>
        <ArrowRight className="w-5 h-5 text-gray-600 group-hover:text-blue-400 transition-colors shrink-0" />
      </Link>

      {/* M1 note */}
      <div className="bg-space-900 border border-space-700 rounded-xl p-6">
        <div className="flex items-center gap-2 mb-2">
          <Hammer className="w-5 h-5 text-yellow-400" />
          <h2 className="text-lg font-semibold text-white">Milestone M1 — walking skeleton</h2>
        </div>
        <p className="text-gray-400 text-sm">
          This is the M1 skeleton: authentication, app shell, and backend health check.
          Catalog browsing, search, house map, labels, and drive features arrive in later milestones.
        </p>
      </div>
    </div>
  );
}
