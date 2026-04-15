'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Camera, FileUp, Plus, Trash2, X, FileText, Image as ImageIcon, ChevronDown, ChevronRight, Eye, Calendar } from 'lucide-react';
import api from '@/lib/api';
import { Modal } from '@/components/shared/Modal';

type Receipt = {
  id: number;
  media_url: string;
  filename?: string | null;
  content_type?: string | null;
  size_bytes?: number | null;
  uploaded_at: string;
};

type Expense = {
  id: number;
  activity_id: number;
  title: string;
  amount: string;
  spent_on?: string | null;
  note?: string | null;
  created_at: string;
  receipts: Receipt[];
};

type Activity = {
  id: number;
  fundraiser_id: number;
  name: string;
  description?: string | null;
  occurred_on?: string | null;
  created_at: string;
  expenses: Expense[];
  total_spent: number;
  expense_count: number;
};

type PanelData = {
  fundraiser_id: number;
  mode: string;
  transparency_enabled: boolean;
  total_collected: number;
  total_spent: number;
  balance: number;
  activities: Activity[];
};

export function TransparencyPanel({
  fundraiserId,
  onTransparencyChange,
}: {
  fundraiserId: number;
  onTransparencyChange?: (enabled: boolean) => void;
}) {
  const [data, setData] = useState<PanelData | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [togglingTx, setTogglingTx] = useState(false);

  // Modals
  const [showNewActivity, setShowNewActivity] = useState(false);
  const [expenseTargetActivity, setExpenseTargetActivity] = useState<Activity | null>(null);
  const [viewingReceipt, setViewingReceipt] = useState<Receipt | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setErr(null);
      const { data: d } = await api.get(`/fundraisers/${fundraiserId}/activities`);
      setData(d);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || 'Error al cargar transparencia');
    } finally {
      setLoading(false);
    }
  }, [fundraiserId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const toggleTransparency = async () => {
    if (!data) return;
    setTogglingTx(true);
    try {
      await api.patch(`/fundraisers/${fundraiserId}`, {
        transparency_enabled: !data.transparency_enabled,
      });
      const next = !data.transparency_enabled;
      setData({ ...data, transparency_enabled: next });
      onTransparencyChange?.(next);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || 'Error al actualizar');
    } finally {
      setTogglingTx(false);
    }
  };

  const deleteActivity = async (aid: number) => {
    if (!confirm('¿Eliminar esta actividad? Debe estar vacía.')) return;
    try {
      await api.delete(`/fundraisers/activities/${aid}`);
      await fetchData();
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'No se pudo eliminar');
    }
  };

  const deleteExpense = async (eid: number) => {
    if (!confirm('¿Eliminar este gasto y sus comprobantes?')) return;
    try {
      await api.delete(`/fundraisers/expenses/${eid}`);
      await fetchData();
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'No se pudo eliminar');
    }
  };

  const deleteReceipt = async (rid: number) => {
    if (!confirm('¿Eliminar este comprobante?')) return;
    try {
      await api.delete(`/fundraisers/receipts/${rid}`);
      await fetchData();
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'No se pudo eliminar');
    }
  };

  if (loading) {
    return <div className="text-center text-slate-400 py-8 text-xs font-bold">Cargando…</div>;
  }
  if (err) {
    return <div className="text-center text-red-500 py-8 text-xs font-bold bg-red-50 rounded-2xl p-4">{err}</div>;
  }
  if (!data) return null;

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="grid grid-cols-3 gap-2">
        <StatTile label="Recaudado" value={`$${data.total_collected.toFixed(2)}`} color="text-emerald-600 bg-emerald-50" />
        <StatTile label="Gastado" value={`$${data.total_spent.toFixed(2)}`} color="text-amber-600 bg-amber-50" />
        <StatTile label="Saldo" value={`$${data.balance.toFixed(2)}`} color={data.balance >= 0 ? 'text-indigo-600 bg-indigo-50' : 'text-red-600 bg-red-50'} />
      </div>

      {/* Transparency toggle */}
      <div className="flex items-center justify-between bg-slate-50 rounded-2xl p-4">
        <div className="min-w-0">
          <div className="text-xs font-black text-slate-800">Publicar reporte a padres</div>
          <div className="text-[10px] text-slate-400 font-bold leading-snug">
            Cuando esté activo, los padres pueden pedir el PDF por WhatsApp con <span className="font-mono">reporte</span>.
          </div>
        </div>
        <button
          onClick={toggleTransparency}
          disabled={togglingTx}
          className={`relative w-12 h-7 rounded-full transition-colors flex-shrink-0 ${data.transparency_enabled ? 'bg-emerald-500' : 'bg-slate-300'}`}
        >
          <span className={`absolute top-1 left-1 w-5 h-5 bg-white rounded-full shadow transition-transform ${data.transparency_enabled ? 'translate-x-5' : ''}`} />
        </button>
      </div>

      {/* Activities list */}
      <div className="flex items-center justify-between pt-2">
        <h3 className="text-[10px] font-black uppercase tracking-widest text-slate-400">Actividades</h3>
        <button
          onClick={() => setShowNewActivity(true)}
          className="text-indigo-600 text-[10px] font-black uppercase flex items-center gap-1"
        >
          <Plus className="w-3 h-3" /> Nueva
        </button>
      </div>

      {data.activities.length === 0 ? (
        <div className="text-center text-slate-400 py-8 text-xs font-bold bg-slate-50/50 rounded-2xl">
          Sin actividades todavía
        </div>
      ) : (
        <div className="space-y-2">
          {data.activities.map((a) => (
            <ActivityRow
              key={a.id}
              activity={a}
              expanded={expandedId === a.id}
              onToggle={() => setExpandedId(expandedId === a.id ? null : a.id)}
              onAddExpense={() => setExpenseTargetActivity(a)}
              onDeleteActivity={() => deleteActivity(a.id)}
              onDeleteExpense={deleteExpense}
              onDeleteReceipt={deleteReceipt}
              onViewReceipt={setViewingReceipt}
            />
          ))}
        </div>
      )}

      {/* Modals */}
      <AnimatePresence>
        {showNewActivity && (
          <NewActivityModal
            fundraiserId={fundraiserId}
            onClose={() => setShowNewActivity(false)}
            onSaved={() => { setShowNewActivity(false); fetchData(); }}
          />
        )}
        {expenseTargetActivity && (
          <NewExpenseModal
            activity={expenseTargetActivity}
            onClose={() => setExpenseTargetActivity(null)}
            onSaved={() => { setExpenseTargetActivity(null); fetchData(); }}
          />
        )}
        {viewingReceipt && (
          <ReceiptLightbox receipt={viewingReceipt} onClose={() => setViewingReceipt(null)} />
        )}
      </AnimatePresence>
    </div>
  );
}

function StatTile({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className={`rounded-2xl p-3 ${color}`}>
      <div className="text-[9px] font-black uppercase tracking-widest opacity-60">{label}</div>
      <div className="text-base font-black truncate">{value}</div>
    </div>
  );
}

function ActivityRow({
  activity, expanded, onToggle, onAddExpense, onDeleteActivity, onDeleteExpense, onDeleteReceipt, onViewReceipt,
}: {
  activity: Activity;
  expanded: boolean;
  onToggle: () => void;
  onAddExpense: () => void;
  onDeleteActivity: () => void;
  onDeleteExpense: (eid: number) => void;
  onDeleteReceipt: (rid: number) => void;
  onViewReceipt: (r: Receipt) => void;
}) {
  return (
    <div className="bg-white border border-slate-100 rounded-2xl overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-4 hover:bg-slate-50"
      >
        <div className="flex items-center gap-2 min-w-0">
          {expanded ? <ChevronDown className="w-4 h-4 text-slate-400 flex-shrink-0" /> : <ChevronRight className="w-4 h-4 text-slate-400 flex-shrink-0" />}
          <div className="min-w-0 text-left">
            <div className="text-xs font-black text-slate-800 truncate">{activity.name}</div>
            <div className="text-[10px] text-slate-400 font-bold">
              {activity.occurred_on || new Date(activity.created_at).toLocaleDateString()}
              {' · '}
              {activity.expense_count} {activity.expense_count === 1 ? 'gasto' : 'gastos'}
            </div>
          </div>
        </div>
        <div className="text-xs font-black text-amber-600 flex-shrink-0">${activity.total_spent.toFixed(2)}</div>
      </button>

      {expanded && (
        <div className="border-t border-slate-100 p-4 space-y-3 bg-slate-50/40">
          {activity.description && (
            <p className="text-[11px] text-slate-500 font-medium">{activity.description}</p>
          )}
          {activity.expenses.length === 0 ? (
            <p className="text-[11px] text-slate-400 font-bold text-center py-2">Sin gastos registrados</p>
          ) : (
            activity.expenses.map((e) => (
              <ExpenseCard
                key={e.id}
                expense={e}
                onDeleteExpense={() => onDeleteExpense(e.id)}
                onDeleteReceipt={onDeleteReceipt}
                onViewReceipt={onViewReceipt}
              />
            ))
          )}
          <div className="flex gap-2 pt-1">
            <button
              onClick={onAddExpense}
              className="flex-1 bg-indigo-600 text-white py-3 rounded-xl text-[10px] font-black uppercase tracking-widest flex items-center justify-center gap-1"
            >
              <Plus className="w-3 h-3" /> Gasto
            </button>
            {activity.expenses.length === 0 && (
              <button
                onClick={onDeleteActivity}
                className="bg-red-50 text-red-500 px-4 py-3 rounded-xl"
                title="Eliminar actividad vacía"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ExpenseCard({
  expense, onDeleteExpense, onDeleteReceipt, onViewReceipt,
}: {
  expense: Expense;
  onDeleteExpense: () => void;
  onDeleteReceipt: (rid: number) => void;
  onViewReceipt: (r: Receipt) => void;
}) {
  return (
    <div className="bg-white rounded-xl p-3 border border-slate-100">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-xs font-black text-slate-800 truncate">{expense.title}</div>
          {expense.spent_on && (
            <div className="text-[10px] text-slate-400 font-bold">{expense.spent_on}</div>
          )}
          {expense.note && (
            <div className="text-[11px] text-slate-500 mt-1">{expense.note}</div>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="text-xs font-black text-amber-600">${parseFloat(expense.amount).toFixed(2)}</span>
          <button onClick={onDeleteExpense} className="text-slate-300 hover:text-red-500 transition-colors">
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
      {expense.receipts.length > 0 && (
        <div className="flex gap-2 mt-3 overflow-x-auto">
          {expense.receipts.map((r) => (
            <ReceiptThumb
              key={r.id}
              receipt={r}
              onView={() => onViewReceipt(r)}
              onDelete={() => onDeleteReceipt(r.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ReceiptThumb({ receipt, onView, onDelete }: { receipt: Receipt; onView: () => void; onDelete: () => void }) {
  const isPdf = (receipt.content_type || '').includes('pdf');
  return (
    <div className="relative group flex-shrink-0">
      <button
        onClick={onView}
        className={`w-16 h-16 rounded-xl border border-slate-200 overflow-hidden flex items-center justify-center ${isPdf ? 'bg-red-50' : 'bg-slate-100'}`}
      >
        {isPdf ? (
          <FileText className="w-6 h-6 text-red-500" />
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={receipt.media_url} alt={receipt.filename || 'receipt'} className="w-full h-full object-cover" />
        )}
      </button>
      <button
        onClick={onDelete}
        className="absolute -top-1 -right-1 bg-white rounded-full p-1 shadow opacity-0 group-hover:opacity-100 transition-opacity"
        title="Eliminar comprobante"
      >
        <X className="w-3 h-3 text-red-500" />
      </button>
    </div>
  );
}

function ReceiptLightbox({ receipt, onClose }: { receipt: Receipt; onClose: () => void }) {
  const isPdf = (receipt.content_type || '').includes('pdf');
  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 bg-black/80 z-[60] flex items-center justify-center p-6"
      onClick={onClose}
    >
      <button onClick={onClose} className="absolute top-6 right-6 text-white bg-white/20 p-2 rounded-full">
        <X className="w-5 h-5" />
      </button>
      {isPdf ? (
        <a href={receipt.media_url} target="_blank" rel="noopener noreferrer"
          className="bg-white px-6 py-4 rounded-2xl text-sm font-black flex items-center gap-2"
          onClick={(e) => e.stopPropagation()}>
          <FileText className="w-5 h-5" /> Abrir PDF
        </a>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={receipt.media_url} alt={receipt.filename || 'receipt'}
          className="max-w-full max-h-full rounded-xl"
          onClick={(e) => e.stopPropagation()} />
      )}
    </motion.div>
  );
}

// ─── New activity modal ───────────────────────────────────────────────────────
function NewActivityModal({ fundraiserId, onClose, onSaved }: { fundraiserId: number; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [occurredOn, setOccurredOn] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    if (!name.trim()) return;
    setSaving(true);
    setErr(null);
    try {
      await api.post(`/fundraisers/${fundraiserId}/activities`, {
        name: name.trim(),
        description: description.trim() || null,
        occurred_on: occurredOn || null,
      });
      onSaved();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || 'Error al guardar');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="Nueva actividad" onClose={onClose}>
      <div className="space-y-4">
        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-400">Nombre</label>
          <input
            value={name} onChange={e => setName(e.target.value)}
            placeholder="Ej: Fiesta fin de año"
            className="w-full px-4 py-4 bg-slate-50 rounded-2xl font-bold text-sm outline-none border-none"
          />
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-400">Descripción (opcional)</label>
          <textarea
            value={description} onChange={e => setDescription(e.target.value)}
            rows={2}
            className="w-full px-4 py-3 bg-slate-50 rounded-2xl font-medium text-sm outline-none border-none resize-none"
          />
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-400">Fecha (opcional)</label>
          <div className="relative">
            <Calendar className="w-4 h-4 absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="date" value={occurredOn} onChange={e => setOccurredOn(e.target.value)}
              className="w-full pl-11 pr-4 py-4 bg-slate-50 rounded-2xl font-bold text-sm outline-none border-none"
            />
          </div>
        </div>
        {err && <div className="text-red-500 text-xs font-bold bg-red-50 rounded-xl p-3">{err}</div>}
        <button
          onClick={save} disabled={saving || !name.trim()}
          className="w-full py-5 bg-indigo-600 text-white rounded-[1.5rem] font-black shadow-xl disabled:opacity-50"
        >
          {saving ? '…' : 'Crear actividad'}
        </button>
      </div>
    </Modal>
  );
}

// ─── New expense modal (receipts required) ────────────────────────────────────
function NewExpenseModal({ activity, onClose, onSaved }: { activity: Activity; onClose: () => void; onSaved: () => void }) {
  const [title, setTitle] = useState('');
  const [amount, setAmount] = useState('');
  const [spentOn, setSpentOn] = useState('');
  const [note, setNote] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const cameraRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    const incoming = Array.from(list);
    setFiles((prev) => [...prev, ...incoming]);
  };

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const canSubmit = title.trim() && amount && files.length > 0 && !saving;

  const save = async () => {
    if (!canSubmit) return;
    setSaving(true);
    setErr(null);
    try {
      const fd = new FormData();
      fd.append('title', title.trim());
      fd.append('amount', amount);
      if (spentOn) fd.append('spent_on', spentOn);
      if (note.trim()) fd.append('note', note.trim());
      files.forEach((f) => fd.append('receipts', f, f.name));
      await api.post(`/fundraisers/activities/${activity.id}/expenses`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      onSaved();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || 'Error al guardar el gasto');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={`Gasto · ${activity.name}`} onClose={onClose}>
      <div className="space-y-4">
        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-400">Título</label>
          <input
            value={title} onChange={e => setTitle(e.target.value)}
            placeholder="Ej: Torta"
            className="w-full px-4 py-4 bg-slate-50 rounded-2xl font-bold text-sm outline-none border-none"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <label className="text-[10px] font-black uppercase tracking-widest text-slate-400">Monto</label>
            <input
              type="number" inputMode="decimal" step="0.01"
              value={amount} onChange={e => setAmount(e.target.value)}
              placeholder="0.00"
              className="w-full px-4 py-4 bg-slate-50 rounded-2xl font-bold text-sm outline-none border-none"
            />
          </div>
          <div className="space-y-2">
            <label className="text-[10px] font-black uppercase tracking-widest text-slate-400">Fecha</label>
            <input
              type="date" value={spentOn} onChange={e => setSpentOn(e.target.value)}
              className="w-full px-4 py-4 bg-slate-50 rounded-2xl font-bold text-sm outline-none border-none"
            />
          </div>
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-400">Nota (opcional)</label>
          <textarea
            value={note} onChange={e => setNote(e.target.value)}
            rows={2}
            className="w-full px-4 py-3 bg-slate-50 rounded-2xl font-medium text-sm outline-none border-none resize-none"
          />
        </div>

        {/* Receipts */}
        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-400">
            Comprobantes <span className="text-red-500">*</span>
          </label>
          <input
            ref={cameraRef}
            type="file" accept="image/*" capture="environment"
            className="hidden"
            onChange={(e) => { addFiles(e.target.files); e.target.value = ''; }}
          />
          <input
            ref={fileRef}
            type="file" accept="image/*,application/pdf" multiple
            className="hidden"
            onChange={(e) => { addFiles(e.target.files); e.target.value = ''; }}
          />
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button" onClick={() => cameraRef.current?.click()}
              className="flex items-center justify-center gap-2 bg-indigo-50 text-indigo-600 py-4 rounded-2xl text-xs font-black uppercase"
            >
              <Camera className="w-4 h-4" /> Tomar foto
            </button>
            <button
              type="button" onClick={() => fileRef.current?.click()}
              className="flex items-center justify-center gap-2 bg-slate-100 text-slate-600 py-4 rounded-2xl text-xs font-black uppercase"
            >
              <FileUp className="w-4 h-4" /> Archivo
            </button>
          </div>
          {files.length === 0 ? (
            <p className="text-[10px] text-slate-400 font-bold">
              Se requiere al menos una foto o archivo.
            </p>
          ) : (
            <div className="space-y-2">
              {files.map((f, i) => (
                <div key={i} className="flex items-center gap-2 bg-slate-50 rounded-xl px-3 py-2">
                  {f.type.includes('pdf') ? (
                    <FileText className="w-4 h-4 text-red-500 flex-shrink-0" />
                  ) : (
                    <ImageIcon className="w-4 h-4 text-indigo-500 flex-shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-bold text-slate-700 truncate">{f.name}</div>
                    <div className="text-[10px] text-slate-400 font-bold">{(f.size / 1024).toFixed(0)} KB</div>
                  </div>
                  <button onClick={() => removeFile(i)} className="text-slate-300 hover:text-red-500">
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {err && <div className="text-red-500 text-xs font-bold bg-red-50 rounded-xl p-3">{err}</div>}

        <button
          onClick={save} disabled={!canSubmit}
          className="w-full py-5 bg-indigo-600 text-white rounded-[1.5rem] font-black shadow-xl disabled:opacity-50"
        >
          {saving ? 'Subiendo…' : 'Guardar gasto'}
        </button>
      </div>
    </Modal>
  );
}
