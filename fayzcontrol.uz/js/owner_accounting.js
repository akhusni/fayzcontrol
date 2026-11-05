/**
 * FAYZ MEDICAL HOUSE — OWNER PRIVATE ACCOUNTING & BOOKKEEPING (HISOBXONA)
 * Exclusively for the clinic owner and superadmin.
 * Real-time cashbook, timestamp tracking, expense destinations, income sources,
 * and comprehensive search/filters.
 */
(function () {
  'use strict';

  const STORE_PERIOD_KEY = 'fmh_owner_acc_period';
  const METHOD_LABELS = {
    cash: 'Naqd pul',
    card: 'Plastik karta',
    bank: "Bank o'tkazmasi",
    online: 'Click / Payme'
  };

  const DEFAULT_SUGGESTIONS = {
    expense: [
      "Bino ta'miri va qurilish mollari",
      "Klinika jihozlari va asboblar",
      "Xo'jalik mollari va kanselyariya",
      "Shaxsiy dividend (Egasiga)",
      "Bino ijarasi (Arenda)",
      "Kommunal to'lovlar va internet",
      "Avtomobil va yoqilg'i xarajatlari",
      "Reklama va marketing",
      "Qo'shimcha xarajat"
    ],
    income: [
      "Klinika daromadidan ulush",
      "Shaxsiy investitsiya / kiritma",
      "Investor mablag'i",
      "Ijara tushumi",
      "Boshqa tushum"
    ]
  };

  // State
  let period = 'month'; // 'today' | 'week' | 'month' | 'all' | 'custom'
  let filterType = 'all'; // 'all' | 'income' | 'expense'
  let filterMethod = 'all';
  let filterScope = 'all'; // 'all' | 'clinic' | 'private'
  let searchQuery = '';
  let customStart = '';
  let customEnd = '';
  let transactions = [];
  let summary = {};
  let editingTrxId = null;
  let activeModalType = 'expense'; // 'income' | 'expense'

  // Utility: HTML escape
  function esc(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Utility: Money formatting (e.g. 5 000 000 so'm)
  function formatMoney(n) {
    const v = Math.round(Number(n) || 0);
    const s = Math.abs(v).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '\u202f');
    return (v < 0 ? '\u2212' : '') + s + "\u00a0so'm";
  }

  // Utility: Pretty DateTime display (05.11.2026, 14:35:10)
  function formatDateTime(dtStr) {
    if (!dtStr) return '—';
    const clean = String(dtStr).replace('T', ' ').trim();
    const parts = clean.split(' ');
    const datePart = parts[0] || '';
    const timePart = parts[1] || '';
    const dSegments = datePart.split('-');
    if (dSegments.length === 3) {
      const prettyDate = `${dSegments[2]}.${dSegments[1]}.${dSegments[0]}`;
      return timePart ? `${prettyDate}, ${timePart.slice(0, 8)}` : prettyDate;
    }
    return clean;
  }

  // Utility: Get current local datetime for <input type="datetime-local">
  function getLocalIsoDateTime() {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    const d = String(now.getDate()).padStart(2, '0');
    const h = String(now.getHours()).padStart(2, '0');
    const min = String(now.getMinutes()).padStart(2, '0');
    return `${y}-${m}-${d}T${h}:${min}`;
  }

  // Compute date ranges based on period
  function getDateRange(p) {
    const now = new Date();
    const today = now.toISOString().slice(0, 10);
    if (p === 'today') {
      return { start: today, end: today };
    }
    if (p === 'week') {
      const d = new Date(now);
      d.setDate(d.getDate() - 6);
      return { start: d.toISOString().slice(0, 10), end: today };
    }
    if (p === 'month') {
      const start = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10);
      return { start, end: today };
    }
    if (p === 'custom') {
      return { start: customStart || today, end: customEnd || today };
    }
    return { start: '', end: '' }; // 'all'
  }

  // ---------------------------------------------------------------------------
  // Data Fetching
  // ---------------------------------------------------------------------------
  async function loadTransactions() {
    const tbody = document.getElementById('own-acc-tbody');
    const cardsWrap = document.getElementById('own-acc-cards-wrap');
    const refreshBtn = document.getElementById('btn-acc-refresh');

    if (refreshBtn) {
      const ic = refreshBtn.querySelector('i');
      if (ic) ic.classList.add('fa-spin');
    }

    const { start, end } = getDateRange(period);
    const params = new URLSearchParams();
    if (start) params.set('start', start);
    if (end) params.set('end', end);
    if (filterType !== 'all') params.set('type', filterType);
    if (filterMethod !== 'all') params.set('payment_method', filterMethod);
    if (filterScope !== 'all') params.set('clinic_scope', filterScope);
    if (searchQuery) params.set('search', searchQuery);
    params.set('limit', '300');

    try {
      const res = await fetch(`/api/owner/accounting/transactions?${params.toString()}`);
      if (refreshBtn) {
        const ic = refreshBtn.querySelector('i');
        if (ic) ic.classList.remove('fa-spin');
      }

      if (!res.ok) {
        if (res.status === 403) {
          showToast("Ruxsat berilmagan. Ushbu hisobxona faqat klinika egasi uchun.", "danger");
        } else {
          showToast("Ma'lumotlarni yuklab bo'lmadi.", "danger");
        }
        return;
      }

      const data = await res.json();
      transactions = data.transactions || [];
      summary = data.summary || {};
      renderKPIs();
      renderTable();
      updateSuggestions(data.categories || []);
    } catch (err) {
      if (refreshBtn) {
        const ic = refreshBtn.querySelector('i');
        if (ic) ic.classList.remove('fa-spin');
      }
      showToast("Server bilan aloqa uzildi. Internetni tekshiring.", "danger");
    }
  }

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------
  function renderKPIs() {
    const inEl = document.getElementById('own-acc-kpi-income');
    const inCnt = document.getElementById('own-acc-kpi-income-cnt');
    const outEl = document.getElementById('own-acc-kpi-expense');
    const outCnt = document.getElementById('own-acc-kpi-expense-cnt');
    const balEl = document.getElementById('own-acc-kpi-balance');
    const todayEl = document.getElementById('own-acc-kpi-today');

    const pIn = summary.period_income || 0;
    const pOut = summary.period_expense || 0;
    const pBal = summary.period_balance || 0;
    const allBal = summary.all_time_balance || 0;

    if (inEl) inEl.textContent = formatMoney(pIn);
    if (inCnt) inCnt.textContent = `${summary.income_count || 0} ta tushum`;
    if (outEl) outEl.textContent = formatMoney(pOut);
    if (outCnt) outCnt.textContent = `${summary.expense_count || 0} ta chiqim`;

    if (balEl) {
      balEl.textContent = formatMoney(allBal);
      balEl.classList.remove('text-positive', 'text-negative');
      balEl.classList.add(allBal >= 0 ? 'text-positive' : 'text-negative');
    }

    if (todayEl) {
      const tIn = summary.today_income || 0;
      const tOut = summary.today_expense || 0;
      todayEl.innerHTML = `<span>+${formatMoney(tIn)}</span> / <span class="c-out">−${formatMoney(tOut)}</span>`;
    }
  }

  function renderTable() {
    const tbody = document.getElementById('own-acc-tbody');
    const cardsWrap = document.getElementById('own-acc-cards-wrap');
    const emptyBox = document.getElementById('own-acc-empty');
    const countBadge = document.getElementById('own-acc-table-count');

    if (countBadge) countBadge.textContent = `${transactions.length} ta amaliyot`;

    if (!transactions.length) {
      if (tbody) tbody.innerHTML = '';
      if (cardsWrap) cardsWrap.innerHTML = '';
      if (emptyBox) emptyBox.hidden = false;
      return;
    }

    if (emptyBox) emptyBox.hidden = true;

    // Desktop table rows
    if (tbody) {
      tbody.innerHTML = transactions.map(t => {
        const isIn = t.transaction_type === 'income';
        const typeBadge = isIn
          ? '<span class="own-badge badge-income"><i class="fas fa-arrow-down-left"></i> Kirim</span>'
          : '<span class="own-badge badge-expense"><i class="fas fa-arrow-up-right"></i> Chiqim</span>';
        const isClinic = !!t.is_clinic_account;
        const clinicTag = isClinic
          ? '<span class="own-scope-pill scope-clinic" title="Klinika hisobidan (Umumiy buxgalteriyaga kiritilgan)"><i class="fas fa-building"></i> Klinika hisobidan</span>'
          : '<span class="own-scope-pill scope-private" title="Faqat egasiga (Shaxsiy hisobxona)"><i class="fas fa-user-shield"></i> Faqat egasiga</span>';
        const amtSign = isIn ? '+' : '−';
        const amtClass = isIn ? 'amt-income' : 'amt-expense';
        const methodLabel = METHOD_LABELS[t.payment_method] || t.payment_method || 'Naqd';

        return `
          <tr data-id="${esc(t.id)}">
            <td class="col-time">
              <div class="trx-time-main">${esc(formatDateTime(t.transaction_time))}</div>
              <small class="trx-id-sub">${esc(t.id)}</small>
            </td>
            <td class="col-type">
              ${typeBadge}
              <div class="trx-scope-wrap">${clinicTag}</div>
            </td>
            <td class="col-dest">
              <strong class="trx-dest-title">${esc(t.destination_or_source)}</strong>
              ${t.category && t.category !== t.destination_or_source ? `<span class="trx-cat-sub">${esc(t.category)}</span>` : ''}
            </td>
            <td class="col-reason">
              <div class="trx-reason-text" title="${esc(t.reason)}">${esc(t.reason)}</div>
              ${t.notes ? `<small class="trx-notes"><i class="fas fa-info-circle"></i> ${esc(t.notes)}</small>` : ''}
            </td>
            <td class="col-method">
              <span class="trx-method-tag"><i class="fas fa-credit-card"></i> ${esc(methodLabel)}</span>
            </td>
            <td class="col-amt ${amtClass}">
              <strong>${amtSign}&nbsp;${formatMoney(t.amount)}</strong>
            </td>
            <td class="col-actions">
              <div class="trx-row-actions">
                <button type="button" class="btn-action-icon btn-edit-trx" data-id="${esc(t.id)}" title="Tahrirlash">
                  <i class="fas fa-pen"></i>
                </button>
                <button type="button" class="btn-action-icon btn-del-trx" data-id="${esc(t.id)}" title="O'chirish">
                  <i class="fas fa-trash-alt"></i>
                </button>
              </div>
            </td>
          </tr>
        `;
      }).join('');
    }

    // Mobile cards feed
    if (cardsWrap) {
      cardsWrap.innerHTML = transactions.map(t => {
        const isIn = t.transaction_type === 'income';
        const amtSign = isIn ? '+' : '−';
        const amtClass = isIn ? 'amt-income' : 'amt-expense';
        const methodLabel = METHOD_LABELS[t.payment_method] || t.payment_method || 'Naqd';

        return `
          <div class="own-mob-card ${isIn ? 'mob-in' : 'mob-out'}" data-id="${esc(t.id)}">
            <div class="mob-card-head">
              <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                <span class="own-badge ${isIn ? 'badge-income' : 'badge-expense'}">
                  <i class="fas ${isIn ? 'fa-arrow-down-left' : 'fa-arrow-up-right'}"></i> ${isIn ? 'Kirim' : 'Chiqim'}
                </span>
                ${clinicTag}
              </div>
              <span class="mob-card-time"><i class="fas fa-clock"></i> ${esc(formatDateTime(t.transaction_time))}</span>
            </div>
            <div class="mob-card-body">
              <div class="mob-card-dest">
                <span class="mob-label">${isIn ? 'Qayerdan / Qayerga' : 'Qayerga'}:</span>
                <strong>${esc(t.destination_or_source)}</strong>
              </div>
              <div class="mob-card-reason">
                <span class="mob-label">Nega bo'lgani:</span>
                <p>${esc(t.reason)}</p>
              </div>
              ${t.notes ? `<div class="mob-card-notes"><small><i class="fas fa-info-circle"></i> ${esc(t.notes)}</small></div>` : ''}
            </div>
            <div class="mob-card-foot">
              <div class="mob-card-amt ${amtClass}">
                ${amtSign}&nbsp;${formatMoney(t.amount)}
                <small class="mob-method">(${esc(methodLabel)})</small>
              </div>
              <div class="mob-card-btns">
                <button type="button" class="btn-action-icon btn-edit-trx" data-id="${esc(t.id)}" title="Tahrirlash">
                  <i class="fas fa-pen"></i>
                </button>
                <button type="button" class="btn-action-icon btn-del-trx" data-id="${esc(t.id)}" title="O'chirish">
                  <i class="fas fa-trash-alt"></i>
                </button>
              </div>
            </div>
          </div>
        `;
      }).join('');
    }

    attachRowEvents();
  }

  function attachRowEvents() {
    document.querySelectorAll('.btn-edit-trx').forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const id = btn.dataset.id;
        openEditModal(id);
      };
    });

    document.querySelectorAll('.btn-del-trx').forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const id = btn.dataset.id;
        openDeleteModal(id);
      };
    });
  }

  function updateSuggestions(categories) {
    const listEl = document.getElementById('owner-dest-suggestions');
    if (!listEl) return;
    const defaults = DEFAULT_SUGGESTIONS[activeModalType] || [];
    const combined = Array.from(new Set([...defaults, ...(categories || [])]));
    listEl.innerHTML = combined.map(c => `<option value="${esc(c)}"></option>`).join('');
  }

  // ---------------------------------------------------------------------------
  // Modal Management
  // ---------------------------------------------------------------------------
  function openAddModal(type) {
    editingTrxId = null;
    activeModalType = type || 'expense';

    const modal = document.getElementById('modal-owner-transaction');
    const titleEl = document.getElementById('own-modal-title');
    const form = document.getElementById('form-owner-transaction');
    if (form) form.reset();

    if (titleEl) {
      titleEl.innerHTML = activeModalType === 'income'
        ? '<i class="fas fa-plus-circle c-in"></i> Yangi Kirim Kiritish'
        : '<i class="fas fa-minus-circle c-out"></i> Yangi Chiqim Kiritish';
    }

    setModalType(activeModalType);

    // Default timestamp to current local time
    const timeInp = document.getElementById('trx-time');
    if (timeInp) timeInp.value = getLocalIsoDateTime();

    const clinicChk = document.getElementById('trx-clinic-account');
    if (clinicChk) clinicChk.checked = false;

    if (modal) {
      modal.hidden = false;
      modal.classList.add('modal-open');
    }

    const amtInp = document.getElementById('trx-amount');
    if (amtInp) amtInp.focus();
  }

  function openEditModal(trxId) {
    const trx = transactions.find(t => t.id === trxId);
    if (!trx) return;

    editingTrxId = trxId;
    activeModalType = trx.transaction_type;

    const modal = document.getElementById('modal-owner-transaction');
    const titleEl = document.getElementById('own-modal-title');

    if (titleEl) {
      titleEl.innerHTML = `<i class="fas fa-pen"></i> Amaliyotni Tahrirlash (${esc(trx.id)})`;
    }

    setModalType(activeModalType);

    // Populate inputs
    const amtInp = document.getElementById('trx-amount');
    const destInp = document.getElementById('trx-destination');
    const reasonInp = document.getElementById('trx-reason');
    const methodInp = document.getElementById('trx-method');
    const timeInp = document.getElementById('trx-time');
    const notesInp = document.getElementById('trx-notes');

    if (amtInp) amtInp.value = Math.round(trx.amount).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    if (destInp) destInp.value = trx.destination_or_source || '';
    if (reasonInp) reasonInp.value = trx.reason || '';
    if (methodInp) methodInp.value = trx.payment_method || 'cash';
    if (notesInp) notesInp.value = trx.notes || '';

    const clinicChk = document.getElementById('trx-clinic-account');
    if (clinicChk) clinicChk.checked = !!trx.is_clinic_account;

    if (timeInp && trx.transaction_time) {
      const clean = trx.transaction_time.replace(' ', 'T').slice(0, 16);
      timeInp.value = clean;
    }

    if (modal) {
      modal.hidden = false;
      modal.classList.add('modal-open');
    }
  }

  function setModalType(type) {
    activeModalType = type;
    const btnIn = document.getElementById('btn-type-income');
    const btnOut = document.getElementById('btn-type-expense');
    const destLabel = document.getElementById('lbl-destination');
    const destInp = document.getElementById('trx-destination');
    const reasonLabel = document.getElementById('lbl-reason');

    if (btnIn) {
      btnIn.classList.toggle('active', type === 'income');
      btnIn.setAttribute('aria-pressed', type === 'income' ? 'true' : 'false');
    }
    if (btnOut) {
      btnOut.classList.toggle('active', type === 'expense');
      btnOut.setAttribute('aria-pressed', type === 'expense' ? 'true' : 'false');
    }

    if (type === 'income') {
      if (destLabel) destLabel.innerHTML = 'Qayerdan / Qayerga keldi? <span class="req">*</span>';
      if (destInp) destInp.placeholder = "Masalan: Klinika ulushi, Shaxsiy kiritma, Investor to'lovi...";
      if (reasonLabel) reasonLabel.innerHTML = 'Nega kiritildi? (Daromad sababi / izoh) <span class="req">*</span>';
    } else {
      if (destLabel) destLabel.innerHTML = 'Qayerga sarflandi? (Manzil / Maqsad) <span class="req">*</span>';
      if (destInp) destInp.placeholder = "Masalan: Bino ta'miri, Klinika jihozlari, Kanselyariya, Shaxsiy dividend...";
      if (reasonLabel) reasonLabel.innerHTML = 'Nega bo\'lgani? (Xarajat sababi / batafsil izoh) <span class="req">*</span>';
    }

    updateSuggestions();
  }

  function closeModal() {
    const modal = document.getElementById('modal-owner-transaction');
    if (modal) {
      modal.hidden = true;
      modal.classList.remove('modal-open');
    }
    editingTrxId = null;
  }

  function openDeleteModal(trxId) {
    const trx = transactions.find(t => t.id === trxId);
    if (!trx) return;

    const modal = document.getElementById('modal-owner-del-confirm');
    const descEl = document.getElementById('del-confirm-desc');
    const confirmBtn = document.getElementById('btn-confirm-delete');

    if (descEl) {
      descEl.innerHTML = `
        <strong>${esc(trx.id)}</strong> raqamli amaliyot:<br>
        <strong>${esc(trx.destination_or_source)}</strong> — <em>${esc(formatMoney(trx.amount))}</em> (${esc(formatDateTime(trx.transaction_time))})<br>
        <small class="del-reason-sub">Sababi: ${esc(trx.reason)}</small>
      `;
    }

    if (confirmBtn) {
      confirmBtn.onclick = async () => {
        confirmBtn.disabled = true;
        try {
          const res = await fetch(`/api/owner/accounting/transactions/${encodeURIComponent(trxId)}`, {
            method: 'DELETE'
          });
          confirmBtn.disabled = false;
          if (res.ok) {
            closeDeleteModal();
            showToast("Amaliyot muvaffaqiyatli o'chirildi.", "success");
            loadTransactions();
          } else {
            const body = await res.json().catch(() => ({}));
            showToast(body.error || "O'chirib bo'lmadi.", "danger");
          }
        } catch (e) {
          confirmBtn.disabled = false;
          showToast("Server bilan aloqa uzildi.", "danger");
        }
      };
    }

    if (modal) {
      modal.hidden = false;
      modal.classList.add('modal-open');
    }
  }

  function closeDeleteModal() {
    const modal = document.getElementById('modal-owner-del-confirm');
    if (modal) {
      modal.hidden = true;
      modal.classList.remove('modal-open');
    }
  }

  // ---------------------------------------------------------------------------
  // Save Transaction (Create / Update)
  // ---------------------------------------------------------------------------
  async function saveTransaction(e) {
    e.preventDefault();
    const saveBtn = document.getElementById('btn-modal-save');
    const amtInp = document.getElementById('trx-amount');
    const destInp = document.getElementById('trx-destination');
    const reasonInp = document.getElementById('trx-reason');
    const methodInp = document.getElementById('trx-method');
    const timeInp = document.getElementById('trx-time');
    const notesInp = document.getElementById('trx-notes');

    const rawAmt = amtInp ? amtInp.value.replace(/\s+/g, '').replace(',', '.') : '';
    const amount = parseFloat(rawAmt);
    if (!amount || amount <= 0) {
      showToast("Iltimos, to'g'ri summani kiriting.", "warning");
      if (amtInp) amtInp.focus();
      return;
    }

    const destination = destInp ? destInp.value.trim() : '';
    if (!destination) {
      showToast(activeModalType === 'expense' ? "Qayerga sarflanganini kiriting." : "Qayerdan/Qayerga kelganini kiriting.", "warning");
      if (destInp) destInp.focus();
      return;
    }

    const reason = reasonInp ? reasonInp.value.trim() : '';
    if (!reason) {
      showToast("Amaliyot nega bo'lgani (sababi / izohi)ni kiriting.", "warning");
      if (reasonInp) reasonInp.focus();
      return;
    }

    const clinicChk = document.getElementById('trx-clinic-account');
    const isClinicAccount = clinicChk ? clinicChk.checked : false;

    const payload = {
      transaction_type: activeModalType,
      amount: amount,
      destination_or_source: destination,
      reason: reason,
      payment_method: methodInp ? methodInp.value : 'cash',
      transaction_time: timeInp ? timeInp.value : '',
      notes: notesInp ? notesInp.value.trim() : '',
      is_clinic_account: isClinicAccount
    };

    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saqlanmoqda...';
    }

    try {
      const url = editingTrxId
        ? `/api/owner/accounting/transactions/${encodeURIComponent(editingTrxId)}`
        : '/api/owner/accounting/transactions';
      const method = editingTrxId ? 'PUT' : 'POST';

      const res = await fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i class="fas fa-check"></i> Saqlash';
      }

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        showToast(body.error || "Amaliyotni saqlab bo'lmadi.", "danger");
        return;
      }

      closeModal();
      showToast(editingTrxId ? "Amaliyot tahrirlandi." : "Yangi amaliyot kiritildi.", "success");
      loadTransactions();
    } catch (err) {
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i class="fas fa-check"></i> Saqlash';
      }
      showToast("Tarmoq xatosi. Qaytadan urinib ko'ring.", "danger");
    }
  }

  // ---------------------------------------------------------------------------
  // Export CSV & Print
  // ---------------------------------------------------------------------------
  function exportCSV() {
    if (!transactions.length) {
      showToast("Eksport qilish uchun ma'lumot yo'q.", "warning");
      return;
    }

    const headers = ['ID', 'Vaqt (Timestamp)', 'Turi', 'Manba', 'Qayerga / Qayerdan', 'Nega bo\'lgani (Sababi)', 'To\'lov shakli', 'Summa (so\'m)', 'Izoh'];
    const rows = transactions.map(t => [
      `"${t.id}"`,
      `"${formatDateTime(t.transaction_time)}"`,
      `"${t.transaction_type === 'income' ? 'Kirim' : 'Chiqim'}"`,
      `"${t.is_clinic_account ? "Klinika hisobidan" : "Faqat egasiga"}"`,
      `"${(t.destination_or_source || '').replace(/"/g, '""')}"`,
      `"${(t.reason || '').replace(/"/g, '""')}"`,
      `"${METHOD_LABELS[t.payment_method] || t.payment_method || ''}"`,
      `"${t.amount}"`,
      `"${(t.notes || '').replace(/"/g, '""')}"`
    ]);

    const csvContent = '\uFEFF' + [headers.join(','), ...rows.map(r => r.join(','))].join('\r\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `Owner_Hisobxona_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast("Excel (CSV) fayl yuklab olindi.", "success");
  }

  // Toast notification helper
  function showToast(msg, type) {
    if (window.FMH_Toast) {
      window.FMH_Toast(msg, type);
    } else {
      alert(msg);
    }
  }

  // ---------------------------------------------------------------------------
  // Master Tabs Switching: Egasi Hisobxonasi vs Klinika Pul Oqimi & Tahlil
  // ---------------------------------------------------------------------------
  function initTabs() {
    const tabBtns = document.querySelectorAll('.own-nav-tab');
    const panes = document.querySelectorAll('.own-tab-pane');

    tabBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        const targetId = btn.dataset.target;
        tabBtns.forEach(b => {
          b.classList.toggle('active', b === btn);
          b.setAttribute('aria-selected', b === btn ? 'true' : 'false');
        });
        panes.forEach(p => {
          const isTarget = p.id === targetId;
          p.hidden = !isTarget;
          p.classList.toggle('active', isTarget);
        });

        // Trigger chart resize if switching to analytics
        if (targetId === 'pane-analytics' && window.dispatchEvent) {
          window.dispatchEvent(new Event('resize'));
        }
      });
    });
  }

  // ---------------------------------------------------------------------------
  // Initialization & Event Listeners
  // ---------------------------------------------------------------------------
  function init() {
    initTabs();

    // Amount input live spacer
    const amtInp = document.getElementById('trx-amount');
    if (amtInp) {
      amtInp.addEventListener('input', (e) => {
        const raw = e.target.value.replace(/\D/g, '');
        if (raw) {
          e.target.value = raw.replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
        }
      });
    }

    // Modal type switcher buttons
    const btnTypeIn = document.getElementById('btn-type-income');
    const btnTypeOut = document.getElementById('btn-type-expense');
    if (btnTypeIn) btnTypeIn.addEventListener('click', () => setModalType('income'));
    if (btnTypeOut) btnTypeOut.addEventListener('click', () => setModalType('expense'));

    // Open Add modals
    const btnAddIn = document.getElementById('btn-add-income');
    const btnAddOut = document.getElementById('btn-add-expense');
    const btnEmptyAddIn = document.getElementById('btn-empty-add-in');
    const btnEmptyAddOut = document.getElementById('btn-empty-add-out');

    if (btnAddIn) btnAddIn.addEventListener('click', () => openAddModal('income'));
    if (btnAddOut) btnAddOut.addEventListener('click', () => openAddModal('expense'));
    if (btnEmptyAddIn) btnEmptyAddIn.addEventListener('click', () => openAddModal('income'));
    if (btnEmptyAddOut) btnEmptyAddOut.addEventListener('click', () => openAddModal('expense'));

    // iPhone / Mobile bottom floating action buttons
    const mobFabIn = document.getElementById('mob-fab-income');
    const mobFabOut = document.getElementById('mob-fab-expense');
    if (mobFabIn) mobFabIn.addEventListener('click', () => openAddModal('income'));
    if (mobFabOut) mobFabOut.addEventListener('click', () => openAddModal('expense'));

    // Form submit
    const form = document.getElementById('form-owner-transaction');
    if (form) form.addEventListener('submit', saveTransaction);

    // Modal cancels / close
    const btnModalCancel = document.getElementById('btn-modal-cancel');
    const btnModalCloseX = document.getElementById('btn-modal-close-x');
    if (btnModalCancel) btnModalCancel.addEventListener('click', closeModal);
    if (btnModalCloseX) btnModalCloseX.addEventListener('click', closeModal);

    const btnDelCancel = document.getElementById('btn-del-cancel');
    const btnDelCloseX = document.getElementById('btn-del-close-x');
    if (btnDelCancel) btnDelCancel.addEventListener('click', closeDeleteModal);
    if (btnDelCloseX) btnDelCloseX.addEventListener('click', closeDeleteModal);

    // Close modal on backdrop click
    document.querySelectorAll('.own-modal-backdrop').forEach(bd => {
      bd.addEventListener('click', (e) => {
        if (e.target === bd) {
          closeModal();
          closeDeleteModal();
        }
      });
    });

    // Periods
    document.querySelectorAll('.own-acc-period').forEach(b => {
      b.addEventListener('click', () => {
        document.querySelectorAll('.own-acc-period').forEach(x => x.classList.remove('active'));
        b.classList.add('active');
        period = b.dataset.period;
        const customBox = document.getElementById('own-acc-custom');
        if (customBox) customBox.hidden = period !== 'custom';
        if (period !== 'custom') {
          loadTransactions();
        }
      });
    });

    // Custom date range apply
    const btnCustomApply = document.getElementById('btn-acc-apply-custom');
    if (btnCustomApply) {
      btnCustomApply.addEventListener('click', () => {
        const s = document.getElementById('own-acc-start');
        const e = document.getElementById('own-acc-end');
        customStart = s ? s.value : '';
        customEnd = e ? e.value : '';
        if (!customStart || !customEnd) {
          showToast("Dan va Gacha sanalarni to'liq tanlang.", "warning");
          return;
        }
        loadTransactions();
      });
    }

    // Filter by type
    const filterTypeSel = document.getElementById('own-acc-filter-type');
    if (filterTypeSel) {
      filterTypeSel.addEventListener('change', (e) => {
        filterType = e.target.value;
        loadTransactions();
      });
    }

    // Filter by payment method
    const filterMethodSel = document.getElementById('own-acc-filter-method');
    if (filterMethodSel) {
      filterMethodSel.addEventListener('change', (e) => {
        filterMethod = e.target.value;
        loadTransactions();
      });
    }

    // Filter by scope (clinic account vs private)
    const filterScopeSel = document.getElementById('own-acc-filter-scope');
    if (filterScopeSel) {
      filterScopeSel.addEventListener('change', (e) => {
        filterScope = e.target.value;
        loadTransactions();
      });
    }

    // Search query with debounce
    const searchInp = document.getElementById('own-acc-search');
    let searchTimer = null;
    if (searchInp) {
      searchInp.addEventListener('input', (e) => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
          searchQuery = e.target.value.trim();
          loadTransactions();
        }, 300);
      });
    }

    // Refresh & Export & Print
    const refreshBtn = document.getElementById('btn-acc-refresh');
    if (refreshBtn) refreshBtn.addEventListener('click', loadTransactions);

    const exportBtn = document.getElementById('btn-acc-export');
    if (exportBtn) exportBtn.addEventListener('click', exportCSV);

    const printBtn = document.getElementById('btn-acc-print');
    if (printBtn) {
      printBtn.addEventListener('click', () => {
        window.print();
      });
    }

    // Initial load
    loadTransactions();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
