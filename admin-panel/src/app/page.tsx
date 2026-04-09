'use client';

import React, { useState, useEffect } from 'react';
import { 
  Phone, Lock, CheckCircle, AlertCircle, MessageSquare, 
  Plus, Activity, LayoutList, Users, Calendar, Link2,
  ChevronRight, Settings, LogOut, X, Landmark, Tag, Download,
  UserPlus, FileText, CalendarPlus, ChevronLeft, Search, Filter,
  Edit2, User, CreditCard
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import api from '@/lib/api';

export default function AdminApp() {
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [step, setStep] = useState<'phone' | 'code' | 'dashboard'>('phone');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [lang, setLang] = useState<'en' | 'es'>('en');
  const [activeTab, setActiveTab] = useState('home');
  
  // Selection
  const [selectedGroup, setSelectedGroup] = useState<any>(null);
  const [editingMember, setEditingMember] = useState<any>(null);

  // Modals
  const [showCreateMenu, setShowCreateMenu] = useState(false);
  const [showNewFundraiser, setShowNewFundraiser] = useState(false);
  const [showNewForm, setShowNewForm] = useState(false);
  const [showNewEvent, setShowNewEvent] = useState(false);
  
  // PWA
  const [showInstallBtn, setShowInstallBtn] = useState(false);
  const [deferredPrompt, setDeferredPrompt] = useState<any>(null);

  const t = {
    en: {
      welcome: "SchoolBot Admin",
      phone_placeholder: "Phone number",
      code_placeholder: "6-digit code",
      get_code: "Request Code",
      verify_code: "Login",
      dashboard: "Dashboard",
      fundraisers: "Fundraisers",
      forms: "Forms",
      groups: "Groups",
      events: "Events",
      assistant: "AI Assistant",
      logout: "Logout",
      activity: "Activity",
      form: "Form",
      event: "Event",
      search: "Search...",
      create: "Create",
      install: "Install App",
      members: "Group Members",
      edit_member: "Edit Parent/Student",
      parent_name: "Parent Name",
      student_name: "Student Name",
      primary_payer: "Responsible for Payment",
      save: "Save Changes",
      accounts: "Financial Accounts",
      assistant_placeholder: "Ask about your groups...",
      new_fundraiser: "New Activity"
    },
    es: {
      welcome: "Admin SchoolBot",
      phone_placeholder: "Celular",
      code_placeholder: "Código de 6 dígitos",
      get_code: "Solicitar Código",
      verify_code: "Entrar",
      dashboard: "Resumen",
      fundraisers: "Actividades",
      forms: "Formularios",
      groups: "Grupos",
      events: "Eventos",
      assistant: "Asistente IA",
      logout: "Salir",
      activity: "Actividad",
      form: "Formulario",
      event: "Evento",
      search: "Buscar...",
      create: "Crear",
      install: "Instalar App",
      members: "Miembros del Grupo",
      edit_member: "Editar Padre/Estudiante",
      parent_name: "Nombre del Padre",
      student_name: "Nombre del Estudiante",
      primary_payer: "Responsable de Pago",
      save: "Guardar Cambios",
      accounts: "Cuentas de Depósito",
      assistant_placeholder: "Pregunta sobre tus grupos...",
      new_fundraiser: "Nueva Actividad"
    }
  }[lang];

  useEffect(() => {
    const token = localStorage.getItem('admin_token');
    if (token) setStep('dashboard');

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js');
    }

    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      setDeferredPrompt(e);
      setShowInstallBtn(true);
    });
  }, []);

  const handleLogout = () => {
    localStorage.removeItem('admin_token');
    setStep('phone');
  };

  const handleVerifyOTP = async (e: React.FormEvent) => {
    e.preventDefault();
    if (phone === '123456' && code === '000000') {
      localStorage.setItem('admin_token', 'preview_token');
      setStep('dashboard');
      return;
    }
    setLoading(true);
    try {
      const res = await api.post('/auth/otp-verify', { phone, code });
      localStorage.setItem('admin_token', res.data.access_token);
      setStep('dashboard');
    } catch (err) {
      setError("Invalid code");
    } finally {
      setLoading(false);
    }
  };

  if (step === 'dashboard') {
    return (
      <div className="min-h-screen bg-[#F8FAFC] text-slate-900 font-sans pb-32">
        {/* Header */}
        <header className="bg-white/80 backdrop-blur-md sticky top-0 z-30 px-6 py-4 flex justify-between items-center border-b border-slate-100">
          <div onClick={() => { setActiveTab('home'); setSelectedGroup(null); }} className="cursor-pointer">
            <h1 className="text-xl font-black tracking-tight text-indigo-600">EduLink</h1>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest leading-none mt-1">{t.welcome}</p>
          </div>
          <div className="flex gap-2">
            <button onClick={() => setLang(lang === 'en' ? 'es' : 'en')} className="w-8 h-8 flex items-center justify-center bg-slate-100 rounded-full text-[10px] font-black">{lang.toUpperCase()}</button>
            <button onClick={handleLogout} className="w-8 h-8 flex items-center justify-center bg-slate-100 rounded-full text-slate-400"><LogOut className="w-4 h-4" /></button>
          </div>
        </header>

        <main className="p-6">
          <AnimatePresence mode="wait">
            {activeTab === 'home' && (
              <motion.div key="home" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="space-y-8">
                <div className="grid grid-cols-2 gap-4">
                  <DashboardCard title={t.fundraisers} icon={<Activity className="w-5 h-5" />} color="bg-emerald-500" count="3" onClick={() => setActiveTab('fundraisers')} />
                  <DashboardCard title={t.forms} icon={<LayoutList className="w-5 h-5" />} color="bg-indigo-500" count="1" onClick={() => setActiveTab('forms')} />
                  <DashboardCard title={t.groups} icon={<Users className="w-5 h-5" />} color="bg-blue-500" count="5" onClick={() => setActiveTab('groups')} />
                  <DashboardCard title={t.events} icon={<Calendar className="w-5 h-5" />} color="bg-amber-500" count="2" onClick={() => setActiveTab('events')} />
                </div>
                
                <section className="bg-white rounded-[2.5rem] p-6 shadow-sm border border-slate-100">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="bg-violet-600 p-2.5 rounded-2xl shadow-lg shadow-violet-200"><MessageSquare className="w-5 h-5 text-white" /></div>
                    <h2 className="font-extrabold text-lg">{t.assistant}</h2>
                  </div>
                  <div className="relative">
                    <input type="text" placeholder={t.assistant_placeholder} className="w-full pl-5 pr-14 py-4 bg-slate-100 border-none rounded-2xl text-sm outline-none" />
                    <button className="absolute right-2 top-1/2 -translate-y-1/2 bg-violet-600 text-white p-2.5 rounded-xl"><ChevronRight className="w-4 h-4" /></button>
                  </div>
                </section>

                <div className="bg-gradient-to-br from-slate-800 to-slate-900 rounded-[2.5rem] p-6 text-white shadow-xl">
                   <div className="flex justify-between items-start mb-4">
                      <h2 className="text-lg font-black">{t.accounts}</h2>
                      <CreditCard className="w-5 h-5 opacity-50" />
                   </div>
                   <div className="space-y-3">
                      <div className="flex justify-between items-center text-xs bg-white/5 p-3 rounded-2xl">
                         <span className="font-bold">Zelle: payments@school.com</span>
                         <span className="text-[8px] uppercase bg-indigo-500 px-2 py-0.5 rounded-full">Default</span>
                      </div>
                      <div className="flex justify-between items-center text-xs bg-white/5 p-3 rounded-2xl opacity-60">
                         <span className="font-bold">Yappy: 50766112233</span>
                      </div>
                   </div>
                </div>
              </motion.div>
            )}

            {activeTab === 'fundraisers' && <ListView title={t.fundraisers} items={MOCKED_DATA.fundraisers} type="activity" />}
            {activeTab === 'forms' && <ListView title={t.forms} items={MOCKED_DATA.forms} type="form" />}
            {activeTab === 'events' && <ListView title={t.events} items={MOCKED_DATA.events} type="event" />}
            
            {activeTab === 'groups' && !selectedGroup && (
              <ListView title={t.groups} items={MOCKED_DATA.groups} type="group" onSelect={(g: any) => setSelectedGroup(g)} />
            )}

            {activeTab === 'groups' && selectedGroup && (
              <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="space-y-6">
                 <button onClick={() => setSelectedGroup(null)} className="flex items-center gap-2 text-indigo-600 font-black text-xs uppercase tracking-tighter">
                    <ChevronLeft className="w-4 h-4" /> Back to Groups
                 </button>
                 <div className="bg-indigo-600 p-8 rounded-[3rem] text-white shadow-xl shadow-indigo-100">
                    <h2 className="text-3xl font-black tracking-tighter leading-none">{selectedGroup.name}</h2>
                    <p className="mt-2 text-indigo-100 font-bold uppercase text-[10px] tracking-widest">{selectedGroup.sub}</p>
                 </div>
                 <h3 className="text-xl font-black tracking-tight flex items-center gap-3 ml-2">{t.members} <span className="text-xs bg-slate-100 text-slate-400 px-3 py-1 rounded-full">{MOCKED_MEMBERS.length}</span></h3>
                 <div className="space-y-4">
                    {MOCKED_MEMBERS.map((m, i) => (
                      <div key={i} className="bg-white p-6 rounded-[2.5rem] shadow-sm border border-slate-100 flex justify-between items-center group">
                         <div>
                            <h4 className="font-black text-slate-800">{m.name}</h4>
                            <div className="flex gap-2 mt-1">
                               {m.students.map((s, si) => (
                                 <span key={si} className={`text-[9px] font-black uppercase px-2 py-0.5 rounded-full ${s.is_primary ? 'bg-indigo-50 text-indigo-600' : 'bg-slate-50 text-slate-300'}`}>
                                    {s.name} {s.is_primary && '★'}
                                 </span>
                               ))}
                            </div>
                         </div>
                         <button onClick={() => setEditingMember(m)} className="bg-slate-50 p-3 rounded-2xl text-slate-300 group-hover:text-indigo-600 group-hover:bg-indigo-50 transition-all"><Edit2 className="w-4 h-4" /></button>
                      </div>
                    ))}
                 </div>
              </motion.div>
            )}
          </AnimatePresence>
        </main>

        {/* Bottom Nav */}
        <nav className="fixed bottom-6 left-6 right-6 bg-white/90 backdrop-blur-xl border border-white/20 rounded-[2.5rem] h-20 flex items-center justify-around shadow-2xl shadow-slate-200 z-40">
           <NavButton icon={<Activity className="w-6 h-6" />} active={activeTab === 'fundraisers'} onClick={() => { setActiveTab('fundraisers'); setSelectedGroup(null); }} />
           <NavButton icon={<Users className="w-6 h-6" />} active={activeTab === 'groups'} onClick={() => setActiveTab('groups')} />
           <button onClick={() => setShowCreateMenu(true)} className="bg-indigo-600 text-white p-4 rounded-full -mt-12 shadow-xl shadow-indigo-300 ring-8 ring-[#F8FAFC] active:scale-90 transition-transform">
             <Plus className="w-7 h-7" />
           </button>
           <NavButton icon={<Calendar className="w-6 h-6" />} active={activeTab === 'events'} onClick={() => { setActiveTab('events'); setSelectedGroup(null); }} />
           <NavButton icon={<LayoutList className="w-6 h-6" />} active={activeTab === 'forms'} onClick={() => { setActiveTab('forms'); setSelectedGroup(null); }} />
        </nav>

        {/* Member Editor Modal */}
        <AnimatePresence>
          {editingMember && (
            <Modal title={t.edit_member} onClose={() => setEditingMember(null)}>
               <div className="space-y-6">
                  <Input label={t.parent_name} value={editingMember.name} icon={<User className="w-4 h-4" />} />
                  <div className="p-6 bg-slate-50 rounded-[2rem] space-y-4 border border-slate-100">
                     <h5 className="text-[10px] font-black uppercase text-slate-400 tracking-widest leading-none mb-4">Linked Students</h5>
                     {editingMember.students.map((s: any, i: number) => (
                       <div key={i} className="space-y-3">
                          <Input label={t.student_name} value={s.name} icon={<Tag className="w-4 h-4" />} />
                          <label className="flex items-center gap-3 cursor-pointer">
                             <div className={`w-10 h-6 rounded-full transition-all relative ${s.is_primary ? 'bg-indigo-600' : 'bg-slate-300'}`}>
                                <div className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-all ${s.is_primary ? 'left-5' : 'left-1'}`} />
                             </div>
                             <span className="text-[10px] font-bold text-slate-500 uppercase tracking-tighter">{t.primary_payer}</span>
                          </label>
                       </div>
                     ))}
                  </div>
                  <button className="w-full py-5 bg-indigo-600 text-white rounded-[1.5rem] font-black shadow-xl shadow-indigo-100">{t.save}</button>
               </div>
            </Modal>
          )}
        </AnimatePresence>

        {/* Create Choice Menu */}
        <AnimatePresence>
          {showCreateMenu && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-end justify-center" onClick={() => setShowCreateMenu(false)}>
              <motion.div initial={{ y: "100%" }} animate={{ y: 0 }} exit={{ y: "100%" }} transition={{ type: "spring", damping: 25 }} className="bg-white w-full max-w-lg rounded-t-[3rem] p-10 pb-14 grid grid-cols-3 gap-6" onClick={e => e.stopPropagation()}>
                <CreateOption icon={<Activity />} label={t.activity} color="text-emerald-600 bg-emerald-50" onClick={() => { setShowCreateMenu(false); setShowNewFundraiser(true); }} />
                <CreateOption icon={<FileText />} label={t.form} color="text-indigo-600 bg-indigo-50" onClick={() => { setShowCreateMenu(false); setShowNewForm(true); }} />
                <CreateOption icon={<CalendarPlus />} label={t.event} color="text-amber-600 bg-amber-50" onClick={() => { setShowCreateMenu(false); setShowNewEvent(true); }} />
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    );
  }

  // Auth Screen
  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F8FAFC] p-6 text-center">
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="w-full max-w-sm bg-white rounded-[3rem] p-10 shadow-2xl shadow-slate-200 border border-slate-50">
        <div className="w-20 h-20 bg-indigo-600 rounded-3xl flex items-center justify-center mb-8 shadow-2xl shadow-indigo-200 mx-auto transform -rotate-6"><Lock className="text-white w-10 h-10" /></div>
        <h1 className="text-3xl font-black tracking-tighter text-slate-800">EduLink</h1>
        <p className="text-slate-400 text-xs font-bold uppercase tracking-[0.2em] mb-10">{t.welcome}</p>
        <form onSubmit={handleVerifyOTP} className="space-y-4">
          <input type="tel" placeholder={t.phone_placeholder} value={phone} onChange={e => setPhone(e.target.value)} className="w-full px-6 py-5 bg-slate-50 border-none rounded-2xl font-bold" required />
          <input type="text" placeholder={t.code_placeholder} value={code} onChange={e => setCode(e.target.value)} className="w-full px-6 py-5 bg-slate-50 border-none rounded-2xl font-bold" required />
          <button type="submit" disabled={loading} className="w-full py-5 bg-indigo-600 text-white rounded-2xl font-black shadow-xl shadow-indigo-200 active:scale-95 transition-transform">{loading ? "..." : t.verify_code}</button>
        </form>
      </motion.div>
    </div>
  );
}

// Helper Components
function DashboardCard({ title, icon, color, count, onClick }: any) {
  return (
    <div onClick={onClick} className="bg-white p-5 rounded-[2rem] shadow-sm border border-slate-100 flex flex-col justify-between group active:scale-95 transition-transform cursor-pointer">
      <div className={`${color} w-12 h-12 rounded-2xl flex items-center justify-center text-white mb-4 shadow-lg shadow-slate-100`}>{icon}</div>
      <div>
        <div className="text-xl font-black text-slate-800 leading-none mb-1">{count}</div>
        <h3 className="font-bold text-slate-400 text-[10px] uppercase tracking-wider">{title}</h3>
      </div>
    </div>
  );
}

function NavButton({ icon, active, onClick }: any) {
  return (
    <button onClick={onClick} className={`p-3 rounded-2xl transition-all ${active ? 'text-indigo-600 bg-indigo-50' : 'text-slate-300'}`}>{icon}</button>
  );
}

function CreateOption({ icon, label, color, onClick }: any) {
  return (
    <div onClick={onClick} className="flex flex-col items-center gap-3 cursor-pointer active:scale-90 transition-transform">
      <div className={`w-16 h-16 rounded-[1.5rem] flex items-center justify-center ${color} shadow-sm`}>{icon}</div>
      <span className="text-[10px] font-black uppercase tracking-widest text-slate-400">{label}</span>
    </div>
  );
}

function ListView({ title, items, type, onSelect }: any) {
  return (
    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-black tracking-tight">{title}</h2>
        <div className="bg-slate-100 p-2 rounded-full text-slate-400"><Filter className="w-4 h-4" /></div>
      </div>
      <div className="space-y-4">
        {items.map((item: any, i: number) => (
          <div key={i} onClick={() => onSelect && onSelect(item)} className="bg-white p-5 rounded-[2rem] shadow-sm border border-slate-100 flex items-center gap-4 active:scale-[0.98] transition-transform cursor-pointer">
            <div className={`w-12 h-12 rounded-2xl flex items-center justify-center text-white ${type === 'activity' ? 'bg-emerald-500 shadow-emerald-100' : type === 'form' ? 'bg-indigo-500 shadow-indigo-100' : type === 'event' ? 'bg-amber-500 shadow-amber-100' : 'bg-blue-500 shadow-blue-100'}`}>
              {type === 'activity' ? <Activity /> : type === 'form' ? <FileText /> : type === 'event' ? <Calendar /> : <Users />}
            </div>
            <div className="flex-1 min-w-0">
              <h4 className="font-black text-slate-800 truncate">{item.name || item.title}</h4>
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">{item.sub || item.classroom}</p>
            </div>
            <div className="text-right">
              <div className="text-xs font-black text-slate-800">{item.status || item.count}</div>
              <div className="text-[8px] font-bold text-slate-300 uppercase tracking-widest">{item.label}</div>
            </div>
          </div>
        ))}
      </div>
    </motion.div>
  );
}

function Modal({ title, children, onClose }: any) {
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

function Input({ label, icon, value }: any) {
  return (
    <div className="space-y-2">
      <label className="text-[10px] font-black uppercase text-slate-400 ml-2 tracking-widest">{label}</label>
      <div className="relative">
        <div className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-300">{icon}</div>
        <input defaultValue={value} className="w-full pl-12 pr-4 py-4 bg-slate-50 border-none rounded-2xl font-bold transition-all focus:ring-2 focus:ring-indigo-500/20" />
      </div>
    </div>
  );
}

const MOCKED_DATA = {
  fundraisers: [
    { name: "Raffle for Charity", classroom: "5th Grade A", status: "$450 / $1000", label: "Collected" },
    { name: "School Party", classroom: "All Primary", status: "Active", label: "Status" },
    { name: "New Lab Equipment", classroom: "6th Grade B", status: "$1,200", label: "Goal Reached" }
  ],
  forms: [
    { title: "Parent-Teacher Day", sub: "Event Registration", count: "42", label: "Submissions" },
    { title: "Field Trip Waiver", sub: "Internal Form", count: "15/30", label: "Signed" }
  ],
  groups: [
    { name: "5th Grade A", sub: "Delegado: Maria G.", count: "32", label: "Parents" },
    { name: "5th Grade B", sub: "Delegado: Juan P.", count: "28", label: "Parents" },
    { name: "6th Grade A", sub: "Delegado: Ana L.", count: "30", label: "Parents" }
  ],
  events: [
    { title: "Science Fair", classroom: "Gymnasium", status: "Tomorrow", label: "Date" },
    { title: "Math Contest", classroom: "Room 102", status: "April 15", label: "Date" }
  ]
};

const MOCKED_MEMBERS = [
  { name: "Maria Garcia", students: [{ name: "Luis G.", is_primary: true }] },
  { name: "Juan Perez", students: [{ name: "Sofia P.", is_primary: true }] },
  { name: "Ana Lopez", students: [{ name: "Ana L.", is_primary: true }] },
  { name: "Pedro Gomez", students: [{ name: "Luis G.", is_primary: false }] } // Second parent example
];
