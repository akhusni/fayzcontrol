/**
 * Fayz Medical House — Buxgalteriya & Moliya Boshqaruv Dvigateli (Accounting Engine)
 * Features:
 * - Real-time KPI summary (Gross Revenue, Expenses, Net Profit, Debt, Kassa Balances)
 * - Inpatient Billing Ledger synced with 14 beds and bookings (FMH_FACILITY_14BEDS_STORAGE_V7)
 * - POS & Cash Flow Transaction Journal (Kirim / Chiqim)
 * - Staff payroll from the server (GET /api/hr/payroll) and salary payouts
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
  // The payroll month the salary section shows and pays (YYYY-MM). It was
  // always the current calendar month, so last month's pay could not be paid
  // once the month had turned. Empty until init picks the current month.
  let payrollMonth = '';

  const UI_PAYMENT_METHODS = {
    cash: 'cash', cash_register: 'cash',
    terminal: 'terminal', card: 'terminal',
    online: 'online', payme_click: 'online', card_transfer: 'online', click: 'online', payme: 'online',
    bank: 'bank', bank_wire: 'bank'
  };
  function uiPaymentMethod(m) {
    return UI_PAYMENT_METHODS[String(m || '').toLowerCase()] || m;
  }

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

  // The rates come from the one price list (js/fmh_pricing.js). This table
  // used to carry its own 720 000 / 1 100 000 / ..., and those figures were
  // sent as the daily price of a new bill, so a price changed in the editor
  // never reached accounting.
  function listedRate(id) {
    return (window.FMH_Pricing && window.FMH_Pricing.rate(id)) || 0;
  }

  const OFFICIAL_RATES = {
    "statsionar_shared": { name: "Statsionar (1 karavot / 720 ming)", get rate() { return listedRate('statsionar_shared'); }, desc: "2 kishilik xonada 1 ta o'rin" },
    "statsionar_full_room": { name: "Statsionar Butun Xona (1 kishi / VIP Solo)", get rate() { return listedRate('statsionar_full_room'); }, desc: "Butun xona 1 kishi uchun (2-o'rin berilmaydi)" },
    "kunlik_statsionar": { name: "Kunlik Statsionar (Kunduzgi o'rin)", get rate() { return listedRate('kunlik_statsionar'); }, desc: "Faqat kunduzgi vaqtda muolaja olish" },
    "ambulator_1": { name: "Ambulator (Kuniga 1 mahal muolaja)", get rate() { return listedRate('ambulator_1'); }, desc: "Kuniga 1 mahal qatnab muolaja" },
    "ambulator_2": { name: "Ambulator (Kuniga 2 mahal muolaja)", get rate() { return listedRate('ambulator_2'); }, desc: "Kuniga 2 mahal qatnab muolaja" }
  };

  // Bills raised for a desk visit carry the appointment's service type.
  const VISIT_LABELS = {
    consultation: 'Shifokor konsultatsiyasi',
    outpatient: 'Ambulator muolaja kursi'
  };

  // The new-bill <select> in accounting.html has the prices typed into its
  // option text; they are rewritten from the price list once it is loaded.
  function applyListedPackageLabels() {
    document.querySelectorAll('#newbill-package-select option').forEach(opt => {
      const rate = listedRate(opt.value);
      const cut = opt.textContent.lastIndexOf(' — ');
      if (rate > 0 && cut > 0) {
        const spaced = String(Math.round(rate)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
        opt.textContent = `${opt.textContent.slice(0, cut)} — ${spaced} so'm / kun`;
      }
    });
  }

  // Format currency helper (e.g. 720 000 so'm)
  function formatUZS(amount) {
    if (isNaN(amount) || amount === null) amount = 0;
    return new Intl.NumberFormat('uz-UZ').format(Math.round(amount)) + " so'm";
  }

  // Stock quantities can be fractions (ml, half tablets): 12 -> "12", 2.5 -> "2.5",
  // and a float tail such as 0.30000000000000004 never reaches the screen.
  function fmtQty(v) {
    if (v === null || v === undefined || v === '') return '—';
    const n = Number(v);
    if (!isFinite(n)) return '—';
    return String(Math.round(n * 1000) / 1000);
  }

  // What a bill line can really take off the shelf: the server's usable
  // (non-expired) quantity when it sent one, else the cached on-hand figure.
  function billableQty(m) {
    const a = (m.available_quantity === null || m.available_quantity === undefined) ? Number(m.stock) : Number(m.available_quantity);
    return isFinite(a) ? a : 0;
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

  // A value passed to an inline onclick="f(...)" must be a JS string literal:
  // the browser decodes the attribute before running it, so an id holding a
  // quote (appointment ids were once copied from the request into invoice
  // ids) ended the string and ran as script. JSON.stringify makes a safe
  // literal; esc() keeps it inside the attribute.
  function jsArg(v) {
    return esc(JSON.stringify(String(v)));
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
          payroll_lines: [],
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

      // The payroll is never taken from the browser cache: it is the
      // server's figure for this month or nothing.
      accountingData.payroll_lines = [];
      accountingData.payroll_info = null;
      delete accountingData.doctors_payroll;

      // Sync with MySQL Financial Ledger, Admissions & Staff
      await syncWithLedgerAndBackend();
      await loadPayroll();

      const mBtn = document.getElementById('accounting-month-btn');
      if (mBtn) {
        mBtn.textContent = `Shu Oy (${new Date().toLocaleDateString('uz-UZ', { month: 'long' })})`;
      }
      updatePayrollTitle();
      const monthInput = document.getElementById('accounting-payroll-month');
      if (monthInput) {
        monthInput.value = currentPayrollMonth();
        monthInput.max = getTodayISO().slice(0, 7);
        monthInput.addEventListener('change', async () => {
          const v = String(monthInput.value || '');
          if (!/^\d{4}-\d{2}$/.test(v) || v > getTodayISO().slice(0, 7)) {
            monthInput.value = currentPayrollMonth();
            return;
          }
          payrollMonth = v;
          updatePayrollTitle();
          await loadPayroll();
          renderDoctorsPayroll();
        });
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
          // The server stores the database's method names (payme_click,
          // bank_wire, ...) but the balances, filter and labels here speak
          // cash/terminal/online/bank; unmapped rows silently fell out of
          // every cash-desk balance.
          accountingData.transactions = liveAcc.transactions.map(t => ({
            ...t,
            payment_method: uiPaymentMethod(t.payment_method)
          }));
        }
        if (liveAcc.medication_purchases && Array.isArray(liveAcc.medication_purchases)) {
          accountingData.medication_purchases = liveAcc.medication_purchases;
        }
        if (Array.isArray(liveAcc.invoice_items)) {
          accountingData.invoice_items = liveAcc.invoice_items;
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
            // 0 is a real threshold ("no minimum"), so it must not turn into 10.
            min_stock_level: (m.min_stock_level === null || m.min_stock_level === undefined || m.min_stock_level === '' || !isFinite(Number(m.min_stock_level))) ? 10 : Number(m.min_stock_level),
            available_quantity: m.available_quantity,
            stock_status: m.stock_status,
            // Low = strictly below the threshold or nothing usable; the server
            // decides (it knows expired lots), the comparison is only a fallback.
            status: m.stock_status
              ? ((m.stock_status === 'low' || m.stock_status === 'out') ? 'low' : 'adequate')
              : ((m.stock !== undefined ? Number(m.stock) : Number(m.stock_quantity || 0)) < (isFinite(Number(m.min_stock_level)) && m.min_stock_level !== null && m.min_stock_level !== '' ? Number(m.min_stock_level) : 15) ? 'low' : 'adequate')
          }));
        }
      }

      if (staffRes.ok) {
        const staffList = await staffRes.json();
        if (Array.isArray(staffList)) {
          // Only the new-bill form's doctor picker uses this list now. Pay
          // used to be built here too, from 8 500 000 / 12 000 000 and an
          // 8-10 % "commission" typed into this file; it now comes from the
          // server payroll (loadPayroll).
          const docStaff = staffList.filter(s => s.role === 'doctor' || s.role === 'chief_doctor' || (s.specialty && s.specialty.trim() !== '') || String(s.full_name || '').toLowerCase().includes('dr'));
          accountingData.doctors_list = docStaff.map((d) => ({
            id: d.id,
            name: d.full_name,
            role: d.specialty || d.role || 'Shifokor'
          }));
        }
      }

      if (ledgerRes.ok) {
        const ledgerRows = await ledgerRes.json();
        if (Array.isArray(ledgerRows)) {
          accountingData.patients_billing = ledgerRows.map(row => {
            // A desk visit (consultation or outpatient course) is billed on
            // its appointment: no bed, no daily price, no length.
            const isVisit = !row.admission_id;
            return {
              id: row.invoice_id,
              booking_id: row.admission_id,
              appointment_id: row.appointment_id || null,
              patient_id: row.patient_id || null,
              is_visit: isVisit,
              // These used to fall back to bed BED-1A, a fake phone number,
              // today and a 10-day stay, so a bill missing them showed (and
              // printed) a stay nobody had. Missing stays missing ("—").
              bed_id: row.bed_id || null,
              bed_name: row.room_number ? `${row.room_number}-xona (${row.bed_code || ''})` : (row.bed_code || 'Ambulator'),
              patient_name: row.patient_name || 'Bemor',
              patient_phone: row.patient_phone || '',
              patient_city: '',
              program: VISIT_LABELS[row.program_type] || row.program_type || '—',
              // The stay's own programme decides the package; the price is
              // only a guess for a programme that is not a package id.
              package_type: isVisit ? null : (OFFICIAL_RATES[row.program_type] ? row.program_type
                : ((listedRate('statsionar_full_room') > 0 &&
                    Number(row.daily_price) >= listedRate('statsionar_full_room'))
                   ? 'statsionar_full_room' : 'statsionar_shared')),
              doctor: row.doctor_name || 'Shifokor biriktirilmagan',
              start_date: row.start_date ? String(row.start_date).slice(0, 10) : '',
              end_date: row.end_date ? String(row.end_date).slice(0, 10) : '',
              days_count: Number(row.total_days) > 0 ? Number(row.total_days) : null,
              // A stay with no stored rate shows 0, not an invented 720 000.
              daily_rate: Number(row.daily_price) || 0,
              gross_due: Number(row.total_billed) || 0,
              discount_amount: Number(row.discount_amount) || 0,
              total_due: row.net_amount || row.total_billed,
              paid_cash: row.paid_cash || 0,
              paid_terminal: row.paid_terminal || 0,
              paid_online: row.paid_card_online || 0,
              paid_bank: 0,
              total_paid: row.total_paid || 0,
              debt_remaining: row.balance_due || 0,
              // Saved bill lines from the server; the totals above already
              // include them (the invoice triggers add them up).
              extra_services: (accountingData.invoice_items || [])
                .filter(it => it.invoice_id === row.invoice_id)
                .map(it => ({
                  id: it.id,
                  name: it.service_name,
                  type: it.item_type,
                  unit_price: Number(it.unit_price) || 0,
                  qty: Number(it.quantity) || 1,
                  total: Number(it.total_amount) || 0,
                  notes: '',
                  added_at: it.created_at
                })),
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

  // The month's pay, from the server (GET /api/hr/payroll): base salary
  // plus the duty shifts saved on the roster, minus income tax and pension,
  // exactly as the HR page shows it. This page used to work out its own
  // "doctors payroll" from figures typed into this file (8 500 000 /
  // 12 000 000 and an 8-10 % share of patient bills that nobody had ever
  // set), and paid that out -- a second pay formula next to HR's.
  // There is no recorded commission rate, so no commission is shown; the PO
  // decides whether doctors get one (CHANGES.md).
  function currentPayrollMonth() {
    if (!payrollMonth) payrollMonth = getTodayISO().slice(0, 7);
    return payrollMonth;
  }

  function updatePayrollTitle() {
    const payrollTitle = document.getElementById('accounting-doctors-title');
    if (!payrollTitle) return;
    const [y, m] = currentPayrollMonth().split('-').map(Number);
    const label = new Date(y, m - 1, 1).toLocaleDateString('uz-UZ', { month: 'long', year: 'numeric' });
    payrollTitle.innerHTML = `<i class="fas fa-user-md" style="color: var(--primary);"></i> Xodimlar Oylik Maoshi — Kadrlar hisobi (${esc(label)})`;
  }

  async function loadPayroll() {
    const month = currentPayrollMonth();
    let res;
    try {
      res = await fetch('/api/hr/payroll?month=' + encodeURIComponent(month));
    } catch (e) {
      accountingData.payroll_lines = [];
      accountingData.payroll_info = { month, error: "Server bilan aloqa yo'q — maosh hisobi yuklanmadi." };
      return;
    }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      accountingData.payroll_lines = [];
      accountingData.payroll_info = {
        month,
        error: res.status === 403
          ? "Maosh hisobi faqat buxgalteriya va kadrlar bo'limiga ko'rinadi."
          : (body.error || `Maosh hisobi yuklanmadi (${res.status}).`)
      };
      return;
    }
    accountingData.payroll_lines = (Array.isArray(body.staff) ? body.staff : []).map(l => ({
      id: l.staff_id,
      name: l.full_name || '',
      role: l.role || '',
      is_active: l.is_active !== false,
      base_salary: Number(l.base_salary) || 0,
      duty_shifts: Number(l.duty_shifts) || 0,
      duty_pay: Number(l.duty_pay) || 0,
      gross: Number(l.gross) || 0,
      income_tax: Number(l.income_tax) || 0,
      pension: Number(l.pension) || 0,
      deductions: Number(l.deductions) || 0,
      net: Number(l.net) || 0
    }));
    accountingData.payroll_info = {
      month: body.month || month,
      totals: body.totals || null,
      rates: body.rates || null,
      unlinked: Array.isArray(body.unlinked_shifts) ? body.unlinked_shifts : [],
      mismatches: Array.isArray(body.name_mismatches) ? body.name_mismatches : []
    };
  }

  // Paid for the picked payroll month if the journal holds a salary payout
  // for this person and that month. Worked out on every render from the
  // synced journal, so the badge cannot drift back to "calculated" and invite
  // a second payout. Older payouts carry no payroll_month and count by the
  // day they were recorded; the server makes the same check and refuses a
  // repeat, so this is only the early warning.
  function payrollPaid(staffId) {
    const month = currentPayrollMonth();
    return (accountingData.transactions || []).some(t =>
      t.category === 'salary' && t.related_staff_id === staffId &&
      String(t.payroll_month || t.date || '').slice(0, 7) === month);
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

      // A desk visit has no daily rate; its price is the bill line itself.
      let priceTag = b.is_visit ? '' : `<span style="font-family: var(--font-mono); font-size: 0.72rem; color: #38bdf8; background: rgba(56, 189, 248, 0.12); padding: 2px 6px; border-radius: 4px;">${formatShortUZS(b.daily_rate)}/kun</span>`;

      let extraServicesHTML = '';
      if (b.extra_services && b.extra_services.length > 0) {
        extraServicesHTML = `
          <div style="margin-top: 4px; display: flex; flex-wrap: wrap; gap: 4px;">
            ${b.extra_services.map(s => `
              <span class="extra-service-pill" title="${esc(s.notes || '')}">
                <i class="fas fa-plus-circle"></i> ${esc(s.name)} (${s.qty}x = +${formatShortUZS(s.total)})
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
        ? `<button class="btn-portal btn-outline-portal" style="padding: 4px 8px; font-size: 0.75rem; background: rgba(245, 158, 11, 0.15); color: #fbbf24; border-color: rgba(245, 158, 11, 0.4);" onclick="window.FMH_Accounting.openPaymentModal(${jsArg(b.id)}, true)" title="Bemorga ortiqcha to'langan pulni qaytarish (Refund Payout)">
             <i class="fas fa-undo"></i> Qaytarish
           </button>`
        : `<button class="btn-portal btn-primary-portal" style="padding: 4px 8px; font-size: 0.75rem;" onclick="window.FMH_Accounting.openPaymentModal(${jsArg(b.id)})" title="To'lov Qabul Qilish">
             <i class="fas fa-hand-holding-usd"></i> To'lov
           </button>`;

      return `
        <tr>
          <td class="mono-val" style="color: var(--primary); font-weight: 700;">${esc(b.id)}</td>
          <td>
            <div class="patient-cell">
              <span class="patient-name-bold">${esc(b.patient_name)}</span>
              <span class="patient-details-sub"><i class="fas fa-phone-alt"></i> ${esc(b.patient_phone || '—')}${b.patient_city ? ' • ' + esc(b.patient_city) : ''}</span>
            </div>
          </td>
          <td>
            <div style="font-weight: 600; color: var(--text-primary); display: flex; align-items: center; gap: 6px;">
              ${esc(b.bed_name || 'Ambulator')} ${priceTag}
            </div>
            <div class="patient-details-sub">${esc(b.program)} (${b.days_count ? b.days_count + ' kun' : (b.is_visit ? esc(b.start_date || '—') : '—')})</div>
            ${extraServicesHTML}
          </td>
          <td>
            <span style="font-size: 0.8rem; color: var(--text-secondary);">${esc(b.doctor || 'Shifokor biriktirilmagan')}</span>
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
              <button class="btn-portal btn-outline-portal" style="padding: 4px 8px; font-size: 0.75rem; color: var(--purple); border-color: rgba(168, 85, 247, 0.4);" onclick="window.FMH_Accounting.openAddServiceModal(${jsArg(b.id)})" title="Qo'shimcha Dori/Xizmat Qo'shish">
                <i class="fas fa-plus"></i> Xizmat
              </button>
              <button class="btn-portal btn-outline-portal" style="padding: 4px 8px; font-size: 0.75rem;" onclick="window.FMH_Accounting.openInvoiceReceipt(${jsArg(b.id)})" title="Kvitansiya / Chek">
                <i class="fas fa-receipt"></i> Chek
              </button>
              ${b.patient_id ? `<button class="btn-portal btn-outline-portal" style="padding: 4px 8px; font-size: 0.75rem;" data-patient-id="${esc(b.patient_id)}" onclick="window.FMH_Accounting.openPatientInvoices(this.dataset.patientId)" title="Bemorning barcha hisoblari">
                <i class="fas fa-folder-open"></i> Hisoblar
              </button>` : ''}
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
          <td class="mono-val" style="color: var(--text-muted); font-size: 0.78rem;">${esc(t.id)}</td>
          <td>
            <div style="font-weight: 600; color: var(--text-primary);">${esc(t.title)}</div>
            <div class="patient-details-sub">${esc(t.notes || '')}</div>
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
            <button class="btn-portal btn-outline-portal" style="padding: 3px 8px; font-size: 0.75rem;" onclick="window.FMH_Accounting.printTxnReceipt(${jsArg(t.id)})">
              <i class="fas fa-receipt"></i> Kvitansiya
            </button>
          </td>
        </tr>
      `;
    }).join('');
  }

  // ==========================================================================
  // RENDER TAB: STAFF PAYROLL (from the server; see loadPayroll)
  // ==========================================================================

  const ROLE_LABELS = {
    chief_doctor: 'Bosh shifokor', doctor: 'Shifokor', nurse: 'Hamshira',
    sanitar: 'Sanitarka', receptionist: 'Qabulxona', accountant: 'Buxgalter',
    admin: 'Administrator', pharmacist: 'Farmatsevt', hr_manager: 'Kadrlar bo\'limi',
    ward_manager: 'Statsionar menejeri', kitchen_staff: 'Oshxona', support: 'Xodim'
  };

  function renderDoctorsPayroll() {
    const grid = document.getElementById('doctors-payroll-grid');
    if (!grid || !accountingData) return;

    const info = accountingData.payroll_info;
    const list = Array.isArray(accountingData.payroll_lines) ? accountingData.payroll_lines : [];
    const emptyBox = (title, text) => `
        <div style="grid-column: 1/-1; text-align: center; padding: 3rem; color: var(--text-muted); background: var(--card-bg); border-radius: 12px; border: 1px dashed var(--border-color);">
          <i class="fas fa-user-md" style="font-size: 2.2rem; margin-bottom: 0.75rem; opacity: 0.5; color: var(--primary);"></i>
          <div style="font-size: 1rem; font-weight: 700; color: var(--text-primary); margin-bottom: 0.25rem;">${esc(title)}</div>
          <div style="font-size: 0.85rem;">${esc(text)}</div>
        </div>`;

    if (info && info.error) {
      grid.innerHTML = emptyBox("Maosh hisobi ko'rsatilmaydi", info.error);
      return;
    }
    if (list.length === 0) {
      grid.innerHTML = emptyBox("Hozircha oylik qaydnomasi bo'sh",
        "Kadrlar (HR) bo'limida xodimlar va ularning maoshi kiritilgach, bu yerda ko'rinadi.");
      return;
    }

    // Roster days the server could not pay to anyone are reported, not
    // guessed at: HR has to fix the roster or the staff record.
    const unlinked = (info && info.unlinked) || [];
    const mismatches = (info && info.mismatches) || [];
    const skipped = unlinked.reduce((s, u) => s + (Number(u.shifts) || 0), 0) +
                    mismatches.reduce((s, m) => s + (Number(m.shifts) || 0), 0);
    const warning = skipped > 0 ? `
        <div style="grid-column: 1/-1; padding: 0.75rem 1rem; border-radius: 10px; background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.4); color: #fbbf24; font-size: 0.85rem;">
          <i class="fas fa-exclamation-triangle"></i> Navbatchilik jadvalidagi ${skipped} ta smena hech bir xodimga bog'lanmagan yoki ismi mos kelmaydi — ular maoshga qo'shilmadi. Kadrlar bo'limida tekshiring.
        </div>` : '';

    grid.innerHTML = warning + list.map(doc => {
      const paid = payrollPaid(doc.id);
      return `
        <div class="doctor-payroll-card">
          <div class="doc-card-header">
            <div class="doc-avatar"><i class="fas fa-user-md"></i></div>
            <div class="doc-info">
              <div class="doc-name">${esc(doc.name)}</div>
              <div class="doc-role">${esc(ROLE_LABELS[doc.role] || doc.role || 'Xodim')}${doc.is_active ? '' : ' (faol emas)'}</div>
            </div>
            <span class="badge-status ${paid ? 'badge-paid' : 'badge-partial'}">
              ${paid ? "To'langan" : "Hisoblangan"}
            </span>
          </div>

          <div class="doc-stats-row">
            <div class="doc-stat-item">
              <div class="label">Asosiy Oylik Maosh</div>
              <div class="val">${formatShortUZS(doc.base_salary)}</div>
            </div>
            <div class="doc-stat-item">
              <div class="label">Navbatchilik (${doc.duty_shifts} smena)</div>
              <div class="val" style="color: var(--emerald);">+${formatShortUZS(doc.duty_pay)}</div>
            </div>
            <div class="doc-stat-item">
              <div class="label">Hisoblangan (brutto)</div>
              <div class="val">${formatShortUZS(doc.gross)}</div>
            </div>
            <div class="doc-stat-item">
              <div class="label">Ushlab qolinadi (soliq + pensiya)</div>
              <div class="val" style="color: var(--rose);">-${formatShortUZS(doc.deductions)}</div>
            </div>
          </div>

          <div class="doc-total-payable-box">
            <div class="doc-payable-label">Qo'lga beriladi (sof):</div>
            <div class="doc-payable-amount">${formatUZS(doc.net)}</div>
          </div>

          <div style="display: flex; gap: 0.5rem; justify-content: flex-end;">
            <button class="btn-portal btn-success-portal" style="width: 100%;" data-staff-id="${esc(doc.id)}" onclick="window.FMH_Accounting.payoutDoctorSalary(this.dataset.staffId)">
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

  // ------------------------------------------------------------
  // MEDICINE USE: doses the nurses marked "given", what they took
  // from stock and what that cost at the buying price.
  // ------------------------------------------------------------
  function isoDay(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  async function loadMedicineUsage() {
    const startEl = document.getElementById('med-usage-start');
    const endEl = document.getElementById('med-usage-end');
    const tbody = document.getElementById('med-usage-tbody');
    if (!startEl || !endEl || !tbody) return;
    if (!startEl.value || !endEl.value) {
      const now = new Date();
      startEl.value = isoDay(new Date(now.getFullYear(), now.getMonth(), 1));
      endEl.value = isoDay(now);
    }
    let usage;
    try {
      const res = await fetch(`/api/accounting/medicine-usage?start=${encodeURIComponent(startEl.value)}&end=${encodeURIComponent(endEl.value)}`);
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        window.FMH_Toast(body.error || `Dori sarfini yuklab bo'lmadi (${res.status})`, 'danger');
        return;
      }
      usage = body;
    } catch (e) {
      window.FMH_Toast("Server bilan aloqa yo'q", 'danger');
      return;
    }

    const summary = document.getElementById('med-usage-summary');
    if (summary) {
      summary.innerHTML = `Jami berilgan dozalar: <strong>${usage.total_doses}</strong> • Ombordagi dorilar tannarxi: <strong>${formatUZS(usage.total_cost)}</strong>`;
    }

    tbody.innerHTML = usage.linked.length ? usage.linked.map(r => {
      const low = (r.low !== undefined) ? !!r.low : r.stock_quantity < r.min_stock_level;
      const shortfall = Math.round((Number(r.doses) - Number(r.units_taken)) * 1000) / 1000;
      return `
        <tr>
          <td><strong>${esc(r.name)}</strong><br><small style="color: var(--text-muted);">${esc(r.form)}</small></td>
          <td>${r.doses}</td>
          <td>${fmtQty(r.units_taken)}${shortfall > 0 ? ` <small style="color: var(--warning);">(${fmtQty(shortfall)} tasi uchun omborda qoldiq yo'q edi)</small>` : ''}</td>
          <td>${formatUZS(r.cost)}</td>
          <td style="color: ${low ? 'var(--warning)' : 'inherit'}; font-weight: 700;">${fmtQty(r.stock_quantity)}</td>
        </tr>`;
    }).join('') : `<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">Bu davrda ombordagi dorilardan berilmagan</td></tr>`;

    const box = document.getElementById('med-unlinked-box');
    if (!box) return;
    if (!usage.unlinked.length) {
      box.innerHTML = '';
      return;
    }
    const stock = Array.isArray(accountingData && accountingData.pharmacy_stock) ? accountingData.pharmacy_stock : [];
    const options = stock.map(m => `<option value="${esc(m.id)}">${esc(m.name)} (${esc(m.form)})</option>`).join('');
    box.innerHTML = `
      <div style="font-weight: 700; margin-bottom: 0.5rem; color: var(--warning);">
        <i class="fas fa-link"></i> Ombor bilan bog'lanmagan dorilar
      </div>
      <div style="font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 0.75rem;">
        Shifokor yozgan nom ombordagi nomga mos kelmadi, shuning uchun bu dozalar ombordan ayirilmadi. Bir marta bog'lang — keyingi dozalar avtomatik hisoblanadi.
      </div>
      ${usage.unlinked.map((u, i) => `
        <div style="display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; padding: 0.5rem 0; border-top: 1px solid var(--border-color);">
          <span style="flex: 1 1 200px;"><strong>${esc(u.medication_name)}</strong> — ${u.doses} doza</span>
          <select class="form-input med-link-select" data-idx="${i}" style="flex: 1 1 200px; width: auto;">
            <option value="">Ombordagi dorini tanlang...</option>${options}
          </select>
          <button type="button" class="btn-portal btn-primary-portal med-link-btn" data-idx="${i}">Bog'lash</button>
        </div>`).join('')}
    `;
    box.querySelectorAll('.med-link-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = Number(btn.dataset.idx);
        const sel = box.querySelector(`.med-link-select[data-idx="${idx}"]`);
        linkMedicineName(usage.unlinked[idx].medication_name, sel ? sel.value : '');
      });
    });
  }

  async function linkMedicineName(name, medicationId) {
    if (!medicationId) {
      window.FMH_Toast("Ombordagi dorini tanlang", 'warning');
      return;
    }
    try {
      const res = await fetch('/api/accounting/medicine-links', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ medication_name: name, medication_id: medicationId })
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        window.FMH_Toast(body.error || `Bog'lab bo'lmadi (${res.status})`, 'danger');
        return;
      }
      const past = Number(body.settled_doses) || 0;
      window.FMH_Toast(`"${name}" ombor bilan bog'landi.${past ? ` Avval berilgan ${past} doza ham ombordan ayirildi.` : ''} Keyingi dozalar avtomatik ayiriladi.`, 'success');
      loadMedicineUsage();
    } catch (e) {
      window.FMH_Toast("Server bilan aloqa yo'q", 'danger');
    }
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
        ? `<button class="btn-portal btn-outline-portal" style="padding: 2px 7px; font-size: 0.72rem;" onclick="window.FMH_Accounting.printTxnReceipt(${jsArg(p.accounting_transaction_id)})" title="Kassa Cheki">
             <i class="fas fa-receipt"></i> Chek
           </button>`
        : '';

      const deleteBtn = `<button class="btn-portal btn-outline-portal" style="padding: 2px 7px; font-size: 0.72rem; color: var(--rose); border-color: rgba(244,63,94,0.3);" onclick="window.FMH_Accounting.deleteMedPurchase(${jsArg(p.id)})" title="Xaridni bekor qilish">
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
      const minStock = Number(item.min_stock_level);
      // The server's verdict wins (strictly below the threshold, expired lots
      // not counted); the comparison is only a fallback and is strict too.
      const isLow = item.stock_status ? (item.stock_status === 'low' || item.stock_status === 'out') : stock < minStock;
      const availNum = (item.available_quantity === null || item.available_quantity === undefined) ? null : Number(item.available_quantity);
      const usableNote = (availNum !== null && isFinite(availNum) && availNum < stock)
        ? `<br><small style="color: var(--text-muted); font-weight: 400;">yaroqli: ${fmtQty(availNum)}</small>` : '';
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
          <td class="mono-val" style="font-weight: 700; color: ${isLow ? 'var(--rose)' : 'var(--primary)'};">${fmtQty(stock)} ${esc(unitName)}${usableNote}</td>
          <td class="mono-val">${formatUZS(unitPrice)}</td>
          <td class="mono-val" style="font-weight: 700; color: var(--text-primary);">${formatUZS(totalVal)}</td>
          <td>${badge}</td>
          <td>
            <button class="btn-portal btn-outline-portal" style="padding: 2px 8px; font-size: 0.75rem;" onclick="window.FMH_Accounting.openMedPurchaseModal(${jsArg(item.id)})" title="Ushbu dorini xarid qilish (Kirim)">
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

      // Patient payments are already in the transactions above: the
      // payments trigger writes each one into accounting_transactions on the
      // day it was paid. Adding the bills' total_paid as well counted every
      // patient payment twice (and on the stay's start month, not the day
      // the money came in).
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
    let consultAmt = 0;

    (accountingData.patients_billing || []).forEach(p => {
      const prog = (p.program || '').toLowerCase();
      const due = Number(p.total_due) || 0;
      // A desk visit's whole bill is its one line: count it once, under its
      // own heading, not again as an "extra service".
      if (p.is_visit) {
        if (prog.includes('konsultatsiya')) consultAmt += due;
        else ambulatorAmt += due;
        return;
      }
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

    const totalAll = statsionarAmt + kunlikAmt + ambulatorAmt + consultAmt + pharmacyAmt;
    const calcPct = (amt) => totalAll > 0 ? Math.round((amt / totalAll) * 100) : 0;

    const depts = [
      { name: "Statsionar Davolanish (720 ming / 1.1 mln)", amount: statsionarAmt, color: "#38bdf8", pct: calcPct(statsionarAmt) },
      { name: "Kunlik Statsionar (630 ming / kun)", amount: kunlikAmt, color: "#10b981", pct: calcPct(kunlikAmt) },
      { name: "Ambulator Muolajalar (310 ming & 500 ming)", amount: ambulatorAmt, color: "#a855f7", pct: calcPct(ambulatorAmt) },
      { name: "Shifokor Konsultatsiyalari", amount: consultAmt, color: "#818cf8", pct: calcPct(consultAmt) },
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

    // Itemized table rows. Only a stay has a bed-days line; a desk visit
    // (consultation, outpatient course) is just its own bill line below.
    const hasStayRow = !bill.is_visit && bill.days_count;
    let itemRows = hasStayRow ? `
      <tr>
        <td>1</td>
        <td><strong>${esc(bill.program)}</strong><br><small style="color: #64748b;">${esc(bill.bed_name)} • Shifokor nazorati, muolajalar va parhez taomnoma</small></td>
        <td style="text-align: center; font-weight: 700;">${bill.days_count} kun</td>
        <td style="text-align: right;">${formatUZS(bill.daily_rate)}</td>
        <td style="text-align: right; font-weight: 700;">${formatUZS(bill.days_count * bill.daily_rate)}</td>
      </tr>
    ` : '';

    if (bill.extra_services && bill.extra_services.length > 0) {
      bill.extra_services.forEach((s, i) => {
        itemRows += `
          <tr>
            <td>${i + (hasStayRow ? 2 : 1)}</td>
            <td><strong>${esc(s.name)}</strong><br><small style="color: #64748b;">Qo'shimcha tayinlangan muolaja / dori (${esc(s.notes || 'Shifokor ko\'rsatmasi')})</small></td>
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
            <div class="name">${esc(bill.patient_name)}</div>
            <div style="font-size: 0.8rem; color: #475569;">Tel: ${esc(bill.patient_phone || '—')}</div>
            <div style="font-size: 0.8rem; color: #475569;">Manzil: ${bill.patient_city || '—'}</div>
          </div>
          <div class="inv-meta-col">
            <div class="title">Muolaja / Tarif Paketi:</div>
            <div style="font-weight: 700; color: #0f172a;">${esc(bill.program)}</div>
            <div style="font-size: 0.8rem; color: #475569;">Joy: ${esc(bill.bed_name || 'Ambulator')}</div>
            <div style="font-size: 0.8rem; color: #475569;">${bill.is_visit
              ? `Sana: ${esc(bill.start_date || '—')}`
              : `Davomiyligi: ${bill.days_count ? bill.days_count + ' kun' : '—'} (${esc(bill.start_date || '—')} — ${esc(bill.end_date || '—')})`}</div>
            <div style="font-size: 0.8rem; color: #475569;">Mas'ul shifokor: ${esc(bill.doctor || '—')}</div>
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
            <div>Kassir-Buxgalter: ____________________</div>
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
            <span style="text-align: right; font-weight: 600;">${esc(t.title)}</span>
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
      // A refused payment used to close the form with no message, so the
      // cashier could not tell it had not been recorded. The form now stays
      // open with the server's reason.
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.error || `To'lov saqlanmadi (${res.status})`, 'danger');
        return;
      }
      if (isRefund) {
        showToast(`💸 ${bill.patient_name} uchun ${formatUZS(Math.abs(amount))} qaytarish kassa jurnaliga kiritildi!`, 'info');
      } else {
        showToast(`✅ ${bill.patient_name} uchun ${formatUZS(amount)} to'lov muvaffaqiyatli qabul qilindi!`, 'success');
      }
    } catch (err) {
      showToast("Server bilan aloqa yo'q — to'lov saqlanmadi.", 'danger');
      return;
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

    fillAddServiceOptions();
    updateAddServiceCalculation();
    modal.classList.add('active');
  }

  // The choice list used to be 8 fixed demo medicines (ids no stock item
  // has) and 5 services at prices typed into the page. It is now the real
  // stock with its prices, and the services from the one price list.
  let addSvcPricing = null;
  function fillAddServiceOptions() {
    const select = document.getElementById('addsvc-item-select');
    if (!select) return;
    const build = () => {
      const meds = (accountingData.pharmacy_stock || []).filter(m => m.id);
      const svcs = (addSvcPricing && Array.isArray(addSvcPricing.additional_services))
        ? addSvcPricing.additional_services : null;
      const keepServices = svcs ? null : select.querySelector('optgroup[data-group="services"]') ||
        Array.from(select.querySelectorAll('optgroup')).find(g => g.querySelector('option[value^="srv-"]'));
      const parts = [];
      parts.push('<optgroup label="Dorixona Ombordagi Dorilar (Ombordan hisobdan chiqariladi)">' +
        (meds.length ? meds.map(m =>
          `<option value="MED:${esc(m.id)}" data-price="${Number(m.unit_price) || 0}" data-type="pharmacy"${billableQty(m) > 0 ? '' : ' disabled'}>` +
          `💊 ${esc(m.name)}${m.form ? ' (' + esc(m.form) + ')' : ''} — ${formatUZS(Number(m.unit_price) || 0)} · qoldiq ${fmtQty(billableQty(m))}</option>`
        ).join('') : '<option value="" disabled>Ombor ma\'lumoti yuklanmagan</option>') +
        '</optgroup>');
      if (svcs) {
        parts.push('<optgroup data-group="services" label="Qo\'shimcha Tibbiy Muolajalar & Tekshiruvlar">' +
          svcs.map(s => `<option value="${esc(s.id)}" data-price="${Number(s.price) || 0}" data-type="procedure">` +
            `${esc(s.name)} — ${formatUZS(Number(s.price) || 0)}</option>`).join('') +
          '</optgroup>');
      } else if (keepServices) {
        keepServices.setAttribute('data-group', 'services');
        parts.push(keepServices.outerHTML);
      }
      select.innerHTML = parts.join('');
      const first = select.querySelector('option:not([disabled])');
      if (first) select.value = first.value;
      updateAddServiceCalculation();
    };
    build();
    if (!addSvcPricing) {
      fetch('/api/settings/pricing', { cache: 'no-store' })
        .then(r => r.ok ? r.json() : null)
        .then(p => { if (p && Array.isArray(p.additional_services)) { addSvcPricing = p; build(); } })
        .catch(() => {});
    }
  }

  function updateAddServiceCalculation() {
    const select = document.getElementById('addsvc-item-select');
    const qty = Number(document.getElementById('addsvc-qty-input').value) || 1;
    if (!select) return;

    const opt = select.selectedOptions[0];
    if (!opt) return;
    const unitPrice = Number(opt.dataset.price) || 0;
    const total = unitPrice * qty;

    const preview = document.getElementById('addsvc-total-preview');
    if (preview) {
      preview.textContent = formatUZS(total);
    }
  }

  // The bill line is saved on the server, which sets the price (price list
  // or stock) and takes medicine off the shelf. The line used to live only
  // in this page's copy of the bill and vanished on the next 4-second sync.
  async function handleAddServiceSubmit(e) {
    e.preventDefault();
    const billId = document.getElementById('addsvc-bill-id').value;
    const select = document.getElementById('addsvc-item-select');
    const qty = Number(document.getElementById('addsvc-qty-input').value) || 1;
    const notes = document.getElementById('addsvc-notes-input').value.trim();

    if (!billId || !select || !select.value) return;

    const bill = accountingData.patients_billing.find(b => b.id === billId);
    if (!bill) return;

    const opt = select.selectedOptions[0];
    const rawName = opt.textContent.split('—')[0].trim();
    const submitBtn = e.submitter || null;
    if (submitBtn) submitBtn.disabled = true;
    try {
      const res = await fetch('/api/accounting/invoice-items', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ invoice_id: bill.id, service_code: select.value, quantity: qty, notes: notes })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showToast(data.error || `Xizmat qo'shilmadi (${res.status})`, 'danger');
        return;
      }
      closeAllModals();
      await syncWithLedgerAndBackend(false);
      renderAll();
      showToast(`💊 <strong>${esc(data.service_name || rawName)}</strong> (${qty}x) ${esc(bill.patient_name)} hisobiga qo'shildi.`);
    } catch (err) {
      showToast("Server bilan aloqa yo'q — xizmat qo'shilmadi.", 'danger');
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
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
    // The field came pre-filled with a name nobody at the clinic has, so
    // every hand-over was signed by him unless somebody retyped it.
    if (!collector) {
      showToast("Inkassator / mas'ul xodim ismini kiriting.", 'warning');
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
      // The server keeps only the title (as the journal description), so
      // the required collector name went nowhere; it is part of the title.
      title: `Bankka naqd pul inkassatsiyasi (${bank}) — topshirdi: ${collector}${notes ? '. ' + notes : ''}`,
      amount: amount,
      payment_method: "cash",
      patient_name: null,
      bill_id: null,
      date: getTodayISO(),
      time: new Date().toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' }),
      cashier: collector,
      notes: `${bank} bank hisob raqamiga topshirildi. ${notes}`
    };

    const savedId = await postTransaction(newTxn);
    if (!savedId) return;
    newTxn.id = savedId;

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
    // Left empty: the length of a stay is the desk's to type. A prefilled
    // 10 days billed ten days to anyone who did not change it.
    document.getElementById('newbill-days-input').value = '';
    document.getElementById('newbill-advance-input').value = '';

    const docSelect = document.getElementById('newbill-doctor-select');
    if (docSelect) {
      if (accountingData.doctors_list && accountingData.doctors_list.length > 0) {
        docSelect.innerHTML = accountingData.doctors_list.map(d => `<option value="${esc(d.name)}">${esc(d.name)} (${esc(d.role)})</option>`).join('');
      } else {
        docSelect.innerHTML = `<option value="">— Shifokor biriktirilmagan —</option>`;
      }
    }

    updateNewBillCalculation();

    modal.classList.add('active');
  }

  function updateNewBillCalculation() {
    const pkgKey = document.getElementById('newbill-package-select').value;
    const days = Number(document.getElementById('newbill-days-input').value) || 0;
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
    const days = Number(document.getElementById('newbill-days-input').value);
    const bedId = document.getElementById('newbill-bed-select').value;
    const doctor = document.getElementById('newbill-doctor-select').value;
    const advancePaid = Number(document.getElementById('newbill-advance-input').value) || 0;
    const method = document.getElementById('newbill-method-select').value;

    if (!name) {
      showToast("Iltimos, bemor ismini kiriting!", 'warning');
      return;
    }
    // A blank length used to become 10 days.
    if (!Number.isInteger(days) || days < 1) {
      showToast("Necha kun yotishini kiriting.", 'warning');
      return;
    }

    const pkg = OFFICIAL_RATES[pkgKey] || OFFICIAL_RATES.statsionar_shared;
    const totalDue = pkg.rate * days;
    const debt = Math.max(0, totalDue - advancePaid);

    let resJsonInvoiceId = null;
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
      resJsonInvoiceId = resJson.invoice_id || null;
    } catch (e) {
      showToast("Server bilan aloqa yo'q — qabul saqlanmadi.", 'error');
      return;
    }

    // The stay is saved by now; the advance is a second request. Its answer
    // was ignored, so a refused advance still read as paid. Say so instead,
    // and let the stay stand.
    if (resJsonInvoiceId && advancePaid > 0) {
      let advanceError = null;
      try {
        const payRes = await fetch('/api/payments', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            invoice_id: resJsonInvoiceId,
            amount: advancePaid,
            payment_method: method,
            account_destination: method === 'cash' ? 'kassa' : 'terminal_bank',
            notes: `Yangi hisob ochilganda avans to'lovi (${days} kunlik)`,
            payment_date: getTodayISO()
          })
        });
        if (!payRes.ok) {
          const err = await payRes.json().catch(() => ({}));
          advanceError = err.error || `Xatolik (${payRes.status})`;
        }
      } catch (e) {
        advanceError = "Server bilan aloqa yo'q";
      }
      if (advanceError) {
        showToast(`Diqqat: hisob ochildi, lekin avans to'lovi saqlanmadi — ${esc(advanceError)}. To'lovni qayta kiriting.`, 'warning');
      }
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
      // Nobody at the clinic has this name; the journal shows who signed in.
      cashier: '',
      notes: notes
    };

    const savedId = await postTransaction(newTxn);
    if (!savedId) return;
    newTxn.id = savedId;

    accountingData.transactions.unshift(newTxn);
    saveData();
    closeAllModals();
    renderAll();
    showToast(type === 'income' ? `✅ Yangi tushum (${formatUZS(amount)}) qo'shildi!` : `💸 Yangi xarajat (${formatUZS(amount)}) qayd etildi!`, type === 'income' ? 'success' : 'info');
  }

  // Saves one cash-journal entry and returns the server's id, or null after
  // showing why it was refused. The three callers ignored the answer, so a
  // refused entry was shown as saved until the next sync quietly dropped it.
  async function postTransaction(txn) {
    try {
      const res = await fetch('/api/accounting/transaction', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(txn)
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showToast(data.error || `Operatsiya saqlanmadi (${res.status})`, 'danger');
        return null;
      }
      return data.id || txn.id;
    } catch (e) {
      showToast("Server bilan aloqa yo'q — operatsiya saqlanmadi.", 'danger');
      return null;
    }
  }

  // ==========================================================================
  // ALL INVOICES OF ONE PATIENT (read-only)
  // ==========================================================================

  const INVOICE_STATUS_LABELS = {
    unpaid: "To'lanmagan", partial: 'Qisman', paid: "To'langan",
    refund_due: 'Qaytarish kerak', refunded: 'Qaytarilgan'
  };
  const ITEM_TYPE_LABELS = {
    bed_stay: 'Yotoq kunlari', consultation: 'Konsultatsiya', medication: 'Dori',
    lab_test: 'Tahlil', procedure: 'Muolaja', other: 'Boshqa'
  };

  // The bills table shows one invoice per row, so a patient's earlier unpaid
  // visit or stay was easy to miss when taking money for the current one.
  // Everything here comes from the server and is escaped; nothing is edited.
  async function openPatientInvoices(patientId) {
    const modal = document.getElementById('patient-invoices-modal');
    const content = document.getElementById('patient-invoices-content');
    if (!modal || !content || !patientId) return;
    content.innerHTML = `<div style="padding: 2rem; text-align: center; color: var(--text-muted);"><i class="fas fa-spinner fa-spin"></i> Yuklanmoqda...</div>`;
    modal.classList.add('active');

    let data;
    try {
      const res = await fetch('/api/accounting/patient-invoices?patient_id=' + encodeURIComponent(patientId));
      data = await res.json().catch(() => ({}));
      if (!res.ok) {
        content.innerHTML = `<div style="padding: 2rem; text-align: center; color: var(--rose);">${esc(data.error || `Hisoblar yuklanmadi (${res.status}).`)}</div>`;
        return;
      }
    } catch (e) {
      content.innerHTML = `<div style="padding: 2rem; text-align: center; color: var(--rose);">Server bilan aloqa yo'q.</div>`;
      return;
    }

    const p = data.patient || {};
    const invoices = Array.isArray(data.invoices) ? data.invoices : [];
    const t = data.totals || {};
    const money = (v) => formatUZS(Number(v) || 0);
    const cell = 'padding: 4px 8px; border-bottom: 1px solid var(--border-color);';

    const invoiceBlock = (inv) => {
      const where = inv.kind === 'visit'
        ? `${esc(VISIT_LABELS[inv.program_type] || inv.program_type || 'Tashrif')} • ${esc(inv.start_date ? String(inv.start_date).slice(0, 10) : '—')}`
        : `${esc(inv.program_type || 'Statsionar')} • ${inv.room_number ? esc(inv.room_number) + '-xona ' : ''}${esc(inv.bed_code || '—')} • ${esc(inv.start_date ? String(inv.start_date).slice(0, 10) : '—')} — ${esc(inv.end_date ? String(inv.end_date).slice(0, 10) : '—')}${inv.total_days ? ' (' + esc(inv.total_days) + ' kun)' : ''}`;
      const items = (inv.items || []).map(it => `
            <tr>
              <td style="${cell}">${esc(it.service_name)}<br><small style="color: var(--text-muted);">${esc(ITEM_TYPE_LABELS[it.item_type] || it.item_type || '')}</small></td>
              <td style="${cell} text-align: center;">${esc(Number(it.quantity))}</td>
              <td style="${cell} text-align: right;">${money(it.unit_price)}</td>
              <td style="${cell} text-align: right; font-weight: 700;">${money(it.total_amount)}</td>
            </tr>`).join('') || `<tr><td colspan="4" style="${cell} color: var(--text-muted);">Qatorlar yo'q</td></tr>`;
      const pays = (inv.payments || []).map(pm => `
            <tr>
              <td style="${cell}">${esc(pm.payment_date ? String(pm.payment_date).slice(0, 10) : '—')}</td>
              <td style="${cell}">${esc(pm.payment_method || '')}${pm.notes ? ' — ' + esc(pm.notes) : ''}</td>
              <td style="${cell} text-align: right; font-weight: 700; color: ${Number(pm.amount) < 0 ? '#fbbf24' : 'var(--emerald)'};">${money(pm.amount)}</td>
            </tr>`).join('') || `<tr><td colspan="3" style="${cell} color: var(--text-muted);">To'lovlar yo'q</td></tr>`;
      return `
        <div style="border: 1px solid var(--border-color); border-radius: 10px; padding: 0.9rem; margin-bottom: 0.9rem;">
          <div style="display: flex; justify-content: space-between; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.4rem;">
            <strong style="font-family: var(--font-mono);">${esc(inv.invoice_id)}</strong>
            <span>${esc(INVOICE_STATUS_LABELS[inv.payment_status] || inv.payment_status || '')}</span>
          </div>
          <div style="font-size: 0.82rem; color: var(--text-secondary); margin-bottom: 0.5rem;">${where} • Shifokor: ${esc(inv.doctor_name || '—')}</div>
          <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; font-size: 0.82rem;">
              <thead><tr><th style="${cell} text-align: left;">Xizmat</th><th style="${cell}">Miqdor</th><th style="${cell} text-align: right;">Narx</th><th style="${cell} text-align: right;">Jami</th></tr></thead>
              <tbody>${items}</tbody>
            </table>
          </div>
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 0.4rem; margin: 0.6rem 0; font-size: 0.82rem;">
            <div>Hisoblangan: <strong>${money(inv.total_billed)}</strong></div>
            <div>Chegirma: <strong>${money(inv.discount_amount)}</strong></div>
            <div>To'lanishi kerak: <strong>${money(inv.net_amount)}</strong></div>
            <div>To'langan: <strong style="color: var(--emerald);">${money(inv.total_paid)}</strong></div>
            <div>Qoldiq: <strong style="color: ${Number(inv.balance_due) > 0 ? 'var(--rose)' : 'inherit'};">${money(inv.balance_due)}</strong></div>
          </div>
          <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; font-size: 0.8rem;">
              <thead><tr><th style="${cell} text-align: left;">To'lov sanasi</th><th style="${cell} text-align: left;">Usul</th><th style="${cell} text-align: right;">Summa</th></tr></thead>
              <tbody>${pays}</tbody>
            </table>
          </div>
        </div>`;
    };

    content.innerHTML = `
      <div style="margin-bottom: 0.9rem;">
        <div style="font-size: 1.05rem; font-weight: 800;">${esc(p.full_name || 'Bemor')}</div>
        <div style="font-size: 0.82rem; color: var(--text-muted);">${esc(p.patient_code || p.id || '')}${p.phone ? ' • ' + esc(p.phone) : ''}</div>
      </div>
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.5rem; margin-bottom: 1rem; font-size: 0.85rem;">
        <div>Hisoblar soni: <strong>${invoices.length}</strong></div>
        <div>Jami to'lanishi kerak: <strong>${money(t.net_amount)}</strong></div>
        <div>Jami to'langan: <strong style="color: var(--emerald);">${money(t.total_paid)}</strong></div>
        <div>Jami qoldiq: <strong style="color: ${Number(t.balance_due) > 0 ? 'var(--rose)' : 'inherit'};">${money(t.balance_due)}</strong></div>
      </div>
      ${invoices.length ? invoices.map(invoiceBlock).join('') : `<div style="padding: 1.5rem; text-align: center; color: var(--text-muted);">Bu bemorda hisob yo'q.</div>`}
    `;
  }

  // ==========================================================================
  // DOCTOR SALARY PAYOUT
  // ==========================================================================

  async function payoutDoctorSalary(docId) {
    const doc = (accountingData.payroll_lines || []).find(d => d.id === docId);
    if (!doc) return;
    if (payrollPaid(doc.id)) {
      showToast(`${esc(doc.name)} uchun ${esc(currentPayrollMonth())} oyi maoshi allaqachon to'langan.`, 'warning');
      return;
    }
    // The employee is handed the net figure. Income tax and pension are
    // withheld from it and go to the state, not to the employee; paying the
    // state is its own expense entry, so recording the gross here would count
    // the withheld part twice once that is entered. The HR payslip calls the
    // same figure "Sof to'lanadigan".
    const amount = Math.round(Number(doc.net) || 0);
    if (!(amount > 0)) {
      showToast("To'lanadigan summa 0 so'm. Avval Kadrlar bo'limida xodimning maoshini kiriting.", 'warning');
      return;
    }
    const month = (accountingData.payroll_info && accountingData.payroll_info.month) || currentPayrollMonth();

    const confirmed = await fmhConfirm({
      title: "Maosh To'lovini Tasdiqlash",
      message: `<strong>${esc(doc.name)}</strong> uchun ${esc(month)} oyi maoshi: qo'lga <strong>${formatUZS(amount)}</strong> (hisoblangan ${formatUZS(doc.gross)}, ushlab qolinadi ${formatUZS(doc.deductions)}). To'lansinmi?`,
      confirmText: "To'lash",
      cancelText: "Bekor Qilish",
      type: 'primary'
    });
    if (!confirmed) {
      return;
    }
    // A second click while the first request is on its way.
    if (payrollPaid(doc.id)) return;

    const newTxn = {
      type: "expense",
      category: "salary",
      // The journal keeps only this text, so the breakdown goes in it.
      title: `Oylik maosh ${month} — ${doc.name} (hisoblangan ${formatUZS(doc.gross)}, ushlab qolindi ${formatUZS(doc.deductions)})`,
      amount: amount,
      related_staff_id: doc.id,
      payroll_month: month,
      payment_method: "bank",
      patient_name: null,
      bill_id: null,
      date: getTodayISO(),
      time: new Date().toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' }),
      cashier: '',
      notes: `${doc.name}: asosiy ${formatUZS(doc.base_salary)} + navbatchilik ${formatUZS(doc.duty_pay)} = ${formatUZS(doc.gross)}; ushlab qolindi ${formatUZS(doc.deductions)}; qo'lga ${formatUZS(amount)}`
    };

    const savedId = await postTransaction(newTxn);
    if (!savedId) return;
    newTxn.id = savedId;

    accountingData.transactions.unshift(newTxn);
    saveData();
    renderAll();
    showToast(`✅ ${esc(doc.name)} ga ${formatUZS(amount)} oylik maosh to'landi va xarajatlarga yozildi!`);
  }

  // ==========================================================================
  // MODAL 8: MEDICATION PURCHASE & RESTOCK (DORI XARIDI VA KLINIKA CHIQIMI)
  // ==========================================================================

  let medPurchaseRowCount = 0;
  let medPurRequestId = '';

  function newRequestId() {
    try {
      if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
    } catch (e) { /* fall through */ }
    return 'medpur-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
  }

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
    // One id per open form: a double click or a retry after a lost answer
    // returns the first purchase instead of booking a second expense.
    medPurRequestId = newRequestId();

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
        <input type="hidden" class="medpur-item-id" value="${initialData ? esc(initialData.id) : ''}">
        <details class="medpur-extra" style="margin-top: 6px;">
          <summary style="cursor: pointer; font-size: 0.74rem; color: var(--text-muted);">Qadoq / partiya / muddat (ixtiyoriy)</summary>
          <div class="medpur-item-help" style="font-size: 0.72rem; color: var(--text-muted); margin-top: 6px;"></div>
          <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px;">
            <input type="number" class="form-input medpur-item-upp" min="0" step="any" placeholder="Qadoqdagi dona (masalan 10)" title="Bir qadoqda nechta dona (tabletka, ml...). Bo'sh qoldirilsa: miqdor — dona, narx — 1 dona narxi." style="flex: 1 1 110px; font-size: 0.8rem;">
            <input type="text" class="form-input medpur-item-batch" maxlength="64" placeholder="Partiya №" style="flex: 1 1 90px; font-size: 0.8rem;">
            <input type="date" class="form-input medpur-item-expiry" title="Yaroqlilik muddati" style="flex: 1 1 130px; font-size: 0.8rem;">
          </div>
          <div class="medpur-item-note" style="font-size: 0.72rem; color: var(--text-muted); margin-top: 4px;"></div>
        </details>
      </td>
      <td style="padding: 6px 8px;">
        <input type="text" class="form-input medpur-item-cat" placeholder="Guruhi" style="font-size: 0.82rem;" value="${initialData ? esc(initialData.group || initialData.category || '') : ''}">
      </td>
      <td style="padding: 6px 8px;">
        <input type="number" class="form-input medpur-item-qty" min="1" step="1" required placeholder="Soni (dona)" style="font-family: var(--font-mono); font-weight: 700; font-size: 0.85rem;" value="1">
        <div class="medpur-item-qty-unit" style="font-size: 0.7rem; color: var(--text-muted); margin-top: 2px;">dona</div>
      </td>
      <td style="padding: 6px 8px;">
        <input type="number" class="form-input medpur-item-price" min="0" step="500" required placeholder="1 dona narxi" style="font-family: var(--font-mono); font-weight: 700; font-size: 0.85rem;" value="">
        <div class="medpur-item-price-unit" style="font-size: 0.7rem; color: var(--text-muted); margin-top: 2px;">1 dona narxi</div>
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
        // The price field is what the clinic PAID. The catalogue's unit_price is
        // what the patient is billed, so it is never offered here as a cost.
      }
      updateMedPurchaseTotals();
    });

    qtyInput.addEventListener('input', updateMedPurchaseTotals);
    priceInput.addEventListener('input', updateMedPurchaseTotals);
    tr.querySelector('.medpur-item-upp').addEventListener('input', updateMedPurchaseTotals);

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
      // With a package size, quantity counts packages and the price is per package.
      // The two ways of reading the same two numbers are spelled out on the row, so the
      // clerk can never mistake "10 packs at 50 000" for "10 tablets at 50 000".
      const upp = parseFloat(tr.querySelector('.medpur-item-upp')?.value) || 0;
      const byPack = upp > 0;
      const note = tr.querySelector('.medpur-item-note');
      if (note) {
        note.textContent = byPack
          ? `Miqdor = qadoq soni, narx = 1 qadoq narxi. Omborga: ${fmtQty(qty)} × ${fmtQty(upp)} = ${fmtQty(qty * upp)} dona (1 dona ≈ ${formatUZS(price / upp)}).`
          : '';
      }
      const help = tr.querySelector('.medpur-item-help');
      if (help) {
        help.textContent = byPack
          ? "Qadoqdagi dona kiritilgan: miqdor — qadoq soni, narx — 1 qadoq narxi."
          : "Bo'sh qoldirilsa: miqdor — dona (asosiy birlik), narx — 1 dona narxi. Qadoq bilan sotib olingan bo'lsa, «Qadoqdagi dona»ni kiriting.";
      }
      const qtyEl = tr.querySelector('.medpur-item-qty');
      if (qtyEl) qtyEl.placeholder = byPack ? 'Qadoq soni' : 'Soni (dona)';
      const priceEl = tr.querySelector('.medpur-item-price');
      if (priceEl) priceEl.placeholder = byPack ? '1 qadoq narxi' : '1 dona narxi';
      const qtyUnit = tr.querySelector('.medpur-item-qty-unit');
      if (qtyUnit) qtyUnit.textContent = byPack ? 'qadoq' : 'dona';
      const priceUnit = tr.querySelector('.medpur-item-price-unit');
      if (priceUnit) priceUnit.textContent = byPack ? '1 qadoq narxi' : '1 dona narxi';
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
    let rowError = null;

    rows.forEach(tr => {
      const name = tr.querySelector('.medpur-item-name')?.value.trim();
      const cat = tr.querySelector('.medpur-item-cat')?.value.trim() || 'Dori-darmon';
      const medId = tr.querySelector('.medpur-item-id')?.value || null;
      const qty = parseFloat(tr.querySelector('.medpur-item-qty')?.value) || 0;
      const price = parseFloat(tr.querySelector('.medpur-item-price')?.value) || 0;

      if (name && qty > 0 && price >= 0) {
        const item = {
          medication_id: medId,
          medication_name: name,
          category: cat,
          form: 'dona',
          quantity: qty,
          unit_price: price
        };
        // Optional receipt details, sent only when typed (the server keeps
        // them on the lot; nothing is guessed when they are empty).
        const uppRaw = (tr.querySelector('.medpur-item-upp')?.value || '').trim();
        if (uppRaw !== '') {
          const upp = Number(uppRaw);
          if (!isFinite(upp) || upp <= 0) {
            rowError = `"${name}": qadoqdagi birlik soni 0 dan katta bo'lishi kerak.`;
          } else {
            item.units_per_package = upp;
          }
        }
        const batchNo = (tr.querySelector('.medpur-item-batch')?.value || '').trim();
        if (batchNo) item.batch_no = batchNo;
        const expiry = (tr.querySelector('.medpur-item-expiry')?.value || '').trim();
        if (expiry) item.expiry_date = expiry;
        items.push(item);
      }
    });

    if (rowError) {
      showToast(rowError, 'warning');
      return;
    }

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
      items: items,
      client_request_id: medPurRequestId || undefined
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
    const list = accountingData.medication_purchases || [];
    const p = list.find(x => x.id === purchaseId);
    const medName = p ? p.medication_name : 'Ushbu dori xaridi';

    // The server withdraws the WHOLE receipt this line was bought with (every line and the cash
    // expense), not just the drug named in the row. The rows of one receipt share its receipt id,
    // or at least its cash-desk transaction, so the dialog can say how many lines go.
    let siblings = p ? [p] : [];
    if (p) {
      const same = p.receipt_id
        ? list.filter(x => x.receipt_id === p.receipt_id)
        : (p.accounting_transaction_id ? list.filter(x => x.accounting_transaction_id === p.accounting_transaction_id) : [p]);
      if (same.length) siblings = same;
    }
    const lineCount = siblings.length || 1;
    const namesList = siblings.length > 1
      ? `<br><small>${siblings.map(x => esc(x.medication_name)).join(', ')}</small>`
      : '';

    const confirmed = await fmhConfirm({
      title: "Dori Xaridini Bekor Qilish",
      message: `<strong>${esc(medName)}</strong> xaridi bekor qilinsinmi?<br>Butun xarid (${lineCount} ta qator) va uning kassa yozuvi bekor qilinadi, ombor qoldig'i kamaytiriladi.${namesList}<br>Xaridning bir qismi allaqachon ishlatilgan bo'lsa, bekor qilib bo'lmaydi.`,
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
        const out = await res.json().catch(() => ({}));
        // Drop every removed line from the list at once (a failed refresh must not leave
        // ghost rows), then reload the real list from the server.
        const removed = Array.isArray(out.removed_purchase_ids) && out.removed_purchase_ids.length
          ? out.removed_purchase_ids : [purchaseId];
        accountingData.medication_purchases = (accountingData.medication_purchases || []).filter(x => removed.indexOf(x.id) < 0);
        await syncWithLedgerAndBackend(false);
        renderAll();
        showToast(removed.length > 1
          ? `✅ Dori xaridi bekor qilindi: ${removed.length} ta qator olib tashlandi`
          : "✅ Dori xaridi muvaffaqiyatli bekor qilindi", 'info');
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

    // Same figures as the server payroll the cards show; no commission.
    const rows = (accountingData.payroll_lines || []).map((d, index) => ({
      "№": index + 1,
      "Xodim ID": d.id,
      "Xodim F.I.Sh.": d.name,
      "Lavozimi": ROLE_LABELS[d.role] || d.role,
      "Asosiy Oylik Maosh (so'm)": d.base_salary,
      "Navbatchilik smenalari": d.duty_shifts,
      "Navbatchilik puli (so'm)": d.duty_pay,
      "Hisoblangan (brutto, so'm)": d.gross,
      "Daromad solig'i (so'm)": d.income_tax,
      "Pensiya (so'm)": d.pension,
      "Qo'lga beriladi (sof, so'm)": d.net,
      "To'lov Holati": payrollPaid(d.id) ? "To'langan" : "Hisoblangan"
    }));

    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Xodimlar Oyligi");

    const fileName = `FMH_Xodimlar_Oylik_Hisoboti_${getFormattedDate()}.xlsx`;
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
      "Ombordagi Qoldiq": `${fmtQty(item.stock)} ${item.unit}`,
      "Bemorga Narxi (so'm)": item.unit_price,
      "Jami (bemor narxida, so'm)": item.stock * item.unit_price,
      "Holat": item.status === 'low' ? "Kam qolgan" : "Yetarli"
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
    const docRows = (accountingData.payroll_lines || []).map((d, index) => ({
      "№": index + 1,
      "Xodim": d.name,
      "Lavozimi": ROLE_LABELS[d.role] || d.role,
      "Asosiy Maosh": d.base_salary,
      "Navbatchilik": d.duty_pay,
      "Brutto": d.gross,
      "Ushlab qolindi": d.deductions,
      "Qo'lga (sof)": d.net,
      "Holat": payrollPaid(d.id) ? "To'langan" : "Hisoblangan"
    }));
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(docRows), "Xodimlar Oyligi");

    // Sheet 4: Pharmacy
    const pharmRows = accountingData.pharmacy_stock.map((p, index) => ({
      "№": index + 1,
      "Dori Nomi": p.name,
      "Guruh": p.group,
      "Qoldiq": `${fmtQty(p.stock)} ${p.unit}`,
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
          Kassir: ______________<br>
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
    } else if (tabId === 'doctors') {
      // HR may have saved roster days or salaries since the page opened.
      loadPayroll().then(renderDoctorsPayroll);
    } else if (tabId === 'pharmacy') {
      renderMedicationPurchases();
      renderPharmacyInventory();
      loadMedicineUsage();
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
    applyListedPackageLabels();
    if (window.FMH_Pricing) window.FMH_Pricing.ready.then(applyListedPackageLabels);

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
    loadMedicineUsage,
    exportMedPurchasesToExcel,
    payoutDoctorSalary,
    openPatientInvoices,
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
