'use client';

import React, { useState, useEffect } from 'react';
import {
  Lock, MessageSquare, Plus, Activity, LayoutList, Users, Calendar,
  ChevronRight, Settings, LogOut, X, Tag, FileText, CalendarPlus,
  ChevronLeft, Filter, Edit2, User, CreditCard, Check, Trash2,
  Bell, Globe, Key, DollarSign, ShoppingBag, CheckSquare, ToggleLeft, Home
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import api from '@/lib/api';

// ─── Types ────────────────────────────────────────────────────────────────────
interface Product { name: string; price: string; }
interface Question { text: string; type: string; required: boolean; options: string[]; }

const QUESTION_TYPES = ['yes_no', 'text', 'single_choice', 'multi_choice', 'number', 'date'];
const FORM_PURPOSES = ['intake', 'survey', 'event_registration', 'volunteer_signup'];

// ─── Translations ─────────────────────────────────────────────────────────────
const TRANSLATIONS = {
  en: {
    welcome: "SchoolBot Admin", phone_placeholder: "Phone number",
    code_placeholder: "6-digit code", get_code: "Request Code", verify_code: "Login",
    dashboard: "Dashboard", fundraisers: "Fundraisers", forms: "Forms",
    groups: "Groups", events: "Events", assistant: "AI Assistant",
    logout: "Logout", create: "Create", activity: "Fundraiser",
    form: "Form", event: "Event", members: "Group Members",
    parent_name: "Parent Name", student_name: "Student Name",
    primary_payer: "Primary Payer", save: "Save", settings: "Settings",
    accounts: "Payment Accounts", edulink_setup: "School Portal (EduLink)",
    remind: "Send Reminders", reopen: "Reopen", close: "Close",
    report: "Live Report", fund_name: "Activity Name", fund_account: "Deposit To",
    fund_type: "Type", fund_amount: "Fixed Amount",
    fixed: "Fixed Amount", variable: "Catalog (Variable)",
    add_product: "Add Product", product_name: "Product Name", product_price: "Price",
    audience: "Target Groups", form_title: "Form Title",
    form_description: "Description (optional)", form_purpose: "Purpose",
    intake: "Intake / Registration", survey: "Survey",
    event_registration: "Event Registration", volunteer_signup: "Volunteer Signup",
    question: "Question", question_type: "Type", yes_no: "Yes / No",
    text: "Short Text", single_choice: "Single Choice", multi_choice: "Multiple Choice",
    number: "Number", date: "Date", required: "Required",
    options: "Options (comma separated)", add_question: "Add Question",
    event_title: "Event Title", event_description: "Description",
    event_date: "Date", event_location: "Location",
    portal_user: "Portal Username", portal_pass: "Portal Password",
    reminder_sent: "Reminders Sent!", assistant_placeholder: "Ask about your groups...",
    new_fundraiser: "New Fundraiser", new_form: "New Form", new_event: "New Event",
    no_items: "No items yet", loading: "Loading...", send: "Send",
    account_label: "Account Label", account_type: "Type", account_details: "Details",
    add_account: "Add Account", is_default: "Set as Default",
    bank: "Bank Transfer", phone_yappy: "Yappy (Phone)", submissions: "Submissions",
    payments: "Payments", back: "Back", delete: "Delete", edit: "Edit",
    confirm_delete: "Delete?", language: "Language",
  },
  es: {
    welcome: "Admin SchoolBot", phone_placeholder: "Celular",
    code_placeholder: "Código de 6 dígitos", get_code: "Solicitar Código", verify_code: "Entrar",
    dashboard: "Resumen", fundraisers: "Actividades", forms: "Formularios",
    groups: "Grupos", events: "Eventos", assistant: "Asistente IA",
    logout: "Salir", create: "Crear", activity: "Actividad de Pago",
    form: "Formulario", event: "Evento", members: "Miembros",
    parent_name: "Nombre del Padre", student_name: "Nombre del Estudiante",
    primary_payer: "Responsable Pago", save: "Guardar", settings: "Configuración",
    accounts: "Cuentas de Pago", edulink_setup: "Portal Escolar (EduLink)",
    remind: "Enviar Recordatorios", reopen: "Reabrir", close: "Cerrar",
    report: "Reporte en Vivo", fund_name: "Nombre de Actividad", fund_account: "Depositar a",
    fund_type: "Tipo", fund_amount: "Monto Fijo",
    fixed: "Monto Fijo", variable: "Catálogo (Variable)",
    add_product: "Agregar Producto", product_name: "Nombre del Producto", product_price: "Precio",
    audience: "Grupos Objetivo", form_title: "Título del Formulario",
    form_description: "Descripción (opcional)", form_purpose: "Propósito",
    intake: "Registro / Inscripción", survey: "Encuesta",
    event_registration: "Inscripción a Evento", volunteer_signup: "Solicitud Voluntario",
    question: "Pregunta", question_type: "Tipo", yes_no: "Sí / No",
    text: "Texto Corto", single_choice: "Opción Única", multi_choice: "Opción Múltiple",
    number: "Número", date: "Fecha", required: "Requerido",
    options: "Opciones (separadas por coma)", add_question: "Agregar Pregunta",
    event_title: "Título del Evento", event_description: "Descripción",
    event_date: "Fecha", event_location: "Ubicación",
    portal_user: "Usuario del Portal", portal_pass: "Contraseña del Portal",
    reminder_sent: "¡Recordatorios Enviados!", assistant_placeholder: "Pregunta sobre tus grupos...",
    new_fundraiser: "Nueva Actividad", new_form: "Nuevo Formulario", new_event: "Nuevo Evento",
    no_items: "Sin elementos", loading: "Cargando...", send: "Enviar",
    account_label: "Etiqueta", account_type: "Tipo", account_details: "Detalles",
    add_account: "Agregar Cuenta", is_default: "Establecer por Defecto",
    bank: "Transferencia Bancaria", phone_yappy: "Yappy (Teléfono)", submissions: "Respuestas",
    payments: "Pagos", back: "Atrás", delete: "Eliminar", edit: "Editar",
    confirm_delete: "¿Eliminar?", language: "Idioma",
  }
} as const;

// ─── Main Component ───────────────────────────────────────────────────────────
export default function AdminApp() {
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [step, setStep] = useState<'phone' | 'code' | 'dashboard'>('phone');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [lang, setLang] = useState<'en' | 'es'>('es');
  const [activeTab, setActiveTab] = useState('home');
  const [adminPhone, setAdminPhone] = useState('');

  // Lists
  const [fundraisers, setFundraisers] = useState<any[]>([]);
  const [forms, setForms] = useState<any[]>([]);
  const [classrooms, setClassrooms] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [accounts, setAccounts] = useState<any[]>([]);
  const [dataLoading, setDataLoading] = useState(true);
  const [showArchivedFunds, setShowArchivedFunds] = useState(false);
  const [showArchivedForms, setShowArchivedForms] = useState(false);

  // Detail views
  const [selectedGroup, setSelectedGroup] = useState<any>(null);
  const [groupMembers, setGroupMembers] = useState<any[]>([]);
  const [groupMembersLoading, setGroupMembersLoading] = useState(false);
  const [selectedReport, setSelectedReport] = useState<any>(null);
  const [reportData, setReportData] = useState<any>(null);
  const [editingMember, setEditingMember] = useState<any>(null);
  const [editFirstName, setEditFirstName] = useState('');
  const [editLastName, setEditLastName] = useState('');

  // Modals
  const [showCreateMenu, setShowCreateMenu] = useState(false);
  const [showNewFundraiser, setShowNewFundraiser] = useState(false);
  const [showNewForm, setShowNewForm] = useState(false);
  const [showNewEvent, setShowNewEvent] = useState(false);
  const [showAddAccount, setShowAddAccount] = useState(false);

  // Fundraiser form
  const [fName, setFName] = useState('');
  const [fFriendlyName, setFFriendlyName] = useState('');
  const [fType, setFType] = useState<'fixed' | 'variable'>('fixed');
  const [fAmount, setFAmount] = useState('');
  const [fAccountId, setFAccountId] = useState('');
  const [fAudience, setFAudience] = useState<number[]>([]);
  const [fProducts, setFProducts] = useState<Product[]>([{ name: '', price: '' }]);

  // Form builder
  const [fbTitle, setFbTitle] = useState('');
  const [fbDesc, setFbDesc] = useState('');
  const [fbPurpose, setFbPurpose] = useState('intake');
  const [fbAudience, setFbAudience] = useState<number[]>([]);
  const [fbQuestions, setFbQuestions] = useState<Question[]>([
    { text: '', type: 'yes_no', required: true, options: [] }
  ]);

  // Event form
  const [evTitle, setEvTitle] = useState('');
  const [evDesc, setEvDesc] = useState('');
  const [evDate, setEvDate] = useState('');
  const [evLocation, setEvLocation] = useState('');

  // Account form
  const [accLabel, setAccLabel] = useState('');
  const [accType, setAccType] = useState('phone');
  const [accDetails, setAccDetails] = useState('');
  const [accDefault, setAccDefault] = useState(false);

  // Chat
  const [chatInput, setChatInput] = useState('');
  const [chatMessages, setChatMessages] = useState<{ role: 'user' | 'bot'; text: string }[]>([]);

  const t = TRANSLATIONS[lang];

  // ── Auth ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    const token = localStorage.getItem('admin_token');
    if (token) {
      setStep('dashboard');
      try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        setAdminPhone(payload.phone || payload.sub || '');
      } catch {}
    }
  }, []);

  useEffect(() => { if (step === 'dashboard') fetchAll(); }, [step]);

  // Auto-clear error after 4s
  useEffect(() => {
    if (!error) return;
    const t = setTimeout(() => setError(''), 4000);
    return () => clearTimeout(t);
  }, [error]);

  const fetchAll = async (opts?: { archivedFunds?: boolean; archivedForms?: boolean }) => {
    setDataLoading(true);
    const af = opts?.archivedFunds ?? showArchivedFunds;
    const afo = opts?.archivedForms ?? showArchivedForms;
    try {
      const [fr, fo, cl, ev, ac] = await Promise.all([
        api.get(af ? '/fundraisers?status=closed' : '/fundraisers'),
        api.get(afo ? '/forms?status=closed' : '/forms'),
        api.get('/classrooms'),
        api.get('/events'),
        api.get('/auth/accounts'),
      ]);
      setFundraisers(fr.data || []);
      setForms(fo.data || []);
      setClassrooms(cl.data || []);
      setEvents(ev.data || []);
      setAccounts(ac.data || []);
      if ((ac.data || []).length > 0) setFAccountId(String(ac.data[0].id));
    } catch (e) { console.error(e); setError('Error loading data'); }
    finally { setDataLoading(false); }
  };

  const handleRequestOTP = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true); setError('');
    try {
      const res = await api.post('/auth/otp-request', { phone });
      // Preview backdoor: backend says use 000000
      if (res.data?.message?.includes('000000')) setCode('000000');
      setStep('code');
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Error al solicitar código');
    }
    finally { setLoading(false); }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true); setError('');
    try {
      const res = await api.post('/auth/otp-verify', { phone, code });
      localStorage.setItem('admin_token', res.data.access_token);
      setAdminPhone(phone);
      setStep('dashboard');
    } catch { setError('Código inválido'); }
    finally { setLoading(false); }
  };

  // ── Navigation helpers ────────────────────────────────────────────────────
  const goTab = (tab: string) => {
    setActiveTab(tab);
    setSelectedReport(null); setReportData(null);
    setSelectedGroup(null); setGroupMembers([]);
  };

  const selectGroup = async (g: any) => {
    setSelectedGroup(g); setGroupMembers([]); setGroupMembersLoading(true);
    try { const r = await api.get(`/classrooms/${g.id}/members`); setGroupMembers(r.data || []); }
    catch (e) { console.error(e); }
    finally { setGroupMembersLoading(false); }
  };

  const selectReport = async (item: any, type: 'fundraiser' | 'form') => {
    setSelectedReport({ ...item, type }); setReportData(null);
    try {
      const path = type === 'fundraiser' ? `/fundraisers/${item.id}/report` : `/forms/${item.id}/report`;
      const r = await api.get(path); setReportData(r.data);
    } catch (e) { console.error(e); }
  };

  const sendReminder = async () => {
    setLoading(true);
    try {
      const path = selectedReport.type === 'fundraiser'
        ? `/fundraisers/${selectedReport.id}/remind`
        : `/forms/${selectedReport.id}/remind`;
      await api.post(path); alert(t.reminder_sent);
    } catch { setError('Failed'); }
    finally { setLoading(false); }
  };

  const toggleReportStatus = async () => {
    if (!selectedReport) return;
    const isActive = (reportData?.status || selectedReport.status) === 'active';
    const newStatus = isActive ? 'closed' : 'active';
    setLoading(true);
    try {
      const path = selectedReport.type === 'fundraiser'
        ? `/fundraisers/${selectedReport.id}`
        : `/forms/${selectedReport.id}`;
      await api.patch(path, { status: newStatus });
      setReportData((prev: any) => ({ ...prev, status: newStatus }));
      setSelectedReport((prev: any) => ({ ...prev, status: newStatus }));
      await fetchAll();
    } catch { setError('Error'); }
    finally { setLoading(false); }
  };

  const openMemberEdit = (member: any) => {
    setEditingMember(member);
    const parts = (member.name || '').split(' ');
    setEditFirstName(parts[0] || '');
    setEditLastName(parts.slice(1).join(' ') || '');
  };

  const saveMember = async () => {
    if (!editingMember || !selectedGroup) return;
    setLoading(true);
    try {
      await api.patch(`/classrooms/${selectedGroup.id}/members/${editingMember.id}`, {
        first_name: editFirstName,
        last_name: editLastName,
      });
      setEditingMember(null);
      // Refresh members
      const r = await api.get(`/classrooms/${selectedGroup.id}/members`);
      setGroupMembers(r.data || []);
    } catch { setError('Error saving'); }
    finally { setLoading(false); }
  };

  // ── Create handlers ───────────────────────────────────────────────────────
  const createFundraiser = async () => {
    if (!fName.trim()) return;
    setLoading(true);
    try {
      const selectedAcc = accounts.find(a => String(a.id) === fAccountId);
      await api.post('/fundraisers', {
        name: fName,
        friendly_name: fFriendlyName || fName,
        account_number: selectedAcc?.details || fAccountId,
        type: fType,
        fixed_amount: fType === 'fixed' ? fAmount : null,
        audience_classroom_ids: fAudience,
        products: fType === 'variable' ? fProducts.filter(p => p.name) : null,
      });
      setShowNewFundraiser(false);
      setFName(''); setFFriendlyName(''); setFAmount(''); setFAudience([]); setFProducts([{ name: '', price: '' }]);
      await fetchAll();
      goTab('fundraisers');
    } catch { setError('Error creating'); }
    finally { setLoading(false); }
  };

  const createForm = async () => {
    if (!fbTitle.trim() || fbQuestions.filter(q => q.text).length === 0) return;
    setLoading(true);
    try {
      await api.post('/forms', {
        title: fbTitle, description: fbDesc, purpose: fbPurpose,
        audience_classroom_ids: fbAudience,
        questions: fbQuestions.filter(q => q.text).map((q, i) => ({ ...q, order: i })),
      });
      setShowNewForm(false);
      setFbTitle(''); setFbDesc(''); setFbAudience([]);
      setFbQuestions([{ text: '', type: 'yes_no', required: true, options: [] }]);
      await fetchAll();
      goTab('forms');
    } catch { setError('Error creating'); }
    finally { setLoading(false); }
  };

  const createEvent = async () => {
    if (!evTitle.trim()) return;
    setLoading(true);
    try {
      await api.post('/events', { title: evTitle, description: evDesc, date: evDate, location: evLocation });
      setShowNewEvent(false);
      setEvTitle(''); setEvDesc(''); setEvDate(''); setEvLocation('');
      await fetchAll();
      goTab('events');
    } catch { setError('Error creating'); }
    finally { setLoading(false); }
  };

  const addAccount = async () => {
    if (!accLabel.trim() || !accDetails.trim()) return;
    setLoading(true);
    try {
      await api.post('/auth/accounts', { label: accLabel, acc_type: accType, details: accDetails, is_default: accDefault });
      setShowAddAccount(false);
      setAccLabel(''); setAccDetails(''); setAccDefault(false);
      await fetchAll();
    } catch { setError('Error'); }
    finally { setLoading(false); }
  };

  const deleteAccount = async (id: number) => {
    if (!confirm(t.confirm_delete)) return;
    try { await api.delete(`/auth/accounts/${id}`); await fetchAll(); }
    catch { setError('Error'); }
  };

  const sendChat = async () => {
    if (!chatInput.trim()) return;
    const msg = chatInput; setChatInput('');
    setChatMessages(prev => [...prev, { role: 'user', text: msg }]);
    try {
      const r = await api.post('/assistant/ask', { text: msg });
      setChatMessages(prev => [...prev, { role: 'bot', text: r.data.answer || r.data.response || '...' }]);
    } catch {
      setChatMessages(prev => [...prev, { role: 'bot', text: '❌ Error' }]);
    }
  };

  // ── Audience toggle helper ────────────────────────────────────────────────
  const toggleAudience = (id: number, current: number[], setter: (v: number[]) => void) => {
    setter(current.includes(id) ? current.filter(x => x !== id) : [...current, id]);
  };

  // ── Auth screen ───────────────────────────────────────────────────────────
  if (step !== 'dashboard') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F8FAFC] p-6 text-center">
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
          className="w-full max-w-sm bg-white rounded-[3rem] p-10 shadow-2xl shadow-slate-200 border border-slate-50">
          <div className="w-20 h-20 bg-indigo-600 rounded-3xl flex items-center justify-center mb-8 shadow-2xl shadow-indigo-200 mx-auto -rotate-6">
            <Lock className="text-white w-10 h-10" />
          </div>
          <h1 className="text-3xl font-black tracking-tighter text-slate-800">EduLink</h1>
          <p className="text-slate-400 text-xs font-bold uppercase tracking-[0.2em] mb-10">{t.welcome}</p>
          {error && <p className="text-red-500 text-xs mb-4 bg-red-50 py-2 rounded-xl">{error}</p>}

          <AnimatePresence mode="wait">
            {step === 'phone' && (
              <motion.form key="phone-step" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }}
                onSubmit={handleRequestOTP} className="space-y-4">
                <input type="tel" placeholder={t.phone_placeholder} value={phone} onChange={e => setPhone(e.target.value)}
                  className="w-full px-6 py-5 bg-slate-50 border-none rounded-2xl font-bold outline-none focus:ring-2 focus:ring-indigo-500/20" required />
                <button type="submit" disabled={loading}
                  className="w-full py-5 bg-indigo-600 text-white rounded-2xl font-black shadow-xl shadow-indigo-200 active:scale-95 transition-transform">
                  {loading ? '...' : t.get_code}
                </button>
                <p className="text-[10px] text-slate-400">
                  Dev: <button type="button" className="text-indigo-500 font-black" onClick={() => { setPhone('123456'); setCode('000000'); setStep('code'); }}>usar 123456</button>
                </p>
              </motion.form>
            )}

            {step === 'code' && (
              <motion.form key="code-step" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }}
                onSubmit={handleLogin} className="space-y-4">
                <p className="text-sm text-slate-500 mb-2">
                  {phone === '123456' ? '🔧 Modo dev — código:' : 'Código enviado a'} <span className="font-black text-slate-800">{phone === '123456' ? '000000' : `+${phone}`}</span>
                </p>
                <input type="text" placeholder={t.code_placeholder} value={code} onChange={e => setCode(e.target.value)}
                  className="w-full px-6 py-5 bg-slate-50 border-none rounded-2xl font-bold outline-none focus:ring-2 focus:ring-indigo-500/20 text-center tracking-[0.5em] text-2xl"
                  maxLength={6} required autoFocus />
                <button type="submit" disabled={loading}
                  className="w-full py-5 bg-indigo-600 text-white rounded-2xl font-black shadow-xl shadow-indigo-200 active:scale-95 transition-transform">
                  {loading ? '...' : t.verify_code}
                </button>
                <button type="button" onClick={() => { setStep('phone'); setCode(''); setError(''); }}
                  className="text-[10px] text-slate-400 font-black uppercase tracking-wider">← {t.back}</button>
              </motion.form>
            )}
          </AnimatePresence>
        </motion.div>
      </div>
    );
  }

  // ── Dashboard ─────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 font-sans pb-40">
      {/* Error toast */}
      <AnimatePresence>
        {error && (
          <motion.div initial={{ opacity: 0, y: -20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }}
            className="fixed top-4 left-4 right-4 z-[100] bg-red-500 text-white px-5 py-3 rounded-2xl text-sm font-black shadow-xl flex justify-between items-center">
            <span>{error}</span>
            <button onClick={() => setError('')}><X className="w-4 h-4" /></button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Header */}
      <header className="bg-white/80 backdrop-blur-md sticky top-0 z-30 px-6 py-4 flex justify-between items-center border-b border-slate-100">
        <div onClick={() => goTab('home')} className="cursor-pointer">
          <h1 className="text-xl font-black tracking-tight text-indigo-600">EduLink</h1>
          <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest leading-none mt-1">{adminPhone || t.welcome}</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setLang(lang === 'en' ? 'es' : 'en')}
            className="w-8 h-8 flex items-center justify-center bg-slate-100 rounded-full text-[10px] font-black">
            {lang.toUpperCase()}
          </button>
          <button onClick={() => { localStorage.removeItem('admin_token'); setStep('phone'); }}
            className="w-8 h-8 flex items-center justify-center bg-slate-100 rounded-full text-slate-400">
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </header>

      <main className="p-6">
        <AnimatePresence mode="wait">

          {/* Home */}
          {!selectedReport && !selectedGroup && activeTab === 'home' && (
            <motion.div key="home" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-8">
              <div className="grid grid-cols-2 gap-4">
                <DashCard title={t.fundraisers} icon={<Activity />} color="bg-emerald-500"
                  count={fundraisers.length} onClick={() => goTab('fundraisers')} />
                <DashCard title={t.forms} icon={<LayoutList />} color="bg-indigo-500"
                  count={forms.length} onClick={() => goTab('forms')} />
                <DashCard title={t.groups} icon={<Users />} color="bg-blue-500"
                  count={classrooms.length} onClick={() => goTab('groups')} />
                <DashCard title={t.events} icon={<Calendar />} color="bg-amber-500"
                  count={events.length} onClick={() => goTab('events')} />
              </div>

              {/* Assistant */}
              <section className="bg-white rounded-[2.5rem] p-6 shadow-sm border border-slate-100">
                <div className="flex items-center gap-3 mb-4">
                  <div className="bg-violet-600 p-2.5 rounded-2xl shadow-lg shadow-violet-200">
                    <MessageSquare className="w-5 h-5 text-white" />
                  </div>
                  <h2 className="font-extrabold text-lg">{t.assistant}</h2>
                </div>
                {chatMessages.length > 0 && (
                  <div className="space-y-3 mb-4 max-h-48 overflow-y-auto">
                    {chatMessages.map((m, i) => (
                      <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div className={`text-xs px-4 py-2 rounded-2xl max-w-[80%] ${m.role === 'user' ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-700'}`}>
                          {m.text}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                <div className="relative">
                  <input type="text" placeholder={t.assistant_placeholder} value={chatInput}
                    onChange={e => setChatInput(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && sendChat()}
                    className="w-full pl-5 pr-14 py-4 bg-slate-100 border-none rounded-2xl text-sm outline-none" />
                  <button onClick={sendChat} className="absolute right-2 top-1/2 -translate-y-1/2 bg-violet-600 text-white p-2.5 rounded-xl">
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </section>
            </motion.div>
          )}

          {/* Fundraisers list */}
          {!selectedReport && activeTab === 'fundraisers' && (
            <ListView key="fund-list" title={t.fundraisers} items={fundraisers} type="activity"
              noItemsLabel={t.no_items} loading={dataLoading} onSelect={(f: any) => selectReport(f, 'fundraiser')}
              showArchived={showArchivedFunds}
              onToggleArchived={() => {
                const next = !showArchivedFunds;
                setShowArchivedFunds(next);
                fetchAll({ archivedFunds: next });
              }} />
          )}

          {/* Forms list */}
          {!selectedReport && activeTab === 'forms' && (
            <ListView key="form-list" title={t.forms} items={forms} type="form"
              noItemsLabel={t.no_items} loading={dataLoading} onSelect={(f: any) => selectReport(f, 'form')}
              showArchived={showArchivedForms}
              onToggleArchived={() => {
                const next = !showArchivedForms;
                setShowArchivedForms(next);
                fetchAll({ archivedForms: next });
              }} />
          )}

          {/* Events list */}
          {activeTab === 'events' && (
            <motion.div key="events" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="space-y-6">
              <h2 className="text-2xl font-black tracking-tight">{t.events}</h2>
              <div className="space-y-4">
                {events.length === 0 ? (
                  <div className="text-center text-slate-400 py-12">{t.no_items}</div>
                ) : events.map((ev: any, i: number) => (
                  <div key={i} className="bg-white p-5 rounded-[2rem] shadow-sm border border-slate-100">
                    <div className="flex items-center gap-4">
                      <div className="w-12 h-12 bg-amber-500 rounded-2xl flex items-center justify-center text-white flex-shrink-0">
                        <Calendar className="w-5 h-5" />
                      </div>
                      <div className="min-w-0">
                        <h4 className="font-black text-slate-800 truncate">{ev.title}</h4>
                        <p className="text-[10px] font-bold text-slate-400">{ev.date ? new Date(ev.date).toLocaleDateString() : ''} {ev.location && `· ${ev.location}`}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </motion.div>
          )}

          {/* Groups list */}
          {!selectedGroup && activeTab === 'groups' && (
            <ListView key="group-list" title={t.groups} items={classrooms} type="group"
              noItemsLabel={t.no_items} loading={dataLoading} onSelect={(g: any) => selectGroup(g)} />
          )}

          {/* Group detail */}
          {selectedGroup && activeTab === 'groups' && (
            <motion.div key="group-detail" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="space-y-6">
              <button onClick={() => { setSelectedGroup(null); setGroupMembers([]); }}
                className="flex items-center gap-2 text-indigo-600 font-black text-xs uppercase tracking-tighter">
                <ChevronLeft className="w-4 h-4" /> {t.back}
              </button>
              <div className="bg-blue-600 p-6 rounded-[3rem] text-white shadow-xl">
                <h2 className="text-2xl font-black tracking-tight">{selectedGroup.name}</h2>
                <p className="text-white/60 text-xs mt-1 font-bold uppercase tracking-widest">{t.members}</p>
              </div>
              <div className="space-y-3">
                {groupMembersLoading ? (
                  <div className="text-center text-slate-400 py-8">{t.loading}</div>
                ) : groupMembers.length === 0 ? (
                  <div className="text-center text-slate-400 py-8">{t.no_items}</div>
                ) : groupMembers.map((m: any, i: number) => (
                  <div key={i} className="bg-white p-5 rounded-[2rem] shadow-sm border border-slate-100">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 bg-blue-50 rounded-2xl flex items-center justify-center flex-shrink-0">
                        <User className="w-5 h-5 text-blue-500" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="font-black text-slate-800 text-sm truncate">{m.name}</div>
                        <div className="text-[10px] font-bold text-slate-400">{m.jid?.replace('@c.us', '').replace('@lid', '')}</div>
                      </div>
                      <button onClick={() => openMemberEdit(m)} className="text-slate-300 hover:text-indigo-500 transition-colors flex-shrink-0 p-1">
                        <Edit2 className="w-4 h-4" />
                      </button>
                    </div>
                    {m.students?.length > 0 && (
                      <div className="mt-3 space-y-2 border-t border-slate-50 pt-3">
                        {m.students.map((s: any, j: number) => (
                          <div key={j} className="flex items-center justify-between ml-13">
                            <div className="flex items-center gap-2">
                              <div className="w-7 h-7 bg-slate-100 rounded-full flex items-center justify-center text-xs">👶</div>
                              <span className="text-xs font-bold text-slate-600">{s.name}</span>
                            </div>
                            {s.is_primary_payer && (
                              <span className="text-[8px] font-black uppercase bg-emerald-50 text-emerald-600 px-2 py-0.5 rounded-full">{t.primary_payer}</span>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </motion.div>
          )}

          {/* Settings */}
          {activeTab === 'settings' && (
            <motion.div key="settings" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-8">
              <h2 className="text-2xl font-black tracking-tight">{t.settings}</h2>

              <section className="space-y-4">
                <h3 className="section-label flex items-center gap-2"><CreditCard className="w-3 h-3" /> {t.accounts}</h3>
                <div className="space-y-3">
                  {accounts.length === 0 && <p className="text-slate-400 text-sm text-center py-4">{t.no_items}</p>}
                  {accounts.map((acc: any, i: number) => (
                    <div key={i} className="bg-white p-5 rounded-3xl border border-slate-100 flex justify-between items-center">
                      <div>
                        <div className="font-black text-xs text-slate-800">{acc.label}</div>
                        <div className="text-[10px] font-bold text-slate-400">{acc.details}</div>
                      </div>
                      <div className="flex items-center gap-2">
                        {acc.is_default && <span className="bg-indigo-50 text-indigo-600 text-[8px] font-black px-2 py-0.5 rounded-full uppercase">Default</span>}
                        <button onClick={() => deleteAccount(acc.id)} className="text-slate-300 hover:text-red-400 transition-colors">
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  ))}
                  <button onClick={() => setShowAddAccount(true)}
                    className="w-full py-4 bg-slate-100 text-slate-400 rounded-3xl text-[10px] font-black uppercase tracking-widest border-2 border-dashed border-slate-200">
                    + {t.add_account}
                  </button>
                </div>
              </section>

              <section className="space-y-4">
                <h3 className="section-label flex items-center gap-2"><Globe className="w-3 h-3" /> {t.edulink_setup}</h3>
                <div className="bg-white p-6 rounded-[2.5rem] border border-slate-100 space-y-4 shadow-sm">
                  <FlatInput label={t.portal_user} icon={<User className="w-4 h-4" />} />
                  <FlatInput label={t.portal_pass} icon={<Key className="w-4 h-4" />} type="password" />
                  <button className="w-full py-4 bg-indigo-600 text-white rounded-2xl font-black text-xs uppercase shadow-lg shadow-indigo-100">
                    {t.save}
                  </button>
                </div>
              </section>
            </motion.div>
          )}

          {/* Report detail */}
          {selectedReport && (
            <motion.div key="report" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="space-y-6">
              <button onClick={() => { setSelectedReport(null); setReportData(null); }}
                className="flex items-center gap-2 text-indigo-600 font-black text-xs uppercase tracking-tighter">
                <ChevronLeft className="w-4 h-4" /> {t.back}
              </button>
              <div className={`${selectedReport.type === 'fundraiser' ? 'bg-emerald-600' : 'bg-indigo-600'} p-8 rounded-[3rem] text-white shadow-xl`}>
                <div className="flex justify-between items-start">
                  <div>
                    <h2 className="text-3xl font-black tracking-tighter leading-none">{selectedReport.name || selectedReport.title}</h2>
                    <p className="mt-2 text-white/70 font-bold uppercase text-[10px] tracking-widest">{selectedReport.status}</p>
                  </div>
                  <span className="bg-white/20 px-3 py-1 rounded-full text-[10px] font-black uppercase backdrop-blur-md">{selectedReport.type}</span>
                </div>
                <div className="mt-8 flex gap-3">
                  <button onClick={sendReminder} disabled={loading}
                    className="flex-1 bg-white text-slate-900 py-3 rounded-2xl text-xs font-black uppercase flex items-center justify-center gap-2 shadow-lg active:scale-95 transition-transform">
                    <Bell className="w-3 h-3" /> {t.remind}
                  </button>
                  <button onClick={toggleReportStatus} disabled={loading}
                    className="bg-white/20 px-4 py-3 rounded-2xl text-white backdrop-blur-md text-xs font-black uppercase">
                    {(reportData?.status || selectedReport.status) === 'active' ? t.close : t.reopen}
                  </button>
                </div>
              </div>

              <div className="bg-white rounded-[2.5rem] p-6 shadow-sm border border-slate-100">
                <h3 className="text-xl font-black tracking-tight mb-6 flex items-center gap-3">
                  {selectedReport.type === 'fundraiser' ? t.payments : t.submissions}
                  <span className="text-xs bg-slate-100 text-slate-400 px-3 py-1 rounded-full">LIVE</span>
                </h3>
                <div className="space-y-4">
                  {reportData == null ? (
                    <div className="text-center text-slate-400 py-4">{t.loading}</div>
                  ) : (reportData?.payments || reportData?.submissions || []).length === 0 ? (
                    <div className="text-center text-slate-400">{t.no_items}</div>
                  ) : (reportData?.payments || reportData?.submissions).map((s: any, i: number) => (
                    <div key={i} className="flex justify-between items-center p-4 bg-slate-50/50 rounded-2xl border border-slate-50">
                      <div className="min-w-0">
                        <div className="font-black text-slate-800 text-xs truncate">{s.parent}</div>
                        <div className="text-[10px] text-slate-400 font-bold">{s.child || s.student}</div>
                      </div>
                      <div className="text-right flex-shrink-0">
                        {s.amount && <div className="text-xs font-black text-slate-700">${s.amount}</div>}
                        <span className={`text-[10px] font-black uppercase px-2 py-0.5 rounded-full ${s.status === 'confirmed' || s.status === 'submitted' ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'}`}>
                          {s.status}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </motion.div>
          )}

        </AnimatePresence>
      </main>

      {/* Bottom nav */}
      <nav className="fixed bottom-6 left-4 right-4 z-40">
        {/* Create FAB */}
        <div className="flex justify-center mb-3">
          <button onClick={() => setShowCreateMenu(true)}
            className="bg-indigo-600 text-white px-6 py-3 rounded-full shadow-xl shadow-indigo-300 flex items-center gap-2 active:scale-90 transition-transform">
            <Plus className="w-5 h-5" />
            <span className="text-xs font-black uppercase tracking-widest">{t.create}</span>
          </button>
        </div>
        {/* Tab bar */}
        <div className="bg-white/90 backdrop-blur-xl border border-white/20 rounded-[2rem] h-16 flex items-center gap-1 px-2 shadow-2xl shadow-slate-200 overflow-x-auto">
          <NavBtn icon={<Home />} label="Inicio" active={activeTab === 'home'} onClick={() => goTab('home')} />
          <NavBtn icon={<Activity />} label={t.fundraisers} active={activeTab === 'fundraisers'} onClick={() => goTab('fundraisers')} />
          <NavBtn icon={<LayoutList />} label={t.forms} active={activeTab === 'forms'} onClick={() => goTab('forms')} />
          <NavBtn icon={<Users />} label={t.groups} active={activeTab === 'groups'} onClick={() => goTab('groups')} />
          <NavBtn icon={<Calendar />} label={t.events} active={activeTab === 'events'} onClick={() => goTab('events')} />
          <NavBtn icon={<Settings />} label={t.settings} active={activeTab === 'settings'} onClick={() => goTab('settings')} />
        </div>
      </nav>

      {/* Create menu */}
      <AnimatePresence>
        {showCreateMenu && (
          <Backdrop onClose={() => setShowCreateMenu(false)}>
            <div className="grid grid-cols-3 gap-6 p-10 pb-14">
              <CreateOpt icon={<Activity />} label={t.activity} color="text-emerald-600 bg-emerald-50"
                onClick={() => { setShowCreateMenu(false); setShowNewFundraiser(true); }} />
              <CreateOpt icon={<FileText />} label={t.form} color="text-indigo-600 bg-indigo-50"
                onClick={() => { setShowCreateMenu(false); setShowNewForm(true); }} />
              <CreateOpt icon={<CalendarPlus />} label={t.event} color="text-amber-600 bg-amber-50"
                onClick={() => { setShowCreateMenu(false); setShowNewEvent(true); }} />
            </div>
          </Backdrop>
        )}
      </AnimatePresence>

      {/* ── New Fundraiser Modal ──────────────────────────────────────────── */}
      <AnimatePresence>
        {showNewFundraiser && (
          <Modal title={t.new_fundraiser} onClose={() => setShowNewFundraiser(false)}>
            <div className="space-y-5">
              <FlatInput label={t.fund_name} icon={<Tag className="w-4 h-4" />}
                value={fName} onChange={setFName} />
              <FlatInput label="Nombre amigable (para el bot)" icon={<MessageSquare className="w-4 h-4" />}
                value={fFriendlyName} onChange={setFFriendlyName} />

              {/* Account */}
              <div className="space-y-2">
                <label className="label-sm">{t.fund_account}</label>
                {accounts.length === 0 ? (
                  <p className="text-xs text-amber-600 bg-amber-50 px-4 py-3 rounded-2xl">
                    Agrega una cuenta en Configuración primero.
                  </p>
                ) : (
                  <select value={fAccountId} onChange={e => setFAccountId(e.target.value)}
                    className="w-full px-4 py-4 bg-slate-50 border-none rounded-2xl font-bold appearance-none outline-none text-sm">
                    {accounts.map((acc: any) => (
                      <option key={acc.id} value={String(acc.id)}>{acc.label} · {acc.details}</option>
                    ))}
                  </select>
                )}
              </div>

              {/* Type */}
              <div className="space-y-2">
                <label className="label-sm">{t.fund_type}</label>
                <div className="grid grid-cols-2 gap-2">
                  {(['fixed', 'variable'] as const).map(tp => (
                    <button key={tp} onClick={() => setFType(tp)}
                      className={`py-3 rounded-2xl text-xs font-black uppercase transition-all ${fType === tp ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-100' : 'bg-slate-100 text-slate-400'}`}>
                      {tp === 'fixed' ? t.fixed : t.variable}
                    </button>
                  ))}
                </div>
              </div>

              {/* Fixed amount */}
              {fType === 'fixed' && (
                <FlatInput label={t.fund_amount} icon={<DollarSign className="w-4 h-4" />}
                  value={fAmount} onChange={setFAmount} type="number" />
              )}

              {/* Products */}
              {fType === 'variable' && (
                <div className="space-y-2">
                  <label className="label-sm">{t.add_product}</label>
                  <div className="space-y-2">
                    {fProducts.map((p, i) => (
                      <div key={i} className="flex gap-2">
                        <input placeholder={t.product_name} value={p.name}
                          onChange={e => { const a = [...fProducts]; a[i].name = e.target.value; setFProducts(a); }}
                          className="flex-1 px-3 py-3 bg-slate-50 rounded-xl font-bold text-sm outline-none border-none" />
                        <input placeholder="$" value={p.price} type="number"
                          onChange={e => { const a = [...fProducts]; a[i].price = e.target.value; setFProducts(a); }}
                          className="w-20 px-3 py-3 bg-slate-50 rounded-xl font-bold text-sm outline-none border-none" />
                        {i > 0 && (
                          <button onClick={() => setFProducts(fProducts.filter((_, j) => j !== i))}
                            className="text-slate-300"><X className="w-4 h-4" /></button>
                        )}
                      </div>
                    ))}
                  </div>
                  <button onClick={() => setFProducts([...fProducts, { name: '', price: '' }])}
                    className="text-indigo-600 text-xs font-black uppercase">+ {t.add_product}</button>
                </div>
              )}

              {/* Audience */}
              <AudiencePicker label={t.audience} classrooms={classrooms} selected={fAudience}
                onToggle={(id: number) => toggleAudience(id, fAudience, setFAudience)} />

              <button onClick={createFundraiser} disabled={loading || !fName.trim()}
                className="w-full py-5 bg-indigo-600 text-white rounded-[1.5rem] font-black shadow-xl disabled:opacity-50">
                {loading ? '...' : t.create}
              </button>
            </div>
          </Modal>
        )}
      </AnimatePresence>

      {/* ── New Form Modal ────────────────────────────────────────────────── */}
      <AnimatePresence>
        {showNewForm && (
          <Modal title={t.new_form} onClose={() => setShowNewForm(false)}>
            <div className="space-y-5">
              <FlatInput label={t.form_title} icon={<FileText className="w-4 h-4" />}
                value={fbTitle} onChange={setFbTitle} />
              <FlatInput label={t.form_description} icon={<FileText className="w-4 h-4" />}
                value={fbDesc} onChange={setFbDesc} />

              {/* Purpose */}
              <div className="space-y-2">
                <label className="label-sm">{t.form_purpose}</label>
                <select value={fbPurpose} onChange={e => setFbPurpose(e.target.value)}
                  className="w-full px-4 py-4 bg-slate-50 rounded-2xl font-bold text-sm outline-none border-none appearance-none">
                  {FORM_PURPOSES.map(p => (
                    <option key={p} value={p}>{(t as any)[p] || p}</option>
                  ))}
                </select>
              </div>

              {/* Questions */}
              <div className="space-y-3">
                <label className="label-sm">{t.question}</label>
                {fbQuestions.map((q, i) => (
                  <div key={i} className="bg-slate-50 p-4 rounded-2xl space-y-3">
                    <div className="flex gap-2">
                      <input placeholder={`${t.question} ${i + 1}`} value={q.text}
                        onChange={e => { const a = [...fbQuestions]; a[i].text = e.target.value; setFbQuestions(a); }}
                        className="flex-1 px-3 py-2 bg-white rounded-xl font-bold text-sm outline-none border border-slate-100" />
                      {fbQuestions.length > 1 && (
                        <button onClick={() => setFbQuestions(fbQuestions.filter((_, j) => j !== i))}
                          className="text-slate-300"><X className="w-4 h-4" /></button>
                      )}
                    </div>
                    <div className="flex gap-2">
                      <select value={q.type}
                        onChange={e => { const a = [...fbQuestions]; a[i].type = e.target.value; setFbQuestions(a); }}
                        className="flex-1 px-3 py-2 bg-white rounded-xl font-bold text-xs outline-none border border-slate-100 appearance-none">
                        {QUESTION_TYPES.map(qt => <option key={qt} value={qt}>{(t as any)[qt] || qt}</option>)}
                      </select>
                      <button onClick={() => { const a = [...fbQuestions]; a[i].required = !a[i].required; setFbQuestions(a); }}
                        className={`px-3 py-2 rounded-xl text-[10px] font-black uppercase ${q.required ? 'bg-indigo-600 text-white' : 'bg-white text-slate-400 border border-slate-100'}`}>
                        {t.required}
                      </button>
                    </div>
                    {(q.type === 'single_choice' || q.type === 'multi_choice') && (
                      <input placeholder={t.options} value={q.options.join(', ')}
                        onChange={e => { const a = [...fbQuestions]; a[i].options = e.target.value.split(',').map(s => s.trim()); setFbQuestions(a); }}
                        className="w-full px-3 py-2 bg-white rounded-xl font-bold text-xs outline-none border border-slate-100" />
                    )}
                  </div>
                ))}
                <button onClick={() => setFbQuestions([...fbQuestions, { text: '', type: 'yes_no', required: true, options: [] }])}
                  className="text-indigo-600 text-xs font-black uppercase">+ {t.add_question}</button>
              </div>

              {/* Audience */}
              <AudiencePicker label={t.audience} classrooms={classrooms} selected={fbAudience}
                onToggle={(id: number) => toggleAudience(id, fbAudience, setFbAudience)} />

              <button onClick={createForm} disabled={loading || !fbTitle.trim()}
                className="w-full py-5 bg-indigo-600 text-white rounded-[1.5rem] font-black shadow-xl disabled:opacity-50">
                {loading ? '...' : t.create}
              </button>
            </div>
          </Modal>
        )}
      </AnimatePresence>

      {/* ── New Event Modal ───────────────────────────────────────────────── */}
      <AnimatePresence>
        {showNewEvent && (
          <Modal title={t.new_event} onClose={() => setShowNewEvent(false)}>
            <div className="space-y-5">
              <FlatInput label={t.event_title} icon={<Calendar className="w-4 h-4" />}
                value={evTitle} onChange={setEvTitle} />
              <FlatInput label={t.event_description} icon={<FileText className="w-4 h-4" />}
                value={evDesc} onChange={setEvDesc} />
              <FlatInput label={t.event_date} icon={<Calendar className="w-4 h-4" />}
                value={evDate} onChange={setEvDate} type="datetime-local" />
              <FlatInput label={t.event_location} icon={<Globe className="w-4 h-4" />}
                value={evLocation} onChange={setEvLocation} />
              <button onClick={createEvent} disabled={loading || !evTitle.trim()}
                className="w-full py-5 bg-indigo-600 text-white rounded-[1.5rem] font-black shadow-xl disabled:opacity-50">
                {loading ? '...' : t.create}
              </button>
            </div>
          </Modal>
        )}
      </AnimatePresence>

      {/* ── Add Account Modal ─────────────────────────────────────────────── */}
      <AnimatePresence>
        {showAddAccount && (
          <Modal title={t.add_account} onClose={() => setShowAddAccount(false)}>
            <div className="space-y-5">
              <FlatInput label={t.account_label} icon={<Tag className="w-4 h-4" />}
                value={accLabel} onChange={setAccLabel} />
              <div className="space-y-2">
                <label className="label-sm">{t.account_type}</label>
                <div className="grid grid-cols-2 gap-2">
                  {(['phone', 'bank'] as const).map(tp => (
                    <button key={tp} onClick={() => setAccType(tp)}
                      className={`py-3 rounded-2xl text-xs font-black uppercase ${accType === tp ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-400'}`}>
                      {tp === 'phone' ? t.phone_yappy : t.bank}
                    </button>
                  ))}
                </div>
              </div>
              <FlatInput label={t.account_details} icon={<CreditCard className="w-4 h-4" />}
                value={accDetails} onChange={setAccDetails} />
              <label className="flex items-center gap-3 cursor-pointer">
                <div onClick={() => setAccDefault(!accDefault)}
                  className={`w-12 h-7 rounded-full transition-colors flex items-center px-1 ${accDefault ? 'bg-indigo-600' : 'bg-slate-200'}`}>
                  <div className={`w-5 h-5 bg-white rounded-full shadow transition-transform ${accDefault ? 'translate-x-5' : ''}`} />
                </div>
                <span className="text-xs font-black uppercase text-slate-500">{t.is_default}</span>
              </label>
              <button onClick={addAccount} disabled={loading || !accLabel.trim() || !accDetails.trim()}
                className="w-full py-5 bg-indigo-600 text-white rounded-[1.5rem] font-black shadow-xl disabled:opacity-50">
                {loading ? '...' : t.add_account}
              </button>
            </div>
          </Modal>
        )}
      </AnimatePresence>

      {/* ── Edit Member Modal ─────────────────────────────────────────────── */}
      <AnimatePresence>
        {editingMember && (
          <Modal title={t.edit} onClose={() => setEditingMember(null)}>
            <div className="space-y-5">
              <FlatInput label={t.parent_name + ' (nombre)'} icon={<User className="w-4 h-4" />}
                value={editFirstName} onChange={setEditFirstName} />
              <FlatInput label={t.parent_name + ' (apellido)'} icon={<User className="w-4 h-4" />}
                value={editLastName} onChange={setEditLastName} />
              <button onClick={saveMember} disabled={loading}
                className="w-full py-5 bg-indigo-600 text-white rounded-[1.5rem] font-black shadow-xl disabled:opacity-50">
                {loading ? '...' : t.save}
              </button>
            </div>
          </Modal>
        )}
      </AnimatePresence>
    </div>
  );
}

// ─── Sub-components ────────────────────────────────────────────────────────────

function DashCard({ title, icon, color, count, onClick }: any) {
  return (
    <div onClick={onClick} className="bg-white p-5 rounded-[2rem] shadow-sm border border-slate-100 flex flex-col justify-between active:scale-95 transition-transform cursor-pointer">
      <div className={`${color} w-12 h-12 rounded-2xl flex items-center justify-center text-white mb-4 shadow-lg shadow-slate-100`}>{icon}</div>
      <div>
        <div className="text-xl font-black text-slate-800 leading-none mb-1">{count}</div>
        <h3 className="font-bold text-slate-400 text-[10px] uppercase tracking-wider">{title}</h3>
      </div>
    </div>
  );
}

function NavBtn({ icon, label, active, onClick }: any) {
  return (
    <button onClick={onClick} className={`flex flex-col items-center gap-0.5 px-3 py-2 rounded-2xl transition-all flex-shrink-0 ${active ? 'text-indigo-600 bg-indigo-50' : 'text-slate-300'}`}>
      <div className="w-5 h-5">{icon}</div>
      {label && <span className={`text-[8px] font-black uppercase tracking-tight leading-none ${active ? 'text-indigo-600' : 'text-slate-300'}`}>{label}</span>}
    </button>
  );
}

function CreateOpt({ icon, label, color, onClick }: any) {
  return (
    <div onClick={onClick} className="flex flex-col items-center gap-3 cursor-pointer active:scale-90 transition-transform">
      <div className={`w-16 h-16 rounded-[1.5rem] flex items-center justify-center ${color} shadow-sm border border-black/5`}>{icon}</div>
      <span className="text-[10px] font-black uppercase tracking-widest text-slate-400">{label}</span>
    </div>
  );
}

function ListView({ title, items, type, noItemsLabel, loading, onSelect, showArchived, onToggleArchived }: any) {
  const accentColors: any = { activity: 'bg-emerald-500', form: 'bg-indigo-500', group: 'bg-blue-500' };
  const barColors: any = { activity: 'bg-emerald-400', form: 'bg-indigo-400' };

  return (
    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-black tracking-tight">{title}</h2>
        {onToggleArchived && (
          <button onClick={onToggleArchived}
            className={`text-[10px] font-black uppercase tracking-widest px-3 py-1.5 rounded-full transition-all ${showArchived ? 'bg-slate-700 text-white' : 'bg-slate-100 text-slate-400'}`}>
            {showArchived ? 'Activos' : 'Ver todos'}
          </button>
        )}
      </div>
      <div className="space-y-3">
        {loading ? (
          [0,1,2].map(i => (
            <div key={i} className="bg-white p-5 rounded-[2rem] border border-slate-100 animate-pulse">
              <div className="flex items-center gap-4 mb-3">
                <div className="w-10 h-10 bg-slate-100 rounded-2xl flex-shrink-0" />
                <div className="flex-1 space-y-2">
                  <div className="h-3 bg-slate-100 rounded-full w-2/3" />
                  <div className="h-2 bg-slate-100 rounded-full w-1/3" />
                </div>
              </div>
              <div className="h-1.5 bg-slate-100 rounded-full" />
            </div>
          ))
        ) : items.length === 0 ? (
          <div className="text-center text-slate-400 py-12">{noItemsLabel}</div>
        ) : items.map((item: any, i: number) => {
          const pct = item.completion_pct ?? null;
          const paid = item.paid_count ?? item.submitted_count ?? null;
          const total = item.audience_count ?? null;
          const collected = item.total_collected ?? null;
          const isArchived = item.status === 'archived' || item.status === 'closed';

          return (
            <div key={i} onClick={() => onSelect?.(item)}
              className={`bg-white p-5 rounded-[2rem] shadow-sm border active:scale-[0.98] transition-transform cursor-pointer ${isArchived ? 'border-slate-100 opacity-60' : 'border-slate-100'}`}>
              <div className="flex items-center gap-3 mb-3">
                <div className={`w-10 h-10 rounded-2xl flex items-center justify-center text-white flex-shrink-0 text-[11px] font-black ${accentColors[type] || 'bg-slate-400'}`}>
                  {item.code ? item.code.slice(0, 3) : (type === 'group' ? <Users className="w-4 h-4" /> : null)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h4 className="font-black text-slate-800 truncate text-sm">{item.name || item.title}</h4>
                    {isArchived && <span className="text-[8px] font-black uppercase bg-slate-100 text-slate-400 px-1.5 py-0.5 rounded-full flex-shrink-0">{item.status}</span>}
                  </div>
                  <p className="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">
                    {item.code ? `${item.code} · ` : ''}{item.purpose || item.type || ''}
                  </p>
                </div>
                <div className="text-right flex-shrink-0">
                  {collected !== null && <div className="text-sm font-black text-emerald-600">${collected.toLocaleString()}</div>}
                  {paid !== null && total !== null && (
                    <div className="text-[10px] font-bold text-slate-400">{paid}/{total}</div>
                  )}
                </div>
                <ChevronRight className="w-4 h-4 text-slate-300 flex-shrink-0" />
              </div>
              {pct !== null && (
                <div className="space-y-1">
                  <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full transition-all ${barColors[type] || 'bg-slate-400'}`} style={{ width: `${pct}%` }} />
                  </div>
                  <div className="text-[9px] font-black text-slate-300 text-right">{pct}% completado</div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </motion.div>
  );
}

function Backdrop({ children, onClose }: any) {
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-end justify-center" onClick={onClose}>
      <motion.div initial={{ y: '100%' }} animate={{ y: 0 }} exit={{ y: '100%' }}
        transition={{ type: 'spring', damping: 25 }}
        className="bg-white w-full max-w-lg rounded-t-[3rem]" onClick={e => e.stopPropagation()}>
        {children}
      </motion.div>
    </motion.div>
  );
}

function Modal({ title, children, onClose }: any) {
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-end justify-center" onClick={onClose}>
      <motion.div initial={{ y: '100%' }} animate={{ y: 0 }} exit={{ y: '100%' }}
        transition={{ type: 'spring', damping: 25 }}
        className="bg-white w-full max-w-lg rounded-t-[3rem] p-8 pb-12 overflow-y-auto max-h-[90vh]" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-8">
          <h2 className="text-2xl font-black tracking-tight">{title}</h2>
          <button onClick={onClose} className="bg-slate-100 p-2 rounded-full text-slate-400"><X /></button>
        </div>
        {children}
      </motion.div>
    </motion.div>
  );
}

function FlatInput({ label, icon, value, onChange, type = 'text' }: any) {
  return (
    <div className="space-y-2">
      <label className="label-sm">{label}</label>
      <div className="relative">
        {icon && <div className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-300">{icon}</div>}
        <input type={type} value={value ?? ''} onChange={e => onChange?.(e.target.value)}
          className={`w-full ${icon ? 'pl-12' : 'pl-4'} pr-4 py-4 bg-slate-50 border-none rounded-2xl font-bold focus:ring-2 focus:ring-indigo-500/20 outline-none transition-all text-sm`} />
      </div>
    </div>
  );
}

function AudiencePicker({ label, classrooms, selected, onToggle }: any) {
  return (
    <div className="space-y-2">
      <label className="label-sm">{label}</label>
      <div className="flex flex-wrap gap-2">
        {classrooms.length === 0 && <p className="text-xs text-slate-400">No hay grupos</p>}
        {classrooms.map((c: any) => {
          const on = selected.includes(c.id);
          return (
            <button key={c.id} onClick={() => onToggle(c.id)}
              className={`px-3 py-1.5 rounded-full text-[11px] font-black transition-all ${on ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-500'}`}>
              {c.name}
            </button>
          );
        })}
      </div>
    </div>
  );
}
