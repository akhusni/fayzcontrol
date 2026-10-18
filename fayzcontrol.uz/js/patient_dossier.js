/**
 * Fayz Medical House — Patient Dossier Windows File Explorer & Registry Portal
 * Displays all clinic patients (Last-Came-First-Served / LIFO order),
 * provides direct download and preview for Section A, B, C, D, and the unified full dossier.
 */

(function () {
  'use strict';

  // Global State
  const state = {
    patients: [],
    filteredPatients: [],
    activeFilter: 'all', // 'all' | 'inpatient' | 'outpatient'
    searchTerm: '',
    isLoading: false
  };

  // DOM Elements
  const el = {};

  document.addEventListener('DOMContentLoaded', init);

  function init() {
    cacheElements();
    bindEvents();
    fetchPatients();
  }

  function cacheElements() {
    el.searchInput = document.getElementById('patient-search-input');
    el.btnClearSearch = document.getElementById('btn-clear-search');
    el.filterBtns = document.querySelectorAll('.filter-btn');
    el.btnRefresh = document.getElementById('btn-refresh-list');
    el.tbody = document.getElementById('registry-table-tbody');
    el.showingCount = document.getElementById('table-showing-count');

    // Stats
    el.statTotal = document.getElementById('stat-total-patients');
    el.statInpatient = document.getElementById('stat-inpatient-count');
    el.statOutpatient = document.getElementById('stat-outpatient-count');

    // PDF Viewer Modal
    el.pdfModal = document.getElementById('pdf-viewer-modal');
    el.pdfModalTitle = document.getElementById('pdf-modal-filename');
    el.pdfModalIframe = document.getElementById('pdf-modal-iframe');
    el.btnPdfModalDownload = document.getElementById('btn-pdf-modal-download');
    el.btnPdfModalPrint = document.getElementById('btn-pdf-modal-print');
    el.btnClosePdfModal = document.getElementById('btn-close-pdf-modal');
  }

  function bindEvents() {
    // Search input
    if (el.searchInput) {
      el.searchInput.addEventListener('input', function (e) {
        state.searchTerm = (e.target.value || '').trim().toLowerCase();
        if (el.btnClearSearch) {
          el.btnClearSearch.style.display = state.searchTerm ? 'block' : 'none';
        }
        applyFilterAndRender();
      });
    }

    if (el.btnClearSearch) {
      el.btnClearSearch.addEventListener('click', function () {
        if (el.searchInput) el.searchInput.value = '';
        state.searchTerm = '';
        el.btnClearSearch.style.display = 'none';
        applyFilterAndRender();
        if (el.searchInput) el.searchInput.focus();
      });
    }

    // Filter Buttons
    if (el.filterBtns) {
      el.filterBtns.forEach(function (btn) {
        btn.addEventListener('click', function () {
          el.filterBtns.forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          state.activeFilter = btn.dataset.filter || 'all';
          applyFilterAndRender();
        });
      });
    }

    // Refresh Button
    if (el.btnRefresh) {
      el.btnRefresh.addEventListener('click', function () {
        fetchPatients(true);
      });
    }

    // Modal Events
    if (el.btnClosePdfModal) {
      el.btnClosePdfModal.addEventListener('click', closePdfModal);
    }

    if (el.pdfModal) {
      el.pdfModal.addEventListener('click', function (e) {
        if (e.target === el.pdfModal) closePdfModal();
      });
    }

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && el.pdfModal && el.pdfModal.classList.contains('active')) {
        closePdfModal();
      }
    });

    if (el.btnPdfModalPrint) {
      el.btnPdfModalPrint.addEventListener('click', function () {
        if (el.pdfModalIframe && el.pdfModalIframe.contentWindow) {
          try {
            el.pdfModalIframe.contentWindow.focus();
            el.pdfModalIframe.contentWindow.print();
          } catch (err) {
            window.print();
          }
        }
      });
    }
  }

  // --- API CALLS ---
  function fetchPatients(isManualRefresh = false) {
    state.isLoading = true;
    renderLoading();

    fetch('/api/dossiers/patients')
      .then(function (res) {
        if (!res.ok) throw new Error('Bemorlar ro\'yxatini olishda xatolik: ' + res.status);
        return res.json();
      })
      .then(function (data) {
        state.patients = data.patients || [];
        updateStats();
        applyFilterAndRender();
        if (isManualRefresh && window.FMHDialogs) {
          window.FMHDialogs.toast('Bemorlar reestri muvaffaqiyatli yangilandi', 'success');
        }
      })
      .catch(function (err) {
        console.error(err);
        renderError('Ma\'lumotlarni yuklab bo\'lmadi: ' + err.message);
        if (window.FMHDialogs) {
          window.FMHDialogs.toast('Xatolik: ' + err.message, 'error');
        }
      })
      .finally(function () {
        state.isLoading = false;
      });
  }

  function updateStats() {
    const total = state.patients.length;
    let inp = 0;
    let out = 0;

    state.patients.forEach(function (p) {
      if (p.admission_id) inp++;
      else out++;
    });

    if (el.statTotal) el.statTotal.textContent = total.toLocaleString();
    if (el.statInpatient) el.statInpatient.textContent = inp.toLocaleString();
    if (el.statOutpatient) el.statOutpatient.textContent = out.toLocaleString();
  }

  function applyFilterAndRender() {
    let list = state.patients.slice();

    // 1. Category Filter
    if (state.activeFilter === 'inpatient') {
      list = list.filter(p => !!p.admission_id);
    } else if (state.activeFilter === 'outpatient') {
      list = list.filter(p => !p.admission_id);
    }

    // 2. Search Filter
    if (state.searchTerm) {
      const q = state.searchTerm;
      list = list.filter(function (p) {
        const name = (p.full_name || '').toLowerCase();
        const code = (p.patient_code || '').toLowerCase();
        const phone = (p.phone || '').toLowerCase();
        const diag = (p.diagnosis || '').toLowerCase();
        return name.includes(q) || code.includes(q) || phone.includes(q) || diag.includes(q);
      });
    }

    state.filteredPatients = list;
    renderTable();
  }

  // --- RENDER TABLE ---
  function renderTable() {
    if (!el.tbody) return;

    if (state.filteredPatients.length === 0) {
      el.tbody.innerHTML = `
        <tr>
          <td colspan="9" style="text-align: center; padding: 40px; color: var(--dossier-text-muted);">
            <i class="fas fa-search" style="font-size: 28px; margin-bottom: 10px; color: var(--dossier-text-light);"></i>
            <p style="font-weight: 600; font-size: 14px; margin: 0;">Bunday mezon bo'yicha bemorlar topilmadi</p>
            <p style="font-size: 12px; color: var(--dossier-text-light); margin-top: 4px;">Qidiruv so'zini o'zgartirib ko'ring yoki filtrni barchasiga o'tkazing.</p>
          </td>
        </tr>
      `;
      if (el.showingCount) el.showingCount.textContent = "Ko'rsatilmoqda: 0 ta bemor";
      return;
    }

    let html = '';
    const currentYear = new Date().getFullYear();

    state.filteredPatients.forEach(function (pt, idx) {
      const isInpatient = !!pt.admission_id;
      const ageStr = pt.birth_year ? (currentYear - parseInt(pt.birth_year)) + ' yosh' : '—';
      const safeCode = pt.patient_code || ('ID:' + pt.id);
      const safeName = pt.full_name || 'Nomsiz bemor';

      // Location badge
      let locHtml = '';
      if (isInpatient) {
        const roomTxt = pt.room_number ? (pt.room_number + '-xona') : 'Statsionar';
        const bedTxt = pt.bed_number ? (', ' + pt.bed_number) : '';
        locHtml = `<span class="ward-badge inpatient"><i class="fas fa-bed"></i> ${escapeHtml(roomTxt + bedTxt)}</span>`;
      } else {
        locHtml = `<span class="ward-badge outpatient"><i class="fas fa-walking"></i> Ambulator</span>`;
      }

      // Gender badge
      let genderHtml = '';
      if (pt.gender === 'female') {
        genderHtml = `<span class="gender-badge female"><i class="fas fa-venus"></i> Ayol</span>`;
      } else if (pt.gender === 'male') {
        genderHtml = `<span class="gender-badge male"><i class="fas fa-mars"></i> Erkak</span>`;
      } else {
        genderHtml = `<span class="gender-badge" style="color: var(--dossier-text-light);">—</span>`;
      }

      html += `
        <tr data-patient-id="${pt.id}">
          <td class="col-num">${idx + 1}</td>

          <td class="col-patient">
            <div class="patient-cell-wrap">
              <div class="patient-name-row">
                <span class="patient-name">${escapeHtml(safeName)}</span>
                <span class="patient-code-tag">${escapeHtml(safeCode)}</span>
              </div>
              <div class="patient-meta-row">
                ${locHtml}
                ${pt.diagnosis ? `<span title="${escapeHtml(pt.diagnosis)}" style="max-width: 170px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">• ${escapeHtml(pt.diagnosis)}</span>` : ''}
              </div>
            </div>
          </td>

          <td class="col-phone">
            <div class="phone-cell-wrap">
              <i class="fas fa-phone-alt"></i>
              <span>${escapeHtml(pt.phone || '—')}</span>
            </div>
          </td>

          <td class="col-age">
            <div class="age-gender-wrap">
              <span class="age-text">${ageStr}</span>
              ${genderHtml}
            </div>
          </td>

          <!-- Kasallik tarixi & Anamnez -->
          <td class="col-section col-sec-a">
            <div class="section-action-cell">
              <i class="fas fa-check-circle file-status-indicator" title="Kasallik tarixi shakllantirishga tayyor"></i>
              <button type="button" class="btn-sec-download" title="Kasallik tarixi va anamnezni ko'chirish (PDF)" onclick="window.FMHDossier.downloadSection(${pt.id}, 'a', '${escapeJs(safeCode)}')">
                <i class="fas fa-download"></i> <span>Ko'chirish</span>
              </button>
              <button type="button" class="btn-sec-preview" title="Kasallik tarixini ko'rish" onclick="window.FMHDossier.previewSection(${pt.id}, 'a', 'Kasallik tarixi va anamnez (${escapeJs(safeName)}')">
                <i class="fas fa-eye"></i>
              </button>
            </div>
          </td>

          <!-- Status & Ko'rik -->
          <td class="col-section col-sec-b">
            <div class="section-action-cell">
              <i class="fas fa-check-circle file-status-indicator" title="Status va ko'rik shakllantirishga tayyor"></i>
              <button type="button" class="btn-sec-download" title="Psixosomatik status va ko'rikni ko'chirish (PDF)" onclick="window.FMHDossier.downloadSection(${pt.id}, 'b', '${escapeJs(safeCode)}')">
                <i class="fas fa-download"></i> <span>Ko'chirish</span>
              </button>
              <button type="button" class="btn-sec-preview" title="Status va ko'rikni ko'rish" onclick="window.FMHDossier.previewSection(${pt.id}, 'b', 'Status va ko\\'rik (${escapeJs(safeName)}')">
                <i class="fas fa-eye"></i>
              </button>
            </div>
          </td>

          <!-- Dorilar varaqasi -->
          <td class="col-section col-sec-c">
            <div class="section-action-cell">
              <i class="fas fa-check-circle file-status-indicator" title="Dorilar varaqasi shakllantirishga tayyor"></i>
              <button type="button" class="btn-sec-download" title="Dorilar varaqasini ko'chirish (PDF)" onclick="window.FMHDossier.downloadSection(${pt.id}, 'c', '${escapeJs(safeCode)}')">
                <i class="fas fa-download"></i> <span>Ko'chirish</span>
              </button>
              <button type="button" class="btn-sec-preview" title="Dorilar varaqasini ko'rish" onclick="window.FMHDossier.previewSection(${pt.id}, 'c', 'Dorilar varaqasi (${escapeJs(safeName)}')">
                <i class="fas fa-eye"></i>
              </button>
            </div>
          </td>

          <!-- Chiqarish epikrizi -->
          <td class="col-section col-sec-d">
            <div class="section-action-cell">
              <i class="fas fa-check-circle file-status-indicator" title="Chiqarish epikrizi shakllantirishga tayyor"></i>
              <button type="button" class="btn-sec-download" title="Chiqarish epikrizini ko'chirish (PDF)" onclick="window.FMHDossier.downloadSection(${pt.id}, 'd', '${escapeJs(safeCode)}')">
                <i class="fas fa-download"></i> <span>Ko'chirish</span>
              </button>
              <button type="button" class="btn-sec-preview" title="Chiqarish epikrizini ko'rish" onclick="window.FMHDossier.previewSection(${pt.id}, 'd', 'Chiqarish epikrizi (${escapeJs(safeName)}')">
                <i class="fas fa-eye"></i>
              </button>
            </div>
          </td>

          <!-- Umumiy to'liq dossye -->
          <td class="col-general">
            <div class="full-action-cell">
              <button type="button" class="btn-full-download" title="1 ta umumlashtirilgan to'liq rasmiy dossyeni ko'chirish" onclick="window.FMHDossier.downloadSection(${pt.id}, 'full', '${escapeJs(safeCode)}')">
                <i class="fas fa-file-pdf"></i> <span>To'liq Dossye</span>
              </button>
              <button type="button" class="btn-full-preview" title="To'liq dossyeni ko'rish" onclick="window.FMHDossier.previewSection(${pt.id}, 'full', 'Umumiy to\\'liq dossye (${escapeJs(safeName)}')">
                <i class="fas fa-eye"></i>
              </button>
            </div>
          </td>
        </tr>
      `;
    });

    el.tbody.innerHTML = html;
    if (el.showingCount) {
      el.showingCount.textContent = `Ko'rsatilmoqda: ${state.filteredPatients.length} ta bemor (Jami: ${state.patients.length} ta)`;
    }
  }

  function renderLoading() {
    if (!el.tbody) return;
    el.tbody.innerHTML = `
      <tr>
        <td colspan="9" class="table-loading-cell">
          <i class="fas fa-circle-notch fa-spin"></i>
          <p>Bemorlar reestri yuklanmoqda...</p>
        </td>
      </tr>
    `;
  }

  function renderError(msg) {
    if (!el.tbody) return;
    el.tbody.innerHTML = `
      <tr>
        <td colspan="9" style="text-align: center; padding: 30px; color: var(--dossier-danger);">
          <i class="fas fa-exclamation-triangle" style="font-size: 24px; margin-bottom: 8px;"></i>
          <p style="font-weight: 600;">${escapeHtml(msg)}</p>
          <button type="button" class="btn-sec-download" style="margin-top: 10px;" onclick="window.FMHDossier.fetchPatients(true)">
            <i class="fas fa-sync-alt"></i> Qayta urinib ko'rish
          </button>
        </td>
      </tr>
    `;
  }

  // --- ACTIONS (DOWNLOAD & PREVIEW) ---
  function downloadSection(patientId, section, patientCode) {
    if (!patientId) return;
    const url = `/api/dossiers/section-pdf?patient_id=${patientId}&section=${section}&download=1`;
    
    // Create temporary link to trigger immediate download
    const link = document.createElement('a');
    link.href = url;
    link.target = '_blank';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    if (window.FMHDialogs) {
      const secName = {
        'a': 'Kasallik tarixi va anamnez',
        'b': 'Psixosomatik status va ko\'rik',
        'c': 'Dorilar varaqasi',
        'd': 'Chiqarish epikrizi',
        'full': 'Umumiy to\'liq dossye'
      }[section] || 'Dossye';
      window.FMHDialogs.toast(`${secName} yuklab olinmoqda...`, 'info', 2500);
    }
  }

  function previewSection(patientId, section, docTitle) {
    if (!patientId) return;
    const previewUrl = `/api/dossiers/section-pdf?patient_id=${patientId}&section=${section}&download=0`;
    const downloadUrl = `/api/dossiers/section-pdf?patient_id=${patientId}&section=${section}&download=1`;

    if (el.pdfModalTitle) {
      el.pdfModalTitle.textContent = docTitle || 'Dossye hujjati';
    }

    if (el.btnPdfModalDownload) {
      el.btnPdfModalDownload.href = downloadUrl;
    }

    if (el.pdfModalIframe) {
      el.pdfModalIframe.src = previewUrl;
    }

    if (el.pdfModal) {
      el.pdfModal.classList.add('active');
    }
  }

  function closePdfModal() {
    if (el.pdfModal) {
      el.pdfModal.classList.remove('active');
    }
    if (el.pdfModalIframe) {
      el.pdfModalIframe.src = 'about:blank';
    }
  }

  // Utility helpers
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function escapeJs(str) {
    if (!str) return '';
    return String(str).replace(/'/g, "\\'");
  }

  // Global namespace export for inline HTML onclick handlers
  window.FMHDossier = {
    fetchPatients: fetchPatients,
    downloadSection: downloadSection,
    previewSection: previewSection,
    closePdfModal: closePdfModal
  };

})();
