import { useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
  DatabaseBackup,
  FileDown,
  Shapes,
  Shield,
  Smartphone,
  Tags,
  Wrench,
} from 'lucide-react';
import CategoriesFieldsTab from '../components/admin/CategoriesFieldsTab';
import TagsTab from '../components/admin/TagsTab';
import ImportExportTab from '../components/admin/ImportExportTab';
import BackupsTab from '../components/admin/BackupsTab';
import MaintenanceTab from '../components/admin/MaintenanceTab';
import DeviceTokensTab from '../components/admin/DeviceTokensTab';

type TabId =
  | 'categories'
  | 'tags'
  | 'device-tokens'
  | 'import-export'
  | 'backups'
  | 'maintenance';

const TABS: { id: TabId; label: string; icon: LucideIcon }[] = [
  { id: 'categories', label: 'Categories & Fields', icon: Shapes },
  { id: 'tags', label: 'Tags', icon: Tags },
  { id: 'device-tokens', label: 'Device tokens', icon: Smartphone },
  { id: 'import-export', label: 'Import / Export', icon: FileDown },
  { id: 'backups', label: 'Backups', icon: DatabaseBackup },
  { id: 'maintenance', label: 'Maintenance', icon: Wrench },
];

export default function AdminPage() {
  const [tab, setTab] = useState<TabId>('categories');

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex items-center gap-2.5 mb-4">
        <Shield className="w-6 h-6 text-blue-400" />
        <h1 className="text-xl font-bold text-white">Admin</h1>
      </div>

      <div className="md:grid md:grid-cols-[13rem_1fr] md:gap-4 md:items-start">
        {/* Tab rail — vertical on md+, horizontal scroll on mobile */}
        <nav className="flex md:flex-col gap-1 mb-4 md:mb-0 overflow-x-auto pb-1 md:pb-0">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm whitespace-nowrap transition-colors shrink-0 md:shrink md:w-full text-left ${
                tab === id
                  ? 'bg-blue-500/20 text-blue-400'
                  : 'text-gray-400 hover:text-white hover:bg-space-800'
              }`}
            >
              <Icon className="w-4 h-4 shrink-0" />
              {label}
            </button>
          ))}
        </nav>

        <div className="min-w-0">
          {tab === 'categories' && <CategoriesFieldsTab />}
          {tab === 'tags' && <TagsTab />}
          {tab === 'device-tokens' && <DeviceTokensTab />}
          {tab === 'import-export' && <ImportExportTab />}
          {tab === 'backups' && <BackupsTab />}
          {tab === 'maintenance' && <MaintenanceTab />}
        </div>
      </div>
    </div>
  );
}
