'use client';

import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X } from 'lucide-react';

export function Modal({ title, children, onClose }: any) {
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-end justify-center" onClick={onClose}>
      <motion.div initial={{ y: "100%" }} animate={{ y: 0 }} exit={{ y: "100%" }} transition={{ type: "spring", damping: 25 }} className="bg-white w-full max-w-lg rounded-t-[3rem] p-8 pb-12 overflow-y-auto max-h-[90vh]" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-8">
          <h2 className="text-2xl font-black tracking-tight">{title}</h2>
          <button onClick={onClose} className="bg-slate-100 p-2 rounded-full text-slate-400"><X /></button>
        </div>
        {children}
      </motion.div>
    </motion.div>
  );
}
