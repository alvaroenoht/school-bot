'use client';

import { useEffect, useState } from 'react';
import { Modal } from '@/components/shared/Modal';
import api from '@/lib/api';
import { History } from 'lucide-react';

type AuditRow = {
  id: number;
  action: string;
  actor_jid: string;
  at: string;
  snapshot: any;
};

const LABEL: Record<string, string> = {
  created_manual: 'Pago manual registrado',
  voided:         'Anulado',
  restored:       'Restaurado',
};

const COLOR: Record<string, string> = {
  created_manual: 'bg-indigo-50 text-indigo-600',
  voided:         'bg-red-50 text-red-600',
  restored:       'bg-emerald-50 text-emerald-600',
};

export function PaymentAuditDrawer({ paymentId, onClose }: { paymentId: number; onClose: () => void }) {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [err, setErr]   = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get(`/fundraisers/payments/${paymentId}/audit`);
        setRows(data);
      } catch (e: any) {
        setErr(e?.response?.data?.detail || 'Error al cargar auditoría');
      }
    })();
  }, [paymentId]);

  return (
    <Modal title="Auditoría del pago" onClose={onClose}>
      <div className="space-y-3">
        {err && <div className="text-red-500 text-xs font-bold bg-red-50 rounded-xl p-3">{err}</div>}
        {rows == null ? (
          <div className="text-center text-slate-400 py-6 text-xs font-bold">Cargando…</div>
        ) : rows.length === 0 ? (
          <div className="text-center text-slate-400 py-6 text-xs font-bold">Sin registros.</div>
        ) : (
          rows.map(r => (
            <div key={r.id} className="bg-slate-50 rounded-2xl p-4">
              <div className="flex items-center justify-between mb-1">
                <span className={`text-[10px] font-black uppercase px-2 py-0.5 rounded-full ${COLOR[r.action] || 'bg-slate-100 text-slate-500'}`}>
                  <History className="w-3 h-3 inline mr-1 -mt-0.5" />
                  {LABEL[r.action] || r.action}
                </span>
                <span className="text-[10px] font-bold text-slate-400">
                  {new Date(r.at).toLocaleString()}
                </span>
              </div>
              <div className="text-[11px] font-bold text-slate-600">
                por <span className="font-mono">{r.actor_jid}</span>
              </div>
              {r.snapshot?.reason && (
                <div className="mt-2 text-xs text-slate-700 italic">"{r.snapshot.reason}"</div>
              )}
              {r.action === 'created_manual' && (
                <div className="mt-2 text-[11px] text-slate-500">
                  ${r.snapshot?.amount} · método: {r.snapshot?.method_note || '—'}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </Modal>
  );
}
