/**
 * Fayz Medical House — Patient Dossier Portal JavaScript
 * Manages 4-Page and 2-Page Official PDF Dossiers, Patient History, and Medications
 */

(function () {
  'use strict';

  // Global State
  const state = {
    patients: [],
    selectedPatientId: null,
    currentData: null,
    activeFilter: 'all',
    searchTerm: '',
    isLoading: false
  };

  // DOM Elements Cache
  const el = {};

  document.addEventListener('DOMContentLoaded', init);

  function init() {
    cacheElements();
    bindEvents();
    checkUrlParams();
    fetchPatients();
  }

  function cacheElements() {
    el.patientSearchInput = document.getElementById('patient-search-input');
    el.patientsScrollContainer = document.getElementById('patients-scroll-container');
    el.patientCountBadge = document.getElementById('patient-count-badge');
    el.filterPills = document.querySelectorAll('.filter-pill');

    // Hero elements
    el.heroPatientName = document.getElementById('hero-patient-name');
    el.heroPatientId = document.getElementById('hero-patient-id');
    el.heroPatientAgeGender = document.getElementById('hero-patient-age-gender');
    el.heroPatientPhone = document.getElementById('hero-patient-phone');
    el.heroPatientBed = document.getElementById('hero-patient-bed');
    el.heroDiagnosis = document.getElementById('hero-diagnosis');
    el.heroDoctor = document.getElementById('hero-doctor');
    el.heroAdmissionDate = document.getElementById('hero-admission-date');
    el.heroAllergies = document.getElementById('hero-allergies');

    // Hero buttons
    el.btnGenerate4page = document.getElementById('btn-generate-4page');
    el.btnGenerate2page = document.getElementById('btn-generate-2page');
    el.btnCustomDossierModal = document.getElementById('btn-custom-dossier-modal');

    // Tabs
    el.tabBtns = document.querySelectorAll('.tab-btn');
    el.tabPanes = document.querySelectorAll('.tab-pane');
    el.tabArchiveBadge = document.getElementById('tab-archive-badge');
    el.tabMedBadge = document.getElementById('tab-med-badge');

    // Archive container
    el.dossiersGridContainer = document.getElementById('dossiers-grid-container');
    el.btnRefreshDossiers = document.getElementById('btn-refresh-dossiers');

    // Tab 2 Inputs
    el.inputClinicalDiagnosis = document.getElementById('input-clinical-diagnosis');
    el.inputComplaints = document.getElementById('input-complaints');
    el.inputPastHistory = document.getElementById('input-past-history');
    el.inputSomaticStatus = document.getElementById('input-somatic-status');
    el.inputMentalStatus = document.getElementById('input-mental-status');
    el.btnSaveAnamnesis = document.getElementById('btn-save-anamnesis');

    // Tab 3 Tables
    el.prescriptionsTableBody = document.getElementById('prescriptions-table-body');
    el.administrationsTableBody = document.getElementById('administrations-table-body');

    // Tab 4 Table
    el.vitalsTableBody = document.getElementById('vitals-table-body');

    // Tab 5 Displays
    el.epicrisisResultDisplay = document.getElementById('epicrisis-result-display');
    el.epicrisisTextDisplay = document.getElementById('epicrisis-text-display');
    el.epicrisisRecsDisplay = document.getElementById('epicrisis-recs-display');

    // PDF Viewer Modal
    el.pdfViewerModal = document.getElementById('pdf-viewer-modal');
    el.pdfModalFilename = document.getElementById('pdf-modal-filename');
    el.pdfModalIframe = document.getElementById('pdf-modal-iframe');
    el.btnPdfModalDownload = document.getElementById('btn-pdf-modal-download');
    el.btnPdfModalPrint = document.getElementById('btn-pdf-modal-print');
    el.btnClosePdfModal = document.getElementById('btn-close-pdf-modal');

    // Custom Modal
    el.customGenModal = document.getElementById('custom-gen-modal');
    el.selectModalDocType = document.getElementById('select-modal-doc-type');
    el.inputModalCustomNotes = document.getElementById('input-modal-custom-notes');
    el.btnSubmitCustomGenerate = document.getElementById('btn-submit-custom-generate');
    el.btnCancelCustomModal = document.getElementById('btn-cancel-custom-modal');
    el.btnCloseCustomModal = document.getElementById('btn-close-custom-modal');
    el.modalSpinner = document.getElementById('modal-spinner');
  }

  function bindEvents() {
    // Search
    if (el.patientSearchInput) {
      el.patientSearchInput.addEventListener('input', function (e) {
        state.searchTerm = e.target.value.trim().toLowerCase();
        renderPatientsList();
      });
    }

    // Filter pills
    if (el.filterPills) {
      el.filterPills.forEach(pill => {
        pill.addEventListener('click', function () {
          el.filterPills.forEach(p => p.classList.remove('active'));
          this.classList.add('active');
          state.activeFilter = this.getAttribute('data-filter') || 'all';
          renderPatientsList();
        });
      });
    }

    // Tab navigation
    if (el.tabBtns) {
      el.tabBtns.forEach(btn => {
        btn.addEventListener('click', function () {
          const targetTab = this.getAttribute('data-tab');
          switchTab(targetTab);
        });
      });
    }

    // Generation buttons
    if (el.btnGenerate4page) {
      el.btnGenerate4page.addEventListener('click', () => generateDossier('4_page'));
    }
    if (el.btnGenerate2page) {
      el.btnGenerate2page.addEventListener('click', () => generateDossier('2_page'));
    }
    if (el.btnCustomDossierModal) {
      el.btnCustomDossierModal.addEventListener('click', () => openCustomModal());
    }

    // Save Anamnesis
    if (el.btnSaveAnamnesis) {
      el.btnSaveAnamnesis.addEventListener('click', saveClinicalData);
    }

    // Refresh Archive
    if (el.btnRefreshDossiers) {
      el.btnRefreshDossiers.addEventListener('click', () => {
        if (state.selectedPatientId) selectPatient(state.selectedPatientId);
      });
    }

    // Custom Modal triggers
    if (el.btnCloseCustomModal) {
      el.btnCloseCustomModal.addEventListener('click', closeCustomModal);
    }
    if (el.btnCancelCustomModal) {
      el.btnCancelCustomModal.addEventListener('click', closeCustomModal);
    }
    if (el.btnSubmitCustomGenerate) {
      el.btnSubmitCustomGenerate.addEventListener('click', submitCustomGenerate);
    }

    // PDF Viewer Modal triggers
    if (el.btnClosePdfModal) {
      el.btnClosePdfModal.addEventListener('click', closePdfViewerModal);
    }
    if (el.btnPdfModalPrint) {
      el.btnPdfModalPrint.addEventListener('click', () => {
        if (el.pdfModalIframe && el.pdfModalIframe.contentWindow) {
          try {
            el.pdfModalIframe.contentWindow.focus();
            el.pdfModalIframe.contentWindow.print();
          } catch (e) {
            window.open(el.pdfModalIframe.src, '_blank');
          }
        }
      });
    }

    // Close modals on escape
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closePdfViewerModal();
        closeCustomModal();
      }
    });
  }

  function switchTab(tabId) {
    if (!tabId) return;
    el.tabBtns.forEach(btn => {
      if (btn.getAttribute('data-tab') === tabId) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    el.tabPanes.forEach(pane => {
      if (pane.id === tabId) {
        pane.classList.add('active');
      } else {
        pane.classList.remove('active');
      }
    });
  }

  function checkUrlParams() {
    const params = new URLSearchParams(window.location.search);
    const pid = params.get('patient_id') || params.get('pid');
    if (pid) {
      state.selectedPatientId = pid;
    }
  }

  // --------------------------------------------------------------------------
  // Data Fetching
  // --------------------------------------------------------------------------
  async function fetchPatients() {
    try {
      const res = await fetch('/api/dossiers/patients');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      state.patients = data.patients || [];
      renderPatientsList();

      if (state.patients.length > 0) {
        if (state.selectedPatientId) {
          selectPatient(state.selectedPatientId);
        } else {
          selectPatient(state.patients[0].id);
        }
      } else {
        renderEmptyState();
      }
    } catch (err) {
      console.error('Bemorlar ro\'yxatini olishda xatolik:', err);
      el.patientsScrollContainer.innerHTML = `
        <div style="text-align: center; padding: 30px; color: var(--dossier-danger);">
          <i class="fas fa-exclamation-triangle" style="font-size: 24px;"></i>
          <p style="margin-top: 10px; font-size: 13px;">Bemorlar ro'yxatini yuklab bo'lmadi.</p>
        </div>`;
    }
  }

  function renderPatientsList() {
    const filtered = state.patients.filter(p => {
      // Filter tab
      if (state.activeFilter === 'inpatient' && !p.admission_id) return false;
      if (state.activeFilter === 'has_dossier' && (!p.dossiers_count || p.dossiers_count === 0)) return false;

      // Search term
      if (state.searchTerm) {
        const text = `${p.full_name || ''} ${p.patient_code || ''} ${p.phone || ''} ${p.diagnosis || ''}`.toLowerCase();
        if (!text.includes(state.searchTerm)) return false;
      }
      return true;
    });

    if (el.patientCountBadge) {
      el.patientCountBadge.textContent = `${filtered.length} ta bemor`;
    }

    if (!filtered.length) {
      el.patientsScrollContainer.innerHTML = `
        <div style="text-align: center; padding: 40px 15px; color: var(--dossier-text-light);">
          <i class="fas fa-user-slash" style="font-size: 28px; margin-bottom: 8px;"></i>
          <p style="font-size: 13px;">Bemorlar topilmadi</p>
        </div>`;
      return;
    }

    let html = '';
    filtered.forEach(p => {
      const isSelected = p.id === state.selectedPatientId;
      const bedText = p.bed_number ? `Xona ${p.room_number || '-'}, Karavot ${p.bed_number}` : (p.admission_id ? 'Statsionar' : 'Ambulator');
      const dossierCount = p.dossiers_count || 0;
      const badgeClass = dossierCount > 0 ? '' : 'zero';

      html += `
        <div class="patient-card ${isSelected ? 'active' : ''}" data-id="${p.id}">
          <div class="patient-card-top">
            <span class="patient-card-name">${escapeHtml(p.full_name || 'Noma\'lum bemor')}</span>
            <span class="patient-card-id">${escapeHtml(p.patient_code || 'PAT')}</span>
          </div>
          <div class="patient-card-details">
            <span><i class="fas fa-bed"></i> ${escapeHtml(bedText)}</span>
            <span>•</span>
            <span>${p.gender === 'female' ? 'Ayol' : 'Erkak'}</span>
          </div>
          <div class="patient-card-footer">
            <span class="dossier-count-badge ${badgeClass}">
              <i class="fas fa-file-pdf"></i> ${dossierCount} ta PDF
            </span>
            <span style="max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              ${escapeHtml(p.diagnosis || 'Tashxis qayd etilmagan')}
            </span>
          </div>
        </div>
      `;
    });

    el.patientsScrollContainer.innerHTML = html;

    // Attach click handlers
    const cards = el.patientsScrollContainer.querySelectorAll('.patient-card');
    cards.forEach(card => {
      card.addEventListener('click', function () {
        const pid = this.getAttribute('data-id');
        selectPatient(pid);
      });
    });
  }

  async function selectPatient(patientId) {
    if (!patientId) return;
    state.selectedPatientId = patientId;

    // Highlight card
    const cards = el.patientsScrollContainer.querySelectorAll('.patient-card');
    cards.forEach(card => {
      if (card.getAttribute('data-id') === patientId) {
        card.classList.add('active');
      } else {
        card.classList.remove('active');
      }
    });

    try {
      const res = await fetch(`/api/dossiers/patient/${encodeURIComponent(patientId)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      state.currentData = data;
      renderPatientDetails(data);
    } catch (err) {
      console.error('Bemor ma\'lumotlarini olishda xatolik:', err);
      showToast('Bemor ma\'lumotlarini yuklashda xatolik yuz berdi.', 'error');
    }
  }

  function renderPatientDetails(data) {
    const p = data.patient || {};
    const adm = data.admission || {};
    const mh = data.anamnesis || {};
    const vitals = data.vitals || [];
    const rx = data.prescriptions || [];
    const adminLogs = data.administrations || [];
    const epicrisis = data.epicrisis || {};
    const dossiers = data.dossiers || [];

    // Hero details
    el.heroPatientName.textContent = p.full_name || 'Noma\'lum';
    el.heroPatientId.innerHTML = `<i class="fas fa-id-badge"></i> ${escapeHtml(p.patient_code || p.id || '-')}`;
    
    // Age and gender
    let ageStr = '';
    if (p.birth_date) {
      const bYear = new Date(p.birth_date).getFullYear();
      const age = new Date().getFullYear() - bYear;
      ageStr = `${age} yosh`;
    } else if (p.birth_year) {
      const age = new Date().getFullYear() - parseInt(p.birth_year, 10);
      ageStr = `${age} yosh`;
    }
    const genderStr = p.gender === 'female' ? 'Ayol' : (p.gender === 'male' ? 'Erkak' : '-');
    el.heroPatientAgeGender.innerHTML = `<i class="fas fa-venus-mars"></i> ${genderStr}${ageStr ? ' • ' + ageStr : ''}`;
    
    el.heroPatientPhone.innerHTML = `<i class="fas fa-phone"></i> ${escapeHtml(p.phone || 'Telefon yo\'q')}`;
    
    const bedStr = adm.bed_number ? `Xona ${adm.room_number || '-'}, Karavot ${adm.bed_number}` : 'Ambulator qabul';
    el.heroPatientBed.innerHTML = `<i class="fas fa-bed"></i> ${escapeHtml(bedStr)}`;

    el.heroDiagnosis.textContent = adm.diagnosis || mh.clinical_diagnosis || p.chronic_conditions || 'Qayd etilmagan';
    el.heroDoctor.textContent = adm.doctor_name || 'Qayd etilmagan';
    el.heroAdmissionDate.textContent = adm.admission_date ? formatDate(adm.admission_date) : 'Yotqizilmagan';
    
    const allergyText = p.medical_allergies || 'Mavjud emas';
    el.heroAllergies.textContent = allergyText;
    if (allergyText !== 'Mavjud emas' && allergyText !== 'Yo\'q') {
      el.heroAllergies.style.color = 'var(--dossier-danger)';
    } else {
      el.heroAllergies.style.color = 'var(--dossier-text-main)';
    }

    // Badges
    el.tabArchiveBadge.textContent = dossiers.length;
    el.tabMedBadge.textContent = rx.length;

    // Update patient list dossier count badge in state
    const targetP = state.patients.find(x => x.id === p.id);
    if (targetP) {
      targetP.dossiers_count = dossiers.length;
      targetP.diagnosis = adm.diagnosis || targetP.diagnosis;
      renderPatientsList();
    }

    // 1. Render Dossiers Archive
    renderDossiersArchive(dossiers);

    // 2. Render Anamnesis
    el.inputClinicalDiagnosis.value = adm.diagnosis || mh.clinical_diagnosis || '';
    el.inputComplaints.value = mh.complaints || '';
    el.inputPastHistory.value = mh.past_medical_history || '';
    el.inputSomaticStatus.value = mh.somatic_status || '';
    el.inputMentalStatus.value = mh.psychiatric_status || '';

    // 3. Render Prescriptions & Administrations
    renderPrescriptions(rx);
    renderAdministrations(adminLogs);

    // 4. Render Vitals
    renderVitals(vitals);

    // 5. Render Epicrisis
    renderEpicrisis(epicrisis);
  }

  function renderDossiersArchive(dossiers) {
    if (!dossiers || !dossiers.length) {
      el.dossiersGridContainer.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1;">
          <i class="fas fa-folder-open"></i>
          <h3>Ushbu bemor uchun saqlangan PDF dossye yo'q</h3>
          <p>Yuqoridagi <strong>"4 Sahifali Dossye (PDF)"</strong> yoki <strong>"2 Sahifali Dossye (PDF)"</strong> tugmasini bosib rasmiy kasallik tarixini shakllantiring.</p>
          <button type="button" class="btn-dossier-primary" onclick="document.getElementById('btn-generate-4page').click()">
            <i class="fas fa-file-pdf"></i> <span>4 Sahifali Dossye Shakllantirish</span>
          </button>
        </div>`;
      return;
    }

    let html = '';
    dossiers.forEach(doc => {
      const is4Page = doc.doc_type === '4_page';
      const typeLabel = is4Page ? '4 Sahifali To\'liq Dossye' : '2 Sahifali Qisqa Dossye';
      const typeClass = is4Page ? 'four-page' : 'two-page';
      const sizeKb = doc.file_size ? Math.round(doc.file_size / 1024) : 0;
      const formattedDate = formatDateTime(doc.created_at);

      html += `
        <div class="dossier-item-card" data-dossier-id="${doc.id}">
          <div class="dossier-card-head">
            <span class="dossier-card-type ${typeClass}">
              <i class="fas ${is4Page ? 'fa-file-lines' : 'fa-file-medical'}"></i> ${typeLabel}
            </span>
            <span class="dossier-card-date">${formattedDate}</span>
          </div>
          <div class="dossier-card-file" title="${escapeHtml(doc.file_name || '')}">
            ${escapeHtml(doc.file_name || 'Dossier.pdf')}
          </div>
          <div class="dossier-card-meta">
            <div><i class="fas fa-file"></i> Sahifalar: <strong>${doc.page_count || (is4Page ? 4 : 2)} bet</strong> • Hajmi: ${sizeKb} KB</div>
            <div><i class="fas fa-user-edit"></i> Shakllantirdi: <strong>${escapeHtml(doc.created_by || 'shifokor')}</strong></div>
            <div><i class="fas fa-pills"></i> Dori-darmonlar soni: <strong>${doc.medications_count || 0} ta</strong></div>
            ${doc.notes ? `<div style="font-style: italic; color: var(--dossier-text-light); margin-top: 4px;">«${escapeHtml(doc.notes)}»</div>` : ''}
          </div>
          <div class="dossier-card-actions">
            <button type="button" class="btn-card-action btn-preview-dossier" data-id="${doc.id}" data-file="${escapeHtml(doc.file_name || '')}" title="PDFni brauzerda ko'rish">
              <i class="fas fa-eye"></i> Ko'rish
            </button>
            <a href="/api/dossiers/file/${encodeURIComponent(doc.id)}?download=1" class="btn-card-action" download title="PDFni kompyuterga yuklab olish">
              <i class="fas fa-download"></i> Yuklash
            </a>
            <button type="button" class="btn-card-action danger btn-delete-dossier" data-id="${doc.id}" title="Dossyeni o'chirish">
              <i class="fas fa-trash"></i>
            </button>
          </div>
        </div>
      `;
    });

    el.dossiersGridContainer.innerHTML = html;

    // Attach actions
    const previewBtns = el.dossiersGridContainer.querySelectorAll('.btn-preview-dossier');
    previewBtns.forEach(btn => {
      btn.addEventListener('click', function () {
        const id = this.getAttribute('data-id');
        const fname = this.getAttribute('data-file');
        openPdfViewerModal(id, fname);
      });
    });

    const deleteBtns = el.dossiersGridContainer.querySelectorAll('.btn-delete-dossier');
    deleteBtns.forEach(btn => {
      btn.addEventListener('click', function () {
        const id = this.getAttribute('data-id');
        deleteDossier(id);
      });
    });
  }

  function renderPrescriptions(rxList) {
    if (!rxList || !rxList.length) {
      el.prescriptionsTableBody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--dossier-text-light);">Tayinlangan dori-darmonlar mavjud emas</td></tr>`;
      return;
    }

    let html = '';
    rxList.forEach(rx => {
      const statusPill = rx.status === 'active' 
        ? '<span class="status-pill active"><i class="fas fa-check"></i> Faol</span>'
        : '<span class="status-pill inactive">Yakunlangan</span>';

      html += `
        <tr>
          <td><strong>${escapeHtml(rx.medication_name || '-')}</strong></td>
          <td>${escapeHtml(rx.dosage || '-')} ${rx.form ? `(${escapeHtml(rx.form)})` : ''}</td>
          <td>${escapeHtml(rx.route || '-')}</td>
          <td>${rx.duration_days ? rx.duration_days + ' kun' : '-'}</td>
          <td>${escapeHtml(rx.timing || rx.instructions || '-')}</td>
          <td>${statusPill}</td>
        </tr>
      `;
    });
    el.prescriptionsTableBody.innerHTML = html;
  }

  function renderAdministrations(adminList) {
    if (!adminList || !adminList.length) {
      el.administrationsTableBody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--dossier-text-light);">Qabul qilingan dori yozuvlari mavjud emas</td></tr>`;
      return;
    }

    let html = '';
    adminList.forEach(log => {
      html += `
        <tr>
          <td>${formatDateTime(log.administered_at)}</td>
          <td><strong>${escapeHtml(log.medication_name || '-')}</strong></td>
          <td>${escapeHtml(log.dosage || '-')}</td>
          <td>${escapeHtml(log.route || '-')}</td>
          <td><i class="fas fa-user-nurse" style="color: var(--dossier-accent); margin-right: 4px;"></i> ${escapeHtml(log.nurse_name || 'Hamshira')}</td>
          <td><span class="status-pill active"><i class="fas fa-check-circle"></i> Berildi</span></td>
        </tr>
      `;
    });
    el.administrationsTableBody.innerHTML = html;
  }

  function renderVitals(vitalsList) {
    if (!vitalsList || !vitalsList.length) {
      el.vitalsTableBody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--dossier-text-light);">Vital belgilar monitoring yozuvlari mavjud emas</td></tr>`;
      return;
    }

    let html = '';
    vitalsList.forEach(v => {
      const dateStr = v.log_date ? formatDate(v.log_date) : formatDateTime(v.created_at);
      const bp = (v.bp_systolic && v.bp_diastolic) ? `${v.bp_systolic}/${v.bp_diastolic}` : (v.blood_pressure || '-');
      const pulse = v.pulse || v.heart_rate || '-';
      const temp = v.temperature ? `${v.temperature}°C` : '-';
      const spo2 = v.spo2 ? `${v.spo2}%` : '-';
      const note = v.notes || v.nurse_note || '-';

      html += `
        <tr>
          <td>${dateStr}</td>
          <td><strong>${escapeHtml(bp)}</strong></td>
          <td>${pulse}</td>
          <td>${temp}</td>
          <td>${spo2}</td>
          <td>${escapeHtml(note)}</td>
        </tr>
      `;
    });
    el.vitalsTableBody.innerHTML = html;
  }

  function renderEpicrisis(epicrisis) {
    if (!epicrisis || !epicrisis.id) {
      el.epicrisisResultDisplay.textContent = 'Epikriz rasmiylashtirilmagan';
      el.epicrisisTextDisplay.textContent = 'Bemor uchun hozircha bosqichli yoki chiqarish epikrizi kiritilmagan.';
      el.epicrisisRecsDisplay.textContent = 'Mavjud emas';
      return;
    }

    el.epicrisisResultDisplay.textContent = epicrisis.treatment_outcome || epicrisis.discharge_condition || 'Davolash o\'tkazildi';
    el.epicrisisTextDisplay.textContent = epicrisis.epicrisis_text || epicrisis.anamnesis_and_course || 'Qayd etilmagan';
    el.epicrisisRecsDisplay.textContent = epicrisis.recommendations || epicrisis.psycho_recommendations || 'Mavjud emas';
  }

  function renderEmptyState() {
    el.heroPatientName.textContent = 'Bemorlar mavjud emas';
    el.heroPatientId.innerHTML = '<i class="fas fa-id-badge"></i> -';
    el.dossiersGridContainer.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1;">
        <i class="fas fa-users-slash"></i>
        <h3>Bazada bemorlar ro'yxati topilmadi</h3>
        <p>Qabulxona orqali yangi bemor ro'yxatga olinganidan so'ng bu yerda uning PDF dossyesi boshqariladi.</p>
      </div>`;
  }

  // --------------------------------------------------------------------------
  // Dossier Generation & Clinical Data Saving
  // --------------------------------------------------------------------------
  async function generateDossier(docType, customNotes) {
    if (!state.selectedPatientId) {
      showToast('Iltimos, avval bemorni tanlang.', 'warning');
      return;
    }

    const docTypeLabel = docType === '4_page' ? '4 sahifali to\'liq' : '2 sahifali qisqa';
    const btn = docType === '4_page' ? el.btnGenerate4page : el.btnGenerate2page;
    const origHtml = btn.innerHTML;

    btn.disabled = true;
    btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> <span>Shakllantirilmoqda...</span>`;

    try {
      const payload = {
        patient_id: state.selectedPatientId,
        doc_type: docType,
        notes: customNotes || null,
        custom_data: {
          diagnosis: el.inputClinicalDiagnosis ? el.inputClinicalDiagnosis.value.trim() : null,
          complaints: el.inputComplaints ? el.inputComplaints.value.trim() : null,
          past_history: el.inputPastHistory ? el.inputPastHistory.value.trim() : null,
          somatic_status: el.inputSomaticStatus ? el.inputSomaticStatus.value.trim() : null,
          mental_status: el.inputMentalStatus ? el.inputMentalStatus.value.trim() : null
        }
      };

      const res = await fetch('/api/dossiers/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const resData = await res.json();
      if (!res.ok) {
        throw new Error(resData.error || `HTTP ${res.status}`);
      }

      showToast(`${docTypeLabel} rasmiy PDF dossye muvaffaqiyatli saqlandi!`, 'success');

      // Refresh current patient details
      await selectPatient(state.selectedPatientId);

      // Open newly generated dossier in viewer modal
      if (resData.dossier && resData.dossier.id) {
        openPdfViewerModal(resData.dossier.id, resData.dossier.file_name);
      }
    } catch (err) {
      console.error('Dossye shakllantirishda xatolik:', err);
      showToast(err.message || 'PDF dossye yaratishda xatolik yuz berdi.', 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  }

  async function saveClinicalData() {
    if (!state.selectedPatientId) {
      showToast('Iltimos, avval bemorni tanlang.', 'warning');
      return;
    }

    const btn = el.btnSaveAnamnesis;
    const origHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> <span>Saqlanmoqda...</span>`;

    try {
      const payload = {
        patient_id: state.selectedPatientId,
        diagnosis: el.inputClinicalDiagnosis.value.trim(),
        complaints: el.inputComplaints.value.trim(),
        past_history: el.inputPastHistory.value.trim(),
        somatic_status: el.inputSomaticStatus.value.trim(),
        mental_status: el.inputMentalStatus.value.trim()
      };

      const res = await fetch('/api/dossiers/save-clinical-data', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const resData = await res.json();
      if (!res.ok) throw new Error(resData.error || `HTTP ${res.status}`);

      showToast('Klinik ma\'lumotlar muvaffaqiyatli yangilandi!', 'success');
      el.heroDiagnosis.textContent = payload.diagnosis || 'Qayd etilmagan';
    } catch (err) {
      console.error('Klinik ma\'lumotlarni saqlashda xatolik:', err);
      showToast(err.message || 'Ma\'lumotlarni saqlab bo\'lmadi.', 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  }

  async function deleteDossier(dossierId) {
    if (!dossierId) return;

    const confirmed = window.confirm("Haqiqatdan ham ushbu PDF dossye hujjatini serverdan o'chirmoqchimisiz?");
    if (!confirmed) return;

    try {
      const res = await fetch(`/api/dossiers/${encodeURIComponent(dossierId)}`, {
        method: 'DELETE'
      });
      const resData = await res.json();
      if (!res.ok) throw new Error(resData.error || `HTTP ${res.status}`);

      showToast('PDF dossye muvaffaqiyatli o\'chirildi.', 'success');
      await selectPatient(state.selectedPatientId);
    } catch (err) {
      console.error('Dossyeni o\'chirishda xatolik:', err);
      showToast(err.message || 'Dossyeni o\'chirishda xatolik yuz berdi.', 'error');
    }
  }

  // --------------------------------------------------------------------------
  // Modals Management
  // --------------------------------------------------------------------------
  function openPdfViewerModal(dossierId, fileName) {
    if (!el.pdfViewerModal) return;
    const url = `/api/dossiers/file/${encodeURIComponent(dossierId)}`;
    el.pdfModalFilename.textContent = fileName || 'Bemor Dossyesi.pdf';
    el.pdfModalIframe.src = url;
    el.btnPdfModalDownload.href = `${url}?download=1`;
    el.pdfViewerModal.classList.add('active');
  }

  function closePdfViewerModal() {
    if (!el.pdfViewerModal) return;
    el.pdfViewerModal.classList.remove('active');
    el.pdfModalIframe.src = 'about:blank';
  }

  function openCustomModal() {
    if (!state.selectedPatientId) {
      showToast('Iltimos, avval bemorni tanlang.', 'warning');
      return;
    }
    if (el.customGenModal) {
      el.inputModalCustomNotes.value = '';
      el.customGenModal.classList.add('active');
    }
  }

  function closeCustomModal() {
    if (el.customGenModal) {
      el.customGenModal.classList.remove('active');
    }
  }

  async function submitCustomGenerate() {
    const docType = el.selectModalDocType.value || '4_page';
    const notes = el.inputModalCustomNotes.value.trim();

    closeCustomModal();
    await generateDossier(docType, notes);
  }

  // --------------------------------------------------------------------------
  // Utilities
  // --------------------------------------------------------------------------
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function formatDate(dStr) {
    if (!dStr) return '-';
    try {
      const d = new Date(dStr);
      if (isNaN(d.getTime())) return dStr;
      const day = String(d.getDate()).padStart(2, '0');
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const y = d.getFullYear();
      return `${day}.${m}.${y}`;
    } catch (e) {
      return dStr;
    }
  }

  function formatDateTime(dStr) {
    if (!dStr) return '-';
    try {
      const d = new Date(dStr);
      if (isNaN(d.getTime())) return dStr;
      const day = String(d.getDate()).padStart(2, '0');
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const y = d.getFullYear();
      const h = String(d.getHours()).padStart(2, '0');
      const min = String(d.getMinutes()).padStart(2, '0');
      return `${day}.${m}.${y} ${h}:${min}`;
    } catch (e) {
      return dStr;
    }
  }

  function showToast(message, type) {
    if (window.FMH && typeof window.FMH.toast === 'function') {
      window.FMH.toast(message, type || 'info');
      return;
    }
    // Fallback lightweight toast
    const toast = document.createElement('div');
    toast.style.position = 'fixed';
    toast.style.bottom = '24px';
    toast.style.right = '24px';
    toast.style.padding = '12px 20px';
    toast.style.borderRadius = '8px';
    toast.style.color = '#ffffff';
    toast.style.fontWeight = '600';
    toast.style.fontSize = '13px';
    toast.style.boxShadow = '0 6px 20px rgba(0,0,0,0.25)';
    toast.style.zIndex = '999999';
    toast.style.transition = 'all 0.3s ease';

    if (type === 'error') {
      toast.style.background = '#ef4444';
    } else if (type === 'warning') {
      toast.style.background = '#f59e0b';
    } else {
      toast.style.background = '#10b981';
    }

    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

})();
