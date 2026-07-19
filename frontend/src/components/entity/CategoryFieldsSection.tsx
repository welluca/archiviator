import { useCallback, useEffect, useMemo, useState } from 'react';
import { AxiosError } from 'axios';
import { ExternalLink, Loader2, Save } from 'lucide-react';
import { categoriesApi, fieldsApi } from '../../api/metadata';
import { entitiesApi, apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import type { Category, Entity, FieldDef } from '../../types';

// ── Per-type input ───────────────────────────────────────────────────────────

const inputBase =
  'w-full bg-space-950 border border-space-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500 placeholder-gray-600';

function FieldInput({
  def,
  value,
  onChange,
}: {
  def: FieldDef;
  value: string;
  onChange: (v: string) => void;
}) {
  // Autocomplete options for text fields, fetched lazily on first focus.
  const [options, setOptions] = useState<string[] | null>(null);
  const loadOptions = () => {
    if (def.type !== 'text' || options !== null) return;
    fieldsApi
      .autocomplete(def.id)
      .then(setOptions)
      .catch(() => setOptions([]));
  };

  if (def.type === 'date') {
    return (
      <input
        type="date"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={inputBase}
      />
    );
  }

  if (def.type === 'number') {
    return (
      <div className="relative">
        <input
          type="text"
          inputMode="decimal"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="0"
          className={`${inputBase} ${def.unit ? 'pr-12' : ''}`}
        />
        {def.unit && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-500 pointer-events-none">
            {def.unit}
          </span>
        )}
      </div>
    );
  }

  if (def.type === 'url') {
    const openable = /^https?:\/\//i.test(value.trim());
    return (
      <div className="relative">
        <input
          type="url"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="https://…"
          className={`${inputBase} pr-9`}
        />
        <a
          href={openable ? value.trim() : undefined}
          target="_blank"
          rel="noopener noreferrer"
          title="Open link"
          className={`absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-md transition-colors ${
            openable
              ? 'text-gray-400 hover:text-white hover:bg-space-700'
              : 'text-gray-700 pointer-events-none'
          }`}
        >
          <ExternalLink className="w-3.5 h-3.5" />
        </a>
      </div>
    );
  }

  // text — with a datalist fed by the frequency-ordered autocomplete endpoint
  const listId = `field-options-${def.id}`;
  return (
    <>
      <input
        type="text"
        list={listId}
        value={value}
        onFocus={loadOptions}
        onChange={(e) => onChange(e.target.value)}
        className={inputBase}
      />
      {options && options.length > 0 && (
        <datalist id={listId}>
          {options.map((o) => (
            <option key={o} value={o} />
          ))}
        </datalist>
      )}
    </>
  );
}

// ── Section ──────────────────────────────────────────────────────────────────

interface CategoryFieldsSectionProps {
  entity: Entity;
  onEntityUpdate: (e: Entity) => void;
}

/** Category select + dynamic custom-fields form (category defs + globals,
 * plus any defs still carrying a value from a previous category). */
export function CategoryFieldsSection({ entity, onEntityUpdate }: CategoryFieldsSectionProps) {
  const toast = useToast();
  const [categories, setCategories] = useState<Category[]>([]);
  const [defs, setDefs] = useState<FieldDef[]>([]);
  /** Last-saved snapshot, keyed by def id (canonical value_text). */
  const [saved, setSaved] = useState<Record<number, string>>({});
  const [form, setForm] = useState<Record<number, string>>({});
  const [loadingFields, setLoadingFields] = useState(true);
  const [saving, setSaving] = useState(false);
  const [switchingCat, setSwitchingCat] = useState(false);

  useEffect(() => {
    categoriesApi.list().then(setCategories).catch(() => {});
  }, []);

  const loadFields = useCallback(async () => {
    setLoadingFields(true);
    try {
      const [applicable, existing] = await Promise.all([
        fieldsApi.applicable(entity.category_id),
        fieldsApi.values(entity.id),
      ]);
      // Union of applicable defs and defs that already carry a value.
      const map = new Map<number, FieldDef>();
      for (const d of applicable) map.set(d.id, d);
      for (const v of existing) if (!map.has(v.def.id)) map.set(v.def.id, v.def);
      const merged = [...map.values()].sort(
        (a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name)
      );
      const vals: Record<number, string> = {};
      for (const v of existing) vals[v.def.id] = v.value_text;
      setDefs(merged);
      setSaved(vals);
      setForm(vals);
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to load fields'));
    } finally {
      setLoadingFields(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entity.id, entity.category_id]);

  useEffect(() => {
    loadFields();
  }, [loadFields]);

  const dirty = useMemo(
    () => defs.some((d) => (form[d.id] ?? '') !== (saved[d.id] ?? '')),
    [defs, form, saved]
  );

  const handleCategoryChange = async (raw: string) => {
    const catId = raw === '' ? null : Number(raw);
    if (catId === entity.category_id || switchingCat) return;
    setSwitchingCat(true);
    try {
      const updated = await entitiesApi.update(entity.id, { category_id: catId });
      onEntityUpdate(updated); // loadFields re-runs via the category_id dep
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to change category'));
    } finally {
      setSwitchingCat(false);
    }
  };

  /** 422s carry per-field coercion errors — surface each message. */
  const toastFieldErrors = (err: unknown) => {
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
    toast.error(apiErrorDetail(err, 'Failed to save fields'));
  };

  const handleSave = async () => {
    if (!dirty || saving) return;
    setSaving(true);
    try {
      await fieldsApi.setValues(
        entity.id,
        defs.map((d) => ({ field_def_id: d.id, value: (form[d.id] ?? '').trim() }))
      );
      toast.success('Fields saved');
      await loadFields(); // pull server-canonical value_text back
    } catch (err) {
      toastFieldErrors(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="bg-space-900 border border-space-700 rounded-xl p-4">
      {/* Category select */}
      <div className="flex flex-wrap items-center gap-3 mb-1">
        <label className="text-[10px] uppercase tracking-wide text-gray-500">
          Category
        </label>
        <select
          value={entity.category_id ?? ''}
          onChange={(e) => handleCategoryChange(e.target.value)}
          disabled={switchingCat}
          className="bg-space-950 border border-space-700 rounded-lg px-2 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
        >
          <option value="">No category</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.icon ? `${c.icon} ${c.name}` : c.name}
            </option>
          ))}
        </select>
        {switchingCat && <Loader2 className="w-4 h-4 animate-spin text-gray-500" />}

        <div className="flex-1" />

        {dirty && (
          <span className="flex items-center gap-1.5 text-xs text-amber-400">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
            Unsaved changes
          </span>
        )}
        <button
          onClick={handleSave}
          disabled={!dirty || saving}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm transition-colors"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          Save
        </button>
      </div>

      {/* Fields form */}
      {loadingFields ? (
        <div className="flex items-center gap-2 text-gray-500 text-sm py-6 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading fields…
        </div>
      ) : defs.length === 0 ? (
        <p className="text-sm text-gray-500 py-4 text-center">
          {entity.category_id === null
            ? 'No fields — pick a category to unlock its fields.'
            : 'This category has no fields defined yet.'}
        </p>
      ) : (
        <div className="grid sm:grid-cols-2 gap-3 mt-3">
          {defs.map((def) => (
            <div key={def.id}>
              <label className="flex items-center gap-1.5 text-xs text-gray-400 mb-1">
                <span className="truncate">{def.name}</span>
                {def.required && <span className="text-red-400">*</span>}
                {def.category_id === null && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-space-800 border border-space-700 text-gray-500">
                    global
                  </span>
                )}
              </label>
              <FieldInput
                def={def}
                value={form[def.id] ?? ''}
                onChange={(v) => setForm((prev) => ({ ...prev, [def.id]: v }))}
              />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default CategoryFieldsSection;
