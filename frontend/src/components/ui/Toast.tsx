import React, { createContext, useContext, useState, useCallback } from 'react';
import { CheckCircle2, Info, AlertTriangle, XCircle, X } from 'lucide-react';

type ToastType = 'success' | 'info' | 'warning' | 'error';

interface Toast {
  id: number;
  type: ToastType;
  message: string;
  exiting?: boolean;
}

interface ToastContextType {
  success: (message: string) => void;
  info: (message: string) => void;
  warning: (message: string) => void;
  error: (message: string) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

let nextId = 0;

const icons: Record<ToastType, React.ReactNode> = {
  success: <CheckCircle2 className="w-5 h-5 text-green-400 shrink-0" />,
  info: <Info className="w-5 h-5 text-blue-400 shrink-0" />,
  warning: <AlertTriangle className="w-5 h-5 text-yellow-400 shrink-0" />,
  error: <XCircle className="w-5 h-5 text-red-400 shrink-0" />,
};

const borderColors: Record<ToastType, string> = {
  success: 'border-green-500/30',
  info: 'border-blue-500/30',
  warning: 'border-yellow-500/30',
  error: 'border-red-500/30',
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.map((t) => (t.id === id ? { ...t, exiting: true } : t)));
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 300);
  }, []);

  const addToast = useCallback((type: ToastType, message: string) => {
    const id = nextId++;
    setToasts((prev) => [...prev, { id, type, message }]);
    const duration = type === 'error' ? 6000 : 4000;
    setTimeout(() => dismiss(id), duration);
  }, [dismiss]);

  const api: ToastContextType = {
    success: useCallback((msg: string) => addToast('success', msg), [addToast]),
    info: useCallback((msg: string) => addToast('info', msg), [addToast]),
    warning: useCallback((msg: string) => addToast('warning', msg), [addToast]),
    error: useCallback((msg: string) => addToast('error', msg), [addToast]),
  };

  return (
    <ToastContext.Provider value={api}>
      {children}
      {/* Toast container — fixed top-right */}
      <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 pointer-events-none">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`
              pointer-events-auto flex items-start gap-3 px-4 py-3 rounded-lg
              bg-space-900 border ${borderColors[toast.type]}
              shadow-lg shadow-black/30 min-w-[300px] max-w-[420px]
              transition-all duration-300 ease-out
              ${toast.exiting ? 'opacity-0 translate-x-8' : 'opacity-100 translate-x-0 animate-slide-in'}
            `}
          >
            {icons[toast.type]}
            <p className="text-sm text-gray-200 flex-1 pt-0.5">{toast.message}</p>
            <button
              onClick={() => dismiss(toast.id)}
              className="text-gray-500 hover:text-gray-300 shrink-0"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextType {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast must be used within a ToastProvider');
  return context;
}
