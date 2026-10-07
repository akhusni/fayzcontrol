/**
 * Fayz Medical House — Qabulxona & Bemorlarni Ro'yxatga Olish Portali
 * reception.js — Tab Manager, Patient Intake, Appointments, Call Log, Directory, Print, Excel
 */

'use strict';

window.FMH_Reception = (function () {

  // ============================================================
  // STATE
  // ============================================================
  const State = {
    data: null,          // reception_db.json
    beds: [],            // from /api/beds
    patients: [],        // from /api/patients
    admissions: [],      // from /api/admissions
    staff: [],           // from /api/staff
    activeTab: 'intake',
    intake: {
      serviceType: 'inpatient',
      selectedBed: null,
      selectedFloor: 'all',
      isAnonymous: false,
    },
    apt: {
      selectedDoctorId: null,
      selectedDate: todayStr(),
      selectedSlot: null,
      bookedSlots: {},  // { doctorId_date: [time,...] }
    },
    callFilter: 'all',
    directorySearch: '',
    directoryFilter: 'all',
    editingCallId: null,
    editingAptId: null,
  };

  // ============================================================
  // HELPERS
  // ============================================================
  function todayStr() {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    const d = String(now.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  }

  function nowForDateTimeInput() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day}T${hours}:${minutes}`;
  }

  // Patient names reach the board straight from the database and are placed
  // into markup, so they are escaped rather than trusted.
  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatUZS(n) {
    if (n == null || isNaN(n)) return '0 so\'m';
    return Number(n).toLocaleString('uz-UZ') + ' so\'m';
  }

  function formatDate(str) {
    if (!str) return '—';
    const s = String(str).split('T')[0];
    const parts = s.split('-');
    if (parts.length === 3) {
      const monthsUz = ['Yanvar', 'Fevral', 'Mart', 'Aprel', 'May', 'Iyun', 'Iyul', 'Avgust', 'Sentyabr', 'Oktyabr', 'Noyabr', 'Dekabr'];
      const mIdx = parseInt(parts[1], 10) - 1;
      if (mIdx >= 0 && mIdx < 12) {
        return `${parseInt(parts[2], 10)}-${monthsUz[mIdx]}, ${parts[0]}`;
      }
      return `${parts[2]}.${parts[1]}.${parts[0]}`;
    }
    return str;
  }

  function formatDateTime(str) {
    if (!str) return '—';
    const d = new Date(str);
    return d.toLocaleDateString('uz-UZ', { month: 'short', day: 'numeric' }) + ' ' +
      d.toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' });
  }

  function formatDuration(sec) {
    if (!sec) return '—';
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function randomId(prefix) {
    return prefix + '-' + Date.now().toString(36).toUpperCase().slice(-6);
  }

  // Delegates to the shared toast in js/fmh_dialogs.js: that one announces
  // messages via aria-live, keeps errors on screen long enough to read,
  // stacks instead of erasing an unread message, and can be dismissed.
  function showToast(msg, type = 'success') {
    return window.FMH_Toast(msg, type);
  }

  function serviceTypeName(id) {
    const map = {
      inpatient: 'Statsionar Yotqizish',
      outpatient: 'Ambulator Konsultatsiya',
      home_visit: 'Uyga Narkologik Yordam',
      anonymous: 'Anonim Qabul',
    };
    return map[id] || id;
  }

  function programName(id) {
    if (!State.data) return id;
    // program_types is desk configuration the API may not send. Reading
    // .find on the missing key threw a TypeError out of the admissions
    // table, the call list and every export that names a programme.
    const p = (State.data.program_types || []).find(x => x.id === id);
    return p ? p.name_uz : id;
  }

  function sourceIcon(id) {
    const map = {
      hotline: 'fa-phone', telegram: 'fa-paper-plane', instagram: 'fa-camera',
      website: 'fa-globe', word_of_mouth: 'fa-users', repeat: 'fa-redo', doctor_referral: 'fa-stethoscope'
    };
    return map[id] || 'fa-question';
  }

  function dayName(dateStr) {
    const days = ['Yakshanba', 'Dushanba', 'Seshanba', 'Chorshanba', 'Payshanba', 'Juma', 'Shanba'];
    return days[new Date(dateStr).getDay()];
  }

  function englishDayName(dateStr) {
    const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    return days[new Date(dateStr).getDay()];
  }

  // ============================================================
  // MASTER EMBEDDED DATA (Zero-Network / file:// Protocol Resilient)
  // Ensures Reception is ALWAYS 100% rendered with zero blank screens
  // ============================================================
  // The ward layout used to be embedded here as a fallback, and fetched
  // from data/clinic_rooms.json when the network was up. Both had drifted
  // from the rooms and beds tables, which are what the booking guard
  // actually consults; the layout now arrives with the occupancy board.

  const DEFAULT_RECEPTION_DATA = {
    service_types: [
      { id: 'inpatient', name_uz: 'Statsionar Yotqizish', icon: 'fa-bed', color: '#38bdf8' },
      { id: 'outpatient', name_uz: 'Ambulator Muolaja', icon: 'fa-stethoscope', color: '#34d399' },
      { id: 'consultation', name_uz: 'Shifokor Konsultatsiyasi', icon: 'fa-user-doctor', color: '#818cf8' }
    ],
    program_types: [
      { id: 'statsionar_shared', name_uz: "Statsionar (1 karavot / 2 kishilik xona)", default_days: 10, default_rate: 720000, package_type: 'inpatient' },
      { id: 'statsionar_full_room', name_uz: "Statsionar Butun Xona — VIP Solo (1 kishi)", default_days: 10, default_rate: 1100000, package_type: 'inpatient' },
      { id: 'kunlik_statsionar', name_uz: "Kunlik Statsionar (Kunduzgi o'rin)", default_days: 10, default_rate: 630000, package_type: 'inpatient' },
      { id: 'ambulator_1', name_uz: "Ambulator — Kuniga 1 mahal muolaja", default_days: 10, default_rate: 310000, package_type: 'outpatient' },
      { id: 'ambulator_2', name_uz: "Ambulator — Kuniga 2 mahal muolaja", default_days: 10, default_rate: 500000, package_type: 'outpatient' }
    ],
    doctors: [],
    referral_sources: [
      { id: 'hotline', name_uz: 'Ishonch telefoni (Hotline)' },
      { id: 'telegram', name_uz: 'Telegram kanal & bot' },
      { id: 'instagram', name_uz: 'Instagram & Facebook' },
      { id: 'website', name_uz: 'Rasmiy veb-sayt' },
      { id: 'word_of_mouth', name_uz: 'Tanish / Do\'st tavsiyasi' },
      { id: 'repeat', name_uz: 'Qayta murojaat' },
      { id: 'doctor_referral', name_uz: 'Boshqa shifokor yo\'llanmasi' }
    ],
    appointments: [],
    call_logs: [],
    walk_ins: [],
    home_visits: []
  };

  // ============================================================
  // INIT & DATA LOADING
  // ============================================================
  async function init() {
    // Accept/reject are delegated: the list is re-rendered after every change.
    document.addEventListener('click', e => {
      const btn = e.target.closest('.btn-request');
      if (!btn) return;
      decideRequest(btn.dataset.id,
                    btn.classList.contains('accept') ? 'accept' : 'reject', btn);
    });

    // 1. Synchronously populate default resilient state so UI is never blank
    State.data = JSON.parse(JSON.stringify(DEFAULT_RECEPTION_DATA));
    // The bed grid stays on its loading state until the server answers. It
    // used to be filled in from a guess first, which showed the desk a ward
    // that was free by default.
    State.beds = [];
    indexBookedSlots();

    // 2. Initial Render
    renderKPIs();
    renderIntakeTab();
    renderAppointmentsTab();
    renderCallLogTab();
    renderDirectoryTab();
    setupTabs();
    setupIntakeServiceTypes();
    setupIntakeAnonToggle();
    updateTodayDate();

    // 3. Asynchronously load external JSON or REST APIs if available
    try {
      await Promise.all([loadReceptionData(), loadApiData()]);
      renderKPIs();
      renderIntakeTab();
      renderAppointmentsTab();
      renderCallLogTab();
      renderDirectoryTab();
    } catch (e) {
      console.log('[Reception] Running on resilient embedded dataset.');
    }

    // 4. Periodic Real-Time Refresh (Every 4s)
    setInterval(refreshLiveDataSilently, 4000);

    console.log('[FMH Reception] Portal initialized with live sync.');
  }

  async function refreshLiveDataSilently() {
    try {
      await loadApiData();
      renderKPIs();
    } catch (e) { /* ignore silent failure */ }
  }

  function indexBookedSlots() {
    State.apt.bookedSlots = {};
    if (State.data && State.data.appointments) {
      State.data.appointments.forEach(apt => {
        if (apt.status !== 'cancelled') {
          const key = apt.doctor_id + '_' + apt.date;
          if (!State.apt.bookedSlots[key]) State.apt.bookedSlots[key] = [];
          State.apt.bookedSlots[key].push(apt.time);
        }
      });
    }
  }

  // The API owns the live tables (appointments, calls, staff) and says
  // nothing about the desk configuration it does not store. Assigning the
  // response straight over State.data therefore deleted whole keys:
  // program_types vanished, renderIntakeProgramOptions built a <select>
  // with no <option>, and clicking "VIP Solo" in the rich picker set
  // sel.value to a value the select did not contain. A <select> resolves
  // that to the empty string, so the change handler found no option, gave
  // up early, and the daily rate stayed on the 720 000 written into the
  // HTML. The full-room tariff was impossible to charge. Merging keeps
  // every default the response leaves out.
  function mergeReceptionData(fetched) {
    const merged = JSON.parse(JSON.stringify(DEFAULT_RECEPTION_DATA));
    Object.keys(fetched || {}).forEach(key => {
      const value = fetched[key];
      if (value === null || value === undefined) return;
      // An empty list from the server is real data for the tables it owns,
      // but for the desk lists it only means "not configured here", and
      // blanking a dropdown is worse than showing the built-in tariffs.
      if (Array.isArray(value) && !value.length &&
          Array.isArray(merged[key]) && merged[key].length) return;
      merged[key] = value;
    });
    return merged;
  }

  async function loadReceptionData() {
    try {
      const r = await fetch('/api/reception/data');
      if (r.ok) {
        const fetched = await r.json();
        if (fetched) {
          State.data = mergeReceptionData(fetched);
          indexBookedSlots();
        }
      }
    } catch (e) {
      // Keep resilient default
    }
  }

  async function loadApiData() {
    // The ward layout is no longer read from data/clinic_rooms.json: the rooms
    // and beds tables are what the booking guard consults, and the file had
    // drifted from them.
    // --- REST API endpoints (relative URLs) ---
    try {
      const [patientsRes, admissionsRes, recRes, staffRes, bedsRes] = await Promise.all([
        fetch('/api/patients'),
        fetch('/api/admissions'),
        fetch('/api/reception/data'),
        fetch('/api/staff'),
        fetch('/api/beds')
      ]);
      if (patientsRes.ok) State.patients = await patientsRes.json();
      if (admissionsRes.ok) State.admissions = await admissionsRes.json();
      if (bedsRes.ok) State.liveBeds = await bedsRes.json();
      if (recRes.ok) {
        const recData = await recRes.json();
        if (recData) {
          State.data = mergeReceptionData(recData);
        }
      }
      if (staffRes.ok) {
        const staffList = await staffRes.json();
        if (Array.isArray(staffList)) {
          // Sanitarlar va hamshiralar davolash va konsultatsiya ko'rsatmaydi, faqat shifokorlar (doctor, chief_doctor)
          const docStaff = staffList.filter(s => s.role === 'doctor' || s.role === 'chief_doctor');
          State.data.doctors = docStaff.map((d, i) => ({
            id: d.id,
            full_name: d.full_name,
            specialty: d.specialty || d.role || 'Narkolog-Psixiatr',
            specialty_short: d.role === 'chief_doctor' ? 'Bosh Shifokor' : 'Shifokor',
            room: `${i + 1}-Kabinet`,
            avatar_color: '#38bdf8',
            available_days: ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'],
            slot_duration_min: 30,
            work_start: '09:00',
            work_end: '18:00',
            lunch_start: '13:00',
            lunch_end: '14:00'
          }));
          indexBookedSlots();
        }
      }
    } catch (e) {
      // Running in offline / local file mode
    }

    // Occupancy for the dates the form is asking about, and for today (the
    // KPI census), both straight from the admissions table.
    await Promise.all([
      fetchAvailability(),
      fetchTodayBoard(),
    ]);
  }


  // ============================================================
  // BED AVAILABILITY — asked of the server, for the dates in the form
  //
  // This used to be worked out here in the browser: the ward layout from a
  // static data/clinic_rooms.json, merged with bookings kept in localStorage
  // under the building-management key, plus a hand-written table of which bed
  // partners which so a room sold whole could grey out its second bed.
  //
  // None of that ever left the machine. A booking in one receptionist's
  // localStorage blocked a real bed for whoever sat at that computer and was
  // invisible to everyone else — and to the server, which is what actually
  // approves the booking. The layout drifted from the rooms table, and the
  // overlap arithmetic here disagreed with the server's at the boundary, so
  // the desk was offered beds that were then refused on submit.
  //
  // /api/facility/availability answers the same question from the admissions
  // table, using the rule that approves the booking.
  // ============================================================

  function addDays(dateStr, days) {
    const [y, m, d] = String(dateStr).slice(0, 10).split('-').map(Number);
    const dt = new Date(Date.UTC(y, (m || 1) - 1, d || 1));
    dt.setUTCDate(dt.getUTCDate() + (days || 0));
    return dt.toISOString().slice(0, 10);
  }

  // The dates the form is currently asking about.
  function intakeWindow() {
    const start = document.getElementById('intake-start-date')?.value || todayStr();
    const days = parseInt(document.getElementById('intake-days')?.value) || 7;
    return { start: String(start).slice(0, 10), end: addDays(start, days) };
  }

  async function fetchAvailability(startDate, endDate) {
    const win = intakeWindow();
    const start = startDate || win.start;
    const end = endDate || win.end;
    try {
      const res = await fetch('/api/facility/availability'
        + `?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${res.status}`);
      }
      const board = await res.json();
      State.availability = board;
      State.beds = flattenAvailability(board);
      return board;
    } catch (e) {
      // Keep the previous picture rather than blanking the grid: an empty
      // board reads as "no free beds", which is a different claim from
      // "could not ask".
      console.error('availability:', e);
      showToast(`Karavot holatini yuklab bo'lmadi: ${e.message}`, 'error');
      return State.availability || null;
    }
  }

  // Today's picture, for the header census. Kept separate from the board
  // above because the form is usually asking about a future stay, and the
  // KPI strip is about who is in the building right now.
  async function fetchTodayBoard() {
    const today = todayStr();
    try {
      const res = await fetch('/api/facility/availability'
        + `?start=${today}&end=${addDays(today, 1)}`);
      if (!res.ok) return State.todayBoard || null;
      State.todayBoard = await res.json();
      return State.todayBoard;
    } catch (e) {
      console.error('today census:', e);
      return State.todayBoard || null;
    }
  }

  // Both the picker and the room board read this flat per-bed shape.
  function flattenAvailability(board) {
    const beds = [];
    (board?.rooms || []).forEach(room => {
      (room.beds || []).forEach(b => {
        const occ = b.occupant || null;
        const conflict = b.conflict || null;
        const entry = {
          bed_id: b.bed_id,
          bed_code: b.bed_code,
          bed_type: b.bed_type,
          default_daily_rate: b.default_daily_rate,
          floor_number: b.floor_number,
          room_id: b.room_id,
          room_number: b.room_number,
          room_name_uz: b.room_name_uz,
          physical_bed_status: b.physical_status,
          status: b.status,
          system_bed_status: b.status,
          next_reserved_date: b.next_booking || null,
          current_patient: null,
          check_out: null,
          booking_start: null,
          booking_end: null,
          locked_by: null,
          lock_reason: null,
          conflict_date: null,
        };

        if (b.status === 'occupied' && occ) {
          entry.current_patient = occ.patient_name;
          entry.check_out = occ.end_date;
          entry.booking_start = occ.start_date;
          entry.booking_end = occ.end_date;
        } else if (b.status === 'room_locked' && occ) {
          // The room was sold whole: this bed stays empty and is paid for.
          entry.status = 'occupied';
          entry.system_bed_status = 'occupied';
          entry.lock_reason = 'vip_solo_partner';
          entry.locked_by = occ.patient_name;
          entry.booking_start = occ.start_date;
          entry.booking_end = occ.end_date;
        } else if (b.status === 'partial_conflict' && conflict) {
          entry.current_patient = conflict.patient_name;
          entry.conflict_date = conflict.start_date;
          entry.check_out = conflict.end_date;
        }
        beds.push(entry);
      });
    });
    return beds;
  }

  // Re-read the ward from the server. Kept under its old exported name so
  // the buttons and the cross-tab listeners that call it keep working.
  function refreshBedsFromBuildingManagement() {
    return loadApiData().then(() => {
      renderBedPicker();
      renderKPIs();
      // The rooms tab asks about its own date range, so it is re-read rather
      // than repainted from the intake window's answer.
      if (State.activeTab === 'rooms') loadRoomsBoard();
      showToast("Karavot holatlari bazadan yangilandi ✓", 'success');
    }).catch(() => {});
  }


  function updateTodayDate() {
    const el = document.getElementById('today-date-display');
    if (el) {
      const now = new Date();
      el.textContent = now.toLocaleDateString('uz-UZ', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
    }
  }

  // ============================================================
  // BED CENSUS FOR TODAY
  //
  // Who is in the building right now. This used to be counted here, over the
  // admissions list merged with whatever the browser had in localStorage, and
  // it carried its own copy of the whole-room rule as a hand-written table of
  // partner beds. It is one reading of the same board the picker uses, so it
  // now comes from the server with everything else.
  // ============================================================
  function getRealTimeBedCensus() {
    const board = State.todayBoard;
    if (!board || !board.summary) {
      return { total: 0, occupied: 0, available: 0, occupiedBedIds: [] };
    }
    const beds = (board.rooms || []).reduce((acc, r) => acc.concat(r.beds || []), []);
    // A bed held empty because its room was sold whole is not free to offer,
    // so it counts against availability even though nobody is lying in it.
    const held = beds.filter(b => b.status === 'occupied' || b.status === 'room_locked');
    return {
      total: board.summary.total_beds || beds.length,
      occupied: held.length,
      available: board.summary.available || 0,
      occupiedBedIds: held.map(b => b.bed_id),
    };
  }

  // ============================================================
  // KPI SUMMARY CARDS
  // ============================================================
  function renderKPIs() {
    const todayStr_ = todayStr();
    const apts = (State.data && State.data.appointments) ? State.data.appointments : [];
    const calls = (State.data && State.data.call_logs) ? State.data.call_logs : [];
    const walkIns = (State.data && State.data.walk_ins) ? State.data.walk_ins : [];
    const homeVisits = (State.data && State.data.home_visits) ? State.data.home_visits : [];

    // REAL-TIME BED CENSUS (TODAY ONLY, EXCLUDES ANY FUTURE RESERVATIONS)
    const census = getRealTimeBedCensus();

    const todayApts = apts.filter(a => a.date === todayStr_ || (a.created_at && a.created_at.startsWith(todayStr_)));
    const newCalls = calls.filter(c => c.status === 'new' || c.status === 'callback_needed');
    const todayWalkIns = walkIns.filter(w => w.date === todayStr_ || (w.created_at && w.created_at.startsWith(todayStr_)));
    const todayHV = homeVisits.filter(h => h.scheduled_for && h.scheduled_for.startsWith(todayStr_));
    const totalPatientsCount = State.patients.length || (walkIns.length + homeVisits.length + (State.admissions || []).length);

    // Update Top Bar & KPI Summary Cards
    setValue('kpi-beds-available', census.available);
    setValue('chip-beds-available', census.available);
    setValue('kpi-beds-occupied', census.occupied);
    setValue('kpi-today-apts', todayApts.length);
    setValue('chip-today-apts', todayApts.length);
    setValue('kpi-new-calls', newCalls.length);
    setValue('chip-new-calls', newCalls.length);
    setValue('kpi-today-walkins', todayWalkIns.length + todayHV.length);
    setValue('kpi-total-patients', totalPatientsCount);

    // Update Tab Count Badges
    setValue('tab-count-apts', todayApts.length);
    setValue('tab-count-calls', newCalls.length);
    setValue('directory-count', totalPatientsCount);
  }

  function setValue(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  // ============================================================
  // TABS
  // ============================================================
  function setupTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });
  }

  function switchTab(tabId) {
    State.activeTab = tabId;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + tabId));
    // The board is re-read on open rather than kept warm: somebody else may
    // have admitted or discharged a patient since the page loaded.
    if (tabId === 'rooms') renderRoomsTab();
    if (tabId === 'requests') loadRequests();
  }

  // ============================================================
  // TAB 1: INTAKE FORM
  // ============================================================
  // ============================================================
  // TAB 1: INTAKE FORM
  // ============================================================
  function setupIntakeServiceTypes() {
    document.querySelectorAll('.service-type-card').forEach(card => {
      card.addEventListener('click', () => {
        document.querySelectorAll('.service-type-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');
        State.intake.serviceType = card.dataset.service;

        const sel = document.getElementById('intake-program-select');
        const rateInput = document.getElementById('intake-daily-rate');

        if (State.intake.serviceType === 'consultation') {
          State.intake.selectedBed = null;
        } else if (State.intake.serviceType === 'outpatient') {
          // Switch dropdown to ambulator
          if (sel) {
            const ambOpt = Array.from(sel.options).find(o => o.value.includes('ambulator'));
            if (ambOpt) {
              sel.value = ambOpt.value;
              if (rateInput) rateInput.value = ambOpt.dataset.rate || 310000;
            }
          }
          State.intake.selectedBed = null;
        } else if (State.intake.serviceType === 'inpatient') {
          if (sel) {
            const current = sel.value || '';
            const currentOpt = Array.from(sel.options).find(o => o.value === current);
            const isInpatient = currentOpt &&
              (currentOpt.dataset.type || 'inpatient') === 'inpatient';
            if (!isInpatient) {
              const firstInpatient = Array.from(sel.options).find(
                o => (o.dataset.type || 'inpatient') === 'inpatient');
              if (firstInpatient) sel.value = firstInpatient.value;
            }
            sel.dispatchEvent(new CustomEvent('externalUpdate'));
            const opt = sel.options[sel.selectedIndex];
            if (rateInput && opt && Number(opt.dataset.rate) > 0) {
              rateInput.value = Number(opt.dataset.rate);
            }
          }
        }

        renderIntakeSections();
        renderBedPicker();
        updateCostPreview();
      });
    });
    // Default select consultation or inpatient
    const defaultCard = document.querySelector('.service-type-card[data-service="consultation"]') || document.querySelector('.service-type-card[data-service="inpatient"]');
    if (defaultCard) {
      document.querySelectorAll('.service-type-card').forEach(c => c.classList.remove('selected'));
      defaultCard.classList.add('selected');
      State.intake.serviceType = defaultCard.dataset.service;
    }
    renderIntakeSections();
  }

  function setupIntakeAnonToggle() {
    // Legacy stub - anonymous toggle removed per requirements
  }

  function renderIntakeAnonBanner() {
    // Legacy stub
  }

  function renderIntakePatientFields() {
    const nameField = document.getElementById('intake-patient-name');
    const phoneField = document.getElementById('intake-patient-phone');
    if (nameField) {
      nameField.placeholder = 'Familiya Ism Sharif *';
      nameField.required = true;
    }
    if (phoneField) {
      phoneField.placeholder = '+998 90 123 45 67 *';
      phoneField.required = true;
    }
  }

  function renderIntakeSections() {
    const type = State.intake.serviceType || 'consultation';
    const progVal = document.getElementById('intake-program-select')?.value || '';
    const isAmbProg = progVal.includes('ambulator');
    
    const bedSection = document.getElementById('intake-bed-section');
    const consultSection = document.getElementById('intake-consultation-section');
    const aptSection = document.getElementById('intake-apt-section');

    const showBed = type === 'inpatient' && !isAmbProg;
    const showConsultation = type === 'consultation';
    const showOutpatient = type === 'outpatient' || (type !== 'consultation' && isAmbProg);

    if (bedSection) bedSection.style.display = showBed ? 'block' : 'none';
    if (consultSection) consultSection.style.display = showConsultation ? 'block' : 'none';
    if (aptSection) aptSection.style.display = showOutpatient ? 'block' : 'none';
    
    updateCostPreview();
  }

  function renderIntakeTab() {
    const startDateEl = document.getElementById('intake-start-date');
    if (startDateEl && !startDateEl.value) {
      startDateEl.value = todayStr();
    }
    renderBedPicker();
    renderIntakeDoctorSelect();
    renderIntakeProgramOptions();
    renderReferralOptions();
    renderPayMethodOptions();
    updateCostPreview();
    setupCostListeners();
    renderRecentWalkIns();
  }

    function renderBedPicker() {
    const grid = document.getElementById('bed-picker-grid');
    if (!grid) return;

    const startDate = document.getElementById('intake-start-date')?.value || todayStr();
    const days = parseInt(document.getElementById('intake-days')?.value) || 7;
    let endDate = startDate;
    try {
      const d = new Date(startDate);
      d.setDate(d.getDate() + days);
      endDate = d.toISOString().slice(0, 10);
    } catch(e) {}

    // Update dynamic date display indicator
    const dateDisplay = document.getElementById('bed-dynamic-date-display');
    if (dateDisplay) {
      dateDisplay.innerHTML = `<span style="color:#10b981;">${formatDate(startDate)}</span> &nbsp;→&nbsp; <span style="color:#38bdf8;">${formatDate(endDate)}</span> &nbsp;(${days} kunlik davolanish)`;
    }

    let beds = State.beds || [];
    const floor = State.intake.selectedFloor;
    if (floor !== 'all') beds = beds.filter(b => String(b.floor_number) === String(floor));

    if (!beds || !beds.length) {
      grid.innerHTML = '<div class="empty-state"><i class="fas fa-spinner fa-spin"></i><p>Karavot ma\'lumotlari yuklanmoqda...</p></div>';
      return;
    }

    // Update floor tab counts
    const allBeds = State.beds || [];
    const f1 = allBeds.filter(b => b.floor_number === 1);
    const f2 = allBeds.filter(b => b.floor_number === 2);
    const availAll = allBeds.filter(b => b.system_bed_status === 'available' || b.status === 'available').length;
    const el1 = document.querySelector('.floor-tab[data-floor="1"]');
    const el2 = document.querySelector('.floor-tab[data-floor="2"]');
    const elAll = document.querySelector('.floor-tab[data-floor="all"]');
    if (elAll) elAll.textContent = `Barchasi (${availAll} bo'sh)`;
    if (el1) el1.innerHTML = `<i class="fas fa-layer-group"></i> 1-Qavat (${f1.filter(b => (b.system_bed_status||b.status) === 'available').length} bo'sh)`;
    if (el2) el2.innerHTML = `<i class="fas fa-building"></i> 2-Qavat (${f2.filter(b => (b.system_bed_status||b.status) === 'available').length} bo'sh)`;

    grid.innerHTML = beds.map(b => {
      const status = b.system_bed_status || b.status || 'available';
      const isSelected = State.intake.selectedBed === b.bed_id;
      const isAvail = status === 'available';
      const isPartial = status === 'partial_conflict';
      const rate = b.default_daily_rate || 720000;

      let cls = `bed-slot ${status}`;
      if (isSelected) cls += ' selected';

      // Build rich tooltip and status label
      let tooltip = `${b.room_name_uz || b.room_number + '-Xona'} | Karavot: ${b.bed_code || b.bed_id} | ${formatUZS(rate)}/kun`;
      let statusLabel = 'Bo\'sh';
      let subLabel = '';

      if (status === 'occupied') {
        if (b.lock_reason === 'vip_solo_partner') {
          statusLabel = '👑 VIP Lok';
          subLabel = `${(b.locked_by || 'Solo band').slice(0, 10)}`;
          tooltip += ` | 👑 VIP Solo band: ${b.locked_by} (${b.booking_start || ''} - ${b.booking_end || ''})`;
        } else {
          statusLabel = '🔴 Band';
          subLabel = `${(b.current_patient || 'Bemor').slice(0, 10)}`;
          tooltip += ` | 🔴 Band: ${b.current_patient || 'Bemor'} (chiqish: ${b.check_out || 'noma`lum'})`;
        }
      } else if (status === 'cleaning') {
        statusLabel = '🧹 Dezinfeksiya';
        subLabel = 'Tozalanmoqda';
        tooltip += ` | 🧹 Sanitar tozalash va dezinfeksiya jarayonida (qabulga yopiq)`;
      } else if (status === 'maintenance' || status === 'out_of_service') {
        // These two fell through to the free branch and were painted green,
        // so a bed withdrawn from service was still offered to the desk.
        const isRepair = status === 'maintenance';
        statusLabel = isRepair ? '🔧 Ta`mirda' : '⛔ Xizmatdan tashqari';
        subLabel = 'Qabulga yopiq';
        tooltip += ` | ${isRepair ? "🔧 Ta'mirlash ishlari" : '⛔ Xizmatdan chiqarilgan'} — bemor joylashtirilmaydi`;
      } else if (isPartial) {
        statusLabel = '⚠️ Band';
        subLabel = `${b.conflict_date ? b.conflict_date.slice(5) + ' dan' : 'Qisman'}`;
        tooltip += ` | ⚠️ Ushbu davrda (${b.conflict_date} sanasidan) ${b.current_patient} tomonidan band!`;
      } else {
        statusLabel = '🟢 Bo\'sh';
        if (b.next_reserved_date) {
          subLabel = `${b.next_reserved_date.slice(5)} gacha`;
          tooltip += ` | 🟢 Bo'sh (${b.next_reserved_date} gacha band qilingan)`;
        } else if (b.next_booking) {
          subLabel = `${b.next_booking.start_date.slice(5)} gacha`;
          tooltip += ` | 🟢 Bo'sh (${b.next_booking.start_date} gacha) — Kelgusi: ${b.next_booking.patient_name}`;
        } else if (b.next_partner_lock) {
          subLabel = `${b.next_partner_lock.start_date.slice(5)} gacha`;
          tooltip += ` | 🟢 Bo'sh (${b.next_partner_lock.start_date} gacha) — Kelgusi VIP Solo: ${b.next_partner_lock.patient_name}`;
        } else {
          subLabel = 'To`liq bo`sh';
          tooltip += ` | 🟢 Tanlangan davr uchun to'liq bo'sh`;
        }
      }

      const onclickAction = isAvail ? `onclick="window.FMH_Reception.selectBed('${b.bed_id}', ${rate})"` : `onclick="window.FMH_Reception.notifyBedConflict('${b.bed_id}', '${status}', '${(b.current_patient || b.locked_by || '').replace(/'/g, "\'")}')"`;

      return `
        <div class="${cls}" ${onclickAction} title="${tooltip.replace(/"/g, '&quot;')}" style="position:relative;">
          <span class="bed-code">${b.bed_code || b.bed_id}</span>
          <span class="bed-type">${statusLabel}</span>
          <span class="bed-sub">${subLabel}</span>
        </div>`;
    }).join('');
  }

  function notifyBedConflict(bedId, status, occupant) {
    const startDate = document.getElementById('intake-start-date')?.value || todayStr();
    if (status === 'cleaning') {
      showToast(`⚠️ ${bedId} karavotida hozir dezinfeksiya va sanitar tozalash ketmoqda. Bemor joylashtirishdan oldin Statsionar bo'limida tozalashni yakunlang!`, 'warning');
    } else if (status === 'maintenance' || status === 'out_of_service') {
      showToast(`⛔ ${bedId} karavoti hozir xizmatda emas (${status === 'maintenance' ? "ta'mirlash" : 'xizmatdan chiqarilgan'}). Statsionar bo'limi uni qaytargach tanlash mumkin.`, 'warning');
    } else if (status === 'occupied') {
      showToast(`❌ ${bedId} karavoti ${startDate} sanasida band! (${occupant || 'Bemor yotibdi'})`, 'warning');
    } else if (status === 'partial_conflict') {
      showToast(`⚠️ ${bedId} karavotida tanlangan davr davomida bron mavjud! Boshqa karavot tanlang.`, 'warning');
    }
  }

  // ============================================================
  // TAB: ENQUIRIES FROM THE PUBLIC WEBSITE
  //
  // The site's booking form used to POST straight at
  // /api/reception/appointment. Once the API required a session that endpoint
  // answered 401 and the enquiry vanished — nothing recorded, nobody told.
  // They arrive in appointment_requests now, and this is where the desk reads
  // them. Nothing here is a patient until somebody accepts it.
  // ============================================================

  const REQUEST_STATUS_UZ = {
    new: 'Yangi',
    accepted: 'Qabul qilingan',
    rejected: 'Rad etilgan',
  };

  async function loadRequests() {
    const host = document.getElementById('requests-list');
    if (!host) return;
    const want = document.getElementById('requests-filter')?.value || 'new';
    host.innerHTML = '<div class="empty-state"><i class="fas fa-spinner fa-spin"></i><p>Yuklanmoqda...</p></div>';
    try {
      const res = await fetch('/api/reception/requests?status=' + encodeURIComponent(want));
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `Xatolik (${res.status})`);
      }
      const data = await res.json();
      State.requests = data.requests || [];
      renderRequests(data);
    } catch (e) {
      host.innerHTML = `<div class="empty-state"><i class="fas fa-triangle-exclamation"></i><p>${escapeHtml(e.message)}</p></div>`;
    }
  }

  function renderRequests(data) {
    const host = document.getElementById('requests-list');
    const badge = document.getElementById('tab-count-requests');
    if (badge) {
      badge.textContent = data.waiting || 0;
      badge.classList.toggle('is-waiting', (data.waiting || 0) > 0);
    }
    if (!data.requests.length) {
      host.innerHTML = `<div class="empty-state"><i class="fas fa-inbox"></i>
        <p>Bu holatda so'rov yo'q.</p></div>`;
      return;
    }
    host.innerHTML = data.requests.map(r => {
      const isNew = r.status === 'new';
      return `
        <article class="request-card ${escapeHtml(r.status)}">
          <div class="request-main">
            <div class="request-name">${escapeHtml(r.full_name)}</div>
            <div class="request-meta">
              <span><i class="fas fa-phone"></i> ${escapeHtml(r.phone)}</span>
              ${r.preferred_date ? `<span><i class="fas fa-calendar"></i> ${formatDate(r.preferred_date)}</span>` : ''}
              <span><i class="fas fa-clock"></i> ${formatDateTime(r.created_at)}</span>
            </div>
            ${r.note ? `<div class="request-note">${escapeHtml(r.note)}</div>` : ''}
            ${r.handled_by ? `<div class="request-handled">${REQUEST_STATUS_UZ[r.status]} — ${escapeHtml(r.handled_by)}</div>` : ''}
          </div>
          <div class="request-actions">
            <span class="request-status ${escapeHtml(r.status)}">${REQUEST_STATUS_UZ[r.status] || r.status}</span>
            ${isNew ? `
              <button type="button" class="btn-request accept" data-id="${escapeHtml(r.id)}">
                <i class="fas fa-user-check"></i> Qabul qilish
              </button>
              <button type="button" class="btn-request reject" data-id="${escapeHtml(r.id)}">
                <i class="fas fa-ban"></i> Rad etish
              </button>` : ''}
          </div>
        </article>`;
    }).join('');
  }

  async function decideRequest(id, action, button) {
    if (action === 'reject') {
      const ok = window.fmhConfirm
        ? await window.fmhConfirm({
            title: "So'rovni rad etish",
            message: "Bu so'rov rad etilgan deb belgilanadi. Bemor kartasi ochilmaydi.",
            confirmText: 'Rad etish', cancelText: 'Bekor qilish', type: 'warning' })
        : true;
      if (!ok) return;
    }
    button.disabled = true;
    try {
      const res = await fetch(`/api/reception/requests/${encodeURIComponent(id)}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Xatolik (${res.status})`);
      showToast(action === 'accept'
        ? "✓ So'rov qabul qilindi — bemor navbatga yozildi"
        : "So'rov rad etildi", action === 'accept' ? 'success' : 'warning');
      await loadRequests();
      if (action === 'accept') {
        await loadApiData();
        renderKPIs();
        renderAppointmentsTab();
        renderDirectoryTab();
      }
    } catch (e) {
      showToast(e.message, 'error');
      button.disabled = false;
    }
  }

  // ============================================================
  // TAB: THE ROOMS BOARD (free / occupied, for a chosen date range)
  //
  // The desk's first question of the day, and the one the intake form could
  // not answer: which rooms are free, and until when. The bed picker inside
  // the form only ever shows the dates that form is asking about, and only as
  // fourteen loose beds — a two-bed room is a unit the desk sells, so it is
  // shown as one.
  // ============================================================

  const ROOM_STATUS_UZ = {
    free: "Bo'sh",
    partial: "Qisman band",
    full: "To'la band",
  };

  const BED_STATUS_UZ = {
    available: "Bo'sh",
    occupied: 'Band',
    room_locked: 'Butun xona (bo`sh turadi)',
    partial_conflict: 'Davr ichida band',
    cleaning: 'Dezinfeksiya',
    maintenance: "Ta'mirda",
    out_of_service: 'Xizmatdan tashqari',
  };

  function roomsBoardWindow() {
    const start = document.getElementById('rooms-board-start')?.value || todayStr();
    const end = document.getElementById('rooms-board-end')?.value || addDays(start, 7);
    return { start: String(start).slice(0, 10), end: String(end).slice(0, 10) };
  }

  async function loadRoomsBoard() {
    const win = roomsBoardWindow();
    if (win.end <= win.start) {
      showToast("Ketish sanasi kelish sanasidan keyin bo'lishi kerak.", 'warning');
      return;
    }
    const grid = document.getElementById('rooms-board-grid');
    if (grid) grid.innerHTML = '<div class="empty-state"><i class="fas fa-spinner fa-spin"></i><p>Xonalar holati yuklanmoqda...</p></div>';
    try {
      const res = await fetch('/api/facility/availability'
        + `?start=${encodeURIComponent(win.start)}&end=${encodeURIComponent(win.end)}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${res.status}`);
      }
      State.roomsBoard = await res.json();
      renderRoomsBoard();
    } catch (e) {
      console.error('rooms board:', e);
      if (grid) {
        grid.innerHTML = `<div class="empty-state"><i class="fas fa-triangle-exclamation"></i><p>${escapeHtml(e.message)}</p></div>`;
      }
      showToast(`Xonalar holatini yuklab bo'lmadi: ${e.message}`, 'error');
    }
  }

  function setRoomsBoardPreset(days) {
    const startEl = document.getElementById('rooms-board-start');
    const endEl = document.getElementById('rooms-board-end');
    const start = startEl?.value || todayStr();
    if (startEl) startEl.value = start;
    if (endEl) endEl.value = addDays(start, days);
    document.querySelectorAll('.rooms-board-preset').forEach(b =>
      b.classList.toggle('active', String(b.dataset.days) === String(days)));
    loadRoomsBoard();
  }

  function renderRoomsBoard() {
    const grid = document.getElementById('rooms-board-grid');
    if (!grid) return;
    const board = State.roomsBoard;
    if (!board || !board.rooms) {
      grid.innerHTML = '<div class="empty-state"><i class="fas fa-spinner fa-spin"></i><p>Xonalar holati yuklanmoqda...</p></div>';
      return;
    }

    renderRoomsBoardSummary(board);

    const floors = {};
    board.rooms.forEach(r => {
      (floors[r.floor_number] = floors[r.floor_number] || []).push(r);
    });

    grid.innerHTML = Object.keys(floors).sort().map(floorNo => {
      const rooms = floors[floorNo];
      const freeHere = rooms.reduce((n, r) => n + r.free_beds, 0);
      return `
        <div class="rooms-floor">
          <div class="rooms-floor-head">
            <span><i class="fas fa-layer-group"></i> ${floorNo}-Qavat</span>
            <span class="rooms-floor-count">${freeHere} bo'sh o'rin</span>
          </div>
          <div class="rooms-floor-grid">
            ${rooms.map(renderRoomCard).join('')}
          </div>
        </div>`;
    }).join('');
  }

  function renderRoomCard(room) {
    const status = room.status || 'free';
    const capacity = room.beds.length;
    return `
      <div class="room-card ${status}${room.locked_whole_room ? ' whole-room' : ''}">
        <div class="room-card-head">
          <div>
            <div class="room-card-title">${escapeHtml(room.room_name_uz || room.room_number + '-Xona')}</div>
            <div class="room-card-sub">${capacity} o'rin${room.locked_whole_room ? " · 👑 Butun xona band" : ''}</div>
          </div>
          <span class="room-chip ${status}">${ROOM_STATUS_UZ[status] || status}</span>
        </div>
        <div class="room-card-beds">
          ${room.beds.map(renderRoomCardBed).join('')}
        </div>
      </div>`;
  }

  function renderRoomCardBed(bed) {
    const status = bed.status || 'available';
    const who = bed.occupant || bed.conflict || null;
    let detail;
    if (status === 'available') {
      detail = bed.next_booking
        ? `${formatDate(bed.next_booking)} gacha bo'sh`
        : "Butun davr bo'sh";
    } else if (who) {
      detail = `${escapeHtml(who.patient_name || 'Bemor')} · ${formatDate(who.start_date)} — ${formatDate(who.end_date)}`;
    } else {
      detail = 'Qabulga yopiq';
    }
    return `
      <div class="room-bed ${status}">
        <span class="room-bed-code">${escapeHtml(bed.bed_code || bed.bed_id)}</span>
        <span class="room-bed-status">${BED_STATUS_UZ[status] || status}</span>
        <span class="room-bed-detail">${detail}</span>
      </div>`;
  }

  function renderRoomsBoardSummary(board) {
    const el = document.getElementById('rooms-board-summary');
    if (!el || !board.summary) return;
    const s = board.summary;
    const cells = [
      { label: "Bo'sh o'rin", value: s.available, tone: 'good' },
      { label: 'Band', value: s.occupied, tone: 'bad' },
      { label: 'Butun xona ushlab turilgan', value: s.room_locked, tone: 'vip' },
      { label: 'Davr ichida band', value: s.partial_conflict, tone: 'warn' },
      { label: 'Dezinfeksiya', value: s.cleaning, tone: 'warn' },
      { label: "Bo'sh xona", value: `${s.free_rooms} / ${s.total_rooms}`, tone: 'good' },
    ];
    el.innerHTML = cells.map(c => `
      <div class="rooms-summary-cell ${c.tone}">
        <span class="rooms-summary-value">${c.value}</span>
        <span class="rooms-summary-label">${c.label}</span>
      </div>`).join('');
  }

  function renderRoomsTab() {
    const startEl = document.getElementById('rooms-board-start');
    const endEl = document.getElementById('rooms-board-end');
    if (startEl && !startEl.value) startEl.value = todayStr();
    if (endEl && !endEl.value) endEl.value = addDays(startEl?.value || todayStr(), 7);
    loadRoomsBoard();
  }

  async function updateBedPickerForSelectedDate() {
    const win = intakeWindow();
    await fetchAvailability(win.start, win.end);
    const start = win.start;

    // Check if previously selected bed is still available on new dates
    if (State.intake.selectedBed) {
      const current = (State.beds || []).find(b => b.bed_id === State.intake.selectedBed);
      if (current && (current.system_bed_status !== 'available' && current.status !== 'available')) {
        showToast(`⚠️ Tanlangan ${State.intake.selectedBed} karavoti yangi sanada (${start}) band!`, 'warning');
        State.intake.selectedBed = null;
        const bedTypeEl = document.getElementById('intake-bed-type-label');
        if (bedTypeEl) bedTypeEl.innerHTML = '<span style="color:#f59e0b;">⚠️ Karavotni qayta tanlang</span>';
      }
    }

    renderBedPicker();
    renderKPIs();
  }

  function setBedDatePreset(offsetDays) {
    const d = new Date();
    d.setDate(d.getDate() + offsetDays);
    const newDateStr = d.toISOString().slice(0, 10);
    
    const startInput = document.getElementById('intake-start-date');
    if (startInput) {
      startInput.value = newDateStr;
    }

    document.querySelectorAll('.btn-bed-date-preset').forEach(btn => {
      btn.classList.toggle('active', parseInt(btn.dataset.offset) === offsetDays);
    });

    updateBedPickerForSelectedDate();
    updateCostPreview();
    showToast(`📅 ${formatDate(newDateStr)} sanasi bo'yicha karavotlar holati yangilandi`, 'info');
  }

  function selectBed(bedId, rate, type) {
    State.intake.selectedBed = bedId;
    const rateInput = document.getElementById('intake-daily-rate');
    const sel = document.getElementById('intake-program-select');
    const isLux = sel?.value === 'statsionar_full_room';
    
    if (rateInput) {
      rateInput.value = isLux ? 1100000 : (rate || 720000);
    }
    // Set bed type label
    const bedTypeEl = document.getElementById('intake-bed-type-label');
    if (bedTypeEl) {
      bedTypeEl.innerHTML = isLux 
        ? `<span style="color: #a855f7; font-weight: 700;">👑 Lyuks (Butun xona 1 kishi): Tanlangan karavot: ${bedId}, xonadagi ikkinchi karavot avtomatik bloklanadi.</span>`
        : `<span style="color: #10b981; font-weight: 700;">🟢 Tanlangan karavot: ${bedId}</span>`;
    }
    renderBedPicker();
    updateCostPreview();
    showToast(`${bedId} karavoti tanlandi`, 'success');
  }

  function switchBedFloor(floor) {
    State.intake.selectedFloor = floor;
    document.querySelectorAll('.floor-tab').forEach(t => t.classList.toggle('active', t.dataset.floor === String(floor)));
    renderBedPicker();
  }

  // ============================================================
  // RICH CUSTOM DROPDOWN ENGINE
  // ============================================================
  function buildRichSelect(selectId, items, customConfig = {}) {
    const sel = document.getElementById(selectId);
    if (!sel) return;

    // Remove existing wrapper if re-rendering
    let existingWrapper = sel.parentNode.querySelector(`.rich-select-wrapper[data-for="${selectId}"]`);
    if (existingWrapper) existingWrapper.remove();

    sel.style.display = 'none';

    const wrapper = document.createElement('div');
    wrapper.className = 'rich-select-wrapper';
    wrapper.dataset.for = selectId;

    const trigger = document.createElement('div');
    trigger.className = 'rich-select-trigger';
    trigger.setAttribute('tabindex', '0');

    const dropdown = document.createElement('div');
    dropdown.className = 'rich-select-dropdown';

    wrapper.appendChild(trigger);
    wrapper.appendChild(dropdown);
    sel.parentNode.insertBefore(wrapper, sel.nextSibling);

    function updateTrigger(item) {
      if (!item) {
        trigger.innerHTML = `
          <div class="rich-select-value">
            <span class="rich-select-text" style="color: var(--text-muted);">— Tanlang —</span>
          </div>
          <i class="fas fa-chevron-down rich-select-chevron"></i>`;
        return;
      }
      const iconHtml = item.icon ? `<span class="rich-select-icon">${item.icon}</span>` : '';
      const tagHtml = item.priceTag ? `<span class="rich-select-tag">${item.priceTag}</span>` : '';
      trigger.innerHTML = `
        <div class="rich-select-value">
          ${iconHtml}
          <span class="rich-select-text">${item.title || item.name}</span>
          ${tagHtml}
        </div>
        <i class="fas fa-chevron-down rich-select-chevron"></i>`;
    }

    // Build options HTML
    dropdown.innerHTML = '';
    
    // Check if items have categories/groups
    const groups = {};
    items.forEach(it => {
      const g = it.group || 'Asosiy';
      if (!groups[g]) groups[g] = [];
      groups[g].push(it);
    });

    const groupKeys = Object.keys(groups);
    const hasMultipleGroups = groupKeys.length > 1;

    groupKeys.forEach(gKey => {
      const gDiv = document.createElement('div');
      gDiv.className = 'rich-select-group';
      
      if (hasMultipleGroups && gKey !== 'Asosiy') {
        const gTitle = document.createElement('div');
        gTitle.className = 'rich-select-group-title';
        gTitle.textContent = gKey;
        gDiv.appendChild(gTitle);
      }

      groups[gKey].forEach(item => {
        const opt = document.createElement('div');
        opt.className = `rich-select-option ${String(sel.value) === String(item.value) ? 'is-selected' : ''}`;
        opt.dataset.val = item.value;

        const iconBadge = item.icon 
          ? `<div class="rich-opt-icon" style="${item.iconBg ? `background:${item.iconBg};color:${item.iconColor||'#fff'};` : ''}">${item.icon}</div>` 
          : '';

        const descHtml = item.desc ? `<div class="rich-opt-desc">${item.desc}</div>` : '';
        const priceHtml = item.priceTag ? `<div class="rich-opt-price">${item.priceTag}</div>` : '';

        opt.innerHTML = `
          <div class="rich-opt-left">
            ${iconBadge}
            <div class="rich-opt-info">
              <div class="rich-opt-title">${item.title || item.name}</div>
              ${descHtml}
            </div>
          </div>
          <div class="rich-opt-right">
            ${priceHtml}
            <i class="fas fa-check rich-opt-check"></i>
          </div>`;

        opt.addEventListener('click', (e) => {
          e.stopPropagation();
          sel.value = item.value;
          dropdown.querySelectorAll('.rich-select-option').forEach(o => o.classList.remove('is-selected'));
          opt.classList.add('is-selected');
          updateTrigger(item);
          wrapper.classList.remove('is-open');
          sel.dispatchEvent(new Event('change', { bubbles: true }));
        });

        gDiv.appendChild(opt);
      });

      dropdown.appendChild(gDiv);
    });

    // Set initial selected trigger
    const currentItem = items.find(it => String(it.value) === String(sel.value)) || items[0];
    if (currentItem) {
      updateTrigger(currentItem);
    }

    // Toggle open/close
    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      const isOpen = wrapper.classList.contains('is-open');
      // Close other open rich selects
      document.querySelectorAll('.rich-select-wrapper.is-open').forEach(w => {
        if (w !== wrapper) w.classList.remove('is-open');
      });
      wrapper.classList.toggle('is-open', !isOpen);
    });

    // Sync if select.value changes externally
    sel.addEventListener('externalUpdate', () => {
      const match = items.find(it => String(it.value) === String(sel.value));
      if (match) {
        updateTrigger(match);
        dropdown.querySelectorAll('.rich-select-option').forEach(o => {
          o.classList.toggle('is-selected', o.dataset.val === String(match.value));
        });
      }
    });
  }

  // Global click outside to close
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.rich-select-wrapper')) {
      document.querySelectorAll('.rich-select-wrapper.is-open').forEach(w => w.classList.remove('is-open'));
    }
  });

  function renderIntakeDoctorSelect() {
    const sel = document.getElementById('intake-doctor-select');
    if (!sel) return;
    const doctors = State.data.doctors || [];
    sel.innerHTML = '<option value="">— Shifokor tanlang —</option>' +
      doctors.map(d => `<option value="${d.id}">${d.full_name} (${d.specialty_short})</option>`).join('');

    const richItems = doctors.map(d => ({
      value: d.id,
      title: d.full_name,
      desc: `${d.specialty_short} • ${d.room || '1-Kabinet'}`,
      icon: '<i class="fas fa-user-md"></i>',
      iconBg: d.avatar_color ? `${d.avatar_color}25` : 'rgba(99, 102, 241, 0.2)',
      iconColor: d.avatar_color || '#818cf8',
      priceTag: d.work_start ? `${d.work_start} - ${d.work_end}` : null,
      group: 'Shifokorlar Tarkibi'
    }));

    buildRichSelect('intake-doctor-select', richItems);
  }

  function renderIntakeProgramOptions() {
    const sel = document.getElementById('intake-program-select');
    if (!sel) return;
    const programs = State.data.program_types || [];
    sel.innerHTML = programs.map(p => `<option value="${p.id}" data-type="${p.package_type || 'inpatient'}" data-days="${p.default_days}" data-rate="${p.default_rate}">${p.name_uz} — ${Number(p.default_rate).toLocaleString('uz-UZ')} so'm/kun</option>`).join('');

    const richItems = [
      {
        value: 'statsionar_shared',
        title: "Statsionar (1 karavot / 2 kishilik xona)",
        desc: "24 soatlik to'liq nazorat, 4 mahal parhez taomnoma",
        priceTag: "720,000 so'm/kun",
        icon: '<i class="fas fa-bed"></i>',
        iconBg: 'rgba(16, 185, 129, 0.2)',
        iconColor: '#10b981',
        group: "🏨 STATSIONAR BO'LIMI"
      },
      {
        value: 'statsionar_full_room',
        title: "Statsionar Butun Xona — VIP Solo (1 kishi)",
        desc: "100% maxfiy, xonada yolg'iz, 2-karavot avtomatik bloklanadi",
        priceTag: "1,100,000 so'm/kun",
        icon: '<i class="fas fa-crown"></i>',
        iconBg: 'rgba(168, 85, 247, 0.2)',
        iconColor: '#c084fc',
        group: "🏨 STATSIONAR BO'LIMI"
      },
      {
        value: 'kunlik_statsionar',
        title: "Kunlik Statsionar (Kunduzgi o'rin)",
        desc: "Kunduzgi muolajalar va dam olish, kechasi qolmaydi",
        priceTag: "630,000 so'm/kun",
        icon: '<i class="fas fa-sun"></i>',
        iconBg: 'rgba(245, 158, 11, 0.2)',
        iconColor: '#fbbf24',
        group: "🏨 STATSIONAR BO'LIMI"
      },
      {
        value: 'ambulator_1',
        title: "Ambulator — Kuniga 1 mahal muolaja",
        desc: "Klinikaga kuniga 1 mahal kelib kapelnitsa va inyeksiya",
        priceTag: "310,000 so'm/kun",
        icon: '<i class="fas fa-tint"></i>',
        iconBg: 'rgba(56, 189, 248, 0.2)',
        iconColor: '#38bdf8',
        group: "🩺 AMBULATOR MUOLAJALAR"
      },
      {
        value: 'ambulator_2',
        title: "Ambulator — Kuniga 2 mahal muolaja",
        desc: "Ertalab va kechqurun, intensiv ambulator kursi",
        priceTag: "500,000 so'm/kun",
        icon: '<i class="fas fa-bolt"></i>',
        iconBg: 'rgba(244, 63, 94, 0.2)',
        iconColor: '#f43f5e',
        group: "🩺 AMBULATOR MUOLAJALAR"
      }
    ];

    buildRichSelect('intake-program-select', richItems);
    
    // trigger on change to update rate and toggle bed section dynamically
    const fireChange = () => {
      const opt = sel.options[sel.selectedIndex];
      if (!opt) return;
      const daysInput = document.getElementById('intake-days');
      const rateInput = document.getElementById('intake-daily-rate');
      if (daysInput && Number(opt.dataset.days) > 0) daysInput.value = opt.dataset.days;
      
      const rate = Number(opt.dataset.rate) || 720000;
      if (rateInput) rateInput.value = rate;

      const val = opt.value;
      if (val.includes('ambulator') || opt.dataset.type === 'outpatient') {
        State.intake.serviceType = 'outpatient';
        State.intake.selectedBed = null;
        document.querySelectorAll('.service-type-card').forEach(c => {
          c.classList.toggle('selected', c.dataset.service === 'outpatient');
        });
      } else if (val === 'statsionar_full_room' || val === 'statsionar_shared' || val === 'kunlik_statsionar') {
        State.intake.serviceType = 'inpatient';
        document.querySelectorAll('.service-type-card').forEach(c => {
          c.classList.toggle('selected', c.dataset.service === 'inpatient');
        });
      }

      // Notify rich select to sync
      sel.dispatchEvent(new CustomEvent('externalUpdate'));

      renderIntakeSections();
      renderBedPicker();
      updateCostPreview();
    };
    sel.addEventListener('change', fireChange);
    fireChange(); // apply first option defaults on load
  }

  function renderReferralOptions() {
    const sel = document.getElementById('intake-referral-select');
    if (!sel) return;
    const sources = State.data.referral_sources || [];
    sel.innerHTML = '<option value="">— Qanday topdi? —</option>' +
      sources.map(s => `<option value="${s.id}">${s.name_uz}</option>`).join('');

    const iconMap = {
      hotline: { icon: '<i class="fas fa-phone"></i>', color: '#38bdf8' },
      telegram: { icon: '<i class="fab fa-telegram"></i>', color: '#0ea5e9' },
      instagram: { icon: '<i class="fab fa-instagram"></i>', color: '#ec4899' },
      website: { icon: '<i class="fas fa-globe"></i>', color: '#10b981' },
      word_of_mouth: { icon: '<i class="fas fa-users"></i>', color: '#f59e0b' },
      repeat: { icon: '<i class="fas fa-redo"></i>', color: '#a855f7' },
      doctor_referral: { icon: '<i class="fas fa-stethoscope"></i>', color: '#14b8a6' }
    };

    const richItems = sources.map(s => {
      const meta = iconMap[s.id] || { icon: '<i class="fas fa-bullhorn"></i>', color: '#6366f1' };
      return {
        value: s.id,
        title: s.name_uz,
        icon: meta.icon,
        iconBg: `${meta.color}20`,
        iconColor: meta.color
      };
    });

    buildRichSelect('intake-referral-select', richItems);
  }

  function renderPayMethodOptions() {
    const sel = document.getElementById('intake-pay-method');
    if (!sel) return;
    const payItems = [
      { value: 'cash', title: 'Naqd pul', desc: 'Kassada to\'lov', icon: '<i class="fas fa-money-bill-wave"></i>', iconBg: 'rgba(16, 185, 129, 0.2)', iconColor: '#10b981' },
      { value: 'card', title: 'Karta / Terminal', desc: 'Uzcard, Humo terminal', icon: '<i class="fas fa-credit-card"></i>', iconBg: 'rgba(56, 189, 248, 0.2)', iconColor: '#38bdf8' },
      { value: 'online', title: 'Online (Click / Payme)', desc: 'Masofaviy to\'lov', icon: '<i class="fas fa-qrcode"></i>', iconBg: 'rgba(168, 85, 247, 0.2)', iconColor: '#c084fc' },
      { value: 'mixed', title: 'Aralash To\'lov', desc: 'Naqd + Karta', icon: '<i class="fas fa-random"></i>', iconBg: 'rgba(245, 158, 11, 0.2)', iconColor: '#fbbf24' }
    ];
    buildRichSelect('intake-pay-method', payItems);
  }

  function setupCostListeners() {
    ['intake-start-date', 'intake-days', 'intake-daily-rate', 'intake-advance', 'intake-discount', 'intake-consultation-fee', 'intake-outpatient-fee'].forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener('input', () => {
          updateCostPreview();
          if (id === 'intake-start-date' || id === 'intake-days') {
            updateBedPickerForSelectedDate();
          }
        });
        el.addEventListener('change', () => {
          updateCostPreview();
          if (id === 'intake-start-date' || id === 'intake-days') {
            updateBedPickerForSelectedDate();
          }
        });
      }
    });
  }

  function updateCostPreview() {
    const type = State.intake.serviceType || 'consultation';
    let days = parseInt(document.getElementById('intake-days')?.value) || 0;
    let rate = parseFloat(document.getElementById('intake-daily-rate')?.value) || 0;
    const advance = parseFloat(document.getElementById('intake-advance')?.value) || 0;
    const discount = parseFloat(document.getElementById('intake-discount')?.value) || 0;
    const startDateInput = document.getElementById('intake-start-date')?.value;

    if (type === 'consultation') {
      rate = parseFloat(document.getElementById('intake-consultation-fee')?.value) || 250000;
      days = 1;
    } else if (type === 'outpatient') {
      rate = parseFloat(document.getElementById('intake-outpatient-fee')?.value) || 310000;
    }

    if (startDateInput) {
      const startD = new Date(startDateInput);
      const endD = new Date(startD);
      endD.setDate(endD.getDate() + (type === 'consultation' ? 0 : days));
      setValue('preview-start-date', formatDate(startDateInput));
      setValue('preview-end-date', formatDate(endD.toISOString().slice(0, 10)));
    } else {
      setValue('preview-start-date', '—');
      setValue('preview-end-date', '—');
    }

    const gross = type === 'consultation' ? rate : (days * rate);
    const discountAmount = gross * (discount / 100);
    const net = gross - discountAmount;
    const balance = Math.max(0, net - advance);

    setValue('preview-days', type === 'consultation' ? '1 qabul' : (days + ' kun'));
    setValue('preview-rate', type === 'consultation' ? (formatUZS(rate) + ' (bir martalik)') : (formatUZS(rate) + '/kun'));
    setValue('preview-gross', formatUZS(gross));
    setValue('preview-discount', discount ? `-${formatUZS(discountAmount)} (${discount}%)` : '0 so\'m');
    setValue('preview-net', formatUZS(net));
    setValue('preview-advance', formatUZS(advance));
    setValue('preview-balance', formatUZS(balance));
  }

  function renderRecentWalkIns() {
    const container = document.getElementById('recent-walkins');
    if (!container) return;
    const items = [...(State.data.walk_ins || []), ...(State.data.home_visits || [])].slice(-5).reverse();
    if (!items.length) {
      container.innerHTML = '<div class="empty-state"><i class="fas fa-inbox"></i><p>Bugun hali qabul yo\'q</p></div>';
      return;
    }
    container.innerHTML = items.map(item => {
      const isHome = !!item.service;
      const icon = isHome ? 'fa-house-medical' : (item.service_type === 'anonymous' ? 'fa-user-secret' : 'fa-user-plus');
      const color = isHome ? '#f59e0b' : (item.service_type === 'anonymous' ? '#a855f7' : '#14b8a6');
      const name = item.patient_name || item.client_name || 'Anonim';
      const detail = isHome ? `Uyga chaqiruv • ${item.service || ''}` : `${serviceTypeName(item.service_type)} • ${programName(item.program)}`;
      const time = item.time || (item.scheduled_for ? item.scheduled_for.slice(11, 16) : '');
      const pill = item.status === 'admitted' ? 'pill-admitted' : (item.status === 'completed' ? 'pill-completed' : 'pill-new');

      return `
        <div class="walk-in-card">
          <div class="walk-in-icon" style="background: ${color}22; color: ${color}">
            <i class="fas ${icon}"></i>
          </div>
          <div class="walk-in-main">
            <div class="walk-in-name">${name} ${item.is_anonymous ? '<i class="fas fa-user-secret" style="color:#a855f7;font-size:0.75rem;"></i>' : ''}</div>
            <div class="walk-in-detail">${detail} • ${time}</div>
            ${item.assigned_bed ? `<div style="font-size:0.7rem;color:var(--text-muted);margin-top:3px;"><i class="fas fa-bed"></i> ${item.assigned_bed}</div>` : ''}
          </div>
          <span class="status-pill ${pill}">${item.status === 'admitted' ? 'Qabul qilindi' : item.status === 'completed' ? 'Yakunlandi' : 'Yangi'}</span>
        </div>`;
    }).join('');
  }

  // ============================================================
  // INTAKE SUBMIT
  // ============================================================
    async function submitIntakeForm(e) {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    const type = State.intake.serviceType || 'consultation';
    const nameInput = document.getElementById('intake-patient-name');
    const phoneInput = document.getElementById('intake-patient-phone');
    const name = (nameInput?.value || '').trim();
    const phone = (phoneInput?.value || '').trim();

    if (!name) {
      showToast('Iltimos, bemor ismini kiriting', 'error');
      nameInput?.focus();
      return;
    }

    const submitBtn = document.getElementById('btn-submit-intake');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Qabul qilinmoqda...';
    }

    try {
      const isAnon = Boolean(document.getElementById('intake-anon-check')?.checked || State.intake?.isAnonymous);
      const program = document.getElementById('intake-program-select')?.value || 'statsionar_shared';
      const doctorId = document.getElementById('intake-doctor-select')?.value || null;
      const days = parseInt(document.getElementById('intake-days')?.value) || 7;
      const rate = parseFloat(document.getElementById('intake-daily-rate')?.value) || 720000;
      const advance = parseFloat(document.getElementById('intake-advance')?.value) || 0;
      const discount = parseFloat(document.getElementById('intake-discount')?.value) || 0;
      const payMethod = document.getElementById('intake-pay-method')?.value || 'cash';
      const notes = (document.getElementById('intake-notes')?.value || '').trim();
      const referral = document.getElementById('intake-referral-select')?.value || 'hotline';
      const startDate = document.getElementById('intake-start-date')?.value || todayStr();
      const birthDate = document.getElementById('intake-patient-birthdate')?.value || '';
      const gender = document.getElementById('intake-patient-gender')?.value || '';

      if (type === 'inpatient') {
        // Auto-select first available bed if none clicked
        if (!State.intake.selectedBed) {
          const avail = (State.beds || []).find(b => (b.system_bed_status || b.status) === 'available');
          if (avail) {
            selectBed(avail.bed_id, avail.default_daily_rate || rate);
          } else {
            showToast('Hozirda bo\'sh karavotlar mavjud emas', 'error');
            return;
          }
        }

        const bedId = State.intake.selectedBed || null;
        const startDateStr = String(startDate).slice(0, 10);
        const startDateObj = new Date(startDateStr);
        const endDateObj = new Date(startDateObj);
        endDateObj.setDate(endDateObj.getDate() + days);
        const endDateStr = endDateObj.toISOString().slice(0, 10);

        const payload = {
          patient_name: isAnon ? 'Anonim Bemor' : name,
          patient_phone: isAnon ? '' : phone,
          birth_date: birthDate,
          gender: gender,
          is_anonymous: isAnon ? 1 : 0,
          bed_id: bedId,
          attending_doctor_id: doctorId,
          program_type: program,
          start_date: startDateStr,
          end_date: endDateStr,
          daily_price: rate,
          discount_percent: discount,
          notes: notes,
          referral_source: referral,
        };

        const res = await fetch('/api/admissions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.error || `Xatolik yuz berdi (${res.status})`);
        }

        const json = await res.json();
        showToast(`✓ Bemor muvaffaqiyatli qabul qilindi! (${isAnon ? 'Anonim' : name}, Karavot: ${bedId})`, 'success');

        // Record advance payment if provided
        if (advance > 0 && json.invoice_id) {
          try {
            await fetch('/api/payments', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                invoice_id: json.invoice_id,
                amount: advance,
                payment_method: payMethod,
                account_destination: payMethod === 'cash' ? 'kassa' : 'bank',
                notes: 'Birlamchi qabul avans to`lovi'
              }),
            });
          } catch (ePay) {
            console.warn('Payment note:', ePay);
          }
        }

        // Reset form
        State.intake.selectedBed = null;
        document.getElementById('intake-form')?.reset();
        const startEl = document.getElementById('intake-start-date');
        if (startEl) startEl.value = todayStr();

        await loadApiData();
        renderKPIs();
        renderBedPicker();
        renderRecentWalkIns();
        renderDirectoryTab();

        // Print admission voucher
        setTimeout(() => {
          printAdmissionSlip({
            name: isAnon ? 'Anonim Bemor' : name,
            phone,
            bedId,
            startDate: startDateStr,
            program,
            days,
            rate,
            advance
          }, json.id);
        }, 500);

      } else if (type === 'outpatient') {
        const fee = parseFloat(document.getElementById('intake-outpatient-fee')?.value) || 310000;
        const aptRes = await fetch('/api/reception/appointment', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            patient_name: name,
            patient_phone: phone,
            is_anonymous: 0,
            birth_date: birthDate,
            gender: gender,
            doctor_id: doctorId,
            service_type: 'outpatient',
            date: startDate,
            time: new Date().toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' }),
            notes: notes || 'Ambulator muolaja (Reception)'
          })
        });
        const aptData = await aptRes.json().catch(() => ({}));
        if (!aptRes.ok) {
          showToast(aptData.error || "Tashrif saqlanmadi.", 'error');
          return;
        }
        showToast(`✓ Ambulator bemor qabuli qayd etildi! (${name})`, 'success');
        document.getElementById('intake-form')?.reset();
        await loadApiData();
        renderKPIs();
        renderRecentWalkIns();
        renderAppointmentsTab();
        renderDirectoryTab();

      } else if (type === 'consultation') {
        if (!doctorId) {
          showToast("Iltimos, konsultatsiya uchun mas'ul shifokorni tanlang!", 'warning');
          document.getElementById('intake-doctor-select')?.focus();
          return;
        }
        const fee = parseFloat(document.getElementById('intake-consultation-fee')?.value) || 250000;
        const consultTime = document.getElementById('intake-consultation-time')?.value || new Date().toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' });
        const aptRes = await fetch('/api/reception/appointment', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            patient_name: name,
            patient_phone: phone,
            is_anonymous: 0,
            birth_date: birthDate,
            gender: gender,
            doctor_id: doctorId,
            service_type: 'consultation',
            consultation_fee: fee,
            date: startDate,
            time: consultTime,
            notes: notes || 'Shifokor konsultatsiyasi (Qabulxona)'
          })
        });
        const aptData = await aptRes.json().catch(() => ({}));
        if (!aptRes.ok) {
          showToast(aptData.error || "Konsultatsiya qayd etilmadi.", 'error');
          return;
        }
        showToast(`✓ Konsultatsiya muvaffaqiyatli rasmiylashtirildi! Bemor shifokor kabinetiga biriktirildi (${name}).`, 'success');
        document.getElementById('intake-form')?.reset();
        await loadApiData();
        renderKPIs();
        renderRecentWalkIns();
        renderAppointmentsTab();
        renderDirectoryTab();

        // Print consultation voucher
        setTimeout(() => {
          printConsultationSlip({
            name,
            phone,
            doctorId,
            date: startDate,
            time: consultTime,
            fee,
            notes
          }, aptData.id);
        }, 400);
      }
    } catch (err) {
      console.error('Admission submit error:', err);
      showToast(`Qabul qilishda xatolik: ${err.message}`, 'error');
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-user-check"></i> Qabul Qilish va Tasdiqlash';
      }
    }
  }

  function printConsultationSlip(data, aptId) {
    const doctorObj = (State.data.doctors || []).find(d => d.id === data.doctorId) || { full_name: 'Mas\'ul Shifokor' };
    const printArea = document.getElementById('print-area');
    if (!printArea) return;
    printArea.innerHTML = `
      <div class="print-sheet-a4" style="max-width: 600px; margin: 0 auto; padding: 25px; font-family: sans-serif; border: 1px solid #ddd; background: #fff; color: #000;">
        <div style="text-align:center; border-bottom: 2px solid #000; padding-bottom: 12px; margin-bottom: 15px;">
          <h2 style="margin: 0; font-size: 1.4rem;">FAYZ MEDICAL HOUSE</h2>
          <div style="font-size: 0.85rem; color: #555;">XUSUSIY NARKOLOGIYA VA PSIXIATRIYA KLINIKASI</div>
          <div style="font-size: 0.85rem; font-weight: bold; margin-top: 5px; color: #4338ca;">SHIFOKOR KONSULTATSIYASI YO'LLANMASI & KVITANSIYASI</div>
        </div>
        <table style="width: 100%; font-size: 0.92rem; line-height: 1.9; border-collapse: collapse;">
          <tr><td style="color:#666; width: 42%;">Bemor F.I.Sh.:</td><td><strong>${data.name}</strong></td></tr>
          <tr><td style="color:#666;">Telefon Raqami:</td><td><strong>${data.phone || '—'}</strong></td></tr>
          <tr><td style="color:#666;">Biriktirilgan Shifokor:</td><td><strong style="color: #4338ca;">${doctorObj.full_name}</strong></td></tr>
          <tr><td style="color:#666;">Qabul Sanasi & Vaqti:</td><td>${data.date} (soat ${data.time})</td></tr>
          <tr><td style="color:#666;">Xizmat Turi:</td><td>Shifokor Konsultatsiyasi</td></tr>
          <tr><td style="color:#666;">Konsultatsiya To'lovi:</td><td><strong>${formatUZS(data.fee)}</strong></td></tr>
          ${data.notes ? `<tr><td style="color:#666;">Dastlabki Eslatma:</td><td>${data.notes}</td></tr>` : ''}
        </table>
        <div style="margin-top: 15px; padding: 10px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 0.8rem; color: #475569;">
          Eslatma: Ushbu bemor shifokor qabulida bo'lgach, shifokor kabinetida konsultatsiya xulosasi va retsept rasmiylashtiriladi.
        </div>
        <div style="margin-top: 25px; padding-top: 15px; border-top: 1px dashed #999; font-size: 0.75rem; color: #666; display: flex; justify-content: space-between;">
          <div>Qabulxona (Reception) Imzosi: _________</div>
          <div>Sana: ${new Date().toLocaleDateString('uz-UZ')}</div>
        </div>
      </div>
    `;
    setTimeout(() => {
      window.print();
    }, 200);
  }

  function startDirectIntake(options = {}) {
    switchTab('intake');
    if (options.name) {
      const nameEl = document.getElementById('intake-patient-name');
      if (nameEl) nameEl.value = options.name;
    }
    if (options.phone) {
      const phoneEl = document.getElementById('intake-patient-phone');
      if (phoneEl) phoneEl.value = options.phone;
    }
    if (options.serviceType) {
      const card = document.querySelector(`.service-type-card[data-service="${options.serviceType}"]`);
      if (card) card.click();
    }
    if (options.doctorId) {
      const docSel = document.getElementById('intake-doctor-select');
      if (docSel) docSel.value = options.doctorId;
    }
    if (options.notes) {
      const notesEl = document.getElementById('intake-notes');
      if (notesEl) notesEl.value = options.notes;
    }
    document.getElementById('intake-patient-name')?.focus();
    showToast('Qabul shakli to\'ldirishga tayyor', 'info');
  }

  function openAdmissionConfirmModal(data) {
    const modal = document.getElementById('modal-admission-confirm');
    if (!modal) return;
    // The '- 0' here was where the discount belonged: the last screen the
    // desk sees before confirming showed the gross as the net, so a patient
    // was read back a figure higher than the one they had agreed to.
    const gross = data.days * data.rate;
    const discountPct = Number(data.discount) || 0;
    const discountAmount = gross * (discountPct / 100);
    const net = gross - discountAmount;
    const balance = Math.max(0, net - data.advance);
    modal.querySelector('#confirm-patient-name').textContent = data.isAnon ? 'Anonim Bemor' : (data.name || '—');
    modal.querySelector('#confirm-bed-id').textContent = data.bedId || '—';
    if (modal.querySelector('#confirm-start-date')) {
      modal.querySelector('#confirm-start-date').textContent = data.startDate ? formatDate(data.startDate) : '—';
    }
    modal.querySelector('#confirm-program').textContent = programName(data.program);
    modal.querySelector('#confirm-days').textContent = data.days + ' kun';
    modal.querySelector('#confirm-rate').textContent = formatUZS(data.rate) + '/kun';
    if (modal.querySelector('#confirm-gross')) {
      modal.querySelector('#confirm-gross').textContent = formatUZS(gross);
    }
    if (modal.querySelector('#confirm-discount')) {
      modal.querySelector('#confirm-discount').textContent = discountAmount
        ? `-${formatUZS(discountAmount)} (${discountPct}%)`
        : formatUZS(0);
    }
    modal.querySelector('#confirm-net').textContent = formatUZS(net);
    modal.querySelector('#confirm-advance').textContent = formatUZS(data.advance);
    modal.querySelector('#confirm-balance').textContent = formatUZS(balance);
    modal.querySelector('#confirm-pay-method').textContent = { cash: 'Naqd', card: 'Karta/Terminal', online: 'Online', mixed: 'Aralash' }[data.payMethod] || data.payMethod;
    // Store for actual submission
    modal._pendingData = data;
    openModal('modal-admission-confirm');
  }

  async function confirmAdmission() {
    const modal = document.getElementById('modal-admission-confirm');
    const data = modal?._pendingData;
    if (!data) {
      showToast('Qabul ma\'lumotlari topilmadi', 'error');
      closeModal('modal-admission-confirm');
      return;
    }

    const startIso = data.startDate || todayStr();
    const startDateStr = String(startIso).slice(0, 10);
    const startDateObj = new Date(startDateStr);
    const endDateObj = new Date(startDateObj);
    endDateObj.setDate(endDateObj.getDate() + (parseInt(data.days) || 7));
    const endDateStr = endDateObj.toISOString().slice(0, 10);

    const payload = {
      patient_name: data.isAnon ? 'Anonim Bemor' : (data.name || ''),
      patient_phone: data.phone || '',
      is_anonymous: data.isAnon ? 1 : 0,
      bed_id: data.bedId || null,
      attending_doctor_id: data.doctorId || null,
      program_type: data.program || 'statsionar_shared',
      start_date: startDateStr,
      end_date: endDateStr,
      daily_price: parseFloat(data.rate) || 720000.0,
      notes: data.notes || '',
      referral_source: data.referral || 'reception',
    };

    try {
      const res = await fetch('/api/admissions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.error || `Server xatosi (${res.status})`);
      }

      const json = await res.json();
      closeModal('modal-admission-confirm');
      showToast(`✓ Bemor muvaffaqiyatli qabul qilindi! (${data.isAnon ? 'Anonim' : data.name})`, 'success');

      // Record advance payment if provided
      if (data.advance > 0 && json.invoice_id) {
        try {
          await fetch('/api/payments', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              invoice_id: json.invoice_id,
              amount: data.advance,
              payment_method: data.payMethod || 'cash',
              account_destination: data.payMethod === 'cash' ? 'kassa' : 'bank',
              notes: 'Birlamchi qabul avans to`lovi'
            }),
          });
        } catch (ePay) {
          console.warn('Payment recording note:', ePay);
        }
      }

      // The admission is in the database; it used to be copied into this
      // browser's localStorage as well, which is where the phantom bookings
      // came from. That copy was never cleared when a stay was discharged or
      // deleted, so it went on blocking the bed on this machine only.
      // building_management.js rebuilds the same store from /api/admissions
      // every time it loads, so nothing is lost by not writing it here.
      window.dispatchEvent(new CustomEvent('fmh_bookings_updated'));

      // Reset form and re-fetch real database data
      State.intake.selectedBed = null;
      document.getElementById('intake-form')?.reset();
      const startDateEl1 = document.getElementById('intake-start-date');
      if (startDateEl1) startDateEl1.value = todayStr();

      await loadApiData();
      renderKPIs();
      renderBedPicker();
      renderRecentWalkIns();

      // Print intake voucher
      setTimeout(() => printAdmissionSlip(data, json.id), 500);

    } catch (err) {
      console.error('Admission submit error:', err);
      closeModal('modal-admission-confirm');
      showToast(`Qabul qilishda xatolik: ${err.message}`, 'error');
    }
  }

  function openHomeVisitConfirmModal(data) {
    const address = document.getElementById('intake-home-address')?.value.trim();
    const landmark = document.getElementById('intake-home-landmark')?.value.trim();
    const fee = document.getElementById('intake-home-fee')?.value || 850000;
    showToast(`Uyga chaqiruv qayd etildi: ${data.name || 'Anonim'} — ${address}`, 'success');
  }

  // ============================================================
  // TAB 2: APPOINTMENTS
  // ============================================================
  function renderAppointmentsTab() {
    renderDoctorCards();
    // Select first doctor by default
    const doctors = State.data.doctors || [];
    if (doctors.length > 0 && !State.apt.selectedDoctorId) {
      selectDoctor(doctors[0].id);
    }
    renderTodayAppointmentsList();
  }

  function renderDoctorCards() {
    const container = document.getElementById('doctor-card-list');
    if (!container) return;
    const doctors = State.data.doctors || [];
    container.innerHTML = doctors.map(d => `
      <div class="doctor-card ${d.id === State.apt.selectedDoctorId ? 'active' : ''}" onclick="window.FMH_Reception.selectDoctor('${d.id}')">
        <div class="doctor-avatar" style="background: ${d.avatar_color}">${d.full_name.split(' ').map(n => n[0]).join('').substring(0, 2)}</div>
        <div>
          <div class="doctor-info-name">${d.full_name}</div>
          <div class="doctor-info-spec">${d.specialty_short}</div>
          <div class="doctor-info-room"><i class="fas fa-door-open"></i> ${d.room}</div>
        </div>
      </div>`).join('');
  }

  function selectDoctor(doctorId) {
    State.apt.selectedDoctorId = doctorId;
    State.apt.selectedSlot = null;
    renderDoctorCards();
    renderSlotGrid();
  }

  function renderSlotGrid() {
    const doctor = (State.data.doctors || []).find(d => d.id === State.apt.selectedDoctorId);
    if (!doctor) return;

    const dateStr = State.apt.selectedDate;
    const engDay = englishDayName(dateStr);
    const isWorkDay = doctor.available_days.includes(engDay);

    const container = document.getElementById('slot-grid-container');
    const dateLabel = document.getElementById('slot-date-label');
    if (dateLabel) dateLabel.textContent = `${dayName(dateStr)}, ${formatDate(dateStr)}`;

    if (!isWorkDay) {
      if (container) container.innerHTML = `
        <div class="empty-state">
          <i class="fas fa-calendar-times"></i>
          <h3>${doctor.full_name}</h3>
          <p>Bu kuni (${dayName(dateStr)}) ishlamaydi</p>
        </div>`;
      return;
    }

    // Generate slots
    const slots = generateSlots(doctor, dateStr);
    if (container) {
      container.innerHTML = `<div class="slot-grid">${slots.map(slot => `
        <div class="slot-btn ${slot.type} ${slot.time === State.apt.selectedSlot ? 'selected' : ''}"
          ${slot.type === 'free' ? `onclick="window.FMH_Reception.selectSlot('${slot.time}')"` : ''}>
          ${slot.time}
        </div>`).join('')}</div>`;
    }
  }

  function generateSlots(doctor, dateStr) {
    const key = doctor.id + '_' + dateStr;
    const booked = State.apt.bookedSlots[key] || [];
    const slots = [];
    const durMin = doctor.slot_duration_min || 30;

    function timeToMin(t) { const [h, m] = t.split(':').map(Number); return h * 60 + m; }
    function minToTime(m) { return String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0'); }

    const start = timeToMin(doctor.work_start);
    const end = timeToMin(doctor.work_end);
    const lunchStart = timeToMin(doctor.lunch_start);
    const lunchEnd = timeToMin(doctor.lunch_end);

    for (let t = start; t < end; t += durMin) {
      const timeStr = minToTime(t);
      if (t >= lunchStart && t < lunchEnd) {
        slots.push({ time: timeStr, type: 'lunch' });
      } else if (booked.includes(timeStr)) {
        slots.push({ time: timeStr, type: 'booked' });
      } else {
        slots.push({ time: timeStr, type: 'free' });
      }
    }
    return slots;
  }

  function selectSlot(time) {
    State.apt.selectedSlot = time;
    renderSlotGrid();
    openBookingModal();
  }

  function changeSlotDate(delta) {
    const d = new Date(State.apt.selectedDate);
    d.setDate(d.getDate() + delta);
    State.apt.selectedDate = d.toISOString().slice(0, 10);
    State.apt.selectedSlot = null;
    renderSlotGrid();
  }

    function openBookingModal(slot) {
    if (slot) State.apt.selectedSlot = slot;
    if (!State.apt.selectedDoctorId && State.data.doctors?.length) {
      State.apt.selectedDoctorId = State.data.doctors[0].id;
    }
    const doctor = (State.data.doctors || []).find(d => d.id === State.apt.selectedDoctorId) || State.data.doctors?.[0];
    if (!State.apt.selectedSlot) {
      State.apt.selectedSlot = '10:00';
    }
    const modal = document.getElementById('modal-apt-booking');
    if (!modal) return;
    setValue('apt-modal-doctor', doctor ? `${doctor.full_name} — ${doctor.room || '1-Kabinet'}` : 'Shifokor biriktirilgan');
    setValue('apt-modal-date', `${dayName(State.apt.selectedDate)}, ${formatDate(State.apt.selectedDate)}`);
    setValue('apt-modal-time', State.apt.selectedSlot);
    openModal('modal-apt-booking');
  }

  async function submitAppointment() {
    const name = document.getElementById('apt-patient-name')?.value.trim();
    const phone = document.getElementById('apt-patient-phone')?.value.trim();
    const serviceType = document.getElementById('apt-service-type')?.value || 'outpatient';
    const program = document.getElementById('apt-program')?.value;
    const notes = document.getElementById('apt-notes')?.value.trim();
    const isAnon = document.getElementById('apt-anon-check')?.checked;

    if (!isAnon && !name) { showToast('Bemor ismini kiriting', 'error'); return; }
    if (!State.apt.selectedDoctorId) { showToast('Shifokorni tanlang', 'error'); return; }

    const aptId = randomId('APT-2026');
    const newApt = {
      id: aptId,
      doctor_id: State.apt.selectedDoctorId,
      patient_name: isAnon ? 'Anonim Bemor' : name,
      patient_phone: isAnon ? '—' : phone,
      date: State.apt.selectedDate,
      time: State.apt.selectedSlot,
      service_type: serviceType,
      program,
      status: 'confirmed',
      notes,
      is_anonymous: isAnon,
      created_at: new Date().toISOString(),
    };

    // Booked only once the server has it. The answer used to be ignored, so a
    // refused booking still took the slot on screen; and a second request
    // then registered the patient again through /api/patients, leaving a
    // duplicate record behind every appointment -- the appointment endpoint
    // already finds or registers the patient itself. The id comes from the
    // server, which checks it is free.
    const payload = Object.assign({}, newApt);
    delete payload.id;
    try {
      const res = await fetch('/api/reception/appointment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showToast(data.error || "Qabul saqlanmadi. Qayta urinib ko'ring.", 'error');
        return;
      }
      if (data.id) newApt.id = data.id;
      if (data.patient_id) newApt.patient_id = data.patient_id;
    } catch (e) {
      showToast("Server bilan aloqa yo'q — qabul saqlanmadi.", 'error');
      return;
    }

    if (!State.data.appointments) State.data.appointments = [];
    State.data.appointments.push(newApt);

    // Mark slot as booked
    const key = State.apt.selectedDoctorId + '_' + State.apt.selectedDate;
    if (!State.apt.bookedSlots[key]) State.apt.bookedSlots[key] = [];
    State.apt.bookedSlots[key].push(State.apt.selectedSlot);

    closeModal('modal-apt-booking');
    document.getElementById('apt-booking-form')?.reset();
    State.apt.selectedSlot = null;
    renderSlotGrid();
    renderKPIs();
    renderTodayAppointmentsList();
    showToast(`✓ ${formatDate(newApt.date)} soat ${newApt.time} ga yozildi`, 'success');
  }

  function renderTodayAppointmentsList() {
    const container = document.getElementById('today-appointments-list');
    if (!container) return;
    const today = todayStr();
    const apts = (State.data.appointments || []).filter(a => a.date === today);

    if (!apts.length) {
      container.innerHTML = '<div class="empty-state"><i class="fas fa-calendar-check"></i><p>Bugun uchun yozilganlar yo\'q</p></div>';
      return;
    }

    container.innerHTML = apts.sort((a, b) => a.time.localeCompare(b.time)).map(apt => {
      const doctor = (State.data.doctors || []).find(d => d.id === apt.doctor_id);
      const pillCls = { booked: 'pill-booked', completed: 'pill-completed', cancelled: 'pill-cancelled', converted: 'pill-converted' }[apt.status] || 'pill-new';
      const pillLabel = { booked: 'Bron qilindi', completed: 'Bo\'ldi', cancelled: 'Bekor', converted: 'Qabul qilindi' }[apt.status] || apt.status;

      return `
        <div class="walk-in-card" style="border-color: rgba(20,184,166,0.15)">
          <div class="walk-in-icon" style="background: rgba(20,184,166,0.12); color: var(--primary-light); font-family: var(--font-mono); font-size: 0.85rem; font-weight:800;">${apt.time}</div>
          <div class="walk-in-main">
            <div class="walk-in-name">${apt.patient_name} ${apt.is_anonymous ? '<i class="fas fa-user-secret" style="color:#a855f7;font-size:0.7rem;"></i>' : ''}</div>
            <div class="walk-in-detail">${doctor ? doctor.full_name + ' • ' + doctor.room : apt.doctor_id} | ${serviceTypeName(apt.service_type)}</div>
            ${apt.notes ? `<div class="walk-in-detail" style="margin-top:3px;">${apt.notes}</div>` : ''}
          </div>
          <div style="display:flex;flex-direction:column;gap:0.4rem;align-items:flex-end;">
            <span class="status-pill ${pillCls}">${pillLabel}</span>
            <div style="display:flex;gap:0.3rem;align-items:center;">
              <button class="btn-portal btn-primary-portal" style="padding:3px 8px;font-size:0.7rem;" onclick="window.FMH_Reception.startDirectIntake({ name: '${(apt.patient_name||'').replace(/'/g, "\\'")}', phone: '${(apt.patient_phone||'').replace(/'/g, "\\'")}', serviceType: '${apt.service_type||'inpatient'}', doctorId: '${apt.doctor_id||''}', notes: '${(apt.notes||'').replace(/'/g, "\\'")}' })" title="Statsionar yoki Qabulga o'tkazish">
                <i class="fas fa-user-check"></i> Qabul Qilish
              </button>
              <button class="btn-portal btn-outline-portal" style="padding:3px 8px;font-size:0.7rem;" onclick="window.FMH_Reception.cancelAppointment('${apt.id}')" title="Bekor qilish">
                <i class="fas fa-times"></i>
              </button>
            </div>
          </div>
        </div>`;
    }).join('');
  }

  function cancelAppointment(aptId) {
    const apt = (State.data.appointments || []).find(a => a.id === aptId);
    if (!apt) return;
    apt.status = 'cancelled';
    // Remove from booked slots
    const key = apt.doctor_id + '_' + apt.date;
    if (State.apt.bookedSlots[key]) {
      State.apt.bookedSlots[key] = State.apt.bookedSlots[key].filter(t => t !== apt.time);
    }
    renderSlotGrid();
    renderTodayAppointmentsList();
    renderKPIs();
    showToast('Yozuv bekor qilindi', 'warning');
  }

  // ============================================================
  // TAB 3: CALL LOG / CRM
  // ============================================================
  function renderCallLogTab() {
    const container = document.getElementById('call-log-list');
    if (!container) return;
    let calls = State.data.call_logs || [];
    if (State.callFilter !== 'all') calls = calls.filter(c => c.status === State.callFilter);
    if (!calls.length) {
      container.innerHTML = '<div class="empty-state"><i class="fas fa-phone-slash"></i><h3>Qo\'ng\'iroqlar yo\'q</h3><p>Tanlangan filtr bo\'yicha ma\'lumot topilmadi</p></div>';
      return;
    }
    container.innerHTML = calls.slice().reverse().map(call => {
      const pillMap = { new: ['pill-new', 'Yangi'], callback_needed: ['pill-callback', 'Qayta qo\'ng\'iroq'], booked: ['pill-booked', 'Yozildi'], converted: ['pill-converted', 'Qabul qilindi'], lost: ['pill-cancelled', 'Yo\'qoldi'] };
      const [pillCls, pillLabel] = pillMap[call.status] || ['pill-new', call.status];
      const interestIcon = { inpatient: 'fa-bed', outpatient: 'fa-stethoscope', home_visit: 'fa-house-medical', anonymous: 'fa-user-secret' }[call.service_interest] || 'fa-question';

      return `
        <div class="call-log-card" id="call-${call.id}">
          <div class="call-log-icon" style="background: rgba(99,102,241,0.12); color: var(--indigo-light);">
            <i class="fas fa-phone-alt"></i>
          </div>
          <div>
            <div class="call-log-caller">${call.caller_name || 'Noma\'lum'}</div>
            <div class="call-log-phone"><i class="fas fa-phone" style="font-size:0.65rem;"></i> ${call.caller_phone}</div>
            <div class="call-log-time"><i class="fas fa-clock" style="font-size:0.6rem;"></i> ${formatDateTime(call.call_time)} • Davomiyligi: ${formatDuration(call.duration_sec)}</div>
            ${call.notes ? `<div class="call-log-notes">${call.notes}</div>` : ''}
            <div class="call-log-meta">
              <span class="interest-chip"><i class="fas ${interestIcon}"></i> ${serviceTypeName(call.service_interest)}</span>
              ${call.program_interest ? `<span class="interest-chip"><i class="fas fa-capsules"></i> ${programName(call.program_interest)}</span>` : ''}
              ${call.follow_up_date ? `<span class="interest-chip" style="color:var(--amber);"><i class="fas fa-calendar-alt"></i> Qayta: ${formatDate(call.follow_up_date)}</span>` : ''}
              ${call.operator ? `<span class="interest-chip"><i class="fas fa-headset"></i> ${call.operator}</span>` : ''}
            </div>
          </div>
          <div class="call-actions">
            <span class="status-pill ${pillCls}">${pillLabel}</span>
            <div style="display:flex;gap:0.3rem;flex-wrap:wrap;justify-content:flex-end;">
              <button class="btn-portal btn-primary-portal" style="padding:4px 9px;font-size:0.7rem;" onclick="window.FMH_Reception.startDirectIntake({ name: '${(call.caller_name||'').replace(/'/g, "\\'")}', phone: '${(call.caller_phone||'').replace(/'/g, "\\'")}', serviceType: '${call.service_interest||'inpatient'}', notes: '${(call.notes||'').replace(/'/g, "\\'")}' })" title="Qo'ng'iroqdan Bemor Qabulini Boshlash">
                <i class="fas fa-user-plus"></i> Qabul Qilish
              </button>
              <button class="btn-portal btn-outline-portal" style="padding:4px 9px;font-size:0.7rem;" onclick="window.FMH_Reception.openEditCallModal('${call.id}')">
                <i class="fas fa-edit"></i> Yangilash
              </button>
              <button class="btn-portal btn-indigo-portal" style="padding:4px 9px;font-size:0.7rem;" onclick="window.FMH_Reception.convertCallToAppointment('${call.id}')">
                <i class="fas fa-calendar-plus"></i> Yozish
              </button>
            </div>
          </div>
        </div>`;
    }).join('');
  }

  function filterCalls(status) {
    State.callFilter = status;
    document.querySelectorAll('.call-filter-btn').forEach(b => b.classList.toggle('active', b.dataset.filter === status));
    renderCallLogTab();
  }

  function openNewCallModal() {
    State.editingCallId = null;
    document.getElementById('call-modal-title').textContent = 'Yangi Qo\'ng\'iroq Qayd Etish';
    document.getElementById('call-log-form')?.reset();
    // set default time
    const dt = document.getElementById('call-datetime');
    if (dt) dt.value = new Date().toISOString().slice(0, 16);
    openModal('modal-call-log');
  }

  function openEditCallModal(callId) {
    const call = (State.data.call_logs || []).find(c => c.id === callId);
    if (!call) return;
    State.editingCallId = callId;
    document.getElementById('call-modal-title').textContent = 'Qo\'ng\'iroqni Tahrirlash';
    setVal('call-caller-name', call.caller_name);
    setVal('call-caller-phone', call.caller_phone);
    setVal('call-datetime', call.call_time?.slice(0, 16));
    setVal('call-duration', call.duration_sec);
    setVal('call-service-interest', call.service_interest);
    setVal('call-program-interest', call.program_interest);
    setVal('call-status', call.status);
    setVal('call-follow-up', call.follow_up_date);
    setVal('call-notes', call.notes);
    openModal('modal-call-log');
  }

  function setVal(id, val) {
    const el = document.getElementById(id);
    if (el) el.value = val || '';
  }

  async function submitCallLog() {
    const name = document.getElementById('call-caller-name')?.value.trim();
    const phone = document.getElementById('call-caller-phone')?.value.trim();
    const callTime = document.getElementById('call-datetime')?.value;
    const duration = parseInt(document.getElementById('call-duration')?.value) || 0;
    const serviceInterest = document.getElementById('call-service-interest')?.value;
    const programInterest = document.getElementById('call-program-interest')?.value;
    const status = document.getElementById('call-status')?.value || 'new';
    const followUp = document.getElementById('call-follow-up')?.value;
    const notes = document.getElementById('call-notes')?.value.trim();

    if (!phone) { showToast('Telefon raqamini kiriting', 'error'); return; }

    if (State.editingCallId) {
      const call = (State.data.call_logs || []).find(c => c.id === State.editingCallId);
      if (call) {
        Object.assign(call, { caller_name: name || 'Noma\'lum', caller_phone: phone, call_time: callTime, duration_sec: duration, service_interest: serviceInterest, program_interest: programInterest, status, follow_up_date: followUp || null, notes });
        showToast('Qo\'ng\'iroq yangilandi', 'success');
      }
    } else {
      const newCall = {
        id: randomId('CALL-2026'),
        caller_name: name || 'Noma\'lum',
        caller_phone: phone,
        call_time: callTime || new Date().toISOString(),
        duration_sec: duration,
        service_interest: serviceInterest,
        program_interest: programInterest,
        status,
        priority: 'medium',
        follow_up_date: followUp || null,
        notes,
        operator: 'Administrator',
        created_at: new Date().toISOString(),
      };
      if (!State.data.call_logs) State.data.call_logs = [];
      State.data.call_logs.push(newCall);

      try {
        await fetch('/api/reception/call-log', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(newCall)
        });
      } catch (e) {}

      showToast('✓ Yangi qo\'ng\'iroq qayd etildi', 'success');
    }

    closeModal('modal-call-log');
    renderCallLogTab();
    renderKPIs();
  }

  function convertCallToAppointment(callId) {
    const call = (State.data.call_logs || []).find(c => c.id === callId);
    if (!call) return;
    // Pre-fill appointment modal
    call.status = 'booked';
    switchTab('appointments');
    showToast('Shifokor va vaqt slotini tanlang', 'info');
    renderCallLogTab();
  }

  // ============================================================
  // TAB 4: PATIENT DIRECTORY
  // ============================================================
  function renderDirectoryTab() {
    const container = document.getElementById('patient-directory-body');
    if (!container) return;

    let rows = State.patients.length ? State.patients : buildOfflinePatients();
    const q = State.directorySearch.toLowerCase();
    if (q) rows = rows.filter(p => (p.full_name || '').toLowerCase().includes(q) || (p.patient_code || '').toLowerCase().includes(q) || (p.phone || '').toLowerCase().includes(q));
    if (State.directoryFilter !== 'all') rows = rows.filter(p => p.status === State.directoryFilter);

    if (!rows.length) {
      container.innerHTML = `<tr><td colspan="8"><div class="empty-state"><i class="fas fa-user-slash"></i><p>Bemor topilmadi</p></div></td></tr>`;
      return;
    }

    container.innerHTML = rows.map(p => {
      const admission = (State.admissions || []).find(a => a.patient_id === p.id && a.status === 'active');
      const statusPill = admission ? '<span class="status-pill pill-admitted">Yotmoqda</span>' :
        '<span class="status-pill pill-completed">Chiqarilgan</span>';

      return `<tr>
        <td><span class="patient-code-cell">${p.patient_code || '—'}</span></td>
        <td class="patient-name-cell">${p.full_name || 'Anonim'}</td>
        <td><span style="font-family:var(--font-mono);font-size:0.78rem;">${p.phone || '—'}</span></td>
        <td>${formatDate(p.created_at)}</td>
        <td>${admission ? `<span style="font-family:var(--font-mono);font-size:0.75rem;color:var(--primary-light);">${admission.bed_code || admission.bed_id}</span>` : '—'}</td>
        <td>${admission ? `<span class="status-pill pill-new" style="font-size:0.63rem;">${programName(admission.program_type)}</span>` : '—'}</td>
        <td>${statusPill}</td>
        <td>
          <div style="display:flex;gap:0.3rem;">
            <button class="btn-portal btn-outline-portal" style="padding:3px 7px;font-size:0.68rem;" onclick="window.FMH_Reception.viewPatientDossier('${p.id}')" title="Dossier"><i class="fas fa-folder-open"></i></button>
            <button class="btn-portal btn-primary-portal" style="padding:3px 7px;font-size:0.68rem;" onclick="window.FMH_Reception.printPatientReceipt('${p.id}')" title="Kvitansiya"><i class="fas fa-print"></i></button>
            <button class="btn-portal btn-danger-portal" style="padding:3px 7px;font-size:0.68rem;background:rgba(239,68,68,0.15);color:#f87171;border:1px solid rgba(239,68,68,0.3);" onclick="window.FMH_Reception.deletePatient('${p.id}')" title="O'chirish"><i class="fas fa-trash-alt"></i></button>
          </div>
        </td>
      </tr>`;
    }).join('');

    setValue('directory-count', rows.length);
  }

  async function deletePatient(patientId) {
    const p = State.patients.find(pt => pt.id === patientId || pt.patient_code === patientId);
    const pName = p ? p.full_name : patientId;

    const confirmed = await fmhConfirm({
      title: "Bemorni O'chirish",
      message: `Haqiqatan ham <strong>${pName}</strong> bemorini va barcha bog'liq qabul, to'lov va joylashuv ma'lumotlarini butunlay o'chirmoqchimisiz?`,
      confirmText: "O'chirish",
      cancelText: "Bekor Qilish",
      type: 'danger'
    });
    if (!confirmed) {
      return;
    }

    try {
      await fetch('/api/patients/' + encodeURIComponent(patientId), { method: 'DELETE' });
    } catch (e) {
      console.warn('DELETE patient error:', e);
    }

    State.patients = State.patients.filter(pt => pt.id !== patientId && pt.patient_code !== patientId);
    State.admissions = (State.admissions || []).filter(a => a.patient_id !== patientId && a.patient_code !== patientId);
    renderDirectoryTab();
    renderKPIs();
    closeModal('modal-patient-dossier');
    showToast(`🗑️ "${pName}" bazadan butunlay o'chirildi!`, 'danger');
  }

  function buildOfflinePatients() {
    const walkIns = State.data.walk_ins || [];
    const homeVisits = State.data.home_visits || [];
    return [
      ...walkIns.map((w, i) => ({
        id: 'PAT-OFF-' + i,
        patient_code: 'FMH-2026-' + String(1000 + i).padStart(4, '0'),
        full_name: w.is_anonymous ? 'Anonim Bemor' : w.patient_name,
        phone: w.patient_phone,
        created_at: `${w.date}T${w.time}:00`,
        status: w.status,
      })),
      ...homeVisits.map((h, i) => ({
        id: 'PAT-HV-' + i,
        patient_code: 'FMH-2026-HV-' + String(i + 1).padStart(3, '0'),
        full_name: h.client_name,
        phone: h.client_phone,
        created_at: h.requested_at,
        status: h.status,
      })),
    ];
  }

  function searchDirectory(q) {
    State.directorySearch = q;
    renderDirectoryTab();
  }

  function filterDirectory(filter) {
    State.directoryFilter = filter;
    renderDirectoryTab();
  }

  function viewPatientDossier(patientId) {
    const patient = State.patients.find(p => p.id === patientId);
    if (!patient) { showToast('Bemorning to\'liq kartasi topilmadi', 'info'); return; }
    const admissions = (State.admissions || []).filter(a => a.patient_id === patientId);
    const modal = document.getElementById('modal-patient-dossier');
    if (!modal) return;
    setValue('dossier-code', patient.patient_code || '—');
    setValue('dossier-name', patient.full_name || 'Anonim');
    setValue('dossier-phone', patient.phone || '—');
    setValue('dossier-created', formatDate(patient.created_at));
    setValue('dossier-visits', admissions.length + ' marta');
    // Admissions history
    const histEl = document.getElementById('dossier-admissions');
    if (histEl) {
      if (!admissions.length) {
        histEl.innerHTML = '<div class="empty-state" style="padding:1.5rem;"><p>Tashrif tarixi yo\'q</p></div>';
      } else {
        histEl.innerHTML = admissions.map(a => `
          <div class="apt-summary-row">
            <span class="label">${formatDate(a.start_date)} → ${formatDate(a.planned_end_date)}</span>
            <span class="value">${a.bed_code || a.bed_id}</span>
            <span class="status-pill ${a.status === 'active' ? 'pill-admitted' : 'pill-completed'}">${a.status === 'active' ? 'Yotmoqda' : 'Chiqarilgan'}</span>
          </div>`).join('');
      }
    }
    modal._patientId = patientId;
    openModal('modal-patient-dossier');
  }

  // ============================================================
  // MODALS
  // ============================================================
  function openModal(id) {
    const m = document.getElementById(id);
    if (m) m.classList.add('open');
  }

  function closeModal(id) {
    const m = document.getElementById(id);
    if (m) m.classList.remove('open');
  }

  function closeAllModals() {
    document.querySelectorAll('.modal-backdrop').forEach(m => m.classList.remove('open'));
  }

  // Close on backdrop click
  document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-backdrop')) closeAllModals();
  });

    // ============================================================
  // PRINT (POWERED BY UNIFIED ENTERPRISE PRINT ENGINE)
  // ============================================================
  function printAdmissionSlip(data, admId) {
    if (window.FMH_Print) {
      window.FMH_Print.admissionSlip(data, admId);
    } else {
      window.print();
    }
  }

  // Reads what the desk has actually entered on the intake form. Returns
  // null when the form is still untouched, because an empty sheet is a
  // legitimate thing to print for the counter. Nothing is invented: a
  // field the desk left alone comes back empty and prints as a ruled line.
  function collectIntakeForPrint() {
    const val = id => (document.getElementById(id)?.value || '').trim();
    const label = id => {
      const sel = document.getElementById(id);
      if (!sel || sel.selectedIndex < 0) return '';
      const opt = sel.options[sel.selectedIndex];
      return opt && opt.value ? (opt.textContent || '').trim() : '';
    };

    const isAnon = Boolean(document.getElementById('intake-anon-check')?.checked);
    const days = parseInt(val('intake-days'), 10) || 0;
    const startDate = val('intake-start-date');
    let endDate = '';
    if (startDate && days > 0) {
      try {
        const d = new Date(startDate);
        d.setDate(d.getDate() + days);
        endDate = formatDate(d.toISOString().slice(0, 10));
      } catch (e) { endDate = ''; }
    }

    const data = {
      patient_name: isAnon ? 'ANONIM BEMOR' : val('intake-patient-name'),
      patient_phone: isAnon ? '' : val('intake-patient-phone'),
      birth_date: isAnon ? '' : val('intake-patient-birthdate'),
      is_anonymous: isAnon,
      address: val('intake-home-address'),
      service_type: State.intake.serviceType,
      program_label: label('intake-program-select'),
      doctor_name: label('intake-doctor-select'),
      referral_label: label('intake-referral-select'),
      pay_method_label: label('intake-pay-method'),
      bed_id: State.intake.selectedBed || '',
      start_date: startDate ? formatDate(startDate) : '',
      end_date: endDate,
      days: days,
      daily_rate: parseFloat(val('intake-daily-rate')) || 0,
      discount_percent: parseFloat(val('intake-discount')) || 0,
      advance: parseFloat(val('intake-advance')) || 0,
      notes: val('intake-notes')
    };

    const touched = Boolean(
      val('intake-patient-name') || val('intake-patient-phone') ||
      isAnon || State.intake.selectedBed || data.advance > 0 ||
      data.discount_percent > 0 || data.notes
    );
    return touched ? data : null;
  }

  function printBlankIntakeForm() {
    if (window.FMH_Print) {
      // This printed an empty template even when the intake form was fully
      // filled in, so the sheet the patient signs carried neither their
      // details nor the money. The form state is handed over now; an
      // untouched form still prints the empty version for the counter.
      window.FMH_Print.blankIntakeForm(collectIntakeForPrint());
    } else {
      window.print();
    }
  }

  function printPatientReceipt(patientId) {
    const patient = (State.patients || []).find(p => p.id === patientId) || { id: patientId, full_name: 'Anonim Bemor' };
    const admission = (State.admissions || []).find(a => a.patient_id === patientId) || {};
    if (window.FMH_Print) {
      // These fell back to 720 000 when the stay had no figures yet, so an
      // unpaid patient was handed a receipt saying 720 000 had been paid.
      // A receipt may only state what the invoice actually holds; a missing
      // figure prints as zero.
      window.FMH_Print.patientReceipt(patient, {
        // net_amount is the figure after the reception discount;
        // total_billed is before it. Printing the gross as the total made
        // the receipt disagree with what the patient was asked to pay.
        total_amount: Number(admission.net_amount) || Number(admission.total_billed) || 0,
        gross_amount: Number(admission.total_billed) || 0,
        discount_amount: Number(admission.discount_amount) || 0,
        paid_amount: Number(admission.total_paid) || 0,
      }, {
        id: `RCP-${Date.now().toString().slice(-4)}`,
        amount: Number(admission.total_paid) || 0,
        payment_method: 'cash',
        notes: 'Statsionar qabul to`lovi'
      });
    } else {
      window.print();
    }
  }

  // ============================================================
  // EXCEL EXPORT
  // ============================================================
  function exportToExcel() {
    if (typeof XLSX === 'undefined') { showToast('Excel moduli yuklanmagan', 'error'); return; }

    const wb = XLSX.utils.book_new();

    // Sheet 1: Appointments
    const apts = (State.data.appointments || []).map(a => {
      const d = (State.data.doctors || []).find(doc => doc.id === a.doctor_id);
      return {
        'ID': a.id,
        'Sana': a.date,
        'Vaqt': a.time,
        'Bemor': a.patient_name,
        'Telefon': a.patient_phone,
        'Shifokor': d?.full_name || a.doctor_id,
        'Xizmat turi': serviceTypeName(a.service_type),
        'Dastur': programName(a.program),
        'Status': a.status,
        'Eslatma': a.notes || '',
      };
    });
    if (apts.length) XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(apts), 'Qabul Yozishlari');

    // Sheet 2: Call Logs
    const calls = (State.data.call_logs || []).map(c => ({
      'ID': c.id,
      'Ism': c.caller_name,
      'Telefon': c.caller_phone,
      'Vaqt': c.call_time,
      'Davomiylik (sek)': c.duration_sec,
      'Xizmat qiziqishi': serviceTypeName(c.service_interest),
      'Dastur': programName(c.program_interest),
      'Status': c.status,
      'Operator': c.operator,
      'Eslatma': c.notes || '',
      'Qayta qo\'ng\'iroq': c.follow_up_date || '',
    }));
    if (calls.length) XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(calls), 'Qo\'ng\'iroqlar');

    // Sheet 3: Walk-ins
    const walkIns = [...(State.data.walk_ins || []), ...(State.data.home_visits || [])].map(w => ({
      'ID': w.id,
      'Sana': w.date || w.scheduled_for?.slice(0, 10),
      'Vaqt': w.time || w.scheduled_for?.slice(11, 16),
      'Bemor': w.patient_name || w.client_name || 'Anonim',
      'Telefon': w.patient_phone || w.client_phone || '—',
      'Turi': w.service_type ? serviceTypeName(w.service_type) : 'Uyga chaqiruv',
      'Dastur': programName(w.program),
      'Karavot': w.assigned_bed || '—',
      'Avans': w.payment_advance || w.fee || 0,
      'Status': w.status,
    }));
    if (walkIns.length) XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(walkIns), 'Qabullar');

    XLSX.writeFile(wb, `Qabulxona_${todayStr()}.xlsx`);
    showToast('Excel fayli yuklab olindi ✓', 'success');
  }

  // ============================================================
  // THEME ENGINE
  // ============================================================
  function applyTheme(theme) {
    if (window.FMH_Theme) {
      window.FMH_Theme.set(theme);
      return;
    }
    document.documentElement.setAttribute('data-theme', theme);
    document.body.className = `reception-portal ${theme}-mode`;
    localStorage.setItem('fmh_theme', theme);

    const btn = document.getElementById('reception-theme-toggle');
    if (btn) {
      if (theme === 'day') {
        btn.innerHTML = '<i class="fas fa-moon" style="color: #6366f1;"></i> <span>Tungi</span>';
      } else {
        btn.innerHTML = '<i class="fas fa-sun" style="color: #fbbf24;"></i> <span>Kunduzgi</span>';
      }
    }
  }

  function toggleTheme() {
    if (window.FMH_Theme) {
      return window.FMH_Theme.toggle();
    }
    const current = localStorage.getItem('fmh_theme') || 'night';
    const next = current === 'day' ? 'night' : 'day';
    applyTheme(next);
    showToast(next === 'day' ? '☀️ Kunduzgi rejim yoqildi' : '🌙 Tungi rejim yoqildi', 'info');
  }

  // ============================================================
  // PUBLIC API
  // ============================================================
    return {
    init,
    applyTheme,
    toggleTheme,
    selectBed,
    switchBedFloor,
    selectDoctor,
    selectSlot,
    changeSlotDate,
    cancelAppointment,
    submitIntakeForm,
    submitAppointment,
    confirmAdmission,
    openBookingModal,
    openAdmissionConfirmModal,
    openHomeVisitConfirmModal,
    openNewCallModal,
    openEditCallModal,
    submitCallLog,
    convertCallToAppointment,
    filterCalls,
    searchDirectory,
    filterDirectory,
    viewPatientDossier,
    printPatientReceipt,
    deletePatient,
    printBlankIntakeForm,
    exportToExcel,
    renderBedPicker,
    renderIntakeSections,
    updateCostPreview,
    refreshBedsFromBuildingManagement,
    closeModal,
    closeAllModals,
    openModal,
    switchTab,
    startDirectIntake,
    setBedDatePreset,
    updateBedPickerForSelectedDate,
    notifyBedConflict,
    renderRoomsBoard,
    renderRoomsTab,
    loadRequests,
    loadRoomsBoard,
    setRoomsBoardPreset,
  };

})();

// Boot & Real-Time Sync Listeners
document.addEventListener('DOMContentLoaded', () => {
  const saved = localStorage.getItem('fmh_theme') || 'night';
  window.FMH_Reception.applyTheme(saved);
  window.FMH_Reception.init();
});

// Another tab changed something the ward cares about, so re-read it from the
// server. The bed key this watched for ('..._V16') was two versions behind the
// one anything actually wrote, so this never fired for beds at all; occupancy
// no longer lives in localStorage either way.
window.addEventListener('storage', (e) => {
  if (e.key === 'FMH_RECEPTION_DATA_V1' || e.key === 'FMH_PATIENTS_V1') {
    window.FMH_Reception.refreshBedsFromBuildingManagement();
  }
});

window.addEventListener('fmh_bookings_updated', () => {
  window.FMH_Reception.refreshBedsFromBuildingManagement();
});
