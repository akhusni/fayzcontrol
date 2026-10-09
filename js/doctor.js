/**
 * FAYZ MEDICAL HOUSE — DOCTOR'S POST & CLINICAL EMR ENGINE
 * Full clinical patient history, 206-drug prescriber (List Naznacheniy),
 * examination diary (dnevnik obxoda), and official discharge recommendations.
 */

(function () {
  'use strict';

  // Default Patient Dataset (Clean empty state)
  const DEFAULT_PATIENTS = [];

  // What a blank prints as. Blanks used to be filled with plausible findings
  // -- BP 120/80, "tremor present", ICD-10 F10.2, "no allergies" -- which on
  // a signed record cannot be told apart from something actually measured.
  const NOT_RECORDED = 'Qayd etilmagan';
  const genderLabel = (g) => g === 'female' ? 'Ayol' : (g === 'male' ? 'Erkak' : '—');
  const DISCHARGE_OUTCOMES = {
    recovered: "Sog'aydi", improved: 'Yaxshilandi', unchanged: "O'zgarishsiz",
    transferred: "Boshqa muassasaga o'tkazildi",
    against_medical_advice: 'Shifokor tavsiyasiga qarshi ketdi'
  };

  // Clinic Doctor Profiles (display only).
  //
  // These carried each doctor's plaintext password, which meant anyone who
  // could load this page could read the real login credentials for every
  // doctor in the clinic. The list now holds only what the picker needs to
  // show; the password is typed and verified server-side against its hash.
  const CLINIC_DOCTORS = [
    {
      username: 'dr_xusan',
      staff_id: 'STF-DOC-01',
      name: 'Dr. Umarov Xusan Payziboyevich',
      role: 'Bosh Shifokor / Narkolog-Psixiatr',
      specialty: 'Narkologiya va Psixiatriya',
      avatar: '👨‍⚕️'
    },
    {
      username: 'dr_farida',
      staff_id: 'STF-DOC-02',
      name: 'Dr. Shermuxamedova Farida Miraxatovna',
      role: 'Davolovchi Shifokor-Narkolog',
      specialty: 'Narkologiya',
      avatar: '👩‍⚕️'
    },
    {
      username: 'dr_yuliya',
      staff_id: 'STF-DOC-03',
      name: 'Dr. Vasina Yuliya Aleksandrovna',
      role: 'Davolovchi Shifokor-Psixiatr',
      specialty: 'Psixiatriya va Psixoterapiya',
      avatar: '👩‍⚕️'
    }
  ];

  // Master State
  const state = {
    doctors: [],
    authenticatedDoctor: null,
    activeDoctorId: '',
    patients: [],
    filteredPatients: [],
    selectedPatient: null,
    pharmacology: [],
    anamnesisMap: {},
    prescriptionsMap: {},
    // What the warehouse actually handed to each patient: {patientId: {status, rows}}.
    // Filled only from the server answer and never written to localStorage.
    dispensings: {},
    dailyNotesMap: {},
    currentFilter: 'all',
    searchQuery: '',
    activeTab: 'anamnesis',
    currentTheme: localStorage.getItem('fmh_theme') || 'night',
    newCase: {
      step: 1,
      intakeType: 'outpatient',
      prescriptions: []
    }
  };

  const STORAGE_KEYS = {
    THEME: 'fmh_theme',
    ANAMNESIS: 'FMH_ANAMNESIS_STORAGE_V2',
    PRESCRIPTIONS: 'FMH_PRESCRIPTIONS_STORAGE_V2',
    DAILY_NOTES: 'FMH_DAILY_NOTES_STORAGE_V2',
    ACTIVE_DOCTOR: 'fmh_active_doctor'
  };

  // Toast Notification Helper (Minimal, non-intrusive)
  // Delegates to the shared toast in js/fmh_dialogs.js: that one announces
  // messages via aria-live, keeps errors on screen long enough to read,
  // stacks instead of erasing an unread message, and can be dismissed.
  function showToast(message, type = 'success') {
    return window.FMH_Toast(message, type);
  }

  // =========================================================================
  // THEME ENGINE (DAY MODE ☀️ / NIGHT MODE 🌙)
  // =========================================================================
  function applyTheme(theme) {
    if (window.FMH_Theme) {
      window.FMH_Theme.set(theme);
      state.currentTheme = window.FMH_Theme.get();
      return;
    }
    state.currentTheme = theme;
    document.documentElement.setAttribute('data-theme', theme);
    document.body.className = `doctor-portal ${theme}-mode`;
    localStorage.setItem(STORAGE_KEYS.THEME, theme);

    const toggleBtn = document.getElementById('doctor-theme-toggle');
    if (toggleBtn) {
      if (theme === 'day') {
        toggleBtn.innerHTML = '<i class="fas fa-moon" style="color: #6366f1;"></i> <span>Tungi</span>';
        toggleBtn.title = "Tungi rejimga o'tish";
      } else {
        toggleBtn.innerHTML = '<i class="fas fa-sun" style="color: #fbbf24;"></i> <span>Kunduzgi</span>';
        toggleBtn.title = "Kunduzgi rejimga o'tish";
      }
    }
  }

  function toggleTheme() {
    if (window.FMH_Theme) {
      window.FMH_Theme.toggle();
      state.currentTheme = window.FMH_Theme.get();
      return;
    }
    const nextTheme = state.currentTheme === 'day' ? 'night' : 'day';
    applyTheme(nextTheme);
  }

  // =========================================================================
  // INITIALIZATION & DATA LOADING
  // =========================================================================
  async function init() {
    applyTheme(state.currentTheme);
    await checkDoctorAuth();
    updateDoctorIdentityDisplay();
    setupEventListeners();

    // Instant render with default data so UI is NEVER empty
    filterPatients('all');
    if (state.patients.length > 0) {
      selectPatient(state.patients[0]);
    }

    // Async load API data from MySQL without blocking UI
    try { await loadStaffDatabase(); } catch (e) { console.warn(e); }
    try { await loadPharmacologyDatabase(); } catch (e) { console.warn(e); }
    try { await loadPatientDatabase(); } catch (e) { console.warn(e); }
    try { await loadClinicalRecords(); } catch (e) { console.warn(e); }

    // Check URL hash / query param for pre-selected patient or new consultation
    const urlParams = new URLSearchParams(window.location.search);
    const targetPatientId = urlParams.get('patient') || urlParams.get('id');
    if (targetPatientId) {
      const match = state.patients.find(p => p.id === targetPatientId || p.patient_code === targetPatientId);
      if (match) selectPatient(match);
    }
    if (urlParams.get('action') === 'new_consultation' || window.location.hash === '#new-case') {
      setTimeout(() => openNewConsultationModal(), 350);
    }

    updateKPIs();

    // Auto-refresh every 10s
    setInterval(async () => {
      try {
        await loadPatientDatabase();
        updateKPIs();
      } catch (err) {}
    }, 10000);

    window.addEventListener('storage', (e) => {
      if (e.key === 'FMH_FACILITY_14BEDS_STORAGE_V18' || e.key === 'FMH_PATIENTS_V1') {
        loadPatientDatabase();
        updateKPIs();
      }
    });
  }

  async function loadStaffDatabase() {
    try {
      const res = await fetch('/api/staff');
      if (res.ok) {
        const staffList = await res.json();
        const docs = staffList.filter(s => 
          s.role === 'doctor' || s.role === 'chief_doctor'
        ).map(s => ({
          id: s.id,
          name: s.full_name,
          title: s.specialty || s.role || 'Shifokor',
          phone: s.phone || ''
        }));
        state.doctors = docs;
        if (state.authenticatedDoctor) {
          const match = docs.find(d => d.id === state.authenticatedDoctor.staff_id || d.name.toLowerCase().includes(state.authenticatedDoctor.name.toLowerCase()));
          if (match) {
            state.activeDoctorId = match.id;
          }
        } else if (docs.length > 0 && !state.activeDoctorId) {
          state.activeDoctorId = docs[0].id;
        }
        updateDoctorIdentityDisplay();
      }
    } catch (e) {
      console.warn("Could not load /api/staff", e);
    }
  }

  async function loadPharmacologyDatabase() {
    try {
      const res = await fetch('./data/pharmacology_db.json');
      const data = await res.json();
      state.pharmacology = data.medications || [];
      // Normalize
      state.pharmacology.forEach(m => {
        if (!m.name) m.name = m.trade_name_uz || m.trade_name || m.inn || 'Dori';
        if (!m.form) m.form = m.dosage_form || 'Tabletkalar';
      });
      populateDrugDataList();
      console.log(`[DoctorWorkstation] Loaded ${state.pharmacology.length} medications into prescription engine.`);
    } catch (err) {
      console.warn("Could not load pharmacology_db.json via fetch, trying fayz_house_meds.json", err);
      try {
        const res2 = await fetch('./data/fayz_house_meds.json');
        const data2 = await res2.json();
        state.pharmacology = data2.medications || [];
        populateDrugDataList();
      } catch (err2) {
        console.warn("Fallback medications used", err2);
      }
    }
  }

  function populateDrugDataList() {
    let datalist = document.getElementById('rx-medications-datalist');
    if (!datalist) {
      datalist = document.createElement('datalist');
      datalist.id = 'rx-medications-datalist';
      document.body.appendChild(datalist);
    }
    const sorted = [...state.pharmacology].sort((a, b) => {
      if (a.fayz_house_list && !b.fayz_house_list) return -1;
      if (!a.fayz_house_list && b.fayz_house_list) return 1;
      return (a.fayz_house_num || 999) - (b.fayz_house_num || 999);
    });

    const options = [];
    const seen = new Set();
    sorted.forEach(m => {
      const canonicalName = m.name || m.trade_name_uz || 'Dori';
      const key = canonicalName.trim().toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      const numPrefix = m.fayz_house_num ? `[№${m.fayz_house_num}] ` : '';
      options.push(`<option value="${canonicalName}">${numPrefix}${canonicalName}</option>`);
    });
    datalist.innerHTML = options.join('');
    setupDrugAutocomplete();
  }

  async function loadPatientDatabase() {
    try {
      const res = await fetch('/api/patients');
      if (res.ok) {
        const livePatients = await res.json();
        if (Array.isArray(livePatients)) {
          state.patients = livePatients;
          filterPatients(state.currentFilter);
          if (state.patients.length > 0) {
            const match = state.selectedPatient ? state.patients.find(p => p.id === state.selectedPatient.id) : null;
            if (!match) {
              selectPatient(state.patients[0]);
            } else {
              state.selectedPatient = match;
            }
          } else {
            state.selectedPatient = null;
            renderEmptyWorkstation();
          }
        }
      }
    } catch (e) {
      console.warn("Could not load /api/patients", e);
    }
  }

  async function loadClinicalRecords() {
    // 1. Anamnesis
    const savedAnamnesis = localStorage.getItem(STORAGE_KEYS.ANAMNESIS);
    if (savedAnamnesis) {
      try { state.anamnesisMap = JSON.parse(savedAnamnesis); } catch (e) {}
    }

    // 2. Prescriptions
    const savedRx = localStorage.getItem(STORAGE_KEYS.PRESCRIPTIONS);
    if (savedRx) {
      try { state.prescriptionsMap = JSON.parse(savedRx); } catch (e) {}
    }

    // 3. Daily Notes
    const savedNotes = localStorage.getItem(STORAGE_KEYS.DAILY_NOTES);
    if (savedNotes) {
      try { state.dailyNotesMap = JSON.parse(savedNotes); } catch (e) {}
    }
  }

  // =========================================================================
  // PATIENT SELECTION & FILTERING
  // =========================================================================
  function filterPatients(filterType = 'all') {
    state.currentFilter = filterType;
    document.querySelectorAll('.doc-pill-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-filter') === filterType);
    });

    // Update dynamic count badges on filter pills
    const allCount = state.patients.length;
    const inpatientsCount = state.patients.filter(p => p.status === 'active' && p.active_admission).length;
    const consultCount = state.patients.filter(p => p.service_type === 'consultation' || (p.latest_appointment && p.latest_appointment.service_type === 'consultation') || (!p.active_admission && p.referral_source === 'reception')).length;
    const outpatientsCount = state.patients.filter(p => p.status !== 'active' || !p.active_admission).length;
    const allergyCount = state.patients.filter(p => p.medical_allergies && p.medical_allergies.toLowerCase() !== 'yo\'q' && p.medical_allergies.trim() !== '').length;

    const activeDoc = state.authenticatedDoctor || state.doctors.find(d => d.id === state.activeDoctorId);
    const docName = activeDoc ? activeDoc.name.toLowerCase() : '';
    const docId = (state.authenticatedDoctor && state.authenticatedDoctor.staff_id) || state.activeDoctorId;
    const myCount = state.patients.filter(p => {
      const pDocId = p.doctor_id || (p.active_admission && p.active_admission.doctor_id) || p.consulting_doctor_id;
      const pDocName = (p.doctor_name || (p.active_admission && p.active_admission.doctor_name) || p.consulting_doctor_name || '').toLowerCase();
      return (docId && pDocId === docId) || (docName && pDocName.includes(docName));
    }).length;

    const elAll = document.getElementById('cnt-all');
    const elIn = document.getElementById('cnt-inpatient');
    const elMy = document.getElementById('cnt-my');
    const elConsult = document.getElementById('cnt-consultation');
    const elAllergy = document.getElementById('cnt-allergy');
    const elOut = document.getElementById('cnt-outpatient');
    if (elAll) elAll.textContent = allCount;
    if (elIn) elIn.textContent = inpatientsCount;
    if (elMy) elMy.textContent = myCount;
    if (elConsult) elConsult.textContent = consultCount;
    if (elAllergy) elAllergy.textContent = allergyCount;
    if (elOut) elOut.textContent = outpatientsCount;

    // Toggle search clear button
    const clearBtn = document.getElementById('btn-clear-search');
    if (clearBtn) {
      clearBtn.style.display = state.searchQuery ? 'block' : 'none';
    }

    let list = [...state.patients];

    if (filterType === 'inpatient') {
      list = list.filter(p => p.status === 'active' && p.active_admission);
    } else if (filterType === 'consultation') {
      list = list.filter(p => p.service_type === 'consultation' || (p.latest_appointment && p.latest_appointment.service_type === 'consultation') || (!p.active_admission && p.referral_source === 'reception'));
    } else if (filterType === 'outpatient') {
      list = list.filter(p => p.status !== 'active' || !p.active_admission);
    } else if (filterType === 'my_patients') {
      list = list.filter(p => {
        const pDocId = p.doctor_id || (p.active_admission && p.active_admission.doctor_id) || p.consulting_doctor_id;
        const pDocName = (p.doctor_name || (p.active_admission && p.active_admission.doctor_name) || p.consulting_doctor_name || '').toLowerCase();
        return (docId && pDocId === docId) || (docName && pDocName.includes(docName));
      });
    } else if (filterType === 'allergy') {
      list = list.filter(p => p.medical_allergies && p.medical_allergies.toLowerCase() !== 'yo\'q' && p.medical_allergies.trim() !== '');
    }

    if (state.searchQuery) {
      const q = state.searchQuery.toLowerCase();
      list = list.filter(p => 
        p.full_name.toLowerCase().includes(q) ||
        p.patient_code.toLowerCase().includes(q) ||
        (p.phone && p.phone.includes(q)) ||
        (p.active_admission && p.active_admission.bed_code && p.active_admission.bed_code.toLowerCase().includes(q)) ||
        (p.active_admission && p.active_admission.room_number && p.active_admission.room_number.includes(q)) ||
        (p.diagnosis && p.diagnosis.toLowerCase().includes(q)) ||
        (p.primary_diagnosis && p.primary_diagnosis.toLowerCase().includes(q)) ||
        (p.icd10_code && p.icd10_code.toLowerCase().includes(q))
      );
    }

    const oldData = state.filteredPatients ? JSON.stringify(state.filteredPatients) : null;
    const newData = JSON.stringify(list);
    
    if (oldData !== newData) {
      state.filteredPatients = list;
      const container = document.getElementById('doctor-patient-list');
      const scrollPos = container ? container.scrollTop : 0;
      
      renderPatientList();
      
      if (container) {
        requestAnimationFrame(() => {
          container.scrollTop = scrollPos;
        });
      }
    } else {
      state.filteredPatients = list;
    }
  }

  function clearSearch() {
    const input = document.getElementById('doctor-patient-search');
    if (input) input.value = '';
    state.searchQuery = '';
    const clearBtn = document.getElementById('btn-clear-search');
    if (clearBtn) clearBtn.style.display = 'none';
    filterPatients(state.currentFilter);
  }

  function renderPatientList() {
    const container = document.getElementById('doctor-patient-list');
    if (!container) return;

    if (state.filteredPatients.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; padding: 2rem 1rem; color: var(--text-muted); font-size: 0.85rem;">
          <i class="fas fa-search" style="font-size: 1.5rem; margin-bottom: 8px; opacity: 0.5;"></i>
          <div>Hech qanday bemor topilmadi</div>
        </div>
      `;
      return;
    }

    container.innerHTML = state.filteredPatients.map(p => {
      const isSelected = state.selectedPatient && state.selectedPatient.id === p.id;
      const isConsultation = p.service_type === 'consultation' || (p.latest_appointment && p.latest_appointment.service_type === 'consultation');
      const bedStr = p.active_admission ? `${p.active_admission.room_number}-xona ${p.active_admission.bed_code}` : (isConsultation ? `<span style="color:#0284c7; font-weight:700;"><i class="fas fa-stethoscope"></i> Konsultatsiya</span>` : 'Ambulator');
      const hasAllergy = p.medical_allergies && p.medical_allergies.toLowerCase() !== 'yo\'q' && p.medical_allergies.trim() !== '';

      // Nothing clinical is invented: a patient with no recorded vitals used
      // to show 120/80, 72 bpm, 99% here, which reads as a real measurement.
      const lv = p.latest_vitals || null;
      const bp = (lv && lv.vital_bp_systolic != null && lv.vital_bp_diastolic != null) ? `${lv.vital_bp_systolic}/${lv.vital_bp_diastolic}` : '—';
      const pulse = (lv && lv.vital_pulse != null) ? lv.vital_pulse : '—';
      const spo2 = (lv && lv.vital_spo2 != null) ? `${lv.vital_spo2}%` : '—';

      const notes = state.dailyNotesMap[p.id] || [];
      const condition = notes.length > 0 ? notes[0].condition : '';
      let statusClass = '';
      if (condition === 'moderate') statusClass = 'status-moderate';
      else if (condition === 'severe' || condition === 'critical') statusClass = 'status-critical';

      let dayCounterStr = '';
      if (p.active_admission && p.active_admission.admission_date) {
        const adDate = new Date(p.active_admission.admission_date);
        const today = new Date();
        const diffMs = today - adDate;
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24)) + 1;
        if (diffDays > 0) {
          dayCounterStr = `<span class="day-counter-badge" style="margin-left:6px; font-size:0.75rem; background:var(--bg-lighter); padding:2px 6px; border-radius:12px;">Day ${diffDays}</span>`;
        }
      }

      const diag = p.diagnosis || p.primary_diagnosis || '';
      const diagStr = diag.length > 40 ? diag.substring(0, 40) + '...' : diag;
      const diagHtml = diagStr ? `<div class="doc-pt-diagnosis" style="font-size:0.8rem; color:var(--text-secondary); margin-top:4px;"><i>${diagStr}</i></div>` : '';

      return `
        <div class="doc-patient-card ${isSelected ? 'active' : ''} ${statusClass}" onclick="window.FMH_Doctor.selectPatientById('${p.id}')">
          <div class="doc-pt-top">
            <div class="doc-pt-name">${p.full_name} ${dayCounterStr}</div>
            <span class="doc-bed-tag">${bedStr}</span>
          </div>
          <div class="doc-pt-details">
            <span><i class="fas fa-id-badge"></i> ${p.patient_code}</span> • 
            <span>${p.birth_year ? (new Date().getFullYear() - p.birth_year) + ' yosh' : 'N/A'}</span>
          </div>
          ${diagHtml}
          <div class="doc-pt-vitals">
            <span><i class="fas fa-heartbeat"></i> ${bp} mm</span>
            <span>• ${pulse} bpm</span>
            <span>• SpO2 ${spo2}</span>
          </div>
          ${hasAllergy ? `
            <div class="doc-pt-allergy-alert">
              <i class="fas fa-exclamation-triangle"></i> Allergiya: ${p.medical_allergies}
            </div>
          ` : ''}
        </div>
      `;
    }).join('');
  }

  async function selectPatient(patient) {
    state.selectedPatient = patient;
    state.dispensings[patient.id] = { status: 'loading', rows: [] };
    renderPatientList();
    renderWorkstation();

    // Fetch live clinical records from MySQL DB
    try {
      const res = await fetch(`/api/doctor/clinical/${patient.id}`);
      if (res.ok) {
        const bundle = await res.json();
        if (bundle.anamnesis) {
          state.anamnesisMap[patient.id] = bundle.anamnesis;
        }
        // These were previously guarded on `length > 0`, so when the database
        // legitimately returned an empty list — because another doctor had
        // deleted the record — the stale localStorage copy was kept and stayed
        // on screen. An array present in the response is now authoritative.
        if (Array.isArray(bundle.prescriptions)) {
          state.prescriptionsMap[patient.id] = bundle.prescriptions;
        }
        if (Array.isArray(bundle.daily_notes)) {
          state.dailyNotesMap[patient.id] = bundle.daily_notes.map(normalizeNote);
        }
        if (bundle.discharge_epicrisis) {
          if (!state.epicrisisMap) state.epicrisisMap = {};
          state.epicrisisMap[patient.id] = bundle.discharge_epicrisis;
        }
        // Dispensing history comes from the server only; an answer without
        // the list is shown as "could not load", never as "nothing given".
        state.dispensings[patient.id] = Array.isArray(bundle.dispensings)
          ? { status: 'ok', rows: bundle.dispensings }
          : { status: 'error', rows: [] };
        renderWorkstation();
      } else {
        state.dispensings[patient.id] = { status: 'error', rows: [] };
        renderDispensingHistory();
      }
    } catch (e) {
      console.warn("Could not fetch clinical bundle from MySQL API", e);
      state.dispensings[patient.id] = { status: 'error', rows: [] };
      renderDispensingHistory();
    }
  }

  function selectPatientById(id) {
    const p = state.patients.find(item => item.id === id || item.patient_code === id);
    if (p) selectPatient(p);
  }

  // =========================================================================
  // CLINICAL WORKSTATION RENDERING & LOGIC
  // =========================================================================
  function renderEmptyWorkstation() {
    const emptyView = document.getElementById('empty-workstation-view');
    const vitalsDash = document.getElementById('ws-vitals-dashboard');
    const jumpStrip = document.getElementById('ws-quick-jump-strip');
    if (emptyView) emptyView.style.display = 'flex';
    if (vitalsDash) vitalsDash.style.display = 'none';
    if (jumpStrip) jumpStrip.style.display = 'none';

    // hide tab panes and badges
    document.querySelectorAll('.ws-tab-pane').forEach(el => el.classList.remove('active'));
    ['tab-badge-rx', 'tab-badge-notes'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = 'none';
    });

    const avatarEl = document.getElementById('ws-patient-avatar');
    const nameEl = document.getElementById('ws-patient-name');
    const metaEl = document.getElementById('ws-patient-meta');

    if (avatarEl) avatarEl.textContent = '—';
    if (nameEl) nameEl.textContent = "Bemor Tanlanmagan";
    if (metaEl) {
      metaEl.innerHTML = `
        <span style="color: var(--text-muted); font-size: 0.85rem;">
          <i class="fas fa-info-circle"></i> Chap paneldan bemor kartasini tanlang yoki yangi konsultatsiya oching.
        </span>
      `;
    }

    const allergyBanner = document.getElementById('ws-allergy-banner');
    if (allergyBanner) allergyBanner.style.display = 'none';
  }

  function quickJump(tabName) {
    switchTab(tabName);
    if (tabName === 'diary') {
      const el = document.getElementById('note-dynamics');
      if (el) el.focus();
    } else if (tabName === 'prescriptions') {
      const el = document.getElementById('rx-drug-name');
      if (el) el.focus();
    } else if (tabName === 'anamnesis') {
      const el = document.getElementById('anam-complaints');
      if (el) el.focus();
    } else if (tabName === 'epicrisis') {
      const el = document.getElementById('epicrisis-home-rx');
      if (el) el.focus();
    }
  }

  function updateVitalsDashboard() {
    const dashboard = document.getElementById('ws-vitals-dashboard');
    if (!dashboard) return;

    const p = state.selectedPatient;
    if (!p) {
      dashboard.style.display = 'none';
      return;
    }

    const notes = state.dailyNotesMap[p.id] || [];
    if (notes.length === 0) {
      dashboard.style.display = 'none';
      return;
    }

    dashboard.style.display = 'grid';
    
    const latestNote = notes[0];
    const bp = latestNote.bp || '—';
    const pulse = latestNote.pulse || '—';
    const temp = latestNote.temp || '—';
    const spo2 = latestNote.spo2 || '—';
    const condition = latestNote.condition || '';

    const bpEl = document.getElementById('vital-bp-val');
    const pulseEl = document.getElementById('vital-pulse-val');
    const tempEl = document.getElementById('vital-temp-val');
    const spo2El = document.getElementById('vital-spo2-val');
    const conditionEl = document.getElementById('vital-condition-val');

    if (bpEl) bpEl.textContent = bp;
    if (pulseEl) pulseEl.textContent = pulse;
    if (tempEl) tempEl.textContent = temp;
    if (spo2El) spo2El.textContent = spo2;

    if (conditionEl) {
      const condMap = {
        satisfactory: 'Qoniqarli',
        moderate: 'O\'rta og\'ir',
        severe: 'Og\'ir',
        critical: 'Kritik'
      };
      conditionEl.textContent = condMap[condition] || condition || '—';
    }

    const setClass = (el, val, type) => {
      if (!el) return;
      el.className = '';
      // An unmeasured value gets no colour; green would read as "normal".
      if (val === '—' || isNaN(Number(val))) return;
      if (type === 'pulse') {
        if (val > 120) el.classList.add('vital-critical');
        else if (val > 100) el.classList.add('vital-elevated');
        else el.classList.add('vital-normal');
      } else if (type === 'temp') {
        if (val > 38.5) el.classList.add('vital-critical');
        else if (val > 37.5) el.classList.add('vital-elevated');
        else el.classList.add('vital-normal');
      } else if (type === 'spo2') {
        if (val < 90) el.classList.add('vital-critical');
        else if (val < 95) el.classList.add('vital-elevated');
        else el.classList.add('vital-normal');
      }
    };

    setClass(pulseEl, pulse, 'pulse');
    setClass(tempEl, temp, 'temp');
    setClass(spo2El, spo2, 'spo2');
  }

  function updateTabBadges() {
    const p = state.selectedPatient;
    if (!p) return;

    const rxCount = (state.prescriptionsMap[p.id] || []).length;
    const rxBadge = document.getElementById('tab-badge-rx');
    if (rxBadge) {
      rxBadge.textContent = rxCount;
      rxBadge.style.display = rxCount > 0 ? 'inline-flex' : 'none';
    }

    const notesCount = (state.dailyNotesMap[p.id] || []).length;
    const notesBadge = document.getElementById('tab-badge-notes');
    if (notesBadge) {
      notesBadge.textContent = notesCount;
      notesBadge.style.display = notesCount > 0 ? 'inline-flex' : 'none';
    }
  }

  function renderWorkstation() {
    const p = state.selectedPatient;
    if (!p) {
      renderEmptyWorkstation();
      return;
    }

    const emptyView = document.getElementById('empty-workstation-view');
    const jumpStrip = document.getElementById('ws-quick-jump-strip');
    if (emptyView) emptyView.style.display = 'none';
    if (jumpStrip) jumpStrip.style.display = 'flex';
    
    // Switch to active tab or default to anamnesis
    switchTab(state.activeTab || 'anamnesis');

    updateVitalsDashboard();
    updateTabBadges();

    // Set today date in Diary
    const dateEl = document.getElementById('diary-today-date');
    if (dateEl) {
      const now = new Date();
      dateEl.textContent = 'Bugun: ' + now.toLocaleDateString('uz-UZ', { year: 'numeric', month: 'long', day: 'numeric' });
    }

    // Header info
    const avatarEl = document.getElementById('ws-patient-avatar');
    const nameEl = document.getElementById('ws-patient-name');
    const metaEl = document.getElementById('ws-patient-meta');

    if (avatarEl) {
      const initials = p.full_name.replace('Bemor ', '').split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase() || 'PT';
      avatarEl.textContent = initials;
    }
    if (nameEl) nameEl.textContent = p.full_name;
    if (metaEl) {
      const age = p.birth_year ? `${new Date().getFullYear() - p.birth_year} yosh` : 'N/A';
      const gender = genderLabel(p.gender);
      const isConsultation = p.service_type === 'consultation' || (p.latest_appointment && p.latest_appointment.service_type === 'consultation');
      const bed = p.active_admission ? `${p.active_admission.room_number}-xona (${p.active_admission.bed_code} karavot)` : (isConsultation ? 'Konsultatsiya qabuli' : 'Ambulator');
      const program = p.active_admission ? p.active_admission.program_type.toUpperCase() : (isConsultation ? 'KONSULTATSIYA' : 'STANDART');

      let dayCounterStr = '';
      if (p.active_admission && p.active_admission.admission_date) {
        const adDate = new Date(p.active_admission.admission_date);
        const today = new Date();
        const diffDays = Math.max(1, Math.floor((today - adDate) / (1000 * 60 * 60 * 24)) + 1);
        dayCounterStr = `<span class="day-counter-badge" style="margin-left:4px;"><i class="fas fa-clock"></i> ${diffDays}-kun</span>`;
      }

      const diag = p.diagnosis || p.primary_diagnosis || '';
      const diagBadge = diag ? `<span class="status-pill" style="background: rgba(16, 185, 129, 0.12); color: var(--emerald); border: 1px solid rgba(16, 185, 129, 0.3);"><i class="fas fa-tag"></i> ${diag.length > 30 ? diag.substring(0, 30) + '...' : diag}</span>` : '';

      metaEl.innerHTML = `
        <span><strong style="color: var(--doctor-cyan-light); font-family: var(--font-mono); font-size: 0.95rem;">${p.patient_code}</strong></span> • 
        <span><i class="fas fa-user"></i> ${age} (${gender})</span> • 
        <span><i class="fas fa-phone-alt"></i> ${p.phone || '+998 90 000-00-00'}</span> • 
        <span><i class="fas fa-bed"></i> ${bed} ${dayCounterStr}</span> • 
        <span class="status-pill status-active">${program}</span>
        ${diagBadge ? ` • ${diagBadge}` : ''}
      `;
    }

    // Allergy Alert Banner in Workstation
    const allergyBanner = document.getElementById('ws-allergy-banner');
    if (allergyBanner) {
      const hasAllergy = p.medical_allergies && p.medical_allergies.toLowerCase() !== 'yo\'q' && p.medical_allergies.trim() !== '';
      if (hasAllergy) {
        allergyBanner.style.display = 'flex';
        allergyBanner.innerHTML = `
          <i class="fas fa-exclamation-triangle"></i>
          <div>
            <strong>DORI ALLERGIYASI OGOHLANTIRISHI:</strong> Bemor <strong>${p.medical_allergies}</strong> ga yuqori sezuvchanlikka ega. Ushbu preparatlar va ularning analoglarini tayinlash qat'iyan taqiqlanadi!
          </div>
        `;
      } else {
        allergyBanner.style.display = 'none';
      }
    }

    renderAnamnesisTab();
    renderPrescriptionsTab();
    renderDispensingHistory();
    renderDailyNotesTab();
    renderEpicrisisTab();
  }

  // --- TAB 1: ANAMNESIS & EXAMINATION ---
  function renderAnamnesisTab() {
    const p = state.selectedPatient;
    if (!p) return;

    const anamnesis = state.anamnesisMap[p.id] || {
      complaints: p.notes || '',
      anamnesis_morbi: '',
      anamnesis_vitae: '',
      allergic_status: p.medical_allergies || '',
      somatic_status: '',
      psychiatric_status: '',
      diagnosis_primary: '',
      diagnosis_secondary: '',
      icd10_code: ''
    };

    document.getElementById('anam-complaints').value = anamnesis.complaints || '';
    document.getElementById('anam-morbi').value = anamnesis.anamnesis_morbi || '';
    document.getElementById('anam-vitae').value = anamnesis.anamnesis_vitae || '';
    document.getElementById('anam-allergy').value = anamnesis.allergic_status || p.medical_allergies || '';
    document.getElementById('anam-somatic').value = anamnesis.somatic_status || '';
    document.getElementById('anam-psychiatric').value = anamnesis.psychiatric_status || '';
    document.getElementById('anam-diagnosis-primary').value = anamnesis.diagnosis_primary || '';
    document.getElementById('anam-diagnosis-secondary').value = anamnesis.diagnosis_secondary || '';
    document.getElementById('anam-icd10').value = anamnesis.icd10_code || '';
  }

  async function saveAnamnesis(silent = false) {
    const p = state.selectedPatient;
    if (!p) return false;

    const data = {
      patient_id: p.id,
      admission_id: p.active_admission ? p.active_admission.admission_id : null,
      doctor_id: (state.authenticatedDoctor && state.authenticatedDoctor.staff_id) || state.activeDoctorId,
      doctor_name: (state.authenticatedDoctor && state.authenticatedDoctor.name) || '',
      complaints: document.getElementById('anam-complaints')?.value || '',
      anamnesis_morbi: document.getElementById('anam-morbi')?.value || '',
      anamnesis_vitae: document.getElementById('anam-vitae')?.value || '',
      allergic_status: document.getElementById('anam-allergy')?.value || '',
      somatic_status: document.getElementById('anam-somatic')?.value || '',
      psychiatric_status: document.getElementById('anam-psychiatric')?.value || '',
      diagnosis_primary: document.getElementById('anam-diagnosis-primary')?.value || '',
      diagnosis_secondary: document.getElementById('anam-diagnosis-secondary')?.value || '',
      icd10_code: document.getElementById('anam-icd10')?.value || ''
    };

    // Saved only once the server has it.
    try {
      const res = await fetch('/api/doctor/anamnesis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        if (!silent) showToast(err.error || "Anamnez saqlanmadi. Qayta urinib ko'ring.", 'danger');
        return false;
      }
    } catch (e) {
      if (!silent) showToast("Server bilan aloqa yo'q — anamnez saqlanmadi.", 'danger');
      return false;
    }

    state.anamnesisMap[p.id] = data;
    localStorage.setItem(STORAGE_KEYS.ANAMNESIS, JSON.stringify(state.anamnesisMap));

    // Update patient allergy if edited
    p.medical_allergies = data.allergic_status;
    if (data.diagnosis_primary) p.diagnosis = data.diagnosis_primary;
    if (data.icd10_code) p.icd10_code = data.icd10_code;

    if (!silent) {
      showToast(`✅ <strong>${p.full_name}</strong> konsultatsiyasi va kasallik tarixi muvaffaqiyatli saqlandi!`);
    }
    renderPatientList();
    renderWorkstation();
    return true;
  }

  async function goToPrescriptionMenu() {
    const p = state.selectedPatient;
    if (!p) {
      showToast("Iltimos, avval bemorni tanlang!", "warning");
      return;
    }

    // Auto-save consultation intake
    await saveAnamnesis(true);

    // Switch to Prescriptions tab (Tab 2)
    switchTab('prescriptions');
    showToast("✅ Konsultatsiya xulosasi saqlandi. Endi retsept va dori-darmonlarni tayinlang.", "success");

    setTimeout(() => {
      const rxDrug = document.getElementById('rx-drug-name');
      if (rxDrug) {
        rxDrug.focus();
        rxDrug.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }, 150);
  }

  async function finalizeConsultation() {
    const p = state.selectedPatient;
    if (!p) {
      showToast("Iltimos, avval bemorni tanlang!", "warning");
      return;
    }

    await saveAnamnesis(true);
    const rxList = state.prescriptionsMap[p.id] || [];
    showToast(`🎉 <strong>${p.full_name}</strong> konsultatsiyasi va ${rxList.length} ta dori tayinlovi yakunlandi!`, "success");
  }

  // Smart Clinical Templates for Anamnesis
  function applyAnamnesisTemplate(key) {
    const templates = {
      complaints_alcohol: "Bosh og'rig'i, qo'llarda tremor, kuchli xumor, ko'ngil aynishi, umumiy holsizlik, yurak tez urishi va vegetativ buzilishlar.",
      complaints_abstinence: "Uyqusizlik, ichki bezovtalik, qaltiroq, disforiya, affektiv labillik, ishtahasizlik va terlash kuchayishi.",
      complaints_anxiety: "Tushkun kayfiyat, doimiy ichki xavotir, qo'rquv hissi, diqqat tarqoqligi, tungi uyquning to'liq buzilishi.",
      complaints_narcotic: "Suyak-mushaklarda qaqshash og'riqlari, bezovtalik, ko'z yoshlanishi, aksirish, qorindagi og'riqlar, disforik holat.",
      morbi_zapoy_5d: "Spirtli ichimliklarni uzluksiz iste'mol qilish davomiyligi 5 kun. Oxirgi doza 12 soat oldin. O'z vaqtida mustaqil to'xtata olmagan.",
      morbi_chronic_8y: "Spirtli ichimlik iste'mol qilish staji 8 yil, tolerantlik yuqori. O'tgan yili statsionar reabilitatsiya o'tagan.",
      morbi_first_intake: "Birinchi marta klinikaga murojaat qilishi. Toksik modda qabulidan so'ng ahvoli og'irlashgan.",
      morbi_relapse: "6 oylik remissiyadan so'ng stress fonida spirtli ichimlik qabul qilish qaytalangan (relaps).",
      vitae_standard: "O'tkazilgan yuqumli kasalliklar (OIV, Gepatit B/C) va o'tkir travmalar inkor qilinadi. Surunkali somatik kasalliklar yo'q.",
      allergy_none: "Yo'q",
      allergy_novocaine: "Novokain (terida toshmalar, qichishish)",
      allergy_penicillin: "Penitsillin guruhi antibiotiklari (Kvinke shishi xavfi)",
      somatic_moderate: "Teri qoplamalari giperemiyalangan, quruq. Til oq karash bilan qoplangan. Qo'llarda distal tremor. AQB 140/90, puls 92 ur/daq. Qorin yumshoq, og'riqsiz.",
      somatic_stable: "Teri va ko'rinadigan shilliq qavatlar tabiiy rangda. O'pka va yurak auskultatsiyasida patologik shovqinlar yo'q. AQB 120/80 mm Hg, puls 74 ur/daq, ritmik.",
      psych_anxious: "Ongi ravshan, o'z shaxsiga, makon va zamonga oriyentatsiyasi to'liq. Kayfiyati tushkun, affektiv fon labil, xavotirli. O'z holatiga tanqidiy munosabat sust.",
      psych_sedated: "Bemor sokin, tinchlangan, muloqotga kirishadi. Ko'z qarashi barqaror. Xavotir belgilari kamaygan, adekvat."
    };

    const text = templates[key];
    if (!text) return;

    if (key.startsWith('complaints_')) {
      const el = document.getElementById('anam-complaints');
      if (el) el.value = el.value ? el.value + ' ' + text : text;
    } else if (key.startsWith('morbi_')) {
      const el = document.getElementById('anam-morbi');
      if (el) el.value = el.value ? el.value + ' ' + text : text;
    } else if (key.startsWith('vitae_')) {
      const el = document.getElementById('anam-vitae');
      if (el) el.value = text;
    } else if (key.startsWith('allergy_')) {
      const el = document.getElementById('anam-allergy');
      if (el) el.value = text;
    } else if (key.startsWith('somatic_')) {
      const el = document.getElementById('anam-somatic');
      if (el) el.value = text;
    } else if (key.startsWith('psych_')) {
      const el = document.getElementById('anam-psychiatric');
      if (el) el.value = text;
    }

    showToast("⚡ Shablon matni kiritildi", "info");
  }

  function applyDiagnosisPreset(code, primaryText) {
    const icdEl = document.getElementById('anam-icd10');
    const diagEl = document.getElementById('anam-diagnosis-primary');
    if (icdEl) icdEl.value = code;
    if (diagEl) diagEl.value = primaryText;
    showToast(`✅ Tashxis tanlandi: ${code}`, "success");
  }

  // --- TAB 2: PRESCRIPTIONS & PHARMACOTHERAPY ---
  function renderPrescriptionsTab() {
    const p = state.selectedPatient;
    if (!p) return;

    let rxList = state.prescriptionsMap[p.id] || [];
    const tbody = document.getElementById('rx-table-body');
    if (!tbody) return;

    // Apply status filter if set
    const filter = state.currentRxFilter || 'all';
    if (filter === 'active') {
      rxList = rxList.filter(r => r.status === 'active');
    } else if (filter === 'completed') {
      rxList = rxList.filter(r => r.status === 'completed');
    } else if (filter === 'cancelled') {
      rxList = rxList.filter(r => r.status === 'cancelled');
    }

    if (rxList.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="8" style="text-align: center; padding: 2rem; color: var(--text-muted);">
            ${filter !== 'all' ? 'Ushbu toifadagi dorilar mavjud emas.' : 'Hozircha ushbu bemorga dori-darmonlar tayinlanmagan. Yuqoridagi formadan yangi dori yoki tayyor protokol qo\'shing.'}
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = rxList.map((rx, idx) => {
      const statusClass = rx.status === 'completed' ? 'status-completed' : (rx.status === 'cancelled' ? 'status-cancelled' : 'status-active');
      const statusLabel = rx.status === 'completed' ? 'Bajarildi' : (rx.status === 'cancelled' ? 'Bekor qilindi' : 'Faol');

      return `
        <tr>
          <td><strong style="color: var(--heading-color); font-size: 0.92rem;">${rx.medication_name}</strong><div style="font-size: 0.74rem; color: var(--text-muted);">${rx.form || ''}</div></td>
          <td><strong style="font-family: var(--font-mono); color: var(--doctor-cyan-light);">${rx.dosage}</strong></td>
          <td><span class="status-pill status-completed">${rx.route}</span></td>
          <td>${rx.frequency}<div style="font-size: 0.74rem; color: var(--text-muted);">${rx.timing || ''}</div></td>
          <td><strong>${rx.duration_days} kun</strong></td>
          <td>${rxQtyCell(rx)}</td>
          <td><span class="status-pill ${statusClass}">${statusLabel}</span></td>
          <td>
            <div style="display: flex; gap: 4px;">
              ${rx.status === 'active' ? `
                <button class="btn-doc-primary" style="padding: 3px 8px; font-size: 0.72rem;" onclick="window.FMH_Doctor.toggleRxStatus('${p.id}', '${rx.id}', 'completed')" title="Muolaja bajarildi deb belgilash"><i class="fas fa-check"></i></button>
                <button class="btn-doc-outline" style="padding: 3px 8px; font-size: 0.72rem;" onclick="window.FMH_Doctor.toggleRxStatus('${p.id}', '${rx.id}', 'cancelled')" title="Bekor qilish"><i class="fas fa-ban"></i></button>
              ` : `
                <button class="btn-doc-outline" style="padding: 3px 8px; font-size: 0.72rem;" onclick="window.FMH_Doctor.toggleRxStatus('${p.id}', '${rx.id}', 'active')" title="Qayta faollashtirish"><i class="fas fa-redo"></i></button>
              `}
              <button class="btn-doc-danger" style="padding: 3px 8px; font-size: 0.72rem;" onclick="window.FMH_Doctor.deletePrescription('${p.id}', '${rx.id}')" title="O'chirish"><i class="fas fa-trash"></i></button>
            </div>
          </td>
        </tr>
      `;
    }).join('');
  }

  function filterRxTable(status) {
    state.currentRxFilter = status;
    document.querySelectorAll('.rx-filter-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-rx-filter') === status);
    });
    renderPrescriptionsTab();
  }

  // --- WAREHOUSE LINK & DISPENSING HISTORY ---------------------------------
  // The doctor may tie an order to a warehouse item and a total quantity. That
  // is information for the prescriber and the person handing the drug out:
  // saving an order never removes anything from the shelf (stock leaves only
  // when it is handed out, see inventory.py), and a shortage is a warning,
  // never a block. Nothing here is guessed: no item or quantity means none.
  const wh = { item: null, results: [], seq: 0, timer: null, autoName: '', ready: false };

  // 12 -> "12", 2.5 -> "2.5": quantities can be fractions (ml, half tablets).
  function fmtQty(v) {
    if (v === null || v === undefined || v === '') return '—';
    const n = Number(v);
    if (!isFinite(n)) return '—';
    return String(Math.round(n * 1000) / 1000);
  }

  // "2026-10-10T14:23:11" -> "10.10.2026 14:23"; anything else is shown as sent.
  function fmtDateTime(v) {
    if (!v) return '—';
    const m = String(v).match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
    return m ? `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}` : escapeHtml(v);
  }

  // The server decides low / out (it knows about expired lots); this only maps
  // its stock_status to a colour. 'out' also covers nothing usable on hand.
  function whStockClass(item) {
    const a = Number(item.available_quantity);
    if (item.stock_status === 'out' || !(a > 0)) return 'out';
    if (item.stock_status === 'low') return 'low';
    return 'ok';
  }

  function whCurrentQuery() {
    const own = (document.getElementById('rx-wh-search')?.value || '').trim();
    return own || (document.getElementById('rx-drug-name')?.value || '').trim();
  }

  function whQuery() {
    clearTimeout(wh.timer);
    const text = whCurrentQuery();
    if (text.length < 2) {
      wh.seq++;
      wh.results = [];
      renderWhResults();
      return;
    }
    wh.timer = setTimeout(() => runWhSearch(text), 300);
  }

  async function runWhSearch(text) {
    const mySeq = ++wh.seq;
    let results = null; // null = the warehouse could not be read
    try {
      const res = await fetch(`/api/warehouse/availability?q=${encodeURIComponent(text)}&limit=8`);
      if (res.ok) {
        const data = await res.json();
        results = Array.isArray(data.items) ? data.items : [];
      }
    } catch (e) { /* offline: handled as unavailable below */ }
    if (mySeq !== wh.seq) return; // a newer search has started
    wh.results = results;
    // After a pick from the drug list: link the item automatically only when
    // exactly one warehouse item has that very name.
    if (results && wh.autoName && !wh.item) {
      const exact = results.filter(i => String(i.name || '').trim().toLowerCase() === wh.autoName);
      if (exact.length === 1) selectWarehouseItem(exact[0]);
    }
    wh.autoName = '';
    renderWhResults();
  }

  function renderWhResults() {
    const box = document.getElementById('rx-wh-results');
    if (!box) return;
    if (wh.results === null) {
      box.innerHTML = `<div class="rx-wh-hint">Ombor ma'lumoti hozir mavjud emas. Retsept ombor bilan bog'lanmasdan saqlanadi.</div>`;
      return;
    }
    if (!wh.results.length) {
      box.innerHTML = whCurrentQuery().length >= 2 ? `<div class="rx-wh-hint">Omborda mos dori topilmadi.</div>` : '';
      return;
    }
    box.innerHTML = `<div class="rx-wh-hint" style="width: 100%; margin: 0;"><i class="fas fa-check-circle" style="color: var(--emerald);"></i> Omborda bor — bog'lash uchun tanlang:</div>` +
      wh.results.map(it => {
        const cls = whStockClass(it);
        const unit = it.base_unit ? ' ' + it.base_unit : '';
        const label = [it.name, it.strength, it.form].filter(Boolean).join(' · ');
        const badge = cls === 'out' ? 'Tugagan' : `${fmtQty(it.available_quantity)}${unit}`;
        const sel = wh.item && wh.item.id === it.id ? ' is-selected' : '';
        return `<button type="button" class="rx-wh-chip${sel}" data-wh-id="${escapeHtml(it.id)}">
          <i class="fas fa-warehouse"></i> ${escapeHtml(label)}
          <span class="rx-wh-badge ${cls}">${escapeHtml(badge)}</span>
        </button>`;
      }).join('');
  }

  function updateWhStatus() {
    const el = document.getElementById('rx-wh-status');
    if (!el) return;
    const item = wh.item;
    if (!item) {
      el.innerHTML = `Ombor dorisi tanlanmagan.<span class="rx-wh-note">Retsept ombordan hech narsa olmaydi: dori faqat berilganda chiqariladi.</span>`;
      return;
    }
    const unit = escapeHtml(item.base_unit || '');
    const avail = Number(item.available_quantity) || 0;
    const qtyRaw = (document.getElementById('rx-qty')?.value || '').trim();
    const qty = qtyRaw === '' ? null : Number(qtyRaw);
    const notes = [];
    let line;
    if (whStockClass(item) === 'out') {
      line = `<span class="out">Ombordan tugagan</span>`;
      notes.push("Ogohlantirish xolos: retseptni baribir saqlash mumkin.");
    } else if (qty !== null && isFinite(qty) && qty > avail) {
      line = `<span class="out">Yetarli emas: ${fmtQty(avail)} mavjud, ${fmtQty(qty)} kerak</span>`;
      notes.push("Ogohlantirish xolos: retseptni baribir saqlash mumkin.");
    } else if (whStockClass(item) === 'low') {
      line = `<span class="low">Omborda: ${fmtQty(avail)} ${unit} (kam qolgan)</span>`;
    } else {
      line = `<span class="ok">Omborda: ${fmtQty(avail)} ${unit}</span>`;
    }
    if (qty !== null && isFinite(qty) && !item.allow_fraction && qty !== Math.floor(qty)) {
      notes.push("Bu dori faqat butun sonda beriladi.");
    }
    el.innerHTML = `<strong>${escapeHtml(item.name)}</strong>
      <button type="button" class="rx-wh-clear" data-wh-clear="1" title="Tanlovni bekor qilish"><i class="fas fa-times"></i></button><br>
      ${line}${notes.map(n => `<span class="rx-wh-note">${escapeHtml(n)}</span>`).join('')}`;
  }

  function selectWarehouseItem(item) {
    wh.item = item;
    wh.autoName = '';
    const unitEl = document.getElementById('rx-qty-unit');
    if (unitEl) unitEl.value = item.base_unit || '';
    // The typed name is kept (it is what the nurse sheet shows); only an empty
    // name is filled from the warehouse item.
    const nameEl = document.getElementById('rx-drug-name');
    if (nameEl && !nameEl.value.trim()) nameEl.value = item.name || '';
    renderWhResults();
    updateWhStatus();
  }

  function clearWarehouseItem() {
    wh.item = null;
    const unitEl = document.getElementById('rx-qty-unit');
    if (unitEl) unitEl.value = '';
    renderWhResults();
    updateWhStatus();
  }

  function resetWarehousePanel() {
    clearTimeout(wh.timer);
    wh.seq++;
    wh.item = null;
    wh.results = [];
    wh.autoName = '';
    ['rx-wh-search', 'rx-qty', 'rx-qty-unit'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    renderWhResults();
    updateWhStatus();
  }

  // The drug list (pharmacology) pick keeps working as before; on top of it the
  // warehouse is searched by that name. An item the doctor already chose by
  // hand is not replaced, and a late answer never overrides a manual choice.
  function whOnDrugPicked(med) {
    if (!med || wh.item) return;
    const name = String(med.name || med.paper_name || '').trim();
    if (name.length < 2) return;
    const own = document.getElementById('rx-wh-search');
    if (own) own.value = '';
    wh.autoName = name.toLowerCase();
    clearTimeout(wh.timer);
    runWhSearch(name);
  }

  function whOnNameTyped(value) {
    if (!value || !value.trim()) {
      clearTimeout(wh.timer);
      wh.seq++;
      wh.results = [];
      if (wh.item) clearWarehouseItem(); else renderWhResults();
      return;
    }
    if (!(document.getElementById('rx-wh-search')?.value || '').trim()) whQuery();
  }

  function setupWarehousePanel() {
    if (wh.ready) return;
    const search = document.getElementById('rx-wh-search');
    const qty = document.getElementById('rx-qty');
    const results = document.getElementById('rx-wh-results');
    const status = document.getElementById('rx-wh-status');
    if (!search || !qty || !results || !status) return;
    wh.ready = true;
    search.addEventListener('input', whQuery);
    qty.addEventListener('input', updateWhStatus);
    // Item ids come from the server: they are read from data-attributes here,
    // never pasted into an inline handler.
    results.addEventListener('click', (e) => {
      const btn = e.target.closest('.rx-wh-chip');
      if (!btn || !Array.isArray(wh.results)) return;
      const id = btn.getAttribute('data-wh-id');
      if (wh.item && wh.item.id === id) { clearWarehouseItem(); return; }
      const item = wh.results.find(i => i.id === id);
      if (item) selectWarehouseItem(item);
    });
    status.addEventListener('click', (e) => {
      if (e.target.closest('[data-wh-clear]')) clearWarehouseItem();
    });
    updateWhStatus();
  }

  // Prescribed / given / left for one order, plus what the shelf holds now.
  function rxQtyCell(rx) {
    const hasQty = rx.quantity_prescribed !== null && rx.quantity_prescribed !== undefined && rx.quantity_prescribed !== '';
    const unit = rx.quantity_unit || rx.available_unit || '';
    const u = unit ? ' ' + escapeHtml(unit) : '';
    const lines = [];
    if (hasQty) {
      lines.push(`Buyurilgan: <strong>${fmtQty(rx.quantity_prescribed)}${u}</strong>`);
    } else {
      lines.push(`<span class="rx-qty-muted">Miqdor ko'rsatilmagan</span>`);
    }
    if (rx.quantity_dispensed !== null && rx.quantity_dispensed !== undefined && (hasQty || Number(rx.quantity_dispensed) > 0)) {
      lines.push(`Berilgan: <strong>${fmtQty(rx.quantity_dispensed)}${u}</strong>`);
    }
    if (hasQty && rx.remaining_quantity !== null && rx.remaining_quantity !== undefined) {
      lines.push(`Qolgan: <strong>${fmtQty(rx.remaining_quantity)}${u}</strong>`);
    }
    if ((rx.status || 'active') === 'active' && rx.available_quantity !== null && rx.available_quantity !== undefined) {
      const avail = Number(rx.available_quantity) || 0;
      const need = (rx.remaining_quantity !== null && rx.remaining_quantity !== undefined)
        ? Number(rx.remaining_quantity)
        : (hasQty ? Number(rx.quantity_prescribed) : null);
      if (avail <= 0) {
        lines.push(`<span class="rx-wh-badge out">Ombordan tugagan</span>`);
      } else if (need !== null && need > avail) {
        lines.push(`<span class="rx-wh-badge out">Omborda yetarli emas: ${fmtQty(avail)}${u}</span>`);
      } else {
        lines.push(`<span class="rx-wh-badge ok">Omborda: ${fmtQty(avail)}${u}</span>`);
      }
    }
    return `<div class="rx-qty-cell">${lines.join('<br>')}</div>`;
  }

  // "Berilgan dori va materiallar": the server's dispensing rows for the open
  // patient, exactly as sent (actual quantity, unit, lot). Reversed rows stay
  // visible, struck through, with the reason.
  function renderDispensingHistory() {
    const tbody = document.getElementById('dsp-table-body');
    const p = state.selectedPatient;
    if (!tbody || !p) return;
    const rec = state.dispensings[p.id];
    const message = (text) => {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 1.5rem; color: var(--text-muted);">${text}</td></tr>`;
    };
    if (!rec || rec.status === 'loading') { message('Yuklanmoqda...'); return; }
    if (rec.status === 'error') { message("Berilgan dorilar ro'yxatini yuklab bo'lmadi."); return; }
    if (!rec.rows.length) { message('Hali dori berilmagan.'); return; }

    tbody.innerHTML = rec.rows.map(d => {
      const reversed = d.status === 'reversed';
      const strike = reversed ? ' dsp-strike' : '';
      const dose = [d.dosage, d.route, d.frequency, d.instructions].filter(Boolean).map(escapeHtml).join(' • ');
      const lots = Array.isArray(d.batch_numbers) && d.batch_numbers.length ? d.batch_numbers.map(escapeHtml).join(', ') : '—';
      const status = reversed
        ? `<span class="status-pill status-cancelled">Qaytarilgan</span>
           <span class="dsp-note">${fmtDateTime(d.reversed_at)}${d.reversed_by ? ' · ' + escapeHtml(d.reversed_by) : ''}${d.reverse_reason ? '<br>Sabab: ' + escapeHtml(d.reverse_reason) : ''}</span>`
        : `<span class="status-pill status-active">Berilgan</span>`;
      return `
        <tr class="${reversed ? 'dsp-reversed' : ''}">
          <td style="white-space: nowrap;"><span class="${strike.trim()}">${fmtDateTime(d.dispensed_at)}</span></td>
          <td><strong class="${strike.trim()}">${escapeHtml(d.item_name || '—')}</strong></td>
          <td><strong class="${strike.trim()}">${fmtQty(d.quantity)}${d.unit ? ' ' + escapeHtml(d.unit) : ''}</strong></td>
          <td><span class="${strike.trim()}">${dose || '—'}</span></td>
          <td>${escapeHtml(d.prescribed_by || '—')}</td>
          <td>${escapeHtml(d.dispensed_by || '—')}</td>
          <td>${lots}</td>
          <td>${status}</td>
        </tr>`;
    }).join('');
  }

  function setRxField(field, value) {
    const el = document.getElementById(`rx-${field}`);
    if (el) {
      el.value = value;
      el.focus();
    }
  }

  function findMedication(query) {
    if (!query) return null;
    if (window.FMH_MedSearch) {
      return window.FMH_MedSearch.findBestMatch(state.pharmacology, query);
    }
    const q = query.trim().toLowerCase();
    return state.pharmacology.find(m => 
      (m.name && m.name.toLowerCase() === q) ||
      (m.paper_name && m.paper_name.toLowerCase() === q) ||
      (m.trade_name_uz && m.trade_name_uz.toLowerCase() === q) ||
      (m.trade_name_ru && m.trade_name_ru.toLowerCase() === q) ||
      (m.name && m.name.toLowerCase().startsWith(q)) ||
      (m.paper_name && m.paper_name.toLowerCase().startsWith(q)) ||
      (m.trade_name_uz && m.trade_name_uz.toLowerCase().startsWith(q)) ||
      (m.trade_name_ru && m.trade_name_ru.toLowerCase().startsWith(q))
    ) || null;
  }

  function applyMedicationToRxForm(med) {
    if (!med) return;
    const input = document.getElementById('rx-drug-name');
    if (input) {
      input.value = med.name || med.paper_name;
      const clearBtn = input.closest('.fmh-med-search-wrapper')?.querySelector('.fmh-med-clear-btn');
      if (clearBtn) clearBtn.style.display = 'flex';
    }
    if (med.form || med.dosage_form) {
      const f = med.form || med.dosage_form;
      const formEl = document.getElementById('rx-form');
      if (formEl) {
        // Match existing option or add
        let found = false;
        for (let i = 0; i < formEl.options.length; i++) {
          if (formEl.options[i].value.toLowerCase().includes(f.toLowerCase())) {
            formEl.selectedIndex = i;
            found = true;
            break;
          }
        }
        if (!found) formEl.value = f;
      }
    }
    if (med.default_dosage) {
      const el = document.getElementById('rx-dosage');
      if (el) el.value = med.default_dosage;
    }
    if (med.default_route) {
      const el = document.getElementById('rx-route');
      if (el) {
        let found = false;
        for (let i = 0; i < el.options.length; i++) {
          if (el.options[i].value.toLowerCase().includes(med.default_route.toLowerCase())) {
            el.selectedIndex = i;
            found = true;
            break;
          }
        }
        if (!found) el.value = med.default_route;
      }
    }
    if (med.default_frequency) {
      const el = document.getElementById('rx-frequency');
      if (el) {
        let found = false;
        for (let i = 0; i < el.options.length; i++) {
          if (el.options[i].value.toLowerCase().includes(med.default_frequency.toLowerCase())) {
            el.selectedIndex = i;
            found = true;
            break;
          }
        }
        if (!found) el.value = med.default_frequency;
      }
    }
    if (med.default_timing) {
      const el = document.getElementById('rx-timing');
      if (el) {
        let found = false;
        for (let i = 0; i < el.options.length; i++) {
          if (el.options[i].value.toLowerCase().includes(med.default_timing.toLowerCase())) {
            el.selectedIndex = i;
            found = true;
            break;
          }
        }
        if (!found) el.value = med.default_timing;
      }
    }
    if (med.default_duration) {
      const el = document.getElementById('rx-duration');
      if (el) el.value = med.default_duration;
    }
    if (med.instructions) {
      const el = document.getElementById('rx-instructions');
      if (el) el.value = med.instructions;
    }

    whOnDrugPicked(med);
    updateDrugDetailsBanner(med);
  }

  function quickSelectMed(nameOrNum) {
    const med = findMedication(String(nameOrNum));
    if (med) {
      clearWarehouseItem(); // a different drug: the earlier warehouse link no longer applies
      applyMedicationToRxForm(med);
      showToast(`⚡ "${med.name}" formaga tezkor yuklandi!`, 'success');
    } else {
      showToast(`Dori topilmadi: "${nameOrNum}"`, 'warning');
    }
  }

  // The drug safety card used escapeHtml(), which only exists privately
  // inside med_search_engine.js. The ReferenceError stopped the card (and
  // its allergy check) from ever rendering. This page needs its own copy.
  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function updateDrugDetailsBanner(med) {
    const banner = document.getElementById('rx-active-drug-card');
    if (!banner || !med) return;

    const p = state.selectedPatient;
    let allergyAlertHTML = '';
    const numBadge = med.fayz_house_num ? `<span style="display:inline-flex; align-items:center; justify-content:center; padding:2px 7px; background:#0b3b60; color:#fff; border-radius:4px; font-weight:800; font-size:0.75rem;">№${med.fayz_house_num}</span>` : '';
    const isPsychotropic = med.prescription_type === 'Rx_Strict_Psychotropic';
    const badgeHTML = isPsychotropic
      ? `<span style="padding:2px 8px; border-radius:5px; background:#fef2f2; color:#dc2626; border:1px solid #fecaca; font-weight:700; font-size:0.72rem;"><i class="fas fa-exclamation-triangle"></i> Qat'iy Psixotrop (Nazoratda)</span>`
      : (med.prescription_type === 'Rx_Standard'
        ? `<span style="padding:2px 8px; border-radius:5px; background:#eff6ff; color:#2563eb; border:1px solid #bfdbfe; font-weight:700; font-size:0.72rem;"><i class="fas fa-file-prescription"></i> Retseptli (Rx)</span>`
        : `<span style="padding:2px 8px; border-radius:5px; background:#f0fdf4; color:#16a34a; border:1px solid #bbf7d0; font-weight:700; font-size:0.72rem;"><i class="fas fa-check-circle"></i> Retseptsiz (OTC)</span>`);

    // Allergen check
    if (p && p.medical_allergies && p.medical_allergies.toLowerCase() !== 'yo\'q') {
      const allergy = p.medical_allergies.toLowerCase();
      const medText = `${med.name} ${med.paper_name || ''} ${med.inn || ''} ${med.trade_name_ru || ''}`.toLowerCase();
      const isDangerous = (medText.includes('novo') && allergy.includes('novo')) ||
                          (medText.includes('peni') && allergy.includes('peni')) ||
                          (medText.includes('sulfa') && allergy.includes('sulfa')) ||
                          (medText.includes('aspirin') && allergy.includes('aspirin')) ||
                          (allergy.split(/[,;\s]+/).some(token => token.length > 3 && medText.includes(token)));

      if (isDangerous) {
        allergyAlertHTML = `
          <div style="margin-top:8px; padding:8px 12px; background:#fef2f2; border:1px solid #f87171; border-radius:6px; color:#b91c1c; font-size:0.78rem; font-weight:700; display:flex; align-items:center; gap:8px;">
            <i class="fas fa-exclamation-circle" style="font-size:1.1rem; color:#ef4444;"></i>
            <span>⚠️ DIQQAT! Ushbu bemorda allergik xavf aniqlandi: <u>"${escapeHtml(p.medical_allergies)}"</u>!</span>
          </div>
        `;
        showToast(`⚠️ <strong>DIQQAT:</strong> Bemor allergiyasi mavjud: "${p.medical_allergies}"!`, 'danger');
      } else {
        allergyAlertHTML = `
          <div style="margin-top:6px; font-size:0.74rem; color:#16a34a; display:flex; align-items:center; gap:6px;">
            <i class="fas fa-shield-alt"></i> Allergik qarshi ko'rsatma aniqlanmadi (Bemorda: "${escapeHtml(p.medical_allergies)}")
          </div>
        `;
      }
    }

    const paperDisplay = med.paper_name && med.paper_name !== med.name ? `<span style="color:#0284c7; font-weight:600;">• Qog'ozda: ${escapeHtml(med.paper_name)}</span>` : '';
    const innDisplay = med.inn ? `<span style="color:#64748b;">• МНН: ${escapeHtml(med.inn)}</span>` : '';

    banner.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px; flex-wrap:wrap;">
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
          ${numBadge}
          <strong style="color:var(--heading-color, #0f172a); font-size:0.96rem;">${escapeHtml(med.name)}</strong>
          ${paperDisplay}
          ${innDisplay}
          ${badgeHTML}
        </div>
        <button type="button" onclick="window.FMH_Doctor.clearDrugDetailsBanner()" style="background:transparent; border:none; color:#94a3b8; cursor:pointer; font-size:0.85rem;" title="Yopish">
          <i class="fas fa-times"></i>
        </button>
      </div>
      <div style="display:flex; gap:12px; font-size:0.76rem; color:var(--text-muted, #64748b); margin-top:5px; flex-wrap:wrap;">
        <span><i class="fas fa-pills" style="color:#0d9488;"></i> <b>Shakli:</b> ${escapeHtml(med.form || med.dosage_form || '—')}</span>
        <span><i class="fas fa-syringe" style="color:#0d9488;"></i> <b>Standart:</b> ${escapeHtml(med.default_dosage || '—')} (${escapeHtml(med.default_route || '—')})</span>
        <span><i class="fas fa-clock" style="color:#0d9488;"></i> <b>Qabul:</b> ${escapeHtml(med.default_frequency || '—')} • ${escapeHtml(med.default_timing || '—')}</span>
      </div>
      ${allergyAlertHTML}
    `;
    banner.style.display = 'block';
  }

  function clearDrugDetailsBanner() {
    const banner = document.getElementById('rx-active-drug-card');
    if (banner) {
      banner.style.display = 'none';
      banner.innerHTML = '';
    }
  }

  function onDrugNameInput(value) {
    whOnNameTyped(value);
    if (!value || !value.trim()) {
      clearDrugDetailsBanner();
      return;
    }
    // DO NOT OVERWRITE input.value or auto-populate form while user is actively typing!
    // Autocomplete dropdown handles display and suggestions.
  }

  function onDrugNameChange(value) {
    if (!value || !value.trim()) {
      clearDrugDetailsBanner();
      return;
    }
    const val = value.trim();
    // Only resolve on change if it is an explicit clinic number (e.g. 18 or №18)
    const isNum = /^[№#\s]*\d+$/.test(val);
    if (isNum) {
      const match = findMedication(val);
      if (match) {
        applyMedicationToRxForm(match);
        return;
      }
    }

    // Or if it is an exact match (or exact transliterated match) with a known drug:
    const valLow = val.toLowerCase();
    const exact = state.pharmacology.find(m => {
      const n = (m.name || '').toLowerCase();
      const p = (m.paper_name || '').toLowerCase();
      if (n === valLow || p === valLow) return true;
      if (window.FMH_MedSearch) {
        if (window.FMH_MedSearch.cyrToLat(valLow) === n || window.FMH_MedSearch.latToCyr(n) === valLow) return true;
        if (p && (window.FMH_MedSearch.cyrToLat(valLow) === p || window.FMH_MedSearch.latToCyr(p) === valLow)) return true;
      }
      return false;
    });

    if (exact) {
      applyMedicationToRxForm(exact);
    }
  }

  // --- 88 TA KLINIKA DORILARI MODAL OYNASI ---
  let activeClinicCat = 'all';
  let clinicMedsFilterQuery = '';

  function openClinicMedsModal() {
    let modal = document.getElementById('clinic-meds-modal');
    if (!modal) {
      createClinicMedsModalDOM();
      modal = document.getElementById('clinic-meds-modal');
    }
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    renderClinicMedsList();
  }

  function closeClinicMedsModal() {
    const modal = document.getElementById('clinic-meds-modal');
    if (modal) modal.style.display = 'none';
    document.body.style.overflow = '';
  }

  function createClinicMedsModalDOM() {
    const modalDiv = document.createElement('div');
    modalDiv.id = 'clinic-meds-modal';
    modalDiv.className = 'modal-backdrop open';
    modalDiv.style.cssText = 'position: fixed; inset: 0; background: rgba(15, 23, 42, 0.75); backdrop-filter: blur(4px); z-index: 99999; display: flex; align-items: center; justify-content: center; padding: 20px;';
    modalDiv.innerHTML = `
      <div style="background: var(--card-bg, #ffffff); border: 1px solid var(--border-color, #cbd5e1); border-radius: 16px; width: 100%; max-width: 960px; max-height: 90vh; display: flex; flex-direction: column; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.35); overflow: hidden;">
        <!-- Header -->
        <div style="padding: 1rem 1.4rem; background: linear-gradient(135deg, #0b3b60, #0d9488); color: #ffffff; display: flex; align-items: center; justify-content: space-between;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <i class="fas fa-pills" style="font-size: 1.4rem; color: #38bdf8;"></i>
            <div>
              <h3 style="margin: 0; font-size: 1.1rem; font-weight: 800; font-family: var(--font-heading);">Fayz Medical House — 88 ta Klinika Dorilari Katalogi</h3>
              <span style="font-size: 0.76rem; opacity: 0.85;">Rasmiy ro'yxatdan tezkor retsept va muolaja tayinlash</span>
            </div>
          </div>
          <button onclick="window.FMH_Doctor.closeClinicMedsModal()" style="background: rgba(255,255,255,0.15); border: none; color: #fff; width: 32px; height: 32px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; justify-content: center;">
            <i class="fas fa-times"></i>
          </button>
        </div>

        <!-- Toolbar & Filter -->
        <div style="padding: 0.85rem 1.4rem; border-bottom: 1px solid var(--border-color, #e2e8f0); display: flex; flex-direction: column; gap: 10px; background: var(--bg-card, #f8fafc);">
          <div style="position: relative; display: flex; align-items: center;">
            <i class="fas fa-search" style="position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: #94a3b8;"></i>
            <input type="text" id="clinic-meds-search" placeholder="Dori nomi, raqami yoki MNN (Lotin yoki Кирилл: masalan: Verzepam, 18, Димедрол, Ольфрекс, Haloperidol)..." 
              style="width: 100%; padding: 8px 130px 8px 36px; border-radius: 8px; border: 1px solid #cbd5e1; font-size: 0.88rem; outline: none;"
              oninput="window.FMH_Doctor.onClinicMedsFilter(this.value)">
            <button type="button" id="clinic-meds-clear-btn" style="position: absolute; right: 100px; top: 50%; transform: translateY(-50%); width: 22px; height: 22px; border-radius: 50%; border: none; background: rgba(148, 163, 184, 0.25); color: #64748b; display: none; align-items: center; justify-content: center; font-size: 0.72rem; cursor: pointer;" onclick="window.FMH_Doctor.clearClinicMedsSearch()">
              <i class="fas fa-times"></i>
            </button>
            <span id="clinic-meds-script-badge" style="position: absolute; right: 8px; top: 50%; transform: translateY(-50%); font-size: 0.68rem; font-weight: 700; padding: 3px 8px; border-radius: 6px; background: rgba(13, 148, 136, 0.12); color: #0d9488; border: 1px solid rgba(13, 148, 136, 0.25); pointer-events: none; white-space: nowrap;">
              🔤 Lotin ⇄ Кирилл
            </span>
          </div>

          <!-- Category Pills -->
          <div style="display: flex; gap: 6px; overflow-x: auto; padding-bottom: 4px; scrollbar-width: thin;" id="clinic-meds-cat-bar">
            <button class="clinic-cat-btn active" data-cat="all" onclick="window.FMH_Doctor.setClinicCat('all')">Hammasi (88)</button>
            <button class="clinic-cat-btn" data-cat="psychiatry_anxiolytics_hypnotics" onclick="window.FMH_Doctor.setClinicCat('psychiatry_anxiolytics_hypnotics')">Trankvilizatorlar (11)</button>
            <button class="clinic-cat-btn" data-cat="psychiatry_antipsychotics" onclick="window.FMH_Doctor.setClinicCat('psychiatry_antipsychotics')">Neyroleptiklar (15)</button>
            <button class="clinic-cat-btn" data-cat="psychiatry_antidepressants" onclick="window.FMH_Doctor.setClinicCat('psychiatry_antidepressants')">Antidepressantlar (12)</button>
            <button class="clinic-cat-btn" data-cat="narcology_detox" onclick="window.FMH_Doctor.setClinicCat('narcology_detox')">Narkologiya & Detoks (4)</button>
            <button class="clinic-cat-btn" data-cat="infusion_detox_solutions" onclick="window.FMH_Doctor.setClinicCat('infusion_detox_solutions')">Infuzion Eritmalar (5)</button>
            <button class="clinic-cat-btn" data-cat="cardiovascular_emergency" onclick="window.FMH_Doctor.setClinicCat('cardiovascular_emergency')">Kardiologiya & Kriz (18)</button>
            <button class="clinic-cat-btn" data-cat="neurology_nootropics" onclick="window.FMH_Doctor.setClinicCat('neurology_nootropics')">Nootroplar & Vitamin (7)</button>
            <button class="clinic-cat-btn" data-cat="mood_stabilizers_anticonvulsants" onclick="window.FMH_Doctor.setClinicCat('mood_stabilizers_anticonvulsants')">Normotimiklar (4)</button>
            <button class="clinic-cat-btn" data-cat="analgesics_antiinflammatory_general" onclick="window.FMH_Doctor.setClinicCat('analgesics_antiinflammatory_general')">Analgetiklar & NYAQV (7)</button>
            <button class="clinic-cat-btn" data-cat="hepatoprotectors_gi" onclick="window.FMH_Doctor.setClinicCat('hepatoprotectors_gi')">Oshqozon-Ichak (5)</button>
          </div>
        </div>

        <!-- List Body -->
        <div id="clinic-meds-list-container" style="flex: 1; overflow-y: auto; padding: 1rem 1.4rem; display: flex; flex-direction: column; gap: 8px;">
        </div>

        <!-- Footer -->
        <div style="padding: 0.75rem 1.4rem; border-top: 1px solid var(--border-color, #cbd5e1); display: flex; justify-content: space-between; align-items: center; background: var(--bg-card, #f8fafc); font-size: 0.8rem; color: var(--text-muted, #64748b);">
          <div>Ko'rsatilmoqda: <b id="clinic-meds-shown-count">88</b> ta dori</div>
          <button onclick="window.FMH_Doctor.closeClinicMedsModal()" class="btn-doc-outline" style="padding: 4px 14px; font-size: 0.8rem;">Yopish</button>
        </div>
      </div>
    `;
    document.body.appendChild(modalDiv);

    // Add minimal CSS for category buttons if not present
    if (!document.getElementById('clinic-meds-modal-style')) {
      const st = document.createElement('style');
      st.id = 'clinic-meds-modal-style';
      st.innerHTML = `
        .clinic-cat-btn {
          white-space: nowrap;
          padding: 4px 10px;
          border-radius: 20px;
          border: 1px solid #cbd5e1;
          background: #ffffff;
          color: #334155;
          font-size: 0.74rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.15s;
        }
        .clinic-cat-btn:hover { background: #e2e8f0; }
        .clinic-cat-btn.active {
          background: #0d9488;
          color: #ffffff;
          border-color: #0d9488;
        }
        .clinic-med-card {
          border: 1px solid #e2e8f0;
          border-radius: 10px;
          padding: 10px 14px;
          background: #ffffff;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          transition: all 0.15s;
        }
        .clinic-med-card:hover {
          border-color: #0d9488;
          box-shadow: 0 4px 12px rgba(13, 148, 136, 0.08);
        }
      `;
      document.head.appendChild(st);
    }
  }

  function setClinicCat(cat) {
    activeClinicCat = cat;
    document.querySelectorAll('#clinic-meds-cat-bar .clinic-cat-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-cat') === cat);
    });
    renderClinicMedsList();
  }

  function clearClinicMedsSearch() {
    const inp = document.getElementById('clinic-meds-search');
    if (inp) {
      inp.value = '';
      onClinicMedsFilter('');
      inp.focus();
    }
  }

  function onClinicMedsFilter(query) {
    clinicMedsFilterQuery = (query || '').trim();
    const clearBtn = document.getElementById('clinic-meds-clear-btn');
    const badge = document.getElementById('clinic-meds-script-badge');
    if (clearBtn) clearBtn.style.display = clinicMedsFilterQuery ? 'flex' : 'none';
    if (badge && window.FMH_MedSearch) {
      const s = window.FMH_MedSearch.detectScript(clinicMedsFilterQuery);
      if (s === 'cyrillic') {
        badge.innerHTML = '🇷🇺 Кирилл ➔ Lotin';
        badge.style.color = '#0284c7';
      } else if (s === 'latin') {
        badge.innerHTML = '🇺🇿 Lotin ➔ Кирилл';
        badge.style.color = '#9333ea';
      } else {
        badge.innerHTML = '🔤 Lotin ⇄ Кирилл';
        badge.style.color = '#0d9488';
      }
    }
    renderClinicMedsList();
  }

  function renderClinicMedsList() {
    const container = document.getElementById('clinic-meds-list-container');
    if (!container) return;

    const clinicMeds = state.pharmacology
      .filter(m => m.fayz_house_list === true)
      .sort((a, b) => (a.fayz_house_num || 0) - (b.fayz_house_num || 0));

    const q = clinicMedsFilterQuery;
    const cat = activeClinicCat;

    let filtered = [];
    if (window.FMH_MedSearch) {
      filtered = window.FMH_MedSearch.search(clinicMeds, q, cat);
    } else {
      filtered = clinicMeds.filter(m => {
        if (cat !== 'all' && m.category !== cat) return false;
        if (!q) return true;
        const qLow = q.toLowerCase();
        const numMatch = String(m.fayz_house_num || '') === q;
        const nameMatch = (m.name || '').toLowerCase().includes(qLow) ||
                          (m.paper_name || '').toLowerCase().includes(qLow) ||
                          (m.trade_name_uz || '').toLowerCase().includes(qLow) ||
                          (m.trade_name_ru || '').toLowerCase().includes(qLow) ||
                          (m.inn || '').toLowerCase().includes(qLow);
        return numMatch || nameMatch;
      });
    }

    const countEl = document.getElementById('clinic-meds-shown-count');
    if (countEl) countEl.innerText = filtered.length;

    if (filtered.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; padding: 2.5rem; color: #94a3b8;">
          <i class="fas fa-search" style="font-size: 2rem; margin-bottom: 8px;"></i>
          <div>Kiritilgan so'rov bo'yicha hech qanday dori topilmadi.</div>
          <div style="font-size: 0.8rem; margin-top: 4px; color: #64748b;">Kirill yoki Lotin alifbosida yozib ko'ring (masalan: <em>mexidol / мексидол / 18</em>)</div>
        </div>
      `;
      return;
    }

    container.innerHTML = filtered.map(m => {
      const isPsychotropic = m.prescription_type === 'Rx_Strict_Psychotropic';
      const badgeClass = isPsychotropic ? 'background: #fef2f2; color: #dc2626; border: 1px solid #fecaca;' :
                          (m.prescription_type === 'Rx_Standard' ? 'background: #eff6ff; color: #2563eb; border: 1px solid #bfdbfe;' : 'background: #f0fdf4; color: #16a34a; border: 1px solid #bbf7d0;');
      const badgeText = isPsychotropic ? "⚠️ Qat'iy Psixotrop" : (m.prescription_type === 'Rx_Standard' ? "Rx (Retseptli)" : "OTC (Retseptsiz)");

      const displayName = window.FMH_MedSearch ? window.FMH_MedSearch.highlightMatched(m.name, q) : (m.name || '');
      const paperName = window.FMH_MedSearch ? window.FMH_MedSearch.highlightMatched(m.paper_name || '', q) : (m.paper_name || '');
      const innName = window.FMH_MedSearch ? window.FMH_MedSearch.highlightMatched(m.inn || m.trade_name_uz || '', q) : (m.inn || m.trade_name_uz || '');

      return `
        <div class="clinic-med-card">
          <div style="display: flex; align-items: center; gap: 12px; flex: 1;">
            <div style="width: 38px; height: 38px; border-radius: 8px; background: #f1f5f9; display: flex; align-items: center; justify-content: center; font-weight: 800; color: #0b3b60; font-size: 0.85rem; border: 1px solid #cbd5e1; flex-shrink: 0;">
              №${m.fayz_house_num}
            </div>
            <div>
              <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                <strong style="font-size: 0.95rem; color: #0f172a;">${displayName}</strong>
                <span style="font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; font-weight: 700; ${badgeClass}">
                  ${badgeText}
                </span>
              </div>
              <div style="font-size: 0.76rem; color: #64748b; margin-top: 2px;">
                <span style="color: #0284c7; font-weight: 600;">Qog'ozdagi yozilishi:</span> ${paperName} &nbsp;•&nbsp; 
                <span style="color: #64748b;">МНН: ${innName}</span> &nbsp;•&nbsp;
                <span style="color: #0d9488; font-weight: 600;">${m.form}</span>
              </div>
              <div style="font-size: 0.74rem; color: #475569; margin-top: 3px; display: flex; gap: 12px; flex-wrap: wrap;">
                <span><i class="fas fa-syringe" style="color: #94a3b8; font-size: 0.7rem;"></i> <b>Standart:</b> ${m.default_dosage} (${m.default_route})</span>
                <span><i class="fas fa-clock" style="color: #94a3b8; font-size: 0.7rem;"></i> ${m.default_frequency} • ${m.default_timing}</span>
              </div>
            </div>
          </div>

          <div style="display: flex; gap: 6px; flex-shrink: 0;">
            <button onclick="window.FMH_Doctor.fillFormWithMed(${m.fayz_house_num})" title="Formaga yuklash" 
              style="padding: 6px 10px; border-radius: 6px; border: 1px solid #cbd5e1; background: #ffffff; color: #334155; font-size: 0.76rem; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 5px;">
              <i class="fas fa-edit"></i> Formaga
            </button>
            <button onclick="window.FMH_Doctor.prescribeClinicMed(${m.fayz_house_num})" title="To'g'ridan-to'g'ri bemorga tayinlash"
              style="padding: 6px 12px; border-radius: 6px; border: none; background: #0d9488; color: #ffffff; font-size: 0.76rem; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 5px;">
              <i class="fas fa-plus"></i> Tayinlash
            </button>
          </div>
        </div>
      `;
    }).join('');
  }

  function fillFormWithMed(medNum) {
    const med = state.pharmacology.find(m => m.fayz_house_num === medNum || m.id === `FMH-${String(medNum).padStart(3, '0')}`);
    if (!med) return;
    const drugInput = document.getElementById('rx-drug-name');
    if (drugInput) drugInput.value = med.name;
    if (med.form) document.getElementById('rx-form').value = med.form;
    if (med.default_dosage) document.getElementById('rx-dosage').value = med.default_dosage;
    if (med.default_route) document.getElementById('rx-route').value = med.default_route;
    if (med.default_frequency) document.getElementById('rx-frequency').value = med.default_frequency;
    if (med.default_timing) document.getElementById('rx-timing').value = med.default_timing;
    if (med.default_duration) document.getElementById('rx-duration').value = med.default_duration;
    if (med.instructions) document.getElementById('rx-instructions').value = med.instructions;
    clearWarehouseItem(); // a different drug: the earlier warehouse link no longer applies
    whOnDrugPicked(med);
    closeClinicMedsModal();
    showToast(`✅ "${med.name}" tayinlov formasiga yuklandi!`, 'success');
    if (drugInput) drugInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  async function prescribeClinicMed(medNum) {
    const p = state.selectedPatient;
    if (!p) {
      showToast('Iltimos, avval bemorni tanlang!', 'warning');
      return;
    }
    const med = state.pharmacology.find(m => m.fayz_house_num === medNum || m.id === `FMH-${String(medNum).padStart(3, '0')}`);
    if (!med) return;

    // Allergy check
    if (p.medical_allergies && p.medical_allergies.toLowerCase() !== 'yo\'q') {
      const allergy = p.medical_allergies.toLowerCase();
      const dName = med.name.toLowerCase();
      if ((dName.includes('novo') && allergy.includes('novo')) ||
          (dName.includes('peni') && allergy.includes('peni')) ||
          (dName.includes('sulfa') && allergy.includes('sulfa'))) {
        const confirmPrescribe = await fmhConfirm({
          title: "⚠️ Allergiya Ogohlantirishi",
          message: `Bemor ushbu doriga allergiyaga ega: <strong>${p.medical_allergies}</strong>.<br><br>Baribir tayinlashni tasdiqlaysizmi?`,
          confirmText: "Baribir Tayinlash",
          cancelText: "Bekor Qilish",
          type: 'warning'
        });
        if (!confirmPrescribe) return;
      }
    }

    const rxData = {
      id: 'RX-' + Math.floor(Math.random() * 90000 + 10000),
      medication_name: med.name,
      form: med.form || med.dosage_form || '',
      dosage: med.default_dosage || med.strength || '',
      route: med.default_route || '',
      frequency: med.default_frequency || '',
      duration_days: med.default_duration || null,
      timing: med.default_timing || '',
      instructions: med.instructions || '',
      status: 'active',
      doctor_name: (state.authenticatedDoctor && state.authenticatedDoctor.name) || ''
    };

    // addPrescription announces the result itself.
    if (!(await addPrescription(rxData))) return;
    closeClinicMedsModal();
  }

  async function addPrescription(customRx = null) {
    const p = state.selectedPatient;
    if (!p) return;

    let rxData;
    if (customRx) {
      rxData = customRx;
    } else {
      const drugName = document.getElementById('rx-drug-name').value.trim();
      if (!drugName) {
        showToast('Iltimos, dori nomini kiriting!', 'warning');
        return;
      }

      // Check Allergy Safety
      if (p.medical_allergies && p.medical_allergies.toLowerCase() !== 'yo\'q') {
        const allergy = p.medical_allergies.toLowerCase();
        const dName = drugName.toLowerCase();
        if ((dName.includes('novo') && allergy.includes('novo')) ||
            (dName.includes('peni') && allergy.includes('peni')) ||
            (dName.includes('sulfa') && allergy.includes('sulfa'))) {
          const confirmPrescribe = await fmhConfirm({
            title: "⚠️ Allergiya Ogohlantirishi",
            message: `Bemor ushbu doriga allergiyaga ega: <strong>${p.medical_allergies}</strong>.<br><br>Baribir tayinlashni tasdiqlaysizmi?`,
            confirmText: "Baribir Tayinlash",
            cancelText: "Bekor Qilish",
            type: 'warning'
          });
          if (!confirmPrescribe) return;
        }
      }

      const matchedCanonical = findMedication(drugName);
      const canonicalName = matchedCanonical ? matchedCanonical.name : drugName;

      rxData = {
        id: 'RX-' + Math.floor(Math.random() * 90000 + 10000),
        medication_name: canonicalName,
        form: document.getElementById('rx-form').value,
        dosage: document.getElementById('rx-dosage').value,
        route: document.getElementById('rx-route').value,
        frequency: document.getElementById('rx-frequency').value,
        duration_days: parseInt(document.getElementById('rx-duration').value) || null,
        timing: document.getElementById('rx-timing').value,
        instructions: document.getElementById('rx-instructions').value,
        status: 'active',
        doctor_name: (state.authenticatedDoctor && state.authenticatedDoctor.name) || ''
      };

      // Optional warehouse link (form only: protocol and clinic-list orders
      // carry none). A quantity is kept exactly as typed; an empty field
      // stays empty and no quantity is invented.
      const qtyRaw = (document.getElementById('rx-qty')?.value || '').trim();
      if (qtyRaw !== '') {
        const qty = Number(qtyRaw);
        if (!isFinite(qty) || qty <= 0) {
          showToast("Miqdor 0 dan katta son bo'lishi kerak.", 'warning');
          return;
        }
        rxData.quantity_prescribed = qty;
        if (wh.item) rxData.quantity_unit = wh.item.base_unit;
      }
      if (wh.item) rxData.medication_id = wh.item.id;
    }

    // The order is shown as given only once the server has stored it. The
    // answer used to be ignored, so an order the server refused (no dose, no
    // route) still appeared on this list with a success message -- and never
    // reached the nurse station, which reads the database.
    let stockWarning = null;
    try {
      const res = await fetch('/api/doctor/prescriptions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: rxData.id,
          patient_id: p.id,
          admission_id: p.active_admission ? p.active_admission.admission_id : null,
          doctor_id: (state.authenticatedDoctor && state.authenticatedDoctor.staff_id) || state.activeDoctorId,
          doctor_name: (state.authenticatedDoctor && state.authenticatedDoctor.name) || rxData.doctor_name,
          ...rxData
        })
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || "Retsept saqlanmadi. Qayta urinib ko'ring.", 'danger');
        return false;
      }
      // The order is saved either way; the server only advises when the shelf
      // holds less than was prescribed.
      const saved = await res.json().catch(() => ({}));
      stockWarning = saved && saved.stock_warning ? saved.stock_warning : null;
    } catch (e) {
      showToast("Server bilan aloqa yo'q — retsept saqlanmadi.", 'danger');
      return false;
    }

    // Nothing has been handed out yet: dispensed is 0 and all of it remains.
    if (rxData.quantity_prescribed !== undefined) {
      rxData.quantity_dispensed = 0;
      rxData.remaining_quantity = rxData.quantity_prescribed;
    }

    if (!state.prescriptionsMap[p.id]) state.prescriptionsMap[p.id] = [];
    state.prescriptionsMap[p.id].unshift(rxData);
    localStorage.setItem(STORAGE_KEYS.PRESCRIPTIONS, JSON.stringify(state.prescriptionsMap));

    // Reset Form
    if (!customRx) {
      const rxDrugInput = document.getElementById('rx-drug-name');
      if (rxDrugInput) {
        rxDrugInput.value = '';
        const clearBtn = rxDrugInput.closest('.fmh-med-search-wrapper')?.querySelector('.fmh-med-clear-btn');
        if (clearBtn) clearBtn.style.display = 'none';
      }
      document.getElementById('rx-dosage').value = '';
      document.getElementById('rx-instructions').value = '';
      clearDrugDetailsBanner();
      resetWarehousePanel();
    }

    showToast(`💊 <strong>${rxData.medication_name}</strong> retsept varaqasiga muvaffaqiyatli qo'shildi!`);
    if (stockWarning && stockWarning.message) showToast(escapeHtml(stockWarning.message), 'warning');
    renderPrescriptionsTab();
    updateTabBadges();
    updateKPIs();
    return true;
  }

  async function applyPresetProtocol(protocolType) {
    const p = state.selectedPatient;
    if (!p) return;

    let items = [];
    if (protocolType === 'detox') {
      items = [
        { medication_name: 'Reamberin 1.5% 400ml', form: 'Infuzion flakon', dosage: '400 ml', route: 'V/I tomchilab (kapelnitsa)', frequency: 'Kuniga 1 mahal', duration_days: 5, timing: 'Ertalab 09:30', instructions: 'Sekin tomchilatib yuborilsin' },
        { medication_name: 'Gepa-Merts (L-ornitin-L-aspartat)', form: 'Ampula 10ml', dosage: '10 ml', route: 'V/I tomchilab (kapelnitsa)', frequency: 'Kuniga 1 mahal', duration_days: 5, timing: 'Tushlik 13:30', instructions: '200ml fiziologik eritmada eritib' },
        { medication_name: 'Meksidol (Etilmetilgidroksipiridin)', form: 'Ampula 5% 2ml', dosage: '4 ml', route: 'V/I oqimli', frequency: 'Kuniga 2 mahal', duration_days: 7, timing: 'Ertalab & Kechqurun', instructions: 'Sekin 3-5 daqiqa davomida' },
        { medication_name: 'Tiamin xlorid (Vitamin B1)', form: 'Ampula 5% 1ml', dosage: '2 ml', route: 'V/M inyeksiya', frequency: 'Kuniga 1 mahal', duration_days: 10, timing: 'Ertalab 10:00', instructions: 'Mushak ichiga' }
      ];
    } else if (protocolType === 'alcohol_abstinence') {
      items = [
        { medication_name: 'Magniy sulfat 25% 10ml', form: 'Ampula', dosage: '10 ml', route: 'V/I tomchilab (kapelnitsa)', frequency: 'Kuniga 1 mahal', duration_days: 5, timing: 'Ertalab 10:00', instructions: '200ml Glukoza 5% bilan' },
        { medication_name: 'Piridoksin (Vitamin B6)', form: 'Ampula 5% 1ml', dosage: '2 ml', route: 'V/M inyeksiya', frequency: 'Kuniga 1 mahal', duration_days: 7, timing: 'Ertalab 11:00', instructions: 'Mushak ichiga' },
        { medication_name: 'Fenazepam / Gidazepam', form: 'Tabletkalar', dosage: '0.05 g', route: 'Ichishga (Per os)', frequency: 'Kuniga 1 mahal', duration_days: 5, timing: 'Uyqudan oldin 21:30', instructions: 'Sedatsiya va uyquni barqarorlashtirish' }
      ];
    } else if (protocolType === 'hepato_neuro') {
      items = [
        { medication_name: 'Glutation (Tad 600)', form: 'Flakon 600mg', dosage: '600 mg', route: 'V/I tomchilab (kapelnitsa)', frequency: 'Kuniga 1 mahal', duration_days: 7, timing: 'Ertalab 09:30', instructions: 'VIP antioksidant' },
        { medication_name: 'Serebrolizin (Cerebrolysin)', form: 'Ampula 5ml', dosage: '5 ml', route: 'V/I oqimli', frequency: 'Kuniga 1 mahal', duration_days: 10, timing: 'Ertalab 10:30', instructions: 'Miyaning neyrometabolik tiklanishi' }
      ];
    } else if (protocolType === 'psychiatry') {
      items = [
        { medication_name: 'Grandaksin (Tofisopam)', form: 'Tabletkalar', dosage: '50 mg', route: 'Ichishga (Per os)', frequency: 'Kuniga 2 mahal', duration_days: 14, timing: 'Ertalab va Tushlik', instructions: 'Kunduzgi trankvilizator' },
        { medication_name: 'Sertralin (Zoloft)', form: 'Tabletkalar', dosage: '50 mg', route: 'Ichishga (Per os)', frequency: 'Kuniga 1 mahal', duration_days: 30, timing: 'Ertalab nonushtadan so\'ng', instructions: 'Antidepressant terapiya' }
      ];
    }

    // Each order is saved one after another and counted. The summary used to
    // say every drug was prescribed even when the server refused them all
    // (each refusal already shows its own message from addPrescription).
    let saved = 0;
    for (const item of items) {
      const ok = await addPrescription({
        id: 'RX-' + Math.floor(Math.random() * 90000 + 10000),
        status: 'active',
        doctor_name: (state.authenticatedDoctor && state.authenticatedDoctor.name) || '',
        ...item
      });
      if (ok) saved++;
    }

    if (saved === items.length) {
      showToast(`⚡ Protokol biriktirildi: <strong>${saved} ta dori</strong> tayinlandi!`);
    } else if (saved > 0) {
      showToast(`Protokol qisman biriktirildi: ${items.length} tadan <strong>${saved} ta dori</strong> saqlandi.`, 'warning');
    } else if (items.length) {
      showToast('Protokol saqlanmadi: birorta dori tayinlanmadi.', 'danger');
    }
  }

  async function toggleRxStatus(patientId, rxId, newStatus) {
    const list = state.prescriptionsMap[patientId];
    if (!list) return;
    const item = list.find(rx => rx.id === rxId);
    if (item) {
      const oldStatus = item.status;
      item.status = newStatus; // optimistic update
      try {
        const res = await fetch(`/api/doctor/prescriptions/${rxId}/status`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: newStatus })
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.error || "Xatolik: Holatni yangilab bo'lmadi");
        }

        localStorage.setItem(STORAGE_KEYS.PRESCRIPTIONS, JSON.stringify(state.prescriptionsMap));
        renderPrescriptionsTab();
        showToast(`Dori holati yangilandi: ${newStatus.toUpperCase()}`);
      } catch (err) {
        // revert
        item.status = oldStatus;
        showToast(escapeHtml(err.message || "Xatolik: Holatni yangilab bo'lmadi"), "error");
      }
    }
  }

  function deletePrescription(patientId, rxId) {
    const list = state.prescriptionsMap[patientId];
    if (!list) return;
    const item = list.find(rx => rx.id === rxId);
    const medName = item ? item.medication_name : 'ushbu dorini';

    // The previous fallback here called onConfirm() immediately when the dialog
    // was unavailable, so on this page — which never loaded it — prescriptions
    // were deleted with no prompt at all. The dialog is now loaded globally from
    // js/fmh_dialogs.js; if it is ever missing, refuse to delete rather than
    // silently destroying a clinical record.
    const confirmFn = window.FMH_ConfirmDialog || function () {
      showToast("Tasdiqlash oynasi yuklanmadi — o'chirish bekor qilindi", 'danger');
    };

    confirmFn({
      title: "Retseptni O'chirish",
      message: `<strong>${medName}</strong> tayinlovini retsept varaqasidan o'chirmoqchimisiz?`,
      confirmText: "O'chirish (Enter ↵)",
      cancelText: "Bekor Qilish",
      type: "danger",
      onConfirm: async () => {
        try {
          const res = await fetch(`/api/doctor/prescriptions/${encodeURIComponent(rxId)}`, { method: 'DELETE' });
          if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || "Xatolik: Retseptni o'chirib bo'lmadi");
          }

          state.prescriptionsMap[patientId] = list.filter(rx => rx.id !== rxId);
          localStorage.setItem(STORAGE_KEYS.PRESCRIPTIONS, JSON.stringify(state.prescriptionsMap));
          renderPrescriptionsTab();
          updateTabBadges();
          showToast("🗑️ Dori retseptdan o'chirildi");
          updateKPIs();
        } catch (err) {
          showToast(escapeHtml(err.message || "Xatolik: Retseptni o'chirib bo'lmadi"), "error");
        }
      }
    });
  }

  // --- TAB 3: DAILY PROGRESS NOTES (DNEVNIK OBXODA) ---

  // The server stores notes as doctor_daily_notes columns (note_date,
  // patient_condition, vital_*, dynamics_notes, treatment_adjustments). This
  // page was written against a different shape, so every note loaded from the
  // server rendered as "undefined" with empty vitals. Convert once on load;
  // notes already in page shape pass through unchanged.
  function normalizeNote(n) {
    if (!n || n.dynamics_notes === undefined) return n;
    const sys = n.vital_bp_systolic, dia = n.vital_bp_diastolic;
    return {
      id: n.id,
      date: n.note_date ? String(n.note_date).slice(0, 10) : '',
      condition: n.patient_condition || '',
      bp: (sys != null && dia != null) ? `${sys}/${dia}` : null,
      pulse: n.vital_pulse != null ? n.vital_pulse : null,
      temp: n.vital_temp != null ? n.vital_temp : null,
      spo2: n.vital_spo2 != null ? n.vital_spo2 : null,
      dynamics: n.dynamics_notes || '',
      treatment: n.treatment_adjustments || '',
      doctor_name: n.doctor_name || ''
    };
  }

  function localDateStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  function renderDailyNotesTab() {
    const p = state.selectedPatient;
    if (!p) return;

    const notes = state.dailyNotesMap[p.id] || [];
    const container = document.getElementById('daily-notes-container');
    if (!container) return;

    if (notes.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; padding: 2rem; color: var(--text-muted);">
          Hozircha kunlik ko'rik qaydlari mavjud emas. Quyidagi formadan yangi ko'rik natijasini yozing.
        </div>
      `;
      return;
    }

    // Notes now come from the server, typed on this page, the ward round or
    // by another doctor. Put into innerHTML as they were, a note containing
    // markup ran as script in every doctor's session that opened the tab.
    container.innerHTML = notes.map(normalizeNote).map(n => {
      const condBadge = n.condition === 'satisfactory' ? '<span class="status-pill status-active">Qoniqarli</span>' : (n.condition === 'critical' ? '<span class="status-pill status-cancelled">Kritik</span>' : (n.condition === 'severe' ? '<span class="status-pill status-cancelled">Og\'ir</span>' : (n.condition === 'moderate' ? '<span class="status-pill status-completed">O\'rta og\'ir</span>' : '')));
      return `
        <div class="diary-entry-card">
          <div class="diary-top-row">
            <div class="diary-date"><i class="fas fa-calendar-check"></i> ${escapeHtml(n.date)} • ${escapeHtml(n.doctor_name || '—')}</div>
            ${condBadge}
          </div>
          <div class="diary-vitals-box">
            <span><strong>Qon bosimi:</strong> ${escapeHtml(n.bp || '—')} mm Hg</span>
            <span><strong>Puls:</strong> ${escapeHtml(n.pulse || '—')} ur/min</span>
            <span><strong>Harorat:</strong> ${escapeHtml(n.temp || '—')} °C</span>
            <span><strong>SpO2:</strong> ${n.spo2 ? escapeHtml(n.spo2) + '%' : '—'}</span>
          </div>
          <div style="font-size: 0.88rem; color: var(--text-primary); margin-bottom: 6px; line-height: 1.5;">
            <strong>Dinamika va holat:</strong> ${escapeHtml(n.dynamics)}
          </div>
          ${n.treatment ? `
            <div style="font-size: 0.82rem; color: var(--doctor-cyan-light); background: rgba(6, 182, 212, 0.08); padding: 6px 10px; border-radius: 6px;">
              <strong>Korreksiya:</strong> ${escapeHtml(n.treatment)}
            </div>
          ` : ''}
        </div>
      `;
    }).join('');
  }

  async function addDailyNote() {
    const p = state.selectedPatient;
    if (!p) return;

    const dynamics = document.getElementById('note-dynamics').value.trim();
    if (!dynamics) {
      showToast('Iltimos, bemor holati dinamikasini yozing!', 'warning');
      return;
    }

    // Local date: toISOString() is UTC, so before 05:00 in Tashkent the note
    // landed on yesterday.
    const todayStr = localDateStr();
    const bpRaw = document.getElementById('note-bp').value.trim();
    let bpSys = '', bpDia = '';
    if (bpRaw) {
      const m = bpRaw.match(/^(\d{2,3})\s*\/\s*(\d{2,3})$/);
      if (!m) {
        showToast("Qon bosimini 120/80 ko'rinishida yozing", 'warning');
        return;
      }
      bpSys = m[1]; bpDia = m[2];
    }
    const pulseRaw = document.getElementById('note-pulse').value.trim();
    const tempRaw = document.getElementById('note-temp').value.trim();
    const spo2Raw = document.getElementById('note-spo2').value.trim();
    const treatment = document.getElementById('note-treatment').value.trim();
    const condition = document.getElementById('note-condition').value;

    // Field names match POST /api/doctor/notes (the same ones ward.js sends).
    // The old names (condition, bp, dynamics, treatment_changes) were not
    // read by the server, so every note was refused with "Dinamika shart".
    // Only vitals the doctor typed are sent: an absent field leaves the
    // nurse's or ward round's reading for the day untouched.
    const payload = {
      patient_id: p.id,
      admission_id: (p.active_admission && p.active_admission.admission_id) || null,
      note_date: todayStr,
      patient_condition: condition,
      dynamics_notes: dynamics,
      treatment_adjustments: treatment
    };
    if (bpSys) { payload.vital_bp_systolic = bpSys; payload.vital_bp_diastolic = bpDia; }
    if (pulseRaw) payload.vital_pulse = pulseRaw;
    if (tempRaw) payload.vital_temp = tempRaw;
    if (spo2Raw) payload.vital_spo2 = spo2Raw;

    const newNote = {
      date: todayStr,
      condition: condition,
      bp: bpSys ? `${bpSys}/${bpDia}` : null,
      pulse: pulseRaw ? Number(pulseRaw) : null,
      temp: tempRaw ? Number(tempRaw) : null,
      spo2: spo2Raw ? Number(spo2Raw) : null,
      dynamics: dynamics,
      treatment: treatment,
      doctor_name: (state.authenticatedDoctor && state.authenticatedDoctor.name) || ''
    };

    try {
      const res = await fetch('/api/doctor/notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || "Xatolik: Qaydni saqlab bo'lmadi", "error");
        return;
      }

      // One note per stay per day: saving again today replaces today's note.
      state.dailyNotesMap[p.id] = (state.dailyNotesMap[p.id] || []).filter(n => normalizeNote(n).date !== todayStr);
      state.dailyNotesMap[p.id].unshift(newNote);
      localStorage.setItem(STORAGE_KEYS.DAILY_NOTES, JSON.stringify(state.dailyNotesMap));

      // Reset Form
      document.getElementById('note-dynamics').value = '';
      document.getElementById('note-treatment').value = '';

      showToast(`📝 <strong>${todayStr}</strong> kungi ko'rik qaydi muvaffaqiyatli kiritildi!`);
      renderDailyNotesTab();
      updateTabBadges();
      updateVitalsDashboard();
    } catch (err) {
      showToast("Server bilan aloqa yo'q. Qayd saqlanmadi.", "error");
    }
  }

  // The one-click "normal values" button (120/80, 74, 36.6, 99%) was removed:
  // it let a round be recorded with vitals nobody measured.

  function appendDynamicsPhrase(phrase) {
    const el = document.getElementById('note-dynamics');
    if (!el) return;
    el.value = el.value ? el.value.trim() + ' ' + phrase : phrase;
    el.focus();
  }

  function setTreatmentPhrase(phrase) {
    const el = document.getElementById('note-treatment');
    if (!el) return;
    el.value = phrase;
    el.focus();
  }

  // --- TAB 4: DISCHARGE EPICRISIS & RECOMMENDATIONS ---
  function renderEpicrisisTab() {
    const p = state.selectedPatient;
    if (!p) return;

    const anam = state.anamnesisMap[p.id] || {};
    const rxList = state.prescriptionsMap[p.id] || [];

    // The programme name ("DETOX davolash kursi") stood in for a diagnosis
    // and was saved as the final diagnosis on the discharge paper.
    const diag = anam.diagnosis_primary || '';
    state.epicrisisDiag = diag;

    document.getElementById('epicrisis-diag').textContent = diag || '—';
    const outcomeSel = document.getElementById('epicrisis-outcome');
    const savedEpi = (state.epicrisisMap && state.epicrisisMap[p.id]) || {};
    document.getElementById('epicrisis-patient').textContent = `${p.full_name} (${p.patient_code})`;
    // Show what was saved for THIS patient. The home-medicines box used to be
    // overwritten with the inpatient list on every render, and the advice box
    // was never touched, so the previous patient's advice stayed on screen
    // and could be saved onto the next patient's discharge paper.
    //
    // The saved summary counts only when it belongs to the current stay: the
    // server sends the latest one from any stay, so a readmitted patient
    // opened with last stay's home medicines, advice and outcome filled in.
    //
    // The boxes are filled only when the patient or the saved record changes.
    // This runs on every workstation re-render (each anamnesis save), which
    // wiped advice the doctor had typed but not yet saved.
    //
    // The home-medicines box starts empty when nothing is saved; it used to
    // be pre-filled with every prescription, including stopped ones, which
    // also left "Auto epikriz" nothing to fill.
    const curAdm = p.active_admission ? p.active_admission.admission_id : null;
    const sameStay = Object.keys(savedEpi).length > 0 &&
      (!curAdm || savedEpi.admission_id === curAdm);
    const marker = state.epicrisisRendered || {};
    const savedRef = (state.epicrisisMap && state.epicrisisMap[p.id]) || null;
    if (marker.id !== p.id || marker.saved !== savedRef) {
      if (outcomeSel) outcomeSel.value = sameStay ? (savedEpi.discharge_status || '') : '';
      document.getElementById('epicrisis-home-rx').value = sameStay ? (savedEpi.home_prescriptions || '') : '';
      const psychoEl = document.getElementById('epicrisis-psycho');
      if (psychoEl) psychoEl.value = sameStay ? (savedEpi.psycho_recommendations || '') : '';
      state.epicrisisRendered = { id: p.id, saved: savedRef };
    }
  }

  async function saveEpicrisis() {
    const p = state.selectedPatient;
    if (!p) return;

    const data = {
      patient_id: p.id,
      admission_id: p.active_admission ? p.active_admission.admission_id : null,
      doctor_id: (state.authenticatedDoctor && state.authenticatedDoctor.staff_id) || state.activeDoctorId,
      doctor_name: (state.authenticatedDoctor && state.authenticatedDoctor.name) || '',
      epicrisis_date: localDateStr(),
      diagnosis_final: state.epicrisisDiag || '',
      icd10_code: document.getElementById('anam-icd10')?.value || null,
      // Was always "the course was completed successfully" with outcome
      // 'recovered', whatever actually happened. The outcome is now chosen.
      treatment_summary: null,
      home_prescriptions: document.getElementById('epicrisis-home-rx')?.value || '',
      psycho_recommendations: document.getElementById('epicrisis-psycho')?.value || '',
      discharge_status: document.getElementById('epicrisis-outcome')?.value || ''
    };

    if (!data.diagnosis_final) {
      showToast("Avval anamnez bo'limida asosiy tashxisni kiriting.", 'warning');
      return;
    }
    if (!data.discharge_status) {
      showToast('Chiqish natijasini tanlang.', 'warning');
      document.getElementById('epicrisis-outcome')?.focus();
      return;
    }

    try {
      const res = await fetch('/api/doctor/epicrisis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || "Epikriz saqlanmadi. Qayta urinib ko'ring.", 'danger');
        return;
      }
    } catch (e) {
      showToast("Server bilan aloqa yo'q — epikriz saqlanmadi.", 'danger');
      return;
    }

    if (!state.epicrisisMap) state.epicrisisMap = {};
    state.epicrisisMap[p.id] = data;

    showToast(`📋 <strong>${p.full_name}</strong> chiqarish epikrizi MySQL bazasiga saqlandi!`);
  }

  // "Auto-generate" used to paste a fixed list (Meksidol, Neyromultivit,
  // Gepabene, Magne B6) and fixed advice for every patient, i.e. home
  // medicines nobody prescribed. It now only copies this patient's own
  // active prescriptions into an empty home-medicines box; the doctor edits
  // from there. The advice box is left to the doctor.
  function autoGenerateEpicrisis() {
    const p = state.selectedPatient;
    if (!p) {
      showToast("Avval bemorni tanlang!", "warning");
      return;
    }

    // Only orders still running: 'completed' (a finished IV course) and
    // 'held' were listed as home medicines too.
    const rxList = (state.prescriptionsMap[p.id] || []).filter(r => (r.status || 'active') === 'active');
    if (rxList.length === 0) {
      showToast("Bemorda faol tayinlov yo'q. Uyga dori tavsiyalarini qo'lda yozing.", "warning");
      return;
    }

    const homeRxInput = document.getElementById('epicrisis-home-rx');
    if (homeRxInput && homeRxInput.value.trim()) {
      showToast("Uyga dorilar maydoni to'ldirilgan. Avval uni tozalang.", "warning");
      return;
    }
    if (homeRxInput) {
      homeRxInput.value = rxList.map((r, i) => `${i + 1}. ${r.medication_name} — ${r.dosage || ''} (${r.route || ''}, ${r.frequency || ''})`).join('\n');
    }

    showToast("Bemorning faol tayinlovlari uyga dorilar maydoniga ko'chirildi. Tekshirib, tahrirlang.", "info");
  }

  function appendHomeRx(text) {
    const el = document.getElementById('epicrisis-home-rx');
    if (!el) return;
    el.value = text;
    el.focus();
    showToast("Uyga davolanish paketi o'rnatildi", "info");
  }

  function setPsychoRec(text) {
    const el = document.getElementById('epicrisis-psycho');
    if (!el) return;
    el.value = text;
    el.focus();
    showToast("Reabilitatsiya tavsiyalari kiritildi", "info");
  }

  // =========================================================================
  // OFFICIAL PRINT & PDF EXPORT ENGINE WITH CLINIC CREDENTIALS
  // =========================================================================
  function openOfficialDocModal(docType = 'prescriptions') {
    const modal = document.getElementById('official-doc-modal');
    if (!modal) return;
    const select = document.getElementById('doc-type-select');
    if (select) select.value = docType;
    modal.style.display = 'flex';
    renderOfficialDocumentPreview();
  }

  function closeOfficialDocModal() {
    const modal = document.getElementById('official-doc-modal');
    if (modal) modal.style.display = 'none';
  }

    function printOfficialDocument(docType = 'prescriptions') {
    const p = state.selectedPatient;
    if (!p) {
      showToast('Iltimos, avval bemorni tanlang!', 'warning');
      return;
    }
    const activeDoc = state.authenticatedDoctor || state.doctors.find(d => d.id === state.activeDoctorId) || state.doctors[0];
    const rxList = state.prescriptionsMap[p.id] || [];
    const epicrisis = (state.epicrisisMap && state.epicrisisMap[p.id]) || {};

    if (window.FMH_Print) {
      if (docType === 'prescriptions') {
        window.FMH_Print.prescriptionSheet(p, rxList, activeDoc);
      } else if (docType === 'epicrisis') {
        window.FMH_Print.dischargeEpicrisis(p, epicrisis, activeDoc);
      } else {
        // The print engine has no history or dossier layout, and this branch
        // printed the discharge summary instead. Those two documents come
        // from the server PDF, which builds them from the saved record.
        downloadPDF(docType);
      }
    } else {
      openOfficialDocModal(docType);
      setTimeout(() => { window.print(); }, 150);
    }
  }

  async function downloadPDF(forcedType) {
    const p = state.selectedPatient;
    if (!p) {
      showToast('Iltimos, avval bemorni tanlang!', 'warning');
      return;
    }
    const docType = (typeof forcedType === 'string' && forcedType) || document.getElementById('doc-type-select')?.value || 'prescriptions';
    const filename = `FMH_${docType.toUpperCase()}_${p.patient_code || p.id}.pdf`;

    showToast('⏳ <strong>MySQL ma\'lumotlar bazasidan PDF yaratilmoqda...</strong>', 'info');

    try {
      const pdfUrl = `/api/doctor/download-pdf/${encodeURIComponent(p.id)}?doc_type=${encodeURIComponent(docType)}`;
      const res = await fetch(pdfUrl);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);

      const a = document.createElement('a');
      a.style.display = 'none';
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();

      setTimeout(() => {
        URL.revokeObjectURL(blobUrl);
        a.remove();
      }, 1000);

      showToast('✅ <strong>SQL ma\'lumotlari asosida PDF yuklab olindi!</strong>', 'success');
    } catch (err) {
      console.warn('Blob fetch download fallback', err);
      window.open(`/api/doctor/download-pdf/${p.id}?doc_type=${docType}`, '_blank');
    }
  }

  function renderOfficialDocumentPreview() {
    const p = state.selectedPatient;
    const container = document.getElementById('printable-a4-document');
    if (!container) return;

    if (!p) {
      container.innerHTML = `<div style="text-align: center; padding: 3rem; color: #64748b;">Iltimos, avval bemorni tanlang!</div>`;
      return;
    }

    const docType = document.getElementById('doc-type-select')?.value || 'prescriptions';
    const activeDoc = state.authenticatedDoctor || state.doctors.find(d => d.id === state.activeDoctorId) || state.doctors[0];
    const anam = state.anamnesisMap[p.id] || {};
    const rxList = state.prescriptionsMap[p.id] || [];
    const dailyNotes = state.dailyNotesMap[p.id] || [];
    const epicrisis = (state.epicrisisMap && state.epicrisisMap[p.id]) || {};

    const age = p.birth_year ? (new Date().getFullYear() - p.birth_year) : 'N/A';
    const genderStr = genderLabel(p.gender);
    const roomStr = p.active_admission ? `${p.active_admission.room_number}-xona (${p.active_admission.bed_code})` : 'Ambulator';
    const todayStr = new Date().toLocaleDateString('uz-UZ', { year: 'numeric', month: 'long', day: 'numeric' });

    let titleText = "RASMIY MUOLAJA VARAQASI (LIST NAZNACHENIY)";
    let subtitleText = "Klinik dori-darmonlar va tibbiy muolajalar tayinlovi";

    if (docType === 'anamnesis') {
      titleText = "KASALLIK TARIXI VA KASALLIK ANAMNEZI (EMR)";
      subtitleText = "Statsionar / Ambulator bemorning birlamchi tibbiy ko'rik hujjati";
    } else if (docType === 'epicrisis') {
      titleText = "STATSIONARDAN CHIQARISH EPIKRIZI";
      subtitleText = "Rasmiy tibbiy xulosa, natijalar va uyda davolanish tavsiyalari";
    } else if (docType === 'full_dossier') {
      titleText = "TO'LIQ BEMOR KLINIK EMR DOSSYESI";
      subtitleText = "Yagona kompleks tibbiy hujjat (Anamnez, Retseptlar, Ko'riklar & Epikriz)";
    }

    let mainContentHtml = '';

    // SECTION 1: PRESCRIPTIONS TABLE
    const rxTableHtml = `
      <div class="a4-section-title"><i class="fas fa-pills"></i> Dori-Darmon va Muolaja Tayinlovlari (List Naznacheniy)</div>
      <table class="a4-table">
        <thead>
          <tr>
            <th style="width: 30px;">№</th>
            <th>Dori vositasi & Shakli</th>
            <th>Doza</th>
            <th>Yuborish Yo'li</th>
            <th>Qabul vaqti / Davriyligi</th>
            <th>Davomiyligi</th>
            <th>Holati</th>
          </tr>
        </thead>
        <tbody>
          ${rxList.length > 0 ? rxList.map((r, i) => `
            <tr>
              <td>${i + 1}</td>
              <td><strong>${r.medication_name}</strong><br><small style="color: #64748b;">${r.form || ''}</small></td>
              <td><strong>${r.dosage}</strong></td>
              <td>${r.route}</td>
              <td>${r.frequency}<br><small style="color: #64748b;">${r.timing || ''}</small></td>
              <td>${r.duration_days} kun</td>
              <td><span style="font-weight: 700; color: ${r.status === 'completed' ? '#10b981' : (r.status === 'cancelled' ? '#f43f5e' : '#0284c7')};">${r.status === 'completed' ? 'Bajarildi' : (r.status === 'cancelled' ? 'Bekor qilindi' : 'Bajarilmoqda')}</span></td>
            </tr>
          `).join('') : '<tr><td colspan="7" style="text-align: center; color: #94a3b8;">Tayinlangan dori-darmonlar yo\'q.</td></tr>'}
        </tbody>
      </table>
    `;

    // SECTION 2: ANAMNESIS HTML
    const anamnesisHtml = `
      <div class="a4-section-title"><i class="fas fa-notes-medical"></i> Bemor Shikoyatlari & Anamnezi</div>
      <div style="font-size: 12.5px; display: grid; gap: 8px; margin-bottom: 16px;">
        <div><strong>Bemor shikoyatlari:</strong> ${document.getElementById('anam-complaints')?.value || anam.complaints || NOT_RECORDED}</div>
        <div><strong>Anamnesis Morbi (Kasallik rivojlanishi):</strong> ${document.getElementById('anam-morbi')?.value || anam.anamnesis_morbi || NOT_RECORDED}</div>
        <div><strong>Anamnesis Vitae (Hayotiy anamnez):</strong> ${document.getElementById('anam-vitae')?.value || anam.anamnesis_vitae || NOT_RECORDED}</div>
        <div><strong>Somatik & Nevrologik holat:</strong> ${document.getElementById('anam-somatic')?.value || anam.somatic_status || NOT_RECORDED}</div>
        <div><strong>Psixik status:</strong> ${document.getElementById('anam-psychiatric')?.value || anam.psychiatric_status || NOT_RECORDED}</div>
      </div>
    `;

    // SECTION 3: DAILY NOTES HTML
    const dailyNotesHtml = `
      <div class="a4-section-title"><i class="fas fa-clipboard-list"></i> Shifokor Kundalik Ko'rigi Qaydlari (Dnevnik Obxoda)</div>
      <table class="a4-table">
        <thead>
          <tr>
            <th style="width: 90px;">Sana</th>
            <th style="width: 100px;">Gemodinamika</th>
            <th>Holat Dinamikasi va O'zgarishlar</th>
            <th>Korreksiya</th>
          </tr>
        </thead>
        <tbody>
          ${dailyNotes.length > 0 ? dailyNotes.map(n => `
            <tr>
              <td><strong>${escapeHtml(n.date)}</strong></td>
              <td>Bosim: ${escapeHtml(n.bp || '—')}<br>Puls: ${escapeHtml(n.pulse || '—')}<br>Temp: ${escapeHtml(n.temp || '—')}°C</td>
              <td>${escapeHtml(n.dynamics)}</td>
              <td>${escapeHtml(n.treatment || '—')}</td>
            </tr>
          `).join('') : '<tr><td colspan="4" style="text-align: center; color: #94a3b8;">Kundalik ko\'rik qaydlari mavjud emas.</td></tr>'}
        </tbody>
      </table>
    `;

    // SECTION 4: EPICRISIS HTML
    const epicrisisHtml = `
      <div class="a4-section-title"><i class="fas fa-file-signature"></i> Chiqarish Epikrizi & Uyga Davolanish Tavsiyalari</div>
      <div style="font-size: 12.5px; display: grid; gap: 10px; margin-bottom: 16px;">
        <div style="background: #f8fafc; padding: 10px; border-radius: 6px; border: 1px solid #e2e8f0;">
          <strong>Klinik Xulosa va Natija:</strong> ${epicrisis.treatment_summary || DISCHARGE_OUTCOMES[epicrisis.discharge_status] || NOT_RECORDED}
        </div>
        <div>
          <strong>Uyda Davom Ettirish Uchun Tavsiya Etilgan Farmakoterapiya:</strong>
          <pre style="font-family: inherit; white-space: pre-wrap; margin-top: 4px; background: #fff; padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px;">${document.getElementById('epicrisis-home-rx')?.value || epicrisis.home_prescriptions || NOT_RECORDED}</pre>
        </div>
        <div>
          <strong>Psixoterapevtik va Reabilitatsiya Tavsiyalari:</strong>
          <div style="background: #fff; padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; margin-top: 4px;">${document.getElementById('epicrisis-psycho')?.value || epicrisis.psycho_recommendations || NOT_RECORDED}</div>
        </div>
      </div>
    `;

    if (docType === 'prescriptions') {
      mainContentHtml = rxTableHtml;
    } else if (docType === 'anamnesis') {
      mainContentHtml = anamnesisHtml + rxTableHtml;
    } else if (docType === 'epicrisis') {
      mainContentHtml = epicrisisHtml;
    } else if (docType === 'full_dossier') {
      mainContentHtml = anamnesisHtml + rxTableHtml + dailyNotesHtml + epicrisisHtml;
    }

    const primaryDiag = document.getElementById('anam-diagnosis-primary')?.value || anam.diagnosis_primary || NOT_RECORDED;
    const icdCode = document.getElementById('anam-icd10')?.value || anam.icd10_code || '—';

    container.innerHTML = `
      <!-- Official Clinic Header Letterhead -->
      <div class="a4-clinic-header">
        <div class="a4-brand-logo">
          <div class="a4-brand-icon">
            <i class="fas fa-hospital-alt"></i>
          </div>
          <div>
            <div class="a4-brand-name">FAYZ MEDICAL HOUSE</div>
            <div class="a4-brand-sub">XUSUSIY NARKOLOGIYA VA PSIXIATRIYA KLINIKASI</div>
          </div>
        </div>

        <div class="a4-clinic-meta">
          <div><strong>O'zR SSV Litsenziyasi:</strong> № 4082-00</div>
          <div><strong>Manzil:</strong> Toshkent sh., Yunusobod t., Bodomzor str. 42</div>
          <div><strong>Ishonch Telefoni:</strong> +998 (71) 200-03-03 / +998 (90) 372-03-03</div>
          <div><strong>Veb-sayt:</strong> www.fayzmedicalhouse.uz</div>
        </div>
      </div>

      <!-- Document Title Bar -->
      <div class="a4-doc-title-bar">
        <div class="a4-doc-title">${titleText}</div>
        <div class="a4-doc-subtitle">${subtitleText} • Sana: ${todayStr}</div>
      </div>

      <!-- Patient Identity Grid -->
      <div class="a4-patient-grid">
        <div class="a4-patient-field"><span>Bemor F.I.SH.:</span> <strong>${p.full_name}</strong></div>
        <div class="a4-patient-field"><span>Bemor Kodi/ID:</span> <strong style="color: #0284c7;">${p.patient_code}</strong></div>
        <div class="a4-patient-field"><span>Yoshi / Jinsi:</span> <strong>${age} yosh (${genderStr})</strong></div>
        <div class="a4-patient-field"><span>Joylashuvi / Xona:</span> <strong>${roomStr}</strong></div>
        <div class="a4-patient-field"><span>Asosiy Klinik Tashxis:</span> <strong>${primaryDiag}</strong></div>
        <div class="a4-patient-field"><span>XKT-10 (ICD-10) Kodi:</span> <strong>${icdCode}</strong></div>
        <div class="a4-patient-field" style="grid-column: span 2;"><span>Dori Allergiyalari Statusi:</span> <strong style="color: ${!p.medical_allergies ? '#64748b' : (p.medical_allergies.toLowerCase() !== 'yo\'q' ? '#f43f5e' : '#10b981')};">${p.medical_allergies || NOT_RECORDED}</strong></div>
      </div>

      <!-- Main Clinical Content Area -->
      ${mainContentHtml}

      <!-- Official Doctor Signature & Stamp Footer Block -->
      <div class="a4-footer-signature">
        <div>
          <div style="font-weight: 700; color: #0f172a; margin-bottom: 2px;">Mas'ul / Navbatchi Shifokor:</div>
          <div style="font-size: 13px; font-weight: 800; color: #0284c7;">${activeDoc.name}</div>
          <div style="font-size: 10px; color: #64748b;">${activeDoc.title || 'Klinik Narkolog & Psixiatr'}</div>
          <div style="margin-top: 25px; border-top: 1px solid #000; width: 140px; text-align: center; font-size: 9px; color: #64748b;">(Shifokor Imzosi)</div>
        </div>

        <div style="text-align: center;">
          <div class="stamp-box">
            FAYZ MEDICAL HOUSE<br>KLINIKA MUHR O'RNI<br>(OFFICIAL STAMP)
          </div>
        </div>

        <div style="text-align: right;">
          <div style="font-weight: 700; color: #0f172a;">Hujjat Verifikatsiyasi:</div>
          <div style="font-size: 10px; color: #64748b; margin-top: 4px;">Sertifikat kodi: EMR-${p.patient_code}-${Math.floor(Math.random()*8999+1000)}</div>
          <div style="font-size: 10px; color: #64748b;">Chop etilgan vaqt: ${new Date().toLocaleTimeString('uz-UZ')}</div>
          <div style="margin-top: 10px; font-size: 9px; color: #94a3b8;">Ushbu hujjat Fayz Medical House EMR MySQL 8.0 ma'lumotlar bazasi tomonidan tasdiqlangan.</div>
        </div>
      </div>
    `;
  }

  // KPI updater
  function updateKPIs() {
    const chipInpatients = document.getElementById('kpi-inpatients-count');
    const chipPrescriptions = document.getElementById('kpi-rx-count');
    const chipAllergies = document.getElementById('kpi-allergy-count');

    const inpatientsCount = state.patients.filter(p => p.status === 'active' && p.active_admission).length;
    let totalRx = 0;
    Object.values(state.prescriptionsMap).forEach(list => totalRx += list.filter(r => r.status === 'active').length);
    const allergyCount = state.patients.filter(p => p.medical_allergies && p.medical_allergies.toLowerCase() !== 'yo\'q' && p.medical_allergies.trim() !== '').length;

    if (chipInpatients) chipInpatients.textContent = inpatientsCount;
    if (chipPrescriptions) chipPrescriptions.textContent = totalRx;
    if (chipAllergies) chipAllergies.textContent = allergyCount;
  }

  // Tab switcher
  function switchTab(tabId) {
    state.activeTab = tabId;
    document.querySelectorAll('.ws-tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId);
    });
    document.querySelectorAll('.ws-tab-pane').forEach(pane => {
      pane.classList.toggle('active', pane.id === `tab-${tabId}`);
    });
  }

  function setupDrugAutocomplete() {
    const rxInput = document.getElementById('rx-drug-name');
    if (rxInput && window.FMH_MedSearch) {
      rxInput.removeAttribute('list');
      window.FMH_MedSearch.attachAutocomplete({
        input: rxInput,
        getMedications: () => state.pharmacology,
        onSelect: (med) => {
          clearWarehouseItem(); // a different drug picked from the list: drop the earlier warehouse link
          applyMedicationToRxForm(med);
        },
        onInput: (val) => {
          onDrugNameInput(val);
        },
        onClear: () => {
          clearDrugDetailsBanner();
        }
      });
    }

    const modalRxInput = document.getElementById('modal-rx-drug-name');
    if (modalRxInput && window.FMH_MedSearch) {
      modalRxInput.removeAttribute('list');
      window.FMH_MedSearch.attachAutocomplete({
        input: modalRxInput,
        getMedications: () => state.pharmacology,
        onSelect: (med) => {
          if (med) {
            modalRxInput.value = med.name;
            if (med.default_dosage) {
              const el = document.getElementById('modal-rx-dosage');
              if (el) el.value = med.default_dosage;
            }
            if (med.default_route) {
              const rEl = document.getElementById('modal-rx-route');
              if (rEl) {
                for (let i = 0; i < rEl.options.length; i++) {
                  if (rEl.options[i].value.toLowerCase().includes(med.default_route.toLowerCase())) {
                    rEl.selectedIndex = i;
                    break;
                  }
                }
              }
            }
            if (med.default_frequency) {
              const fEl = document.getElementById('modal-rx-frequency');
              if (fEl) {
                for (let i = 0; i < fEl.options.length; i++) {
                  if (fEl.options[i].value.toLowerCase().includes(med.default_frequency.toLowerCase())) {
                    fEl.selectedIndex = i;
                    break;
                  }
                }
              }
            }
            if (med.default_duration) {
              const dEl = document.getElementById('modal-rx-days');
              if (dEl) dEl.value = med.default_duration;
            }
            if (med.instructions) {
              const nEl = document.getElementById('modal-rx-notes');
              if (nEl) nEl.value = med.instructions;
            }
          }
        }
      });
    }
  }

  // Event Listeners setup
  function setupEventListeners() {
    const searchInput = document.getElementById('doctor-patient-search');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        state.searchQuery = e.target.value.trim();
        filterPatients(state.currentFilter);
      });
    }

    setupDrugAutocomplete();
    setupWarehousePanel();
  }

  async function deleteCurrentPatient() {
    const p = state.selectedPatient;
    if (!p) {
      showToast('Iltimos, avval bemorni tanlang!', 'warning');
      return;
    }

    const confirmedDelete = await fmhConfirm({
      title: "Bemorni O'chirish",
      message: `Haqiqatan ham <strong>${p.full_name}</strong> bemorini va uning barcha tibbiy, statsionar va farmakologik qaydlarini butunlay o'chirmoqchimisiz?`,
      confirmText: "O'chirish",
      cancelText: "Bekor Qilish",
      type: 'danger'
    });
    if (!confirmedDelete) {
      return;
    }

    // Only remove the patient from screen once the server has. The answer
    // used to be ignored, so a refused delete (e.g. no permission) still
    // said "fully deleted" while the record stayed in the database.
    try {
      const res = await fetch('/api/patients/' + encodeURIComponent(p.id), { method: 'DELETE' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || "Bemorni o'chirib bo'lmadi.", 'danger');
        return;
      }
    } catch (e) {
      showToast("Server bilan aloqa yo'q. Bemor o'chirilmadi.", 'danger');
      return;
    }

    state.patients = state.patients.filter(pt => pt.id !== p.id);
    state.selectedPatient = null;
    renderPatientList();
    renderWorkstation();
    showToast(`🗑️ "${p.full_name}" bazadan butunlay o'chirildi!`, 'danger');
  }

  // =========================================================================
  // DOCTOR AUTHENTICATION & IDENTITY ENGINE
  // =========================================================================
  // Who is at the keyboard comes from the server session only.
  //
  // This trusted the doctor last saved in localStorage, so on a shared PC the
  // next person to open the page worked -- and signed orders -- under the
  // previous doctor's name. An administrator was made CLINIC_DOCTORS[0], a
  // real doctor, and everything they wrote went out over that doctor's
  // signature. An administrator now works as themselves (no staff id), which
  // the server records as unsigned while the audit trail names the account.
  function doctorFromUser(u, roleLabel) {
    const isDoctor = u.role === 'doctor' || u.role === 'chief_doctor';
    const match = CLINIC_DOCTORS.find(d => d.username === u.username);
    if (match) return { ...match, staff_id: u.staff_id || match.staff_id };
    return {
      username: u.username,
      staff_id: u.staff_id || null,
      name: u.full_name || u.username,
      role: isDoctor ? (u.role === 'chief_doctor' ? 'Bosh Shifokor / Narkolog' : 'Shifokor') : (roleLabel || u.role),
      specialty: u.specialty || '',
      avatar: u.avatar || '👨‍⚕️',
      is_superadmin: !isDoctor
    };
  }

  async function checkDoctorAuth() {
    localStorage.removeItem(STORAGE_KEYS.ACTIVE_DOCTOR);
    let session = null;
    try {
      const res = await fetch('/api/auth/session', { cache: 'no-store' });
      if (res.ok) session = await res.json();
    } catch (e) {}

    if (!session || !session.authenticated || !session.user) {
      state.authenticatedDoctor = null;
      state.activeDoctorId = '';
      showDoctorAuthModal();
      return false;
    }
    state.authenticatedDoctor = doctorFromUser(session.user, session.role_label);
    state.activeDoctorId = state.authenticatedDoctor.staff_id || '';
    hideDoctorAuthModal();
    return true;
  }

  function showDoctorAuthModal() {
    const modal = document.getElementById('doctor-auth-modal');
    if (modal) {
      modal.style.display = 'flex';
      document.body.style.overflow = 'hidden';
    }
  }

  function hideDoctorAuthModal() {
    const modal = document.getElementById('doctor-auth-modal');
    if (modal) {
      modal.style.display = 'none';
      document.body.style.overflow = '';
    }
  }

  function selectAuthPreset(username) {
    // Fills the username only. It used to receive the password as an argument
    // and prefill it, which made the sign-in box decorative: the credential
    // was already in the page.
    const uInput = document.getElementById('auth-doctor-username');
    const pInput = document.getElementById('auth-doctor-password');
    if (uInput) uInput.value = username;
    if (pInput) {
      pInput.value = '';
      pInput.focus();
    }

    document.querySelectorAll('.auth-doc-card').forEach(card => {
      card.classList.toggle('active', card.id === `auth-preset-${username}`);
    });

    const err = document.getElementById('auth-error-msg');
    if (err) err.style.display = 'none';
  }

  async function handleAuthSubmit(e) {
    if (e && e.preventDefault) e.preventDefault();
    const username = (document.getElementById('auth-doctor-username')?.value || '').trim();
    const password = (document.getElementById('auth-doctor-password')?.value || '').trim();
    const errEl = document.getElementById('auth-error-msg');

    if (!username || !password) {
      if (errEl) {
        errEl.innerText = 'Iltimos, login va parolni kiriting!';
        errEl.style.display = 'block';
      }
      return;
    }

    let verified = false;
    let doctorData = null;

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      if (res.ok) {
        const data = await res.json();
        // Success is the status code plus a user object. This used to test
        // data.ok, a field the endpoint never returns, so verification
        // failed even for a correct password and fell through to the
        // local check below.
        if (data.user) {
          verified = true;
          doctorData = doctorFromUser(data.user);
        }
      }
    } catch (netErr) {
      console.warn("Backend auth call failed, checking local credentials", netErr);
    }

    // There is deliberately no local fallback here.
    //
    // This block used to accept a hardcoded username/password pair
    // whenever the server call did not
    // verify -- which, because of the data.ok bug above, was every time.
    // The pair was also visible in this file, so the cabinet gate was an
    // open door into the clinical record. Only the server decides now.

    if (!verified) {
      if (errEl) {
        errEl.innerText = 'Login yoki parol noto\'g\'ri! Shifokor ma\'lumotlarini tekshiring.';
        errEl.style.display = 'block';
      }
      showToast('Noto\'g\'ri login yoki parol!', 'danger');
      return;
    }

    state.authenticatedDoctor = doctorData;
    state.activeDoctorId = doctorData.staff_id || '';

    hideDoctorAuthModal();
    updateDoctorIdentityDisplay();
    filterPatients(state.currentFilter);
    showToast(`✅ Xush kelibsiz, <strong>${doctorData.name}</strong>!`, 'success');
  }

  async function logoutDoctor() {
    const confirmedLogout = await fmhConfirm({
      title: "Kabinetdan Chiqish",
      message: "Haqiqatan ham shifokor shaxsiy kabinetidan chiqmoqchimisiz?",
      confirmText: "Chiqish",
      cancelText: "Bekor Qilish",
      type: 'warning'
    });
    if (!confirmedLogout) return;
    // End the server session too. Clearing only this page left the account
    // signed in, so the next person at a shared PC reloaded straight back
    // into this doctor's cabinet.
    try { await fetch('/api/auth/logout', { method: 'POST' }); } catch (e) {}
    localStorage.removeItem(STORAGE_KEYS.ACTIVE_DOCTOR);
    [STORAGE_KEYS.ANAMNESIS, STORAGE_KEYS.PRESCRIPTIONS, STORAGE_KEYS.DAILY_NOTES]
      .forEach(k => localStorage.removeItem(k));
    state.anamnesisMap = {}; state.prescriptionsMap = {}; state.dailyNotesMap = {}; state.dispensings = {};
    state.authenticatedDoctor = null;
    state.activeDoctorId = '';
    showDoctorAuthModal();
    updateDoctorIdentityDisplay();
    showToast("Shifokor hisobidan chiqildi", "info");
  }

  function updateDoctorIdentityDisplay() {
    const doc = state.authenticatedDoctor || { name: '—', role: '' };
    const nameEl = document.getElementById('active-doctor-display-name');
    const titleEl = document.getElementById('active-doctor-display-title');
    const avatarEl = document.getElementById('active-doctor-avatar');
    const modalDocEl = document.getElementById('case-modal-doctor-name');

    if (nameEl) nameEl.textContent = doc.name;
    if (titleEl) titleEl.textContent = doc.role || doc.specialty || 'Shifokor';
    if (avatarEl) avatarEl.textContent = doc.avatar || '👨‍⚕️';
    if (modalDocEl) modalDocEl.textContent = doc.role || doc.specialty ? `${doc.name} (${doc.role || doc.specialty})` : doc.name;
  }

  // =========================================================================
  // MULTI-STEP CONSULTATION, KASALLIK VARAQASI & RETSEPTLAR WORKFLOW
  // =========================================================================
  async function openNewConsultationModal() {
    if (!state.authenticatedDoctor) {
      showDoctorAuthModal();
      return;
    }

    const form = document.getElementById('new-case-form');
    if (form) form.reset();

    state.newCase = {
      step: 1,
      intakeType: 'outpatient',
      prescriptions: []
    };

    updateDoctorIdentityDisplay();
    toggleIntakeType('outpatient');
    switchCaseStep(1);
    renderModalPrescriptions();
    await loadBedOptionsForModal();

    const modal = document.getElementById('doctor-consultation-case-modal');
    if (modal) {
      modal.style.display = 'flex';
      document.body.style.overflow = 'hidden';
    }
  }

  function closeNewConsultationModal() {
    const modal = document.getElementById('doctor-consultation-case-modal');
    if (modal) {
      modal.style.display = 'none';
      document.body.style.overflow = '';
    }
  }

  function toggleIntakeType(type) {
    state.newCase.intakeType = type;
    const optOut = document.getElementById('opt-intake-outpatient');
    const optIn = document.getElementById('opt-intake-inpatient');
    const bedSec = document.getElementById('inpatient-room-bed-section');

    if (type === 'inpatient') {
      optIn?.classList.add('selected');
      optOut?.classList.remove('selected');
      if (bedSec) bedSec.style.display = 'block';
    } else {
      optOut?.classList.add('selected');
      optIn?.classList.remove('selected');
      if (bedSec) bedSec.style.display = 'none';
    }
  }

  async function loadBedOptionsForModal() {
    const select = document.getElementById('case-bed-select');
    if (!select) return;

    select.innerHTML = '<option value="">— Koykani tanlang —</option>';

    let beds = [];
    try {
      const res = await fetch('/api/facility/rooms');
      if (res.ok) {
        const data = await res.json();
        if (data && data.floors) {
          data.floors.forEach(fl => {
            (fl.rooms || []).forEach(rm => {
              (rm.beds || []).forEach(bd => {
                beds.push({
                  bed_id: bd.bed_id || bd.id,
                  room_number: rm.room_number || rm.name_uz,
                  bed_number: bd.bed_number || bd.label,
                  room_type: rm.room_type || bd.type || 'Standart',
                  status: bd.status || 'available',
                  patient_name: bd.patient_name || ''
                });
              });
            });
          });
        }
      }
    } catch (e) {
      console.warn("Could not load /api/facility/rooms, using fallback beds", e);
    }

    if (beds.length === 0) {
      const fallbackRooms = [
        { room: "11", type: "Standart", beds: ["1A", "1B"] },
        { room: "12", type: "Standart", beds: ["2A", "2B"] },
        { room: "21", type: "VIP", beds: ["3A", "3B"] },
        { room: "22", type: "VIP", beds: ["4A", "4B"] },
        { room: "23", type: "Standart", beds: ["5A", "5B"] },
        { room: "24", type: "Standart", beds: ["6A", "6B"] },
        { room: "25", type: "Standart", beds: ["7A", "7B"] }
      ];
      fallbackRooms.forEach(r => {
        r.beds.forEach(b => {
          beds.push({
            bed_id: `BED-${b}`,
            room_number: r.room,
            bed_number: b,
            room_type: r.type,
            status: 'available',
            patient_name: ''
          });
        });
      });
    }

    select.innerHTML = '<option value="">— Bo\'sh koykani tanlang —</option>' + beds.map(b => {
      const isOccupied = b.status === 'occupied' || (b.patient_name && b.patient_name.trim() !== '');
      const label = `${b.room_number}-xona (${b.room_type}) — Koyka ${b.bed_number} ${isOccupied ? `[Band: ${b.patient_name}]` : "[Bo'sh]"}`;
      return `<option value="${b.bed_id}" data-room="${b.room_number}" data-bed="${b.bed_number}" data-type="${b.room_type}" ${isOccupied ? 'disabled style="color: #94a3b8;"' : ''}>${label}</option>`;
    }).join('');

    select.onchange = () => {
      const opt = select.options[select.selectedIndex];
      const roomType = opt ? opt.getAttribute('data-type') : 'Standart';
      const typeInput = document.getElementById('case-room-type');
      if (typeInput) typeInput.value = roomType || 'Standart';
    };
  }

  function switchCaseStep(step) {
    if (step < 1 || step > 3) return;

    if (step > 1) {
      const name = document.getElementById('case-patient-name')?.value.trim();
      const dob = document.getElementById('case-patient-dob')?.value.trim();
      const phone = document.getElementById('case-patient-phone')?.value.trim();

      if (!name || !dob || !phone) {
        showToast("Iltimos, bemorning F.I.Sh., yoshi va telefon raqamini to'liq kiriting!", "warning");
        return;
      }

      if (state.newCase.intakeType === 'inpatient') {
        const bed = document.getElementById('case-bed-select')?.value;
        if (!bed) {
          showToast("Statsionar yotqizish uchun xona va koykani tanlang!", "warning");
          return;
        }
      }
    }

    if (step > 2) {
      const complaints = document.getElementById('case-complaints')?.value.trim();
      const diagnosis = document.getElementById('case-diagnosis')?.value.trim();

      if (!complaints || !diagnosis) {
        showToast("Iltimos, asosiy shikoyatlar va klinik tashxisni kiriting!", "warning");
        return;
      }
    }

    state.newCase.step = step;

    [1, 2, 3].forEach(n => {
      const tab = document.getElementById(`case-tab-btn-${n}`);
      const pane = document.getElementById(`case-step-${n}`);
      if (tab) tab.classList.toggle('active', n === step);
      if (pane) pane.classList.toggle('active', n === step);
    });

    const btnPrev = document.getElementById('btn-case-prev');
    const btnNext = document.getElementById('btn-case-next');
    const btnSubmit = document.getElementById('btn-case-submit');

    if (btnPrev) btnPrev.style.display = step > 1 ? 'inline-flex' : 'none';
    if (btnNext) {
      btnNext.style.display = step < 3 ? 'inline-flex' : 'none';
      if (step === 2) {
        btnNext.innerHTML = 'Keyingisi: Retsept va Dori Tayinlash <i class="fas fa-arrow-right"></i>';
      } else {
        btnNext.innerHTML = 'Davom Etish <i class="fas fa-arrow-right"></i>';
      }
    }
    if (btnSubmit) btnSubmit.style.display = step === 3 ? 'inline-flex' : 'none';
  }

  function nextCaseStep() {
    switchCaseStep(state.newCase.step + 1);
  }

  function prevCaseStep() {
    switchCaseStep(state.newCase.step - 1);
  }

  async function addModalPrescriptionRow() {
    const drugNameInput = document.getElementById('modal-rx-drug-name');
    const dosageInput = document.getElementById('modal-rx-dosage');
    const routeSelect = document.getElementById('modal-rx-route');
    const freqSelect = document.getElementById('modal-rx-frequency');
    const daysInput = document.getElementById('modal-rx-days');
    const notesInput = document.getElementById('modal-rx-notes');

    const drugName = (drugNameInput?.value || '').trim();
    if (!drugName) {
      showToast("Iltimos, dori vositasi nomini kiriting!", "warning");
      return;
    }

    const dosage = (dosageInput?.value || '').trim();
    const durationDays = parseInt(daysInput?.value) || 5;
    const frequency = freqSelect?.value || 'Kuniga 2 mahal';
    const notes = (notesInput?.value || '').trim();
    const fullInstructions = notes ? `${frequency} (${notes})` : frequency;

    if (!dosage) {
      showToast("Iltimos, bir martalik dozani kiriting (masalan: 400 ml, 1 tab, 2 ml).", "warning");
      return;
    }

    const allergyText = (document.getElementById('case-allergies')?.value || '').toLowerCase();
    const dLower = drugName.toLowerCase();
    if (allergyText && allergyText !== 'yo\'q') {
      if ((dLower.includes('novo') && allergyText.includes('novo')) ||
          (dLower.includes('peni') && allergyText.includes('peni')) ||
          (dLower.includes('sulfa') && allergyText.includes('sulfa'))) {
        const confirmAllergy = await fmhConfirm({
          title: "⚠️ Allergik Xavf",
          message: `Ushbu bemorda allergik xavf qayd etilgan: <strong>${allergyText}</strong>.<br><br>Baribir retseptga qo'shasizmi?`,
          confirmText: "Baribir Qo'shish",
          cancelText: "Bekor Qilish",
          type: 'warning'
        });
        if (!confirmAllergy) return;
      }
    }

    const item = {
      id: 'RX-' + Math.floor(Math.random() * 90000 + 10000),
      medication_name: drugName,
      form: routeSelect?.value.includes('tomchi') ? 'Infuzion flakon' : (routeSelect?.value.includes('per os') ? 'Tabletkalar' : 'Ampula'),
      dosage: dosage,
      route: routeSelect?.value || '',
      duration_days: durationDays,
      frequency: frequency,
      timing: 'Muolaja jadvali bo\'yicha',
      instructions: fullInstructions,
      status: 'active'
    };

    state.newCase.prescriptions.push(item);
    renderModalPrescriptions();

    if (drugNameInput) drugNameInput.value = '';
    if (dosageInput) dosageInput.value = '';
    if (notesInput) notesInput.value = '';
    showToast(`💊 "${item.medication_name}" tayinlovlar ro'yxatiga qo'shildi!`, "info");
  }

  function removeModalPrescriptionRow(idx) {
    if (idx >= 0 && idx < state.newCase.prescriptions.length) {
      const removed = state.newCase.prescriptions.splice(idx, 1);
      renderModalPrescriptions();
      showToast(`O'chirildi: ${removed[0]?.medication_name}`, "info");
    }
  }

  function renderModalPrescriptions() {
    const tbody = document.getElementById('modal-prescriptions-table-body');
    if (!tbody) return;

    if (state.newCase.prescriptions.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" style="text-align: center; padding: 24px; color: #64748b;">
            Hali retsept qo'shilmagan. Yuqoridagi formadan qo'shing yoki tayyor protokollarni bosing.
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = state.newCase.prescriptions.map((rx, idx) => `
      <tr style="border-bottom: 1px solid rgba(255,255,255,0.06);">
        <td style="padding: 8px 12px; font-weight: 700; color: #38bdf8;">${idx + 1}</td>
        <td style="padding: 8px 12px;"><strong style="color: #f1f5f9;">${rx.medication_name}</strong></td>
        <td style="padding: 8px 12px; color: #a5f3fc; font-family: monospace;">${rx.dosage}</td>
        <td style="padding: 8px 12px;"><span class="status-pill status-completed" style="font-size: 0.72rem;">${rx.route}</span></td>
        <td style="padding: 8px 12px; font-weight: 600;">${rx.duration_days} kun</td>
        <td style="padding: 8px 12px; color: #cbd5e1; font-size: 0.78rem;">${rx.frequency}</td>
        <td style="padding: 8px 12px; text-align: center;">
          <button type="button" class="btn-doc-danger" style="padding: 2px 8px; font-size: 0.7rem;" onclick="window.FMH_Doctor.removeModalPrescriptionRow(${idx})" title="O'chirish">
            <i class="fas fa-trash"></i>
          </button>
        </td>
      </tr>
    `).join('');
  }

  function applyModalPreset(presetKey) {
    let presetItems = [];
    if (presetKey === 'detox') {
      presetItems = [
        { medication_name: 'Reosorbilakt 400ml', form: 'Infuzion flakon', dosage: '400 ml', route: 'v/i tomchilab', duration_days: 3, frequency: '1 marta ertalab, k/k sekin' },
        { medication_name: 'Natriy Xlorid 0.9% 400ml', form: 'Infuzion flakon', dosage: '400 ml', route: 'v/i tomchilab', duration_days: 3, frequency: '1 marta kunduzi, k/k' },
        { medication_name: 'Magniy sulfat 25% 10ml', form: 'Ampula', dosage: '10 ml', route: 'v/i tomchilab', duration_days: 3, frequency: '1 marta NaCl bilan birga' },
        { medication_name: 'Askorbin kislotasi (Vit C) 5%', form: 'Ampula', dosage: '4 ml', route: 'v/i tomchilab', duration_days: 3, frequency: '1 marta tomchilab' },
        { medication_name: 'Piratsetam 20% 10ml', form: 'Ampula', dosage: '10 ml', route: 'v/i tomchilab', duration_days: 5, frequency: '1 marta ertalab' }
      ];
    } else if (presetKey === 'abstinence_heavy') {
      presetItems = [
        { medication_name: 'Reamberin 1.5% 400ml', form: 'Infuzion flakon', dosage: '400 ml', route: 'v/i tomchilab', duration_days: 4, frequency: '1 marta ertalab, k/k' },
        { medication_name: 'Diazepam (Relanium) 0.5% 2ml', form: 'Ampula', dosage: '2 ml', route: 'v/m inyeksiya', duration_days: 3, frequency: '2 marta (ertalab/kechqurun)' },
        { medication_name: 'Tiamin xlorid (B1) 5% 1ml', form: 'Ampula', dosage: '2 ml', route: 'v/m inyeksiya', duration_days: 5, frequency: '1 marta mushak ichiga' },
        { medication_name: 'Piridoksin (B6) 5% 1ml', form: 'Ampula', dosage: '2 ml', route: 'v/m inyeksiya', duration_days: 5, frequency: '1 marta mushak ichiga' },
        { medication_name: 'Metoklopramid (Serukal) 2ml', form: 'Ampula', dosage: '2 ml', route: 'v/m inyeksiya', duration_days: 2, frequency: 'Ko\'ngil aynaganda v/m' }
      ];
    } else if (presetKey === 'sedation') {
      presetItems = [
        { medication_name: 'Diazepam 10mg / 2ml', form: 'Ampula', dosage: '2 ml', route: 'v/m inyeksiya', duration_days: 3, frequency: '1 marta uyqudan 30 daqiqa oldin' },
        { medication_name: 'Fenazepam 1mg', form: 'Tabletkalar', dosage: '1 tab (1mg)', route: 'per os', duration_days: 5, frequency: 'Kechqurun uyqudan oldin' },
        { medication_name: 'Karbamazepin 200mg', form: 'Tabletkalar', dosage: '100 mg (1/2 tab)', route: 'per os', duration_days: 7, frequency: 'Kechqurun qabul qilish' }
      ];
    } else if (presetKey === 'hepatoprotect') {
      presetItems = [
        { medication_name: 'Essentiale Forte N 5ml', form: 'Ampula', dosage: '5 ml', route: 'v/i oqim bilan', duration_days: 5, frequency: '1 marta sekin v/i oqimli' },
        { medication_name: 'Geptral (Ademetionin) 400mg', form: 'Flakon', dosage: '400 mg', route: 'v/i tomchilab', duration_days: 5, frequency: '1 marta fiziologik eritmada' },
        { medication_name: 'Glukoza 5% 400ml + Insulin 4TB', form: 'Infuzion flakon', dosage: '400 ml', route: 'v/i tomchilab', duration_days: 3, frequency: '1 marta tushlikda' }
      ];
    }

    presetItems.forEach(item => {
      state.newCase.prescriptions.push({
        id: 'RX-' + Math.floor(Math.random() * 90000 + 10000),
        status: 'active',
        timing: 'Klinik protokol',
        instructions: item.frequency,
        ...item
      });
    });

    renderModalPrescriptions();
    showToast(`⚡ Protokol bo'yicha ${presetItems.length} ta dori ro'yxatga kiritildi!`, "success");
  }

  async function handleCaseSubmit(e) {
    if (e && e.preventDefault) e.preventDefault();

    if (!state.authenticatedDoctor) {
      showToast("Iltimos, avval shifokor kabinetiga kiring!", "danger");
      showDoctorAuthModal();
      return;
    }

    const name = document.getElementById('case-patient-name')?.value.trim();
    const dob = document.getElementById('case-patient-dob')?.value.trim();
    const gender = document.getElementById('case-patient-gender')?.value || '';
    const phone = document.getElementById('case-patient-phone')?.value.trim();
    const address = document.getElementById('case-patient-address')?.value.trim() || '';
    const passport = document.getElementById('case-patient-passport')?.value.trim() || '';
    const relative = document.getElementById('case-patient-relative')?.value.trim() || '';

    const complaints = document.getElementById('case-complaints')?.value.trim();
    const anamnesisMorbi = document.getElementById('case-anamnesis-morbi')?.value.trim() || '';
    const anamnesisVitae = document.getElementById('case-anamnesis-vitae')?.value.trim() || '';
    const allergies = document.getElementById('case-allergies')?.value.trim() || '';
    // Only the vitals actually entered; blanks used to become 120/80, 76,
    // 36.6 and 98% in the saved somatic status.
    const vitalVal = (id) => (document.getElementById(id)?.value || '').trim();
    const somaticStatus = [
      ['AQB', vitalVal('case-vital-bp')], ['Puls', vitalVal('case-vital-pulse')],
      ['Temp', vitalVal('case-vital-temp')], ['SpO2', vitalVal('case-vital-spo2')]
    ].filter(([, v]) => v).map(([k, v]) => `${k}: ${v}`).join(', ');
    const psychiatricStatus = document.getElementById('case-mental-status')?.value.trim() || '';
    const icdCode = document.getElementById('case-icd-code')?.value.trim() || '';
    const diagnosis = document.getElementById('case-diagnosis')?.value.trim();

    if (!name || !dob || !phone || !complaints || !diagnosis) {
      showToast("Iltimos, barcha majburiy klinik maydonlarni to'ldiring!", "warning");
      return;
    }

    let birthYear = null;
    const yearMatch = dob.match(/\b(19\d\d|20\d\d)\b/);
    if (yearMatch) birthYear = parseInt(yearMatch[1]);

    const bedSelect = document.getElementById('case-bed-select');
    const selectedBedOption = bedSelect && bedSelect.selectedIndex >= 0 ? bedSelect.options[bedSelect.selectedIndex] : null;
    const bedId = bedSelect?.value || null;
    const roomType = document.getElementById('case-room-type')?.value || 'Standart';
    const stayDays = parseInt(document.getElementById('case-stay-days')?.value) || 7;

    const payload = {
      doctor_id: state.authenticatedDoctor.staff_id,
      doctor_name: state.authenticatedDoctor.name,
      patient_name: name,
      patient_phone: phone,
      gender: gender === 'Ayol' ? 'female' : (gender === 'Erkak' ? 'male' : null),
      birth_year: birthYear,
      address: address,
      emergency_contact: relative,
      allergic_status: allergies,
      consultation_type: state.newCase.intakeType,
      inpatient_details: state.newCase.intakeType === 'inpatient' ? {
        bed_id: bedId,
        room_number: selectedBedOption ? selectedBedOption.getAttribute('data-room') : '11',
        bed_number: selectedBedOption ? selectedBedOption.getAttribute('data-bed') : '1A',
        program_type: `${roomType} Statsionar davolash kursi`,
        start_date: new Date().toISOString().split('T')[0],
        end_date: new Date(Date.now() + stayDays * 86400000).toISOString().split('T')[0],
        // The rate comes from the one price list (js/fmh_pricing.js), not
        // a typed-in 1 100 000 / 720 000. A 0 (list not loaded) is left to
        // the server, which then bills the listed shared rate.
        daily_price: (window.FMH_Pricing
          ? window.FMH_Pricing.rate(roomType === 'VIP' ? 'statsionar_full_room' : 'statsionar_shared')
          : 0) || null
      } : null,
      anamnesis: {
        complaints: complaints,
        anamnesis_morbi: anamnesisMorbi,
        anamnesis_vitae: anamnesisVitae,
        allergic_status: allergies,
        somatic_status: somaticStatus,
        psychiatric_status: psychiatricStatus,
        diagnosis_primary: diagnosis,
        diagnosis_secondary: passport ? `Pasport/PINFL: ${passport}` : '',
        icd10_code: icdCode
      },
      prescriptions: state.newCase.prescriptions
    };

    const submitBtn = document.getElementById('btn-case-submit');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saqlanmoqda...';
    }

    try {
      const res = await fetch('/api/doctor/consultation-case', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      let resData = {};
      try { resData = await res.json(); } catch (e) {}

      if (res.ok && (resData.success || resData.patient_id)) {
        const patientId = resData.patient_id;
        const patientCode = resData.patient_code;

        const newPatient = {
          id: patientId,
          patient_code: patientCode,
          full_name: name,
          gender: payload.gender,
          birth_year: birthYear,
          phone: phone,
          address: address,
          medical_allergies: allergies,
          doctor_id: state.authenticatedDoctor.staff_id,
          doctor_name: state.authenticatedDoctor.name,
          consulting_doctor_id: state.authenticatedDoctor.staff_id,
          consulting_doctor_name: state.authenticatedDoctor.name,
          status: 'active',
          active_admission: state.newCase.intakeType === 'inpatient' ? {
            admission_id: resData.admission_id,
            room_number: payload.inpatient_details.room_number,
            bed_code: payload.inpatient_details.bed_number,
            doctor_id: state.authenticatedDoctor.staff_id,
            doctor_name: state.authenticatedDoctor.name,
            program_type: payload.inpatient_details.program_type
          } : null
        };

        state.anamnesisMap[patientId] = {
          patient_id: patientId,
          admission_id: resData.admission_id,
          doctor_id: state.authenticatedDoctor.staff_id,
          complaints: complaints,
          anamnesis_morbi: anamnesisMorbi,
          anamnesis_vitae: anamnesisVitae,
          allergic_status: allergies,
          somatic_status: somaticStatus,
          psychiatric_status: psychiatricStatus,
          diagnosis_primary: diagnosis,
          diagnosis_secondary: passport ? `Pasport/PINFL: ${passport}` : '',
          icd10_code: icdCode
        };
        localStorage.setItem(STORAGE_KEYS.ANAMNESIS, JSON.stringify(state.anamnesisMap));

        if (state.newCase.prescriptions.length > 0) {
          state.prescriptionsMap[patientId] = state.newCase.prescriptions.map(rx => ({
            ...rx,
            doctor_name: state.authenticatedDoctor.name
          }));
          localStorage.setItem(STORAGE_KEYS.PRESCRIPTIONS, JSON.stringify(state.prescriptionsMap));
        }

        state.patients.unshift(newPatient);
        filterPatients(state.currentFilter);
        selectPatient(newPatient);

        closeNewConsultationModal();
        showToast(`✅ Bemor "${name}" uchun kasallik varaqasi va ${state.newCase.prescriptions.length} ta retsept muvaffaqiyatli saqlandi!`, "success");

        if (state.newCase.prescriptions.length > 0) {
          setTimeout(() => {
            window.FMH_ConfirmDialog({
              title: "Muolaja Varaqasini Chop Etish",
              message: `Bemor <strong>${name}</strong> uchun rasmiy muolaja varaqasini (List Naznacheniy / A4) hozir chop etasizmi?`,
              confirmText: "Chop Etish",
              cancelText: "Keyinroq",
              type: 'primary',
              onConfirm: () => openOfficialDocModal('prescriptions')
            });
          }, 300);
        }

        updateKPIs();
      } else {
        showToast(resData.error || "Xatolik yuz berdi. Qayta urinib ko'ring.", "danger");
      }
    } catch (err) {
      console.error("Consultation case error:", err);
      showToast("Server bilan bog'lanishda xatolik!", "danger");
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-check-circle"></i> Tasdiqlash & Kasallik Varaqasini Ochish';
      }
    }
  }

  // Global window exposure
  window.FMH_Doctor = {
    init,
    toggleTheme,
    selectPatientById,
    filterPatients,
    clearSearch,
    quickJump,
    switchTab,
    goToPrescriptionMenu,
    finalizeConsultation,
    saveAnamnesis,
    saveEpicrisis,
    applyAnamnesisTemplate,
    applyDiagnosisPreset,
    addPrescription,
    applyPresetProtocol,
    setRxField,
    filterRxTable,
    toggleRxStatus,
    deletePrescription,
    deleteCurrentPatient,
    addDailyNote,
    appendDynamicsPhrase,
    setTreatmentPhrase,
    autoGenerateEpicrisis,
    appendHomeRx,
    setPsychoRec,
    onDrugNameInput,
    onDrugNameChange,
    quickSelectMed,
    clearDrugDetailsBanner,
    applyMedicationToRxForm,
    findMedication,
    openClinicMedsModal,
    closeClinicMedsModal,
    onClinicMedsFilter,
    clearClinicMedsSearch,
    setClinicCat,
    fillFormWithMed,
    prescribeClinicMed,
    openOfficialDocModal,
    closeOfficialDocModal,
    renderOfficialDocumentPreview,
    printOfficialDocument,
    printPrescriptionSheet: () => printOfficialDocument('prescriptions'),
    printEpicrisis: () => printOfficialDocument('epicrisis'),
    downloadPDF,

    // Doctor Auth & Identity
    checkDoctorAuth,
    showDoctorAuthModal,
    hideDoctorAuthModal,
    selectAuthPreset,
    handleAuthSubmit,
    logoutDoctor,
    updateDoctorIdentityDisplay,

    // Consultation & Case Sheet Engine
    openNewConsultationModal,
    closeNewConsultationModal,
    toggleIntakeType,
    loadBedOptionsForModal,
    switchCaseStep,
    nextCaseStep,
    prevCaseStep,
    addModalPrescriptionRow,
    removeModalPrescriptionRow,
    renderModalPrescriptions,
    applyModalPreset,
    handleCaseSubmit
  };

  // Auto-init on DOM ready (with readyState check to run if already loaded)
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
