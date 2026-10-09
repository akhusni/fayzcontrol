/**
 * Fayz Medical House — Ombor (medical warehouse) page.
 *
 * Talks only to /api/warehouse/* (warehouse_api.py) and /api/auth/session.
 * The server decides everything that matters (permissions, stock rules, costs);
 * this page only chooses what to show and hides controls a role cannot use.
 *
 * Money and quantities: the server sends JSON numbers, so the page never adds
 * money up from them. The receipt form does its own arithmetic on the typed
 * text with BigInt, so a line total is exactly what the server will compute
 * (no 0.1 + 0.2 surprises on a UZS invoice).
 *
 * Rules kept throughout: every server string that reaches innerHTML goes
 * through esc(); no inline handlers (buttons carry data-action / data-id and
 * one delegated listener reads them); fmhConfirm before every stock change;
 * one client_request_id per form, reused on retry, so a double click or a
 * re-send can never move stock twice.
 */
(function () {
  'use strict';

  const API = '/api/warehouse';
  const PHARMA_TYPES = ['medicine', 'vitamin', 'injection'];

  // ---------------------------------------------------------------------------
  // Uzbek labels for codes the server returns
  // ---------------------------------------------------------------------------
  const STATUS_LABEL = { ok: 'Yetarli', low: 'Kam', out: 'Tugagan', expired: "Muddati o'tgan", expiring: 'Muddati yaqin' };
  const ALERT_LABEL = { out_of_stock: 'Tugagan', low_stock: 'Kam qoldiq', expired: "Muddati o'tgan", expiring_soon: 'Muddati yaqin' };
  const TXN_LABEL = {
    receipt: 'Kirim', dispense: 'Berildi', adjustment_in: 'Tuzatish (+)', adjustment_out: 'Tuzatish (−)',
    supplier_return: 'Yetkazib beruvchiga qaytarildi', patient_return: 'Bemordan qaytdi',
    writeoff: 'Hisobdan chiqarildi', reversal: 'Teskari yozuv', opening: "Boshlang'ich qoldiq"
  };
  const RECEIPT_STATUS = { draft: 'Qoralama', posted: 'Tasdiqlangan', reversed: 'Qaytarilgan', cancelled: 'Bekor qilingan' };
  const DISP_STATUS = { completed: 'Berilgan', reversed: 'Qaytarilgan' };
  const PAYMENT_LABEL = {
    cash: 'Naqd pul', cash_register: 'Kassa', terminal: 'Terminal', card_transfer: "Kartaga o'tkazma",
    payme_click: 'Payme / Click', bank_wire: "Bank o'tkazmasi"
  };
  const SOURCE_LABEL = { manual: "Qo'lda", nurse_round: 'Hamshira', billing: 'Hisob-kitob', receipt: 'Kirim', adjustment: 'Tuzatish' };
  const ADJ_KINDS = [
    { id: 'increase', label: 'Qoldiqni oshirish (topilgan mahsulot)' },
    { id: 'decrease', label: 'Qoldiqni kamaytirish (kam chiqdi)' },
    { id: 'writeoff', label: "Hisobdan chiqarish (yaroqsiz, singan, muddati o'tgan)" },
    { id: 'supplier_return', label: 'Yetkazib beruvchiga qaytarish' },
    { id: 'patient_return', label: 'Bemordan qaytgan mahsulot' }
  ];
  const REVERSIBLE_TXN = ['adjustment_in', 'adjustment_out', 'supplier_return', 'patient_return', 'writeoff'];
  const REPORTS = [
    { id: 'stock', label: 'Joriy qoldiq' },
    { id: 'low-stock', label: 'Kam qoldiq' },
    { id: 'out-of-stock', label: 'Tugagan mahsulotlar' },
    { id: 'expiry', label: 'Yaroqlilik muddati' },
    { id: 'valuation', label: 'Ombor qiymati', cost: true },
    { id: 'valuation-by-category', label: "Qiymat (kategoriya bo'yicha)", cost: true },
    { id: 'receipts', label: 'Kirimlar', dates: true },
    { id: 'dispensings', label: 'Berilgan dori va materiallar', dates: true },
    { id: 'adjustments', label: 'Tuzatishlar va hisobdan chiqarish', dates: true },
    { id: 'movement', label: 'Mahsulot harakati', dates: true, item: true },
    { id: 'reconciliation', label: 'Hisoblarni solishtirish' }
  ];
  // Cell values the server returns as codes, by column key.
  const CODE_COLUMNS = {
    stock_status: STATUS_LABEL, txn_type: TXN_LABEL, status: Object.assign({}, RECEIPT_STATUS, DISP_STATUS),
    state: { expired: "Muddati o'tgan", expiring: 'Muddati yaqin' }, source: SOURCE_LABEL
  };

  // ---------------------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------------------
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  const ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ESC_MAP[c]);
  }

  function pad2(n) { return n < 10 ? '0' + n : String(n); }
  function todayISO() {
    const d = new Date();
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
  }

  function newRequestId() {
    try {
      if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
    } catch (e) { /* fall through */ }
    let s = '';
    try {
      const a = new Uint8Array(16);
      window.crypto.getRandomValues(a);
      s = Array.from(a, (b) => (b < 16 ? '0' : '') + b.toString(16)).join('');
    } catch (e) {
      s = Math.random().toString(16).slice(2) + Math.random().toString(16).slice(2);
    }
    return 'w-' + Date.now().toString(36) + '-' + s.slice(0, 24);
  }

  function debounce(fn, ms) {
    let t = null;
    return function () {
      const args = arguments;
      clearTimeout(t);
      t = setTimeout(() => fn.apply(null, args), ms);
    };
  }

  // The fmt* functions return text that is safe to put into innerHTML.
  const NF_QTY = new Intl.NumberFormat('uz-UZ', { maximumFractionDigits: 3 });
  const NF_MONEY = new Intl.NumberFormat('uz-UZ', { maximumFractionDigits: 2 });
  const NF_COST = new Intl.NumberFormat('uz-UZ', { maximumFractionDigits: 4 });

  function fmtQty(v) {
    if (v === null || v === undefined || v === '') return '—';
    const n = Number(v);
    return isFinite(n) ? NF_QTY.format(n) : esc(v);
  }
  function fmtMoney(v, fine) {
    if (v === null || v === undefined || v === '') return '—';
    const n = Number(v);
    return isFinite(n) ? (fine ? NF_COST : NF_MONEY).format(n) + " so'm" : esc(v);
  }
  function fmtDate(v) {
    if (!v) return '—';
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(v));
    return m ? m[3] + '.' + m[2] + '.' + m[1] : esc(v);
  }
  function fmtDateTime(v) {
    if (!v) return '—';
    const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(String(v));
    return m ? m[3] + '.' + m[2] + '.' + m[1] + ' ' + m[4] + ':' + m[5] : fmtDate(v);
  }
  function plural(v, unit) {
    return fmtQty(v) + (unit ? ' ' + esc(unit) : '');
  }

  function badge(kind, label) {
    return '<span class="wh-badge b-' + esc(kind) + '">' + esc(label) + '</span>';
  }
  function statusBadge(status) {
    return badge(status, STATUS_LABEL[status] || status);
  }

  function qs(params) {
    const parts = [];
    Object.keys(params).forEach((k) => {
      const v = params[k];
      if (v === null || v === undefined || v === '') return;
      parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(v));
    });
    return parts.length ? '?' + parts.join('&') : '';
  }

  function toast(message, type) {
    if (typeof window.FMH_Toast === 'function') window.FMH_Toast(esc(message), type || 'success');
  }

  // ---------------------------------------------------------------------------
  // Exact decimal arithmetic for the receipt form (BigInt, 6 decimal places)
  // ---------------------------------------------------------------------------
  const HAS_BIGINT = typeof BigInt === 'function';
  const SCALE_PLACES = 6;
  const ZERO = HAS_BIGINT ? BigInt(0) : 0;
  const ONE = HAS_BIGINT ? BigInt(1) : 1;
  const TWO = HAS_BIGINT ? BigInt(2) : 2;
  const SCALE = HAS_BIGINT ? BigInt('1000000') : 1000000;

  /** "1 500,25" / "1500.25" -> BigInt scaled by 1e6, or null when blank/invalid/too many decimals. */
  function parseDec(value, maxPlaces) {
    if (!HAS_BIGINT) return null;
    const s = String(value == null ? '' : value).replace(/[\s ]/g, '').replace(',', '.');
    if (!/^\d+(\.\d+)?$/.test(s)) return null;
    const parts = s.split('.');
    let frac = parts[1] || '';
    if (frac.length > maxPlaces) {
      if (/[1-9]/.test(frac.slice(maxPlaces))) return null;
      frac = frac.slice(0, maxPlaces);
    }
    frac = (frac + '000000').slice(0, SCALE_PLACES);
    return BigInt(parts[0] + frac);
  }
  /** round-half-up of n / d for non-negative BigInts. */
  function roundDiv(n, d) {
    return (n * TWO + d) / (TWO * d);
  }
  /** BigInt count of 10^-places units -> "12 345,6" (trailing zeros trimmed down to minPlaces). */
  function fmtScaled(n, places, minPlaces) {
    if (!HAS_BIGINT || n === null || n === undefined) return '—';
    let s = String(n < ZERO ? -n : n);
    while (s.length <= places) s = '0' + s;
    let int = places ? s.slice(0, s.length - places) : s;
    let frac = places ? s.slice(s.length - places) : '';
    while (frac.length > (minPlaces || 0) && frac.charAt(frac.length - 1) === '0') frac = frac.slice(0, -1);
    int = int.replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    return (n < ZERO ? '−' : '') + int + (frac ? ',' + frac : '');
  }
  /** What the server accepts as a number: dots, no spaces. */
  function canonicalNumber(value) {
    return String(value == null ? '' : value).replace(/[\s ]/g, '').replace(',', '.');
  }

  // ---------------------------------------------------------------------------
  // Server calls
  // ---------------------------------------------------------------------------
  async function api(method, path, body) {
    const opts = { method: method, credentials: 'same-origin', headers: {} };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(API + path, opts);
    } catch (e) {
      return { ok: false, status: 0, data: { error: "Server bilan aloqa yo'q. Internetni tekshirib, qayta urinib ko'ring." } };
    }
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) {
      if (!data || typeof data !== 'object') data = {};
      if (res.status === 403) data.error = "Bu amal uchun sizda ruxsat yo'q.";
      else if (!data.error) data.error = res.status === 404 ? 'Topilmadi.' : "Server xatosi. Birozdan keyin qayta urinib ko'ring.";
    }
    return { ok: res.ok, status: res.status, data: data };
  }

  // ---------------------------------------------------------------------------
  // Session, permissions, shared state
  // ---------------------------------------------------------------------------
  const S = {
    session: null,
    perms: [],
    whRead: false, whWrite: false, accWrite: false,
    costs: false,            // does the server show us cost fields? (decided by the first response)
    settings: { default_min_stock: 10, expiry_warning_days: 30, units: [], item_types: [] },
    suppliers: null,
    categories: [],
    tab: 'dashboard',
    loaded: {},              // tab -> true once loaded
    stale: {},               // tab -> true when data changed elsewhere
    patientsPromise: null,
    patients: []
  };

  function can(module, action) {
    const perms = S.perms || [];
    if (perms.indexOf('*') >= 0) return true;
    for (let i = 0; i < perms.length; i++) {
      const parts = String(perms[i]).split(':');
      if (parts[0] !== module) continue;
      const scope = parts[1];
      if (!scope) return true;
      if (scope === action) return true;
      if (scope === 'write' && action === 'read') return true;
    }
    return false;
  }

  function invalidate() {
    ['dashboard', 'inventory', 'receipts', 'dispensing', 'ledger', 'reports'].forEach((t) => { S.stale[t] = true; });
  }

  function typeLabel(id) {
    const t = (S.settings.item_types || []).find((x) => x.id === id);
    return t ? t.label : id;
  }

  async function loadSuppliers(force) {
    if (S.suppliers && !force) return S.suppliers;
    const r = await api('GET', '/suppliers');
    S.suppliers = r.ok ? (r.data.suppliers || []) : (S.suppliers || []);
    return S.suppliers;
  }

  function supplierOptions(selected, firstLabel) {
    const list = S.suppliers || [];
    return '<option value="">' + esc(firstLabel || 'Barchasi') + '</option>' + list.map((s) =>
      '<option value="' + esc(s.id) + '"' + (String(selected) === String(s.id) ? ' selected' : '') + '>' + esc(s.name) + '</option>').join('');
  }

  // The patient list comes from the CRM endpoint (there is no search endpoint);
  // it is loaded once, on first use, and filtered here.
  function loadPatients() {
    if (!S.patientsPromise) {
      S.patientsPromise = fetch('/api/patients', { credentials: 'same-origin' })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error('http ' + r.status))))
        .then((list) => {
          S.patients = Array.isArray(list) ? list.map((p) => ({
            id: p.id, code: p.patient_code, name: p.full_name, phone: p.phone,
            admission_id: p.active_admission ? p.active_admission.admission_id : null
          })) : [];
          return S.patients;
        })
        .catch((e) => { S.patientsPromise = null; throw e; });
    }
    return S.patientsPromise;
  }

  // ---------------------------------------------------------------------------
  // UI primitives: layers (modal / drawer), confirmation, reason prompt, combo
  // ---------------------------------------------------------------------------
  const layers = [];
  let layerSeq = 0;

  function confirmDialogOpen() { return !!document.getElementById('fmh-confirm-dialog-backdrop'); }

  function openLayer(opts) {
    const o = Object.assign({
      title: '', subtitle: '', html: '', footer: '', drawer: false, wide: false, narrow: false,
      dismissOnBg: true, onClose: null
    }, opts || {});
    const launcher = document.activeElement;
    const uid = 'whl' + (++layerSeq);
    const el = document.createElement('div');
    el.className = 'wh-layer' + (o.drawer ? ' is-drawer' : '');
    el.innerHTML =
      '<div class="wh-layer-bg" data-layer-bg></div>' +
      '<section class="wh-modal' + (o.drawer ? ' wh-drawer' : '') + (o.wide ? ' wh-modal-wide' : '') + (o.narrow ? ' wh-modal-narrow' : '') +
      '" role="dialog" aria-modal="true" aria-labelledby="' + uid + '-t">' +
        '<header class="wh-modal-head"><div style="min-width:0">' +
          '<h2 class="wh-modal-title" id="' + uid + '-t"></h2><p class="wh-modal-sub" hidden></p></div>' +
          '<button type="button" class="wh-icon-btn" data-layer-close aria-label="Yopish"><i class="fas fa-xmark" aria-hidden="true"></i></button>' +
        '</header>' +
        '<div class="wh-modal-body"></div>' +
        '<footer class="wh-modal-foot" hidden></footer>' +
      '</section>';
    document.body.appendChild(el);
    document.body.classList.add('wh-noscroll');

    const layer = {
      el: el,
      box: el.querySelector('.wh-modal'),
      body: el.querySelector('.wh-modal-body'),
      foot: el.querySelector('.wh-modal-foot'),
      closed: false,
      setTitle: function (title, sub) {
        el.querySelector('.wh-modal-title').textContent = title || '';
        const p = el.querySelector('.wh-modal-sub');
        p.textContent = sub || '';
        p.hidden = !sub;
      },
      setBody: function (html) { layer.body.innerHTML = html; },
      setFoot: function (html) { layer.foot.innerHTML = html || ''; layer.foot.hidden = !html; },
      close: function () {
        if (layer.closed) return;
        layer.closed = true;
        const i = layers.indexOf(layer);
        if (i >= 0) layers.splice(i, 1);
        el.remove();
        if (!layers.length) document.body.classList.remove('wh-noscroll');
        if (launcher && document.body.contains(launcher) && typeof launcher.focus === 'function') {
          try { launcher.focus(); } catch (e) { /* ignore */ }
        }
        if (typeof o.onClose === 'function') o.onClose();
      }
    };
    layer.setTitle(o.title, o.subtitle);
    layer.setBody(o.html);
    layer.setFoot(o.footer);
    layers.push(layer);

    el.addEventListener('click', (e) => {
      if (e.target.closest('[data-layer-close]')) { layer.close(); return; }
      if (o.dismissOnBg && e.target.hasAttribute('data-layer-bg')) layer.close();
    });
    el.addEventListener('keydown', (e) => {
      if (e.key !== 'Tab') return;
      const f = $$('a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])', layer.box)
        .filter((n) => n.offsetParent !== null);
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
    setTimeout(() => {
      if (layer.closed) return;
      const first = layer.body.querySelector('input:not([type="hidden"]):not([disabled]), select, textarea');
      (first || el.querySelector('[data-layer-close]')).focus();
    }, 30);
    return layer;
  }

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || !layers.length || confirmDialogOpen()) return;
    layers[layers.length - 1].close();
  });

  /** fmhConfirm with the page's wording; `message` is HTML built with esc() by the caller. */
  function confirmBox(o) {
    if (typeof window.fmhConfirm !== 'function') return Promise.resolve(false);
    return window.fmhConfirm({
      title: esc(o.title || 'Tasdiqlang'),
      message: o.message || '',
      confirmText: esc(o.confirmText || 'Tasdiqlash'),
      cancelText: 'Bekor qilish',
      type: o.type || 'warning'
    });
  }

  /** Reversals need a written reason. Resolves to the text, or null when cancelled. */
  function askReason(o) {
    return new Promise((resolve) => {
      let done = false;
      const layer = openLayer({
        title: o.title, subtitle: o.subtitle || '', narrow: true, dismissOnBg: false,
        html:
          '<form novalidate data-reason-form>' +
            (o.message ? '<p class="wh-hint" style="margin:0 0 12px">' + o.message + '</p>' : '') +
            '<label class="wh-field"><span class="wh-label">Sabab <span class="wh-req">*</span></span>' +
            '<textarea class="wh-textarea" name="reason" maxlength="500" placeholder="Nima uchun? (kamida 3 ta belgi)"></textarea>' +
            '<span class="wh-field-error" data-err hidden></span></label>' +
          '</form>',
        footer:
          '<button type="button" class="wh-btn" data-layer-close>Bekor qilish</button>' +
          '<button type="button" class="wh-btn ' + (o.danger === false ? 'wh-btn-primary' : 'wh-btn-danger') + '" data-reason-ok>' + esc(o.confirmText || 'Tasdiqlash') + '</button>',
        onClose: () => { if (!done) resolve(null); }
      });
      const ta = $('textarea', layer.body);
      const err = $('[data-err]', layer.body);
      function submit() {
        const v = ta.value.replace(/\s+/g, ' ').trim();
        if (v.length < 3) {
          err.textContent = 'Sabab kamida 3 ta belgidan iborat bo\'lishi kerak.';
          err.hidden = false;
          ta.setAttribute('aria-invalid', 'true');
          ta.focus();
          return;
        }
        done = true;
        layer.close();
        resolve(v);
      }
      $('[data-reason-ok]', layer.foot).addEventListener('click', submit);
      ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit(); });
    });
  }

  async function runBusy(btn, fn) {
    if (btn && btn.getAttribute('aria-busy') === 'true') return undefined;
    if (btn) { btn.setAttribute('aria-busy', 'true'); btn.disabled = true; }
    try { return await fn(); }
    finally { if (btn) { btn.removeAttribute('aria-busy'); btn.disabled = false; } }
  }

  // --- Search-and-pick combo box ---------------------------------------------------
  // source(query) -> Promise<[{id, label, sub, raw}]>. One picked value at a time.
  function makeCombo(host, o) {
    const id = 'cb' + (++layerSeq);
    host.classList.add('wh-combo');
    host.innerHTML =
      '<input class="wh-input" type="text" autocomplete="off" role="combobox" aria-expanded="false" aria-autocomplete="list" ' +
        'aria-controls="' + id + '-l" placeholder="' + esc(o.placeholder || 'Qidirish…') + '" aria-label="' + esc(o.ariaLabel || o.placeholder || 'Qidirish') + '">' +
      '<ul class="wh-combo-list" id="' + id + '-l" role="listbox" hidden></ul>' +
      '<div class="wh-chosen" hidden><span class="wh-chosen-text"></span>' +
        '<button type="button" class="wh-icon-btn" aria-label="Tanlovni bekor qilish"><i class="fas fa-xmark" aria-hidden="true"></i></button></div>';
    const input = $('input', host), list = $('ul', host), chosenEl = $('.wh-chosen', host), chosenText = $('.wh-chosen-text', host);
    let options = [], active = -1, seq = 0, chosen = null;

    function renderList(html) { list.innerHTML = html; list.hidden = !html; input.setAttribute('aria-expanded', html ? 'true' : 'false'); }
    function paintActive() {
      $$('.wh-combo-opt', list).forEach((li, i) => {
        li.setAttribute('aria-selected', i === active ? 'true' : 'false');
        if (i === active) { input.setAttribute('aria-activedescendant', li.id); li.scrollIntoView({ block: 'nearest' }); }
      });
    }
    async function search() {
      const q = input.value.trim();
      const mine = ++seq;
      if (q.length < (o.minChars || 0)) { renderList(''); return; }
      renderList('<li class="wh-combo-msg" role="presentation">Qidirilmoqda…</li>');
      let res = null;
      try { res = await o.source(q); } catch (e) { res = null; }
      if (mine !== seq) return;
      if (res === null) { options = []; renderList('<li class="wh-combo-msg" role="presentation">Qidirishda xatolik. Qayta urinib ko\'ring.</li>'); return; }
      options = res;
      active = options.length ? 0 : -1;
      if (!options.length) { renderList('<li class="wh-combo-msg" role="presentation">Hech narsa topilmadi.</li>'); return; }
      renderList(options.map((x, i) =>
        '<li class="wh-combo-opt" role="option" id="' + id + '-o' + i + '" data-i="' + i + '" aria-selected="' + (i === 0 ? 'true' : 'false') + '">' +
        esc(x.label) + (x.sub ? '<small>' + esc(x.sub) + '</small>' : '') + '</li>').join(''));
    }
    const searchSoon = debounce(search, o.debounce === undefined ? 250 : o.debounce);

    function pick(item) {
      chosen = item;
      input.hidden = true;
      chosenEl.hidden = false;
      chosenText.innerHTML = esc(item.label) + (item.sub ? '<small>' + esc(item.sub) + '</small>' : '');
      renderList('');
      if (o.onChange) o.onChange(item);
    }
    function clear(silent) {
      chosen = null;
      chosenEl.hidden = true;
      input.hidden = false;
      input.value = '';
      renderList('');
      if (!silent && o.onChange) o.onChange(null);
      if (!silent) input.focus();
    }

    input.addEventListener('input', searchSoon);
    input.addEventListener('focus', () => { if (o.openOnFocus !== false) search(); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); if (list.hidden) search(); else { active = Math.min(options.length - 1, active + 1); paintActive(); } }
      else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(0, active - 1); paintActive(); }
      else if (e.key === 'Enter') { if (!list.hidden && active >= 0 && options[active]) { e.preventDefault(); pick(options[active]); } }
      else if (e.key === 'Escape') { if (!list.hidden) { e.preventDefault(); e.stopPropagation(); renderList(''); } }
    });
    input.addEventListener('blur', () => setTimeout(() => renderList(''), 160));
    list.addEventListener('mousedown', (e) => {
      const li = e.target.closest('.wh-combo-opt');
      if (!li) return;
      e.preventDefault();
      const item = options[Number(li.dataset.i)];
      if (item) pick(item);
    });
    $('button', chosenEl).addEventListener('click', () => clear(false));

    return {
      get value() { return chosen; },
      set: pick,
      clear: function () { clear(true); },
      focus: function () { (chosen ? $('button', chosenEl) : input).focus(); }
    };
  }

  // Item and patient sources shared by several screens.
  function itemOption(i) {
    const bits = [];
    if (i.strength) bits.push(i.strength);
    if (i.form) bits.push(i.form);
    bits.push(typeLabel(i.item_type));
    return { id: i.id, label: i.name + (i.strength ? ' ' + i.strength : ''), sub: bits.join(' · ') + ' · qoldiq: ' + NF_QTY.format(Number(i.available_quantity || 0)) + ' ' + (i.base_unit || ''), raw: i };
  }
  function itemSource(extra) {
    return async function (q) {
      const r = await api('GET', '/items' + qs(Object.assign({ q: q, active: '1', limit: 15, sort: 'name' }, extra || {})));
      if (!r.ok) return null;
      return (r.data.items || []).map(itemOption);
    };
  }
  function patientOption(p) {
    return { id: p.id, label: p.name || p.id, sub: [p.code, p.phone].filter(Boolean).join(' · '), raw: p };
  }
  async function patientSource(q) {
    let list;
    try { list = await loadPatients(); } catch (e) { return null; }
    const needle = q.toLowerCase();
    return list.filter((p) =>
      String(p.name || '').toLowerCase().indexOf(needle) >= 0 ||
      String(p.code || '').toLowerCase().indexOf(needle) >= 0 ||
      String(p.phone || '').toLowerCase().indexOf(needle) >= 0).slice(0, 15).map(patientOption);
  }

  // ---------------------------------------------------------------------------
  // Generic render helpers
  // ---------------------------------------------------------------------------
  function loadingHtml(rows) {
    let s = '<div class="wh-card-body" aria-busy="true" aria-live="polite"><span class="sr-only" style="position:absolute;left:-9999px">Yuklanmoqda…</span>';
    for (let i = 0; i < (rows || 4); i++) s += '<span class="wh-skel wh-skel-row" style="margin:12px 0"></span>';
    return s + '</div>';
  }
  function emptyHtml(icon, title, text, actionHtml) {
    return '<div class="wh-state"><i class="fas ' + esc(icon) + '" aria-hidden="true"></i><strong>' + esc(title) + '</strong>' +
      (text ? '<p>' + esc(text) + '</p>' : '') + (actionHtml || '') + '</div>';
  }
  function errorHtml(message, retryAction) {
    return '<div class="wh-state wh-state-error" role="alert"><i class="fas fa-triangle-exclamation" aria-hidden="true"></i>' +
      '<strong>Ma\'lumotni yuklab bo\'lmadi</strong><p>' + esc(message) + '</p>' +
      (retryAction ? '<button type="button" class="wh-btn" data-action="' + esc(retryAction) + '"><i class="fas fa-rotate" aria-hidden="true"></i> Qayta urinish</button>' : '') + '</div>';
  }

  function pagerHtml(p, action) {
    // p = {offset, limit, total}
    const from = p.total ? p.offset + 1 : 0;
    const to = Math.min(p.offset + p.limit, p.total);
    return '<div class="wh-pager"><span>' + (p.total ? from + '–' + to + ' / ' + p.total : 'Natija yo\'q') + '</span>' +
      '<div class="wh-pager-btns">' +
      '<button type="button" class="wh-btn wh-btn-sm" data-action="' + action + '" data-dir="-1"' + (p.offset <= 0 ? ' disabled' : '') + '><i class="fas fa-chevron-left" aria-hidden="true"></i> Oldingi</button>' +
      '<button type="button" class="wh-btn wh-btn-sm" data-action="' + action + '" data-dir="1"' + (p.offset + p.limit >= p.total ? ' disabled' : '') + '>Keyingi <i class="fas fa-chevron-right" aria-hidden="true"></i></button>' +
      '</div></div>';
  }

  function fieldError(form, err) {
    // Show a server refusal on the form: banner on top, red frame on the field it names.
    $$('[aria-invalid="true"]', form).forEach((n) => n.removeAttribute('aria-invalid'));
    let banner = $('[data-form-error]', form);
    if (!banner) {
      banner = document.createElement('div');
      banner.className = 'wh-form-error';
      banner.setAttribute('role', 'alert');
      banner.setAttribute('data-form-error', '');
      form.insertBefore(banner, form.firstChild);
    }
    banner.textContent = (err && err.error) || 'Xatolik yuz berdi.';
    banner.hidden = false;
    let target = null;
    if (err && err.field) {
      target = form.querySelector('[name="' + String(err.field).replace(/[^A-Za-z0-9_-]/g, '') + '"]');
      if (target) { target.setAttribute('aria-invalid', 'true'); }
    }
    (target || banner).scrollIntoView({ block: 'nearest' });
    if (target && typeof target.focus === 'function') target.focus();
  }
  function clearFormError(form) {
    const banner = $('[data-form-error]', form);
    if (banner) banner.hidden = true;
    $$('[aria-invalid="true"]', form).forEach((n) => n.removeAttribute('aria-invalid'));
  }

  // The actions table is filled in by each section below.
  const ACTIONS = {};
  document.addEventListener('click', (e) => {
    const t = e.target.closest('[data-action]');
    if (!t || t.disabled) return;
    const fn = ACTIONS[t.dataset.action];
    if (!fn) return;
    e.preventDefault();
    fn(t, e);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    const t = e.target;
    if (t && t.tagName === 'TR' && t.dataset && t.dataset.action) {
      const fn = ACTIONS[t.dataset.action];
      if (fn) { e.preventDefault(); fn(t, e); }
    }
  });

  // ---------------------------------------------------------------------------
  // Defaults used only when GET /settings could not be read
  // ---------------------------------------------------------------------------
  const DEFAULT_UNITS = ['dona', 'tabletka', 'kapsula', 'ampula', 'flakon', 'shisha', 'shprits', 'paket',
    'ml', 'l', 'g', 'mg', 'kg', 'qadoq', 'quti', 'blister', 'tuba', 'doza', 'juft'];
  const DEFAULT_TYPES = [
    { id: 'medicine', label: 'Dori-darmon' }, { id: 'vitamin', label: 'Vitamin' },
    { id: 'injection', label: 'Inyeksiya / eritma' }, { id: 'syringe', label: 'Shprits' },
    { id: 'consumable', label: 'Sarf materiali' }, { id: 'equipment', label: 'Jihoz' }, { id: 'other', label: 'Boshqa' }
  ];
  function unitList() { return (S.settings.units && S.settings.units.length) ? S.settings.units : DEFAULT_UNITS; }
  function typeList() { return (S.settings.item_types && S.settings.item_types.length) ? S.settings.item_types : DEFAULT_TYPES; }
  function unitOptions(selected, emptyLabel) {
    return (emptyLabel !== undefined ? '<option value="">' + esc(emptyLabel) + '</option>' : '') +
      unitList().map((u) => '<option value="' + esc(u) + '"' + (u === selected ? ' selected' : '') + '>' + esc(u) + '</option>').join('');
  }

  function rememberCategories(items) {
    let grew = false;
    (items || []).forEach((i) => {
      if (i.category && S.categories.indexOf(i.category) < 0) { S.categories.push(i.category); grew = true; }
    });
    if (grew) {
      S.categories.sort((a, b) => a.localeCompare(b));
      const dl = document.getElementById('wh-categories');
      if (dl) dl.innerHTML = S.categories.map((c) => '<option value="' + esc(c) + '"></option>').join('');
      const sel = document.getElementById('inv-category');
      if (sel) {
        const cur = sel.value;
        sel.innerHTML = '<option value="">Barcha kategoriyalar</option>' + S.categories.map((c) =>
          '<option value="' + esc(c) + '"' + (c === cur ? ' selected' : '') + '>' + esc(c) + '</option>').join('');
      }
    }
  }

  // ===========================================================================
  // DASHBOARD
  // ===========================================================================
  const DASH = { alerts: [], alertsError: '', alertFilter: 'all', summary: null };

  async function loadDashboard() {
    const panel = $('#panel-dashboard');
    if (!S.loaded.dashboard) {
      panel.innerHTML = '<div class="wh-kpi-grid" aria-busy="true">' +
        new Array(6).join('<span class="wh-skel wh-skel-kpi"></span>') + '</div>' + '<div class="wh-card">' + loadingHtml(5) + '</div>';
    }
    const results = await Promise.all([api('GET', '/summary'), api('GET', '/alerts' + qs({ status: 'active' }))]);
    const sum = results[0], al = results[1];
    S.stale.dashboard = false;
    if (!sum.ok) {
      S.loaded.dashboard = false;
      panel.innerHTML = errorHtml(sum.data.error, 'dash-retry');
      return;
    }
    S.loaded.dashboard = true;
    DASH.summary = sum.data;
    S.costs = sum.data.total_value !== undefined;
    if (sum.data.settings) {
      S.settings.default_min_stock = sum.data.settings.default_min_stock;
      S.settings.expiry_warning_days = sum.data.settings.expiry_warning_days;
    }
    DASH.alerts = al.ok ? (al.data.alerts || []) : [];
    DASH.alertsError = al.ok ? '' : al.data.error;
    renderDashboard();
  }

  function kpiHtml(o) {
    const zero = o.value === 0 || o.value === '0';
    const inner =
      '<span class="wh-kpi-label">' + esc(o.label) + '</span>' +
      (o.filter ? '<span class="wh-kpi-go" aria-hidden="true"><i class="fas fa-arrow-right"></i></span>' : '') +
      '<span class="wh-kpi-value' + (o.money ? ' is-money' : '') + '">' + o.valueHtml + '</span>' +
      (o.sub ? '<span class="wh-kpi-sub">' + o.sub + '</span>' : '');
    if (o.filter) {
      return '<button type="button" class="wh-kpi ' + o.cls + (zero ? ' is-zero' : '') + '" data-action="kpi" data-filter="' + esc(o.filter) + '"' +
        ' title="Mahsulotlar jadvalida ko\'rsatish">' + inner + '</button>';
    }
    return '<div class="wh-kpi ' + o.cls + '">' + inner + '</div>';
  }

  function renderDashboard() {
    const sum = DASH.summary;
    const panel = $('#panel-dashboard');
    const days = (sum.settings && sum.settings.expiry_warning_days) || S.settings.expiry_warning_days;
    const units = sum.units_by_unit || [];
    let kpis = '';
    kpis += kpiHtml({ cls: 'k-ok', label: 'Mahsulot turlari', value: sum.items_total, valueHtml: fmtQty(sum.items_total), sub: 'Faol mahsulotlar soni', filter: 'all' });
    kpis += '<div class="wh-kpi k-info"><span class="wh-kpi-label">Qoldiq (birlik bo\'yicha)</span>' +
      (units.length
        ? '<ul class="wh-unit-lines">' + units.map((u) => '<li><b>' + fmtQty(u.qty) + '</b><span>' + esc(u.unit) + '</span></li>').join('') + '</ul>'
        : '<div class="wh-kpi-value is-zero">0</div>') +
      '<div class="wh-kpi-sub">Har bir birlik alohida sanaladi</div></div>';
    if (S.costs) {
      kpis += kpiHtml({ cls: 'k-money', label: 'Ombor qiymati', money: true, valueHtml: fmtMoney(sum.total_value),
        sub: 'Yaroqli: ' + fmtMoney(sum.available_value) + '<br>Muddati o\'tgan: ' + fmtMoney(sum.expired_value) });
    }
    kpis += kpiHtml({ cls: 'k-low', label: 'Kam qoldiq', value: sum.low_stock_count, valueHtml: fmtQty(sum.low_stock_count), sub: 'Minimaldan kam', filter: 'low' });
    kpis += kpiHtml({ cls: 'k-out', label: 'Tugagan', value: sum.out_of_stock_count, valueHtml: fmtQty(sum.out_of_stock_count), sub: 'Yaroqli qoldiq yo\'q', filter: 'out' });
    kpis += kpiHtml({ cls: 'k-exp', label: "Muddati o'tgan", value: sum.expired_count, valueHtml: fmtQty(sum.expired_count), sub: 'Partiyasi muddati o\'tgan', filter: 'expired' });
    kpis += kpiHtml({ cls: 'k-soon', label: 'Muddati yaqin', value: sum.expiring_count, valueHtml: fmtQty(sum.expiring_count), sub: esc(days) + ' kun ichida tugaydi', filter: 'expiring' });

    const costs = S.costs;
    const receipts = (sum.recent_receipts || []);
    const disp = (sum.recent_dispensings || []);

    let rc = '';
    if (!receipts.length) rc = emptyHtml('fa-truck-ramp-box', 'Kirim hali yo\'q', 'Tasdiqlangan kirim hujjatlari shu yerda ko\'rinadi.');
    else {
      rc = '<ul class="wh-list">' + receipts.map((r) =>
        '<li><button type="button" class="wh-row-click" data-action="open-receipt" data-id="' + esc(r.id) + '">' +
        '<span class="wh-row-main"><strong>' + esc(r.supplier_name || 'Yetkazib beruvchi ko\'rsatilmagan') + '</strong>' +
        '<small>' + esc(r.id) + ' · ' + fmtDate(r.receipt_date) + ' · ' + esc(r.line_count) + ' qator' +
        (r.invoice_number ? ' · № ' + esc(r.invoice_number) : '') + '</small></span>' +
        '<span class="wh-row-side">' + (costs && r.total_amount !== undefined ? '<b>' + fmtMoney(r.total_amount) + '</b>' : '') + '</span></button></li>').join('') + '</ul>';
    }
    let dp = '';
    if (!disp.length) dp = emptyHtml('fa-hand-holding-medical', 'Berish hali yo\'q', 'Bemorlarga berilgan dori va materiallar shu yerda ko\'rinadi.');
    else {
      dp = '<ul class="wh-list">' + disp.map((d) =>
        '<li><div class="wh-row-click" style="cursor:default">' +
        '<span class="wh-row-main"><strong>' + esc(d.item_name) + '</strong>' +
        '<small>' + esc(d.patient_name || '—') + ' · ' + fmtDateTime(d.created_at) + (d.status === 'reversed' ? ' · qaytarilgan' : '') + '</small></span>' +
        '<span class="wh-row-side"><b>' + plural(d.quantity, d.base_unit) + '</b></span></div></li>').join('') + '</ul>';
    }

    panel.innerHTML =
      '<div class="wh-kpi-grid">' + kpis + '</div>' +
      '<div class="wh-card" id="dash-alerts"></div>' +
      '<div class="wh-grid-2" style="margin-top:16px">' +
        '<div class="wh-card"><div class="wh-card-head"><h2 class="wh-card-title"><i class="fas fa-truck-ramp-box" aria-hidden="true"></i> So\'nggi kirimlar</h2>' +
          '<button type="button" class="wh-btn wh-btn-sm" data-action="goto-tab" data-tab="receipts">Hammasi</button></div>' + rc + '</div>' +
        '<div class="wh-card"><div class="wh-card-head"><h2 class="wh-card-title"><i class="fas fa-hand-holding-medical" aria-hidden="true"></i> So\'nggi berilganlar</h2>' +
          (S.whWrite ? '<button type="button" class="wh-btn wh-btn-sm" data-action="goto-tab" data-tab="dispensing">Dori berish</button>' : '') + '</div>' + dp + '</div>' +
      '</div>';
    renderAlerts();
  }

  function renderAlerts() {
    const host = $('#dash-alerts');
    if (!host) return;
    const all = DASH.alerts;
    const counts = { all: all.length, out_of_stock: 0, low_stock: 0, expired: 0, expiring_soon: 0 };
    all.forEach((a) => { if (counts[a.alert_type] !== undefined) counts[a.alert_type]++; });
    const f = DASH.alertFilter;
    const shown = all.filter((a) => f === 'all' || a.alert_type === f);
    const chips = [['all', 'Hammasi'], ['out_of_stock', 'Tugagan'], ['low_stock', 'Kam qoldiq'], ['expired', "Muddati o'tgan"], ['expiring_soon', 'Muddati yaqin']]
      .map((c) => '<button type="button" class="wh-chip" data-action="alert-filter" data-filter="' + c[0] + '" aria-pressed="' + (f === c[0]) + '">' +
        esc(c[1]) + ' <span>' + counts[c[0]] + '</span></button>').join('');
    let body;
    if (DASH.alertsError) body = errorHtml(DASH.alertsError, 'dash-retry');
    else if (!shown.length) body = emptyHtml('fa-circle-check', 'Ogohlantirish yo\'q', all.length ? 'Bu turdagi ogohlantirish yo\'q.' : 'Hamma mahsulot normada: kam qoldiq ham, muddati yaqin partiya ham yo\'q.');
    else {
      const LIMIT = 80;
      body = '<ul class="wh-list wh-scroll">' + shown.slice(0, LIMIT).map((a) => {
        const unit = a.base_unit || '';
        let info;
        if (a.alert_type === 'low_stock' || a.alert_type === 'out_of_stock') {
          const shortage = Math.max(Number(a.threshold || 0) - Number(a.quantity || 0), 0);
          info = 'Qoldiq: <b>' + plural(a.quantity, unit) + '</b><br>Minimal: ' + plural(a.threshold, unit) + ' · Yetishmaydi: <b>' + plural(shortage, unit) + '</b>';
        } else {
          info = 'Qoldiq: <b>' + plural(a.quantity, unit) + '</b><br>Muddati: ' + fmtDate(a.expiry_date);
        }
        return '<li><button type="button" class="wh-row-click" data-action="open-item" data-id="' + esc(a.item_id) + '">' +
          '<span class="wh-row-main"><strong>' + esc(a.item_name) + '</strong><small>' + badge(a.alert_type, ALERT_LABEL[a.alert_type] || a.alert_type) +
          (a.batch_no ? ' &nbsp;Partiya: ' + esc(a.batch_no) : '') + '</small></span>' +
          '<span class="wh-row-side">' + info + '</span></button></li>';
      }).join('') + '</ul>' + (shown.length > LIMIT ? '<div class="wh-pager"><span>Yana ' + (shown.length - LIMIT) + ' ta ogohlantirish bor. To\'liq ro\'yxat: Mahsulotlar bo\'limi.</span></div>' : '');
    }
    host.innerHTML = '<div class="wh-card-head"><h2 class="wh-card-title"><i class="fas fa-bell" aria-hidden="true"></i> Faol ogohlantirishlar</h2></div>' +
      '<div class="wh-chips" style="padding-bottom:10px">' + chips + '</div>' + body;
  }

  ACTIONS['dash-retry'] = () => { S.loaded.dashboard = false; loadDashboard(); };
  ACTIONS['alert-filter'] = (t) => { DASH.alertFilter = t.dataset.filter; renderAlerts(); };
  ACTIONS['goto-tab'] = (t) => switchTab(t.dataset.tab);
  ACTIONS['kpi'] = (t) => {
    const f = t.dataset.filter;
    resetInvFilters();
    if (f !== 'all') INV.status = f;
    S.stale.inventory = true;
    switchTab('inventory');
  };

  // ===========================================================================
  // INVENTORY TABLE
  // ===========================================================================
  const INV = { q: '', category: '', item_type: '', status: '', supplier_id: '', active: '1', sort: 'name', dir: 'asc', limit: 25, offset: 0, items: [], total: 0, seq: 0, shell: false, error: '' };

  function resetInvFilters() {
    Object.assign(INV, { q: '', category: '', item_type: '', status: '', supplier_id: '', active: '1', sort: 'name', dir: 'asc', offset: 0 });
  }

  const SORTS = [
    ['name', 'Nomi'], ['category', 'Kategoriya'], ['available_quantity', 'Mavjud miqdor'], ['nearest_expiry', 'Eng yaqin muddat'],
    ['stock_status', 'Holat'], ['min_stock_level', 'Minimal qoldiq'], ['shortage', 'Yetishmovchilik']
  ];

  function ensureInvShell() {
    if (INV.shell) return;
    const panel = $('#panel-inventory');
    const sorts = SORTS.concat(S.costs ? [['stock_value', 'Qiymati']] : []);
    panel.innerHTML =
      '<div class="wh-card">' +
        '<div class="wh-toolbar">' +
          '<label class="wh-field wh-grow"><span class="wh-label">Qidirish</span><input class="wh-input" id="inv-q" type="search" placeholder="Nomi, xalqaro nomi, artikul yoki shtrix-kod" autocomplete="off"></label>' +
          '<label class="wh-field"><span class="wh-label">Turi</span><select class="wh-select" id="inv-type"><option value="">Barcha turlar</option>' +
            typeList().map((t) => '<option value="' + esc(t.id) + '">' + esc(t.label) + '</option>').join('') + '</select></label>' +
          '<label class="wh-field"><span class="wh-label">Holat</span><select class="wh-select" id="inv-status"><option value="">Barcha holatlar</option>' +
            Object.keys(STATUS_LABEL).map((k) => '<option value="' + k + '">' + esc(STATUS_LABEL[k]) + '</option>').join('') + '</select></label>' +
          '<label class="wh-field"><span class="wh-label">Kategoriya</span><select class="wh-select" id="inv-category"><option value="">Barcha kategoriyalar</option></select></label>' +
          '<label class="wh-field"><span class="wh-label">Yetkazib beruvchi</span><select class="wh-select" id="inv-supplier"><option value="">Barchasi</option></select></label>' +
          '<label class="wh-field"><span class="wh-label">Faollik</span><select class="wh-select" id="inv-active"><option value="1">Faol</option><option value="0">Nofaol</option><option value="">Hammasi</option></select></label>' +
          '<div class="wh-field"><span class="wh-label">Saralash</span><div style="display:flex;gap:6px"><select class="wh-select" id="inv-sort" aria-label="Saralash">' +
            sorts.map((s) => '<option value="' + s[0] + '">' + esc(s[1]) + '</option>').join('') + '</select>' +
            '<button type="button" class="wh-btn" id="inv-dir" data-action="inv-dir" title="Tartibni almashtirish" aria-label="Saralash tartibi"><i class="fas fa-arrow-down-short-wide" aria-hidden="true"></i></button></div></div>' +
          '<div class="wh-toolbar-end">' +
            '<button type="button" class="wh-btn" data-action="inv-reset"><i class="fas fa-filter-circle-xmark" aria-hidden="true"></i> Tozalash</button>' +
            (S.whWrite ? '<button type="button" class="wh-btn wh-btn-primary" data-action="item-new"><i class="fas fa-plus" aria-hidden="true"></i> Yangi mahsulot</button>' : '') +
          '</div>' +
        '</div>' +
        '<div class="wh-chips" id="inv-chips" hidden></div>' +
        '<div id="inv-body"></div>' +
        '<div id="inv-pager"></div>' +
      '</div>';
    INV.shell = true;
    const reload = () => { INV.offset = 0; loadInventory(); };
    $('#inv-q').addEventListener('input', debounce((e) => { INV.q = e.target.value.trim(); reload(); }, 300));
    [['inv-type', 'item_type'], ['inv-status', 'status'], ['inv-category', 'category'], ['inv-supplier', 'supplier_id'], ['inv-active', 'active'], ['inv-sort', 'sort']]
      .forEach((p) => $('#' + p[0]).addEventListener('change', (e) => { INV[p[1]] = e.target.value; reload(); }));
    loadSuppliers().then(() => {
      const sel = $('#inv-supplier');
      if (sel) sel.innerHTML = supplierOptions(INV.supplier_id, 'Barchasi');
    });
    // All categories once, so the filter lists more than the current page.
    api('GET', '/items' + qs({ limit: 500, sort: 'category' })).then((r) => { if (r.ok) rememberCategories(r.data.items); });
  }

  function syncInvControls() {
    const set = (id, v) => { const el = $('#' + id); if (el && el.value !== v) el.value = v; };
    set('inv-q', INV.q); set('inv-type', INV.item_type); set('inv-status', INV.status);
    set('inv-category', INV.category); set('inv-supplier', INV.supplier_id); set('inv-active', INV.active); set('inv-sort', INV.sort);
    const dir = $('#inv-dir');
    if (dir) dir.innerHTML = '<i class="fas ' + (INV.dir === 'desc' ? 'fa-arrow-up-wide-short' : 'fa-arrow-down-short-wide') + '" aria-hidden="true"></i>';
    // Filter chips: what is narrowing the list besides the search box.
    const chips = [];
    if (INV.status) chips.push(['status', 'Holat: ' + (STATUS_LABEL[INV.status] || INV.status)]);
    if (INV.item_type) chips.push(['item_type', 'Turi: ' + typeLabel(INV.item_type)]);
    if (INV.category) chips.push(['category', 'Kategoriya: ' + INV.category]);
    if (INV.supplier_id) chips.push(['supplier_id', 'Yetkazib beruvchi tanlangan']);
    if (INV.active !== '1') chips.push(['active', INV.active === '0' ? 'Faqat nofaol' : 'Faol va nofaol']);
    const host = $('#inv-chips');
    host.hidden = !chips.length;
    host.innerHTML = chips.map((c) => '<span class="wh-chip wh-chip-active">' + esc(c[1]) +
      ' <button type="button" class="wh-icon-btn" style="width:20px;height:20px;min-width:20px" data-action="inv-clear" data-key="' + c[0] + '" aria-label="Filtrni olib tashlash"><i class="fas fa-xmark" aria-hidden="true"></i></button></span>').join('');
  }

  async function loadInventory() {
    ensureInvShell();
    syncInvControls();
    const body = $('#inv-body');
    const mine = ++INV.seq;
    if (!S.loaded.inventory || !INV.items.length) body.innerHTML = loadingHtml(6);
    else $('.wh-table-wrap', body) && $('.wh-table-wrap', body).classList.add('wh-table-busy');
    const params = { q: INV.q, category: INV.category, item_type: INV.item_type, status: INV.status, supplier_id: INV.supplier_id,
      active: INV.active, sort: INV.sort, dir: INV.dir, limit: INV.limit, offset: INV.offset };
    const r = await api('GET', '/items' + qs(params));
    if (mine !== INV.seq) return;
    S.stale.inventory = false;
    if (!r.ok) {
      S.loaded.inventory = false;
      body.innerHTML = errorHtml(r.data.error, 'inv-retry');
      $('#inv-pager').innerHTML = '';
      return;
    }
    S.loaded.inventory = true;
    INV.items = r.data.items || [];
    INV.total = r.data.total || 0;
    if (INV.items.length) S.costs = S.costs || INV.items[0].avg_unit_cost !== undefined;
    rememberCategories(INV.items);
    // A page past the end (rows were removed meanwhile) goes back to the last page.
    if (!INV.items.length && INV.total > 0 && INV.offset > 0) {
      INV.offset = Math.max(0, Math.floor((INV.total - 1) / INV.limit) * INV.limit);
      loadInventory();
      return;
    }
    renderInventory();
  }

  function sortHeader(label, key, extraCls) {
    const on = INV.sort === key;
    return '<th scope="col" class="' + (extraCls || '') + '"' + (on ? ' aria-sort="' + (INV.dir === 'desc' ? 'descending' : 'ascending') + '"' : '') + '>' +
      '<button type="button" class="wh-th-btn" data-action="inv-sort" data-sort="' + key + '">' + esc(label) +
      (on ? '<span class="wh-sort-ind">' + (INV.dir === 'desc' ? '▼' : '▲') + '</span>' : '') + '</button></th>';
  }

  function expiryCell(i) {
    if (!i.nearest_expiry) return '—';
    const d = new Date(i.nearest_expiry + 'T00:00:00');
    const days = Math.round((d.getTime() - new Date(todayISO() + 'T00:00:00').getTime()) / 86400000);
    const warn = (S.settings.expiry_warning_days || 30);
    const cls = days <= warn ? 'wh-soon-text' : '';
    return '<span class="' + cls + '">' + fmtDate(i.nearest_expiry) + '</span><span class="wh-cell-sub">' +
      (days <= 0 ? 'bugun' : days + ' kun qoldi') + '</span>';
  }

  function renderInventory() {
    const body = $('#inv-body');
    const costs = S.costs && INV.items.length && INV.items[0].avg_unit_cost !== undefined;
    if (!INV.items.length) {
      const filtered = INV.q || INV.status || INV.item_type || INV.category || INV.supplier_id || INV.active !== '1';
      body.innerHTML = emptyHtml('fa-box-open', filtered ? 'Mahsulot topilmadi' : 'Omborda mahsulot yo\'q',
        filtered ? 'Qidiruv yoki filtrlarga mos mahsulot yo\'q.' : 'Birinchi mahsulotni qo\'shing yoki kirim hujjati orqali qabul qiling.',
        filtered ? '<button type="button" class="wh-btn" data-action="inv-reset">Filtrlarni tozalash</button>' :
          (S.whWrite ? '<button type="button" class="wh-btn wh-btn-primary" data-action="item-new"><i class="fas fa-plus" aria-hidden="true"></i> Yangi mahsulot</button>' : ''));
      $('#inv-pager').innerHTML = '';
      return;
    }
    const rows = INV.items.map((i) => {
      const unit = i.base_unit;
      const pkg = i.package_unit ? '1 ' + esc(i.package_unit) + ' = ' + plural(i.units_per_package, unit) : '—';
      const expired = Number(i.expired_quantity) > 0 ? '<span class="wh-cell-sub wh-expired-text">Muddati o\'tgan: ' + plural(i.expired_quantity, unit) + '</span>' : '';
      return '<tr class="wh-row-click' + (i.is_active ? '' : ' is-inactive') + '" tabindex="0" data-action="open-item" data-id="' + esc(i.id) + '">' +
        '<td data-label="Nomi"><span class="wh-cell-name">' + esc(i.name) + '</span><span class="wh-cell-sub">' + esc(i.category || '') +
          (i.generic_name ? ' · ' + esc(i.generic_name) : '') + (i.sku ? ' · ' + esc(i.sku) : '') + '</span></td>' +
        '<td data-label="Dozasi">' + (i.strength ? esc(i.strength) : '—') + '</td>' +
        '<td data-label="Turi / shakli">' + esc(typeLabel(i.item_type)) + '<span class="wh-cell-sub">' + esc(i.form || '') + '</span></td>' +
        '<td data-label="Mavjud" class="wh-right wh-num"><b>' + fmtQty(i.available_quantity) + '</b> ' + esc(unit) + expired + '</td>' +
        '<td data-label="Qadoq">' + pkg + '</td>' +
        (costs ? '<td data-label="Qadoq narxi" class="wh-right wh-num">' + fmtMoney(i.last_package_price) + '</td>' +
          '<td data-label="Tannarx (1 ' + esc(unit) + ')" class="wh-right wh-num" title="Oxirgi kirim narxi: ' + fmtMoney(i.last_unit_cost, true).replace(/<[^>]*>/g, '') + '">' + fmtMoney(i.avg_unit_cost, true) + '</td>' +
          '<td data-label="Qiymati" class="wh-right wh-num">' + fmtMoney(i.stock_value) + '</td>' : '') +
        '<td data-label="Minimal" class="wh-right wh-num">' + plural(i.min_stock_level, unit) + '</td>' +
        '<td data-label="Muddati">' + expiryCell(i) + '</td>' +
        '<td data-label="Holat">' + statusBadge(i.stock_status) + (i.is_active ? '' : ' ' + badge('inactive', 'Nofaol')) + '</td></tr>';
    }).join('');
    body.innerHTML = '<div class="wh-table-wrap"><table class="wh-table wh-stack"><thead><tr>' +
      sortHeader('Nomi', 'name') + '<th scope="col">Dozasi</th><th scope="col">Turi / shakli</th>' +
      sortHeader('Mavjud', 'available_quantity', 'wh-right') + '<th scope="col">Qadoq</th>' +
      (costs ? '<th scope="col" class="wh-right">Qadoq narxi</th><th scope="col" class="wh-right">Tannarx</th>' + sortHeader('Qiymati', 'stock_value', 'wh-right') : '') +
      sortHeader('Minimal', 'min_stock_level', 'wh-right') + sortHeader('Muddati', 'nearest_expiry') + sortHeader('Holat', 'stock_status') +
      '</tr></thead><tbody>' + rows + '</tbody></table></div>';
    $('#inv-pager').innerHTML = pagerHtml({ offset: INV.offset, limit: INV.limit, total: INV.total }, 'inv-page') ;
    // Page size lives in the pager line.
    const pg = $('#inv-pager .wh-pager');
    const sel = document.createElement('label');
    sel.className = 'wh-hint';
    sel.innerHTML = 'Sahifada: <select class="wh-select" id="inv-limit" aria-label="Sahifadagi qatorlar">' +
      [25, 50, 100].map((n) => '<option value="' + n + '"' + (n === INV.limit ? ' selected' : '') + '>' + n + '</option>').join('') + '</select>';
    pg.insertBefore(sel, pg.lastElementChild);
    $('#inv-limit').addEventListener('change', (e) => { INV.limit = Number(e.target.value); INV.offset = 0; loadInventory(); });
  }

  ACTIONS['inv-retry'] = () => loadInventory();
  ACTIONS['inv-reset'] = () => { resetInvFilters(); loadInventory(); };
  ACTIONS['inv-clear'] = (t) => { const k = t.dataset.key; INV[k] = (k === 'active') ? '1' : ''; INV.offset = 0; loadInventory(); };
  ACTIONS['inv-dir'] = () => { INV.dir = INV.dir === 'asc' ? 'desc' : 'asc'; INV.offset = 0; loadInventory(); };
  ACTIONS['inv-sort'] = (t) => {
    const k = t.dataset.sort;
    if (INV.sort === k) INV.dir = INV.dir === 'asc' ? 'desc' : 'asc';
    else { INV.sort = k; INV.dir = (k === 'name' || k === 'category') ? 'asc' : 'desc'; }
    INV.offset = 0;
    loadInventory();
  };
  ACTIONS['inv-page'] = (t) => {
    const next = INV.offset + Number(t.dataset.dir) * INV.limit;
    INV.offset = Math.max(0, next);
    loadInventory();
    $('#panel-inventory').scrollIntoView({ block: 'start' });
  };

  // ===========================================================================
  // ITEM DRAWER
  // ===========================================================================
  const ITEMS = {};   // id -> last loaded item detail

  function itemDrawer() {
    for (let i = layers.length - 1; i >= 0; i--) if (layers[i].itemId) return layers[i];
    return null;
  }

  async function openItem(id) {
    const existing = layers.find((l) => l.itemId === id);
    if (existing) { await paintItem(existing); return existing; }
    const layer = openLayer({ drawer: true, title: 'Mahsulot', html: loadingHtml(8) });
    layer.itemId = id;
    await paintItem(layer);
    return layer;
  }

  function dlRow(label, valueHtml) {
    return '<div><dt>' + esc(label) + '</dt><dd>' + valueHtml + '</dd></div>';
  }

  async function paintItem(layer) {
    const r = await api('GET', '/items/' + encodeURIComponent(layer.itemId));
    if (layer.closed) return;
    if (!r.ok) {
      layer.setTitle('Mahsulot', '');
      layer.setBody(errorHtml(r.data.error, 'item-reload'));
      layer.setFoot('');
      return;
    }
    const it = r.data;
    ITEMS[it.id] = it;
    layer.item = it;
    const unit = it.base_unit;
    const costs = it.avg_unit_cost !== undefined;
    if (costs) S.costs = true;
    layer.setTitle(it.name + (it.strength ? ' ' + it.strength : ''),
      [typeLabel(it.item_type), it.category, it.sku].filter(Boolean).join(' · '));

    const detail =
      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">' + statusBadge(it.stock_status) +
      (it.is_active ? '' : badge('inactive', 'Nofaol')) + (it.track_expiry ? badge('ok', 'Yaroqlilik nazoratda') : '') + '</div>' +
      '<dl class="wh-dl">' +
        dlRow('Mavjud (yaroqli)', '<b>' + plural(it.available_quantity, unit) + '</b>') +
        dlRow('Muddati o\'tgan', Number(it.expired_quantity) > 0 ? '<span class="wh-expired-text">' + plural(it.expired_quantity, unit) + '</span>' : '0') +
        dlRow('Jami qoldiq', plural(it.stock_quantity, unit)) +
        dlRow('Minimal qoldiq', plural(it.min_stock_level, unit)) +
        dlRow('Yetishmovchilik', Number(it.shortage) > 0 ? '<span class="wh-expired-text">' + plural(it.shortage, unit) + '</span>' : '—') +
        dlRow('Eng yaqin muddat', it.nearest_expiry ? fmtDate(it.nearest_expiry) : '—') +
        dlRow('Qadoq', it.package_unit ? '1 ' + esc(it.package_unit) + ' = ' + plural(it.units_per_package, unit) : 'Qadoqsiz') +
        dlRow('Bemor narxi (1 ' + unit + ')', fmtMoney(it.unit_price)) +
        (costs ? dlRow("O'rtacha tannarx (1 " + unit + ')', fmtMoney(it.avg_unit_cost, true)) +
          dlRow('Oxirgi qadoq narxi', fmtMoney(it.last_package_price)) +
          dlRow('Oxirgi birlik narxi', fmtMoney(it.last_unit_cost, true)) +
          dlRow('Ombor qiymati', fmtMoney(it.stock_value)) +
          (it.expired_value !== undefined ? dlRow('shundan muddati o\'tgan', fmtMoney(it.expired_value)) : '') : '') +
        dlRow('Yetkazib beruvchi', esc(it.supplier_name || '—')) +
        dlRow('Xalqaro nomi', esc(it.generic_name || '—')) +
        dlRow('Shakli', esc(it.form || '—')) +
        dlRow('Ishlab chiqaruvchi', esc(it.manufacturer || '—')) +
        dlRow('Shtrix-kod', esc(it.barcode || '—')) +
        dlRow('Kasr miqdor', it.allow_fraction ? 'Ruxsat etilgan' : 'Faqat butun son') +
      '</dl>' + (it.description ? '<p class="wh-hint" style="margin-top:12px">' + esc(it.description) + '</p>' : '');

    const batches = it.batches || [];
    const today = todayISO();
    const bRows = batches.map((b) => {
      const exp = b.expiry_date;
      const cls = b.is_expired && Number(b.remaining_qty) > 0 ? 'wh-expired-text' : '';
      return '<tr><td data-label="Partiya"><span class="wh-mono">' + esc(b.batch_no || '—') + '</span></td>' +
        '<td data-label="Muddati"><span class="' + cls + '">' + fmtDate(exp) + '</span>' +
          (exp && b.is_expired && Number(b.remaining_qty) > 0 ? ' ' + badge('expired', "o'tgan") : '') + '</td>' +
        '<td data-label="Qoldiq" class="wh-right wh-num"><b>' + fmtQty(b.remaining_qty) + '</b> ' + esc(unit) + '</td>' +
        '<td data-label="Qabul qilingan" class="wh-right wh-num">' + fmtQty(b.received_qty) + '</td>' +
        (costs && b.unit_cost !== undefined ? '<td data-label="Tannarx" class="wh-right wh-num">' + fmtMoney(b.unit_cost, true) + '</td>' : '') +
        '<td data-label="Manba">' + esc(SOURCE_LABEL[b.source] || b.source || '—') + '</td>' +
        '<td data-label="Sana">' + fmtDate(b.received_at) + '</td></tr>';
    }).join('');
    const showCost = costs && batches.length && batches[0].unit_cost !== undefined;
    const bTable = batches.length
      ? '<div class="wh-table-wrap"><table class="wh-table wh-stack wh-compact"><thead><tr><th>Partiya</th><th>Muddati</th><th class="wh-right">Qoldiq</th><th class="wh-right">Qabul qilingan</th>' +
        (showCost ? '<th class="wh-right">Tannarx</th>' : '') + '<th>Manba</th><th>Sana</th></tr></thead><tbody>' + bRows + '</tbody></table></div>'
      : '<p class="wh-hint">Partiya yo\'q: bu mahsulot hali omborga qabul qilinmagan.</p>';

    const ledger = it.ledger || [];
    const lRows = ledger.map((t) =>
      '<tr><td data-label="Vaqt" class="wh-nowrap">' + fmtDateTime(t.created_at) + '</td>' +
      '<td data-label="Tur">' + esc(TXN_LABEL[t.txn_type] || t.txn_type) + '</td>' +
      '<td data-label="O\'zgarish" class="wh-right wh-num"><span class="' + (Number(t.qty_delta) >= 0 ? 'wh-qty-in' : 'wh-qty-out') + '">' + (Number(t.qty_delta) > 0 ? '+' : '') + fmtQty(t.qty_delta) + '</span></td>' +
      '<td data-label="Qoldiq" class="wh-right wh-num">' + fmtQty(t.balance_after) + '</td>' +
      '<td data-label="Sabab / xodim">' + esc(t.reason || '') + '<span class="wh-cell-sub">' + esc(t.performed_by || '') + '</span></td></tr>').join('');
    const lTable = ledger.length
      ? '<div class="wh-table-wrap"><table class="wh-table wh-stack wh-compact"><thead><tr><th>Vaqt</th><th>Tur</th><th class="wh-right">O\'zgarish</th><th class="wh-right">Qoldiq</th><th>Sabab / xodim</th></tr></thead><tbody>' + lRows + '</tbody></table></div>'
      : '<p class="wh-hint">Harakat yo\'q.</p>';

    layer.setBody(detail +
      '<div class="wh-block"><h3 class="wh-block-title"><i class="fas fa-layer-group" aria-hidden="true"></i> Partiyalar</h3>' + bTable + '</div>' +
      '<div class="wh-block"><h3 class="wh-block-title"><i class="fas fa-clock-rotate-left" aria-hidden="true"></i> Oxirgi harakatlar</h3>' + lTable + '</div>');

    const id = esc(it.id);
    let foot = '<div class="wh-foot-left">';
    if (S.whWrite) foot += '<button type="button" class="wh-btn ' + (it.is_active ? 'wh-btn-danger' : 'wh-btn-success') + '" data-action="item-toggle" data-id="' + id + '">' +
      '<i class="fas ' + (it.is_active ? 'fa-ban' : 'fa-rotate-left') + '" aria-hidden="true"></i> ' + (it.is_active ? 'Faolsizlantirish' : 'Faollashtirish') + '</button>';
    foot += '<button type="button" class="wh-btn" data-action="item-ledger" data-id="' + id + '"><i class="fas fa-clock-rotate-left" aria-hidden="true"></i> Harakatlar</button></div>';
    if (S.accWrite) foot += '<button type="button" class="wh-btn" data-action="item-threshold" data-id="' + id + '"><i class="fas fa-bell" aria-hidden="true"></i> Minimal qoldiq</button>';
    if (S.whWrite) foot += '<button type="button" class="wh-btn" data-action="item-adjust" data-id="' + id + '"><i class="fas fa-sliders" aria-hidden="true"></i> Tuzatish</button>' +
      '<button type="button" class="wh-btn wh-btn-primary" data-action="item-edit" data-id="' + id + '"><i class="fas fa-pen" aria-hidden="true"></i> Tahrirlash</button>';
    layer.setFoot(foot);
  }

  ACTIONS['open-item'] = (t) => openItem(t.dataset.id);
  ACTIONS['item-reload'] = () => { const l = itemDrawer(); if (l) paintItem(l); };
  ACTIONS['item-ledger'] = (t) => {
    const it = ITEMS[t.dataset.id];
    if (!it) return;
    while (layers.length) layers[layers.length - 1].close();
    LED.item_id = it.id; LED.itemLabel = it.name; LED.offset = 0; LED.type = '';
    S.stale.ledger = true;
    switchTab('ledger');
  };
  ACTIONS['item-edit'] = (t) => { const it = ITEMS[t.dataset.id]; if (it) openItemForm(it); };
  ACTIONS['item-threshold'] = (t) => { const it = ITEMS[t.dataset.id]; if (it) openThreshold(it); };
  ACTIONS['item-adjust'] = (t) => { const it = ITEMS[t.dataset.id]; if (it) openAdjustment(it); };
  ACTIONS['item-new'] = () => openItemForm(null);
  ACTIONS['item-toggle'] = async (t) => {
    const it = ITEMS[t.dataset.id];
    if (!it) return;
    const activate = !it.is_active;
    const ok = await confirmBox({
      title: activate ? 'Mahsulotni faollashtirish' : 'Mahsulotni faolsizlantirish',
      message: '<b>' + esc(it.name) + '</b> ' + (activate ? 'yana kirim va berishga ochiladi.' : 'yangi kirim va berishdan yopiladi. Qoldiq va tarix saqlanadi.'),
      confirmText: activate ? 'Faollashtirish' : 'Faolsizlantirish', type: activate ? 'primary' : 'warning'
    });
    if (!ok) return;
    await runBusy(t, async () => {
      const r = await api('POST', '/items/' + encodeURIComponent(it.id) + '/' + (activate ? 'activate' : 'deactivate'), {});
      if (!r.ok) { toast(r.data.error, 'error'); return; }
      toast(activate ? 'Mahsulot faollashtirildi.' : 'Mahsulot faolsizlantirildi.');
      invalidate();
      const l = itemDrawer();
      if (l) paintItem(l);
      refreshCurrentTab();
    });
  };

  // ---------------------------------------------------------------------------
  // Threshold (accounting only)
  // ---------------------------------------------------------------------------
  function numCheck(s, places) {
    s = canonicalNumber(s);
    if (!/^\d+(\.\d+)?$/.test(s)) return null;
    const frac = s.split('.')[1] || '';
    if (frac.length > places && /[1-9]/.test(frac.slice(places))) return null;
    return Number(s);
  }

  function openThreshold(it) {
    const layer = openLayer({
      title: 'Minimal qoldiq', subtitle: it.name, narrow: true, dismissOnBg: false,
      html: '<form novalidate>' +
        '<label class="wh-field"><span class="wh-label">Minimal qoldiq (' + esc(it.base_unit) + ') <span class="wh-req">*</span></span>' +
        '<input class="wh-input" name="min_stock_level" inputmode="decimal" value="' + esc(it.min_stock_level) + '">' +
        '<span class="wh-hint">Qoldiq shundan <b>kam</b> bo\'lsa, "kam qoldiq" ogohlantirishi chiqadi. Standart: ' + esc(S.settings.default_min_stock) + '.</span></label></form>',
      footer: '<button type="button" class="wh-btn" data-layer-close>Bekor qilish</button><button type="button" class="wh-btn wh-btn-primary" data-save>Saqlash</button>'
    });
    const form = $('form', layer.body);
    async function save(btn) {
      clearFormError(form);
      const v = $('[name="min_stock_level"]', form).value;
      if (numCheck(v, 3) === null) { fieldError(form, { field: 'min_stock_level', error: "Minimal qoldiq 0 yoki undan katta raqam bo'lishi kerak (ko'pi bilan 3 ta kasr)." }); return; }
      await runBusy(btn, async () => {
        const r = await api('PUT', '/items/' + encodeURIComponent(it.id) + '/threshold', { min_stock_level: canonicalNumber(v) });
        if (!r.ok) { fieldError(form, r.data); return; }
        toast('Minimal qoldiq saqlandi.');
        layer.close();
        invalidate();
        const l = itemDrawer();
        if (l) paintItem(l);
        refreshCurrentTab();
      });
    }
    $('[data-save]', layer.foot).addEventListener('click', (e) => save(e.currentTarget));
    form.addEventListener('submit', (e) => { e.preventDefault(); save($('[data-save]', layer.foot)); });
  }

  // ===========================================================================
  // ITEM FORM (create / edit). Also used for the "new item" block of a receipt line.
  // ===========================================================================
  function field(label, control, o) {
    o = o || {};
    return '<label class="wh-field' + (o.span ? ' wh-span-' + o.span : '') + (o.cls ? ' ' + o.cls : '') + '"' + (o.hidden ? ' hidden' : '') + '>' +
      '<span class="wh-label">' + label + (o.req ? ' <span class="wh-req">*</span>' : '') + '</span>' + control +
      (o.hint ? '<span class="wh-hint">' + o.hint + '</span>' : '') + '</label>';
  }
  function textInput(name, value, extra) {
    return '<input class="wh-input" name="' + name + '" value="' + esc(value == null ? '' : value) + '" autocomplete="off" ' + (extra || '') + '>';
  }

  /** Fields of an item. v = current values; ctx = {edit, moved, cost, compact}. */
  function itemFieldsHtml(v, ctx) {
    v = v || {};
    ctx = ctx || {};
    const type = v.item_type || 'medicine';
    const pharma = PHARMA_TYPES.indexOf(type) >= 0;
    const hasPkg = !!v.package_unit;
    let h = '<div class="wh-form-grid">';
    h += '<div class="wh-section-label">Asosiy ma\'lumot</div>';
    h += field('Nomi', textInput('name', v.name, 'maxlength="255"'), { req: true, span: 2 });
    h += field('Turi', '<select class="wh-select" name="item_type">' + typeList().map((t) =>
      '<option value="' + esc(t.id) + '"' + (t.id === type ? ' selected' : '') + '>' + esc(t.label) + '</option>').join('') + '</select>', { req: true });
    h += field('Kategoriya', textInput('category', v.category, 'maxlength="128" list="wh-categories"'), { hint: 'Bo\'sh qoldirilsa, tur nomi yoziladi' });
    h += field('Xalqaro nomi (generik)', textInput('generic_name', v.generic_name, 'maxlength="255"'), { cls: 'js-pharma', hidden: !pharma });
    h += field('Dozasi', textInput('strength', v.strength, 'maxlength="64" placeholder="Masalan: 500 mg"'), { cls: 'js-pharma', hidden: !pharma });
    h += field('Shakli', textInput('form', v.form, 'maxlength="64" placeholder="tabletka, ampula, sirop…"'), { cls: 'js-pharma', hidden: !pharma });
    if (!ctx.compact) {
      h += field('Standart doza', textInput('standard_dosage', v.standard_dosage, 'maxlength="128"'), { cls: 'js-pharma', hidden: !pharma });
      h += field('Ishlab chiqaruvchi', textInput('manufacturer', v.manufacturer, 'maxlength="255"'));
    }

    h += '<div class="wh-section-label">Birlik va qadoq</div>';
    h += field('Hisob birligi', '<select class="wh-select" name="base_unit"' + (ctx.moved ? ' disabled' : '') + '>' + unitOptions(v.base_unit || 'dona') + '</select>',
      { req: true, hint: ctx.moved ? 'Harakatlar bo\'lgan mahsulotning birligi o\'zgarmaydi.' : 'Eng kichik birlik: tabletka, ml, dona…' });
    h += field('Qadoq birligi', '<select class="wh-select" name="package_unit">' + unitOptions(v.package_unit || '', 'Qadoqsiz') + '</select>');
    h += field('Qadoqda nechta?', '<input class="wh-input" name="units_per_package" inputmode="decimal" value="' + esc(v.units_per_package == null ? '1' : v.units_per_package) + '" autocomplete="off">',
      { cls: 'js-upp', hidden: !hasPkg, req: true });
    h += '<div class="wh-field wh-span-all"><span class="wh-hint is-ok" data-unit-hint></span></div>';
    h += '<div class="wh-field"><label class="wh-check"><input type="checkbox" name="allow_fraction"' + (v.allow_fraction ? ' checked' : '') + '> Kasr miqdor mumkin (ml, g…)</label></div>';
    h += '<div class="wh-field"><label class="wh-check"><input type="checkbox" name="track_expiry"' + (v.track_expiry ? ' checked' : '') + '> Yaroqlilik muddati hisobga olinadi</label></div>';

    if (!ctx.compact) {
      h += '<div class="wh-section-label">Qo\'shimcha</div>';
      h += field('Artikul (SKU)', textInput('sku', v.sku, 'maxlength="64"'));
      h += field('Shtrix-kod', textInput('barcode', v.barcode, 'maxlength="64"'));
      h += field('Yetkazib beruvchi', '<select class="wh-select" name="supplier_id">' + supplierOptions(v.supplier_id, 'Tanlanmagan') + '</select>');
      h += field('Izoh', '<textarea class="wh-textarea" name="description" maxlength="2000" rows="2">' + esc(v.description || '') + '</textarea>', { span: 'all' });
    }
    if (ctx.cost) {
      h += '<div class="wh-section-label">Buxgalteriya</div>';
      h += field('Minimal qoldiq', '<input class="wh-input" name="min_stock_level" inputmode="decimal" value="' + esc(v.min_stock_level == null ? '' : v.min_stock_level) + '" autocomplete="off">',
        { hint: 'Qoldiq shundan kam bo\'lsa ogohlantiriladi. Bo\'sh = standart (' + esc(S.settings.default_min_stock) + ').' });
      h += field('Bemor narxi (1 hisob birligi)', '<input class="wh-input" name="unit_price" inputmode="decimal" value="' + esc(v.unit_price == null ? '' : v.unit_price) + '" autocomplete="off">',
        { hint: 'Bemorga hisob-kitobda yoziladigan narx. Xarid narxi emas.' });
    }
    return h + '</div>';
  }

  function updateUnitHint(root) {
    const hint = $('[data-unit-hint]', root);
    if (!hint) return;
    const base = ($('[name="base_unit"]', root) || {}).value || '';
    const pu = ($('[name="package_unit"]', root) || {}).value || '';
    const uppEl = $('[name="units_per_package"]', root);
    const frac = ($('[name="allow_fraction"]', root) || {}).checked;
    const uppField = $('.js-upp', root);
    if (uppField) uppField.hidden = !pu;
    hint.classList.remove('is-ok');
    hint.style.color = '';
    if (!pu) { hint.textContent = 'Qadoq ishlatilmaydi: qoldiq va kirim «' + base + '» hisobida yuritiladi.'; return; }
    const n = numCheck(uppEl ? uppEl.value : '1', 3);
    if (n === null || n <= 0) { hint.textContent = 'Qadoqda nechta ' + base + ' borligini yozing.'; hint.style.color = 'var(--warning-text)'; return; }
    if (!frac && !Number.isInteger(n)) { hint.textContent = 'Kasr miqdorga ruxsat berilmagan: qadoqdagi miqdor butun son bo\'lishi kerak.'; hint.style.color = 'var(--danger-text)'; return; }
    hint.classList.add('is-ok');
    hint.textContent = '1 ' + pu + ' = ' + NF_QTY.format(n) + ' ' + base;
  }

  function bindItemFields(root, o) {
    o = o || {};
    const typeSel = $('[name="item_type"]', root);
    const track = $('[name="track_expiry"]', root);
    if (track) track.addEventListener('change', () => { track.dataset.touched = '1'; });
    function applyType() {
      const pharma = PHARMA_TYPES.indexOf(typeSel.value) >= 0;
      $$('.js-pharma', root).forEach((n) => { n.hidden = !pharma; });
      // New medicines default to tracking expiry; a person's own choice is kept.
      if (o.creating && track && !track.dataset.touched) track.checked = pharma;
    }
    if (typeSel) typeSel.addEventListener('change', applyType);
    ['base_unit', 'package_unit', 'units_per_package', 'allow_fraction'].forEach((n) => {
      const el = $('[name="' + n + '"]', root);
      if (el) { el.addEventListener('input', () => updateUnitHint(root)); el.addEventListener('change', () => updateUnitHint(root)); }
    });
    updateUnitHint(root);
  }

  /** -> {data, threshold} or {error: {field, error}} */
  function readItemFields(root, o) {
    o = o || {};
    const el = (n) => root.querySelector('[name="' + n + '"]');
    const str = (n) => { const e = el(n); return e && !e.disabled ? e.value.trim() : null; };
    const chk = (n) => { const e = el(n); return e ? (e.checked ? 1 : 0) : 0; };
    const bad = (field, error) => ({ error: { field: field, error: error } });
    const d = {};
    const name = str('name');
    if (!name) return bad('name', "Nomi ko'rsatilishi shart.");
    d.name = name;
    d.item_type = str('item_type');
    const pharma = PHARMA_TYPES.indexOf(d.item_type) >= 0;
    const baseEl = el('base_unit');
    if (baseEl && !baseEl.disabled) d.base_unit = baseEl.value;
    const pu = str('package_unit') || '';
    d.package_unit = pu;
    let upp = '1';
    if (pu) {
      upp = canonicalNumber(str('units_per_package'));
      const n = numCheck(upp, 3);
      if (n === null || n <= 0) return bad('units_per_package', "Qadoqdagi miqdor noldan katta raqam bo'lishi kerak (ko'pi bilan 3 ta kasr).");
      if (!chk('allow_fraction') && !Number.isInteger(n)) return bad('units_per_package', "Kasr miqdorga ruxsat berilmagan mahsulotda qadoqdagi miqdor butun son bo'lishi kerak.");
    }
    d.units_per_package = upp;
    d.allow_fraction = chk('allow_fraction');
    d.track_expiry = chk('track_expiry');
    const textFields = ['category', 'manufacturer', 'sku', 'barcode', 'description', 'supplier_id'];
    if (pharma) textFields.push('generic_name', 'strength', 'form', 'standard_dosage');
    textFields.forEach((n) => {
      const v = str(n);
      if (v === null) return;
      if (v === '' && !o.edit) return;       // a new item: blank means "not given"
      d[n] = v;
    });
    let threshold = null;
    const thr = str('min_stock_level');
    if (thr) {
      if (numCheck(thr, 3) === null) return bad('min_stock_level', "Minimal qoldiq 0 yoki undan katta raqam bo'lishi kerak.");
      threshold = canonicalNumber(thr);
    }
    const price = str('unit_price');
    if (price) {
      if (numCheck(price, 2) === null) return bad('unit_price', "Bemor narxi 0 yoki undan katta raqam bo'lishi kerak (ko'pi bilan 2 ta kasr).");
      d.unit_price = canonicalNumber(price);
    }
    if (!o.edit && threshold !== null) d.min_stock_level = threshold;
    return { data: d, threshold: o.edit ? threshold : null };
  }

  function openItemForm(item) {
    const edit = !!item;
    const moved = edit && !!(item.ledger && item.ledger.length);
    const layer = openLayer({
      title: edit ? 'Mahsulotni tahrirlash' : 'Yangi mahsulot', subtitle: edit ? item.name : 'Omborga yangi nom qo\'shish', wide: true, dismissOnBg: false,
      html: '<form novalidate data-item-form>' + itemFieldsHtml(edit ? item : { item_type: 'medicine', base_unit: 'dona', track_expiry: 1 }, { edit: edit, moved: moved, cost: S.accWrite }) + '</form>',
      footer: '<button type="button" class="wh-btn" data-layer-close>Bekor qilish</button>' +
        '<button type="button" class="wh-btn wh-btn-primary" data-save><i class="fas fa-floppy-disk" aria-hidden="true"></i> Saqlash</button>'
    });
    const form = $('form', layer.body);
    bindItemFields(form, { creating: !edit });
    async function save(btn) {
      clearFormError(form);
      const read = readItemFields(form, { edit: edit });
      if (read.error) { fieldError(form, read.error); return; }
      await runBusy(btn, async () => {
        const r = edit
          ? await api('PUT', '/items/' + encodeURIComponent(item.id), read.data)
          : await api('POST', '/items', read.data);
        if (!r.ok) { fieldError(form, r.data); return; }
        const saved = r.data;
        let thresholdFailed = '';
        if (edit && S.accWrite && read.threshold !== null && numCheck(read.threshold, 3) !== Number(item.min_stock_level)) {
          const t = await api('PUT', '/items/' + encodeURIComponent(item.id) + '/threshold', { min_stock_level: read.threshold });
          if (!t.ok) thresholdFailed = t.data.error;
        }
        layer.close();
        invalidate();
        rememberCategories([saved]);
        if (thresholdFailed) toast('Mahsulot saqlandi, lekin minimal qoldiq o\'zgarmadi: ' + thresholdFailed, 'warning');
        else toast(edit ? 'Mahsulot saqlandi.' : 'Mahsulot qo\'shildi.');
        const l = itemDrawer();
        if (edit && l) paintItem(l);
        if (!edit) openItem(saved.id);
        refreshCurrentTab();
      });
    }
    $('[data-save]', layer.foot).addEventListener('click', (e) => save(e.currentTarget));
    form.addEventListener('submit', (e) => { e.preventDefault(); save($('[data-save]', layer.foot)); });
  }

  // ===========================================================================
  // RECEIPTS (Kirim)
  // ===========================================================================
  const RC = { f: { from: '', to: '', supplier_id: '', status: '' }, offset: 0, limit: 25, total: 0, rows: [], seq: 0, shell: false, form: null };

  function ensureRcShell() {
    if (RC.shell) return;
    const panel = $('#panel-receipts');
    panel.innerHTML =
      '<div id="rc-list-view"><div class="wh-card">' +
        '<div class="wh-toolbar">' +
          '<label class="wh-field"><span class="wh-label">Sanadan</span><input class="wh-input" type="date" id="rc-from"></label>' +
          '<label class="wh-field"><span class="wh-label">Sanagacha</span><input class="wh-input" type="date" id="rc-to"></label>' +
          '<label class="wh-field"><span class="wh-label">Yetkazib beruvchi</span><select class="wh-select" id="rc-supplier"><option value="">Barchasi</option></select></label>' +
          '<label class="wh-field"><span class="wh-label">Holat</span><select class="wh-select" id="rc-status"><option value="">Barcha holatlar</option>' +
            Object.keys(RECEIPT_STATUS).map((k) => '<option value="' + k + '">' + esc(RECEIPT_STATUS[k]) + '</option>').join('') + '</select></label>' +
          '<div class="wh-toolbar-end">' +
            '<button type="button" class="wh-btn" data-action="rc-reset"><i class="fas fa-filter-circle-xmark" aria-hidden="true"></i> Tozalash</button>' +
            (S.accWrite ? '<button type="button" class="wh-btn wh-btn-primary" data-action="rc-new"><i class="fas fa-plus" aria-hidden="true"></i> Yangi kirim</button>' : '') +
          '</div>' +
        '</div>' +
        (!S.accWrite ? '<div class="wh-card-body" style="padding-bottom:0"><div class="wh-note">Kirim hujjatini faqat buxgalter (kassir) kiritadi. Siz hujjatlarni ko\'ra olasiz.</div></div>' : '') +
        '<div id="rc-body"></div><div id="rc-pager"></div>' +
      '</div></div>' +
      '<div id="rc-edit-view" hidden></div>';
    RC.shell = true;
    const reload = () => { RC.offset = 0; loadReceipts(); };
    [['rc-from', 'from'], ['rc-to', 'to'], ['rc-supplier', 'supplier_id'], ['rc-status', 'status']].forEach((p) =>
      $('#' + p[0]).addEventListener('change', (e) => { RC.f[p[1]] = e.target.value; reload(); }));
    loadSuppliers().then(() => { const s = $('#rc-supplier'); if (s) s.innerHTML = supplierOptions(RC.f.supplier_id, 'Barchasi'); });
  }

  async function loadReceipts() {
    ensureRcShell();
    const mine = ++RC.seq;
    const body = $('#rc-body');
    if (!S.loaded.receipts || !RC.rows.length) body.innerHTML = loadingHtml(5);
    const r = await api('GET', '/receipts' + qs({ from: RC.f.from, to: RC.f.to, supplier_id: RC.f.supplier_id, status: RC.f.status, limit: RC.limit, offset: RC.offset }));
    if (mine !== RC.seq) return;
    S.stale.receipts = false;
    if (!r.ok) { S.loaded.receipts = false; body.innerHTML = errorHtml(r.data.error, 'rc-retry'); $('#rc-pager').innerHTML = ''; return; }
    S.loaded.receipts = true;
    RC.rows = r.data.receipts || [];
    RC.total = r.data.total || 0;
    if (!RC.rows.length && RC.total > 0 && RC.offset > 0) { RC.offset = 0; loadReceipts(); return; }
    renderReceiptList();
  }

  function renderReceiptList() {
    const body = $('#rc-body');
    if (!RC.rows.length) {
      const filtered = RC.f.from || RC.f.to || RC.f.supplier_id || RC.f.status;
      body.innerHTML = emptyHtml('fa-truck-ramp-box', filtered ? 'Hujjat topilmadi' : 'Kirim hujjati yo\'q',
        filtered ? 'Tanlangan filtrlarga mos hujjat yo\'q.' : 'Yangi kirim hujjati yaratilganda shu yerda ko\'rinadi.',
        filtered ? '<button type="button" class="wh-btn" data-action="rc-reset">Filtrlarni tozalash</button>' : '');
      $('#rc-pager').innerHTML = '';
      return;
    }
    const costs = RC.rows[0].total_amount !== undefined;
    body.innerHTML = '<div class="wh-table-wrap"><table class="wh-table wh-stack"><thead><tr><th>Hujjat</th><th>Sana</th><th>Yetkazib beruvchi</th><th>Hisob-faktura</th><th>Holat</th><th class="wh-right">Qatorlar</th>' +
      (costs ? '<th class="wh-right">Summa</th>' : '') + '</tr></thead><tbody>' +
      RC.rows.map((r) =>
        '<tr class="wh-row-click" tabindex="0" data-action="open-receipt" data-id="' + esc(r.id) + '">' +
        '<td data-label="Hujjat"><span class="wh-mono">' + esc(r.id) + '</span></td>' +
        '<td data-label="Sana">' + fmtDate(r.receipt_date) + '</td>' +
        '<td data-label="Yetkazib beruvchi">' + esc(r.supplier_name || '—') + '</td>' +
        '<td data-label="Hisob-faktura">' + esc(r.invoice_number || '—') + '</td>' +
        '<td data-label="Holat">' + badge(r.status, RECEIPT_STATUS[r.status] || r.status) + '</td>' +
        '<td data-label="Qatorlar" class="wh-right wh-num">' + esc(r.line_count) + '</td>' +
        (costs ? '<td data-label="Summa" class="wh-right wh-num"><b>' + fmtMoney(r.total_amount) + '</b></td>' : '') + '</tr>').join('') +
      '</tbody></table></div>';
    $('#rc-pager').innerHTML = pagerHtml({ offset: RC.offset, limit: RC.limit, total: RC.total }, 'rc-page');
  }

  ACTIONS['rc-retry'] = () => loadReceipts();
  ACTIONS['rc-reset'] = () => {
    RC.f = { from: '', to: '', supplier_id: '', status: '' }; RC.offset = 0;
    ['rc-from', 'rc-to', 'rc-supplier', 'rc-status'].forEach((id) => { const e = $('#' + id); if (e) e.value = ''; });
    loadReceipts();
  };
  ACTIONS['rc-page'] = (t) => { RC.offset = Math.max(0, RC.offset + Number(t.dataset.dir) * RC.limit); loadReceipts(); };

  // --- Receipt detail ------------------------------------------------------------
  async function openReceipt(id) {
    const layer = openLayer({ title: 'Kirim hujjati', subtitle: id, wide: true, html: loadingHtml(6) });
    layer.receiptId = id;
    await paintReceipt(layer);
  }
  function receiptLayer() {
    for (let i = layers.length - 1; i >= 0; i--) if (layers[i].receiptId) return layers[i];
    return null;
  }

  async function paintReceipt(layer) {
    const r = await api('GET', '/receipts/' + encodeURIComponent(layer.receiptId));
    if (layer.closed) return;
    if (!r.ok) { layer.setBody(errorHtml(r.data.error, 'receipt-reload')); layer.setFoot(''); return; }
    const rec = r.data;
    layer.receipt = rec;
    const costs = rec.total_amount !== undefined;
    layer.setTitle('Kirim hujjati ' + rec.id, (rec.supplier_name || 'Yetkazib beruvchi ko\'rsatilmagan') + ' · ' + String(rec.receipt_date || '').slice(0, 10));
    const lines = rec.lines || [];
    const lineCost = costs && lines.length && lines[0].package_price !== undefined;
    const rows = lines.map((l) =>
      '<tr><td data-label="№" class="wh-num">' + esc(l.line_no) + '</td>' +
      '<td data-label="Mahsulot"><span class="wh-cell-name">' + esc(l.item_name) + '</span>' +
        '<span class="wh-cell-sub">Partiya: ' + esc(l.batch_no || '—') + '</span></td>' +
      '<td data-label="Qadoq" class="wh-right wh-num">' + fmtQty(l.packages) + ' × ' + fmtQty(l.units_per_package) + '</td>' +
      '<td data-label="Jami miqdor" class="wh-right wh-num"><b>' + fmtQty(l.quantity_base) + '</b></td>' +
      (lineCost ? '<td data-label="Qadoq narxi" class="wh-right wh-num">' + fmtMoney(l.package_price) + '</td>' +
        '<td data-label="Birlik narxi" class="wh-right wh-num">' + fmtMoney(l.unit_cost, true) + '</td>' +
        '<td data-label="Summa" class="wh-right wh-num"><b>' + fmtMoney(l.line_total) + '</b></td>' : '') +
      '<td data-label="Muddati">' + fmtDate(l.expiry_date) + '</td></tr>').join('');
    layer.setBody(
      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">' + badge(rec.status, RECEIPT_STATUS[rec.status] || rec.status) + '</div>' +
      '<dl class="wh-dl">' +
        dlRow('Sana', fmtDate(rec.receipt_date)) +
        dlRow('Yetkazib beruvchi', esc(rec.supplier_name || '—')) +
        dlRow('Hisob-faktura', esc(rec.invoice_number || '—')) +
        (costs ? dlRow('To\'lov usuli', esc(PAYMENT_LABEL[rec.payment_method] || rec.payment_method || '—')) +
          dlRow('Jami summa', '<b>' + fmtMoney(rec.total_amount) + '</b>') +
          dlRow('Kassa yozuvi', esc(rec.accounting_transaction_ref || '—')) : '') +
        dlRow('Yaratgan', esc(rec.created_by || '—') + '<br><span class="wh-dim">' + fmtDateTime(rec.created_at) + '</span>') +
        (rec.posted_at ? dlRow('Tasdiqlagan', esc(rec.posted_by || '—') + '<br><span class="wh-dim">' + fmtDateTime(rec.posted_at) + '</span>') : '') +
        (rec.reversed_at ? dlRow('Qaytargan', esc(rec.reversed_by || '—') + '<br><span class="wh-dim">' + fmtDateTime(rec.reversed_at) + '</span>') : '') +
      '</dl>' +
      (rec.reverse_reason ? '<div class="wh-note" style="margin-top:12px"><b>Qaytarish sababi:</b> ' + esc(rec.reverse_reason) + '</div>' : '') +
      (rec.notes ? '<p class="wh-hint" style="margin-top:12px"><b>Izoh:</b> ' + esc(rec.notes) + '</p>' : '') +
      (rec.status === 'draft' ? '<div class="wh-note is-warn" style="margin-top:12px">Qoralama: mahsulotlar hali omborga qabul qilinmagan va kassada xarajat yozilmagan.</div>' : '') +
      '<div class="wh-block"><h3 class="wh-block-title"><i class="fas fa-list" aria-hidden="true"></i> Qatorlar (' + lines.length + ')</h3>' +
      '<div class="wh-table-wrap"><table class="wh-table wh-stack wh-compact"><thead><tr><th>№</th><th>Mahsulot</th><th class="wh-right">Qadoq × birlik</th><th class="wh-right">Jami miqdor</th>' +
        (lineCost ? '<th class="wh-right">Qadoq narxi</th><th class="wh-right">Birlik narxi</th><th class="wh-right">Summa</th>' : '') + '<th>Muddati</th></tr></thead><tbody>' + rows + '</tbody></table></div></div>');
    let foot = '';
    const id = esc(rec.id);
    if (S.accWrite && rec.status === 'draft') {
      foot = '<div class="wh-foot-left"><button type="button" class="wh-btn wh-btn-danger" data-action="receipt-cancel" data-id="' + id + '"><i class="fas fa-ban" aria-hidden="true"></i> Qoralamani bekor qilish</button></div>' +
        '<button type="button" class="wh-btn wh-btn-primary" data-action="receipt-post" data-id="' + id + '"><i class="fas fa-circle-check" aria-hidden="true"></i> Tasdiqlash va omborga qabul qilish</button>';
    } else if (S.accWrite && rec.status === 'posted') {
      foot = '<div class="wh-foot-left"><button type="button" class="wh-btn wh-btn-danger" data-action="receipt-reverse" data-id="' + id + '"><i class="fas fa-rotate-left" aria-hidden="true"></i> Kirimni qaytarish</button></div>';
    }
    layer.setFoot(foot);
  }

  function afterReceiptChange() {
    invalidate();
    const l = receiptLayer();
    if (l) paintReceipt(l);
    refreshCurrentTab();
  }

  ACTIONS['open-receipt'] = (t) => openReceipt(t.dataset.id);
  ACTIONS['receipt-reload'] = () => { const l = receiptLayer(); if (l) paintReceipt(l); };
  ACTIONS['receipt-post'] = async (t) => {
    const l = receiptLayer();
    const rec = l && l.receipt;
    if (!rec) return;
    const ok = await confirmBox({
      title: 'Kirimni tasdiqlash',
      message: '<b>' + esc(rec.id) + '</b>: ' + (rec.lines || []).length + ' qator' + (rec.total_amount !== undefined ? ', jami <b>' + fmtMoney(rec.total_amount) + '</b>' : '') +
        '.<br>Mahsulotlar omborga qabul qilinadi va kassada xarajat yoziladi. Buni keyin faqat "qaytarish" bilan bekor qilish mumkin.',
      confirmText: 'Tasdiqlash va qabul qilish', type: 'primary'
    });
    if (!ok) return;
    await runBusy(t, async () => {
      const r = await api('POST', '/receipts/' + encodeURIComponent(rec.id) + '/post', {});
      if (!r.ok) { toast(r.data.error, 'error'); return; }
      toast('Kirim tasdiqlandi: mahsulotlar omborga qabul qilindi.');
      afterReceiptChange();
    });
  };
  ACTIONS['receipt-cancel'] = async (t) => {
    const l = receiptLayer();
    const rec = l && l.receipt;
    if (!rec) return;
    const ok = await confirmBox({ title: 'Qoralamani bekor qilish', message: '<b>' + esc(rec.id) + '</b> qoralamasi bekor qilinadi. Ombor qoldig\'iga ta\'sir qilmaydi.', confirmText: 'Bekor qilish', type: 'danger' });
    if (!ok) return;
    await runBusy(t, async () => {
      const r = await api('POST', '/receipts/' + encodeURIComponent(rec.id) + '/cancel', {});
      if (!r.ok) { toast(r.data.error, 'error'); return; }
      toast('Qoralama bekor qilindi.');
      afterReceiptChange();
    });
  };
  ACTIONS['receipt-reverse'] = async (t) => {
    const l = receiptLayer();
    const rec = l && l.receipt;
    if (!rec) return;
    const reason = await askReason({
      title: 'Kirimni qaytarish', subtitle: rec.id,
      message: 'Qabul qilingan mahsulot ombordan olinadi, kassa xarajati bekor qilinadi. Mahsulotning bir qismi ishlatilgan bo\'lsa, qaytarib bo\'lmaydi.',
      confirmText: 'Qaytarish'
    });
    if (!reason) return;
    await runBusy(t, async () => {
      const r = await api('POST', '/receipts/' + encodeURIComponent(rec.id) + '/reverse', { reason: reason });
      if (!r.ok) { toast(r.data.error, 'error'); return; }
      toast('Kirim qaytarildi.');
      afterReceiptChange();
    });
  };

  // --- Receipt editor --------------------------------------------------------------
  let lineSeq = 0;
  function newLine() {
    return { key: ++lineSeq, mode: 'existing', item: null, ni: null, packages: '', price: '', batch: '', expiry: '' };
  }
  function newReceiptState() {
    return { requestId: newRequestId(), supplierId: '', newSupplier: false, supplierName: '', invoice: '', date: todayISO(), method: 'cash', notes: '', lines: [newLine()], submitting: false };
  }

  function showReceiptView(which) {
    $('#rc-list-view').hidden = which !== 'list';
    $('#rc-edit-view').hidden = which !== 'edit';
    if (which === 'edit') window.scrollTo({ top: 0 });
  }

  async function openReceiptForm() {
    ensureRcShell();
    if (!S.accWrite) return;
    if (!HAS_BIGINT) { toast('Brauzeringiz juda eski: kirim hujjatini kiritish uchun yangilang.', 'error'); return; }
    await loadSuppliers();
    RC.form = newReceiptState();
    renderReceiptForm();
    showReceiptView('edit');
  }

  function renderReceiptForm() {
    const F = RC.form;
    const host = $('#rc-edit-view');
    host.innerHTML =
      '<div class="wh-card"><div class="wh-card-head"><h2 class="wh-card-title"><i class="fas fa-file-circle-plus" aria-hidden="true"></i> Yangi kirim hujjati</h2>' +
        '<button type="button" class="wh-btn wh-btn-sm" data-action="rc-back"><i class="fas fa-arrow-left" aria-hidden="true"></i> Ro\'yxatga qaytish</button></div>' +
        '<div class="wh-card-body"><form novalidate id="rc-head" data-rc-head><div class="wh-form-grid">' +
          field('Yetkazib beruvchi', '<select class="wh-select" name="supplier">' + supplierOptions(F.newSupplier ? '__new__' : F.supplierId, 'Tanlanmagan') +
            '<option value="__new__"' + (F.newSupplier ? ' selected' : '') + '>＋ Yangi yetkazib beruvchi…</option></select>') +
          field('Yangi yetkazib beruvchi nomi', textInput('supplier_name', F.supplierName, 'maxlength="255"'), { cls: 'js-newsup', hidden: !F.newSupplier }) +
          field('Hisob-faktura raqami', textInput('invoice_number', F.invoice, 'maxlength="128"')) +
          field('Kirim sanasi', '<input class="wh-input" type="date" name="receipt_date" value="' + esc(F.date) + '" max="' + todayISO() + '">', { req: true }) +
          field("To'lov usuli", '<select class="wh-select" name="payment_method">' + Object.keys(PAYMENT_LABEL).map((k) =>
            '<option value="' + k + '"' + (k === F.method ? ' selected' : '') + '>' + esc(PAYMENT_LABEL[k]) + '</option>').join('') + '</select>', { req: true }) +
          field('Izoh', '<textarea class="wh-textarea" name="notes" maxlength="2000" rows="2">' + esc(F.notes) + '</textarea>', { span: 'all' }) +
        '</div></form></div></div>' +
      '<div class="wh-card"><div class="wh-card-head"><h2 class="wh-card-title"><i class="fas fa-list" aria-hidden="true"></i> Mahsulot qatorlari</h2>' +
        '<button type="button" class="wh-btn wh-btn-sm" data-action="rc-add-line"><i class="fas fa-plus" aria-hidden="true"></i> Qator qo\'shish</button></div>' +
        '<div class="wh-card-body" id="rc-lines"></div></div>' +
      '<div class="wh-receipt-total"><div><div class="wh-label">Jami summa</div><div class="wh-total-num" id="rc-total" aria-live="polite">0 so\'m</div>' +
        '<div class="wh-hint" id="rc-total-sub"></div></div>' +
        '<div class="wh-hint" style="max-width:340px">Qoralama ombor qoldig\'iga ta\'sir qilmaydi. Tasdiqlansa, mahsulotlar qabul qilinadi va kassada xarajat yoziladi.</div></div>' +
      '<div class="wh-form-error" id="rc-error" role="alert" hidden style="margin-top:14px"></div>' +
      '<div class="wh-sticky-actions">' +
        '<button type="button" class="wh-btn" data-action="rc-back">Bekor qilish</button>' +
        '<button type="button" class="wh-btn" data-action="rc-save-draft"><i class="fas fa-floppy-disk" aria-hidden="true"></i> Qoralama saqlash</button>' +
        '<button type="button" class="wh-btn wh-btn-primary" data-action="rc-save-post"><i class="fas fa-circle-check" aria-hidden="true"></i> Tasdiqlash va omborga qabul qilish</button></div>';

    const head = $('#rc-head');
    const sup = $('[name="supplier"]', head);
    sup.addEventListener('change', () => {
      F.newSupplier = sup.value === '__new__';
      F.supplierId = F.newSupplier ? '' : sup.value;
      $('.js-newsup', head).hidden = !F.newSupplier;
      if (F.newSupplier) $('[name="supplier_name"]', head).focus();
    });
    head.addEventListener('submit', (e) => e.preventDefault());
    renderLines();
    const linesHost = $('#rc-lines');
    linesHost.addEventListener('input', onLineInput);
    linesHost.addEventListener('change', onLineInput);
  }

  function readHeadIntoState() {
    const F = RC.form, head = $('#rc-head');
    if (!head) return;
    F.invoice = $('[name="invoice_number"]', head).value;
    F.date = $('[name="receipt_date"]', head).value;
    F.method = $('[name="payment_method"]', head).value;
    F.notes = $('[name="notes"]', head).value;
    F.supplierName = $('[name="supplier_name"]', head).value;
  }

  function rawItemValues(root) {
    const v = {};
    $$('[name]', root).forEach((e) => { v[e.name] = (e.type === 'checkbox') ? (e.checked ? 1 : 0) : e.value; });
    return v;
  }
  function snapshotLines() {
    $$('.wh-line', $('#rc-lines') || document.createElement('div')).forEach((card) => {
      const L = RC.form.lines.find((x) => x.key === Number(card.dataset.key));
      if (!L) return;
      $$('[data-f]', card).forEach((e) => { L[e.dataset.f] = e.value; });
      const ni = $('.wh-newitem', card);
      if (L.mode === 'new' && ni) L.ni = rawItemValues(ni);
    });
  }

  function lineUnits(L, card) {
    // -> {upp: BigInt|null, unit, pkgUnit, allowFraction, trackExpiry}
    if (L.mode === 'new') {
      const ni = $('.wh-newitem', card);
      const v = ni ? rawItemValues(ni) : (L.ni || {});
      const pu = v.package_unit || '';
      return {
        upp: pu ? parseDec(canonicalNumber(v.units_per_package), 3) : parseDec('1', 3),
        unit: v.base_unit || 'dona', pkgUnit: pu, allowFraction: !!Number(v.allow_fraction), trackExpiry: !!Number(v.track_expiry), name: v.name || ''
      };
    }
    const it = L.item;
    if (!it) return { upp: null, unit: '', pkgUnit: '', allowFraction: false, trackExpiry: false, name: '' };
    return { upp: parseDec(String(it.units_per_package), 3), unit: it.base_unit, pkgUnit: it.package_unit || '', allowFraction: !!it.allow_fraction, trackExpiry: !!it.track_expiry, name: it.name };
  }

  const TEN_10 = HAS_BIGINT ? BigInt('10000000000') : 0;
  const TEN_9 = HAS_BIGINT ? BigInt('1000000000') : 0;
  const TEN_4 = HAS_BIGINT ? BigInt('10000') : 0;

  /** Exact figures of one line from the typed text, or {valid: false}. */
  function calcLine(L, card) {
    const u = lineUnits(L, card);
    const pk = parseDec(L.packages, 3), pr = parseDec(L.price, 2);
    if (pk === null || pr === null || u.upp === null || u.upp <= ZERO || pk <= ZERO) return { valid: false, u: u };
    const qty3 = roundDiv(pk * u.upp, TEN_9);          // base units, 3 decimals
    return {
      valid: true, u: u,
      qty3: qty3,
      unit4: roundDiv(pr * TEN_4, u.upp),               // cost of one base unit, 4 decimals
      total2: roundDiv(pk * pr, TEN_10),                // line total, 2 decimals
      whole: qty3 % BigInt(1000) === ZERO
    };
  }

  function lineHtml(L, idx, total) {
    const it = L.item;
    const existing = L.mode === 'existing';
    return '<div class="wh-line" data-key="' + L.key + '">' +
      '<div class="wh-line-head"><span class="wh-line-no">QATOR ' + (idx + 1) + '</span>' +
        '<div style="display:flex;gap:6px;align-items:center">' +
          '<button type="button" class="wh-chip" data-action="rc-mode" data-key="' + L.key + '" data-mode="existing" aria-pressed="' + existing + '">Mavjud mahsulot</button>' +
          '<button type="button" class="wh-chip" data-action="rc-mode" data-key="' + L.key + '" data-mode="new" aria-pressed="' + !existing + '">Yangi mahsulot</button>' +
          (total > 1 ? '<button type="button" class="wh-icon-btn" data-action="rc-remove" data-key="' + L.key + '" aria-label="Qatorni o\'chirish" title="Qatorni o\'chirish"><i class="fas fa-trash" aria-hidden="true"></i></button>' : '') +
        '</div></div>' +
      (existing
        ? '<div class="wh-field" style="margin-bottom:10px"><span class="wh-label">Mahsulot <span class="wh-req">*</span></span><div data-combo></div>' +
          '<span class="wh-hint" data-unit-line></span></div>'
        : '<div class="wh-newitem"><div class="wh-hint" style="margin-bottom:10px">Katalogda yo\'q mahsulot: hujjat tasdiqlanganda yangi mahsulot sifatida yaratiladi.</div>' +
          itemFieldsHtml(L.ni || { item_type: 'medicine', base_unit: 'dona', track_expiry: 1 }, { compact: true, creating: true }) + '</div>') +
      '<div class="wh-line-grid" style="margin-top:10px">' +
        field('Qadoq soni <span data-pkg-label></span>', '<input class="wh-input" data-f="packages" inputmode="decimal" autocomplete="off" value="' + esc(L.packages) + '">', { req: true }) +
        field('Qadoq narxi (so\'m)', '<input class="wh-input" data-f="price" inputmode="decimal" autocomplete="off" value="' + esc(L.price) + '">', { req: true }) +
        field('Partiya raqami', '<input class="wh-input" data-f="batch" maxlength="64" autocomplete="off" value="' + esc(L.batch) + '">') +
        field('Yaroqlilik muddati <span data-exp-req></span>', '<input class="wh-input" type="date" data-f="expiry" value="' + esc(L.expiry) + '" min="' + todayISO() + '">') +
      '</div>' +
      '<div class="wh-line-calc" data-calc></div><div class="wh-line-error" data-lerr role="alert" hidden></div></div>';
  }

  function renderLines() {
    const F = RC.form, host = $('#rc-lines');
    host.innerHTML = F.lines.map((L, i) => lineHtml(L, i, F.lines.length)).join('');
    F.lines.forEach((L) => {
      const card = $('.wh-line[data-key="' + L.key + '"]', host);
      if (L.mode === 'existing') {
        const combo = makeCombo($('[data-combo]', card), {
          placeholder: 'Mahsulot nomini yozing…', ariaLabel: 'Mahsulot', source: itemSource(),
          onChange: (opt) => { L.item = opt ? opt.raw : null; refreshLine(L, card); updateReceiptTotal(); }
        });
        if (L.item) combo.set(itemOption(L.item));
      } else {
        bindItemFields($('.wh-newitem', card), { creating: true });
      }
      refreshLine(L, card);
    });
    updateReceiptTotal();
  }

  function refreshLine(L, card) {
    const u = lineUnits(L, card);
    const pk = $('[data-pkg-label]', card);
    if (pk) pk.textContent = u.pkgUnit ? '(' + u.pkgUnit + ')' : (u.unit ? '(' + u.unit + ')' : '');
    const er = $('[data-exp-req]', card);
    if (er) er.innerHTML = u.trackExpiry ? '<span class="wh-req">*</span>' : '';
    const hint = $('[data-unit-line]', card);
    if (hint && L.item) {
      hint.textContent = L.item.package_unit ? '1 ' + L.item.package_unit + ' = ' + NF_QTY.format(Number(L.item.units_per_package)) + ' ' + L.item.base_unit : 'Qadoqsiz: son ' + L.item.base_unit + ' hisobida.';
    } else if (hint) hint.textContent = '';
    const c = calcLine(L, card);
    const calc = $('[data-calc]', card);
    if (!c.valid) {
      calc.innerHTML = '<span class="wh-dim">Qadoq soni va narxini kiriting — jami shu yerda hisoblanadi.</span>';
    } else {
      calc.innerHTML = '<span>Jami miqdor: <b>' + fmtScaled(c.qty3, 3, 0) + ' ' + esc(c.u.unit) + '</b></span>' +
        '<span>1 ' + esc(c.u.unit) + ' = <b>' + fmtScaled(c.unit4, 4, 0) + " so'm</b></span>" +
        '<span>Qator summasi: <b>' + fmtScaled(c.total2, 2, 0) + " so'm</b></span>" +
        (!c.u.allowFraction && !c.whole ? '<span class="wh-expired-text">Bu mahsulot butun sonlarda hisoblanadi: kasr chiqdi.</span>' : '');
    }
  }

  function updateReceiptTotal() {
    const F = RC.form;
    if (!F) return;
    let sum = ZERO, valid = 0;
    F.lines.forEach((L) => {
      const card = $('.wh-line[data-key="' + L.key + '"]');
      if (!card) return;
      const c = calcLine(L, card);
      if (c.valid) { sum += c.total2; valid++; }
    });
    $('#rc-total').textContent = fmtScaled(sum, 2, 0) + " so'm";
    $('#rc-total-sub').textContent = valid + ' / ' + F.lines.length + ' qator hisoblangan';
  }

  function onLineInput(e) {
    const card = e.target.closest('.wh-line');
    if (!card) return;
    const L = RC.form.lines.find((x) => x.key === Number(card.dataset.key));
    if (!L) return;
    if (e.target.dataset && e.target.dataset.f) L[e.target.dataset.f] = e.target.value;
    card.classList.remove('has-error');
    const er = $('[data-lerr]', card);
    if (er) er.hidden = true;
    refreshLine(L, card);
    updateReceiptTotal();
  }

  ACTIONS['rc-new'] = () => openReceiptForm();
  ACTIONS['rc-add-line'] = () => { snapshotLines(); RC.form.lines.push(newLine()); renderLines(); const cards = $$('#rc-lines .wh-line'); const last = cards[cards.length - 1]; if (last) last.scrollIntoView({ block: 'center' }); };
  ACTIONS['rc-remove'] = async (t) => {
    const F = RC.form;
    if (F.lines.length <= 1) return;
    snapshotLines();
    F.lines = F.lines.filter((x) => x.key !== Number(t.dataset.key));
    renderLines();
  };
  ACTIONS['rc-mode'] = (t) => {
    snapshotLines();
    const L = RC.form.lines.find((x) => x.key === Number(t.dataset.key));
    if (!L || L.mode === t.dataset.mode) return;
    L.mode = t.dataset.mode;
    renderLines();
  };
  function receiptDirty() {
    const F = RC.form;
    if (!F) return false;
    snapshotLines();
    readHeadIntoState();
    return !!(F.invoice || F.notes || F.supplierId || F.supplierName || F.lines.some((L) => L.item || L.packages || L.price || L.batch || L.expiry || (L.ni && L.ni.name)));
  }
  ACTIONS['rc-back'] = async () => {
    if (RC.form && RC.form.submitting) return;
    if (receiptDirty()) {
      const ok = await confirmBox({ title: 'Hujjatdan chiqish', message: 'Kiritilgan ma\'lumotlar saqlanmaydi. Chiqasizmi?', confirmText: 'Ha, chiqish', type: 'warning' });
      if (!ok) return;
    }
    RC.form = null;
    showReceiptView('list');
  };
  ACTIONS['rc-save-draft'] = (t) => submitReceipt(false, t);
  ACTIONS['rc-save-post'] = (t) => submitReceipt(true, t);

  function showReceiptError(msg, lineKey, field) {
    const box = $('#rc-error');
    box.textContent = msg;
    box.hidden = false;
    let target = box;
    if (lineKey) {
      const card = $('.wh-line[data-key="' + lineKey + '"]');
      if (card) {
        card.classList.add('has-error');
        const er = $('[data-lerr]', card);
        er.textContent = msg;
        er.hidden = false;
        target = card;
        if (field) {
          const map = { packages: 'packages', package_price: 'price', batch_no: 'batch', expiry_date: 'expiry' };
          let inp = null;
          if (map[field]) inp = $('[data-f="' + map[field] + '"]', card);
          else if (field === 'item_id') inp = $('[data-combo] input', card);
          else inp = $('.wh-newitem [name="' + String(field).replace(/[^A-Za-z0-9_-]/g, '') + '"]', card);
          if (inp) { inp.setAttribute('aria-invalid', 'true'); inp.addEventListener('input', () => inp.removeAttribute('aria-invalid'), { once: true }); try { inp.focus(); } catch (e) { /* hidden */ } }
        }
      }
    } else if (field) {
      const inp = $('#rc-head [name="' + String(field).replace(/[^A-Za-z0-9_-]/g, '') + '"]');
      if (inp) { inp.setAttribute('aria-invalid', 'true'); inp.focus(); }
    }
    target.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }

  /** -> {payload, total2, count} or {error, lineKey, field} */
  function buildReceiptPayload(post) {
    const F = RC.form;
    snapshotLines();
    readHeadIntoState();
    $$('#rc-edit-view [aria-invalid="true"]').forEach((n) => n.removeAttribute('aria-invalid'));
    $$('#rc-lines .wh-line').forEach((c) => { c.classList.remove('has-error'); const e = $('[data-lerr]', c); if (e) e.hidden = true; });
    $('#rc-error').hidden = true;
    if (!F.date) return { error: 'Kirim sanasi ko\'rsatilishi shart.', field: 'receipt_date' };
    if (F.date > todayISO()) return { error: 'Kirim sanasi kelajakda bo\'lishi mumkin emas.', field: 'receipt_date' };
    if (F.newSupplier && !F.supplierName.trim()) return { error: 'Yangi yetkazib beruvchi nomini yozing yoki ro\'yxatdan tanlang.', field: 'supplier_name' };
    const lines = [];
    let total = ZERO;
    for (let i = 0; i < F.lines.length; i++) {
      const L = F.lines[i];
      const card = $('.wh-line[data-key="' + L.key + '"]');
      const where = (i + 1) + '-qator: ';
      const out = {};
      if (L.mode === 'existing') {
        if (!L.item) return { error: where + 'mahsulot tanlanmagan.', lineKey: L.key, field: 'item_id' };
        out.item_id = L.item.id;
      } else {
        const read = readItemFields($('.wh-newitem', card), { edit: false });
        if (read.error) return { error: where + read.error.error, lineKey: L.key, field: read.error.field };
        out.new_item = read.data;
      }
      const c = calcLine(L, card);
      if (parseDec(L.packages, 3) === null || parseDec(L.packages, 3) <= ZERO) return { error: where + "qadoq soni noldan katta raqam bo'lishi kerak (ko'pi bilan 3 ta kasr).", lineKey: L.key, field: 'packages' };
      if (parseDec(L.price, 2) === null) return { error: where + "qadoq narxi 0 yoki undan katta raqam bo'lishi kerak (ko'pi bilan 2 ta kasr).", lineKey: L.key, field: 'package_price' };
      if (!c.valid) return { error: where + 'miqdorni hisoblab bo\'lmadi: qadoqdagi miqdorni tekshiring.', lineKey: L.key, field: 'packages' };
      if (!c.u.allowFraction && !c.whole) return { error: where + (c.u.name || 'mahsulot') + ' butun sonlarda hisoblanadi: ' + fmtScaled(c.qty3, 3, 0) + ' chiqdi.', lineKey: L.key, field: 'packages' };
      if (c.u.trackExpiry && !L.expiry) return { error: where + 'yaroqlilik muddati kiritilishi shart.', lineKey: L.key, field: 'expiry_date' };
      if (L.expiry && L.expiry < todayISO()) return { error: where + 'muddati o\'tgan mahsulotni qabul qilib bo\'lmaydi.', lineKey: L.key, field: 'expiry_date' };
      out.packages = canonicalNumber(L.packages);
      out.package_price = canonicalNumber(L.price);
      if (L.batch.trim()) out.batch_no = L.batch.trim();
      if (L.expiry) out.expiry_date = L.expiry;
      lines.push(out);
      total += c.total2;
    }
    const payload = { client_request_id: F.requestId, receipt_date: F.date, payment_method: F.method, post: !!post, lines: lines };
    if (F.newSupplier) payload.supplier_name = F.supplierName.trim();
    else if (F.supplierId) payload.supplier_id = F.supplierId;
    if (F.invoice.trim()) payload.invoice_number = F.invoice.trim();
    if (F.notes.trim()) payload.notes = F.notes.trim();
    return { payload: payload, total2: total, count: lines.length };
  }

  async function submitReceipt(post, btn) {
    const F = RC.form;
    if (!F || F.submitting) return;
    const built = buildReceiptPayload(post);
    if (built.error) { showReceiptError(built.error, built.lineKey, built.field); return; }
    if (post) {
      const ok = await confirmBox({
        title: 'Kirimni tasdiqlash',
        message: built.count + ' qator, jami <b>' + fmtScaled(built.total2, 2, 0) + " so'm</b>.<br>Mahsulotlar darhol omborga qabul qilinadi va kassada xarajat yoziladi. Buni keyin faqat \"qaytarish\" bilan bekor qilish mumkin.",
        confirmText: 'Tasdiqlash va qabul qilish', type: 'primary'
      });
      if (!ok) return;
    }
    F.submitting = true;
    const buttons = $$('.wh-sticky-actions .wh-btn');
    buttons.forEach((b) => { b.disabled = true; });
    if (btn) btn.setAttribute('aria-busy', 'true');
    try {
      const r = await api('POST', '/receipts', built.payload);
      if (!r.ok) {
        let msg = r.data.error || 'Saqlab bo\'lmadi.';
        if (r.status === 0) msg += ' Hujjat yuborilgan bo\'lishi mumkin: qayta yuborsangiz takrorlanmaydi (xavfsiz).';
        const m = /^(\d+)-qator/.exec(msg);
        const L = m ? F.lines[Number(m[1]) - 1] : null;
        showReceiptError(msg, L ? L.key : null, r.data.field);
        return;
      }
      let rec = r.data;
      // Same request id seen before and left as a draft: finish the post the person asked for.
      if (post && rec.status === 'draft') {
        const p = await api('POST', '/receipts/' + encodeURIComponent(rec.id) + '/post', {});
        if (!p.ok) { showReceiptError(p.data.error); return; }
        rec = p.data;
      }
      toast(rec.status === 'posted' ? 'Kirim tasdiqlandi: mahsulotlar omborga qabul qilindi.' : 'Qoralama saqlandi.');
      RC.form = null;
      invalidate();
      showReceiptView('list');
      loadReceipts();
      openReceipt(rec.id);
    } finally {
      F.submitting = false;
      buttons.forEach((b) => { b.disabled = false; });
      if (btn) btn.removeAttribute('aria-busy');
    }
  }

  // ===========================================================================
  // DISPENSING (Berish)
  // ===========================================================================
  const DS = {
    patient: null, pending: [], queue: null, queueError: '', queuePatients: {}, shell: false, combo: null,
    h: { from: '', to: '', status: '', offset: 0, limit: 25, rows: [], total: 0, seq: 0 }
  };

  function ensureDsShell() {
    if (DS.shell) return;
    const panel = $('#panel-dispensing');
    panel.innerHTML =
      '<div class="wh-card"><div class="wh-card-head"><h2 class="wh-card-title"><i class="fas fa-user-injured" aria-hidden="true"></i> Bemor</h2></div>' +
        '<div class="wh-card-body"><div id="ds-pick"><div data-combo style="max-width:520px"></div>' +
          '<p class="wh-hint" style="margin-top:6px">Ismi, kodi yoki telefon raqami bilan qidiring (kamida 2 ta belgi) yoki quyidagi ro\'yxatdan tanlang.</p></div>' +
          '<div class="wh-patient-bar" id="ds-bar" hidden></div></div></div>' +
      '<div class="wh-card" id="ds-queue" style="margin-top:16px"></div>' +
      '<div class="wh-card" id="ds-rx" style="margin-top:16px" hidden></div>' +
      '<div class="wh-card" id="ds-hist" style="margin-top:16px"></div>';
    DS.shell = true;
    DS.combo = makeCombo($('#ds-pick [data-combo]'), {
      placeholder: 'Bemor ismi, kodi yoki telefoni…', ariaLabel: 'Bemorni qidirish', source: patientSource, minChars: 2, openOnFocus: false,
      onChange: (opt) => { if (opt) selectPatient(opt.raw); }
    });
    renderHistShell();
  }

  async function loadDispensing() {
    ensureDsShell();
    S.stale.dispensing = false;
    S.loaded.dispensing = true;
    await Promise.all([loadQueue(), DS.patient ? loadPatientRx() : Promise.resolve(), loadDispHist()]);
  }

  async function loadQueue() {
    const host = $('#ds-queue');
    host.hidden = !!DS.patient;
    if (DS.patient) return;
    if (!DS.queue) host.innerHTML = '<div class="wh-card-head"><h2 class="wh-card-title"><i class="fas fa-prescription" aria-hidden="true"></i> Retsept bo\'yicha kutayotganlar</h2></div>' + loadingHtml(3);
    const r = await api('GET', '/prescriptions/pending');
    if (!r.ok) { DS.queue = null; DS.queueError = r.data.error; host.innerHTML = '<div class="wh-card-head"><h2 class="wh-card-title">Retsept bo\'yicha kutayotganlar</h2></div>' + errorHtml(r.data.error, 'ds-retry'); return; }
    const by = {};
    (r.data.prescriptions || []).forEach((p) => {
      const g = by[p.patient_id] || (by[p.patient_id] = { id: p.patient_id, name: p.patient_name, code: p.patient_code, admission_id: p.admission_id || null, items: [], count: 0 });
      g.count++;
      if (g.items.indexOf(p.item_name) < 0) g.items.push(p.item_name);
    });
    DS.queuePatients = by;
    DS.queue = Object.keys(by).map((k) => by[k]);
    const body = DS.queue.length
      ? '<ul class="wh-list wh-scroll">' + DS.queue.map((g) =>
        '<li><button type="button" class="wh-row-click" data-action="ds-pick" data-id="' + esc(g.id) + '">' +
        '<span class="wh-row-main"><strong>' + esc(g.name) + '</strong><small>' + esc(g.code || '') + ' · ' + esc(g.items.slice(0, 3).join(', ')) + (g.items.length > 3 ? ' …' : '') + '</small></span>' +
        '<span class="wh-row-side">' + badge('draft', g.count + ' ta retsept') + '</span></button></li>').join('') + '</ul>'
      : emptyHtml('fa-circle-check', 'Kutayotgan retsept yo\'q', 'Faol retsepti bor bemorlar shu yerda ko\'rinadi. Retseptsiz material berish uchun bemorni qidiring.');
    host.innerHTML = '<div class="wh-card-head"><h2 class="wh-card-title"><i class="fas fa-prescription" aria-hidden="true"></i> Retsept bo\'yicha kutayotganlar</h2>' +
      '<button type="button" class="wh-btn wh-btn-sm" data-action="ds-retry"><i class="fas fa-rotate" aria-hidden="true"></i></button></div>' + body;
  }

  function selectPatient(p) {
    DS.patient = { id: p.id, name: p.name || p.patient_name || p.id, code: p.code || p.patient_code || '', admission_id: p.admission_id || null };
    // The queue knows the active admission for a prescription's patient; the CRM list knows it too.
    if (!DS.patient.admission_id && DS.queuePatients[p.id]) DS.patient.admission_id = DS.queuePatients[p.id].admission_id;
    $('#ds-pick').hidden = true;
    const bar = $('#ds-bar');
    bar.hidden = false;
    bar.innerHTML = '<div><strong>' + esc(DS.patient.name) + '</strong><div class="wh-hint">' + esc(DS.patient.code) + '</div></div>' +
      '<button type="button" class="wh-btn wh-btn-sm" data-action="ds-clear"><i class="fas fa-user-pen" aria-hidden="true"></i> Boshqa bemor</button>';
    $('#ds-queue').hidden = true;
    DS.h.offset = 0;
    loadPatientRx();
    loadDispHist();
  }

  ACTIONS['ds-pick'] = (t) => { const g = DS.queuePatients[t.dataset.id]; if (g) selectPatient(g); };
  ACTIONS['ds-clear'] = () => {
    DS.patient = null; DS.pending = [];
    $('#ds-pick').hidden = false;
    $('#ds-bar').hidden = true;
    $('#ds-rx').hidden = true;
    if (DS.combo) DS.combo.clear();
    DS.h.offset = 0;
    loadQueue();
    loadDispHist();
  };
  ACTIONS['ds-retry'] = () => { DS.queue = null; loadQueue(); };

  async function loadPatientRx() {
    const host = $('#ds-rx');
    host.hidden = false;
    host.innerHTML = '<div class="wh-card-head"><h2 class="wh-card-title"><i class="fas fa-prescription" aria-hidden="true"></i> Faol retseptlar</h2></div>' + loadingHtml(3);
    const pid = DS.patient.id;
    const r = await api('GET', '/prescriptions/pending' + qs({ patient_id: pid }));
    if (!DS.patient || DS.patient.id !== pid) return;
    const head = '<div class="wh-card-head"><h2 class="wh-card-title"><i class="fas fa-prescription" aria-hidden="true"></i> Faol retseptlar</h2>' +
      '<button type="button" class="wh-btn wh-btn-sm" data-action="ds-consumable"><i class="fas fa-syringe" aria-hidden="true"></i> Retseptsiz material berish</button></div>';
    if (!r.ok) { host.innerHTML = head + errorHtml(r.data.error, 'ds-rx-retry'); return; }
    DS.pending = r.data.prescriptions || [];
    if (!DS.pending.length) {
      host.innerHTML = head + emptyHtml('fa-file-circle-xmark', 'Berilishi kerak retsept yo\'q',
        'Bu bemorning faol retsepti yo\'q yoki hammasi berib bo\'lingan. Shprits va sarf materiallarini yuqoridagi tugma bilan bering.');
      return;
    }
    host.innerHTML = head + '<div class="wh-card-body"><div class="wh-rx-grid">' + DS.pending.map((p, i) => {
      const unit = p.base_unit;
      const avail = Number(p.available_quantity || 0);
      const meta = [p.dosage, p.route, p.frequency, p.duration_days ? p.duration_days + ' kun' : ''].filter(Boolean).map(esc).join(' · ');
      return '<div class="wh-rx"><h3 class="wh-rx-title">' + esc(p.item_name) + '</h3>' +
        '<div class="wh-rx-meta">' + (meta || 'Dozalash ko\'rsatilmagan') + '</div>' +
        (p.medication_name && p.medication_name !== p.item_name ? '<div class="wh-rx-meta">Retseptda: ' + esc(p.medication_name) + '</div>' : '') +
        (p.instructions ? '<div class="wh-rx-meta">' + esc(p.instructions) + '</div>' : '') +
        '<div class="wh-rx-meta">Shifokor: ' + esc(p.doctor_name || '—') + ' · ' + fmtDate(p.created_at) + '</div>' +
        '<div class="wh-rx-nums"><div><span>Buyurilgan</span><b>' + (p.quantity_prescribed === null ? '—' : fmtQty(p.quantity_prescribed)) + '</b></div>' +
          '<div><span>Berilgan</span><b>' + fmtQty(p.dispensed_quantity) + '</b></div>' +
          '<div><span>Qolgan</span><b>' + (p.remaining_quantity === null ? 'Cheklanmagan' : fmtQty(p.remaining_quantity)) + '</b></div>' +
          '<div><span>Omborda</span><b class="' + (avail <= 0 ? 'wh-expired-text' : '') + '">' + fmtQty(avail) + '</b></div></div>' +
        '<div class="wh-rx-meta">Birlik: ' + esc(unit) + (p.quantity_unit && p.quantity_unit !== unit ? ' (retseptda: ' + esc(p.quantity_unit) + ')' : '') + ' · ' + statusBadge(p.stock_status) + '</div>' +
        '<button type="button" class="wh-btn wh-btn-primary" data-action="ds-dispense" data-i="' + i + '"' + (avail <= 0 ? ' disabled title="Omborda yaroqli qoldiq yo\'q"' : '') + '>' +
          '<i class="fas fa-hand-holding-medical" aria-hidden="true"></i> Berish</button></div>';
    }).join('') + '</div></div>';
  }
  ACTIONS['ds-rx-retry'] = () => loadPatientRx();
  ACTIONS['ds-dispense'] = (t) => { const p = DS.pending[Number(t.dataset.i)]; if (p && DS.patient) openDispenseModal({ rx: p }); };
  ACTIONS['ds-consumable'] = () => { if (DS.patient) openDispenseModal({ rx: null }); };

  const CONSUMABLE_TYPES = ['syringe', 'consumable', 'equipment', 'other'];

  function consumableSource(q) {
    return api('GET', '/items' + qs({ q: q, active: '1', limit: 40, sort: 'name' })).then((r) => {
      if (!r.ok) return null;
      return (r.data.items || []).filter((i) => CONSUMABLE_TYPES.indexOf(i.item_type) >= 0).slice(0, 15).map(itemOption);
    });
  }

  function openDispenseModal(o) {
    const patient = DS.patient;
    const rx = o.rx;
    const reqId = newRequestId();           // one id per opened form: a retry can never dispense twice
    let item = rx ? { id: rx.item_id, name: rx.item_name, base_unit: rx.base_unit, allow_fraction: rx.allow_fraction, available_quantity: rx.available_quantity } : null;
    const avail0 = rx ? Number(rx.available_quantity || 0) : 0;
    // Prefill: what the prescription still allows, capped at what is on the shelf.
    // No stated quantity on the prescription means nothing is guessed: the field stays empty.
    let pre = '';
    if (rx && rx.remaining_quantity !== null) {
      let q = Math.min(Number(rx.remaining_quantity), avail0);
      if (!rx.allow_fraction) q = Math.floor(q);
      pre = q > 0 ? String(q) : '';
    }
    const layer = openLayer({
      title: rx ? 'Dori berish' : 'Retseptsiz material berish', subtitle: patient.name, dismissOnBg: false,
      html: '<form novalidate data-ds-form>' +
        (rx
          ? '<dl class="wh-dl" style="margin-bottom:14px">' +
            dlRow('Mahsulot', '<b>' + esc(rx.item_name) + '</b>') +
            dlRow('Dozalash', esc([rx.dosage, rx.route, rx.frequency].filter(Boolean).join(' · ') || '—')) +
            dlRow('Buyurilgan', rx.quantity_prescribed === null ? 'Miqdor yozilmagan' : plural(rx.quantity_prescribed, rx.base_unit)) +
            dlRow('Allaqachon berilgan', plural(rx.dispensed_quantity, rx.base_unit)) +
            dlRow('Qolgan', rx.remaining_quantity === null ? 'Cheklanmagan' : plural(rx.remaining_quantity, rx.base_unit)) +
            dlRow('Omborda (yaroqli)', '<b>' + plural(rx.available_quantity, rx.base_unit) + '</b>') + '</dl>'
          : '<div class="wh-field" style="margin-bottom:12px"><span class="wh-label">Mahsulot <span class="wh-req">*</span></span><div data-combo></div>' +
            '<span class="wh-hint">Dori-darmon faqat retsept bo\'yicha beriladi. Bu yerda shprits, sarf materiali va jihozlar tanlanadi.</span></div>') +
        '<div class="wh-form-grid">' +
          field('Miqdor <span data-unit-label>' + (item ? '(' + esc(item.base_unit) + ')' : '') + '</span>', '<input class="wh-input" name="quantity" inputmode="decimal" autocomplete="off" value="' + esc(pre) + '">', { req: true,
            hint: '<span data-avail>' + (item ? 'Omborda: ' + plural(item.available_quantity, item.base_unit) : '') + '</span>' }) +
          (rx ? '' : field('Yotoq (admission)', '<select class="wh-select" name="admission_id"><option value="">Ko\'rsatilmagan</option>' +
            (patient.admission_id ? '<option value="' + esc(patient.admission_id) + '">Faol yotoq: ' + esc(patient.admission_id) + '</option>' : '') + '</select>') +
            field('Konsultatsiya raqami', textInput('consultation_id', '', 'maxlength="64"'), { hint: 'Ixtiyoriy' })) +
          field('Izoh', '<textarea class="wh-textarea" name="notes" maxlength="2000" rows="2"></textarea>', { span: 'all' }) +
        '</div></form><div id="ds-result" class="wh-result" hidden></div>',
      footer: '<button type="button" class="wh-btn" data-layer-close>Bekor qilish</button>' +
        '<button type="button" class="wh-btn wh-btn-primary" data-save><i class="fas fa-hand-holding-medical" aria-hidden="true"></i> Berish</button>',
      onClose: () => { if (layer && layer.dirty) { S.stale.dispensing = true; loadDispensing(); } }
    });
    const form = $('form', layer.body);
    if (!rx) {
      makeCombo($('[data-combo]', layer.body), {
        placeholder: 'Shprits, paket, qo\'lqop…', ariaLabel: 'Mahsulot', source: consumableSource,
        onChange: (opt) => {
          item = opt ? opt.raw : null;
          $('[data-unit-label]', form).textContent = item ? '(' + item.base_unit + ')' : '';
          $('[data-avail]', form).textContent = item ? 'Omborda: ' + NF_QTY.format(Number(item.available_quantity || 0)) + ' ' + item.base_unit : '';
        }
      });
    }
    async function save(btn) {
      clearFormError(form);
      if (!item) { fieldError(form, { error: 'Mahsulot tanlanmagan.' }); return; }
      const qEl = $('[name="quantity"]', form);
      const n = numCheck(qEl.value, 3);
      if (n === null || n <= 0) { fieldError(form, { field: 'quantity', error: "Miqdor noldan katta raqam bo'lishi kerak (ko'pi bilan 3 ta kasr)." }); return; }
      if (!item.allow_fraction && !Number.isInteger(n)) { fieldError(form, { field: 'quantity', error: item.name + ' butun sonlarda beriladi: kasr miqdor kiritib bo\'lmaydi.' }); return; }
      const avail = Number(item.available_quantity || 0);
      if (n > avail) { fieldError(form, { field: 'quantity', error: 'Omborda yetarli qoldiq yo\'q. Mavjud (yaroqli): ' + NF_QTY.format(avail) + ' ' + item.base_unit + '.' }); return; }
      if (rx && rx.remaining_quantity !== null && n > Number(rx.remaining_quantity)) {
        fieldError(form, { field: 'quantity', error: 'Retseptda qolgan miqdor: ' + NF_QTY.format(Number(rx.remaining_quantity)) + ' ' + item.base_unit + '. Bundan ko\'p berib bo\'lmaydi.' }); return;
      }
      const ok = await confirmBox({
        title: 'Dori berishni tasdiqlang',
        message: 'Bemor: <b>' + esc(patient.name) + '</b><br>Beriladi: <b>' + fmtQty(n) + ' ' + esc(item.base_unit) + ' ' + esc(item.name) + '</b><br>' +
          'Omborda qoladi: ' + fmtQty(Number((avail - n).toFixed(3))) + ' ' + esc(item.base_unit) + '.<br>Ombor qoldig\'idan darhol ayriladi.',
        confirmText: 'Berish', type: 'primary'
      });
      if (!ok) return;
      await runBusy(btn, async () => {
        const body = { client_request_id: reqId, patient_id: patient.id, item_id: item.id, quantity: canonicalNumber(qEl.value) };
        if (rx) body.prescription_id = rx.prescription_id;
        const adm = $('[name="admission_id"]', form), cons = $('[name="consultation_id"]', form), notes = $('[name="notes"]', form).value.trim();
        if (adm && adm.value) body.admission_id = adm.value;
        if (cons && cons.value.trim()) body.consultation_id = cons.value.trim();
        if (notes) body.notes = notes;
        const r = await api('POST', '/dispense', body);
        if (!r.ok) {
          const e = Object.assign({}, r.data);
          if (r.status === 0) e.error += ' Natija noma\'lum: qayta bossangiz, takrorlanmaydi (xavfsiz).';
          fieldError(form, e);
          return;
        }
        layer.dirty = true;
        invalidate();
        showDispenseResult(layer, r.data, r.status === 200);
      });
    }
    $('[data-save]', layer.foot).addEventListener('click', (e) => save(e.currentTarget));
    form.addEventListener('submit', (e) => { e.preventDefault(); save($('[data-save]', layer.foot)); });
  }

  function showDispenseResult(layer, d, duplicate) {
    $('form', layer.body).hidden = true;
    const res = $('#ds-result', layer.body);
    res.hidden = false;
    res.innerHTML =
      '<div class="wh-note is-ok"><b><i class="fas fa-circle-check" aria-hidden="true"></i> ' + (duplicate ? 'Bu so\'rov avval bajarilgan: takror yozilmadi.' : 'Berildi.') + '</b><br>' +
        esc(d.item_name) + ' — <b>' + plural(d.quantity, d.base_unit) + '</b> · ' + esc(d.patient_name || '') + ' · <span class="wh-mono">' + esc(d.id) + '</span></div>' +
      '<div class="wh-block"><h3 class="wh-block-title"><i class="fas fa-layer-group" aria-hidden="true"></i> Qaysi partiyadan olindi</h3>' +
      '<div class="wh-table-wrap"><table class="wh-table wh-stack wh-compact"><thead><tr><th>Partiya</th><th>Muddati</th><th class="wh-right">Miqdor</th></tr></thead><tbody>' +
      (d.batches || []).map((b) => '<tr><td data-label="Partiya"><span class="wh-mono">' + esc(b.batch_no || '—') + '</span></td><td data-label="Muddati">' + fmtDate(b.expiry_date) + '</td>' +
        '<td data-label="Miqdor" class="wh-right wh-num"><b>' + fmtQty(b.quantity) + '</b> ' + esc(d.base_unit) + '</td></tr>').join('') + '</tbody></table></div></div>';
    layer.setFoot('<button type="button" class="wh-btn wh-btn-primary" data-layer-close>Yopish</button>');
    layer.setTitle('Berildi', d.patient_name || '');
  }

  // --- Dispensing history ----------------------------------------------------------
  function renderHistShell() {
    $('#ds-hist').innerHTML =
      '<div class="wh-card-head"><h2 class="wh-card-title"><i class="fas fa-clock-rotate-left" aria-hidden="true"></i> Berish tarixi <span class="wh-dim" id="ds-h-scope"></span></h2></div>' +
      '<div class="wh-toolbar">' +
        '<label class="wh-field"><span class="wh-label">Sanadan</span><input class="wh-input" type="date" id="ds-h-from"></label>' +
        '<label class="wh-field"><span class="wh-label">Sanagacha</span><input class="wh-input" type="date" id="ds-h-to"></label>' +
        '<label class="wh-field"><span class="wh-label">Holat</span><select class="wh-select" id="ds-h-status"><option value="">Hammasi</option>' +
          Object.keys(DISP_STATUS).map((k) => '<option value="' + k + '">' + esc(DISP_STATUS[k]) + '</option>').join('') + '</select></label>' +
      '</div><div id="ds-h-body"></div><div id="ds-h-pager"></div>';
    [['ds-h-from', 'from'], ['ds-h-to', 'to'], ['ds-h-status', 'status']].forEach((p) =>
      $('#' + p[0]).addEventListener('change', (e) => { DS.h[p[1]] = e.target.value; DS.h.offset = 0; loadDispHist(); }));
  }

  async function loadDispHist() {
    const h = DS.h;
    const body = $('#ds-h-body');
    if (!body) return;
    const mine = ++h.seq;
    $('#ds-h-scope').textContent = DS.patient ? '— ' + DS.patient.name : '— hamma bemorlar';
    if (!h.rows.length) body.innerHTML = loadingHtml(4);
    const r = await api('GET', '/dispensings' + qs({ patient_id: DS.patient ? DS.patient.id : '', from: h.from, to: h.to, status: h.status, limit: h.limit, offset: h.offset }));
    if (mine !== h.seq) return;
    if (!r.ok) { body.innerHTML = errorHtml(r.data.error, 'ds-h-retry'); $('#ds-h-pager').innerHTML = ''; return; }
    h.rows = r.data.dispensings || [];
    h.total = r.data.total || 0;
    if (!h.rows.length) {
      body.innerHTML = emptyHtml('fa-clipboard-list', 'Yozuv topilmadi', DS.patient ? 'Bu bemorga hali hech narsa berilmagan.' : 'Tanlangan filtrlarga mos yozuv yo\'q.');
      $('#ds-h-pager').innerHTML = '';
      return;
    }
    body.innerHTML = '<div class="wh-table-wrap"><table class="wh-table wh-stack"><thead><tr><th>Vaqt</th><th>Bemor</th><th>Mahsulot</th><th class="wh-right">Miqdor</th><th>Partiyalar</th><th>Bergan xodim</th><th>Holat</th><th></th></tr></thead><tbody>' +
      h.rows.map((d) =>
        '<tr><td data-label="Vaqt" class="wh-nowrap">' + fmtDateTime(d.created_at) + '</td>' +
        '<td data-label="Bemor">' + esc(d.patient_name || '—') + '</td>' +
        '<td data-label="Mahsulot"><span class="wh-cell-name">' + esc(d.item_name) + '</span><span class="wh-cell-sub">' + esc([d.dosage, d.frequency].filter(Boolean).join(' · ')) +
          (d.prescription_id ? (d.dosage || d.frequency ? ' · ' : '') + 'Retsept ' + esc(d.prescription_id) : '') + '</span></td>' +
        '<td data-label="Miqdor" class="wh-right wh-num"><b>' + fmtQty(d.quantity) + '</b> ' + esc(d.base_unit) + '</td>' +
        '<td data-label="Partiyalar">' + (d.batches || []).map((b) => '<span class="wh-mono" title="Muddati: ' + esc(b.expiry_date || '—') + '">' + esc(b.batch_no || '—') + ' (' + fmtQty(b.quantity) + ')</span>').join('<br>') + '</td>' +
        '<td data-label="Bergan xodim">' + esc(d.dispensed_by || '—') + '<span class="wh-cell-sub">' + esc(SOURCE_LABEL[d.source] || d.source || '') + '</span></td>' +
        '<td data-label="Holat">' + badge(d.status, DISP_STATUS[d.status] || d.status) +
          (d.status === 'reversed' && d.reverse_reason ? '<span class="wh-cell-sub">' + esc(d.reverse_reason) + '</span>' : '') + '</td>' +
        '<td data-label="">' + (S.whWrite && d.status === 'completed'
          ? '<button type="button" class="wh-btn wh-btn-sm wh-btn-danger" data-action="ds-reverse" data-id="' + esc(d.id) + '"><i class="fas fa-rotate-left" aria-hidden="true"></i> Qaytarish</button>' : '') + '</td></tr>').join('') +
      '</tbody></table></div>';
    $('#ds-h-pager').innerHTML = pagerHtml({ offset: h.offset, limit: h.limit, total: h.total }, 'ds-h-page');
  }
  ACTIONS['ds-h-retry'] = () => loadDispHist();
  ACTIONS['ds-h-page'] = (t) => { DS.h.offset = Math.max(0, DS.h.offset + Number(t.dataset.dir) * DS.h.limit); loadDispHist(); };
  ACTIONS['ds-reverse'] = async (t) => {
    const d = DS.h.rows.find((x) => x.id === t.dataset.id);
    if (!d) return;
    const reason = await askReason({
      title: 'Dori berishni qaytarish', subtitle: d.id,
      message: '<b>' + esc(d.item_name) + '</b> — ' + plural(d.quantity, d.base_unit) + ' (' + esc(d.patient_name || '') + ') omborga qaytariladi.',
      confirmText: 'Qaytarish'
    });
    if (!reason) return;
    await runBusy(t, async () => {
      const r = await api('POST', '/dispensings/' + encodeURIComponent(d.id) + '/reverse', { reason: reason });
      if (!r.ok) { toast(r.data.error, 'error'); return; }
      toast('Dori berish qaytarildi: mahsulot omborga qaytdi.');
      invalidate();
      S.stale.dispensing = false;
      loadDispensing();
    });
  };

  // ===========================================================================
  // LEDGER (Harakatlar) and adjustments
  // ===========================================================================
  const LED = {
    item_id: '', itemLabel: '', type: '', from: '', to: '', patient_id: '', patientLabel: '', offset: 0, limit: 50,
    rows: [], total: 0, seq: 0, shell: false, itemCombo: null, patCombo: null, syncing: false
  };

  function ensureLedShell() {
    if (LED.shell) return;
    $('#panel-ledger').innerHTML =
      '<div class="wh-card"><div class="wh-toolbar">' +
        '<div class="wh-field wh-grow"><span class="wh-label">Mahsulot</span><div id="led-item"></div></div>' +
        '<label class="wh-field"><span class="wh-label">Harakat turi</span><select class="wh-select" id="led-type"><option value="">Barchasi</option>' +
          Object.keys(TXN_LABEL).map((k) => '<option value="' + k + '">' + esc(TXN_LABEL[k]) + '</option>').join('') + '</select></label>' +
        '<label class="wh-field"><span class="wh-label">Sanadan</span><input class="wh-input" type="date" id="led-from"></label>' +
        '<label class="wh-field"><span class="wh-label">Sanagacha</span><input class="wh-input" type="date" id="led-to"></label>' +
        '<div class="wh-field wh-grow"><span class="wh-label">Bemor</span><div id="led-patient"></div></div>' +
        '<div class="wh-toolbar-end">' +
          '<button type="button" class="wh-btn" data-action="led-reset"><i class="fas fa-filter-circle-xmark" aria-hidden="true"></i> Tozalash</button>' +
          (S.whWrite ? '<button type="button" class="wh-btn wh-btn-primary" data-action="adj-new"><i class="fas fa-sliders" aria-hidden="true"></i> Tuzatish kiritish</button>' : '') +
        '</div></div><div id="led-body"></div><div id="led-pager"></div></div>';
    LED.shell = true;
    const reload = () => { LED.offset = 0; loadLedger(); };
    LED.itemCombo = makeCombo($('#led-item'), {
      placeholder: 'Mahsulot nomi…', ariaLabel: 'Mahsulot bo\'yicha', source: itemSource({ active: '' }),
      onChange: (opt) => { if (LED.syncing) return; LED.item_id = opt ? opt.id : ''; LED.itemLabel = opt ? opt.label : ''; reload(); }
    });
    LED.patCombo = makeCombo($('#led-patient'), {
      placeholder: 'Bemor ismi yoki kodi…', ariaLabel: 'Bemor bo\'yicha', source: patientSource, minChars: 2, openOnFocus: false,
      onChange: (opt) => { if (LED.syncing) return; LED.patient_id = opt ? opt.id : ''; LED.patientLabel = opt ? opt.label : ''; reload(); }
    });
    [['led-type', 'type'], ['led-from', 'from'], ['led-to', 'to']].forEach((p) =>
      $('#' + p[0]).addEventListener('change', (e) => { LED[p[1]] = e.target.value; reload(); }));
  }

  function syncLedControls() {
    LED.syncing = true;
    try {
      if (LED.item_id && !LED.itemCombo.value) LED.itemCombo.set({ id: LED.item_id, label: LED.itemLabel || LED.item_id, sub: '' });
      if (!LED.item_id && LED.itemCombo.value) LED.itemCombo.clear();
      if (LED.patient_id && !LED.patCombo.value) LED.patCombo.set({ id: LED.patient_id, label: LED.patientLabel || LED.patient_id, sub: '' });
      if (!LED.patient_id && LED.patCombo.value) LED.patCombo.clear();
    } finally { LED.syncing = false; }
    $('#led-type').value = LED.type; $('#led-from').value = LED.from; $('#led-to').value = LED.to;
  }

  async function loadLedger() {
    ensureLedShell();
    syncLedControls();
    const mine = ++LED.seq;
    const body = $('#led-body');
    if (!LED.rows.length) body.innerHTML = loadingHtml(6);
    const r = await api('GET', '/transactions' + qs({ item_id: LED.item_id, type: LED.type, patient_id: LED.patient_id, from: LED.from, to: LED.to, limit: LED.limit, offset: LED.offset }));
    if (mine !== LED.seq) return;
    S.stale.ledger = false;
    if (!r.ok) { S.loaded.ledger = false; body.innerHTML = errorHtml(r.data.error, 'led-retry'); $('#led-pager').innerHTML = ''; return; }
    S.loaded.ledger = true;
    LED.rows = r.data.transactions || [];
    LED.total = r.data.total || 0;
    if (!LED.rows.length && LED.total > 0 && LED.offset > 0) { LED.offset = 0; loadLedger(); return; }
    renderLedger();
  }

  function renderLedger() {
    const body = $('#led-body');
    if (!LED.rows.length) {
      const filtered = LED.item_id || LED.type || LED.from || LED.to || LED.patient_id;
      body.innerHTML = emptyHtml('fa-clock-rotate-left', 'Harakat topilmadi', filtered ? 'Tanlangan filtrlarga mos harakat yo\'q.' : 'Kirim, berish va tuzatishlar shu yerda ko\'rinadi.',
        filtered ? '<button type="button" class="wh-btn" data-action="led-reset">Filtrlarni tozalash</button>' : '');
      $('#led-pager').innerHTML = '';
      return;
    }
    const costs = LED.rows[0].unit_cost !== undefined;
    const reversed = {};
    LED.rows.forEach((t) => { if (t.reversal_of) reversed[t.reversal_of] = t.id; });
    body.innerHTML = '<div class="wh-table-wrap"><table class="wh-table wh-stack wh-compact"><thead><tr><th>Vaqt</th><th>Tur</th><th>Mahsulot</th><th>Partiya</th><th class="wh-right">O\'zgarish</th><th class="wh-right">Qoldiq (oldin → keyin)</th>' +
      (costs ? '<th class="wh-right">Tannarx</th><th class="wh-right">Qiymat</th>' : '') + '<th>Sabab / bog\'liq</th><th>Xodim</th><th></th></tr></thead><tbody>' +
      LED.rows.map((t) => {
        const delta = Number(t.qty_delta);
        const links = [];
        if (t.reversal_of) links.push('↩ #' + esc(t.reversal_of) + ' qaytarildi');
        if (reversed[t.id]) links.push(badge('reversed', 'Qaytarilgan'));
        if (t.receipt_id) links.push('<button type="button" class="wh-btn wh-btn-sm wh-btn-ghost" style="min-height:22px;padding:0 4px" data-action="open-receipt" data-id="' + esc(t.receipt_id) + '">' + esc(t.receipt_id) + '</button>');
        if (t.dispensing_id) links.push('<span class="wh-mono">' + esc(t.dispensing_id) + '</span>');
        if (t.patient_id) links.push('Bemor ' + esc(t.patient_id));
        const canRev = S.whWrite && REVERSIBLE_TXN.indexOf(t.txn_type) >= 0 && !reversed[t.id] && !t.reversal_of;
        return '<tr><td data-label="Vaqt" class="wh-nowrap">' + fmtDateTime(t.created_at) + '<span class="wh-cell-sub wh-mono">#' + esc(t.id) + '</span></td>' +
          '<td data-label="Tur">' + badge(t.txn_type === 'reversal' ? 'reversal' : (delta >= 0 ? 'ok' : 'low'), TXN_LABEL[t.txn_type] || t.txn_type) + '</td>' +
          '<td data-label="Mahsulot"><button type="button" class="wh-btn wh-btn-ghost wh-btn-sm" style="padding:0;min-height:0;text-align:left;white-space:normal;font-weight:700" data-action="open-item" data-id="' + esc(t.item_id) + '">' + esc(t.item_name) + '</button></td>' +
          '<td data-label="Partiya"><span class="wh-mono">' + esc(t.batch_no || '—') + '</span></td>' +
          '<td data-label="O\'zgarish" class="wh-right wh-num"><span class="' + (delta >= 0 ? 'wh-qty-in' : 'wh-qty-out') + '">' + (delta > 0 ? '+' : '') + fmtQty(delta) + '</span> ' + esc(t.base_unit || '') + '</td>' +
          '<td data-label="Qoldiq" class="wh-right wh-num">' + fmtQty(t.balance_before) + ' → <b>' + fmtQty(t.balance_after) + '</b></td>' +
          (costs ? '<td data-label="Tannarx" class="wh-right wh-num">' + fmtMoney(t.unit_cost, true) + '</td><td data-label="Qiymat" class="wh-right wh-num">' + fmtMoney(t.value_delta) + '</td>' : '') +
          '<td data-label="Sabab">' + esc(t.reason || '') + (t.notes ? '<span class="wh-cell-sub">' + esc(t.notes) + '</span>' : '') + (links.length ? '<span class="wh-cell-sub">' + links.join(' · ') + '</span>' : '') + '</td>' +
          '<td data-label="Xodim">' + esc(t.performed_by || '—') + '<span class="wh-cell-sub">' + esc(SOURCE_LABEL[t.source] || '') + '</span></td>' +
          '<td data-label="">' + (canRev ? '<button type="button" class="wh-btn wh-btn-sm wh-btn-danger" data-action="txn-reverse" data-id="' + esc(t.id) + '"><i class="fas fa-rotate-left" aria-hidden="true"></i> Qaytarish</button>' : '') + '</td></tr>';
      }).join('') + '</tbody></table></div>';
    $('#led-pager').innerHTML = pagerHtml({ offset: LED.offset, limit: LED.limit, total: LED.total }, 'led-page');
  }

  ACTIONS['led-retry'] = () => loadLedger();
  ACTIONS['led-reset'] = () => {
    Object.assign(LED, { item_id: '', itemLabel: '', type: '', from: '', to: '', patient_id: '', patientLabel: '', offset: 0 });
    loadLedger();
  };
  ACTIONS['led-page'] = (t) => { LED.offset = Math.max(0, LED.offset + Number(t.dataset.dir) * LED.limit); loadLedger(); };
  ACTIONS['adj-new'] = () => openAdjustment(null);
  ACTIONS['txn-reverse'] = async (t) => {
    const row = LED.rows.find((x) => String(x.id) === t.dataset.id);
    if (!row) return;
    const reason = await askReason({
      title: 'Harakatni qaytarish', subtitle: '#' + row.id + ' · ' + (TXN_LABEL[row.txn_type] || row.txn_type),
      message: '<b>' + esc(row.item_name) + '</b>: ' + (Number(row.qty_delta) > 0 ? '+' : '') + fmtQty(row.qty_delta) + ' ' + esc(row.base_unit || '') + ' teskari yozuv bilan bekor qilinadi. Bir harakatni faqat bir marta qaytarish mumkin.',
      confirmText: 'Qaytarish'
    });
    if (!reason) return;
    await runBusy(t, async () => {
      const r = await api('POST', '/transactions/' + encodeURIComponent(row.id) + '/reverse', { reason: reason });
      if (!r.ok) { toast(r.data.error, 'error'); return; }
      toast('Harakat qaytarildi.');
      invalidate();
      loadLedger();
    });
  };

  // --- Adjustment form --------------------------------------------------------------
  const ADJ_UP = ['increase', 'patient_return'];

  function openAdjustment(preItem) {
    const reqId = newRequestId();
    let item = preItem ? { id: preItem.id, name: preItem.name, base_unit: preItem.base_unit, allow_fraction: preItem.allow_fraction, track_expiry: preItem.track_expiry } : null;
    let batches = preItem && preItem.batches ? preItem.batches : [];
    let patient = null;
    const layer = openLayer({
      title: 'Ombor qoldig\'ini tuzatish', subtitle: 'Sabab majburiy. Har bir tuzatish harakat daftariga yoziladi.', dismissOnBg: false,
      html: '<form novalidate data-adj-form><div class="wh-form-grid">' +
        field('Tuzatish turi', '<select class="wh-select" name="kind">' + ADJ_KINDS.map((k) => '<option value="' + k.id + '">' + esc(k.label) + '</option>').join('') + '</select>', { req: true, span: 2 }) +
        '<div class="wh-field wh-span-2"><span class="wh-label">Mahsulot <span class="wh-req">*</span></span><div data-combo></div></div>' +
        field('Partiya', '<select class="wh-select" name="batch_id"></select>', { hint: '<span data-batch-hint></span>' }) +
        field('Miqdor <span data-unit-label></span>', '<input class="wh-input" name="quantity" inputmode="decimal" autocomplete="off">', { req: true }) +
        field('Yaroqlilik muddati', '<input class="wh-input" type="date" name="expiry_date" min="' + todayISO() + '">', { cls: 'js-adj-expiry', hint: 'Yangi partiya ochilganda' }) +
        field('Yetkazib beruvchi', '<select class="wh-select" name="supplier_id">' + supplierOptions('', 'Ko\'rsatilmagan') + '</select>', { cls: 'js-adj-supplier', hidden: true }) +
        '<div class="wh-field js-adj-patient" hidden><span class="wh-label">Bemor</span><div data-pcombo></div><span class="wh-hint">Ixtiyoriy</span></div>' +
        field('Sabab', '<textarea class="wh-textarea" name="reason" maxlength="500" rows="2" placeholder="Nima uchun? (kamida 3 ta belgi)"></textarea>', { req: true, span: 'all' }) +
        '</div></form>',
      footer: '<button type="button" class="wh-btn" data-layer-close>Bekor qilish</button>' +
        '<button type="button" class="wh-btn wh-btn-primary" data-save><i class="fas fa-floppy-disk" aria-hidden="true"></i> Saqlash</button>'
    });
    const form = $('form', layer.body);
    loadSuppliers().then(() => { const s = $('[name="supplier_id"]', form); if (s) s.innerHTML = supplierOptions('', 'Ko\'rsatilmagan'); });
    const kindSel = $('[name="kind"]', form), batchSel = $('[name="batch_id"]', form);

    function paintBatches() {
      const up = ADJ_UP.indexOf(kindSel.value) >= 0;
      let h = '<option value="">' + (up ? 'Yangi partiya' : 'Avtomatik (eng yaqin muddatdan)') + '</option>';
      batches.forEach((b) => {
        const rem = Number(b.remaining_qty), rec = Number(b.received_qty);
        if (up ? rem >= rec : rem <= 0) return;   // returning into a full lot is impossible; taking from an empty one too
        h += '<option value="' + esc(b.id) + '">' + esc(b.batch_no || '#' + b.id) + ' · qoldiq ' + NF_QTY.format(rem) + (b.expiry_date ? ' · ' + fmtDate(b.expiry_date).replace(/<[^>]*>/g, '') : '') + '</option>';
      });
      batchSel.innerHTML = h;
      $('.js-adj-expiry', form).hidden = !up;
      $('.js-adj-supplier', form).hidden = kindSel.value !== 'supplier_return';
      $('.js-adj-patient', form).hidden = kindSel.value !== 'patient_return';
      $('[data-batch-hint]', form).textContent = !item ? 'Avval mahsulotni tanlang.' : (up ? 'Mavjud partiyaga qaytarish yoki yangisini ochish.' : 'Aniq partiyani tanlash mumkin.');
    }
    kindSel.addEventListener('change', paintBatches);
    function paintUnit() { $('[data-unit-label]', form).textContent = item ? '(' + item.base_unit + ')' : ''; }

    const combo = makeCombo($('[data-combo]', layer.body), {
      placeholder: 'Mahsulot nomi…', ariaLabel: 'Mahsulot', source: itemSource({ active: '' }),
      onChange: async (opt) => {
        item = opt ? opt.raw : null;
        batches = [];
        paintUnit(); paintBatches();
        if (item) {
          const r = await api('GET', '/items/' + encodeURIComponent(item.id));
          if (r.ok && item && item.id === r.data.id) { batches = r.data.batches || []; item = Object.assign({}, item, { allow_fraction: r.data.allow_fraction, track_expiry: r.data.track_expiry }); paintBatches(); }
        }
      }
    });
    if (item) combo.set(itemOption(Object.assign({ item_type: preItem.item_type, available_quantity: preItem.available_quantity }, preItem)));
    makeCombo($('[data-pcombo]', layer.body), {
      placeholder: 'Bemor ismi yoki kodi…', ariaLabel: 'Bemor', source: patientSource, minChars: 2, openOnFocus: false,
      onChange: (opt) => { patient = opt ? opt.id : null; }
    });
    paintUnit(); paintBatches();

    async function save(btn) {
      clearFormError(form);
      const kind = kindSel.value;
      if (!item) { fieldError(form, { error: 'Mahsulot tanlanmagan.' }); return; }
      const qEl = $('[name="quantity"]', form);
      const n = numCheck(qEl.value, 3);
      if (n === null || n <= 0) { fieldError(form, { field: 'quantity', error: "Miqdor noldan katta raqam bo'lishi kerak (ko'pi bilan 3 ta kasr)." }); return; }
      if (!item.allow_fraction && !Number.isInteger(n)) { fieldError(form, { field: 'quantity', error: item.name + ' butun sonlarda hisoblanadi: kasr miqdor kiritib bo\'lmaydi.' }); return; }
      const reasonText = $('[name="reason"]', form).value.replace(/\s+/g, ' ').trim();
      if (reasonText.length < 3) { fieldError(form, { field: 'reason', error: "Sabab kamida 3 ta belgidan iborat bo'lishi kerak." }); return; }
      const up = ADJ_UP.indexOf(kind) >= 0;
      const expiry = $('[name="expiry_date"]', form).value;
      if (up && !batchSel.value && item.track_expiry && !expiry) { fieldError(form, { field: 'expiry_date', error: 'Bu mahsulot uchun yaroqlilik muddati kiritilishi shart.' }); return; }
      const kindLabel = (ADJ_KINDS.find((k) => k.id === kind) || {}).label || kind;
      const ok = await confirmBox({
        title: 'Tuzatishni tasdiqlang',
        message: esc(kindLabel) + '<br><b>' + esc(item.name) + '</b>: <b>' + fmtQty(n) + ' ' + esc(item.base_unit) + '</b><br>Sabab: ' + esc(reasonText) + '<br>Ombor qoldig\'i darhol o\'zgaradi.',
        confirmText: 'Tasdiqlash', type: ADJ_UP.indexOf(kind) >= 0 ? 'primary' : 'warning'
      });
      if (!ok) return;
      await runBusy(btn, async () => {
        const body = { client_request_id: reqId, kind: kind, item_id: item.id, quantity: canonicalNumber(qEl.value), reason: reasonText };
        if (batchSel.value) body.batch_id = batchSel.value;
        if (up && !batchSel.value && expiry) body.expiry_date = expiry;
        if (kind === 'supplier_return' && $('[name="supplier_id"]', form).value) body.supplier_id = $('[name="supplier_id"]', form).value;
        if (kind === 'patient_return' && patient) body.patient_id = patient;
        const r = await api('POST', '/adjustments', body);
        if (!r.ok) {
          const e = Object.assign({}, r.data);
          if (r.status === 0) e.error += ' Natija noma\'lum: qayta bossangiz, takrorlanmaydi (xavfsiz).';
          fieldError(form, e);
          return;
        }
        layer.close();
        toast(r.status === 200 ? 'Bu tuzatish avval saqlangan: takror yozilmadi.' : 'Tuzatish saqlandi.', r.status === 200 ? 'info' : 'success');
        invalidate();
        const l = itemDrawer();
        if (l) paintItem(l);
        refreshCurrentTab();
      });
    }
    $('[data-save]', layer.foot).addEventListener('click', (e) => save(e.currentTarget));
    form.addEventListener('submit', (e) => { e.preventDefault(); save($('[data-save]', layer.foot)); });
  }

  // ===========================================================================
  // REPORTS (Hisobotlar)
  // ===========================================================================
  const RP = { name: 'stock', from: '', to: '', item: null, rep: null, shell: false, itemCombo: null, seq: 0 };
  const TOTAL_LABEL = {
    total_value: 'Jami qiymat', expired_value: "Muddati o'tgan qiymat", available_value: 'Yaroqli qiymat',
    total_amount: 'Jami summa (tasdiqlangan)', ok: 'Hisoblar mosligi', items_checked: 'Tekshirilgan mahsulotlar'
  };

  function reportDef() { return REPORTS.find((r) => r.id === RP.name) || REPORTS[0]; }

  function ensureReportShell() {
    if (RP.shell) return;
    const list = REPORTS.filter((r) => !r.cost || S.costs);
    if (!list.some((r) => r.id === RP.name)) RP.name = list[0].id;
    $('#panel-reports').innerHTML =
      '<div class="wh-card"><div class="wh-toolbar">' +
        '<label class="wh-field wh-grow"><span class="wh-label">Hisobot</span><select class="wh-select" id="rp-name">' +
          list.map((r) => '<option value="' + r.id + '">' + esc(r.label) + '</option>').join('') + '</select></label>' +
        '<label class="wh-field js-rp-dates"><span class="wh-label">Sanadan</span><input class="wh-input" type="date" id="rp-from"></label>' +
        '<label class="wh-field js-rp-dates"><span class="wh-label">Sanagacha</span><input class="wh-input" type="date" id="rp-to"></label>' +
        '<div class="wh-field wh-grow js-rp-item"><span class="wh-label">Mahsulot <span class="wh-req">*</span></span><div id="rp-item"></div></div>' +
        '<div class="wh-toolbar-end"><button type="button" class="wh-btn wh-btn-primary" data-action="rp-run"><i class="fas fa-play" aria-hidden="true"></i> Ko\'rsatish</button></div>' +
      '</div><div id="rp-actions" class="wh-chips" hidden></div><div id="rp-body"></div></div>';
    RP.shell = true;
    RP.itemCombo = makeCombo($('#rp-item'), {
      placeholder: 'Mahsulot nomi…', ariaLabel: 'Mahsulot', source: itemSource({ active: '' }),
      onChange: (opt) => { RP.item = opt; }
    });
    $('#rp-name').value = RP.name;
    $('#rp-name').addEventListener('change', (e) => { RP.name = e.target.value; RP.rep = null; paintReportControls(); renderReport(); });
    $('#rp-from').addEventListener('change', (e) => { RP.from = e.target.value; });
    $('#rp-to').addEventListener('change', (e) => { RP.to = e.target.value; });
    paintReportControls();
    renderReport();
  }

  function paintReportControls() {
    const d = reportDef();
    $$('.js-rp-dates').forEach((n) => { n.hidden = !d.dates; });
    $$('.js-rp-item').forEach((n) => { n.hidden = !d.item; });
  }

  function reportParams(extra) {
    const d = reportDef();
    return Object.assign({ from: d.dates ? RP.from : '', to: d.dates ? RP.to : '', item_id: d.item && RP.item ? RP.item.id : '' }, extra || {});
  }

  async function loadReports() {
    ensureReportShell();
    S.loaded.reports = true;
    S.stale.reports = false;
    if (RP.rep) runReport();     // keep the shown report fresh after changes elsewhere
  }

  async function runReport() {
    const d = reportDef();
    const body = $('#rp-body');
    if (d.item && !RP.item) { body.innerHTML = emptyHtml('fa-box-open', 'Mahsulotni tanlang', 'Bu hisobot bitta mahsulot bo\'yicha tuziladi.'); return; }
    if (RP.from && RP.to && RP.to < RP.from) { toast("Tugash sanasi boshlanish sanasidan oldin bo'lishi mumkin emas.", 'warning'); return; }
    const mine = ++RP.seq;
    body.innerHTML = loadingHtml(6);
    $('#rp-actions').hidden = true;
    const r = await api('GET', '/reports/' + encodeURIComponent(RP.name) + qs(reportParams()));
    if (mine !== RP.seq) return;
    if (!r.ok) { RP.rep = null; body.innerHTML = errorHtml(r.data.error, 'rp-run'); return; }
    RP.rep = r.data;
    RP.repName = RP.name;
    renderReport();
  }

  function reportCellText(col, v) {
    // Plain text (for Excel): same mapping as the screen, without markup.
    if (v === null || v === undefined || v === '') return '';
    if (typeof v === 'boolean') return v ? 'Ha' : "Yo'q";
    const codes = CODE_COLUMNS[col.key];
    if (codes && typeof v === 'string' && codes[v]) return codes[v];
    if (typeof v === 'number') return v;
    const s = String(v);
    let m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(s);
    if (m) return m[3] + '.' + m[2] + '.' + m[1] + ' ' + m[4] + ':' + m[5];
    m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
    return m ? m[3] + '.' + m[2] + '.' + m[1] : s;
  }
  function reportCellHtml(col, v) {
    if (v === null || v === undefined || v === '') return '—';
    if (typeof v === 'number') return col.cost ? fmtMoney(v, /unit_cost/.test(col.key)) : fmtQty(v);
    const t = reportCellText(col, v);
    return esc(t);
  }

  function renderReport() {
    const body = $('#rp-body');
    const rep = RP.rep;
    const acts = $('#rp-actions');
    if (!rep || RP.repName !== RP.name) {
      acts.hidden = true;
      body.innerHTML = emptyHtml('fa-file-lines', reportDef().label, 'Kerakli sozlamalarni tanlab, "Ko\'rsatish" tugmasini bosing.');
      return;
    }
    const cols = rep.columns || [], rows = rep.rows || [], totals = rep.totals || {};
    acts.hidden = false;
    acts.innerHTML = '<span class="wh-hint" style="align-self:center">' + rows.length + ' qator</span>' +
      '<button type="button" class="wh-btn wh-btn-sm" data-action="rp-csv"><i class="fas fa-file-csv" aria-hidden="true"></i> CSV (Excel uchun)</button>' +
      '<button type="button" class="wh-btn wh-btn-sm" data-action="rp-xlsx"><i class="fas fa-file-excel" aria-hidden="true"></i> Excel (.xlsx)</button>';
    const totalKeys = Object.keys(totals);
    const totalHtml = totalKeys.length ? '<div class="wh-card-body" style="padding-bottom:0"><dl class="wh-dl">' + totalKeys.map((k) => {
      let v = totals[k];
      if (k === 'ok') v = v ? '<span class="wh-qty-in">Hammasi mos</span>' : '<span class="wh-expired-text">Farq bor</span>';
      else if (/value|amount/.test(k)) v = '<b>' + fmtMoney(v) + '</b>';
      else v = fmtQty(v);
      return dlRow(TOTAL_LABEL[k] || k, v);
    }).join('') + '</dl></div>' : '';
    if (!rows.length) {
      body.innerHTML = totalHtml + (RP.name === 'reconciliation' && totals.ok
        ? '<div class="wh-card-body"><div class="wh-note is-ok">Ombor qoldig\'i, partiyalar va harakat daftari barcha mahsulotda mos keladi.</div></div>'
        : emptyHtml('fa-circle-check', 'Ma\'lumot yo\'q', 'Tanlangan hisobot bo\'yicha qator topilmadi.'));
      return;
    }
    body.innerHTML = totalHtml + '<div class="wh-table-wrap" style="margin-top:12px"><table class="wh-table wh-compact"><thead><tr>' +
      cols.map((c) => '<th scope="col">' + esc(c.label) + '</th>').join('') + '</tr></thead><tbody>' +
      rows.map((r) => '<tr>' + cols.map((c) => {
        const v = r[c.key];
        return '<td class="' + (typeof v === 'number' ? 'wh-right wh-num' : '') + '">' + reportCellHtml(c, v) + '</td>';
      }).join('') + '</tr>').join('') + '</tbody></table></div>';
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  ACTIONS['rp-run'] = () => runReport();
  ACTIONS['rp-csv'] = async (t) => {
    await runBusy(t, async () => {
      let res;
      try { res = await fetch(API + '/reports/' + encodeURIComponent(RP.repName) + qs(reportParams({ format: 'csv' })), { credentials: 'same-origin' }); }
      catch (e) { toast("Server bilan aloqa yo'q.", 'error'); return; }
      if (!res.ok) { toast('Faylni yuklab bo\'lmadi.', 'error'); return; }
      const blob = await res.blob();
      downloadBlob(blob, 'ombor-' + RP.repName + '-' + todayISO() + '.csv');
    });
  };

  let xlsxPromise = null;
  function loadXlsx() {
    if (window.XLSX) return Promise.resolve(window.XLSX);
    if (!xlsxPromise) {
      xlsxPromise = new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = 'js/xlsx.full.min.js';
        s.onload = () => (window.XLSX ? resolve(window.XLSX) : reject(new Error('xlsx')));
        s.onerror = () => reject(new Error('xlsx'));
        document.head.appendChild(s);
      }).catch((e) => { xlsxPromise = null; throw e; });
    }
    return xlsxPromise;
  }
  ACTIONS['rp-xlsx'] = async (t) => {
    const rep = RP.rep;
    if (!rep) return;
    await runBusy(t, async () => {
      let X;
      try { X = await loadXlsx(); } catch (e) { toast('Excel kutubxonasini yuklab bo\'lmadi. CSV dan foydalaning.', 'error'); return; }
      const cols = rep.columns || [];
      const aoa = [cols.map((c) => c.label)].concat((rep.rows || []).map((r) => cols.map((c) => reportCellText(c, r[c.key]))));
      const ws = X.utils.aoa_to_sheet(aoa);
      const wb = X.utils.book_new();
      const sheet = (reportDef().label || 'Hisobot').replace(/[\[\]:*?\/\\]/g, ' ').slice(0, 31);
      X.utils.book_append_sheet(wb, ws, sheet);
      X.writeFile(wb, 'ombor-' + RP.repName + '-' + todayISO() + '.xlsx');
    });
  };

  // ===========================================================================
  // TABS, REFRESH, START
  // ===========================================================================
  const TAB_DEFS = {
    dashboard: { allowed: () => S.whRead, load: loadDashboard },
    inventory: { allowed: () => S.whRead, load: loadInventory },
    receipts: { allowed: () => S.whRead, load: loadReceipts },
    dispensing: { allowed: () => S.whWrite, load: loadDispensing },
    ledger: { allowed: () => S.whRead, load: loadLedger },
    reports: { allowed: () => S.whRead, load: loadReports }
  };

  function switchTab(id) {
    if (!TAB_DEFS[id] || !TAB_DEFS[id].allowed()) id = 'dashboard';
    S.tab = id;
    $$('.wh-tab').forEach((b) => {
      const on = b.dataset.tab === id;
      b.setAttribute('aria-selected', on ? 'true' : 'false');
      b.tabIndex = on ? 0 : -1;
    });
    $$('.wh-panel').forEach((p) => { p.hidden = p.id !== 'panel-' + id; });
    if (location.hash !== '#' + id) { try { history.replaceState(null, '', '#' + id); } catch (e) { /* ignore */ } }
    if (!S.loaded[id] || S.stale[id]) TAB_DEFS[id].load();
  }

  function refreshCurrentTab() {
    const d = TAB_DEFS[S.tab];
    if (d) d.load();
  }

  $('#wh-tabs').addEventListener('click', (e) => {
    const b = e.target.closest('.wh-tab');
    if (b && !b.hidden) switchTab(b.dataset.tab);
  });
  $('#wh-tabs').addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const tabs = $$('.wh-tab').filter((b) => !b.hidden);
    const i = tabs.findIndex((b) => b.dataset.tab === S.tab);
    const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
    if (next) { e.preventDefault(); switchTab(next.dataset.tab); next.focus(); }
  });
  window.addEventListener('hashchange', () => {
    const id = location.hash.replace('#', '');
    if (id && id !== S.tab) switchTab(id);
  });
  $('#wh-refresh').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    await runBusy(btn, async () => {
      invalidate();
      await loadSuppliers(true);
      S.loaded.dashboard = false;
      await TAB_DEFS[S.tab].load();
    });
  });

  function fatal(message) {
    const box = $('#wh-fatal');
    box.hidden = false;
    box.innerHTML = '<i class="fas fa-lock" aria-hidden="true"></i><strong>' + esc(message) + '</strong>';
    $('#wh-tabs').hidden = true;
    $$('.wh-panel').forEach((p) => { p.hidden = true; });
  }

  async function init() {
    let sess = null;
    try {
      const r = await fetch('/api/auth/session', { credentials: 'same-origin', cache: 'no-store' });
      sess = await r.json();
    } catch (e) {
      fatal("Server bilan aloqa yo'q. Sahifani yangilab ko'ring.");
      return;
    }
    if (!sess || !sess.authenticated) { location.replace('/login.html?next=' + encodeURIComponent('/warehouse.html')); return; }
    if (sess.must_change_password) return;      // fmh_dialogs.js sends the person to change the password
    S.session = sess;
    S.perms = sess.permissions || [];
    S.whRead = can('warehouse', 'read');
    S.whWrite = can('warehouse', 'write');
    S.accWrite = S.whRead && can('accounting', 'write');
    if (!S.whRead) { fatal("Ombor bo'limiga kirish huquqingiz yo'q."); return; }
    $('#tab-dispensing').hidden = !S.whWrite;
    $('#wh-subtitle').textContent = S.whWrite
      ? (S.accWrite ? 'Qoldiq, kirim, dori berish va narxlar' : 'Qoldiq, dori berish va tuzatishlar')
      : 'Faqat ko\'rish rejimi';

    const dl = document.createElement('datalist');
    dl.id = 'wh-categories';
    document.body.appendChild(dl);

    const st = await api('GET', '/settings');
    if (st.ok) S.settings = Object.assign(S.settings, st.data);
    else toast('Sozlamalarni o\'qib bo\'lmadi: standart qiymatlar ishlatiladi.', 'warning');

    await loadDashboard();      // also tells us whether this role sees costs
    const start = location.hash.replace('#', '') || 'dashboard';
    switchTab(start);
  }

  init();
})();
