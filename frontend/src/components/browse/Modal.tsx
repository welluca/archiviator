import React from 'react';
import { X } from 'lucide-react';

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  /** Tailwind max-width class for the panel. */
  maxWidth?: string;
}

/** Shared modal shell styled after ConfirmDialog. */
export function Modal({ open, title, onClose, children, maxWidth = 'max-w-md' }: ModalProps) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className={`bg-space-900 border border-space-700 rounded-xl w-full ${maxWidth} flex flex-col max-h-[85vh]`}>
        <div className="flex items-center justify-between px-6 pt-5 pb-3">
          <h3 className="text-lg font-semibold text-white">{title}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="px-6 pb-6 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}

export default Modal;
