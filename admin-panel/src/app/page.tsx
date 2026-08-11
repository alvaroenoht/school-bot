'use client';

import React, { useState, useEffect } from 'react';
import {
  Lock, MessageSquare, Plus, Activity, LayoutList, Users, Calendar,
  ChevronRight, Settings, LogOut, X, Tag, FileText, CalendarPlus,
  ChevronLeft, Filter, Edit2, User, CreditCard, Check, Trash2,
  Bell, Globe, Key, DollarSign, ShoppingBag, CheckSquare, ToggleLeft, Home, Link2, Pencil, Download, Megaphone, Tablet, Copy
} from 'lucide-react';
import { motion, AnimatePresence, useMotionValue, animate } from 'framer-motion';
import api from '@/lib/api';
import { TransparencyPanel } from '@/components/fundraisers/TransparencyPanel';
import { ManualPaymentModal } from '@/components/fundraisers/ManualPaymentModal';
import { PaymentAuditDrawer } from '@/components/fundraisers/PaymentAuditDrawer';

// ─── Types ────────────────────────────────────────────────────────────────────
interface Product { name: string; price: string; }
interface Question { text: string; type: string; required: boolean; options: string[]; }

const QUESTION_TYPES = ['yes_no', 'text', 'single_choice', 'multi_choice', 'number', 'date'];
const FORM_PURPOSES = ['intake', 'survey', 'event_registration', 'volunteer_signup'];

// ─── Translations ─────────────────────────────────────────────────────────────
const TRANSLATIONS = {
  en: {
    welcome: "EduLink Admin", phone_placeholder: "Phone number",
    code_placeholder: "6-digit code", get_code: "Request Code", verify_code: "Login",
    dashboard: "Dashboard", fundraisers: "Fundraisers", forms: "Forms",
    groups: "Groups", events: "Events", assistant: "AI Assistant",
    logout: "Logout", create: "Create", activity: "Fundraiser",
    form: "Form", event: "Event", members: "Group Members",
    parent_name: "Parent Name", student_name: "Student Name",
    primary_payer: "Main Contact", save: "Save", settings: "Settings",
    accounts: "Payment Accounts", edulink_setup: "School Portal (EduLink)",
    remind: "Send Reminders", announce: "Announce to Group", reopen: "Reopen", close: "Close",
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
    reminder_sent: "Reminders Sent!", reminder_disabled: "Direct reminders are off to protect the number — post the code in the group instead.", announce_sent: "Announcement Sent!", assistant_placeholder: "Ask about your groups...",
    new_fundraiser: "New Fundraiser", new_form: "New Form", new_event: "New Event", new_classroom: "New Classroom",
    no_items: "No items yet", loading: "Loading...", send: "Send",
    account_label: "Account Label", account_type: "Type", account_details: "Details",
    add_account: "Add Account", is_default: "Set as Default",
    bank: "Bank Transfer", phone_yappy: "Yappy (Phone)", submissions: "Submissions",
    payments: "Payments", back: "Back", delete: "Delete", edit: "Edit",
    confirm_delete: "Delete?", language: "Language",
    see_all: "See all", show_active: "Active only",
    delegates: "Delegates", add_delegate: "Add Delegate",
    payment_slip: "Payment Slip", order_items: "Items Ordered",
    answers: "Answers",
  },
  es: {
    welcome: "EduLink Admin", phone_placeholder: "Celular",
    code_placeholder: "Código de 6 dígitos", get_code: "Solicitar Código", verify_code: "Entrar",
    dashboard: "Resumen", fundraisers: "Actividades", forms: "Formularios",
    groups: "Grupos", events: "Eventos", assistant: "Asistente IA",
    logout: "Salir", create: "Crear", activity: "Actividad de Pago",
    form: "Formulario", event: "Evento", members: "Miembros",
    parent_name: "Nombre del Padre", student_name: "Nombre del Estudiante",
    primary_payer: "Principal", save: "Guardar", settings: "Configuración",
    accounts: "Cuentas de Pago", edulink_setup: "Portal Escolar (EduLink)",
    remind: "Enviar Recordatorios", announce: "Anunciar al Grupo", reopen: "Reabrir", close: "Cerrar",
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
    reminder_sent: "¡Recordatorios Enviados!", reminder_disabled: "Los recordatorios directos están desactivados para proteger el número — comparte el código en el grupo.", announce_sent: "¡Anuncio Enviado!", assistant_placeholder: "Pregunta sobre tus grupos...",
    new_fundraiser: "Nueva Actividad", new_form: "Nuevo Formulario", new_event: "Nuevo Evento", new_classroom: "Nuevo Salón",
    no_items: "Sin elementos", loading: "Cargando...", send: "Enviar",
    account_label: "Etiqueta", account_type: "Tipo", account_details: "Detalles",
    add_account: "Agregar Cuenta", is_default: "Establecer por Defecto",
    bank: "Transferencia Bancaria", phone_yappy: "Yappy (Teléfono)", submissions: "Respuestas",
    payments: "Pagos", back: "Atrás", delete: "Eliminar", edit: "Editar",
    confirm_delete: "¿Eliminar?", language: "Idioma",
    see_all: "Ver todos", show_active: "Solo activos",
    delegates: "Delegados", add_delegate: "Agregar Delegado",
    payment_slip: "Comprobante", order_items: "Artículos",
    answers: "Respuestas",
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
  const [upcomingEvents, setUpcomingEvents] = useState<any[]>([]);
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
  const [editChildName, setEditChildName] = useState('');
  const [editBirthDate, setEditBirthDate] = useState('');
  const [editParents, setEditParents] = useState<any[]>([]);

  // Modals
  const [showCreateMenu, setShowCreateMenu] = useState(false);
  const [showNewFundraiser, setShowNewFundraiser] = useState(false);
  const [showNewForm, setShowNewForm] = useState(false);
  const [showNewEvent, setShowNewEvent] = useState(false);
  const [showAddAccount, setShowAddAccount] = useState(false);
  const [showNewClassroom, setShowNewClassroom] = useState(false);
  const [newClsName, setNewClsName] = useState('');

  // Group detail
  const [showGroupConfig, setShowGroupConfig] = useState<any>(false);
  const [groupUnidentified, setGroupUnidentified] = useState<any[]>([]);
  const [waUntracked, setWaUntracked] = useState<any[]>([]);
  const [showUnidentified, setShowUnidentified] = useState(false);
  const [showWaUntracked, setShowWaUntracked] = useState(false);
  const [assigningWaContact, setAssigningWaContact] = useState<any>(null);
  const [assignWaChildName, setAssignWaChildName] = useState('');

  // Delegate assignment
  const [showAssignRole, setShowAssignRole] = useState(false);
  const [assignPhone, setAssignPhone] = useState('');
  const [assignRole, setAssignRole] = useState('delegado');
  const [classroomRoles, setClassroomRoles] = useState<any[]>([]);
  const [allRoles, setAllRoles] = useState<any[]>([]);

  // Fundraiser form
  const [fName, setFName] = useState('');
  const [fType, setFType] = useState<'fixed' | 'variable'>('fixed');
  const [fAmount, setFAmount] = useState('');
  const [fAccountId, setFAccountId] = useState('');
  const [fAudience, setFAudience] = useState<number[]>([]);
  const [fProducts, setFProducts] = useState<Product[]>([{ name: '', price: '' }]);
  const [fMode, setFMode] = useState<'campaign' | 'fund'>('campaign');

  // Report sub-view (payments vs transparency for fund-mode fundraisers)
  const [reportSubView, setReportSubView] = useState<'payments' | 'transparency'>('payments');

  // Manual-payment modal + audit drawer
  const [showManualPayment, setShowManualPayment] = useState(false);
  const [auditingPaymentId, setAuditingPaymentId] = useState<number | null>(null);

  // Fundraiser edit
  const [editingFundraiser, setEditingFundraiser] = useState<any>(null);
  const [editName, setEditName] = useState('');
  const [editAudience, setEditAudience] = useState<number[]>([]);
  const [editFixedAmount, setEditFixedAmount] = useState('');
  const [editProducts, setEditProducts] = useState<Product[]>([]);
  const [editAccount, setEditAccount] = useState('');

  // Form edit
  const [editingForm, setEditingForm] = useState<any>(null);
  const [editFormTitle, setEditFormTitle] = useState('');
  const [editFormDesc, setEditFormDesc] = useState('');
  const [editFormAudience, setEditFormAudience] = useState<number[]>([]);

  // Contact assignment
  const [assigningContact, setAssigningContact] = useState<any>(null);
  const [assignChildName, setAssignChildName] = useState('');

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
  const [evType, setEvType] = useState<'general' | 'holiday' | 'exam'>('general');
  const [evAudience, setEvAudience] = useState<number[]>([]);

  // Account form
  const [accLabel, setAccLabel] = useState('');
  const [accType, setAccType] = useState('phone');
  const [accDetails, setAccDetails] = useState('');
  const [accDefault, setAccDefault] = useState(false);

  // Seduca creds
  const [seducaUser, setSeducaUser] = useState('');
  const [seducaPass, setSeducaPass] = useState('');
  const [seducaGroups, setSeducaGroups] = useState<any[]>([]);
  const [seducaSaving, setSeducaSaving] = useState(false);
  const [seducaHasCreds, setSeducaHasCreds] = useState(false);
  const [seducaCurrentUser, setSeducaCurrentUser] = useState<string | null>(null);

  // WhatsApp group binding modal
  const [showBindModal, setShowBindModal] = useState(false);
  const [bindingClassroomId, setBindingClassroomId] = useState<number | null>(null);
  const [bindInviteLink, setBindInviteLink] = useState('');
  const [wahaGroups, setWahaGroups] = useState<any[]>([]);
  const [wahaGroupsLoading, setWahaGroupsLoading] = useState(false);

  // Seduca link modal (per-group)
  const [showSeducaLinkModal, setShowSeducaLinkModal] = useState(false);
  const [seducaLinkClassroomId, setSeducaLinkClassroomId] = useState<number | null>(null);
  const [seducaLinkTime, setSeducaLinkTime] = useState('07:00');
  const [seducaLinkDay, setSeducaLinkDay] = useState(0);
  const [seducaLinkDms, setSeducaLinkDms] = useState(true);
  const [selectedSeducaGroupId, setSelectedSeducaGroupId] = useState<number | null>(null);
  const [groupSeducaLinks, setGroupSeducaLinks] = useState<Record<number, any>>({});

  // Dashboard iPad tokens
  const [dashTokens, setDashTokens] = useState<any[]>([]);
  const [dashLabel, setDashLabel] = useState('');
  const [dashCreating, setDashCreating] = useState(false);
  const [dashCopiedId, setDashCopiedId] = useState<number | null>(null);

  // Payment group modal
  const [selectedPayerGroup, setSelectedPayerGroup] = useState<any>(null);
  const [showPaymentModal, setShowPaymentModal] = useState(false);

  // Form submission detail modal
  const [selectedSubmission, setSelectedSubmission] = useState<any>(null);
  const [submissionDetail, setSubmissionDetail] = useState<any>(null);

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

  useEffect(() => {
    if (step === 'dashboard') {
      fetchAll();
      fetchSeducaCreds();
      api.get('/classrooms/all-roles').then(r => setAllRoles(r.data || [])).catch(() => {});
    }
  }, [step]);

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
      const [fr, fo, cl, ev, up, ac] = await Promise.all([
        api.get(af ? '/fundraisers?include_closed=true' : '/fundraisers'),
        api.get(afo ? '/forms?include_closed=true' : '/forms'),
        api.get('/classrooms'),
        api.get('/events'),
        api.get('/events/upcoming?days=30'),
        api.get('/auth/accounts'),
      ]);
      setFundraisers(fr.data || []);
      setForms(fo.data || []);
      setClassrooms(cl.data || []);
      setEvents(ev.data || []);
      setUpcomingEvents(up.data || []);
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
    if (tab === 'settings') { fetchSeducaGroups(); fetchDashTokens(); }
  };

  const selectGroup = async (g: any) => {
    setSelectedGroup(g); setGroupMembers([]); setGroupUnidentified([]); setWaUntracked([]); setGroupMembersLoading(true);
    setShowGroupConfig(false); setShowUnidentified(false);
    try {
      const [mr, lr] = await Promise.all([
        api.get(`/classrooms/${g.id}/members`),
        api.get(`/classrooms/${g.id}/seduca-link`).catch(() => ({ data: { linked: false } })),
      ]);
      const data = mr.data || {};
      setGroupMembers(data.members || []);
      setGroupUnidentified(data.unidentified || []);
      setWaUntracked(data.wa_untracked || []);
      if (lr.data.linked) setGroupSeducaLinks(prev => ({ ...prev, [g.id]: lr.data }));
    } catch (e) { console.error(e); }
    finally { setGroupMembersLoading(false); }
  };

  const fetchSeducaCreds = async () => {
    try {
      const r = await api.get('/me/seduca-creds');
      setSeducaHasCreds(r.data.has_creds);
      setSeducaCurrentUser(r.data.username);
      if (r.data.username) setSeducaUser(r.data.username);
    } catch {}
  };

  const fetchSeducaGroups = async () => {
    try {
      const r = await api.get('/seduca/groups');
      setSeducaGroups(r.data || []);
    } catch {}
  };

  // ── Dashboard iPad tokens ─────────────────────────────────────────────────
  const fetchDashTokens = async () => {
    try {
      const r = await api.get('/dashboard/tokens');
      setDashTokens(r.data || []);
    } catch {}
  };

  const createDashToken = async () => {
    setDashCreating(true); setError('');
    try {
      const r = await api.post('/dashboard/tokens', { label: dashLabel || null });
      setDashTokens(prev => [r.data, ...prev]);
      setDashLabel('');
    } catch (e: any) { setError(e?.response?.data?.detail || 'Error al generar el enlace'); }
    finally { setDashCreating(false); }
  };

  const revokeDashToken = async (id: number) => {
    try {
      await api.delete(`/dashboard/tokens/${id}`);
      setDashTokens(prev => prev.filter((tk) => tk.id !== id));
    } catch (e: any) { setError(e?.response?.data?.detail || 'Error'); }
  };

  const copyDashLink = async (tk: any) => {
    const url = window.location.origin + tk.path;
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      window.prompt('Copia el enlace del dashboard:', url);
    }
    setDashCopiedId(tk.id);
    setTimeout(() => setDashCopiedId(null), 1800);
  };

  const saveSeducaCreds = async () => {
    if (!seducaUser || !seducaPass) return;
    setSeducaSaving(true); setError('');
    try {
      const r = await api.put('/me/seduca-creds', { username: seducaUser, password: seducaPass });
      setSeducaHasCreds(true);
      setSeducaCurrentUser(seducaUser);
      setSeducaPass('');
      setSeducaGroups(r.data.groups || []);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Error al guardar credenciales');
    } finally { setSeducaSaving(false); }
  };

  const openBindModal = (classroomId: number) => {
    setBindingClassroomId(classroomId);
    setBindInviteLink('');
    setShowBindModal(true);
  };

  const bindGroupViaLink = async () => {
    if (!bindingClassroomId || !bindInviteLink.trim()) return;
    setWahaGroupsLoading(true);
    try {
      await api.post(`/classrooms/${bindingClassroomId}/bind-group-link`, { invite_link: bindInviteLink.trim() });
      setShowBindModal(false);
      setBindInviteLink('');
      const r = await api.get('/classrooms');
      setClassrooms(r.data || []);
      const updated = (r.data || []).find((c: any) => c.id === bindingClassroomId);
      if (updated) setSelectedGroup(updated);
      setBindingClassroomId(null);
    } catch (e: any) { setError(e?.response?.data?.detail || 'Error al vincular grupo'); }
    finally { setWahaGroupsLoading(false); }
  };

  const unbindGroup = async (classroomId: number) => {
    try {
      await api.post(`/classrooms/${classroomId}/unbind-group`);
      const r = await api.get('/classrooms');
      setClassrooms(r.data || []);
      const updated = (r.data || []).find((c: any) => c.id === classroomId);
      if (updated) setSelectedGroup(updated);
    } catch (e: any) { setError(e?.response?.data?.detail || 'Error al desvincular'); }
  };

  const openSeducaLinkModal = async (classroomId: number) => {
    setSeducaLinkClassroomId(classroomId);
    setShowSeducaLinkModal(true);
    setSelectedSeducaGroupId(null);
    if (seducaGroups.length === 0) await fetchSeducaGroups();
    try {
      const r = await api.get(`/classrooms/${classroomId}/seduca-link`);
      if (r.data.linked) {
        setGroupSeducaLinks(prev => ({ ...prev, [classroomId]: r.data }));
        setSeducaLinkTime(r.data.summary_time || '07:00');
        setSeducaLinkDay(r.data.summary_day ?? 0);
        setSeducaLinkDms(r.data.answer_dms ?? true);
      }
    } catch {}
  };

  const saveSeducaLink = async () => {
    if (!seducaLinkClassroomId || !selectedSeducaGroupId) return;
    try {
      await api.post(`/classrooms/${seducaLinkClassroomId}/seduca-link`, {
        seduca_group_id: selectedSeducaGroupId,
        summary_time: seducaLinkTime,
        summary_day: seducaLinkDay,
        answer_dms: seducaLinkDms,
      });
      const r = await api.get(`/classrooms/${seducaLinkClassroomId}/seduca-link`);
      setGroupSeducaLinks(prev => ({ ...prev, [seducaLinkClassroomId]: r.data }));
      setShowSeducaLinkModal(false);
    } catch (e: any) { setError(e?.response?.data?.detail || 'Error al vincular Seduca'); }
  };

  const unlinkSeduca = async (classroomId: number) => {
    try {
      await api.delete(`/classrooms/${classroomId}/seduca-link`);
      setGroupSeducaLinks(prev => { const next = { ...prev }; delete next[classroomId]; return next; });
    } catch (e: any) { setError(e?.response?.data?.detail || 'Error'); }
  };

  const selectReport = async (item: any, type: 'fundraiser' | 'form') => {
    setSelectedReport({ ...item, type }); setReportData(null);
    setReportSubView('payments');
    try {
      const path = type === 'fundraiser' ? `/fundraisers/${item.id}/report` : `/forms/${item.id}/report`;
      const r = await api.get(path); setReportData(r.data);
    } catch (e) { console.error(e); }
  };

  const refreshReportData = async () => {
    if (!selectedReport || selectedReport.type !== 'fundraiser') return;
    try {
      const r = await api.get(`/fundraisers/${selectedReport.id}/report`);
      setReportData(r.data);
    } catch (e) { console.error(e); }
  };

  const voidPayment = async (paymentId: number) => {
    const reason = prompt('Motivo de la anulación:');
    if (!reason || !reason.trim()) return;
    try {
      await api.post(`/fundraisers/payments/${paymentId}/void`, { reason: reason.trim() });
      await refreshReportData();
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'No se pudo anular el pago');
    }
  };

  const restorePayment = async (paymentId: number) => {
    if (!confirm('¿Restaurar este pago anulado?')) return;
    try {
      await api.post(`/fundraisers/payments/${paymentId}/restore`);
      await refreshReportData();
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'No se pudo restaurar');
    }
  };

  const sendReminder = async () => {
    setLoading(true);
    try {
      const path = selectedReport.type === 'fundraiser'
        ? `/fundraisers/${selectedReport.id}/remind`
        : `/forms/${selectedReport.id}/remind`;
      const res = await api.post(path);
      if (res?.data?.disabled) { alert(res.data.detail || t.reminder_disabled); }
      else { alert(t.reminder_sent); }
    } catch (e: any) { alert(e?.response?.data?.detail || 'Failed'); }
    finally { setLoading(false); }
  };

  const announceFundraiser = async () => {
    setLoading(true);
    try {
      await api.post(`/fundraisers/${selectedReport.id}/announce`);
      alert(t.announce_sent);
    } catch { setError('Failed'); }
    finally { setLoading(false); }
  };

  const downloadExcel = async () => {
    if (!selectedReport) return;
    setLoading(true);
    try {
      const path = selectedReport.type === 'fundraiser'
        ? `/fundraisers/${selectedReport.id}/excel`
        : `/forms/${selectedReport.id}/excel`;
      const r = await api.get(path, { responseType: 'blob' });
      const url = window.URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement('a');
      a.href = url;
      const name = selectedReport.name || selectedReport.title || 'report';
      a.download = `${name.replace(/\s+/g, '_').substring(0, 30)}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      alert(e?.response?.status === 400 ? 'No data to export' : 'Download failed');
    } finally { setLoading(false); }
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
    setEditChildName(member.child_name && member.child_name !== '—' ? member.child_name : '');
    setEditBirthDate(member.birth_date || '');
    setEditParents((member.parents || []).map((p: any) => ({
      ...p,
      editName: p.name || '',
      is_primary_payer: p.is_primary_payer || false,
    })));
  };

  const saveMember = async () => {
    if (!editingMember || !selectedGroup) return;
    setLoading(true);
    try {
      const updates: Promise<any>[] = editParents.map((p: any) =>
        api.patch(`/classrooms/${selectedGroup.id}/contacts/${p.id}`, {
          child_name: editChildName.trim() || null,
          name: p.editName.trim() || null,
          is_primary_payer: p.is_primary_payer,
        })
      );
      if (editBirthDate !== (editingMember.birth_date || '')) {
        const finalName = editChildName.trim() || editingMember.child_name;
        if (editingMember.student_id) {
          updates.push(
            api.patch(`/students/${editingMember.student_id}`, {
              birth_date: editBirthDate || null,
            })
          );
        } else if (editBirthDate) {
          // Auto-create Student row for classrooms not populated by Seduca sync
          updates.push(
            api.post(`/students`, {
              name: finalName,
              classroom_id: selectedGroup.id,
              birth_date: editBirthDate,
            })
          );
        }
      }
      await Promise.all(updates);
      setEditingMember(null);
      const r = await api.get(`/classrooms/${selectedGroup.id}/members`);
      const data = r.data || {};
      setGroupMembers(data.members || []);
      setGroupUnidentified(data.unidentified || []);
    } catch { setError('Error saving'); }
    finally { setLoading(false); }
  };

  // ── Edit fundraiser ───────────────────────────────────────────────────────
  const openEditFundraiser = (item: any) => {
    setEditingFundraiser(item);
    setEditName(item.name || '');
    setEditAudience(item.audience_classroom_ids || []);
    setEditFixedAmount(item.fixed_amount || '');
    setEditProducts(item.products?.length ? item.products : [{ name: '', price: '' }]);
    setEditAccount(item.account_number || '');
  };

  const saveEditFundraiser = async () => {
    if (!editingFundraiser) return;
    setLoading(true);
    try {
      const payload: any = { name: editName, audience_classroom_ids: editAudience, account_number: editAccount };
      if (editingFundraiser.type === 'fixed') payload.fixed_amount = editFixedAmount;
      if (editingFundraiser.type === 'variable') payload.products = editProducts.filter((p: Product) => p.name);
      await api.patch(`/fundraisers/${editingFundraiser.id}`, payload);
      setEditingFundraiser(null);
      await fetchAll();
    } catch { setError('Error saving'); }
    finally { setLoading(false); }
  };

  // ── Edit form ──────────────────────────────────────────────────────────────
  const openEditForm = (item: any) => {
    setEditingForm(item);
    setEditFormTitle(item.title || '');
    setEditFormAudience(item.audience_classroom_ids || []);
    setEditFormDesc(item.description || '');
  };

  const saveEditForm = async () => {
    if (!editingForm) return;
    setLoading(true);
    try {
      await api.patch(`/forms/${editingForm.id}`, {
        title: editFormTitle,
        description: editFormDesc,
        audience_classroom_ids: editFormAudience,
      });
      setEditingForm(null);
      await fetchAll();
    } catch { setError('Error saving'); }
    finally { setLoading(false); }
  };

  // ── Assign unidentified contact ───────────────────────────────────────────
  const saveContactAssign = async () => {
    if (!assigningContact || !selectedGroup || !assignChildName.trim()) return;
    setLoading(true);
    try {
      await api.patch(`/classrooms/${selectedGroup.id}/contacts/${assigningContact.id}`, {
        child_name: assignChildName.trim(),
      });
      setAssigningContact(null);
      setAssignChildName('');
      const r = await api.get(`/classrooms/${selectedGroup.id}/members`);
      setGroupMembers(r.data?.members || []);
      setGroupUnidentified(r.data?.unidentified || []);
      setWaUntracked(r.data?.wa_untracked || []);
    } catch { setError('Error'); }
    finally { setLoading(false); }
  };

  // ── Assign WA untracked contact (POST new KnownContact + KCG) ────────────
  const saveWaContactAssign = async () => {
    if (!assigningWaContact || !selectedGroup || !assignWaChildName.trim()) return;
    setLoading(true);
    try {
      await api.post(`/classrooms/${selectedGroup.id}/contacts`, {
        jid: assigningWaContact.jid,
        child_name: assignWaChildName.trim(),
      });
      setAssigningWaContact(null);
      setAssignWaChildName('');
      const r = await api.get(`/classrooms/${selectedGroup.id}/members`);
      setGroupMembers(r.data?.members || []);
      setGroupUnidentified(r.data?.unidentified || []);
      setWaUntracked(r.data?.wa_untracked || []);
    } catch { setError('Error'); }
    finally { setLoading(false); }
  };

  // ── Create handlers ───────────────────────────────────────────────────────
  const createFundraiser = async () => {
    if (!fName.trim() || !fAccountId) return;
    setLoading(true);
    try {
      const selectedAcc = accounts.find(a => String(a.id) === fAccountId);
      await api.post('/fundraisers', {
        name: fName,
        account_number: selectedAcc?.details || fAccountId,
        type: fType,
        fixed_amount: fType === 'fixed' ? fAmount : null,
        audience_classroom_ids: fAudience,
        products: fType === 'variable' ? fProducts.filter(p => p.name) : null,
        mode: fMode,
      });
      setShowNewFundraiser(false);
      setFName(''); setFAmount(''); setFAudience([]); setFProducts([{ name: '', price: '' }]); setFMode('campaign');
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
      await api.post('/events', {
        title: evTitle, description: evDesc, date: evDate, location: evLocation,
        type: evType, audience_classroom_ids: evAudience,
      });
      setShowNewEvent(false);
      setEvTitle(''); setEvDesc(''); setEvDate(''); setEvLocation('');
      setEvType('general'); setEvAudience([]);
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

  const createClassroom = async () => {
    if (!newClsName.trim()) return;
    setLoading(true); setError('');
    try {
      await api.post('/classrooms', { name: newClsName.trim(), display_name: newClsName.trim() });
      setNewClsName('');
      setShowNewClassroom(false);
      const r = await api.get('/classrooms');
      setClassrooms(r.data || []);
    } catch (e: any) { setError(e?.response?.data?.detail || 'Error al crear salón'); }
    finally { setLoading(false); }
  };

  const openAssignRole = async (classroomId: number) => {
    setBindingClassroomId(classroomId);
    setAssignPhone(''); setAssignRole('admin');
    setShowAssignRole(true);
    try {
      const r = await api.get(`/classrooms/${classroomId}/roles`);
      setClassroomRoles(r.data || []);
    } catch { setClassroomRoles([]); }
  };

  const saveRole = async () => {
    if (!assignPhone.trim() || !bindingClassroomId) return;
    setLoading(true); setError('');
    try {
      await api.post(`/classrooms/${bindingClassroomId}/roles`, { phone: assignPhone.trim(), role: assignRole });
      const r = await api.get(`/classrooms/${bindingClassroomId}/roles`);
      setClassroomRoles(r.data || []);
      setAssignPhone('');
    } catch (e: any) { setError(e?.response?.data?.detail || 'Error al asignar'); }
    finally { setLoading(false); }
  };

  const removeRole = async (phone: string) => {
    if (!bindingClassroomId) return;
    try {
      await api.delete(`/classrooms/${bindingClassroomId}/roles/${phone}`);
      setClassroomRoles(prev => prev.filter(r => !r.user_jid.startsWith(phone)));
    } catch (e: any) { setError(e?.response?.data?.detail || 'Error'); }
  };

  const deleteReport = async () => {
    if (!selectedReport || !confirm(t.confirm_delete)) return;
    setLoading(true);
    try {
      const path = selectedReport.type === 'fundraiser'
        ? `/fundraisers/${selectedReport.id}`
        : `/forms/${selectedReport.id}`;
      await api.delete(path);
      setSelectedReport(null); setReportData(null);
      await fetchAll();
    } catch (e: any) { setError(e?.response?.data?.detail || 'Error al eliminar'); }
    finally { setLoading(false); }
  };

  const rejectPayment = async (paymentId: number) => {
    if (!confirm('¿Rechazar este pago?')) return;
    try {
      await api.patch(`/fundraisers/payments/${paymentId}`, { status: 'rejected' });
      setSelectedPayerGroup((prev: any) => ({
        ...prev,
        payments: prev.payments.map((p: any) => p.id === paymentId ? { ...p, status: 'rejected' } : p),
      }));
      if (selectedReport) {
        const r = await api.get(`/fundraisers/${selectedReport.id}/report`);
        setReportData(r.data);
      }
    } catch (e: any) { setError(e?.response?.data?.detail || 'Error'); }
  };

  const deleteSubmission = async () => {
    if (!selectedSubmission || !selectedReport || !confirm(t.confirm_delete)) return;
    try {
      await api.delete(`/forms/${selectedReport.id}/submissions/${selectedSubmission.id}`);
      setSelectedSubmission(null); setSubmissionDetail(null);
      const r = await api.get(`/forms/${selectedReport.id}/report`);
      setReportData(r.data);
    } catch (e: any) { setError(e?.response?.data?.detail || 'Error'); }
  };

  const fetchSubmissionDetail = async (formId: number, submissionId: number) => {
    setSubmissionDetail(null);
    try {
      const r = await api.get(`/forms/${formId}/submissions/${submissionId}`);
      setSubmissionDetail(r.data);
    } catch (e) { console.error(e); }
  };

  const refreshSeducaGroups = async () => {
    try {
      const r = await api.get('/seduca/groups');
      setSeducaGroups(r.data || []);
    } catch {}
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
          <div className="w-24 h-24 mb-8 mx-auto">
            <img src="/icon-512.png" alt="EduLink" className="w-full h-full object-contain rounded-3xl shadow-2xl shadow-indigo-200" />
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
              </motion.form>
            )}

            {step === 'code' && (
              <motion.form key="code-step" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }}
                onSubmit={handleLogin} className="space-y-4">
                <p className="text-sm text-slate-500 mb-2">
                  {'Código enviado a'} <span className="font-black text-slate-800">{`+${phone}`}</span>
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
                  count={fundraisers.length} loading={dataLoading} onClick={() => goTab('fundraisers')} />
                <DashCard title={t.forms} icon={<LayoutList />} color="bg-indigo-500"
                  count={forms.length} loading={dataLoading} onClick={() => goTab('forms')} />
                <DashCard title={t.groups} icon={<Users />} color="bg-blue-500"
                  count={classrooms.length} loading={dataLoading} onClick={() => goTab('groups')} />
                <DashCard title={t.events} icon={<Calendar />} color="bg-amber-500"
                  count={events.length} loading={dataLoading} onClick={() => goTab('events')} />
              </div>

              {/* Upcoming events */}
              {upcomingEvents.length > 0 && (
                <div>
                  <h2 className="text-[10px] font-black uppercase tracking-widest text-slate-400 mb-3 px-1">
                    Próximos eventos
                  </h2>
                  <div className="space-y-2">
                    {upcomingEvents.slice(0, 8).map((ev: any, i: number) => {
                      const meta = ev.type === 'birthday' ? { icon: '🎂', bg: 'bg-pink-100', text: 'text-pink-700' }
                        : ev.type === 'holiday' ? { icon: '🎉', bg: 'bg-emerald-100', text: 'text-emerald-700' }
                        : ev.type === 'exam' ? { icon: '📝', bg: 'bg-red-100', text: 'text-red-700' }
                        : { icon: '📅', bg: 'bg-amber-100', text: 'text-amber-700' };
                      const d = new Date(ev.date + 'T00:00:00');
                      const today = new Date(); today.setHours(0, 0, 0, 0);
                      const diffDays = Math.round((d.getTime() - today.getTime()) / 86400000);
                      const rel = diffDays === 0 ? 'Hoy' : diffDays === 1 ? 'Mañana' : `En ${diffDays} días`;
                      const dateLabel = d.toLocaleDateString('es', { day: 'numeric', month: 'short' });
                      return (
                        <div key={`${ev.id || 'syn'}-${i}`}
                          onClick={() => !ev.synthetic && goTab('events')}
                          className={`bg-white rounded-2xl p-4 flex items-center gap-3 border border-slate-100 ${ev.synthetic ? '' : 'cursor-pointer active:scale-[0.98] transition-transform'}`}>
                          <div className={`w-12 h-12 rounded-xl flex items-center justify-center text-xl ${meta.bg}`}>
                            {meta.icon}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="font-black text-sm truncate">{ev.title}</div>
                            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                              {dateLabel} · {rel}{ev.location ? ` · ${ev.location}` : ''}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Assistant — hidden for now */}
            </motion.div>
          )}

          {/* Fundraisers list */}
          {!selectedReport && activeTab === 'fundraisers' && (
            <ListView key="fund-list" title={t.fundraisers} items={[...fundraisers].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())} type="activity"
              noItemsLabel={t.no_items} loading={dataLoading} onSelect={(f: any) => selectReport(f, 'fundraiser')}
              showArchived={showArchivedFunds} seeAllLabel={t.see_all} showActiveLabel={t.show_active}
              onToggleArchived={() => { const next = !showArchivedFunds; setShowArchivedFunds(next); fetchAll({ archivedFunds: next }); }}
              onClose={async (item: any) => {
                try { await api.patch(`/fundraisers/${item.id}`, { status: 'closed' }); await fetchAll(); }
                catch (e: any) { setError(e?.response?.data?.detail || 'Error'); }
              }}
              onDelete={async (item: any) => {
                if (!confirm(t.confirm_delete)) return;
                try { await api.delete(`/fundraisers/${item.id}`); await fetchAll(); }
                catch (e: any) { setError(e?.response?.data?.detail || 'Error al eliminar'); }
              }}
              classrooms={classrooms} />
          )}

          {/* Forms list */}
          {!selectedReport && activeTab === 'forms' && (
            <ListView key="form-list" title={t.forms} items={[...forms].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())} type="form"
              noItemsLabel={t.no_items} loading={dataLoading} onSelect={(f: any) => selectReport(f, 'form')}
              showArchived={showArchivedForms} seeAllLabel={t.see_all} showActiveLabel={t.show_active}
              onToggleArchived={() => { const next = !showArchivedForms; setShowArchivedForms(next); fetchAll({ archivedForms: next }); }}
              onClose={async (item: any) => {
                try { await api.patch(`/forms/${item.id}`, { status: 'closed' }); await fetchAll(); }
                catch (e: any) { setError(e?.response?.data?.detail || 'Error'); }
              }}
              onDelete={async (item: any) => {
                if (!confirm(t.confirm_delete)) return;
                try { await api.delete(`/forms/${item.id}`); await fetchAll(); }
                catch (e: any) { setError(e?.response?.data?.detail || 'Error al eliminar'); }
              }}
              classrooms={classrooms} />
          )}

          {/* Events list */}
          {activeTab === 'events' && (
            <motion.div key="events" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="space-y-6">
              <h2 className="text-2xl font-black tracking-tight">{t.events}</h2>
              <div className="space-y-4">
                {events.length === 0 ? (
                  <div className="text-center text-slate-400 py-12">{t.no_items}</div>
                ) : events.map((ev: any, i: number) => {
                  const typeMeta: Record<string, { icon: string; color: string; label: string }> = {
                    birthday: { icon: '🎂', color: 'bg-pink-500', label: 'Cumpleaños' },
                    holiday:  { icon: '🎉', color: 'bg-emerald-500', label: 'Feriado' },
                    exam:     { icon: '📝', color: 'bg-red-500', label: 'Examen' },
                    general:  { icon: '📅', color: 'bg-amber-500', label: 'General' },
                  };
                  const meta = typeMeta[ev.type] || typeMeta.general;
                  return (
                    <div key={i} className="bg-white p-5 rounded-[2rem] shadow-sm border border-slate-100">
                      <div className="flex items-center gap-4">
                        <div className={`w-12 h-12 ${meta.color} rounded-2xl flex items-center justify-center text-white text-xl flex-shrink-0`}>
                          {meta.icon}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <h4 className="font-black text-slate-800 truncate">{ev.title}</h4>
                            <span className="text-[9px] font-black uppercase tracking-widest px-2 py-0.5 rounded-full bg-slate-100 text-slate-500 flex-shrink-0">{meta.label}</span>
                          </div>
                          <p className="text-[10px] font-bold text-slate-400">
                            {ev.date ? new Date(ev.date).toLocaleDateString() : ''}
                            {ev.location && ` · ${ev.location}`}
                            {ev.is_global && ' · 🌐 Global'}
                          </p>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </motion.div>
          )}

          {/* Groups list */}
          {!selectedGroup && activeTab === 'groups' && (
            <ListView key="group-list" title={t.groups}
              items={[...classrooms].sort((a, b) => (a.display_name || a.name || '').localeCompare(b.display_name || b.name || ''))}
              type="group" noItemsLabel={t.no_items} loading={dataLoading} onSelect={(g: any) => selectGroup(g)}
              onDelete={async (g: any) => {
                if (!confirm(`¿Eliminar grupo "${g.display_name || g.name}"?`)) return;
                try {
                  await api.delete(`/classrooms/${g.id}`);
                  setClassrooms(prev => prev.filter(c => c.id !== g.id));
                } catch (e: any) { setError(e?.response?.data?.detail || 'Error'); }
              }} />
          )}

          {/* Group detail */}
          {selectedGroup && activeTab === 'groups' && (
            <motion.div key="group-detail" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="space-y-6">
              <button onClick={() => { setSelectedGroup(null); setGroupMembers([]); }}
                className="flex items-center gap-2 text-indigo-600 font-black text-xs uppercase tracking-tighter">
                <ChevronLeft className="w-4 h-4" /> {t.back}
              </button>
              <div className="bg-blue-600 p-6 rounded-[3rem] text-white shadow-xl">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-2xl font-black tracking-tight">{selectedGroup.display_name || selectedGroup.name}</h2>
                    <p className="text-white/60 text-xs mt-1 font-bold uppercase tracking-widest">
                      {selectedGroup.kids_count ?? 0} niños · {selectedGroup.members_count ?? 0} contactos
                    </p>
                  </div>
                  <button onClick={() => setShowGroupConfig((v: any) => !v)}
                    className="bg-white/15 hover:bg-white/25 p-2.5 rounded-2xl transition-colors">
                    <Settings className="w-4 h-4" />
                  </button>
                </div>
                {showGroupConfig && (
                  <div className="mt-4 flex items-center gap-2 flex-wrap">
                    {selectedGroup.whatsapp_group_id
                      ? <button onClick={() => unbindGroup(selectedGroup.id)}
                          className="bg-white/10 hover:bg-white/20 text-white text-[9px] font-black px-3 py-1.5 rounded-full uppercase transition-colors">
                          Desvincular WA
                        </button>
                      : <button onClick={() => openBindModal(selectedGroup.id)}
                          className="bg-white/20 hover:bg-white/30 text-white text-[9px] font-black px-3 py-1.5 rounded-full uppercase transition-colors">
                          + Vincular WA
                        </button>}
                    <button onClick={() => openAssignRole(selectedGroup.id)}
                      className="bg-white/10 hover:bg-white/20 text-white text-[9px] font-black px-3 py-1.5 rounded-full uppercase transition-colors">
                      Delegados
                    </button>
                    {groupSeducaLinks[selectedGroup.id]?.linked
                      ? <>
                          <button onClick={() => openSeducaLinkModal(selectedGroup.id)}
                            className="bg-emerald-400/30 text-white text-[9px] font-black px-3 py-1.5 rounded-full uppercase">
                            Seduca ✓
                          </button>
                          <button onClick={() => unlinkSeduca(selectedGroup.id)}
                            className="bg-white/10 text-white text-[9px] font-black px-3 py-1.5 rounded-full uppercase">
                            Desvincular Seduca
                          </button>
                        </>
                      : <button onClick={() => openSeducaLinkModal(selectedGroup.id)}
                          className="bg-white/10 hover:bg-white/20 text-white text-[9px] font-black px-3 py-1.5 rounded-full uppercase transition-colors">
                          + Seduca
                        </button>}
                  </div>
                )}
              </div>
              <div className="space-y-3">
                {groupMembersLoading ? (
                  <div className="text-center text-slate-400 py-8">{t.loading}</div>
                ) : groupMembers.length === 0 ? (
                  <div className="text-center text-slate-400 py-8">{t.no_items}</div>
                ) : groupMembers.map((m: any, i: number) => (
                  <div key={i} className="bg-white p-5 rounded-[2rem] shadow-sm border border-slate-100">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 bg-blue-50 rounded-2xl flex items-center justify-center flex-shrink-0 text-lg">👦</div>
                      <div className="min-w-0 flex-1">
                        <div className="font-black text-slate-800 text-sm">{m.child_name}</div>
                      </div>
                      <button onClick={() => openMemberEdit(m)} className="text-slate-300 hover:text-indigo-500 transition-colors flex-shrink-0 p-1">
                        <Edit2 className="w-4 h-4" />
                      </button>
                    </div>
                    {m.parents?.length > 0 && (
                      <div className="mt-3 space-y-2 border-t border-slate-50 pt-3 ml-3">
                        {m.parents.map((p: any, j: number) => (
                          <MemberParentRow key={j} parent={p} />
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
              {/* Unidentified contacts — collapsible */}
              {groupUnidentified.length > 0 && (
                <div>
                  <button onClick={() => setShowUnidentified(v => !v)}
                    className="text-[10px] font-black uppercase tracking-widest text-slate-400 flex items-center gap-1">
                    <ChevronRight className={`w-3 h-3 transition-transform ${showUnidentified ? 'rotate-90' : ''}`} />
                    {groupUnidentified.length} contactos sin identificar
                  </button>
                  {showUnidentified && (
                    <div className="mt-3 space-y-2">
                      {groupUnidentified.map((u: any, i: number) => (
                        <div key={i} className="bg-slate-50 px-4 py-3 rounded-2xl">
                          <div className="flex items-center justify-between">
                            <div>
                              <div className="text-xs font-bold text-slate-500">{u.name}</div>
                              {u.phone && <div className="text-[10px] font-mono text-slate-400">+{u.phone}</div>}
                            </div>
                            {u.id && (
                              <button onClick={() => { setAssigningContact(u); setAssignChildName(''); }}
                                className="text-indigo-600 text-[10px] font-black uppercase">
                                Identificar
                              </button>
                            )}
                          </div>
                          {assigningContact?.kcg_id === u.kcg_id && (
                            <div className="mt-2 flex gap-2">
                              <input placeholder="Nombre del niño" value={assignChildName}
                                onChange={e => setAssignChildName(e.target.value)}
                                className="flex-1 px-3 py-2 bg-white rounded-xl text-sm font-bold outline-none border border-slate-200" />
                              <button onClick={saveContactAssign} disabled={!assignChildName.trim()}
                                className="bg-indigo-600 text-white px-3 py-2 rounded-xl text-xs font-black disabled:opacity-50">
                                <Check className="w-3 h-3" />
                              </button>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {/* WA group members not yet tracked — collapsible */}
              {waUntracked.length > 0 && (
                <div>
                  <button onClick={() => setShowWaUntracked(v => !v)}
                    className="text-[10px] font-black uppercase tracking-widest text-amber-500 flex items-center gap-1">
                    <ChevronRight className={`w-3 h-3 transition-transform ${showWaUntracked ? 'rotate-90' : ''}`} />
                    {waUntracked.length} miembros del grupo WA sin registrar
                  </button>
                  {showWaUntracked && (
                    <div className="mt-3 space-y-2">
                      {waUntracked.map((u: any, i: number) => (
                        <div key={i} className="bg-amber-50 px-4 py-3 rounded-2xl">
                          <div className="flex items-center justify-between">
                            <div>
                              <div className="text-xs font-bold text-amber-700">{u.name}</div>
                              {u.phone && <div className="text-[10px] font-mono text-amber-500">+{u.phone}</div>}
                            </div>
                            <button onClick={() => { setAssigningWaContact(u); setAssignWaChildName(''); }}
                              className="text-amber-600 text-[10px] font-black uppercase">
                              Identificar
                            </button>
                          </div>
                          {assigningWaContact?.jid === u.jid && (
                            <div className="mt-2 flex gap-2">
                              <input placeholder="Nombre del niño" value={assignWaChildName}
                                onChange={e => setAssignWaChildName(e.target.value)}
                                className="flex-1 px-3 py-2 bg-white rounded-xl text-sm font-bold outline-none border border-amber-200" />
                              <button onClick={saveWaContactAssign} disabled={!assignWaChildName.trim()}
                                className="bg-amber-600 text-white px-3 py-2 rounded-xl text-xs font-black disabled:opacity-50">
                                <Check className="w-3 h-3" />
                              </button>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </motion.div>
          )}

          {/* Settings */}
          {activeTab === 'settings' && (
            <motion.div key="settings" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-8">
              <h2 className="text-2xl font-black tracking-tight">{t.settings}</h2>

              {allRoles.length > 0 && (
                <section className="space-y-4">
                  <h3 className="section-label flex items-center gap-2"><Users className="w-3 h-3" /> {t.delegates}</h3>
                  <div className="space-y-2">
                    {allRoles.map((r: any, i: number) => (
                      <div key={i} className="bg-white p-4 rounded-3xl border border-slate-100 flex items-center justify-between">
                        <div>
                          <div className="font-black text-xs text-slate-800">{r.name || r.phone}</div>
                          {r.name && <div className="text-[10px] font-bold text-slate-400">{r.phone}</div>}
                          <div className="text-[10px] font-bold text-slate-400">{r.classroom_name} · <span className="uppercase">{r.role}</span></div>
                        </div>
                        <button onClick={async () => {
                          try {
                            await api.delete(`/classrooms/${r.classroom_id}/roles/${r.phone}`);
                            setAllRoles(prev => prev.filter((_r, j) => j !== i));
                          } catch (e: any) { setError(e?.response?.data?.detail || 'Error'); }
                        }} className="text-slate-300 hover:text-red-400 transition-colors">
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    ))}
                  </div>
                </section>
              )}

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
                <h3 className="section-label flex items-center gap-2"><Globe className="w-3 h-3" /> Seduca</h3>
                <div className="bg-white p-6 rounded-[2.5rem] border border-slate-100 space-y-4 shadow-sm">
                  {seducaHasCreds && (
                    <div className="bg-emerald-50 px-4 py-2 rounded-2xl text-emerald-700 text-xs font-bold flex items-center justify-between gap-2">
                      <span className="flex items-center gap-2"><Check className="w-3 h-3" /> {seducaCurrentUser}</span>
                      <button onClick={refreshSeducaGroups}
                        className="text-emerald-600 font-black text-[10px] uppercase underline underline-offset-2">
                        Ver grupos
                      </button>
                    </div>
                  )}
                  <FlatInput label="Usuario Seduca" icon={<User className="w-4 h-4" />}
                    value={seducaUser} onChange={setSeducaUser} />
                  <FlatInput label="Contraseña" icon={<Key className="w-4 h-4" />} type="password"
                    value={seducaPass} onChange={setSeducaPass} />
                  <button
                    onClick={saveSeducaCreds}
                    disabled={seducaSaving || !seducaUser || !seducaPass}
                    className="w-full py-4 bg-indigo-600 text-white rounded-2xl font-black text-xs uppercase shadow-lg shadow-indigo-100 disabled:opacity-50">
                    {seducaSaving ? 'Verificando...' : 'Guardar y descubrir grupos'}
                  </button>
                  {seducaGroups.length > 0 && (
                    <div className="pt-2 space-y-2">
                      <p className="text-[10px] font-black uppercase tracking-widest text-slate-400">Grupos Seduca descubiertos</p>
                      {seducaGroups.map((g: any) => (
                        <div key={g.id} className="bg-slate-50 px-4 py-2 rounded-2xl flex items-center justify-between">
                          <span className="text-xs font-bold text-slate-700">{g.name}</span>
                          {g.bound_classroom_id
                            ? <span className="text-[9px] font-black uppercase bg-emerald-50 text-emerald-600 px-2 py-0.5 rounded-full">Vinculado</span>
                            : <span className="text-[9px] font-black uppercase bg-slate-100 text-slate-400 px-2 py-0.5 rounded-full">Sin vincular</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </section>

              <section className="space-y-4">
                <h3 className="section-label flex items-center gap-2"><Tablet className="w-3 h-3" /> Dashboard iPad</h3>
                <div className="bg-white p-6 rounded-[2.5rem] border border-slate-100 space-y-4 shadow-sm">
                  <p className="text-[11px] font-bold text-slate-400 leading-relaxed">
                    Genera un enlace de solo lectura con las tareas de tus hijos para dejar abierto siempre en un iPad. Mantiene la sesión ~1 año; puedes revocarlo cuando quieras.
                  </p>
                  <FlatInput label="Nombre del dispositivo (opcional)" icon={<Tablet className="w-4 h-4" />}
                    value={dashLabel} onChange={setDashLabel} />
                  <button
                    onClick={createDashToken}
                    disabled={dashCreating}
                    className="w-full py-4 bg-indigo-600 text-white rounded-2xl font-black text-xs uppercase shadow-lg shadow-indigo-100 disabled:opacity-50">
                    {dashCreating ? 'Generando...' : '+ Generar enlace'}
                  </button>
                  {dashTokens.length > 0 && (
                    <div className="pt-2 space-y-2">
                      {dashTokens.map((tk: any) => (
                        <div key={tk.id} className="bg-slate-50 px-4 py-3 rounded-2xl flex items-center justify-between gap-2">
                          <div className="min-w-0">
                            <div className="text-xs font-black text-slate-700 truncate">{tk.label || 'Sin nombre'}</div>
                            <div className="text-[10px] font-bold text-slate-400">
                              {(tk.student_ids || []).length} estudiante(s) · {tk.last_used_at ? 'usado' : 'sin usar'}
                            </div>
                          </div>
                          <div className="flex items-center gap-3 flex-shrink-0">
                            <button onClick={() => copyDashLink(tk)}
                              className="text-indigo-600 font-black text-[10px] uppercase flex items-center gap-1">
                              {dashCopiedId === tk.id
                                ? <><Check className="w-3 h-3" /> Copiado</>
                                : <><Copy className="w-3 h-3" /> Copiar</>}
                            </button>
                            <button onClick={() => revokeDashToken(tk.id)} className="text-slate-300 hover:text-red-400 transition-colors">
                              <X className="w-4 h-4" />
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
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
              <div className={`${selectedReport.type === 'fundraiser' ? 'bg-emerald-600' : 'bg-indigo-600'} p-6 rounded-[3rem] text-white shadow-xl`}>
                <div className="flex items-center gap-3 mb-1">
                  <h2 className="text-lg font-black tracking-tight leading-snug break-words min-w-0 flex-1">{selectedReport.name || selectedReport.title}</h2>
                  <span className={`text-[9px] font-black uppercase px-2 py-0.5 rounded-full flex-shrink-0 ${
                    (reportData?.status || selectedReport.status) === 'active' ? 'bg-white/20' : 'bg-white/10 text-white/60'
                  }`}>{reportData?.status || selectedReport.status}</span>
                </div>
                {selectedReport.type === 'fundraiser' && reportData && (
                  <div className="flex items-baseline gap-3 mt-2 mb-4">
                    <span className="text-3xl font-black">${reportData.payments?.reduce((s: number, p: any) => s + (p.status === 'confirmed' && !p.voided_at ? parseFloat(p.amount || 0) : 0), 0).toFixed(2)}</span>
                    <span className="text-white/50 text-xs font-bold">{reportData.payments?.filter((p: any) => p.status === 'confirmed' && !p.voided_at).length || 0} pagos</span>
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  <button onClick={sendReminder} disabled={loading}
                    className="bg-white text-slate-900 px-4 py-2.5 rounded-2xl text-[10px] font-black uppercase flex items-center gap-1.5 shadow-lg active:scale-95 transition-transform">
                    <Bell className="w-3 h-3" /> {t.remind}
                  </button>
                  {selectedReport.type === 'fundraiser' && (
                    <button onClick={announceFundraiser} disabled={loading}
                      className="bg-white text-slate-900 px-4 py-2.5 rounded-2xl text-[10px] font-black uppercase flex items-center gap-1.5 shadow-lg active:scale-95 transition-transform">
                      <Megaphone className="w-3 h-3" /> {t.announce}
                    </button>
                  )}
                  <button onClick={downloadExcel} disabled={loading}
                    className="bg-white text-slate-900 px-4 py-2.5 rounded-2xl text-[10px] font-black uppercase flex items-center gap-1.5 shadow-lg active:scale-95 transition-transform">
                    <Download className="w-3 h-3" /> Excel
                  </button>
                  <button onClick={toggleReportStatus} disabled={loading}
                    className="bg-white/15 px-4 py-2.5 rounded-2xl text-white text-[10px] font-black uppercase">
                    {(reportData?.status || selectedReport.status) === 'active' ? t.close : t.reopen}
                  </button>
                  {(reportData?.status || selectedReport.status) === 'active' && (
                    <button onClick={() => selectedReport.type === 'fundraiser' ? openEditFundraiser(selectedReport) : openEditForm(selectedReport)}
                      className="bg-white/15 px-3 py-2.5 rounded-2xl text-white text-[10px] font-black uppercase flex items-center gap-1">
                      <Pencil className="w-3 h-3" />
                    </button>
                  )}
                  {reportData != null &&
                   (reportData.payments?.length === 0 || reportData.submissions?.length === 0) && (
                    <button onClick={deleteReport} disabled={loading}
                      className="bg-red-500/20 hover:bg-red-500/40 px-3 py-2.5 rounded-2xl text-white text-[10px] font-black uppercase transition-colors">
                      <Trash2 className="w-3 h-3" />
                    </button>
                  )}
                </div>
              </div>

              {/* Fund-mode tab switcher (payments vs transparency) */}
              {selectedReport.type === 'fundraiser' && selectedReport.mode === 'fund' && (
                <div className="flex gap-2">
                  <button
                    onClick={() => setReportSubView('payments')}
                    className={`flex-1 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all ${reportSubView === 'payments' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-100' : 'bg-slate-100 text-slate-400'}`}
                  >
                    Pagos
                  </button>
                  <button
                    onClick={() => setReportSubView('transparency')}
                    className={`flex-1 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all ${reportSubView === 'transparency' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-100' : 'bg-slate-100 text-slate-400'}`}
                  >
                    Transparencia
                  </button>
                </div>
              )}

              {selectedReport.type === 'fundraiser' && selectedReport.mode === 'fund' && reportSubView === 'transparency' ? (
                <div className="bg-white rounded-[2.5rem] p-6 shadow-sm border border-slate-100">
                  <h3 className="text-xl font-black tracking-tight mb-6">Transparencia</h3>
                  <TransparencyPanel fundraiserId={selectedReport.id} />
                </div>
              ) : (
              <div className="bg-white rounded-[2.5rem] p-6 shadow-sm border border-slate-100">
                <div className="flex items-center justify-between mb-6">
                  <h3 className="text-xl font-black tracking-tight flex items-center gap-3">
                    {selectedReport.type === 'fundraiser' ? t.payments : t.submissions}
                    <span className="text-xs bg-slate-100 text-slate-400 px-3 py-1 rounded-full">LIVE</span>
                  </h3>
                  {selectedReport.type === 'fundraiser' && reportData && reportData.type !== 'variable' && (
                    <button
                      onClick={() => setShowManualPayment(true)}
                      className="bg-indigo-50 text-indigo-600 px-3 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest"
                    >
                      + Pago manual
                    </button>
                  )}
                </div>
                <div className="space-y-4">
                  {reportData == null ? (
                    <div className="text-center text-slate-400 py-4">{t.loading}</div>
                  ) : selectedReport.type === 'fundraiser' ? (
                    (() => {
                      const payments: any[] = reportData?.payments || [];
                      const grouped = payments.reduce((acc: any, p: any) => {
                        const key = p.payer_jid || p.parent || 'unknown';
                        if (!acc[key]) acc[key] = { name: p.parent, child: p.child, classrooms: [], payments: [] };
                        if (p.classroom && !acc[key].classrooms.includes(p.classroom)) acc[key].classrooms.push(p.classroom);
                        acc[key].payments.push(p);
                        return acc;
                      }, {} as Record<string, any>);
                      const groups = Object.values(grouped) as any[];
                      if (groups.length === 0) return <div className="text-center text-slate-400">{t.no_items}</div>;
                      const unpaid: any[] = reportData?.unpaid || [];
                      return <>
                        {groups.map((g: any, i: number) => {
                          const live = g.payments.filter((p: any) => !p.voided_at);
                          const total = live.reduce((sum: number, p: any) => sum + parseFloat(p.amount || 0), 0);
                          const allConfirmed = live.length > 0 && live.every((p: any) => p.status === 'confirmed');
                          const anyConfirmed = live.some((p: any) => p.status === 'confirmed');
                          const hasManual = g.payments.some((p: any) => p.entry_method === 'manual');
                          const hasVoided = g.payments.some((p: any) => p.voided_at);
                          return (
                            <div key={i} onClick={() => { setSelectedPayerGroup(g); setShowPaymentModal(true); }}
                              className="flex justify-between items-center p-4 bg-slate-50/50 hover:bg-slate-100 rounded-2xl border border-slate-50 cursor-pointer active:scale-[0.98] transition-transform">
                              <div className="min-w-0">
                                <div className="font-black text-slate-800 text-xs truncate flex items-center gap-1.5">
                                  {g.name}
                                  {hasManual && <span className="text-[9px] font-black uppercase bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded-full">manual</span>}
                                  {hasVoided && <span className="text-[9px] font-black uppercase bg-red-50 text-red-500 px-1.5 py-0.5 rounded-full">anulado</span>}
                                </div>
                                <div className="text-[10px] text-slate-400 font-bold">{g.child}</div>
                              </div>
                              <div className="flex items-center gap-2 flex-shrink-0">
                                {reportData?.multi_classroom && g.classrooms.length > 0 && (
                                  <span className="text-[10px] font-black uppercase px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-600">
                                    {g.classrooms.join(', ')}
                                  </span>
                                )}
                                <div className="text-right">
                                  <div className="text-xs font-black text-emerald-600">${total.toFixed(2)}</div>
                                  <span className={`text-[10px] font-black uppercase px-2 py-0.5 rounded-full ${allConfirmed ? 'bg-emerald-50 text-emerald-600' : anyConfirmed ? 'bg-blue-50 text-blue-600' : 'bg-amber-50 text-amber-600'}`}>
                                    {allConfirmed ? 'confirmed' : anyConfirmed ? 'partial' : g.payments[0]?.status}
                                  </span>
                                </div>
                                <ChevronRight className="w-4 h-4 text-slate-300" />
                              </div>
                            </div>
                          );
                        })}
                        {unpaid.length > 0 && (
                          <div className="mt-6">
                            <h3 className="text-[10px] font-black uppercase tracking-widest text-red-400 mb-3">
                              Sin pagar ({unpaid.length})
                            </h3>
                            <div className="space-y-2">
                              {unpaid.map((u: any, i: number) => (
                                <div key={i} className="flex justify-between items-center p-3 bg-red-50/50 rounded-2xl border border-red-50">
                                  <div className="min-w-0">
                                    <div className="font-black text-slate-700 text-xs truncate">{u.child_name}</div>
                                    <div className="text-[10px] text-slate-400 font-bold">{u.parent_name} · {u.classroom}</div>
                                  </div>
                                  <span className="text-[10px] font-black uppercase px-2 py-0.5 rounded-full bg-red-100 text-red-500 flex-shrink-0">
                                    pendiente
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </>;
                    })()
                  ) : (
                    (() => {
                      const submissions: any[] = reportData?.submissions || [];
                      if (submissions.length === 0) return <div className="text-center text-slate-400">{t.no_items}</div>;
                      return <>{submissions.map((s: any, i: number) => (
                        <div key={i} onClick={() => { setSelectedSubmission(s); fetchSubmissionDetail(selectedReport.id, s.id); }}
                          className="flex justify-between items-center p-4 bg-slate-50/50 hover:bg-slate-100 rounded-2xl border border-slate-50 cursor-pointer active:scale-[0.98] transition-transform">
                          <div className="min-w-0">
                            <div className="font-black text-slate-800 text-xs truncate">{s.parent}</div>
                            <div className="text-[10px] text-slate-400 font-bold truncate">{s.student}</div>
                          </div>
                          <div className="flex items-center gap-2 flex-shrink-0">
                            {reportData?.multi_classroom && s.classroom && (
                              <span className="text-[10px] font-black uppercase px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-600">
                                {s.classroom}
                              </span>
                            )}
                            <span className={`text-[10px] font-black uppercase px-2 py-0.5 rounded-full ${s.status === 'submitted' ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'}`}>
                              {s.status}
                            </span>
                            <ChevronRight className="w-4 h-4 text-slate-300" />
                          </div>
                        </div>
                      ))}</>;
                    })()
                  )}
                </div>
              </div>
              )}
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
              <CreateOpt icon={<Users />} label={t.new_classroom} color="text-blue-600 bg-blue-50"
                onClick={() => { setShowCreateMenu(false); setShowNewClassroom(true); }} />
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

              {/* Mode */}
              <div className="space-y-2">
                <label className="label-sm">Modo</label>
                <div className="grid grid-cols-2 gap-2">
                  <button onClick={() => setFMode('campaign')}
                    className={`py-3 rounded-2xl text-xs font-black uppercase transition-all ${fMode === 'campaign' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-100' : 'bg-slate-100 text-slate-400'}`}>
                    Campaña
                  </button>
                  <button onClick={() => setFMode('fund')}
                    className={`py-3 rounded-2xl text-xs font-black uppercase transition-all ${fMode === 'fund' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-100' : 'bg-slate-100 text-slate-400'}`}>
                    Fondo
                  </button>
                </div>
                <p className="text-[10px] text-slate-400 font-bold leading-snug">
                  {fMode === 'fund'
                    ? 'Fondo colectivo: acumula aportes para financiar varias actividades. Permite subir comprobantes de gastos.'
                    : 'Campaña: recauda una vez para un propósito específico.'}
                </p>
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

      {/* ── Edit Fundraiser Modal ────────────────────────────────────────── */}
      <AnimatePresence>
        {editingFundraiser && (
          <Modal title="Editar actividad" onClose={() => setEditingFundraiser(null)}>
            <div className="space-y-5">
              <FlatInput label={t.fund_name} icon={<Tag className="w-4 h-4" />}
                value={editName} onChange={setEditName} />
              {editingFundraiser?.type === 'fixed' && (
                <FlatInput label={t.fund_amount} icon={<DollarSign className="w-4 h-4" />}
                  value={editFixedAmount} onChange={setEditFixedAmount} type="number" />
              )}
              {editingFundraiser?.type === 'variable' && (
                <div className="space-y-2">
                  <label className="label-sm">{t.add_product}</label>
                  <div className="space-y-2">
                    {editProducts.map((p: Product, i: number) => (
                      <div key={i} className="flex gap-2">
                        <input placeholder={t.product_name} value={p.name}
                          onChange={e => { const a = [...editProducts]; a[i] = { ...a[i], name: e.target.value }; setEditProducts(a); }}
                          className="flex-1 px-3 py-3 bg-slate-50 rounded-xl font-bold text-sm outline-none border-none" />
                        <input placeholder="$" value={p.price} type="number"
                          onChange={e => { const a = [...editProducts]; a[i] = { ...a[i], price: e.target.value }; setEditProducts(a); }}
                          className="w-20 px-3 py-3 bg-slate-50 rounded-xl font-bold text-sm outline-none border-none" />
                        {editProducts.length > 1 && (
                          <button onClick={() => setEditProducts(editProducts.filter((_: Product, j: number) => j !== i))}
                            className="text-slate-300"><X className="w-4 h-4" /></button>
                        )}
                      </div>
                    ))}
                  </div>
                  <button onClick={() => setEditProducts([...editProducts, { name: '', price: '' }])}
                    className="text-indigo-600 text-xs font-black uppercase">+ {t.add_product}</button>
                </div>
              )}
              {/* Account */}
              <div className="space-y-2">
                <label className="label-sm">{t.fund_account}</label>
                <select value={accounts.find((a: any) => a.details === editAccount)?.id || ''}
                  onChange={e => { const acc = accounts.find((a: any) => String(a.id) === e.target.value); if (acc) setEditAccount(acc.details); }}
                  className="w-full px-4 py-4 bg-slate-50 border-none rounded-2xl font-bold appearance-none outline-none text-sm">
                  {accounts.map((acc: any) => (
                    <option key={acc.id} value={String(acc.id)}>{acc.label} · {acc.details}</option>
                  ))}
                </select>
              </div>
              <AudiencePicker label={t.audience} classrooms={classrooms} selected={editAudience}
                onToggle={(id: number) => toggleAudience(id, editAudience, setEditAudience)} />
              <button onClick={saveEditFundraiser} disabled={loading || !editName.trim()}
                className="w-full py-5 bg-indigo-600 text-white rounded-[1.5rem] font-black shadow-xl disabled:opacity-50">
                {loading ? '...' : 'Guardar'}
              </button>
            </div>
          </Modal>
        )}
      </AnimatePresence>

      {/* ── Edit Form Modal ─────────────────────────────────────────────── */}
      <AnimatePresence>
        {editingForm && (
          <Modal title="Editar formulario" onClose={() => setEditingForm(null)}>
            <div className="space-y-5">
              <FlatInput label={t.form_title} icon={<FileText className="w-4 h-4" />}
                value={editFormTitle} onChange={setEditFormTitle} />
              <FlatInput label={t.form_description} icon={<FileText className="w-4 h-4" />}
                value={editFormDesc} onChange={setEditFormDesc} />
              <AudiencePicker label={t.audience} classrooms={classrooms} selected={editFormAudience}
                onToggle={(id: number) => toggleAudience(id, editFormAudience, setEditFormAudience)} />
              <button onClick={saveEditForm} disabled={loading || !editFormTitle.trim()}
                className="w-full py-5 bg-indigo-600 text-white rounded-[1.5rem] font-black shadow-xl disabled:opacity-50">
                {loading ? '...' : 'Guardar'}
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
              <div className="space-y-2">
                <label className="label-sm">Tipo</label>
                <div className="grid grid-cols-3 gap-2">
                  {([
                    { v: 'general', label: '📅 General' },
                    { v: 'holiday', label: '🎉 Feriado' },
                    { v: 'exam',    label: '📝 Examen'  },
                  ] as const).map(opt => (
                    <button key={opt.v} onClick={() => setEvType(opt.v)}
                      className={`py-3 rounded-2xl text-xs font-black uppercase ${evType === opt.v ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-400'}`}>
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
              <AudiencePicker label={t.audience} classrooms={classrooms} selected={evAudience}
                onToggle={(id: number) => toggleAudience(id, evAudience, setEvAudience)} />
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
              <FlatInput label={t.student_name} icon={<User className="w-4 h-4" />}
                value={editChildName} onChange={setEditChildName} />
              <FlatInput label="Cumpleaños 🎂" icon={<Calendar className="w-4 h-4" />}
                value={editBirthDate} onChange={setEditBirthDate} type="date" />
              {editParents.map((p: any, i: number) => (
                <div key={i} className="space-y-2 bg-slate-50 p-4 rounded-2xl">
                  <FlatInput label={`${t.parent_name} ${editParents.length > 1 ? i + 1 : ''}`}
                    value={p.editName}
                    onChange={(v: string) => setEditParents(prev => prev.map((x, j) => j === i ? { ...x, editName: v } : x))} />
                  <button
                    onClick={() => setEditParents(prev => prev.map((x, j) => j === i ? { ...x, is_primary_payer: !x.is_primary_payer } : x))}
                    className={`flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-black transition-all ${p.is_primary_payer ? 'bg-emerald-500 text-white' : 'bg-white text-slate-400 border border-slate-200'}`}>
                    <CreditCard className="w-3.5 h-3.5" />
                    {t.primary_payer}
                  </button>
                </div>
              ))}
              <button onClick={saveMember} disabled={loading}
                className="w-full py-5 bg-indigo-600 text-white rounded-[1.5rem] font-black shadow-xl disabled:opacity-50">
                {loading ? '...' : t.save}
              </button>
            </div>
          </Modal>
        )}
      </AnimatePresence>

      {/* Delegate role assignment modal */}
      <AnimatePresence>
        {showAssignRole && (
          <Modal title={t.delegates} onClose={() => setShowAssignRole(false)}>
            <div className="space-y-5">
              {classroomRoles.length > 0 && (
                <div className="space-y-2">
                  {classroomRoles.map((r: any) => (
                    <div key={r.user_jid} className="flex items-center justify-between bg-slate-50 px-4 py-2 rounded-2xl">
                      <div>
                        <div className="text-xs font-black text-slate-700">{r.name || r.phone || r.user_jid.replace('@c.us','')}</div>
                        {r.name && <div className="text-[10px] font-bold text-slate-400">{r.phone || r.user_jid.replace('@c.us','')}</div>}
                        <div className="text-[10px] font-bold text-slate-400 uppercase">{r.role}</div>
                      </div>
                      <button onClick={() => removeRole(r.phone || r.user_jid.replace('@c.us',''))}
                        className="text-slate-300 hover:text-red-400 transition-colors">
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <div className="border-t border-slate-100 pt-4 space-y-3">
                <p className="text-[10px] font-black uppercase tracking-widest text-slate-400">{t.add_delegate}</p>
                <FlatInput label="Teléfono (ej: 50766112233)" icon={<User className="w-4 h-4" />}
                  value={assignPhone} onChange={setAssignPhone} />
                <div className="space-y-2">
                  <label className="label-sm">Rol</label>
                  <select value={assignRole} onChange={e => setAssignRole(e.target.value)}
                    className="w-full px-4 py-3 bg-slate-50 rounded-2xl text-sm font-bold focus:outline-none focus:ring-2 focus:ring-indigo-500/20">
                    <option value="delegado">Delegado</option>
                    <option value="soporte">Soporte</option>
                  </select>
                </div>
                <button onClick={saveRole} disabled={loading || !assignPhone.trim()}
                  className="w-full py-4 bg-indigo-600 text-white rounded-2xl font-black text-xs uppercase disabled:opacity-50">
                  {loading ? '...' : 'Asignar'}
                </button>
              </div>
            </div>
          </Modal>
        )}
      </AnimatePresence>

      {/* New Classroom modal */}
      <AnimatePresence>
        {showNewClassroom && (
          <Modal title={t.new_classroom} onClose={() => setShowNewClassroom(false)}>
            <div className="space-y-5">
              <FlatInput label="Nombre del salón" icon={<Users className="w-4 h-4" />}
                value={newClsName} onChange={setNewClsName} />
              <button onClick={createClassroom} disabled={loading || !newClsName.trim()}
                className="w-full py-5 bg-blue-600 text-white rounded-[1.5rem] font-black shadow-xl disabled:opacity-50">
                {loading ? '...' : t.new_classroom}
              </button>
            </div>
          </Modal>
        )}
      </AnimatePresence>

      {/* WhatsApp group binding modal */}
      <AnimatePresence>
        {showBindModal && (
          <Modal title="Vincular grupo de WhatsApp" onClose={() => setShowBindModal(false)}>
            <div className="space-y-4">
              <p className="text-xs text-slate-500 font-medium">
                Pega el enlace de invitación del grupo de WhatsApp.<br />
                El bot se unirá automáticamente al grupo.
              </p>
              <FlatInput
                label="Enlace de invitación (chat.whatsapp.com/...)"
                icon={<Link2 className="w-4 h-4" />}
                value={bindInviteLink}
                onChange={setBindInviteLink}
              />
              <p className="text-[10px] text-slate-400 font-medium">
                Ejemplo: https://chat.whatsapp.com/ABC123XYZ
              </p>
              <button
                onClick={bindGroupViaLink}
                disabled={wahaGroupsLoading || !bindInviteLink.trim()}
                className="w-full py-5 bg-green-600 text-white rounded-[1.5rem] font-black shadow-xl disabled:opacity-50">
                {wahaGroupsLoading ? '...' : 'Vincular grupo'}
              </button>
            </div>
          </Modal>
        )}
      </AnimatePresence>

      {/* Manual payment + audit drawer (fund-mode fundraisers) */}
      <AnimatePresence>
        {showManualPayment && selectedReport?.type === 'fundraiser' && (
          <ManualPaymentModal
            fundraiserId={selectedReport.id}
            fundraiserName={selectedReport.name}
            onClose={() => setShowManualPayment(false)}
            onSaved={async () => { setShowManualPayment(false); await refreshReportData(); }}
          />
        )}
        {auditingPaymentId != null && (
          <PaymentAuditDrawer
            paymentId={auditingPaymentId}
            onClose={() => setAuditingPaymentId(null)}
          />
        )}
      </AnimatePresence>

      {/* Payment slip modal */}
      <AnimatePresence>
        {showPaymentModal && selectedPayerGroup && (
          <Modal title={t.payment_slip} onClose={() => { setShowPaymentModal(false); setSelectedPayerGroup(null); }}>
            <div className="space-y-4">
              <div>
                <div className="font-black text-slate-800">{selectedPayerGroup.name}</div>
                <div className="text-xs text-slate-400 font-bold">{selectedPayerGroup.child}</div>
              </div>
              {selectedPayerGroup.payments.map((p: any, i: number) => {
                const isManual = p.entry_method === 'manual';
                const isVoided = !!p.voided_at;
                return (
                <div key={i} className={`rounded-2xl p-4 space-y-2 ${isVoided ? 'bg-red-50/40 border border-red-100' : 'bg-slate-50'}`}>
                  <div className="flex justify-between items-start">
                    <div className="min-w-0">
                      <div className={`font-black text-sm ${isVoided ? 'text-slate-400 line-through' : 'text-slate-800'}`}>${p.amount}</div>
                      <div className="text-[10px] font-bold text-slate-400">
                        {p.date ? new Date(p.date).toLocaleDateString() : ''}
                        {p.confirmation_code && <span className="ml-2">· #{p.confirmation_code}</span>}
                      </div>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {isManual && (
                          <span className="text-[9px] font-black uppercase bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded-full">
                            manual
                          </span>
                        )}
                        {isVoided && (
                          <span className="text-[9px] font-black uppercase bg-red-100 text-red-600 px-1.5 py-0.5 rounded-full">
                            anulado
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <span className={`text-[10px] font-black uppercase px-2 py-0.5 rounded-full ${p.status === 'confirmed' && !isVoided ? 'bg-emerald-50 text-emerald-600' : p.status === 'rejected' || isVoided ? 'bg-red-50 text-red-500' : 'bg-amber-50 text-amber-600'}`}>
                        {isVoided ? 'voided' : p.status}
                      </span>
                      {!isVoided && p.status !== 'rejected' && (
                        <button onClick={() => rejectPayment(p.id)}
                          className="text-slate-300 hover:text-red-400 transition-colors" title="Rechazar">
                          <X className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </div>
                  {p.method_note && (
                    <div className="text-[11px] text-slate-600 italic">{p.method_note}</div>
                  )}
                  {p.recorded_by_jid && (
                    <div className="text-[10px] text-slate-400 font-bold">
                      Registrado por: <span className="font-mono">{p.recorded_by_jid}</span>
                    </div>
                  )}
                  {isVoided && p.void_reason && (
                    <div className="text-[11px] text-red-600 font-bold">
                      Anulado: {p.void_reason}
                    </div>
                  )}
                  {(p.receipt_media_url || p.manual_proof_url) && (
                    <img src={p.receipt_media_url || p.manual_proof_url} alt="Comprobante"
                      className="w-full rounded-2xl border border-slate-100 object-contain max-h-64" />
                  )}
                  {p.order_items?.length > 0 && (
                    <div className="border-t border-slate-100 pt-2">
                      <div className="text-[10px] font-black uppercase text-slate-400 mb-1">{t.order_items}</div>
                      <div className="space-y-1">
                        {p.order_items.map((oi: any, j: number) => (
                          <div key={j} className="flex justify-between text-xs font-bold text-slate-700">
                            <span>{oi.product} × {oi.quantity}</span>
                            <span>${oi.subtotal}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="flex gap-2 pt-2 border-t border-slate-100">
                    <button
                      onClick={() => setAuditingPaymentId(p.id)}
                      className="text-[10px] font-black uppercase text-slate-500 hover:text-indigo-600 transition-colors"
                    >
                      Auditoría
                    </button>
                    {isVoided ? (
                      <button
                        onClick={() => restorePayment(p.id)}
                        className="text-[10px] font-black uppercase text-emerald-600 hover:text-emerald-700 ml-auto"
                      >
                        Restaurar
                      </button>
                    ) : (
                      <button
                        onClick={() => voidPayment(p.id)}
                        className="text-[10px] font-black uppercase text-red-500 hover:text-red-600 ml-auto"
                      >
                        Anular
                      </button>
                    )}
                  </div>
                </div>
              );
              })}
            </div>
          </Modal>
        )}
      </AnimatePresence>

      {/* Form submission detail modal */}
      <AnimatePresence>
        {selectedSubmission && (
          <Modal title={t.answers} onClose={() => { setSelectedSubmission(null); setSubmissionDetail(null); }}>
            <div className="space-y-4">
              <div>
                <div className="font-black text-slate-800">{selectedSubmission.parent}</div>
                <div className="text-xs text-slate-400 font-bold">{selectedSubmission.student} · {selectedSubmission.date ? new Date(selectedSubmission.date).toLocaleDateString() : ''}</div>
              </div>
              {submissionDetail == null ? (
                <div className="text-center text-slate-400 py-6">{t.loading}</div>
              ) : submissionDetail.answers?.length === 0 ? (
                <div className="text-center text-slate-400 py-4">{t.no_items}</div>
              ) : submissionDetail.answers?.map((a: any, i: number) => (
                <div key={i} className="bg-slate-50 rounded-2xl p-4">
                  <div className="font-black text-slate-700 text-xs mb-1">{a.question}</div>
                  <div className="text-sm text-slate-800">
                    {a.value_json != null
                      ? (Array.isArray(a.value_json) ? a.value_json.join(', ') : String(a.value_json))
                      : a.value || '—'}
                  </div>
                </div>
              ))}
              {submissionDetail != null && (
                <button onClick={deleteSubmission}
                  className="w-full py-4 bg-red-50 text-red-500 rounded-2xl font-black text-xs uppercase mt-2 hover:bg-red-100 transition-colors">
                  <span className="flex items-center justify-center gap-2"><Trash2 className="w-3 h-3" /> {t.delete}</span>
                </button>
              )}
            </div>
          </Modal>
        )}
      </AnimatePresence>

      {/* Seduca link modal */}
      <AnimatePresence>
        {showSeducaLinkModal && (
          <Modal title="Vincular grupo Seduca" onClose={() => setShowSeducaLinkModal(false)}>
            <div className="space-y-5">
              {seducaGroups.length === 0 ? (
                <div className="text-center text-slate-400 py-4 text-sm">
                  Agrega credenciales Seduca en Configuración primero.
                </div>
              ) : (
                <>
                  <p className="text-[10px] font-black uppercase tracking-widest text-slate-400">Selecciona grupo Seduca</p>
                  <div className="space-y-2 max-h-48 overflow-y-auto">
                    {seducaGroups.map((g: any) => (
                      <button key={g.id}
                        onClick={() => setSelectedSeducaGroupId(g.id)}
                        disabled={!!g.bound_classroom_id && g.bound_classroom_id !== seducaLinkClassroomId}
                        className={`w-full p-3 rounded-2xl text-left transition-colors text-xs font-bold ${
                          selectedSeducaGroupId === g.id
                            ? 'bg-indigo-600 text-white'
                            : 'bg-slate-50 hover:bg-indigo-50 text-slate-700 disabled:opacity-40'
                        }`}>
                        <div>{g.classroom_name || g.name}</div>
                        {g.classroom_name && g.name && g.classroom_name !== g.name && (
                          <div className="text-[10px] font-semibold opacity-60 mt-0.5">{g.name}</div>
                        )}
                        {g.bound_classroom_id && g.bound_classroom_id !== seducaLinkClassroomId &&
                          <span className="mt-1 inline-block text-[9px] opacity-60">({g.bound_classroom_name})</span>}
                      </button>
                    ))}
                  </div>
                  <div className="space-y-3">
                    <label className="block text-[10px] font-black uppercase tracking-widest text-slate-400">
                      Día del resumen semanal
                    </label>
                    <div className="flex gap-1.5">
                      {['Lu','Ma','Mi','Ju','Vi','Sa','Do'].map((d, i) => (
                        <button key={i} onClick={() => setSeducaLinkDay(i)}
                          className={`flex-1 py-2.5 rounded-xl text-[10px] font-black uppercase transition-all ${seducaLinkDay === i ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-400'}`}>
                          {d}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="space-y-3">
                    <label className="block text-[10px] font-black uppercase tracking-widest text-slate-400">
                      Hora del resumen
                    </label>
                    <input type="time" value={seducaLinkTime} onChange={(e) => setSeducaLinkTime(e.target.value)}
                      className="w-full border border-slate-200 rounded-2xl px-4 py-3 text-sm font-bold focus:outline-none focus:border-indigo-400" />
                  </div>
                  <label className="flex items-center gap-3 cursor-pointer">
                    <div onClick={() => setSeducaLinkDms(!seducaLinkDms)}
                      className={`w-10 h-6 rounded-full transition-colors ${seducaLinkDms ? 'bg-indigo-600' : 'bg-slate-200'} flex items-center`}>
                      <div className={`w-4 h-4 bg-white rounded-full shadow transition-transform mx-1 ${seducaLinkDms ? 'translate-x-4' : ''}`} />
                    </div>
                    <span className="text-xs font-bold text-slate-600">Responder DMs de padres</span>
                  </label>
                  <button onClick={saveSeducaLink} disabled={!selectedSeducaGroupId}
                    className="w-full py-5 bg-indigo-600 text-white rounded-[1.5rem] font-black shadow-xl disabled:opacity-50">
                    Guardar
                  </button>
                </>
              )}
            </div>
          </Modal>
        )}
      </AnimatePresence>
    </div>
  );
}

// ─── Sub-components ────────────────────────────────────────────────────────────

function DashCard({ title, icon, color, count, loading, onClick }: any) {
  return (
    <div onClick={onClick} className="bg-white p-5 rounded-[2rem] shadow-sm border border-slate-100 flex flex-col justify-between active:scale-95 transition-transform cursor-pointer">
      <div className={`${color} w-12 h-12 rounded-2xl flex items-center justify-center text-white mb-4 shadow-lg shadow-slate-100`}>{icon}</div>
      <div>
        <div className="text-xl font-black text-slate-800 leading-none mb-1">
          {loading ? <span className="inline-block w-6 h-5 bg-slate-100 rounded animate-pulse" /> : count}
        </div>
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

function MemberParentRow({ parent }: { parent: any }) {
  const [showPhone, setShowPhone] = React.useState(false);
  const isRealPhone = parent.phone && parent.phone.length <= 15 && /^\d{7,15}$/.test(parent.phone);
  return (
    <button onClick={() => setShowPhone(v => !v)}
      className="flex items-center gap-2 w-full text-left hover:bg-slate-50 rounded-2xl px-2 py-1 transition-colors">
      <div className="w-7 h-7 bg-slate-100 rounded-full flex items-center justify-center text-xs flex-shrink-0">👤</div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-bold text-slate-600">{parent.name}</span>
          {parent.is_primary_payer && (
            <span className="bg-emerald-100 text-emerald-600 text-[8px] font-black px-1.5 py-0.5 rounded-full uppercase">principal</span>
          )}
        </div>
        {showPhone && (
          isRealPhone
            ? <div className="text-[10px] font-mono text-indigo-500 mt-0.5">+{parent.phone}</div>
            : <div className="text-[10px] text-slate-300 mt-0.5">Sin teléfono</div>
        )}
      </div>
    </button>
  );
}

function SwipeableCard({ children, onClose, onDelete }: { children: React.ReactNode; onClose?: () => void; onDelete?: () => void }) {
  const x = useMotionValue(0);
  const THRESHOLD = 80;

  const handleDragEnd = (_: any, info: any) => {
    if (info.offset.x < -THRESHOLD && onClose) {
      onClose();
    } else if (info.offset.x > THRESHOLD && onDelete) {
      onDelete();
    }
    animate(x, 0, { type: 'spring', stiffness: 400, damping: 30 });
  };

  return (
    <div className="relative overflow-hidden rounded-[2rem]">
      {/* Background action strips */}
      <div className="absolute inset-0 flex items-center justify-between px-6 rounded-[2rem]">
        {onDelete && (
          <div className="flex items-center gap-1 text-red-500">
            <Trash2 className="w-4 h-4" />
            <span className="text-[10px] font-black uppercase">Eliminar</span>
          </div>
        )}
        {onClose && (
          <div className="flex items-center gap-1 text-orange-500 ml-auto">
            <span className="text-[10px] font-black uppercase">Cerrar</span>
            <X className="w-4 h-4" />
          </div>
        )}
      </div>
      <motion.div drag="x" dragConstraints={{ left: 0, right: 0 }} dragElastic={0.25}
        style={{ x }} onDragEnd={handleDragEnd} className="relative z-10">
        {children}
      </motion.div>
    </div>
  );
}

function ListView({ title, items, type, noItemsLabel, loading, onSelect, showArchived, onToggleArchived, seeAllLabel, showActiveLabel, onClose, onDelete, onEdit, classrooms }: any) {
  const accentColors: any = { activity: 'bg-emerald-500', form: 'bg-indigo-500', group: 'bg-blue-500' };
  const barColors: any = { activity: 'bg-emerald-400', form: 'bg-indigo-400' };

  return (
    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-black tracking-tight">{title}</h2>
        {onToggleArchived && (
          <button onClick={onToggleArchived}
            className={`text-[10px] font-black uppercase tracking-widest px-3 py-1.5 rounded-full transition-all ${showArchived ? 'bg-slate-700 text-white' : 'bg-slate-100 text-slate-400'}`}>
            {showArchived ? (showActiveLabel || 'Active only') : (seeAllLabel || 'See all')}
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

          const canDelete = (item.paid_count === 0 && item.submitted_count === 0) || (item.paid_count == null && item.submitted_count == null);
          const canClose = !isArchived && (onClose || onDelete);

          return (
            <SwipeableCard key={i}
              onClose={(onClose && !isArchived) ? () => onClose(item) : undefined}
              onDelete={(onDelete && canDelete) ? () => onDelete(item) : undefined}>
            <div onClick={() => onSelect?.(item)}
              className={`bg-white p-5 rounded-[2rem] shadow-sm border active:scale-[0.98] transition-transform cursor-pointer ${isArchived ? 'border-slate-100 opacity-60' : 'border-slate-100'}`}>
              <div className="flex items-center gap-3 mb-3">
                <div className={`w-10 h-10 rounded-2xl flex items-center justify-center text-white flex-shrink-0 text-[11px] font-black ${accentColors[type] || 'bg-slate-400'}`}>
                  {item.code ? item.code.slice(0, 3) : (type === 'group' ? <Users className="w-4 h-4" /> : null)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h4 className="font-black text-slate-800 text-sm leading-tight break-words line-clamp-2">{item.name || item.title}</h4>
                    {isArchived && <span className="text-[8px] font-black uppercase bg-slate-100 text-slate-400 px-1.5 py-0.5 rounded-full flex-shrink-0">{item.status}</span>}
                  </div>
                  <p className="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">
                    {item.code ? `${item.code} · ` : ''}{item.purpose || item.type || ''}
                    {item.kids_count != null && ` · ${item.kids_count} niños`}
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
              {(type === 'activity' || type === 'form') && classrooms && item.audience_classroom_ids?.length > 0 && (
                <div className="flex flex-wrap gap-1 mb-2">
                  {item.audience_classroom_ids.map((id: number) => {
                    const cls = classrooms.find((c: any) => c.id === id);
                    return cls ? (
                      <span key={id} className={`px-2 py-0.5 text-[9px] font-black rounded-full uppercase tracking-tight ${type === 'form' ? 'bg-indigo-50 text-indigo-700' : 'bg-emerald-50 text-emerald-700'}`}>
                        {cls.name}
                      </span>
                    ) : null;
                  })}
                </div>
              )}
              {pct !== null && (
                <div className="space-y-1">
                  <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full transition-all ${barColors[type] || 'bg-slate-400'}`} style={{ width: `${pct}%` }} />
                  </div>
                  <div className="text-[9px] font-black text-slate-300 text-right">{pct}% completado</div>
                </div>
              )}
            </div>
            </SwipeableCard>
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
