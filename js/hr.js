/**
 * Fayz Medical House — HR & Inson Resurslari Boshqaruvi Moduli (HR Management JS)
 * Version: 2.3.0 (Single Whole-Building 24h Nurse & Next-Gen Scheduling Engine)
 * Features:
 * 1. Specific Official Tariffs:
 *    - Hamshira (Butun bino, 1-va 2-qavat) 24h = 400,000 so'm
 *    - Sanitarka 24h = 300,000 so'm
 *    - Shifokor 1 Tun = 350,000 so'm
 *    - Kunlik umumiy navbatchilik xarajati: 1 050 000 so'm / kun
 * 2. 1-Click Brigade Team Builder (1/3 Rejimi - 1 sutka ish, 3 sutka dam; 1/2 Rejimi)
 * 3. Rapid Stamp & Paint Mode (Tezkor Bo'yash Rejimi)
 * 4. 3-in-1 View Switcher: 7-Day Monthly Calendar Grid, Staff Gantt Matrix Timeline, Detailed Table
 * 5. 1-Click Shift Swapper & Telegram/WhatsApp Duty Roster Generator
 * 6. Live Payroll Engine & Official Printable Pay Slips
 */



(function () {
  'use strict';

  const STORAGE_KEY = 'FMH_HR_DATABASE_V4';

  // Specific Official Navbatchilik Tariffs
  const DUTY_TARIFFS = {
    doctor_night: 350000,    // 350,000 so'm per doctor night shift (20:00 - 08:00)
    nurse_24h: 400000,       // 400,000 so'm per nurse 24-hour shift (Entire building: 1st & 2nd floors)
    sanitar_24h: 300000      // 300,000 so'm per sanitar 24-hour shift (1 sutka)
  };

  const DEFAULT_BRIGADES = [];

  // Formatters
  const formatUZS = (val) => {
    if (val === null || val === undefined || isNaN(val)) return '0 so\'m';
    return Math.round(val).toLocaleString('uz-UZ') + ' so\'m';
  };

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

  // Main HR State
  const State = {
    facility: {},
    staff: [],
    dutyTariffs: DUTY_TARIFFS,
    brigades: DEFAULT_BRIGADES,
    monthlySchedule: [],
    attendance: [],
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

    try {
      let res = await fetch('/api/hr/data').catch(() => null);
      if (!res || !res.ok) {
        res = await fetch('data/hr_db.json').catch(() => null);
      }
      if (res && res.ok) {
        const data = await res.json();
        populateState(data);
        ensureMonthlySchedule();
        saveToLocalStorage();
        renderAll();
        return;
      }
    } catch (e) {
      console.warn('API and static fetch failed, checking local storage...', e);
    }

    const localData = localStorage.getItem(STORAGE_KEY);
    if (localData) {
      try {
        const parsed = JSON.parse(localData);
        populateState(parsed);
        ensureMonthlySchedule();
        renderAll();
        return;
      } catch (e) {
        console.warn('Failed to parse local HR DB:', e);
      }
    }

    ensureMonthlySchedule();
    renderAll();

    // Auto-refresh every 5s
    setInterval(async () => {
      try {
        const sRes = await fetch('/api/staff');
        if (sRes.ok) renderAll();
      } catch (err) {}
    }, 5000);
  }

  function populateState(data) {
    State.facility = data.facility_info || {};
    State.staff = data.staff || [];
    State.dutyTariffs = data.duty_tariffs || DUTY_TARIFFS;
    State.brigades = (data.brigades && data.brigades[0].nurse_id) ? data.brigades : DEFAULT_BRIGADES;
    State.monthlySchedule = data.monthly_duty_schedule || [];
    State.attendance = data.attendance_records || [];
  }

  function saveToLocalStorage() {
    const payload = {
      facility_info: State.facility,
      duty_tariffs: State.dutyTariffs,
      brigades: State.brigades,
      staff: State.staff,
      monthly_duty_schedule: State.monthlySchedule,
      attendance_records: State.attendance
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  }

  // ==========================================================================
  // BRIGADE & SCHEDULING ENGINES (SINGLE WHOLE-BUILDING NURSE)
  // ==========================================================================

  function ensureMonthlySchedule() {
    const now = new Date();
    const curDays = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
    if (!State.monthlySchedule || State.monthlySchedule.length < curDays || State.monthlySchedule[0].nurse_f1_id !== undefined) {
      generateMonthlySchedule(State.activeAlgorithm);
    } else {
      recalculateStaffDutyCounts();
    }
  }

  /**
   * Generates dynamic monthly schedule based on current real-time month & year.
   */
  function generateMonthlySchedule(algoType = 'brigade_1_3') {
    const now = new Date();
    const curYear = now.getFullYear();
    const curMonth = now.getMonth();
    const daysInMonth = new Date(curYear, curMonth + 1, 0).getDate();
    const schedule = [];
    const daysOfWeekUz = ['Yak', 'Dush', 'Sesh', 'Chor', 'Pay', 'Jum', 'Shan'];
    const pad = n => String(n).padStart(2, '0');

    const doctors = (State.staff || []).filter(s => s.role === 'doctor' || s.role === 'chief_doctor');
    const nurses = (State.staff || []).filter(s => s.role === 'nurse');
    const sanitars = (State.staff || []).filter(s => s.role === 'support');

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
        doc = (State.staff || []).find(s => s.id === currentBrigade.doctor_id) || doctors[0] || null;
        nurseF1 = (State.staff || []).find(s => s.id === (currentBrigade.nurse_f1_id || currentBrigade.nurse_id)) || nurses[0] || null;
        nurseF2 = (State.staff || []).find(s => s.id === currentBrigade.nurse_f2_id) || (nurses.length > 1 ? nurses[1] : null);
        san = (State.staff || []).find(s => s.id === currentBrigade.sanitar_id) || sanitars[0] || null;
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

      const dailyDutyCost = (doc ? DUTY_TARIFFS.doctor_night : 0) +
                            (nurseF1 ? DUTY_TARIFFS.nurse_24h : 0) +
                            (nurseF2 ? DUTY_TARIFFS.nurse_24h : 0) +
                            (san ? DUTY_TARIFFS.sanitar_24h : 0);

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
        daily_duty_cost: dailyDutyCost
      });
    }

    State.monthlySchedule = schedule;
    recalculateStaffDutyCounts();
    saveToLocalStorage();
  }

  function recalculateStaffDutyCounts() {
    State.staff.forEach(s => {
      s.monthly_duty_count = 0;
      s.monthly_duty_earnings = 0;
    });

    State.monthlySchedule.forEach(sch => {
      if (sch.doctor_night_id) {
        const doc = State.staff.find(s => s.id === sch.doctor_night_id);
        if (doc) {
          doc.monthly_duty_count = (doc.monthly_duty_count || 0) + 1;
          doc.monthly_duty_earnings = (doc.monthly_duty_earnings || 0) + DUTY_TARIFFS.doctor_night;
        }
      }
      if (sch.nurse_f1_id || sch.nurse_id) {
        const nId = sch.nurse_f1_id || sch.nurse_id;
        const n = State.staff.find(s => s.id === nId);
        if (n) {
          n.monthly_duty_count = (n.monthly_duty_count || 0) + 1;
          n.monthly_duty_earnings = (n.monthly_duty_earnings || 0) + DUTY_TARIFFS.nurse_24h;
        }
      }
      if (sch.nurse_f2_id) {
        const n2 = State.staff.find(s => s.id === sch.nurse_f2_id);
        if (n2) {
          n2.monthly_duty_count = (n2.monthly_duty_count || 0) + 1;
          n2.monthly_duty_earnings = (n2.monthly_duty_earnings || 0) + DUTY_TARIFFS.nurse_24h;
        }
      }
      if (sch.sanitar_id) {
        const san = State.staff.find(s => s.id === sch.sanitar_id);
        if (san) {
          san.monthly_duty_count = (san.monthly_duty_count || 0) + 1;
          san.monthly_duty_earnings = (san.monthly_duty_earnings || 0) + DUTY_TARIFFS.sanitar_24h;
        }
      }
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
      const staff = State.staff.find(s => s.id === staffId);
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

      if (State.activePaintStamp.staffId === 'eraser') {
        if (slotType === 'doctor_night') { targetDay.doctor_night_id = ''; targetDay.doctor_night_name = '—'; }
        else if (slotType === 'nurse_f1') { targetDay.nurse_f1_id = ''; targetDay.nurse_f1_name = '—'; targetDay.nurse_id = ''; targetDay.nurse_name = '—'; }
        else if (slotType === 'nurse_f2') { targetDay.nurse_f2_id = ''; targetDay.nurse_f2_name = '—'; }
        else if (slotType === 'nurse_24h' || slotType === 'nurse') { targetDay.nurse_f1_id = ''; targetDay.nurse_f1_name = '—'; targetDay.nurse_id = ''; targetDay.nurse_name = '—'; }
        else if (slotType === 'sanitar_24h') { targetDay.sanitar_id = ''; targetDay.sanitar_name = '—'; }
      } else {
        const staffId = State.activePaintStamp.staffId;
        const staffName = State.activePaintStamp.name;

        if (slotType === 'doctor_night') {
          targetDay.doctor_night_id = staffId;
          targetDay.doctor_night_name = staffName;
        } else if (slotType === 'nurse_f1') {
          targetDay.nurse_f1_id = staffId;
          targetDay.nurse_f1_name = staffName;
          targetDay.nurse_id = staffId;
          targetDay.nurse_name = staffName;
        } else if (slotType === 'nurse_f2') {
          targetDay.nurse_f2_id = staffId;
          targetDay.nurse_f2_name = staffName;
        } else if (slotType === 'nurse_24h' || slotType === 'nurse') {
          targetDay.nurse_f1_id = staffId;
          targetDay.nurse_f1_name = staffName;
          targetDay.nurse_id = staffId;
          targetDay.nurse_name = staffName;
        } else if (slotType === 'sanitar_24h') {
          targetDay.sanitar_id = staffId;
          targetDay.sanitar_name = staffName;
        }
      }

      recalculateStaffDutyCounts();
      saveToLocalStorage();
      renderShiftRoster();
      renderPayrollTable();
      updateKPIs();
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
      <!-- Official Navbatchilik Tariffs Banner -->
      <div class="duty-tariff-grid">
        <div class="tariff-card tariff-doctor">
          <div>
            <div class="tariff-role"><i class="fas fa-user-md"></i> Shifokorlar (Doctors)</div>
            <div class="tariff-name">1 Tungi Navbatchilik (20:00 - 08:00)</div>
          </div>
          <div class="tariff-price">350 000 so'm</div>
        </div>

        <div class="tariff-card tariff-nurse">
          <div>
            <div class="tariff-role"><i class="fas fa-syringe"></i> Hamshira (Butun Bino — 1 & 2 Qavat)</div>
            <div class="tariff-name">24-Soatlik Navbatchilik (1 Sutka)</div>
          </div>
          <div class="tariff-price">400 000 so'm</div>
        </div>

        <div class="tariff-card tariff-sanitar">
          <div>
            <div class="tariff-role"><i class="fas fa-broom"></i> Sanitarkalar (Sanitars)</div>
            <div class="tariff-name">24-Soatlik Navbatchilik (1 Sutka)</div>
          </div>
          <div class="tariff-price">300 000 so'm</div>
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

  function renderStampModeBanner() {
    const activeStaffId = State.activePaintStamp ? State.activePaintStamp.staffId : '';

    return `
      <div class="stamp-mode-banner">
        <div style="display: flex; align-items: center; gap: 8px;">
          <div style="font-weight: 800; color: #ffffff; font-size: 0.88rem;">
            <i class="fas fa-magic" style="color: #38bdf8;"></i> Faol Shtamp:
          </div>
          <div style="font-size: 0.8rem; color: #38bdf8; font-weight: 700;">
            ${State.activePaintStamp ? State.activePaintStamp.name : 'Xodim tanlang'}
          </div>
        </div>

        <div class="stamp-selector-list">
          ${State.staff.filter(s => s.role === 'doctor' || s.role === 'chief_doctor' || s.role === 'nurse' || s.id.startsWith('STF-SAN')).map(s => {
            const isActive = activeStaffId === s.id;
            const roleType = s.role === 'doctor' || s.role === 'chief_doctor' ? 'doctor_night' : s.role === 'nurse' ? 'nurse' : 'sanitar';
            return `
              <div class="stamp-chip ${isActive ? 'active' : ''}" onclick="window.FMH_HR.setPaintStamp('${s.id}', '${roleType}')">
                <i class="${s.role === 'doctor' || s.role === 'chief_doctor' ? 'fas fa-user-md' : s.role === 'nurse' ? 'fas fa-syringe' : 'fas fa-broom'}"></i>
                ${s.full_name.split(' ')[1] || s.full_name}
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
                  <span class="cal-day-badge">${sch.brigade_name ? sch.brigade_name.split(' ')[0] : 'Smena'}</span>
                </div>

                <div class="cal-slot-list">
                  <div class="cal-slot-item slot-doc" onclick="window.FMH_HR.handleSlotClick(${sch.day}, 'doctor_night')" title="Shifokor Tungi (350k) - Tanlash uchun bosing">
                    <span style="overflow:hidden; text-overflow:ellipsis;"><i class="fas fa-user-md"></i> ${(sch.doctor_night_name || '—').split(' ')[1] || sch.doctor_night_name || '—'}</span>
                    <span style="font-size:0.65rem; opacity:0.8;">350k</span>
                  </div>

                  <div class="cal-slot-item slot-nurse" onclick="window.FMH_HR.handleSlotClick(${sch.day}, 'nurse_f1')" title="1-Qavat 24h Hamshira (400k)">
                    <span style="overflow:hidden; text-overflow:ellipsis;"><i class="fas fa-syringe"></i> ${(sch.nurse_f1_name || sch.nurse_name || '—').split(' ')[0]} (1-Q)</span>
                    <span style="font-size:0.65rem; opacity:0.8;">400k</span>
                  </div>

                  <div class="cal-slot-item slot-nurse" onclick="window.FMH_HR.handleSlotClick(${sch.day}, 'nurse_f2')" title="2-Qavat 24h Hamshira (400k)">
                    <span style="overflow:hidden; text-overflow:ellipsis;"><i class="fas fa-syringe"></i> ${(sch.nurse_f2_name || '—').split(' ')[0]} (2-Q)</span>
                    <span style="font-size:0.65rem; opacity:0.8;">400k</span>
                  </div>

                  <div class="cal-slot-item slot-sanitar" onclick="window.FMH_HR.handleSlotClick(${sch.day}, 'sanitar_24h')" title="24h Sanitarka (300k)">
                    <span style="overflow:hidden; text-overflow:ellipsis;"><i class="fas fa-broom"></i> ${(sch.sanitar_name || '—').split(' ')[0]}</span>
                    <span style="font-size:0.65rem; opacity:0.8;">300k</span>
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
    const shiftStaffList = State.staff.filter(s => s.role === 'doctor' || s.role === 'chief_doctor' || s.role === 'nurse' || s.id.startsWith('STF-SAN'));

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
                    <div style="font-weight: 700; color: #ffffff;">${staff.full_name}</div>
                    <div style="font-size: 0.7rem; color: var(--indigo-light);">${staff.role_title_uz || staff.role}</div>
                  </td>
                  <td style="font-family: var(--font-mono); font-weight: 700; color: #34d399; font-size: 0.75rem;">
                    ${staff.monthly_duty_count || 0} smena<br>
                    <span style="color: var(--text-muted); font-size: 0.7rem;">${formatUZS(staff.monthly_duty_earnings)}</span>
                  </td>

                  ${days.map(d => {
                    const sch = State.monthlySchedule.find(s => s.day === d);
                    let chip = '<span class="gantt-chip-rest">•</span>';

                    if (sch) {
                      if (sch.doctor_night_id === staff.id) {
                        chip = `<span class="gantt-chip-duty gantt-chip-doc" onclick="window.FMH_HR.handleSlotClick(${d}, 'doctor_night')" title="${d}-kun: Tungi Shifokor (350k)">D</span>`;
                      } else if (sch.nurse_id === staff.id) {
                        chip = `<span class="gantt-chip-duty gantt-chip-nurse" onclick="window.FMH_HR.handleSlotClick(${d}, 'nurse_24h')" title="${d}-kun: Butun Bino 24h Hamshira (400k)">H</span>`;
                      } else if (sch.sanitar_id === staff.id) {
                        chip = `<span class="gantt-chip-duty gantt-chip-san" onclick="window.FMH_HR.handleSlotClick(${d}, 'sanitar_24h')" title="${d}-kun: 24h Sanitarka (300k)">S</span>`;
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
    const curMonthName = new Date().toLocaleDateString('uz-UZ', { month: 'long' });

    return `
      <div class="table-responsive-wrapper">
        <table class="hr-table">
          <thead>
            <tr>
              <th style="width: 100px;">Sana & Kun</th>
              <th>🩺 Tungi Shifokor (350k)</th>
              <th>💉 24h Hamshira (Butun Bino — 400k)</th>
              <th>🧹 24h Sanitarka (300k)</th>
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
                    <div style="font-size: 0.72rem; color: var(--text-muted);">${sch.day_name}</div>
                  </td>
                  <td>
                    <div class="duty-slot-badge duty-slot-doc" onclick="window.FMH_HR.handleSlotClick(${sch.day}, 'doctor_night')">
                      <span><i class="fas fa-user-md"></i> ${sch.doctor_night_name}</span>
                    </div>
                  </td>
                  <td>
                    <div class="duty-slot-badge duty-slot-nurse" onclick="window.FMH_HR.handleSlotClick(${sch.day}, 'nurse_24h')">
                      <span><i class="fas fa-syringe"></i> ${sch.nurse_name} (1-2 Qavat)</span>
                    </div>
                  </td>
                  <td>
                    <div class="duty-slot-badge duty-slot-sanitar" onclick="window.FMH_HR.handleSlotClick(${sch.day}, 'sanitar_24h')">
                      <span><i class="fas fa-broom"></i> ${sch.sanitar_name}</span>
                    </div>
                  </td>
                  <td><span style="font-size: 0.8rem; color: #fbbf24;"><i class="fas fa-phone-alt"></i> ${sch.oncall_doc_name}</span></td>
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

    const doctors = State.staff.filter(s => s.role === 'doctor' || s.role === 'chief_doctor');
    const nurses = State.staff.filter(s => s.role === 'nurse');
    const sanitars = State.staff.filter(s => s.role === 'support' && s.id.startsWith('STF-SAN'));

    container.innerHTML = State.brigades.map((brg, bIdx) => {
      return `
        <div class="brigade-card brigade-${brg.id.split('-')[1].toLowerCase()}">
          <div class="brigade-title">
            <span><i class="fas fa-users-medical"></i> ${brg.name}</span>
            <span class="status-badge badge-active">Faol</span>
          </div>

          <div class="form-group">
            <label class="form-label" style="font-size: 0.72rem;">🩺 Tungi Shifokor (350k):</label>
            <select class="brigade-member-select" id="brg-${bIdx}-doc">
              ${doctors.map(d => `<option value="${d.id}" ${d.id === brg.doctor_id ? 'selected' : ''}>${d.full_name}</option>`).join('')}
            </select>
          </div>

          <div class="form-group">
            <label class="form-label" style="font-size: 0.72rem;">💉 1-Qavat 24h Hamshirasi (400k):</label>
            <select class="brigade-member-select" id="brg-${bIdx}-nurse-f1">
              ${nurses.map(n => `<option value="${n.id}" ${n.id === (brg.nurse_f1_id || brg.nurse_id) ? 'selected' : ''}>${n.full_name}</option>`).join('')}
            </select>
          </div>

          <div class="form-group">
            <label class="form-label" style="font-size: 0.72rem;">💉 2-Qavat 24h Hamshirasi (400k):</label>
            <select class="brigade-member-select" id="brg-${bIdx}-nurse-f2">
              <option value="">— Biriktirilmasin —</option>
              ${nurses.map(n => `<option value="${n.id}" ${n.id === brg.nurse_f2_id ? 'selected' : ''}>${n.full_name}</option>`).join('')}
            </select>
          </div>

          <div class="form-group">
            <label class="form-label" style="font-size: 0.72rem;">🧹 24h Sanitarka (300k):</label>
            <select class="brigade-member-select" id="brg-${bIdx}-san">
              ${sanitars.map(s => `<option value="${s.id}" ${s.id === brg.sanitar_id ? 'selected' : ''}>${s.full_name}</option>`).join('')}
            </select>
          </div>
        </div>
      `;
    }).join('');

    modal.classList.add('active');
  }

  function applyBrigadesToMonth(presetType = 'brigade_1_3') {
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
    generateMonthlySchedule(presetType);
    renderShiftRoster();
    renderPayrollTable();
    updateKPIs();
    closeAllModals();
    showToast('4 ta Brigada (Shifokor, 1-va 2-qavat hamshiralari, sanitarka) butun oyga tatbiq etildi!', 'success');
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
      const days = Array.from({length: 31}, (_, i) => `<option value="${i+1}">${i+1}-Avgust 2026</option>`).join('');
      selA.innerHTML = days;
      selB.innerHTML = days;
      selA.value = "1";
      selB.value = "4";
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

    if (roleType === 'all' || roleType === 'doctor') {
      const tempId = targetA.doctor_night_id;
      const tempName = targetA.doctor_night_name;
      targetA.doctor_night_id = targetB.doctor_night_id;
      targetA.doctor_night_name = targetB.doctor_night_name;
      targetB.doctor_night_id = tempId;
      targetB.doctor_night_name = tempName;
    }

    if (roleType === 'all' || roleType === 'nurse') {
      const tempNId = targetA.nurse_id;
      const tempNName = targetA.nurse_name;
      targetA.nurse_id = targetB.nurse_id;
      targetA.nurse_name = targetB.nurse_name;
      targetB.nurse_id = tempNId;
      targetB.nurse_name = tempNName;
    }

    if (roleType === 'all' || roleType === 'sanitar') {
      const tempSanId = targetA.sanitar_id;
      const tempSanName = targetA.sanitar_name;
      targetA.sanitar_id = targetB.sanitar_id;
      targetA.sanitar_name = targetB.sanitar_name;
      targetB.sanitar_id = tempSanId;
      targetB.sanitar_name = tempSanName;
    }

    recalculateStaffDutyCounts();
    saveToLocalStorage();
    renderShiftRoster();
    renderPayrollTable();
    updateKPIs();
    closeAllModals();
    showToast(`${dayA}-Avgust va ${dayB}-Avgust smenalari o'rni almashtirildi!`, 'success');
  }

  // ==========================================================================
  // TELEGRAM & WHATSAPP EXPORT MODAL LOGIC
  // ==========================================================================

  function openTelegramModal() {
    const modal = document.getElementById('telegram-modal');
    const previewBox = document.getElementById('telegram-preview-box');
    if (!modal || !previewBox) return;

    let text = `🏥 FAYZ MEDICAL HOUSE — 24/7 NAVBATCHILIK JADVALI (AVGUST 2026)\n`;
    text += `📍 Toshkent sh., Yunusobod t., Nurmakon 2A | 24/7 Hotline: +998 90 372-03-03\n`;
    text += `━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n`;

    State.monthlySchedule.forEach(sch => {
      text += `📅 ${sch.day}-Avgust (${sch.day_name}):\n`;
      text += `  🩺 Tungi Shifokor: ${sch.doctor_night_name}\n`;
      text += `  💉 24h Hamshira (Butun bino): ${sch.nurse_name}\n`;
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
    let typeTitle = 'Tungi Navbatchi Shifokor (Tarif: 350 000 so\'m/tun)';

    if (slotType === 'nurse_f1') {
      roleFilter = 'nurse';
      typeTitle = '1-Qavat 24-Soatlik Hamshirasi (Tarif: 400 000 so\'m/24h)';
    } else if (slotType === 'nurse_f2') {
      roleFilter = 'nurse';
      typeTitle = '2-Qavat 24-Soatlik Hamshirasi (Tarif: 400 000 so\'m/24h)';
    } else if (slotType === 'nurse_24h' || slotType === 'nurse') {
      roleFilter = 'nurse';
      typeTitle = '24-Soatlik Hamshira (Tarif: 400 000 so\'m/24h)';
    } else if (slotType === 'sanitar_24h') {
      roleFilter = 'support';
      typeTitle = '24-Soatlik Sanitarka (Tarif: 300 000 so\'m/24h)';
    }

    if (titleEl) titleEl.innerHTML = `<i class="fas fa-user-check" style="color: #38bdf8;"></i> ${day}-Avgust uchun ${typeTitle}`;

    let eligible = State.staff.filter(s => s.role === roleFilter || (roleFilter === 'doctor' && s.role === 'chief_doctor') || (roleFilter === 'support' && s.id.startsWith('STF-SAN')));

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
        <div class="${cardClass}" onclick="window.FMH_HR.assignSlotStaff('${staff.id}')">
          <div style="display: flex; justify-content: space-between; align-items: flex-start;">
            <div>
              <div style="font-weight: 800; color: #ffffff; font-size: 0.95rem;">${staff.full_name}</div>
              <div style="font-size: 0.74rem; color: var(--indigo-light);">${staff.role_title_uz || staff.role}</div>
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
    const staff = State.staff.find(s => s.id === staffId);
    if (!targetDay || !staff) return;

    if (slotType === 'doctor_night') {
      targetDay.doctor_night_id = staff.id;
      targetDay.doctor_night_name = staff.full_name;
    } else if (slotType === 'nurse_f1') {
      targetDay.nurse_f1_id = staff.id;
      targetDay.nurse_f1_name = staff.full_name;
      targetDay.nurse_id = staff.id;
      targetDay.nurse_name = staff.full_name;
    } else if (slotType === 'nurse_f2') {
      targetDay.nurse_f2_id = staff.id;
      targetDay.nurse_f2_name = staff.full_name;
    } else if (slotType === 'nurse_24h' || slotType === 'nurse') {
      targetDay.nurse_f1_id = staff.id;
      targetDay.nurse_f1_name = staff.full_name;
      targetDay.nurse_id = staff.id;
      targetDay.nurse_name = staff.full_name;
    } else if (slotType === 'sanitar_24h') {
      targetDay.sanitar_id = staff.id;
      targetDay.sanitar_name = staff.full_name;
    }

    recalculateStaffDutyCounts();
    saveToLocalStorage();
    renderShiftRoster();
    renderPayrollTable();
    updateKPIs();
    closeAllModals();
    showToast(`${day}-Avgust uchun ${staff.full_name} muvaffaqiyatli biriktirildi!`, 'success');
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

      let dutyRateLabel = '—';
      if (staff.duty_rate_type === 'doctor_night') dutyRateLabel = '350 000 so\'m/tun';
      else if (staff.duty_rate_type === 'nurse_24h') dutyRateLabel = '400 000 so\'m/24h';
      else if (staff.duty_rate_type === 'sanitar_24h') dutyRateLabel = '300 000 so\'m/24h';

      return `
        <div class="staff-card" data-staff-id="${staff.id}">
          <div class="staff-card-header">
            <div class="staff-avatar" style="background: ${staff.avatar_color || '#4f46e5'};">
              ${initials}
              <span class="status-dot ${statusClass}" title="${statusLabel}"></span>
            </div>
            <div class="staff-info">
              <div class="staff-name">${staff.full_name}</div>
              <div class="staff-role-badge"><i class="fas fa-id-badge"></i> ${staff.role_title_uz || staff.role}</div>
              <div class="staff-specialty">${staff.specialty || 'Mutaxassis'}</div>
            </div>
          </div>

          <div class="staff-meta-row">
            <div class="staff-meta-chip" title="Telefon"><i class="fas fa-phone"></i> ${staff.phone || '—'}</div>
            <div class="staff-meta-chip" title="Oylik Navbatchilik"><i class="fas fa-clock"></i> ${staff.monthly_duty_count || 0} smena (${formatUZS(staff.monthly_duty_earnings)})</div>
            <div class="staff-meta-chip" title="Navbatchilik Tarifi"><i class="fas fa-tag"></i> ${dutyRateLabel}</div>
            <div class="staff-meta-chip" title="Toifa"><i class="fas fa-award"></i> ${staff.category || 'Mutaxassis'}</div>
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
          </div>
        </div>
      `;
    }).join('');
  }

  // ==========================================================================
  // TAB 3: ATTENDANCE, TAB 4: PAYROLL
  // ==========================================================================

  function renderAttendanceSheet() {
    const tbody = document.getElementById('attendance-tbody');
    if (!tbody) return;

    const badge = document.getElementById('badge-att-count');
    if (badge) badge.textContent = State.staff.length;

    tbody.innerHTML = State.staff.map((staff, idx) => {
      const att = State.attendance.find(a => a.staff_id === staff.id) || {
        status: 'present',
        check_in: '08:00',
        check_out: null,
        worked_hours: 8.0,
        late_minutes: 0,
        notes: 'Standart ish kuni'
      };

      let badgeHtml = '<span class="status-badge badge-present"><i class="fas fa-check"></i> Keldi</span>';
      if (att.status === 'late') {
        badgeHtml = `<span class="status-badge badge-late"><i class="fas fa-clock"></i> Kechikdi (${att.late_minutes} daq)</span>`;
      } else if (att.status === 'scheduled_night') {
        badgeHtml = '<span class="status-badge badge-shift"><i class="fas fa-moon"></i> Tungi smena</span>';
      } else if (att.status === 'rest') {
        badgeHtml = '<span class="status-badge badge-info"><i class="fas fa-bed"></i> Dam olishda</span>';
      } else if (att.status === 'absent') {
        badgeHtml = '<span class="status-badge badge-danger"><i class="fas fa-times"></i> Kelmadi</span>';
      }

      return `
        <tr>
          <td><span style="font-family: var(--font-mono); font-weight: 700; color: var(--text-muted);">${idx + 1}</span></td>
          <td>
            <div style="font-weight: 700; color: #ffffff;">${staff.full_name}</div>
            <div style="font-size: 0.74rem; color: var(--text-secondary);">${staff.role_title_uz || staff.role}</div>
          </td>
          <td><span class="staff-meta-chip"><i class="fas fa-building"></i> ${staff.department_name_uz || staff.department}</span></td>
          <td><span style="font-family: var(--font-mono); font-weight: 700; color: #38bdf8;">${att.check_in || '—'}</span></td>
          <td><span style="font-family: var(--font-mono); font-weight: 700; color: var(--text-muted);">${att.check_out || 'Ish jarayonida'}</span></td>
          <td><span style="font-family: var(--font-mono); font-weight: 700; color: #34d399;">${att.worked_hours || 0} soat</span></td>
          <td>${badgeHtml}</td>
          <td><span style="font-size: 0.78rem; color: var(--text-secondary);">${att.notes || '—'}</span></td>
          <td style="text-align: center;">
            <button class="btn-portal btn-outline-portal" style="padding: 4px 8px; font-size: 0.74rem;" onclick="window.FMH_HR.openLogAttendanceModal('${staff.id}')">
              <i class="fas fa-user-check"></i> Qayd etish
            </button>
          </td>
        </tr>
      `;
    }).join('');
  }

  function renderPayrollTable() {
    const tbody = document.getElementById('payroll-tbody');
    if (!tbody) return;

    let grandGross = 0;
    let grandTaxes = 0;
    let grandNet = 0;

    tbody.innerHTML = State.staff.map((staff) => {
      const base = staff.base_salary || 0;
      const dutyEarnings = staff.monthly_duty_earnings || 0;
      const dutyCount = staff.monthly_duty_count || 0;

      let dutyRateLabel = '';
      if (staff.duty_rate_type === 'doctor_night') dutyRateLabel = `${dutyCount} tun x 350 000`;
      else if (staff.duty_rate_type === 'nurse_24h') dutyRateLabel = `${dutyCount} smena x 400 000`;
      else if (staff.duty_rate_type === 'sanitar_24h') dutyRateLabel = `${dutyCount} smena x 300 000`;

      const inpatientBonus = (staff.role === 'doctor' || staff.role === 'chief_doctor') ? 2600000 : 0;
      const detoxBonus = (staff.detox_procedure_fee || 0) * 6;
      
      const gross = base + dutyEarnings + inpatientBonus + detoxBonus;
      const tax = gross * 0.12;
      const inps = gross * 0.001;
      const totalDeductions = tax + inps;
      const net = gross - totalDeductions;

      grandGross += gross;
      grandTaxes += totalDeductions;
      grandNet += net;

      return `
        <tr>
          <td><span style="font-family: var(--font-mono); font-weight: 700; color: var(--text-muted);">${staff.id}</span></td>
          <td>
            <div style="font-weight: 700; color: #ffffff;">${staff.full_name}</div>
            <div style="font-size: 0.72rem; color: var(--indigo-light);">${staff.role_title_uz || staff.role}</div>
          </td>
          <td><span style="font-family: var(--font-mono);">${formatUZS(base)}</span></td>
          <td>
            <div style="font-family: var(--font-mono); font-weight: 700; color: #34d399;">+${formatUZS(dutyEarnings)}</div>
            <div style="font-size: 0.7rem; color: var(--text-muted);">${dutyRateLabel || '—'}</div>
          </td>
          <td><span style="font-family: var(--font-mono); color: #38bdf8;">+${formatUZS(inpatientBonus + detoxBonus)}</span></td>
          <td><span style="font-family: var(--font-mono); color: #fb7185;">-${formatUZS(totalDeductions)}</span></td>
          <td><span style="font-family: var(--font-mono); font-weight: 800; color: #34d399; font-size: 0.95rem;">${formatUZS(net)}</span></td>
          <td><span class="status-badge badge-active"><i class="fas fa-check-circle"></i> Hisoblangan</span></td>
          <td style="text-align: center;">
            <button class="btn-portal btn-primary-portal" style="padding: 4px 10px; font-size: 0.74rem;" onclick="window.FMH_HR.generatePayslip('${staff.id}')">
              <i class="fas fa-receipt"></i> Pay Slip
            </button>
          </td>
        </tr>
      `;
    }).join('');

    const elGrandGross = document.getElementById('payroll-total-gross');
    if (elGrandGross) elGrandGross.textContent = formatUZS(grandGross);
    const elGrandTaxes = document.getElementById('payroll-total-taxes');
    if (elGrandTaxes) elGrandTaxes.textContent = formatUZS(grandTaxes);
    const elGrandNet = document.getElementById('payroll-total-net');
    if (elGrandNet) elGrandNet.textContent = formatUZS(grandNet);
  }

  // ==========================================================================
  // OFFICIAL PAYSLIP & DOSSIER
  // ==========================================================================

  function generatePayslip(staffId) {
    const staff = State.staff.find(s => s.id === staffId);
    if (!staff) return;

    const base = staff.base_salary || 0;
    const dutyEarnings = staff.monthly_duty_earnings || 0;
    const dutyCount = staff.monthly_duty_count || 0;

    let dutyItemLabel = 'Navbatchilik To\'lovi:';
    if (staff.duty_rate_type === 'doctor_night') {
      dutyItemLabel = `Tungi Navbatchilik (${dutyCount} tun x 350 000 so'm):`;
    } else if (staff.duty_rate_type === 'nurse_24h') {
      dutyItemLabel = `24-Soatlik Hamshiralik Navbatchiligi (Butun Bino) (${dutyCount} smena x 400 000 so'm):`;
    } else if (staff.duty_rate_type === 'sanitar_24h') {
      dutyItemLabel = `24-Soatlik Sanitariya Navbatchiligi (${dutyCount} smena x 300 000 so'm):`;
    }

    const inpatientBonus = (staff.role === 'doctor' || staff.role === 'chief_doctor') ? 2600000 : 0;
    const detoxBonus = (staff.detox_procedure_fee || 0) * 6;
    
    const gross = base + dutyEarnings + inpatientBonus + detoxBonus;
    const tax = gross * 0.12;
    const inps = gross * 0.001;
    const totalDeductions = tax + inps;
    const net = gross - totalDeductions;

    const modal = document.getElementById('payslip-modal');
    const container = document.getElementById('payslip-sheet-container');
    if (!modal || !container) return;

    container.innerHTML = `
      <div class="payslip-sheet">
        <div class="payslip-header">
          <div>
            <div class="payslip-title">FAYZ MEDICAL HOUSE</div>
            <div style="font-size: 0.8rem; color: #64748b; font-weight: 600;">OYLIK MAOSH VA DAROMADLAR QAYDNOMASI (PAY SLIP)</div>
            <div style="font-size: 0.75rem; color: #94a3b8;">Davr: Avgust 2026 | Toshkent sh., Yunusobod t., Nurmakon 2A</div>
          </div>
          <div style="text-align: right;">
            <div style="font-size: 0.95rem; font-weight: 700; font-family: var(--font-mono);">№ PS-2026-${staff.id.replace('STF-', '')}</div>
            <div style="font-size: 0.75rem; color: #64748b;">Sana: 15.08.2026</div>
          </div>
        </div>

        <table class="payslip-table">
          <tr>
            <th style="width: 25%;">Xodim F.I.Sh:</th>
            <td style="font-weight: 700;">${staff.full_name}</td>
            <th style="width: 25%;">Xodim ID:</th>
            <td style="font-family: var(--font-mono); font-weight: 700;">${staff.id}</td>
          </tr>
          <tr>
            <th>Lavozim / Ixtisoslik:</th>
            <td>${staff.role_title_uz || staff.role}</td>
            <th>Bo'lim:</th>
            <td>${staff.department_name_uz || staff.department}</td>
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
                <td style="font-weight: 700; color: #0284c7;">${dutyItemLabel}</td>
                <td style="text-align: right; font-family: var(--font-mono); font-weight: 800; color: #0284c7;">+${formatUZS(dutyEarnings)}</td>
              </tr>
              <tr>
                <td>Statsionar Bemorlar Gonorari:</td>
                <td style="text-align: right; font-family: var(--font-mono);">${formatUZS(inpatientBonus)}</td>
              </tr>
              <tr>
                <td>Detoksikatsiya / Chaqiruv Bonusi:</td>
                <td style="text-align: right; font-family: var(--font-mono);">${formatUZS(detoxBonus)}</td>
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
                <td>Jismoniy Shaxslar Daromad Solig'i (12%):</td>
                <td style="text-align: right; font-family: var(--font-mono);">${formatUZS(tax)}</td>
              </tr>
              <tr>
                <td>INPS Shaxsiy Pensiya (0.1%):</td>
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
            Holat: <span style="color: #10b981; font-weight: 700;">TO'LANGAN ✓</span>
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

    let tariffLabel = 'Belgilanmagan';
    if (staff.duty_rate_type === 'doctor_night') tariffLabel = 'Shifokor Tungi (350 000 so\'m)';
    else if (staff.duty_rate_type === 'nurse_24h') tariffLabel = 'Hamshira 24 Soatlik (400 000 so\'m)';
    else if (staff.duty_rate_type === 'sanitar_24h') tariffLabel = 'Sanitarka 24 Soatlik (300 000 so\'m)';

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
          <div style="font-weight: 600; color: #ffffff;">${staff.department_name_uz || staff.department} — ${staff.specialty}</div>
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
          <div style="font-weight: 600; color: #ffffff;">${staff.category || 'Mutaxassis'}</div>
        </div>
        <div class="form-group">
          <label class="form-label">KPI Reyting</label>
          <div style="font-weight: 700; color: #fbbf24;"><i class="fas fa-star"></i> ${staff.kpi_rating || 5.0} / 5.0</div>
        </div>
      </div>

      <div style="margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid var(--border-subtle); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem;">
        <button class="btn-portal btn-danger-portal" style="background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); padding: 6px 14px; font-size: 0.82rem;" onclick="window.FMH_HR.deleteStaff('${staff.id}')">
          <i class="fas fa-trash-alt"></i> Xodimni Tizimdan O'chirish
        </button>
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
    const confirmed = await fmhConfirm({
      title: "Xodimni O'chirish",
      message: `<strong>${staffName}</strong> xodimini bazadan butunlay o'chirishni tasdiqlaysizmi?`,
      confirmText: "O'chirish",
      cancelText: "Bekor Qilish",
      type: 'danger'
    });
    if (!confirmed) {
      return;
    }

    try {
      await fetch('/api/staff/' + encodeURIComponent(staffId), { method: 'DELETE' });
    } catch (err) {
      console.warn('DELETE /api/staff error:', err);
    }

    State.staff = State.staff.filter(s => s.id !== staffId);
    saveToLocalStorage();
    renderAll();
    closeAllModals();
    showToast(`${staffName} muvaffaqiyatli o'chirildi!`, 'danger');
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
      role: 'admin',
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

  function openEditStaffModal(staffId) {
    const staff = State.staff.find(s => s.id === staffId);
    if (!staff) return;

    closeAllModals();

    const modal = document.getElementById('add-staff-modal');
    const form = document.getElementById('add-staff-form');
    if (!modal || !form) return;

    form.reset();

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
    if (form.role) form.role.value = staff.role || 'doctor';
    if (form.role_title_uz) form.role_title_uz.value = staff.role_title_uz || '';
    if (form.department) form.department.value = staff.department || 'doctors';
    if (form.specialty) form.specialty.value = staff.specialty || '';
    if (form.category) form.category.value = staff.category || 'Oliy toifa';
    if (form.base_salary) {
      form.base_salary.value = staff.base_salary || staff.salary_base || 10000000;
      updateSalaryPreview(staff.base_salary || staff.salary_base || 10000000);
    }
    if (form.detox_procedure_fee) form.detox_procedure_fee.value = staff.detox_procedure_fee || 0;
    if (form.shift_type) form.shift_type.value = staff.shift_type || 'day_standard';
    if (form.assigned_floor) form.assigned_floor.value = staff.assigned_floor || 'all';
    if (form.email) form.email.value = staff.email || '';
    if (form.telegram) form.telegram.value = staff.telegram || '';
    if (form.passport_pinfl) form.passport_pinfl.value = staff.passport_pinfl || '';
    if (form.experience_years) form.experience_years.value = staff.experience_years || 5;
    if (form.hire_date) form.hire_date.value = staff.hire_date || new Date().toISOString().split('T')[0];

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
    else if (roleVal === 'admin' && (form.role_title_uz && form.role_title_uz.value.toLowerCase().includes('sanitar'))) dutyRate = 'sanitar_24h';

    let staffId = editingId;
    if (!staffId) {
      const count = (State.staff || []).length + 1;
      const prefix = (roleVal === 'doctor' || roleVal === 'chief_doctor') ? 'DOC' : (roleVal === 'nurse' ? 'NRS' : (roleVal === 'receptionist' ? 'REC' : 'ADM'));
      staffId = `STF-${prefix}-${String(count).padStart(2, '0')}`;
    }

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
      role_title_uz: (form.role_title_uz && form.role_title_uz.value.trim()) ? form.role_title_uz.value.trim() : (roleVal === 'doctor' ? 'Shifokor-Narkolog' : (roleVal === 'nurse' ? 'Navbatchi Hamshira' : 'Tibbiy Xodim')),
      department: departmentVal,
      department_name_uz: departmentNameUz,
      specialty: (form.specialty && form.specialty.value.trim()) ? form.specialty.value.trim() : (roleVal === 'doctor' ? 'Narkologiya' : (roleVal === 'nurse' ? 'Hamshiralik ishi' : 'Umumiy')),
      phone: (form.phone ? form.phone.value : '').trim(),
      email: (form.email && form.email.value.trim()) ? form.email.value.trim() : `${staffId.toLowerCase()}@fayzmedical.uz`,
      telegram: form.telegram ? form.telegram.value.replace('@', '').trim() : (existingStaff?.telegram || ''),
      passport_pinfl: form.passport_pinfl ? form.passport_pinfl.value.trim() : (existingStaff?.passport_pinfl || ''),
      hire_date: (form.hire_date && form.hire_date.value) ? form.hire_date.value : (existingStaff?.hire_date || new Date().toISOString().split('T')[0]),
      experience_years: form.experience_years ? (parseInt(form.experience_years.value) || 1) : (existingStaff?.experience_years || 5),
      category: form.category ? form.category.value : (existingStaff?.category || 'Oliy toifa'),
      shift_type: form.shift_type ? form.shift_type.value : (existingStaff?.shift_type || 'day_standard'),
      assigned_floor: form.assigned_floor ? form.assigned_floor.value : (existingStaff?.assigned_floor || 'all'),
      base_salary: form.base_salary ? (parseFloat(form.base_salary.value) || 10000000) : 10000000,
      duty_rate_type: dutyRate,
      monthly_duty_count: existingStaff?.monthly_duty_count || 0,
      monthly_duty_earnings: existingStaff?.monthly_duty_earnings || 0,
      detox_procedure_fee: form.detox_procedure_fee ? (parseFloat(form.detox_procedure_fee.value) || 0) : (existingStaff?.detox_procedure_fee || 0),
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
      if (res.ok) {
        const data = await res.json();
        if (data.id) staffRecord.id = data.id;
        else if (data.staff && data.staff.id) staffRecord.id = data.staff.id;
      }
    } catch (err) {
      console.warn('POST /api/staff network warning, persisting locally:', err);
    }

    if (!State.staff) State.staff = [];
    const existsIdx = State.staff.findIndex(s => s.id === staffRecord.id);
    if (existsIdx >= 0) {
      State.staff[existsIdx] = { ...State.staff[existsIdx], ...staffRecord };
    } else {
      State.staff.unshift(staffRecord);
    }

    ensureMonthlySchedule();
    saveToLocalStorage();
    renderAll();
    try { form.reset(); } catch(e) {}
    closeAllModals();
    showToast(isEdit ? `${staffRecord.full_name} ma'lumotlari yangilandi!` : `${staffRecord.full_name} muvaffaqiyatli qo'shildi!`, 'success');
  }

  function openLogAttendanceModal(staffId) {
    const staff = State.staff.find(s => s.id === staffId);
    if (!staff) return;

    State.selectedStaffId = staffId;
    const modal = document.getElementById('log-attendance-modal');
    const staffNameEl = document.getElementById('att-modal-staff-name');
    if (staffNameEl) staffNameEl.textContent = staff.full_name;
    if (modal) modal.classList.add('active');
  }

  function handleLogAttendanceSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const staffId = State.selectedStaffId;
    if (!staffId) return;

    const existingIdx = State.attendance.findIndex(a => a.staff_id === staffId);
    const newRecord = {
      id: `ATT-2026-${staffId}`,
      staff_id: staffId,
      date: '2026-08-15',
      check_in: form.check_in.value || '08:00',
      check_out: form.check_out.value || null,
      status: form.status.value,
      worked_hours: parseFloat(form.worked_hours.value) || 8.0,
      late_minutes: parseInt(form.late_minutes.value) || 0,
      notes: form.notes.value || 'Davomat yangilandi'
    };

    if (existingIdx >= 0) State.attendance[existingIdx] = newRecord;
    else State.attendance.push(newRecord);

    saveToLocalStorage();
    renderAttendanceSheet();
    updateKPIs();
    closeAllModals();
    showToast('Davomat muvaffaqiyatli saqlandi!', 'success');
  }

  function exportAllToExcel() {
    if (typeof XLSX === 'undefined') {
      showToast('Excel moduli yuklanmoqda...', 'danger');
      return;
    }

    const wb = XLSX.utils.book_new();

    const scheduleData = State.monthlySchedule.map(s => ({
      'Sana': s.date,
      'Kun': s.day_name,
      'Brigada': s.brigade_name || '—',
      'Tungi Shifokor (350 000)': s.doctor_night_name,
      '24h Hamshira (Butun Bino — 400 000)': s.nurse_name,
      '24h Sanitarka (300 000)': s.sanitar_name,
      '24/7 On-Call Shifokor': s.oncall_doc_name,
      'Kunlik Navbatchilik Chiqimi': s.daily_duty_cost
    }));
    const wsSchedule = XLSX.utils.json_to_sheet(scheduleData);
    XLSX.utils.book_append_sheet(wb, wsSchedule, '24-7 Navbatchilik Jadvali');

    const payData = State.staff.map(s => {
      const base = s.base_salary || 0;
      const dutyEarnings = s.monthly_duty_earnings || 0;
      const inpatientBonus = (s.role === 'doctor' || s.role === 'chief_doctor') ? 2600000 : 0;
      const detoxBonus = (s.detox_procedure_fee || 0) * 6;
      const gross = base + dutyEarnings + inpatientBonus + detoxBonus;
      const tax = gross * 0.12;
      const inps = gross * 0.001;
      const net = gross - tax - inps;
      return {
        'Xodim ID': s.id,
        'F.I.Sh': s.full_name,
        'Lavozim': s.role_title_uz || s.role,
        'Asosiy Oklad': base,
        'Navbatchiliklar Soni': s.monthly_duty_count || 0,
        'Navbatchilik To\'lovi': dutyEarnings,
        'Detox & Statsionar Bonusi': inpatientBonus + detoxBonus,
        'Jami Gross': gross,
        'Daromad Solig\'i (12%)': tax,
        'INPS (0.1%)': inps,
        'Sof To\'lanadigan (Net)': net,
        'To\'lov Holati': 'To\'langan'
      };
    });
    const wsPay = XLSX.utils.json_to_sheet(payData);
    XLSX.utils.book_append_sheet(wb, wsPay, 'Oylik Maosh Qaydi');

    XLSX.writeFile(wb, `FMH_Navbatchilik_va_Oyliklar_Avgust_2026.xlsx`);
    showToast('24/7 Navbatchilik va Oyliklar Excel hisoboti yuklab olindi!', 'success');
  }

  function closeAllModals() {
    document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('active'));
  }

  function switchTab(tabId) {
    State.activeTab = tabId;
    document.querySelectorAll('.portal-tabs .tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId);
    });

    document.querySelectorAll('.tab-panel').forEach(panel => {
      panel.classList.toggle('active', panel.id === `tab-panel-${tabId}`);
    });
  }

  function updateKPIs() {
    const totalStaff = State.staff.length;
    const todayAtt = State.attendance.filter(a => a.status === 'present' || a.status === 'late');

    let totalPayroll = 0;
    State.staff.forEach(s => {
      const base = s.base_salary || 0;
      const dutyEarnings = s.monthly_duty_earnings || 0;
      const inpatientComm = (s.role === 'doctor' || s.role === 'chief_doctor') ? 2600000 : 0;
      const detoxBonus = (s.detox_procedure_fee || 0) * 6;

      const gross = base + dutyEarnings + inpatientComm + detoxBonus;
      const tax = gross * 0.12;
      const inps = gross * 0.001;
      const net = gross - (tax + inps);
      totalPayroll += net;
    });

    const elTotal = document.getElementById('stat-total-staff');
    if (elTotal) elTotal.textContent = `${totalStaff} nafar`;

    const elDuty = document.getElementById('stat-on-duty');
    if (elDuty) elDuty.textContent = `${todayAtt.length} nafar`;

    const elPayroll = document.getElementById('stat-payroll-budget');
    if (elPayroll) elPayroll.textContent = formatUZS(totalPayroll);

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

    const base = staff.base_salary || staff.salary_base || 0;
    const dutyEarnings = staff.monthly_duty_earnings || 0;
    const inpatientBonus = ((staff.role === 'doctor' || staff.role === 'chief_doctor') ? 2600000 : 0)
      + (staff.detox_procedure_fee || 0) * 6;

    if (window.FMH_Print) {
      window.FMH_Print.employeePayslip(staff, {
        base_salary: base,
        bonuses: inpatientBonus,
        night_shifts: dutyEarnings
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
    triggerAutoSchedule: () => {
      applyBrigadesToMonth('brigade_1_3');
      showToast('1/3 Rejimi bo\'yicha 4 ta brigada butun oyga avtomatik tatbiq etildi!', 'success');
    },
    exportAllToExcel,
    closeAllModals,
    switchTab,
    deleteStaff,
    editStaff: (id) => openEditStaffModal(id),
    printPayslip,
    toggleTheme: () => window.FMH_Theme ? window.FMH_Theme.toggle() : null,
    applyTheme: (t) => window.FMH_Theme ? window.FMH_Theme.set(t) : null
  };

})();
