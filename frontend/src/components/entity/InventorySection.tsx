import { useEffect, useMemo, useState } from 'react';
import { AxiosError } from 'axios';
import {
  AlertTriangle,
  Banknote,
  ChevronDown,
  ChevronRight,
  Loader2,
  Minus,
  Plus,
  Save,
} from 'lucide-react';
import { entitiesApi, apiErrorDetail, type UpdateEntityPayload } from '../../api/entities';
import { inventoryApi } from '../../api/inventory';
import { useToast } from '../ui/Toast';
import { formatMoney, formatQuantity } from '../../utils/format';
import type { Entity } from '../../types';

const inputBase =
  'w-full bg-space-950 border border-space-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500 placeholder-gray-600 disabled:opacity-50 disabled:cursor-not-allowed';

const blockLabel = 'text-[10px] uppercase tracking-wide text-gray-500 mb-2';
const fieldLabel = 'block text-xs text-gray-400 mb-1';

const CURRENCIES = ['EUR', 'USD', 'CHF', 'GBP'];

// ── Form model (string-typed inputs + booleans) ──────────────────────────────

interface InvForm {
  quantity: string;
  unit: string;
  is_consumable: boolean;
  low_stock_threshold: string;
  purchase_date: string;
  purchase_price: string;
  purchase_from: string;
  currency: string;
  current_value: string;
  insured: boolean;
  warranty_expires: string;
  warranty_lifetime: boolean;
  warranty_notes: string;
  serial_number: string;
  model_number: string;
  manufacturer: string;
  sold_date: string;
  sold_to: string;
  sold_price: string;
  sold_notes: string;
}

type NumKey = 'quantity' | 'low_stock_threshold' | 'purchase_price' | 'current_value' | 'sold_price';
type BoolKey = 'is_consumable' | 'insured' | 'warranty_lifetime';

const NUM_KEYS: NumKey[] = [
  'quantity',
  'low_stock_threshold',
  'purchase_price',
  'current_value',
  'sold_price',
];
const BOOL_KEYS: BoolKey[] = ['is_consumable', 'insured', 'warranty_lifetime'];
const NUM_LABELS: Record<NumKey, string> = {
  quantity: 'Quantity',
  low_stock_threshold: 'Low-stock threshold',
  purchase_price: 'Purchase price',
  current_value: 'Current value',
  sold_price: 'Sold price',
};

const numToStr = (n: number | null): string => (n === null ? '' : formatQuantity(n));

const toForm = (e: Entity): InvForm => ({
  quantity: numToStr(e.quantity),
  unit: e.unit ?? '',
  is_consumable: e.is_consumable,
  low_stock_threshold: numToStr(e.low_stock_threshold),
  purchase_date: e.purchase_date ?? '',
  purchase_price: numToStr(e.purchase_price),
  purchase_from: e.purchase_from ?? '',
  currency: e.currency ?? '',
  current_value: numToStr(e.current_value),
  insured: e.insured,
  warranty_expires: e.warranty_expires ?? '',
  warranty_lifetime: e.warranty_lifetime,
  warranty_notes: e.warranty_notes ?? '',
  serial_number: e.serial_number ?? '',
  model_number: e.model_number ?? '',
  manufacturer: e.manufacturer ?? '',
  sold_date: e.sold_date ?? '',
  sold_to: e.sold_to ?? '',
  sold_price: numToStr(e.sold_price),
  sold_notes: e.sold_notes ?? '',
});

const FORM_KEYS = Object.keys(toForm({} as unknown as Entity)) as (keyof InvForm)[];

/** Something inventory-ish is already filled in — auto-expand the card.
 * quantity is NOT NULL (default 1), so only a non-default value counts. */
const hasInventoryData = (e: Entity): boolean =>
  e.quantity !== 1 ||
  e.unit !== null ||
  e.is_consumable ||
  e.low_stock_threshold !== null ||
  e.purchase_date !== null ||
  e.purchase_price !== null ||
  e.purchase_from !== null ||
  e.current_value !== null ||
  e.insured ||
  e.warranty_expires !== null ||
  e.warranty_lifetime ||
  e.warranty_notes !== null ||
  e.serial_number !== null ||
  e.model_number !== null ||
  e.manufacturer !== null ||
  e.sold_date !== null ||
  e.sold_to !== null ||
  e.sold_price !== null ||
  e.sold_notes !== null;

export const isLowStock = (e: Entity): boolean =>
  e.is_consumable && e.low_stock_threshold !== null && e.quantity <= e.low_stock_threshold;

// ── Section ──────────────────────────────────────────────────────────────────

interface InventorySectionProps {
  entity: Entity;
  onEntityUpdate: (e: Entity) => void;
}

export function InventorySection({ entity, onEntityUpdate }: InventorySectionProps) {
  const toast = useToast();
  const [open, setOpen] = useState(() => hasInventoryData(entity));
  const [form, setForm] = useState<InvForm>(() => toForm(entity));
  const [baseline, setBaseline] = useState<InvForm>(() => toForm(entity));
  const [saving, setSaving] = useState(false);
  const [adjusting, setAdjusting] = useState(false);
  const [soldOpen, setSoldOpen] = useState(() => entity.sold_date !== null);
  const [currencyOther, setCurrencyOther] = useState(
    () => entity.currency !== null && !CURRENCIES.includes(entity.currency)
  );

  // Reset the form when navigating to another entity.
  useEffect(() => {
    const snap = toForm(entity);
    setForm(snap);
    setBaseline(snap);
    setOpen(hasInventoryData(entity));
    setSoldOpen(entity.sold_date !== null);
    setCurrencyOther(entity.currency !== null && !CURRENCIES.includes(entity.currency));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entity.id]);

  const dirty = useMemo(
    () => FORM_KEYS.some((k) => form[k] !== baseline[k]),
    [form, baseline]
  );

  const set = <K extends keyof InvForm>(key: K, value: InvForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const lowStock = isLowStock(entity);
  const displayValue = entity.current_value ?? entity.purchase_price;

  // ── Quantity stepper (optimistic, revert on fail) ─────────────────────────
  const adjustQuantity = async (delta: number) => {
    if (adjusting) return;
    const prev = entity;
    const optimisticQ = Math.max(0, entity.quantity + delta);
    setAdjusting(true);
    onEntityUpdate({ ...entity, quantity: optimisticQ });
    setForm((f) => ({ ...f, quantity: numToStr(optimisticQ) }));
    setBaseline((b) => ({ ...b, quantity: numToStr(optimisticQ) }));
    try {
      const updated = await inventoryApi.quantityAdjust(entity.id, delta);
      onEntityUpdate(updated);
      setForm((f) => ({ ...f, quantity: numToStr(updated.quantity) }));
      setBaseline((b) => ({ ...b, quantity: numToStr(updated.quantity) }));
    } catch (err) {
      onEntityUpdate(prev);
      setForm((f) => ({ ...f, quantity: numToStr(prev.quantity) }));
      setBaseline((b) => ({ ...b, quantity: numToStr(prev.quantity) }));
      toast.error(apiErrorDetail(err, 'Failed to adjust quantity'));
    } finally {
      setAdjusting(false);
    }
  };

  // ── Save (PATCH only dirty fields) ────────────────────────────────────────
  const toastSaveErrors = (err: unknown) => {
    if (err instanceof AxiosError && err.response?.status === 422) {
      const detail = err.response.data?.detail;
      if (typeof detail === 'string') {
        toast.error(detail);
        return;
      }
      if (Array.isArray(detail)) {
        const msgs = detail
          .map((d) => (typeof d?.msg === 'string' ? (d.msg as string) : null))
          .filter((m): m is string => m !== null);
        if (msgs.length > 0) {
          msgs.slice(0, 4).forEach((m) => toast.error(m));
          return;
        }
      }
    }
    toast.error(apiErrorDetail(err, 'Failed to save inventory'));
  };

  const handleSave = async () => {
    if (!dirty || saving) return;

    const patch: UpdateEntityPayload = {};
    for (const key of FORM_KEYS) {
      if (form[key] === baseline[key]) continue;
      if ((BOOL_KEYS as string[]).includes(key)) {
        patch[key as BoolKey] = form[key as BoolKey];
      } else if ((NUM_KEYS as string[]).includes(key)) {
        const raw = (form[key] as string).trim().replace(',', '.');
        if (raw === '') {
          // quantity is NOT NULL server-side (explicit null = 422): an emptied
          // input just keeps the current value (omitted from the PATCH).
          if (key === 'quantity') continue;
          patch[key as Exclude<NumKey, 'quantity'>] = null;
        } else {
          const n = Number(raw);
          if (!Number.isFinite(n)) {
            toast.error(`${NUM_LABELS[key as NumKey]} is not a valid number`);
            return;
          }
          patch[key as NumKey] = n;
        }
      } else if (key === 'currency') {
        const raw = form.currency.trim().toUpperCase();
        patch.currency = raw === '' ? null : raw;
      } else {
        // text + date fields: empty clears
        const raw = (form[key] as string).trim();
        (patch as Record<string, string | null>)[key] = raw === '' ? null : raw;
      }
    }

    setSaving(true);
    try {
      const updated = await entitiesApi.update(entity.id, patch);
      onEntityUpdate(updated);
      const snap = toForm(updated);
      setForm(snap);
      setBaseline(snap);
      toast.success('Inventory saved');
    } catch (err) {
      toastSaveErrors(err);
    } finally {
      setSaving(false);
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────
  const stepBtn =
    'w-9 h-9 flex items-center justify-center rounded-lg bg-space-800 hover:bg-space-700 border border-space-600 text-gray-300 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0';

  return (
    <section className="bg-space-900 border border-space-700 rounded-xl mt-4 overflow-hidden">
      {/* Header (always visible, toggles) */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2.5 px-4 py-3 text-left hover:bg-space-800/50 transition-colors"
      >
        {open ? (
          <ChevronDown className="w-4 h-4 text-gray-500 shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-gray-500 shrink-0" />
        )}
        <Banknote className="w-4 h-4 text-blue-400 shrink-0" />
        <span className="text-sm font-semibold text-white">Inventory &amp; value</span>

        {/* Summary chips */}
        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-space-800 border border-space-700 text-gray-400 shrink-0">
          {formatQuantity(entity.quantity)}
          {entity.unit ? ` ${entity.unit}` : '×'}
        </span>
        {displayValue !== null && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-space-800 border border-space-700 text-gray-400 shrink-0">
            {formatMoney(displayValue, entity.currency || 'EUR')}
          </span>
        )}
        {entity.sold_date !== null && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-space-800 border border-space-600 text-gray-500 shrink-0">
            sold
          </span>
        )}
        {lowStock && (
          <span className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-900/40 border border-amber-700/40 text-amber-400 shrink-0">
            <AlertTriangle className="w-3 h-3" /> low stock
          </span>
        )}

        <span className="flex-1" />

        {dirty && (
          <span className="flex items-center gap-1.5 text-xs text-amber-400 shrink-0">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
            <span className="hidden sm:inline">Unsaved changes</span>
          </span>
        )}
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-4">
          {/* Low-stock banner */}
          {lowStock && (
            <div className="flex items-center gap-2.5 px-3 py-2 rounded-lg bg-amber-900/30 border border-amber-700/40 text-amber-300 text-sm">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              Running low: {formatQuantity(entity.quantity)}
              {entity.unit ? ` ${entity.unit}` : ''} left (threshold{' '}
              {formatQuantity(entity.low_stock_threshold ?? 0)})
            </div>
          )}

          {/* Quantity & stock */}
          <div>
            <p className={blockLabel}>Quantity &amp; stock</p>
            <div className="flex flex-wrap items-end gap-3">
              <div>
                <label className={fieldLabel}>Quantity</label>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => adjustQuantity(-1)}
                    disabled={adjusting || entity.quantity <= 0}
                    title="Remove one"
                    className={stepBtn}
                  >
                    <Minus className="w-4 h-4" />
                  </button>
                  <input
                    type="text"
                    inputMode="decimal"
                    value={form.quantity}
                    onChange={(e) => set('quantity', e.target.value)}
                    placeholder="—"
                    className={`${inputBase} w-20 text-center`}
                  />
                  <button
                    type="button"
                    onClick={() => adjustQuantity(1)}
                    disabled={adjusting}
                    title="Add one"
                    className={stepBtn}
                  >
                    <Plus className="w-4 h-4" />
                  </button>
                </div>
              </div>
              <div className="w-28">
                <label className={fieldLabel}>Unit</label>
                <input
                  type="text"
                  value={form.unit}
                  onChange={(e) => set('unit', e.target.value)}
                  placeholder="pcs, m, kg…"
                  className={inputBase}
                />
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer pb-2.5">
                <input
                  type="checkbox"
                  checked={form.is_consumable}
                  onChange={(e) => set('is_consumable', e.target.checked)}
                  className="accent-blue-600"
                />
                Consumable
              </label>
              {form.is_consumable && (
                <div className="w-36">
                  <label className={fieldLabel}>Low-stock threshold</label>
                  <input
                    type="text"
                    inputMode="decimal"
                    value={form.low_stock_threshold}
                    onChange={(e) => set('low_stock_threshold', e.target.value)}
                    placeholder="e.g. 2"
                    className={inputBase}
                  />
                </div>
              )}
            </div>
          </div>

          {/* Purchase */}
          <div>
            <p className={blockLabel}>Purchase</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div>
                <label className={fieldLabel}>Date</label>
                <input
                  type="date"
                  value={form.purchase_date}
                  onChange={(e) => set('purchase_date', e.target.value)}
                  className={inputBase}
                />
              </div>
              <div>
                <label className={fieldLabel}>Price</label>
                <input
                  type="text"
                  inputMode="decimal"
                  value={form.purchase_price}
                  onChange={(e) => set('purchase_price', e.target.value)}
                  placeholder="0.00"
                  className={inputBase}
                />
              </div>
              <div>
                <label className={fieldLabel}>From</label>
                <input
                  type="text"
                  value={form.purchase_from}
                  onChange={(e) => set('purchase_from', e.target.value)}
                  placeholder="Shop, person…"
                  className={inputBase}
                />
              </div>
              <div>
                <label className={fieldLabel}>Currency</label>
                {currencyOther ? (
                  <input
                    type="text"
                    value={form.currency}
                    onChange={(e) => set('currency', e.target.value.toUpperCase())}
                    onBlur={() => {
                      if (form.currency === '' || CURRENCIES.includes(form.currency)) {
                        setCurrencyOther(false);
                      }
                    }}
                    placeholder="3-letter code"
                    maxLength={3}
                    autoFocus
                    className={inputBase}
                  />
                ) : (
                  <select
                    value={form.currency}
                    onChange={(e) => {
                      if (e.target.value === '__other') {
                        setCurrencyOther(true);
                        set('currency', '');
                      } else {
                        set('currency', e.target.value);
                      }
                    }}
                    className={inputBase}
                  >
                    <option value="">Default</option>
                    {CURRENCIES.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                    <option value="__other">Other…</option>
                  </select>
                )}
              </div>
            </div>
          </div>

          {/* Value & warranty */}
          <div className="grid sm:grid-cols-2 gap-4">
            <div>
              <p className={blockLabel}>Value</p>
              <div className="flex items-end gap-3">
                <div className="flex-1">
                  <label className={fieldLabel}>Current value</label>
                  <input
                    type="text"
                    inputMode="decimal"
                    value={form.current_value}
                    onChange={(e) => set('current_value', e.target.value)}
                    placeholder={
                      form.purchase_price !== ''
                        ? `${form.purchase_price} (purchase price)`
                        : '0.00'
                    }
                    className={inputBase}
                  />
                </div>
                <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer pb-2.5">
                  <input
                    type="checkbox"
                    checked={form.insured}
                    onChange={(e) => set('insured', e.target.checked)}
                    className="accent-blue-600"
                  />
                  Insured
                </label>
              </div>
            </div>
            <div>
              <p className={blockLabel}>Warranty</p>
              <div className="flex items-end gap-3">
                <div className="flex-1">
                  <label className={fieldLabel}>Expires</label>
                  <input
                    type="date"
                    value={form.warranty_lifetime ? '' : form.warranty_expires}
                    onChange={(e) => set('warranty_expires', e.target.value)}
                    disabled={form.warranty_lifetime}
                    className={inputBase}
                  />
                </div>
                <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer pb-2.5 whitespace-nowrap">
                  <input
                    type="checkbox"
                    checked={form.warranty_lifetime}
                    onChange={(e) => set('warranty_lifetime', e.target.checked)}
                    className="accent-blue-600"
                  />
                  Lifetime
                </label>
              </div>
              <input
                type="text"
                value={form.warranty_notes}
                onChange={(e) => set('warranty_notes', e.target.value)}
                placeholder="Warranty notes (receipt no., conditions…)"
                className={`${inputBase} mt-2`}
              />
            </div>
          </div>

          {/* Identifiers */}
          <div>
            <p className={blockLabel}>Identifiers</p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <label className={fieldLabel}>Serial number</label>
                <input
                  type="text"
                  value={form.serial_number}
                  onChange={(e) => set('serial_number', e.target.value)}
                  className={inputBase}
                />
              </div>
              <div>
                <label className={fieldLabel}>Model number</label>
                <input
                  type="text"
                  value={form.model_number}
                  onChange={(e) => set('model_number', e.target.value)}
                  className={inputBase}
                />
              </div>
              <div>
                <label className={fieldLabel}>Manufacturer</label>
                <input
                  type="text"
                  value={form.manufacturer}
                  onChange={(e) => set('manufacturer', e.target.value)}
                  className={inputBase}
                />
              </div>
            </div>
          </div>

          {/* Sold */}
          <div>
            {soldOpen ? (
              <>
                <p className={blockLabel}>Sold</p>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div>
                    <label className={fieldLabel}>Date</label>
                    <input
                      type="date"
                      value={form.sold_date}
                      onChange={(e) => set('sold_date', e.target.value)}
                      className={inputBase}
                    />
                  </div>
                  <div>
                    <label className={fieldLabel}>To</label>
                    <input
                      type="text"
                      value={form.sold_to}
                      onChange={(e) => set('sold_to', e.target.value)}
                      className={inputBase}
                    />
                  </div>
                  <div>
                    <label className={fieldLabel}>Price</label>
                    <input
                      type="text"
                      inputMode="decimal"
                      value={form.sold_price}
                      onChange={(e) => set('sold_price', e.target.value)}
                      placeholder="0.00"
                      className={inputBase}
                    />
                  </div>
                  <div>
                    <label className={fieldLabel}>Notes</label>
                    <input
                      type="text"
                      value={form.sold_notes}
                      onChange={(e) => set('sold_notes', e.target.value)}
                      className={inputBase}
                    />
                  </div>
                </div>
                <p className="text-xs text-gray-600 mt-1.5">
                  A sold date excludes this entry from the valuation. Clear the date to
                  undo.
                </p>
              </>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setSoldOpen(true);
                  if (form.sold_date === '') {
                    set('sold_date', new Date().toISOString().slice(0, 10));
                  }
                }}
                className="text-xs text-gray-500 hover:text-gray-300 underline decoration-dotted underline-offset-2 transition-colors"
              >
                Mark as sold…
              </button>
            )}
          </div>

          {/* Save row */}
          <div className="flex items-center justify-end gap-3 pt-1 border-t border-space-800">
            {dirty && (
              <span className="flex items-center gap-1.5 text-xs text-amber-400">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                Unsaved changes
              </span>
            )}
            <button
              onClick={handleSave}
              disabled={!dirty || saving}
              className="flex items-center gap-1.5 px-3 py-1.5 mt-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm transition-colors"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              Save
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

export default InventorySection;
