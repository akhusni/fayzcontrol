/**
 * FAYZ MEDICAL HOUSE — owner's money report (phone first).
 * Read-only: GET /api/owner/summary for the chosen period, then render.
 */
(function () {
  'use strict';

  const MONTHS = ['yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun',
    'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr'];
  const MONTHS_SHORT = ['yan', 'fev', 'mar', 'apr', 'may', 'iyn', 'iyl', 'avg', 'sen', 'okt', 'noy', 'dek'];
  const METHOD = { cash: 'Naqd', card: 'Karta', online: 'Click/Payme', bank: 'Bank' };
  const PAGE = 20;
  const STORE_KEY = 'fmh_owner_period';

  let report = null;
  let period = 'month';

  function esc(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // 26690000 -> "26 690 000 so'm" (narrow no-break spaces keep it on one line)
  function money(n) {
    const v = Math.round(Number(n) || 0);
    const s = Math.abs(v).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    return (v < 0 ? '−' : '') + s + " so'm";
  }

  // Large figures in the statement: "26,7 mln so'm"
  function moneyShort(n) {
    const v = Number(n) || 0;
    const a = Math.abs(v);
    const sign = v < 0 ? '−' : '';
    if (a >= 1e9) return `${sign}${(a / 1e9).toFixed(1).replace('.', ',')}<small>mlrd so'm</small>`;
    if (a >= 1e6) return `${sign}${(a / 1e6).toFixed(1).replace('.', ',')}<small>mln so'm</small>`;
    return esc(money(v));
  }

  function iso(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  function parseIso(s) {
    const [y, m, d] = s.split('-').map(Number);
    return new Date(y, m - 1, d);
  }

  function dayLabel(s) {
    const d = parseIso(s);
    return `${d.getDate()}-${MONTHS_SHORT[d.getMonth()]}`;
  }

  function rangeFor(p) {
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    switch (p) {
      case 'today': return [today, today];
      case 'week': return [new Date(today.getTime() - 6 * 864e5), today];
      case 'last_month': return [new Date(today.getFullYear(), today.getMonth() - 1, 1),
        new Date(today.getFullYear(), today.getMonth(), 0)];
      case 'year': return [new Date(today.getFullYear(), 0, 1), today];
      default: return [new Date(today.getFullYear(), today.getMonth(), 1), today];
    }
  }

  function describePeriod(start, end) {
    const a = parseIso(start);
    const b = parseIso(end);
    const todayIso = iso(new Date());
    if (start === end) {
      return `${start === todayIso ? 'Bugun, ' : ''}${a.getDate()} ${MONTHS[a.getMonth()]} ${a.getFullYear()}`;
    }
    if (a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth()) {
      return `${a.getDate()}–${b.getDate()} ${MONTHS[a.getMonth()]} ${a.getFullYear()}`;
    }
    return `${a.getDate()} ${MONTHS[a.getMonth()]} ${a.getFullYear()} — ${b.getDate()} ${MONTHS[b.getMonth()]} ${b.getFullYear()}`;
  }

  // ------------------------------------------------------------------
  // Loading
  // ------------------------------------------------------------------
  async function load(start, end) {
    document.getElementById('own-when').textContent = 'Yuklanmoqda…';
    try {
      const res = await fetch(`/api/owner/summary?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`);
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        document.getElementById('own-when').textContent = body.error || `Hisobotni yuklab bo'lmadi (${res.status}).`;
        if (window.FMH_Toast) window.FMH_Toast(body.error || "Hisobotni yuklab bo'lmadi", 'danger');
        return;
      }
      report = body;
      render();
    } catch (e) {
      document.getElementById('own-when').textContent = "Server bilan aloqa yo'q. Internetni tekshirib, qayta urining.";
    }
  }

  function choose(p) {
    period = p;
    try { localStorage.setItem(STORE_KEY, p); } catch (e) { /* private mode */ }
    document.querySelectorAll('.own-period').forEach(b => {
      b.setAttribute('aria-pressed', b.dataset.period === p ? 'true' : 'false');
    });
    const custom = document.getElementById('own-custom');
    if (p === 'custom') {
      custom.hidden = false;
      const s = document.getElementById('own-start');
      const e = document.getElementById('own-end');
      if (!s.value || !e.value) {
        const [a, b] = rangeFor('month');
        s.value = iso(a);
        e.value = iso(b);
      }
      return;
    }
    custom.hidden = true;
    const [a, b] = rangeFor(p);
    load(iso(a), iso(b));
  }

  // ------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------
  function render() {
    renderStatement();
    renderRiver();
    renderGroups('income', report.income_by_source, 'own-income-groups', "Bu davrda tushum yo'q.");
    renderGroups('expense', report.expense_by_category, 'own-expense-groups', "Bu davrda xarajat yozilmagan.");
    renderTransfer();
    renderChart();
    renderMethods();
    renderDebts();
    renderMeds();
  }

  function change(now, before) {
    if (!before) return null;
    return Math.round(((now - before) / Math.abs(before)) * 100);
  }

  function renderStatement() {
    document.getElementById('own-when').textContent = describePeriod(report.period.start, report.period.end);
    document.getElementById('own-income').innerHTML = moneyShort(report.income);
    document.getElementById('own-expense').innerHTML = moneyShort(report.expense);
    const net = report.net;
    const netEl = document.getElementById('own-net');
    netEl.innerHTML = moneyShort(net);
    netEl.closest('.own-line').classList.toggle('is-loss', net < 0);
    document.getElementById('own-net-label').textContent = net < 0 ? 'Zarar' : 'Qoldi';

    const p = report.previous;
    const parts = [];
    const ci = change(report.income, p.income);
    const ce = change(report.expense, p.expense);
    if (ci !== null) parts.push(`tushum <b>${ci >= 0 ? '▲' : '▼'} ${Math.abs(ci)}%</b>`);
    if (ce !== null) parts.push(`xarajat <b>${ce >= 0 ? '▲' : '▼'} ${Math.abs(ce)}%</b>`);
    document.getElementById('own-compare').innerHTML = parts.length
      ? `Oldingi ${report.period.days} kunga nisbatan: ${parts.join(', ')}`
      : '';
  }

  function per100(part, whole) {
    const v = (part / whole) * 100;
    return v > 0 && v < 0.5 ? "&lt;1 so'm" : `${Math.round(v)} so'm`;
  }

  function renderRiver() {
    const river = document.getElementById('own-river');
    const key = document.getElementById('own-river-key');
    const title = document.getElementById('own-river-title');
    const income = report.income;
    const expenses = report.expense_by_category;

    if (income <= 0) {
      title.textContent = "Har 100 so'm tushumdan";
      river.innerHTML = '';
      key.innerHTML = `<li><i style="background: var(--own-rule)"></i><span>Bu davrda tushum yo'q${report.expense > 0 ? `, lekin ${esc(money(report.expense))} sarflangan` : ''}.</span><b></b></li>`;
      return;
    }

    // Scale to whichever is larger, so a loss shows the overrun in red.
    const whole = Math.max(income, report.expense);
    const segs = [];
    expenses.forEach((g, i) => {
      segs.push({
        label: g.label,
        amount: g.amount,
        color: 'var(--own-out)',
        opacity: Math.max(0.35, 1 - i * 0.13),
      });
    });
    if (report.net > 0) {
      segs.push({ label: "Klinikada qoldi (foyda)", amount: report.net, color: 'var(--own-in)', opacity: 1 });
    }

    title.textContent = report.net >= 0
      ? "Har 100 so'm tushumdan"
      : "Xarajat tushumdan oshib ketdi";
    // In a loss the bar is as long as the spending; the hatched tail is the
    // part no income covered.
    river.innerHTML = segs.map(s =>
      `<span style="width: ${(s.amount / whole) * 100}%; background: ${s.color}; opacity: ${s.opacity}" title="${esc(s.label)}"></span>`
    ).join('') + (report.net < 0
      ? `<em class="own-river-over" style="width: ${((-report.net) / whole) * 100}%"></em>`
      : '');
    river.setAttribute('aria-label', segs.map(s => `${s.label}: ${Math.round((s.amount / income) * 100)} so'm`).join('; '));

    key.innerHTML = segs.map(s => `
      <li>
        <i style="background: ${s.color}; opacity: ${s.opacity}"></i>
        <span>${esc(s.label)}</span>
        <b>${per100(s.amount, income)}</b>
      </li>`).join('') + (report.net < 0
      ? `<li><i class="is-over"></i><span>Tushumdan ortiqcha sarflangan</span><b>${esc(money(-report.net))}</b></li>`
      : '');
  }

  function renderGroups(kind, groups, listId, emptyText) {
    const list = document.getElementById(listId);
    if (!groups.length) {
      list.innerHTML = `<li class="own-empty">${emptyText}</li>`;
      return;
    }
    const top = groups[0].amount || 1;
    list.innerHTML = groups.map(g => `
      <li class="${kind === 'income' ? 'is-in' : 'is-out'}">
        <button type="button" class="own-group-btn" aria-expanded="false" data-kind="${kind}" data-group="${esc(g.key)}">
          <span class="own-group-name">${esc(g.label)}<small>${g.count} ta</small></span>
          <span class="own-group-amount">${esc(money(g.amount))}<i class="fas fa-chevron-down" aria-hidden="true"></i></span>
          <span class="own-group-bar"><i style="width: ${Math.max(2, (g.amount / top) * 100)}%"></i></span>
        </button>
      </li>`).join('');
    list.querySelectorAll('.own-group-btn').forEach(btn => {
      btn.addEventListener('click', () => toggleGroup(btn));
    });
  }

  function toggleGroup(btn) {
    const li = btn.parentElement;
    const open = btn.getAttribute('aria-expanded') === 'true';
    const existing = li.querySelector('.own-entries-wrap');
    if (open) {
      btn.setAttribute('aria-expanded', 'false');
      if (existing) existing.remove();
      return;
    }
    btn.setAttribute('aria-expanded', 'true');
    const entries = report.entries.filter(e => e.type === btn.dataset.kind && e.group === btn.dataset.group);
    const groups = btn.dataset.kind === 'income' ? report.income_by_source : report.expense_by_category;
    const group = groups.find(g => g.key === btn.dataset.group);
    const wrap = document.createElement('div');
    wrap.className = 'own-entries-wrap';
    li.appendChild(wrap);
    // The server sends at most 600 rows; say so before the list, not after.
    const missing = group ? group.count - entries.length : 0;
    showEntries(wrap, entries, PAGE, missing > 0
      ? `Bu davrda ${group.count} ta yozuv bor, bu yerda oxirgi ${entries.length} tasi. Hammasini ko'rish uchun qisqaroq davr tanlang.`
      : '');
  }

  function showEntries(wrap, entries, count, note) {
    const shown = entries.slice(0, count);
    const items = shown.map(e => {
      const what = e.who || e.description || 'Izohsiz';
      const meta = [dayLabel(e.date), METHOD[e.method] || e.method];
      if (e.who && e.description) meta.push(e.description);
      if (Math.abs(e.total - e.amount) > 1) meta.push(`${money(e.total)} to'lovning bir qismi`);
      return `
        <li>
          <span class="own-entry-what">${esc(what)}</span>
          <span class="own-entry-amount">${esc(money(e.amount))}</span>
          <span class="own-entry-meta">${esc(meta.join(' • '))}</span>
        </li>`;
    }).join('');
    const rest = entries.length - shown.length;
    wrap.innerHTML = (note ? `<p class="own-hint">${esc(note)}</p>` : '')
      + `<ul class="own-entries">${items || '<li class="own-empty">Yozuv topilmadi.</li>'}</ul>`
      + (rest > 0 ? `<button type="button" class="own-more">Yana ${rest} ta ko'rsatish</button>` : '');
    const more = wrap.querySelector('.own-more');
    if (more) more.addEventListener('click', () => showEntries(wrap, entries, count + PAGE, note));
  }

  function renderTransfer() {
    const el = document.getElementById('own-transfer');
    if (report.transfers > 0) {
      el.hidden = false;
      el.textContent = `Kassadan bankka o'tkazilgan ${money(report.transfers)} xarajat emas — bu klinikaning o'z puli, faqat joyi o'zgargan.`;
    } else {
      el.hidden = true;
    }
  }

  // Days for a month, weeks up to four months, months beyond that.
  function buckets() {
    const days = report.daily;
    let size = 'day';
    if (days.length > 120) size = 'month';
    else if (days.length > 31) size = 'week';
    if (size === 'day') return days.map(d => ({ label: dayLabel(d.date), income: d.income, expense: d.expense }));
    const out = [];
    days.forEach((d, i) => {
      const dt = parseIso(d.date);
      const key = size === 'month' ? `${dt.getFullYear()}-${dt.getMonth()}` : Math.floor(i / 7);
      let b = out[out.length - 1];
      if (!b || b.key !== key) {
        b = { key, label: size === 'month' ? MONTHS_SHORT[dt.getMonth()] : dayLabel(d.date), income: 0, expense: 0 };
        out.push(b);
      }
      b.income += d.income;
      b.expense += d.expense;
    });
    return out;
  }

  function renderChart() {
    const host = document.getElementById('own-chart');
    const data = buckets();
    const max = Math.max(1, ...data.map(b => Math.max(b.income, b.expense)));
    if (data.every(b => !b.income && !b.expense)) {
      host.innerHTML = `<p class="own-empty">Bu davrda pul harakati yo'q.</p>`;
      return;
    }
    const W = 340, H = 180, top = 14, mid = 100, low = 160;
    const step = W / data.length;
    const bw = Math.max(2, Math.min(18, step * 0.62));
    const upH = mid - top, downH = low - mid;
    const bars = data.map((b, i) => {
      const x = i * step + (step - bw) / 2;
      const hi = (b.income / max) * upH;
      const he = (b.expense / max) * downH;
      const tip = `${b.label}: tushum ${money(b.income)}, xarajat ${money(b.expense)}`;
      return `<g><title>${esc(tip)}</title>`
        + (hi ? `<rect x="${x.toFixed(1)}" y="${(mid - hi).toFixed(1)}" width="${bw.toFixed(1)}" height="${hi.toFixed(1)}" rx="1.5" fill="var(--own-in)"/>` : '')
        + (he ? `<rect x="${x.toFixed(1)}" y="${mid + 1}" width="${bw.toFixed(1)}" height="${he.toFixed(1)}" rx="1.5" fill="var(--own-out)"/>` : '')
        + '</g>';
    }).join('');
    const first = data[0].label;
    const last = data[data.length - 1].label;
    host.innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Kunma-kun tushum va xarajat">
        <line x1="0" x2="${W}" y1="${mid + 0.5}" y2="${mid + 0.5}" stroke="var(--own-rule)" stroke-width="1"/>
        <text x="0" y="10" font-size="10" fill="var(--own-ink-3)">eng ko'p: ${esc(money(max))}</text>
        ${bars}
        <text x="0" y="${H - 4}" font-size="10" fill="var(--own-ink-3)">${esc(first)}</text>
        <text x="${W}" y="${H - 4}" font-size="10" fill="var(--own-ink-3)" text-anchor="end">${esc(last)}</text>
      </svg>`;
  }

  function renderMethods() {
    const tbody = document.querySelector('#own-methods tbody');
    tbody.innerHTML = report.by_method.length
      ? report.by_method.map(m => `
          <tr>
            <td>${esc(m.label)}</td>
            <td class="in">${esc(money(m.income))}</td>
            <td class="out">${esc(money(m.expense))}</td>
          </tr>`).join('')
      : `<tr><td colspan="3" class="own-empty">Bu davrda pul harakati yo'q.</td></tr>`;
  }

  function renderDebts() {
    const d = report.debts;
    document.getElementById('own-debt-total').innerHTML = d.count
      ? `${esc(money(d.total))}<small>${d.count} ta kelgan bemorning hisobi to'liq to'lanmagan. Hisob butun yotish muddati uchun yoziladi, shuning uchun bir qismi hali muddati kelmagan bo'lishi mumkin.</small>`
      : `0 so'm<small>Kelgan bemorlarning barcha hisoblari to'langan</small>`;
    document.getElementById('own-debts').innerHTML = d.top.map(x => `
      <li>
        <span class="own-entry-what">${esc(x.who)}</span>
        <span class="own-entry-amount">${esc(money(x.amount))}</span>
        <span class="own-entry-meta">${x.since ? esc(dayLabel(String(x.since).slice(0, 10))) + ' kuni yotqizilgan' : ''}</span>
      </li>`).join('');
  }

  function renderMeds() {
    const m = report.medicine_used;
    document.getElementById('own-med-summary').textContent = m.doses
      ? `${m.doses} ta doza berildi. Ombordagi dorilarning tannarxi: ${money(m.cost)}.`
      : "Bu davrda hamshiralar dori berganini belgilamagan.";
    document.getElementById('own-meds').innerHTML = m.top.map(x => `
      <li>
        <span class="own-entry-what">${esc(x.name)}</span>
        <span class="own-entry-amount">${esc(money(x.cost))}</span>
        <span class="own-entry-meta">${x.doses} doza • omborda <span class="${x.low ? 'is-low' : ''}">${x.left} ta qoldi${x.low ? ' — kam' : ''}</span></span>
      </li>`).join('');
  }

  // ------------------------------------------------------------------
  // Start
  // ------------------------------------------------------------------
  function init() {
    document.querySelectorAll('.own-period').forEach(b => {
      b.addEventListener('click', () => choose(b.dataset.period));
    });
    document.getElementById('own-apply').addEventListener('click', () => {
      const s = document.getElementById('own-start').value;
      const e = document.getElementById('own-end').value;
      if (!s || !e) {
        if (window.FMH_Toast) window.FMH_Toast('Ikkala sanani tanlang', 'warning');
        return;
      }
      if (s > e) {
        if (window.FMH_Toast) window.FMH_Toast("Boshlanish sanasi tugash sanasidan keyin bo'lishi mumkin emas", 'warning');
        return;
      }
      load(s, e);
    });
    let saved = null;
    try { saved = localStorage.getItem(STORE_KEY); } catch (e) { /* private mode */ }
    choose(saved && saved !== 'custom' ? saved : 'month');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
