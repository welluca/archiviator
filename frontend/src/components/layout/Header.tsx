import { useState } from 'react';
import { Menu, LogOut, Archive, ChevronDown, User as UserIcon } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';

interface HeaderProps {
  onMenuClick: () => void;
}

export function Header({ onMenuClick }: HeaderProps) {
  const { user, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <header className="bg-space-900 border-b border-space-700 px-4 py-3 pt-[max(0.75rem,env(safe-area-inset-top))] flex items-center justify-between shrink-0">
      <div className="flex items-center gap-3">
        <button onClick={onMenuClick} className="lg:hidden text-gray-400 hover:text-white">
          <Menu className="w-6 h-6" />
        </button>
        <div className="flex items-center gap-2">
          <Archive className="w-6 h-6 text-blue-400" />
          <h1 className="text-lg font-bold text-white">Archiviator</h1>
        </div>
      </div>

      <div className="relative">
        <button
          onClick={() => setMenuOpen((v) => !v)}
          className="flex items-center gap-2 text-sm text-gray-300 hover:text-white transition-colors px-2 py-1 rounded-lg hover:bg-space-800"
        >
          <UserIcon className="w-4 h-4 text-blue-400" />
          <span>{user?.username}</span>
          <ChevronDown className="w-4 h-4 text-gray-500" />
        </button>

        {menuOpen && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
            <div className="absolute right-0 mt-2 z-50 w-44 bg-space-900 border border-space-700 rounded-lg shadow-lg shadow-black/40 py-1">
              <div className="px-3 py-2 border-b border-space-700">
                <p className="text-sm text-white">{user?.username}</p>
                <p className="text-xs text-gray-500">Signed in</p>
              </div>
              <button
                onClick={() => { setMenuOpen(false); logout(); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-300 hover:text-red-400 hover:bg-space-800 transition-colors"
              >
                <LogOut className="w-4 h-4" />
                Sign out
              </button>
            </div>
          </>
        )}
      </div>
    </header>
  );
}

export default Header;
