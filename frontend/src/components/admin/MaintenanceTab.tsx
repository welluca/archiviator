import { useState } from 'react';
import { Loader2, RefreshCw, Wrench } from 'lucide-react';
import { adminApi } from '../../api/admin';
import { apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';

export default function MaintenanceTab() {
  const toast = useToast();
  const [rebuilding, setRebuilding] = useState(false);

  const handleRebuild = async () => {
    if (rebuilding) return;
    setRebuilding(true);
    try {
      const { indexed } = await adminApi.rebuildSearch();
      toast.success(`Search index rebuilt — ${indexed} entr${indexed === 1 ? 'y' : 'ies'} indexed`);
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to rebuild the search index'));
    } finally {
      setRebuilding(false);
    }
  };

  return (
    <div className="bg-space-900 border border-space-700 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-1">
        <Wrench className="w-4 h-4 text-blue-400" />
        <h3 className="text-sm font-semibold text-white">Maintenance</h3>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Drops and refills the full-text search index from the live rows. Use it if search
        results ever look stale or incomplete — it is safe to run any time.
      </p>
      <button
        onClick={handleRebuild}
        disabled={rebuilding}
        className="flex items-center gap-2 px-3 py-2 bg-space-800 hover:bg-space-700 disabled:opacity-50 text-gray-300 border border-space-600 rounded-lg text-sm transition-colors"
      >
        {rebuilding ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <RefreshCw className="w-4 h-4" />
        )}
        Rebuild search index
      </button>
    </div>
  );
}
