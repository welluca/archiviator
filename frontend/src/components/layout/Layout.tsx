import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import Header from './Header';
import Sidebar from './Sidebar';
import Omnibox from '../search/Omnibox';

export function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [omniboxOpen, setOmniboxOpen] = useState(false);

  return (
    <div className="h-screen bg-space-950 flex flex-col overflow-hidden">
      <Header
        onMenuClick={() => setSidebarOpen(true)}
        onSearchClick={() => setOmniboxOpen(true)}
      />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
        <main className="flex-1 p-4 sm:p-6 lg:p-8 pb-[max(1rem,env(safe-area-inset-bottom))] overflow-y-auto">
          <Outlet />
        </main>
      </div>

      {/* Global search overlay — stays mounted so Ctrl/Cmd+K works anywhere */}
      <Omnibox
        open={omniboxOpen}
        onOpen={() => setOmniboxOpen(true)}
        onClose={() => setOmniboxOpen(false)}
      />
    </div>
  );
}

export default Layout;
