/**
 * Fayz Medical House — HR & Inson Resurslari Boshqaruvi Moduli (HR Management JS)
 * Version: 2.3.0 (Single Whole-Building 24h Nurse & Next-Gen Scheduling Engine)
 * Features:
 * 1. Duty tariffs (doctor night, nurse 24h, sanitar 24h) come from the
 *    server price list (/api/duty-schedule, /api/hr/data), never from this file.
 * 2. 1-Click Brigade Team Builder (1/3 Rejimi - 1 sutka ish, 3 sutka dam; 1/2 Rejimi)
 * 3. Rapid Stamp & Paint Mode (Tezkor Bo'yash Rejimi)
 * 4. 3-in-1 View Switcher: 7-Day Monthly Calendar Grid, Staff Gantt Matrix Timeline, Detailed Table
 * 5. 1-Click Shift Swapper & Telegram/WhatsApp Duty Roster Generator
 * 6. Live Payroll Engine & Official Printable Pay Slips
 */



(function () {
  'use strict';

  const STORAGE_KEY = 'FMH_HR_DATABASE_V4';

  // Duty tariffs used to be typed here (and again in a dozen labels), so a
  // price-list change left HR showing and paying the old rates. They now come
  // from the server price list; FMH_Pricing is only the fallback.
  const DUTY_TARIFFS = {};

  const DEFAULT_BRIGADES = [];

  const UZ_MONTHS = ['Yanvar', 'Fevral', 'Mart', 'Aprel', 'May', 'Iyun', 'Iyul', 'Avgust', 'Sentabr', 'Oktabr', 'Noyabr', 'Dekabr'];
  const UZ_WEEKDAYS = ['Yakshanba', 'Dushanba', 'Seshanba', 'Chorshanba', 'Payshanba', 'Juma', 'Shanba'];
  const UZ_WEEKDAYS_SHORT = ['Yak', 'Dush', 'Sesh', 'Chor', 'Pay', 'Jum', 'Shan'];
  const EMPTY_SLOT = '—';
  const pad2 = n => String(n).padStart(2, '0');

  // Formatters
  const formatUZS = (val) => {
    if (val === null || val === undefined || isNaN(val)) return '0 so\'m';
    return Math.round(val).toLocaleString('uz-UZ') + ' so\'m';
  };

  // Names and ids come from the server (staff table, saved roster) and are
  // put into innerHTML; escape them so a stray < or " cannot break the page.
  const esc = (v) => String(v === null || v === undefined ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  function tariff(key) {
    const n = Number(State.dutyTariffs && State.dutyTariffs[key]);
    if (Number.isFinite(n) && n > 0) return n;
    if (window.FMH_Pricing && typeof window.FMH_Pricing.dutyTariff === 'function') {
      const p = Number(window.FMH_Pricing.dutyTariff(key));
      if (Number.isFinite(p) && p > 0) return p;
    }
    return 0;
  }

  // Short form for the small calendar chips ("350k").
  function tariffShort(key) {
    const n = tariff(key);
    return n ? `${Math.round(n / 1000)}k` : '—';
  }

  // The roster month (the current calendar month), 'YYYY-MM'.
  function monthKey() {
    return `${State.currentYear}-${pad2(State.currentMonth)}`;
  }

  function monthLabel(key) {
    const parts = String(key || monthKey()).split('-');
    const m = parseInt(parts[1], 10);
    return `${UZ_MONTHS[m - 1] || ''} ${parts[0]}`;
  }

  function dayLabel(day) {
    return `${day}-${UZ_MONTHS[State.currentMonth - 1]}`;
  }

  const formatDate = (dateStr) => {
    if (!dateStr) return '—';
    try {
      const parts = dateStr.split('-');
      if (parts.length === 3) return `${parts[2]}.${parts[1]}.${parts[0]}`;
      return dateStr;
    } catch (e) {
      return dateStr;
    }
  };

  // Today's date in clinic (browser) time, YYYY-MM-DD.
  function todayIso() {
    return new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  }

  // Main HR State
  const State = {
    facility: {},
    staff: [],
    dutyTariffs: Object.assign({}, DUTY_TARIFFS),
    brigades: DEFAULT_BRIGADES,
    monthlySchedule: [],
    rosterLoadError: null,
    payroll: null,
    payrollError: null,
    payrollSeq: 0,
    attendance: [],
    // The day the attendance sheet shows and records (YYYY-MM-DD, clinic time).
    attendanceDate: todayIso(),
    rosterSeq: 0,
    activeTab: 'staff',
    staffFilterDept: 'all',
    staffFilterStatus: 'all',
    searchQuery: '',
    selectedStaffId: null,
    selectedSlot: null,
    
    // Next-Gen Scheduling State
    dutyViewMode: 'grid', // 'grid' (7-day calendar) | 'gantt' (staff matrix) | 'table' (list)
    paintModeActive: false,
    activePaintStamp: null,
    activeAlgorithm: 'brigade_1_3',
    currentMonth: new Date().getMonth() + 1,
    currentYear: new Date().getFullYear()
  };

  // Delegates to the shared toast in js/fmh_dialogs.js: that one announces
  // messages via aria-live, keeps errors on screen long enough to read,
  // stacks instead of erasing an unread message, and can be dismissed.
  function showToast(message, type = 'info') {
    return window.FMH_Toast(message, type);
  }

  async function initDatabase() {
    // Dynamic date presets setup
    const now = new Date();
    const btnToday = document.getElementById('hr-btn-today');
    if (btnToday) {
      btnToday.textContent = `Bugun (${now.toLocaleDateString('uz-UZ', { day: 'numeric', month: 'long' })})`;
    }
    const btnMonth = document.getElementById('hr-btn-month');
    if (btnMonth) {
      btnMonth.textContent = now.toLocaleDateString('uz-UZ', { month: 'long', year: 'numeric' });
    }
    const inpStart = document.getElementById('date-filter-start');
    const inpEnd = document.getElementById('date-filter-end');
    const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
    const lastDay = new Date(now.getFullYear(), now.getMonth() + 1, 0);
    const pad = n => String(n).padStart(2, '0');
    if (inpStart) inpStart.value = `${firstDay.getFullYear()}-${pad(firstDay.getMonth() + 1)}-${pad(firstDay.getDate())}`;
    if (inpEnd) inpEnd.value = `${lastDay.getFullYear()}-${pad(lastDay.getMonth() + 1)}-${pad(lastDay.getDate())}`;

    let hrLoaded = false;
    try {
      let res = await fetch('/api/hr/data').catch(() => null);
      if (!res || !res.ok) {
        res = await fetch('data/hr_db.json').catch(() => null);
      }
      if (res && res.ok) {
        const data = await res.json();
        populateState(data);
        saveToLocalStorage();
        hrLoaded = true;
      }
    } catch (e) {
      console.warn('API and static fetch failed, checking local storage...', e);
    }

    if (!hrLoaded) {
      const localData = localStorage.getItem(STORAGE_KEY);
      if (localData) {
        try {
          // Attendance is the server's (POST /api/hr/attendance); an old
          // browser copy must never be shown as if it were recorded.
          const cached = JSON.parse(localData);
          delete cached.attendance_records;
          populateState(cached);
        } catch (e) {
          console.warn('Failed to parse local HR DB:', e);
        }
      }
    }

    // The roster always comes from the server, whatever happened above.
    await loadDutyRoster();
    renderAll();
    loadPayroll();
  }

  function populateState(data) {
    State.facility = data.facility_info || {};
    State.staff = data.staff || [];
    if (data.duty_tariffs && typeof data.duty_tariffs === 'object') {
      State.dutyTariffs = Object.assign({}, State.dutyTariffs, data.duty_tariffs);
    }
    // An empty brigades list used to throw here (brigades[0] undefined), which
    // dropped the whole server load and fell back to the browser cache.
    State.brigades = (Array.isArray(data.brigades) && data.brigades[0] && data.brigades[0].nurse_id) ? data.brigades : DEFAULT_BRIGADES;
    // monthly_duty_schedule is deliberately ignored: the roster lives only
    // in /api/duty-schedule. A browser copy used to override HR's saved
    // edits and feed payroll with an invented rota.
    State.attendance = data.attendance_records || [];
  }

  // Offline cache of the staff list only (used when /api/hr/data is
  // unreachable). Roster, tariffs, payroll and attendance are never cached
  // here: attendance used to live only in this cache, so it never reached
  // the database and was lost on another computer.
  function saveToLocalStorage() {
    const payload = {
      facility_info: State.facility,
      brigades: State.brigades,
      staff: State.staff
    };
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(payload)); } catch (e) { /* storage full or blocked */ }
  }

  // ==========================================================================
  // SERVER DUTY ROSTER (/api/duty-schedule) <-> HR DAY OBJECTS
  // ==========================================================================

  // An empty slot is shown as a dash; the server stores an empty string.
  function slotName(name) {
    const s = name === null || name === undefined ? '' : String(name).trim();
    return (!s || s.charAt(0) === '—') ? '' : s;
  }

  function parseDay(dateStr) {
    const p = String(dateStr).split('-').map(Number);
    return new Date(p[0], p[1] - 1, p[2]);
  }

  function dailyDutyCost(d) {
    return (d.doctor_night_id ? tariff('doctor_night') : 0) +
           ((d.nurse_f1_id || d.nurse_id) ? tariff('nurse_24h') : 0) +
           (d.nurse_f2_id ? tariff('nurse_24h') : 0) +
           (d.sanitar_id ? tariff('sanitar_24h') : 0);
  }

  // Server day -> HR day. The server object is kept in _server so fields HR
  // does not edit (sanitar_secondary, notes from the Duty page) survive a save:
  // the server replaces a stored day entirely with what we send.
  function fromServerDay(sd) {
    const dt = parseDay(sd.date);
    const nm = (v) => slotName(v) || EMPTY_SLOT;
    const nurse1Id = sd.nurse_primary_id || '';
    const d = {
      day: dt.getDate(),
      date: sd.date,
      day_name: UZ_WEEKDAYS_SHORT[dt.getDay()],
      is_weekend: dt.getDay() === 0 || dt.getDay() === 6,
      doctor_night_id: sd.doctor_night_id || '',
      doctor_night_name: nm(sd.doctor_night),
      nurse_id: nurse1Id,
      nurse_name: nm(sd.nurse_primary),
      nurse_f1_id: nurse1Id,
      nurse_f1_name: nm(sd.nurse_primary),
      nurse_f2_id: sd.nurse_secondary_id || '',
      nurse_f2_name: nm(sd.nurse_secondary),
      sanitar_id: sd.sanitar_primary_id || '',
      sanitar_name: nm(sd.sanitar_primary),
      oncall_doc_id: sd.doctor_primary_id || '',
      oncall_doc_name: nm(sd.doctor_primary),
      suggested: false,
      _server: sd
    };
    d.daily_duty_cost = dailyDutyCost(d);
    return d;
  }

  // HR day -> server day. Only server-shaped fields go out; HR-only fields
  // (brigade_*, daily_duty_cost, suggested, nurse_f1/f2 aliases) stay local.
  function toServerDay(h) {
    const out = Object.assign({}, h._server || {});
    const dt = parseDay(h.date);
    const nurse1Id = h.nurse_f1_id || h.nurse_id || '';
    Object.assign(out, {
      date: h.date,
      day: dt.getDate(),
      month: dt.getMonth() + 1,
      year: dt.getFullYear(),
      weekday: UZ_WEEKDAYS[dt.getDay()],
      is_weekend: dt.getDay() === 0 || dt.getDay() === 6,
      doctor_night_id: h.doctor_night_id || '',
      doctor_night: slotName(h.doctor_night_name),
      doctor_primary_id: h.oncall_doc_id || '',
      doctor_primary: slotName(h.oncall_doc_name),
      nurse_primary_id: nurse1Id,
      nurse_primary: slotName(h.nurse_f1_id ? h.nurse_f1_name : h.nurse_name),
      nurse_secondary_id: h.nurse_f2_id || '',
      nurse_secondary: slotName(h.nurse_f2_name),
      sanitar_primary_id: h.sanitar_id || '',
      sanitar_primary: slotName(h.sanitar_name)
    });
    ['suggested', 'brigade_id', 'brigade_name', 'brigade_color', 'daily_duty_cost', 'day_name',
     'nurse_id', 'nurse_name', 'nurse_f1_id', 'nurse_f1_name', 'nurse_f2_id', 'nurse_f2_name',
     'sanitar_id', 'sanitar_name', 'oncall_doc_id', 'oncall_doc_name', 'doctor_night_name', '_server'
    ].forEach(k => { delete out[k]; });
    return out;
  }

  // One place that fills a slot, so the nurse aliases (nurse_id / nurse_f1_id)
  // cannot drift apart: the swap used to move only nurse_id, and the save
  // would then send the stale nurse_f1 value.
  function setSlot(d, slotType, id, name) {
    const sid = id || '';
    const sname = sid ? (name || EMPTY_SLOT) : EMPTY_SLOT;
    if (slotType === 'doctor_night') {
      d.doctor_night_id = sid; d.doctor_night_name = sname;
    } else if (slotType === 'nurse_f1' || slotType === 'nurse_24h' || slotType === 'nurse') {
      d.nurse_f1_id = sid; d.nurse_f1_name = sname;
      d.nurse_id = sid; d.nurse_name = sname;
    } else if (slotType === 'nurse_f2') {
      d.nurse_f2_id = sid; d.nurse_f2_name = sname;
    } else if (slotType === 'sanitar_24h' || slotType === 'sanitar') {
      d.sanitar_id = sid; d.sanitar_name = sname;
    } else if (slotType === 'oncall') {
      d.oncall_doc_id = sid; d.oncall_doc_name = sname;
    }
    d.daily_duty_cost = dailyDutyCost(d);
  }

  function snapshotDays(days) {
    return days.map(d => {
      const copy = JSON.parse(JSON.stringify(Object.assign({}, d, { _server: null })));
      copy._server = d._server || null;
      return copy;
    });
  }

  function restoreDays(snaps) {
    snaps.forEach(s => {
      const i = State.monthlySchedule.findIndex(d => d.date === s.date);
      if (i >= 0) State.monthlySchedule[i] = s;
    });
  }

  async function loadDutyRoster() {
    // Month arrows can be clicked faster than the server answers; only the
    // latest load may fill the roster, or an older month's answer would be
    // shown under the newer month's label.
    const seq = ++State.rosterSeq;
    let loadError = null;
    let data = null;
    try {
      const res = await fetch('/api/duty-schedule');
      if (res.ok) {
        data = await res.json();
      } else {
        const err = await res.json().catch(() => ({}));
        loadError = (err && err.error) || 'Navbatchilik jadvali serverdan yuklanmadi';
      }
    } catch (e) {
      loadError = 'Server bilan aloqa yo\'q — navbatchilik jadvali yuklanmadi';
    }
    if (seq !== State.rosterSeq) return false;
    State.rosterLoadError = loadError;

    // Without the server roster we cannot tell saved days from empty ones,
    // so show nothing rather than a suggestion that a save could write over
    // real saved days.
    if (!data) {
      State.monthlySchedule = [];
      recalculateStaffDutyCounts();
      return;
    }

    if (data.duty_tariffs && typeof data.duty_tariffs === 'object') {
      State.dutyTariffs = Object.assign({}, State.dutyTariffs, data.duty_tariffs);
    }
    State.staffPool = data.staff_pool || null;

    const prefix = monthKey() + '-';
    const savedByDate = {};
    (Array.isArray(data.shifts) ? data.shifts : []).forEach(sd => {
      if (sd && typeof sd.date === 'string' && sd.date.indexOf(prefix) === 0) savedByDate[sd.date] = sd;
    });

    // Saved days come from the server as-is; every other day of the month is
    // a suggestion (suggested: true) that is not paid until HR saves it.
    // The old ensureMonthlySchedule() regenerated the whole month on every
    // load, so HR's edits vanished on refresh.
    State.monthlySchedule = generateMonthlySchedule(State.activeAlgorithm).map(sg =>
      savedByDate[sg.date] ? fromServerDay(savedByDate[sg.date]) : sg
    );
    recalculateStaffDutyCounts();
    return true;
  }

  // ==========================================================================
  // ROSTER / PAYROLL MONTH (previous / next / current)
  // ==========================================================================
  // The roster and payroll tabs only ever showed the current month, so HR
  // could not look back at last month's pay or plan the next one.
  function isCurrentMonth() {
    const now = new Date();
    return State.currentYear === now.getFullYear() && State.currentMonth === now.getMonth() + 1;
  }

  async function setRosterMonth(year, month) {
    State.currentYear = year;
    State.currentMonth = month;
    // A stamp or picker opened on the old month must not write into the new one.
    State.selectedSlot = null;
    State.monthlySchedule = [];
    State.rosterLoading = true;
    // Drop the old month's pay and any payroll answer still on its way.
    State.payroll = null;
    State.payrollError = null;
    State.payrollSeq++;
    renderShiftRoster();
    renderPayrollTable();
    const loaded = await loadDutyRoster();
    if (loaded === false) return; // a newer month was picked meanwhile
    State.rosterLoading = false;
    renderAll();
    loadPayroll();
  }

  function changeRosterMonth(delta) {
    const d = new Date(State.currentYear, State.currentMonth - 1 + delta, 1);
    return setRosterMonth(d.getFullYear(), d.getMonth() + 1);
  }

  function goToCurrentMonth() {
    const now = new Date();
    return setRosterMonth(now.getFullYear(), now.getMonth() + 1);
  }

  function monthNavHtml() {
    return `
      <div class="hr-month-nav" style="display: inline-flex; align-items: center; gap: 0.4rem; flex-wrap: wrap;">
        <button type="button" class="btn-portal btn-outline-portal" style="padding: 5px 10px;" onclick="window.FMH_HR.changeRosterMonth(-1)" title="Oldingi oy" aria-label="Oldingi oy">
          <i class="fas fa-chevron-left"></i>
        </button>
        <span style="font-weight: 700; color: var(--text-primary); min-width: 8.5rem; text-align: center;">${esc(monthLabel())}</span>
        <button type="button" class="btn-portal btn-outline-portal" style="padding: 5px 10px;" onclick="window.FMH_HR.changeRosterMonth(1)" title="Keyingi oy" aria-label="Keyingi oy">
          <i class="fas fa-chevron-right"></i>
        </button>
        ${isCurrentMonth() ? '' : `
        <button type="button" class="btn-portal btn-outline-portal" style="padding: 5px 10px;" onclick="window.FMH_HR.goToCurrentMonth()">
          <i class="fas fa-calendar-day"></i> Bugun
        </button>`}
      </div>
    `;
  }

  // People who may take a duty slot: active staff of that role. Sanitarkas
  // are real staff with role 'sanitar' now; the old filter on 'support'
  // matched nobody.
  function dutyPool(kind) {
    const roles = kind === 'doctor' ? ['doctor', 'chief_doctor'] : (kind === 'nurse' ? ['nurse'] : ['sanitar']);
    const fromStaff = (State.staff || []).filter(s => roles.indexOf(s.role) >= 0 && s.status !== 'inactive');
    if (fromStaff.length || !State.staffPool) return fromStaff;
    const key = kind === 'doctor' ? 'doctors' : (kind === 'nurse' ? 'nurses' : 'sanitarkas');
    return (State.staffPool[key] || []).map(p => ({ id: p.id, full_name: p.name, role: roles[0] }));
  }

  function findStaff(id) {
    if (!id) return null;
    return (State.staff || []).find(s => s.id === id) ||
      ['doctor', 'nurse', 'sanitar'].map(dutyPool).reduce((a, b) => a.concat(b), []).find(s => s.id === id) || null;
  }

  // POST only the changed days (full server-shaped objects). On refusal the
  // local edit is rolled back and the server's message shown; a success toast
  // is never shown for a save the server refused.
  async function saveRosterDays(days, snapshots, okMessage) {
    if (State.rosterLoadError) {
      restoreDays(snapshots);
      afterRosterChange();
      showToast('Jadval serverdan yuklanmagan — saqlab bo\'lmaydi. Sahifani yangilang.', 'danger');
      return false;
    }
    // One save at a time. With two in flight, a late refusal of the first
    // restored its snapshot over the second edit, so the screen showed a day
    // the server no longer held.
    if (State.rosterSaving) {
      restoreDays(snapshots);
      afterRosterChange();
      showToast('Oldingi o\'zgarish saqlanmoqda, biroz kuting.', 'info');
      return false;
    }
    const shifts = days.map(toServerDay);
    let res = null;
    State.rosterSaving = true;
    try {
      res = await fetch('/api/duty-schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shifts })
      });
    } catch (e) {
      res = null;
    }
    if (!res || !res.ok) {
      let msg = res ? 'Navbatchilik jadvali saqlanmadi' : 'Server bilan aloqa yo\'q — jadval saqlanmadi';
      if (res) {
        try {
          const err = await res.json();
          if (err && err.error) msg = err.error;
        } catch (e) { /* non-JSON error body */ }
      }
      State.rosterSaving = false;
      restoreDays(snapshots);
      afterRosterChange();
      showToast(msg, 'danger');
      return false;
    }
    State.rosterSaving = false;
    shifts.forEach(sd => {
      const live = State.monthlySchedule.find(d => d.date === sd.date);
      if (live) {
        live._server = sd;
        live.suggested = false;
      }
    });
    afterRosterChange();
    loadPayroll();
    if (okMessage) showToast(okMessage, 'success');
    return true;
  }

  function afterRosterChange() {
    recalculateStaffDutyCounts();
    renderShiftRoster();
    renderStaffDirectory();
    updateKPIs();
  }

  // "Yangi Smena Qo'shish" in hr.html called a function that did not exist.
  // A shift is a slot on a day, so point HR at the calendar where each slot
  // opens the staff picker.
  function openAssignShiftModal() {
    switchTab('shifts');
    showToast("Smena qo'shish: kalendarda kunni va lavozimni (shifokor, hamshira, sanitarka) bosing.", 'info');
  }

  async function saveSuggestedRoster() {
    const days = State.monthlySchedule.filter(d => d.suggested);
    if (!days.length) {
      showToast('Saqlanmagan taklif kunlari yo\'q.', 'info');
      return;
    }
    await saveRosterDays(days, snapshotDays(days), `${monthLabel()} navbatchilik jadvali saqlandi (${days.length} kun).`);
  }

  // ==========================================================================
  // BRIGADE & SCHEDULING ENGINES (SINGLE WHOLE-BUILDING NURSE)
  // ==========================================================================

  /**
   * Builds a suggested rota for the roster month (every day suggested: true).
   * It does not touch State; callers decide which days to use.
   */
  function generateMonthlySchedule(algoType = 'brigade_1_3') {
    const curYear = State.currentYear;
    const curMonth = State.currentMonth - 1;
    const daysInMonth = new Date(curYear, curMonth + 1, 0).getDate();
    const schedule = [];
    const daysOfWeekUz = UZ_WEEKDAYS_SHORT;
    const pad = pad2;

    const doctors = dutyPool('doctor');
    const nurses = dutyPool('nurse');
    const sanitars = dutyPool('sanitar');

    const brigadesCount = algoType === 'brigade_1_2' ? 3 : 4;
    const activeBrigades = (State.brigades && State.brigades.length > 0) ? State.brigades.slice(0, brigadesCount) : [];

    for (let day = 1; day <= daysInMonth; day++) {
      const dateStr = `${curYear}-${pad(curMonth + 1)}-${pad(day)}`;
      const dayDate = new Date(curYear, curMonth, day);
      const dayName = daysOfWeekUz[dayDate.getDay()];
      const isWeekend = dayDate.getDay() === 0 || dayDate.getDay() === 6;

      let currentBrigade = null;
      if (activeBrigades.length > 0) {
        currentBrigade = activeBrigades[(day - 1) % activeBrigades.length];
      }

      let doc = null;
      let nurseF1 = null;
      let nurseF2 = null;
      let san = null;
      let onCall = null;

      if (currentBrigade) {
        doc = findStaff(currentBrigade.doctor_id) || doctors[0] || null;
        nurseF1 = findStaff(currentBrigade.nurse_f1_id || currentBrigade.nurse_id) || nurses[0] || null;
        nurseF2 = findStaff(currentBrigade.nurse_f2_id) || (nurses.length > 1 ? nurses[1] : null);
        san = findStaff(currentBrigade.sanitar_id) || sanitars[0] || null;
      } else {
        doc = doctors.length > 0 ? (doctors[(day - 1) % doctors.length] || doctors[0]) : null;
        nurseF1 = nurses.length > 0 ? (nurses[(day - 1) % nurses.length] || nurses[0]) : null;
        nurseF2 = nurses.length > 1 ? (nurses[((day - 1) + 1) % nurses.length] || nurses[1]) : null;
        san = sanitars.length > 0 ? (sanitars[(day - 1) % sanitars.length] || sanitars[0]) : null;
      }

      if (doctors.length > 1 && doc) {
        onCall = doctors.find(d => d.id !== doc.id) || doctors[0];
      } else if (doctors.length === 1) {
        onCall = doctors[0];
      }

      const dailyCost = (doc ? tariff('doctor_night') : 0) +
                        (nurseF1 ? tariff('nurse_24h') : 0) +
                        (nurseF2 ? tariff('nurse_24h') : 0) +
                        (san ? tariff('sanitar_24h') : 0);

      schedule.push({
        day,
        date: dateStr,
        day_name: dayName,
        is_weekend: isWeekend,
        brigade_id: currentBrigade ? currentBrigade.id : `BRG-${((day - 1) % 4) + 1}`,
        brigade_name: currentBrigade ? currentBrigade.name : `${((day - 1) % 4) + 1}-Smena`,
        brigade_color: currentBrigade ? currentBrigade.color : '#6366f1',
        doctor_night_id: doc ? doc.id : null,
        doctor_night_name: doc ? doc.full_name : '— Belgilanmagan —',
        nurse_id: nurseF1 ? nurseF1.id : null,
        nurse_name: nurseF1 ? nurseF1.full_name : '— Belgilanmagan —',
        nurse_f1_id: nurseF1 ? nurseF1.id : null,
        nurse_f1_name: nurseF1 ? nurseF1.full_name : '— Belgilanmagan —',
        nurse_f2_id: nurseF2 ? nurseF2.id : null,
        nurse_f2_name: nurseF2 ? nurseF2.full_name : '— Belgilanmagan —',
        sanitar_id: san ? san.id : null,
        sanitar_name: san ? san.full_name : '— Belgilanmagan —',
        oncall_doc_id: onCall ? onCall.id : null,
        oncall_doc_name: onCall ? onCall.full_name : '— Belgilanmagan —',
        daily_duty_cost: dailyCost,
        suggested: true,
        _server: null
      });
    }

    return schedule;
  }

  // Per-person counts shown on the roster, staff cards and picker. Only SAVED
  // days count: a suggestion is not paid until HR saves it, so counting it
  // here showed earnings that payroll would never pay.
  function recalculateStaffDutyCounts() {
    State.staff.forEach(s => {
      s.monthly_duty_count = 0;
      s.monthly_duty_earnings = 0;
    });

    const add = (id, key) => {
      if (!id) return;
      const st = State.staff.find(s => s.id === id);
      if (st) {
        st.monthly_duty_count = (st.monthly_duty_count || 0) + 1;
        st.monthly_duty_earnings = (st.monthly_duty_earnings || 0) + tariff(key);
      }
    };

    State.monthlySchedule.forEach(sch => {
      if (sch.suggested) return;
      add(sch.doctor_night_id, 'doctor_night');
      add(sch.nurse_f1_id || sch.nurse_id, 'nurse_24h');
      add(sch.nurse_f2_id, 'nurse_24h');
      add(sch.sanitar_id, 'sanitar_24h');
    });
  }

  // ==========================================================================
  // STAMP / PAINT MODE LOGIC
  // ==========================================================================

  function togglePaintMode() {
    State.paintModeActive = !State.paintModeActive;
    if (State.paintModeActive && !State.activePaintStamp) {
      const defaultDoc = State.staff.find(s => s.role === 'doctor');
      if (defaultDoc) setPaintStamp(defaultDoc.id, 'doctor_night');
    }
    renderShiftRoster();
    if (State.paintModeActive) {
      showToast('🖌️ Tezkor Bo\'yash (Stamp Mode) faollashdi! Kalendar katagiga bosib xodimni biriktiring.', 'info');
    } else {
      showToast('Bo\'yash rejimi o\'chirildi.', 'info');
    }
  }

  function setPaintStamp(staffId, roleType) {
    if (staffId === 'eraser') {
      State.activePaintStamp = { staffId: 'eraser', name: 'O\'chirgich (Eraser)', roleType: 'eraser', color: '#f43f5e' };
    } else {
      const staff = findStaff(staffId);
      if (!staff) return;
      State.activePaintStamp = {
        staffId: staff.id,
        name: staff.full_name,
        roleType: roleType || (staff.role === 'doctor' || staff.role === 'chief_doctor' ? 'doctor_night' : staff.role === 'nurse' ? 'nurse' : 'sanitar'),
        color: staff.avatar_color || '#4f46e5'
      };
    }
    renderShiftRoster();
    showToast(`Faol Shtamp: ${State.activePaintStamp.name}`, 'success');
  }

  function handleSlotClick(day, slotType) {
    if (State.paintModeActive && State.activePaintStamp) {
      const targetDay = State.monthlySchedule.find(s => s.day === day);
      if (!targetDay) return;
      const snaps = snapshotDays([targetDay]);

      if (State.activePaintStamp.staffId === 'eraser') {
        setSlot(targetDay, slotType, '', '');
      } else {
        setSlot(targetDay, slotType, State.activePaintStamp.staffId, State.activePaintStamp.name);
      }

      // Show the stamp at once, then save that one day; a refusal rolls it back.
      renderShiftRoster();
      saveRosterDays([targetDay], snaps, null);
    } else {
      openQuickPicker(day, slotType);
    }
  }

  // ==========================================================================
  // 3-IN-1 VIEW RENDERERS FOR SHIFT ROSTER
  // ==========================================================================

  function renderShiftRoster() {
    const container = document.getElementById('shifts-container');
    if (!container) return;

    let viewHtml = '';
    if (State.dutyViewMode === 'grid') {
      viewHtml = renderMonthlyCalendarGrid();
    } else if (State.dutyViewMode === 'gantt') {
      viewHtml = renderStaffGanttMatrix();
    } else {
      viewHtml = renderDutyTable();
    }

    container.innerHTML = `
      <div style="margin-bottom: 0.75rem;">${monthNavHtml()}</div>
      ${renderRosterStatusBanner()}

      <!-- Official Navbatchilik Tariffs Banner -->
      <div class="duty-tariff-grid">
        <div class="tariff-card tariff-doctor">
          <div>
            <div class="tariff-role"><i class="fas fa-user-md"></i> Shifokorlar (Doctors)</div>
            <div class="tariff-name">1 Tungi Navbatchilik (20:00 - 08:00)</div>
          </div>
          <div class="tariff-price">${formatUZS(tariff('doctor_night'))}</div>
        </div>

        <div class="tariff-card tariff-nurse">
          <div>
            <div class="tariff-role"><i class="fas fa-syringe"></i> Hamshira (Butun Bino — 1 & 2 Qavat)</div>
            <div class="tariff-name">24-Soatlik Navbatchilik (1 Sutka)</div>
          </div>
          <div class="tariff-price">${formatUZS(tariff('nurse_24h'))}</div>
        </div>

        <div class="tariff-card tariff-sanitar">
          <div>
            <div class="tariff-role"><i class="fas fa-broom"></i> Sanitarkalar (Sanitars)</div>
            <div class="tariff-name">24-Soatlik Navbatchilik (1 Sutka)</div>
          </div>
          <div class="tariff-price">${formatUZS(tariff('sanitar_24h'))}</div>
        </div>
      </div>

      <!-- View Controls & Quick Action Buttons Bar -->
      <div class="duty-view-controls-bar">
        <div class="duty-view-pills">
          <button class="duty-view-btn ${State.dutyViewMode === 'grid' ? 'active' : ''}" onclick="window.FMH_HR.setDutyViewMode('grid')">
            <i class="fas fa-calendar-alt"></i> 7-Kunlik Kalendar Grid
          </button>
          <button class="duty-view-btn ${State.dutyViewMode === 'gantt' ? 'active' : ''}" onclick="window.FMH_HR.setDutyViewMode('gantt')">
            <i class="fas fa-stream"></i> Xodimlar Gantt Matritsasi
          </button>
          <button class="duty-view-btn ${State.dutyViewMode === 'table' ? 'active' : ''}" onclick="window.FMH_HR.setDutyViewMode('table')">
            <i class="fas fa-list-alt"></i> Batafsil Jadval
          </button>
        </div>

        <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
          <button class="btn-portal ${State.paintModeActive ? 'btn-danger-portal' : 'btn-primary-portal'}" onclick="window.FMH_HR.togglePaintMode()">
            <i class="fas fa-paint-brush"></i> ${State.paintModeActive ? 'Bo\'yashni Yakunlash' : 'Tezkor Bo\'yash (Stamp Mode)'}
          </button>
          <button class="btn-portal btn-outline-portal" onclick="window.FMH_HR.openBrigadeModal()" style="border-color: rgba(99, 102, 241, 0.4); color: #818cf8;">
            <i class="fas fa-users"></i> Brigadalar & Qoliplar (1/3)
          </button>
          <button class="btn-portal btn-outline-portal" onclick="window.FMH_HR.openSwapModal()" style="border-color: rgba(245, 158, 11, 0.4); color: #fbbf24;">
            <i class="fas fa-random"></i> Smena Almashtirish
          </button>
          <button class="btn-portal btn-outline-portal" onclick="window.FMH_HR.openTelegramModal()" style="border-color: rgba(56, 189, 248, 0.4); color: #38bdf8;">
            <i class="fab fa-telegram-plane"></i> Telegram uchun Nusxa
          </button>
        </div>
      </div>

      <!-- Active Stamp / Paint Mode Selector Banner (if active) -->
      ${State.paintModeActive ? renderStampModeBanner() : ''}

      <!-- Main Rendered View (Grid, Gantt or Table) -->
      ${viewHtml}
    `;
  }

  // Tells HR which days are only a suggestion (not saved, not paid) and
  // offers one button to save them. Also reports a roster that failed to load.
  function renderRosterStatusBanner() {
    if (State.rosterLoading) {
      return `
        <div role="status" style="margin-bottom: 0.75rem; padding: 0.5rem 1rem; border-radius: var(--radius-md); border: 1px solid var(--border-subtle); color: var(--text-secondary); font-size: 0.8rem; font-weight: 600;">
          <i class="fas fa-spinner fa-spin"></i> ${esc(monthLabel())}: jadval yuklanmoqda...
        </div>
      `;
    }
    if (State.rosterLoadError) {
      return `
        <div role="alert" style="margin-bottom: 0.75rem; padding: 0.75rem 1rem; border-radius: var(--radius-md); border: 1px solid rgba(244, 63, 94, 0.45); background: rgba(244, 63, 94, 0.1); color: #fb7185; font-size: 0.85rem; font-weight: 600;">
          <i class="fas fa-exclamation-triangle"></i> ${esc(State.rosterLoadError)}. Jadvalni o'zgartirib bo'lmaydi — sahifani yangilang.
        </div>
      `;
    }
    const total = State.monthlySchedule.length;
    const suggested = State.monthlySchedule.filter(d => d.suggested).length;
    if (!suggested) {
      return `
        <div style="margin-bottom: 0.75rem; padding: 0.5rem 1rem; border-radius: var(--radius-md); border: 1px solid rgba(16, 185, 129, 0.35); background: rgba(16, 185, 129, 0.08); color: #34d399; font-size: 0.8rem; font-weight: 600;">
          <i class="fas fa-check-circle"></i> ${esc(monthLabel())}: jadval serverda saqlangan (${total} kun). Har bir o'zgarish darhol saqlanadi.
        </div>
      `;
    }
    const scope = suggested === total ? 'Butun oy' : `${suggested} kun`;
    return `
      <div role="status" style="margin-bottom: 0.75rem; padding: 0.75rem 1rem; border-radius: var(--radius-md); border: 1px dashed rgba(245, 158, 11, 0.6); background: rgba(245, 158, 11, 0.1); display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap;">
        <div style="color: #fbbf24; font-size: 0.85rem; font-weight: 600;">
          <i class="fas fa-exclamation-circle"></i> Saqlanmagan taklif: ${esc(monthLabel())} — ${scope} hali saqlanmagan.
          <span style="display: block; font-weight: 500; font-size: 0.78rem; color: var(--text-secondary);">"Taklif" belgili kunlar uchun navbatchilik to'lanmaydi, toki jadval saqlanmaguncha.</span>
        </div>
        <button class="btn-portal btn-success-portal" onclick="window.FMH_HR.saveSuggestedRoster()">
          <i class="fas fa-save"></i> Jadvalni saqlash
        </button>
      </div>
    `;
  }

  function renderStampModeBanner() {
    const activeStaffId = State.activePaintStamp ? State.activePaintStamp.staffId : '';

    return `
      <div class="stamp-mode-banner">
        <div style="display: flex; align-items: center; gap: 8px;">
          <div style="font-weight: 800; color: #ffffff; font-size: 0.88rem;">
            <i class="fas fa-magic" style="color: #38bdf8;"></i> Faol Shtamp:
          </div>
          <div style="font-size: 0.8rem; color: #38bdf8; font-weight: 700;">
            ${esc(State.activePaintStamp ? State.activePaintStamp.name : 'Xodim tanlang')}
          </div>
        </div>

        <div class="stamp-selector-list">
          ${dutyPool('doctor').concat(dutyPool('nurse'), dutyPool('sanitar')).map(s => {
            const isActive = activeStaffId === s.id;
            const roleType = s.role === 'doctor' || s.role === 'chief_doctor' ? 'doctor_night' : s.role === 'nurse' ? 'nurse' : 'sanitar';
            return `
              <div class="stamp-chip ${isActive ? 'active' : ''}" onclick="window.FMH_HR.setPaintStamp('${esc(s.id)}', '${roleType}')">
                <i class="${s.role === 'doctor' || s.role === 'chief_doctor' ? 'fas fa-user-md' : s.role === 'nurse' ? 'fas fa-syringe' : 'fas fa-broom'}"></i>
                ${esc(String(s.full_name || '').split(' ')[1] || s.full_name)}
              </div>
            `;
          }).join('')}

          <div class="stamp-chip stamp-chip-eraser ${activeStaffId === 'eraser' ? 'active' : ''}" onclick="window.FMH_HR.setPaintStamp('eraser', 'eraser')">
            <i class="fas fa-eraser"></i> O'chirgich
          </div>
        </div>
      </div>
    `;
  }

  /**
   * View 1: 7-Day Google Calendar Style Monthly Grid (1 Nurse per day for entire building)
   */
  function renderMonthlyCalendarGrid() {
    const daysHeaders = ['Dushanba', 'Seshanba', 'Chorshanba', 'Payshanba', 'Juma', 'Shanba', 'Yakshanba'];
    const tDoc = tariffShort('doctor_night');
    const tNurse = tariffShort('nurse_24h');
    const tSan = tariffShort('sanitar_24h');

    return `
      <div class="cal-grid-container">
        <div class="cal-grid-days-header">
          ${daysHeaders.map((dh, idx) => `<div class="${idx >= 5 ? 'weekend' : ''}">${dh}</div>`).join('')}
        </div>

        <div class="monthly-calendar-grid">
          ${State.monthlySchedule.map(sch => {
            const todayDay = new Date().getDate();
            const isToday = sch.day === todayDay;
            const cellClass = `cal-day-cell ${isToday ? 'today' : ''} ${sch.is_weekend ? 'weekend' : ''} ${State.paintModeActive ? 'paintable-hover' : ''}`;

            return `
              <div class="${cellClass}">
                <div class="cal-day-top">
                  <span class="cal-day-num">${sch.day} ${isToday ? '<span class="status-badge badge-active" style="font-size:0.6rem; padding:1px 4px;">Bugun</span>' : ''}</span>
                  ${sch.suggested
                    ? '<span class="cal-day-badge" style="border: 1px dashed #fbbf24; color: #fbbf24;" title="Saqlanmagan taklif — to\'lanmaydi">Taklif</span>'
                    : `<span class="cal-day-badge">${esc(sch.brigade_name ? sch.brigade_name.split(' ')[0] : 'Smena')}</span>`}
                </div>

                <div class="cal-slot-list">
                  <div class="cal-slot-item slot-doc" onclick="window.FMH_HR.handleSlotClick(${sch.day}, 'doctor_night')" title="Shifokor Tungi (${tDoc}) - Tanlash uchun bosing">
                    <span style="overflow:hidden; text-overflow:ellipsis;"><i class="fas fa-user-md"></i> ${esc((sch.doctor_night_name || '—').split(' ')[1] || sch.doctor_night_name || '—')}</span>
                    <span style="font-size:0.65rem; opacity:0.8;">${tDoc}</span>
                  </div>

                  <div class="cal-slot-item slot-nurse" onclick="window.FMH_HR.handleSlotClick(${sch.day}, 'nurse_f1')" title="1-Qavat 24h Hamshira (${tNurse})">
                    <span style="overflow:hidden; text-overflow:ellipsis;"><i class="fas fa-syringe"></i> ${esc((sch.nurse_f1_name || sch.nurse_name || '—').split(' ')[0])} (1-Q)</span>
                    <span style="font-size:0.65rem; opacity:0.8;">${tNurse}</span>
                  </div>

                  <div class="cal-slot-item slot-nurse" onclick="window.FMH_HR.handleSlotClick(${sch.day}, 'nurse_f2')" title="2-Qavat 24h Hamshira (${tNurse})">
                    <span style="overflow:hidden; text-overflow:ellipsis;"><i class="fas fa-syringe"></i> ${esc((sch.nurse_f2_name || '—').split(' ')[0])} (2-Q)</span>
                    <span style="font-size:0.65rem; opacity:0.8;">${tNurse}</span>
                  </div>

                  <div class="cal-slot-item slot-sanitar" onclick="window.FMH_HR.handleSlotClick(${sch.day}, 'sanitar_24h')" title="24h Sanitarka (${tSan})">
                    <span style="overflow:hidden; text-overflow:ellipsis;"><i class="fas fa-broom"></i> ${esc((sch.sanitar_name || '—').split(' ')[0])}</span>
                    <span style="font-size:0.65rem; opacity:0.8;">${tSan}</span>
                  </div>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;
  }

  /**
   * View 2: Staff Gantt Timeline Matrix
   */
  function renderStaffGanttMatrix() {
    const todayDay = new Date().getDate();
    const daysInMonth = State.monthlySchedule.length || 31;
    const days = Array.from({ length: daysInMonth }, (_, i) => i + 1);
    const shiftStaffList = dutyPool('doctor').concat(dutyPool('nurse'), dutyPool('sanitar'));

    return `
      <div class="gantt-matrix-wrapper">
        <table class="gantt-table">
          <thead>
            <tr>
              <th class="gantt-staff-col">Xodim & Lavozim</th>
              <th style="min-width: 80px;">Smena / Summa</th>
              ${days.map(d => `<th style="${d === todayDay ? 'background: #4f46e5; color:#fff;' : ''}">${d}</th>`).join('')}
            </tr>
          </thead>
          <tbody>
            ${shiftStaffList.map(staff => {
              return `
                <tr>
                  <td class="gantt-staff-col">
                    <div style="font-weight: 700; color: #ffffff;">${esc(staff.full_name)}</div>
                    <div style="font-size: 0.7rem; color: var(--indigo-light);">${esc(staff.role_title_uz || staff.role)}</div>
                  </td>
                  <td style="font-family: var(--font-mono); font-weight: 700; color: #34d399; font-size: 0.75rem;">
                    ${staff.monthly_duty_count || 0} smena<br>
                    <span style="color: var(--text-muted); font-size: 0.7rem;">${formatUZS(staff.monthly_duty_earnings)}</span>
                  </td>

                  ${days.map(d => {
                    const sch = State.monthlySchedule.find(s => s.day === d);
                    let chip = '<span class="gantt-chip-rest">•</span>';

                    if (sch) {
                      // A suggested (unsaved) day shows a faded chip.
                      const sug = sch.suggested ? ' style="opacity: 0.55; border-style: dashed;"' : '';
                      const sugNote = sch.suggested ? ' — saqlanmagan taklif' : '';
                      if (sch.doctor_night_id === staff.id) {
                        chip = `<span class="gantt-chip-duty gantt-chip-doc"${sug} onclick="window.FMH_HR.handleSlotClick(${d}, 'doctor_night')" title="${d}-kun: Tungi Shifokor (${tariffShort('doctor_night')})${sugNote}">D</span>`;
                      } else if (sch.nurse_id === staff.id) {
                        chip = `<span class="gantt-chip-duty gantt-chip-nurse"${sug} onclick="window.FMH_HR.handleSlotClick(${d}, 'nurse_24h')" title="${d}-kun: Butun Bino 24h Hamshira (${tariffShort('nurse_24h')})${sugNote}">H</span>`;
                      } else if (sch.nurse_f2_id === staff.id) {
                        chip = `<span class="gantt-chip-duty gantt-chip-nurse"${sug} onclick="window.FMH_HR.handleSlotClick(${d}, 'nurse_f2')" title="${d}-kun: 2-Qavat 24h Hamshira (${tariffShort('nurse_24h')})${sugNote}">H</span>`;
                      } else if (sch.sanitar_id === staff.id) {
                        chip = `<span class="gantt-chip-duty gantt-chip-san"${sug} onclick="window.FMH_HR.handleSlotClick(${d}, 'sanitar_24h')" title="${d}-kun: 24h Sanitarka (${tariffShort('sanitar_24h')})${sugNote}">S</span>`;
                      }
                    }

                    return `<td style="${d === todayDay ? 'background: rgba(79, 70, 229, 0.1);' : ''}">${chip}</td>`;
                  }).join('')}
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  /**
   * View 3: Detailed Table (1 Nurse per day for entire building)
   */
  function renderDutyTable() {
    const todayDay = new Date().getDate();
    const curMonthName = UZ_MONTHS[State.currentMonth - 1];

    return `
      <div class="table-responsive-wrapper">
        <table class="hr-table">
          <thead>
            <tr>
              <th style="width: 100px;">Sana & Kun</th>
              <th>🩺 Tungi Shifokor (${tariffShort('doctor_night')})</th>
              <th>💉 24h Hamshira (Butun Bino — ${tariffShort('nurse_24h')})</th>
              <th>🧹 24h Sanitarka (${tariffShort('sanitar_24h')})</th>
              <th>🚑 On-Call Shifokor</th>
              <th style="text-align: right;">Kunlik Chiqim</th>
              <th style="text-align: center;">Tahrirlash</th>
            </tr>
          </thead>
          <tbody>
            ${State.monthlySchedule.map(sch => {
              const isToday = sch.day === todayDay;
              const rowHighlight = isToday ? 'style="background: rgba(99, 102, 241, 0.08); border-left: 3px solid #818cf8;"' : sch.is_weekend ? 'style="background: rgba(255, 255, 255, 0.015);"' : '';

              return `
                <tr ${rowHighlight}>
                  <td>
                    <div style="font-weight: 800; font-family: var(--font-mono); color: ${isToday ? '#38bdf8' : '#ffffff'};">
                      ${sch.day} ${curMonthName} ${isToday ? '<span class="status-badge badge-active" style="font-size: 0.65rem; padding: 1px 5px;">Bugun</span>' : ''}
                    </div>
                    <div style="font-size: 0.72rem; color: var(--text-muted);">${esc(sch.day_name)}${sch.suggested ? ' <span style="color: #fbbf24; font-weight: 700;" title="Saqlanmagan taklif — to\'lanmaydi">• Taklif</span>' : ''}</div>
                  </td>
                  <td>
                    <div class="duty-slot-badge duty-slot-doc" onclick="window.FMH_HR.handleSlotClick(${sch.day}, 'doctor_night')">
                      <span><i class="fas fa-user-md"></i> ${esc(sch.doctor_night_name)}</span>
                    </div>
                  </td>
                  <td>
                    <div class="duty-slot-badge duty-slot-nurse" onclick="window.FMH_HR.handleSlotClick(${sch.day}, 'nurse_24h')">
                      <span><i class="fas fa-syringe"></i> ${esc(sch.nurse_name)} (1-2 Qavat)</span>
                    </div>
                  </td>
                  <td>
                    <div class="duty-slot-badge duty-slot-sanitar" onclick="window.FMH_HR.handleSlotClick(${sch.day}, 'sanitar_24h')">
                      <span><i class="fas fa-broom"></i> ${esc(sch.sanitar_name)}</span>
                    </div>
                  </td>
                  <td><span style="font-size: 0.8rem; color: #fbbf24;"><i class="fas fa-phone-alt"></i> ${esc(sch.oncall_doc_name)}</span></td>
                  <td style="text-align: right; font-family: var(--font-mono); font-weight: 700; color: #34d399;">${formatUZS(sch.daily_duty_cost)}</td>
                  <td style="text-align: center;">
                    <button class="btn-portal btn-outline-portal" style="padding: 3px 8px; font-size: 0.72rem;" onclick="window.FMH_HR.openQuickPicker(${sch.day}, 'doctor_night')">
                      <i class="fas fa-edit"></i>
                    </button>
                  </td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  // ==========================================================================
  // BRIGADE BUILDER MODAL LOGIC (1 DOCTOR, 1 NURSE, 1 SANITAR PER BRIGADE)
  // ==========================================================================

  function openBrigadeModal() {
    const modal = document.getElementById('brigade-modal');
    const container = document.getElementById('brigade-cards-container');
    if (!modal || !container) return;

    const doctors = dutyPool('doctor');
    const nurses = dutyPool('nurse');
    const sanitars = dutyPool('sanitar');

    container.innerHTML = State.brigades.map((brg, bIdx) => {
      return `
        <div class="brigade-card brigade-${esc(String(brg.id || '').split('-')[1] || '').toLowerCase()}">
          <div class="brigade-title">
            <span><i class="fas fa-users-medical"></i> ${esc(brg.name)}</span>
            <span class="status-badge badge-active">Faol</span>
          </div>

          <div class="form-group">
            <label class="form-label" style="font-size: 0.72rem;">🩺 Tungi Shifokor (${tariffShort('doctor_night')}):</label>
            <select class="brigade-member-select" id="brg-${bIdx}-doc">
              ${doctors.map(d => `<option value="${esc(d.id)}" ${d.id === brg.doctor_id ? 'selected' : ''}>${esc(d.full_name)}</option>`).join('')}
            </select>
          </div>

          <div class="form-group">
            <label class="form-label" style="font-size: 0.72rem;">💉 1-Qavat 24h Hamshirasi (${tariffShort('nurse_24h')}):</label>
            <select class="brigade-member-select" id="brg-${bIdx}-nurse-f1">
              ${nurses.map(n => `<option value="${esc(n.id)}" ${n.id === (brg.nurse_f1_id || brg.nurse_id) ? 'selected' : ''}>${esc(n.full_name)}</option>`).join('')}
            </select>
          </div>

          <div class="form-group">
            <label class="form-label" style="font-size: 0.72rem;">💉 2-Qavat 24h Hamshirasi (${tariffShort('nurse_24h')}):</label>
            <select class="brigade-member-select" id="brg-${bIdx}-nurse-f2">
              <option value="">— Biriktirilmasin —</option>
              ${nurses.map(n => `<option value="${esc(n.id)}" ${n.id === brg.nurse_f2_id ? 'selected' : ''}>${esc(n.full_name)}</option>`).join('')}
            </select>
          </div>

          <div class="form-group">
            <label class="form-label" style="font-size: 0.72rem;">🧹 24h Sanitarka (${tariffShort('sanitar_24h')}):</label>
            <select class="brigade-member-select" id="brg-${bIdx}-san">
              ${sanitars.map(s => `<option value="${esc(s.id)}" ${s.id === brg.sanitar_id ? 'selected' : ''}>${esc(s.full_name)}</option>`).join('')}
            </select>
          </div>
        </div>
      `;
    }).join('');

    modal.classList.add('active');
  }

  async function applyBrigadesToMonth(presetType = 'brigade_1_3') {
    if (State.rosterLoadError) {
      showToast('Jadval serverdan yuklanmagan — saqlab bo\'lmaydi. Sahifani yangilang.', 'danger');
      return false;
    }
    // This rewrites every day of the month on the server, including days
    // payroll already pays from, so ask before replacing saved days.
    const savedCount = State.monthlySchedule.filter(d => !d.suggested).length;
    if (savedCount > 0) {
      const ok = await fmhConfirm({
        title: 'Jadvalni almashtirish',
        message: `${esc(monthLabel())} uchun saqlangan ${savedCount} kunlik jadval yangi brigada jadvali bilan almashtiriladi. Davom etasizmi?`,
        confirmText: 'Almashtirish',
        cancelText: 'Bekor Qilish',
        type: 'warning'
      });
      if (!ok) return false;
    }

    State.brigades.forEach((brg, bIdx) => {
      const docEl = document.getElementById(`brg-${bIdx}-doc`);
      const nurseF1El = document.getElementById(`brg-${bIdx}-nurse-f1`);
      const nurseF2El = document.getElementById(`brg-${bIdx}-nurse-f2`);
      const sanEl = document.getElementById(`brg-${bIdx}-san`);

      if (docEl) brg.doctor_id = docEl.value;
      if (nurseF1El) {
        brg.nurse_f1_id = nurseF1El.value;
        brg.nurse_id = nurseF1El.value;
      }
      if (nurseF2El) brg.nurse_f2_id = nurseF2El.value || null;
      if (sanEl) brg.sanitar_id = sanEl.value;
    });

    State.activeAlgorithm = presetType;
    const snaps = snapshotDays(State.monthlySchedule);
    const fresh = generateMonthlySchedule(presetType).map(d => {
      // Keep the stored server day underneath so fields HR does not edit
      // (e.g. the Duty page's reserve sanitarka) survive the save.
      const old = State.monthlySchedule.find(o => o.date === d.date);
      d._server = old ? old._server : null;
      return d;
    });
    State.monthlySchedule = fresh;
    closeAllModals();
    renderShiftRoster();
    return saveRosterDays(fresh, snaps, 'Brigadalar butun oyga tatbiq etildi va jadval saqlandi!');
  }

  // ==========================================================================
  // SHIFT SWAPPER MODAL LOGIC
  // ==========================================================================

  function openSwapModal() {
    const modal = document.getElementById('swap-modal');
    if (!modal) return;
    const selA = document.getElementById('swap-day-a');
    const selB = document.getElementById('swap-day-b');
    if (selA && selB) {
      // The roster month's real days (this listed 31 days of "Avgust 2026"
      // whatever the month).
      const days = State.monthlySchedule.map(s => `<option value="${s.day}">${dayLabel(s.day)} ${State.currentYear}</option>`).join('');
      selA.innerHTML = days;
      selB.innerHTML = days;
      selA.value = "1";
      selB.value = State.monthlySchedule.length >= 4 ? "4" : "1";
    }
    // Option labels in hr.html carry tariffs; rewrite them from the price list.
    const roleSel = document.getElementById('swap-role-type');
    if (roleSel) {
      const labels = {
        doctor: `Faqat Shifokorlarni (Doctor Night — ${tariffShort('doctor_night')})`,
        nurse: `Faqat Hamshirani (24h Nurse Butun Bino — ${tariffShort('nurse_24h')})`,
        sanitar: `Faqat Sanitarkani (24h Sanitar — ${tariffShort('sanitar_24h')})`
      };
      Array.from(roleSel.options).forEach(o => { if (labels[o.value]) o.textContent = labels[o.value]; });
    }
    modal.classList.add('active');
  }

  function executeSwap() {
    const dayA = parseInt(document.getElementById('swap-day-a').value);
    const dayB = parseInt(document.getElementById('swap-day-b').value);
    const roleType = document.getElementById('swap-role-type').value;

    const targetA = State.monthlySchedule.find(s => s.day === dayA);
    const targetB = State.monthlySchedule.find(s => s.day === dayB);

    if (!targetA || !targetB || dayA === dayB) {
      showToast('Iltimos, ikkita turli kunni tanlang!', 'danger');
      return;
    }

    const snaps = snapshotDays([targetA, targetB]);
    const swap = (idKey, nameKey, slotType) => {
      const a = { id: targetA[idKey], name: targetA[nameKey] };
      setSlot(targetA, slotType, targetB[idKey], targetB[nameKey]);
      setSlot(targetB, slotType, a.id, a.name);
    };

    if (roleType === 'all' || roleType === 'doctor') {
      swap('doctor_night_id', 'doctor_night_name', 'doctor_night');
    }

    // Both nurse posts move together; swapping only nurse_id left the
    // first-floor alias (nurse_f1_*) behind, which is what gets saved.
    if (roleType === 'all' || roleType === 'nurse') {
      swap('nurse_f1_id', 'nurse_f1_name', 'nurse_f1');
      swap('nurse_f2_id', 'nurse_f2_name', 'nurse_f2');
    }

    if (roleType === 'all' || roleType === 'sanitar') {
      swap('sanitar_id', 'sanitar_name', 'sanitar_24h');
    }

    closeAllModals();
    renderShiftRoster();
    saveRosterDays([targetA, targetB], snaps, `${dayLabel(dayA)} va ${dayLabel(dayB)} smenalari o'rni almashtirildi va saqlandi!`);
  }

  // ==========================================================================
  // TELEGRAM & WHATSAPP EXPORT MODAL LOGIC
  // ==========================================================================

  function openTelegramModal() {
    const modal = document.getElementById('telegram-modal');
    const previewBox = document.getElementById('telegram-preview-box');
    if (!modal || !previewBox) return;

    let text = `🏥 FAYZ MEDICAL HOUSE — 24/7 NAVBATCHILIK JADVALI (${monthLabel().toUpperCase()})\n`;
    text += `📍 Toshkent sh., Yunusobod t., Nurmakon 2A | 24/7 Hotline: +998 90 372-03-03\n`;
    text += `━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n`;

    State.monthlySchedule.forEach(sch => {
      text += `📅 ${dayLabel(sch.day)} (${sch.day_name})${sch.suggested ? ' [taklif, saqlanmagan]' : ''}:\n`;
      text += `  🩺 Tungi Shifokor: ${sch.doctor_night_name}\n`;
      text += `  💉 24h Hamshira (Butun bino): ${sch.nurse_name}\n`;
      if (sch.nurse_f2_id) text += `  💉 24h Hamshira (2-qavat): ${sch.nurse_f2_name}\n`;
      text += `  🧹 24h Sanitarka: ${sch.sanitar_name}\n`;
      text += `  🚑 On-Call Detoks: ${sch.oncall_doc_name}\n\n`;
    });

    previewBox.textContent = text;
    modal.classList.add('active');
  }

  function copyTelegramText() {
    const previewBox = document.getElementById('telegram-preview-box');
    if (!previewBox) return;
    navigator.clipboard.writeText(previewBox.textContent).then(() => {
      showToast('Telegram formati xotiraga nusxalandi! Endi guruhga tashlashingiz mumkin.', 'success');
    }).catch(() => {
      showToast('Nusxalashda xatolik yuz berdi', 'danger');
    });
  }

  // ==========================================================================
  // QUICK PICKER MODAL
  // ==========================================================================

  function openQuickPicker(day, slotType) {
    State.selectedSlot = { day, slotType };

    const modal = document.getElementById('quick-picker-modal');
    const titleEl = document.getElementById('quick-picker-title');
    const container = document.getElementById('quick-picker-candidates');
    if (!modal || !container) return;

    let roleFilter = 'doctor';
    let typeTitle = `Tungi Navbatchi Shifokor (Tarif: ${formatUZS(tariff('doctor_night'))}/tun)`;

    if (slotType === 'nurse_f1') {
      roleFilter = 'nurse';
      typeTitle = `1-Qavat 24-Soatlik Hamshirasi (Tarif: ${formatUZS(tariff('nurse_24h'))}/24h)`;
    } else if (slotType === 'nurse_f2') {
      roleFilter = 'nurse';
      typeTitle = `2-Qavat 24-Soatlik Hamshirasi (Tarif: ${formatUZS(tariff('nurse_24h'))}/24h)`;
    } else if (slotType === 'nurse_24h' || slotType === 'nurse') {
      roleFilter = 'nurse';
      typeTitle = `24-Soatlik Hamshira (Tarif: ${formatUZS(tariff('nurse_24h'))}/24h)`;
    } else if (slotType === 'sanitar_24h') {
      roleFilter = 'sanitar';
      typeTitle = `24-Soatlik Sanitarka (Tarif: ${formatUZS(tariff('sanitar_24h'))}/24h)`;
    }

    if (titleEl) titleEl.innerHTML = `<i class="fas fa-user-check" style="color: #38bdf8;"></i> ${dayLabel(day)} uchun ${typeTitle}`;

    let eligible = dutyPool(roleFilter);

    const prevDay = day > 1 ? State.monthlySchedule.find(s => s.day === day - 1) : null;

    container.innerHTML = eligible.map(staff => {
      let isRestRecommended = true;
      let conflictReason = null;

      if (prevDay) {
        const workedYesterday = prevDay.doctor_night_id === staff.id || prevDay.nurse_id === staff.id || prevDay.nurse_f1_id === staff.id || prevDay.nurse_f2_id === staff.id || prevDay.sanitar_id === staff.id;
        if (workedYesterday) {
          isRestRecommended = false;
          conflictReason = 'Kecha 24h / tungi navbatchilikda edi (Kamida 1 sutka dam tavsiya etiladi)';
        }
      }

      const cardClass = conflictReason ? 'smart-picker-card conflict' : isRestRecommended ? 'smart-picker-card recommended' : 'smart-picker-card';

      return `
        <div class="${cardClass}" onclick="window.FMH_HR.assignSlotStaff('${esc(staff.id)}')">
          <div style="display: flex; justify-content: space-between; align-items: flex-start;">
            <div>
              <div style="font-weight: 800; color: #ffffff; font-size: 0.95rem;">${esc(staff.full_name)}</div>
              <div style="font-size: 0.74rem; color: var(--indigo-light);">${esc(staff.role_title_uz || staff.role)}</div>
            </div>
            ${isRestRecommended ? '<span class="status-badge badge-active"><i class="fas fa-check"></i> Tavsiya</span>' : conflictReason ? '<span class="status-badge badge-danger"><i class="fas fa-exclamation-triangle"></i> Ziddiyat</span>' : '<span class="status-badge badge-late">1 kun dam</span>'}
          </div>

          <div style="font-size: 0.76rem; color: var(--text-secondary); display: flex; justify-content: space-between;">
            <span>Shu oydagi navbatchiliklari:</span>
            <span style="font-family: var(--font-mono); font-weight: 700; color: #38bdf8;">${staff.monthly_duty_count || 0} smena</span>
          </div>

          <div style="font-size: 0.76rem; color: var(--text-secondary); display: flex; justify-content: space-between;">
            <span>Navbatchilik daromadi:</span>
            <span style="font-family: var(--font-mono); font-weight: 700; color: #34d399;">${formatUZS(staff.monthly_duty_earnings)}</span>
          </div>

          ${conflictReason ? `<div style="font-size: 0.72rem; color: #fb7185; margin-top: 4px;"><i class="fas fa-info-circle"></i> ${conflictReason}</div>` : ''}

          <button class="btn-portal btn-primary-portal" style="width: 100%; justify-content: center; font-size: 0.78rem; margin-top: 4px;">
            <i class="fas fa-check"></i> Biriktirish
          </button>
        </div>
      `;
    }).join('');

    modal.classList.add('active');
  }

  function assignSlotStaff(staffId) {
    if (!State.selectedSlot) return;
    const { day, slotType } = State.selectedSlot;
    const targetDay = State.monthlySchedule.find(s => s.day === day);
    const staff = findStaff(staffId);
    if (!targetDay || !staff) return;

    const snaps = snapshotDays([targetDay]);
    setSlot(targetDay, slotType, staff.id, staff.full_name);

    closeAllModals();
    renderShiftRoster();
    saveRosterDays([targetDay], snaps, `${dayLabel(day)} uchun ${staff.full_name} biriktirildi va saqlandi!`);
  }

  // Which duty tariff applies to a person. Staff added from MySQL (e.g. the
  // sanitarkas, role 'sanitar') carry no duty_rate_type, so fall back to role.
  function dutyKeyFor(staff) {
    if (!staff) return null;
    if (['doctor_night', 'nurse_24h', 'sanitar_24h'].indexOf(staff.duty_rate_type) >= 0) return staff.duty_rate_type;
    if (staff.duty_rate_type === 'none') return null;
    if (staff.role === 'doctor' || staff.role === 'chief_doctor') return 'doctor_night';
    if (staff.role === 'nurse') return 'nurse_24h';
    if (staff.role === 'sanitar') return 'sanitar_24h';
    return null;
  }

  // ==========================================================================
  // TAB 1: STAFF DIRECTORY
  // ==========================================================================
  function renderStaffDirectory() {
    const container = document.getElementById('staff-grid-container');
    if (!container) return;

    let filtered = State.staff;

    if (State.staffFilterDept !== 'all') {
      filtered = filtered.filter(s => s.department === State.staffFilterDept);
    }

    if (State.staffFilterStatus !== 'all') {
      filtered = filtered.filter(s => s.status === State.staffFilterStatus);
    }

    if (State.searchQuery.trim()) {
      const q = State.searchQuery.toLowerCase().trim();
      filtered = filtered.filter(s => 
        (s.full_name && s.full_name.toLowerCase().includes(q)) ||
        (s.specialty && s.specialty.toLowerCase().includes(q)) ||
        (s.role_title_uz && s.role_title_uz.toLowerCase().includes(q)) ||
        (s.phone && s.phone.includes(q)) ||
        (s.id && s.id.toLowerCase().includes(q))
      );
    }

    const badge = document.getElementById('badge-staff-count');
    if (badge) badge.textContent = filtered.length;

    if (filtered.length === 0) {
      container.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; padding: 3rem; background: var(--bg-card); border-radius: var(--radius-lg); border: 1px dashed var(--border-subtle);">
          <i class="fas fa-user-slash" style="font-size: 2.5rem; color: var(--text-muted); margin-bottom: 1rem;"></i>
          <h3 style="color: var(--text-primary); font-size: 1.1rem; margin-bottom: 0.5rem;">Xodim topilmadi</h3>
          <p style="color: var(--text-secondary); font-size: 0.85rem;">Qidiruv yoki filtr mezonlarini o'zgartirib ko'ring.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = filtered.map(staff => {
      const initials = staff.full_name ? staff.full_name.split(' ').map(n => n[0]).join('').substring(0, 2) : 'ST';
      const statusClass = staff.status === 'active' ? 'active' : 'inactive';
      const statusLabel = staff.status === 'active' ? 'Faol' : 'Noaktiv';
      // A deactivated employee stays on the list, dimmed and labelled, with
      // a way back; the old delete made them vanish until the next reload.
      const isInactive = staff.status === 'inactive';

      const dutyKey = dutyKeyFor(staff);
      const dutyRateLabel = dutyKey ? `${formatUZS(tariff(dutyKey))}/${dutyKey === 'doctor_night' ? 'tun' : '24h'}` : '—';

      return `
        <div class="staff-card" data-staff-id="${staff.id}"${isInactive ? ' style="opacity: 0.65;"' : ''}>
          <div class="staff-card-header">
            <div class="staff-avatar" style="background: ${staff.avatar_color || '#4f46e5'};">
              ${initials}
              <span class="status-dot ${statusClass}" title="${statusLabel}"></span>
            </div>
            <div class="staff-info">
              <div class="staff-name">${staff.full_name}</div>
              <div class="staff-role-badge"><i class="fas fa-id-badge"></i> ${staff.role_title_uz || staff.role}</div>
              ${isInactive ? '<span class="status-badge badge-danger" style="margin-top: 4px;"><i class="fas fa-user-slash"></i> Faolsizlantirilgan</span>' : ''}
              <div class="staff-specialty">${esc(staff.specialty || '—')}</div>
            </div>
          </div>

          <div class="staff-meta-row">
            <div class="staff-meta-chip" title="Telefon"><i class="fas fa-phone"></i> ${staff.phone || '—'}</div>
            <div class="staff-meta-chip" title="Oylik Navbatchilik"><i class="fas fa-clock"></i> ${staff.monthly_duty_count || 0} smena (${formatUZS(staff.monthly_duty_earnings)})</div>
            <div class="staff-meta-chip" title="Navbatchilik Tarifi"><i class="fas fa-tag"></i> ${dutyRateLabel}</div>
            <div class="staff-meta-chip" title="Toifa"><i class="fas fa-award"></i> ${esc(staff.category || '—')}</div>
          </div>

          <div class="staff-kpi-bar">
            <div style="color: var(--text-muted); font-size: 0.75rem;">
              Oklad: <span class="staff-salary-tag">${formatUZS(staff.base_salary)}</span>
            </div>
            <div style="display: flex; align-items: center; gap: 4px; color: #fbbf24; font-weight: 700;">
              <i class="fas fa-star"></i> ${staff.kpi_rating || 5.0}
            </div>
          </div>

          <div class="staff-actions-row">
            <button class="btn-portal btn-outline-portal" style="padding: 5px 10px; font-size: 0.76rem;" onclick="window.FMH_HR.openStaffDossier('${staff.id}')">
              <i class="fas fa-folder-open"></i> Shaxsiy Ishi
            </button>
            <button class="btn-portal btn-outline-portal" style="padding: 5px 10px; font-size: 0.76rem; border-color: rgba(99, 102, 241, 0.4); color: #818cf8;" onclick="window.FMH_HR.generatePayslip('${staff.id}')">
              <i class="fas fa-file-invoice-dollar"></i> Oylik Varaqasi
            </button>
            <button class="btn-portal btn-outline-portal" style="padding: 5px 8px; font-size: 0.76rem;" onclick="window.FMH_HR.editStaff('${staff.id}')" title="Tahrirlash">
              <i class="fas fa-edit"></i>
            </button>
            ${isInactive ? `
            <button class="btn-portal btn-success-portal" style="padding: 5px 10px; font-size: 0.76rem;" onclick="window.FMH_HR.reactivateStaff('${esc(staff.id)}')" title="Qayta faollashtirish">
              <i class="fas fa-user-check"></i> Faollashtirish
            </button>` : ''}
          </div>
        </div>
      `;
    }).join('');
  }

  // ==========================================================================
  // TAB 3: ATTENDANCE, TAB 4: PAYROLL
  // ==========================================================================

  // The saved attendance row for one person on the sheet's day, or null.
  function attendanceFor(staffId, day) {
    const d = day || State.attendanceDate;
    return State.attendance.find(a => a.staff_id === staffId && String(a.work_date || '').slice(0, 10) === d) || null;
  }

  const SHIFT_LABELS = { day: 'Kunduzgi', night: 'Tungi', '24h': '24 soat' };

  function renderAttendanceSheet() {
    const tbody = document.getElementById('attendance-tbody');
    if (!tbody) return;

    const dateInp = document.getElementById('attendance-date');
    if (dateInp && dateInp.value !== State.attendanceDate) dateInp.value = State.attendanceDate;

    // Active staff only: a deactivated person has no attendance to record.
    const people = State.staff.filter(s => s.status !== 'inactive');

    // Someone with no saved row used to be shown as "Keldi 08:00, 8 soat,
    // Standart ish kuni" -- attendance nobody had recorded.
    tbody.innerHTML = people.map((staff, idx) => {
      const att = attendanceFor(staff.id);

      let badgeHtml = '<span class="status-badge badge-info"><i class="fas fa-minus"></i> Qayd etilmagan</span>';
      if (att && att.status === 'present') {
        badgeHtml = '<span class="status-badge badge-present"><i class="fas fa-check"></i> Keldi</span>';
      } else if (att && att.status === 'late') {
        const mins = att.late_minutes !== null && att.late_minutes !== undefined ? ` (${Number(att.late_minutes)} daq)` : '';
        badgeHtml = `<span class="status-badge badge-late"><i class="fas fa-clock"></i> Kechikdi${mins}</span>`;
      } else if (att && att.status === 'absent') {
        badgeHtml = '<span class="status-badge badge-danger"><i class="fas fa-times"></i> Kelmadi</span>';
      } else if (att && att.status === 'on_leave') {
        badgeHtml = '<span class="status-badge badge-info"><i class="fas fa-umbrella-beach"></i> Ta\'tilda</span>';
      } else if (att && att.status === 'sick') {
        badgeHtml = '<span class="status-badge badge-info"><i class="fas fa-notes-medical"></i> Kasal</span>';
      }
      if (att && SHIFT_LABELS[att.shift_type]) {
        badgeHtml += ` <span class="status-badge badge-shift">${SHIFT_LABELS[att.shift_type]}</span>`;
      }
      const cin = att && att.check_in_time ? att.check_in_time : '—';
      const away = att && ['absent', 'on_leave', 'sick'].indexOf(att.status) >= 0;
      // "Still at work" only makes sense for today; an old day without a
      // check-out simply has none recorded.
      const stillIn = att && att.check_in_time && !away && State.attendanceDate === todayIso();
      const cout = att && att.check_out_time ? att.check_out_time : (stillIn ? 'Ish jarayonida' : '—');
      const hours = att && att.worked_hours !== null && att.worked_hours !== undefined ? `${att.worked_hours} soat` : '—';

      return `
        <tr>
          <td><span style="font-family: var(--font-mono); font-weight: 700; color: var(--text-muted);">${idx + 1}</span></td>
          <td>
            <div style="font-weight: 700; color: #ffffff;">${staff.full_name}</div>
            <div style="font-size: 0.74rem; color: var(--text-secondary);">${staff.role_title_uz || staff.role}</div>
          </td>
          <td><span class="staff-meta-chip"><i class="fas fa-building"></i> ${staff.department_name_uz || staff.department}</span></td>
          <td><span style="font-family: var(--font-mono); font-weight: 700; color: #38bdf8;">${esc(cin)}</span></td>
          <td><span style="font-family: var(--font-mono); font-weight: 700; color: var(--text-muted);">${esc(cout)}</span></td>
          <td><span style="font-family: var(--font-mono); font-weight: 700; color: #34d399;">${esc(hours)}</span></td>
          <td>${badgeHtml}</td>
          <td><span style="font-size: 0.78rem; color: var(--text-secondary);">${esc((att && att.notes) || '—')}</span></td>
          <td style="text-align: center;">
            <button class="btn-portal btn-outline-portal" style="padding: 4px 8px; font-size: 0.74rem;" onclick="window.FMH_HR.openLogAttendanceModal('${staff.id}')">
              <i class="fas fa-user-check"></i> Qayd etish
            </button>
          </td>
        </tr>
      `;
    }).join('');
  }

  // ==========================================================================
  // PAYROLL (server: GET /api/hr/payroll?month=YYYY-MM)
  // ==========================================================================
  // Payroll used to be computed here from a rota the browser invented on
  // every load, plus a flat 2 600 000 "inpatient bonus" for every doctor and
  // a detox bonus of fee x 6. The server now counts pay from the SAVED roster
  // only; this page just shows it.
  async function loadPayroll() {
    const month = monthKey();
    const seq = ++State.payrollSeq;
    let res = null;
    try {
      res = await fetch('/api/hr/payroll?month=' + encodeURIComponent(month));
    } catch (e) {
      res = null;
    }
    let data = null;
    let msg = res ? 'Oylik hisob-kitobi yuklanmadi' : 'Server bilan aloqa yo\'q — oylik hisob-kitobi yuklanmadi';
    if (res) {
      try {
        const body = await res.json();
        if (res.ok) data = body;
        else if (body && body.error) msg = body.error;
      } catch (e) { /* non-JSON body */ }
    }
    if (seq !== State.payrollSeq) return State.payroll; // a newer load won
    State.payroll = data;
    State.payrollError = data ? null : msg;
    if (!data) showToast(msg, 'danger');
    renderPayrollTable();
    updateKPIs();
    return data;
  }

  function payrollRow(staffId) {
    const p = State.payroll;
    return p && Array.isArray(p.staff) ? (p.staff.find(r => r.staff_id === staffId) || null) : null;
  }

  // "3 tun x 350 000 so'm" from the server's per-tariff counts.
  function dutyPayLabel(row) {
    const counts = (row && row.duty_counts) || {};
    const tariffs = (State.payroll && State.payroll.tariffs) || {};
    return Object.keys(counts).filter(k => counts[k] > 0).map(k => {
      const rate = tariffs[k] !== undefined ? Number(tariffs[k]) : tariff(k);
      return `${counts[k]} ${k === 'doctor_night' ? 'tun' : 'smena'} x ${formatUZS(rate)}`;
    }).join(', ');
  }

  function staffTitle(staffId, fallback) {
    const st = (State.staff || []).find(s => s.id === staffId);
    return (st && (st.role_title_uz || st.role)) || fallback || '';
  }

  function ensurePayrollChrome() {
    const tbody = document.getElementById('payroll-tbody');
    if (!tbody) return null;
    // The toolbar title in hr.html says "(Avgust 2026)"; show the real month.
    const titleEl = document.querySelector('#tab-panel-payroll .section-toolbar-card > div:first-child');
    if (titleEl) {
      titleEl.innerHTML = `<i class="fas fa-calculator" style="color: var(--purple);"></i> Shifokorlar va Xodimlar Oylik Maoshi Hisob-Kitobi (${esc(monthLabel())})`;
    }
    // Same month switcher as the roster tab: payroll follows the roster month.
    const actions = document.querySelector('#tab-panel-payroll .section-toolbar-card > div:nth-child(2)');
    if (actions) {
      let nav = document.getElementById('payroll-month-nav');
      if (!nav) {
        nav = document.createElement('div');
        nav.id = 'payroll-month-nav';
        actions.insertBefore(nav, actions.firstChild);
      }
      nav.innerHTML = monthNavHtml();
    }
    let box = document.getElementById('payroll-warning-box');
    if (!box) {
      const wrapper = tbody.closest('.table-responsive-wrapper');
      if (!wrapper || !wrapper.parentNode) return null;
      box = document.createElement('div');
      box.id = 'payroll-warning-box';
      wrapper.parentNode.insertBefore(box, wrapper);
    }
    return box;
  }

  // Shifts the server could not pay (unknown id, or roster name that does
  // not match the staff record behind the id) and unsaved days. Without this
  // HR would see a lower total and not know why.
  function renderPayrollWarnings(box) {
    if (!box) return;
    const p = State.payroll;
    if (!p) { box.innerHTML = ''; return; }
    const parts = [];
    const mism = Array.isArray(p.name_mismatches) ? p.name_mismatches : [];
    const unl = Array.isArray(p.unlinked_shifts) ? p.unlinked_shifts : [];
    if (mism.length || unl.length) {
      const items = mism.map(m =>
        `<li>Jadvalda: <strong>${esc(m.roster_name)}</strong> — xodim ${esc(m.staff_id)}: <strong>${esc(m.staff_name)}</strong> (${Number(m.shifts) || 0} smena)</li>`
      ).concat(unl.map(u =>
        `<li>Jadvalda: <strong>${esc(u.name || '—')}</strong> — ${u.staff_id ? `ID ${esc(u.staff_id)} xodimlar ro'yxatida yo'q` : 'xodim ID biriktirilmagan'} (${Number(u.shifts) || 0} smena)</li>`
      ));
      parts.push(`
        <div role="alert" style="margin-bottom: 0.75rem; padding: 0.75rem 1rem; border-radius: var(--radius-md); border: 1px solid rgba(244, 63, 94, 0.45); background: rgba(244, 63, 94, 0.08); color: #fb7185; font-size: 0.82rem;">
          <div style="font-weight: 700;"><i class="fas fa-exclamation-triangle"></i> Bu smenalar to'lanmaydi — navbatchilik jadvalini to'g'rilang:</div>
          <ul style="margin: 0.4rem 0 0 1.2rem; color: var(--text-secondary);">${items.join('')}</ul>
        </div>
      `);
    }
    const saved = Number(p.saved_days) || 0;
    const total = Number(p.days_in_month) || 0;
    if (total && saved < total) {
      parts.push(`
        <div role="status" style="margin-bottom: 0.75rem; padding: 0.6rem 1rem; border-radius: var(--radius-md); border: 1px dashed rgba(245, 158, 11, 0.6); background: rgba(245, 158, 11, 0.08); color: #fbbf24; font-size: 0.82rem; font-weight: 600;">
          <i class="fas fa-info-circle"></i> ${esc(monthLabel(p.month))}: ${saved} / ${total} kunlik jadval saqlangan. Saqlanmagan kunlar uchun navbatchilik to'lanmaydi.
        </div>
      `);
    }
    box.innerHTML = parts.join('');
  }

  function renderPayrollTable() {
    const tbody = document.getElementById('payroll-tbody');
    if (!tbody) return;
    renderPayrollWarnings(ensurePayrollChrome());

    const setTotals = (gross, ded, net) => {
      const elGrandGross = document.getElementById('payroll-total-gross');
      if (elGrandGross) elGrandGross.textContent = gross;
      const elGrandTaxes = document.getElementById('payroll-total-taxes');
      if (elGrandTaxes) elGrandTaxes.textContent = ded;
      const elGrandNet = document.getElementById('payroll-total-net');
      if (elGrandNet) elGrandNet.textContent = net;
    };

    const p = State.payroll;
    if (!p || !Array.isArray(p.staff)) {
      const msg = State.payrollError ? esc(State.payrollError) : 'Oylik hisob-kitobi yuklanmoqda...';
      tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; padding: 1.5rem; color: var(--text-muted);">${msg}</td></tr>`;
      setTotals('—', '—', '—');
      return;
    }

    tbody.innerHTML = p.staff.map((row) => {
      const dutyLabel = dutyPayLabel(row);
      // Column order follows the hr.html header: Oklad | Statsionar & Detox |
      // Tungi Smena. There is no source for inpatient/detox pay, so it shows a
      // dash instead of the old invented figures.
      return `
        <tr>
          <td><span style="font-family: var(--font-mono); font-weight: 700; color: var(--text-muted);">${esc(row.staff_id)}</span></td>
          <td>
            <div style="font-weight: 700; color: #ffffff;">${esc(row.full_name)}</div>
            <div style="font-size: 0.72rem; color: var(--indigo-light);">${esc(staffTitle(row.staff_id, row.role))}${row.is_active === false ? ' • Noaktiv' : ''}</div>
          </td>
          <td><span style="font-family: var(--font-mono);">${formatUZS(row.base_salary)}</span></td>
          <td><span style="font-family: var(--font-mono); color: var(--text-muted);">—</span></td>
          <td>
            <div style="font-family: var(--font-mono); font-weight: 700; color: #34d399;">+${formatUZS(row.duty_pay)}</div>
            <div style="font-size: 0.7rem; color: var(--text-muted);">${esc(dutyLabel || '—')}</div>
          </td>
          <td><span style="font-family: var(--font-mono); color: #fb7185;">-${formatUZS(row.deductions)}</span></td>
          <td><span style="font-family: var(--font-mono); font-weight: 800; color: #34d399; font-size: 0.95rem;">${formatUZS(row.net)}</span></td>
          <td><span class="status-badge badge-active"><i class="fas fa-check-circle"></i> Hisoblangan</span></td>
          <td style="text-align: center;">
            <button class="btn-portal btn-primary-portal" style="padding: 4px 10px; font-size: 0.74rem;" onclick="window.FMH_HR.generatePayslip('${esc(row.staff_id)}')">
              <i class="fas fa-receipt"></i> Pay Slip
            </button>
          </td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="9" style="text-align: center; padding: 1.5rem; color: var(--text-muted);">Bu oy uchun xodimlar topilmadi.</td></tr>';

    const t = p.totals || {};
    setTotals(formatUZS(t.gross), formatUZS(t.deductions), formatUZS(t.net));
  }

  // ==========================================================================
  // OFFICIAL PAYSLIP & DOSSIER
  // ==========================================================================

  // The payslip used to print "Davr: Avgust 2026", "Sana: 15.08.2026" and
  // "TO'LANGAN" for everyone, with browser-computed figures. It now shows the
  // server payroll row for the roster month.
  async function generatePayslip(staffId) {
    if (!State.payroll) await loadPayroll();
    const row = payrollRow(staffId);
    if (!row) {
      if (State.payroll) showToast('Bu xodim uchun shu oy oylik hisobi topilmadi.', 'warning');
      return;
    }
    const st = (State.staff || []).find(s => s.id === staffId) || {};
    const staff = {
      id: row.staff_id,
      full_name: row.full_name,
      role: row.role,
      role_title_uz: st.role_title_uz,
      department: st.department,
      department_name_uz: st.department_name_uz
    };

    const base = Number(row.base_salary) || 0;
    const dutyEarnings = Number(row.duty_pay) || 0;
    const dutyLabel = dutyPayLabel(row);
    const dutyItemLabel = dutyLabel ? `Navbatchilik To'lovi (${dutyLabel}):` : 'Navbatchilik To\'lovi:';
    const gross = Number(row.gross) || 0;
    const tax = Number(row.income_tax) || 0;
    const inps = Number(row.pension) || 0;
    const totalDeductions = Number(row.deductions) || 0;
    const net = Number(row.net) || 0;
    const rates = State.payroll.rates || {};
    const pct = (r, dflt) => `${Math.round((r !== undefined ? Number(r) : dflt) * 1000) / 10}%`;
    const period = monthLabel(State.payroll.month);
    const now = new Date();
    const todayStr = `${pad2(now.getDate())}.${pad2(now.getMonth() + 1)}.${now.getFullYear()}`;

    const modal = document.getElementById('payslip-modal');
    const container = document.getElementById('payslip-sheet-container');
    if (!modal || !container) return;
    // printPayslip() (the modal's Print button) reads this; nothing set it,
    // so Print always answered "select an employee first".
    modal._currentStaffId = staffId;

    container.innerHTML = `
      <div class="payslip-sheet">
        <div class="payslip-header">
          <div>
            <div class="payslip-title">FAYZ MEDICAL HOUSE</div>
            <div style="font-size: 0.8rem; color: #64748b; font-weight: 600;">OYLIK MAOSH VA DAROMADLAR QAYDNOMASI (PAY SLIP)</div>
            <div style="font-size: 0.75rem; color: #94a3b8;">Davr: ${esc(period)} | Toshkent sh., Yunusobod t., Nurmakon 2A</div>
          </div>
          <div style="text-align: right;">
            <div style="font-size: 0.95rem; font-weight: 700; font-family: var(--font-mono);">№ PS-${esc(State.payroll.month)}-${esc(String(staff.id).replace('STF-', ''))}</div>
            <div style="font-size: 0.75rem; color: #64748b;">Sana: ${todayStr}</div>
          </div>
        </div>

        <table class="payslip-table">
          <tr>
            <th style="width: 25%;">Xodim F.I.Sh:</th>
            <td style="font-weight: 700;">${esc(staff.full_name)}</td>
            <th style="width: 25%;">Xodim ID:</th>
            <td style="font-family: var(--font-mono); font-weight: 700;">${esc(staff.id)}</td>
          </tr>
          <tr>
            <th>Lavozim / Ixtisoslik:</th>
            <td>${esc(staff.role_title_uz || staff.role)}</td>
            <th>Bo'lim:</th>
            <td>${esc(staff.department_name_uz || staff.department || '—')}</td>
          </tr>
        </table>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-top: 1rem;">
          <div>
            <div style="font-weight: 700; color: #0f172a; margin-bottom: 6px; border-bottom: 2px solid #0284c7; padding-bottom: 4px;">
              HISOBLANGAN DAROMADLAR (KIRIM)
            </div>
            <table class="payslip-table">
              <tr>
                <td>Asosiy Oklad (Oylik stavka):</td>
                <td style="text-align: right; font-family: var(--font-mono); font-weight: 700;">${formatUZS(base)}</td>
              </tr>
              <tr style="background: rgba(56, 189, 248, 0.08);">
                <td style="font-weight: 700; color: #0284c7;">${esc(dutyItemLabel)}</td>
                <td style="text-align: right; font-family: var(--font-mono); font-weight: 800; color: #0284c7;">+${formatUZS(dutyEarnings)}</td>
              </tr>
              <tr>
                <td>Statsionar Bemorlar Gonorari:</td>
                <td style="text-align: right; font-family: var(--font-mono);">—</td>
              </tr>
              <tr>
                <td>Detoksikatsiya / Chaqiruv Bonusi:</td>
                <td style="text-align: right; font-family: var(--font-mono);">—</td>
              </tr>
              <tr style="background: #f1f5f9; font-weight: 800;">
                <td>JAMI HISOBLANDI (GROSS):</td>
                <td style="text-align: right; font-family: var(--font-mono); color: #0284c7;">${formatUZS(gross)}</td>
              </tr>
            </table>
          </div>

          <div>
            <div style="font-weight: 700; color: #0f172a; margin-bottom: 6px; border-bottom: 2px solid #e11d48; padding-bottom: 4px;">
              USHLANMALAR VA SOLIQLAR (CHIQIM)
            </div>
            <table class="payslip-table">
              <tr>
                <td>Jismoniy Shaxslar Daromad Solig'i (${pct(rates.income_tax, 0.12)}):</td>
                <td style="text-align: right; font-family: var(--font-mono);">${formatUZS(tax)}</td>
              </tr>
              <tr>
                <td>INPS Shaxsiy Pensiya (${pct(rates.pension, 0.001)}):</td>
                <td style="text-align: right; font-family: var(--font-mono);">${formatUZS(inps)}</td>
              </tr>
              <tr style="background: #fef2f2; font-weight: 800;">
                <td>JAMI USHLANMALAR:</td>
                <td style="text-align: right; font-family: var(--font-mono); color: #e11d48;">${formatUZS(totalDeductions)}</td>
              </tr>
            </table>
          </div>
        </div>

        <div class="payslip-net-box">
          <div>
            <div style="font-size: 0.8rem; color: #64748b; font-weight: 700; text-transform: uppercase;">XODIMGA TO'LANADIGAN SOF SUMMA (NET PAYABLE)</div>
            <div style="font-size: 1.6rem; font-weight: 900; font-family: var(--font-mono); color: #0284c7;">${formatUZS(net)}</div>
          </div>
          <div style="text-align: right; font-size: 0.75rem; color: #64748b;">
            To'lov Shakli: Bank Plastik Kartasiga<br>
            Holat: <span style="color: #0284c7; font-weight: 700;">Hisoblangan</span>
          </div>
        </div>
      </div>
    `;

    modal.classList.add('active');
  }

  function openStaffDossier(staffId) {
    const staff = State.staff.find(s => s.id === staffId);
    if (!staff) return;

    const modal = document.getElementById('staff-dossier-modal');
    const content = document.getElementById('staff-dossier-content');
    if (!modal || !content) return;

    const dutyKey = dutyKeyFor(staff);
    let tariffLabel = 'Belgilanmagan';
    if (dutyKey === 'doctor_night') tariffLabel = `Shifokor Tungi (${formatUZS(tariff('doctor_night'))})`;
    else if (dutyKey === 'nurse_24h') tariffLabel = `Hamshira 24 Soatlik (${formatUZS(tariff('nurse_24h'))})`;
    else if (dutyKey === 'sanitar_24h') tariffLabel = `Sanitarka 24 Soatlik (${formatUZS(tariff('sanitar_24h'))})`;

    content.innerHTML = `
      <div style="display: flex; align-items: center; gap: 1.25rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border-subtle);">
        <div class="staff-avatar" style="width: 64px; height: 64px; font-size: 1.5rem; background: ${staff.avatar_color || '#4f46e5'};">
          ${staff.full_name.split(' ').map(n => n[0]).join('').substring(0, 2)}
        </div>
        <div>
          <h2 style="color: #ffffff; font-size: 1.25rem; font-weight: 800;">${staff.full_name}</h2>
          <div style="color: var(--indigo-light); font-weight: 600; font-size: 0.85rem;">${staff.role_title_uz || staff.role}</div>
          <div style="color: var(--text-muted); font-size: 0.78rem;">ID: ${staff.id} • Ishga qabul: ${formatDate(staff.hire_date)}</div>
        </div>
      </div>

      <div class="form-grid" style="margin-top: 1rem;">
        <div class="form-group">
          <label class="form-label">Bo'lim & Ixtisoslik</label>
          <div style="font-weight: 600; color: #ffffff;">${esc(staff.department_name_uz || staff.department || '—')} — ${esc(staff.specialty || '—')}</div>
        </div>
        <div class="form-group">
          <label class="form-label">Navbatchilik Tarifi & Stavka</label>
          <div style="font-weight: 700; color: #38bdf8;">${tariffLabel}</div>
        </div>
        <div class="form-group">
          <label class="form-label">Shu Oydagi Navbatchiliklari</label>
          <div style="font-weight: 800; color: #34d399; font-family: var(--font-mono);">${staff.monthly_duty_count || 0} smena (${formatUZS(staff.monthly_duty_earnings)})</div>
        </div>
        <div class="form-group">
          <label class="form-label">Asosiy Oylik Oklad</label>
          <div style="font-weight: 700; color: #ffffff; font-family: var(--font-mono);">${formatUZS(staff.base_salary)}</div>
        </div>
        <div class="form-group">
          <label class="form-label">Telefon & Aloqa</label>
          <div style="font-weight: 600; color: #ffffff;">${staff.phone} (${staff.telegram || '—'})</div>
        </div>
        <div class="form-group">
          <label class="form-label">Tibbiy Toifasi</label>
          <div style="font-weight: 600; color: #ffffff;">${esc(staff.category || '—')}</div>
        </div>
        <div class="form-group">
          <label class="form-label">KPI Reyting</label>
          <div style="font-weight: 700; color: #fbbf24;"><i class="fas fa-star"></i> ${staff.kpi_rating || 5.0} / 5.0</div>
        </div>
      </div>

      <div style="margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid var(--border-subtle); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem;">
        ${staff.status === 'inactive' ? `
        <button class="btn-portal btn-success-portal" style="padding: 6px 14px; font-size: 0.82rem;" onclick="window.FMH_HR.reactivateStaff('${esc(staff.id)}')">
          <i class="fas fa-user-check"></i> Qayta Faollashtirish
        </button>` : `
        <button class="btn-portal btn-danger-portal" style="background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); padding: 6px 14px; font-size: 0.82rem;" onclick="window.FMH_HR.deleteStaff('${esc(staff.id)}')">
          <i class="fas fa-user-slash"></i> Xodimni Faolsizlantirish
        </button>`}
        <div style="display: flex; gap: 0.5rem;">
          <button class="btn-portal btn-outline-portal" style="padding: 6px 14px; font-size: 0.82rem; border-color: rgba(245, 158, 11, 0.5); color: #fbbf24;" onclick="window.FMH_HR.openEditStaffModal('${staff.id}')">
            <i class="fas fa-edit"></i> Tahrirlash
          </button>
          <button class="btn-portal btn-primary-portal" style="padding: 6px 16px; font-size: 0.82rem;" onclick="window.FMH_HR.generatePayslip('${staff.id}')">
            <i class="fas fa-file-invoice-dollar"></i> Oylik Varaqasi (Payslip)
          </button>
        </div>
      </div>
    `;

    modal.classList.add('active');
  }

  async function deleteStaff(staffId) {
    const staff = State.staff.find(s => s.id === staffId);
    const staffName = staff ? staff.full_name : staffId;
    // The server never deletes a staff row (clinical records name their
    // author through it); it deactivates. The dialog used to promise a
    // permanent delete.
    const confirmed = await fmhConfirm({
      title: "Xodimni Faolsizlantirish",
      message: `<strong>${esc(staffName)}</strong> faolsizlantirilsinmi? U navbatchilik va shifokorlar ro'yxatlarida ko'rinmaydi, lekin barcha yozuvlari saqlanadi va keyin qayta faollashtirish mumkin.`,
      confirmText: "Faolsizlantirish",
      cancelText: "Bekor Qilish",
      type: 'danger'
    });
    if (!confirmed) {
      return;
    }

    // Removed from the list only once the server agrees. The answer used to
    // be ignored, so a refused delete still said "o'chirildi" and the person
    // came back on the next load.
    try {
      const res = await fetch('/api/staff/' + encodeURIComponent(staffId), { method: 'DELETE' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || `Xodim faolsizlantirilmadi (${res.status})`, 'error');
        return;
      }
    } catch (err) {
      showToast("Server bilan aloqa yo'q. Xodim faolsizlantirilmadi.", 'error');
      return;
    }

    setStaffActive(staffId, false);
    closeAllModals();
    showToast(`${staffName} faolsizlantirildi. Uni "Faollashtirish" tugmasi bilan qaytarish mumkin.`, 'success');
  }

  function setStaffActive(staffId, active) {
    const st = State.staff.find(s => s.id === staffId);
    if (st) {
      st.status = active ? 'active' : 'inactive';
      st.is_active = active ? 1 : 0;
    }
    saveToLocalStorage();
    recalculateStaffDutyCounts();
    renderAll();
  }

  // POST /api/staff/<id>/reactivate only flips is_active back; it does not
  // rewrite the record from what this page holds.
  async function reactivateStaff(staffId) {
    const staff = State.staff.find(s => s.id === staffId);
    const staffName = staff ? staff.full_name : staffId;
    try {
      const res = await fetch('/api/staff/' + encodeURIComponent(staffId) + '/reactivate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}'
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || `Xodim faollashtirilmadi (${res.status})`, 'error');
        return;
      }
    } catch (err) {
      showToast("Server bilan aloqa yo'q. Xodim faollashtirilmadi.", 'error');
      return;
    }
    setStaffActive(staffId, true);
    closeAllModals();
    showToast(`${staffName} qayta faollashtirildi.`, 'success');
  }

  // ==========================================================================
  // SMART EMPLOYEE ONBOARDING & PRESET ENGINE
  // ==========================================================================
  const STAFF_PRESETS = {
    doctor: {
      key: 'doctor',
      role: 'doctor',
      role_title_uz: 'Shifokor-Narkolog',
      department: 'doctors',
      department_name_uz: 'Shifokorlar Bo\'limi',
      specialty: 'Detoksikatsiya, Narkologiya',
      category: 'Oliy toifa',
      base_salary: 12000000,
      detox_procedure_fee: 150000,
      shift_type: 'day_standard',
      assigned_floor: 'all',
      duty_rate_type: 'doctor_night',
      bls_cpr_certified: true,
      is_clinical: true
    },
    toxicologist: {
      key: 'toxicologist',
      role: 'doctor',
      role_title_uz: 'Toksikolog-Reanimatolog',
      department: 'doctors',
      department_name_uz: 'Shifokorlar Bo\'limi',
      specialty: 'Intensiv Terapiya, Toksikologiya',
      category: 'Oliy toifa',
      base_salary: 14000000,
      detox_procedure_fee: 200000,
      shift_type: 'shift_24h',
      assigned_floor: '1',
      duty_rate_type: 'doctor_night',
      bls_cpr_certified: true,
      is_clinical: true
    },
    nurse: {
      key: 'nurse',
      role: 'nurse',
      role_title_uz: 'Navbatchi Hamshira',
      department: 'nurses',
      department_name_uz: 'Hamshiralar Bo\'limi',
      specialty: 'Muolaja & Infuzion Terapiya',
      category: '1-toifa',
      base_salary: 6000000,
      detox_procedure_fee: 100000,
      shift_type: 'shift_24h',
      assigned_floor: 'all',
      duty_rate_type: 'nurse_24h',
      bls_cpr_certified: true,
      is_clinical: true
    },
    receptionist: {
      key: 'receptionist',
      role: 'receptionist',
      role_title_uz: 'Qabulxona Administratori',
      department: 'administration',
      department_name_uz: 'Ma\'muriyat & Qabulxona',
      specialty: 'Mijozlar bilan ishlash & CRM',
      category: 'Mutaxassis',
      base_salary: 5000000,
      detox_procedure_fee: 0,
      shift_type: 'day_standard',
      assigned_floor: '1',
      duty_rate_type: 'none',
      bls_cpr_certified: false,
      is_clinical: false
    },
    accountant: {
      key: 'accountant',
      role: 'accountant',
      role_title_uz: 'Bosh Buxgalter',
      department: 'administration',
      department_name_uz: 'Buxgalteriya & Moliya',
      specialty: 'Buxgalteriya hisobi va soliqlar',
      category: 'Mutaxassis',
      base_salary: 9000000,
      detox_procedure_fee: 0,
      shift_type: 'day_standard',
      assigned_floor: 'all',
      duty_rate_type: 'none',
      bls_cpr_certified: false,
      is_clinical: false
    },
    sanitar: {
      key: 'sanitar',
      role: 'sanitar',
      role_title_uz: 'Kichik Tibbiy Xodim (Sanitarka)',
      department: 'support',
      department_name_uz: 'Xizmat & Sanitariya',
      specialty: 'Sanitariya & Statsionar parvarish',
      category: 'Mutaxassis',
      base_salary: 3800000,
      detox_procedure_fee: 0,
      shift_type: 'shift_24h',
      assigned_floor: 'all',
      duty_rate_type: 'sanitar_24h',
      bls_cpr_certified: false,
      is_clinical: false
    },
    security: {
      key: 'security',
      role: 'admin',
      role_title_uz: 'Xavfsizlik Xodimi (Qo\'riqchi)',
      department: 'support',
      department_name_uz: 'Xizmat & Xavfsizlik',
      specialty: '24/7 Nazorat va Xavfsizlik',
      category: 'Mutaxassis',
      base_salary: 4000000,
      detox_procedure_fee: 0,
      shift_type: 'shift_24h',
      assigned_floor: 'all',
      duty_rate_type: 'none',
      bls_cpr_certified: false,
      is_clinical: false
    }
  };

  function formatUzbekPhone(val) {
    if (!val) return '+998 ';
    let digits = val.replace(/\D/g, '');
    if (digits.startsWith('998')) {
      digits = digits.substring(3);
    }
    digits = digits.substring(0, 9);
    let res = '+998';
    if (digits.length > 0) res += ' (' + digits.substring(0, 2);
    if (digits.length >= 2) res += ') ' + digits.substring(2, 5);
    if (digits.length >= 5) res += '-' + digits.substring(5, 7);
    if (digits.length >= 7) res += '-' + digits.substring(7, 9);
    return res;
  }

  function updateSalaryPreview(amount) {
    const preview = document.getElementById('salary-formatted-preview');
    if (!preview) return;
    const num = parseFloat(amount) || 0;
    preview.textContent = formatUZS(num);
  }

  function switchStaffFormMode(mode) {
    const btnQuick = document.getElementById('btn-mode-quick');
    const btnDetailed = document.getElementById('btn-mode-detailed');
    const extendedSection = document.getElementById('extended-details-section');

    if (mode === 'detailed') {
      if (btnQuick) btnQuick.classList.remove('active');
      if (btnDetailed) btnDetailed.classList.add('active');
      if (extendedSection) {
        extendedSection.classList.remove('is-hidden');
        setTimeout(() => {
          extendedSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 50);
      }
    } else {
      if (btnQuick) btnQuick.classList.add('active');
      if (btnDetailed) btnDetailed.classList.remove('active');
      if (extendedSection) extendedSection.classList.add('is-hidden');
    }
  }

  function toggleClinicalSection(role) {
    const clinicalSection = document.getElementById('clinical-details-section');
    if (!clinicalSection) return;
    const isClinical = (role === 'doctor' || role === 'chief_doctor' || role === 'nurse');
    if (isClinical) {
      clinicalSection.classList.remove('is-hidden');
    } else {
      clinicalSection.classList.add('is-hidden');
    }
  }

  function applyStaffPreset(presetKey) {
    const preset = STAFF_PRESETS[presetKey];
    if (!preset) return;

    // Highlight active preset chip
    const chips = document.querySelectorAll('.staff-preset-chip');
    chips.forEach(c => {
      if (c.dataset.preset === presetKey) c.classList.add('active');
      else c.classList.remove('active');
    });

    const form = document.getElementById('add-staff-form');
    if (!form) return;

    if (form.role) form.role.value = preset.role;
    if (form.role_title_uz) form.role_title_uz.value = preset.role_title_uz;
    if (form.department) form.department.value = preset.department;
    if (form.specialty) form.specialty.value = preset.specialty;
    if (form.category) form.category.value = preset.category;
    if (form.base_salary) {
      form.base_salary.value = preset.base_salary;
      updateSalaryPreview(preset.base_salary);
    }
    if (form.detox_procedure_fee) form.detox_procedure_fee.value = preset.detox_procedure_fee;
    if (form.shift_type) form.shift_type.value = preset.shift_type;
    if (form.assigned_floor) form.assigned_floor.value = preset.assigned_floor;
    if (form.bls_cpr_certified) form.bls_cpr_certified.checked = preset.bls_cpr_certified;

    toggleClinicalSection(preset.role);
  }

  function openAddStaffModal() {
    const modal = document.getElementById('add-staff-modal');
    const form = document.getElementById('add-staff-form');
    if (!modal || !form) return;

    // Reset form to clean add state
    form.reset();
    removeExtraRoleOptions(form);
    const idInput = document.getElementById('staff-form-id');
    if (idInput) idInput.value = '';

    const titleEl = document.getElementById('staff-modal-title');
    if (titleEl) titleEl.textContent = 'Yangi Xodim Qo\'shish';

    const iconEl = document.getElementById('staff-modal-icon');
    if (iconEl) iconEl.className = 'fas fa-user-plus';

    const pillEl = document.getElementById('staff-edit-pill');
    if (pillEl) pillEl.classList.remove('visible');

    const submitText = document.getElementById('staff-submit-text');
    if (submitText) submitText.textContent = 'Xodimni Saqlash';

    // Set today's date dynamically
    const todayStr = new Date().toISOString().split('T')[0];
    const hireDateInp = document.getElementById('staff-input-hire-date');
    if (hireDateInp) hireDateInp.value = todayStr;

    // Default preset and quick mode
    applyStaffPreset('doctor');
    switchStaffFormMode('quick');

    const phoneInp = document.getElementById('staff-input-phone');
    if (phoneInp && !phoneInp.value) phoneInp.value = '+998 ';

    modal.classList.add('active');
    setTimeout(() => {
      const nameInp = document.getElementById('staff-input-name');
      if (nameInp) nameInp.focus();
    }, 100);
  }

  function removeExtraRoleOptions(form) {
    if (!form || !form.role) return;
    Array.from(form.role.options).filter(o => o.dataset.extraRole).forEach(o => o.remove());
  }

  function openEditStaffModal(staffId) {
    const staff = State.staff.find(s => s.id === staffId);
    if (!staff) return;

    closeAllModals();

    const modal = document.getElementById('add-staff-modal');
    const form = document.getElementById('add-staff-form');
    if (!modal || !form) return;

    form.reset();
    removeExtraRoleOptions(form);

    const idInput = document.getElementById('staff-form-id');
    if (idInput) idInput.value = staff.id;

    const titleEl = document.getElementById('staff-modal-title');
    if (titleEl) titleEl.textContent = `Xodimni Tahrirlash: ${staff.full_name}`;

    const iconEl = document.getElementById('staff-modal-icon');
    if (iconEl) iconEl.className = 'fas fa-user-edit';

    const pillEl = document.getElementById('staff-edit-pill');
    if (pillEl) pillEl.classList.add('visible');

    const submitText = document.getElementById('staff-submit-text');
    if (submitText) submitText.textContent = 'O\'zgarishlarni Saqlash';

    // Populate existing details
    if (form.full_name) form.full_name.value = staff.full_name || '';
    if (form.phone) form.phone.value = staff.phone || '+998 ';
    if (form.role) {
      // A pharmacist, HR manager, ward manager or kitchen worker has no
      // option in this list; the select went blank and the save turned them
      // into 'admin'. Offer their own role for this edit.
      if (staff.role && !Array.from(form.role.options).some(o => o.value === staff.role)) {
        const opt = document.createElement('option');
        opt.value = staff.role;
        opt.textContent = staff.role_title_uz || staff.role;
        opt.dataset.extraRole = '1';
        form.role.appendChild(opt);
      }
      form.role.value = staff.role || 'doctor';
    }
    if (form.role_title_uz) form.role_title_uz.value = staff.role_title_uz || '';
    if (form.department) form.department.value = staff.department || 'doctors';
    if (form.specialty) form.specialty.value = staff.specialty || '';
    // Saved on the server now (staff HR columns); an empty value stays
    // empty instead of showing a guess that the next save would store.
    if (form.category) form.category.value = staff.category || '';
    if (form.base_salary) {
      // A salary of 0 (a sanitarka paid only by duty shifts) is real; '||'
      // replaced it with 10 000 000, which the next save then stored.
      const sal = staff.base_salary ?? staff.salary_base ?? '';
      form.base_salary.value = sal;
      updateSalaryPreview(sal);
    }
    if (form.detox_procedure_fee) form.detox_procedure_fee.value = (staff.detox_procedure_fee !== null && staff.detox_procedure_fee !== undefined) ? staff.detox_procedure_fee : '';
    // The server stores day/night/24h/rotating; the form offers its own names.
    if (form.shift_type) form.shift_type.value = ({ day: 'day_standard', night: 'night_only', '24h': 'shift_24h', rotating: 'on_call' })[staff.shift_type] || staff.shift_type || 'day_standard';
    if (form.assigned_floor) form.assigned_floor.value = staff.assigned_floor || '';
    if (form.bls_cpr_certified) form.bls_cpr_certified.checked = Number(staff.bls_cpr_certified) === 1 || staff.bls_cpr_certified === true;
    if (form.email) form.email.value = staff.email || '';
    if (form.telegram) form.telegram.value = staff.telegram || '';
    if (form.passport_pinfl) form.passport_pinfl.value = staff.passport_pinfl || '';
    if (form.experience_years) form.experience_years.value = (staff.experience_years !== null && staff.experience_years !== undefined) ? staff.experience_years : '';
    if (form.hire_date) form.hire_date.value = staff.hire_date ? String(staff.hire_date).slice(0, 10) : '';

    // Remove active preset highlight because it's a custom edit
    document.querySelectorAll('.staff-preset-chip').forEach(c => c.classList.remove('active'));

    toggleClinicalSection(staff.role);
    switchStaffFormMode('detailed');

    modal.classList.add('active');
  }

  async function handleAddStaffSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const editingId = form.staff_id ? form.staff_id.value.trim() : '';
    const isEdit = Boolean(editingId);

    const roleVal = form.role ? form.role.value : 'doctor';
    let dutyRate = 'none';
    if (roleVal === 'doctor' || roleVal === 'chief_doctor') dutyRate = 'doctor_night';
    else if (roleVal === 'nurse') dutyRate = 'nurse_24h';
    else if (roleVal === 'sanitar') dutyRate = 'sanitar_24h';

    // A new employee gets its id from the server. The page used to build
    // STF-<role>-<staff count + 1>, which is often an id someone already
    // has, and the server's upsert then overwrote that person's record.
    const staffId = editingId;

    const existingStaff = isEdit ? State.staff.find(s => s.id === staffId) : null;

    const departmentVal = form.department ? form.department.value : (roleVal === 'nurse' ? 'nurses' : (roleVal === 'doctor' ? 'doctors' : 'administration'));
    let departmentNameUz = 'Shifokorlar Bo\'limi';
    if (departmentVal === 'nurses') departmentNameUz = 'Hamshiralar Bo\'limi';
    else if (departmentVal === 'administration') departmentNameUz = 'Ma\'muriyat & Qabulxona';
    else if (departmentVal === 'diagnostics') departmentNameUz = 'Diagnostika & Laboratoriya';
    else if (departmentVal === 'support') departmentNameUz = 'Xizmat & Xavfsizlik';

    const staffRecord = {
      id: staffId,
      full_name: (form.full_name ? form.full_name.value : '').trim(),
      role: roleVal,
      // The fields below are stored on the server (staff HR columns) and
      // used to be filled with guesses (title, 5 years, today's hire date,
      // 'Oliy toifa') when left blank. A blank now stays blank.
      role_title_uz: form.role_title_uz ? form.role_title_uz.value.trim() : (existingStaff?.role_title_uz || ''),
      department: departmentVal,
      department_name_uz: departmentNameUz,
      specialty: form.specialty ? form.specialty.value.trim() : (existingStaff?.specialty || ''),
      phone: (form.phone ? form.phone.value : '').trim(),
      email: (form.email && form.email.value.trim()) ? form.email.value.trim() : (existingStaff?.email || ''),
      telegram: form.telegram ? form.telegram.value.replace('@', '').trim() : (existingStaff?.telegram || ''),
      passport_pinfl: form.passport_pinfl ? form.passport_pinfl.value.trim() : (existingStaff?.passport_pinfl || ''),
      hire_date: form.hire_date ? form.hire_date.value : (existingStaff?.hire_date || ''),
      experience_years: form.experience_years ? form.experience_years.value.trim() : (existingStaff?.experience_years ?? ''),
      category: form.category ? form.category.value : (existingStaff?.category || ''),
      shift_type: form.shift_type ? form.shift_type.value : (existingStaff?.shift_type || 'day_standard'),
      assigned_floor: form.assigned_floor ? form.assigned_floor.value : (existingStaff?.assigned_floor || ''),
      bls_cpr_certified: form.bls_cpr_certified ? Boolean(form.bls_cpr_certified.checked) : (existingStaff?.bls_cpr_certified ?? ''),
      base_salary: form.base_salary ? (parseFloat(form.base_salary.value) || 0) : (existingStaff?.base_salary || 0),
      duty_rate_type: dutyRate,
      monthly_duty_count: existingStaff?.monthly_duty_count || 0,
      monthly_duty_earnings: existingStaff?.monthly_duty_earnings || 0,
      detox_procedure_fee: form.detox_procedure_fee ? form.detox_procedure_fee.value.trim() : (existingStaff?.detox_procedure_fee ?? ''),
      kpi_rating: existingStaff?.kpi_rating || 5.0,
      status: existingStaff?.status || 'active',
      avatar_color: existingStaff?.avatar_color || (roleVal === 'doctor' ? '#0284c7' : (roleVal === 'nurse' ? '#10b981' : '#6366f1'))
    };

    try {
      const res = await fetch('/api/staff', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(staffRecord)
      });
      // A refused or unsent save used to be added to the list and reported
      // as saved, so HR saw an employee nobody else could.
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || `Xodim saqlanmadi (${res.status})`, 'error');
        return;
      }
      const data = await res.json();
      if (data.id) staffRecord.id = data.id;
      else if (data.staff && data.staff.id) staffRecord.id = data.staff.id;
      // Keep what the server stored (cleaned telegram, numbers, NULLs).
      if (data.staff) {
        ['hire_date', 'experience_years', 'category', 'role_title_uz', 'department', 'assigned_floor',
         'telegram', 'detox_procedure_fee', 'bls_cpr_certified', 'role'].forEach(k => {
          if (k in data.staff) staffRecord[k] = data.staff[k];
        });
        if (!staffRecord.role_title_uz) staffRecord.role_title_uz = staffRecord.role;
        staffRecord.status = 'active';
      }
    } catch (err) {
      showToast("Server bilan aloqa yo'q. Xodim saqlanmadi.", 'error');
      return;
    }

    if (!State.staff) State.staff = [];
    const existsIdx = State.staff.findIndex(s => s.id === staffRecord.id);
    if (existsIdx >= 0) {
      State.staff[existsIdx] = { ...State.staff[existsIdx], ...staffRecord };
    } else {
      State.staff.unshift(staffRecord);
    }

    saveToLocalStorage();
    renderAll();
    try { form.reset(); } catch(e) {}
    closeAllModals();
    showToast(isEdit ? `${staffRecord.full_name} ma'lumotlari yangilandi!` : `${staffRecord.full_name} muvaffaqiyatli qo'shildi!`, 'success');
  }

  // Times only make sense for someone who came; minutes late only for 'late'.
  function syncAttendanceForm(form) {
    if (!form || !form.status) return;
    const away = ['absent', 'on_leave', 'sick'].indexOf(form.status.value) >= 0;
    ['check_in', 'check_out'].forEach(n => {
      if (!form[n]) return;
      form[n].disabled = away;
      if (away) form[n].value = '';
    });
    if (form.late_minutes) {
      const late = form.status.value === 'late';
      form.late_minutes.disabled = !late;
      if (!late) form.late_minutes.value = '';
    }
  }

  function openLogAttendanceModal(staffId) {
    const staff = State.staff.find(s => s.id === staffId);
    if (!staff) return;

    State.selectedStaffId = staffId;
    const modal = document.getElementById('log-attendance-modal');
    const form = document.getElementById('log-attendance-form');
    const staffNameEl = document.getElementById('att-modal-staff-name');
    if (staffNameEl) staffNameEl.textContent = `${staff.full_name} — ${formatDate(State.attendanceDate)}`;

    // Open on what is already saved for that day, so a correction starts
    // from the record instead of from made-up defaults.
    if (form) {
      form.reset();
      const att = attendanceFor(staffId);
      const staffShift = { day: 'day', night: 'night', '24h': '24h' }[staff.shift_type] || '';
      if (form.status) form.status.value = att ? att.status : '';
      if (form.shift_type) form.shift_type.value = att ? att.shift_type : staffShift;
      if (form.check_in) form.check_in.value = att && att.check_in_time ? att.check_in_time : '';
      if (form.check_out) form.check_out.value = att && att.check_out_time ? att.check_out_time : '';
      if (form.late_minutes) form.late_minutes.value = att && att.late_minutes !== null && att.late_minutes !== undefined ? att.late_minutes : '';
      if (form.notes) form.notes.value = att && att.notes ? att.notes : '';
      syncAttendanceForm(form);
    }
    if (modal) modal.classList.add('active');
  }

  // Attendance is read back from the server after every save, so the sheet
  // shows what was stored (including hours worked out from the times).
  async function reloadAttendance() {
    try {
      const res = await fetch('/api/hr/data');
      if (!res.ok) return false;
      const data = await res.json();
      State.attendance = Array.isArray(data.attendance_records) ? data.attendance_records : [];
      return true;
    } catch (e) {
      return false;
    }
  }

  async function handleLogAttendanceSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const staffId = State.selectedStaffId;
    if (!staffId) return;

    // Used to be written to this browser only (and to a fixed date before
    // that), so nobody else ever saw it.
    const payload = {
      staff_id: staffId,
      work_date: State.attendanceDate,
      status: form.status ? form.status.value : '',
      shift_type: form.shift_type ? form.shift_type.value : '',
      check_in: form.check_in && !form.check_in.disabled ? form.check_in.value : '',
      check_out: form.check_out && !form.check_out.disabled ? form.check_out.value : '',
      late_minutes: form.late_minutes && !form.late_minutes.disabled ? form.late_minutes.value : '',
      notes: form.notes ? form.notes.value.trim() : ''
    };

    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;
    try {
      const res = await fetch('/api/hr/attendance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || `Davomat saqlanmadi (${res.status})`, 'error');
        return;
      }
      const data = await res.json().catch(() => ({}));
      const reloaded = await reloadAttendance();
      if (!reloaded && data.attendance) {
        // Saved, but the list could not be re-read: show the saved row.
        State.attendance = State.attendance.filter(a =>
          !(a.staff_id === staffId && String(a.work_date || '').slice(0, 10) === payload.work_date));
        State.attendance.unshift(data.attendance);
      }
    } catch (err) {
      showToast("Server bilan aloqa yo'q. Davomat saqlanmadi.", 'error');
      return;
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }

    renderAttendanceSheet();
    updateKPIs();
    closeAllModals();
    showToast('Davomat saqlandi.', 'success');
  }

  async function exportAllToExcel() {
    if (typeof XLSX === 'undefined') {
      showToast('Excel moduli yuklanmoqda...', 'danger');
      return;
    }

    // Payroll comes from the server; without it there is nothing honest to
    // export (the old sheet recomputed pay with invented bonuses).
    const payroll = State.payroll || await loadPayroll();
    if (!payroll || !Array.isArray(payroll.staff)) return;

    const wb = XLSX.utils.book_new();

    const scheduleData = State.monthlySchedule.map(s => ({
      'Sana': s.date,
      'Kun': s.day_name,
      'Holat': s.suggested ? 'Taklif (saqlanmagan)' : 'Saqlangan',
      'Brigada': s.brigade_name || '—',
      [`Tungi Shifokor (${formatUZS(tariff('doctor_night'))})`]: s.doctor_night_name,
      [`24h Hamshira (Butun Bino — ${formatUZS(tariff('nurse_24h'))})`]: s.nurse_name,
      [`24h Hamshira (2-Qavat — ${formatUZS(tariff('nurse_24h'))})`]: s.nurse_f2_name,
      [`24h Sanitarka (${formatUZS(tariff('sanitar_24h'))})`]: s.sanitar_name,
      '24/7 On-Call Shifokor': s.oncall_doc_name,
      'Kunlik Navbatchilik Chiqimi': s.daily_duty_cost
    }));
    const wsSchedule = XLSX.utils.json_to_sheet(scheduleData);
    XLSX.utils.book_append_sheet(wb, wsSchedule, '24-7 Navbatchilik Jadvali');

    const rates = payroll.rates || {};
    const pct = (r, dflt) => `${Math.round((r !== undefined ? Number(r) : dflt) * 1000) / 10}%`;
    const payData = payroll.staff.map(r => ({
      'Xodim ID': r.staff_id,
      'F.I.Sh': r.full_name,
      'Lavozim': staffTitle(r.staff_id, r.role),
      'Asosiy Oklad': r.base_salary,
      'Navbatchiliklar Soni': r.duty_shifts || 0,
      'Navbatchilik Tafsiloti': dutyPayLabel(r) || '—',
      'Navbatchilik To\'lovi': r.duty_pay,
      'Detox & Statsionar Bonusi': '—',
      'Jami Gross': r.gross,
      [`Daromad Solig'i (${pct(rates.income_tax, 0.12)})`]: r.income_tax,
      [`INPS (${pct(rates.pension, 0.001)})`]: r.pension,
      'Sof To\'lanadigan (Net)': r.net,
      'Holat': 'Hisoblangan'
    }));
    const wsPay = XLSX.utils.json_to_sheet(payData);
    XLSX.utils.book_append_sheet(wb, wsPay, 'Oylik Maosh Qaydi');

    XLSX.writeFile(wb, `FMH_Navbatchilik_va_Oyliklar_${payroll.month || monthKey()}.xlsx`);
    showToast('24/7 Navbatchilik va Oyliklar Excel hisoboti yuklab olindi!', 'success');
  }

  function closeAllModals() {
    document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('active'));
  }

  function switchTab(tabId) {
    State.activeTab = tabId;
    // Payroll is the server's; refetch on open so it reflects the latest saves.
    if (tabId === 'payroll') loadPayroll();
    document.querySelectorAll('.portal-tabs .tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId);
    });

    document.querySelectorAll('.tab-panel').forEach(panel => {
      panel.classList.toggle('active', panel.id === `tab-panel-${tabId}`);
    });
  }

  function updateKPIs() {
    const totalStaff = State.staff.filter(s => s.status !== 'inactive').length;
    // Who came TODAY; this used to count every attendance row ever saved.
    const today = todayIso();
    const todayAtt = State.attendance.filter(a =>
      String(a.work_date || '').slice(0, 10) === today && (a.status === 'present' || a.status === 'late'));

    // Net payroll total from the server (was recomputed here with the
    // invented bonuses).
    const totals = State.payroll && State.payroll.totals;

    const elTotal = document.getElementById('stat-total-staff');
    if (elTotal) elTotal.textContent = `${totalStaff} nafar`;

    const elDuty = document.getElementById('stat-on-duty');
    if (elDuty) elDuty.textContent = `${todayAtt.length} nafar`;

    const elPayroll = document.getElementById('stat-payroll-budget');
    if (elPayroll) elPayroll.textContent = totals ? formatUZS(totals.net) : '—';

    const chipStaff = document.getElementById('chip-staff-count');
    if (chipStaff) chipStaff.textContent = totalStaff;
    const chipDuty = document.getElementById('chip-duty-count');
    if (chipDuty) chipDuty.textContent = todayAtt.length;

    const bStaff = document.getElementById('badge-staff-count');
    if (bStaff) bStaff.textContent = totalStaff;
    const bAtt = document.getElementById('badge-att-count');
    if (bAtt) bAtt.textContent = todayAtt.length;
  }

  function renderAll() {
    updateKPIs();
    renderStaffDirectory();
    renderShiftRoster();
    renderAttendanceSheet();
    renderPayrollTable();
  }

  function setupEventListeners() {
    document.querySelectorAll('.portal-tabs .tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const tab = btn.getAttribute('data-tab');
        if (tab) switchTab(tab);
      });
    });

    const searchInput = document.getElementById('search-staff-input');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        State.searchQuery = e.target.value;
        renderStaffDirectory();
      });
    }

    const deptSelect = document.getElementById('filter-staff-dept');
    if (deptSelect) {
      deptSelect.addEventListener('change', (e) => {
        State.staffFilterDept = e.target.value;
        renderStaffDirectory();
      });
    }

    const statusSelect = document.getElementById('filter-staff-status');
    if (statusSelect) {
      statusSelect.addEventListener('change', (e) => {
        State.staffFilterStatus = e.target.value;
        renderStaffDirectory();
      });
    }

    document.querySelectorAll('.modal-close-btn, .btn-modal-cancel').forEach(btn => {
      btn.addEventListener('click', closeAllModals);
    });

    document.querySelectorAll('.modal-overlay').forEach(overlay => {
      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeAllModals();
      });
    });

    const addStaffForm = document.getElementById('add-staff-form');
    if (addStaffForm) {
      addStaffForm.addEventListener('submit', handleAddStaffSubmit);
    }

    // Smart Preset Chips
    document.querySelectorAll('.staff-preset-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        if (chip.dataset.preset) applyStaffPreset(chip.dataset.preset);
      });
    });

    // Salary formatting & quick amount buttons
    const salaryInp = document.getElementById('staff-input-salary');
    if (salaryInp) {
      salaryInp.addEventListener('input', (e) => updateSalaryPreview(e.target.value));
    }

    document.querySelectorAll('.salary-quick-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const inp = document.getElementById('staff-input-salary');
        if (!inp) return;
        if (btn.dataset.amount) {
          inp.value = btn.dataset.amount;
        } else if (btn.dataset.increment) {
          const cur = parseFloat(inp.value) || 0;
          inp.value = cur + parseFloat(btn.dataset.increment);
        }
        updateSalaryPreview(inp.value);
      });
    });

    // Phone input auto-formatting (+998)
    const phoneInp = document.getElementById('staff-input-phone');
    if (phoneInp) {
      phoneInp.addEventListener('input', (e) => {
        e.target.value = formatUzbekPhone(e.target.value);
      });
      phoneInp.addEventListener('focus', (e) => {
        if (!e.target.value) e.target.value = '+998 ';
      });
    }

    // Role select change
    const roleSelect = document.getElementById('staff-input-role');
    if (roleSelect) {
      roleSelect.addEventListener('change', (e) => {
        const role = e.target.value;
        toggleClinicalSection(role);
        const deptSelect = document.getElementById('staff-input-dept');
        if (deptSelect) {
          if (role === 'doctor') deptSelect.value = 'doctors';
          else if (role === 'nurse') deptSelect.value = 'nurses';
          else deptSelect.value = 'administration';
        }
      });
    }

    const logAttForm = document.getElementById('log-attendance-form');
    if (logAttForm) {
      logAttForm.addEventListener('submit', handleLogAttendanceSubmit);
      if (logAttForm.status) logAttForm.status.addEventListener('change', () => syncAttendanceForm(logAttForm));
    }

    // Which day the attendance sheet shows and records.
    const attDate = document.getElementById('attendance-date');
    if (attDate) {
      attDate.max = todayIso();
      attDate.value = State.attendanceDate;
      attDate.addEventListener('change', (e) => {
        const v = e.target.value;
        if (!/^\d{4}-\d{2}-\d{2}$/.test(v) || v > todayIso()) {
          e.target.value = State.attendanceDate;
          showToast("Kelajakdagi kun uchun davomat kiritib bo'lmaydi.", 'warning');
          return;
        }
        State.attendanceDate = v;
        renderAttendanceSheet();
      });
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    initDatabase();
  });

  // Global API Exposure
    // =========================================================================
  // OFFICIAL PAYSLIP PRINTING
  // =========================================================================
  function printPayslip(staffId) {
    let staff = null;
    if (staffId) {
      staff = (State.staff || []).find(s => s.id === staffId);
    }
    if (!staff) {
      // Pick currently viewed staff from modal or first available staff
      const modalStaffId = document.getElementById('payslip-modal')?._currentStaffId;
      if (modalStaffId) staff = (State.staff || []).find(s => s.id === modalStaffId);
      // A payroll row whose person is missing from the HR staff list.
      const pr = modalStaffId && !staff ? payrollRow(modalStaffId) : null;
      if (pr) staff = { id: pr.staff_id, full_name: pr.full_name, role: pr.role, salary_base: pr.base_salary };
    }
    // No employee chosen used to print the first person on the staff list --
    // or Dr. Bobur Mirzayev when the list was empty -- and every payslip
    // carried a 12,000,000 base, 1,500,000 duty pay and an 800,000 bonus for
    // non-doctors that the payroll table does not pay. The printout now uses
    // the table's own formula.
    if (!staff) {
      showToast("Avval xodimni tanlang.", 'warning');
      return;
    }

    // Same figures as the on-screen payslip: the server payroll row. The
    // invented inpatient/detox bonus is gone, so bonuses is 0.
    const row = payrollRow(staff.id);
    if (!row) {
      showToast('Bu xodim uchun shu oy oylik hisobi topilmadi.', 'warning');
      return;
    }

    if (window.FMH_Print) {
      window.FMH_Print.employeePayslip(staff, {
        base_salary: Number(row.base_salary) || 0,
        bonuses: 0,
        night_shifts: Number(row.duty_pay) || 0
      });
    } else {
      window.print();
    }
  }

  window.FMH_HR = {
    openStaffDossier,
    generatePayslip,
    openAddStaffModal,
    openEditStaffModal,
    switchStaffFormMode,
    applyStaffPreset,
    openLogAttendanceModal,
    openQuickPicker,
    assignSlotStaff,
    handleSlotClick,
    setDutyViewMode: (mode) => {
      State.dutyViewMode = mode;
      renderShiftRoster();
    },
    togglePaintMode,
    setPaintStamp,
    openBrigadeModal,
    applyBrigadesToMonth,
    openSwapModal,
    executeSwap,
    openTelegramModal,
    copyTelegramText,
    // applyBrigadesToMonth shows its own toast only after the server saved;
    // this used to add a success toast even when the save was refused.
    triggerAutoSchedule: () => applyBrigadesToMonth('brigade_1_3'),
    saveSuggestedRoster,
    openAssignShiftModal,
    exportAllToExcel,
    closeAllModals,
    switchTab,
    deleteStaff,
    reactivateStaff,
    changeRosterMonth,
    goToCurrentMonth,
    editStaff: (id) => openEditStaffModal(id),
    printPayslip,
    toggleTheme: () => window.FMH_Theme ? window.FMH_Theme.toggle() : null,
    applyTheme: (t) => window.FMH_Theme ? window.FMH_Theme.set(t) : null
  };

})();
