/**
 * FAYZ MEDICAL HOUSE — OWNER DASHBOARD & FINANCIAL ANALYTICS
 * Read-only executive financial suite:
 * GET /api/owner/summary for the chosen period.
 * Fully responsive: Phones, Tablets, Desktops.
 * Integrated with theme_engine.js and Chart.js.
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
  let chartType = 'bar'; // 'bar' | 'line'
  let chartMetric = 'all'; // 'all' | 'net'

  // Chart.js instances
  let trendChartInstance = null;
  let incomeDonutInstance = null;
  let expenseDonutInstance = null;
  let methodsChartInstance = null;

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
    if (!s) return new Date();
    const [y, m, d] = String(s).slice(0, 10).split('-').map(Number);
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

  // Theme-aware colors
  function getThemeColors() {
    const isDay = document.documentElement.getAttribute('data-theme') === 'day' ||
                  document.documentElement.getAttribute('data-theme') === 'light' ||
                  (document.body && (document.body.classList.contains('day-mode') || document.body.classList.contains('light-mode')));
    return {
      isDay,
      textColor: isDay ? '#475569' : '#94a3b8',
      textStrong: isDay ? '#0f172a' : '#f8fafc',
      gridColor: isDay ? 'rgba(15, 23, 42, 0.07)' : 'rgba(255, 255, 255, 0.06)',
      cardBg: isDay ? '#ffffff' : '#0c1830',
      teal: isDay ? '#0f766e' : '#5eead4',
      tealFill: isDay ? 'rgba(15, 118, 110, 0.16)' : 'rgba(94, 234, 212, 0.18)',
      coral: isDay ? '#c2410c' : '#fdba74',
      coralFill: isDay ? 'rgba(194, 65, 12, 0.14)' : 'rgba(253, 186, 116, 0.18)',
      emerald: isDay ? '#059669' : '#34d399',
      emeraldFill: isDay ? 'rgba(5, 150, 105, 0.14)' : 'rgba(52, 211, 153, 0.18)',
      lavender: isDay ? '#6d28d9' : '#c4b5fd',
      rose: isDay ? '#be123c' : '#fb7185',
    };
  }

  // ------------------------------------------------------------------
  // Loading & Period Selection
  // ------------------------------------------------------------------
  async function load(start, end) {
    const whenEl = document.getElementById('own-when');
    const refreshBtn = document.getElementById('own-refresh');
    if (whenEl) whenEl.textContent = 'Yuklanmoqda…';
    if (refreshBtn) {
      const icon = refreshBtn.querySelector('i');
      if (icon) icon.classList.add('fa-spin');
    }

    try {
      const res = await fetch(`/api/owner/summary?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`);
      const body = await res.json().catch(() => ({}));
      if (refreshBtn) {
        const icon = refreshBtn.querySelector('i');
        if (icon) icon.classList.remove('fa-spin');
      }

      if (!res.ok) {
        const errText = body.error || `Hisobotni yuklab bo'lmadi (${res.status}).`;
        if (whenEl) whenEl.textContent = errText;
        if (window.FMH_Toast) window.FMH_Toast(errText, 'danger');
        return;
      }
      report = body;
      render();
    } catch (e) {
      if (refreshBtn) {
        const icon = refreshBtn.querySelector('i');
        if (icon) icon.classList.remove('fa-spin');
      }
      if (whenEl) whenEl.textContent = "Server bilan aloqa yo'q. Internetni tekshirib, qayta urining.";
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
      if (custom) custom.hidden = false;
      const s = document.getElementById('own-start');
      const e = document.getElementById('own-end');
      if (s && e && (!s.value || !e.value)) {
        const [a, b] = rangeFor('month');
        s.value = iso(a);
        e.value = iso(b);
      }
      return;
    }
    if (custom) custom.hidden = true;
    const [a, b] = rangeFor(p);
    load(iso(a), iso(b));
  }

  // ------------------------------------------------------------------
  // Master Render
  // ------------------------------------------------------------------
  function render() {
    if (!report) return;
    renderStatement();
    renderQuickStats();
    renderRiver();
    renderTrendChart();
    renderDonutCharts();
    renderGroups('income', report.income_by_source, 'own-income-groups', "Bu davrda tushum yo'q.");
    renderGroups('expense', report.expense_by_category, 'own-expense-groups', "Bu davrda xarajat yozilmagan.");
    renderTransfer();
    renderMethods();
    renderDebts();
    renderMeds();
  }

  function change(now, before) {
    if (!before) return null;
    return Math.round(((now - before) / Math.abs(before)) * 100);
  }

  function renderStatement() {
    const whenEl = document.getElementById('own-when');
    if (whenEl) whenEl.textContent = describePeriod(report.period.start, report.period.end);

    // Income
    const incomeEl = document.getElementById('own-income');
    if (incomeEl) incomeEl.innerHTML = moneyShort(report.income);
    const incomeFullEl = document.getElementById('own-income-full');
    if (incomeFullEl) incomeFullEl.textContent = money(report.income);
    const incomeCountEl = document.getElementById('own-income-count');
    const incomeOps = (report.income_by_source || []).reduce((acc, x) => acc + (x.count || 0), 0);
    if (incomeCountEl) incomeCountEl.textContent = `${incomeOps} ta to'lov`;

    // Expense
    const expenseEl = document.getElementById('own-expense');
    if (expenseEl) expenseEl.innerHTML = moneyShort(report.expense);
    const expenseFullEl = document.getElementById('own-expense-full');
    if (expenseFullEl) expenseFullEl.textContent = money(report.expense);
    const expenseCountEl = document.getElementById('own-expense-count');
    const expenseOps = (report.expense_by_category || []).reduce((acc, x) => acc + (x.count || 0), 0);
    if (expenseCountEl) expenseCountEl.textContent = `${expenseOps} ta xarajat`;

    // Net
    const net = report.net;
    const netEl = document.getElementById('own-net');
    if (netEl) netEl.innerHTML = moneyShort(net);
    const netFullEl = document.getElementById('own-net-full');
    if (netFullEl) netFullEl.textContent = money(net);
    const netLabel = document.getElementById('own-net-label');
    if (netLabel) netLabel.textContent = net < 0 ? 'Zarar' : 'Qoldi (Sof Foyda)';

    const netCard = document.querySelector('.own-kpi-net');
    if (netCard) netCard.classList.toggle('is-loss', net < 0);

    const netMarginEl = document.getElementById('own-net-margin');
    if (netMarginEl) {
      if (report.income > 0) {
        const marginPct = ((net / report.income) * 100).toFixed(1);
        netMarginEl.textContent = `${marginPct}% marja`;
        netMarginEl.style.display = 'inline-block';
      } else {
        netMarginEl.style.display = 'none';
      }
    }

    // Previous period comparisons
    const p = report.previous || {};
    const ci = change(report.income, p.income);
    const ce = change(report.expense, p.expense);

    const trendIncomeEl = document.getElementById('own-trend-income');
    if (trendIncomeEl) {
      if (ci !== null) {
        trendIncomeEl.className = `own-kpi-trend ${ci >= 0 ? 'is-up' : 'is-down'}`;
        trendIncomeEl.innerHTML = `${ci >= 0 ? '▲' : '▼'} ${Math.abs(ci)}%`;
        trendIncomeEl.style.display = 'inline-block';
      } else {
        trendIncomeEl.style.display = 'none';
      }
    }

    const trendExpenseEl = document.getElementById('own-trend-expense');
    if (trendExpenseEl) {
      if (ce !== null) {
        trendExpenseEl.className = `own-kpi-trend ${ce >= 0 ? 'is-down' : 'is-up'}`;
        trendExpenseEl.innerHTML = `${ce >= 0 ? '▲' : '▼'} ${Math.abs(ce)}%`;
        trendExpenseEl.style.display = 'inline-block';
      } else {
        trendExpenseEl.style.display = 'none';
      }
    }

    const compareEl = document.getElementById('own-compare');
    if (compareEl) {
      const parts = [];
      if (ci !== null) parts.push(`tushum <span class="${ci >= 0 ? 'up' : 'down'}">${ci >= 0 ? '▲' : '▼'} ${Math.abs(ci)}%</span>`);
      if (ce !== null) parts.push(`xarajat <span class="${ce >= 0 ? 'down' : 'up'}">${ce >= 0 ? '▲' : '▼'} ${Math.abs(ce)}%</span>`);
      compareEl.innerHTML = parts.length
        ? `Oldingi ${report.period.days} kunga nisbatan: ${parts.join(', ')}`
        : '';
    }

    // Debt KPI
    const d = report.debts || { total: 0, count: 0 };
    const debtEl = document.getElementById('own-debt-total');
    if (debtEl) debtEl.innerHTML = moneyShort(d.total);
    const debtBadgeEl = document.getElementById('own-debt-count-badge');
    if (debtBadgeEl) debtBadgeEl.textContent = `${d.count} ta bemor`;
    const debtSummaryEl = document.getElementById('own-debt-summary');
    if (debtSummaryEl) debtSummaryEl.textContent = `${money(d.total)} qarzdorlik`;
  }

  function renderQuickStats() {
    const days = Math.max(1, (report.period && report.period.days) || 1);
    const avgDaily = report.income / days;
    const avgEl = document.getElementById('own-avg-daily');
    if (avgEl) avgEl.textContent = `${money(avgDaily)} / kun`;

    const medCostQuick = document.getElementById('own-med-cost-quick');
    if (medCostQuick) {
      const m = report.medicine_used || {};
      medCostQuick.textContent = `${money(m.cost || 0)} (${m.doses || 0} doza)`;
    }

    const transferQuick = document.getElementById('own-transfer-quick');
    if (transferQuick) {
      transferQuick.textContent = report.transfers > 0 ? money(report.transfers) : "O'tkazma yo'q";
    }
  }

  function per100(part, whole) {
    const v = (part / whole) * 100;
    return v > 0 && v < 0.5 ? "&lt;1 so'm" : `${Math.round(v)} so'm`;
  }

  function renderRiver() {
    const river = document.getElementById('own-river');
    const key = document.getElementById('own-river-key');
    const title = document.getElementById('own-river-title');
    if (!river || !key || !title) return;

    const income = report.income;
    const expenses = report.expense_by_category || [];

    if (income <= 0) {
      title.innerHTML = `<i class="fas fa-money-bill-wave"></i> Har 100 so'm tushumdan`;
      river.innerHTML = '';
      key.innerHTML = `<li><i style="background: var(--own-rule)"></i><span>Bu davrda tushum yo'q${report.expense > 0 ? `, lekin ${esc(money(report.expense))} sarflangan` : ''}.</span><b></b></li>`;
      return;
    }

    const whole = Math.max(income, report.expense);
    const segs = [];
    expenses.forEach((g, i) => {
      segs.push({
        label: g.label,
        amount: g.amount,
        color: 'var(--own-out)',
        opacity: Math.max(0.35, 1 - i * 0.12),
      });
    });
    if (report.net > 0) {
      segs.push({ label: "Klinikada qoldi (sof foyda)", amount: report.net, color: 'var(--own-net)', opacity: 1 });
    }

    title.innerHTML = report.net >= 0
      ? `<i class="fas fa-money-bill-wave"></i> Har 100 so'm tushumdan`
      : `<i class="fas fa-triangle-exclamation"></i> Xarajat tushumdan oshib ketdi`;

    river.innerHTML = segs.map(s =>
      `<span style="width: ${(s.amount / whole) * 100}%; background: ${s.color}; opacity: ${s.opacity}" title="${esc(s.label)}: ${per100(s.amount, income)}"></span>`
    ).join('') + (report.net < 0
      ? `<em class="own-river-over" style="width: ${((-report.net) / whole) * 100}%" title="Tushumdan ortiqcha"></em>`
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

  // ------------------------------------------------------------------
  // Interactive Daily Trend Chart (Chart.js)
  // ------------------------------------------------------------------
  function buckets() {
    const days = report.daily || [];
    let size = 'day';
    if (days.length > 120) size = 'month';
    else if (days.length > 31) size = 'week';

    if (size === 'day') {
      return days.map(d => ({
        label: dayLabel(d.date),
        date: d.date,
        income: d.income,
        expense: d.expense,
        net: d.income - d.expense,
      }));
    }

    const out = [];
    days.forEach((d, i) => {
      const dt = parseIso(d.date);
      const key = size === 'month' ? `${dt.getFullYear()}-${dt.getMonth()}` : Math.floor(i / 7);
      let b = out[out.length - 1];
      if (!b || b.key !== key) {
        b = {
          key,
          label: size === 'month' ? MONTHS_SHORT[dt.getMonth()] : dayLabel(d.date),
          date: d.date,
          income: 0,
          expense: 0,
          net: 0,
        };
        out.push(b);
      }
      b.income += d.income;
      b.expense += d.expense;
      b.net += (d.income - d.expense);
    });
    return out;
  }

  function renderTrendChart() {
    const canvas = document.getElementById('own-main-chart');
    if (!canvas || !window.Chart) {
      renderFallbackSvgChart();
      return;
    }

    const data = buckets();
    if (!data.length || data.every(b => !b.income && !b.expense)) {
      if (trendChartInstance) { trendChartInstance.destroy(); trendChartInstance = null; }
      const container = document.getElementById('own-chart-container');
      if (container) container.innerHTML = `<canvas id="own-main-chart"></canvas><p class="own-empty" style="text-align:center;padding:40px 0;">Bu davrda pul harakati yo'q.</p>`;
      return;
    }

    const theme = getThemeColors();
    const labels = data.map(d => d.label);
    const incomeData = data.map(d => d.income);
    const expenseData = data.map(d => d.expense);
    const netData = data.map(d => d.net);

    let datasets = [];
    if (chartMetric === 'all') {
      if (chartType === 'line') {
        datasets = [
          {
            label: 'Tushum',
            data: incomeData,
            borderColor: theme.teal,
            backgroundColor: theme.tealFill,
            borderWidth: 2.5,
            fill: true,
            tension: 0.35,
            pointRadius: data.length > 31 ? 1 : 3.5,
            pointHoverRadius: 6,
          },
          {
            label: 'Xarajat',
            data: expenseData,
            borderColor: theme.coral,
            backgroundColor: theme.coralFill,
            borderWidth: 2.5,
            fill: true,
            tension: 0.35,
            pointRadius: data.length > 31 ? 1 : 3.5,
            pointHoverRadius: 6,
          },
          {
            label: 'Sof Foyda',
            data: netData,
            borderColor: theme.emerald,
            borderWidth: 2,
            borderDash: [4, 4],
            fill: false,
            tension: 0.35,
            pointRadius: data.length > 31 ? 0 : 2.5,
            pointHoverRadius: 5,
          }
        ];
      } else {
        datasets = [
          {
            label: 'Tushum',
            data: incomeData,
            backgroundColor: theme.teal,
            borderRadius: 5,
            borderSkipped: false,
          },
          {
            label: 'Xarajat',
            data: expenseData,
            backgroundColor: theme.coral,
            borderRadius: 5,
            borderSkipped: false,
          }
        ];
      }
    } else {
      // Net Profit only
      datasets = [
        {
          label: 'Sof Qoldiq',
          data: netData,
          backgroundColor: data.map(d => d.net >= 0 ? theme.emerald : theme.rose),
          borderColor: theme.emerald,
          borderWidth: chartType === 'line' ? 2.5 : 0,
          fill: chartType === 'line',
          tension: 0.35,
          borderRadius: 5,
        }
      ];
    }

    if (trendChartInstance) {
      trendChartInstance.destroy();
    }

    const ctx = canvas.getContext('2d');
    trendChartInstance = new window.Chart(ctx, {
      type: chartType,
      data: {
        labels: labels,
        datasets: datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'index',
          intersect: false,
        },
        plugins: {
          legend: {
            display: false, // Custom HTML legend below
          },
          tooltip: {
            backgroundColor: theme.isDay ? 'rgba(15, 23, 42, 0.92)' : 'rgba(12, 24, 48, 0.95)',
            titleColor: '#f8fafc',
            bodyColor: '#cbd5e1',
            padding: 12,
            boxPadding: 6,
            usePointStyle: true,
            callbacks: {
              label: function (ctx) {
                return ` ${ctx.dataset.label}: ${money(ctx.raw)}`;
              }
            }
          }
        },
        scales: {
          x: {
            grid: {
              display: false,
            },
            ticks: {
              color: theme.textColor,
              font: { family: 'Plus Jakarta Sans', size: 11 },
              maxRotation: 0,
              autoSkip: true,
              maxTicksLimit: 14,
            }
          },
          y: {
            grid: {
              color: theme.gridColor,
            },
            ticks: {
              color: theme.textColor,
              font: { family: 'Plus Jakarta Sans', size: 11 },
              callback: function (val) {
                if (Math.abs(val) >= 1e6) return (val / 1e6).toFixed(0) + ' mln';
                if (Math.abs(val) >= 1e3) return (val / 1e3).toFixed(0) + ' ming';
                return val;
              }
            }
          }
        }
      }
    });
  }

  // Fallback SVG chart when Chart.js isn't available
  function renderFallbackSvgChart() {
    const host = document.getElementById('own-chart');
    if (!host) return;
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

  // ------------------------------------------------------------------
  // Donut Charts (Income & Expense breakdowns)
  // ------------------------------------------------------------------
  function renderDonutCharts() {
    if (!window.Chart) return;
    const theme = getThemeColors();

    // 1. Income Donut
    const incomeCanvas = document.getElementById('own-income-donut');
    if (incomeCanvas) {
      if (incomeDonutInstance) { incomeDonutInstance.destroy(); incomeDonutInstance = null; }
      const sources = report.income_by_source || [];
      if (sources.length && report.income > 0) {
        const colors = [
          '#14b8a6', '#06b6d4', '#0ea5e9', '#3b82f6', '#6366f1', '#8b5cf6', '#a855f7'
        ];
        incomeDonutInstance = new window.Chart(incomeCanvas.getContext('2d'), {
          type: 'doughnut',
          data: {
            labels: sources.map(s => s.label),
            datasets: [{
              data: sources.map(s => s.amount),
              backgroundColor: colors.slice(0, sources.length),
              borderWidth: 2,
              borderColor: theme.cardBg,
              hoverOffset: 6,
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '68%',
            plugins: {
              legend: {
                position: 'bottom',
                labels: {
                  color: theme.textColor,
                  font: { family: 'Plus Jakarta Sans', size: 11 },
                  boxWidth: 10,
                  padding: 8,
                }
              },
              tooltip: {
                callbacks: {
                  label: function (ctx) {
                    const total = report.income || 1;
                    const pct = Math.round((ctx.raw / total) * 100);
                    return ` ${ctx.label}: ${money(ctx.raw)} (${pct}%)`;
                  }
                }
              }
            }
          }
        });
      }
    }

    // 2. Expense Donut
    const expenseCanvas = document.getElementById('own-expense-donut');
    if (expenseCanvas) {
      if (expenseDonutInstance) { expenseDonutInstance.destroy(); expenseDonutInstance = null; }
      const cats = report.expense_by_category || [];
      if (cats.length && report.expense > 0) {
        const colors = [
          '#f97316', '#fb923c', '#f43f5e', '#e11d48', '#a855f7', '#ec4899', '#eab308', '#84cc16'
        ];
        expenseDonutInstance = new window.Chart(expenseCanvas.getContext('2d'), {
          type: 'doughnut',
          data: {
            labels: cats.map(c => c.label),
            datasets: [{
              data: cats.map(c => c.amount),
              backgroundColor: colors.slice(0, cats.length),
              borderWidth: 2,
              borderColor: theme.cardBg,
              hoverOffset: 6,
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '68%',
            plugins: {
              legend: {
                position: 'bottom',
                labels: {
                  color: theme.textColor,
                  font: { family: 'Plus Jakarta Sans', size: 11 },
                  boxWidth: 10,
                  padding: 8,
                }
              },
              tooltip: {
                callbacks: {
                  label: function (ctx) {
                    const total = report.expense || 1;
                    const pct = Math.round((ctx.raw / total) * 100);
                    return ` ${ctx.label}: ${money(ctx.raw)} (${pct}%)`;
                  }
                }
              }
            }
          }
        });
      }
    }

    // 3. Payment Methods Horizontal Bar Chart
    const methodsCanvas = document.getElementById('own-methods-chart');
    if (methodsCanvas) {
      if (methodsChartInstance) { methodsChartInstance.destroy(); methodsChartInstance = null; }
      const methods = report.by_method || [];
      if (methods.length) {
        methodsChartInstance = new window.Chart(methodsCanvas.getContext('2d'), {
          type: 'bar',
          data: {
            labels: methods.map(m => m.label),
            datasets: [
              {
                label: 'Tushdi',
                data: methods.map(m => m.income),
                backgroundColor: theme.teal,
                borderRadius: 4,
              },
              {
                label: 'Chiqdi',
                data: methods.map(m => m.expense),
                backgroundColor: theme.coral,
                borderRadius: 4,
              }
            ]
          },
          options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false },
              tooltip: {
                callbacks: {
                  label: function (ctx) {
                    return ` ${ctx.dataset.label}: ${money(ctx.raw)}`;
                  }
                }
              }
            },
            scales: {
              x: {
                grid: { color: theme.gridColor },
                ticks: {
                  color: theme.textColor,
                  font: { family: 'Plus Jakarta Sans', size: 10 },
                  callback: function (val) {
                    if (Math.abs(val) >= 1e6) return (val / 1e6).toFixed(0) + ' mln';
                    return val;
                  }
                }
              },
              y: {
                grid: { display: false },
                ticks: {
                  color: theme.textStrong,
                  font: { family: 'Plus Jakarta Sans', size: 11, weight: '600' },
                }
              }
            }
          }
        });
      }
    }
  }

  // ------------------------------------------------------------------
  // Interactive Drill-Down Accordion Groups
  // ------------------------------------------------------------------
  function renderGroups(kind, groups, listId, emptyText) {
    const list = document.getElementById(listId);
    if (!list) return;
    if (!groups || !groups.length) {
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
    const entries = (report.entries || []).filter(e => e.type === btn.dataset.kind && e.group === btn.dataset.group);
    const groups = btn.dataset.kind === 'income' ? report.income_by_source : report.expense_by_category;
    const group = (groups || []).find(g => g.key === btn.dataset.group);
    const wrap = document.createElement('div');
    wrap.className = 'own-entries-wrap';
    li.appendChild(wrap);
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
    if (!el) return;
    if (report.transfers > 0) {
      el.hidden = false;
      el.textContent = `Kassadan bankka o'tkazilgan ${money(report.transfers)} xarajat emas — bu klinikaning o'z puli, faqat joyi o'zgargan (inkassatsiya).`;
    } else {
      el.hidden = true;
    }
  }

  function renderMethods() {
    const tbody = document.querySelector('#own-methods tbody');
    if (!tbody) return;
    tbody.innerHTML = (report.by_method || []).length
      ? report.by_method.map(m => `
          <tr>
            <td><strong>${esc(m.label)}</strong></td>
            <td class="in">${esc(money(m.income))}</td>
            <td class="out">${esc(money(m.expense))}</td>
          </tr>`).join('')
      : `<tr><td colspan="3" class="own-empty">Bu davrda pul harakati yo'q.</td></tr>`;
  }

  function renderDebts() {
    const d = report.debts || { top: [], total: 0, count: 0 };
    const debtsList = document.getElementById('own-debts');
    if (!debtsList) return;

    if (!d.top || !d.top.length) {
      debtsList.innerHTML = `<li class="own-empty">Barcha hisoblar to'liq to'langan.</li>`;
      return;
    }

    debtsList.innerHTML = d.top.map(x => `
      <li>
        <span class="own-entry-what"><strong>${esc(x.who)}</strong></span>
        <span class="own-entry-amount" style="color:var(--own-debt)">${esc(money(x.amount))}</span>
        <span class="own-entry-meta">${x.since ? esc(dayLabel(String(x.since).slice(0, 10))) + ' sanasida yotqizilgan' : 'Faol kurs'}</span>
      </li>`).join('');
  }

  function renderMeds() {
    const m = report.medicine_used || { top: [], cost: 0, doses: 0 };
    const medSummary = document.getElementById('own-med-summary');
    if (medSummary) {
      medSummary.textContent = m.doses
        ? `${m.doses} ta doza berildi. Ombordagi dorilarning umumiy tannarxi: ${money(m.cost)}.`
        : "Bu davrda hamshiralar dori berganini belgilamagan.";
    }

    const medsList = document.getElementById('own-meds');
    if (!medsList) return;

    if (!m.top || !m.top.length) {
      medsList.innerHTML = `<li class="own-empty">Dori sarfi yozilmagan.</li>`;
      return;
    }

    medsList.innerHTML = m.top.map(x => `
      <li>
        <span class="own-entry-what"><strong>${esc(x.name)}</strong></span>
        <span class="own-entry-amount">${esc(money(x.cost))}</span>
        <span class="own-entry-meta">${x.doses} doza • omborda <span class="${x.low ? 'is-low' : ''}">${x.left} ta qoldi${x.low ? ' — kam!' : ''}</span></span>
      </li>`).join('');
  }

  // ------------------------------------------------------------------
  // Start & Event Listeners
  // ------------------------------------------------------------------
  function init() {
    // Period buttons
    document.querySelectorAll('.own-period').forEach(b => {
      b.addEventListener('click', () => choose(b.dataset.period));
    });

    // Custom date range
    const applyBtn = document.getElementById('own-apply');
    if (applyBtn) {
      applyBtn.addEventListener('click', () => {
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
    }

    // Refresh tool button
    const refreshBtn = document.getElementById('own-refresh');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        const custom = document.getElementById('own-custom');
        if (period === 'custom' && custom && !custom.hidden) {
          const s = document.getElementById('own-start').value;
          const e = document.getElementById('own-end').value;
          if (s && e) load(s, e);
        } else {
          const [a, b] = rangeFor(period);
          load(iso(a), iso(b));
        }
      });
    }

    // Print tool button
    const printBtn = document.getElementById('own-print');
    if (printBtn) {
      printBtn.addEventListener('click', () => {
        window.print();
      });
    }

    // Chart Type toggles (Bar vs Line)
    const btnBar = document.getElementById('btn-chart-bar');
    const btnLine = document.getElementById('btn-chart-line');
    if (btnBar && btnLine) {
      btnBar.addEventListener('click', () => {
        chartType = 'bar';
        btnBar.classList.add('active');
        btnLine.classList.remove('active');
        renderTrendChart();
      });
      btnLine.addEventListener('click', () => {
        chartType = 'line';
        btnLine.classList.add('active');
        btnBar.classList.remove('active');
        renderTrendChart();
      });
    }

    // Chart Metric toggles (All vs Net)
    const btnMetricAll = document.getElementById('btn-metric-all');
    const btnMetricNet = document.getElementById('btn-metric-net');
    if (btnMetricAll && btnMetricNet) {
      btnMetricAll.addEventListener('click', () => {
        chartMetric = 'all';
        btnMetricAll.classList.add('active');
        btnMetricNet.classList.remove('active');
        renderTrendChart();
      });
      btnMetricNet.addEventListener('click', () => {
        chartMetric = 'net';
        btnMetricNet.classList.add('active');
        btnMetricAll.classList.remove('active');
        renderTrendChart();
      });
    }

    // Theme changed listener
    window.addEventListener('fmh-theme-changed', () => {
      if (report) {
        renderTrendChart();
        renderDonutCharts();
      }
    });

    // Window resize debounced listener to keep charts crisp
    let resizeTimer = null;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if (trendChartInstance) trendChartInstance.resize();
        if (incomeDonutInstance) incomeDonutInstance.resize();
        if (expenseDonutInstance) expenseDonutInstance.resize();
        if (methodsChartInstance) methodsChartInstance.resize();
      }, 150);
    });

    // Initial period load
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
