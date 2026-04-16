'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Camera, FileUp, FileText, Image as ImageIcon, X, DollarSign, Phone, User, Search, ChevronDown } from 'lucide-react';
import api from '@/lib/api';
import { Modal } from '@/components/shared/Modal';

type Method = 'cash' | 'bank' | 'other';

type Contact = {
  phone: string;
  name: string;
  children: string[];
  classrooms: string[];
  jid: string;
};

export function ManualPaymentModal({
  fundraiserId,
  fundraiserName,
  onClose,
  onSaved,
}: {
  fundraiserId: number;
  fundraiserName: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [phone, setPhone]           = useState('');
  const [contacts, setContacts]     = useState<Contact[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState('');
  const [childName, setChildName]   = useState('');
  const [amount, setAmount]         = useState('');
  const [method, setMethod]         = useState<Method>('cash');
  const [methodNote, setMethodNote] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [proof, setProof]           = useState<File | null>(null);
  const [saving, setSaving]         = useState(false);
  const [err, setErr]               = useState<string | null>(null);

  const cameraRef = useRef<HTMLInputElement>(null);
  const fileRef   = useRef<HTMLInputElement>(null);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get(`/fundraisers/${fundraiserId}/contacts`);
        setContacts(data || []);
      } catch { /* silent — picker is optional */ }
    })();
  }, [fundraiserId]);

  const filteredContacts = useMemo(() => {
    const q = pickerQuery.trim().toLowerCase();
    if (!q) return contacts;
    return contacts.filter(c =>
      c.name.toLowerCase().includes(q) ||
      c.phone.includes(q) ||
      c.children.some(ch => ch.toLowerCase().includes(q)) ||
      c.classrooms.some(cl => cl.toLowerCase().includes(q))
    );
  }, [contacts, pickerQuery]);

  const pickContact = (c: Contact) => {
    setPhone(c.phone);
    if (c.children.length === 1) setChildName(c.children[0]);
    setPickerOpen(false);
    setPickerQuery('');
  };

  const canSubmit = phone.trim() && amount && !saving;

  const save = async () => {
    if (!canSubmit) return;
    setSaving(true);
    setErr(null);
    try {
      const fd = new FormData();
      fd.append('payer_phone', phone.replace(/\D/g, ''));
      fd.append('amount', amount);
      fd.append('method', method);
      if (childName.trim())   fd.append('child_name', childName.trim());
      if (methodNote.trim())  fd.append('method_note', methodNote.trim());
      if (confirmation.trim()) fd.append('confirmation_code', confirmation.trim());
      if (proof)              fd.append('proof', proof, proof.name);

      await api.post(`/fundraisers/${fundraiserId}/payments/manual`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      onSaved();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || 'Error al registrar el pago');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="Registrar pago manual" onClose={onClose}>
      <div className="space-y-4">
        <div className="bg-amber-50 border border-amber-100 rounded-2xl p-3 text-[11px] font-medium text-amber-800 leading-snug">
          ⚠ El padre recibirá una notificación por WhatsApp. Los pagos manuales quedan
          auditados con tu identidad. Destino: <b>{fundraiserName}</b>
        </div>

        {/* Known-contact picker */}
        {contacts.length > 0 && (
          <div className="space-y-2">
            <label className="text-[10px] font-black uppercase tracking-widest text-slate-400">Elegir del grupo</label>
            <button
              type="button"
              onClick={() => setPickerOpen(o => !o)}
              className="w-full flex items-center justify-between px-4 py-4 bg-slate-50 rounded-2xl text-sm font-bold text-slate-700"
            >
              <span className="truncate">
                {phone
                  ? (contacts.find(c => c.phone === phone)?.name || phone)
                  : `Buscar contacto (${contacts.length})`}
              </span>
              <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${pickerOpen ? 'rotate-180' : ''}`} />
            </button>

            {pickerOpen && (
              <div className="border border-slate-100 rounded-2xl overflow-hidden bg-white">
                <div className="relative border-b border-slate-100">
                  <Search className="w-4 h-4 absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    autoFocus
                    value={pickerQuery} onChange={e => setPickerQuery(e.target.value)}
                    placeholder="Nombre, teléfono, estudiante, salón…"
                    className="w-full pl-11 pr-4 py-3 font-bold text-sm outline-none"
                  />
                </div>
                <div className="max-h-60 overflow-y-auto">
                  {filteredContacts.length === 0 ? (
                    <div className="text-center text-slate-400 py-6 text-xs font-bold">Sin resultados</div>
                  ) : (
                    filteredContacts.map(c => (
                      <button
                        key={c.jid + c.phone}
                        type="button"
                        onClick={() => pickContact(c)}
                        className="w-full px-4 py-3 hover:bg-slate-50 text-left border-b border-slate-50 last:border-b-0"
                      >
                        <div className="text-xs font-black text-slate-800 truncate">{c.name}</div>
                        <div className="text-[10px] text-slate-400 font-bold truncate">
                          {c.phone}
                          {c.children.length > 0 && <span> · {c.children.join(', ')}</span>}
                          {c.classrooms.length > 0 && <span> · {c.classrooms.join(', ')}</span>}
                        </div>
                      </button>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        <Field label="O escribe el teléfono" icon={<Phone className="w-4 h-4" />}>
          <input
            value={phone} onChange={e => setPhone(e.target.value)}
            inputMode="tel" placeholder="507xxxxxxxx"
            className="w-full pl-11 pr-4 py-4 bg-slate-50 rounded-2xl font-bold text-sm outline-none border-none"
          />
        </Field>

        <Field label="Estudiante (opcional)" icon={<User className="w-4 h-4" />}>
          <input
            value={childName} onChange={e => setChildName(e.target.value)}
            className="w-full pl-11 pr-4 py-4 bg-slate-50 rounded-2xl font-bold text-sm outline-none border-none"
          />
        </Field>

        <Field label="Monto" icon={<DollarSign className="w-4 h-4" />}>
          <input
            value={amount} onChange={e => setAmount(e.target.value)}
            type="number" inputMode="decimal" step="0.01" placeholder="0.00"
            className="w-full pl-11 pr-4 py-4 bg-slate-50 rounded-2xl font-bold text-sm outline-none border-none"
          />
        </Field>

        {/* Method */}
        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-400">Método</label>
          <div className="grid grid-cols-3 gap-2">
            {(['cash', 'bank', 'other'] as const).map(m => (
              <button key={m} type="button" onClick={() => setMethod(m)}
                className={`py-3 rounded-2xl text-xs font-black uppercase transition-all ${method === m ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-100' : 'bg-slate-100 text-slate-400'}`}>
                {m === 'cash' ? 'Efectivo' : m === 'bank' ? 'Banco' : 'Otro'}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-400">Nota / referencia</label>
          <input
            value={methodNote} onChange={e => setMethodNote(e.target.value)}
            placeholder='Ej: "Entregado en reunión 10/abr"'
            className="w-full px-4 py-4 bg-slate-50 rounded-2xl font-bold text-sm outline-none border-none"
          />
        </div>

        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-400">Código de confirmación (opcional)</label>
          <input
            value={confirmation} onChange={e => setConfirmation(e.target.value)}
            placeholder="Ej: REF12345"
            className="w-full px-4 py-4 bg-slate-50 rounded-2xl font-bold text-sm outline-none border-none"
          />
        </div>

        {/* Optional proof */}
        <div className="space-y-2">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-400">Comprobante (opcional)</label>
          <input ref={cameraRef} type="file" accept="image/*" capture="environment" className="hidden"
            onChange={(e) => { if (e.target.files?.[0]) setProof(e.target.files[0]); e.target.value = ''; }} />
          <input ref={fileRef}   type="file" accept="image/*,application/pdf" className="hidden"
            onChange={(e) => { if (e.target.files?.[0]) setProof(e.target.files[0]); e.target.value = ''; }} />
          <div className="grid grid-cols-2 gap-2">
            <button type="button" onClick={() => cameraRef.current?.click()}
              className="flex items-center justify-center gap-2 bg-indigo-50 text-indigo-600 py-4 rounded-2xl text-xs font-black uppercase">
              <Camera className="w-4 h-4" /> Tomar foto
            </button>
            <button type="button" onClick={() => fileRef.current?.click()}
              className="flex items-center justify-center gap-2 bg-slate-100 text-slate-600 py-4 rounded-2xl text-xs font-black uppercase">
              <FileUp className="w-4 h-4" /> Archivo
            </button>
          </div>
          {proof && (
            <div className="flex items-center gap-2 bg-slate-50 rounded-xl px-3 py-2">
              {proof.type.includes('pdf')
                ? <FileText className="w-4 h-4 text-red-500 flex-shrink-0" />
                : <ImageIcon className="w-4 h-4 text-indigo-500 flex-shrink-0" />}
              <div className="flex-1 min-w-0">
                <div className="text-xs font-bold text-slate-700 truncate">{proof.name}</div>
                <div className="text-[10px] text-slate-400 font-bold">{(proof.size / 1024).toFixed(0)} KB</div>
              </div>
              <button type="button" onClick={() => setProof(null)} className="text-slate-300 hover:text-red-500">
                <X className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>

        {err && <div className="text-red-500 text-xs font-bold bg-red-50 rounded-xl p-3">{err}</div>}

        <button
          onClick={save} disabled={!canSubmit}
          className="w-full py-5 bg-indigo-600 text-white rounded-[1.5rem] font-black shadow-xl disabled:opacity-50"
        >
          {saving ? 'Registrando…' : 'Registrar pago'}
        </button>
      </div>
    </Modal>
  );
}

function Field({ label, icon, children }: { label: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <label className="text-[10px] font-black uppercase tracking-widest text-slate-400">{label}</label>
      <div className="relative">
        <div className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400">{icon}</div>
        {children}
      </div>
    </div>
  );
}
