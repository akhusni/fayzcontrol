/**
 * FAYZ MEDICAL HOUSE — CONSULTATION & TREATMENT PLAN
 *
 * The intake form is built from /api/consultations/sections, which serves the
 * same field definition the server validates against (consultation.py). There
 * is deliberately no field list in this file: a 41-field clinical form will be
 * revised, and a second copy here would be a second chance to forget one.
 *
 * The plan is a separate form, saved through its own endpoint and printed as
 * its own document, because the intake is the fixed record of one encounter
 * while the plan is a live instruction that gets revised.
 */
(function () {
  'use strict';

  function showToast(message, type = 'success') {
    if (window.FMH_Toast) return window.FMH_Toast(message, type);
    console.warn('[consultation]', type, message);
  }

  const state = {
    meta: null,          // sections + choice vocabularies from the server
    patient: null,
    appointmentId: null,
    queue: [],
    patients: [],
    history: { consultations: [], plans: [] },
    lastIntakeId: null,
    lastPlanId: null,
    doctorName: '',
  };

  const esc = s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  // Fields whose answers are narrative get the full row width.
  const WIDE = new Set(['living_situation', 'primary_complaint', 'onset_note', 'triggers',
    'overdose_history', 'withdrawal_history', 'prior_rehab_detail',
    'prior_psych_diagnoses', 'prior_psych_hospitalizations', 'self_harm_history',
    'current_medications', 'drug_allergies', 'head_trauma', 'infectious_diseases',
    'other_medical', 'family_history_addiction', 'family_history_depression',
    'family_history_other', 'support_network', 'observed_mood', 'observed_thought',
    'observed_behaviour', 'risk_notes', 'working_diagnosis', 'substances']);

  const REQUIRED = new Set(['primary_complaint']);

  const BASIS_LABEL = {
    voluntary: "O'z xohishi bilan",
    family_initiated: 'Oila tashabbusi bilan',
    court_mandated: 'Sud qarori bilan',
  };
  const RISK_LABEL = {
    none: "Yo'q", low: 'Past', moderate: "O'rta", high: 'Yuqori',
  };
  const PLAN_LABEL = {
    outpatient: 'Ambulator', detox: 'Detoksikatsiya', inpatient: 'Statsionar',
    rehab: 'Reabilitatsiya', referral: 'Boshqa muassasaga yo’naltirish',
  };
  const STATUS_LABEL = {
    active: 'Amaldagi', superseded: 'Almashtirilgan',
    completed: 'Tugatilgan', draft: 'Qoralama',
  };

  // -------------------------------------------------------------------------
  // Form building
  // -------------------------------------------------------------------------

  function fieldHTML(f) {
    const wide = WIDE.has(f.name) ? ' wide' : '';
    const req = REQUIRED.has(f.name) ? '<span class="req">*</span>' : '';
    const hint = f.hint ? `<div class="field-hint">${esc(f.hint)}</div>` : '';
    const label = `<label for="f-${f.name}">${esc(f.label)}${req}</label>`;

    switch (f.type) {
      case 'textarea':
        return `<div class="field${wide}">${label}
          <textarea id="f-${f.name}" name="${f.name}" placeholder="${esc(f.hint)}"></textarea>${hint}</div>`;

      case 'date':
        return `<div class="field">${label}
          <input type="date" id="f-${f.name}" name="${f.name}">${hint}</div>`;

      case 'int':
        return `<div class="field">${label}
          <input type="number" min="0" step="1" id="f-${f.name}" name="${f.name}">${hint}</div>`;

      case 'bool':
        return `<div class="field${wide}">${label}
          <label class="field-check">
            <input type="checkbox" id="f-${f.name}" name="${f.name}">
            <span>${esc(f.hint || 'Ha')}</span>
          </label></div>`;

      case 'choice': {
        const vocab = f.name === 'treatment_basis'
          ? state.meta.treatment_basis.map(v => [v, BASIS_LABEL[v] || v])
          : state.meta.risk_levels.map(v => [v, RISK_LABEL[v] || v]);
        const isRisk = f.name !== 'treatment_basis';
        return `<div class="field">${label}
          <select id="f-${f.name}" name="${f.name}" ${isRisk ? 'data-risk="1"' : ''}>
            ${vocab.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join('')}
          </select>${hint}</div>`;
      }

      case 'substances':
        return `<div class="field wide">${label}
          <div class="substance-list" id="substance-list"></div>
          <button type="button" class="btn-row-add" id="btn-add-substance" style="margin-top:9px;">
            <i class="fas fa-plus"></i> Modda qo'shish
          </button>${hint}</div>`;

      default:
        return `<div class="field${wide}">${label}
          <input type="text" id="f-${f.name}" name="${f.name}" placeholder="${esc(f.hint)}">${hint}</div>`;
    }
  }

  function buildIntakeForm() {
    const form = document.getElementById('intake-form');
    form.innerHTML = state.meta.sections.map(sec => `
      <section class="form-section" data-section="${esc(sec.key)}">
        <header class="form-section-head">
          <div class="form-section-title">${esc(sec.label)}</div>
          <div class="form-section-count">${sec.fields.length} maydon</div>
        </header>
        <div class="form-section-body">
          ${sec.fields.map(fieldHTML).join('')}
        </div>
      </section>`).join('');

    // Sections collapse so a doctor can keep the one they are on in view.
    form.querySelectorAll('.form-section-head').forEach(h => {
      h.addEventListener('click', () => h.parentElement.classList.toggle('collapsed'));
    });

    // Colour the risk selects by severity as they change.
    form.querySelectorAll('select[data-risk]').forEach(sel => {
      const paint = () => {
        sel.className = 'risk-' + sel.value;
      };
      sel.addEventListener('change', paint);
      paint();
    });

    document.getElementById('btn-add-substance')
      .addEventListener('click', () => addSubstanceRow());
    addSubstanceRow();
  }

  function addSubstanceRow(values) {
    const list = document.getElementById('substance-list');
    if (!list) return;
    const row = document.createElement('div');
    row.className = 'substance-row';
    row.innerHTML = `
      <div class="field"><label>Modda / alkogol</label>
        <input type="text" data-sub="substance" placeholder="Alkogol, heroin, tramadol..."></div>
      <div class="field"><label>Yoshi</label>
        <input type="number" min="0" max="120" data-sub="age_first_use" placeholder="16"></div>
      <div class="field"><label>Maksimal kunlik</label>
        <input type="text" data-sub="peak_daily_amount" placeholder="1L / 400mg"></div>
      <div class="field"><label>Oxirgi qo'llash</label>
        <input type="date" data-sub="last_use_date"></div>
      <div class="field"><label>Yo'li</label>
        <input type="text" data-sub="route" placeholder="Ichishga / v/i"></div>
      <button type="button" class="btn-row-remove" title="Qatorni olib tashlash">
        <i class="fas fa-xmark"></i>
      </button>`;
    row.querySelector('.btn-row-remove').addEventListener('click', () => {
      row.remove();
      if (!list.children.length) addSubstanceRow();
    });
    if (values) {
      row.querySelectorAll('[data-sub]').forEach(inp => {
        const v = values[inp.dataset.sub];
        if (v != null && v !== '') inp.value = v;
      });
    }
    list.appendChild(row);
  }

  function buildPlanForm() {
    const form = document.getElementById('plan-form');
    const types = state.meta.plan_types
      .map(v => `<option value="${esc(v)}">${esc(PLAN_LABEL[v] || v)}</option>`).join('');
    form.innerHTML = `
      <section class="form-section">
        <header class="form-section-head">
          <div class="form-section-title">Davolash rejasi</div>
          <div class="form-section-count">alohida saqlanadi</div>
        </header>
        <div class="form-section-body">
          <div class="field"><label for="p-plan_type">Reja turi</label>
            <select id="p-plan_type" name="plan_type">${types}</select></div>
          <div class="field"><label for="p-duration_days">Davomiylik (kun)</label>
            <input type="number" min="1" max="365" id="p-duration_days" name="duration_days" placeholder="10"></div>
          <div class="field"><label for="p-review_date">Qayta ko'rik sanasi</label>
            <input type="date" id="p-review_date" name="review_date"></div>
          <div class="field wide"><label for="p-immediate_actions">Darhol bajarilishi kerak<span class="req">*</span></label>
            <textarea id="p-immediate_actions" name="immediate_actions"
              placeholder="Statsionarga yotqizish, vitallarni nazorat qilish..."></textarea></div>
          <div class="field wide" id="detox-wrap"><label for="p-detox_protocol">Detoksikatsiya protokoli</label>
            <textarea id="p-detox_protocol" name="detox_protocol"
              placeholder="Diazepam kamayuvchi sxema, Tiamin..."></textarea>
            <div class="field-hint">Detoks rejasi uchun majburiy.</div></div>
          <div class="field wide"><label for="p-therapy_plan">Psixoterapiya rejasi</label>
            <textarea id="p-therapy_plan" name="therapy_plan"></textarea></div>
          <div class="field wide"><label for="p-goals">Maqsadlar</label>
            <textarea id="p-goals" name="goals"></textarea></div>
          <div class="field wide"><label for="p-precautions">Ehtiyot choralari</label>
            <textarea id="p-precautions" name="precautions"
              placeholder="Tutqanoq tarixi, allergiya, o'zaro ta'sir..."></textarea></div>
        </div>
      </section>

      <section class="form-section">
        <header class="form-section-head">
          <div class="form-section-title">Tavsiya etilgan dorilar</div>
          <div class="form-section-count">retsept emas — tavsiya</div>
        </header>
        <div class="form-section-body">
          <div class="field wide">
            <div class="field-hint" style="margin-bottom:9px;">
              Bu shifokorning rejadagi tavsiyasi. Hamshira bajaradigan haqiqiy
              retsept alohida beriladi.
            </div>
            <div class="substance-list" id="med-list"></div>
            <button type="button" class="btn-row-add" id="btn-add-med" style="margin-top:9px;">
              <i class="fas fa-plus"></i> Dori qo'shish
            </button>
          </div>
        </div>
      </section>`;

    form.querySelectorAll('.form-section-head').forEach(h => {
      h.addEventListener('click', () => h.parentElement.classList.toggle('collapsed'));
    });

    // The detox protocol is only required for a detox plan, so only show it there.
    const typeSel = document.getElementById('p-plan_type');
    const detoxWrap = document.getElementById('detox-wrap');
    const syncDetox = () => {
      detoxWrap.style.display = typeSel.value === 'detox' ? '' : 'none';
    };
    typeSel.addEventListener('change', syncDetox);
    syncDetox();

    document.getElementById('btn-add-med').addEventListener('click', () => addMedRow());
    addMedRow();
  }

  function addMedRow(values) {
    const list = document.getElementById('med-list');
    if (!list) return;
    const row = document.createElement('div');
    row.className = 'substance-row';
    row.innerHTML = `
      <div class="field"><label>Dori nomi</label>
        <input type="text" data-med="name" placeholder="Diazepam"></div>
      <div class="field"><label>Doza</label>
        <input type="text" data-med="dosage" placeholder="10mg"></div>
      <div class="field"><label>Yo'li</label>
        <input type="text" data-med="route" placeholder="IM / Ichishga"></div>
      <div class="field"><label>Qabul tartibi</label>
        <input type="text" data-med="frequency" placeholder="Kuniga 2 mahal"></div>
      <div class="field"><label>Kun</label>
        <input type="number" min="1" max="365" data-med="duration_days" placeholder="5"></div>
      <button type="button" class="btn-row-remove" title="Qatorni olib tashlash">
        <i class="fas fa-xmark"></i>
      </button>`;
    row.querySelector('.btn-row-remove').addEventListener('click', () => {
      row.remove();
      if (!list.children.length) addMedRow();
    });
    if (values) {
      row.querySelectorAll('[data-med]').forEach(inp => {
        const v = values[inp.dataset.med];
        if (v != null && v !== '') inp.value = v;
      });
    }
    list.appendChild(row);
  }

  // -------------------------------------------------------------------------
  // Reading the forms
  // -------------------------------------------------------------------------

  function collectIntake() {
    const out = { patient_id: state.patient.id };
    if (state.appointmentId) out.appointment_id = state.appointmentId;

    state.meta.sections.forEach(sec => sec.fields.forEach(f => {
      if (f.type === 'substances') return;
      const el = document.getElementById('f-' + f.name);
      if (!el) return;
      out[f.name] = (f.type === 'bool') ? el.checked : el.value;
    }));

    const subs = [];
    document.querySelectorAll('#substance-list .substance-row').forEach(row => {
      const entry = {};
      row.querySelectorAll('[data-sub]').forEach(i => { entry[i.dataset.sub] = i.value.trim(); });
      // A row the doctor started and left blank is not an omission to report.
      if (entry.substance) subs.push(entry);
    });
    if (subs.length) out.substances = subs;
    return out;
  }

  function collectPlan() {
    const out = { patient_id: state.patient.id };
    if (state.lastIntakeId) out.consultation_id = state.lastIntakeId;
    ['plan_type', 'duration_days', 'review_date', 'immediate_actions',
     'detox_protocol', 'therapy_plan', 'goals', 'precautions'].forEach(name => {
      const el = document.getElementById('p-' + name);
      if (el) out[name] = el.value;
    });
    const meds = [];
    document.querySelectorAll('#med-list .substance-row').forEach(row => {
      const entry = {};
      row.querySelectorAll('[data-med]').forEach(i => { entry[i.dataset.med] = i.value.trim(); });
      if (entry.name) meds.push(entry);
    });
    if (meds.length) out.medication_plan = meds;
    return out;
  }

  // -------------------------------------------------------------------------
  // Patient selection
  // -------------------------------------------------------------------------

  function selectPatient(patient, appointmentId) {
    state.patient = patient;
    state.appointmentId = appointmentId || null;
    state.lastIntakeId = null;

    document.getElementById('no-patient').style.display = 'none';
    document.getElementById('work-area').style.display = '';

    document.getElementById('sel-name').textContent = patient.full_name || patient.patient_name || '—';
    const bits = [patient.patient_code, patient.phone || patient.patient_phone,
                  patient.birth_date || (patient.birth_year ? patient.birth_year + '-yil' : null),
                  patient.gender === 'female' ? 'Ayol' : (patient.gender === 'male' ? 'Erkak' : null)];
    document.getElementById('sel-meta').textContent = bits.filter(Boolean).join(' · ');

    const flags = [];
    const allergy = patient.medical_allergies;
    if (allergy && String(allergy).trim().toLowerCase() !== "yo'q") {
      flags.push(`<span class="cons-flag flag-danger"><i class="fas fa-triangle-exclamation"></i>${esc(allergy)}</span>`);
    }
    if (appointmentId) {
      flags.push('<span class="cons-flag flag-info"><i class="fas fa-inbox"></i>Qabulxonadan</span>');
    }
    document.getElementById('sel-flags').innerHTML = flags.join('');

    // Carry over what registration already recorded, so the doctor is not
    // retyping details the patient has already given at the desk.
    // Registration takes a real date of birth now. Only fall back to
    // <year>-01-01 for records made before that field existed, where the year
    // is genuinely all anyone knows.
    const dobField = document.getElementById('f-date_of_birth');
    if (dobField && !dobField.value) {
      if (patient.birth_date) {
        dobField.value = String(patient.birth_date).slice(0, 10);
      } else if (patient.birth_year) {
        dobField.value = `${patient.birth_year}-01-01`;
      }
    }
    if (allergy && !document.getElementById('f-drug_allergies').value) {
      document.getElementById('f-drug_allergies').value = allergy;
    }

    document.querySelectorAll('.queue-item').forEach(b => b.classList.remove('selected'));
    const active = document.querySelector(`.queue-item[data-pid="${patient.id}"]`);
    if (active) active.classList.add('selected');

    loadHistory();
  }

  async function loadHistory() {
    if (!state.patient) return;
    try {
      const res = await fetch('/api/consultations/patient/' + encodeURIComponent(state.patient.id));
      if (!res.ok) return;
      state.history = await res.json();
      renderHistory();
    } catch (e) { /* the session wrapper handles a 401 */ }
  }

  function renderHistory() {
    const host = document.getElementById('history-body');
    const c = state.history.consultations || [];
    const p = state.history.plans || [];
    if (!c.length && !p.length) {
      host.innerHTML = '<div class="queue-empty">Bu bemor uchun oldingi konsultatsiya yoki reja yo’q.</div>';
      return;
    }
    host.innerHTML = `
      <div class="hist-group">
        <div class="hist-title">Konsultatsiyalar (${c.length})</div>
        ${c.length ? c.map(x => `
          <div class="hist-row">
            <div class="hist-date">${esc(String(x.consultation_date).slice(0, 16))}</div>
            <div class="hist-main">${esc(x.working_diagnosis || 'Tashxis kiritilmagan')}
              <div class="hist-sub">${esc(x.icd10_code || '')} ${x.doctor_name ? '· ' + esc(x.doctor_name) : ''}
                · ${esc(BASIS_LABEL[x.treatment_basis] || x.treatment_basis)}</div></div>
            <span class="cons-flag flag-${x.risk_to_self === 'high' ? 'danger' : (x.risk_to_self === 'moderate' ? 'warning' : 'info')}">
              Xavf: ${esc(RISK_LABEL[x.risk_to_self] || x.risk_to_self)}</span>
          </div>`).join('') : '<div class="queue-empty">Yo’q</div>'}
      </div>
      <div class="hist-group">
        <div class="hist-title">Davolash rejalari (${p.length})</div>
        ${p.length ? p.map(x => `
          <div class="hist-row">
            <div class="hist-date">${esc(x.plan_date)}</div>
            <div class="hist-main">${esc(PLAN_LABEL[x.plan_type] || x.plan_type)}
              <div class="hist-sub">${x.duration_days ? x.duration_days + ' kun' : ''}
                ${x.review_date ? '· qayta ko’rik ' + esc(x.review_date) : ''}
                ${x.doctor_name ? '· ' + esc(x.doctor_name) : ''}</div></div>
            <span class="badge badge-${esc(x.status)}">${esc(STATUS_LABEL[x.status] || x.status)}</span>
          </div>`).join('') : '<div class="queue-empty">Yo’q</div>'}
      </div>`;
  }

  // -------------------------------------------------------------------------
  // Queue & search
  // -------------------------------------------------------------------------

  async function loadQueue() {
    const mine = document.getElementById('only-mine').checked ? '?mine=1' : '';
    try {
      const res = await fetch('/api/consultations/queue' + mine);
      if (!res.ok) return;
      state.queue = await res.json();
    } catch (e) { return; }

    const host = document.getElementById('queue-list');
    const empty = document.getElementById('queue-empty');
    if (!state.queue.length) {
      host.innerHTML = '';
      empty.style.display = '';
      return;
    }
    empty.style.display = 'none';
    host.innerHTML = state.queue.map(q => `
      <button type="button" class="queue-item" data-pid="${esc(q.patient_id || '')}"
              data-appt="${esc(q.appointment_id)}">
        <div class="queue-name">${esc(q.patient_name)}</div>
        <div class="queue-meta">${esc(q.appointment_date)} ${esc(String(q.appointment_time).slice(0, 5))}
          ${q.doctor_name ? '· ' + esc(q.doctor_name) : ''}</div>
      </button>`).join('');

    host.querySelectorAll('.queue-item').forEach(btn => {
      btn.addEventListener('click', () => {
        const q = state.queue.find(x => x.appointment_id === btn.dataset.appt);
        if (!q) return;
        if (!q.patient_id) {
          showToast('Bu arizada bemor kartochkasi yo’q — avval CRM da ro’yxatdan o’tkazing', 'warning');
          return;
        }
        selectPatient({
          id: q.patient_id, full_name: q.patient_name, patient_code: q.patient_code,
          phone: q.patient_phone, birth_date: q.birth_date,
          birth_year: q.birth_year, gender: q.gender,
          medical_allergies: q.medical_allergies,
        }, q.appointment_id);
      });
    });
  }

  async function searchPatients(term) {
    const host = document.getElementById('search-results');
    if (!term || term.length < 2) { host.innerHTML = ''; return; }
    if (!state.patients.length) {
      try {
        const res = await fetch('/api/crm/patients');
        if (!res.ok) return;
        state.patients = await res.json();
      } catch (e) { return; }
    }
    const q = term.toLowerCase();
    const hits = state.patients.filter(p =>
      (p.full_name || '').toLowerCase().includes(q) ||
      (p.patient_code || '').toLowerCase().includes(q) ||
      (p.phone || '').includes(q)).slice(0, 12);

    host.innerHTML = hits.length ? hits.map(p => `
      <button type="button" class="queue-item" data-pid="${esc(p.id)}">
        <div class="queue-name">${esc(p.full_name)}</div>
        <div class="queue-meta">${esc(p.patient_code)} ${p.phone ? '· ' + esc(p.phone) : ''}</div>
      </button>`).join('') : '<div class="queue-empty">Topilmadi.</div>';

    host.querySelectorAll('.queue-item').forEach(btn => {
      btn.addEventListener('click', () => {
        const p = state.patients.find(x => x.id === btn.dataset.pid);
        if (p) selectPatient(p, null);
      });
    });
  }

  // -------------------------------------------------------------------------
  // Saving
  // -------------------------------------------------------------------------

  async function saveIntake() {
    if (!state.patient) return;
    const btn = document.getElementById('btn-save-intake');
    const payload = collectIntake();

    const confirmed = await window.fmhConfirm({
      title: 'Konsultatsiyani saqlash',
      message: 'Saqlangandan keyin anketa o’zgartirilmaydi — u suhbat ' +
               'paytidagi holatning qaydi. Davom etamizmi?',
      confirmText: 'Saqlash', cancelText: 'Bekor Qilish', type: 'primary',
    });
    if (!confirmed) return;

    btn.disabled = true;
    try {
      const res = await fetch('/api/consultations', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (res.status !== 401) showToast(body.error || 'Saqlanmadi', 'danger');
        return;
      }
      state.lastIntakeId = body.consultation_id;
      showToast('✓ Konsultatsiya saqlandi', 'success');
      loadHistory();
      loadQueue();
      // The plan is the natural next step, so move there.
      switchPane('plan');
    } catch (e) {
      showToast('Serverga ulanib bo’lmadi', 'danger');
    } finally {
      btn.disabled = false;
    }
  }

  async function savePlan() {
    if (!state.patient) return;
    const btn = document.getElementById('btn-save-plan');
    btn.disabled = true;
    try {
      const res = await fetch('/api/treatment-plans', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(collectPlan()),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (res.status !== 401) showToast(body.error || 'Saqlanmadi', 'danger');
        return;
      }
      state.lastPlanId = body.plan_id;
      showToast('✓ Davolash rejasi saqlandi', 'success');
      loadHistory();
    } catch (e) {
      showToast('Serverga ulanib bo’lmadi', 'danger');
    } finally {
      btn.disabled = false;
    }
  }

  // -------------------------------------------------------------------------
  // Printing — two separate documents
  // -------------------------------------------------------------------------

  function letterhead(docTitle) {
    const now = new Date();
    const p = n => String(n).padStart(2, '0');
    return `
      <div class="pr-head">
        <div class="pr-clinic">FAYZ MEDICAL HOUSE</div>
        <div class="pr-doc">${esc(docTitle)}</div>
        <div class="pr-meta">
          Toshkent sh., Yunusobod t. &nbsp;·&nbsp; Litsenziya №: KM-8842/2022 &nbsp;·&nbsp;
          Chop etilgan: ${p(now.getDate())}.${p(now.getMonth() + 1)}.${now.getFullYear()}
          ${p(now.getHours())}:${p(now.getMinutes())}
        </div>
      </div>`;
  }

  function patientBlock() {
    const pt = state.patient || {};
    return `
      <div class="pr-patient">
        <div><span class="pr-label">Bemor:</span> ${esc(pt.full_name || '')}</div>
        <div><span class="pr-label">Kod:</span> ${esc(pt.patient_code || '')}</div>
        <div><span class="pr-label">Shifokor:</span> ${esc(state.doctorName || '')}</div>
        <div><span class="pr-label">Sana:</span> ${new Date().toLocaleDateString('uz-UZ')}</div>
      </div>`;
  }

  function signatures(leftLabel) {
    return `<div class="pr-sign">
      <div class="pr-sign-line">${esc(leftLabel)}</div>
      <div class="pr-sign-line">Bemor / vakil imzosi</div>
    </div>`;
  }

  function printIntake() {
    if (!state.patient) { showToast('Avval bemorni tanlang', 'warning'); return; }
    const data = collectIntake();
    const sections = state.meta.sections.map(sec => {
      const rows = sec.fields.map(f => {
        if (f.type === 'substances') {
          const subs = data.substances || [];
          if (!subs.length) return '';
          return `<table class="pr-table">
            <tr><th>Modda</th><th>Yoshi</th><th>Maks. kunlik</th><th>Oxirgi</th><th>Yo'li</th></tr>
            ${subs.map(s => `<tr><td>${esc(s.substance)}</td><td>${esc(s.age_first_use)}</td>
              <td>${esc(s.peak_daily_amount)}</td><td>${esc(s.last_use_date)}</td>
              <td>${esc(s.route)}</td></tr>`).join('')}
          </table>`;
        }
        let v = data[f.name];
        if (f.type === 'bool') v = v ? 'Ha' : "Yo'q";
        if (f.type === 'choice') {
          v = (f.name === 'treatment_basis' ? BASIS_LABEL[v] : RISK_LABEL[v]) || v;
          if (f.name.startsWith('risk_')) {
            return `<div class="pr-field"><span class="pr-label">${esc(f.label)}:</span>
              <span class="pr-risk">${esc(v)}</span></div>`;
          }
        }
        if (v == null || v === '') return '';
        return `<div class="pr-field"><span class="pr-label">${esc(f.label)}:</span> ${esc(v)}</div>`;
      }).filter(Boolean).join('');
      if (!rows) return '';
      return `<div class="pr-section">
        <div class="pr-section-title">${esc(sec.label)}</div>${rows}</div>`;
    }).filter(Boolean).join('');

    document.getElementById('print-root').innerHTML =
      letterhead('KONSULTATSIYA BAYONNOMASI') + patientBlock() + sections +
      signatures('Shifokor imzosi');
    window.print();
  }

  function printPlan() {
    if (!state.patient) { showToast('Avval bemorni tanlang', 'warning'); return; }
    const d = collectPlan();
    const meds = d.medication_plan || [];
    const row = (label, value) => value
      ? `<div class="pr-field"><span class="pr-label">${esc(label)}:</span> ${esc(value)}</div>` : '';

    document.getElementById('print-root').innerHTML =
      letterhead('DAVOLASH REJASI') + patientBlock() +
      `<div class="pr-section">
         <div class="pr-section-title">Reja</div>
         ${row('Turi', PLAN_LABEL[d.plan_type] || d.plan_type)}
         ${row('Davomiylik', d.duration_days ? d.duration_days + ' kun' : '')}
         ${row("Qayta ko'rik", d.review_date)}
         ${row('Darhol bajarilishi kerak', d.immediate_actions)}
         ${row('Detoksikatsiya protokoli', d.detox_protocol)}
         ${row('Psixoterapiya', d.therapy_plan)}
         ${row('Maqsadlar', d.goals)}
         ${row('Ehtiyot choralari', d.precautions)}
       </div>
       ${meds.length ? `<div class="pr-section">
         <div class="pr-section-title">Tavsiya etilgan dorilar</div>
         <table class="pr-table">
           <tr><th>Dori</th><th>Doza</th><th>Yo'li</th><th>Tartib</th><th>Kun</th></tr>
           ${meds.map(m => `<tr><td>${esc(m.name)}</td><td>${esc(m.dosage)}</td>
             <td>${esc(m.route)}</td><td>${esc(m.frequency)}</td>
             <td>${esc(m.duration_days)}</td></tr>`).join('')}
         </table>
         <div class="pr-field" style="margin-top:4px;">
           Bu tavsiya. Hamshira bajaradigan retsept alohida beriladi.
         </div>
       </div>` : ''}` +
      signatures('Shifokor imzosi');
    window.print();
  }

  // -------------------------------------------------------------------------
  // Wiring
  // -------------------------------------------------------------------------

  function switchPane(name) {
    document.querySelectorAll('.cons-tab').forEach(t =>
      t.classList.toggle('active', t.dataset.pane === name));
    document.querySelectorAll('.cons-pane').forEach(p =>
      p.classList.toggle('active', p.id === 'pane-' + name));
  }

  document.addEventListener('DOMContentLoaded', async () => {
    try {
      const res = await fetch('/api/consultations/sections');
      if (!res.ok) {
        if (res.status !== 401) showToast('Anketa tuzilmasini yuklab bo’lmadi', 'danger');
        return;
      }
      state.meta = await res.json();
    } catch (e) {
      showToast('Serverga ulanib bo’lmadi', 'danger');
      return;
    }

    buildIntakeForm();
    buildPlanForm();

    document.querySelectorAll('.cons-tab').forEach(t =>
      t.addEventListener('click', () => switchPane(t.dataset.pane)));

    document.getElementById('btn-save-intake').addEventListener('click', saveIntake);
    document.getElementById('btn-save-plan').addEventListener('click', savePlan);
    document.getElementById('btn-print-intake').addEventListener('click', printIntake);
    document.getElementById('btn-print-plan').addEventListener('click', printPlan);

    document.getElementById('btn-clear-intake').addEventListener('click', async () => {
      const ok = await window.fmhConfirm({
        title: 'Anketani tozalash', message: 'Kiritilgan barcha ma’lumotlar o’chiriladi.',
        confirmText: 'Tozalash', cancelText: 'Bekor Qilish', type: 'warning' });
      if (ok) buildIntakeForm();
    });
    document.getElementById('btn-clear-plan').addEventListener('click', () => buildPlanForm());

    document.getElementById('only-mine').addEventListener('change', loadQueue);

    let searchTimer = null;
    document.getElementById('patient-search').addEventListener('input', e => {
      clearTimeout(searchTimer);
      const v = e.target.value.trim();
      searchTimer = setTimeout(() => searchPatients(v), 220);
    });

    fetch('/api/auth/session').then(r => r.json()).then(s => {
      if (s && s.user) state.doctorName = s.user.full_name || s.user.username || '';
    }).catch(() => {});

    loadQueue();
  });
})();
