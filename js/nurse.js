/**
 * FAYZ MEDICAL HOUSE — NURSE STATION
 *
 * The daily medication round. The schedule itself is derived server-side from
 * the standing prescriptions (see nursery.py), so this file only renders a day
 * and records outcomes against it — there is no second copy of the dosing
 * rules in the browser to drift out of step with the server's.
 */
(function () {
  'use strict';

  // Same delegation the other portal modules use: the shared toast in
  // fmh_dialogs.js announces via aria-live and keeps errors on screen.
  function showToast(message, type = 'success') {
    if (window.FMH_Toast) return window.FMH_Toast(message, type);
    console.warn('[nurse]', type, message);
  }

  const state = {
    date: todayISO(),
    round: null,
    nurseName: '',
    busy: false,
  };

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

  const STATE_TEXT = {
    given:        ['fa-circle-check',        'Berildi'],
    missed:       ['fa-circle-xmark',        "O'tkazib yuborildi"],
    refused:      ['fa-hand',                'Bemor rad etdi'],
    held:         ['fa-pause',               'To’xtatildi'],
    pending:      ['fa-clock',               'Kutilmoqda'],
    scheduled:    ['fa-calendar-day',        'Rejalashtirilgan'],
    not_recorded: ['fa-triangle-exclamation', 'Qayd etilmagan'],
  };

  const esc = s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  function hasAllergy(text) {
    if (!text) return false;
    const t = String(text).trim().toLowerCase();
    return t && t !== "yo'q" && t !== 'yoq' && t !== '-' &&
           t.indexOf('qayd etilmagan') === -1;
  }

  // -------------------------------------------------------------------------
  // Rendering
  // -------------------------------------------------------------------------

  function renderDose(dose, canRecord) {
    const [icon, label] = STATE_TEXT[dose.state] || ['fa-question', dose.state];
    const detail = [
      dose.dosage, dose.form, dose.route,
      `kun ${dose.day_of_course}/${dose.course_days}`
    ].filter(Boolean).map(esc).join('<span class="sep">·</span>');

    // A range order ("Kuniga 1-2 mahal") plans its lower bound; say so, or a
    // nurse cannot tell whether a further dose is permitted.
    const flexible = dose.max_per_day > 1 &&
      /[-–]/.test(String(dose.frequency || '')) ?
      `<div class="dose-note">Ruxsat etilgan: kuniga ${esc(dose.max_per_day)} martagacha</div>` : '';

    const recordedBy = dose.nurse_name
      ? `<div class="dose-note">${esc(dose.nurse_name)}${dose.administered_at ? ' · ' + esc(String(dose.administered_at).slice(11, 16)) : ''}${dose.notes ? ' · ' + esc(dose.notes) : ''}</div>`
      : (dose.notes ? `<div class="dose-note">${esc(dose.notes)}</div>` : '');

    const actions = canRecord ? `
      <div class="dose-actions">
        <button type="button" class="btn-dose btn-given"   data-rx="${esc(dose.prescription_id)}" data-slot="${dose.slot_index}" data-label="${esc(dose.slot_label)}" data-status="given">Berildi</button>
        <button type="button" class="btn-dose btn-refused" data-rx="${esc(dose.prescription_id)}" data-slot="${dose.slot_index}" data-label="${esc(dose.slot_label)}" data-status="refused">Rad etdi</button>
        <button type="button" class="btn-dose btn-missed"  data-rx="${esc(dose.prescription_id)}" data-slot="${dose.slot_index}" data-label="${esc(dose.slot_label)}" data-status="missed">O'tkazildi</button>
      </div>` : '';

    return `
      <div class="dose-row">
        <div class="dose-slot"><i class="fas fa-hourglass-half"></i>${esc(dose.slot_label)}</div>
        <div class="dose-med">
          <div class="dose-med-name">${esc(dose.medication_name)}</div>
          <div class="dose-med-detail">${detail}</div>
          ${flexible}${recordedBy}
        </div>
        <div class="dose-state state-${esc(dose.state)}">
          <i class="fas ${icon}"></i>${esc(label)}
        </div>
        ${actions}
      </div>`;
  }

  function renderPrn(order, canRecord) {
    const given = order.given_today || [];
    const detail = [order.dosage, order.form, order.route]
      .filter(Boolean).map(esc).join('<span class="sep">·</span>');
    const log = given.length
      ? given.map(g => `${esc(g.nurse_name || '—')}${g.administered_at ? ' · ' + esc(String(g.administered_at).slice(11, 16)) : ''}`).join('; ')
      : 'bugun berilmagan';

    return `
      <div class="prn-row">
        <div class="dose-med">
          <div class="dose-med-name">${esc(order.medication_name)}</div>
          <div class="dose-med-detail">${detail}<span class="sep">·</span>${esc(order.frequency)}</div>
          ${order.instructions ? `<div class="dose-note">${esc(order.instructions)}</div>` : ''}
        </div>
        <div class="prn-count">${esc(log)}</div>
        ${canRecord ? `
        <div class="dose-actions">
          <button type="button" class="btn-dose btn-given" data-rx="${esc(order.prescription_id)}" data-slot="" data-label="Zaruratga ko'ra" data-status="given">
            <i class="fas fa-plus"></i> Berildi
          </button>
        </div>` : ''}
      </div>`;
  }

  function renderRound(round) {
    const host = document.getElementById('round-container');
    const empty = document.getElementById('round-empty');

    if (!round.patients.length) {
      host.innerHTML = '';
      empty.style.display = '';
      return;
    }
    empty.style.display = 'none';

    // A dose cannot be marked given before it is due, so a future sheet is
    // read-only. Past days stay writable: charting is often caught up later.
    const canRecord = !round.is_future;

    host.innerHTML = round.patients.map(p => {
      const doneCount = p.doses.filter(d => d.state === 'given').length;
      const allergy = hasAllergy(p.medical_allergies)
        ? `<div class="patient-allergy" title="Dori allergiyasi">
             <i class="fas fa-triangle-exclamation"></i>${esc(p.medical_allergies)}
           </div>` : '';

      return `
        <article class="patient-card">
          <header class="patient-head">
            <div class="patient-bed">
              ${esc(p.bed_code)}<small>${esc(p.room_number)}-XONA</small>
            </div>
            <div class="patient-ident">
              <div class="patient-name">${esc(p.patient_name)}</div>
              <div class="patient-code">${esc(p.patient_code)}</div>
            </div>
            ${allergy}
            <div class="patient-progress">${doneCount} / ${p.doses.length} berildi</div>
          </header>
          <div class="dose-list">
            ${p.doses.map(d => renderDose(d, canRecord)).join('')}
          </div>
          ${p.as_needed.length ? `
            <div class="prn-block">
              <div class="prn-title">Zaruratga ko'ra (rejada emas)</div>
              ${p.as_needed.map(o => renderPrn(o, canRecord)).join('')}
            </div>` : ''}
        </article>`;
    }).join('');
  }

  function renderTotals(t) {
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    set('chip-planned', t.planned || 0);
    set('chip-given', t.given || 0);
    set('chip-pending', (t.pending || 0) + (t.scheduled || 0));
    set('chip-problem', (t.missed || 0) + (t.refused || 0) + (t.held || 0) + (t.not_recorded || 0));
    set('chip-prn', t.as_needed_orders || 0);
  }

  function renderDateLabel(round) {
    const el = document.getElementById('date-label');
    el.className = 'nurse-date-label';
    let text = humanDate(round.date);
    if (round.is_past) { text += ' — o’tgan kun'; el.classList.add('is-past'); }
    else if (round.is_future) { text += ' — kelajak (faqat ko’rish)'; el.classList.add('is-future'); }
    else { text += ' — bugun'; }
    el.textContent = text;
  }

  // -------------------------------------------------------------------------
  // Data
  // -------------------------------------------------------------------------

  async function load() {
    if (state.busy) return;
    state.busy = true;
    try {
      const res = await fetch('/api/nursery/round?date=' + encodeURIComponent(state.date));
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        // A 401 is handled globally by the session wrapper; anything else is
        // worth telling the nurse about rather than showing a blank ward.
        if (res.status !== 401) {
          showToast(body.error || 'Jadvalni yuklab bo’lmadi', 'danger');
        }
        return;
      }
      state.round = await res.json();
      document.getElementById('round-date').value = state.round.date;
      renderDateLabel(state.round);
      renderTotals(state.round.totals);
      renderRound(state.round);
    } catch (e) {
      showToast('Serverga ulanib bo’lmadi', 'danger');
    } finally {
      state.busy = false;
    }
  }

  async function record(rx, slot, status, label) {
    const payload = {
      prescription_id: rx,
      status: status,
      date: state.date,
      slot_label: label || null,
    };
    // An empty slot means an as-needed or additional dose; the server picks
    // the next free index so two nurses cannot collide on one.
    if (slot !== '' && slot != null) payload.slot_index = Number(slot);

    // Anything other than giving the dose as ordered is a deviation, so it is
    // confirmed and carries a reason.
    if (status !== 'given') {
      const reason = await promptReason(status);
      if (reason === null) return;
      payload.notes = reason || null;
    }

    try {
      const res = await fetch('/api/nursery/administer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (res.status !== 401) showToast(body.error || 'Qayd etilmadi', 'danger');
        return;
      }
      showToast(status === 'given' ? '✓ Doza qayd etildi' : 'Qayd etildi', 'success');
      load();
    } catch (e) {
      showToast('Serverga ulanib bo’lmadi', 'danger');
    }
  }

  function promptReason(status) {
    const titles = {
      missed: ["Dozani o'tkazib yuborish", "Nima uchun berilmadi?"],
      refused: ['Bemor rad etdi', 'Sababi (ixtiyoriy)'],
      held: ["Dozani to'xtatish", 'Sababi (ixtiyoriy)'],
    };
    const [title, ask] = titles[status] || ['Tasdiqlash', 'Izoh'];
    return new Promise(resolve => {
      window.FMH_ConfirmDialog({
        title: title,
        message: `${ask}<br><input id="fmh-dose-reason" type="text" ` +
                 `style="width:100%;margin-top:9px;padding:9px 11px;border-radius:8px;` +
                 `border:1px solid var(--border-color,rgba(255,255,255,0.15));` +
                 `background:var(--bg-input,#060e1f);color:var(--text-primary,#f8fafc);` +
                 `font-family:inherit;font-size:0.88rem;" placeholder="Izoh...">`,
        confirmText: 'Qayd Etish',
        cancelText: 'Bekor Qilish',
        type: 'warning',
        onConfirm: () => {
          const el = document.getElementById('fmh-dose-reason');
          resolve(el ? el.value.trim() : '');
        },
        onCancel: () => resolve(null),
      });
    });
  }

  // -------------------------------------------------------------------------
  // Wiring
  // -------------------------------------------------------------------------

  function go(date) {
    state.date = date;
    load();
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('round-date').value = state.date;

    document.getElementById('btn-prev-day')
      .addEventListener('click', () => go(shiftDate(state.date, -1)));
    document.getElementById('btn-next-day')
      .addEventListener('click', () => go(shiftDate(state.date, 1)));
    document.getElementById('btn-today')
      .addEventListener('click', () => go(todayISO()));
    document.getElementById('round-date')
      .addEventListener('change', e => { if (e.target.value) go(e.target.value); });

    // Dose buttons are delegated: the list is re-rendered on every change.
    document.getElementById('round-container').addEventListener('click', e => {
      const btn = e.target.closest('.btn-dose');
      if (!btn) return;
      record(btn.dataset.rx, btn.dataset.slot, btn.dataset.status, btn.dataset.label);
    });

    document.getElementById('btn-print-round').addEventListener('click', () => {
      const stamp = new Date();
      const p = n => String(n).padStart(2, '0');
      document.getElementById('print-date').textContent = humanDate(state.date);
      document.getElementById('print-nurse').textContent = state.nurseName || '—';
      document.getElementById('print-stamp').textContent =
        `${p(stamp.getDate())}.${p(stamp.getMonth() + 1)}.${stamp.getFullYear()} ` +
        `${p(stamp.getHours())}:${p(stamp.getMinutes())}`;
      window.print();
    });

    // Name the nurse on the printed sheet.
    fetch('/api/auth/session').then(r => r.json()).then(s => {
      if (s && s.user) state.nurseName = s.user.full_name || s.user.username || '';
    }).catch(() => {});

    load();
  });
})();
