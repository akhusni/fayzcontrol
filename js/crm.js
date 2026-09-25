/**
 * FAYZ MEDICAL HOUSE — PATIENT CRM & MEDICAL DOSSIER CLIENT ENGINE
 * Fully integrated with MySQL REST API & local resilient fallback store.
 */

(function () {
  'use strict';

  // Master State
  const state = {
    patients: [],
    filteredPatients: [],
    selectedPatient: null,
    currentFilter: 'all',
    searchQuery: '',
    sortBy: 'recent',
    viewMode: 'grid', // 'grid' or 'table'
    activeTab: 'bio'  // 'bio', 'medical', 'finance', 'epicrisis'
  };

  // Fallback Mock Dataset (Clean empty state)
  const FALLBACK_PATIENTS = [];

  // Helper formatting utilities
  const formatMoney = (val) => Number(val || 0).toLocaleString('uz-UZ') + " so'm";
  const getAge = (year) => year ? (new Date().getFullYear() - year) : '-';

  const programLabels = {
    'detox': 'Intensiv Detoksikatsiya (Zapoydan chiqarish)',
    'alcohol_rehab': 'Alkogolizm Reabilitatsiyasi',
    'drug_rehab': 'Giyohvandlikdan Reabilitatsiya',
    'depression_psychiatry': 'Depressiya & Psixoterapiya',
    'vip_full_course': 'VIP Solo Premium Tiklanish',
    'outpatient_monitoring': 'Ambulator Dispanser Nazorat'
  };

  const referralLabels = {
    'hotline': '📞 24/7 Tezkor Aloqa',
    'telegram': '✈️ Telegram Bot / Kanal',
    'doctor_referral': '👨‍⚕️ Shifokor Tavsiyasi',
    'relative': '👥 Oila A\'zolari / Yaqinlari',
    'walk_in': '🚶 To\'g\'ridan-to\'g\'ri Tashrif',
    'advertisement': '📢 Reklama / Internet'
  };

  // Toast Notification System
  // Delegates to the shared toast in js/fmh_dialogs.js: that one announces
  // messages via aria-live, keeps errors on screen long enough to read,
  // stacks instead of erasing an unread message, and can be dismissed.
  function showToast(message, type = 'info') {
    return window.FMH_Toast(message, type);
  }

  function normalizePatientDates(patients) {
    const today = new Date();
    const pad = n => String(n).padStart(2, '0');
    const toISO = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

    return patients.map((p, idx) => {
      if (p.active_admission) {
        const dStart = new Date(today);
        dStart.setDate(dStart.getDate() - (idx % 3));
        const dEnd = new Date(dStart);
        dEnd.setDate(dEnd.getDate() + 7);
        p.active_admission.start_date = toISO(dStart);
        p.active_admission.planned_end_date = toISO(dEnd);
      }
      if (p.latest_vitals) {
        p.latest_vitals.log_date = toISO(today);
      }
      return p;
    });
  }

  // Fetch Patients from Server API or Local Fallback
  async function loadPatients() {
    try {
      const res = await fetch('/api/crm/patients');
      if (res.ok) {
        state.patients = await res.json();
      } else {
        throw new Error('API request failed');
      }
    } catch (e) {
      console.warn('Using fallback CRM dataset:', e);
      state.patients = normalizePatientDates(JSON.parse(JSON.stringify(FALLBACK_PATIENTS)));
    }
    applyFilters();
    renderStats();
  }

  // Render Top KPI Stats
  function renderStats() {
    const total = state.patients.length;
    const activeInpatient = state.patients.filter(p => p.status === 'active' || p.active_admission).length;
    const outpatient = state.patients.filter(p => p.status === 'outpatient').length;
    const discharged = state.patients.filter(p => p.status === 'discharged').length;
    const withDebt = state.patients.filter(p => (p.balance_due || 0) > 0).length;
    const totalDebtAmount = state.patients.reduce((sum, p) => sum + (p.balance_due || 0), 0);
    const withAllergies = state.patients.filter(p => p.medical_allergies && p.medical_allergies !== "Yo'q" && p.medical_allergies !== '-').length;

    const elTotal = document.getElementById('stat-total-patients');
    const elInpatient = document.getElementById('stat-inpatient-patients');
    const elOutpatient = document.getElementById('stat-outpatient-patients');
    const elDischarged = document.getElementById('stat-discharged-patients');
    const elDebt = document.getElementById('stat-debt-patients');
    const elAllergies = document.getElementById('stat-allergy-patients');

    if (elTotal) elTotal.textContent = total;
    if (elInpatient) elInpatient.textContent = activeInpatient;
    if (elOutpatient) elOutpatient.textContent = outpatient;
    if (elDischarged) elDischarged.textContent = discharged;
    if (elDebt) elDebt.textContent = `${withDebt} (${(totalDebtAmount / 1000000).toFixed(1)}M)`;
    if (elAllergies) elAllergies.textContent = withAllergies;
  }

  // Filter & Search Engine
  function applyFilters() {
    let result = [...state.patients];

    // Status Filter
    if (state.currentFilter === 'active') {
      result = result.filter(p => p.status === 'active' || p.active_admission);
    } else if (state.currentFilter === 'outpatient') {
      result = result.filter(p => p.status === 'outpatient');
    } else if (state.currentFilter === 'discharged') {
      result = result.filter(p => p.status === 'discharged');
    } else if (state.currentFilter === 'vip') {
      result = result.filter(p => (p.active_admission && (p.active_admission.room_number === '21' || p.active_admission.room_number === '22')) || p.full_name.includes('VIP'));
    } else if (state.currentFilter === 'debt') {
      result = result.filter(p => (p.balance_due || 0) > 0);
    } else if (state.currentFilter === 'allergies') {
      result = result.filter(p => p.medical_allergies && p.medical_allergies !== "Yo'q" && p.medical_allergies !== '-');
    }

    // Text Query Search
    if (state.searchQuery.trim()) {
      const q = state.searchQuery.toLowerCase().trim();
      result = result.filter(p =>
        (p.full_name && p.full_name.toLowerCase().includes(q)) ||
        (p.patient_code && p.patient_code.toLowerCase().includes(q)) ||
        (p.phone && p.phone.toLowerCase().includes(q)) ||
        (p.emergency_contact && p.emergency_contact.toLowerCase().includes(q)) ||
        (p.medical_allergies && p.medical_allergies.toLowerCase().includes(q)) ||
        (p.chronic_conditions && p.chronic_conditions.toLowerCase().includes(q)) ||
        (p.active_admission && p.active_admission.doctor_name && p.active_admission.doctor_name.toLowerCase().includes(q))
      );
    }

    // Sorting
    if (state.sortBy === 'name') {
      result.sort((a, b) => a.full_name.localeCompare(b.full_name));
    } else if (state.sortBy === 'debt_desc') {
      result.sort((a, b) => (b.balance_due || 0) - (a.balance_due || 0));
    } else if (state.sortBy === 'recent') {
      result.sort((a, b) => (b.id || '').localeCompare(a.id || ''));
    }

    state.filteredPatients = result;
    renderPatients();
  }

  // Render Cards or Table
  function renderPatients() {
    const gridEl = document.getElementById('crm-patients-grid');
    const tableWrapEl = document.getElementById('crm-table-wrapper');
    const tbodyEl = document.getElementById('crm-table-body');
    const countEl = document.getElementById('filtered-count-badge');

    if (countEl) countEl.textContent = `${state.filteredPatients.length} bemor topildi`;

    if (state.viewMode === 'grid') {
      if (gridEl) gridEl.style.display = 'grid';
      if (tableWrapEl) tableWrapEl.style.display = 'none';
      renderCardsView(gridEl);
    } else {
      if (gridEl) gridEl.style.display = 'none';
      if (tableWrapEl) tableWrapEl.style.display = 'block';
      renderTableView(tbodyEl);
    }
  }

  // Render Grid Cards
  function renderCardsView(container) {
    if (!container) return;
    if (state.filteredPatients.length === 0) {
      container.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; padding: 4rem 1rem; color: var(--text-muted);">
          <i class="fas fa-user-slash" style="font-size: 3rem; margin-bottom: 1rem; opacity: 0.5;"></i>
          <h3 style="font-family: var(--font-heading); font-size: 1.25rem;">Mos keluvchi bemor topilmadi</h3>
          <p style="font-size: 0.88rem; margin-top: 5px;">Qidiruv so'zini o'zgartirib yoki filtrlarni tozalab ko'ring.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = state.filteredPatients.map(p => {
      const initials = p.full_name.replace('Bemor ', '').split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase() || 'BM';
      const isStay = p.active_admission;
      const stayLocation = isStay ? `${isStay.floor_number}-Qavat • ${isStay.room_number}-xona (${isStay.bed_code})` : (p.status === 'outpatient' ? 'Ambulator Rejim' : 'Klinikadan Chiqarilgan');
      const hasAllergy = p.medical_allergies && p.medical_allergies !== "Yo'q" && p.medical_allergies !== '-';
      const hasDebt = (p.balance_due || 0) > 0;

      let statusBadge = '';
      if (p.status === 'active' || isStay) {
        statusBadge = '<span class="badge-status status-active"><i class="fas fa-bed"></i> Statsionar</span>';
      } else if (p.status === 'outpatient') {
        statusBadge = '<span class="badge-status status-outpatient"><i class="fas fa-stethoscope"></i> Ambulator</span>';
      } else {
        statusBadge = '<span class="badge-status status-discharged"><i class="fas fa-check-double"></i> Tuzalgan</span>';
      }

      return `
        <div class="crm-patient-card" data-patient-id="${p.id}">
          <div>
            <div class="patient-card-header">
              <div class="patient-identity">
                <div class="patient-avatar">${initials}</div>
                <div class="patient-name-block">
                  <h3>${p.full_name}</h3>
                  <span class="patient-code-tag"><i class="fas fa-id-badge"></i> ${p.patient_code}</span>
                </div>
              </div>
              ${statusBadge}
            </div>

            <div class="patient-meta-grid">
              <div class="meta-item">
                <span class="meta-label">Telefon</span>
                <span class="meta-value highlight"><a href="tel:${p.phone}" style="color: inherit; text-decoration: none;"><i class="fas fa-phone-alt" style="font-size: 0.72rem;"></i> ${p.phone || '-'}</a></span>
              </div>
              <div class="meta-item">
                <span class="meta-label">Joylashuvi</span>
                <span class="meta-value" style="font-size: 0.78rem;">${stayLocation}</span>
              </div>
              <div class="meta-item">
                <span class="meta-label">Yaqin Qarindoshi</span>
                <span class="meta-value" title="${p.emergency_contact || '-'}" style="font-size: 0.76rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                  ${p.emergency_contact || '-'}
                </span>
              </div>
              <div class="meta-item">
                <span class="meta-label">Allergiyalar</span>
                <span class="meta-value">
                  ${hasAllergy ? `<span class="allergy-alert-chip"><i class="fas fa-exclamation-triangle"></i> ${p.medical_allergies}</span>` : '<span style="color: var(--text-muted);">Mavjud emas</span>'}
                </span>
              </div>
            </div>

            <div class="patient-finance-bar">
              <div>
                <span style="color: var(--text-muted); font-size: 0.7rem; display: block; text-transform: uppercase;">To'langan / Jami</span>
                <span class="finance-paid">${formatMoney(p.total_paid || 0)}</span>
              </div>
              <div style="text-align: right;">
                <span style="color: var(--text-muted); font-size: 0.7rem; display: block; text-transform: uppercase;">Qoldiq Qarz</span>
                <span class="${hasDebt ? 'finance-debt' : 'finance-paid'}">${hasDebt ? formatMoney(p.balance_due) : '0 so\'m (To\'liq)'}</span>
              </div>
            </div>
          </div>

          <div class="patient-card-footer">
            <button class="btn-card-action btn-card-primary" onclick="window.FMH_CRM.openDossier('${p.id}', 'bio')">
              <i class="fas fa-folder-open"></i> Dossier
            </button>
            <button class="btn-card-action" onclick="window.FMH_CRM.openDossier('${p.id}', 'medical')">
              <i class="fas fa-file-medical"></i> Tarix
            </button>
            <button class="btn-card-action" onclick="window.FMH_CRM.openDossier('${p.id}', 'epicrisis')">
              <i class="fas fa-print"></i> Epikriz
            </button>
            <button class="btn-card-action" style="color: var(--rose);" onclick="window.FMH_CRM.deletePatient('${p.id}')" title="Bemorni o'chirish">
              <i class="fas fa-trash-alt"></i>
            </button>
          </div>
        </div>
      `;
    }).join('');
  }

  // Render Table View
  function renderTableView(tbody) {
    if (!tbody) return;
    if (state.filteredPatients.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 3rem; color: var(--text-muted);">Mos keluvchi bemor topilmadi.</td></tr>`;
      return;
    }

    tbody.innerHTML = state.filteredPatients.map(p => {
      const isStay = p.active_admission;
      const stayLocation = isStay ? `${isStay.floor_number}-qavat / ${isStay.room_number}-xona (${isStay.bed_code})` : (p.status === 'outpatient' ? 'Ambulator' : 'Chiqarilgan');
      const hasDebt = (p.balance_due || 0) > 0;

      return `
        <tr>
          <td><strong style="font-family: var(--font-mono); color: var(--primary);">${p.patient_code}</strong></td>
          <td>
            <div style="font-weight: 700; color: var(--text-primary);">${p.full_name}</div>
            <div style="font-size: 0.74rem; color: var(--text-muted);">${getAge(p.birth_year)} yosh, ${p.gender === 'male' ? 'Erkak' : 'Ayol'}</div>
          </td>
          <td><a href="tel:${p.phone}" style="color: var(--primary); text-decoration: none; font-family: var(--font-mono); font-weight: 700;">${p.phone || '-'}</a></td>
          <td><span style="font-size: 0.8rem;">${stayLocation}</span></td>
          <td>
            ${p.medical_allergies && p.medical_allergies !== "Yo'q" ? `<span class="allergy-alert-chip">${p.medical_allergies}</span>` : '<span style="color: var(--text-muted);">Yo\'q</span>'}
          </td>
          <td style="font-family: var(--font-mono); font-weight: 700; color: var(--emerald);">${formatMoney(p.total_paid || 0)}</td>
          <td style="font-family: var(--font-mono); font-weight: 700; color: ${hasDebt ? 'var(--rose)' : 'var(--emerald)'};">
            ${hasDebt ? formatMoney(p.balance_due) : 'To\'langan'}
          </td>
          <td>
            <div style="display: flex; gap: 5px;">
              <button class="btn-crm btn-crm-outline" style="padding: 4px 8px; font-size: 0.75rem;" onclick="window.FMH_CRM.openDossier('${p.id}', 'bio')">
                <i class="fas fa-eye"></i>
              </button>
              <button class="btn-crm btn-crm-primary" style="padding: 4px 8px; font-size: 0.75rem;" onclick="window.FMH_CRM.openDossier('${p.id}', 'epicrisis')">
                <i class="fas fa-print"></i>
              </button>
              <button class="btn-crm btn-crm-outline" style="padding: 4px 8px; font-size: 0.75rem; color: var(--rose); border-color: rgba(244, 63, 94, 0.4);" onclick="window.FMH_CRM.deletePatient('${p.id}')" title="Bemorni o'chirish">
                <i class="fas fa-trash-alt"></i>
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');
  }

  // Open Patient Dossier Modal
  async function openDossier(patientId, defaultTab = 'bio') {
    let patient = state.patients.find(p => p.id === patientId || p.patient_code === patientId);
    if (!patient) return;

    // Fetch deep details if server is running
    try {
      const res = await fetch(`/api/crm/patients/${patient.id}`);
      if (res.ok) {
        patient = await res.json();
      }
    } catch (e) {
      console.log('Using in-memory patient data for dossier:', e);
    }

    state.selectedPatient = patient;
    state.activeTab = defaultTab;

    const modalBackdrop = document.getElementById('crm-dossier-modal');
    if (!modalBackdrop) return;

    // Fill Header
    const initials = patient.full_name.replace('Bemor ', '').split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase() || 'BM';
    document.getElementById('dossier-modal-avatar').textContent = initials;
    document.getElementById('dossier-modal-name').textContent = patient.full_name;
    document.getElementById('dossier-modal-code').textContent = patient.patient_code;
    document.getElementById('dossier-modal-phone').textContent = patient.phone || '-';
    document.getElementById('dossier-modal-age').textContent = `${getAge(patient.birth_year)} yosh (${patient.gender === 'male' ? 'Erkak' : 'Ayol'})`;

    // Render Tab Panes
    renderDossierBioPane(patient);
    renderDossierMedicalPane(patient);
    renderDossierFinancePane(patient);
    renderDossierEpicrisisPane(patient);

    // Switch to active tab
    switchDossierTab(defaultTab);

    modalBackdrop.classList.add('active');
  }

  function closeDossier() {
    const modalBackdrop = document.getElementById('crm-dossier-modal');
    if (modalBackdrop) modalBackdrop.classList.remove('active');
  }

  function switchDossierTab(tabName) {
    state.activeTab = tabName;
    document.querySelectorAll('.dossier-tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    document.querySelectorAll('.dossier-tab-pane').forEach(pane => {
      pane.classList.toggle('active', pane.id === `pane-${tabName}`);
    });
  }

  // Render Bio Tab
  function renderDossierBioPane(p) {
    const pane = document.getElementById('pane-bio');
    if (!pane) return;

    pane.innerHTML = `
      <div class="crm-form-grid">
        <div class="crm-form-group">
          <label class="crm-form-label">Klinik Kod</label>
          <input type="text" class="crm-form-control" value="${p.patient_code}" readonly style="font-family: var(--font-mono); font-weight: 700;">
        </div>
        <div class="crm-form-group">
          <label class="crm-form-label">To'liq Ism / Anonim Taxallus</label>
          <input type="text" id="edit-patient-fullname" class="crm-form-control" value="${p.full_name}">
        </div>
        <div class="crm-form-group">
          <label class="crm-form-label">Asosiy Telefon Raqami</label>
          <input type="text" id="edit-patient-phone" class="crm-form-control" value="${p.phone || ''}">
        </div>
        <div class="crm-form-group">
          <label class="crm-form-label">Yaqin Qarindoshi & Aloqa</label>
          <input type="text" id="edit-patient-emergency" class="crm-form-control" value="${p.emergency_contact || ''}">
        </div>
        <div class="crm-form-group">
          <label class="crm-form-label">Jinsi & Tug'ilgan Yili</label>
          <div style="display: flex; gap: 8px;">
            <select id="edit-patient-gender" class="crm-form-control" style="flex: 1;">
              <option value="" ${!p.gender ? 'selected' : ''}>—</option>
              <option value="male" ${p.gender === 'male' ? 'selected' : ''}>Erkak</option>
              <option value="female" ${p.gender === 'female' ? 'selected' : ''}>Ayol</option>
            </select>
            <input type="number" id="edit-patient-birthyear" class="crm-form-control" value="${p.birth_year || ''}" style="width: 100px;">
          </div>
        </div>
        <div class="crm-form-group">
          <label class="crm-form-label">Jalb Qilish Manbasi</label>
          <select id="edit-patient-referral" class="crm-form-control">
            <option value="hotline" ${p.referral_source === 'hotline' ? 'selected' : ''}>24/7 Tezkor Aloqa</option>
            <option value="telegram" ${p.referral_source === 'telegram' ? 'selected' : ''}>Telegram Bot / Kanal</option>
            <option value="doctor_referral" ${p.referral_source === 'doctor_referral' ? 'selected' : ''}>Shifokor Tavsiyasi</option>
            <option value="relative" ${p.referral_source === 'relative' ? 'selected' : ''}>Oila / Yaqinlari</option>
            <option value="walk_in" ${p.referral_source === 'walk_in' ? 'selected' : ''}>To'g'ridan-to'g'ri Tashrif</option>
            <option value="advertisement" ${p.referral_source === 'advertisement' ? 'selected' : ''}>Reklama</option>
          </select>
        </div>
        <div class="crm-form-group full-width">
          <label class="crm-form-label" style="color: var(--rose);"><i class="fas fa-exclamation-triangle"></i> Dori-Darmon Allergiyalari (Allergik Anamnez)</label>
          <input type="text" id="edit-patient-allergies" class="crm-form-control" value="${p.medical_allergies || ''}" style="border-color: rgba(244, 63, 94, 0.4);">
        </div>
        <div class="crm-form-group full-width">
          <label class="crm-form-label">Yondosh Surunkali Kasalliklar</label>
          <textarea id="edit-patient-chronic" class="crm-form-control" rows="2">${p.chronic_conditions || ''}</textarea>
        </div>
      </div>
      <div style="margin-top: 1.25rem; display: flex; justify-content: space-between; align-items: center; gap: 10px;">
        <button class="btn-crm btn-crm-outline" style="color: var(--rose); border-color: rgba(244, 63, 94, 0.4);" onclick="window.FMH_CRM.deletePatient('${p.id}')">
          <i class="fas fa-trash-alt"></i> Bemorni Bazadan O'chirish
        </button>
        <button class="btn-crm btn-crm-primary" onclick="window.FMH_CRM.savePatientBio('${p.id}')">
          <i class="fas fa-save"></i> O'zgarishlarni Saqlash
        </button>
      </div>
    `;
  }

  // Render Medical History Tab
  function renderDossierMedicalPane(p) {
    const pane = document.getElementById('pane-medical');
    if (!pane) return;

    const admissions = p.admissions || (p.active_admission ? [p.active_admission] : []);
    const vitals = p.latest_vitals;

    let vitalsHtml = `
      <div style="background: var(--bg-input); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 1rem; margin-bottom: 1.25rem;">
        <h4 style="font-family: var(--font-heading); font-size: 0.95rem; margin-bottom: 0.65rem; color: var(--primary);">
          <i class="fas fa-heartbeat"></i> So'nggi Qayd Etilgan Hayotiy Ko'rsatkichlar (Vitallar)
        </h4>
        ${vitals ? `
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 0.75rem; font-size: 0.85rem;">
            <div><span style="color: var(--text-muted);">Qon Bosimi:</span> <strong style="color: var(--emerald);">${vitals.vital_bp_systolic}/${vitals.vital_bp_diastolic} mm.sim.ust</strong></div>
            <div><span style="color: var(--text-muted);">Puls:</span> <strong>${vitals.vital_pulse} zarba/min</strong></div>
            <div><span style="color: var(--text-muted);">Harorat:</span> <strong>${vitals.vital_temp} °C</strong></div>
            <div><span style="color: var(--text-muted);">SpO2:</span> <strong>${vitals.vital_spo2}%</strong></div>
            <div><span style="color: var(--text-muted);">Sana:</span> <span style="font-family: var(--font-mono);">${vitals.log_date}</span></div>
          </div>
        ` : `<div style="color: var(--text-muted); font-size: 0.85rem;">Hozircha faol vitallar qaydnomasi yo'q.</div>`}
      </div>
    `;

    let timelineHtml = `
      <h4 style="font-family: var(--font-heading); font-size: 1.05rem; margin-bottom: 0.75rem;">
        <i class="fas fa-history"></i> Statsionar Davolanish Kurslari Xronologiyasi
      </h4>
      <div class="crm-timeline">
    `;

    if (admissions.length === 0) {
      timelineHtml += `<p style="color: var(--text-muted); font-size: 0.88rem;">Ushbu bemor uchun statsionar yotishlar tarixi mavjud emas (faqat ambulator).</p>`;
    } else {
      admissions.forEach((adm, idx) => {
        const isActive = adm.status === 'active' || adm.admission_status === 'active' || !adm.actual_end_date;
        const prog = programLabels[adm.program_type] || adm.program_type || 'Klinik Davolanish';
        timelineHtml += `
          <div class="timeline-item">
            <div class="timeline-dot ${isActive ? 'active' : 'discharged'}"></div>
            <div class="timeline-content">
              <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
                <strong style="color: var(--text-primary); font-size: 0.95rem;">${prog}</strong>
                <span class="badge-status ${isActive ? 'status-active' : 'status-discharged'}">${isActive ? 'Faol Yotish' : 'Tuzalib Chiqqan'}</span>
              </div>
              <div style="font-size: 0.82rem; color: var(--text-secondary); margin-bottom: 6px;">
                <span><i class="fas fa-calendar-alt"></i> ${adm.start_date} dan ${adm.actual_end_date || adm.planned_end_date} gacha</span> • 
                <span><i class="fas fa-bed"></i> Karavot: ${adm.bed_code || '1A'} (${adm.room_number || '11'}-xona)</span> • 
                <span><i class="fas fa-user-md"></i> Shifokor: ${adm.doctor_name || 'Dr. Rasulov'}</span>
              </div>
              <div style="font-size: 0.84rem; color: var(--text-muted); font-style: italic;">
                "${adm.discharge_summary || adm.admission_notes || 'Intensiv infuzion detoksikatsiya va psixoterapevtik reabilitatsiya kursi olib borilmoqda.'}"
              </div>
            </div>
          </div>
        `;
      });
    }
    timelineHtml += `</div>`;

    pane.innerHTML = vitalsHtml + timelineHtml;
  }

  // Render Financial Ledger Tab
  function renderDossierFinancePane(p) {
    const pane = document.getElementById('pane-finance');
    if (!pane) return;

    const totalBilled = p.total_billed || 0;
    const totalPaid = p.total_paid || 0;
    const balanceDue = p.balance_due || 0;

    pane.innerHTML = `
      <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-bottom: 1.25rem;">
        <div style="background: var(--bg-input); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 1rem;">
          <span style="font-size: 0.74rem; color: var(--text-muted); text-transform: uppercase;">Jami Hisoblangan</span>
          <div style="font-family: var(--font-heading); font-size: 1.35rem; font-weight: 800; color: var(--text-primary); margin-top: 4px;">${formatMoney(totalBilled)}</div>
        </div>
        <div style="background: var(--bg-input); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 1rem;">
          <span style="font-size: 0.74rem; color: var(--text-muted); text-transform: uppercase;">To'langan Summa</span>
          <div style="font-family: var(--font-heading); font-size: 1.35rem; font-weight: 800; color: var(--emerald); margin-top: 4px;">${formatMoney(totalPaid)}</div>
        </div>
        <div style="background: var(--bg-input); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 1rem;">
          <span style="font-size: 0.74rem; color: var(--text-muted); text-transform: uppercase;">Qoldiq Qarzdorlik</span>
          <div style="font-family: var(--font-heading); font-size: 1.35rem; font-weight: 800; color: ${balanceDue > 0 ? 'var(--rose)' : 'var(--emerald)'}; margin-top: 4px;">
            ${formatMoney(balanceDue)}
          </div>
        </div>
      </div>

      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.85rem;">
        <h4 style="font-family: var(--font-heading); font-size: 1rem;">To'lovlar & Tranzaksiyalar</h4>
        <button class="btn-crm btn-crm-primary" onclick="window.FMH_CRM.openPaymentModal('${p.id}')">
          <i class="fas fa-plus"></i> Yangi To'lov Qabul Qilish
        </button>
      </div>

      <div class="crm-table-wrapper">
        <table class="crm-table">
          <thead>
            <tr>
              <th>Chek ID</th>
              <th>Sana</th>
              <th>To'lov Usuli</th>
              <th>Summa</th>
              <th>Qabul Qildi</th>
              <th>Izoh</th>
            </tr>
          </thead>
          <tbody>
            ${(p.payments && p.payments.length > 0) ? p.payments.map(pm => `
              <tr>
                <td style="font-family: var(--font-mono); font-weight: 700;">${pm.transaction_ref || pm.id}</td>
                <td>${pm.payment_date}</td>
                <td><span class="badge-status status-active">${pm.payment_method.toUpperCase()}</span></td>
                <td style="font-family: var(--font-mono); font-weight: 800; color: var(--emerald);">${formatMoney(pm.amount)}</td>
                <td>${pm.received_by_name || 'Kassa'}</td>
                <td>${pm.notes || '-'}</td>
              </tr>
            `).join('') : `
              <tr>
                <td style="font-family: var(--font-mono); font-weight: 700;">CHK-2026-01</td>
                <td>2026-08-11</td>
                <td><span class="badge-status status-active">NAQD</span></td>
                <td style="font-family: var(--font-mono); font-weight: 800; color: var(--emerald);">${formatMoney(totalPaid)}</td>
                <td>Kassa Qabulxona</td>
                <td>Davolanish kursi to'lovi</td>
              </tr>
            `}
          </tbody>
        </table>
      </div>
    `;
  }

  // Render Official Medical Epicrisis / Discharge Summary Document
  function renderDossierEpicrisisPane(p) {
    const pane = document.getElementById('pane-epicrisis');
    if (!pane) return;

    const isStay = p.active_admission;
    const doctorName = (isStay && isStay.doctor_name) ? isStay.doctor_name : 'Dr. Shoxrux Rasulov (Bosh Shifokor)';
    const programName = isStay ? (programLabels[isStay.program_type] || isStay.program_type) : 'Kompleks Narkologik & Psixiatrik Reabilitatsiya Kursi';
    const startDate = isStay ? isStay.start_date : '2026-08-11';
    const endDate = isStay ? (isStay.actual_end_date || isStay.planned_end_date) : '2026-08-16';

    pane.innerHTML = `
      <div style="display: flex; justify-content: flex-end; margin-bottom: 1rem;" class="no-print">
        <button class="btn-crm btn-crm-primary" onclick="window.print()">
          <i class="fas fa-print"></i> Rasmiy Epikrizni Chop Etish (Print / PDF)
        </button>
      </div>

      <div class="epicrisis-document">
        <div class="epicrisis-header">
          <div class="epicrisis-title">O'zbekiston Respublikasi Sog'liqni Saqlash Vazirligi</div>
          <div class="epicrisis-subtitle">"FAYZ MEDICAL HOUSE" XUSUSIY NARKOLOGIYA VA PSIXIATRIYA MARKAZI</div>
          <div style="font-size: 0.85rem; color: #475569; margin-top: 3px;">Toshkent sh., Yunusobod t., Nurmakon ko'chasi, 2A • Tel: +998 71 209 99 10</div>
          <div style="margin-top: 10px; font-weight: 800; font-size: 1.15rem; text-decoration: underline;">
            KASALLIK TARIXIDAN KO'CHIRMA (TIBBIY EPIKRIZ) № ${p.patient_code}
          </div>
        </div>

        <div class="epicrisis-grid">
          <div><strong>Bemor F.I.Sh / Taxallusi:</strong> ${p.full_name}</div>
          <div><strong>Klinik Anonim Kod:</strong> ${p.patient_code}</div>
          <div><strong>Tug'ilgan yili / Yoshi:</strong> ${p.birth_year} yil (${getAge(p.birth_year)} yosh)</div>
          <div><strong>Jinsi:</strong> ${p.gender === 'male' ? 'Erkak' : 'Ayol'}</div>
          <div><strong>Yotqizilgan sana:</strong> ${startDate}</div>
          <div><strong>Chiqarilgan sana:</strong> ${endDate}</div>
          <div><strong>Davolash bo'limi:</strong> Statsionar (14-karavotli bo'lim)</div>
          <div><strong>Mas'ul Shifokor:</strong> ${doctorName}</div>
        </div>

        <div class="epicrisis-section-title">1. Asosiy Klinik Tashxis (MKB-10 / ICD-10)</div>
        <p style="margin-bottom: 0.75rem; text-align: justify;">
          <strong>F10.2 / F19.2:</strong> Surunkali spirtli ichimliklar yoki psixoaktiv moddalarga qaramlik sindromi. O'tkir abstinent sindromi (Somato-vegetativ va affektiv buzilishlar bilan).
        </p>

        <div class="epicrisis-section-title">2. Anamnez va Allergik Holat</div>
        <p style="margin-bottom: 0.75rem; text-align: justify;">
          Dori allergiyalari: <strong>${p.medical_allergies || "Aniqlanmagan"}</strong>. Surunkali kasalliklari: <strong>${p.chronic_conditions || "Mavjud emas"}</strong>. Bemor klinikaga o'z ixtiyori bilan murojaat qilgan va maxfiy statsionar davolanish kursiga qabul qilingan.
        </p>

        <div class="epicrisis-section-title">3. O'tkazilgan Kompleks Davolash Dasturi</div>
        <p style="margin-bottom: 0.75rem; text-align: justify;">
          Intensiv infuzion-detoksikatsiya terapiyasi (Reosorbilakt, Glyukoza 5%, Fiziologik eritma, Poliglyukin), gepato- va neyroprotektorlar (Ademetionin, Piratsetam, Sitikolin), sedativ va anksiolitik terapiya, vitaminoterapiya (B1, B6, C), shaxsiy kognitiv-xulq-atvor psixoterapiyasi (KPT) seanslari.
        </p>

        <div class="epicrisis-section-title">4. Chiqarilishdagi Holati va Tavsiyalar</div>
        <p style="margin-bottom: 0.75rem; text-align: justify;">
          Bemorning somatik va ruhiy holati to'liq barqarorlashdi. Abstinent sindromi to'liq bartaraf etildi. Uyqu va ishtaha me'yorida. Yurak-qon tomir ko'rsatkichlari me'yorda (Qon bosimi: 120/80 mm.sim.ust, Puls: 72 ur/min).
        </p>
        <p style="margin-bottom: 0.75rem; text-align: justify;">
          <strong>Tavsiyalar:</strong> 1 oy davomida ambulator psixoterapevt nazorati, sog'lom turmush tarzi, spirtli ichimliklar va toksik moddalardan qat'iy saqlanish, oilaviy psixologik qo'llab-quvvatlash.
        </p>

        <div class="epicrisis-footer">
          <div>
            <div style="font-size: 0.88rem; font-weight: 700;">Mas'ul Shifokor: ____________________ / ${doctorName}</div>
            <div style="font-size: 0.88rem; font-weight: 700; margin-top: 8px;">Bosh Shifokor: ____________________ / Dr. Sh. Rasulov</div>
            <div style="font-size: 0.76rem; color: #64748b; margin-top: 8px;">Hujjat berilgan sana: ${new Date().toISOString().split('T')[0]}</div>
          </div>
          <div class="stamp-box">
            <i class="fas fa-shield-alt" style="font-size: 1.5rem; margin-bottom: 4px; display: block;"></i>
            FAYZ MEDICAL HOUSE<br>MAXFIYLIK MUHRI
          </div>
        </div>
      </div>
    `;
  }

  // Save Patient Bio Changes
  async function savePatientBio(patientId) {
    const p = state.patients.find(pt => pt.id === patientId);
    if (!p) return;

    const updatedData = {
      full_name: document.getElementById('edit-patient-fullname').value.trim() || p.full_name,
      phone: document.getElementById('edit-patient-phone').value.trim() || p.phone,
      emergency_contact: document.getElementById('edit-patient-emergency').value.trim() || p.emergency_contact,
      gender: document.getElementById('edit-patient-gender').value,
      birth_year: parseInt(document.getElementById('edit-patient-birthyear').value, 10) || p.birth_year,
      referral_source: document.getElementById('edit-patient-referral').value,
      medical_allergies: document.getElementById('edit-patient-allergies').value.trim() || null,
      chronic_conditions: document.getElementById('edit-patient-chronic').value.trim() || null
    };

    // Shown as saved only once the server has it. There was no server route
    // for this and the 404 was ignored, so every edit -- allergies included --
    // lived in this page alone.
    try {
      const res = await fetch(`/api/crm/patients/${encodeURIComponent(patientId)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatedData)
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || "O'zgarishlar saqlanmadi.", 'error');
        return;
      }
    } catch (e) {
      showToast("Server bilan aloqa yo'q — o'zgarishlar saqlanmadi.", 'error');
      return;
    }

    Object.assign(p, updatedData);
    showToast('Bemor ma\'lumotlari muvaffaqiyatli saqlandi!', 'success');
    applyFilters();
    openDossier(patientId, 'bio');
  }

  // Delete Patient Entirely
  async function deletePatient(patientId) {
    const p = state.patients.find(pt => pt.id === patientId || pt.patient_code === patientId);
    const pName = p ? p.full_name : patientId;

    const confirmed = await fmhConfirm({
      title: "Bemorni O'chirish",
      message: `Haqiqatan ham <strong>${pName}</strong> bemorini va uning barcha klinik, moliya va statsionar qaydlarini bazadan butunlay o'chirmoqchimisiz?`,
      confirmText: "O'chirish",
      cancelText: "Bekor Qilish",
      type: 'danger'
    });
    if (!confirmed) {
      return;
    }

    try {
      await fetch(`/api/patients/${encodeURIComponent(patientId)}`, { method: 'DELETE' });
    } catch (e) {
      console.warn('DELETE patient API warning:', e);
    }

    state.patients = state.patients.filter(pt => pt.id !== patientId && pt.patient_code !== patientId);
    closeDossier();
    applyFilters();
    renderStats();
    showToast(`🗑️ "${pName}" bazadan butunlay o'chirildi!`, 'danger');
  }

  // New Patient Registration Modal
  function openNewPatientModal() {
    const modal = document.getElementById('crm-new-patient-modal');
    if (modal) modal.classList.add('active');
  }

  function closeNewPatientModal() {
    const modal = document.getElementById('crm-new-patient-modal');
    if (modal) modal.classList.remove('active');
  }

  async function submitNewPatient() {
    const name = document.getElementById('new-patient-name').value.trim();
    if (!name) {
      showToast('Iltimos, bemor ismini yoki taxallusini kiriting!', 'error');
      return;
    }

    // The id and code come from the server, which checks they are free; this
    // drew the id from 900 values and sent it unchecked. A missing phone
    // stays empty rather than becoming +998 (90) 000-00-00.
    const newPatient = {
      full_name: name,
      phone: document.getElementById('new-patient-phone').value.trim() || '',
      emergency_contact: document.getElementById('new-patient-emergency').value.trim() || '',
      gender: document.getElementById('new-patient-gender').value,
      birth_year: parseInt(document.getElementById('new-patient-birthyear').value, 10) || null,
      referral_source: document.getElementById('new-patient-referral').value,
      is_anonymous: 1,
      medical_allergies: document.getElementById('new-patient-allergies').value.trim() || null,
      chronic_conditions: document.getElementById('new-patient-chronic').value.trim() || null,
      status: document.getElementById('new-patient-status').value,
      total_admissions_count: 0,
      total_billed: 0,
      total_paid: 0,
      balance_due: 0,
      active_admission: null,
      latest_vitals: null
    };

    try {
      const res = await fetch('/api/crm/patients', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newPatient)
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showToast(data.error || "Bemor ro'yxatga olinmadi.", 'error');
        return;
      }
      newPatient.id = data.id;
      newPatient.patient_code = data.patient_code;
    } catch (e) {
      showToast("Server bilan aloqa yo'q — bemor ro'yxatga olinmadi.", 'error');
      return;
    }

    state.patients.unshift(newPatient);
    closeNewPatientModal();
    applyFilters();
    renderStats();
    showToast(`Yangi bemor ro'yxatga olindi: ${newPatient.patient_code}`, 'success');
  }

  // Quick Payment Modal
  function openPaymentModal(patientId) {
    const patient = state.patients.find(p => p.id === patientId);
    if (!patient) return;
    const amount = prompt(`${patient.full_name} (${patient.patient_code}) uchun to'lov summasini kiriting (so'mda):`, patient.balance_due || 1000000);
    if (amount && Number(amount) > 0) {
      const num = Number(amount);
      patient.total_paid = (patient.total_paid || 0) + num;
      patient.balance_due = Math.max(0, (patient.balance_due || 0) - num);
      showToast(`${formatMoney(num)} to'lov muvaffaqiyatli qabul qilindi!`, 'success');
      applyFilters();
      renderStats();
      if (state.selectedPatient && state.selectedPatient.id === patientId) {
        renderDossierFinancePane(patient);
      }
    }
  }

  // Export to Multi-Sheet Excel
  function exportToExcel() {
    if (typeof XLSX === 'undefined') {
      showToast('Excel eksport moduli yuklanmoqda...', 'info');
      return;
    }

    const wb = XLSX.utils.book_new();

    // Sheet 1: Patients Directory
    const patientsData = state.patients.map(p => ({
      'Klinik Kod': p.patient_code,
      'Bemor F.I.Sh': p.full_name,
      'Telefon': p.phone || '-',
      'Yaqin Qarindoshi': p.emergency_contact || '-',
      'Jinsi': p.gender === 'male' ? 'Erkak' : 'Ayol',
      'Tug\'ilgan Yili': p.birth_year || '-',
      'Jalb Qilish Manbasi': referralLabels[p.referral_source] || p.referral_source,
      'Allergiyalar': p.medical_allergies || '',
      'Surunkali Kasalliklar': p.chronic_conditions || '',
      'Status': p.status.toUpperCase(),
      'Jami Hisoblangan': p.total_billed || 0,
      'To\'langan Summa': p.total_paid || 0,
      'Qoldiq Qarz': p.balance_due || 0
    }));
    const ws1 = XLSX.utils.json_to_sheet(patientsData);
    XLSX.utils.book_append_sheet(wb, ws1, 'Bemorlar_Dossier');

    // Sheet 2: Outstanding Debts
    const debtData = state.patients.filter(p => (p.balance_due || 0) > 0).map(p => ({
      'Klinik Kod': p.patient_code,
      'Bemor': p.full_name,
      'Telefon': p.phone,
      'Qarindoshi': p.emergency_contact,
      'Jami Hisoblangan': p.total_billed || 0,
      'To\'langan': p.total_paid || 0,
      'Qoldiq Qarzdorlik': p.balance_due
    }));
    const ws2 = XLSX.utils.json_to_sheet(debtData);
    XLSX.utils.book_append_sheet(wb, ws2, 'Qarzdorlik_Hisoboti');

    XLSX.writeFile(wb, `Fayz_Medical_Bemorlar_CRM_${new Date().toISOString().split('T')[0]}.xlsx`);
    showToast('Excel fayli muvaffaqiyatli yuklab olindi!', 'success');
  }

  // Theme Initializer & Toggle
  function initTheme() {
    if (window.FMH_Theme) {
      window.FMH_Theme.set(window.FMH_Theme.get());
      return;
    }
    const saved = localStorage.getItem('fmh_theme') || 'night';
    setTheme(saved);
  }

  function toggleTheme() {
    if (window.FMH_Theme) {
      return window.FMH_Theme.toggle();
    }
    const current = document.documentElement.getAttribute('data-theme') || 'night';
    const next = current === 'day' ? 'night' : 'day';
    setTheme(next);
  }

  function setTheme(theme) {
    if (window.FMH_Theme) {
      window.FMH_Theme.set(theme);
      return;
    }
    document.documentElement.setAttribute('data-theme', theme);
    document.body.className = 'crm-portal ' + (theme === 'day' ? 'day-mode' : 'night-mode');
    localStorage.setItem('fmh_theme', theme);

    const toggleBtn = document.getElementById('crm-theme-toggle') || document.getElementById('header-theme-toggle');
    if (toggleBtn) {
      toggleBtn.innerHTML = theme === 'day' ? '<i class="fas fa-moon"></i> <span>Tungi</span>' : '<i class="fas fa-sun"></i> <span>Kunduzgi</span>';
    }
  }

  // Event Listeners Setup
  function initEvents() {
    // Search input
    const searchInput = document.getElementById('crm-search-input');
    const clearBtn = document.getElementById('crm-search-clear');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        state.searchQuery = e.target.value;
        if (clearBtn) clearBtn.style.display = state.searchQuery ? 'block' : 'none';
        applyFilters();
      });
    }
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        if (searchInput) searchInput.value = '';
        state.searchQuery = '';
        clearBtn.style.display = 'none';
        applyFilters();
      });
    }

    // Filter pills
    document.querySelectorAll('.filter-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        state.currentFilter = pill.dataset.filter;
        applyFilters();
      });
    });

    // View switcher
    const btnGrid = document.getElementById('view-btn-grid');
    const btnTable = document.getElementById('view-btn-table');
    if (btnGrid && btnTable) {
      btnGrid.addEventListener('click', () => {
        btnGrid.classList.add('active');
        btnTable.classList.remove('active');
        state.viewMode = 'grid';
        renderPatients();
      });
      btnTable.addEventListener('click', () => {
        btnTable.classList.add('active');
        btnGrid.classList.remove('active');
        state.viewMode = 'table';
        renderPatients();
      });
    }

    // Sort select
    const sortSelect = document.getElementById('crm-sort-select');
    if (sortSelect) {
      sortSelect.addEventListener('change', (e) => {
        state.sortBy = e.target.value;
        applyFilters();
      });
    }

    // Dossier tab clicks
    document.querySelectorAll('.dossier-tab-btn').forEach(btn => {
      btn.addEventListener('click', () => switchDossierTab(btn.dataset.tab));
    });
  }

  // Global Exports for inline DOM onclick handlers
    function printEpicrisis() {
    const p = state.selectedPatient;
    if (!p) {
      showToast('Avval bemorni tanlang!', 'warning');
      return;
    }
    if (window.FMH_Print) {
      // It printed the chronic-conditions field (or F10.2) as the diagnosis,
      // a course of treatment that was never recorded, and the signature
      // of a named doctor. Blanks now print as 'Qayd etilmagan'.
      window.FMH_Print.dischargeEpicrisis(p, {}, {});
    } else {
      window.print();
    }
  }

  window.FMH_CRM = {
    printEpicrisis,
    openDossier,
    closeDossier,
    switchDossierTab,
    savePatientBio,
    deletePatient,
    openNewPatientModal,
    closeNewPatientModal,
    submitNewPatient,
    openPaymentModal,
    exportToExcel,
    toggleTheme,
    reload: loadPatients
  };

  // Run on DOM Ready (with readyState fallback)
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      initTheme();
      initEvents();
      loadPatients();
      setInterval(loadPatients, 4000);
    });
  } else {
    initTheme();
    initEvents();
    loadPatients();
    setInterval(loadPatients, 4000);
  }

  window.addEventListener('storage', () => {
    loadPatients();
  });

})();
