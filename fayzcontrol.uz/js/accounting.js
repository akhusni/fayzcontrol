/**
 * Fayz Medical House — Buxgalteriya & Moliya Boshqaruv Dvigateli (Accounting Engine)
 * Features:
 * - Real-time KPI summary (Gross Revenue, Expenses, Net Profit, Debt, Kassa Balances)
 * - Inpatient Billing Ledger synced with 14 beds and bookings (FMH_FACILITY_14BEDS_STORAGE_V7)
 * - POS & Cash Flow Transaction Journal (Kirim / Chiqim)
 * - Doctor Payroll & Commission Calculations
 * - Medication Dispensation & Extra Services to Patient Bill (Ombordan hisobdan chiqarish)
 * - Cash Incasso to Bank (Kassa Inkassatsiyasi)
 * - Custom Date Range Filtering (Bugun, Kecha, Shu Hafta, Shu Oy, Custom Range)
 * - Printable Official Receipts & Invoices with itemized medications and QR Code
 * - Canvas Financial Chart Engine
 * - Native Client-Side Excel (.XLSX) Export Engine per page/tab using SheetJS
 * - Daily Z-Report Cash Closing
 */

(function () {
  'use strict';



  const STORAGE_KEY = 'FMH_ACCOUNTING_STORAGE_V9';
  const BEDS_STORAGE_KEY = 'FMH_FACILITY_14BEDS_STORAGE_V18';

  let accountingData = null;
  let currentTab = 'patients';
  let searchQuery = '';
  let statusFilter = 'all';
  let txnTypeFilter = 'all';
  let txnMethodFilter = 'all';

  // Date Range Filter State
  let dateRangeMode = 'all';
  let filterDateStart = null;
  let filterDateEnd = null;

  function getTodayISO() {
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

  function getMonthRange() {
    const d = new Date();
    const year = d.getFullYear();
    const month = d.getMonth();
    const start = new Date(year, month, 1);
    const end = new Date(year, month + 1, 0);
    const pad = (n) => String(n).padStart(2, '0');
    return {
      start: `${start.getFullYear()}-${pad(start.getMonth() + 1)}-${pad(start.getDate())}`,
      end: `${end.getFullYear()}-${pad(end.getMonth() + 1)}-${pad(end.getDate())}`,
      monthName: d.toLocaleDateString('uz-UZ', { month: 'long' })
    };
  }

  const OFFICIAL_RATES = {
    "statsionar_shared": { name: "Statsionar (1 karavot / 720 ming)", rate: 720000, desc: "2 kishilik xonada 1 ta o'rin" },
    "statsionar_full_room": { name: "Statsionar Butun Xona (1 kishi / VIP Solo)", rate: 1100000, desc: "Butun xona 1 kishi uchun (2-o'rin berilmaydi)" },
    "kunlik_statsionar": { name: "Kunlik Statsionar (Kunduzgi o'rin)", rate: 630000, desc: "Faqat kunduzgi vaqtda muolaja olish" },
    "ambulator_1": { name: "Ambulator (Kuniga 1 mahal muolaja)", rate: 310000, desc: "Kuniga 1 mahal qatnab muolaja" },
    "ambulator_2": { name: "Ambulator (Kuniga 2 mahal muolaja)", rate: 500000, desc: "Kuniga 2 mahal qatnab muolaja" }
  };

  // Format currency helper (e.g. 720 000 so'm)
  function formatUZS(amount) {
    if (isNaN(amount) || amount === null) amount = 0;
    return new Intl.NumberFormat('uz-UZ').format(Math.round(amount)) + " so'm";
  }

  function formatShortUZS(amount) {
    if (isNaN(amount) || amount === null) amount = 0;
    if (amount >= 1000000) {
      return (amount / 1000000).toFixed(1) + " mln";
    }
    if (amount >= 1000) {
      return (amount / 1000).toFixed(0) + " ming";
    }
    return amount.toString();
  }

  function esc(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Toast notification helper
  // Delegates to the shared toast in js/fmh_dialogs.js: that one announces
  // messages via aria-live, keeps errors on screen long enough to read,
  // stacks instead of erasing an unread message, and can be dismissed.
  function showToast(message, type = 'success') {
    return window.FMH_Toast(message, type);
  }

  async function init() {
    try {
      try {
        const response = await fetch('/api/accounting/data');
        if (response.ok) {
          accountingData = await response.json();
        }
      } catch (e) {}

      if (!accountingData) {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored) {
          try { accountingData = JSON.parse(stored); } catch(e) {}
        }
      }

      if (!accountingData) {
        accountingData = {
          clinic_info: {
            name: "FAYZ MEDICAL HOUSE",
            legal_name: "OOO \"FAYZ MEDIKAL SERVIS\"",
            inn: "308492019",
            mfo: "00440",
            bank_account: "20208000900540192001",
            bank_name: "ATB \"Kapitalbank\" Toshkent sh. BXM",
            address: "Toshkent shahri, Olmazor tumani, Qorasaroy ko'chasi 14-uy",
            phones: ["+998 71 200-44-00", "+998 90 999-44-00"]
          },
          patients_billing: [],
          transactions: [],
          doctors_payroll: [],
          pharmacy_stock: [],
          medication_purchases: []
        };
      }

      if (!accountingData.medication_purchases || !Array.isArray(accountingData.medication_purchases)) {
        accountingData.medication_purchases = [];
      }

      // Ensure pharmacy_stock exists
      if (!accountingData.pharmacy_stock || !Array.isArray(accountingData.pharmacy_stock) || accountingData.pharmacy_stock.length === 0) {
        accountingData.pharmacy_stock = [
          { "id": "med-1", "name": "Reamberin eritmasi (400ml)", "group": "Detoksikatsiya / Antioksidant", "stock": 85, "unit": "flakon", "unit_price": 38000, "status": "adequate" },
          { "id": "med-2", "name": "Gemodez-N eritmasi (200ml)", "group": "Detoksikatsiya", "stock": 120, "unit": "flakon", "unit_price": 25000, "status": "adequate" },
          { "id": "med-3", "name": "Meksidol inyeksiyasi (5ml №5)", "group": "Neyroprotektor", "stock": 45, "unit": "quti", "unit_price": 82000, "status": "adequate" },
          { "id": "med-4", "name": "Essensiale Forte N (ampula №5)", "group": "Gepatoprotektor", "stock": 30, "unit": "quti", "unit_price": 115000, "status": "adequate" },
          { "id": "med-5", "name": "Relanium / Diazepam (2ml №10)", "group": "Sedativ / Anksiolitik", "stock": 12, "unit": "quti", "unit_price": 65000, "status": "low" },
          { "id": "med-6", "name": "Geptral / Ademetionin (400mg №5)", "group": "Gepatoprotektor", "stock": 25, "unit": "quti", "unit_price": 240000, "status": "adequate" },
          { "id": "med-7", "name": "Vitamin C (5% 2ml №10)", "group": "Vitaminlar", "stock": 90, "unit": "quti", "unit_price": 18000, "status": "adequate" },
          { "id": "med-8", "name": "Magniy Sulfat (25% 10ml №10)", "group": "Sedativ / Antigipertenziv", "stock": 60, "unit": "quti", "unit_price": 22000, "status": "adequate" }
        ];
      }

      if (!accountingData.doctors_payroll || !Array.isArray(accountingData.doctors_payroll)) {
        accountingData.doctors_payroll = [];
      }

      // Sync with MySQL Financial Ledger, Admissions & Staff
      await syncWithLedgerAndBackend();

      const mBtn = document.getElementById('accounting-month-btn');
      if (mBtn) {
        mBtn.textContent = `Shu Oy (${new Date().toLocaleDateString('uz-UZ', { month: 'long' })})`;
      }
      const payrollTitle = document.getElementById('accounting-doctors-title');
      if (payrollTitle) {
        payrollTitle.innerHTML = `<i class="fas fa-user-md" style="color: var(--primary);"></i> Shifokorlar Oylik Maoshi va Gonorar Qayti (${new Date().toLocaleDateString('uz-UZ', { month: 'long', year: 'numeric' })})`;
      }

      setupEventListeners();
      renderAll();

      // Real-time periodic refresh every 4s
      setInterval(async () => {
        try {
          await syncWithLedgerAndBackend(false);
          renderAll();
        } catch (e) {}
      }, 4000);

      window.addEventListener('storage', (e) => {
        if (e.key === BEDS_STORAGE_KEY || e.key === STORAGE_KEY) {
          syncWithLedgerAndBackend(false);
          renderAll();
        }
      });
    } catch (e) {
      console.error("Accounting init error:", e);
    }
  }

  async function syncWithLedgerAndBackend(shouldSave = true) {
    try {
      const [ledgerRes, accRes, staffRes] = await Promise.all([
        fetch('/api/financial-ledger'),
        fetch('/api/accounting/data'),
        fetch('/api/staff')
      ]);

      if (accRes.ok) {
        const liveAcc = await accRes.json();
        if (liveAcc.transactions && Array.isArray(liveAcc.transactions)) {
          accountingData.transactions = liveAcc.transactions;
        }
        if (liveAcc.medication_purchases && Array.isArray(liveAcc.medication_purchases)) {
          accountingData.medication_purchases = liveAcc.medication_purchases;
        }
        if (liveAcc.pharmacy_stock && Array.isArray(liveAcc.pharmacy_stock)) {
          accountingData.pharmacy_stock = liveAcc.pharmacy_stock.map(m => ({
            id: m.id,
            name: m.name,
            group: m.category || m.group || 'Dori-darmon',
            category: m.category || m.group || 'Dori-darmon',
            stock: m.stock !== undefined ? Number(m.stock) : Number(m.stock_quantity || 0),
            stock_quantity: m.stock !== undefined ? Number(m.stock) : Number(m.stock_quantity || 0),
            unit: m.unit || m.form || 'dona',
            form: m.form || m.unit || 'dona',
            unit_price: Number(m.unit_price) || 0,
            standard_dosage: m.standard_dosage || '',
            min_stock_level: Number(m.min_stock_level) || 10,
            status: (m.stock !== undefined ? Number(m.stock) : Number(m.stock_quantity || 0)) <= (Number(m.min_stock_level) || 15) ? 'low' : 'adequate'
          }));
        }
      }

      if (staffRes.ok) {
        const staffList = await staffRes.json();
        if (Array.isArray(staffList)) {
          const docStaff = staffList.filter(s => s.role === 'doctor' || s.role === 'chief_doctor' || (s.specialty && s.specialty.trim() !== '') || s.full_name.toLowerCase().includes('dr'));
          accountingData.doctors_payroll = docStaff.map((d) => ({
            id: d.id,
            name: d.full_name,
            role: d.specialty || d.role || 'Shifokor',
            base_salary: d.role === 'chief_doctor' ? 12000000 : 8500000,
            commission_rate: d.role === 'chief_doctor' ? 10 : 8,
            status: 'calculated'
          }));
        }
      }

      if (ledgerRes.ok) {
        const ledgerRows = await ledgerRes.json();
        if (Array.isArray(ledgerRows)) {
          accountingData.patients_billing = ledgerRows.map(row => {
            return {
              id: row.invoice_id,
              booking_id: row.admission_id,
              bed_id: row.bed_id || 'BED-1A',
              bed_name: row.room_number ? `${row.room_number}-xona (${row.bed_code || ''})` : (row.bed_code || 'Ambulator'),
              patient_name: row.patient_name || 'Bemor',
              patient_phone: row.patient_phone || '+998 (90) --- -- --',
              patient_city: 'Toshkent sh.',
              program: row.program_type || 'Statsionar',
              package_type: row.daily_price >= 1100000 ? 'statsionar_full_room' : 'statsionar_shared',
              doctor: row.doctor_name || 'Shifokor biriktirilmagan',
              start_date: row.start_date || getTodayISO(),
              end_date: row.end_date || getOffsetDateStr(10),
              days_count: row.total_days || 10,
              daily_rate: row.daily_price || 720000,
              gross_due: Number(row.total_billed) || 0,
              discount_amount: Number(row.discount_amount) || 0,
              total_due: row.net_amount || row.total_billed,
              paid_cash: row.paid_cash || 0,
              paid_terminal: row.paid_terminal || 0,
              paid_online: row.paid_card_online || 0,
              paid_bank: 0,
              total_paid: row.total_paid || 0,
              debt_remaining: row.balance_due || 0,
              extra_services: [],
              status: row.payment_status || 'unpaid',
              created_at: row.created_at || new Date().toISOString()
            };
          });
        }
      }

      if (shouldSave) saveData();
    } catch (err) {
      console.warn("Could not sync with backend ledger:", err);
    }
  }

  function saveData() {
    if (accountingData) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(accountingData));
    }
  }

  // Synchronize with building management 14 beds bookings
  function syncWithInpatientBookings() {
    try {
      const bedsStored = localStorage.getItem(BEDS_STORAGE_KEY);
      if (!bedsStored) return;

      const bedsData = JSON.parse(bedsStored);
      if (!bedsData || !Array.isArray(bedsData)) return;

      let changed = false;

      bedsData.forEach(booking => {
        if (!booking || !booking.patient_name) return;

        // Check if patient already exists in billing
        let bill = accountingData.patients_billing.find(b => b.booking_id === String(booking.id));

        // Determine rate
        let dailyRate = 720000;
        let progName = "Statsionar (1 karavot / 720 ming)";
        let packageKey = "statsionar_shared";

        if (booking.is_full_room || (booking.program && (booking.program.includes("Butun Xona") || booking.program.includes("1.1 mln"))) || (booking.notes && booking.notes.includes("Butun xona"))) {
          dailyRate = 1100000;
          progName = "Statsionar Butun Xona (1 kishi / VIP Solo)";
          packageKey = "statsionar_full_room";
        } else if (booking.program && (booking.program.includes("Kunlik") || booking.program.includes("630 ming"))) {
          dailyRate = 630000;
          progName = "Kunlik Statsionar (Kunduzgi o'rin)";
          packageKey = "kunlik_statsionar";
        }

        // Calculate days (default 10 days or actual date range)
        let days = 10;
        if (booking.start_date && booking.end_date) {
          const d1 = new Date(booking.start_date);
          const d2 = new Date(booking.end_date);
          const diffTime = Math.abs(d2 - d1);
          days = Math.max(1, Math.ceil(diffTime / (1000 * 60 * 60 * 24)));
        }
        const totalDue = days * dailyRate;

        if (!bill) {
          const newBill = {
            id: `BILL-2026-${String(accountingData.patients_billing.length + 1).padStart(3, '0')}`,
            booking_id: String(booking.id),
            bed_id: booking.bed_id,
            bed_name: getBedName(booking.bed_id),
            patient_name: booking.patient_name,
            patient_phone: booking.patient_phone || "+998 (90) --- -- --",
            patient_city: "Toshkent sh.",
            program: progName,
            package_type: packageKey,
            doctor: booking.doctor || "Dr. Rustam Ziyayev (Bosh Narkolog)",
            start_date: booking.start_date || getTodayISO(),
            end_date: booking.end_date || getOffsetDateStr(10),
            days_count: days,
            daily_rate: dailyRate,
            total_due: totalDue,
            paid_cash: 0,
            paid_terminal: 0,
            paid_online: 0,
            paid_bank: 0,
            total_paid: 0,
            debt_remaining: totalDue,
            extra_services: [],
            status: "unpaid",
            created_at: new Date().toISOString()
          };
          accountingData.patients_billing.push(newBill);
          changed = true;
        } else {
          if (bill.patient_name !== booking.patient_name || bill.bed_id !== booking.bed_id) {
            bill.patient_name = booking.patient_name;
            bill.bed_id = booking.bed_id;
            bill.bed_name = getBedName(booking.bed_id);
            bill.doctor = booking.doctor;
            changed = true;
          }
        }
      });

      if (changed) {
        saveData();
      }
    } catch (e) {
      console.warn("Could not sync with beds storage:", e);
    }
  }

  function getBedName(bedId) {
    const cleanId = String(bedId || '').toLowerCase().trim();
    const bedNames = {
      "bed-1a": "11-xona 1A karavot",
      "bed-1b": "11-xona 1B karavot",
      "bed-2a": "12-xona 2A karavot",
      "bed-2b": "12-xona 2B karavot",
      "bed-21a": "21-xona 21A karavot",
      "bed-21b": "21-xona 21B karavot",
      "bed-22a": "22-xona 22A karavot",
      "bed-22b": "22-xona 22B karavot",
      "bed-23a": "23-xona 23A karavot",
      "bed-23b": "23-xona 23B karavot",
      "bed-24a": "24-xona 24A karavot",
      "bed-24b": "24-xona 24B karavot",
      "bed-25a": "25-xona 25A karavot",
      "bed-25b": "25-xona 25B karavot"
    };
    return bedNames[cleanId] || (bedId ? bedId : "Ambulator Qabul");
  }

  // ==========================================================================
  // DATE RANGE FILTER HELPER
  // ==========================================================================

  function isDateInRange(dateStr) {
    if (dateRangeMode === 'all') return true;
    if (!dateStr) return true;

    const d = dateStr.slice(0, 10);
    if (filterDateStart && d < filterDateStart) return false;
    if (filterDateEnd && d > filterDateEnd) return false;
    return true;
  }

  function setDateRangePreset(preset) {
    dateRangeMode = preset;
    const now = new Date();
    const todayStr = getTodayISO();

    document.querySelectorAll('.date-range-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.range === preset);
    });

    const startInput = document.getElementById('date-filter-start');
    const endInput = document.getElementById('date-filter-end');

    if (preset === 'all') {
      filterDateStart = null;
      filterDateEnd = null;
      if (startInput) startInput.value = '';
      if (endInput) endInput.value = '';
      showToast("📅 Barcha vaqtdagi ma'lumotlar ko'rsatilmoqda", "info");
    } else if (preset === 'today') {
      filterDateStart = todayStr;
      filterDateEnd = todayStr;
      if (startInput) startInput.value = todayStr;
      if (endInput) endInput.value = todayStr;
      const todayFormatted = now.toLocaleDateString('uz-UZ', { day: 'numeric', month: 'long' });
      showToast(`📅 Bugungi (${todayFormatted}) ma'lumotlar saralandi`, "info");
    } else if (preset === 'yesterday') {
      const yDate = new Date(now);
      yDate.setDate(yDate.getDate() - 1);
      const pad = n => String(n).padStart(2, '0');
      const yStr = `${yDate.getFullYear()}-${pad(yDate.getMonth() + 1)}-${pad(yDate.getDate())}`;
      filterDateStart = yStr;
      filterDateEnd = yStr;
      if (startInput) startInput.value = yStr;
      if (endInput) endInput.value = yStr;
      const yFormatted = yDate.toLocaleDateString('uz-UZ', { day: 'numeric', month: 'long' });
      showToast(`📅 Kechagi (${yFormatted}) ma'lumotlar saralandi`, "info");
    } else if (preset === 'week') {
      const wDate = new Date(now);
      wDate.setDate(wDate.getDate() - 7);
      const pad = n => String(n).padStart(2, '0');
      const wStr = `${wDate.getFullYear()}-${pad(wDate.getMonth() + 1)}-${pad(wDate.getDate())}`;
      filterDateStart = wStr;
      filterDateEnd = todayStr;
      if (startInput) startInput.value = wStr;
      if (endInput) endInput.value = todayStr;
      showToast("📅 Oxirgi 7 kunlik ma'lumotlar saralandi", "info");
    } else if (preset === 'month') {
      const mRange = getMonthRange();
      filterDateStart = mRange.start;
      filterDateEnd = mRange.end;
      if (startInput) startInput.value = mRange.start;
      if (endInput) endInput.value = mRange.end;
      showToast(`📅 ${mRange.monthName} oyi bo'yicha ma'lumotlar saralandi`, "info");
    }

    renderAll();
  }

  function applyCustomDateRange() {
    const startInput = document.getElementById('date-filter-start');
    const endInput = document.getElementById('date-filter-end');

    if (startInput && endInput && (startInput.value || endInput.value)) {
      dateRangeMode = 'custom';
      filterDateStart = startInput.value || null;
      filterDateEnd = endInput.value || null;

      document.querySelectorAll('.date-range-btn').forEach(btn => btn.classList.remove('active'));
      renderAll();
      showToast(`📅 Sana oralig'i: ${filterDateStart || '...'} — ${filterDateEnd || '...'}`, "info");
    }
  }

  function resetDateRange() {
    setDateRangePreset('all');
  }

  // ==========================================================================
  // CALCULATIONS & KPIS
  // ==========================================================================

  function calculateKPIs() {
    if (!accountingData) return;

    let totalBilled = 0;
    let totalCollected = 0;
    let totalDebt = 0;
    let totalExpense = 0;
    let cashBalance = 0;
    let terminalBalance = 0;
    let onlineBalance = 0;
    let bankBalance = 0;

    // 1. From Patient Billing (Invoices & Collections)
    (accountingData.patients_billing || []).forEach(p => {
      const inRange = isDateInRange(p.start_date || p.created_at);
      const due = Number(p.total_due) || 0;
      const paid = Number(p.total_paid) || 0;
      const debt = Number(p.debt_remaining) || 0;

      if (inRange) {
        totalBilled += due;
        totalCollected += paid;
        totalDebt += debt;
      }

      // Cumulative Balances
      cashBalance += (Number(p.paid_cash) || 0);
      terminalBalance += (Number(p.paid_terminal) || 0);
      onlineBalance += (Number(p.paid_online) || 0);
      bankBalance += (Number(p.paid_bank) || 0);
    });

    // 2. From Transactions Journal (Other non-patient incomes & all expenses)
    (accountingData.transactions || []).forEach(t => {
      const inRange = isDateInRange(t.date);
      const amt = Number(t.amount) || 0;

      if (t.type === 'income') {
        if (!t.invoice_id && !t.bill_id) {
          if (inRange) {
            totalBilled += amt;
            totalCollected += amt;
          }
          if (t.payment_method === 'cash') cashBalance += amt;
          else if (t.payment_method === 'terminal') terminalBalance += amt;
          else if (t.payment_method === 'online') onlineBalance += amt;
          else if (t.payment_method === 'bank') bankBalance += amt;
        }
      } else if (t.type === 'expense') {
        if (inRange) {
          totalExpense += amt;
        }
        if (t.payment_method === 'cash') cashBalance -= amt;
        else if (t.payment_method === 'terminal') terminalBalance -= amt;
        else if (t.payment_method === 'online') onlineBalance -= amt;
        else if (t.payment_method === 'bank') bankBalance -= amt;
      }
    });

    const netProfit = totalCollected - totalExpense;

    // Render into DOM
    document.getElementById('stat-gross-revenue').textContent = formatUZS(totalBilled);
    document.getElementById('stat-net-profit').textContent = formatUZS(netProfit);
    document.getElementById('stat-total-expenses').textContent = formatUZS(totalExpense);
    document.getElementById('stat-total-debt').textContent = formatUZS(totalDebt);
    document.getElementById('stat-cash-drawer').textContent = formatUZS(Math.max(0, cashBalance));

    // Header mini chips
    const chipCash = document.getElementById('chip-cash-val');
    const chipTerminal = document.getElementById('chip-terminal-val');
    const chipOnline = document.getElementById('chip-online-val');
    if (chipCash) chipCash.textContent = formatShortUZS(Math.max(0, cashBalance));
    if (chipTerminal) chipTerminal.textContent = formatShortUZS(Math.max(0, terminalBalance));
    if (chipOnline) chipOnline.textContent = formatShortUZS(Math.max(0, onlineBalance));

    // Update tab badges
    document.getElementById('badge-patients-count').textContent = accountingData.patients_billing.length;
    document.getElementById('badge-txns-count').textContent = accountingData.transactions.length;
    const bPharm = document.getElementById('badge-pharmacy-count');
    if (bPharm) bPharm.textContent = (accountingData.medication_purchases || []).length;
  }

  // ==========================================================================
  // RENDER TAB: PATIENTS BILLING LEDGER
  // ==========================================================================

  function renderPatientsBillingTable() {
    const tbody = document.getElementById('patients-billing-tbody');
    if (!tbody || !accountingData) return;

    let list = [...accountingData.patients_billing];

    // Filter by date range
    list = list.filter(b => isDateInRange(b.start_date || b.created_at));

    // Filter by search
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter(b => 
        (b.patient_name && b.patient_name.toLowerCase().includes(q)) ||
        (b.patient_phone && b.patient_phone.includes(q)) ||
        (b.id && b.id.toLowerCase().includes(q)) ||
        (b.doctor && b.doctor.toLowerCase().includes(q)) ||
        (b.program && b.program.toLowerCase().includes(q)) ||
        (b.bed_name && b.bed_name.toLowerCase().includes(q))
      );
    }

    // Filter by status
    if (statusFilter === 'debt') {
      list = list.filter(b => (Number(b.debt_remaining) || 0) > 0);
    } else if (statusFilter !== 'all') {
      list = list.filter(b => b.status === statusFilter);
    }

    if (list.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="9" style="text-align: center; padding: 2.5rem; color: var(--text-muted);">
            <i class="fas fa-search" style="font-size: 1.5rem; margin-bottom: 0.5rem; display: block;"></i>
            Tanlangan sana va shartlar bo'yicha bemorlar to'lov hisob-kitoblari topilmadi.
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = list.map(b => {
      let statusBadge = '';
      if (b.status === 'paid') {
        statusBadge = `<span class="badge-status badge-paid"><i class="fas fa-check-circle"></i> To'liq To'langan</span>`;
      } else if (b.status === 'partial') {
        statusBadge = `<span class="badge-status badge-partial"><i class="fas fa-adjust"></i> Qisman (${formatShortUZS(b.total_paid)})</span>`;
      } else if (b.status === 'refund_due') {
        statusBadge = `<span class="badge-status" style="background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4);"><i class="fas fa-undo"></i> Qaytarish kerak (${formatShortUZS(Math.abs(b.debt_remaining))})</span>`;
      } else if (b.status === 'refunded') {
        statusBadge = `<span class="badge-status" style="background: rgba(168, 85, 247, 0.2); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4);"><i class="fas fa-history"></i> Qaytarilgan</span>`;
      } else {
        statusBadge = `<span class="badge-status badge-unpaid"><i class="fas fa-exclamation-circle"></i> To'lanmagan</span>`;
      }

      let priceTag = `<span style="font-family: var(--font-mono); font-size: 0.72rem; color: #38bdf8; background: rgba(56, 189, 248, 0.12); padding: 2px 6px; border-radius: 4px;">${formatShortUZS(b.daily_rate)}/kun</span>`;

      let extraServicesHTML = '';
      if (b.extra_services && b.extra_services.length > 0) {
        extraServicesHTML = `
          <div style="margin-top: 4px; display: flex; flex-wrap: wrap; gap: 4px;">
            ${b.extra_services.map(s => `
              <span class="extra-service-pill" title="${s.notes || ''}">
                <i class="fas fa-plus-circle"></i> ${s.name} (${s.qty}x = +${formatShortUZS(s.total)})
              </span>
            `).join('')}
          </div>
        `;
      }

      const isRefundDue = b.status === 'refund_due' || b.debt_remaining < 0;
      const debtDisp = isRefundDue
        ? `<td class="mono-val" style="color: #fbbf24; font-weight: 700;">-${formatUZS(Math.abs(b.debt_remaining))} (Qaytarish)</td>`
        : `<td class="mono-val" style="color: ${b.debt_remaining > 0 ? 'var(--rose)' : 'var(--text-muted)'}; font-weight: 700;">${b.debt_remaining > 0 ? formatUZS(b.debt_remaining) : '— 0'}</td>`;

      const payButton = isRefundDue
        ? `<button class="btn-portal btn-outline-portal" style="padding: 4px 8px; font-size: 0.75rem; background: rgba(245, 158, 11, 0.15); color: #fbbf24; border-color: rgba(245, 158, 11, 0.4);" onclick="window.FMH_Accounting.openPaymentModal('${b.id}', true)" title="Bemorga ortiqcha to'langan pulni qaytarish (Refund Payout)">
             <i class="fas fa-undo"></i> Qaytarish
           </button>`
        : `<button class="btn-portal btn-primary-portal" style="padding: 4px 8px; font-size: 0.75rem;" onclick="window.FMH_Accounting.openPaymentModal('${b.id}')" title="To'lov Qabul Qilish">
             <i class="fas fa-hand-holding-usd"></i> To'lov
           </button>`;

      return `
        <tr>
          <td class="mono-val" style="color: var(--primary); font-weight: 700;">${b.id}</td>
          <td>
            <div class="patient-cell">
              <span class="patient-name-bold">${b.patient_name}</span>
              <span class="patient-details-sub"><i class="fas fa-phone-alt"></i> ${b.patient_phone} • ${b.patient_city || 'Toshkent'}</span>
            </div>
          </td>
          <td>
            <div style="font-weight: 600; color: var(--text-primary); display: flex; align-items: center; gap: 6px;">
              ${b.bed_name || 'Ambulator'} ${priceTag}
            </div>
            <div class="patient-details-sub">${b.program} (${b.days_count} kun)</div>
            ${extraServicesHTML}
          </td>
          <td>
            <span style="font-size: 0.8rem; color: var(--text-secondary);">${b.doctor || 'Shifokor biriktirilmagan'}</span>
          </td>
          <td class="mono-val" style="font-weight: 700; color: var(--text-primary);">
            ${formatUZS(b.total_due)}
          </td>
          <td class="mono-val" style="color: var(--emerald); font-weight: 700;">
            ${formatUZS(b.total_paid)}
          </td>
          ${debtDisp}
          <td>${statusBadge}</td>
          <td>
            <div style="display: flex; gap: 4px; align-items: center; flex-wrap: wrap;">
              ${payButton}
              <button class="btn-portal btn-outline-portal" style="padding: 4px 8px; font-size: 0.75rem; color: var(--purple); border-color: rgba(168, 85, 247, 0.4);" onclick="window.FMH_Accounting.openAddServiceModal('${b.id}')" title="Qo'shimcha Dori/Xizmat Qo'shish">
                <i class="fas fa-plus"></i> Xizmat
              </button>
              <button class="btn-portal btn-outline-portal" style="padding: 4px 8px; font-size: 0.75rem;" onclick="window.FMH_Accounting.openInvoiceReceipt('${b.id}')" title="Kvitansiya / Chek">
                <i class="fas fa-receipt"></i> Chek
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');
  }

  // ==========================================================================
  // RENDER TAB: TRANSACTION JOURNAL & POS
  // ==========================================================================

  function renderTransactionsTable() {
    const tbody = document.getElementById('transactions-tbody');
    if (!tbody || !accountingData) return;

    let list = [...accountingData.transactions];

    // Filter by date range
    list = list.filter(t => isDateInRange(t.date));

    // Filter by type
    if (txnTypeFilter !== 'all') {
      list = list.filter(t => t.type === txnTypeFilter);
    }

    // Filter by payment method
    if (txnMethodFilter !== 'all') {
      list = list.filter(t => t.payment_method === txnMethodFilter);
    }

    // Sort newest first
    list.sort((a, b) => new Date(b.date + ' ' + (b.time || '00:00')) - new Date(a.date + ' ' + (a.time || '00:00')));

    if (list.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" style="text-align: center; padding: 2.5rem; color: var(--text-muted);">
            Tanlangan sana va shartlar bo'yicha kassa operatsiyalari topilmadi.
          </td>
        </tr>
      `;
      return;
    }

    const methodLabels = {
      "cash": '<i class="fas fa-money-bill-wave" style="color: var(--emerald);"></i> Naqd Pul',
      "terminal": '<i class="fas fa-credit-card" style="color: var(--primary);"></i> Uzcard/Humo',
      "online": '<i class="fas fa-mobile-alt" style="color: var(--purple);"></i> Click / Payme',
      "bank": '<i class="fas fa-university" style="color: var(--warning);"></i> Bank O\'tkazma'
    };

    tbody.innerHTML = list.map(t => {
      const isIncome = t.type === 'income';
      let badge = isIncome 
        ? `<span class="badge-status badge-income"><i class="fas fa-arrow-down"></i> Kirim</span>`
        : `<span class="badge-status badge-expense"><i class="fas fa-arrow-up"></i> Chiqim</span>`;

      if (t.category === 'incasso') {
        badge = `<span class="badge-status badge-incasso"><i class="fas fa-university"></i> Inkassatsiya</span>`;
      }

      return `
        <tr>
          <td class="mono-val" style="color: var(--text-muted); font-size: 0.78rem;">${t.id}</td>
          <td>
            <div style="font-weight: 600; color: var(--text-primary);">${t.title}</div>
            <div class="patient-details-sub">${t.notes || ''}</div>
          </td>
          <td>${badge}</td>
          <td class="mono-val" style="font-weight: 800; font-size: 0.95rem; color: ${isIncome ? 'var(--emerald)' : 'var(--rose)'};">
            ${isIncome ? '+' : '-'}${formatUZS(t.amount)}
          </td>
          <td>
            <span class="badge-method">${methodLabels[t.payment_method] || t.payment_method}</span>
          </td>
          <td>
            <div style="font-size: 0.8rem; color: var(--text-secondary);">${t.date} ${t.time || ''}</div>
            <div class="patient-details-sub"><i class="fas fa-user-check"></i> ${t.cashier || 'Buxgalter'}</div>
          </td>
          <td>
            <button class="btn-portal btn-outline-portal" style="padding: 3px 8px; font-size: 0.75rem;" onclick="window.FMH_Accounting.printTxnReceipt('${t.id}')">
              <i class="fas fa-receipt"></i> Kvitansiya
            </button>
          </td>
        </tr>
      `;
    }).join('');
  }

  // ==========================================================================
  // RENDER TAB: DOCTOR PAYROLL & COMMISSIONS
  // ==========================================================================

  function renderDoctorsPayroll() {
    const grid = document.getElementById('doctors-payroll-grid');
    if (!grid || !accountingData) return;

    const list = Array.isArray(accountingData.doctors_payroll) ? accountingData.doctors_payroll : [];

    if (list.length === 0) {
      grid.innerHTML = `
        <div style="grid-column: 1/-1; text-align: center; padding: 3rem; color: var(--text-muted); background: var(--card-bg); border-radius: 12px; border: 1px dashed var(--border-color);">
          <i class="fas fa-user-md" style="font-size: 2.2rem; margin-bottom: 0.75rem; opacity: 0.5; color: var(--primary);"></i>
          <div style="font-size: 1rem; font-weight: 700; color: var(--text-primary); margin-bottom: 0.25rem;">Hozircha shifokorlar oylik qaydnomasi bo'sh</div>
          <div style="font-size: 0.85rem;">Kadrlar (HR) bo'limida yangi shifokorlar qo'shilgach, ularning oylik maoshi va gonorarlari avtomatik hisoblanadi.</div>
        </div>
      `;
      return;
    }

    grid.innerHTML = list.map(doc => {
      const myPatients = (accountingData.patients_billing || []).filter(p => {
        const pDoc = (p.doctor || '').toLowerCase();
        const dName = (doc.name || '').toLowerCase().replace('dr.', '').trim();
        return dName && pDoc.includes(dName);
      });

      const patientCount = myPatients.length;
      const revenueGen = myPatients.reduce((sum, p) => sum + (Number(p.total_due) || 0), 0);
      const commissionEarned = Math.round(revenueGen * ((Number(doc.commission_rate) || 0) / 100));
      const totalPayable = (Number(doc.base_salary) || 0) + commissionEarned;

      return `
        <div class="doctor-payroll-card">
          <div class="doc-card-header">
            <div class="doc-avatar"><i class="fas fa-user-md"></i></div>
            <div class="doc-info">
              <div class="doc-name">${doc.name}</div>
              <div class="doc-role">${doc.role || 'Shifokor'}</div>
            </div>
            <span class="badge-status ${doc.status === 'paid' ? 'badge-paid' : 'badge-partial'}">
              ${doc.status === 'paid' ? "To'langan" : "Hisoblangan"}
            </span>
          </div>

          <div class="doc-stats-row">
            <div class="doc-stat-item">
              <div class="label">Bemorlar Soni (Oy)</div>
              <div class="val" style="color: var(--primary);">${patientCount} ta bemor</div>
            </div>
            <div class="doc-stat-item">
              <div class="label">Klinikaga Tushum</div>
              <div class="val">${formatShortUZS(revenueGen)}</div>
            </div>
            <div class="doc-stat-item">
              <div class="label">Asosiy Oylik Maosh</div>
              <div class="val">${formatShortUZS(doc.base_salary || 0)}</div>
            </div>
            <div class="doc-stat-item">
              <div class="label">Gonorar Ulushi (${doc.commission_rate || 0}%)</div>
              <div class="val" style="color: var(--emerald);">+${formatShortUZS(commissionEarned)}</div>
            </div>
          </div>

          <div class="doc-total-payable-box">
            <div class="doc-payable-label">Jami To'lanadigan Maosh:</div>
            <div class="doc-payable-amount">${formatUZS(totalPayable)}</div>
          </div>

          <div style="display: flex; gap: 0.5rem; justify-content: flex-end;">
            <button class="btn-portal btn-success-portal" style="width: 100%;" onclick="window.FMH_Accounting.payoutDoctorSalary('${doc.id}')">
              <i class="fas fa-check-circle"></i> Oylik Maoshni To'lash (Kassadan Chiqim)
            </button>
          </div>
        </div>
      `;
    }).join('');
  }

  // ==========================================================================
  // RENDER TAB: PHARMACY & MEDICATION EXPENSES (DYNAMIC FROM DB)
  // ==========================================================================

  let medPurchasesSearchQuery = '';
  let pharmacyStockSearchQuery = '';

  function filterMedPurchases() {
    const input = document.getElementById('search-med-purchases-input');
    medPurchasesSearchQuery = input ? input.value.trim().toLowerCase() : '';
    renderMedicationPurchases();
  }

  function filterPharmacyStock() {
    const input = document.getElementById('search-pharmacy-stock-input');
    pharmacyStockSearchQuery = input ? input.value.trim().toLowerCase() : '';
    renderPharmacyInventory();
  }

  function renderMedicationPurchases() {
    const tbody = document.getElementById('med-purchases-tbody');
    if (!tbody || !accountingData) return;

    let list = Array.isArray(accountingData.medication_purchases) ? [...accountingData.medication_purchases] : [];

    // Filter by date range preset
    list = list.filter(p => isDateInRange(p.purchase_date || p.created_at));

    // Dynamic period totals for Tab 5 KPI cards
    const periodExpense = list.reduce((sum, p) => sum + (Number(p.total_price) || 0), 0);
    const periodPurchasesCount = list.length;

    // Filter by search query
    if (medPurchasesSearchQuery) {
      const q = medPurchasesSearchQuery;
      list = list.filter(p =>
        (p.medication_name && p.medication_name.toLowerCase().includes(q)) ||
        (p.category && p.category.toLowerCase().includes(q)) ||
        (p.supplier_name && p.supplier_name.toLowerCase().includes(q)) ||
        (p.invoice_number && p.invoice_number.toLowerCase().includes(q)) ||
        (p.notes && p.notes.toLowerCase().includes(q))
      );
    }

    // Sort newest date first
    list.sort((a, b) => new Date(b.purchase_date || b.created_at) - new Date(a.purchase_date || a.created_at));

    // Update KPI card elements
    const kpiPeriodExp = document.getElementById('pharm-period-expense');
    if (kpiPeriodExp) kpiPeriodExp.textContent = formatUZS(periodExpense);

    const kpiPurchasesCount = document.getElementById('pharm-total-purchases');
    if (kpiPurchasesCount) kpiPurchasesCount.textContent = `${periodPurchasesCount} ta partiya`;

    const kpiExpenseSub = document.getElementById('pharm-expense-sub');
    if (kpiExpenseSub) {
      kpiExpenseSub.textContent = dateRangePreset === 'all' ? "Barcha davrlar bo'yicha jami xarajat" : "Tanlangan oraliq bo'yicha dori xarajatlari";
    }

    const badgeCount = document.getElementById('badge-pharmacy-count');
    if (badgeCount) badgeCount.textContent = (accountingData.medication_purchases || []).length;

    if (list.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="9" style="text-align: center; padding: 2.5rem; color: var(--text-muted);">
            <i class="fas fa-pills" style="font-size: 1.8rem; margin-bottom: 0.5rem; display: block; opacity: 0.5; color: var(--primary);"></i>
            ${medPurchasesSearchQuery ? "Qidiruv shartlariga mos dori xaridlari topilmadi." : "Ushbu davrda dori xaridi qayd etilmagan."}<br>
            <button class="btn-portal btn-primary-portal" style="margin-top: 0.75rem; padding: 5px 14px; font-size: 0.8rem;" onclick="window.FMH_Accounting.openMedPurchaseModal()">
              <i class="fas fa-plus"></i> + Dori Xaridini Kiritish
            </button>
          </td>
        </tr>
      `;
      return;
    }

    const methodLabels = {
      "cash": '<i class="fas fa-money-bill-wave" style="color: var(--emerald);"></i> Naqd Pul',
      "cash_register": '<i class="fas fa-cash-register" style="color: var(--emerald);"></i> Kassa',
      "terminal": '<i class="fas fa-credit-card" style="color: var(--primary);"></i> Terminal',
      "card_transfer": '<i class="fas fa-credit-card" style="color: var(--primary);"></i> Karta',
      "payme_click": '<i class="fas fa-mobile-alt" style="color: var(--purple);"></i> Click/Payme',
      "online": '<i class="fas fa-mobile-alt" style="color: var(--purple);"></i> Online',
      "bank": '<i class="fas fa-university" style="color: var(--warning);"></i> Bank',
      "bank_wire": '<i class="fas fa-university" style="color: var(--warning);"></i> Bank O\'tkazma'
    };

    tbody.innerHTML = list.map(p => {
      const formattedDate = (p.purchase_date || '').slice(0, 10);
      const unitPriceDisp = formatUZS(p.unit_price);
      const totalPriceDisp = formatUZS(p.total_price);
      const qtyDisp = `${p.quantity} ${p.form || 'dona'}`;

      let supplierInfo = esc(p.supplier_name || '—');
      if (p.invoice_number) {
        supplierInfo += `<br><small class="mono-val" style="color: var(--text-muted);"><i class="fas fa-receipt"></i> ${esc(p.invoice_number)}</small>`;
      }

      const receiptBtn = p.accounting_transaction_id
        ? `<button class="btn-portal btn-outline-portal" style="padding: 2px 7px; font-size: 0.72rem;" onclick="window.FMH_Accounting.printTxnReceipt('${p.accounting_transaction_id}')" title="Kassa Cheki">
             <i class="fas fa-receipt"></i> Chek
           </button>`
        : '';

      const deleteBtn = `<button class="btn-portal btn-outline-portal" style="padding: 2px 7px; font-size: 0.72rem; color: var(--rose); border-color: rgba(244,63,94,0.3);" onclick="window.FMH_Accounting.deleteMedPurchase('${p.id}')" title="Xaridni bekor qilish">
                           <i class="fas fa-trash-alt"></i>
                         </button>`;

      return `
        <tr>
          <td class="mono-val" style="font-size: 0.8rem; color: var(--text-secondary);">${formattedDate}</td>
          <td>
            <strong>${esc(p.medication_name)}</strong>
            <div style="font-size: 0.75rem; color: var(--text-muted);">${esc(p.category || 'Dori-darmon')} • ${esc(p.form || 'dona')}</div>
          </td>
          <td class="mono-val" style="font-weight: 700; color: var(--primary);">${qtyDisp}</td>
          <td class="mono-val" style="color: var(--text-secondary);">${unitPriceDisp}</td>
          <td class="mono-val" style="font-weight: 800; color: var(--rose); font-size: 0.95rem;">-${totalPriceDisp}</td>
          <td><span class="badge-method">${methodLabels[p.payment_method] || p.payment_method}</span></td>
          <td>${supplierInfo}</td>
          <td><span style="font-size: 0.78rem; color: var(--text-secondary);"><i class="fas fa-user-check"></i> ${esc(p.recorded_by_name || 'Buxgalter')}</span></td>
          <td>
            <div style="display: flex; gap: 4px; align-items: center;">
              ${receiptBtn}
              ${deleteBtn}
            </div>
          </td>
        </tr>
      `;
    }).join('');
  }

  function renderPharmacyInventory() {
    const tbody = document.getElementById('pharmacy-stock-tbody');
    if (!tbody || !accountingData) return;

    let stockList = Array.isArray(accountingData.pharmacy_stock) ? [...accountingData.pharmacy_stock] : [];

    // Filter by stock search
    if (pharmacyStockSearchQuery) {
      const q = pharmacyStockSearchQuery;
      stockList = stockList.filter(m =>
        (m.name && m.name.toLowerCase().includes(q)) ||
        ((m.group || m.category) && (m.group || m.category).toLowerCase().includes(q))
      );
    }

    // Calculate total inventory valuation
    const allStock = Array.isArray(accountingData.pharmacy_stock) ? accountingData.pharmacy_stock : [];
    let totalValuation = 0;
    allStock.forEach(m => {
      const st = m.stock !== undefined ? Number(m.stock) : Number(m.stock_quantity || 0);
      const pr = Number(m.unit_price) || 0;
      totalValuation += st * pr;
    });

    const kpiMedsCount = document.getElementById('pharm-total-meds');
    if (kpiMedsCount) kpiMedsCount.textContent = `${allStock.length} nomdagi`;

    const kpiValuation = document.getElementById('pharm-total-valuation');
    if (kpiValuation) kpiValuation.textContent = formatUZS(totalValuation);

    if (stockList.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" style="text-align: center; padding: 2rem; color: var(--text-muted);">
            Dorilar omborida mos dori vositalari topilmadi.
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = stockList.map(item => {
      const stock = item.stock !== undefined ? Number(item.stock) : Number(item.stock_quantity || 0);
      const unitPrice = Number(item.unit_price) || 0;
      const totalVal = stock * unitPrice;
      const minStock = Number(item.min_stock_level) || 15;
      const isLow = stock <= minStock;
      const badge = isLow
        ? `<span class="badge-status badge-unpaid"><i class="fas fa-exclamation-triangle"></i> Kam qolgan</span>`
        : `<span class="badge-status badge-paid"><i class="fas fa-check-circle"></i> Yetarli</span>`;

      const unitName = item.unit || item.form || 'dona';
      const groupName = item.group || item.category || 'Dori-darmon';

      return `
        <tr>
          <td>
            <strong>${esc(item.name)}</strong>
            ${item.standard_dosage ? `<br><small style="color: var(--text-muted);">${esc(item.standard_dosage)}</small>` : ''}
          </td>
          <td>${esc(groupName)}</td>
          <td class="mono-val" style="font-weight: 700; color: ${isLow ? 'var(--rose)' : 'var(--primary)'};">${stock} ${esc(unitName)}</td>
          <td class="mono-val">${formatUZS(unitPrice)}</td>
          <td class="mono-val" style="font-weight: 700; color: var(--text-primary);">${formatUZS(totalVal)}</td>
          <td>${badge}</td>
          <td>
            <button class="btn-portal btn-outline-portal" style="padding: 2px 8px; font-size: 0.75rem;" onclick="window.FMH_Accounting.openMedPurchaseModal('${item.id}')" title="Ushbu dorini xarid qilish (Kirim)">
              <i class="fas fa-plus"></i> Xarid
            </button>
          </td>
        </tr>
      `;
    }).join('');
  }

  // ==========================================================================
  // RENDER TAB: ANALYTICS & CANVAS CHARTS
  // ==========================================================================

  function renderAnalytics() {
    renderCanvasChart();
    renderDepartmentBars();
  }

  function renderCanvasChart() {
    const canvas = document.getElementById('monthly-revenue-canvas');
    if (!canvas || !accountingData) return;

    const ctx = canvas.getContext('2d');
    const width = canvas.parentElement.clientWidth || 600;
    const height = 240;
    canvas.width = width;
    canvas.height = height;

    ctx.clearRect(0, 0, width, height);

    // Dynamic month buckets: last 4 months
    const d = new Date();
    const monthNames = ["Yan", "Fev", "Mar", "Apr", "May", "Iyun", "Iyul", "Avg", "Sen", "Okt", "Noy", "Dek"];
    const months = [];
    const incomeData = [0, 0, 0, 0];
    const expenseData = [0, 0, 0, 0];

    for (let i = 3; i >= 0; i--) {
      const past = new Date(d.getFullYear(), d.getMonth() - i, 1);
      const mIdx = past.getMonth();
      const mStr = `${past.getFullYear()}-${String(mIdx + 1).padStart(2, '0')}`;
      months.push(i === 0 ? `${monthNames[mIdx]} (Hozir)` : monthNames[mIdx]);
      
      // Calculate real income and expense for this month
      (accountingData.transactions || []).forEach(t => {
        if ((t.date || '').startsWith(mStr)) {
          const amt = Number(t.amount) || 0;
          if (t.type === 'income') incomeData[3 - i] += amt;
          else if (t.type === 'expense') expenseData[3 - i] += amt;
        }
      });

      // Also sum patient collections in this month
      (accountingData.patients_billing || []).forEach(p => {
        if ((p.start_date || p.created_at || '').startsWith(mStr)) {
          incomeData[3 - i] += (Number(p.total_paid) || 0);
        }
      });
    }

    const maxVal = Math.max(10000000, ...incomeData, ...expenseData) * 1.25;
    const chartBottom = height - 35;
    const chartTop = 20;
    const chartHeight = chartBottom - chartTop;
    const barWidth = Math.min(45, (width / months.length) / 3.5);

    // Draw Grid Lines
    ctx.strokeStyle = "rgba(255, 255, 255, 0.06)";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = chartTop + (chartHeight / 4) * i;
      ctx.beginPath();
      ctx.moveTo(40, y);
      ctx.lineTo(width - 20, y);
      ctx.stroke();

      const labelVal = (maxVal * ((4 - i) / 4) / 1000000).toFixed(1);
      ctx.fillStyle = "#64748b";
      ctx.font = "10px JetBrains Mono";
      ctx.fillText(labelVal + "M", 5, y + 4);
    }

    // Draw Bars
    const groupWidth = (width - 60) / months.length;

    months.forEach((m, idx) => {
      const groupX = 60 + idx * groupWidth;

      // Income bar
      const incH = Math.max(2, (incomeData[idx] / maxVal) * chartHeight);
      const incY = chartBottom - incH;
      const incGrad = ctx.createLinearGradient(0, incY, 0, chartBottom);
      incGrad.addColorStop(0, '#38bdf8');
      incGrad.addColorStop(1, '#0284c7');
      ctx.fillStyle = incGrad;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(groupX - barWidth - 4, incY, barWidth, incH, [4, 4, 0, 0]);
      else ctx.fillRect(groupX - barWidth - 4, incY, barWidth, incH);
      ctx.fill();

      // Expense bar
      const expH = Math.max(2, (expenseData[idx] / maxVal) * chartHeight);
      const expY = chartBottom - expH;
      const expGrad = ctx.createLinearGradient(0, expY, 0, chartBottom);
      expGrad.addColorStop(0, '#f43f5e');
      expGrad.addColorStop(1, '#be123c');
      ctx.fillStyle = expGrad;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(groupX + 4, expY, barWidth, expH, [4, 4, 0, 0]);
      else ctx.fillRect(groupX + 4, expY, barWidth, expH);
      ctx.fill();

      // Month Label
      ctx.fillStyle = "#94a3b8";
      ctx.font = "11px Outfit";
      ctx.textAlign = "center";
      ctx.fillText(m, groupX, chartBottom + 20);
    });
  }

  function renderDepartmentBars() {
    const container = document.getElementById('dept-bars-container');
    if (!container || !accountingData) return;

    let statsionarAmt = 0;
    let kunlikAmt = 0;
    let ambulatorAmt = 0;
    let pharmacyAmt = 0;

    (accountingData.patients_billing || []).forEach(p => {
      const prog = (p.program || '').toLowerCase();
      const due = Number(p.total_due) || 0;
      if (prog.includes('kunlik') || prog.includes('630')) {
        kunlikAmt += due;
      } else if (prog.includes('ambulator') || prog.includes('310') || prog.includes('500')) {
        ambulatorAmt += due;
      } else {
        statsionarAmt += due;
      }

      (p.extra_services || []).forEach(s => {
        pharmacyAmt += Number(s.total) || 0;
      });
    });

    const totalAll = statsionarAmt + kunlikAmt + ambulatorAmt + pharmacyAmt;
    const calcPct = (amt) => totalAll > 0 ? Math.round((amt / totalAll) * 100) : 0;

    const depts = [
      { name: "Statsionar Davolanish (720 ming / 1.1 mln)", amount: statsionarAmt, color: "#38bdf8", pct: calcPct(statsionarAmt) },
      { name: "Kunlik Statsionar (630 ming / kun)", amount: kunlikAmt, color: "#10b981", pct: calcPct(kunlikAmt) },
      { name: "Ambulator Muolajalar (310 ming & 500 ming)", amount: ambulatorAmt, color: "#a855f7", pct: calcPct(ambulatorAmt) },
      { name: "Farmakologiya & Qo'shimcha Xizmatlar", amount: pharmacyAmt, color: "#f59e0b", pct: calcPct(pharmacyAmt) }
    ];

    container.innerHTML = depts.map(d => {
      return `
        <div class="dept-bar-item">
          <div class="dept-bar-labels">
            <span style="color: #ffffff;">${d.name}</span>
            <span style="font-family: var(--font-mono); color: ${d.color};">${formatUZS(d.amount)} (${d.pct}%)</span>
          </div>
          <div class="dept-progress-bg">
            <div class="dept-progress-fill" style="width: ${d.pct}%; background: ${d.color};"></div>
          </div>
        </div>
      `;
    }).join('');
  }

  // ==========================================================================
  // OFFICIAL INVOICE & RECEIPT (MODAL & PRINT)
  // ==========================================================================

  function openInvoiceReceipt(billId) {
    const bill = accountingData.patients_billing.find(b => b.id === billId);
    if (!bill) return;

    const modal = document.getElementById('invoice-receipt-modal');
    const content = document.getElementById('invoice-receipt-content');
    if (!modal || !content) return;

    const clinic = accountingData.clinic_info;
    const now = new Date();
    const dateFormatted = `${now.getDate().toString().padStart(2, '0')}.${(now.getMonth() + 1).toString().padStart(2, '0')}.${now.getFullYear()}`;

    // Itemized table rows
    let itemRows = `
      <tr>
        <td>1</td>
        <td><strong>${bill.program}</strong><br><small style="color: #64748b;">${bill.bed_name} • Shifokor nazorati, muolajalar va parhez taomnoma</small></td>
        <td style="text-align: center; font-weight: 700;">${bill.days_count} kun</td>
        <td style="text-align: right;">${formatUZS(bill.daily_rate)}</td>
        <td style="text-align: right; font-weight: 700;">${formatUZS(bill.days_count * bill.daily_rate)}</td>
      </tr>
    `;

    if (bill.extra_services && bill.extra_services.length > 0) {
      bill.extra_services.forEach((s, i) => {
        itemRows += `
          <tr>
            <td>${i + 2}</td>
            <td><strong>${s.name}</strong><br><small style="color: #64748b;">Qo'shimcha tayinlangan muolaja / dori (${s.notes || 'Shifokor ko\'rsatmasi'})</small></td>
            <td style="text-align: center; font-weight: 700;">${s.qty} ta</td>
            <td style="text-align: right;">${formatUZS(s.unit_price)}</td>
            <td style="text-align: right; font-weight: 700; color: #a855f7;">${formatUZS(s.total)}</td>
          </tr>
        `;
      });
    }

    content.innerHTML = `
      <div class="invoice-preview-container">
        <div class="invoice-header-row">
          <div>
            <div class="inv-brand-name">${clinic.name}</div>
            <div class="inv-brand-details">
              <strong>${clinic.legal_name}</strong><br>
              STIR (INN): ${clinic.inn} • MFO: ${clinic.mfo}<br>
              H/R: ${clinic.bank_account}<br>
              ${clinic.bank_name}<br>
              Tel: ${clinic.phones.join(', ')}<br>
              Manzil: ${clinic.address}
            </div>
          </div>
          <div class="inv-title-badge">
            <div class="inv-doc-title">TO'LOV KVITANSIYASI</div>
            <div class="inv-doc-num">№ ${bill.id}</div>
            <div style="font-size: 0.78rem; color: #64748b; margin-top: 4px;">Sana: ${dateFormatted}</div>
          </div>
        </div>

        <div class="inv-meta-grid">
          <div class="inv-meta-col">
            <div class="title">Bemor Ma'lumotlari:</div>
            <div class="name">${bill.patient_name}</div>
            <div style="font-size: 0.8rem; color: #475569;">Tel: ${bill.patient_phone}</div>
            <div style="font-size: 0.8rem; color: #475569;">Manzil: ${bill.patient_city || 'Toshkent'}</div>
          </div>
          <div class="inv-meta-col">
            <div class="title">Muolaja / Tarif Paketi:</div>
            <div style="font-weight: 700; color: #0f172a;">${bill.program}</div>
            <div style="font-size: 0.8rem; color: #475569;">Joy: ${bill.bed_name || 'Ambulator'}</div>
            <div style="font-size: 0.8rem; color: #475569;">Davomiyligi: ${bill.days_count} kun (${bill.start_date} — ${bill.end_date})</div>
            <div style="font-size: 0.8rem; color: #475569;">Mas'ul shifokor: ${bill.doctor}</div>
          </div>
        </div>

        <table class="inv-table">
          <thead>
            <tr>
              <th>№</th>
              <th>Xizmat / Muolaja / Dori Ta'rifi</th>
              <th style="text-align: center;">Miqdori</th>
              <th style="text-align: right;">Birlik Narxi (UZS)</th>
              <th style="text-align: right;">Jami (UZS)</th>
            </tr>
          </thead>
          <tbody>
            ${itemRows}
          </tbody>
        </table>

        <div class="inv-total-box">
          ${Number(bill.discount_amount) > 0 ? `
          <div class="inv-total-row">
            <span>Hisoblangan Summa (chegirmagacha):</span>
            <span style="font-weight: 700;">${formatUZS(bill.gross_due || bill.total_due)}</span>
          </div>
          <div class="inv-total-row">
            <span>Chegirma${bill.gross_due ? ` (${Math.round(bill.discount_amount / bill.gross_due * 100)}%)` : ''}:</span>
            <span style="font-weight: 700; color: #dc2626;">-${formatUZS(bill.discount_amount)}</span>
          </div>` : ''}
          <div class="inv-total-row">
            <span>${Number(bill.discount_amount) > 0 ? "To'lanishi kerak (chegirmadan keyin):" : 'Hisoblangan Jami Summa:'}</span>
            <span style="font-weight: 700;">${formatUZS(bill.total_due)}</span>
          </div>
          <div class="inv-total-row">
            <span>To'langan Summa (Fakt):</span>
            <span style="font-weight: 700; color: #059669;">${formatUZS(bill.total_paid)}</span>
          </div>
          <div class="inv-total-row grand-total">
            <span>Qoldiq Qarzdorlik:</span>
            <span>${formatUZS(bill.debt_remaining)}</span>
          </div>
        </div>

        <div class="inv-footer-stamps">
          <div class="inv-stamp-mockup">
            <i class="fas fa-stamp" style="font-size: 1.8rem;"></i>
            <div>
              <div>FAYZ MEDICAL HOUSE</div>
              <div style="font-size: 0.65rem; color: #0369a1;">TO'LOV QABUL QILINDI • M.O'.</div>
            </div>
          </div>

          <div style="text-align: right;">
            <div>Kassir-Buxgalter: ____________________ / Dilnoza R.</div>
            <div style="margin-top: 6px;">Bemor (Vakil): ____________________ / ${bill.patient_name.split(' ')[0]}</div>
          </div>
        </div>
      </div>
    `;

    modal.classList.add('active');
  }

  function printTxnReceipt(txnId) {
    const t = accountingData.transactions.find(x => x.id === txnId);
    if (!t) return;

    const modal = document.getElementById('invoice-receipt-modal');
    const content = document.getElementById('invoice-receipt-content');
    if (!modal || !content) return;

    const clinic = accountingData.clinic_info;

    content.innerHTML = `
      <div class="invoice-preview-container" style="max-width: 480px; padding: 1.5rem;">
        <div style="text-align: center; border-bottom: 1px dashed #94a3b8; padding-bottom: 1rem; margin-bottom: 1rem;">
          <div class="inv-brand-name" style="font-size: 1.25rem;">${clinic.name}</div>
          <div style="font-size: 0.75rem; color: #64748b;">${clinic.legal_name} • INN: ${clinic.inn}</div>
          <div style="font-size: 0.8rem; font-weight: 700; color: #0f172a; margin-top: 0.5rem;">
            ${t.category === 'incasso' ? 'INKASSATSIYA DALOLATNOMASI' : 'KASSA KVITANSIYASI'} № ${t.id}
          </div>
        </div>

        <div style="display: flex; flex-direction: column; gap: 0.5rem; font-size: 0.85rem; margin-bottom: 1rem;">
          <div style="display: flex; justify-content: space-between;">
            <span style="color: #64748b;">Operatsiya:</span>
            <strong>${t.category === 'incasso' ? 'INKASSATSIYA (Bankka topshirildi)' : (t.type === 'income' ? 'KIRIM (Tushum)' : 'CHIQIM (Xarajat)')}</strong>
          </div>
          <div style="display: flex; justify-content: space-between;">
            <span style="color: #64748b;">Tavsif:</span>
            <span style="text-align: right; font-weight: 600;">${t.title}</span>
          </div>
          <div style="display: flex; justify-content: space-between;">
            <span style="color: #64748b;">To'lov Usuli:</span>
            <strong>${t.payment_method.toUpperCase()}</strong>
          </div>
          <div style="display: flex; justify-content: space-between;">
            <span style="color: #64748b;">Sana / Vaqt:</span>
            <span>${t.date} ${t.time || ''}</span>
          </div>
          <div style="display: flex; justify-content: space-between;">
            <span style="color: #64748b;">Kassir / Mas'ul:</span>
            <span>${t.cashier || 'Buxgalter'}</span>
          </div>
        </div>

        <div style="border-top: 2px solid #0f172a; border-bottom: 2px solid #0f172a; padding: 0.75rem 0; margin-bottom: 1rem; display: flex; justify-content: space-between; align-items: center;">
          <span style="font-weight: 800; font-size: 1.1rem;">SUMMA:</span>
          <span style="font-family: var(--font-mono); font-weight: 800; font-size: 1.25rem; color: #0284c7;">
            ${formatUZS(t.amount)}
          </span>
        </div>

        <div style="text-align: center; font-size: 0.75rem; color: #64748b;">
          Sog'ligingiz biz uchun eng oliy qadriyat!<br>
          24/7 Shoshilinch aloqa: +998 (90) 372-03-03
        </div>
      </div>
    `;

    modal.classList.add('active');
  }

  // ==========================================================================
  // PAYMENT ACCEPTANCE MODAL
  // ==========================================================================

  function openPaymentModal(billId, isRefund = false) {
    const bill = accountingData.patients_billing.find(b => b.id === billId);
    if (!bill) return;

    const modal = document.getElementById('accept-payment-modal');
    if (!modal) return;

    const refundMode = isRefund || bill.status === 'refund_due' || bill.debt_remaining < 0;

    document.getElementById('pay-bill-id').value = bill.id;
    document.getElementById('pay-patient-name').value = bill.patient_name;
    // The cashier was shown only the net, with nothing to say a discount had
    // been applied at reception, so the sum looked wrong against the tariff.
    const payDiscount = Number(bill.discount_amount) || 0;
    document.getElementById('pay-total-due').value = payDiscount > 0
      ? `${formatUZS(bill.total_due)}  (${formatUZS(bill.gross_due)} - ${formatUZS(payDiscount)} chegirma)`
      : formatUZS(bill.total_due);
    document.getElementById('pay-already-paid').value = formatUZS(bill.total_paid);
    document.getElementById('pay-debt-remaining').value = refundMode 
      ? `-${formatUZS(Math.abs(bill.debt_remaining))} (Qaytarish kerak)` 
      : formatUZS(bill.debt_remaining);

    const titleEl = modal.querySelector('.modal-title') || modal.querySelector('h3');
    const submitBtn = modal.querySelector('button[type="submit"]');

    if (refundMode) {
      if (titleEl) titleEl.innerHTML = `<i class="fas fa-undo" style="color: #fbbf24;"></i> Bemorga Mablag'ni Qaytarish (Refund Payout)`;
      if (submitBtn) {
        submitBtn.innerHTML = `<i class="fas fa-undo"></i> Qaytarishni Tasdiqlash`;
        submitBtn.style.background = 'linear-gradient(135deg, #d97706, #f59e0b)';
      }
      document.getElementById('pay-amount-input').value = Math.abs(bill.debt_remaining) || '';
      document.getElementById('pay-notes-input').value = `Muddatidan oldin chiqish munosabati bilan bemorga qaytarildi (Refund)`;
    } else {
      if (titleEl) titleEl.innerHTML = `<i class="fas fa-hand-holding-usd" style="color: var(--emerald);"></i> To'lov Qabul Qilish`;
      if (submitBtn) {
        submitBtn.innerHTML = `<i class="fas fa-check"></i> To'lovni Tasdiqlash`;
        submitBtn.style.background = '';
      }
      document.getElementById('pay-amount-input').value = bill.debt_remaining > 0 ? bill.debt_remaining : '';
      document.getElementById('pay-notes-input').value = '';
    }

    modal.dataset.isRefund = refundMode ? 'true' : 'false';
    modal.classList.add('active');
  }

  async function handlePaymentSubmit(e) {
    e.preventDefault();
    const modal = document.getElementById('accept-payment-modal');
    const isRefund = modal && modal.dataset.isRefund === 'true';
    const billId = document.getElementById('pay-bill-id').value;
    let rawAmount = Number(document.getElementById('pay-amount-input').value);
    const method = document.getElementById('pay-method-select').value;
    const notes = document.getElementById('pay-notes-input').value.trim();

    if (!billId || isNaN(rawAmount) || rawAmount === 0) {
      showToast("Iltimos, to'g'ri to'lov summasini kiriting!", 'warning');
      return;
    }

    const bill = accountingData.patients_billing.find(b => b.id === billId);
    if (!bill) return;

    // Signed payment: negative if refund payout, positive if income
    const amount = isRefund ? -Math.abs(rawAmount) : Math.abs(rawAmount);

    // Send POST to /api/payments
    try {
      const res = await fetch('/api/payments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          invoice_id: bill.id,
          amount: amount,
          payment_method: method,
          account_destination: method === 'cash' ? 'kassa' : (method === 'terminal' ? 'terminal_bank' : 'click_payme_merchant'),
          notes: notes || (isRefund ? `Bemorga qaytarish (Refund: ${method.toUpperCase()})` : `To'lov qabul qilindi (${method.toUpperCase()})`),
          payment_date: getTodayISO()
        })
      });
      if (res.ok) {
        if (isRefund) {
          showToast(`💸 ${bill.patient_name} uchun ${formatUZS(Math.abs(amount))} qaytarish kassa jurnaliga kiritildi!`, 'info');
        } else {
          showToast(`✅ ${bill.patient_name} uchun ${formatUZS(amount)} to'lov muvaffaqiyatli qabul qilindi!`, 'success');
        }
      }
    } catch (err) {
      console.warn("Payment offline save:", err);
    }

    closeAllModals();
    await syncWithLedgerAndBackend(false);
    renderAll();
  }

  // ==========================================================================
  // ADD EXTRA MEDICATION / SERVICE TO PATIENT BILL & DEDUCT PHARMACY STOCK
  // ==========================================================================

  function openAddServiceModal(billId) {
    const bill = accountingData.patients_billing.find(b => b.id === billId);
    if (!bill) return;

    const modal = document.getElementById('add-service-modal');
    if (!modal) return;

    document.getElementById('addsvc-bill-id').value = bill.id;
    document.getElementById('addsvc-patient-name').value = `${bill.patient_name} (${bill.bed_name})`;
    document.getElementById('addsvc-qty-input').value = 1;
    document.getElementById('addsvc-notes-input').value = '';

    updateAddServiceCalculation();
    modal.classList.add('active');
  }

  function updateAddServiceCalculation() {
    const select = document.getElementById('addsvc-item-select');
    const qty = Number(document.getElementById('addsvc-qty-input').value) || 1;
    if (!select) return;

    const opt = select.selectedOptions[0];
    const unitPrice = Number(opt.dataset.price) || 0;
    const total = unitPrice * qty;

    const preview = document.getElementById('addsvc-total-preview');
    if (preview) {
      preview.textContent = formatUZS(total);
    }
  }

  function handleAddServiceSubmit(e) {
    e.preventDefault();
    const billId = document.getElementById('addsvc-bill-id').value;
    const select = document.getElementById('addsvc-item-select');
    const qty = Number(document.getElementById('addsvc-qty-input').value) || 1;
    const notes = document.getElementById('addsvc-notes-input').value.trim();

    if (!billId || !select) return;

    const bill = accountingData.patients_billing.find(b => b.id === billId);
    if (!bill) return;

    const opt = select.selectedOptions[0];
    const itemCode = select.value;
    const unitPrice = Number(opt.dataset.price) || 0;
    const itemType = opt.dataset.type || 'pharmacy';
    const rawName = opt.textContent.split('—')[0].trim();
    const lineTotal = unitPrice * qty;

    // Deduct stock if from pharmacy
    if (itemType === 'pharmacy') {
      const stockItem = accountingData.pharmacy_stock.find(m => m.id === itemCode);
      if (stockItem) {
        if (stockItem.stock < qty) {
          showToast(`Omborda yetarli qoldiq yo'q! Mavjud: ${stockItem.stock} ${stockItem.unit}`, 'danger');
          return;
        }
        stockItem.stock -= qty;
        if (stockItem.stock <= 15) {
          stockItem.status = 'low';
        }
      }
    }

    if (!bill.extra_services) {
      bill.extra_services = [];
    }

    bill.extra_services.push({
      id: `EX-${Date.now()}`,
      item_id: itemCode,
      name: rawName,
      type: itemType,
      unit_price: unitPrice,
      qty: qty,
      total: lineTotal,
      notes: notes,
      added_at: new Date().toISOString()
    });

    // Update bill total due & remaining debt
    bill.total_due += lineTotal;
    bill.debt_remaining = Math.max(0, bill.total_due - bill.total_paid);
    bill.status = bill.debt_remaining === 0 ? 'paid' : (bill.total_paid > 0 ? 'partial' : 'unpaid');

    saveData();
    closeAllModals();
    renderAll();
    showToast(`💊 <strong>${rawName}</strong> (${qty}x) ${bill.patient_name} hisobiga qo'shildi va ombordan chiqarildi!`);
  }

  // ==========================================================================
  // CASH INCASSO TO BANK (KASSA INKASSATSIYASI)
  // ==========================================================================

  function openIncassoModal() {
    const modal = document.getElementById('incasso-modal');
    if (!modal || !accountingData) return;

    let cashBalance = 0;
    accountingData.transactions.forEach(t => {
      const amt = Number(t.amount) || 0;
      if (t.payment_method === 'cash') {
        if (t.type === 'income') cashBalance += amt;
        else if (t.type === 'expense') cashBalance -= amt;
      }
    });

    cashBalance = Math.max(0, cashBalance);

    const cashDisp = document.getElementById('incasso-current-cash');
    if (cashDisp) cashDisp.textContent = formatUZS(cashBalance);

    const amtInput = document.getElementById('incasso-amount-input');
    if (amtInput) amtInput.value = cashBalance > 0 ? cashBalance : '';

    modal.classList.add('active');
  }

  async function handleIncassoSubmit(e) {
    e.preventDefault();
    const amount = Number(document.getElementById('incasso-amount-input').value);
    const bank = document.getElementById('incasso-bank-select').value;
    const collector = document.getElementById('incasso-collector-name').value.trim();
    const notes = document.getElementById('incasso-notes-input').value.trim();

    if (isNaN(amount) || amount <= 0) {
      showToast("Iltimos, to'g'ri inkassatsiya summasini kiriting!", 'warning');
      return;
    }

    // Check available cash
    let cashBalance = 0;
    accountingData.transactions.forEach(t => {
      const amt = Number(t.amount) || 0;
      if (t.payment_method === 'cash') {
        if (t.type === 'income') cashBalance += amt;
        else if (t.type === 'expense') cashBalance -= amt;
      }
    });

    if (amount > cashBalance && cashBalance > 0) {
      showToast(`Kassada buncha naqd pul mavjud emas! Hozirgi kassa naqd qoldig'i: ${formatUZS(cashBalance)}`, 'danger');
      return;
    }

    const newTxn = {
      id: `TXN-2026-${Date.now().toString().slice(-6)}`,
      type: "expense",
      category: "incasso",
      title: `Bankka naqd pul inkassatsiyasi (${bank})`,
      amount: amount,
      payment_method: "cash",
      patient_name: null,
      bill_id: null,
      date: getTodayISO(),
      time: new Date().toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' }),
      cashier: collector || "Xusnitdinov Azamat",
      notes: `${bank} bank hisob raqamiga topshirildi. ${notes}`
    };

    try {
      await fetch('/api/accounting/transaction', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newTxn)
      });
    } catch (e) {}

    accountingData.transactions.unshift(newTxn);
    saveData();
    closeAllModals();
    renderAll();
    showToast(`🏦 ${formatUZS(amount)} muvaffaqiyatli ${bank} hisob raqamiga inkassatsiya qilindi!`, 'success');
  }

  // ==========================================================================
  // CREATE NEW BILL / PATIENT ADMISSION
  // ==========================================================================

  function openNewBillModal() {
    const modal = document.getElementById('new-bill-modal');
    if (!modal) return;

    document.getElementById('newbill-patient-name').value = '';
    document.getElementById('newbill-patient-phone').value = '+998 ';
    document.getElementById('newbill-package-select').value = 'statsionar_shared';
    document.getElementById('newbill-days-input').value = 10;
    document.getElementById('newbill-advance-input').value = '';

    const docSelect = document.getElementById('newbill-doctor-select');
    if (docSelect) {
      if (accountingData.doctors_payroll && accountingData.doctors_payroll.length > 0) {
        docSelect.innerHTML = accountingData.doctors_payroll.map(d => `<option value="${d.name}">${d.name} (${d.role})</option>`).join('');
      } else {
        docSelect.innerHTML = `<option value="">— Shifokor biriktirilmagan —</option>`;
      }
    }

    updateNewBillCalculation();

    modal.classList.add('active');
  }

  function updateNewBillCalculation() {
    const pkgKey = document.getElementById('newbill-package-select').value;
    const days = Number(document.getElementById('newbill-days-input').value) || 10;
    const pkg = OFFICIAL_RATES[pkgKey] || OFFICIAL_RATES.statsionar_shared;

    const total = pkg.rate * days;
    const totalEl = document.getElementById('newbill-calc-total');
    if (totalEl) {
      totalEl.textContent = formatUZS(total);
    }
  }

  async function handleNewBillSubmit(e) {
    e.preventDefault();
    const name = document.getElementById('newbill-patient-name').value.trim();
    const phone = document.getElementById('newbill-patient-phone').value.trim();
    const pkgKey = document.getElementById('newbill-package-select').value;
    const days = Number(document.getElementById('newbill-days-input').value) || 10;
    const bedId = document.getElementById('newbill-bed-select').value;
    const doctor = document.getElementById('newbill-doctor-select').value;
    const advancePaid = Number(document.getElementById('newbill-advance-input').value) || 0;
    const method = document.getElementById('newbill-method-select').value;

    if (!name) {
      showToast("Iltimos, bemor ismini kiriting!", 'warning');
      return;
    }

    const pkg = OFFICIAL_RATES[pkgKey] || OFFICIAL_RATES.statsionar_shared;
    const totalDue = pkg.rate * days;
    const debt = Math.max(0, totalDue - advancePaid);

    try {
      const res = await fetch('/api/admissions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          patient_name: name,
          patient_phone: phone,
          bed_id: bedId || null,
          daily_price: pkg.rate,
          program_type: pkgKey,
          start_date: getTodayISO(),
          end_date: getOffsetDateStr(days),
          notes: `Buxgalteriya orqali qabul qilindi`
        })
      });
      const resJson = await res.json().catch(() => ({}));
      // A refused admission (no bed chosen -- it used to fall back to
      // BED-1A -- or the bed is taken) was still announced as a new invoice.
      if (!res.ok) {
        showToast(resJson.error || "Qabul saqlanmadi.", 'error');
        return;
      }
      if (resJson.invoice_id && advancePaid > 0) {
        await fetch('/api/payments', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            invoice_id: resJson.invoice_id,
            amount: advancePaid,
            payment_method: method,
            account_destination: method === 'cash' ? 'kassa' : 'terminal_bank',
            notes: `Yangi hisob ochilganda avans to'lovi (${days} kunlik)`,
            payment_date: getTodayISO()
          })
        });
      }
    } catch (e) {
      showToast("Server bilan aloqa yo'q — qabul saqlanmadi.", 'error');
      return;
    }

    await syncWithLedgerAndBackend();
    closeAllModals();
    renderAll();
    showToast(`✅ ${name} uchun ${formatUZS(totalDue)} miqdorida yangi hisob-faktura yaratildi!`);
  }

  // ==========================================================================
  // NEW EXPENSE / INCOME TRANSACTION MODAL
  // ==========================================================================

  function openNewTxnModal(type = 'income') {
    const modal = document.getElementById('new-transaction-modal');
    if (!modal) return;

    document.getElementById('txn-type-select').value = type;
    document.getElementById('txn-title-input').value = '';
    document.getElementById('txn-amount-input').value = '';
    document.getElementById('txn-notes-input').value = '';
    document.getElementById('txn-date-input').value = new Date().toISOString().split('T')[0];

    modal.classList.add('active');
  }

  async function handleTxnSubmit(e) {
    e.preventDefault();
    const type = document.getElementById('txn-type-select').value;
    const title = document.getElementById('txn-title-input').value.trim();
    const amount = Number(document.getElementById('txn-amount-input').value);
    const category = document.getElementById('txn-category-select').value;
    const method = document.getElementById('txn-method-select').value;
    const date = document.getElementById('txn-date-input').value;
    const notes = document.getElementById('txn-notes-input').value.trim();

    if (!title || isNaN(amount) || amount <= 0 || !date) {
      showToast("Iltimos, barcha maydonlarni to'g'ri to'ldiring!", 'warning');
      return;
    }

    const newTxn = {
      id: `TXN-2026-${Date.now().toString().slice(-6)}`,
      type: type,
      category: category,
      title: title,
      amount: amount,
      payment_method: method,
      patient_name: null,
      bill_id: null,
      date: date,
      time: new Date().toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' }),
      cashier: "Dilnoza Rahimova",
      notes: notes
    };

    try {
      await fetch('/api/accounting/transaction', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newTxn)
      });
    } catch (e) {}

    accountingData.transactions.unshift(newTxn);
    saveData();
    closeAllModals();
    renderAll();
    showToast(type === 'income' ? `✅ Yangi tushum (${formatUZS(amount)}) qo'shildi!` : `💸 Yangi xarajat (${formatUZS(amount)}) qayd etildi!`, type === 'income' ? 'success' : 'info');
  }

  // ==========================================================================
  // DOCTOR SALARY PAYOUT
  // ==========================================================================

  async function payoutDoctorSalary(docId) {
    const doc = accountingData.doctors_payroll.find(d => d.id === docId);
    if (!doc) return;

    const confirmed = await fmhConfirm({
      title: "Maosh To'lovini Tasdiqlash",
      message: `<strong>${doc.name}</strong> uchun jami <strong>${formatUZS(doc.total_payable)}</strong> maosh va gonorar to'lansinmi?`,
      confirmText: "To'lash",
      cancelText: "Bekor Qilish",
      type: 'primary'
    });
    if (!confirmed) {
      return;
    }

    doc.status = 'paid';

    // Record expense transaction
    const newTxn = {
      id: `TXN-2026-${Date.now().toString().slice(-6)}`,
      type: "expense",
      category: "salary",
      title: `Shifokor oyligi va gonorari (${doc.name})`,
      amount: doc.total_payable,
      payment_method: "bank",
      patient_name: null,
      bill_id: null,
      date: getTodayISO(),
      time: new Date().toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' }),
      cashier: "Xusnitdinov Azamat",
      notes: `${doc.name} maoshi (${formatUZS(doc.base_salary)}) + ${doc.patients_count_month} ta bemor uchun gonorari (${formatUZS(doc.commission_earned)})`
    };

    try {
      await fetch('/api/accounting/transaction', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newTxn)
      });
    } catch (e) {}

    accountingData.transactions.unshift(newTxn);
    saveData();
    renderAll();
    showToast(`✅ ${doc.name} ga ${formatUZS(doc.total_payable)} oylik maosh to'landi va xarajatlarga yozildi!`);
  }

  // ==========================================================================
  // MODAL 8: MEDICATION PURCHASE & RESTOCK (DORI XARIDI VA KLINIKA CHIQIMI)
  // ==========================================================================

  let medPurchaseRowCount = 0;

  function openMedPurchaseModal(prefillMedId = null) {
    const modal = document.getElementById('medication-purchase-modal');
    if (!modal) return;

    const dateInput = document.getElementById('medpur-date-input');
    if (dateInput) dateInput.value = new Date().toISOString().split('T')[0];
    const methodSelect = document.getElementById('medpur-method-select');
    if (methodSelect) methodSelect.value = 'cash';
    const supplierInput = document.getElementById('medpur-supplier-input');
    if (supplierInput) supplierInput.value = '';
    const invoiceInput = document.getElementById('medpur-invoice-input');
    if (invoiceInput) invoiceInput.value = '';
    const notesInput = document.getElementById('medpur-notes-input');
    if (notesInput) notesInput.value = '';

    const tbody = document.getElementById('medpur-items-tbody');
    if (tbody) tbody.innerHTML = '';
    medPurchaseRowCount = 0;

    let prefill = null;
    if (prefillMedId && accountingData && Array.isArray(accountingData.pharmacy_stock)) {
      prefill = accountingData.pharmacy_stock.find(m => m.id === prefillMedId);
    }

    addMedPurchaseRow(prefill);
    updateMedPurchaseTotals();
    modal.classList.add('active');
  }

  function addMedPurchaseRow(initialData = null) {
    const tbody = document.getElementById('medpur-items-tbody');
    if (!tbody) return;

    medPurchaseRowCount++;
    const rowId = `medpur-row-${medPurchaseRowCount}`;
    const tr = document.createElement('tr');
    tr.id = rowId;
    tr.style.borderBottom = '1px solid var(--border-color)';

    const catalog = (accountingData && Array.isArray(accountingData.pharmacy_stock)) ? accountingData.pharmacy_stock : [];
    const datalistId = `datalist-meds-${medPurchaseRowCount}`;

    tr.innerHTML = `
      <td style="padding: 6px 8px;">
        <input type="text" class="form-input medpur-item-name" list="${datalistId}" required placeholder="Dori nomini tanlang yoki yozing..." style="font-size: 0.85rem;" value="${initialData ? esc(initialData.name) : ''}">
        <datalist id="${datalistId}">
          ${catalog.map(m => `<option value="${esc(m.name)}" data-id="${m.id}" data-category="${esc(m.group || m.category || '')}" data-form="${esc(m.unit || m.form || '')}" data-price="${m.unit_price || 0}"></option>`).join('')}
        </datalist>
        <input type="hidden" class="medpur-item-id" value="${initialData ? initialData.id : ''}">
      </td>
      <td style="padding: 6px 8px;">
        <input type="text" class="form-input medpur-item-cat" placeholder="Guruhi" style="font-size: 0.82rem;" value="${initialData ? esc(initialData.group || initialData.category || '') : ''}">
      </td>
      <td style="padding: 6px 8px;">
        <input type="number" class="form-input medpur-item-qty" min="1" step="1" required placeholder="Soni" style="font-family: var(--font-mono); font-weight: 700; font-size: 0.85rem;" value="1">
      </td>
      <td style="padding: 6px 8px;">
        <input type="number" class="form-input medpur-item-price" min="0" step="500" required placeholder="Narxi" style="font-family: var(--font-mono); font-weight: 700; font-size: 0.85rem;" value="${initialData ? (initialData.unit_price || 0) : ''}">
      </td>
      <td style="padding: 6px 8px;" class="mono-val medpur-item-total" style="font-weight: 700; color: var(--rose);">
        0 so'm
      </td>
      <td style="padding: 6px 4px; text-align: center;">
        <button type="button" class="btn-portal btn-outline-portal btn-remove-medpur-row" style="padding: 2px 6px; font-size: 0.75rem; color: var(--rose); border-color: rgba(244,63,94,0.3);" title="Qatorni o'chirish">
          &times;
        </button>
      </td>
    `;

    tbody.appendChild(tr);

    const nameInput = tr.querySelector('.medpur-item-name');
    const catInput = tr.querySelector('.medpur-item-cat');
    const idInput = tr.querySelector('.medpur-item-id');
    const qtyInput = tr.querySelector('.medpur-item-qty');
    const priceInput = tr.querySelector('.medpur-item-price');
    const removeBtn = tr.querySelector('.btn-remove-medpur-row');

    nameInput.addEventListener('change', () => {
      const val = nameInput.value.trim().toLowerCase();
      const match = catalog.find(m => (m.name || '').toLowerCase() === val);
      if (match) {
        idInput.value = match.id;
        if (!catInput.value) catInput.value = match.group || match.category || '';
        if (!priceInput.value || Number(priceInput.value) === 0) priceInput.value = match.unit_price || '';
      }
      updateMedPurchaseTotals();
    });

    qtyInput.addEventListener('input', updateMedPurchaseTotals);
    priceInput.addEventListener('input', updateMedPurchaseTotals);

    removeBtn.addEventListener('click', () => {
      if (tbody.querySelectorAll('tr').length > 1) {
        tr.remove();
        updateMedPurchaseTotals();
      } else {
        showToast("Kamida bitta dori bo'lishi kerak", 'warning');
      }
    });

    updateMedPurchaseTotals();
  }

  function updateMedPurchaseTotals() {
    let grandTotal = 0;
    const rows = document.querySelectorAll('#medpur-items-tbody tr');
    rows.forEach(tr => {
      const qty = parseFloat(tr.querySelector('.medpur-item-qty')?.value) || 0;
      const price = parseFloat(tr.querySelector('.medpur-item-price')?.value) || 0;
      const total = Math.max(0, qty * price);
      grandTotal += total;
      const totalCell = tr.querySelector('.medpur-item-total');
      if (totalCell) totalCell.textContent = formatUZS(total);
    });

    const grandDisp = document.getElementById('medpur-grand-total-disp');
    if (grandDisp) grandDisp.textContent = formatUZS(grandTotal);
  }

  async function handleMedPurchaseSubmit(e) {
    e.preventDefault();

    const date = document.getElementById('medpur-date-input').value;
    const method = document.getElementById('medpur-method-select').value;
    const supplier = document.getElementById('medpur-supplier-input').value.trim();
    const invoice = document.getElementById('medpur-invoice-input').value.trim();
    const notes = document.getElementById('medpur-notes-input').value.trim();

    const rows = document.querySelectorAll('#medpur-items-tbody tr');
    const items = [];

    rows.forEach(tr => {
      const name = tr.querySelector('.medpur-item-name')?.value.trim();
      const cat = tr.querySelector('.medpur-item-cat')?.value.trim() || 'Dori-darmon';
      const medId = tr.querySelector('.medpur-item-id')?.value || null;
      const qty = parseFloat(tr.querySelector('.medpur-item-qty')?.value) || 0;
      const price = parseFloat(tr.querySelector('.medpur-item-price')?.value) || 0;

      if (name && qty > 0 && price >= 0) {
        items.push({
          medication_id: medId,
          medication_name: name,
          category: cat,
          form: 'dona',
          quantity: qty,
          unit_price: price
        });
      }
    });

    if (items.length === 0) {
      showToast("Iltimos, kamida bitta dori vositasi va uning narxini kiriting!", 'warning');
      return;
    }

    const payload = {
      purchase_date: date,
      payment_method: method,
      supplier_name: supplier,
      invoice_number: invoice,
      notes: notes,
      items: items
    };

    try {
      const res = await fetch('/api/accounting/medication-purchases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || "Xaridni saqlashda xatolik yuz berdi", 'warning');
        return;
      }

      const resData = await res.json();
      const totalAmount = resData.amount || items.reduce((s, it) => s + (it.quantity * it.unit_price), 0);

      // Instantly refresh from server
      await syncWithLedgerAndBackend(false);
      closeAllModals();
      renderAll();
      showToast(`✅ Dori xaridi (${formatUZS(totalAmount)}) buxgalteriya xarajatlariga yozildi va ombor yangilandi!`, 'success');
    } catch (err) {
      console.error("Medication purchase submit error:", err);
      showToast("Server bilan aloqada xatolik", 'warning');
    }
  }

  async function deleteMedPurchase(purchaseId) {
    const p = (accountingData.medication_purchases || []).find(x => x.id === purchaseId);
    const medName = p ? p.medication_name : 'Ushbu dori xaridi';

    const confirmed = await fmhConfirm({
      title: "Dori Xaridini Bekor Qilish",
      message: `<strong>${esc(medName)}</strong> bo'yicha xarid yozuvi o'chirilsinmi? Kassa chiqimi bekor qilinadi va ombor qoldig'i kamaytiriladi.`,
      confirmText: "O'chirish",
      cancelText: "Bekor qilish",
      type: 'danger'
    });
    if (!confirmed) return;

    try {
      const res = await fetch(`/api/accounting/medication-purchases/${encodeURIComponent(purchaseId)}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        await syncWithLedgerAndBackend(false);
        renderAll();
        showToast("✅ Dori xaridi muvaffaqiyatli bekor qilindi", 'info');
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || "O'chirishda xatolik yuz berdi", 'warning');
      }
    } catch (e) {
      showToast("Server bilan aloqada xatolik", 'warning');
    }
  }

  function exportMedPurchasesToExcel() {
    if (!window.XLSX || !accountingData || !accountingData.medication_purchases) {
      showToast("Eksport uchun ma'lumotlar yetarli emas", 'warning');
      return;
    }

    const list = [...accountingData.medication_purchases].filter(p => isDateInRange(p.purchase_date || p.created_at));
    const rows = list.map((p, idx) => ({
      "№": idx + 1,
      "Sana": p.purchase_date,
      "Dori Nomi": p.medication_name,
      "Guruhi": p.category || '',
      "Shakli": p.form || '',
      "Miqdori": p.quantity,
      "Donasi Narxi (UZS)": p.unit_price,
      "Jami Xarajat (UZS)": p.total_price,
      "To'lov Shakli": p.payment_method,
      "Yetkazib Beruvchi": p.supplier_name || '',
      "Chek / Nakladnaya": p.invoice_number || '',
      "Kassir / Mas'ul": p.recorded_by_name || 'Buxgalter',
      "Izoh": p.notes || ''
    }));

    const wb = XLSX.utils.book_new();
    const ws = XLSX.utils.json_to_sheet(rows);
    XLSX.utils.book_append_sheet(wb, ws, "Dori Xarajatlari");
    XLSX.writeFile(wb, `FMH_Dori_Xarajatlari_${getFormattedDate()}.xlsx`);
    showToast("✅ Dori xarajatlari Excel fayli yuklab olindi!");
  }

  // ==========================================================================
  // EXCEL (.XLSX) EXPORT ENGINES PER PAGE / TAB (MATCHING ACTIVE DATE RANGE)
  // ==========================================================================

  function getFormattedDate() {
    return new Date().toISOString().split('T')[0];
  }

  // 1. Export Patient Payments Tab to Excel (.XLSX)
  function exportPatientsToExcel() {
    if (!window.XLSX || !accountingData) {
      showToast("Excel kutubxonasi yuklanmoqda...", 'info');
      return;
    }

    let list = accountingData.patients_billing.filter(b => isDateInRange(b.start_date || b.created_at));

    const rows = list.map((b, index) => ({
      "№": index + 1,
      "Hisob-Faktura ID": b.id,
      "Bemor F.I.Sh.": b.patient_name,
      "Telefon": b.patient_phone,
      "Shahar / Manzil": b.patient_city || 'Toshkent sh.',
      "Xona / Karavot": b.bed_name,
      "Xizmat / Tarif": b.program,
      "Qo'shimcha Dorilar/Xizmatlar": (b.extra_services || []).map(s => `${s.name} (${s.qty}x)`).join(', ') || 'Yo\'q',
      "Mas'ul Shifokor": b.doctor,
      "Kelgan Sanasi": b.start_date,
      "Chiqish Sanasi": b.end_date,
      "Yotgan Kunlari": b.days_count,
      "Kunlik Narx (so'm)": b.daily_rate,
      "Hisoblangan (chegirmagacha, so'm)": b.gross_due || b.total_due,
      "Chegirma (so'm)": b.discount_amount || 0,
      "Jami Summa (so'm)": b.total_due,
      "Naqd Pul To'landi (so'm)": b.paid_cash,
      "Terminal To'landi (so'm)": b.paid_terminal,
      "Online Click/Payme (so'm)": b.paid_online,
      "Bank O'tkazma (so'm)": b.paid_bank,
      "Jami To'langan (so'm)": b.total_paid,
      "Qoldiq Qarz (so'm)": b.debt_remaining,
      "Holati": b.status === 'paid' ? "To'liq to'langan" : (b.status === 'partial' ? "Qisman to'langan" : "To'lanmagan")
    }));

    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Bemorlar To'lovlari");

    const fileName = `FMH_Bemorlar_Tolov_Hisoboti_${getFormattedDate()}.xlsx`;
    XLSX.writeFile(wb, fileName);
    showToast(`📗 <strong>${fileName}</strong> muvaffaqiyatli yuklab olindi!`);
  }

  // 2. Export Cash Flow / Transactions Tab to Excel (.XLSX)
  function exportTransactionsToExcel() {
    if (!window.XLSX || !accountingData) {
      showToast("Excel kutubxonasi yuklanmoqda...", 'info');
      return;
    }

    let list = accountingData.transactions.filter(t => isDateInRange(t.date));

    const rows = list.map((t, index) => ({
      "№": index + 1,
      "Operatsiya ID": t.id,
      "Sana": t.date,
      "Vaqt": t.time || '',
      "Turi": t.type === 'income' ? "KIRIM (Tushum)" : (t.category === 'incasso' ? "INKASSATSIYA" : "CHIQIM (Xarajat)"),
      "Kategoriya": t.category,
      "Operatsiya Nomi / Tavsifi": t.title,
      "Summa (so'm)": t.amount,
      "To'lov Shakli": t.payment_method.toUpperCase(),
      "Bemor": t.patient_name || '—',
      "Kassir / Mas'ul": t.cashier || 'Buxgalter',
      "Izoh": t.notes || ''
    }));

    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Kassa Kirim-Chiqim");

    const fileName = `FMH_Kassa_Kirim_Chiqim_${getFormattedDate()}.xlsx`;
    XLSX.writeFile(wb, fileName);
    showToast(`📗 <strong>${fileName}</strong> muvaffaqiyatli yuklab olindi!`);
  }

  // 3. Export Doctor Payroll Tab to Excel (.XLSX)
  function exportDoctorsToExcel() {
    if (!window.XLSX || !accountingData) {
      showToast("Excel kutubxonasi yuklanmoqda...", 'info');
      return;
    }

    const rows = accountingData.doctors_payroll.map((d, index) => ({
      "№": index + 1,
      "Shifokor ID": d.id,
      "Shifokor F.I.Sh.": d.name,
      "Lavozimi": d.role,
      "Bemorlar Soni (Oy)": d.patients_count_month,
      "Klinikaga Keltirgan Tushum (so'm)": d.total_revenue_generated,
      "Asosiy Oylik Maosh (so'm)": d.base_salary,
      "Gonorar Ulushi (%)": `${d.commission_rate}%`,
      "Hisoblangan Gonorar (so'm)": d.commission_earned,
      "Jami To'lanadigan Maosh (so'm)": d.total_payable,
      "To'lov Holati": d.status === 'paid' ? "To'langan" : "Hisoblangan"
    }));

    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Shifokorlar Oyligi");

    const fileName = `FMH_Shifokorlar_Oylik_Hisoboti_${getFormattedDate()}.xlsx`;
    XLSX.writeFile(wb, fileName);
    showToast(`📗 <strong>${fileName}</strong> muvaffaqiyatli yuklab olindi!`);
  }

  // 4. Export Pharmacy Tab to Excel (.XLSX)
  function exportPharmacyToExcel() {
    if (!window.XLSX || !accountingData.pharmacy_stock) {
      showToast("Excel kutubxonasi yuklanmoqda...", 'info');
      return;
    }

    const rows = accountingData.pharmacy_stock.map((item, index) => ({
      "№": index + 1,
      "Dori Nomi": item.name,
      "Farmakologik Guruhi": item.group,
      "Ombordagi Qoldiq": `${item.stock} ${item.unit}`,
      "Birligi Narxi (so'm)": item.unit_price,
      "Jami Qiymati (so'm)": item.stock * item.unit_price,
      "Holat": item.stock <= 15 ? "Kam qolgan" : "Yetarli"
    }));

    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Dorixona Ombor");

    const fileName = `FMH_Dorixona_Ombor_Hisoboti_${getFormattedDate()}.xlsx`;
    XLSX.writeFile(wb, fileName);
    showToast(`📗 <strong>${fileName}</strong> muvaffaqiyatli yuklab olindi!`);
  }

  // 5. Master Multi-Sheet Excel (.XLSX) Export
  function exportAllToExcel() {
    if (!window.XLSX || !accountingData) {
      showToast("Excel kutubxonasi yuklanmoqda...", 'info');
      return;
    }

    const wb = XLSX.utils.book_new();

    // Sheet 1: Patients
    const patientRows = accountingData.patients_billing.filter(b => isDateInRange(b.start_date || b.created_at)).map((b, index) => ({
      "№": index + 1,
      "Hisob ID": b.id,
      "Bemor F.I.Sh.": b.patient_name,
      "Telefon": b.patient_phone,
      "Xona/Karavot": b.bed_name,
      "Tarif": b.program,
      "Qo'shimcha Dorilar": (b.extra_services || []).map(s => `${s.name} (${s.qty}x)`).join(', ') || 'Yo\'q',
      "Shifokor": b.doctor,
      "Kunlar": b.days_count,
      "Hisoblangan (chegirmagacha)": b.gross_due || b.total_due,
      "Chegirma": b.discount_amount || 0,
      "Jami Summa": b.total_due,
      "To'langan": b.total_paid,
      "Qarz": b.debt_remaining,
      "Holati": b.status
    }));
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(patientRows), "Bemorlar Hisobi");

    // Sheet 2: Transactions
    const txnRows = accountingData.transactions.filter(t => isDateInRange(t.date)).map((t, index) => ({
      "№": index + 1,
      "Operatsiya ID": t.id,
      "Sana": t.date,
      "Turi": t.type.toUpperCase(),
      "Tavsif": t.title,
      "Summa": t.amount,
      "To'lov Usuli": t.payment_method.toUpperCase(),
      "Kassir": t.cashier || ''
    }));
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(txnRows), "Kassa Kirim-Chiqim");

    // Sheet 3: Doctors
    const docRows = accountingData.doctors_payroll.map((d, index) => ({
      "№": index + 1,
      "Shifokor": d.name,
      "Lavozimi": d.role,
      "Bemorlar Soni": d.patients_count_month,
      "Tushum": d.total_revenue_generated,
      "Asosiy Maosh": d.base_salary,
      "Gonorar": d.commission_earned,
      "Jami To'lov": d.total_payable,
      "Holat": d.status
    }));
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(docRows), "Shifokorlar Oyligi");

    // Sheet 4: Pharmacy
    const pharmRows = accountingData.pharmacy_stock.map((p, index) => ({
      "№": index + 1,
      "Dori Nomi": p.name,
      "Guruh": p.group,
      "Qoldiq": `${p.stock} ${p.unit}`,
      "Narx": p.unit_price,
      "Jami Qiymat": p.stock * p.unit_price
    }));
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(pharmRows), "Dorixona Ombor");

    // Sheet 5: Medication Purchases
    if (accountingData.medication_purchases && accountingData.medication_purchases.length > 0) {
      const medPurchRows = accountingData.medication_purchases.filter(p => isDateInRange(p.purchase_date || p.created_at)).map((p, index) => ({
        "№": index + 1,
        "Sana": p.purchase_date,
        "Dori Nomi": p.medication_name,
        "Guruhi": p.category || '',
        "Shakli": p.form || '',
        "Miqdori": p.quantity,
        "Donasi Narxi": p.unit_price,
        "Jami Xarajat": p.total_price,
        "To'lov Shakli": p.payment_method,
        "Yetkazib Beruvchi": p.supplier_name || '',
        "Chek / Nakladnaya": p.invoice_number || '',
        "Kassir / Mas'ul": p.recorded_by_name || 'Buxgalter'
      }));
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(medPurchRows), "Dori Xarajatlari");
    }

    const fileName = `FMH_Kompleks_Buxgalteriya_Hisoboti_${getFormattedDate()}.xlsx`;
    XLSX.writeFile(wb, fileName);
    showToast(`📗 <strong>${fileName}</strong> (barcha varaqlar bilan) yuklab olindi!`);
  }

  // ==========================================================================
  // DAILY Z-REPORT (CASH CLOSING)
  // ==========================================================================

  function openZReportModal() {
    const modal = document.getElementById('z-report-modal');
    const content = document.getElementById('z-report-content');
    if (!modal || !content || !accountingData) return;

    const today = new Date().toISOString().split('T')[0];
    const todayTxns = accountingData.transactions.filter(t => t.date === today);

    let todayIncome = 0;
    let todayExpense = 0;
    let todayCash = 0;
    let todayTerminal = 0;
    let todayOnline = 0;

    todayTxns.forEach(t => {
      const amt = Number(t.amount) || 0;
      if (t.type === 'income') {
        todayIncome += amt;
        if (t.payment_method === 'cash') todayCash += amt;
        else if (t.payment_method === 'terminal') todayTerminal += amt;
        else if (t.payment_method === 'online') todayOnline += amt;
      } else {
        todayExpense += amt;
      }
    });

    content.innerHTML = `
      <div style="background: #ffffff; color: #1e293b; padding: 2rem; border-radius: 12px; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;">
        <div style="text-align: center; border-bottom: 2px dashed #64748b; padding-bottom: 1rem; margin-bottom: 1rem;">
          <h2 style="font-family: 'Outfit', sans-serif; font-size: 1.35rem; color: #0284c7;">FAYZ MEDICAL HOUSE</h2>
          <div>KUNLIK KASSA YOPILISHI (Z-HISOBOT)</div>
          <div style="font-size: 0.75rem; color: #64748b;">Sana: ${today} | Vaqt: ${new Date().toLocaleTimeString()}</div>
        </div>

        <div style="display: flex; flex-direction: column; gap: 0.6rem; margin-bottom: 1.25rem;">
          <div style="display: flex; justify-content: space-between;">
            <span>Bugungi Jami Operatsiyalar:</span>
            <strong>${todayTxns.length} ta</strong>
          </div>
          <div style="display: flex; justify-content: space-between; color: #059669;">
            <span>Bugungi Jami Kirim:</span>
            <strong>+${formatUZS(todayIncome)}</strong>
          </div>
          <div style="display: flex; justify-content: space-between; color: #e11d48;">
            <span>Bugungi Jami Chiqim:</span>
            <strong>-${formatUZS(todayExpense)}</strong>
          </div>
          <div style="border-top: 1px solid #cbd5e1; padding-top: 0.4rem; display: flex; justify-content: space-between; font-weight: 800;">
            <span>KUNLIK SOF QOLDIQ:</span>
            <span>${formatUZS(todayIncome - todayExpense)}</span>
          </div>
        </div>

        <div style="background: #f1f5f9; padding: 0.85rem; border-radius: 6px; margin-bottom: 1.25rem;">
          <div style="font-weight: 700; margin-bottom: 0.35rem; color: #334155;">To'lov Usullari Taqsimoti:</div>
          <div style="display: flex; justify-content: space-between;"><span>💵 Naqd Pul:</span> <span>${formatUZS(todayCash)}</span></div>
          <div style="display: flex; justify-content: space-between;"><span>💳 Terminal (Humo/Uzcard):</span> <span>${formatUZS(todayTerminal)}</span></div>
          <div style="display: flex; justify-content: space-between;"><span>📱 Click / Payme:</span> <span>${formatUZS(todayOnline)}</span></div>
        </div>

        <div style="text-align: center; border-top: 1px dashed #64748b; padding-top: 1rem; font-size: 0.75rem; color: #64748b;">
          Kassir: Dilnoza Rahimova ______________<br>
          Bosh buxgalter tasdiqladi: ______________
        </div>
      </div>
    `;

    modal.classList.add('active');
  }

  // ==========================================================================
  // EVENT LISTENERS & TAB SWITCHING
  // ==========================================================================

  function switchTab(tabId) {
    currentTab = tabId;
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tabId);
    });
    document.querySelectorAll('.tab-panel').forEach(panel => {
      panel.classList.toggle('active', panel.id === `tab-panel-${tabId}`);
    });

    if (tabId === 'analytics') {
      setTimeout(renderAnalytics, 50);
    } else if (tabId === 'pharmacy') {
      renderMedicationPurchases();
      renderPharmacyInventory();
    }
  }

  function closeAllModals() {
    document.querySelectorAll('.modal-backdrop').forEach(m => m.classList.remove('active'));
  }

  // Drilldown filter triggered by clicking top KPI cards
  function filterByKPI(kpiType) {
    if (kpiType === 'revenue') {
      switchTab('transactions');
      txnTypeFilter = 'income';
      txnMethodFilter = 'all';
      const typeSelect = document.getElementById('filter-txn-type');
      if (typeSelect) typeSelect.value = 'income';
      const methodSelect = document.getElementById('filter-txn-method');
      if (methodSelect) methodSelect.value = 'all';
      renderTransactionsTable();
      showToast("📥 <strong>Kassa Kirimlari (Tushum)</strong> ro'yxati ochildi!", "info");
    } else if (kpiType === 'expense') {
      switchTab('transactions');
      txnTypeFilter = 'expense';
      txnMethodFilter = 'all';
      const typeSelect = document.getElementById('filter-txn-type');
      if (typeSelect) typeSelect.value = 'expense';
      const methodSelect = document.getElementById('filter-txn-method');
      if (methodSelect) methodSelect.value = 'all';
      renderTransactionsTable();
      showToast("📤 <strong>Jami Chiqimlar (Xarajatlar)</strong> ro'yxati ochildi!", "danger");
    } else if (kpiType === 'profit') {
      switchTab('analytics');
      showToast("📊 <strong>Sof Foyda & Rentabellik Analitikasi</strong> ochildi!", "info");
    } else if (kpiType === 'debt') {
      switchTab('patients');
      statusFilter = 'partial';
      const statusSelect = document.getElementById('filter-billing-status');
      if (statusSelect) statusSelect.value = 'partial';
      renderPatientsBillingTable();
      showToast("⚠️ <strong>Qoldiq Qarzdorligi mavjud bemorlar</strong> ro'yxati ochildi!", "info");
    } else if (kpiType === 'cash') {
      switchTab('transactions');
      txnTypeFilter = 'all';
      txnMethodFilter = 'cash';
      const typeSelect = document.getElementById('filter-txn-type');
      if (typeSelect) typeSelect.value = 'all';
      const methodSelect = document.getElementById('filter-txn-method');
      if (methodSelect) methodSelect.value = 'cash';
      renderTransactionsTable();
      showToast("💵 <strong>Faqat Naqd Pul kassa operatsiyalari</strong> ochildi!", "info");
    }
  }

  function setupEventListeners() {
    // Tab switching
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    // Search input
    const searchInput = document.getElementById('search-billing-input');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        searchQuery = e.target.value;
        renderPatientsBillingTable();
      });
    }

    // Status filter
    const statusSelect = document.getElementById('filter-billing-status');
    if (statusSelect) {
      statusSelect.addEventListener('change', (e) => {
        statusFilter = e.target.value;
        renderPatientsBillingTable();
      });
    }

    // Txn type filter
    const txnSelect = document.getElementById('filter-txn-type');
    if (txnSelect) {
      txnSelect.addEventListener('change', (e) => {
        txnTypeFilter = e.target.value;
        renderTransactionsTable();
      });
    }

    // Txn method filter
    const methodSelect = document.getElementById('filter-txn-method');
    if (methodSelect) {
      methodSelect.addEventListener('change', (e) => {
        txnMethodFilter = e.target.value;
        renderTransactionsTable();
      });
    }

    // Modal close buttons
    document.querySelectorAll('.modal-close-btn, .modal-cancel-btn').forEach(btn => {
      btn.addEventListener('click', closeAllModals);
    });

    // Forms
    const paymentForm = document.getElementById('accept-payment-form');
    if (paymentForm) paymentForm.addEventListener('submit', handlePaymentSubmit);

    const txnForm = document.getElementById('new-transaction-form');
    if (txnForm) txnForm.addEventListener('submit', handleTxnSubmit);

    const newBillForm = document.getElementById('new-bill-form');
    if (newBillForm) newBillForm.addEventListener('submit', handleNewBillSubmit);

    const newBillPkgSelect = document.getElementById('newbill-package-select');
    if (newBillPkgSelect) newBillPkgSelect.addEventListener('change', updateNewBillCalculation);

    const newBillDaysInput = document.getElementById('newbill-days-input');
    if (newBillDaysInput) newBillDaysInput.addEventListener('input', updateNewBillCalculation);

    // Extra Service Form Listeners
    const addSvcForm = document.getElementById('add-service-form');
    if (addSvcForm) addSvcForm.addEventListener('submit', handleAddServiceSubmit);

    const addSvcItemSelect = document.getElementById('addsvc-item-select');
    if (addSvcItemSelect) addSvcItemSelect.addEventListener('change', updateAddServiceCalculation);

    const addSvcQtyInput = document.getElementById('addsvc-qty-input');
    if (addSvcQtyInput) addSvcQtyInput.addEventListener('input', updateAddServiceCalculation);

    // Incasso Form Listener
    const incassoForm = document.getElementById('incasso-form');
    if (incassoForm) incassoForm.addEventListener('submit', handleIncassoSubmit);

    // Medication Purchase Form & Row Button Listeners
    const medPurForm = document.getElementById('medication-purchase-form');
    if (medPurForm) medPurForm.addEventListener('submit', handleMedPurchaseSubmit);

    const btnAddMedRow = document.getElementById('btn-add-medpur-row');
    if (btnAddMedRow) btnAddMedRow.addEventListener('click', () => addMedPurchaseRow());

    // Window resize for canvas
    window.addEventListener('resize', () => {
      if (currentTab === 'analytics') renderCanvasChart();
    });
  }

  // ==========================================================================
  // ENTERPRISE PRINT ENGINE (STANDALONE PRINT WINDOW WITH EMBEDDED CSS)
  // ==========================================================================

  function printHtmlContent(htmlContent, docTitle = "FMH_Hujjat") {
    if (!htmlContent) return;

    const printWin = window.open('', '_blank', 'width=850,height=900,menubar=no,toolbar=no,location=no,status=no');
    if (!printWin) {
      // Fallback if popup is blocked by browser
      window.print();
      return;
    }

    const printDocumentHtml = `
      <!DOCTYPE html>
      <html lang="uz">
      <head>
        <meta charset="UTF-8">
        <title>${docTitle}</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700;800&display=swap" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
        <style>
          * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
          }
          body {
            background: #ffffff;
            color: #0f172a;
            font-family: 'Outfit', -apple-system, sans-serif;
            padding: 24px;
          }
          .invoice-preview-container {
            max-width: 800px;
            margin: 0 auto;
            background: #ffffff;
            color: #0f172a;
          }
          .inv-brand-name {
            color: #0284c7;
            font-size: 1.6rem;
            font-weight: 800;
            letter-spacing: -0.02em;
          }
          .inv-brand-details {
            font-size: 0.82rem;
            color: #475569;
            line-height: 1.45;
            margin-top: 5px;
          }
          .inv-header-row {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            border-bottom: 2px solid #0284c7;
            padding-bottom: 1rem;
            margin-bottom: 1.25rem;
          }
          .inv-title-badge {
            text-align: right;
          }
          .inv-doc-title {
            font-size: 1.2rem;
            font-weight: 800;
            color: #0284c7;
          }
          .inv-doc-num {
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.05rem;
            font-weight: 700;
            color: #0f172a;
            margin-top: 2px;
          }
          .inv-meta-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 1.25rem;
          }
          .inv-meta-col .title {
            font-size: 0.72rem;
            text-transform: uppercase;
            color: #64748b;
            font-weight: 700;
            margin-bottom: 4px;
          }
          .inv-meta-col .name {
            font-size: 1.05rem;
            font-weight: 800;
            color: #0f172a;
          }
          .inv-table {
            width: 100%;
            border-collapse: collapse;
            margin: 1.25rem 0;
          }
          .inv-table th {
            background: #f1f5f9;
            color: #0f172a;
            border: 1px solid #cbd5e1;
            padding: 8px 10px;
            font-size: 0.82rem;
            text-align: left;
          }
          .inv-table td {
            border: 1px solid #e2e8f0;
            color: #0f172a;
            padding: 8px 10px;
            font-size: 0.85rem;
          }
          .inv-total-box {
            background: #f8fafc;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            padding: 1rem;
            margin: 1.25rem 0;
          }
          .inv-total-row {
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            font-size: 0.9rem;
            color: #334155;
          }
          .inv-total-row.grand-total {
            border-top: 2px solid #0f172a;
            font-size: 1.15rem;
            font-weight: 800;
            color: #b91c1c;
            padding-top: 6px;
            margin-top: 4px;
          }
          .inv-footer-stamps {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-top: 1px dashed #cbd5e1;
            padding-top: 1.25rem;
            margin-top: 1.5rem;
            font-size: 0.8rem;
            color: #475569;
          }
          .inv-stamp-mockup {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            color: #0284c7;
            font-weight: 700;
            border: 2px dashed #38bdf8;
            padding: 6px 14px;
            border-radius: 8px;
          }
          @media print {
            @page {
              size: A4 portrait;
              margin: 10mm;
            }
            body {
              padding: 0;
            }
          }
        </style>
      </head>
      <body>
        ${htmlContent}
        <script>
          window.onload = function() {
            setTimeout(function() {
              window.focus();
              window.print();
            }, 250);
          };
        </script>
      </body>
      </html>
    `;

    printWin.document.open();
    printWin.document.write(printDocumentHtml);
    printWin.document.close();
  }

  function printInvoice() {
    const content = document.getElementById('invoice-receipt-content');
    if (!content) return;
    printHtmlContent(content.innerHTML, "FMH_Tolov_Kvitansiyasi");
  }

  function printZReport() {
    const content = document.getElementById('z-report-content');
    if (!content) return;
    printHtmlContent(content.innerHTML, "FMH_Kunlik_Z_Hisobot");
  }

  function renderAll() {
    calculateKPIs();
    renderPatientsBillingTable();
    renderTransactionsTable();
    renderDoctorsPayroll();
    renderMedicationPurchases();
    renderPharmacyInventory();
    if (currentTab === 'analytics') renderAnalytics();
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
    document.body.className = `accounting-portal ${theme}-mode`;
    localStorage.setItem('fmh_theme', theme);

    const btn = document.getElementById('accounting-theme-toggle');
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

  // Export globally
    // =========================================================================
  // PRINT HELPERS FOR MODALS
  // =========================================================================
  function printInvoiceFromModal() {
    const billId = document.getElementById('pay-bill-id')?.value;
    const patientName = document.getElementById('pay-patient-name')?.value || 'Bemor';
    // An empty amount box used to print a receipt for 720 000 so'm that
    // nobody had paid. A receipt states what was actually taken, so an empty
    // box is zero and the real invoice figures come from the bill itself.
    const amount = parseFloat(document.getElementById('pay-amount-input')?.value) || 0;
    const bill = accountingData.patients_billing.find(b => b.id === billId) || {};

    if (window.FMH_Print) {
      window.FMH_Print.patientReceipt({
        full_name: patientName,
        patient_code: billId || 'FMH-2026'
      }, {
        // The whole invoice, not just this payment: the receipt used to claim
        // the bill equalled the amount handed over, which hid the balance and
        // any discount reception had given.
        total_amount: Number(bill.total_due) || amount,
        gross_amount: Number(bill.gross_due) || 0,
        discount_amount: Number(bill.discount_amount) || 0,
        paid_amount: (Number(bill.total_paid) || 0) + amount
      }, {
        id: `RCP-${Date.now().toString().slice(-4)}`,
        amount: amount,
        payment_method: 'cash',
        notes: 'Statsionar va klinik xizmatlar to`lovi'
      });
    } else {
      window.print();
    }
  }

  function printZReportFromModal() {
    const content = document.getElementById('z-report-content')?.innerHTML || '<h3>Z-HISOBOT</h3>';
    if (window.FMH_Print) {
      window.FMH_Print.printDocument(`
        <div class="fmh-doc-header">
          <div class="fmh-brand-left">
            <div class="fmh-crest-icon"><i class="fas fa-cash-register"></i></div>
            <div class="fmh-brand-text">
              <h1>FAYZ MEDICAL HOUSE</h1>
              <div class="fmh-tagline">KASSA Z-HISOBOTI VA SUTKALIK YOPILISH</div>
            </div>
          </div>
          <div class="fmh-header-badge-box">
            <div class="fmh-doc-badge">KASSA Z-REPORT</div>
            <div class="fmh-doc-id-pill">KASSA №1</div>
          </div>
        </div>
        ${content}
      `, 'Kassa_Z_Hisoboti');
    } else {
      window.print();
    }
  }

  window.FMH_Accounting = {
    printInvoiceFromModal,
    printZReportFromModal,
    init,
    applyTheme,
    toggleTheme,
    switchTab,
    filterByKPI,
    setDateRangePreset,
    applyCustomDateRange,
    resetDateRange,
    openInvoiceReceipt,
    printInvoice,
    printZReport,
    printTxnReceipt,
    openPaymentModal,
    openAddServiceModal,
    openIncassoModal,
    openNewTxnModal,
    openNewBillModal,
    openMedPurchaseModal,
    addMedPurchaseRow,
    deleteMedPurchase,
    filterMedPurchases,
    filterPharmacyStock,
    exportMedPurchasesToExcel,
    payoutDoctorSalary,
    exportToCSV: exportAllToExcel,
    exportAllToExcel,
    exportPatientsToExcel,
    exportTransactionsToExcel,
    exportDoctorsToExcel,
    exportPharmacyToExcel,
    openZReportModal,
    closeAllModals,
    editBillModal: (billId) => {
      openPaymentModal(billId);
    }
  };

  document.addEventListener('DOMContentLoaded', () => {
    const saved = localStorage.getItem('fmh_theme') || 'night';
    applyTheme(saved);
    init();
  });
})();
