import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { LucideIcon } from 'lucide-react';
import {
  Activity,
  AlertTriangle,
  Banknote,
  Box,
  Camera,
  CheckCircle2,
  ChevronRight,
  Clock,
  Cloud,
  Loader2,
  Package,
  XCircle,
} from 'lucide-react';
import apiClient from '../api/client';
import { entitiesApi } from '../api/entities';
import { inventoryApi } from '../api/inventory';
import { driveApi } from '../api/drive';
import EntityIcon from '../components/browse/EntityIcon';
import { formatMoney, formatQuantity } from '../utils/format';
import type { Entity, HealthResponse, ValuationOut } from '../types';

// ── Stat card ────────────────────────────────────────────────────────────────

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  warn,
  amber = false,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  sub?: string;
  warn?: string;
  amber?: boolean;
}) {
  return (
    <div
      className={`bg-space-900 border rounded-xl p-4 ${
        amber ? 'border-amber-700/50' : 'border-space-700'
      }`}
    >
      <div className="flex items-center gap-2 mb-2">
        <Icon className={`w-4 h-4 ${amber ? 'text-amber-400' : 'text-blue-400'}`} />
        <span className="text-xs text-gray-500">{label}</span>
      </div>
      <p className={`text-2xl font-bold ${amber ? 'text-amber-400' : 'text-white'}`}>{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-0.5">{sub}</p>}
      {warn && <p className="text-[11px] text-amber-400/80 mt-0.5">{warn}</p>}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const navigate = useNavigate();

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [counts, setCounts] = useState<{ items: number; containers: number } | null>(null);
  const [valuation, setValuation] = useState<ValuationOut | null>(null);
  const [lowStock, setLowStock] = useState<Entity[] | null>(null);
  const [showAllLowStock, setShowAllLowStock] = useState(false);
  const [recent, setRecent] = useState<Entity[] | null>(null);
  const [driveNewCount, setDriveNewCount] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const loadAll = async () => {
      // Independent loads — one failing endpoint must not blank the others.
      const [healthR, treeR, valuationR, lowStockR, recentR, driveR] =
        await Promise.allSettled([
          apiClient.get<HealthResponse>('/health').then((r) => r.data),
          entitiesApi.getTree(),
          inventoryApi.valuation(),
          inventoryApi.lowStock(),
          inventoryApi.recent(),
          driveApi.status(),
        ]);
      if (cancelled) return;
      if (healthR.status === 'fulfilled') setHealth(healthR.value);
      else setHealthError(healthR.reason?.message || 'Backend unreachable');
      if (treeR.status === 'fulfilled') {
        setCounts({
          items: treeR.value.filter((e) => e.kind === 'item' && !e.archived).length,
          containers: treeR.value.filter((e) => e.kind === 'container' && !e.archived).length,
        });
      }
      if (valuationR.status === 'fulfilled') setValuation(valuationR.value);
      if (lowStockR.status === 'fulfilled') setLowStock(lowStockR.value);
      if (recentR.status === 'fulfilled') setRecent(recentR.value);
      if (driveR.status === 'fulfilled') setDriveNewCount(driveR.value.inbox_counts.new);
      setLoading(false);
    };
    loadAll();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-gray-500 text-sm py-16 justify-center">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading…
      </div>
    );
  }

  const lowCount = lowStock?.length ?? 0;

  return (
    <div className="max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold text-white mb-1">Archiviator</h1>
      <p className="text-gray-500 text-sm mb-5">Self-hosted home catalog</p>

      {/* M7: quick capture */}
      <Link
        to="/intake"
        className="group flex items-center gap-4 bg-gradient-to-r from-blue-600/20 to-space-900 border border-blue-500/40 hover:border-blue-400/70 rounded-xl p-4 mb-5 transition-colors"
      >
        <span className="w-12 h-12 rounded-full bg-blue-600 group-hover:bg-blue-500 flex items-center justify-center transition-colors shrink-0">
          <Camera className="w-6 h-6 text-white" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-white font-semibold text-sm">Quick capture</span>
          <span className="block text-xs text-gray-400 mt-0.5">
            Point, shoot, done — drafts pile up in the Inbox for triage later.
          </span>
        </span>
        <ChevronRight className="w-5 h-5 text-gray-500 group-hover:text-white transition-colors shrink-0" />
      </Link>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
        <StatCard
          icon={Package}
          label="Items"
          value={counts ? String(counts.items) : '—'}
        />
        <StatCard
          icon={Box}
          label="Containers"
          value={counts ? String(counts.containers) : '—'}
        />
        <StatCard
          icon={Banknote}
          label="Total value"
          value={valuation ? formatMoney(valuation.total, valuation.currency) : '—'}
          sub={
            valuation
              ? `${formatMoney(valuation.insured_total, valuation.currency)} insured`
              : undefined
          }
          warn={
            valuation && valuation.mixed_currency_count > 0
              ? `includes ${valuation.mixed_currency_count} ${
                  valuation.mixed_currency_count === 1 ? 'entry' : 'entries'
                } in other currencies, summed numerically`
              : undefined
          }
        />
        <StatCard
          icon={AlertTriangle}
          label="Low stock"
          value={lowStock ? String(lowCount) : '—'}
          sub={lowCount > 0 ? 'consumables to restock' : 'all stocked up'}
          amber={lowCount > 0}
        />
      </div>

      {/* M9: Drive scans inbox chip — only while there is something to triage */}
      {driveNewCount > 0 && (
        <Link
          to="/drive"
          className="group -mt-2 mb-5 flex items-center gap-2.5 w-fit px-3 py-2 rounded-lg bg-blue-900/20 border border-blue-700/40 hover:border-blue-500/60 transition-colors"
        >
          <Cloud className="w-4 h-4 text-blue-400 shrink-0" />
          <span className="text-sm text-white">
            {driveNewCount} new scan{driveNewCount === 1 ? '' : 's'}
          </span>
          <span className="text-xs text-gray-500">in the Drive inbox</span>
          <ChevronRight className="w-4 h-4 text-gray-500 group-hover:text-white transition-colors shrink-0" />
        </Link>
      )}

      {/* Low stock list */}
      {lowCount > 0 && (
        <section className="bg-space-900 border border-amber-700/40 rounded-xl p-4 mb-4">
          <div className="flex items-center gap-2 mb-2.5">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            <h2 className="text-sm font-semibold text-white">Low stock</h2>
            {lowCount > 5 && (
              <button
                type="button"
                onClick={() => setShowAllLowStock((v) => !v)}
                className="text-xs text-blue-400 hover:text-blue-300 hover:underline"
              >
                {showAllLowStock ? 'Show less' : `Show all ${lowCount}`}
              </button>
            )}
          </div>
          <div
            className={`flex flex-wrap gap-2 ${
              showAllLowStock ? 'max-h-64 overflow-y-auto' : ''
            }`}
          >
            {(showAllLowStock ? lowStock! : lowStock!.slice(0, 5)).map((e) => (
              <Link
                key={e.id}
                to={`/entity/${e.id}`}
                className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-amber-900/20 border border-amber-700/40 hover:border-amber-500/60 transition-colors"
              >
                <EntityIcon entity={e} className="w-4 h-4" />
                <span className="text-sm text-white">{e.name}</span>
                <span className="text-xs text-amber-400">
                  {formatQuantity(e.quantity)}
                  {e.unit ? ` ${e.unit}` : ''} / {formatQuantity(e.low_stock_threshold ?? 0)}
                </span>
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* Recently added */}
      <section className="bg-space-900 border border-space-700 rounded-xl p-4 mb-4">
        <div className="flex items-center gap-2 mb-2">
          <Clock className="w-4 h-4 text-blue-400" />
          <h2 className="text-sm font-semibold text-white">Recently added</h2>
        </div>
        {!recent || recent.length === 0 ? (
          <p className="text-sm text-gray-500 py-4 text-center">
            Nothing here yet — add your first entries in{' '}
            <Link to="/browse" className="text-blue-400 hover:underline">
              Browse
            </Link>
            .
          </p>
        ) : (
          <div className="space-y-0.5">
            {recent.map((e) => (
              <div
                key={e.id}
                onClick={() => navigate(`/entity/${e.id}`)}
                className="flex items-center gap-3 px-2 py-2 rounded-lg cursor-pointer border border-transparent hover:border-space-700 hover:bg-space-800/60 transition-colors"
              >
                {e.thumb_url ? (
                  <img
                    src={e.thumb_url}
                    alt=""
                    loading="lazy"
                    className="w-6 h-6 rounded-md object-cover border border-space-700 shrink-0"
                  />
                ) : (
                  <EntityIcon entity={e} className="w-5 h-5 shrink-0" />
                )}
                <span className="text-sm text-white truncate">{e.name}</span>
                {e.breadcrumb && (
                  <span className="flex-1 min-w-0 text-xs text-gray-500 truncate">
                    {e.breadcrumb}
                  </span>
                )}
                <span className="text-xs text-gray-600 shrink-0 ml-auto">
                  {new Date(e.created_at).toLocaleDateString()}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Backend health — small footer card */}
      <div className="bg-space-900 border border-space-700 rounded-xl px-4 py-3 flex items-center gap-3">
        <Activity className="w-4 h-4 text-blue-400 shrink-0" />
        {health ? (
          <>
            <CheckCircle2 className="w-4 h-4 text-green-400 shrink-0" />
            <p className="text-xs text-gray-400">
              Backend <span className="text-green-400">{health.status}</span> — {health.app} v
              {health.version}
            </p>
          </>
        ) : (
          <>
            <XCircle className="w-4 h-4 text-red-400 shrink-0" />
            <p className="text-xs text-gray-400">
              Backend unreachable{healthError ? ` — ${healthError}` : ''}
            </p>
          </>
        )}
      </div>
    </div>
  );
}
