/**
 * Fayz Medical House - Facility & Bed Management Engine
 * Clean Naming: "11-xona 1A karavot", "21-xona 21A karavot", etc.
 * Total Spots: 14 Inpatient Beds (Floor 1: 4 beds, Floor 2: 10 beds)
 * Automatic 2nd Bed Locking on Full Room (Butun Xona / Solo 1.1M)
 * Complete Edit, Change & Delete Engine across Gantt Chart, Table & Blueprint Views
 */

(function () {
  'use strict';

  let clinicData = null;
  let floors = [];
  let bookings = [];
  let currentFloor = 'all'; // '1' | '2' | 'all'
  let currentView = 'blueprint'; // 'blueprint' | 'calendar' | 'table'
  let currentFilter = 'all'; // 'all' | 'available' | 'occupied' | 'reserved'
  let searchQuery = '';
  function getDynamicCalendarStart() {
    const d = new Date();
    d.setDate(d.getDate() - 3);
    return d;
  }
  let calendarStartDate = getDynamicCalendarStart();
  let calendarDaysCount = 14;



  const STORAGE_KEY = 'FMH_FACILITY_14BEDS_STORAGE_V18';

  function getTodayStr() {
    const d = new Date();
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  function getOffsetDateStr(daysOffset) {
    const d = new Date();
    d.setDate(d.getDate() + daysOffset);
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  // Toast notification helper
  // Delegates to the shared toast in js/fmh_dialogs.js: that one announces
  // messages via aria-live, keeps errors on screen long enough to read,
  // stacks instead of erasing an unread message, and can be dismissed.
  function showToast(message, type = 'success') {
    return window.FMH_Toast(message, type);
  }

  // Exact date interval overlap formula
  function datesOverlap(startA, endA, startB, endB) {
    if (!startA || !endA || !startB || !endB) return false;
    return (startA < endB) && (endA > startB);
  }

  // Detect whether a booking reserved the whole room (Butun Xona / Solo 1.1M)
  function isFullRoomBooking(booking) {
    if (!booking) return false;
    if (booking.is_full_room === true) return true;
    const prog = String(booking.program || '').toLowerCase();
    return prog.includes('butun xona') || 
           prog.includes('1.1 mln') || 
           prog.includes('solo') || 
           prog.includes('1 100 000') ||
           prog.includes('full room');
  }

  // Find partner bed in the same room (7 rooms x 2 beds = 14 beds)
  function getPartnerBedId(bedId) {
    if (!bedId) return null;
    const cleanId = String(bedId).toUpperCase().trim();

    const PARTNER_MAP = {
      "BED-1A": "BED-1B", "BED-1B": "BED-1A",
      "BED-2A": "BED-2B", "BED-2B": "BED-2A",
      "BED-21A": "BED-21B", "BED-21B": "BED-21A",
      "BED-22A": "BED-22B", "BED-22B": "BED-22A",
      "BED-23A": "BED-23B", "BED-23B": "BED-23A",
      "BED-24A": "BED-24B", "BED-24B": "BED-24A",
      "BED-25A": "BED-25B", "BED-25B": "BED-25A"
    };

    if (PARTNER_MAP.hasOwnProperty(cleanId)) return PARTNER_MAP[cleanId];

    // Dynamic fallback
    const allBeds = getAllBeds();
    const currentBed = allBeds.find(b => b.bed_id && b.bed_id.toUpperCase() === cleanId);
    if (currentBed && currentBed.room_id) {
      const partner = allBeds.find(b => b.room_id === currentBed.room_id && b.bed_id.toUpperCase() !== cleanId);
      return partner ? partner.bed_id : null;
    }
    return null;
  }

  // Sanitize any existing illegal double-bookings where one was Full Room
  function sanitizeConflictedBookings() {
    const cleaned = [];
    bookings.forEach(b => {
      if (b.status === 'cancelled' || b.status === 'completed') {
        cleaned.push(b);
        return;
      }
      const isFR = isFullRoomBooking(b);
      const partnerId = getPartnerBedId(b.bed_id);
      if (!isFR && partnerId) {
        const hasFullRoomPartner = bookings.find(other => 
          other.id !== b.id &&
          String(other.bed_id).toUpperCase() === String(partnerId).toUpperCase() &&
          isFullRoomBooking(other) &&
          other.status !== 'cancelled' &&
          other.status !== 'completed' &&
          datesOverlap(b.start_date, b.end_date, other.start_date, other.end_date)
        );
        if (hasFullRoomPartner) {
          console.warn(`[Auto-Sanitized] Removed conflicted standard booking ${b.id} on ${b.bed_id} because ${partnerId} is Full Room Solo booked by ${hasFullRoomPartner.patient_name}`);
          return;
        }
      }
      cleaned.push(b);
    });
    bookings = cleaned;
    saveBookings();
  }

  let liveBedsData = [];

  // HTML-escape anything typed by staff (names, notes, server messages)
  // before it goes into innerHTML.
  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // Readable names for the programme ids reception stores in
  // admissions.program_type; an unknown id is shown as stored.
  const PROGRAM_NAMES = {
    statsionar_shared: "Statsionar (1 karavot / 2 kishilik xona)",
    statsionar_full_room: "Statsionar Butun Xona — VIP Solo (1 kishi)",
    kunlik_statsionar: "Kunlik Statsionar (Kunduzgi o'rin)"
  };

  // All admissions start at Reception. The board used to open its own
  // "new patient" form here, but that form only wrote to this page's memory
  // and localStorage: the 4-second refresh replaced it with the server's
  // admissions, so a patient "admitted" on the board vanished right after the
  // success toast and no invoice or bed booking ever existed.
  function goToReception() {
    showToast("Qabul Qabulxonada rasmiylashtiriladi. Qabulxona sahifasi ochilmoqda...", 'info');
    setTimeout(() => { window.location.href = 'reception.html'; }, 700);
  }

  // Set once a refresh fails, so the "showing last known data" warning is
  // given once per outage instead of every 4 seconds.
  let liveFetchFailed = false;

  function noteLiveFetchFailure() {
    if (!liveFetchFailed) {
      liveFetchFailed = true;
      showToast("Server bilan aloqa uzildi — oxirgi ma'lumotlar ko'rsatilmoqda.", 'warning');
    }
  }

  async function fetchLiveBedsAndAdmissions() {
    try {
      const [bedsRes, admRes] = await Promise.all([
        fetch('/api/beds'),
        fetch('/api/admissions')
      ]);

      if (bedsRes.ok) {
        liveBedsData = await bedsRes.json();
      }

      if (admRes.ok) {
        const liveAdmissions = await admRes.json();
        // A missing phone or rate stays empty: showing a made-up number
        // ('+998 90 000 00 00', 720 000) looked like real patient data.
        bookings = liveAdmissions.filter(adm => adm.status === 'active').map(adm => ({
          id: adm.id,
          bed_id: adm.bed_id,
          patient_id: adm.patient_id,
          patient_code: adm.patient_code || '',
          patient_name: adm.patient_name || 'Bemor',
          patient_phone: adm.patient_phone || '',
          doctor: adm.doctor_name || 'Shifokor biriktirilmagan',
          program: adm.program_type || 'Statsionar davolanish',
          daily_rate: (adm.daily_price === null || adm.daily_price === undefined || adm.daily_price === '') ? null : Number(adm.daily_price),
          start_date: adm.start_date,
          end_date: adm.planned_end_date,
          notes: adm.admission_notes || '',
          status: 'active',
          // The server decides "whole room" by programme; the price test is
          // kept for stays booked before the programme id existed.
          is_full_room: adm.program_type === 'statsionar_full_room' || Number(adm.daily_price) >= 1100000
        }));
        saveBookings();
        if (bedsRes.ok) liveFetchFailed = false;
      } else {
        // Keep the last good list. Clearing it made every bed flash "free"
        // whenever one refresh failed (server restart, lost session, Wi-Fi).
        noteLiveFetchFailure();
      }
    } catch (e) {
      noteLiveFetchFailure();
    }
  }

  async function init() {
    try {
      const response = await fetch('./data/clinic_rooms.json');
      clinicData = await response.json();
      floors = clinicData.floors || [];

      // Fetch live beds and admissions from REST API as single source of truth
      await fetchLiveBedsAndAdmissions();

      sanitizeConflictedBookings();
      refreshBedStatuses();
      setupEventListeners();
      renderDashboard();
      if (window.FMH_Pricing) window.FMH_Pricing.ready.then(() => renderDashboard());

      // Real-time periodic refresh every 4s
      setInterval(async () => {
        try {
          await fetchLiveBedsAndAdmissions();
          refreshBedStatuses();
          renderDashboard();
        } catch (e) {}
      }, 4000);

      window.addEventListener('storage', (e) => {
        if (e.key === STORAGE_KEY) {
          try {
            bookings = JSON.parse(e.newValue);
            refreshBedStatuses();
            renderDashboard();
          } catch (err) {}
        }
      });
    } catch (error) {
      console.error('Failed to load clinic blueprint data:', error);
    }
  }

  // Guards the bookings sync against feeding itself. saveBookings() dispatches
  // 'fmh_bookings_updated', and the listener for that event calls
  // sanitizeConflictedBookings(), which ends by calling saveBookings() again.
  // Because dispatchEvent() is synchronous, that cycle recursed until the stack
  // overflowed ("Maximum call stack size exceeded") as soon as the page had any
  // real bookings to sanitize. The flag suppresses only the echo back out while
  // an incoming update is being applied; updates from other portals such as
  // reception.js are still received and still broadcast normally.
  let applyingBookingUpdate = false;

  function saveBookings() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(bookings));
    if (applyingBookingUpdate) return;
    window.dispatchEvent(new CustomEvent('fmh_bookings_updated', { detail: bookings }));
  }

  // Refresh live statuses across all 14 beds, with Full Room locks taking absolute priority
  function refreshBedStatuses() {
    const todayStr = getTodayStr();

    getAllBeds().forEach(bed => {
      const bedIdClean = String(bed.bed_id).toUpperCase();
      const partnerBedId = getPartnerBedId(bed.bed_id);
      const partnerClean = partnerBedId ? String(partnerBedId).toUpperCase() : null;
      bed.under_repair = false;

      // 1. Partner full-room active booking TODAY (Takes absolute FIRST priority for twin locking!)
      const partnerActiveFullRoom = partnerClean ? bookings.find(b =>
        String(b.bed_id).toUpperCase() === partnerClean &&
        isFullRoomBooking(b) &&
        b.status !== 'cancelled' && b.status !== 'completed' &&
        b.start_date <= todayStr &&
        b.end_date >= todayStr
      ) : null;

      // 2. Direct active booking TODAY
      const activeBooking = bookings.find(b => 
        String(b.bed_id).toUpperCase() === bedIdClean && 
        b.status !== 'cancelled' && b.status !== 'completed' &&
        b.start_date <= todayStr && 
        b.end_date >= todayStr
      );

      // Collect ALL non-cancelled bookings for this bed or full-room partner lock
      const allUpcomingBookings = bookings.filter(b => 
        b.status !== 'cancelled' && b.status !== 'completed' &&
        (String(b.bed_id).toUpperCase() === bedIdClean || (partnerClean && String(b.bed_id).toUpperCase() === partnerClean && isFullRoomBooking(b)))
      ).sort((a, b) => a.start_date.localeCompare(b.start_date));

      let nextFreeDate = todayStr;
      allUpcomingBookings.forEach(b => {
        if (b.end_date > nextFreeDate) {
          nextFreeDate = b.end_date;
        }
      });
      bed.next_free_date = nextFreeDate;
      bed.all_upcoming_bookings = allUpcomingBookings;

      // 3. Check FUTURE bookings (starting after today) sorted by start_date
      const directFutureBookings = (!activeBooking) ? bookings.filter(b => 
        String(b.bed_id).toUpperCase() === bedIdClean && 
        b.status !== 'cancelled' && b.status !== 'completed' &&
        b.start_date > todayStr
      ).sort((a, b) => a.start_date.localeCompare(b.start_date)) : [];

      const partnerFutureFullRooms = (!partnerActiveFullRoom && partnerClean) ? bookings.filter(b =>
        String(b.bed_id).toUpperCase() === partnerClean &&
        isFullRoomBooking(b) &&
        b.status !== 'cancelled' && b.status !== 'completed' &&
        b.start_date > todayStr
      ).sort((a, b) => a.start_date.localeCompare(b.start_date)) : [];

      const directFutureBooking = directFutureBookings[0] || null;
      const partnerFutureFullRoom = partnerFutureFullRooms[0] || null;

      // Match live status from /api/beds (v_bed_live_status)
      const liveBed = liveBedsData.find(lb => 
        String(lb.bed_id).toUpperCase() === bedIdClean || 
        String(lb.bed_code).toUpperCase() === bedIdClean || 
        String(lb.bed_code).toUpperCase() === String(bed.bed_number).toUpperCase()
      );

      if (liveBed) {
        bed.physical_bed_status = liveBed.physical_bed_status;
        bed.next_reserved_date = liveBed.next_reserved_date;
      }

      if (partnerActiveFullRoom) {
        // AUTOMATICALLY LOCK SECOND BED AS OCCUPIED/LOCKED TODAY
        bed.status = 'occupied';
        bed.is_locked_by_partner = true;
        bed.locked_by_booking = partnerActiveFullRoom;
        bed.future_booking = null;
        bed.future_lock = null;
        bed.future_bookings_count = 0;
        bed.future_locks_count = 0;
        bed.current_patient = {
          booking_id: partnerActiveFullRoom.id,
          name: `🔒 Butun xona band (${partnerActiveFullRoom.patient_name})`,
          phone: partnerActiveFullRoom.patient_phone,
          patient_code: partnerActiveFullRoom.patient_code,
          program: `Butun xona (2-karavot qulflangan)`,
          doctor: partnerActiveFullRoom.doctor,
          check_in: partnerActiveFullRoom.start_date,
          check_out: partnerActiveFullRoom.end_date,
          notes: `Ushbu xona ${partnerActiveFullRoom.patient_name} tomonidan "Butun xona (Solo)" sifatida band qilingan. Boshqa bemor olinmaydi.`
        };
      } else if (activeBooking) {
        bed.status = 'occupied';
        bed.is_locked_by_partner = false;
        bed.locked_by_booking = null;
        bed.future_booking = null;
        bed.future_lock = null;
        bed.future_bookings_count = 0;
        bed.future_locks_count = 0;
        bed.current_patient = {
          booking_id: activeBooking.id,
          name: activeBooking.patient_name,
          phone: activeBooking.patient_phone,
          patient_code: activeBooking.patient_code,
          program: activeBooking.program,
          doctor: activeBooking.doctor,
          check_in: activeBooking.start_date,
          check_out: activeBooking.end_date,
          notes: activeBooking.notes
        };
      } else if (liveBed && (liveBed.physical_bed_status === 'cleaning' || liveBed.status === 'cleaning' ||
                             liveBed.physical_bed_status === 'maintenance' || liveBed.physical_bed_status === 'out_of_service')) {
        // Clinical sanitation or repair in progress. A bed under repair used
        // to render as free, so the desk could pick a bed the server then
        // refused. It shares the cleaning card (and the "cleaning" filter and
        // counter) but is labelled TA'MIRDA and returned with "Ta'mirlandi".
        bed.status = 'cleaning';
        bed.under_repair = liveBed.physical_bed_status === 'maintenance' || liveBed.physical_bed_status === 'out_of_service';
        bed.is_locked_by_partner = false;
        bed.locked_by_booking = null;
        bed.current_patient = null;
        bed.future_booking = directFutureBooking;
        bed.future_lock = partnerFutureFullRoom;
        bed.future_bookings_count = directFutureBookings.length;
        bed.future_locks_count = partnerFutureFullRooms.length;
      } else {
        // TODAY THE BED IS FREE / AVAILABLE!
        bed.status = 'available';
        bed.under_repair = false;
        bed.is_locked_by_partner = false;
        bed.locked_by_booking = null;
        bed.current_patient = null;
        bed.future_booking = directFutureBooking;
        bed.future_lock = partnerFutureFullRoom;
        bed.future_bookings_count = directFutureBookings.length;
        bed.future_locks_count = partnerFutureFullRooms.length;
      }
    });
  }

  function getAllBeds(floorFilter = null) {
    const beds = [];
    floors.forEach(floor => {
      if (floorFilter && floorFilter !== 'all' && floor.floor_number.toString() !== floorFilter.toString()) {
        return;
      }
      floor.rooms.forEach(r => {
        if (r.has_beds && r.beds) {
          r.beds.forEach(b => {
            b.floor_num = floor.floor_number;
            b.room_id = r.id;
            b.room_name_uz = r.name_uz;
            b.room_number = r.room_number;
            b.simple_name = `${r.room_number}-xona ${b.bed_number} karavot`;
            beds.push(b);
          });
        }
      });
    });
    return beds;
  }

  function switchFloor(floorNum) {
    currentFloor = floorNum.toString();
    document.querySelectorAll('.floor-btn').forEach(btn => {
      if (btn.getAttribute('data-floor') === currentFloor) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });
    renderDashboard();
  }

  function setupEventListeners() {
    // Floor Switchers
    document.querySelectorAll('.floor-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const targetFloor = btn.getAttribute('data-floor');
        switchFloor(targetFloor);
      });
    });

    // View Switchers
    document.querySelectorAll('[data-view-target]').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('[data-view-target]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentView = btn.getAttribute('data-view-target');
        renderDashboard();
      });
    });

    // Status Filter Pills
    document.querySelectorAll('[data-filter-status]').forEach(pill => {
      pill.addEventListener('click', () => {
        document.querySelectorAll('[data-filter-status]').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        currentFilter = pill.getAttribute('data-filter-status');
        renderDashboard();
      });
    });

    // Live Search Input Listener
    const searchInput = document.getElementById('smart-search-input');
    if (searchInput) {
      searchInput.addEventListener('input', () => {
        searchQuery = searchInput.value.trim().toLowerCase();
        renderDashboard();
      });
    }

    // "Yangi Qabul" header button: admissions are registered at Reception.
    const newBookingBtn = document.getElementById('new-booking-btn');
    if (newBookingBtn) {
      newBookingBtn.title = "Qabul Qabulxonada rasmiylashtiriladi";
      newBookingBtn.addEventListener('click', goToReception);
    }

    // Modal Close
    const modalBackdrop = document.getElementById('booking-modal-backdrop');
    const modalCloseBtn = document.getElementById('modal-close-btn');
    const modalCancelBtn = document.getElementById('modal-cancel-btn');

    if (modalCloseBtn) modalCloseBtn.addEventListener('click', closeBookingModal);
    if (modalCancelBtn) modalCancelBtn.addEventListener('click', closeBookingModal);
    if (modalBackdrop) {
      modalBackdrop.addEventListener('click', e => {
        if (e.target === modalBackdrop) closeBookingModal();
      });
    }

    // The modal is a read-only view of an admission; nothing in it submits.
    // Without this, Enter in a field would reload the page.
    const bookingForm = document.getElementById('booking-form');
    if (bookingForm) {
      bookingForm.addEventListener('submit', e => e.preventDefault());
    }

    // Transfer section: the list of free beds depends on the move date.
    const transferDateInput = document.getElementById('transfer-date-input');
    if (transferDateInput) {
      transferDateInput.addEventListener('change', () => {
        const idInput = document.getElementById('booking-id-input');
        const booking = idInput ? bookings.find(b => String(b.id) === String(idInput.value)) : null;
        if (booking) updateTransferBedOptions(booking);
      });
    }
    const transferBtn = document.getElementById('btn-transfer-action');
    if (transferBtn) {
      transferBtn.addEventListener('click', transferCurrentBooking);
    }

    // Calendar / Gantt Nav
    const prevDaysBtn = document.getElementById('cal-prev-btn');
    const nextDaysBtn = document.getElementById('cal-next-btn');
    const todayCalBtn = document.getElementById('cal-today-btn');

    if (prevDaysBtn) {
      prevDaysBtn.addEventListener('click', () => {
        calendarStartDate.setDate(calendarStartDate.getDate() - 7);
        renderCalendarTimeline();
      });
    }

    if (nextDaysBtn) {
      nextDaysBtn.addEventListener('click', () => {
        calendarStartDate.setDate(calendarStartDate.getDate() + 7);
        renderCalendarTimeline();
      });
    }

    if (todayCalBtn) {
      todayCalBtn.addEventListener('click', () => {
        calendarStartDate = new Date();
        calendarStartDate.setDate(calendarStartDate.getDate() - 2);
        renderCalendarTimeline();
      });
    }

    // Cross-tab and Cross-portal live synchronizer
    window.addEventListener('storage', (e) => {
      if (e.key === STORAGE_KEY) {
        try {
          bookings = JSON.parse(e.newValue || '[]');
          sanitizeConflictedBookings();
          refreshBedStatuses();
          renderDashboard();
        } catch (err) {}
      }
    });

    window.addEventListener('fmh_bookings_updated', (e) => {
      if (e.detail && !applyingBookingUpdate) {
        applyingBookingUpdate = true;
        try {
          bookings = e.detail;
          sanitizeConflictedBookings();
          refreshBedStatuses();
          renderDashboard();
        } finally {
          applyingBookingUpdate = false;
        }
      }
    });
  }

  function renderDashboard() {
    renderStatsBanner();

    const blueprintContainer = document.getElementById('view-blueprint-container');
    const calendarContainer = document.getElementById('view-calendar-container');
    const tableContainer = document.getElementById('view-table-container');

    if (blueprintContainer) blueprintContainer.style.display = currentView === 'blueprint' ? 'block' : 'none';
    if (calendarContainer) calendarContainer.style.display = currentView === 'calendar' ? 'block' : 'none';
    if (tableContainer) tableContainer.style.display = currentView === 'table' ? 'block' : 'none';

    if (currentView === 'blueprint') {
      renderSmartPalataDashboard();
    } else if (currentView === 'calendar') {
      renderCalendarTimeline();
    } else if (currentView === 'table') {
      renderBookingsTable();
    }
  }

  function renderStatsBanner() {
    const visibleBeds = getAllBeds(currentFloor);
    const total = visibleBeds.length;
    const cleaning = visibleBeds.filter(b => b.status === 'cleaning').length;
    const available = visibleBeds.filter(b => b.status === 'available').length;
    const occupied = visibleBeds.filter(b => b.status === 'occupied').length;
    const reserved = visibleBeds.filter(b => b.status === 'reserved').length;
    const occupancyRate = total > 0 ? Math.round(((occupied + reserved) / total) * 100) : 0;

    const statTotalEl = document.getElementById('stat-total-beds');
    const statCleanEl = document.getElementById('stat-cleaning-beds');
    const statAvailEl = document.getElementById('stat-available-beds');
    const statOccEl = document.getElementById('stat-occupied-beds');
    const statResEl = document.getElementById('stat-reserved-beds');
    const statRateEl = document.getElementById('stat-occupancy-rate');

    if (statTotalEl) statTotalEl.textContent = total;
    if (statCleanEl) statCleanEl.textContent = cleaning;
    if (statAvailEl) statAvailEl.textContent = available;
    if (statOccEl) statOccEl.textContent = occupied;
    if (statResEl) statResEl.textContent = reserved;
    if (statRateEl) statRateEl.textContent = `${occupancyRate}%`;
  }

  function renderSmartPalataDashboard() {
    const cardFloor1 = document.getElementById('card-smart-floor1');
    const cardFloor2 = document.getElementById('card-smart-floor2');
    const f1Grid = document.getElementById('f1-smart-rooms-grid');
    const f2Grid = document.getElementById('f2-smart-rooms-grid');
    const f1StatsEl = document.getElementById('f1-quick-stats');
    const f2StatsEl = document.getElementById('f2-quick-stats');

    // 1. Manage Floor Visibility
    if (cardFloor1 && cardFloor2) {
      if (currentFloor === '1') {
        cardFloor1.style.display = 'block';
        cardFloor2.style.display = 'none';
      } else if (currentFloor === '2') {
        cardFloor1.style.display = 'none';
        cardFloor2.style.display = 'block';
      } else {
        cardFloor1.style.display = 'block';
        cardFloor2.style.display = 'block';
      }
    }

    // 2. Compute Quick Stats
    const f1Beds = getAllBeds('1');
    const f2Beds = getAllBeds('2');

    const computeStatsHTML = (beds) => {
      const total = beds.length;
      const clean = beds.filter(b => b.status === 'cleaning').length;
      const avail = beds.filter(b => b.status === 'available').length;
      const occ = beds.filter(b => b.status === 'occupied').length;
      const res = beds.filter(b => b.status === 'reserved').length;
      const rate = total > 0 ? Math.round(((occ + res) / total) * 100) : 0;
      return `
        <div class="floor-stat-pill"><span class="stat-pill-dot dot-avail"></span> Bo'sh: <strong>${avail}</strong></div>
        ${clean > 0 ? `<div class="floor-stat-pill" style="border-color: rgba(245, 158, 11, 0.4);"><span class="stat-pill-dot dot-clean"></span> Tozalanmoqda: <strong>${clean}</strong></div>` : ''}
        <div class="floor-stat-pill"><span class="stat-pill-dot dot-occ"></span> Band: <strong>${occ}</strong></div>
        <div class="floor-stat-pill"><span class="stat-pill-dot dot-res"></span> Bron: <strong>${res}</strong></div>
        <div class="floor-stat-pill pill-rate">Bandlik: <strong>${rate}%</strong></div>
      `;
    };

    if (f1StatsEl) f1StatsEl.innerHTML = computeStatsHTML(f1Beds);
    if (f2StatsEl) f2StatsEl.innerHTML = computeStatsHTML(f2Beds);

    // 3. Render Bed Pods
    const renderBedPodHTML = (bed) => {
      if (!bed) return '';
      let isVisible = currentFilter === 'all' || bed.status === currentFilter;

      if (isVisible && searchQuery) {
        const bedText = `${bed.simple_name} ${bed.room_number}`.toLowerCase();
        let patientText = '';
        if (bed.current_patient) {
          patientText = `${bed.current_patient.name} ${bed.current_patient.phone} ${bed.current_patient.patient_code} ${bed.current_patient.program}`.toLowerCase();
        }
        let futureText = '';
        if (bed.future_booking) {
          futureText = `${bed.future_booking.patient_name} ${bed.future_booking.patient_phone} ${bed.future_booking.patient_code}`.toLowerCase();
        }
        if (bed.future_lock) {
          futureText += ` ${esc(bed.future_lock.patient_name)}`;
        }
        const fullMatchStr = `${bedText} ${patientText} ${futureText}`;
        if (!fullMatchStr.includes(searchQuery)) {
          isVisible = false;
        }
      }

      const opacityClass = isVisible ? '' : 'is-filtered-out';

      const partnerBedId = getPartnerBedId(bed.bed_id);
      const partnerBed = partnerBedId ? getAllBeds().find(x => String(x.bed_id).toUpperCase() === String(partnerBedId).toUpperCase()) : null;

      if (bed.is_locked_by_partner && bed.locked_by_booking) {
        const pBooking = bed.locked_by_booking;
        return `
          <div class="smart-bed-pod is-locked ${opacityClass}" onclick="window.FMH_Building.openBookingModal('${pBooking.id}')">
            <div class="bed-pod-header">
              <div class="bed-pod-id"><i class="fas fa-bed"></i> ${bed.simple_name}</div>
              <span class="smart-status-badge badge-locked"><i class="fas fa-lock"></i> BUTUN XONA QULF</span>
            </div>
            <div class="bed-pod-body locked-pod-body">
              <div class="locked-icon-bubble"><i class="fas fa-user-lock"></i></div>
              <div class="locked-main-text">2-Karavot Qulflangan</div>
              <div class="locked-sub-text">Ushbu xona <strong>${esc(pBooking.patient_name)}</strong> tomonidan <em>Butun xona (Yakka)</em> rejimida band qilingan.</div>
              <div class="locked-booking-chip"><i class="fas fa-user-shield"></i> Asosiy karavot: ${partnerBed ? partnerBed.simple_name : '1-karavot'}</div>
            </div>
            <div class="bed-pod-footer" style="display: flex; gap: 4px;">
              <button class="btn-smart-action" onclick="event.stopPropagation(); window.FMH_Building.openBookingModal('${pBooking.id}')"><i class="fas fa-eye"></i> Bronni Ko'rish</button>
              <button class="btn-smart-action" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3);" onclick="event.stopPropagation(); window.FMH_Building.goToReception()" title="Qabul Qabulxonada rasmiylashtiriladi (karavot ${bed.next_free_date} dan bo'sh)"><i class="fas fa-plus-circle"></i> Keyinga Bron</button>
            </div>
          </div>
        `;
      }

      if (bed.status === 'occupied' && bed.current_patient) {
        const p = bed.current_patient;
        const b = bookings.find(x => String(x.id) === String(p.booking_id));
        const progColor = (b && b.program_color) ? b.program_color : '#38bdf8';
        const progName = (b && b.program) ? b.program : 'Statsionar rejim';
        const docName = (b && b.doctor) ? b.doctor : 'Shifokor biriktirilmagan';
        const sDate = (b && b.start_date) ? b.start_date : getTodayStr();
        const eDate = (b && b.end_date) ? b.end_date : '';
        
        let daysText = 'Davolanmoqda';
        let progressPercent = 50;
        if (sDate && eDate) {
          const d1 = new Date(sDate);
          const d2 = new Date(eDate);
          const now = new Date(getTodayStr());
          const totalDays = Math.max(1, Math.round((d2 - d1) / (1000 * 60 * 60 * 24)));
          const passedDays = Math.max(0, Math.min(totalDays, Math.round((now - d1) / (1000 * 60 * 60 * 24))));
          progressPercent = Math.min(100, Math.round((passedDays / totalDays) * 100));
          const leftDays = Math.max(0, totalDays - passedDays);
          daysText = `${leftDays} kun qoldi (${passedDays}/${totalDays} kun)`;
        }

        const initials = p.name ? p.name.split(' ').slice(0, 2).map(n => n[0]).join('') : 'BM';
        const isFR = b ? isFullRoomBooking(b) : false;

        return `
          <div class="smart-bed-pod is-occupied ${opacityClass}" onclick="window.FMH_Building.handleBedClick('${bed.bed_id}')">
            <div class="bed-pod-header">
              <div class="bed-pod-id"><i class="fas fa-bed" style="color: var(--cad-cyan);"></i> ${bed.simple_name}</div>
              <span class="smart-status-badge badge-occupied">
                <span class="pulse-status-dot"></span> BAND
                <svg class="mini-ecg-svg" viewBox="0 0 40 12" style="width: 26px; height: 10px; margin-left: 4px; vertical-align: middle;"><path d="M0,6 L8,6 L11,1 L14,11 L17,3 L20,9 L23,6 L40,6" stroke="#f43f5e" stroke-width="1.6" fill="none" class="ecg-pulse-line"/></svg>
              </span>
            </div>
            <div class="bed-pod-body occupied-pod-body">
              <div class="patient-profile-strip">
                <div class="patient-avatar-wrap" style="border-color: ${progColor};">${esc(initials)}</div>
                <div class="patient-details">
                  <div class="patient-name-line" title="${esc(p.name)}">${esc(p.name)} ${isFR ? '<i class="fas fa-user-lock" style="color: #38bdf8;" title="Butun Xona (Solo)"></i>' : ''}</div>
                  <div class="patient-sub-line">${esc(p.patient_code || 'FMH-BEMOR')} &bull; ${esc(p.phone || '+998 -- --- -- --')}</div>
                </div>
              </div>
              <div class="program-tag-line">
                <span class="program-badge" style="border-left: 3px solid ${progColor};">${esc(progName)}</span>
              </div>
              <div class="dates-period-box">
                <div class="dates-period-text"><i class="fas fa-calendar-alt"></i> ${sDate} ➔ ${eDate}</div>
                <div class="days-remaining-pill">${daysText}</div>
              </div>
              <div class="treatment-progress-track">
                <div class="treatment-progress-fill" style="width: ${progressPercent}%; background: linear-gradient(90deg, ${progColor}, #10b981);"></div>
              </div>
              <div class="doctor-badge-row">
                <i class="fas fa-user-md" style="color: var(--cad-cyan);"></i>
                <span>${esc(docName)}</span>
              </div>
            </div>
            <div class="bed-pod-footer" style="display: flex; gap: 4px;">
              <button class="btn-smart-action btn-edit" onclick="event.stopPropagation(); window.FMH_Building.openBookingModal('${p.booking_id}')" title="Ma'lumotlarni ko'rish va karavotni almashtirish"><i class="fas fa-eye"></i> Ko'rish</button>
              <button class="btn-smart-action" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3);" onclick="event.stopPropagation(); window.FMH_Building.goToReception()" title="Qabul Qabulxonada rasmiylashtiriladi (karavot ${bed.next_free_date} dan bo'sh)"><i class="fas fa-plus-circle"></i> Keyinga Bron</button>
              <button class="btn-smart-action btn-discharge" onclick="event.stopPropagation(); window.FMH_Building.dischargeCurrentPatient('${p.booking_id}')" title="Bemorni chiqarish"><i class="fas fa-sign-out-alt"></i> Chiqarish</button>
            </div>
          </div>
        `;
      }

      if (bed.status === 'reserved' && bed.current_patient) {
        const p = bed.current_patient;
        const b = bookings.find(x => String(x.id) === String(p.booking_id));
        const sDate = (b && b.start_date) ? b.start_date : '';
        const eDate = (b && b.end_date) ? b.end_date : '';
        const docName = (b && b.doctor) ? b.doctor : 'Shifokor biriktirilmagan';
        const progName = (b && b.program) ? b.program : 'Bron qilingan';
        const initials = p.name ? p.name.split(' ').slice(0, 2).map(n => n[0]).join('') : 'BR';

        return `
          <div class="smart-bed-pod is-reserved ${opacityClass}" onclick="window.FMH_Building.handleBedClick('${bed.bed_id}')">
            <div class="bed-pod-header">
              <div class="bed-pod-id"><i class="fas fa-bed" style="color: var(--status-reserved);"></i> ${bed.simple_name}</div>
              <span class="smart-status-badge badge-reserved"><i class="fas fa-clock"></i> BRON QILINGAN</span>
            </div>
            <div class="bed-pod-body reserved-pod-body">
              <div class="patient-profile-strip">
                <div class="patient-avatar-wrap" style="background: rgba(245, 158, 11, 0.15); color: #fbbf24; border-color: #f59e0b;">${esc(initials)}</div>
                <div class="patient-details">
                  <div class="patient-name-line" title="${esc(p.name)}">${esc(p.name)}</div>
                  <div class="patient-sub-line">${esc(p.patient_code || 'FMH-BRON')} &bull; ${esc(p.phone || '+998 -- --- -- --')}</div>
                </div>
              </div>
              <div class="program-tag-line">
                <span class="program-badge" style="border-left: 3px solid #f59e0b;">${esc(progName)}</span>
              </div>
              <div class="dates-period-box" style="background: rgba(245, 158, 11, 0.08); border-color: rgba(245, 158, 11, 0.25);">
                <div class="dates-period-text" style="color: #fbbf24;"><i class="fas fa-calendar-check"></i> Rejalashtirilgan kirish: ${sDate} ➔ ${eDate}</div>
              </div>
              <div class="doctor-badge-row">
                <i class="fas fa-user-md" style="color: #fbbf24;"></i>
                <span>${esc(docName)}</span>
              </div>
            </div>
            <div class="bed-pod-footer" style="display: flex; gap: 4px;">
              <button class="btn-smart-action" onclick="event.stopPropagation(); window.FMH_Building.openBookingModal('${p.booking_id}')" title="Ma'lumotlarni ko'rish va karavotni almashtirish"><i class="fas fa-eye"></i> Ko'rish</button>
              <button class="btn-smart-action" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3);" onclick="event.stopPropagation(); window.FMH_Building.goToReception()" title="Qabul Qabulxonada rasmiylashtiriladi (karavot ${bed.next_free_date} dan bo'sh)"><i class="fas fa-plus-circle"></i> Keyinga Bron</button>
            </div>
          </div>
        `;
      }

      if (bed.status === 'cleaning' || bed.physical_bed_status === 'cleaning') {
        const nextResDateInfo = bed.next_reserved_date ? `
          <div style="background: rgba(245, 158, 11, 0.12); border: 1px dashed #f59e0b; padding: 4px 8px; border-radius: 6px; font-size: 0.73rem; color: #fbbf24; margin-top: 8px;">
            <i class="fas fa-calendar-alt"></i> Kelgusi bron: <strong>${bed.next_reserved_date}</strong>
          </div>
        ` : '';

        // Same card for cleaning and repair; only the words, icon and the
        // action that returns the bed to service differ.
        const repair = !!bed.under_repair;
        const badgeHTML = repair
          ? `<i class="fas fa-tools"></i> TA'MIRDA`
          : `<i class="fas fa-broom"></i> TOZALANMOQDA`;
        const iconClass = repair ? 'fa-tools' : 'fa-hands-wash';
        const mainText = repair ? "Ta'mirlash ishlari" : 'Sanitar Dezinfeksiya';
        const subText = repair
          ? "Karavot ta'mirga yuborilgan. Ta'mir tugaguncha bemor qabul qilinmaydi."
          : "Bemor chiqarilgan / ko'chirilgan. Xona va to'shak dezinfeksiya qilinmoqda.";
        const actionHTML = repair
          ? `<button class="btn-smart-action" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); font-weight: 700; width: 100%; justify-content: center;" onclick="event.stopPropagation(); window.FMH_Building.markBedRepaired('${bed.bed_id}')">
                <i class="fas fa-check-circle"></i> Ta'mirlandi (Qabulga Ochish)
              </button>`
          : `<button class="btn-smart-action" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); font-weight: 700; width: 100%; justify-content: center;" onclick="event.stopPropagation(); window.FMH_Building.markBedClean('${bed.bed_id}')">
                <i class="fas fa-check-circle"></i> Tozalandi (Qabulga Ochish)
              </button>`;

        return `
          <div class="smart-bed-pod is-cleaning ${opacityClass}">
            <div class="bed-pod-header">
              <div class="bed-pod-id"><i class="fas fa-bed" style="color: #f59e0b;"></i> ${bed.simple_name}</div>
              <span class="smart-status-badge badge-cleaning">${badgeHTML}</span>
            </div>
            <div class="bed-pod-body" style="text-align: center; padding: 1.25rem 0.5rem; display: flex; flex-direction: column; align-items: center; justify-content: center;">
              <div style="width: 52px; height: 52px; border-radius: 50%; background: rgba(245, 158, 11, 0.15); color: #f59e0b; display: flex; align-items: center; justify-content: center; font-size: 1.5rem; margin-bottom: 0.75rem; border: 1px solid rgba(245, 158, 11, 0.35);">
                <i class="fas ${iconClass}"></i>
              </div>
              <div style="font-weight: 800; color: var(--text-primary); font-size: 0.98rem;">${mainText}</div>
              <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 4px; line-height: 1.4; max-width: 220px;">
                ${subText}
              </div>
              ${nextResDateInfo}
            </div>
            <div class="bed-pod-footer">
              ${actionHTML}
            </div>
          </div>
        `;
      }

      // Available Bed
      let futureInfoHTML = '';
      let footerButtonsHTML = `<button class="btn-smart-action btn-add-patient" onclick="event.stopPropagation(); window.FMH_Building.goToReception()" title="Qabul Qabulxonada rasmiylashtiriladi"><i class="fas fa-user-plus"></i> Bemor Qabuli</button>`;

      if (bed.future_booking) {
        const extraCount = bed.future_bookings_count > 1 ? ` (+${bed.future_bookings_count - 1} ta bron)` : '';
        futureInfoHTML = `
          <div class="future-booking-banner" style="background: rgba(245, 158, 11, 0.12); border: 1px dashed #f59e0b; padding: 4px 8px; border-radius: 6px; font-size: 0.73rem; color: #fbbf24; margin-top: 6px; line-height: 1.3;">
            <i class="fas fa-calendar-alt"></i> <strong>${bed.future_booking.start_date} gacha bo'sh</strong>
            <div style="font-size: 0.68rem; color: #94a3b8; margin-top: 2px;">Kelgusi bron: ${esc(bed.future_booking.patient_name)}${extraCount}</div>
          </div>
        `;
        footerButtonsHTML = `
          <button class="btn-smart-action btn-add-patient" onclick="event.stopPropagation(); window.FMH_Building.goToReception()" title="Qabul Qabulxonada rasmiylashtiriladi"><i class="fas fa-user-plus"></i> Bugun Qabul</button>
          <button class="btn-smart-action" style="background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3);" onclick="event.stopPropagation(); window.FMH_Building.openBookingModal('${bed.future_booking.id}')" title="Mavjud kelgusi bronni ko'rish/tahrirlash"><i class="fas fa-eye"></i> Bron (${bed.future_bookings_count})</button>
          <button class="btn-smart-action" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3);" onclick="event.stopPropagation(); window.FMH_Building.goToReception()" title="Qabul Qabulxonada rasmiylashtiriladi (karavot ${bed.next_free_date} dan bo'sh)"><i class="fas fa-plus-circle"></i> Keyinga Bron</button>
        `;
      } else if (bed.future_lock) {
        const extraLockCount = bed.future_locks_count > 1 ? ` (+${bed.future_locks_count - 1} ta bron)` : '';
        futureInfoHTML = `
          <div class="future-booking-banner" style="background: rgba(168, 85, 247, 0.12); border: 1px dashed #a855f7; padding: 4px 8px; border-radius: 6px; font-size: 0.73rem; color: #c084fc; margin-top: 6px; line-height: 1.3;">
            <i class="fas fa-lock"></i> <strong>${bed.future_lock.start_date} gacha bo'sh</strong>
            <div style="font-size: 0.68rem; color: #94a3b8; margin-top: 2px;">Kelgusi Solo: ${esc(bed.future_lock.patient_name)}${extraLockCount}</div>
          </div>
        `;
        footerButtonsHTML = `
          <button class="btn-smart-action btn-add-patient" onclick="event.stopPropagation(); window.FMH_Building.goToReception()" title="Qabul Qabulxonada rasmiylashtiriladi"><i class="fas fa-user-plus"></i> Bugun Qabul</button>
          <button class="btn-smart-action" style="background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3);" onclick="event.stopPropagation(); window.FMH_Building.openBookingModal('${bed.future_lock.id}')" title="Solo bronni ko'rish"><i class="fas fa-eye"></i> Bron (${bed.future_locks_count})</button>
          <button class="btn-smart-action" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3);" onclick="event.stopPropagation(); window.FMH_Building.goToReception()" title="Qabul Qabulxonada rasmiylashtiriladi (karavot ${bed.next_free_date} dan bo'sh)"><i class="fas fa-plus-circle"></i> Keyinga Bron</button>
        `;
      } else if (bed.next_reserved_date) {
        futureInfoHTML = `
          <div class="future-booking-banner" style="background: rgba(56, 189, 248, 0.12); border: 1px dashed #38bdf8; padding: 4px 8px; border-radius: 6px; font-size: 0.73rem; color: #38bdf8; margin-top: 6px; line-height: 1.3;">
            <i class="fas fa-calendar-alt"></i> <strong>${bed.next_reserved_date} gacha bo'sh</strong>
            <div style="font-size: 0.68rem; color: #94a3b8; margin-top: 2px;">Kelgusi bron: ${bed.next_reserved_date}</div>
          </div>
        `;
      }

      return `
        <div class="smart-bed-pod is-available ${opacityClass}" onclick="window.FMH_Building.handleBedClick('${bed.bed_id}')">
          <div class="bed-pod-header">
            <div class="bed-pod-id"><i class="fas fa-bed" style="color: var(--status-available);"></i> ${bed.simple_name}</div>
            <span class="smart-status-badge badge-available"><i class="fas fa-check-circle"></i> BO'SH</span>
          </div>
          <div class="bed-pod-body available-pod-body">
            <div class="avail-cta-orb"><i class="fas fa-plus"></i></div>
            <div class="avail-main-title">Qabulga Tayyor</div>
            <div class="avail-price-badge">${sharedRateText()}</div>
            ${futureInfoHTML}
            <div class="avail-amenities-tags" style="margin-top: 6px;">
              <span><i class="fas fa-tv"></i> Smart TV</span>
              <span><i class="fas fa-heartbeat"></i> EKG</span>
              <span><i class="fas fa-shield-virus"></i> Dezinfeksiya</span>
            </div>
          </div>
          <div class="bed-pod-footer" style="display: flex; gap: 5px;">
            ${footerButtonsHTML}
            <button class="btn-smart-action" style="background: rgba(148, 163, 184, 0.12); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.3); flex: 0 0 auto;" onclick="event.stopPropagation(); window.FMH_Building.markBedRepair('${bed.bed_id}')" title="Ta'mirga yuborish" aria-label="Ta'mirga yuborish"><i class="fas fa-tools"></i>${(bed.future_booking || bed.future_lock) ? '' : " Ta'mirga yuborish"}</button>
          </div>
        </div>
      `;
    };

    // Render Floor 1
    if (f1Grid) {
      f1Grid.innerHTML = `
        <!-- Auxiliary Medical Wing (Tibbiy Blok) -->
        <div class="smart-wing-section">
          <div class="wing-section-title"><i class="fas fa-stethoscope" style="color: var(--cad-cyan); margin-right: 8px;"></i> TIBBIY VA MA'MURIY BLOK (1-QAVAT)</div>
          <div class="smart-auxiliary-grid">
            
            <div class="smart-aux-card">
              <div class="aux-card-header">
                <div class="aux-icon" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8;"><i class="fas fa-user-md"></i></div>
                <div>
                  <div class="aux-title">1-Konsultatsiya &bull; Bosh Shifokor</div>
                  <div class="aux-sub">Bosh Narkolog & Psixiatr Kabineti</div>
                </div>
              </div>
              <div class="aux-body">
                <div class="aux-badge-status"><span class="live-dot"></span> Bemorlar Qabuli Ochiq</div>
                <div class="aux-features-list">
                  <span><i class="fas fa-check"></i> Individual Tashxis</span>
                  <span><i class="fas fa-check"></i> Dori Shkafi</span>
                  <span><i class="fas fa-check"></i> Audio / Video Maxfiylik</span>
                </div>
              </div>
            </div>

            <div class="smart-aux-card">
              <div class="aux-card-header">
                <div class="aux-icon" style="background: rgba(168, 85, 247, 0.15); color: #c084fc;"><i class="fas fa-brain"></i></div>
                <div>
                  <div class="aux-title">2-Konsultatsiya &bull; Psixoterapiya</div>
                  <div class="aux-sub">Diagnostika & Psixoterapiya Kabineti</div>
                </div>
              </div>
              <div class="aux-body">
                <div class="aux-badge-status"><span class="live-dot"></span> Faol Psixologik Seanslar</div>
                <div class="aux-features-list">
                  <span><i class="fas fa-check"></i> Kognitiv-Xulqiy Terapiya</span>
                  <span><i class="fas fa-check"></i> Klinik Kushetka</span>
                  <span><i class="fas fa-check"></i> Stress Korreksiyasi</span>
                </div>
              </div>
            </div>

            <div class="smart-aux-card">
              <div class="aux-card-header">
                <div class="aux-icon" style="background: rgba(245, 158, 11, 0.15); color: #fbbf24;"><i class="fas fa-concierge-bell"></i></div>
                <div>
                  <div class="aux-title">Qabulxona & Kutish Lounge</div>
                  <div class="aux-sub">24/7 Registratura va Kutish Zali</div>
                </div>
              </div>
              <div class="aux-body">
                <div class="aux-badge-status"><span class="live-dot"></span> 24/7 Navbatchilik</div>
                <div class="aux-features-list">
                  <span><i class="fas fa-check"></i> Resepshn Peshtaxtasi</span>
                  <span><i class="fas fa-check"></i> Mehmonlar Divani</span>
                  <span><i class="fas fa-check"></i> Ro'yxatga Olish</span>
                </div>
              </div>
            </div>

            <div class="smart-aux-card aux-card-nurse">
              <div class="aux-card-header">
                <div class="aux-icon" style="background: rgba(16, 185, 129, 0.15); color: #34d399;"><i class="fas fa-user-nurse"></i></div>
                <div>
                  <div class="aux-title">Hamshiralar Posti &bull; 24/7</div>
                  <div class="aux-sub">Shoshilinch Triage va Monitoring</div>
                </div>
              </div>
              <div class="aux-body">
                <div class="aux-badge-status" style="background: rgba(16, 185, 129, 0.15); color: #34d399; border-color: rgba(16, 185, 129, 0.3);"><span class="live-dot" style="background: #10b981;"></span> 24/7 Monitoring Faol</div>
                <div class="aux-features-list">
                  <span><i class="fas fa-check"></i> Dori Seyfi (Medicine Safe)</span>
                  <span><i class="fas fa-check"></i> Shoshilinch Chaqiruv</span>
                  <span><i class="fas fa-check"></i> Jonli Vital Triage</span>
                </div>
              </div>
            </div>

          </div>
        </div>

        <!-- Inpatient Suites Wing (11-xona & 12-xona) -->
        <div class="smart-wing-section">
          <div class="wing-section-title"><i class="fas fa-procedures" style="color: var(--cad-cyan); margin-right: 8px;"></i> STATSIONAR PALATALAR (1-QAVAT &bull; 4 TA KARAVOT)</div>
          <div class="smart-wards-deck">
            
            <!-- 11-XONA -->
            <div class="smart-room-suite-card">
              <div class="room-suite-header">
                <div class="room-header-left">
                  <span class="room-num-badge">11-XONA</span>
                  <div>
                    <div class="room-name-title">Standart Statsionar Palata</div>
                    <div class="room-amenities-strip"><i class="fas fa-shower"></i> Sanuzel &bull; <i class="fas fa-tv"></i> 55" TV &bull; <i class="fas fa-snowflake"></i> Konditsioner &bull; <i class="fas fa-wifi"></i> Wi-Fi</div>
                  </div>
                </div>
                <div class="room-rate-badge">${sharedRateText()}</div>
              </div>
              <div class="room-dual-beds-row">
                ${renderBedPodHTML(f1Beds.find(b => b.bed_id === 'BED-1A') || { simple_name: '1A Karavot', status: 'available' })}
                ${renderBedPodHTML(f1Beds.find(b => b.bed_id === 'BED-1B') || { simple_name: '1B Karavot', status: 'available' })}
              </div>
            </div>

            <!-- 12-XONA -->
            <div class="smart-room-suite-card">
              <div class="room-suite-header">
                <div class="room-header-left">
                  <span class="room-num-badge">12-XONA</span>
                  <div>
                    <div class="room-name-title">Standart Statsionar Palata</div>
                    <div class="room-amenities-strip"><i class="fas fa-shower"></i> Sanuzel &bull; <i class="fas fa-tv"></i> 55" TV &bull; <i class="fas fa-snowflake"></i> Konditsioner &bull; <i class="fas fa-wifi"></i> Wi-Fi</div>
                  </div>
                </div>
                <div class="room-rate-badge">${sharedRateText()}</div>
              </div>
              <div class="room-dual-beds-row">
                ${renderBedPodHTML(f1Beds.find(b => b.bed_id === 'BED-2A') || { simple_name: '2A Karavot', status: 'available' })}
                ${renderBedPodHTML(f1Beds.find(b => b.bed_id === 'BED-2B') || { simple_name: '2B Karavot', status: 'available' })}
              </div>
            </div>

          </div>
        </div>
      `;
    }

    // Render Floor 2
    if (f2Grid) {
      f2Grid.innerHTML = `
        <!-- Standart Palatalar (2-QAVAT) -->
        <div class="smart-wing-section">
          <div class="wing-section-title"><i class="fas fa-procedures" style="color: var(--cad-cyan); margin-right: 8px;"></i> 2-QAVAT STATSIONAR PALATALAR (21-25 XONALAR)</div>
          <div class="smart-wards-deck">
            
            <!-- 21-XONA -->
            <div class="smart-room-suite-card">
              <div class="room-suite-header">
                <div class="room-header-left">
                  <span class="room-num-badge">21-XONA</span>
                  <div>
                    <div class="room-name-title">2 O'rinli Statsionar Palata</div>
                    <div class="room-amenities-strip"><i class="fas fa-shower"></i> Sanuzel &bull; <i class="fas fa-tv"></i> Smart TV &bull; <i class="fas fa-snowflake"></i> Konditsioner &bull; <i class="fas fa-wifi"></i> Wi-Fi</div>
                  </div>
                </div>
                <div class="room-rate-badge">${sharedRateText()}</div>
              </div>
              <div class="room-dual-beds-row">
                ${renderBedPodHTML(f2Beds.find(b => b.bed_id === 'BED-21A') || { simple_name: '21A Karavot', status: 'available' })}
                ${renderBedPodHTML(f2Beds.find(b => b.bed_id === 'BED-21B') || { simple_name: '21B Karavot', status: 'available' })}
              </div>
            </div>

            <!-- 22-XONA -->
            <div class="smart-room-suite-card">
              <div class="room-suite-header">
                <div class="room-header-left">
                  <span class="room-num-badge">22-XONA</span>
                  <div>
                    <div class="room-name-title">2 O'rinli Statsionar Palata</div>
                    <div class="room-amenities-strip"><i class="fas fa-shower"></i> Sanuzel &bull; <i class="fas fa-tv"></i> Smart TV &bull; <i class="fas fa-snowflake"></i> Konditsioner &bull; <i class="fas fa-wifi"></i> Wi-Fi</div>
                  </div>
                </div>
                <div class="room-rate-badge">${sharedRateText()}</div>
              </div>
              <div class="room-dual-beds-row">
                ${renderBedPodHTML(f2Beds.find(b => b.bed_id === 'BED-22A') || { simple_name: '22A Karavot', status: 'available' })}
                ${renderBedPodHTML(f2Beds.find(b => b.bed_id === 'BED-22B') || { simple_name: '22B Karavot', status: 'available' })}
              </div>
            </div>

            <!-- 23-XONA -->
            <div class="smart-room-suite-card">
              <div class="room-suite-header">
                <div class="room-header-left">
                  <span class="room-num-badge">23-XONA</span>
                  <div>
                    <div class="room-name-title">2 O'rinli Statsionar Palata</div>
                    <div class="room-amenities-strip"><i class="fas fa-shower"></i> Sanuzel &bull; <i class="fas fa-tv"></i> Smart TV &bull; <i class="fas fa-snowflake"></i> Konditsioner &bull; <i class="fas fa-wifi"></i> Wi-Fi</div>
                  </div>
                </div>
                <div class="room-rate-badge">${sharedRateText()}</div>
              </div>
              <div class="room-dual-beds-row">
                ${renderBedPodHTML(f2Beds.find(b => b.bed_id === 'BED-23A') || { simple_name: '23A Karavot', status: 'available' })}
                ${renderBedPodHTML(f2Beds.find(b => b.bed_id === 'BED-23B') || { simple_name: '23B Karavot', status: 'available' })}
              </div>
            </div>

            <!-- 24-XONA -->
            <div class="smart-room-suite-card">
              <div class="room-suite-header">
                <div class="room-header-left">
                  <span class="room-num-badge">24-XONA</span>
                  <div>
                    <div class="room-name-title">2 O'rinli Statsionar Palata</div>
                    <div class="room-amenities-strip"><i class="fas fa-shower"></i> Sanuzel &bull; <i class="fas fa-tv"></i> Smart TV &bull; <i class="fas fa-snowflake"></i> Konditsioner &bull; <i class="fas fa-wifi"></i> Wi-Fi</div>
                  </div>
                </div>
                <div class="room-rate-badge">${sharedRateText()}</div>
              </div>
              <div class="room-dual-beds-row">
                ${renderBedPodHTML(f2Beds.find(b => b.bed_id === 'BED-24A') || { simple_name: '24A Karavot', status: 'available' })}
                ${renderBedPodHTML(f2Beds.find(b => b.bed_id === 'BED-24B') || { simple_name: '24B Karavot', status: 'available' })}
              </div>
            </div>

            <!-- 25-XONA -->
            <div class="smart-room-suite-card">
              <div class="room-suite-header">
                <div class="room-header-left">
                  <span class="room-num-badge">25-XONA</span>
                  <div>
                    <div class="room-name-title">2 O'rinli Statsionar Palata</div>
                    <div class="room-amenities-strip"><i class="fas fa-shower"></i> Sanuzel &bull; <i class="fas fa-tv"></i> Smart TV &bull; <i class="fas fa-snowflake"></i> Konditsioner &bull; <i class="fas fa-wifi"></i> Wi-Fi</div>
                  </div>
                </div>
                <div class="room-rate-badge">${sharedRateText()}</div>
              </div>
              <div class="room-dual-beds-row">
                ${renderBedPodHTML(f2Beds.find(b => b.bed_id === 'BED-25A') || { simple_name: '25A Karavot', status: 'available' })}
                ${renderBedPodHTML(f2Beds.find(b => b.bed_id === 'BED-25B') || { simple_name: '25B Karavot', status: 'available' })}
              </div>
            </div>

          </div>
        </div>

        <!-- Servis & Oshxona Bloki -->
        <div class="smart-wing-section">
          <div class="wing-section-title"><i class="fas fa-utensils" style="color: #f59e0b; margin-right: 8px;"></i> SERVIS VA TA'MINOT BO'LIMLARI (2-QAVAT)</div>
          <div class="smart-auxiliary-grid">
            
            <div class="smart-aux-card">
              <div class="aux-card-header">
                <div class="aux-icon" style="background: rgba(245, 158, 11, 0.15); color: #fbbf24;"><i class="fas fa-utensils"></i></div>
                <div>
                  <div class="aux-title">Klinik Oshxona & Parhez Taomnoma</div>
                  <div class="aux-sub">Statsionar bemorlar uchun 3 mahal parhez ovqatlanish</div>
                </div>
              </div>
              <div class="aux-body">
                <div class="aux-badge-status"><span class="live-dot"></span> 08:30 &bull; 13:00 &bull; 19:00</div>
                <div class="aux-features-list">
                  <span><i class="fas fa-check"></i> Detoks Menyusi</span>
                  <span><i class="fas fa-check"></i> Parhez Taomlar Stoli</span>
                  <span><i class="fas fa-check"></i> Muzlatgich & Cooktop</span>
                </div>
              </div>
            </div>

            <div class="smart-aux-card">
              <div class="aux-card-header">
                <div class="aux-icon" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8;"><i class="fas fa-shower"></i></div>
                <div>
                  <div class="aux-title">Sanitariya & Gigiyena Bloki</div>
                  <div class="aux-sub">2-qavat tozalik va dush xonalari</div>
                </div>
              </div>
              <div class="aux-body">
                <div class="aux-badge-status"><span class="live-dot"></span> Tozalik Standarti 100%</div>
                <div class="aux-features-list">
                  <span><i class="fas fa-check"></i> Vanna & Dush</span>
                  <span><i class="fas fa-check"></i> Muntazam Dezinfeksiya</span>
                  <span><i class="fas fa-check"></i> Issiq Suv Ta'minoti</span>
                </div>
              </div>
            </div>

            <div class="smart-aux-card">
              <div class="aux-card-header">
                <div class="aux-icon" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8;"><i class="fas fa-shoe-prints"></i></div>
                <div>
                  <div class="aux-title">Markaziy Zinapoya</div>
                  <div class="aux-sub">1-qavatga to'g'ridan-to'g'ri o'tish yo'lagi</div>
                </div>
              </div>
              <div class="aux-body">
                <div class="aux-badge-status"><span class="live-dot"></span> LED Yoritilgan Yo'lak</div>
                <div class="aux-features-list">
                  <span><i class="fas fa-check"></i> Qulay Zinapoyalar</span>
                  <span><i class="fas fa-check"></i> Xavfsizlik Tutqichlari</span>
                  <span><i class="fas fa-check"></i> Evakuatsiya Marshruti</span>
                </div>
              </div>
            </div>

          </div>
        </div>
      `;
    }
  }

  function renderCalendarTimeline() {
    const tableEl = document.getElementById('gantt-table');
    const monthTitleEl = document.getElementById('calendar-month-title');
    if (!tableEl) return;

    const dates = [];
    for (let i = 0; i < calendarDaysCount; i++) {
      const d = new Date(calendarStartDate);
      d.setDate(d.getDate() + i);
      dates.push(d);
    }

    if (monthTitleEl) {
      monthTitleEl.textContent = dates[0].toLocaleDateString('uz-UZ', { month: 'long', year: 'numeric' });
    }

    let theadHTML = `
      <thead>
        <tr>
          <th class="gantt-th-bed">Xona & Karavot</th>
          ${dates.map(d => {
            const dayNum = d.getDate();
            const weekday = d.toLocaleDateString('uz-UZ', { weekday: 'short' });
            const isToday = d.toISOString().split('T')[0] === getTodayStr();

            return `
              <th class="gantt-th-day ${isToday ? 'is-today-th' : ''}">
                <div class="gantt-weekday">${weekday}</div>
                <div class="gantt-daynum">${dayNum}</div>
              </th>
            `;
          }).join('')}
        </tr>
      </thead>
    `;

    const beds = getAllBeds(currentFloor);
    let tbodyHTML = '<tbody>';

    beds.forEach(bed => {
      tbodyHTML += `
        <tr>
          <td class="gantt-cell-bed">
            <strong class="gantt-bed-name"><i class="fas fa-bed" style="color: var(--cad-cyan); margin-right: 6px;"></i>${bed.simple_name}</strong>
          </td>
          ${dates.map(d => {
            const dateISO = d.toISOString().split('T')[0];
            const booking = bookings.find(b => 
              String(b.bed_id).toUpperCase() === String(bed.bed_id).toUpperCase() && 
              b.status !== 'cancelled' && 
              b.status !== 'completed' && 
              b.start_date <= dateISO && 
              b.end_date >= dateISO
            );

            const partnerBedId = getPartnerBedId(bed.bed_id);
            const partnerBooking = (!booking && partnerBedId) ? bookings.find(b =>
              String(b.bed_id).toUpperCase() === String(partnerBedId).toUpperCase() &&
              isFullRoomBooking(b) &&
              b.status !== 'cancelled' &&
              b.status !== 'completed' &&
              b.start_date <= dateISO &&
              b.end_date >= dateISO
            ) : null;

            let slotContent = '';
            if (booking && booking.start_date === dateISO) {
              const start = new Date(booking.start_date);
              const end = new Date(booking.end_date);
              const daysDiff = Math.max(1, Math.round((end - start) / (1000 * 60 * 60 * 24)));
              const widthPx = daysDiff * 46;

              const isFR = isFullRoomBooking(booking);
              const badge = isFR ? '<i class="fas fa-user-lock" style="color: #38bdf8; margin-right: 4px;"></i> ' : '<i class="fas fa-user-circle" style="margin-right: 4px;"></i> ';

              slotContent = `
                <div class="gantt-booking-block" style="background: ${booking.program_color || '#0284c7'}; width: ${widthPx}px;" onclick="event.stopPropagation(); window.FMH_Building.openBookingModal('${booking.id}')" title="Bosib ko'rish: ${esc(booking.patient_name)} (${esc(booking.program)})">
                  <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${badge}${esc(booking.patient_name)}</span>
                  <span class="gantt-delete-quick" onclick="event.stopPropagation(); window.FMH_Building.deleteBooking('${booking.id}')" title="Bronni o'chirish (Delete)">&times;</span>
                </div>
              `;
            } else if (partnerBooking && partnerBooking.start_date === dateISO) {
              const start = new Date(partnerBooking.start_date);
              const end = new Date(partnerBooking.end_date);
              const daysDiff = Math.max(1, Math.round((end - start) / (1000 * 60 * 60 * 24)));
              const widthPx = daysDiff * 46;

              slotContent = `
                <div class="gantt-booking-block gantt-locked-block" style="width: ${widthPx}px;" onclick="event.stopPropagation(); window.FMH_Building.openBookingModal('${partnerBooking.id}')" title="2-karavot qulflangan: ${esc(partnerBooking.patient_name)} (Butun Xona Solo)">
                  <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"><i class="fas fa-lock" style="margin-right: 4px;"></i> [Qulflangan] ${esc(partnerBooking.patient_name)}</span>
                </div>
              `;
            }

            const isSlotActive = booking || partnerBooking;

            return `
              <td class="gantt-slot ${isSlotActive ? 'is-slot-active' : ''}" onclick="window.FMH_Building.handleSlotClick('${bed.bed_id}', '${dateISO}')" title="${booking ? `Bosib ko'rish: ${esc(booking.patient_name)}` : (partnerBooking ? `2-karavot qulflangan: ${esc(partnerBooking.patient_name)}` : 'Qabul Qabulxonada rasmiylashtiriladi')}">
                ${slotContent}
              </td>
            `;
          }).join('')}
        </tr>
      `;
    });

    tbodyHTML += '</tbody>';
    tableEl.innerHTML = theadHTML + tbodyHTML;
  }

  function renderBookingsTable() {
    const tbody = document.getElementById('bookings-table-body');
    if (!tbody) return;

    const filteredBookings = currentFloor === 'all' 
      ? bookings 
      : bookings.filter(b => {
          const bed = getAllBeds().find(x => String(x.bed_id).toUpperCase() === String(b.bed_id).toUpperCase());
          return bed && bed.floor_num.toString() === currentFloor.toString();
        });

    if (filteredBookings.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 2.5rem; color: var(--text-muted);"><i class="fas fa-inbox" style="font-size: 1.5rem; display: block; margin-bottom: 0.5rem; opacity: 0.5;"></i>Hozircha hech qanday bron mavjud emas. Yangi qabul Qabulxonada rasmiylashtiriladi.</td></tr>`;
      return;
    }

    tbody.innerHTML = filteredBookings.map(b => {
      const bed = getAllBeds().find(x => String(x.bed_id).toUpperCase() === String(b.bed_id).toUpperCase());
      const bedLabel = bed ? bed.simple_name : b.bed_id;
      // Every listed stay is an active admission; it is "Bron" until its
      // first night. The pill used to be a button that flipped the status in
      // this browser only (the server never heard of it), so it is plain text.
      const isBand = !b.start_date || b.start_date <= getTodayStr();
      const isFR = isFullRoomBooking(b);
      const partnerBedId = getPartnerBedId(b.bed_id);
      const partnerBed = partnerBedId ? getAllBeds().find(x => String(x.bed_id).toUpperCase() === String(partnerBedId).toUpperCase()) : null;

      const statusBadge = isBand 
        ? `<span class="bed-status-pill pill-occupied">Band</span>`
        : `<span class="bed-status-pill pill-reserved">Bron</span>`;

      const fullRoomBadge = isFR 
        ? `<div style="font-size: 0.72rem; color: #c084fc; margin-top: 2px;"><i class="fas fa-lock"></i> 2-karavot (${partnerBed ? partnerBed.bed_number : 'sherik'}) qulflangan</div>` 
        : '';

      return `
        <tr>
          <td><strong style="color: var(--cad-cyan);">${b.patient_code || b.id}</strong></td>
          <td><strong style="color: var(--text-primary);">${esc(b.patient_name)}</strong><div style="font-size: 0.72rem; color: var(--text-muted);">${esc(b.patient_phone)}</div></td>
          <td><strong style="color: var(--text-primary);"><i class="fas fa-bed" style="color: var(--cad-cyan); margin-right: 4px;"></i>${bedLabel}</strong>${fullRoomBadge}</td>
          <td><span style="border-left: 3px solid ${b.program_color || '#38bdf8'}; padding-left: 6px; color: var(--text-primary);">${esc(b.program)}</span></td>
          <td style="color: var(--text-primary);">${b.start_date} ➔ ${b.end_date}</td>
          <td style="color: var(--text-primary);">${esc(b.doctor)}</td>
          <td>${statusBadge}</td>
          <td>
            <div style="display: flex; gap: 4px; align-items: center;">
              <button class="btn-portal btn-outline-portal" style="padding: 4px 10px; font-size: 0.76rem;" onclick="window.FMH_Building.openBookingModal('${b.id}')" title="Ma'lumotlarni ko'rish va karavotni almashtirish">
                <i class="fas fa-eye"></i> Ko'rish
              </button>
              <button class="btn-portal" style="padding: 4px 10px; font-size: 0.76rem; background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.35);" onclick="window.FMH_Building.deleteBooking('${b.id}')" title="Bronni butunlay o'chirish">
                <i class="fas fa-trash-alt"></i> O'chirish
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');
  }

  function handleBedClick(bedId) {
    const todayStr = getTodayStr();
    const bedIdClean = String(bedId).toUpperCase();
    const activeBooking = bookings.find(b => 
      String(b.bed_id).toUpperCase() === bedIdClean && 
      b.status !== 'cancelled' && 
      b.status !== 'completed' && 
      (b.status === 'active' || (b.start_date <= todayStr && b.end_date >= todayStr))
    );

    const partnerBedId = getPartnerBedId(bedId);
    const partnerActiveFullRoom = (!activeBooking && partnerBedId) ? bookings.find(b =>
      String(b.bed_id).toUpperCase() === String(partnerBedId).toUpperCase() &&
      isFullRoomBooking(b) &&
      b.status !== 'cancelled' &&
      b.status !== 'completed' &&
      (b.status === 'active' || (b.start_date <= todayStr && b.end_date >= todayStr))
    ) : null;

    if (activeBooking) {
      openBookingModal(activeBooking.id);
    } else if (partnerActiveFullRoom) {
      showToast(`🔒 Ushbu karavot <strong>${esc(partnerActiveFullRoom.patient_name)}</strong> tomonidan "Butun Xona (Solo)" sifatida to'liq band qilingan.`, 'info');
      openBookingModal(partnerActiveFullRoom.id);
    } else {
      goToReception();
    }
  }

  function handleSlotClick(bedId, dateStr) {
    const bedIdClean = String(bedId).toUpperCase();
    const existingBooking = bookings.find(b => 
      String(b.bed_id).toUpperCase() === bedIdClean && 
      b.status !== 'cancelled' && 
      b.status !== 'completed' && 
      b.start_date <= dateStr && 
      b.end_date >= dateStr
    );

    const partnerBedId = getPartnerBedId(bedId);
    const partnerBooking = (!existingBooking && partnerBedId) ? bookings.find(b =>
      String(b.bed_id).toUpperCase() === String(partnerBedId).toUpperCase() &&
      isFullRoomBooking(b) &&
      b.status !== 'cancelled' &&
      b.status !== 'completed' &&
      b.start_date <= dateStr &&
      b.end_date >= dateStr
    ) : null;

    if (existingBooking) {
      openBookingModal(existingBooking.id);
    } else if (partnerBooking) {
      showToast(`🔒 Ushbu xona <strong>${esc(partnerBooking.patient_name)}</strong> tomonidan "Butun Xona (Solo)" sifatida to'liq band qilingan.`, 'info');
      openBookingModal(partnerBooking.id);
    } else {
      goToReception();
    }
  }

  // The board never had its own formatter: the discharge dialog called an
  // undefined formatMoney(), threw a ReferenceError while building its text,
  // and so "Chiqarish" silently did nothing on this page.
  // The free-bed price follows the one price list (it was typed into the
  // cards as 720 000 and stayed there whatever the editor said).
  function sharedRateText() {
    const r = window.FMH_Pricing ? window.FMH_Pricing.rate('statsionar_shared') : 0;
    return r > 0 ? formatMoney(r) + ' / kun' : '—';
  }

  function formatMoney(amount) {
    const n = Number(amount);
    if (!isFinite(n)) return '—';
    return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + " so'm";
  }

  function bedLabel(bedId) {
    const bed = getAllBeds().find(x => String(x.bed_id).toUpperCase() === String(bedId).toUpperCase());
    return bed ? bed.simple_name : String(bedId || '');
  }

  // A bed whose physical state is not 'operational' cannot take a patient;
  // the server refuses it (transfer_patient_bed), so it is not offered.
  function isBedPhysicallyUsable(bed) {
    const live = liveBedsData.find(lb =>
      String(lb.bed_id).toUpperCase() === String(bed.bed_id).toUpperCase() ||
      String(lb.bed_code).toUpperCase() === String(bed.bed_id).toUpperCase()
    );
    const phys = live ? (live.physical_bed_status || live.status) : (bed.physical_bed_status || 'operational');
    return !phys || phys === 'operational' || phys === 'available' || phys === 'occupied' || phys === 'reserved';
  }

  // Destination beds for "Karavotni almashtirish": only beds free from the
  // move date to the end of the stay, by the same two rules the server
  // applies (find_booking_conflict): the bed itself is free, and no
  // whole-room stay holds its room-mate (or, when this stay is whole-room,
  // the room-mate is empty too). The server re-checks all of it.
  function updateTransferBedOptions(booking) {
    const select = document.getElementById('transfer-bed-select');
    const dateInput = document.getElementById('transfer-date-input');
    const btn = document.getElementById('btn-transfer-action');
    if (!select || !booking) return;

    const fromDate = (dateInput && dateInput.value) ? dateInput.value : getTodayStr();
    const toDate = booking.end_date > fromDate ? booking.end_date : getOffsetDateStr(1);
    const movingIsFullRoom = isFullRoomBooking(booking);
    const others = bookings.filter(b =>
      String(b.id) !== String(booking.id) &&
      b.status !== 'cancelled' && b.status !== 'completed' &&
      datesOverlap(fromDate, toDate, b.start_date, b.end_date)
    );

    let optionsHTML = '';
    getAllBeds().forEach(bed => {
      const bedIdClean = String(bed.bed_id).toUpperCase();
      if (bedIdClean === String(booking.bed_id).toUpperCase()) return;
      if (!isBedPhysicallyUsable(bed)) return;

      const partnerId = getPartnerBedId(bed.bed_id);
      const partnerClean = partnerId ? String(partnerId).toUpperCase() : null;
      const directClash = others.some(b => String(b.bed_id).toUpperCase() === bedIdClean);
      const partnerClash = partnerClean ? others.some(b =>
        String(b.bed_id).toUpperCase() === partnerClean && (movingIsFullRoom || isFullRoomBooking(b))
      ) : false;
      if (directClash || partnerClash) return;

      optionsHTML += `<option value="${esc(bed.bed_id)}">${esc(bed.simple_name)}</option>`;
    });

    if (optionsHTML) {
      select.innerHTML = `<option value="">— Yangi karavotni tanlang —</option>` + optionsHTML;
      select.disabled = false;
      if (btn) btn.disabled = false;
    } else {
      select.innerHTML = `<option value="">Bu sanalarda bo'sh karavot yo'q</option>`;
      select.disabled = true;
      if (btn) btn.disabled = true;
    }
  }

  // Read-only view of an existing admission. It used to be an edit form whose
  // changes lived only in this browser and were wiped by the next refresh;
  // admission details are changed at Reception, and the only change made
  // here is a real, server-side bed transfer.
  function openBookingModal(bookingId = null) {
    const modalBackdrop = document.getElementById('booking-modal-backdrop');
    if (!modalBackdrop) return;

    const booking = bookingId ? bookings.find(b => String(b.id) === String(bookingId)) : null;
    if (!booking) {
      goToReception();
      return;
    }

    const form = document.getElementById('booking-form');
    if (form) form.reset();

    const setVal = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.value = (value === null || value === undefined) ? '' : value;
    };

    const modalTitleEl = document.getElementById('modal-title-text');
    if (modalTitleEl) modalTitleEl.innerHTML = '<i class="fas fa-procedures" style="color: #38bdf8;"></i> Yotqizish Ma\'lumotlari';

    setVal('booking-id-input', booking.id);
    setVal('booking-patient-name', booking.patient_name || '');
    setVal('booking-patient-phone', booking.patient_phone || '—');
    setVal('booking-patient-code', booking.patient_code || '');
    setVal('booking-bed-current', bedLabel(booking.bed_id));
    setVal('booking-program-view', PROGRAM_NAMES[booking.program] || booking.program || '');
    setVal('booking-rate-view', booking.daily_rate === null || booking.daily_rate === undefined ? '—' : formatMoney(booking.daily_rate) + ' / kun');
    setVal('booking-doctor-view', booking.doctor || '');
    setVal('booking-start-date', booking.start_date || '');
    setVal('booking-end-date', booking.end_date || '');
    setVal('booking-notes', booking.notes || '');

    // Transfer defaults: today in local time (toISOString is UTC and gave
    // yesterday's date before 05:00 in Tashkent), but never before arrival.
    const today = getTodayStr();
    const minDate = booking.start_date && booking.start_date > today ? booking.start_date : today;
    const dateInput = document.getElementById('transfer-date-input');
    if (dateInput) {
      dateInput.value = minDate;
      if (booking.start_date) dateInput.min = booking.start_date;
      if (booking.end_date) {
        const lastNight = new Date(booking.end_date + 'T00:00:00');
        lastNight.setDate(lastNight.getDate() - 1);
        const y = lastNight.getFullYear();
        const m = String(lastNight.getMonth() + 1).padStart(2, '0');
        const d = String(lastNight.getDate()).padStart(2, '0');
        dateInput.max = `${y}-${m}-${d}`;
      }
    }
    setVal('transfer-reason-input', '');
    updateTransferBedOptions(booking);

    const dischargeBtn = document.getElementById('btn-discharge-action');
    const deleteBtn = document.getElementById('btn-delete-booking-action');
    if (dischargeBtn) dischargeBtn.style.display = 'inline-flex';
    if (deleteBtn) deleteBtn.style.display = 'inline-flex';

    modalBackdrop.classList.add('active');
  }

  function closeBookingModal() {
    const modalBackdrop = document.getElementById('booking-modal-backdrop');
    if (modalBackdrop) modalBackdrop.classList.remove('active');
  }

  // POST /api/admissions/<id>/transfer. The server moves the stay, splits the
  // invoice line at the move date, keeps the agreed daily price and sends the
  // old bed to cleaning. The board changes only after the server agrees; on a
  // refusal the modal stays open with the server's reason.
  async function transferCurrentBooking() {
    const idInput = document.getElementById('booking-id-input');
    const bookingId = idInput ? String(idInput.value || '').trim() : '';
    const booking = bookings.find(b => String(b.id) === bookingId);
    if (!booking) {
      showToast("Yotqizish topilmadi. Sahifani yangilang.", 'warning');
      return;
    }

    const select = document.getElementById('transfer-bed-select');
    const dateInput = document.getElementById('transfer-date-input');
    const reasonInput = document.getElementById('transfer-reason-input');
    const newBedId = select ? select.value : '';
    const transferDate = dateInput ? dateInput.value : '';
    const reason = reasonInput ? reasonInput.value.trim() : '';

    if (!newBedId) {
      showToast("Yangi karavotni tanlang.", 'warning');
      return;
    }
    if (!transferDate) {
      showToast("Ko'chirish sanasini kiriting.", 'warning');
      return;
    }

    const ok = await fmhConfirm({
      title: "Karavotni Almashtirish",
      message: `<strong>${esc(booking.patient_name)}</strong>: ${esc(bedLabel(booking.bed_id))} ➔ <strong>${esc(bedLabel(newBedId))}</strong>, ${esc(transferDate)} sanasidan.<br>Avvalgi karavot tozalashga yuboriladi. Kunlik narx o'zgarmaydi.`,
      confirmText: "Ko'chirish",
      cancelText: "Bekor Qilish",
      type: 'primary'
    });
    if (!ok) return;

    const btn = document.getElementById('btn-transfer-action');
    if (btn) btn.disabled = true;
    try {
      const res = await fetch('/api/admissions/' + encodeURIComponent(booking.id) + '/transfer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_bed_id: newBedId, transfer_date: transferDate, reason: reason })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showToast(`❌ ${esc(data.error || "Karavotni almashtirib bo'lmadi.")}`, 'danger');
        return;
      }
    } catch (e) {
      showToast("Server bilan aloqa yo'q. Bemor ko'chirilmadi.", 'danger');
      return;
    } finally {
      if (btn) btn.disabled = false;
    }

    closeBookingModal();
    await fetchLiveBedsAndAdmissions();
    refreshBedStatuses();
    renderDashboard();
    showToast(`✅ <strong>${esc(booking.patient_name)}</strong> ${esc(bedLabel(newBedId))} karavotiga ko'chirildi. Avvalgi karavot tozalashga yuborildi.`);
  }

  // FMH_ConfirmDialog now lives in js/fmh_dialogs.js so every portal shares one
  // implementation (it used to be defined here, which is why the Doctor page had
  // no confirmation dialog at all). Styles remain in css/unified_header.css.

  // The bed-card button passes its own booking id. Reading the hidden modal
  // input instead discharged whichever patient was opened in the modal last,
  // because form.reset() never clears hidden inputs.
  function dischargeCurrentPatient(targetBookingId) {
    const bookingId = String(targetBookingId || document.getElementById('booking-id-input').value || '').trim();
    if (!bookingId) return;

    const booking = bookings.find(b => String(b.id) === String(bookingId));
    if (!booking) return;

    const pName = booking.patient_name || "Bemor";
    const today = getTodayStr();
    const startDate = booking.start_date || today;

    let actualDays = 1;
    try {
      const dStart = new Date(startDate);
      const dEnd = new Date(today);
      const diffTime = dEnd - dStart;
      actualDays = Math.max(1, Math.ceil(diffTime / (1000 * 60 * 60 * 24)));
    } catch(e) {
      actualDays = 1;
    }

    // The stay's own stored rate is what billing uses; guessing it from the
    // programme text showed day-care stays at 720 000 instead of 630 000.
    const _rate = id => (window.FMH_Pricing ? window.FMH_Pricing.rate(id) : 0);
    const dailyPrice = Number(booking.daily_rate) || ((booking.program && (booking.program.includes("1.1 mln") || booking.is_full_room)) ? _rate('statsionar_full_room') : (booking.program && booking.program.includes("630 ming") ? _rate('kunlik_statsionar') : _rate('statsionar_shared')));
    const calculatedTotal = actualDays * dailyPrice;

    window.FMH_ConfirmDialog({
      title: "Bemorni Statsionardan Chiqarish",
      message: `
        <div style="font-size: 0.9rem; line-height: 1.5;">
          <strong>${pName}</strong> muolajasi yakunlanib hisobdan chiqarilmoqda.<br>
          <div style="margin: 10px 0; padding: 10px; background: rgba(56, 189, 248, 0.1); border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 8px;">
            <div>📅 <strong>Yotgan davri:</strong> ${startDate} — ${today} (<strong>${actualDays} kun</strong>)</div>
            <div>💰 <strong>Hisoblangan summa:</strong> ${actualDays} kun × ${formatMoney(dailyPrice)} = <strong style="color: #38bdf8;">${formatMoney(calculatedTotal)}</strong></div>
            <div style="font-size: 0.76rem; color: #94a3b8; margin-top: 4px;">* Dastlabki 10 kun o'rniga haqiqiy yotgan <strong>${actualDays} kun</strong> bo'yicha to'liq hisob-kitob qilinadi.</div>
          </div>
          Karavot bo'shatilsinmi va barcha moliya/buxgalteriya ko'rsatkichlari yakunlansinmi?
        </div>
      `,
      confirmText: `Chiqarish (${actualDays} kunlik hisob)`,
      cancelText: "Ortga",
      type: "info",
      onConfirm: async () => {
        // Only mark the stay discharged once the server agrees; before, a
        // refused discharge still freed the bed on screen and showed success.
        try {
          const res = await fetch('/api/admissions/' + encodeURIComponent(booking.id) + '/discharge', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              discharge_date: today,
              actual_days: actualDays,
              discharge_summary: `Bemor ${actualDays} kunlik statsionar muolajadan so'ng chiqarildi.`
            })
          });
          if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            showToast(err.error || "Bemorni chiqarib bo'lmadi. Qayta urinib ko'ring.", 'danger');
            return;
          }
        } catch (e) {
          showToast("Server bilan aloqa yo'q. Bemor chiqarilmadi.", 'danger');
          return;
        }

        booking.status = 'completed';
        booking.end_date = today;
        booking.total_days = actualDays;
        saveBookings();
        refreshBedStatuses();
        closeBookingModal();
        renderDashboard();
        showToast(`🏥 <strong>${pName}</strong> ${actualDays} kunlik hisob-kitob bilan statsionardan chiqarildi!`, 'info');
      }
    });
  }

  function deleteBooking(bookingId) {
    if (!bookingId) return;
    const booking = bookings.find(b => String(b.id) === String(bookingId));
    const pName = booking ? booking.patient_name : "ushbu bemor";

    // Only the stay (admission + its invoice) is removed here. This page used
    // to also DELETE /api/patients/<name>, and the server matches full_name,
    // so every patient sharing that name lost all their records. Removing a
    // patient belongs to the CRM, which deletes by id.
    window.FMH_ConfirmDialog({
      title: "Qabulni O'chirish",
      message: `Haqiqatan ham <strong>${pName}</strong> uchun qilingan qabulni (karavot bandligi va hisob-fakturasi) o'chirmoqchimisiz? Bemor kartasi CRMda qoladi.`,
      confirmText: "O'chirish (Enter ↵)",
      cancelText: "Bekor Qilish",
      type: "danger",
      onConfirm: async () => {
        try {
          const res = await fetch('/api/admissions/' + encodeURIComponent(bookingId), { method: 'DELETE' });
          if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            showToast(err.error || "Qabulni o'chirib bo'lmadi.", 'danger');
            return;
          }
        } catch (e) {
          showToast("Server bilan aloqa yo'q. Qabul o'chirilmadi.", 'danger');
          return;
        }

        bookings = bookings.filter(b => String(b.id) !== String(bookingId));
        saveBookings();
        refreshBedStatuses();
        closeBookingModal();
        renderDashboard();
        showToast(`🗑️ <strong>${pName}</strong> qabuli o'chirildi.`, 'danger');
      }
    });
  }

  function deleteCurrentBooking() {
    const bookingId = document.getElementById('booking-id-input').value.trim();
    deleteBooking(bookingId);
  }

  function exportBedsToExcel() {
    if (!window.XLSX) {
      window.FMH_Toast("Excel kutubxonasi yuklanmoqda...", 'info');
      return;
    }

    const rows = bookings.map((b, index) => {
      const isFR = isFullRoomBooking(b);
      return {
        "№": index + 1,
        "Bemor ID": b.id,
        "Bemor F.I.Sh.": b.patient_name,
        "Telefon": b.patient_phone || '',
        "Klinik Kod": b.patient_code || '',
        "Qavat": b.floor || (b.bed_id && b.bed_id.includes('2') ? 2 : 1),
        "Karavot": b.bed_id,
        "Xizmat / Dastur": b.program,
        "Butun Xona (Solo)": isFR ? "HA (2-karavot qulflangan)" : "Yo'q",
        "Mas'ul Shifokor": b.doctor,
        "Kirish Sanasi": b.start_date,
        "Chiqish Sanasi": b.end_date,
        "Holati": b.status === 'active' ? "Band (Faol)" : (b.status === 'confirmed' ? "Bron qilingan" : b.status),
        "Tibbiy Izoh": b.notes || ''
      };
    });

    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "14 Karavot Boshqaruvi");

    const fileName = `FMH_Statsionar_Karavotlar_Hisoboti_${new Date().toISOString().split('T')[0]}.xlsx`;
    XLSX.writeFile(wb, fileName);
    showToast(`📗 <strong>${fileName}</strong> muvaffaqiyatli yuklab olindi!`);
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
    document.body.className = `building-portal ${theme}-mode`;
    localStorage.setItem('fmh_theme', theme);

    const btn = document.getElementById('building-theme-toggle');
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

  async function markBedClean(bedId) {
    const cleanId = String(bedId).trim();
    const okClean = await fmhConfirm({
      title: "Sanitar Tozalash Yakuni",
      message: `<strong>${cleanId}</strong> karavotida dezinfeksiya va sanitar tozalash to'liq yakunlandimi?<br>Karavot qabulga ochiladi.`,
      confirmText: "Tasdiqlash",
      cancelText: "Bekor Qilish",
      type: 'primary'
    });
    if (!okClean) return;

    try {
      const res = await fetch(`/api/beds/${encodeURIComponent(cleanId)}/clean`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'operational' })
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`✅ <strong>${cleanId}</strong> dezinfeksiya qilindi va qabulga ochildi!`, 'success');
        await fetchLiveBedsAndAdmissions();
        refreshBedStatuses();
        renderDashboard();
      } else {
        showToast(`❌ Xatolik: ${data.error || 'Karavot holatini o\'zgartirib bo\'lmadi'}`, 'danger');
      }
    } catch (e) {
      showToast(`❌ Tarmoq xatosi: ${e.message}`, 'danger');
    }
  }

  // Send a free bed to repair / return it to service. Same pattern as
  // markBedClean: confirm, POST the physical status, change the board only
  // after the server agrees. Before this a broken bed could not be taken out
  // of service from the board, and one already in 'maintenance' showed as free.
  async function setBedPhysicalStatus(bedId, status, dialog, successText) {
    const cleanId = String(bedId).trim();
    const ok = await fmhConfirm(dialog);
    if (!ok) return;

    try {
      const res = await fetch(`/api/beds/${encodeURIComponent(cleanId)}/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: status })
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        showToast(successText, 'success');
        await fetchLiveBedsAndAdmissions();
        refreshBedStatuses();
        renderDashboard();
      } else {
        showToast(`❌ Xatolik: ${esc(data.error || 'Karavot holatini o\'zgartirib bo\'lmadi')}`, 'danger');
      }
    } catch (e) {
      showToast("❌ Server bilan aloqa yo'q. Karavot holati o'zgarmadi.", 'danger');
    }
  }

  function markBedRepair(bedId) {
    const label = esc(bedLabel(bedId));
    return setBedPhysicalStatus(bedId, 'maintenance', {
      title: "Ta'mirga Yuborish",
      message: `<strong>${label}</strong> ta'mirga yuborilsinmi?<br>Ta'mir tugaguncha bu karavotga bemor qabul qilinmaydi.`,
      confirmText: "Ta'mirga yuborish",
      cancelText: "Bekor Qilish",
      type: 'primary'
    }, `🔧 <strong>${label}</strong> ta'mirga yuborildi.`);
  }

  function markBedRepaired(bedId) {
    const label = esc(bedLabel(bedId));
    return setBedPhysicalStatus(bedId, 'operational', {
      title: "Ta'mir Yakuni",
      message: `<strong>${label}</strong> ta'mirlandimi?<br>Karavot qabulga ochiladi.`,
      confirmText: "Tasdiqlash",
      cancelText: "Bekor Qilish",
      type: 'primary'
    }, `✅ <strong>${label}</strong> ta'mirlandi va qabulga ochildi!`);
  }

  window.FMH_Building = {
    switchFloor,
    applyTheme,
    toggleTheme,
    handleBedClick,
    handleSlotClick,
    openBookingModal,
    closeBookingModal,
    dischargeCurrentPatient,
    markBedClean,
    deleteBooking,
    deleteCurrentBooking,
    goToReception,
    transferCurrentBooking,
    markBedRepair,
    markBedRepaired,
    exportBedsToExcel
  };

  document.addEventListener('DOMContentLoaded', () => {
    const saved = localStorage.getItem('fmh_theme') || 'night';
    applyTheme(saved);
    init();
  });
})();
