import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  FolderOpen,
  Camera,
  Search,
  Map,
  QrCode,
  HardDrive,
  Shield,
  X,
} from 'lucide-react';

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/browse', icon: FolderOpen, label: 'Browse' },
  { to: '/intake', icon: Camera, label: 'Intake' },
  { to: '/search', icon: Search, label: 'Search' },
  { to: '/house-map', icon: Map, label: 'House Map' },
  { to: '/labels', icon: QrCode, label: 'Labels' },
  { to: '/drive', icon: HardDrive, label: 'Drive' },
  { to: '/admin', icon: Shield, label: 'Admin' },
];

export function Sidebar({ isOpen, onClose }: SidebarProps) {
  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div className="fixed inset-0 z-40 bg-black/50 lg:hidden" onClick={onClose} />
      )}

      <aside className={`
        fixed inset-y-0 left-0 z-50 w-56 bg-space-900 border-r border-space-700
        transform transition-transform duration-200 ease-in-out
        lg:relative lg:translate-x-0 lg:z-0
        ${isOpen ? 'translate-x-0' : '-translate-x-full'}
      `}>
        <div className="flex items-center justify-between p-4 lg:hidden">
          <span className="text-white font-semibold">Menu</span>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        <nav className="p-3 space-y-1">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={onClose}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive
                    ? 'bg-blue-500/20 text-blue-400'
                    : 'text-gray-400 hover:text-white hover:bg-space-800'
                }`
              }
            >
              <Icon className="w-5 h-5" />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
    </>
  );
}

export default Sidebar;
