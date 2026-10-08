/**
 * FAYZ MEDICAL HOUSE — TREATMENT PLAN VIEW (read-only)
 *
 * The doctor writes a treatment plan on the consultation page and it is
 * saved, but the two pages that carry it out — the nurse station and the
 * ward round — had no way to see it, so the plan lived only in the doctor's
 * head and on paper. This shows the patient's current plan, read-only, from
 * the same GET endpoints the consultation page uses. Nothing here writes.
 *
 * Usage: window.FMH_PlanView.show(patientId, patientName)
 */
(function () {
  'use strict';

  // Same labels as js/consultation.js, so a plan reads the same everywhere.
  const PLAN_LABEL = {
    outpatient: 'Ambulator', detox: 'Detoksikatsiya', inpatient: 'Statsionar',
    rehab: 'Reabilitatsiya', referral: 'Boshqa muassasaga yo’naltirish',
  };
  const STATUS_LABEL = {
    active: 'Amaldagi', superseded: 'Almashtirilgan',
    completed: 'Tugatilgan', draft: 'Qoralama',
  };

  function esc(v) {
    return String(v === null || v === undefined ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function humanDate(iso) {
    if (!iso) return '';
    const s = String(iso).slice(0, 10);
    const [y, m, d] = s.split('-');
    return (y && m && d) ? `${d}.${m}.${y}` : s;
  }

  let backdrop = null;
  let lastFocus = null;

  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); close(); }
  }

  function close() {
    if (!backdrop) return;
    document.removeEventListener('keydown', onKey);
    backdrop.remove();
    backdrop = null;
    if (lastFocus && typeof lastFocus.focus === 'function') {
      try { lastFocus.focus(); } catch (e) { /* element gone after re-render */ }
    }
  }

  function open(title) {
    close();
    lastFocus = document.activeElement;
    backdrop = document.createElement('div');
    backdrop.className = 'plan-view-backdrop';
    backdrop.innerHTML = `
      <div class="plan-view-card" role="dialog" aria-modal="true" aria-labelledby="plan-view-title">
        <header class="plan-view-head">
          <div class="plan-view-title" id="plan-view-title">
            <i class="fas fa-clipboard-list"></i> ${esc(title)}
          </div>
          <button type="button" class="plan-view-close" aria-label="Yopish">&times;</button>
        </header>
        <div class="plan-view-body">
          <div class="plan-view-empty"><i class="fas fa-spinner fa-spin"></i> Yuklanmoqda...</div>
        </div>
      </div>`;
    backdrop.addEventListener('click', e => { if (e.target === backdrop) close(); });
    backdrop.querySelector('.plan-view-close').addEventListener('click', close);
    document.addEventListener('keydown', onKey);
    document.body.appendChild(backdrop);
    backdrop.querySelector('.plan-view-close').focus();
  }

  function setBody(html) {
    if (!backdrop) return;
    backdrop.querySelector('.plan-view-body').innerHTML = html;
  }

  function field(label, value) {
    if (value === null || value === undefined || String(value).trim() === '') return '';
    return `<div class="plan-view-field">
      <div class="plan-view-label">${esc(label)}</div>
      <div class="plan-view-value">${esc(value)}</div>
    </div>`;
  }

  function renderPlan(plan) {
    const meds = Array.isArray(plan.medication_plan) ? plan.medication_plan : [];
    const meta = [
      PLAN_LABEL[plan.plan_type] || plan.plan_type,
      STATUS_LABEL[plan.status] || plan.status,
      plan.plan_date ? humanDate(plan.plan_date) : '',
      plan.doctor_name ? plan.doctor_name : '',
    ].filter(Boolean).map(esc).join(' · ');

    return `
      <div class="plan-view-meta">${meta}</div>
      ${plan.status !== 'active' ? `<div class="plan-view-note">
        Bu bemorda amaldagi reja yo'q; oxirgi saqlangan reja ko'rsatilmoqda.</div>` : ''}
      ${field('Davomiylik', plan.duration_days ? plan.duration_days + ' kun' : '')}
      ${field("Qayta ko'rik", humanDate(plan.review_date))}
      ${field('Darhol bajarilishi kerak', plan.immediate_actions)}
      ${field('Detoksikatsiya protokoli', plan.detox_protocol)}
      ${field('Psixoterapiya', plan.therapy_plan)}
      ${field('Maqsadlar', plan.goals)}
      ${field('Ehtiyot choralari', plan.precautions)}
      ${meds.length ? `
        <div class="plan-view-label" style="margin-top:12px;">Tavsiya etilgan dorilar</div>
        <div class="plan-view-table-wrap">
          <table class="plan-view-table">
            <thead><tr><th>Dori</th><th>Doza</th><th>Yo'li</th><th>Tartib</th><th>Kun</th></tr></thead>
            <tbody>
              ${meds.map(m => `<tr><td>${esc(m.name)}</td><td>${esc(m.dosage)}</td>
                <td>${esc(m.route)}</td><td>${esc(m.frequency)}</td>
                <td>${esc(m.duration_days)}</td></tr>`).join('')}
            </tbody>
          </table>
        </div>
        <div class="plan-view-note">Bu tavsiya. Bajariladigan dorilar — shifokor retseptidagilar.</div>` : ''}`;
  }

  async function readJson(url) {
    const res = await fetch(url);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(body.error || `Xatolik (${res.status})`);
      err.status = res.status;
      throw err;
    }
    return body;
  }

  async function show(patientId, patientName) {
    if (!patientId) return;
    open(`Davolash rejasi — ${patientName || ''}`.trim());
    try {
      const list = await readJson('/api/treatment-plans/patient/' + encodeURIComponent(patientId));
      const plans = Array.isArray(list) ? list : [];
      // The live instruction is the active plan; saving a new one supersedes
      // the old, so there is at most one. Without one, show the latest.
      const pick = plans.find(p => p.status === 'active') || plans[0];
      if (!pick) {
        setBody('<div class="plan-view-empty">Bu bemor uchun davolash rejasi kiritilmagan.</div>');
        return;
      }
      const plan = await readJson('/api/treatment-plans/' + encodeURIComponent(pick.id));
      setBody(renderPlan(plan));
    } catch (e) {
      if (e.status === 401) { close(); return; }
      setBody(`<div class="plan-view-empty">${esc(e.message || "Rejani yuklab bo'lmadi")}</div>`);
    }
  }

  window.FMH_PlanView = { show, close };
})();
