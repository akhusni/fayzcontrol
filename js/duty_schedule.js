/**
 * FAYZ MEDICAL HOUSE — 24/7 DUTY SCHEDULE & SANITARKA CONTROLLER
 * Full Day/Night Theme Reactive, Multi-View, Month Navigator & Interactive Swap Engine
 */

(function () {
  'use strict';

  const SANITARKAS = [
    { id: "SAN-01", name: "Donoboyeva Laylo", full_name: "Donoboyeva Laylo Donoboyevna", phone: "+998 90 123-45-01" },
    { id: "SAN-02", name: "Egamqulova Xilola", full_name: "Egamqulova Xilola Xoshimqulovna", phone: "+998 90 123-45-02" },
    { id: "SAN-03", name: "Karabaeva Muxayyo", full_name: "Karabaeva Muxayyo Toshpo'latovna", phone: "+998 90 123-45-03" },
    { id: "SAN-04", name: "Karakulova Xurshida", full_name: "Karakulova Xurshida Mirzakim qizi", phone: "+998 90 123-45-04" },
    { id: "SAN-05", name: "Maxkamova Umida", full_name: "Maxkamova Umida Muminovna", phone: "+998 90 123-45-05" },
    { id: "SAN-06", name: "Musaxanova Fotima", full_name: "Musaxanova Fotima Danabayevna", phone: "+998 90 123-45-06" }
  ];

  const UZ_MONTHS = [
    "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
    "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"
  ];

  const UZ_WEEKDAYS = [
    "Yakshanba", "Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba"
  ];

  // State
  const State = {
    currentYear: 2026,
    currentMonth: 10, // 1-indexed (10 = Oktabr)
    activeView: 'calendar', // 'calendar' | 'table' | 'personal'
    selectedSanitar: 'all', // 'all' or sanitarka full_name
    searchQuery: '',
    rawShifts: [],
    dutyTariffs: { sanitar: 300000, nurse: 400000, doctor: 350000 }
  };

  function pad(n) {
    return String(n).padStart(2, '0');
  }

  function formatUZS(num) {
    if (!num) return "0 so'm";
    return Math.round(num).toLocaleString('uz-UZ') + " so'm";
  }

  function getDaysInMonth(year, month) {
    return new Date(year, month, 0).getDate();
  }

  // Generate continuous rotating shifts if not present in API for chosen month
  function ensureMonthShifts(year, month) {
    const daysInMonth = getDaysInMonth(year, month);
    const result = [];
    const nursesList = [
      "Abdukarimova Ra'no", "Atametova Tursunoy", "G'aniyeva Saygul",
      "Safarova Shaxnoza", "Saydaminova Ziyeda", "Xoltoyeva Shaxlo"
    ];
    const docsList = [
      "Dr. Umarov Xusan", "Dr. Shermuxamedova Farida", "Dr. Vasina Yuliya"
    ];

    for (let day = 1; day <= daysInMonth; day++) {
      const dateStr = `${year}-${pad(month)}-${pad(day)}`;
      const dt = new Date(year, month - 1, day);
      const weekday = UZ_WEEKDAYS[dt.getDay()];
      const isWeekend = dt.getDay() === 0 || dt.getDay() === 6;

      // Check if already in State.rawShifts
      const existing = State.rawShifts.find(s => s.date === dateStr);
      if (existing) {
        result.push(existing);
      } else {
        // Continuous cycle calculation based on day offset from 2026-01-01
        const epoch = new Date(2026, 0, 1);
        const diffDays = Math.floor((dt - epoch) / (1000 * 60 * 60 * 24));
        const san1 = SANITARKAS[(Math.abs(diffDays)) % SANITARKAS.length];
        const san2 = SANITARKAS[(Math.abs(diffDays) + 3) % SANITARKAS.length];
        const nurse = nursesList[(Math.abs(diffDays)) % nursesList.length];
        const doc = docsList[(Math.abs(diffDays)) % docsList.length];

        const newShift = {
          date: dateStr,
          day: day,
          month: month,
          year: year,
          weekday: weekday,
          is_weekend: isWeekend,
          sanitar_primary: san1.full_name,
          sanitar_primary_id: san1.id,
          sanitar_secondary: san2.full_name,
          sanitar_secondary_id: san2.id,
          sanitar_shift_time: "24 soat (08:00 - ertasi 08:00)",
          nurse_name: nurse,
          nurse_shift_time: "24 soat (08:00 - ertasi 08:00)",
          doctor_name: doc,
          doctor_shift_time: "Tungi smena (20:00 - 08:00)"
        };
        result.push(newShift);
      }
    }
    return result;
  }

  // -------------------------------------------------------------------------
  // INITIALIZATION & API FETCH
  // -------------------------------------------------------------------------
  async function init() {
    const today = new Date();
    State.currentYear = today.getFullYear();
    State.currentMonth = today.getMonth() + 1;

    try {
      const res = await fetch('/api/duty-schedule');
      if (res.ok) {
        const data = await res.json();
        if (data && Array.isArray(data.shifts) && data.shifts.length > 0) {
          State.rawShifts = data.shifts;
        }
      }
    } catch (e) {
      console.warn("Using local duty schedule rotation:", e);
    }

    renderAll();
    setupEventListeners();
  }

  function renderAll() {
    renderHeroToday();
    renderMonthDisplay();
    renderFilterPills();
    renderPersonalDashboard();

    if (State.activeView === 'calendar') {
      renderCalendar();
    } else if (State.activeView === 'table') {
      renderTable();
    } else if (State.activeView === 'personal') {
      renderPersonalTimeline();
    }

    updatePrintSheet();
  }

  // -------------------------------------------------------------------------
  // 1. HERO CARD: LIVE TODAY 24/7 POST
  // -------------------------------------------------------------------------
  function renderHeroToday() {
    const now = new Date();
    const todayStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    const curMonthShifts = ensureMonthShifts(now.getFullYear(), now.getMonth() + 1);
    const todayShift = curMonthShifts.find(s => s.date === todayStr) || curMonthShifts[0];

    const todayDateEl = document.getElementById('hero-today-date');
    if (todayDateEl) {
      todayDateEl.textContent = `${now.getDate()} ${UZ_MONTHS[now.getMonth()]} ${now.getFullYear()} (${UZ_WEEKDAYS[now.getDay()]})`;
    }

    if (todayShift) {
      const elSan = document.getElementById('hero-sanitar-name');
      const elNur = document.getElementById('hero-nurse-name');
      const elDoc = document.getElementById('hero-doctor-name');

      if (elSan) elSan.textContent = todayShift.sanitar_primary || "Donoboyeva Laylo";
      if (elNur) elNur.textContent = todayShift.nurse_name || "Hamshira smenada";
      if (elDoc) elDoc.textContent = todayShift.doctor_name || "Dr. Umarov Xusan";
    }
  }

  // -------------------------------------------------------------------------
  // 2. MONTH DISPLAY & CONTROLS
  // -------------------------------------------------------------------------
  function renderMonthDisplay() {
    const disp = document.getElementById('month-display-text');
    if (disp) {
      disp.textContent = `${UZ_MONTHS[State.currentMonth - 1]} ${State.currentYear}`;
    }
  }

  function prevMonth() {
    if (State.currentMonth === 1) {
      State.currentMonth = 12;
      State.currentYear--;
    } else {
      State.currentMonth--;
    }
    renderMonthDisplay();
    renderCurrentView();
    renderPersonalDashboard();
    updatePrintSheet();
  }

  function nextMonth() {
    if (State.currentMonth === 12) {
      State.currentMonth = 1;
      State.currentYear++;
    } else {
      State.currentMonth++;
    }
    renderMonthDisplay();
    renderCurrentView();
    renderPersonalDashboard();
    updatePrintSheet();
  }

  function goToToday() {
    const today = new Date();
    State.currentYear = today.getFullYear();
    State.currentMonth = today.getMonth() + 1;
    renderMonthDisplay();
    renderCurrentView();
    renderPersonalDashboard();
    updatePrintSheet();
  }

  // -------------------------------------------------------------------------
  // 3. SANITARKA FILTER PILLS & PERSONAL DASHBOARD
  // -------------------------------------------------------------------------
  function renderFilterPills() {
    const container = document.getElementById('sanitar-pills-list');
    if (!container) return;

    container.innerHTML = '';

    // "All" Button
    const allBtn = document.createElement('button');
    allBtn.type = 'button';
    allBtn.className = `sanitar-pill-btn ${State.selectedSanitar === 'all' ? 'active' : ''}`;
    allBtn.innerHTML = '<i class="fas fa-users"></i> Barcha Sanitarkalar';
    allBtn.onclick = () => selectSanitar('all');
    container.appendChild(allBtn);

    // Individual Sanitarkas
    SANITARKAS.forEach(san => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `sanitar-pill-btn ${State.selectedSanitar === san.full_name ? 'active' : ''}`;
      btn.innerHTML = `<i class="fas fa-broom"></i> ${san.name}`;
      btn.onclick = () => selectSanitar(san.full_name);
      container.appendChild(btn);
    });
  }

  function selectSanitar(name) {
    State.selectedSanitar = name;
    renderFilterPills();
    renderPersonalDashboard();
    renderCurrentView();
    updatePrintSheet();
  }

  function renderPersonalDashboard() {
    const card = document.getElementById('personal-kpi-container');
    if (!card) return;

    if (State.selectedSanitar === 'all') {
      card.style.display = 'none';
      return;
    }

    card.style.display = 'grid';

    const monthShifts = ensureMonthShifts(State.currentYear, State.currentMonth);
    const myShifts = monthShifts.filter(s => (s.sanitar_primary === State.selectedSanitar || s.sanitar_secondary === State.selectedSanitar));

    const totalCount = myShifts.length;
    const totalHours = totalCount * 24;
    const totalEarnings = totalCount * State.dutyTariffs.sanitar;

    // Next upcoming shift
    const now = new Date();
    const todayStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    const nextShift = myShifts.find(s => s.date >= todayStr);

    let nextText = "Bu oyda yakunlandi";
    if (nextShift) {
      if (nextShift.date === todayStr) {
        nextText = "🟢 BUGUN SMENADA!";
      } else {
        const parts = nextShift.date.split('-');
        nextText = `${parts[2]}-${UZ_MONTHS[parseInt(parts[1], 10) - 1].slice(0, 3)} (${nextShift.weekday.slice(0, 4)})`;
      }
    }

    const shortName = State.selectedSanitar.split(' ')[0] + ' ' + (State.selectedSanitar.split(' ')[1] || '');

    card.innerHTML = `
      <div class="personal-kpi-card">
        <div class="personal-kpi-label"><i class="fas fa-user-circle"></i> Xodim</div>
        <div class="personal-kpi-value" style="color: #fbbf24; font-size: 1.05rem;">${shortName}</div>
        <div class="personal-kpi-sub">Sanitarka (1-va 2-post)</div>
      </div>

      <div class="personal-kpi-card">
        <div class="personal-kpi-label"><i class="fas fa-calendar-check"></i> Smenalar Soni</div>
        <div class="personal-kpi-value" style="color: #38bdf8;">${totalCount} ta smena</div>
        <div class="personal-kpi-sub">${totalHours} ish soati (24h sutkalik)</div>
      </div>

      <div class="personal-kpi-card">
        <div class="personal-kpi-label"><i class="fas fa-coins"></i> Hisoblangan Summa</div>
        <div class="personal-kpi-value" style="color: #34d399;">${formatUZS(totalEarnings)}</div>
        <div class="personal-kpi-sub">1 smena = 300 000 so'm</div>
      </div>

      <div class="personal-kpi-card">
        <div class="personal-kpi-label"><i class="fas fa-clock"></i> Navbatdagi Smena</div>
        <div class="personal-kpi-value" style="color: #f43f5e; font-size: 1.05rem;">${nextText}</div>
        <div class="personal-kpi-sub">Smena vaqti: 08:00 - 08:00</div>
      </div>
    `;
  }

  // -------------------------------------------------------------------------
  // 4. VIEW SWITCHER
  // -------------------------------------------------------------------------
  function switchView(viewName) {
    State.activeView = viewName;

    document.querySelectorAll('.duty-view-pill-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-view') === viewName);
    });

    const vCal = document.getElementById('view-calendar-panel');
    const vTab = document.getElementById('view-table-panel');
    const vPer = document.getElementById('view-personal-panel');

    if (vCal) vCal.style.display = viewName === 'calendar' ? 'block' : 'none';
    if (vTab) vTab.style.display = viewName === 'table' ? 'block' : 'none';
    if (vPer) vPer.style.display = viewName === 'personal' ? 'block' : 'none';

    renderCurrentView();
  }

  function renderCurrentView() {
    if (State.activeView === 'calendar') renderCalendar();
    else if (State.activeView === 'table') renderTable();
    else if (State.activeView === 'personal') renderPersonalTimeline();
  }

  // -------------------------------------------------------------------------
  // 5. VIEW 1: MONTHLY CALENDAR GRID
  // -------------------------------------------------------------------------
  function renderCalendar() {
    const container = document.getElementById('calendar-cells-matrix');
    if (!container) return;

    container.innerHTML = '';

    const year = State.currentYear;
    const month = State.currentMonth;
    const daysInMonth = getDaysInMonth(year, month);
    const shifts = ensureMonthShifts(year, month);

    // Calculate starting day of the week (Monday = 0, Sunday = 6)
    const firstDate = new Date(year, month - 1, 1);
    let startDayIndex = firstDate.getDay(); // 0 is Sunday
    startDayIndex = startDayIndex === 0 ? 6 : startDayIndex - 1; // 0 is Monday

    // 1. Add leading empty placeholder cells
    for (let i = 0; i < startDayIndex; i++) {
      const empty = document.createElement('div');
      empty.className = 'cal-cell is-empty';
      container.appendChild(empty);
    }

    const today = new Date();
    const todayStr = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;

    // 2. Add actual month days
    shifts.forEach(shift => {
      const isToday = shift.date === todayStr;
      const isMyShift = State.selectedSanitar !== 'all' && (shift.sanitar_primary === State.selectedSanitar || shift.sanitar_secondary === State.selectedSanitar);
      const isDimmed = State.selectedSanitar !== 'all' && !isMyShift;

      const cell = document.createElement('div');
      let cellClasses = 'cal-cell';
      if (isToday) cellClasses += ' is-today';
      if (isMyShift) cellClasses += ' is-my-shift';
      if (isDimmed) cellClasses += ' is-dimmed';
      cell.className = cellClasses;

      // Sanitarka short name
      const sanShort = (shift.sanitar_primary || '').split(' ')[1] || (shift.sanitar_primary || '').split(' ')[0] || '—';
      const nurseShort = (shift.nurse_name || '').split(' ')[0] || '—';
      const docShort = (shift.doctor_name || '').split(' ')[1] || (shift.doctor_name || '').split(' ')[0] || '—';

      cell.innerHTML = `
        <div class="cal-cell-header">
          <span class="cal-cell-day-num">${shift.day} <span style="font-size:0.68rem; font-weight:600; color:var(--text-muted);">${shift.weekday.slice(0, 4)}</span></span>
          ${isToday ? '<span class="cal-today-tag">BUGUN</span>' : ''}
          ${isMyShift ? '<span class="cal-myshift-tag">SMENAM</span>' : ''}
        </div>

        <div class="cal-mini-badge badge-sanitar" title="Sanitarka (1-Post): ${shift.sanitar_primary}">
          <i class="fas fa-broom badge-icon"></i>
          <span class="badge-role-tag">San:</span>
          <span class="badge-name">${sanShort}</span>
        </div>

        <div class="cal-mini-badge badge-nurse" title="Hamshira: ${shift.nurse_name}">
          <i class="fas fa-syringe badge-icon"></i>
          <span class="badge-role-tag">Ham:</span>
          <span class="badge-name">${nurseShort}</span>
        </div>

        <div class="cal-mini-badge badge-doctor" title="Shifokor: ${shift.doctor_name}">
          <i class="fas fa-user-md badge-icon"></i>
          <span class="badge-role-tag">Shif:</span>
          <span class="badge-name">${docShort}</span>
        </div>
      `;

      cell.onclick = () => openDayModal(shift);
      container.appendChild(cell);
    });
  }

  // -------------------------------------------------------------------------
  // 6. VIEW 2: TABLE ROSTER
  // -------------------------------------------------------------------------
  function renderTable() {
    const tbody = document.getElementById('duty-table-body');
    if (!tbody) return;

    tbody.innerHTML = '';
    const shifts = ensureMonthShifts(State.currentYear, State.currentMonth);
    const today = new Date();
    const todayStr = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;

    const query = State.searchQuery.toLowerCase().trim();

    shifts.forEach(shift => {
      // Filter by selected sanitarka
      if (State.selectedSanitar !== 'all') {
        const matchesSanitar = (shift.sanitar_primary === State.selectedSanitar || shift.sanitar_secondary === State.selectedSanitar);
        if (!matchesSanitar) return;
      }

      // Filter by query
      if (query) {
        const searchable = `${shift.date} ${shift.weekday} ${shift.sanitar_primary} ${shift.nurse_name} ${shift.doctor_name}`.toLowerCase();
        if (!searchable.includes(query)) return;
      }

      const isToday = shift.date === todayStr;
      const isMyRow = State.selectedSanitar !== 'all' && (shift.sanitar_primary === State.selectedSanitar || shift.sanitar_secondary === State.selectedSanitar);

      const tr = document.createElement('tr');
      if (isToday) tr.className = 'is-today-row';
      else if (isMyRow) tr.className = 'is-my-row';

      let statusBadge = '';
      if (isToday) {
        statusBadge = '<span style="color:#38bdf8; font-weight:800; background:rgba(56,189,248,0.15); padding:3px 8px; border-radius:6px;"><i class="fas fa-dot-circle"></i> Bugun</span>';
      } else if (shift.date > todayStr) {
        statusBadge = '<span style="color:#34d399; font-weight:700; background:rgba(16,185,129,0.12); padding:3px 8px; border-radius:6px;">Rejada</span>';
      } else {
        statusBadge = '<span style="color:#94a3b8; font-weight:600;">O\'tgan</span>';
      }

      tr.innerHTML = `
        <td>
          <div style="font-weight:800; font-family:var(--font-mono);">${shift.date}</div>
          <div style="font-size:0.75rem; color:var(--text-muted);">${shift.weekday}</div>
        </td>
        <td>
          <strong style="color: #fbbf24;"><i class="fas fa-broom"></i> ${shift.sanitar_primary || '—'}</strong>
          <div style="font-size:0.72rem; color:var(--text-dim);">24-soatlik post</div>
        </td>
        <td>
          <span style="color: #34d399; font-weight:700;"><i class="fas fa-syringe"></i> ${shift.nurse_name || '—'}</span>
          <div style="font-size:0.72rem; color:var(--text-dim);">Butun bino (1 & 2-qavat)</div>
        </td>
        <td>
          <span style="color: #c084fc; font-weight:700;"><i class="fas fa-user-md"></i> ${shift.doctor_name || '—'}</span>
          <div style="font-size:0.72rem; color:var(--text-dim);">Tungi smena (20:00 - 08:00)</div>
        </td>
        <td style="font-family:var(--font-mono); font-size:0.8rem; color:var(--text-secondary);">
          ${shift.sanitar_shift_time}
        </td>
        <td style="text-align: center;">
          ${statusBadge}
        </td>
      `;

      tr.style.cursor = 'pointer';
      tr.onclick = () => openDayModal(shift);
      tbody.appendChild(tr);
    });
  }

  // -------------------------------------------------------------------------
  // 7. VIEW 3: PERSONAL TIMELINE
  // -------------------------------------------------------------------------
  function renderPersonalTimeline() {
    const container = document.getElementById('timeline-cards-grid');
    if (!container) return;

    container.innerHTML = '';
    const shifts = ensureMonthShifts(State.currentYear, State.currentMonth);
    const today = new Date();
    const todayStr = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;

    // Filter shifts for selected sanitarka (or all if none picked)
    const targetStaff = State.selectedSanitar === 'all' ? SANITARKAS[0].full_name : State.selectedSanitar;
    const myShifts = shifts.filter(s => (s.sanitar_primary === targetStaff || s.sanitar_secondary === targetStaff));

    if (myShifts.length === 0) {
      container.innerHTML = `
        <div style="grid-column: 1 / -1; padding: 2.5rem; text-align: center; color: var(--text-muted);">
          <i class="fas fa-calendar-times" style="font-size: 2.5rem; margin-bottom: 12px; color: var(--text-dim);"></i>
          <div style="font-weight: 700; font-size: 1.1rem; color: var(--text-secondary);">Ushbu oy uchun smena topilmadi</div>
          <div style="font-size: 0.85rem; margin-top: 4px;">Boshqa oyni tanlang yoki yuqoridagi sanitarka ismini almashtiring.</div>
        </div>
      `;
      return;
    }

    myShifts.forEach(shift => {
      const isToday = shift.date === todayStr;
      const isPast = shift.date < todayStr;

      const card = document.createElement('div');
      card.className = `timeline-shift-card ${isToday ? 'card-today' : ''}`;

      card.innerHTML = `
        <div class="timeline-card-date">
          <span><i class="fas fa-calendar-day" style="color:#f59e0b;"></i> ${shift.date}</span>
          ${isToday ? '<span class="cal-today-tag">BUGUN SMENADA</span>' : (isPast ? '<span style="font-size:0.7rem; color:var(--text-dim);">Yakunlandi</span>' : '<span style="font-size:0.7rem; color:#34d399; font-weight:700;">Rejalashtirilgan</span>')}
        </div>
        <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 8px;">
          ${shift.weekday} • 24 Soatlik Navbatchilik
        </div>

        <div class="timeline-card-duty-info">
          <div style="display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 0.84rem;">
            <span style="color: var(--text-muted);"><i class="fas fa-clock"></i> Ish vaqti:</span>
            <strong style="color: var(--primary);">08:00 – ertasi 08:00</strong>
          </div>
          <div style="display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 0.84rem;">
            <span style="color: var(--text-muted);"><i class="fas fa-syringe"></i> Hamkor Hamshira:</span>
            <strong style="color: #34d399;">${shift.nurse_name}</strong>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 0.84rem;">
            <span style="color: var(--text-muted);"><i class="fas fa-user-md"></i> Tungi Shifokor:</span>
            <strong style="color: #c084fc;">${shift.doctor_name}</strong>
          </div>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 14px; font-size: 0.82rem;">
          <span style="color: #fbbf24; font-weight: 700;"><i class="fas fa-coins"></i> 300 000 so'm</span>
          <button type="button" class="btn-duty-action btn-duty-swap" style="padding: 4px 10px; font-size: 0.74rem;" onclick="openSwapForShift('${shift.date}')">
            <i class="fas fa-exchange-alt"></i> Smenani Almashtirish
          </button>
        </div>
      `;

      container.appendChild(card);
    });
  }

  // -------------------------------------------------------------------------
  // 8. MODAL 1: DAY DETAILS MODAL
  // -------------------------------------------------------------------------
  function openDayModal(shift) {
    const modal = document.getElementById('day-modal');
    if (!modal) return;

    document.getElementById('modal-day-title').textContent = `${shift.date} (${shift.weekday}) — 24/7 Navbatchilik`;
    document.getElementById('modal-sanitar-name').textContent = shift.sanitar_primary || '—';
    document.getElementById('modal-sanitar-2').textContent = shift.sanitar_secondary || 'Muxayyo Karabaeva (Zaxira)';
    document.getElementById('modal-nurse-name').textContent = shift.nurse_name || '—';
    document.getElementById('modal-doc-name').textContent = shift.doctor_name || '—';

    modal.classList.add('active');
  }

  function closeDayModal() {
    const modal = document.getElementById('day-modal');
    if (modal) modal.classList.remove('active');
  }

  // -------------------------------------------------------------------------
  // 9. MODAL 2: SHIFT SWAP ENGINE
  // -------------------------------------------------------------------------
  function openSwapModal() {
    const modal = document.getElementById('swap-modal');
    if (!modal) return;

    populateSwapDropdowns();
    modal.classList.add('active');
  }

  function openSwapForShift(dateStr) {
    openSwapModal();
    const dateSelect = document.getElementById('swap-from-date');
    if (dateSelect) dateSelect.value = dateStr;
  }

  function closeSwapModal() {
    const modal = document.getElementById('swap-modal');
    if (modal) modal.classList.remove('active');
  }

  function populateSwapDropdowns() {
    const shifts = ensureMonthShifts(State.currentYear, State.currentMonth);
    const fromSelect = document.getElementById('swap-from-date');
    const toSelect = document.getElementById('swap-to-date');
    const staffSelect = document.getElementById('swap-target-staff');

    if (fromSelect) {
      fromSelect.innerHTML = shifts.map(s => `
        <option value="${s.date}">${s.date} (${s.weekday.slice(0, 4)}) — ${s.sanitar_primary.split(' ')[0]}</option>
      `).join('');
    }

    if (toSelect) {
      toSelect.innerHTML = shifts.map(s => `
        <option value="${s.date}">${s.date} (${s.weekday.slice(0, 4)}) — ${s.sanitar_primary.split(' ')[0]}</option>
      `).join('');
      if (shifts.length > 5) toSelect.selectedIndex = 5;
    }

    if (staffSelect) {
      staffSelect.innerHTML = SANITARKAS.map(s => `
        <option value="${s.full_name}">${s.name} (${s.full_name})</option>
      `).join('');
    }
  }

  async function executeShiftSwap() {
    const fromDate = document.getElementById('swap-from-date').value;
    const toDate = document.getElementById('swap-to-date').value;
    const targetStaff = document.getElementById('swap-target-staff').value;

    if (!fromDate || !toDate) {
      alert("Ikkala sanani ham tanlang");
      return;
    }

    if (fromDate === toDate) {
      alert("Bir xil sanani tanlab bo'lmaydi");
      return;
    }

    // Perform swap in local State.rawShifts
    const s1 = State.rawShifts.find(s => s.date === fromDate);
    const s2 = State.rawShifts.find(s => s.date === toDate);

    if (s1 && s2) {
      const tempSan = s1.sanitar_primary;
      s1.sanitar_primary = s2.sanitar_primary;
      s2.sanitar_primary = tempSan;
    } else {
      // Re-generate and assign
      const monthShifts = ensureMonthShifts(State.currentYear, State.currentMonth);
      const sh1 = monthShifts.find(s => s.date === fromDate);
      const sh2 = monthShifts.find(s => s.date === toDate);
      if (sh1 && sh2) {
        const temp = sh1.sanitar_primary;
        sh1.sanitar_primary = sh2.sanitar_primary;
        sh2.sanitar_primary = temp;
      }
      State.rawShifts = monthShifts;
    }

    // Persist to server via POST /api/duty-schedule
    try {
      await fetch('/api/duty-schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          updated_at: new Date().toISOString(),
          hospital: "Fayz Medical House",
          operating_mode: "24/7 Statsionar & Poliklinika",
          sanitarkas: SANITARKAS,
          shifts: State.rawShifts
        })
      });
    } catch (e) {
      console.warn("Server update failed, saved locally:", e);
    }

    closeSwapModal();
    renderCurrentView();
    renderPersonalDashboard();

    if (window.FMH_Toast) {
      window.FMH_Toast(`✅ Smena muvaffaqiyatli almashtirildi! (${fromDate} ⇄ ${toDate})`, "success");
    } else {
      alert("Smena muvaffaqiyatli almashtirildi!");
    }
  }

  // -------------------------------------------------------------------------
  // 10. ACTION BUTTONS: TELEGRAM & PRINT
  // -------------------------------------------------------------------------
  function copyTelegramRoster() {
    const shifts = ensureMonthShifts(State.currentYear, State.currentMonth);
    let msg = `🏥 *FAYZ MEDICAL HOUSE — 24/7 NAVBATCHILIK JADVALI*\n`;
    msg += `📅 Oy: *${UZ_MONTHS[State.currentMonth - 1]} ${State.currentYear}*\n`;
    msg += `⏱ Smena: 24 soat (08:00 – ertasi 08:00)\n`;
    msg += `------------------------------------\n\n`;

    const filtered = State.selectedSanitar === 'all'
      ? shifts.slice(0, 15)
      : shifts.filter(s => (s.sanitar_primary === State.selectedSanitar || s.sanitar_secondary === State.selectedSanitar));

    filtered.forEach(s => {
      msg += `📌 *${s.date}* (${s.weekday.slice(0, 4)}):\n`;
      msg += `   🧹 Sanitarka: ${s.sanitar_primary}\n`;
      msg += `   💉 Hamshira: ${s.nurse_name}\n`;
      msg += `   🩺 Shifokor: ${s.doctor_name}\n\n`;
    });

    msg += `\n📞 Aloqa: +998 71 209-99-10\n📍 Yunusobod, Nurmakon ko'chasi 2A`;

    navigator.clipboard.writeText(msg).then(() => {
      if (window.FMH_Toast) {
        window.FMH_Toast("✅ Telegram uchun navbatchilik jadvali nusxalandi!", "success");
      } else {
        alert("Telegram uchun navbatchilik jadvali nusxalandi!");
      }
    }).catch(() => {
      alert("Nusxalab bo'lmadi. Brauzer ruxsatini tekshiring.");
    });
  }

  // -------------------------------------------------------------------------
  // OFFICIAL A4 CLINICAL PRINT GENERATOR (100% SINGLE PAGE PERFECTION)
  // -------------------------------------------------------------------------
  function updatePrintSheet() {
    const sheet = document.getElementById('official-duty-print-sheet');
    if (!sheet) return;

    const shifts = ensureMonthShifts(State.currentYear, State.currentMonth);
    const monthName = UZ_MONTHS[State.currentMonth - 1];
    const year = State.currentYear;
    const now = new Date();
    const todayStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;

    // Helper for short person names to fit tight columns gracefully
    function shortName(fullName) {
      if (!fullName) return "—";
      const parts = fullName.trim().split(' ');
      if (parts.length >= 2) {
        return `${parts[0]} ${parts[1][0]}.`;
      }
      return parts[0];
    }

    // Common Header HTML
    const clinicHeaderHTML = `
      <div class="print-header-grid">
        <div class="print-brand-left">
          <div class="print-crest-box">
            <i class="fas fa-hospital-alt"></i>
          </div>
          <div>
            <div class="print-brand-title">FAYZ MEDICAL HOUSE</div>
            <div class="print-brand-sub">Toshkent sh., Yunusobod tumani, Nurmakon ko'chasi 2A | Tel: +998 71 209-99-10</div>
          </div>
        </div>
        <div class="print-stamp-box">
          <div><strong>«TASDIQLAYMAN»</strong></div>
          <div>Bosh shifokor: _______________</div>
          <div style="font-size: 6.5pt; color: #64748b; margin-top: 1px;">M.O'. / Imzo: «___» __________ ${year}-y.</div>
        </div>
      </div>
    `;

    // Case 1: Specific Sanitarka Selected -> Personal Duty Sheet & Official Compensation Certificate
    if (State.selectedSanitar !== 'all') {
      const myShifts = shifts.filter(s => (s.sanitar_primary === State.selectedSanitar || s.sanitar_secondary === State.selectedSanitar));
      const totalCount = myShifts.length;
      const totalHours = totalCount * 24;
      const totalSum = totalCount * State.dutyTariffs.sanitar;

      let rowsHTML = '';
      if (myShifts.length === 0) {
        rowsHTML = `<tr><td colspan="6" style="text-align: center; padding: 12px; color: #64748b;">Ushbu oy uchun navbatchilik biriktirilmagan</td></tr>`;
      } else {
        myShifts.forEach((s, idx) => {
          const isToday = (s.date === todayStr);
          const isPrimary = (s.sanitar_primary === State.selectedSanitar);
          const roleLabel = isPrimary ? "1-Post (Bosh sanitarka)" : "2-Post (Zaxira sanitarka)";
          const partner = isPrimary ? shortName(s.sanitar_secondary) : shortName(s.sanitar_primary);

          rowsHTML += `
            <tr class="${isToday ? 'today-print-row' : ''}">
              <td style="text-align: center; font-weight: 700;">${idx + 1}</td>
              <td style="font-weight: 700; white-space: nowrap;">${s.date} (${s.weekday.slice(0, 4)})</td>
              <td>08:00 – ertasi 08:00 (24 soat)</td>
              <td>${roleLabel}</td>
              <td>${partner}</td>
              <td style="text-align: right; font-weight: 700;">300 000 so'm</td>
            </tr>
          `;
        });
      }

      sheet.innerHTML = `
        ${clinicHeaderHTML}
        
        <div class="print-doc-title-block">
          <h2>XODIMNING SHAXSIY NAVBATCHILIK GRAFIKI VA ISH HAQI TABELI</h2>
          <div class="print-doc-meta">
            <strong>Xodim:</strong> ${State.selectedSanitar} &nbsp;|&nbsp; 
            <strong>Lavozim:</strong> Sanitarka (Kichik tibbiyot xodimi) &nbsp;|&nbsp; 
            <strong>Davr:</strong> ${monthName} ${year}-yil
          </div>
        </div>

        <table class="print-single-table">
          <thead>
            <tr>
              <th style="width: 30px; text-align: center;">№</th>
              <th style="width: 130px;">Sana / Hafta kuni</th>
              <th style="width: 140px;">Smena vaqti</th>
              <th>Vazifasi</th>
              <th>Sherik sanitarka</th>
              <th style="width: 100px; text-align: right;">Tarif (so'm)</th>
            </tr>
          </thead>
          <tbody>
            ${rowsHTML}
          </tbody>
        </table>

        <div class="print-total-summary-box">
          <div>Jami biriktirilgan smenalar: <strong>${totalCount} ta smena (${totalHours} ish soati)</strong></div>
          <div>Hisoblangan jami to'lov: <strong style="font-size: 8.8pt; color: #0f766e;">${formatUZS(totalSum)}</strong></div>
        </div>

        <div class="print-signatures-grid">
          <div class="print-sig-col">
            <div>Bosh hamshira:</div>
            <div class="print-sig-line"></div>
            <div style="font-size: 6.8pt; color: #64748b; margin-top: 2px;">(F.I.SH va imzo)</div>
          </div>
          <div class="print-sig-col center">
            <div>Hisobchi:</div>
            <div class="print-sig-line"></div>
            <div style="font-size: 6.8pt; color: #64748b; margin-top: 2px;">(F.I.SH va imzo)</div>
          </div>
          <div class="print-sig-col right">
            <div>Xodim tanishdim:</div>
            <div class="print-sig-line"></div>
            <div style="font-size: 6.8pt; color: #64748b; margin-top: 2px;">${shortName(State.selectedSanitar)} (Imzo)</div>
          </div>
        </div>
      `;
    } 
    // Case 2: Full Month Team Roster -> Dual Side-by-Side Tables (Days 1-16 & 17-31)
    else {
      const col1Shifts = shifts.slice(0, 16);
      const col2Shifts = shifts.slice(16);

      function renderSubTableRows(shiftSubset) {
        return shiftSubset.map(s => {
          const isWeekend = s.is_weekend;
          const isToday = (s.date === todayStr);
          const dayNum = s.day;
          const wkd = s.weekday.slice(0, 4);

          return `
            <tr class="${isWeekend ? 'weekend-row' : ''} ${isToday ? 'today-print-row' : ''}">
              <td style="text-align: center; font-weight: 800; white-space: nowrap;">${dayNum}-${monthName.slice(0, 3)}</td>
              <td style="color: #475569; font-size: 6.8pt; text-align: center;">${wkd}</td>
              <td style="font-weight: 700; color: #0f172a;">${shortName(s.sanitar_primary)}</td>
              <td style="color: #334155;">${shortName(s.nurse_name)}</td>
              <td style="color: #1e293b;">${shortName(s.doctor_name)}</td>
            </tr>
          `;
        }).join('');
      }

      sheet.innerHTML = `
        ${clinicHeaderHTML}
        
        <div class="print-doc-title-block">
          <h2>KLINIKANING 24/7 TUN-U KUN NAVBATCHILIK JADVALI</h2>
          <div class="print-doc-meta">
            <strong>Oy:</strong> ${monthName} ${year}-yil &nbsp;|&nbsp; 
            <strong>Sutkalik smena:</strong> 08:00 – ertasi 08:00 (24 soat) &nbsp;|&nbsp; 
            <strong>Tungi shifokor:</strong> 20:00 – 08:00
          </div>
        </div>

        <div class="print-dual-table-wrap">
          <!-- Left Column: Days 1 to 16 -->
          <table class="print-sub-table">
            <thead>
              <tr>
                <th style="width: 44px; text-align: center;">Sana</th>
                <th style="width: 28px; text-align: center;">Kun</th>
                <th>Sanitarka (1-Post)</th>
                <th>Hamshira</th>
                <th>Shifokor</th>
              </tr>
            </thead>
            <tbody>
              ${renderSubTableRows(col1Shifts)}
            </tbody>
          </table>

          <!-- Right Column: Days 17 to 31 -->
          <table class="print-sub-table">
            <thead>
              <tr>
                <th style="width: 44px; text-align: center;">Sana</th>
                <th style="width: 28px; text-align: center;">Kun</th>
                <th>Sanitarka (1-Post)</th>
                <th>Hamshira</th>
                <th>Shifokor</th>
              </tr>
            </thead>
            <tbody>
              ${renderSubTableRows(col2Shifts)}
            </tbody>
          </table>
        </div>

        <div class="print-signatures-grid">
          <div class="print-sig-col">
            <div>Bosh hamshira:</div>
            <div class="print-sig-line"></div>
            <div style="font-size: 6.8pt; color: #64748b; margin-top: 2px;">(F.I.SH va imzo)</div>
          </div>
          <div class="print-sig-col center">
            <div>Xodimlar bo'limi (HR):</div>
            <div class="print-sig-line"></div>
            <div style="font-size: 6.8pt; color: #64748b; margin-top: 2px;">(F.I.SH va imzo)</div>
          </div>
          <div class="print-sig-col right">
            <div>Tibbiyot bo'limi mudiri:</div>
            <div class="print-sig-line"></div>
            <div style="font-size: 6.8pt; color: #64748b; margin-top: 2px;">(F.I.SH va imzo)</div>
          </div>
        </div>
      `;
    }
  }

  function printDutySchedule() {
    updatePrintSheet();
    window.print();
  }

  // -------------------------------------------------------------------------
  // 11. EVENT LISTENERS
  // -------------------------------------------------------------------------
  function setupEventListeners() {
    // Stepper buttons
    const btnPrev = document.getElementById('btn-prev-month');
    const btnNext = document.getElementById('btn-next-month');
    const btnToday = document.getElementById('btn-today-step');

    if (btnPrev) btnPrev.onclick = prevMonth;
    if (btnNext) btnNext.onclick = nextMonth;
    if (btnToday) btnToday.onclick = goToToday;

    // View Pills
    document.querySelectorAll('.duty-view-pill-btn').forEach(btn => {
      btn.onclick = () => switchView(btn.getAttribute('data-view'));
    });

    // Search input
    const searchInp = document.getElementById('duty-search-input');
    if (searchInp) {
      searchInp.oninput = (e) => {
        State.searchQuery = e.target.value;
        renderTable();
      };
    }

    // Modal background click
    document.querySelectorAll('.duty-modal-backdrop').forEach(bd => {
      bd.onclick = (e) => {
        if (e.target === bd) {
          bd.classList.remove('active');
        }
      };
    });

    // Swap execute
    const btnSaveSwap = document.getElementById('btn-confirm-swap');
    if (btnSaveSwap) btnSaveSwap.onclick = executeShiftSwap;
  }

  // Expose to window for inline onclick handlers
  window.FMH_DutySchedule = {
    prevMonth,
    nextMonth,
    goToToday,
    switchView,
    selectSanitar,
    openDayModal,
    closeDayModal,
    openSwapModal,
    openSwapForShift,
    closeSwapModal,
    executeShiftSwap,
    copyTelegramRoster,
    updatePrintSheet,
    printDutySchedule
  };

  // Run on DOM ready
  document.addEventListener('DOMContentLoaded', init);

})();
