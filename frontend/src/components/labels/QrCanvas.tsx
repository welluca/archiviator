import { useEffect, useRef } from 'react';
import QRCode from 'qrcode';

interface QrCanvasProps {
  /** Full string encoded in the QR (e.g. `${base_url}/a/${tag}`). */
  value: string;
  /** Rendered square size in CSS pixels. */
  size?: number;
  className?: string;
}

/** Client-rendered QR code on a white tile (scanners need light background
 * even in the dark UI). Pure canvas — no network, no CDN. */
export function QrCanvas({ value, size = 96, className = '' }: QrCanvasProps) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!ref.current || !value) return;
    QRCode.toCanvas(ref.current, value, {
      width: size * (window.devicePixelRatio || 1),
      margin: 1,
      errorCorrectionLevel: 'M',
      color: { dark: '#0f0f1a', light: '#ffffff' },
    }).catch(() => {
      /* invalid input — leave the canvas blank */
    });
  }, [value, size]);

  return (
    <canvas
      ref={ref}
      style={{ width: size, height: size }}
      className={`rounded-md bg-white ${className}`}
      aria-label={`QR code for ${value}`}
    />
  );
}

export default QrCanvas;
