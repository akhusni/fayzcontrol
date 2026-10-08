/**
 * Fayz Medical House - Unified Superpage Master Engine (10-Department Complete HIS)
 * 100% Functional, Reactive, Persistent, Dual-Theme (Day/Night) & Interactive
 */

(function () {
  'use strict';

  // State & RBAC
  let activeDepartment = 'executive';
  // Who is signed in, and what they may see, come from the server -- not from
  // localStorage.
  //
  // This used to read fmh_active_role out of localStorage and default it to
  // 'superadmin', then invent a superadmin user object when none was stored.
  // So a fresh browser opened the full administrative shell, and anyone could
  // set that key to any role and be shown departments their job has no rights
  // to. The data was never at risk -- permissions.py refuses every call
  // regardless -- but the page showed sections that then answered 403 to
  // everything inside them, which reads as a broken system rather than a
  // forbidden one.
  //
  // loadSession() replaces both from /api/auth/session before anything renders.
  let currentRole = null;
  let currentUser = null;
  let serverRole = null;      // the real one, for deciding what may be previewed
  let previewRole = null;     // an administrator looking at another role's layout

  async function loadSession() {
    try {
      const res = await fetch('/api/auth/session');
      const s = await res.json();
      if (s && s.authenticated && s.user) {
        currentUser = s.user;
        serverRole = s.user.role || null;
        currentRole = serverRole;
        return;
      }
    } catch (e) {
      console.error('[superpage] could not read the session:', e);
    }
    // The 401 wrapper in fmh_dialogs.js sends an unauthenticated visitor to
    // the login screen; until then show nothing rather than an admin shell.
    currentUser = null;
    currentRole = null;
  }

  const ROLE_CONFIG = {
    superadmin: {
      name: 'Superadmin',
      pill: 'Superadmin (Mutlaq)',
      avatar: '👑',
      allowedDepartments: ['executive', 'facility', 'accounting', 'pharmacy', 'reception', 'doctors', 'nursery', 'kitchen', 'hr', 'crm'],
      canAccessAll: true
    },
    doctor: {
      name: 'Shifokor-Narkolog',
      pill: 'Shifokor',
      avatar: '👨‍⚕️',
      allowedDepartments: ['doctors', 'facility', 'nursery', 'pharmacy', 'reception', 'crm'],
      canAccessAll: false
    },
    nurse: {
      name: 'Navbatchi Hamshira',
      pill: 'Hamshira',
      avatar: '👩‍⚕️',
      allowedDepartments: ['nursery', 'facility', 'pharmacy', 'kitchen'],
      canAccessAll: false
    },
    accountant: {
      name: 'Buxgalter / Kassir',
      pill: 'Buxgalter',
      avatar: '💳',
      allowedDepartments: ['accounting', 'executive', 'reception', 'facility'],
      canAccessAll: false
    },
    reception: {
      name: "Qabulxona Ma'muri",
      pill: 'Qabulxona',
      avatar: '📋',
      allowedDepartments: ['reception', 'facility', 'doctors', 'crm'],
      canAccessAll: false
    }
  };

  // Dynamic Pricing Configuration
  // Filled from the one price list (js/fmh_pricing.js) by loadPricingConfig.
  // This page used to start from its own hardcoded copy, whose extra
  // services did not even match the server's (plasmapheresis 650 000 here,
  // 450 000 in the file), and a save made while the server was unreachable
  // said "saved locally" although nothing was saved anywhere.
  let pricingConfig = window.FMH_Pricing ? window.FMH_Pricing.get()
                                         : { packages: {}, additional_services: [] };

  let clinicRoomsData = null;
  let pharmacologyData = null;
  let bookings = [];
  let transactions = [];
  let vitalsLogs = [];
  let staffRoster = [];
  let dietaryDeliveries = {};
  let currentFacilityFloor = 'all';
  let currentFacilityView = 'cards';
  let currentTheme = localStorage.getItem('fmh_theme') || 'night';

  const STORAGE_KEYS = {
    THEME: 'fmh_theme',
    BEDS: 'FMH_FACILITY_14BEDS_STORAGE_V18',
    ACCOUNTING: 'FMH_ACCOUNTING_STORAGE_V6',
    VITALS: 'FMH_VITALS_STORAGE_V1',
    STAFF: 'FMH_STAFF_STORAGE_V1',
    DIET: 'FMH_DIET_STORAGE_V1'
  };

  const PARTNER_BEDS = {
    "BED-1A": "BED-1B", "BED-1B": "BED-1A",
    "BED-2A": "BED-2B", "BED-2B": "BED-2A",
    "BED-21A": "BED-21B", "BED-21B": "BED-21A",
    "BED-22A": "BED-22B", "BED-22B": "BED-22A",
    "BED-23A": "BED-23B", "BED-23B": "BED-23A",
    "BED-24A": "BED-24B", "BED-24B": "BED-24A",
    "BED-25A": "BED-25B", "BED-25B": "BED-25A"
  };

  // Toast Notification
  // Delegates to the shared toast in js/fmh_dialogs.js: that one announces
  // messages via aria-live, keeps errors on screen long enough to read,
  // stacks instead of erasing an unread message, and can be dismissed.
  function showToast(message, type = 'success') {
    return window.FMH_Toast(message, type);
  }

  function formatUZS(amount) {
    return new Intl.NumberFormat('uz-UZ').format(amount) + " so'm";
  }

  // =========================================================================
  // DYNAMIC PRICING ENGINE & RBAC HELPERS
  // =========================================================================
  async function loadPricingConfig() {
    if (!window.FMH_Pricing) return;
    await window.FMH_Pricing.ready;
    pricingConfig = window.FMH_Pricing.get();
  }

  function listedRate(id) {
    const pk = (pricingConfig && pricingConfig.packages) || {};
    return (pk[id] && Number(pk[id].daily_rate)) || 0;
  }

  function getDailyRateForProgram(program, defaultRate) {
    const fallback = Number(defaultRate) || listedRate('statsionar_shared');
    if (!pricingConfig || !pricingConfig.packages) return fallback;
    if (!program) return listedRate('statsionar_shared') || fallback;
    // A stay booked from the desk carries the package id itself
    // ('statsionar_full_room', 'kunlik_statsionar', 'ambulator_2'); the text
    // guesses below matched none of them, so those stays were costed at the
    // shared rate.
    if (pricingConfig.packages[program] && program !== 'consultation') {
      return listedRate(program);
    }
    const p = program.toLowerCase();
    if (p.includes('vip') || p.includes('butun xona') || p.includes('solo') || p.includes('1.1') || p.includes('1100000')) {
      return listedRate('statsionar_full_room');
    }
    if (p.includes('kunduzgi') || p.includes('daycare') || p.includes('630')) {
      return listedRate('kunlik_statsionar');
    }
    if (p.includes('ambulator') && (p.includes('2 mahal') || p.includes('500'))) {
      return listedRate('ambulator_2');
    }
    if (p.includes('ambulator') || p.includes('310')) {
      return listedRate('ambulator_1');
    }
    return listedRate('statsionar_shared') || fallback;
  }

  function updateHeaderUserWidget() {
    const cfg = ROLE_CONFIG[currentRole] || ROLE_CONFIG.superadmin;
    const avatarEl = document.getElementById('current-user-avatar');
    const nameEl = document.getElementById('current-user-name');
    const pillEl = document.getElementById('current-user-role-pill');
    const superBtn = document.getElementById('btn-superadmin-control');

    if (avatarEl) avatarEl.textContent = cfg.avatar;
    if (nameEl) nameEl.textContent = (currentUser && currentUser.full_name) ? currentUser.full_name : cfg.name;
    if (pillEl) pillEl.textContent = cfg.pill;

    if (superBtn) {
      if (currentRole === 'superadmin') {
        superBtn.style.display = 'inline-flex';
      } else {
        superBtn.style.display = 'none';
      }
    }

    enforceRolePermissions();
  }

  function enforceRolePermissions() {
    const cfg = ROLE_CONFIG[currentRole] || ROLE_CONFIG.superadmin;
    const allowed = cfg.allowedDepartments;

    document.querySelectorAll('.super-nav-item').forEach(item => {
      const dept = item.getAttribute('data-dept-target');
      if (!dept) return;

      if (cfg.canAccessAll || allowed.includes(dept)) {
        item.style.opacity = '1';
        item.style.pointerEvents = 'auto';
        item.removeAttribute('data-disabled');
      } else {
        item.style.opacity = '0.35';
        item.style.pointerEvents = 'none';
        item.setAttribute('data-disabled', 'true');
      }
    });

    if (!cfg.canAccessAll && !allowed.includes(activeDepartment)) {
      const fallback = allowed[0] || 'facility';
      switchDepartment(fallback);
    }
  }

  function openRoleSwitcherModal() {
    const modal = document.getElementById('super-role-switcher-modal');
    if (modal) modal.classList.add('active');
  }

  function switchRole(roleKey) {
    if (!ROLE_CONFIG[roleKey]) return;
    // Previewing another role is an administrator's tool, so it is gated on
    // the role the SERVER reports, not on the one currently displayed --
    // otherwise one switch into 'superadmin' unlocked every other switch.
    // It changes only what this page draws; every request still carries the
    // real account and is answered on that basis.
    if (serverRole !== 'superadmin' && serverRole !== 'admin') {
      showToast("⚠️ Rolni almashtirish faqat administrator uchun.", "danger");
      return;
    }
    currentRole = roleKey;

    // The header keeps showing who is actually signed in. This used to swap
    // in an invented person -- 'Dr. Rahim Karimov', 'Malika Karimova' -- so
    // the page, and anything printed from it, displayed a name belonging to
    // nobody. Previewing a role changes the layout, never the identity.
    previewRole = roleKey;

    closeAllModals();
    updateHeaderUserWidget();
    showToast(
      `Ko'rinish: <strong>${ROLE_CONFIG[roleKey].name}</strong> — ` +
      `siz hamon <strong>${(currentUser && currentUser.full_name) || 'tizimda'}</strong> ` +
      `sifatida ishlayapsiz.`, 'info');
  }

  // =========================================================================
  // THEME ENGINE (DAY MODE ☀️ / NIGHT MODE 🌙)
  // =========================================================================
  function applyTheme(theme) {
    if (window.FMH_Theme) {
      window.FMH_Theme.set(theme);
      currentTheme = window.FMH_Theme.get();
      return;
    }
    currentTheme = theme;
    document.documentElement.setAttribute('data-theme', theme);
    document.body.className = `${theme}-mode`;
    localStorage.setItem(STORAGE_KEYS.THEME, theme);

    const toggleBtn = document.getElementById('super-theme-toggle-btn');
    if (toggleBtn) {
      if (theme === 'day') {
        toggleBtn.innerHTML = '<i class="fas fa-moon" style="color: #6366f1;"></i> <span>Tungi Rejim</span>';
        toggleBtn.title = "Tungi rejimga o'tish (Night Mode)";
      } else {
        toggleBtn.innerHTML = '<i class="fas fa-sun" style="color: #fbbf24;"></i> <span>Kunduzgi</span>';
        toggleBtn.title = "Kunduzgi rejimga o'tish (Day Mode)";
      }
    }
  }

  function toggleTheme() {
    if (window.FMH_Theme) {
      window.FMH_Theme.toggle();
      currentTheme = window.FMH_Theme.get();
      return;
    }
    const nextTheme = currentTheme === 'day' ? 'night' : 'day';
    applyTheme(nextTheme);
    showToast(nextTheme === 'day' ? '☀️ <strong>Kunduzgi rejim</strong> yoqildi' : '🌙 <strong>Tungi rejim</strong> yoqildi', 'info');
  }

  async function init() {
    applyTheme(currentTheme);
    startLiveClock();
    // Before anything renders: the server decides who this is.
    await loadSession();
    await loadPricingConfig();
    await loadMasterDatabases();
    initSampleTransactions();
    await initSampleStaffRoster();
    initSampleVitals();
    initSampleDiet();
    setupNavigation();
    setupGlobalSearch();

    updateHeaderUserWidget();

    const hash = window.location.hash.replace('#', '').trim();
    if (hash && ['executive', 'facility', 'accounting', 'pharmacy', 'reception', 'doctors', 'nursery', 'kitchen', 'hr', 'crm'].includes(hash)) {
      activeDepartment = hash;
    }

    window.addEventListener('hashchange', () => {
      const newHash = window.location.hash.replace('#', '').trim();
      if (newHash && ['executive', 'facility', 'accounting', 'pharmacy', 'reception', 'doctors', 'nursery', 'kitchen', 'hr', 'crm'].includes(newHash)) {
        switchDepartment(newHash, false);
      }
    });

    renderActiveDepartment();

    // Auto-refresh every 4s
    setInterval(async () => {
      try {
        await loadMasterDatabases();
        renderActiveDepartment();
      } catch (err) {}
    }, 4000);

    window.addEventListener('storage', (e) => {
      if (e.key === STORAGE_KEYS.BEDS || e.key === STORAGE_KEYS.ACCOUNTING) {
        loadMasterDatabases();
        renderActiveDepartment();
      }
    });
  }

  function startLiveClock() {
    const clockEl = document.getElementById('super-clock');
    function update() {
      const now = new Date();
      if (clockEl) {
        clockEl.textContent = now.toLocaleDateString('uz-UZ', { 
          day: '2-digit', month: 'short', year: 'numeric' 
        }) + ' • ' + now.toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      }
    }
    update();
    setInterval(update, 1000);
  }

  async function loadMasterDatabases() {
    try {
      const resRooms = await fetch('./data/clinic_rooms.json');
      clinicRoomsData = await resRooms.json();

      const savedBookings = localStorage.getItem(STORAGE_KEYS.BEDS);
      if (savedBookings) {
        try { bookings = JSON.parse(savedBookings); } catch (e) { bookings = clinicRoomsData.sample_calendar_bookings || []; }
      } else {
        bookings = clinicRoomsData.sample_calendar_bookings || [];
        localStorage.setItem(STORAGE_KEYS.BEDS, JSON.stringify(bookings));
      }

      // Sync active admissions from MySQL REST API
      try {
        const admRes = await fetch('/api/admissions');
        if (admRes.ok) {
          const liveAdm = await admRes.json();
          liveAdm.forEach(adm => {
            if (adm.status === 'active') {
              const existingIdx = bookings.findIndex(b => b.id === adm.id || b.bed_id === adm.bed_id);
              const admBooking = {
                id: adm.id,
                bed_id: adm.bed_id,
                patient_name: adm.patient_name || 'Bemor',
                patient_phone: adm.patient_phone || '+998 90 000 00 00',
                doctor: adm.doctor_name || 'Shifokor biriktirilmagan',
                program: adm.program_type || 'Statsionar davolanish',
                daily_rate: adm.daily_price || listedRate('statsionar_shared'),
                start_date: adm.start_date,
                end_date: adm.planned_end_date,
                status: 'active',
                is_full_room: adm.program_type === 'statsionar_full_room' ||
                  (listedRate('statsionar_full_room') > 0 && adm.daily_price >= listedRate('statsionar_full_room'))
              };
              if (existingIdx >= 0) {
                bookings[existingIdx] = { ...bookings[existingIdx], ...admBooking };
              } else {
                bookings.push(admBooking);
              }
            }
          });
          localStorage.setItem(STORAGE_KEYS.BEDS, JSON.stringify(bookings));
        }
      } catch (e) {
        console.warn('Offline mode for admissions', e);
      }

      const resPharm = await fetch('./data/pharmacology_db.json');
      pharmacologyData = await resPharm.json();

      let liveBedsData = [];
      try {
        const bedsRes = await fetch('/api/beds');
        if (bedsRes.ok) {
          liveBedsData = await bedsRes.json();
        }
      } catch (e) {}

      refreshBedStatuses();
    } catch (err) {
      console.error("Error loading DB:", err);
    }
  }

  function getTodayISO() {
    const d = new Date();
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  function initSampleTransactions() {
    transactions = [];
    localStorage.setItem(STORAGE_KEYS.ACCOUNTING, JSON.stringify(transactions));
  }

  async function initSampleStaffRoster() {
    try {
      const res = await fetch('/api/staff');
      if (res.ok) {
        const list = await res.json();
        if (Array.isArray(list) && list.length > 0) {
          staffRoster = list;
          return;
        }
      }
    } catch (e) {}
    staffRoster = [];
  }

  function initSampleVitals() {
    vitalsLogs = [];
    localStorage.setItem(STORAGE_KEYS.VITALS, JSON.stringify(vitalsLogs));
  }

  function initSampleDiet() {
    dietaryDeliveries = {};
  }

  function getAllBeds(floorFilter = null) {
    const beds = [];
    if (!clinicRoomsData || !clinicRoomsData.floors) return beds;

    clinicRoomsData.floors.forEach(floor => {
      if (floorFilter && floorFilter !== 'all' && floor.floor_number.toString() !== floorFilter.toString()) return;

      floor.rooms.forEach(r => {
        if (r.has_beds && r.beds) {
          r.beds.forEach(b => {
            b.floor_num = floor.floor_number;
            b.room_number = r.room_number;
            b.simple_name = `${r.room_number}-xona ${b.bed_number} karavot`;
            beds.push(b);
          });
        }
      });
    });
    return beds;
  }

  let liveBedsData = [];

  function refreshBedStatuses() {
    const todayStr = getTodayISO();
    getAllBeds().forEach(bed => {
      const activeBooking = bookings.find(b => 
        b.bed_id === bed.bed_id && 
        b.status === 'active' && 
        b.start_date <= todayStr && 
        b.end_date >= todayStr
      );
      const reservedBooking = bookings.find(b => 
        b.bed_id === bed.bed_id && 
        b.status === 'confirmed' && 
        b.start_date > todayStr
      );

      const liveBed = (liveBedsData || []).find(lb =>
        lb.bed_id === bed.bed_id || lb.bed_code === bed.bed_id || lb.bed_code === bed.bed_number
      );
      if (liveBed) {
        bed.physical_bed_status = liveBed.physical_bed_status;
        bed.next_reserved_date = liveBed.next_reserved_date;
      }

      if (activeBooking) {
        bed.status = 'occupied';
        bed.current_patient = activeBooking;
      } else if (reservedBooking) {
        bed.status = 'reserved';
        bed.current_patient = reservedBooking;
      } else if (liveBed && (liveBed.physical_bed_status === 'cleaning' || liveBed.status === 'cleaning')) {
        bed.status = 'cleaning';
        bed.current_patient = null;
      } else {
        bed.status = 'available';
        bed.current_patient = null;
      }
    });
  }

  function setupNavigation() {
    document.querySelectorAll('[data-dept-target]').forEach(btn => {
      btn.addEventListener('click', () => {
        const target = btn.getAttribute('data-dept-target');
        if (target) switchDepartment(target);
      });
    });
  }

  function switchDepartment(deptName, updateHash = true) {
    activeDepartment = deptName;
    if (updateHash && window.location.hash !== `#${deptName}`) {
      window.location.hash = deptName;
    }

    document.querySelectorAll('.super-nav-item').forEach(item => {
      if (item.getAttribute('data-dept-target') === deptName) {
        item.classList.add('active');
      } else {
        item.classList.remove('active');
      }
    });

    document.querySelectorAll('.super-dept-section').forEach(sec => {
      if (sec.id === `dept-${deptName}`) {
        sec.classList.add('active');
      } else {
        sec.classList.remove('active');
      }
    });

    const titleMap = {
      'executive': '📊 Boshqaruv Markazi & BI Analitika',
      'facility': '🏨 Bino & 14 Statsionar Karavot (Gantt & Boshqaruv)',
      'accounting': '💳 Buxgalteriya, Kassa & Billing (POS)',
      'pharmacy': '💊 Farmakologiya & Dorixona (206 Dori)',
      'reception': '📋 Qabulxona & Resepshn (Triaj)',
      'doctors': '🩺 Shifokorlar & Konsultatsiya EMR',
      'nursery': '💉 Hamshiralar Posti & Kundalik Muolajalar',
      'kitchen': '🍲 Klinik Parhez & Oshxona Taomnomasi',
      'hr': '👥 Kadrlar & Shifokorlar Navbatchiligi',
      'crm': '📂 Bemorlar CRM & Kasallik Tarixi'
    };

    const titleEl = document.getElementById('super-current-dept-title');
    if (titleEl) titleEl.textContent = titleMap[deptName] || 'Klinika Boshqaruvi';

    renderActiveDepartment();
  }

  function renderActiveDepartment() {
    refreshBedStatuses();

    switch (activeDepartment) {
      case 'executive':
        renderExecutiveDashboard();
        break;
      case 'facility':
        renderFacilityDepartment();
        break;
      case 'accounting':
        renderAccountingDepartment();
        break;
      case 'pharmacy':
        renderPharmacyDepartment();
        break;
      case 'reception':
        renderReceptionDepartment();
        break;
      case 'doctors':
        renderDoctorsDepartment();
        break;
      case 'nursery':
        renderNurseryDepartment();
        break;
      case 'kitchen':
        renderKitchenDepartment();
        break;
      case 'hr':
        renderHRDepartment();
        break;
      case 'crm':
        renderCRMDepartment();
        break;
    }
  }

  /* =========================================================================
     DEPARTMENT 1: EXECUTIVE BI DASHBOARD
     ========================================================================= */
  async function renderExecutiveDashboard() {
    let summary = null;
    try {
      const res = await fetch('/api/stats/summary');
      if (res.ok) summary = await res.json();
    } catch (e) {}

    const allBeds = getAllBeds();
    const occupied = summary ? summary.occupied_beds : allBeds.filter(b => b.status === 'occupied').length;
    const totalBeds = summary ? summary.total_beds : (allBeds.length || 14);
    const occupancyRate = summary ? summary.occupancy_rate : Math.round((occupied / totalBeds) * 100);

    const totalIncome = summary ? summary.gross_revenue : transactions.filter(t => t.type === 'kirim').reduce((acc, t) => acc + t.amount, 0);
    const totalPaid = summary ? summary.total_paid : totalIncome;
    const totalDebt = summary ? summary.balance_due : 0;
    const netProfit = totalPaid;

    const elOcc = document.getElementById('exec-occupied-beds');
    const elRate = document.getElementById('exec-occupancy-rate');
    const elInc = document.getElementById('exec-gross-revenue');
    const elProf = document.getElementById('exec-net-profit');

    if (elOcc) elOcc.textContent = `${occupied} / ${totalBeds}`;
    if (elRate) elRate.textContent = `${occupancyRate}%`;
    if (elInc) elInc.textContent = formatUZS(totalIncome);
    if (elProf) elProf.textContent = formatUZS(netProfit);
  }

  /* =========================================================================
     DEPARTMENT 2: BUILDING & 14 INPATIENT BEDS
     ========================================================================= */
  function renderFacilityDepartment() {
    const grid = document.getElementById('facility-beds-grid');
    if (!grid) return;

    const allBeds = getAllBeds(currentFacilityFloor);
    grid.innerHTML = allBeds.map(bed => {
      const p = bed.current_patient;
      let pName = p ? p.patient_name : "Bo'sh (Qabulga Tayyor)";
      let pProg = p ? p.program : (bed.next_reserved_date ? `Bo'sh (${bed.next_reserved_date} gacha)` : '10 kunlik standart kurs');
      let statusLabel = bed.status === 'available' ? "Bo'sh" : (bed.status === 'occupied' ? "Band" : (bed.status === 'cleaning' ? "Tozalanmoqda" : "Bron"));

      if (bed.status === 'cleaning') {
        pName = "🧹 Sanitar Dezinfeksiya";
        pProg = "Xona va to'shak dezinfeksiya jarayonida";
      }

      return `
        <div class="charming-bed-card card-status-${bed.status}" onclick="window.FMH_Super.openBookingModal(${jsArg(p ? p.id : '')}, ${jsArg(bed.bed_id)})">
          <div class="bed-card-header">
            <div class="bed-badge-id"><i class="fas fa-bed" style="color: var(--primary);"></i> ${bed.simple_name}</div>
            <span class="pill-status pill-${bed.status}">${statusLabel}</span>
          </div>
          <div class="bed-patient-title" style="font-weight: 700; color: var(--heading-color); font-size: 0.95rem; margin: 6px 0;">${pName}</div>
          <div style="font-size: 0.76rem; color: var(--text-muted);">${bed.simple_name} • ${pProg}</div>
        </div>
      `;
    }).join('');
  }

  function switchFacilityFloor(fl, btn) {
    currentFacilityFloor = fl;
    if (btn) {
      document.querySelectorAll('#facility-floor-filters .super-filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    }
    renderFacilityDepartment();
  }

  /* =========================================================================
     DEPARTMENT 3: ACCOUNTING & BILLING POS
     ========================================================================= */
  function renderAccountingDepartment(filterType = 'all') {
    const totalKirim = transactions.filter(t => t.type === 'kirim').reduce((acc, t) => acc + t.amount, 0);
    const totalChiqim = transactions.filter(t => t.type === 'chiqim').reduce((acc, t) => acc + t.amount, 0);
    const kassaBalance = totalKirim - totalChiqim;
    const pendingDue = bookings.filter(b => b.status === 'active').reduce((acc, b) => {
      const start = new Date(b.start_date);
      const end = new Date(b.end_date);
      const days = Math.max(1, Math.round((end - start) / (1000 * 60 * 60 * 24)));
      const dailyRate = getDailyRateForProgram(b.program, b.daily_rate);
      const totalBill = days * dailyRate;
      const paid = transactions.filter(t => t.type === 'kirim' && t.patient && t.patient.toLowerCase().includes(b.patient_name.toLowerCase())).reduce((s, t) => s + t.amount, 0);
      return acc + Math.max(0, totalBill - paid);
    }, 0);

    const elKirim = document.getElementById('acct-kpi-kirim');
    const elChiqim = document.getElementById('acct-kpi-chiqim');
    const elBalance = document.getElementById('acct-kpi-balance');
    const elPending = document.getElementById('acct-kpi-pending');
    if (elKirim) elKirim.textContent = formatUZS(totalKirim);
    if (elChiqim) elChiqim.textContent = formatUZS(totalChiqim);
    if (elBalance) elBalance.textContent = formatUZS(kassaBalance);
    if (elPending) elPending.textContent = formatUZS(pendingDue);

    const tbody = document.getElementById('accounting-transactions-body');
    if (!tbody) return;

    let list = transactions;
    if (filterType !== 'all') {
      list = list.filter(t => t.type === filterType);
    }

    tbody.innerHTML = list.map(t => {
      const isKirim = t.type === 'kirim';
      const typeBadge = isKirim 
        ? '<span class="pill-status pill-available"><i class="fas fa-arrow-down"></i> Kirim</span>' 
        : '<span class="pill-status pill-occupied"><i class="fas fa-arrow-up"></i> Chiqim</span>';

      return `
        <tr>
          <td><strong style="color: var(--primary); font-family: var(--font-mono);">${t.id}</strong></td>
          <td><div style="font-size: 0.78rem; color: var(--text-muted);">${t.date}</div></td>
          <td>${typeBadge}</td>
          <td><strong>${t.category}</strong></td>
          <td>${t.patient}</td>
          <td><strong style="color: ${isKirim ? 'var(--success)' : 'var(--danger)'}; font-family: var(--font-mono); font-size: 0.95rem;">${isKirim ? '+' : '-'}${formatUZS(t.amount)}</strong></td>
          <td><span style="font-size: 0.78rem; background: var(--bg-hover); padding: 3px 8px; border-radius: 4px; border: 1px solid var(--border-color);">${t.method}</span></td>
          <td><button class="btn-super btn-super-outline" style="padding: 3px 8px; font-size: 0.72rem;" onclick="window.FMH_Super.printInvoice(${jsArg(t.id)})"><i class="fas fa-print"></i> Kvitansiya</button></td>
        </tr>
      `;
    }).join('');

    // Inpatient Billing Calculator Table
    const billTbody = document.getElementById('accounting-inpatient-billing-body');
    if (!billTbody) return;

    billTbody.innerHTML = bookings.map(b => {
      const start = new Date(b.start_date);
      const end = new Date(b.end_date);
      const days = Math.max(1, Math.round((end - start) / (1000 * 60 * 60 * 24)));
      
      let dailyRate = listedRate('statsionar_shared');
      if (b.program && (b.program.includes("1.1 mln") || b.program.includes("Butun Xona"))) dailyRate = listedRate('statsionar_full_room');
      else if (b.program && b.program.includes("630 ming")) dailyRate = listedRate('kunlik_statsionar');

      const totalBill = days * dailyRate;
      const matchingTx = transactions.filter(t => t.type === 'kirim' && t.patient.toLowerCase().includes(b.patient_name.toLowerCase()));
      const totalPaid = matchingTx.reduce((acc, t) => acc + t.amount, 0) || (b.status === 'active' ? totalBill : 0);
      const remainingDebt = Math.max(0, totalBill - totalPaid);

      return `
        <tr>
          <td><strong style="color: var(--primary);">${b.bed_id}</strong></td>
          <td><strong>${b.patient_name}</strong></td>
          <td><span style="font-family: var(--font-mono); font-size: 0.75rem; color: var(--text-muted);">${b.patient_code || b.id}</span></td>
          <td>${b.program}</td>
          <td><span style="font-family: var(--font-mono);">${formatUZS(dailyRate)}</span></td>
          <td><strong>${days} kun</strong></td>
          <td><strong style="color: var(--heading-color); font-family: var(--font-mono);">${formatUZS(totalBill)}</strong></td>
          <td><strong style="color: var(--success); font-family: var(--font-mono);">${formatUZS(totalPaid)}</strong></td>
          <td><strong style="color: ${remainingDebt > 0 ? 'var(--danger)' : 'var(--success)'}; font-family: var(--font-mono);">${remainingDebt > 0 ? formatUZS(remainingDebt) : '0 so\'m (To\'liq)'}</strong></td>
          <td>
            <button class="btn-super btn-super-success" style="padding: 3px 8px; font-size: 0.72rem;" onclick="window.FMH_Super.openPaymentModal(${jsArg(b.patient_name + ' (' + b.bed_id + ')')},${remainingDebt > 0 ? remainingDebt : listedRate('statsionar_shared')})">
              <i class="fas fa-coins"></i> To'lov
            </button>
          </td>
        </tr>
      `;
    }).join('');
  }

  function filterTransactions(type, btn) {
    if (btn) {
      document.querySelectorAll('#accounting-type-filters .super-filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    }
    renderAccountingDepartment(type);
  }

  /* =========================================================================
     DEPARTMENT 4: PHARMACOLOGY (206 DRUGS)
     ========================================================================= */
  let currentPharmacyCategory = 'all';
  let currentPharmacyQuery = '';

  function renderPharmacyDepartment(filterCat = currentPharmacyCategory, query = currentPharmacyQuery) {
    const grid = document.getElementById('pharmacy-drugs-grid');
    if (!grid || !pharmacologyData || !pharmacologyData.medications) return;

    currentPharmacyCategory = filterCat;
    currentPharmacyQuery = query;

    let list = pharmacologyData.medications;
    if (window.FMH_MedSearch) {
      list = window.FMH_MedSearch.search(list, query, filterCat);
    } else {
      if (filterCat !== 'all') {
        list = list.filter(m => m.category && m.category.toLowerCase().includes(filterCat.toLowerCase()));
      }
      if (query) {
        const q = query.toLowerCase();
        list = list.filter(m => (m.name || '').toLowerCase().includes(q) || (m.inn && m.inn.toLowerCase().includes(q)));
      }
    }

    if (list.length === 0) {
      grid.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; padding: 2.5rem; color: #94a3b8;">
          <i class="fas fa-search" style="font-size: 2rem; margin-bottom: 8px;"></i>
          <div>Kiritilgan so'rov bo'yicha dori topilmadi.</div>
          <div style="font-size: 0.8rem; margin-top: 4px; color: #64748b;">Kirill yoki Lotin alifbosida yozib ko'ring (masalan: <em>mexidol / мексидол / 18</em>)</div>
        </div>
      `;
      return;
    }

    grid.innerHTML = list.slice(0, 48).map(d => {
      const displayName = window.FMH_MedSearch ? window.FMH_MedSearch.highlightMatched(d.name, query) : (d.name || '');
      const numBadge = d.fayz_house_num ? `<span style="display:inline-block; font-size:0.7rem; font-weight:800; color:#0b3b60; background:#f1f5f9; padding:1px 5px; border-radius:4px; margin-right:4px; border:1px solid #cbd5e1;">№${d.fayz_house_num}</span>` : '';
      return `
        <div class="pharmacy-drug-card">
          <div>
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px;">
              <strong style="color: var(--heading-color); font-size: 0.95rem;">${numBadge}${displayName}</strong>
              <span class="pill-status pill-available" style="font-size: 0.65rem;">Mavjud</span>
            </div>
            <div style="font-size: 0.75rem; color: var(--primary); font-weight: 700; margin-bottom: 4px;">${d.inn || d.category || 'MNN'}</div>
            <div style="font-size: 0.74rem; color: var(--text-muted); line-height: 1.3;">${d.form || d.dosage_form || 'Ampula / Flakon'} • Doza: ${d.dosage || d.default_dosage || 'Standart'}</div>
          </div>
          <div style="border-top: 1px solid var(--border-color); margin-top: 10px; padding-top: 8px; display: flex; justify-content: space-between; align-items: center;">
            <span style="font-family: var(--font-mono); font-weight: 700; color: var(--success); font-size: 0.88rem;">${formatUZS(d.price || 45000)}</span>
            <button class="btn-super btn-super-primary" style="padding: 3px 8px; font-size: 0.72rem;" onclick="window.FMH_Super.prescribeDrug(${jsArg(d.name)})">+ Retsept</button>
          </div>
        </div>
      `;
    }).join('');
  }

  function onPharmacySearch(val) {
    currentPharmacyQuery = (val || '').trim();
    const clearBtn = document.getElementById('pharmacy-search-clear');
    const badge = document.getElementById('pharmacy-search-script-badge');
    if (clearBtn) clearBtn.style.display = currentPharmacyQuery ? 'flex' : 'none';
    if (badge && window.FMH_MedSearch) {
      const s = window.FMH_MedSearch.detectScript(currentPharmacyQuery);
      if (s === 'cyrillic') {
        badge.innerHTML = '🇷🇺 Кирилл ➔ Lotin';
        badge.style.color = '#0284c7';
      } else if (s === 'latin') {
        badge.innerHTML = '🇺🇿 Lotin ➔ Кирилл';
        badge.style.color = '#9333ea';
      } else {
        badge.innerHTML = '🔤 Lotin ⇄ Кирилл';
        badge.style.color = '#0d9488';
      }
    }
    renderPharmacyDepartment(currentPharmacyCategory, currentPharmacyQuery);
  }

  function clearPharmacySearch() {
    const inp = document.getElementById('pharmacy-search-input');
    if (inp) {
      inp.value = '';
      onPharmacySearch('');
      inp.focus();
    }
  }

  function filterPharmacyCategory(cat, btn) {
    if (btn) {
      document.querySelectorAll('#pharmacy-category-filters .super-filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    }
    renderPharmacyDepartment(cat, currentPharmacyQuery);
  }

  /* =========================================================================
     DEPARTMENT 5: RECEPTION & INTAKE
     ========================================================================= */
  function renderReceptionDepartment() {
    const tbody = document.getElementById('reception-queue-body');
    if (!tbody) return;

    tbody.innerHTML = bookings.map(b => `
      <tr>
        <td><strong style="color: var(--primary); font-family: var(--font-mono);">${b.patient_code || b.id}</strong></td>
        <td><strong>${b.patient_name}</strong><div style="font-size: 0.72rem; color: var(--text-muted);">${b.patient_phone || '+998 90 000-00-00'}</div></td>
        <td><span class="pill-status pill-available">${b.bed_id}</span></td>
        <td>${b.program}</td>
        <td>${b.doctor}</td>
        <td>${b.start_date} ➔ ${b.end_date}</td>
        <td>
          <button class="btn-super btn-super-outline" style="padding: 3px 8px; font-size: 0.72rem;" onclick="window.FMH_Super.openBookingModal(${jsArg(b.id)})"><i class="fas fa-edit"></i> Ko'rish</button>
        </td>
      </tr>
    `).join('');
  }

  /* =========================================================================
     DEPARTMENT 6: DOCTORS & EMR
     ========================================================================= */
  function renderDoctorsDepartment() {
    const listEl = document.getElementById('doctors-patient-cards');
    if (!listEl) return;

    listEl.innerHTML = bookings.filter(b => b.status === 'active').map(b => `
      <div class="doctor-emr-card">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
          <div>
            <h4 style="color: var(--heading-color); font-size: 1rem; font-weight: 700;">${b.patient_name}</h4>
            <span style="font-size: 0.75rem; color: var(--primary); font-weight: 600;">${b.bed_id} • ${b.patient_code || b.id}</span>
          </div>
          <span class="pill-status pill-occupied">Statsionar Davolashda</span>
        </div>
        <div style="font-size: 0.8rem; color: var(--text-muted); margin: 8px 0; background: var(--bg-hover); padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border-color); line-height: 1.5;">
          <strong>Dastur:</strong> ${b.program}<br>
          <strong>Mas'ul Shifokor:</strong> ${b.doctor}<br>
          <strong>Klinik Izoh:</strong> ${b.notes || 'Toksikologik tozalash va reabilitatsiya.'}
        </div>
        <div style="display: flex; gap: 6px; margin-top: 10px;">
          <a href="doctor.html?patient=${b.patient_code || b.id}" class="btn-super btn-super-primary" style="flex: 1; padding: 6px 10px; font-size: 0.75rem; text-decoration: none; text-align: center; background: linear-gradient(135deg, #0284c7, #06b6d4);"><i class="fas fa-pills"></i> Dori & Anamnez Yozish</a>
          <a href="doctor.html?patient=${b.patient_code || b.id}" class="btn-super btn-super-outline" style="padding: 6px 10px; font-size: 0.75rem; text-decoration: none;"><i class="fas fa-user-md"></i> Shifokor Posti &rarr;</a>
        </div>
      </div>
    `).join('');
  }

  /* =========================================================================
     DEPARTMENT 7: NURSERY & VITALS POST
     ========================================================================= */
  function renderNurseryDepartment() {
    const tbody = document.getElementById('nursery-vitals-body');
    if (!tbody) return;

    tbody.innerHTML = vitalsLogs.map(v => `
      <tr>
        <td><strong>${v.bed}</strong></td>
        <td><strong>${v.patient}</strong></td>
        <td><span style="font-family: var(--font-mono); color: var(--primary);">${v.time}</span></td>
        <td><strong style="color: var(--heading-color);">${v.bp} mm Hg</strong></td>
        <td>${v.pulse} ur/min</td>
        <td>${v.temp}°C</td>
        <td><span style="color: var(--success); font-weight: 700;">${v.spo2}</span></td>
        <td><span class="pill-status pill-available">${v.status}</span></td>
        <td><button class="btn-super btn-super-outline" style="padding: 3px 8px; font-size: 0.72rem;" onclick="window.FMH_Super.openVitalsModal(${jsArg(v.bed)})"><i class="fas fa-plus"></i> O'lchash</button></td>
      </tr>
    `).join('');
  }

  /* =========================================================================
     DEPARTMENT 8: KITCHEN & DIETARY
     ========================================================================= */
  function renderKitchenDepartment() {
    const tbody = document.getElementById('kitchen-diet-body');
    if (!tbody) return;

    const activeBeds = getAllBeds().filter(b => b.status === 'occupied');
    tbody.innerHTML = activeBeds.map(b => {
      const deliv = dietaryDeliveries[b.bed_id] || { b: true, l: true, d: false };
      return `
        <tr>
          <td><strong>${b.simple_name}</strong></td>
          <td><strong>${b.current_patient ? b.current_patient.patient_name : ''}</strong></td>
          <td><span class="pill-status pill-purple">Detoks Parhez (Stol №5)</span></td>
          <td>Mol go'shti bulyoni, suli yormasi, kompot, qora non suxarisi</td>
          <td>
            <div style="display: flex; gap: 4px;">
              <button class="super-preset-pill ${deliv.b ? 'active' : ''}" onclick="window.FMH_Super.toggleMeal(${jsArg(b.bed_id)}, 'b')">Nonushta ${deliv.b ? '✓' : ''}</button>
              <button class="super-preset-pill ${deliv.l ? 'active' : ''}" onclick="window.FMH_Super.toggleMeal(${jsArg(b.bed_id)}, 'l')">Tushlik ${deliv.l ? '✓' : ''}</button>
              <button class="super-preset-pill ${deliv.d ? 'active' : ''}" onclick="window.FMH_Super.toggleMeal(${jsArg(b.bed_id)}, 'd')">Kechki ${deliv.d ? '✓' : ''}</button>
            </div>
          </td>
          <td><span class="pill-status pill-available"><i class="fas fa-check"></i> Yetkazildi</span></td>
        </tr>
      `;
    }).join('');
  }

  function toggleMeal(bedId, mealType) {
    if (!dietaryDeliveries[bedId]) dietaryDeliveries[bedId] = { b: false, l: false, d: false };
    dietaryDeliveries[bedId][mealType] = !dietaryDeliveries[bedId][mealType];
    renderKitchenDepartment();
    showToast(`🍲 Taom holati yangilandi: ${bedId}`);
  }

  /* =========================================================================
     DEPARTMENT 9: HR & STAFF ROSTER
     ========================================================================= */
  function renderHRDepartment() {
    const grid = document.getElementById('hr-staff-grid');
    if (!grid) return;

    if (!staffRoster || staffRoster.length === 0) {
      grid.innerHTML = '<div style="color: var(--text-muted); grid-column: 1/-1; padding: 20px;">Hozircha xodimlar ro\'yxati bo\'sh. Superadmin paneli orqali xodimlarni qabul qilishingiz mumkin.</div>';
      return;
    }

    grid.innerHTML = staffRoster.map(s => {
      const name = s.full_name || s.name || 'Xodim';
      const role = s.role || 'Shifokor';
      const spec = s.specialty || '';
      const shift = s.shift || '24/7 Navbatchilik';
      const room = s.room || ((role === 'doctor' || role === 'chief_doctor') ? '1-xona' : 'Hamshiralar posti');
      const phone = s.phone || '+998 90 000-00-00';
      const status = s.status === 'active' || !s.status ? 'Faol Navbatchi' : 'Dam olishda';

      return `
      <div class="hr-staff-card">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px;">
          <div>
            <h4 style="color: var(--heading-color); font-size: 1rem; font-weight: 700;">${name}</h4>
            <div style="font-size: 0.76rem; color: var(--primary); font-weight: 700;">${role} ${spec ? `(${spec})` : ''}</div>
          </div>
          <span class="pill-status pill-available">${status}</span>
        </div>
        <div style="font-size: 0.78rem; color: var(--text-muted); margin: 10px 0; line-height: 1.5; background: var(--bg-hover); padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border-color);">
          <strong>Smena:</strong> ${shift}<br>
          <strong>Kabinet / Post:</strong> ${room}<br>
          <strong>Aloqa:</strong> ${phone}
        </div>
        <div style="display: flex; gap: 6px; margin-top: 8px;">
          <a href="tel:${phone}" class="btn-super btn-super-outline" style="flex: 1; padding: 4px; font-size: 0.75rem; text-decoration: none;"><i class="fas fa-phone"></i> Qo'ng'iroq</a>
          <button class="btn-super btn-super-primary" style="padding: 4px 10px; font-size: 0.75rem;" onclick="window.FMH_Super.showToast(${jsArg('✅ Navbatchilik tasdiqlandi: ' + name)})">Navbatchilik</button>
        </div>
      </div>
      `;
    }).join('');
  }

  /* =========================================================================
     DEPARTMENT 10: PATIENT CRM & ARCHIVES
     ========================================================================= */
  function renderCRMDepartment(query = '') {
    const tbody = document.getElementById('crm-patients-body');
    if (!tbody) return;

    let list = bookings;
    if (query) {
      const q = query.toLowerCase();
      list = list.filter(b => b.patient_name.toLowerCase().includes(q) || (b.patient_phone && b.patient_phone.includes(q)) || (b.patient_code && b.patient_code.toLowerCase().includes(q)));
    }

    tbody.innerHTML = list.map(b => `
      <tr>
        <td><strong style="color: var(--primary); font-family: var(--font-mono);">${b.patient_code || b.id}</strong></td>
        <td><strong>${b.patient_name}</strong></td>
        <td>${b.patient_phone || '+998 90 000-00-00'}</td>
        <td>${b.bed_id}</td>
        <td>${b.program}</td>
        <td>${b.doctor}</td>
        <td><span class="pill-status pill-${b.status === 'active' ? 'occupied' : 'available'}">${b.status === 'active' ? 'Faol Davolanmoqda' : 'Yakunlangan'}</span></td>
        <td>
          <button class="btn-super btn-super-outline" style="padding: 3px 8px; font-size: 0.72rem;" onclick="window.FMH_Super.openBookingModal(${jsArg(b.id)})"><i class="fas fa-folder-open"></i> Tarix</button>
        </td>
      </tr>
    `).join('');
  }

  function setupGlobalSearch() {
    const searchInput = document.getElementById('super-global-search');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        const val = e.target.value.trim();
        if (activeDepartment === 'pharmacy') renderPharmacyDepartment('all', val);
        else if (activeDepartment === 'crm') renderCRMDepartment(val);
      });
    }
  }

  /* =========================================================================
     MODAL CONTROLS & EVENT HANDLERS
     ========================================================================= */
  function closeAllModals() {
    document.querySelectorAll('.super-modal-backdrop').forEach(m => m.classList.remove('active'));
  }

  function openBookingModal(bookingId = null, preselectedBedId = null) {
    const modal = document.getElementById('super-booking-modal');
    const bedSelect = document.getElementById('modal-bed-select');
    const titleEl = document.getElementById('modal-booking-title');
    const deleteBtn = document.getElementById('btn-modal-delete-booking');
    const submitBtnText = document.getElementById('btn-modal-submit-text');

    if (!modal) return;

    if (bedSelect) {
      bedSelect.innerHTML = getAllBeds().map(b => `
        <option value="${b.bed_id}" ${preselectedBedId === b.bed_id ? 'selected' : ''}>
          ${b.simple_name}
        </option>
      `).join('');
    }

    const form = document.getElementById('modal-booking-form');
    if (form) form.reset();

    const bookingIdInput = document.getElementById('modal-booking-id');
    const startDateInput = document.getElementById('modal-start-date');
    const endDateInput = document.getElementById('modal-end-date');

    // Dynamically load doctors from /api/staff
    fetch('/api/staff').then(res => res.json()).then(staffList => {
        // Sanitarlar va hamshiralar davolash va konsultatsiya ko'rsatmaydi, faqat shifokorlar
        const docStaff = staffList.filter(s => s.role === 'doctor' || s.role === 'chief_doctor');
        const docSelect = document.getElementById('modal-doctor-select');
        if (docSelect) {
          if (docStaff.length > 0) {
            docSelect.innerHTML = docStaff.map(d => `<option value="${d.full_name} (${d.specialty || d.role})">${d.full_name} (${d.specialty || d.role})</option>`).join('');
          } else {
            docSelect.innerHTML = `<option value="">— Shifokor biriktirilmagan —</option>`;
          }
          if (bookingId) {
            const booking = bookings.find(b => String(b.id) === String(bookingId));
            if (booking && booking.doctor) docSelect.value = booking.doctor;
          }
        }
    }).catch(() => {});

    if (bookingId) {
      const booking = bookings.find(b => String(b.id) === String(bookingId));
      if (booking) {
        if (titleEl) titleEl.textContent = `Bemor Ma'lumotlarini Tahrirlash: ${booking.patient_name}`;
        if (bookingIdInput) bookingIdInput.value = booking.id;
        document.getElementById('modal-patient-name').value = booking.patient_name;
        document.getElementById('modal-patient-phone').value = booking.patient_phone || '';
        document.getElementById('modal-program-select').value = booking.program;
        document.getElementById('modal-doctor-select').value = booking.doctor || '';
        if (bedSelect) bedSelect.value = booking.bed_id;
        if (startDateInput) startDateInput.value = booking.start_date;
        if (endDateInput) endDateInput.value = booking.end_date;
        document.getElementById('modal-booking-notes').value = booking.notes || '';
        if (deleteBtn) deleteBtn.style.display = 'inline-flex';
        if (submitBtnText) submitBtnText.textContent = "O'zgarishlarni Saqlash";
      }
    } else {
      if (titleEl) titleEl.textContent = "Yangi Bemor Qabuli va Karavot Biriktirish";
      if (bookingIdInput) bookingIdInput.value = '';
      if (deleteBtn) deleteBtn.style.display = 'none';
      if (submitBtnText) submitBtnText.textContent = "Qabulni Tasdiqlash";

      const today = new Date();
      const next10 = new Date(today);
      next10.setDate(today.getDate() + 10);

      if (startDateInput) startDateInput.value = today.toISOString().split('T')[0];
      if (endDateInput) endDateInput.value = next10.toISOString().split('T')[0];
    }

    modal.classList.add('active');
  }

  function applyDurationPreset(days) {
    const startInput = document.getElementById('modal-start-date');
    const endInput = document.getElementById('modal-end-date');
    if (!startInput || !endInput) return;

    const start = startInput.value ? new Date(startInput.value) : new Date();
    const end = new Date(start);
    end.setDate(start.getDate() + days);
    endInput.value = end.toISOString().split('T')[0];
  }

  function handleBookingSubmit(e) {
    e.preventDefault();

    const bookingId = document.getElementById('modal-booking-id').value;
    const patientName = document.getElementById('modal-patient-name').value.trim();
    const patientPhone = document.getElementById('modal-patient-phone').value.trim();
    const bedId = document.getElementById('modal-bed-select').value;
    const program = document.getElementById('modal-program-select').value;
    const doctor = document.getElementById('modal-doctor-select').value;
    const startDate = document.getElementById('modal-start-date').value;
    const endDate = document.getElementById('modal-end-date').value;
    const notes = document.getElementById('modal-booking-notes').value.trim();

    if (!patientName || !bedId || !startDate || !endDate) {
      window.FMH_Toast("Iltimos, barcha majburiy maydonlarni to'ldiring!", 'warning');
      return;
    }

    if (bookingId) {
      const idx = bookings.findIndex(b => String(b.id) === String(bookingId));
      if (idx !== -1) {
        bookings[idx] = {
          ...bookings[idx],
          patient_name: patientName,
          patient_phone: patientPhone,
          bed_id: bedId,
          program: program,
          doctor: doctor,
          start_date: startDate,
          end_date: endDate,
          notes: notes
        };
        showToast(`✅ <strong>${patientName}</strong> ma'lumotlari yangilandi!`);
      }
    } else {
      const newId = `FMH-B${Math.floor(100 + Math.random() * 900)}`;
      const newBooking = {
        id: newId,
        patient_code: `FMH-${Math.floor(1000 + Math.random() * 9000)}`,
        patient_name: patientName,
        patient_phone: patientPhone,
        bed_id: bedId,
        program: program,
        doctor: doctor,
        start_date: startDate,
        end_date: endDate,
        status: "active",
        notes: notes
      };
      bookings.push(newBooking);
      showToast(`🎉 <strong>${patientName}</strong> muvaffaqiyatli ${bedId} karavotiga qabul qilindi!`);
    }

    localStorage.setItem(STORAGE_KEYS.BEDS, JSON.stringify(bookings));
    closeAllModals();
    renderActiveDepartment();
  }

  async function deleteCurrentBooking() {
    const bookingId = document.getElementById('modal-booking-id').value;
    if (!bookingId) return;

    const booking = bookings.find(b => String(b.id) === String(bookingId));
    const pName = booking ? booking.patient_name : "ushbu";

    const okBooking = await fmhConfirm({
      title: "Bronni O'chirish",
      message: `Haqiqatan ham <strong>${pName}</strong> uchun qilingan bron/qabulni o'chirmoqchimisiz?`,
      confirmText: "O'chirish",
      cancelText: "Bekor Qilish",
      type: 'danger'
    });
    if (!okBooking) return;

    bookings = bookings.filter(b => String(b.id) !== String(bookingId));
    localStorage.setItem(STORAGE_KEYS.BEDS, JSON.stringify(bookings));
    closeAllModals();
    renderActiveDepartment();
    showToast(`🗑️ <strong>${pName}</strong> uchun olingan bron o'chirildi va karavot bo'shatildi!`, 'danger');
  }

  function openPaymentModal(patientName = '', amount = '') {
    const modal = document.getElementById('super-payment-modal');
    if (!modal) return;
    
    if (patientName) {
      const pInput = document.getElementById('payment-patient-name');
      if (pInput) pInput.value = patientName;
    }
    if (amount) {
      const aInput = document.getElementById('payment-amount');
      if (aInput) aInput.value = amount;
    }

    modal.classList.add('active');
  }

  function handlePaymentSubmit(e) {
    e.preventDefault();

    const type = document.getElementById('payment-type').value;
    const category = document.getElementById('payment-category').value;
    const patient = document.getElementById('payment-patient-name').value.trim();
    const amount = Number(document.getElementById('payment-amount').value);
    const method = document.getElementById('payment-method').value;

    if (!patient || !amount) {
      window.FMH_Toast("Iltimos, barcha maydonlarni to'ldiring!", 'warning');
      return;
    }

    const now = new Date();
    const dateStr = now.toISOString().split('T')[0] + ' ' + now.toTimeString().slice(0, 5);

    const newTx = {
      id: `TX-${Math.floor(1000 + Math.random() * 9000)}`,
      date: dateStr,
      type: type,
      category: category,
      patient: patient,
      amount: amount,
      method: method,
      status: "To'langan"
    };

    transactions.unshift(newTx);
    localStorage.setItem(STORAGE_KEYS.ACCOUNTING, JSON.stringify(transactions));
    closeAllModals();
    renderActiveDepartment();
    showToast(`💳 <strong>${formatUZS(amount)}</strong> to'lov muvaffaqiyatli kassa jurnaliga kiritildi!`);
    printInvoice(newTx.id);
  }

  function printInvoice(txId) {
    const tx = transactions.find(t => t.id === txId) || transactions[0];
    if (!tx) return;

    document.getElementById('rc-id').textContent = tx.id;
    document.getElementById('rc-date').textContent = tx.date;
    document.getElementById('rc-patient').textContent = tx.patient;
    document.getElementById('rc-method').textContent = tx.method;
    document.getElementById('rc-amount').textContent = formatUZS(tx.amount);
    document.getElementById('rc-service-sum').textContent = formatUZS(tx.amount);

    const receiptModal = document.getElementById('super-receipt-modal');
    if (receiptModal) receiptModal.classList.add('active');
  }

  function openVitalsModal(preselectedBed = null) {
    const modal = document.getElementById('super-vitals-modal');
    const bedSelect = document.getElementById('vitals-bed-select');
    if (!modal || !bedSelect) return;

    bedSelect.innerHTML = getAllBeds().filter(b => b.status === 'occupied').map(b => `
      <option value="${b.simple_name}" ${preselectedBed === b.simple_name ? 'selected' : ''}>
        ${b.simple_name} — ${b.current_patient ? b.current_patient.patient_name : ''}
      </option>
    `).join('');

    modal.classList.add('active');
  }

  function handleVitalsSubmit(e) {
    e.preventDefault();

    const bed = document.getElementById('vitals-bed-select').value;
    const bp = document.getElementById('vitals-bp').value.trim();
    const pulse = document.getElementById('vitals-pulse').value.trim();
    const temp = document.getElementById('vitals-temp').value.trim();
    const spo2 = document.getElementById('vitals-spo2').value.trim();

    const now = new Date();
    const timeStr = now.toTimeString().slice(0, 5);

    vitalsLogs.unshift({
      bed: bed,
      patient: bed.split('—')[1] || 'Bemor',
      time: timeStr,
      bp: bp,
      pulse: pulse,
      temp: temp,
      spo2: spo2,
      status: "Barqaror"
    });

    localStorage.setItem(STORAGE_KEYS.VITALS, JSON.stringify(vitalsLogs));
    closeAllModals();
    renderActiveDepartment();
    showToast(`💉 <strong>${bed}</strong> uchun hayotiy ko'rsatkichlar qayd etildi!`);
  }

  function prescribeDrug(drugName) {
    showToast(`💊 <strong>${drugName}</strong> bemor retseptiga qo'shildi!`);
  }

  function prescribeDrugForPatient(patientName) {
    showToast(`🩺 <strong>${patientName}</strong> uchun dori / kapelnitsa tayinlash oynasi ochildi!`);
  }

  function exportBedsToExcel() {
    if (!window.XLSX) {
      window.FMH_Toast("Excel kutubxonasi yuklanmoqda...", 'info');
      return;
    }

    const rows = bookings.map((b, index) => ({
      "№": index + 1,
      "Bemor ID": b.id,
      "Bemor F.I.Sh.": b.patient_name,
      "Telefon": b.patient_phone || '',
      "Klinik Kod": b.patient_code || '',
      "Karavot": b.bed_id,
      "Xizmat / Dastur": b.program,
      "Mas'ul Shifokor": b.doctor,
      "Kirish Sanasi": b.start_date,
      "Chiqish Sanasi": b.end_date,
      "Holati": b.status === 'active' ? "Band" : "Bron"
    }));

    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Fayz Medical House Bemorlar");

    const fileName = `FMH_Bemorlar_va_Karavotlar_${new Date().toISOString().split('T')[0]}.xlsx`;
    XLSX.writeFile(wb, fileName);
    showToast(`📗 <strong>${fileName}</strong> muvaffaqiyatli yuklab olindi!`);
  }

    function printCurrentInvoice() {
    const rcId = document.getElementById('rc-id')?.textContent || 'RCP-2026';
    const rcPatient = document.getElementById('rc-patient')?.textContent || 'Bemor';
    const rcAmountStr = document.getElementById('rc-amount')?.textContent || '720000';
    const cleanAmount = parseFloat(rcAmountStr.replace(/[^0-9]/g, '')) || 720000;

    if (window.FMH_Print) {
      window.FMH_Print.patientReceipt({
        full_name: rcPatient,
        patient_code: 'FMH-2026-TX'
      }, {
        total_amount: cleanAmount,
        paid_amount: cleanAmount
      }, {
        id: rcId,
        amount: cleanAmount,
        payment_method: 'terminal',
        notes: 'Klinik xizmatlar to`lovi'
      });
    } else {
      window.print();
    }
  }

  /* =========================================================================
     SUPERADMIN ELASTIC COMMAND CENTER & MANAGEMENT
     ========================================================================= */
  function openSuperadminPanel() {
    if (currentRole !== 'superadmin') {
      showToast("⚠️ Bu bo'lim faqat Superadmin uchun ruxsat etilgan!", "danger");
      return;
    }
    const modal = document.getElementById('super-admin-modal');
    if (!modal) return;

    renderAdminPricingTab();
    renderAdminRoomsTab();
    renderAdminStaffTab();
    renderAdminUsersTab();

    modal.classList.add('active');
  }

  function switchAdminTab(tabName, btn) {
    document.querySelectorAll('.superadmin-tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.superadmin-tab-content').forEach(c => c.classList.remove('active'));

    if (btn) btn.classList.add('active');
    const targetContent = document.getElementById(`admin-tab-${tabName}`);
    if (targetContent) targetContent.classList.add('active');
    // The audit trail is large; it is read only when its tab is opened.
    if (tabName === 'audit') renderAuditTab();
  }

  // --- 1. PRICING & TARIFFS ---
  // Editor inputs -> package ids of the one price list.
  const PRICE_INPUTS = {
    'price-standard-shared': 'statsionar_shared',
    'price-vip-solo': 'statsionar_full_room',
    'price-daycare': 'kunlik_statsionar',
    'price-ambulator-1': 'ambulator_1',
    'price-ambulator-2': 'ambulator_2',
    'price-consultation': 'consultation'
  };
  // Editor inputs -> pay for one duty shift (payroll counts these).
  const DUTY_TARIFF_INPUTS = {
    'price-duty-doctor-night': 'doctor_night',
    'price-duty-nurse-24h': 'nurse_24h',
    'price-duty-sanitar-24h': 'sanitar_24h'
  };

  function spacedAmount(n) {
    return String(Math.round(Number(n) || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  }

  function renderAdminPricingTab() {
    // The inputs show the listed prices; there is no second set of numbers
    // to fall back on any more.
    Object.keys(PRICE_INPUTS).forEach(inputId => {
      const el = document.getElementById(inputId);
      if (el) el.value = listedRate(PRICE_INPUTS[inputId]);
    });
    Object.keys(DUTY_TARIFF_INPUTS).forEach(inputId => {
      const el = document.getElementById(inputId);
      if (el && window.FMH_Pricing) el.value = window.FMH_Pricing.dutyTariff(DUTY_TARIFF_INPUTS[inputId]);
    });
    // The hints under the inputs were typed in ("Hozirgi standart: 720 000")
    // and went stale after the first edit; they now show the listed price.
    document.querySelectorAll('[data-price-hint]').forEach(el => {
      const rate = listedRate(el.getAttribute('data-price-hint'));
      el.textContent = el.textContent
        .replace(/^(Hozirgi standart: )[\d ]+/, `$1${spacedAmount(rate)}`)
        .replace(/(10 kunlik kurs: )[\d ]+/, `$1${spacedAmount(rate * 10)}`);
    });

    renderAdminServicesTable();
  }

  function renderAdminServicesTable() {
    const tbody = document.getElementById('admin-services-table-body');
    if (!tbody) return;
    const services = pricingConfig.additional_services || [];
    if (services.length === 0) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">Qo'shimcha xizmatlar mavjud emas</td></tr>`;
      return;
    }
    tbody.innerHTML = services.map(s => `
      <tr>
        <td><strong>${s.name}</strong></td>
        <td><span class="pill-status pill-purple">${s.category || 'Muolaja'}</span></td>
        <td><strong style="color: var(--success);">${formatUZS(s.price)}</strong></td>
        <td>
          <button type="button" class="btn-super btn-super-outline" style="padding: 2px 6px; font-size: 0.72rem; color: var(--danger);" onclick="window.FMH_Super.deleteService(${jsArg(s.id)})" title="O'chirish">
            <i class="fas fa-trash"></i>
          </button>
        </td>
      </tr>
    `).join('');
  }

  // Returns true only when the server has stored the list. The old version
  // filled an empty or 0 price with a hardcoded default, ignored the
  // server's reason for a refusal, and on a network error said the prices
  // were "saved locally" although nothing was saved anywhere.
  async function savePricingSettings(e) {
    if (e) e.preventDefault();
    if (window.FMH_Pricing && window.FMH_Pricing.isFallback()) {
      showToast("Narxlar serverdan yuklanmagan. Sahifani yangilang, so'ng qayta saqlang.", 'danger');
      return false;
    }

    const packages = {};
    for (const inputId of Object.keys(PRICE_INPUTS)) {
      const el = document.getElementById(inputId);
      if (!el) continue;
      const raw = String(el.value || '').trim();
      const value = Number(raw);
      if (raw === '' || !Number.isFinite(value) || value < 0) {
        showToast("Narx to'g'ri kiritilmagan.", 'warning');
        el.focus();
        return false;
      }
      const pkgId = PRICE_INPUTS[inputId];
      packages[pkgId] = { daily_rate: value };
      const name = pricingConfig.packages && pricingConfig.packages[pkgId] && pricingConfig.packages[pkgId].name_uz;
      if (name) packages[pkgId].name_uz = name;
    }

    const dutyTariffs = {};
    for (const inputId of Object.keys(DUTY_TARIFF_INPUTS)) {
      const el = document.getElementById(inputId);
      if (!el) continue;
      const raw = String(el.value || '').trim();
      const value = Number(raw);
      if (raw === '' || !Number.isFinite(value) || value < 0) {
        showToast("Navbatchilik narxi to'g'ri kiritilmagan.", 'warning');
        el.focus();
        return false;
      }
      dutyTariffs[DUTY_TARIFF_INPUTS[inputId]] = value;
    }

    // updated_by is taken from the session on the server.
    const payload = {
      packages,
      additional_services: pricingConfig.additional_services || []
    };
    if (Object.keys(dutyTariffs).length) payload.duty_tariffs = dutyTariffs;

    try {
      const res = await fetch('/api/settings/pricing', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      let body = null;
      try { body = await res.json(); } catch (_) { body = null; }
      if (!res.ok) {
        showToast((body && body.error) || "Narxlarni saqlashda xatolik yuz berdi", "danger");
        await loadPricingConfig();
        renderAdminPricingTab();
        return false;
      }
      if (window.FMH_Pricing) {
        await window.FMH_Pricing.reload();
        await loadPricingConfig();
      } else if (body && body.pricing) {
        pricingConfig = body.pricing;
      }
      showToast("✅ Yangi narxlar va tariflar tizimga saqlandi!", "success");
      renderActiveDepartment();
      return true;
    } catch (err) {
      showToast("Server bilan bog'lanishda xatolik: narxlar saqlanmadi.", "danger");
      await loadPricingConfig();
      renderAdminPricingTab();
      return false;
    }
  }

  async function promptAddService() {
    if (window.FMH_Pricing && window.FMH_Pricing.isFallback()) {
      showToast("Narxlar serverdan yuklanmagan. Sahifani yangilang.", 'danger');
      return;
    }
    const name = prompt("Yangi qo'shimcha xizmat yoki muolaja nomi:");
    if (!name || !name.trim()) return;
    const category = prompt("Kategoriya (Muolaja, Diagnostika, Laboratoriya):", "Muolaja") || "Muolaja";
    const priceStr = prompt("Xizmat narxi (so'mda):", "");
    const digits = (priceStr || '').replace(/[^0-9]/g, '');
    // An empty price used to become 100 000; a price nobody typed is not saved.
    if (!digits) {
      showToast("Xizmat narxi kiritilmadi.", 'warning');
      return;
    }
    const price = Number(digits);

    const newService = {
      id: `SRV-${Date.now().toString(36).toUpperCase()}`,
      name: name.trim(),
      category: category.trim(),
      price: price
    };

    if (!pricingConfig.additional_services) pricingConfig.additional_services = [];
    pricingConfig.additional_services.push(newService);

    const saved = await savePricingSettings();
    renderAdminServicesTable();
    if (saved) showToast(`✅ "${name}" xizmati narxlar katalogiga qo'shildi!`);
  }

  async function deleteService(serviceId) {
    const okService = await fmhConfirm({
      title: "Xizmatni O'chirish",
      message: "Ushbu xizmatni narxlar ro'yxatidan o'chirmoqchimisiz?",
      confirmText: "O'chirish",
      cancelText: "Bekor Qilish",
      type: 'danger'
    });
    if (!okService) return;
    pricingConfig.additional_services = (pricingConfig.additional_services || []).filter(s => s.id !== serviceId);
    const saved = await savePricingSettings();
    renderAdminServicesTable();
    if (saved) showToast("🗑️ Xizmat narxlar ro'yxatidan o'chirildi");
  }

  // --- 2. ROOMS & BEDS INFRASTRUCTURE ---
  async function renderAdminRoomsTab() {
    const roomSelect = document.getElementById('attach-bed-room-select');
    const tbody = document.getElementById('admin-rooms-table-body');
    if (!clinicRoomsData || !clinicRoomsData.floors) return;

    if (roomSelect) {
      const optRooms = [];
      clinicRoomsData.floors.forEach(fl => {
        fl.rooms.forEach(r => {
          optRooms.push(`<option value="${r.id}">${fl.floor_number}-qavat: ${r.room_number || r.name_uz} (${r.type})</option>`);
        });
      });
      roomSelect.innerHTML = optRooms.join('');
    }

    if (tbody) {
      const rows = [];
      clinicRoomsData.floors.forEach(fl => {
        fl.rooms.forEach(r => {
          const bedsList = (r.beds || []).map(b => `
            <span style="display: inline-flex; align-items: center; gap: 4px; background: var(--bg-card); padding: 2px 6px; border-radius: 4px; margin: 2px; border: 1px solid var(--border-color); font-size: 0.76rem;">
              🛏️ <strong>${b.bed_number || b.bed_id}</strong> (${formatUZS(b.daily_rate || listedRate('statsionar_shared'))})
              <button type="button" title="Karavotni ajratish (Detach)" onclick="window.FMH_Super.detachBed(${jsArg(b.bed_id)})" style="background: none; border: none; color: var(--danger); cursor: pointer; padding: 0 2px;">&times;</button>
            </span>
          `).join('');

          rows.push(`
            <tr>
              <td><strong>${fl.floor_number}-qavat</strong></td>
              <td><strong>${r.room_number || r.name_uz}</strong> <span style="font-size: 0.72rem; color: var(--text-muted);">(${r.type})</span></td>
              <td>${bedsList || '<em style="color: var(--text-muted); font-size: 0.75rem;">Karavotlar yo\'q</em>'}</td>
              <td>
                <button type="button" class="btn-super btn-super-outline" style="padding: 2px 6px; font-size: 0.72rem; color: var(--danger);" onclick="window.FMH_Super.deleteRoom(${jsArg(r.id)})" title="Xonani o'chirish">
                  <i class="fas fa-trash"></i>
                </button>
              </td>
            </tr>
          `);
        });
      });
      tbody.innerHTML = rows.join('');
    }
  }

  async function handleAddRoom(e) {
    if (e) e.preventDefault();
    const floor = Number(document.getElementById('new-room-floor').value);
    const roomNumber = document.getElementById('new-room-number').value.trim();
    const roomType = document.getElementById('new-room-type').value;

    if (!roomNumber) return;

    try {
      const res = await fetch('/api/facility/rooms', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          floor_number: floor,
          room_number: roomNumber,
          room_name_uz: `${roomNumber}-xona`,
          room_type: roomType
        })
      });
      if (res.ok) {
        showToast(`🏨 <strong>${roomNumber}-xona</strong> tizimga muvaffaqiyatli qo'shildi!`);
        document.getElementById('admin-add-room-form').reset();
        await loadMasterDatabases();
        renderAdminRoomsTab();
        renderActiveDepartment();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || "Xona qo'shishda xatolik yuz berdi", "danger");
      }
    } catch (err) {
      showToast("Server bilan bog'lanishda xatolik", "danger");
    }
  }

  async function handleAttachBed(e) {
    if (e) e.preventDefault();
    const roomId = document.getElementById('attach-bed-room-select').value;
    const bedCode = document.getElementById('attach-bed-code').value.trim();
    const dailyRate = Number(document.getElementById('attach-bed-rate').value) || listedRate('statsionar_shared');

    if (!roomId || !bedCode) return;

    try {
      const res = await fetch('/api/facility/beds', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          room_id: roomId,
          bed_number: bedCode,
          bed_id: bedCode.startsWith('BED-') ? bedCode : `BED-${bedCode}`,
          daily_rate: dailyRate
        })
      });
      if (res.ok) {
        showToast(`🛏️ <strong>${bedCode}</strong> karavot muvaffaqiyatli biriktirildi!`);
        document.getElementById('admin-attach-bed-form').reset();
        document.getElementById('attach-bed-rate').value = listedRate('statsionar_shared');
        await loadMasterDatabases();
        renderAdminRoomsTab();
        renderActiveDepartment();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || "Karavot biriktirishda xatolik", "danger");
      }
    } catch (err) {
      showToast("Server bilan bog'lanishda xatolik", "danger");
    }
  }

  async function detachBed(bedId) {
    const okDetach = await fmhConfirm({
      title: "Karavotni Ajratish",
      message: `Haqiqatan ham <strong>${bedId}</strong> karavotni xonadan ajratmoqchimisiz (Detach)?`,
      confirmText: "Ajratish",
      cancelText: "Bekor Qilish",
      type: 'warning'
    });
    if (!okDetach) return;

    try {
      const res = await fetch(`/api/facility/beds/${encodeURIComponent(bedId)}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        showToast(`🗑️ <strong>${bedId}</strong> karavot ajratildi!`, 'info');
        await loadMasterDatabases();
        renderAdminRoomsTab();
        renderActiveDepartment();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || "Karavotni ajratishda xatolik", "danger");
      }
    } catch (err) {
      showToast("Server bilan bog'lanishda xatolik", "danger");
    }
  }

  async function deleteRoom(roomId) {
    const okRoom = await fmhConfirm({
      title: "Xonani O'chirish",
      message: `Haqiqatan ham ushbu xonani o'chirmoqchimisiz?`,
      confirmText: "O'chirish",
      cancelText: "Bekor Qilish",
      type: 'danger'
    });
    if (!okRoom) return;

    try {
      const res = await fetch(`/api/facility/rooms/${encodeURIComponent(roomId)}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        showToast("🗑️ Xona tizimdan o'chirildi!", "info");
        await loadMasterDatabases();
        renderAdminRoomsTab();
        renderActiveDepartment();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || "Xonani o'chirishda xatolik", "danger");
      }
    } catch (err) {
      showToast("Server bilan bog'lanishda xatolik", "danger");
    }
  }

  // --- 3. STAFF MANAGEMENT (HIRE / FIRE) ---
  async function renderAdminStaffTab() {
    const tbody = document.getElementById('admin-staff-table-body');
    if (!tbody) return;

    try {
      const res = await fetch('/api/staff');
      if (res.ok) {
        const staffList = await res.json();
        staffRoster = staffList;
        if (staffList.length === 0) {
          tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">Xodimlar mavjud emas</td></tr>`;
          return;
        }

        tbody.innerHTML = staffList.map(s => {
          const staffId = s.id;
          const name = s.full_name || s.name;
          const role = s.role;
          const spec = s.specialty || '—';
          // The list carries salary_base (to HR, accounting and the owner);
          // 'salary' never existed, so this column always showed a dash.
          const sal = s.salary_base != null && s.salary_base !== '' ? formatUZS(s.salary_base) : '—';

          return `
            <tr>
              <td><strong>${esc(name)}</strong><br><small style="color: var(--text-muted);">${esc(s.phone || '')}</small></td>
              <td><span class="pill-status pill-available">${esc(role)}</span></td>
              <td>${esc(spec)}</td>
              <td><strong style="color: var(--warning);">${sal}</strong></td>
              <td>
                <button type="button" class="btn-super btn-super-outline" style="padding: 2px 8px; font-size: 0.72rem; color: var(--danger);" onclick="window.FMH_Super.fireStaff(${jsArg(staffId)}, ${jsArg(name || '')})" title="Ishdan bo'shatish">
                  <i class="fas fa-user-minus"></i> Bo'shatish
                </button>
              </td>
            </tr>
          `;
        }).join('');
        renderHRDepartment();
      }
    } catch (e) {
      console.error("Error loading staff:", e);
    }
  }

  async function handleHireStaff(e) {
    if (e) e.preventDefault();
    const name = document.getElementById('hire-staff-name').value.trim();
    const role = document.getElementById('hire-staff-role').value;
    const specialty = document.getElementById('hire-staff-specialty').value.trim();
    const phone = document.getElementById('hire-staff-phone').value.trim();
    // POST /api/staff reads base_salary; 'salary' was ignored and the blank
    // field showed 10 000 000. Blank stays blank (the server stores 0) and
    // a bad amount comes back as a refusal.
    const salary = document.getElementById('hire-staff-salary').value.trim();
    const shift = document.getElementById('hire-staff-shift').value;

    if (!name || !specialty || !phone) return;

    try {
      const res = await fetch('/api/staff', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          full_name: name,
          role: role,
          specialty: specialty,
          phone: phone,
          base_salary: salary,
          shift_type: shift,
          status: 'active'
        })
      });

      if (res.ok) {
        showToast(`🎉 <strong>${esc(name)}</strong> muvaffaqiyatli ishga qabul qilindi (Rasmiylashtirildi)!`);
        document.getElementById('admin-hire-staff-form').reset();
        await initSampleStaffRoster();
        renderAdminStaffTab();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || "Xodimni qabul qilishda xatolik", "danger");
      }
    } catch (err) {
      showToast("Server bilan bog'lanishda xatolik", "danger");
    }
  }

  async function fireStaff(staffId, staffName) {
    const okFire = await fmhConfirm({
      title: "Xodimni Bo'shatish",
      message: `Haqiqatan ham <strong>${esc(staffName)}</strong>ni ishdan bo'shatmoqchimisiz?`,
      confirmText: "Bo'shatish",
      cancelText: "Bekor Qilish",
      type: 'danger'
    });
    if (!okFire) return;

    try {
      const res = await fetch(`/api/staff/${encodeURIComponent(staffId)}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        showToast(`👋 <strong>${esc(staffName)}</strong> xodimlar safidan bo'shatildi!`, 'danger');
        await initSampleStaffRoster();
        renderAdminStaffTab();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || "Xodimni bo'shatishda xatolik", "danger");
      }
    } catch (err) {
      showToast("Server bilan bog'lanishda xatolik", "danger");
    }
  }

  // --- 4. USER ACCOUNTS & RBAC ---
  //
  // The console offered 6 of the 13 roles from a hand-typed list, could only
  // create and delete, and put names straight into innerHTML. Roles now come
  // from GET /api/users/roles (permissions.ROLES), accounts can be edited,
  // blocked and given a one-time password, and every value is escaped.
  function esc(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // A value passed to an inline onclick="f(...)" must be a JS string literal,
  // not just HTML-escaped text: the browser decodes &#39; back to ' before the
  // handler runs, so a staff or room id containing a quote used to end the
  // string and run the rest as script with the viewer's (superadmin) rights.
  // JSON.stringify makes a safe literal; esc() keeps it inside the attribute.
  function jsArg(v) {
    return esc(JSON.stringify(String(v)));
  }

  let adminRoles = [];
  let adminUsers = [];
  let adminStaffOptions = [];

  async function readError(res, fallback) {
    const err = await res.json().catch(() => ({}));
    return err.error || fallback;
  }

  function roleLabel(key) {
    const r = adminRoles.find(x => x.key === key);
    return r ? r.label : key;
  }

  async function loadAdminRoles() {
    try {
      const res = await fetch('/api/users/roles');
      if (!res.ok) return;
      adminRoles = await res.json();
      const opts = adminRoles.map(r =>
        `<option value="${esc(r.key)}">${esc(r.label)} (${esc(r.key)})</option>`).join('');
      const reg = document.getElementById('reg-role');
      if (reg) {
        const keep = reg.value;
        reg.innerHTML = `<option value="">— Rolni tanlang —</option>` + opts;
        if (keep && adminRoles.some(r => r.key === keep)) reg.value = keep;
      }
      const edit = document.getElementById('user-edit-role');
      if (edit) edit.innerHTML = opts;
    } catch (e) {
      console.error('Error loading roles:', e);
    }
  }

  // /api/staff lists active staff only. Rebuilding the picker used to drop
  // the option for a user linked to an employee who has since been
  // deactivated, so the picker fell back to "Bog'lanmagan" and the next
  // save unlinked the account. The current link is always kept as an
  // option. The load is a shared promise so the edit form waits for it
  // instead of being rebuilt underneath (the load was not awaited).
  let adminStaffLoad = null;
  function keepStaffOption(el, value) {
    if (!el || !value) return;
    if (!Array.from(el.options).some(o => o.value === value)) {
      el.insertAdjacentHTML('beforeend', `<option value="${esc(value)}">${esc(value)} (faol emas)</option>`);
    }
    el.value = value;
  }

  function loadAdminStaffOptions() {
    adminStaffLoad = (async () => {
      try {
        const res = await fetch('/api/staff');
        if (!res.ok) return;
        adminStaffOptions = await res.json();
        const opts = `<option value="">— Bog'lanmagan —</option>` + adminStaffOptions.map(s =>
          `<option value="${esc(s.id)}">${esc(s.full_name || s.name || s.id)} — ${esc(s.role || '')} (${esc(s.id)})</option>`).join('');
        ['reg-staff', 'user-edit-staff'].forEach(id => {
          const el = document.getElementById(id);
          if (el) { const keep = el.value; el.innerHTML = opts; el.value = keep; keepStaffOption(el, keep); }
        });
      } catch (e) {
        console.error('Error loading staff for user links:', e);
      }
    })();
    return adminStaffLoad;
  }

  let usersTableWired = false;
  function wireUsersTable(tbody) {
    if (usersTableWired) return;
    usersTableWired = true;
    // One delegated listener: ids travel in data attributes, never inside an
    // inline onclick string where a quote in an id would break out.
    tbody.addEventListener('click', (ev) => {
      const btn = ev.target.closest('button[data-user-action]');
      if (!btn) return;
      const uid = btn.getAttribute('data-uid');
      const action = btn.getAttribute('data-user-action');
      if (action === 'edit') openUserEdit(uid);
      else if (action === 'reset') resetUserPassword(uid);
      else if (action === 'delete') deleteUser(uid);
    });
  }

  async function renderAdminUsersTab() {
    const tbody = document.getElementById('admin-users-table-body');
    if (!tbody) return;
    wireUsersTable(tbody);
    if (!adminRoles.length) loadAdminRoles();
    loadAdminStaffOptions();

    try {
      const res = await fetch('/api/users');
      if (!res.ok) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--danger);">${esc(await readError(res, "Ro'yxatni yuklab bo'lmadi"))}</td></tr>`;
        return;
      }
      adminUsers = await res.json();
      if (adminUsers.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">Foydalanuvchilar mavjud emas</td></tr>`;
        return;
      }

      tbody.innerHTML = adminUsers.map(u => {
        const active = u.is_active !== false;
        const uid = esc(u.id || u.username);
        const actions = `
          <div class="user-actions">
            <button type="button" class="btn-super btn-super-outline" data-user-action="edit" data-uid="${uid}" title="Tahrirlash"><i class="fas fa-pen"></i></button>
            ${u.protected ? '<span style="font-size: 0.72rem; color: var(--text-muted); align-self: center;">Himoyalangan</span>' : `
              <button type="button" class="btn-super btn-super-outline" data-user-action="reset" data-uid="${uid}" title="Parolni tiklash"><i class="fas fa-key"></i></button>
              <button type="button" class="btn-super btn-super-outline" style="color: var(--danger);" data-user-action="delete" data-uid="${uid}" title="O'chirish"><i class="fas fa-trash"></i></button>
            `}
          </div>`;
        return `
          <tr>
            <td><strong style="color: var(--primary); font-family: var(--font-mono);">${esc(u.username)}</strong></td>
            <td><strong>${esc(u.full_name)}</strong><br><small style="color: var(--text-muted);">${esc(u.phone || '')}${u.staff_id ? ' · ' + esc(u.staff_id) : ''}</small></td>
            <td><span class="pill-status ${u.role === 'superadmin' ? 'pill-occupied' : 'pill-available'}" title="${esc(u.role)}">${esc(roleLabel(u.role))}</span></td>
            <td>${active ? '<span class="pill-status pill-available">Faol</span>' : '<span class="pill-status pill-occupied">Bloklangan</span>'}${u.must_change_password ? '<br><small style="color: var(--warning);">Parol almashtirilmagan</small>' : ''}</td>
            <td>${actions}</td>
          </tr>
        `;
      }).join('');
    } catch (e) {
      console.error("Error loading users:", e);
    }
  }

  function openModalById(id) {
    const m = document.getElementById(id);
    if (m) m.classList.add('active');
  }

  // Closes one of the user dialogs only, leaving the admin centre open
  // underneath (closeAllModals would close that too).
  function closeUserModal(id) {
    const m = document.getElementById(id);
    if (m) m.classList.remove('active');
    if (id === 'super-user-password-modal') {
      // The password is not kept anywhere once the dialog is closed.
      const v = document.getElementById('user-pw-value');
      if (v) v.value = '';
    }
  }

  function showOneTimePassword(username, password) {
    document.getElementById('user-pw-username').textContent = username || '';
    const v = document.getElementById('user-pw-value');
    v.value = password || '';
    openModalById('super-user-password-modal');
    v.focus();
    v.select();
  }

  async function copyOneTimePassword() {
    const v = document.getElementById('user-pw-value');
    if (!v || !v.value) return;
    try {
      await navigator.clipboard.writeText(v.value);
    } catch (e) {
      v.select();
      try { document.execCommand('copy'); } catch (e2) { /* the field stays selected */ }
    }
    showToast('Parol nusxalandi');
  }

  async function handleCreateUser(e) {
    if (e) e.preventDefault();
    const username = document.getElementById('reg-username').value.trim();
    const fullName = document.getElementById('reg-fullname').value.trim();
    const password = document.getElementById('reg-password').value;
    const role = document.getElementById('reg-role').value;
    const phone = document.getElementById('reg-phone').value.trim();
    const staffEl = document.getElementById('reg-staff');
    const staffId = staffEl ? staffEl.value : '';

    if (!username || !fullName || !role) {
      showToast("Login, F.I.Sh va rolni kiriting", "error");
      return;
    }

    const payload = { username: username, full_name: fullName, role: role, phone: phone };
    // Blank: the server issues a one-time password and shows it once.
    if (password) payload.password = password;
    if (staffId) payload.staff_id = staffId;

    try {
      const res = await fetch('/api/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        showToast(await readError(res, "Foydalanuvchi yaratishda xatolik"), "error");
        return;
      }
      const data = await res.json().catch(() => ({}));
      showToast(`👤 <strong>${esc(fullName)} (${esc(username)})</strong> yangi foydalanuvchi sifatida yaratildi!`);
      document.getElementById('admin-create-user-form').reset();
      if (data.temporary_password) showOneTimePassword(username, data.temporary_password);
      renderAdminUsersTab();
    } catch (err) {
      showToast("Server bilan bog'lanishda xatolik", "error");
    }
  }

  async function openUserEdit(uid) {
    const u = adminUsers.find(x => x.id === uid || x.username === uid);
    if (!u) return;
    if (!adminRoles.length) await loadAdminRoles();
    await (adminStaffLoad || loadAdminStaffOptions());
    document.getElementById('user-edit-id').value = u.id || u.username;
    document.getElementById('user-edit-username').textContent = u.username || '';
    document.getElementById('user-edit-fullname').value = u.full_name || '';
    document.getElementById('user-edit-phone').value = u.phone || '';
    const roleSel = document.getElementById('user-edit-role');
    if (u.role && !adminRoles.some(r => r.key === u.role)) {
      // A role permissions.py no longer knows: show it so it is not changed silently.
      roleSel.insertAdjacentHTML('afterbegin', `<option value="${esc(u.role)}">${esc(u.role)}</option>`);
    }
    roleSel.value = u.role || '';
    const staffSel = document.getElementById('user-edit-staff');
    staffSel.value = '';
    keepStaffOption(staffSel, u.staff_id || '');
    document.getElementById('user-edit-active').value = u.is_active === false ? '0' : '1';
    roleSel.disabled = !!u.protected;
    document.getElementById('user-edit-active').disabled = !!u.protected;
    document.getElementById('user-edit-protected-note').style.display = u.protected ? 'block' : 'none';
    openModalById('super-user-edit-modal');
  }

  async function handleUserEditSubmit(e) {
    if (e) e.preventDefault();
    const uid = document.getElementById('user-edit-id').value;
    const u = adminUsers.find(x => x.id === uid || x.username === uid);
    if (!u) return;
    // Only what changed is sent, so a protected account's role and state are
    // never part of the request.
    const payload = {};
    const fullName = document.getElementById('user-edit-fullname').value.trim();
    const phone = document.getElementById('user-edit-phone').value.trim();
    const role = document.getElementById('user-edit-role').value;
    const staffId = document.getElementById('user-edit-staff').value;
    const active = document.getElementById('user-edit-active').value === '1';
    if (fullName !== (u.full_name || '')) payload.full_name = fullName;
    if (phone !== (u.phone || '')) payload.phone = phone;
    if (staffId !== (u.staff_id || '')) payload.staff_id = staffId;
    if (!u.protected) {
      if (role !== u.role) payload.role = role;
      if (active !== (u.is_active !== false)) payload.is_active = active;
    }
    if (!Object.keys(payload).length) {
      closeUserModal('super-user-edit-modal');
      return;
    }
    if (payload.is_active === false) {
      const ok = await fmhConfirm({
        title: 'Hisobni bloklash',
        message: `<strong>${esc(u.username)}</strong> tizimga kira olmaydi va hozirgi sessiyasi yopiladi. Davom etasizmi?`,
        confirmText: 'Bloklash',
        cancelText: 'Bekor qilish',
        type: 'danger'
      });
      if (!ok) return;
    }
    try {
      const res = await fetch(`/api/users/${encodeURIComponent(uid)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        showToast(await readError(res, "Saqlab bo'lmadi"), "error");
        return;
      }
      showToast("Foydalanuvchi ma'lumotlari yangilandi");
      closeUserModal('super-user-edit-modal');
      renderAdminUsersTab();
    } catch (err) {
      showToast("Server bilan bog'lanishda xatolik", "error");
    }
  }

  async function resetUserPassword(uid) {
    const u = adminUsers.find(x => x.id === uid || x.username === uid);
    const name = u ? u.username : uid;
    const ok = await fmhConfirm({
      title: 'Parolni tiklash',
      message: `<strong>${esc(name)}</strong> uchun yangi bir martalik parol beriladi. Eski parol ishlamay qoladi va ochiq sessiyalar yopiladi.`,
      confirmText: 'Yangi parol berish',
      cancelText: 'Bekor qilish',
      type: 'warning'
    });
    if (!ok) return;
    try {
      const res = await fetch(`/api/users/${encodeURIComponent(uid)}/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}'
      });
      if (!res.ok) {
        showToast(await readError(res, "Parolni tiklab bo'lmadi"), "error");
        return;
      }
      const data = await res.json();
      showOneTimePassword(data.username || name, data.temporary_password);
      renderAdminUsersTab();
    } catch (err) {
      showToast("Server bilan bog'lanishda xatolik", "error");
    }
  }

  async function deleteUser(userId) {
    const okUser = await fmhConfirm({
      title: "Foydalanuvchini O'chirish",
      message: "Haqiqatan ham ushbu foydalanuvchini o'chirmoqchimisiz? (Vaqtincha to'xtatish uchun \"Bloklangan\" holatidan foydalaning.)",
      confirmText: "O'chirish",
      cancelText: "Bekor Qilish",
      type: 'danger'
    });
    if (!okUser) return;

    try {
      const res = await fetch(`/api/users/${encodeURIComponent(userId)}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        showToast("🗑️ Foydalanuvchi tizimdan o'chirildi!", "info");
        renderAdminUsersTab();
      } else {
        showToast(await readError(res, "Foydalanuvchini o'chirishda xatolik"), "error");
      }
    } catch (err) {
      showToast("Server bilan bog'lanishda xatolik", "error");
    }
  }

  // --- 5. AUDIT LOG VIEWER (read-only, GET /api/audit) ---
  const AUDIT_ACTION_LABELS = {
    CREATE: 'Yaratildi',
    UPDATE: "O'zgartirildi",
    DELETE: "O'chirildi",
    CHECK_IN: 'Joylashtirildi',
    CHECK_OUT: 'Chiqarildi',
    TRANSFER: "Ko'chirildi",
    PAYMENT_RECEIVED: "To'lov",
    LOGIN: 'Kirdi',
    LOGIN_FAILED: 'Kirish xatosi',
    LOGOUT: 'Chiqdi',
    ACCESS_DENIED: 'Rad etildi',
    PASSWORD_CHANGED: "Parol o'zgardi"
  };
  const auditState = { offset: 0, total: 0, facetsLoaded: false, busy: false };

  function auditFilters() {
    const val = id => (document.getElementById(id) || {}).value || '';
    return {
      from: val('audit-from'),
      to: val('audit-to'),
      user: val('audit-user').trim(),
      entity: val('audit-entity'),
      action: val('audit-action'),
      q: val('audit-q').trim(),
      limit: val('audit-limit') || '50'
    };
  }

  async function renderAuditTab() {
    const tbody = document.getElementById('admin-audit-table-body');
    if (!tbody || auditState.busy) return;
    auditState.busy = true;
    const f = auditFilters();
    const params = new URLSearchParams();
    Object.keys(f).forEach(k => { if (f[k]) params.set(k, f[k]); });
    params.set('offset', String(auditState.offset));
    if (!auditState.facetsLoaded) params.set('facets', '1');
    try {
      const res = await fetch('/api/audit?' + params.toString());
      if (!res.ok) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--danger);">${esc(await readError(res, "Jurnalni yuklab bo'lmadi"))}</td></tr>`;
        return;
      }
      const data = await res.json();
      if (data.entities) {
        const ent = document.getElementById('audit-entity');
        ent.innerHTML = '<option value="">Barchasi</option>' +
          data.entities.map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join('');
        ent.value = f.entity;
        const act = document.getElementById('audit-action');
        act.innerHTML = '<option value="">Barchasi</option>' +
          (data.actions || []).map(x => `<option value="${esc(x)}">${esc(AUDIT_ACTION_LABELS[x] || x)}</option>`).join('');
        act.value = f.action;
        auditState.facetsLoaded = true;
      }
      auditState.total = data.total || 0;
      const rows = data.rows || [];
      tbody.innerHTML = rows.length ? rows.map(r => `
        <tr>
          <td class="audit-time">${esc(r.timestamp)}</td>
          <td><strong>${esc(r.actor || '—')}</strong><br><small style="color: var(--text-muted);">${esc(r.actor_role || '')}${r.ip ? ' · ' + esc(r.ip) : ''}</small></td>
          <td title="${esc(r.action)}">${esc(AUDIT_ACTION_LABELS[r.action] || r.action)}</td>
          <td>${esc(r.entity)}</td>
          <td style="font-family: var(--font-mono); font-size: 0.76rem;">${esc(r.entity_id)}</td>
          <td class="audit-summary">${esc(r.summary || '')}</td>
        </tr>`).join('')
        : `<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">Hech narsa topilmadi</td></tr>`;
      const limit = Number(data.limit) || 50;
      const first = rows.length ? auditState.offset + 1 : 0;
      const last = auditState.offset + rows.length;
      document.getElementById('audit-page-info').textContent =
        `${first}–${last} / ${auditState.total}`;
      document.getElementById('audit-prev').disabled = auditState.offset <= 0;
      document.getElementById('audit-next').disabled = auditState.offset + limit >= auditState.total;
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--danger);">Server bilan bog'lanishda xatolik</td></tr>`;
    } finally {
      auditState.busy = false;
    }
  }

  function searchAudit(e) {
    if (e) e.preventDefault();
    auditState.offset = 0;
    renderAuditTab();
  }

  function pageAudit(dir) {
    const limit = Number(auditFilters().limit) || 50;
    const next = auditState.offset + dir * limit;
    if (next < 0 || (dir > 0 && next >= auditState.total)) return;
    auditState.offset = next;
    renderAuditTab();
  }

  function resetAuditFilters() {
    const form = document.getElementById('admin-audit-filter-form');
    if (form) form.reset();
    searchAudit();
  }

  window.FMH_Super = {
    printCurrentInvoice,
    switchDepartment,
    switchFacilityFloor,
    exportBedsToExcel,
    printInvoice,
    showToast,
    closeAllModals,
    openBookingModal,
    handleBookingSubmit,
    deleteCurrentBooking,
    applyDurationPreset,
    openPaymentModal,
    handlePaymentSubmit,
    openVitalsModal,
    handleVitalsSubmit,
    prescribeDrug,
    prescribeDrugForPatient,
    filterPharmacyCategory,
    onPharmacySearch,
    clearPharmacySearch,
    filterTransactions,
    toggleMeal,
    toggleTheme,
    applyTheme,
    // Superadmin & RBAC
    openRoleSwitcherModal,
    switchRole,
    openSuperadminPanel,
    switchAdminTab,
    savePricingSettings,
    promptAddService,
    deleteService,
    handleAddRoom,
    handleAttachBed,
    detachBed,
    deleteRoom,
    handleHireStaff,
    fireStaff,
    handleCreateUser,
    deleteUser,
    closeUserModal,
    copyOneTimePassword,
    handleUserEditSubmit,
    searchAudit,
    pageAudit,
    resetAuditFilters
  };

  document.addEventListener('DOMContentLoaded', init);
})();
