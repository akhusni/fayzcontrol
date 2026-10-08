/**
 * FAYZ MEDICAL HOUSE — STATIONARY WARD ROUND
 *
 * Who is in a bed on a given day, and whether the doctor has seen them yet.
 *
 * The per-patient check-up already existed inside the EMR, but there was no
 * list: a doctor had to already know who was in the building and open each
 * record in turn, with nothing anywhere saying who had been seen and who was
 * still waiting. The board is built server-side (nursery.ward_round), so the
 * ordering and the "seen" rule live in one place.
 */
(function () {
  'use strict';

  function showToast(message, type = 'success') {
    if (window.FMH_Toast) return window.FMH_Toast(message, type);
    console.warn('[ward]', type, message);
  }

  const state = { date: todayISO(), board: null, doctorName: '' };

  function todayISO() {
    const d = new Date();
    const p = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }

  function shiftDate(iso, days) {
    const [y, m, d] = iso.split('-').map(Number);
    const dt = new Date(y, m - 1, d);
    dt.setDate(dt.getDate() + days);
    const p = n => String(n).padStart(2, '0');
    return `${dt.getFullYear()}-${p(dt.getMonth() + 1)}-${p(dt.getDate())}`;
  }

  const MONTHS = ['Yanvar', 'Fevral', 'Mart', 'Aprel', 'May', 'Iyun',
                  'Iyul', 'Avgust', 'Sentabr', 'Oktabr', 'Noyabr', 'Dekabr'];
  const WEEKDAYS = ['Yakshanba', 'Dushanba', 'Seshanba', 'Chorshanba',
                    'Payshanba', 'Juma', 'Shanba'];

  function humanDate(iso) {
    const [y, m, d] = iso.split('-').map(Number);
    const dt = new Date(y, m - 1, d);
    return `${d}-${MONTHS[m - 1]} ${y}, ${WEEKDAYS[dt.getDay()]}`;
  }

  function esc(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function hasAllergy(text) {
    const t = (text || '').trim().toLowerCase();
    return t && t !== "yo'q" && t !== 'yoq' && t !== '-' && t !== 'none';
  }

  const CONDITIONS = [
    ['satisfactory', 'Qoniqarli'],
    ['moderate',     "O'rta og'ir"],
    ['severe',       "Og'ir"],
    ['critical',     'Kritik'],
  ];

  const VITALS = [
    { key: 'vital_bp_systolic',  label: 'Sist.',   unit: 'mm',  step: '1' },
    { key: 'vital_bp_diastolic', label: 'Diast.',  unit: 'mm',  step: '1' },
    { key: 'vital_pulse',        label: 'Puls',    unit: 'zarb', step: '1' },
    { key: 'vital_temp',         label: 'Harorat', unit: '°C',  step: '0.1' },
    { key: 'vital_spo2',         label: 'SpO2',    unit: '%',   step: '1' },
  ];

  // What the nurse recorded, shown as context rather than as a field the
  // doctor edits: the two observations are separate records by separate
  // people, and overwriting one from the other would lose that.
  function nurseVitalsLine(v) {
    if (!v) return '<span class="ward-novitals">Hamshira ko\'rsatkichlari yozilmagan</span>';
    const bits = [];
    if (v.vital_bp_systolic || v.vital_bp_diastolic) {
      bits.push(`AB ${v.vital_bp_systolic ?? '—'}/${v.vital_bp_diastolic ?? '—'}`);
    }
    if (v.vital_pulse != null) bits.push(`Puls ${v.vital_pulse}`);
    if (v.vital_temp != null) bits.push(`${v.vital_temp}°C`);
    if (v.vital_spo2 != null) bits.push(`SpO2 ${v.vital_spo2}%`);
    if (v.nurse_notes) bits.push(esc(v.nurse_notes));
    if (!bits.length) return '<span class="ward-novitals">Hamshira ko\'rsatkichlari yozilmagan</span>';
    return `<i class="fas fa-syringe"></i> ${bits.join(' &nbsp;·&nbsp; ')}`
      + (v.nurse_name ? ` <span class="ward-by">— ${esc(v.nurse_name)}</span>` : '');
  }

  function renderPatient(p, canRecord) {
    const c = p.checkup || {};
    const allergy = hasAllergy(p.medical_allergies)
      ? `<div class="patient-allergy" title="Dori allergiyasi">
           <i class="fas fa-triangle-exclamation"></i>${esc(p.medical_allergies)}
         </div>` : '';

    const vitalInputs = VITALS.map(f => `
      <label class="vital-field">
        <span class="vital-label">${f.label}</span>
        <input type="number" step="${f.step}" class="vital-input"
               data-adm="${esc(p.admission_id)}" data-field="${f.key}"
               value="${c[f.key] === null || c[f.key] === undefined ? '' : esc(c[f.key])}"
               ${canRecord ? '' : 'disabled'}>
        <span class="vital-unit">${f.unit}</span>
      </label>`).join('');

    const conditionOpts = CONDITIONS.map(([v, label]) =>
      `<option value="${v}"${(c.patient_condition || 'moderate') === v ? ' selected' : ''}>${label}</option>`
    ).join('');

    return `
      <article class="patient-card ward-card${p.seen ? ' is-seen' : ''}">
        <header class="patient-head">
          <div class="patient-bed">
            ${esc(p.bed_code)}<small>${esc(p.room_number)}-XONA</small>
          </div>
          <div class="patient-ident">
            <div class="patient-name">${esc(p.patient_name)}</div>
            <div class="patient-code">
              ${esc(p.patient_code)} · ${p.day_of_stay}/${p.total_days}-kun
              ${p.doctor_name ? ' · ' + esc(p.doctor_name) : ''}
            </div>
          </div>
          ${allergy}
          <button type="button" class="btn-plan-view no-print" data-pid="${esc(p.patient_id)}"
                  data-name="${esc(p.patient_name)}" title="Shifokorning davolash rejasi (faqat o'qish)">
            <i class="fas fa-clipboard-list"></i> Davolash rejasi
          </button>
          <div class="ward-status ${p.seen ? 'seen' : 'waiting'}">
            <i class="fas ${p.seen ? 'fa-circle-check' : 'fa-clock'}"></i>
            ${p.seen ? "Ko'rikdan o'tgan" : 'Kutilmoqda'}
          </div>
        </header>

        <div class="ward-nursevitals">${nurseVitalsLine(p.vitals)}</div>

        <div class="ward-form">
          <div class="ward-form-row">
            <label class="ward-field ward-field-condition">
              <span class="ward-label">Umumiy holati</span>
              <select class="ward-condition" data-adm="${esc(p.admission_id)}"
                      ${canRecord ? '' : 'disabled'}>${conditionOpts}</select>
            </label>
            ${vitalInputs}
          </div>
          <div class="ward-form-row">
            <label class="ward-field ward-grow">
              <span class="ward-label">Dinamika (majburiy)</span>
              <textarea class="ward-dynamics" rows="2"
                        data-adm="${esc(p.admission_id)}"
                        placeholder="Bugungi holati, shikoyatlari, kuzatuv..."
                        ${canRecord ? '' : 'disabled'}>${esc(c.dynamics_notes || '')}</textarea>
            </label>
            <label class="ward-field ward-grow">
              <span class="ward-label">Davolashga o'zgartirish</span>
              <textarea class="ward-adjust" rows="2"
                        data-adm="${esc(p.admission_id)}"
                        placeholder="Dozani o'zgartirish, qo'shimcha tekshiruv..."
                        ${canRecord ? '' : 'disabled'}>${esc(c.treatment_adjustments || '')}</textarea>
            </label>
          </div>
          <div class="ward-form-actions">
            ${c.doctor_name ? `<span class="ward-by">Yozgan: ${esc(c.doctor_name)}</span>` : ''}
            <button type="button" class="btn-ward-save"
                    data-adm="${esc(p.admission_id)}" data-patient="${esc(p.patient_id)}"
                    ${canRecord ? '' : 'disabled'}>
              <i class="fas fa-floppy-disk"></i> ${p.seen ? "Ko'rikni yangilash" : "Ko'rikni saqlash"}
            </button>
          </div>
        </div>
      </article>`;
  }

  function render(board) {
    const host = document.getElementById('ward-container');
    const empty = document.getElementById('ward-empty');
    if (!board.patients.length) {
      host.innerHTML = '';
      empty.style.display = '';
      return;
    }
    empty.style.display = 'none';
    // A round cannot be written before it happens.
    const canRecord = !board.is_future;
    host.innerHTML = board.patients.map(p => renderPatient(p, canRecord)).join('');

    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    set('chip-total', board.totals.total);
    set('chip-seen', board.totals.seen);
    set('chip-waiting', board.totals.waiting);

    const label = document.getElementById('date-label');
    label.className = 'nurse-date-label';
    let text = humanDate(board.date);
    if (board.is_past) { text += ' — o’tgan kun'; label.classList.add('is-past'); }
    else if (board.is_future) { text += ' — kelajak (yozib bo’lmaydi)'; label.classList.add('is-future'); }
    label.textContent = text;
  }

  async function load() {
    try {
      const res = await fetch('/api/doctor/ward-round?date=' + encodeURIComponent(state.date));
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        showToast(body.error || 'Ro’yxatni yuklab bo’lmadi', 'danger');
        return;
      }
      state.board = await res.json();
      render(state.board);
    } catch (e) {
      showToast('Serverga ulanib bo’lmadi', 'danger');
    }
  }

  async function save(admissionId, patientId, button) {
    const pick = sel => document.querySelector(`${sel}[data-adm="${CSS.escape(admissionId)}"]`);
    const dynamics = (pick('.ward-dynamics') || {}).value || '';
    if (!dynamics.trim()) {
      showToast("Dinamika to'ldirilishi shart", 'danger');
      (pick('.ward-dynamics') || {}).focus?.();
      return;
    }

    const payload = {
      patient_id: patientId,
      admission_id: admissionId,
      note_date: state.date,
      patient_condition: (pick('.ward-condition') || {}).value || 'moderate',
      dynamics_notes: dynamics,
      treatment_adjustments: (pick('.ward-adjust') || {}).value || '',
    };
    document.querySelectorAll(
      `.vital-input[data-adm="${CSS.escape(admissionId)}"]`
    ).forEach(el => { payload[el.dataset.field] = el.value; });

    button.disabled = true;
    try {
      const res = await fetch('/api/doctor/notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Xatolik (${res.status})`);
      showToast("Ko'rik saqlandi ✓", 'success');
      await load();
    } catch (e) {
      showToast(e.message, 'danger');
      button.disabled = false;
    }
  }

  function go(date) {
    state.date = date;
    document.getElementById('ward-date').value = date;
    load();
  }

  function init() {
    document.getElementById('ward-date').value = state.date;

    document.getElementById('btn-prev-day')
      .addEventListener('click', () => go(shiftDate(state.date, -1)));
    document.getElementById('btn-next-day')
      .addEventListener('click', () => go(shiftDate(state.date, 1)));
    document.getElementById('btn-today')
      .addEventListener('click', () => go(todayISO()));
    document.getElementById('ward-date')
      .addEventListener('change', e => go(e.target.value || todayISO()));

    document.getElementById('ward-container').addEventListener('click', e => {
      const plan = e.target.closest('.btn-plan-view');
      if (plan) {
        if (window.FMH_PlanView) window.FMH_PlanView.show(plan.dataset.pid, plan.dataset.name);
        return;
      }
      const btn = e.target.closest('.btn-ward-save');
      if (!btn) return;
      save(btn.dataset.adm, btn.dataset.patient, btn);
    });

    document.getElementById('btn-print-ward').addEventListener('click', () => {
      const stamp = new Date();
      const p = n => String(n).padStart(2, '0');
      document.getElementById('print-date').textContent = humanDate(state.date);
      document.getElementById('print-doctor').textContent = state.doctorName || '—';
      document.getElementById('print-stamp').textContent =
        `${p(stamp.getDate())}.${p(stamp.getMonth() + 1)}.${stamp.getFullYear()} ` +
        `${p(stamp.getHours())}:${p(stamp.getMinutes())}`;
      window.print();
    });

    // Name the doctor on the printed sheet.
    fetch('/api/auth/session')
      .then(r => r.json())
      .then(s => {
        if (s && s.user) state.doctorName = s.user.full_name || s.user.username || '';
      })
      .catch(() => {});

    load();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
