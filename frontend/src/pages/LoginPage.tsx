import { useState, FormEvent } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Archive, Loader2 } from 'lucide-react';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [localError, setLocalError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  // Return-to destination, in priority order:
  // 1. state.from set by ProtectedRoute (full location incl. search + hash —
  //    /a/{tag} QR scans while logged out depend on this),
  // 2. ?next= set by the axios interceptor's hard redirect on refresh failure,
  // 3. '/'. Only same-origin paths are accepted (no scheme/host injection).
  const stateFrom = (location.state as any)?.from as
    | { pathname: string; search?: string; hash?: string }
    | undefined;
  const nextParam = new URLSearchParams(location.search).get('next');
  let from = '/';
  if (stateFrom?.pathname) {
    from = `${stateFrom.pathname}${stateFrom.search ?? ''}${stateFrom.hash ?? ''}`;
  } else if (nextParam && nextParam.startsWith('/') && !nextParam.startsWith('//')) {
    from = nextParam;
  }

  if (isAuthenticated) {
    navigate(from, { replace: true });
    return null;
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLocalError('');
    setLoading(true);
    try {
      await login(username, password);
      navigate(from, { replace: true });
    } catch (err: any) {
      setLocalError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-space-950 px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <Archive className="w-12 h-12 text-blue-400 mx-auto mb-3" />
          <h1 className="text-2xl font-bold text-white">Archiviator</h1>
          <p className="text-gray-500 text-sm mt-1">Sign in to your home catalog</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-space-900 rounded-xl p-6 border border-space-700 space-y-4">
          {localError && (
            <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-2">
              {localError}
            </div>
          )}

          <div>
            <label className="block text-sm text-gray-400 mb-1">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-space-800 border border-space-600 rounded-lg px-3 py-2 text-white
                         focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500"
              required
              autoFocus
            />
          </div>

          <div>
            <label className="block text-sm text-gray-400 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-space-800 border border-space-600 rounded-lg px-3 py-2 text-white
                         focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500"
              required
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-blue-600/50 text-white
                       font-medium py-2 rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            {loading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  );
}
