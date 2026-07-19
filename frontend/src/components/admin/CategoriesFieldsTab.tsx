import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Check,
  Globe,
  Loader2,
  Pencil,
  Plus,
  Shapes,
  Trash2,
  X,
} from 'lucide-react';
import { categoriesApi, fieldsApi } from '../../api/metadata';
import { apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import type { Category, FieldDef, FieldType } from '../../types';

const inputSm =
  'bg-space-950 border border-space-700 rounded-md px-2 py-1.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500';

const FIELD_TYPES: FieldType[] = ['text', 'number', 'date', 'url'];

type Scope = 'global' | number;

// ── Field-def editor (shared by category defs and globals) ───────────────────

interface DefDraft {
  name: string;
  type: FieldType;
  unit: string;
  required: boolean;
  sort_order: string;
}

const emptyDraft: DefDraft = { name: '', type: 'text', unit: '', required: false, sort_order: '0' };

const draftFrom = (d: FieldDef): DefDraft => ({
  name: d.name,
  type: d.type,
  unit: d.unit ?? '',
  required: d.required,
  sort_order: String(d.sort_order),
});

function DefEditorRow({
  draft,
  onChange,
  onCommit,
  onCancel,
  committing,
  commitIcon,
}: {
  draft: DefDraft;
  onChange: (d: DefDraft) => void;
  onCommit: () => void;
  onCancel?: () => void;
  committing: boolean;
  commitIcon: 'save' | 'add';
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <input
        value={draft.name}
        onChange={(e) => onChange({ ...draft, name: e.target.value })}
        placeholder="Field name"
        className={`${inputSm} flex-1 min-w-[8rem]`}
      />
      <select
        value={draft.type}
        onChange={(e) => onChange({ ...draft, type: e.target.value as FieldType })}
        className={inputSm}
      >
        {FIELD_TYPES.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
      <input
        value={draft.unit}
        onChange={(e) => onChange({ ...draft, unit: e.target.value })}
        placeholder="unit"
        className={`${inputSm} w-16`}
      />
      <input
        type="number"
        value={draft.sort_order}
        onChange={(e) => onChange({ ...draft, sort_order: e.target.value })}
        title="Sort order"
        className={`${inputSm} w-16`}
      />
      <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer px-1">
        <input
          type="checkbox"
          checked={draft.required}
          onChange={(e) => onChange({ ...draft, required: e.target.checked })}
          className="accent-blue-600"
        />
        req.
      </label>
      <button
        onClick={onCommit}
        disabled={committing || draft.name.trim() === ''}
        title={commitIcon === 'add' ? 'Add field' : 'Save field'}
        className="p-1.5 rounded-md bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white transition-colors"
      >
        {committing ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : commitIcon === 'add' ? (
          <Plus className="w-3.5 h-3.5" />
        ) : (
          <Check className="w-3.5 h-3.5" />
        )}
      </button>
      {onCancel && (
        <button
          onClick={onCancel}
          title="Cancel"
          className="p-1.5 rounded-md text-gray-500 hover:text-white hover:bg-space-700 transition-colors"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}

// ── Tab ──────────────────────────────────────────────────────────────────────

export default function CategoriesFieldsTab() {
  const toast = useToast();
  const [categories, setCategories] = useState<Category[]>([]);
  const [globalDefs, setGlobalDefs] = useState<FieldDef[]>([]);
  const [loading, setLoading] = useState(true);
  const [scope, setScope] = useState<Scope>('global');

  // Category CRUD state
  const [newCatName, setNewCatName] = useState('');
  const [newCatIcon, setNewCatIcon] = useState('');
  const [creatingCat, setCreatingCat] = useState(false);
  const [editCatId, setEditCatId] = useState<number | null>(null);
  const [editCatName, setEditCatName] = useState('');
  const [editCatIcon, setEditCatIcon] = useState('');
  const [savingCat, setSavingCat] = useState(false);
  const [deleteCat, setDeleteCat] = useState<Category | null>(null);

  // Field-def CRUD state
  const [newDef, setNewDef] = useState<DefDraft>(emptyDraft);
  const [creatingDef, setCreatingDef] = useState(false);
  const [editDefId, setEditDefId] = useState<number | null>(null);
  const [editDef, setEditDef] = useState<DefDraft>(emptyDraft);
  const [savingDef, setSavingDef] = useState(false);
  const [deleteDef, setDeleteDef] = useState<FieldDef | null>(null);

  const load = useCallback(async () => {
    try {
      const [cats, globals] = await Promise.all([
        categoriesApi.list(true),
        fieldsApi.applicable(null), // globals only
      ]);
      setCategories(cats);
      setGlobalDefs(globals.filter((d) => d.category_id === null));
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to load categories'));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const scopeCategory = useMemo(
    () => (scope === 'global' ? null : categories.find((c) => c.id === scope) ?? null),
    [scope, categories]
  );

  const scopeDefs = useMemo(() => {
    const defs =
      scope === 'global'
        ? globalDefs
        : (scopeCategory?.fields ?? []).filter((d) => d.category_id === scopeCategory?.id);
    return [...defs].sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name));
  }, [scope, globalDefs, scopeCategory]);

  // ── Category actions ──────────────────────────────────────────────────────
  const handleCreateCat = async () => {
    const name = newCatName.trim();
    if (name === '' || creatingCat) return;
    setCreatingCat(true);
    try {
      const cat = await categoriesApi.create({
        name,
        icon: newCatIcon.trim() || undefined,
      });
      setNewCatName('');
      setNewCatIcon('');
      await load();
      setScope(cat.id);
      toast.success(`Category “${cat.name}” created`);
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to create category'));
    } finally {
      setCreatingCat(false);
    }
  };

  const startEditCat = (c: Category) => {
    setEditCatId(c.id);
    setEditCatName(c.name);
    setEditCatIcon(c.icon ?? '');
  };

  const handleSaveCat = async () => {
    if (editCatId === null || savingCat) return;
    const name = editCatName.trim();
    if (name === '') return;
    setSavingCat(true);
    try {
      await categoriesApi.update(editCatId, {
        name,
        icon: editCatIcon.trim() === '' ? null : editCatIcon.trim(),
      });
      setEditCatId(null);
      await load();
      toast.success('Category saved');
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to save category'));
    } finally {
      setSavingCat(false);
    }
  };

  const handleDeleteCat = async () => {
    if (!deleteCat) return;
    const target = deleteCat;
    setDeleteCat(null);
    try {
      await categoriesApi.remove(target.id);
      if (scope === target.id) setScope('global');
      await load();
      toast.success(`Category “${target.name}” deleted`);
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to delete category'));
    }
  };

  // ── Field-def actions ─────────────────────────────────────────────────────
  const defPayloadFrom = (d: DefDraft) => ({
    name: d.name.trim(),
    type: d.type,
    unit: d.unit.trim() === '' ? undefined : d.unit.trim(),
    required: d.required,
    sort_order: Number(d.sort_order) || 0,
  });

  const handleCreateDef = async () => {
    if (creatingDef || newDef.name.trim() === '') return;
    setCreatingDef(true);
    try {
      await fieldsApi.create({
        category_id: scope === 'global' ? null : scope,
        ...defPayloadFrom(newDef),
      });
      setNewDef(emptyDraft);
      await load();
      toast.success('Field created');
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to create field'));
    } finally {
      setCreatingDef(false);
    }
  };

  const handleSaveDef = async () => {
    if (editDefId === null || savingDef || editDef.name.trim() === '') return;
    setSavingDef(true);
    try {
      const p = defPayloadFrom(editDef);
      await fieldsApi.update(editDefId, {
        name: p.name,
        type: p.type,
        unit: p.unit ?? null,
        required: p.required,
        sort_order: p.sort_order,
      });
      setEditDefId(null);
      await load();
      toast.success('Field saved');
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to save field'));
    } finally {
      setSavingDef(false);
    }
  };

  const handleDeleteDef = async () => {
    if (!deleteDef) return;
    const target = deleteDef;
    setDeleteDef(null);
    try {
      await fieldsApi.remove(target.id);
      await load();
      toast.success(`Field “${target.name}” deleted`);
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to delete field'));
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center gap-2 text-gray-500 text-sm py-12 justify-center">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading…
      </div>
    );
  }

  const scopeBtn = (active: boolean) =>
    `w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-left transition-colors ${
      active ? 'bg-blue-500/20 text-blue-300' : 'text-gray-400 hover:text-white hover:bg-space-800'
    }`;

  return (
    <div className="grid md:grid-cols-[16rem_1fr] gap-4">
      {/* Category list */}
      <div className="bg-space-900 border border-space-700 rounded-xl p-3">
        <button onClick={() => setScope('global')} className={scopeBtn(scope === 'global')}>
          <Globe className="w-4 h-4 shrink-0" />
          <span className="flex-1 truncate">Global fields</span>
          <span className="text-xs text-gray-500">{globalDefs.length}</span>
        </button>

        <div className="border-t border-space-800 my-2" />

        <div className="space-y-0.5">
          {categories.map((c) =>
            editCatId === c.id ? (
              <div key={c.id} className="flex items-center gap-1.5 px-1 py-1">
                <input
                  value={editCatIcon}
                  onChange={(e) => setEditCatIcon(e.target.value)}
                  placeholder="🙂"
                  className={`${inputSm} w-11 text-center`}
                />
                <input
                  value={editCatName}
                  onChange={(e) => setEditCatName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSaveCat()}
                  autoFocus
                  className={`${inputSm} flex-1 min-w-0`}
                />
                <button
                  onClick={handleSaveCat}
                  disabled={savingCat || editCatName.trim() === ''}
                  title="Save"
                  className="p-1.5 rounded-md bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white transition-colors"
                >
                  {savingCat ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Check className="w-3.5 h-3.5" />
                  )}
                </button>
                <button
                  onClick={() => setEditCatId(null)}
                  title="Cancel"
                  className="p-1.5 rounded-md text-gray-500 hover:text-white hover:bg-space-700 transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ) : (
              <div key={c.id} className="group flex items-center">
                <button onClick={() => setScope(c.id)} className={scopeBtn(scope === c.id)}>
                  <span className="w-4 text-center shrink-0">{c.icon || '·'}</span>
                  <span className="flex-1 truncate">{c.name}</span>
                  <span className="text-xs text-gray-500">
                    {(c.fields ?? []).filter((d) => d.category_id === c.id).length}
                  </span>
                </button>
                <button
                  onClick={() => startEditCat(c)}
                  title="Rename / change icon"
                  className="p-1.5 rounded-md text-gray-600 hover:text-white hover:bg-space-700 opacity-0 group-hover:opacity-100 transition-all shrink-0"
                >
                  <Pencil className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => setDeleteCat(c)}
                  title="Delete category"
                  className="p-1.5 rounded-md text-gray-600 hover:text-red-400 hover:bg-space-700 opacity-0 group-hover:opacity-100 transition-all shrink-0"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            )
          )}
        </div>

        {/* Create category */}
        <div className="border-t border-space-800 mt-2 pt-2 flex items-center gap-1.5">
          <input
            value={newCatIcon}
            onChange={(e) => setNewCatIcon(e.target.value)}
            placeholder="🙂"
            title="Icon (emoji)"
            className={`${inputSm} w-11 text-center`}
          />
          <input
            value={newCatName}
            onChange={(e) => setNewCatName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCreateCat()}
            placeholder="New category"
            className={`${inputSm} flex-1 min-w-0`}
          />
          <button
            onClick={handleCreateCat}
            disabled={creatingCat || newCatName.trim() === ''}
            title="Create category"
            className="p-1.5 rounded-md bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white transition-colors"
          >
            {creatingCat ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Plus className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
      </div>

      {/* Field defs of the selected scope */}
      <div className="bg-space-900 border border-space-700 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <Shapes className="w-4 h-4 text-blue-400" />
          <h3 className="text-sm font-semibold text-white">
            {scope === 'global'
              ? 'Global fields — apply to every category'
              : `Fields of “${scopeCategory?.name ?? '?'}”`}
          </h3>
        </div>

        {scopeDefs.length === 0 ? (
          <p className="text-sm text-gray-500 py-4 text-center">No fields yet — add one below.</p>
        ) : (
          <div className="space-y-1 mb-3">
            {scopeDefs.map((d) =>
              editDefId === d.id ? (
                <div key={d.id} className="px-2 py-1.5 rounded-lg bg-space-950 border border-space-700">
                  <DefEditorRow
                    draft={editDef}
                    onChange={setEditDef}
                    onCommit={handleSaveDef}
                    onCancel={() => setEditDefId(null)}
                    committing={savingDef}
                    commitIcon="save"
                  />
                </div>
              ) : (
                <div
                  key={d.id}
                  className="group flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-space-800/60 transition-colors"
                >
                  <span className="flex-1 min-w-0 text-sm text-white truncate">{d.name}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-space-800 border border-space-700 text-gray-400 shrink-0">
                    {d.type}
                  </span>
                  {d.unit && <span className="text-xs text-gray-500 shrink-0">{d.unit}</span>}
                  {d.required && <span className="text-xs text-red-400 shrink-0">required</span>}
                  <span className="text-[10px] text-gray-600 shrink-0" title="Sort order">
                    #{d.sort_order}
                  </span>
                  <button
                    onClick={() => {
                      setEditDefId(d.id);
                      setEditDef(draftFrom(d));
                    }}
                    title="Edit field"
                    className="p-1.5 rounded-md text-gray-600 hover:text-white hover:bg-space-700 opacity-0 group-hover:opacity-100 transition-all shrink-0"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => setDeleteDef(d)}
                    title="Delete field"
                    className="p-1.5 rounded-md text-gray-600 hover:text-red-400 hover:bg-space-700 opacity-0 group-hover:opacity-100 transition-all shrink-0"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              )
            )}
          </div>
        )}

        {/* Add field */}
        <div className="border-t border-space-800 pt-3">
          <DefEditorRow
            draft={newDef}
            onChange={setNewDef}
            onCommit={handleCreateDef}
            committing={creatingDef}
            commitIcon="add"
          />
        </div>
      </div>

      <ConfirmDialog
        open={deleteCat !== null}
        title="Delete category"
        message={`Delete “${deleteCat?.name ?? ''}”? Its field definitions and all stored values are removed. Entities keep existing but lose the category.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={handleDeleteCat}
        onCancel={() => setDeleteCat(null)}
      />
      <ConfirmDialog
        open={deleteDef !== null}
        title="Delete field"
        message={`Delete field “${deleteDef?.name ?? ''}”? All values stored for it on any entity are removed.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={handleDeleteDef}
        onCancel={() => setDeleteDef(null)}
      />
    </div>
  );
}
