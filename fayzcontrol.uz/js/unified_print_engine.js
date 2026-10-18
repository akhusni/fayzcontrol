/**
 * Fayz Medical House — Unified Enterprise Print Engine
 * High-fidelity, clinical-grade A4 document generation across all portals.
 */

window.FMH_Print = (function() {
  'use strict';

  // What an empty field prints as. These papers are signed and handed to
  // the patient, and every blank used to print as something plausible: a
  // diagnosis, a course of treatment, a named doctor who never saw the
  // patient, stay dates of 20-27 August, a 720,000 so'm payment, a 1.5
  // million bonus on every payslip.
  const NOT_RECORDED = 'Qayd etilmagan';
  const DISCHARGE_OUTCOMES = {
    recovered: "Sog'aydi", improved: 'Yaxshilandi', unchanged: "O'zgarishsiz",
    transferred: "Boshqa muassasaga o'tkazildi",
    against_medical_advice: 'Shifokor tavsiyasiga qarshi ketdi'
  };

  function formatUZS(amount) {
    return (Number(amount) || 0).toLocaleString('uz-UZ') + " so'm";
  }

  function formatDate(isoStr) {
    if (!isoStr) return '—';
    try {
      const d = new Date(isoStr);
      return isNaN(d.getTime()) ? String(isoStr) : d.toLocaleDateString('uz-UZ', { year: 'numeric', month: 'long', day: 'numeric' });
    } catch(e) {
      return String(isoStr);
    }
  }

  function formatDateTime(isoStr) {
    if (!isoStr) return '—';
    try {
      const d = new Date(isoStr);
      return isNaN(d.getTime()) ? String(isoStr) : `${d.toLocaleDateString('uz-UZ')} ${d.toLocaleTimeString('uz-UZ', {hour:'2-digit', minute:'2-digit'})}`;
    } catch(e) {
      return String(isoStr);
    }
  }

  function getCommonHeader(docTitle, docId, docCategory = "RASMIY TIBBIY HUJJAT") {
    const now = new Date();
    return `
      <div class="fmh-doc-header">
        <div class="fmh-brand-left">
          <div class="fmh-crest-icon">
            <i class="fas fa-hospital-symbol"></i>
          </div>
          <div class="fmh-brand-text">
            <h1>FAYZ MEDICAL HOUSE</h1>
            <div class="fmh-tagline">Ixtisoslashtirilgan Narkologiya & Psixiatriya Shifoxonasi</div>
            <div class="fmh-contacts">
              Toshkent sh., Yunusobod t., Nurmakon ko'chasi 2A &nbsp;|&nbsp; 
              Tel: +998 71 209 99 10 / +998 90 372 03 03 &nbsp;|&nbsp; Litsenziya №8472-FMH
            </div>
          </div>
        </div>
        <div class="fmh-header-badge-box">
          <div class="fmh-doc-badge">${docTitle}</div>
          <div class="fmh-doc-meta-sub">${docCategory}</div>
          <div class="fmh-doc-id-pill">ID: ${docId || 'DOC-' + Date.now().toString().slice(-6)}</div>
        </div>
      </div>`;
  }

  function getCommonAuthZone(roles = {}) {
    const docName = roles.doctor || "—";
    const headName = roles.head || "Qabulxona Mudiri";
    const patientName = roles.patient || "Bemor / Vakil";

    return `
      <div class="fmh-auth-zone">
        <div class="fmh-sign-box">
          <div class="fmh-sign-line"></div>
          <div class="fmh-sign-title">Mas'ul Shifokor</div>
          <div class="fmh-sign-name">${docName}</div>
        </div>
        
        <div class="fmh-official-stamp">
          <div>FAYZ MEDICAL</div>
          <div class="stamp-star">★ ★ ★</div>
          <div>LITS. 8472-FMH</div>
          <div>TOSHKENT</div>
        </div>

        <div class="fmh-sign-box">
          <div class="fmh-sign-line"></div>
          <div class="fmh-sign-title">${roles.patientTitle || "Bemor / Qonuniy Vakil"}</div>
          <div class="fmh-sign-name">${patientName}</div>
        </div>
      </div>`;
  }

  function getCommonFooter() {
    const now = new Date();
    return `
      <div class="fmh-doc-footer">
        <div class="fmh-legal-notice">
          Ushbu hujjat O'zbekiston Respublikasi "Fuqarolar sog'lig'ini saqlash to'g'risida"gi Qonuniga muvofiq 100% qat'iy tibbiy sir sifatida himoyalangan.
        </div>
        <div class="fmh-qr-badge">
          <i class="fas fa-qrcode"></i> VERIFIED: FMH-2026-SECURE
        </div>
      </div>`;
  }

  /**
   * Print HTML Document via dedicated clean print window or in-page print-area
   */
  /**
   * Print HTML Document via dedicated isolated iframe
   * Guarantees 100% clean A4 print preview with zero parent-portal CSS interference.
   */
  function printDocument(innerHtml, docTitle = "FAYZ MEDICAL HOUSE", options = {}) {
    try {
      const isLandscape = Boolean(options && (options.landscape || options.orientation === 'landscape'));
      const pageSize = isLandscape ? 'A4 landscape' : 'A4 portrait';

      // Remove any existing print iframe
      const oldFrame = document.getElementById('fmh-isolated-print-frame');
      if (oldFrame) {
        try { oldFrame.remove(); } catch(e) {}
      }

      // Create new iframe placed off-screen for full rendering fidelity
      const iframe = document.createElement('iframe');
      iframe.id = 'fmh-isolated-print-frame';
      iframe.style.position = 'fixed';
      iframe.style.left = '-9999px';
      iframe.style.top = '0';
      iframe.style.width = isLandscape ? '297mm' : '210mm';
      iframe.style.height = isLandscape ? '210mm' : '297mm';
      iframe.style.border = '0';
      iframe.style.zIndex = '-9999';
      document.body.appendChild(iframe);

      const frameDoc = iframe.contentWindow.document;
      const documentBody = innerHtml.includes('fmh-print-document')
        ? innerHtml
        : `<div class="fmh-print-document ${isLandscape ? 'is-landscape' : ''}"><div class="fmh-print-content">${innerHtml}</div></div>`;

      const fullDocHtml = `<!DOCTYPE html>
<html lang="uz">
<head>
  <meta charset="UTF-8">
  <title>${docTitle}</title>
  <base href="${window.location.origin}/">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700;800&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
  <link rel="stylesheet" href="css/unified_print.css?v=6.0">
  <style>
    @page { size: ${pageSize}; margin: 8mm 10mm 8mm 10mm; }
    *, *::before, *::after {
      box-sizing: border-box;
      -webkit-print-color-adjust: exact !important;
      print-color-adjust: exact !important;
    }
    html, body {
      background: #ffffff !important;
      color: #0f172a !important;
      margin: 0 !important;
      padding: 0 !important;
      width: 100% !important;
      font-family: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif !important;
      font-size: 9.5pt !important;
      line-height: 1.45 !important;
    }
    .fmh-print-document {
      width: 100% !important;
      max-width: ${isLandscape ? '297mm' : '210mm'} !important;
      margin: 0 auto !important;
      padding: ${isLandscape ? '8mm 12mm' : '10mm 12mm'} !important;
      box-shadow: none !important;
      border: none !important;
      background: #ffffff !important;
    }
    .fmh-doc-header { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2.5px solid #0f766e; padding-bottom: 8px; margin-bottom: 10px; }
    .fmh-brand-left { display: flex; align-items: center; gap: 10px; }
    .fmh-crest-icon { width: 44px; height: 44px; background: #0f766e !important; color: #fff !important; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 20px; font-weight: 800; }
    .fmh-brand-text h1 { font-size: 14pt; font-weight: 800; color: #0f766e; margin: 0; line-height: 1.15; text-transform: uppercase; }
    .fmh-brand-text .fmh-tagline { font-size: 7.5pt; font-weight: 600; color: #475569; margin-top: 1px; }
    .fmh-brand-text .fmh-contacts { font-size: 7.2pt; color: #64748b; margin-top: 2px; }
    .fmh-header-badge-box { text-align: right; display: flex; flex-direction: column; align-items: flex-end; }
    .fmh-doc-badge { display: inline-block; background: #0f766e !important; color: #fff !important; font-size: 8.5pt; font-weight: 800; padding: 3px 8px; border-radius: 4px; text-transform: uppercase; }
    .fmh-doc-meta-sub { font-size: 7.2pt; color: #475569; margin-top: 3px; font-weight: 600; }
    .fmh-doc-id-pill { font-family: 'JetBrains Mono', Consolas, monospace; background: #f1f5f9; border: 1px solid #cbd5e1; padding: 1px 5px; border-radius: 3px; font-size: 7.5pt; font-weight: 700; margin-top: 2px; }
    .fmh-meta-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 5px 12px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 5px; padding: 7px 10px; margin-bottom: 8px; }
    .fmh-meta-grid-4 { grid-template-columns: repeat(4, 1fr); }
    .fmh-meta-grid-3 { grid-template-columns: repeat(3, 1fr); }
    .fmh-meta-item { display: flex; flex-direction: column; font-size: 8.5pt; }
    .fmh-meta-item .lbl { font-size: 7pt; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.3px; }
    .fmh-meta-item .val { font-weight: 600; color: #0f172a; margin-top: 1px; }
    .fmh-meta-item .val.highlight { color: #0f766e !important; font-weight: 700 !important; }
    .fmh-section-title { display: flex; align-items: center; gap: 5px; font-size: 8.8pt; font-weight: 700; color: #0f766e; text-transform: uppercase; margin-top: 8px; margin-bottom: 5px; border-bottom: 1px solid #cbd5e1; padding-bottom: 2px; }
    .fmh-callout-box { background: #f0fdf4; border-left: 3px solid #10b981; padding: 5px 8px; margin: 6px 0; font-size: 8pt; color: #14532d; border-radius: 0 4px 4px 0; }
    .fmh-callout-box.blue { background: #f0f9ff; border-left-color: #0284c7; color: #0c4a6e; }
    .fmh-callout-box.amber { background: #fffbeb; border-left-color: #f59e0b; color: #78350f; }
    .fmh-data-table { width: 100%; border-collapse: collapse; margin: 5px 0 8px 0; font-size: 8pt; }
    .fmh-data-table th { background: #0f766e !important; color: #ffffff !important; font-weight: 700; text-transform: uppercase; font-size: 7pt; padding: 4px 6px; text-align: left; border: 1px solid #0f766e; }
    .fmh-data-table td { padding: 4px 6px; border: 1px solid #cbd5e1; color: #1e293b; vertical-align: middle; }
    .fmh-data-table tr:nth-child(even) td { background: #f8fafc !important; }
    .fmh-data-table tfoot td { font-weight: 700; background: #e2e8f0 !important; border-top: 1.5px solid #0f766e; }
    .fmh-auth-zone { display: flex; justify-content: space-between; align-items: flex-end; margin-top: 12px; padding-top: 8px; border-top: 1px solid #e2e8f0; page-break-inside: avoid; break-inside: avoid; }
    .fmh-sign-box { width: 30%; text-align: center; font-size: 7pt; color: #334155; }
    .fmh-sign-line { border-bottom: 1.2px solid #0f172a; height: 24px; margin-bottom: 3px; }
    .fmh-sign-title { font-weight: 700; color: #0f172a; text-transform: uppercase; }
    .fmh-sign-name { color: #64748b; margin-top: 1px; font-style: italic; }
    .fmh-official-stamp { width: 72px; height: 72px; border: 1.8px dashed #0f766e; border-radius: 50%; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; color: #0f766e; font-size: 5pt; font-weight: 800; text-transform: uppercase; padding: 2px; transform: rotate(-6deg); }
    .fmh-doc-footer { margin-top: 10px; padding-top: 5px; border-top: 1px solid #cbd5e1; display: flex; justify-content: space-between; align-items: center; font-size: 6.8pt; color: #64748b; page-break-inside: avoid; break-inside: avoid; }
    .text-right { text-align: right !important; }
    .text-center { text-align: center !important; }
    .font-mono { font-family: 'JetBrains Mono', Consolas, monospace !important; }
  </style>
</head>
<body>
  ${documentBody}
</body>
</html>`;

      frameDoc.open();
      frameDoc.write(fullDocHtml);
      frameDoc.close();

      setTimeout(() => {
        try {
          iframe.contentWindow.focus();
          iframe.contentWindow.print();
        } catch (iframeErr) {
          console.warn('[FMH_Print] Iframe print fallback:', iframeErr);
          const win = window.open('', '_blank');
          if (win) {
            win.document.open();
            win.document.write(fullDocHtml);
            win.document.close();
            setTimeout(() => { win.focus(); win.print(); }, 250);
          } else {
            window.print();
          }
        }
      }, 250);

    } catch (err) {
      console.error('[FMH_Print] Direct window.print fallback:', err);
      window.print();
    }
  }

  /**
   * 1. RECEPTION: Admission Slip (Statsionarga Qabul Varaqasi)
   */
  function admissionSlip(data, admId) {
    const isAnon = Boolean(data.is_anonymous || data.isAnon);
    const pName = isAnon ? "[ ANONIM BEMOR ]" : (data.name || data.patient_name || "—");
    const pPhone = isAnon ? "Maxfiy" : (data.phone || data.patient_phone || "—");
    const days = parseInt(data.days || data.total_days) || 0;
    const rate = parseFloat(data.rate || data.daily_price) || 0;
    const total = days * rate;
    const advance = parseFloat(data.advance) || 0;
    const balance = Math.max(0, total - advance);
    const startDate = data.startDate || data.start_date || new Date().toISOString().slice(0, 10);
    const id = admId || data.id || '—';

    const html = `
      ${getCommonHeader("STATSIONARGA QABUL VARAQASI", id, "QABULXONA & KASSA BO'LIMI")}
      
      <div class="fmh-meta-grid fmh-meta-grid-4">
        <div class="fmh-meta-item">
          <span class="lbl">Bemor F.I.Sh.</span>
          <span class="val highlight">${pName}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Telefon Raqami</span>
          <span class="val">${pPhone}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Biriktirilgan Karavot</span>
          <span class="val highlight"><i class="fas fa-bed"></i> ${data.bedId || data.bed_id || '—'}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Qabul Sanasi</span>
          <span class="val">${formatDate(startDate)}</span>
        </div>
      </div>

      <div class="fmh-section-title"><i class="fas fa-notes-medical"></i> Davolanish Dasturi va Tarif</div>
      <table class="fmh-data-table">
        <thead>
          <tr>
            <th>Xizmat / Dastur Nomi</th>
            <th class="text-center">Davomiylik</th>
            <th class="text-right">Kunlik Tarif</th>
            <th class="text-right">Jami Qiymat</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <strong>${data.program || data.program_type || '—'}</strong>
              <div style="font-size:7pt; color:#64748b;">24/7 Shifokor va hamshiralik nazorati, palata, 3 mahal parhez taom, dori-darmonlar</div>
            </td>
            <td class="text-center"><strong>${days} kun</strong></td>
            <td class="text-right font-mono">${formatUZS(rate)}</td>
            <td class="text-right font-mono"><strong>${formatUZS(total)}</strong></td>
          </tr>
        </tbody>
        <tfoot>
          <tr>
            <td colspan="3" class="text-right">Birlamchi To'langan Avans:</td>
            <td class="text-right font-mono" style="color:#059669;">${formatUZS(advance)}</td>
          </tr>
          <tr>
            <td colspan="3" class="text-right">To'lanishi Kerak Bo'lgan Qoldiq:</td>
            <td class="text-right font-mono" style="color:${balance > 0 ? '#dc2626' : '#059669'}; font-size:9pt;">${formatUZS(balance)}</td>
          </tr>
        </tfoot>
      </table>

      <div class="fmh-section-title"><i class="fas fa-shield-alt"></i> Maxfiylik va Kafolat Shartnomasi</div>
      <div class="fmh-callout-box">
        <strong>100% Anonimlik Kafolati:</strong> Bemorning shaxsiy ma'lumotlari hech qanday uchinchi shaxslarga, davlat organlariga yoki dispanser ro'yxatiga berilmaydi. Davolanish to'liq ixtiyoriy va maxfiy amalga oshiriladi. Bemor va uning qonuniy vakillari klinika ichki tartib-qoidalariga rioya qilish majburiyatini oladi.
      </div>

      ${getCommonAuthZone({
        doctor: data.doctor_name || "—",
        patient: pName
      })}

      ${getCommonFooter()}
    `;

    printDocument(html, `FMH_Qabul_${id}`);
  }

  /**
   * 2. RECEPTION: Blank Intake Form (Toza Bemor Anketa Blanki)
   */
  function blankIntakeForm(data) {
    // Reception called this with no argument, so after filling the intake
    // form in on screen the desk printed a completely empty sheet: none of
    // the patient's details and none of the money reached the paper the
    // patient is asked to sign. Passing the desk's form state fills the
    // same template in; called with nothing it still prints the empty
    // version, which is what stocks the counter.
    const d = data || {};
    const isFilled = Boolean(data);
    const esc = v => String(v === 0 || v ? v : '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    // A value that was entered is printed; anything the intake form does
    // not ask for keeps its ruled line so it can be written in by hand.
    // Nothing is substituted for a missing answer.
    const fill = v => {
      const s = esc(v).trim();
      return s ? `<span class="val">${s}</span>` : '<div class="fmh-line-fill"></div>';
    };
    const tick = on => (isFilled ? (on ? '\u2611' : '\u2610')
                                 : '<span class="fmh-box-sq"></span>');

    const days = Number(d.days) || 0;
    const rate = Number(d.daily_rate) || 0;
    const gross = days * rate;
    const discountPct = Number(d.discount_percent) || 0;
    const discountAmount = gross * (discountPct / 100);
    const net = gross - discountAmount;
    const advance = Number(d.advance) || 0;
    const balance = Math.max(0, net - advance);

    const moneyBlock = !isFilled ? '' : `
      <div class="fmh-section-title"><i class="fas fa-calculator"></i> 3. To\u2018lov Hisob-Kitobi</div>
      <table class="fmh-data-table">
        <thead>
          <tr>
            <th>Hisob-kitob bandi</th>
            <th class="text-center">Miqdor</th>
            <th class="text-right">Summa (so\u2018m)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Kunlik tarif</td>
            <td class="text-center font-mono">${days} kun</td>
            <td class="text-right font-mono">${formatUZS(rate)}</td>
          </tr>
          <tr>
            <td>Jami (brutto)</td>
            <td class="text-center">\u2014</td>
            <td class="text-right font-mono">${formatUZS(gross)}</td>
          </tr>
          <tr>
            <td>Chegirma${discountPct ? ` (${discountPct}%)` : ''}</td>
            <td class="text-center">\u2014</td>
            <td class="text-right font-mono">${discountAmount ? '-' + formatUZS(discountAmount) : formatUZS(0)}</td>
          </tr>
          <tr>
            <td><strong>To\u2018lanishi kerak (netto)</strong></td>
            <td class="text-center">\u2014</td>
            <td class="text-right font-mono"><strong>${formatUZS(net)}</strong></td>
          </tr>
          <tr>
            <td>Avans to\u2018lov (qabul qilindi)</td>
            <td class="text-center">${esc(d.pay_method_label || '')}</td>
            <td class="text-right font-mono" style="color:#059669;">${formatUZS(advance)}</td>
          </tr>
        </tbody>
        <tfoot>
          <tr>
            <td colspan="2" class="text-right">Qoldiq qarz:</td>
            <td class="text-right font-mono" style="color:${balance > 0 ? '#dc2626' : '#059669'};">${formatUZS(balance)}</td>
          </tr>
        </tfoot>
      </table>`;

    const html = `
      ${getCommonHeader("BEMOR QABUL & ANKETA BLANKI", "FMH-BLANK-A4", "BIRLAMCHI REGISTRATURA")}
      
      <div class="fmh-section-title"><i class="fas fa-id-card"></i> 1. Bemorning Shaxsiy Ma'lumotlari</div>
      <div class="fmh-meta-grid fmh-meta-grid-2">
        <div class="fmh-meta-item">
          <span class="lbl">F.I.Sh. (Familiya Ism Sharif):</span>
          ${fill(d.patient_name)}
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Tug'ilgan Sana / Yil:</span>
          ${fill(d.birth_date)}
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Telefon Raqami:</span>
          ${fill(d.patient_phone)}
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Anonim Rejim:</span>
          <div class="fmh-check-group" style="margin-top:2px;">
            <span class="fmh-check-item">${tick(d.is_anonymous)} Ha (100% Maxfiy)</span>
            <span class="fmh-check-item">${tick(isFilled && !d.is_anonymous)} Yo'q (Ochiq)</span>
          </div>
        </div>
        <div class="fmh-meta-item" style="grid-column: span 2;">
          <span class="lbl">Yashash Manzili (Viloyat, Tuman, Ko'cha):</span>
          ${fill(d.address)}
        </div>
      </div>

      <div class="fmh-section-title"><i class="fas fa-bed"></i> 2. Belgilangan Qabul va Joylashtirish Rejasi</div>
      <div class="fmh-meta-grid fmh-meta-grid-4">
        <div class="fmh-meta-item">
          <span class="lbl">Dastur / Tarif:</span>
          ${fill(d.program_label)}
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Kelish Sanasi:</span>
          ${fill(d.start_date)}
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Ketish Sanasi (Reja):</span>
          ${fill(d.end_date)}
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Qanday Topdi (Manba):</span>
          ${fill(d.referral_label)}
        </div>
      </div>
      <div class="fmh-meta-grid fmh-meta-grid-4">
        <div class="fmh-meta-item">
          <span class="lbl">Xizmat Turi:</span>
          <span class="val">${tick(d.service_type === 'inpatient')} Statsionar ${tick(d.service_type === 'outpatient')} Ambulator</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Karavot / Palata:</span>
          ${fill(d.bed_id)}
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Mas'ul Shifokor:</span>
          ${fill(d.doctor_name)}
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Avans To'lov (so'm):</span>
          ${fill(isFilled ? formatUZS(advance) : '')}
        </div>
      </div>

      <div class="fmh-meta-grid">
        <div class="fmh-meta-item">
          <span class="lbl">Qabulxona Izohi:</span>
          ${fill(d.notes)}
        </div>
      </div>

      ${moneyBlock}

      <div class="fmh-section-title"><i class="fas fa-file-contract"></i> ${isFilled ? '4' : '3'}. Shaxsiy Rozilik va Majburiyat</div>
      <div class="fmh-callout-box">
        Men, yuqorida ko'rsatilgan bemor (yoki uning qonuniy vakili), «Fayz Medical House» klinikasida davolanishga va shifokor ko'riklariga ixtiyoriy rozilik beraman. Barcha tibbiy ma'lumotlar maxfiy saqlanishi ma'lum qilindi.
      </div>

      ${getCommonAuthZone({
        doctor: "Qabulxona Registratori",
        patient: "Bemor / Vakil Imzosi"
      })}

      ${getCommonFooter()}
    `;

    printDocument(html, "FMH_Bemor_Qabul_Blanki");
  }

  /**
   * 3. DOCTOR EMR: Nurse Prescription & Infusion Chart (List Naznacheniy)
   */
  function prescriptionSheet(patient, rxList = [], doctor = {}) {
    const isAnon = Boolean(patient.is_anonymous);
    const pName = isAnon ? "[ ANONIM BEMOR ]" : (patient.full_name || "Bemor");
    const docName = doctor.full_name || "—";
    const adm = patient.active_admission || {};
    const bedStr = adm.bed_code || adm.bed_id || "—";

    let rowsHtml = "";
    if (!rxList || !rxList.length) {
      rowsHtml = `<tr><td colspan="6" class="text-center" style="padding:15px; color:#64748b;">Hozircha faol dori-darmon tayinlovlari yo'q</td></tr>`;
    } else {
      rowsHtml = rxList.map((rx, idx) => `
        <tr>
          <td class="text-center font-mono">${idx + 1}</td>
          <td><strong>${rx.medication_name || rx.name || 'Dori vositasi'}</strong></td>
          <td class="text-center font-mono">${rx.dosage || rx.standard_dosage || '—'}</td>
          <td class="text-center">${rx.route || '—'}</td>
          <td class="text-center">${rx.frequency || '—'}</td>
          <td style="font-size:7pt;">${rx.instructions || rx.notes || ''}</td>
        </tr>`).join('');
    }

    const html = `
      ${getCommonHeader("HAMSHIRALIK MUOLAJA VARAQASI", `RX-${patient.patient_code || patient.id}`, "LIST NAZNACHENIY & FARMAKOTERAPIYA")}
      
      <div class="fmh-meta-grid fmh-meta-grid-4">
        <div class="fmh-meta-item">
          <span class="lbl">Bemor F.I.Sh.</span>
          <span class="val highlight">${pName}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Bemor KODI</span>
          <span class="val font-mono">${patient.patient_code || patient.id}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Palata / Karavot</span>
          <span class="val"><i class="fas fa-bed"></i> ${bedStr}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Mas'ul Shifokor</span>
          <span class="val">${docName}</span>
        </div>
      </div>

      <div class="fmh-section-title"><i class="fas fa-pills"></i> Tasdiqlangan Dori Vositalari va Infuzion Terapiya</div>
      <table class="fmh-data-table">
        <thead>
          <tr>
            <th class="text-center" style="width:30px;">№</th>
            <th>Dori Vositasining Nomi</th>
            <th class="text-center">Doza</th>
            <th class="text-center">Yuborish Usuli</th>
            <th class="text-center">Qabullar</th>
            <th>Maxsus Ko'rsatmalar</th>
          </tr>
        </thead>
        <tbody>
          ${rowsHtml}
        </tbody>
      </table>

      <div class="fmh-section-title"><i class="fas fa-user-nurse"></i> Hamshira Bajarish Qaydnomasi</div>
      <div class="fmh-meta-grid fmh-meta-grid-3">
        <div class="fmh-meta-item">
          <span class="lbl">Ertalabki Muolaja (08:00):</span>
          <span class="val">☐ Bajarildi (Imzo: _______)</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Kunduzgi Muolaja (14:00):</span>
          <span class="val">☐ Bajarildi (Imzo: _______)</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Kechki Muolaja (20:00):</span>
          <span class="val">☐ Bajarildi (Imzo: _______)</span>
        </div>
      </div>

      ${getCommonAuthZone({
        doctor: docName,
        patientTitle: "Katta Hamshira",
        patient: "—"
      })}

      ${getCommonFooter()}
    `;

    printDocument(html, `FMH_Muolaja_${patient.patient_code || patient.id}`);
  }

  /**
   * 4. DOCTOR / CRM: Medical Discharge Epicrisis (Chiqarish Epikrizi)
   */
  function dischargeEpicrisis(patient, epicrisis = {}, doctor = {}) {
    const isAnon = Boolean(patient.is_anonymous);
    const pName = isAnon ? "[ ANONIM BEMOR ]" : (patient.full_name || "Bemor");
    const docName = doctor.full_name || "—";
    const adm = patient.active_admission || {};
    const admStart = adm.start_date || epicrisis.admission_date || "";
    const admEnd = adm.actual_end_date || adm.planned_end_date || epicrisis.discharge_date || "";

    const html = `
      ${getCommonHeader("RASMIY TIBBIY CHIQARISH EPIKRIZI", `EPI-${patient.patient_code || patient.id}`, "KASALLIK TARIXI & REABILITATSIYA")}
      
      <div class="fmh-meta-grid fmh-meta-grid-4">
        <div class="fmh-meta-item">
          <span class="lbl">Bemor F.I.Sh.</span>
          <span class="val highlight">${pName}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Bemor KODI</span>
          <span class="val font-mono">${patient.patient_code || patient.id}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Yotgan Davri</span>
          <span class="val">${formatDate(admStart)} → ${formatDate(admEnd)}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Mas'ul Shifokor</span>
          <span class="val">${docName}</span>
        </div>
      </div>

      <div class="fmh-section-title"><i class="fas fa-diagnoses"></i> 1. Yakuniy Klinik Tashxis (ICD-10)</div>
      <div class="fmh-callout-box blue">
        <strong>Asosiy Tashxis:</strong> ${epicrisis.final_diagnosis || epicrisis.diagnosis_final || epicrisis.diagnosis || NOT_RECORDED}
        ${epicrisis.diagnosis_secondary ? `<br><span style="font-size:7.5pt; color:#475569;">Hamroh kasalliklar: ${epicrisis.diagnosis_secondary}</span>` : ''}
      </div>

      <div class="fmh-section-title"><i class="fas fa-procedures"></i> 2. O'tkazilgan Kompleks Muolajalar</div>
      <p style="margin:4px 0; font-size:8.5pt;">
        ${epicrisis.treatment_summary || NOT_RECORDED}
      </p>

      <div class="fmh-section-title"><i class="fas fa-heartbeat"></i> 3. Chiqarishdagi Klinik Holat & Natija</div>
      <div class="fmh-callout-box">
        <strong>Holat:</strong> ${DISCHARGE_OUTCOMES[epicrisis.discharge_status] || epicrisis.discharge_status || NOT_RECORDED}
      </div>

      <div class="fmh-section-title"><i class="fas fa-clipboard-list"></i> 4. Ambulator Tavsiyalar va Profilaktika</div>
      <p style="margin:4px 0; font-size:8.5pt;">
        ${epicrisis.recommendations || epicrisis.psycho_recommendations || NOT_RECORDED}
      </p>

      ${getCommonAuthZone({
        doctor: docName,
        head: "Bosh Shifokor",
        patient: pName
      })}

      ${getCommonFooter()}
    `;

    printDocument(html, `FMH_Epikriz_${patient.patient_code || patient.id}`);
  }

  /**
   * 5. ACCOUNTING / RECEPTION: Official Payment Receipt & Invoice
   */
  function patientReceipt(patient, invoice = {}, payment = {}) {
    const isAnon = Boolean(patient?.is_anonymous);
    const pName = isAnon ? "[ ANONIM BEMOR ]" : (patient?.full_name || "Bemor");
    const pCode = patient?.patient_code || "—";
    const amount = Number(payment.amount || invoice.paid_amount || invoice.amount || 0);
    const totalBilled = Number(invoice.total_amount || amount);
    const discount = Number(invoice.discount_amount) || 0;
    const grossBilled = Number(invoice.gross_amount) || (totalBilled + discount);
    const balance = Math.max(0, totalBilled - amount);
    const payId = payment.id || invoice.id || '—';

    const html = `
      ${getCommonHeader("RASMIY TO'LOV KVITANSIYASI", payId, "MOLIYA & KASSA BO'LIMI")}
      
      <div class="fmh-meta-grid fmh-meta-grid-4">
        <div class="fmh-meta-item">
          <span class="lbl">To'lovchi F.I.Sh.</span>
          <span class="val highlight">${pName}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Bemor KODI</span>
          <span class="val font-mono">${pCode}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">To'lov Usuli</span>
          <span class="val">${payment.payment_method === 'card' ? 'Terminal / Karta' : 'Naqd Pul'}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">To'lov Sanasi</span>
          <span class="val">${formatDateTime(payment.created_at || new Date())}</span>
        </div>
      </div>

      <div class="fmh-section-title"><i class="fas fa-receipt"></i> To'lov Tafsilotlari</div>
      <table class="fmh-data-table">
        <thead>
          <tr>
            <th>Operatsiya / Xizmat Tavsifi</th>
            <th class="text-center">Kvitansiya Kodi</th>
            <th class="text-right">Hisoblangan</th>
            <th class="text-right">To'langan Summa</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <strong>${payment.notes || 'Statsionar davolanish va tibbiy xizmatlar to`lovi'}</strong>
              <div style="font-size:7pt; color:#64748b;">Fayz Medical House Markaziy Kassasi orqali qabul qilindi</div>
            </td>
            <td class="text-center font-mono">${payId}</td>
            <td class="text-right font-mono">${formatUZS(totalBilled)}</td>
            <td class="text-right font-mono"><strong style="color:#059669; font-size:9.5pt;">${formatUZS(amount)}</strong></td>
          </tr>
        </tbody>
        <tfoot>
          ${discount > 0 ? `
          <tr>
            <td colspan="3" class="text-right">Hisoblangan summa (chegirmagacha):</td>
            <td class="text-right font-mono">${formatUZS(grossBilled)}</td>
          </tr>
          <tr>
            <td colspan="3" class="text-right">Chegirma:</td>
            <td class="text-right font-mono" style="color:#dc2626;">-${formatUZS(discount)}</td>
          </tr>` : ''}
          <tr>
            <td colspan="3" class="text-right">Qolgan Balans (Qarz/Ortiqcha):</td>
            <td class="text-right font-mono" style="color:${balance > 0 ? '#dc2626' : '#059669'};">${formatUZS(balance)}</td>
          </tr>
        </tfoot>
      </table>

      <div class="fmh-callout-box">
        <strong>Fiskal Eslatma:</strong> Ushbu kvitansiya klinikada amalga oshirilgan rasmiy to'lovni tasdiqlovchi birlamchi buxgalteriya hujjati hisoblanadi.
      </div>

      ${getCommonAuthZone({
        doctor: "Kassa Mudiri / Bosh Buxgalter",
        patientTitle: "To'lovchi Imzosi",
        patient: pName
      })}

      ${getCommonFooter()}
    `;

    printDocument(html, `FMH_Kvitansiya_${payId}`);
  }

  /**
   * 6. HR: Employee Official Payslip (Xodim Ish Haqi Varaqasi)
   */
  function employeePayslip(staff, salaryData = {}) {
    const base = Number(salaryData.base_salary || staff.salary_base || 0);
    const bonus = Number(salaryData.bonuses || 0);
    const nightShift = Number(salaryData.night_shifts || 0);
    const gross = base + bonus + nightShift;
    const incomeTax = gross * 0.12;
    const inps = gross * 0.001;
    const deductions = incomeTax + inps;
    const net = gross - deductions;
    const slipId = `PAYROLL-2026-${staff.id || 'STF'}`;

    const html = `
      ${getCommonHeader("XODIM OYLIK ISH HAQI VARAQASI", slipId, "KADRLAR & BUXGALTERIYA BO'LIMI")}
      
      <div class="fmh-meta-grid fmh-meta-grid-4">
        <div class="fmh-meta-item">
          <span class="lbl">Xodim F.I.Sh.</span>
          <span class="val highlight">${staff.full_name || "Xodim"}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Lavozim / Bo'lim</span>
          <span class="val">${staff.specialty || staff.role || "Shifokor"}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Tabel Raqami</span>
          <span class="val font-mono">${staff.id || "—"}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Hisob Davri</span>
          <span class="val">${new Date().toLocaleDateString('uz-UZ', { year: 'numeric', month: 'long' })}</span>
        </div>
      </div>

      <div class="fmh-section-title"><i class="fas fa-coins"></i> 1. Hisoblangan Daromadlar (Kirim)</div>
      <table class="fmh-data-table">
        <thead>
          <tr>
            <th>To'lov Turi</th>
            <th class="text-center">Koeffitsiyent</th>
            <th class="text-right">Summa (UZS)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Oklad (Asosiy oylik ish haqi)</td>
            <td class="text-center">100%</td>
            <td class="text-right font-mono">${formatUZS(base)}</td>
          </tr>
          <tr>
            <td>Navbatchilik va Tungi smena ustamalari</td>
            <td class="text-center">Reja bo'yicha</td>
            <td class="text-right font-mono">${formatUZS(nightShift)}</td>
          </tr>
          <tr>
            <td>KPI va Samaradorlik Mukofotlari</td>
            <td class="text-center">Bonus</td>
            <td class="text-right font-mono">${formatUZS(bonus)}</td>
          </tr>
        </tbody>
        <tfoot>
          <tr>
            <td colspan="2" class="text-right">JAMI HISOBLANGAN (BRUTTO):</td>
            <td class="text-right font-mono" style="color:#0f766e; font-size:9.5pt;"><strong>${formatUZS(gross)}</strong></td>
          </tr>
        </tfoot>
      </table>

      <div class="fmh-section-title"><i class="fas fa-percentage"></i> 2. Qonuniy Ushlanmalar (Soliqlar)</div>
      <table class="fmh-data-table">
        <thead>
          <tr>
            <th>Ushlanma Turi</th>
            <th class="text-center">Stavka</th>
            <th class="text-right">Summa (UZS)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Jismoniy shaxslardan olinadigan daromad solig'i (JSHODS)</td>
            <td class="text-center">12%</td>
            <td class="text-right font-mono">${formatUZS(incomeTax)}</td>
          </tr>
          <tr>
            <td>Shaxsiy jamg'arib boriladigan pensiya badali (INPS)</td>
            <td class="text-center">0.1%</td>
            <td class="text-right font-mono">${formatUZS(inps)}</td>
          </tr>
        </tbody>
        <tfoot>
          <tr>
            <td colspan="2" class="text-right">JAMI USHLANMALAR:</td>
            <td class="text-right font-mono" style="color:#dc2626;">-${formatUZS(deductions)}</td>
          </tr>
        </tfoot>
      </table>

      <div class="fmh-callout-box">
        <strong>QO'LGA TEGADIGAN SOF MAOSH (NET):</strong> 
        <span style="font-size:11pt; font-weight:800; color:#0f766e; margin-left:8px;" class="font-mono">${formatUZS(net)}</span>
      </div>

      ${getCommonAuthZone({
        doctor: "Bosh Buxgalter",
        patientTitle: "Xodim Imzosi",
        patient: staff.full_name || "Xodim"
      })}

      ${getCommonFooter()}
    `;

    printDocument(html, `FMH_Maosh_${staff.id || 'STF'}`);
  }

  /**
   * 7. ACCOUNTING / POS: Official Transaction Receipt & Cash Voucher
   */
  function transactionReceipt(txn, clinicInfo = {}) {
    const t = txn || {};
    const txnId = t.id || 'TXN-' + Date.now().toString().slice(-6);
    const isIncome = t.type === 'income' || t.category === 'income';
    const isIncasso = t.category === 'incasso';
    const opTitle = isIncasso
      ? "INKASSATSIYA DALOLATNOMASI"
      : (isIncome ? "RASMIY KIRIM KASSA KVITANSIYASI" : "RASMIY CHIQIM KASSA ORDERI");
    const amount = Math.abs(Number(t.amount) || 0);
    const cashier = t.cashier || t.created_by || "Bosh Buxgalter";

    const html = `
      ${getCommonHeader(opTitle, txnId, "KASSA & MOLIYA BO'LIMI")}
      
      <div class="fmh-meta-grid fmh-meta-grid-4">
        <div class="fmh-meta-item">
          <span class="lbl">Operatsiya Turi:</span>
          <span class="val highlight">${isIncasso ? 'INKASSATSIYA' : (isIncome ? 'Kirim (Tushum)' : 'Chiqim (Xarajat)')}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Hujjat Raqami:</span>
          <span class="val font-mono">${txnId}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">To'lov Usuli:</span>
          <span class="val">${String(t.payment_method || 'naqd').toUpperCase()}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Sana va Vaqt:</span>
          <span class="val">${t.date || formatDate(new Date())} ${t.time || ''}</span>
        </div>
      </div>

      <div class="fmh-section-title"><i class="fas fa-receipt"></i> Operatsiya Tafsilotlari</div>
      <table class="fmh-data-table">
        <thead>
          <tr>
            <th>Xarajat / Kirim Maqsadi</th>
            <th class="text-center">Kategoriya</th>
            <th class="text-right">Summa (UZS)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <strong>${t.title || t.notes || 'Klinik kassa operatsiyasi'}</strong>
              <div style="font-size:7.5pt; color:#64748b;">${t.notes && t.notes !== t.title ? t.notes : 'Fayz Medical House rasmiy markaziy kassasi orqali qayd etildi'}</div>
            </td>
            <td class="text-center"><strong>${t.category || (isIncome ? 'Tushum' : 'Xarajat')}</strong></td>
            <td class="text-right font-mono" style="font-size:10pt; font-weight:800; color:${isIncome ? '#059669' : '#dc2626'};">
              ${formatUZS(amount)}
            </td>
          </tr>
        </tbody>
        <tfoot>
          <tr>
            <td colspan="2" class="text-right">JAMI OPERATSIYA QIYMATI:</td>
            <td class="text-right font-mono" style="font-size:10.5pt; color:${isIncome ? '#059669' : '#dc2626'};">
              <strong>${formatUZS(amount)}</strong>
            </td>
          </tr>
        </tfoot>
      </table>

      <div class="fmh-callout-box ${isIncome ? '' : 'amber'}">
        <strong>Fiskal & Buxgalteriya Qaydnomasi:</strong> Ushbu kassa cheki va orderi O'zbekiston Respublikasi buxgalteriya hisobi standartlariga asosan birlamchi kassa hujjati hisoblanadi.
      </div>

      ${getCommonAuthZone({
        doctor: cashier,
        patientTitle: isIncome ? "To'lovchi / Mijoz Imzosi" : "Mablag'ni Qabul Qiluvchi",
        patient: t.patient || t.counterparty || "Mijoz / Xodim"
      })}

      ${getCommonFooter()}
    `;

    printDocument(html, `FMH_Chek_${txnId}`);
  }

  /**
   * 8. ACCOUNTING: Daily Cash Closing Z-Report
   */
  function zReport(zData = {}, clinicInfo = {}) {
    const today = zData.date || new Date().toISOString().slice(0, 10);
    const income = Number(zData.income || 0);
    const expense = Number(zData.expense || 0);
    const net = income - expense;
    const cash = Number(zData.cash || 0);
    const terminal = Number(zData.terminal || 0);
    const online = Number(zData.online || 0);
    const txnCount = Number(zData.txnCount || 0);
    const docId = `Z-${today.replace(/-/g, '')}-01`;

    const html = `
      ${getCommonHeader("KASSA SUTKALIK YOPILISH HISOBOTI (Z-REPORT)", docId, "KASSA & MOLIYA BO'LIMI")}
      
      <div class="fmh-meta-grid fmh-meta-grid-4">
        <div class="fmh-meta-item">
          <span class="lbl">Kassa Raqami:</span>
          <span class="val highlight">Markaziy Kassa №1</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Hisob Sanasi:</span>
          <span class="val font-mono">${formatDate(today)}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Operatsiyalar Soni:</span>
          <span class="val font-mono"><strong>${txnCount} ta</strong></span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Hisobot Vaqti:</span>
          <span class="val">${formatDateTime(new Date())}</span>
        </div>
      </div>

      <div class="fmh-section-title"><i class="fas fa-coins"></i> 1. To'lov Turlari Bo'yicha Tushum (Kirim)</div>
      <table class="fmh-data-table">
        <thead>
          <tr>
            <th>To'lov Kanal / Turi</th>
            <th class="text-center">Kanal Holati</th>
            <th class="text-right">Summa (UZS)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Naqd Pul Tushumi (Kassa)</strong></td>
            <td class="text-center" style="color:#059669;">Qabul qilindi</td>
            <td class="text-right font-mono"><strong>${formatUZS(cash)}</strong></td>
          </tr>
          <tr>
            <td><strong>Terminal / Bank Plastik Kartalari</strong></td>
            <td class="text-center" style="color:#0284c7;">Bank tranzaksiya</td>
            <td class="text-right font-mono"><strong>${formatUZS(terminal)}</strong></td>
          </tr>
          <tr>
            <td><strong>Online / Click & Payme Merchant</strong></td>
            <td class="text-center" style="color:#7c3aed;">Elektron to'lov</td>
            <td class="text-right font-mono"><strong>${formatUZS(online)}</strong></td>
          </tr>
        </tbody>
        <tfoot>
          <tr>
            <td colspan="2" class="text-right">JAMI SUTKALIK KIRIM:</td>
            <td class="text-right font-mono" style="color:#059669; font-size:10pt;"><strong>${formatUZS(income)}</strong></td>
          </tr>
        </tfoot>
      </table>

      <div class="fmh-section-title"><i class="fas fa-chart-pie"></i> 2. Balans va Yakuniy Kassa Qoldig'i</div>
      <table class="fmh-data-table">
        <thead>
          <tr>
            <th>Moliyaviy Ko'rsatkich</th>
            <th class="text-right">Qiymat (UZS)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Jami Sutkalik Tushum (Kirim):</td>
            <td class="text-right font-mono" style="color:#059669;">+${formatUZS(income)}</td>
          </tr>
          <tr>
            <td>Jami Kassa Chiqimlari va Xarajatlari:</td>
            <td class="text-right font-mono" style="color:#dc2626;">-${formatUZS(expense)}</td>
          </tr>
        </tbody>
        <tfoot>
          <tr>
            <td class="text-right">SOF KASSA BALANSI (NET CASH):</td>
            <td class="text-right font-mono" style="color:#0f766e; font-size:10.5pt;"><strong>${formatUZS(net)}</strong></td>
          </tr>
        </tfoot>
      </table>

      <div class="fmh-callout-box">
        <strong>Kassa Tasdig'i:</strong> Kunlik kassa summalari va terminallar bo'yicha tushumlar to'liq solishtirildi va qabul qilindi.
      </div>

      ${getCommonAuthZone({
        doctor: zData.cashier || "Navbatchi Kassir-Buxgalter",
        patientTitle: "Bosh Buxgalter",
        patient: "Fayz Medical House"
      })}

      ${getCommonFooter()}
    `;

    printDocument(html, `FMH_Z_Report_${today}`);
  }

  /**
   * 9. DOCTOR EMR: Official Patient Case Sheet & Anamnesis (Kasallik Tarixi)
   */
  function caseHistory(patient = {}, anamnesis = {}, doctor = {}, dailyNotes = []) {
    const isAnon = Boolean(patient.is_anonymous);
    const pName = isAnon ? "[ ANONIM BEMOR ]" : (patient.full_name || "Bemor");
    const docName = doctor.full_name || "—";
    const adm = patient.active_admission || {};
    const bedStr = adm.bed_code || adm.bed_id || "Ambulator";

    const html = `
      ${getCommonHeader("KASALLIK TARIXI VA TIBBIY ANAMNEZ VARAQASI", `EMR-${patient.patient_code || patient.id || '2026'}`, "RASMIY TIBBIY KO'RIK HUJJATI")}
      
      <div class="fmh-meta-grid fmh-meta-grid-4">
        <div class="fmh-meta-item">
          <span class="lbl">Bemor F.I.Sh.</span>
          <span class="val highlight">${pName}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Bemor KODI</span>
          <span class="val font-mono">${patient.patient_code || patient.id || '—'}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Palata / Karavot</span>
          <span class="val"><i class="fas fa-bed"></i> ${bedStr}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Mas'ul Shifokor</span>
          <span class="val">${docName}</span>
        </div>
      </div>

      <div class="fmh-section-title"><i class="fas fa-comment-medical"></i> 1. Bemor Shikoyatlari (Chief Complaints)</div>
      <div class="fmh-callout-box">
        ${anamnesis.complaints || NOT_RECORDED}
      </div>

      <div class="fmh-section-title"><i class="fas fa-history"></i> 2. Kasallik Rivojlanishi (Anamnesis Morbi)</div>
      <p style="margin:4px 0; font-size:8.5pt;">
        ${anamnesis.anamnesis_morbi || NOT_RECORDED}
      </p>

      <div class="fmh-section-title"><i class="fas fa-heartbeat"></i> 3. Hayot Anamnezi & Somatik Holat (Anamnesis Vitae)</div>
      <p style="margin:4px 0; font-size:8.5pt;">
        ${anamnesis.anamnesis_vitae || anamnesis.somatic_status || NOT_RECORDED}
      </p>

      <div class="fmh-section-title"><i class="fas fa-brain"></i> 4. Psixik Status va Xulq-Atvor</div>
      <p style="margin:4px 0; font-size:8.5pt;">
        ${anamnesis.psychiatric_status || NOT_RECORDED}
      </p>

      <div class="fmh-section-title"><i class="fas fa-diagnoses"></i> 5. Klinik Tashxis (ICD-10)</div>
      <div class="fmh-callout-box blue">
        <strong>Asosiy Tashxis:</strong> ${anamnesis.diagnosis || patient.diagnosis || NOT_RECORDED}
      </div>

      ${getCommonAuthZone({
        doctor: docName,
        patientTitle: "Bosh Shifokor",
        patient: "Fayz Medical House"
      })}

      ${getCommonFooter()}
    `;

    printDocument(html, `FMH_Kasallik_Tarixi_${patient.patient_code || patient.id || '2026'}`);
  }

  /**
   * 10. WAREHOUSE: Official Goods Receipt & Delivery Note (Kirim Nakladnasi)
   */
  function warehouseReceipt(receipt = {}, lines = [], clinicInfo = {}) {
    const recId = receipt.id || 'RC-' + Date.now().toString().slice(-4);
    const dateStr = receipt.receipt_date || new Date().toISOString().slice(0, 10);
    const supplier = receipt.supplier_name || "Yetkazib Beruvchi";
    const invoiceNum = receipt.invoice_number || "—";
    const totalAmount = Number(receipt.total_amount) || 0;

    let rowsHtml = '';
    if (!lines || !lines.length) {
      rowsHtml = `<tr><td colspan="7" class="text-center" style="padding:15px; color:#64748b;">Kirim qilingan tovarlar ro'yxati mavjud emas</td></tr>`;
    } else {
      rowsHtml = lines.map((l, i) => `
        <tr>
          <td class="text-center font-mono">${l.line_no || (i + 1)}</td>
          <td><strong>${l.item_name || 'Dori / Material'}</strong></td>
          <td class="text-center font-mono">${l.batch_no || '—'}</td>
          <td class="text-center font-mono">${formatDate(l.expiry_date)}</td>
          <td class="text-center font-mono">${l.packages ? `${l.packages} qadoq` : `${l.quantity_base} dona`}</td>
          <td class="text-right font-mono">${formatUZS(l.package_price || l.unit_cost || 0)}</td>
          <td class="text-right font-mono"><strong>${formatUZS(l.line_total || 0)}</strong></td>
        </tr>
      `).join('');
    }

    const html = `
      ${getCommonHeader("TIBBIY OMBOR KIRIM NAKLADNASI (TOVAR CHEKI)", recId, "DORI-DARMON & MODDIY ZAXIRA")}
      
      <div class="fmh-meta-grid fmh-meta-grid-4">
        <div class="fmh-meta-item">
          <span class="lbl">Nakladnaya №:</span>
          <span class="val highlight font-mono">${recId}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Kirim Sanasi:</span>
          <span class="val">${formatDate(dateStr)}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Yetkazib Beruvchi:</span>
          <span class="val">${supplier}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Faktura / Hisob №:</span>
          <span class="val font-mono">${invoiceNum}</span>
        </div>
      </div>

      <div class="fmh-section-title"><i class="fas fa-boxes-stacked"></i> Qabul Qilingan Dori va Tibbiy Buyumlar</div>
      <table class="fmh-data-table">
        <thead>
          <tr>
            <th class="text-center" style="width:30px;">№</th>
            <th>Mahsulot Nomi</th>
            <th class="text-center">Partiya</th>
            <th class="text-center">Amal Qilish</th>
            <th class="text-center">Miqdor</th>
            <th class="text-right">Narxi</th>
            <th class="text-right">Jami Summa</th>
          </tr>
        </thead>
        <tbody>
          ${rowsHtml}
        </tbody>
        <tfoot>
          <tr>
            <td colspan="6" class="text-right">JAMI KIRIM SUMMASI:</td>
            <td class="text-right font-mono" style="font-size:10pt; color:#059669;"><strong>${formatUZS(totalAmount)}</strong></td>
          </tr>
        </tfoot>
      </table>

      <div class="fmh-callout-box">
        <strong>Moddiy Mas'uliyat Tasdig'i:</strong> Yuqorida ko'rsatilgan dori vositalari va materiallar butun, sertifikatlangan va yaroqlilik muddatlariga muvofiq qabul qilindi.
      </div>

      ${getCommonAuthZone({
        doctor: receipt.created_by || "Ombor Mudiri / Farmatsevt",
        patientTitle: "Yetkazib Beruvchi (Ekspeditor)",
        patient: supplier
      })}

      ${getCommonFooter()}
    `;

    printDocument(html, `FMH_Nakladnaya_${recId}`);
  }

  /**
   * 11. WAREHOUSE: Official Inventory Stock Sheet (Qoldiqlar Ro'yxati)
   */
  function warehouseInventory(items = [], meta = {}, clinicInfo = {}) {
    const today = meta.date || new Date().toISOString().slice(0, 10);
    const docId = `INV-${today.replace(/-/g, '')}`;

    let rowsHtml = '';
    if (!items || !items.length) {
      rowsHtml = `<tr><td colspan="6" class="text-center" style="padding:15px; color:#64748b;">Omborda mahsulotlar topilmadi</td></tr>`;
    } else {
      rowsHtml = items.map((it, i) => `
        <tr>
          <td class="text-center font-mono">${i + 1}</td>
          <td><strong>${it.name || it.item_name || 'Dori'}</strong></td>
          <td class="text-center">${it.category_name || it.category || '—'}</td>
          <td class="text-center font-mono"><strong>${it.total_quantity_base || it.stock || 0} ${it.base_unit || 'dona'}</strong></td>
          <td class="text-right font-mono">${formatUZS(it.avg_unit_cost || it.price || 0)}</td>
          <td class="text-right font-mono">${formatUZS((it.total_quantity_base || it.stock || 0) * (it.avg_unit_cost || it.price || 0))}</td>
        </tr>
      `).join('');
    }

    const html = `
      ${getCommonHeader("OMBOR QOLDIQLARI VA INVENTARIZATSIYA VARAQASI", docId, "DORI-DARMON & MODDIY ZAXIRA")}
      
      <div class="fmh-meta-grid fmh-meta-grid-3">
        <div class="fmh-meta-item">
          <span class="lbl">Hisob Sanasi:</span>
          <span class="val highlight">${formatDate(today)}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Mahsulot Turlari:</span>
          <span class="val font-mono">${items.length} xil</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Mas'ul Shaxs:</span>
          <span class="val">${meta.manager || "Bosh Farmatsevt / Omborchi"}</span>
        </div>
      </div>

      <div class="fmh-section-title"><i class="fas fa-pills"></i> Ombordagi Zaxiralar Ro'yxati</div>
      <table class="fmh-data-table">
        <thead>
          <tr>
            <th class="text-center" style="width:30px;">№</th>
            <th>Mahsulot Nomi</th>
            <th class="text-center">Kategoriya</th>
            <th class="text-center">Mavjud Zaxira</th>
            <th class="text-right">Birlik Narxi</th>
            <th class="text-right">Umumiy Qiymati</th>
          </tr>
        </thead>
        <tbody>
          ${rowsHtml}
        </tbody>
      </table>

      ${getCommonAuthZone({
        doctor: meta.manager || "Ombor Mudiri",
        patientTitle: "Bosh Buxgalter",
        patient: "Fayz Medical House"
      })}

      ${getCommonFooter()}
    `;

    printDocument(html, `FMH_Ombor_Qoldiq_${today}`, { orientation: 'landscape' });
  }

  /**
   * 12. CONSULTATION: Official Consultation Protocol & Treatment Plan
   */
  function consultationProtocol(patient = {}, consData = {}, doctor = {}) {
    const isAnon = Boolean(patient.is_anonymous);
    const pName = isAnon ? "[ ANONIM BEMOR ]" : (patient.full_name || "Bemor");
    const docName = doctor.full_name || doctor.username || "Shifokor";
    const consId = consData.id || `CONS-${Date.now().toString().slice(-4)}`;
    const sections = consData.sections || [];
    const plan = consData.plan || {};
    const meds = plan.medication_plan || [];

    let sectionsHtml = '';
    if (sections && sections.length) {
      sectionsHtml = sections.map(sec => `
        <div class="fmh-section-title"><i class="fas fa-stethoscope"></i> ${sec.label || 'Bo`lim'}</div>
        <div class="fmh-meta-grid">
          ${(sec.fields || []).map(f => `
            <div class="fmh-meta-item">
              <span class="lbl">${f.label || ''}</span>
              <span class="val">${f.value || NOT_RECORDED}</span>
            </div>
          `).join('')}
        </div>
      `).join('');
    }

    let medsHtml = '';
    if (meds && meds.length) {
      medsHtml = `
        <div class="fmh-section-title"><i class="fas fa-pills"></i> Tavsiya Etilgan Farmakoterapiya</div>
        <table class="fmh-data-table">
          <thead>
            <tr>
              <th>Dori Vositasining Nomi</th>
              <th class="text-center">Doza</th>
              <th class="text-center">Yuborish Yo'li</th>
              <th class="text-center">Tartib</th>
              <th class="text-center">Davomiyligi</th>
            </tr>
          </thead>
          <tbody>
            ${meds.map(m => `
              <tr>
                <td><strong>${m.name || 'Dori'}</strong></td>
                <td class="text-center font-mono">${m.dosage || '—'}</td>
                <td class="text-center">${m.route || '—'}</td>
                <td class="text-center">${m.frequency || '—'}</td>
                <td class="text-center font-mono">${m.duration_days ? m.duration_days + ' kun' : '—'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }

    const html = `
      ${getCommonHeader("KONSULTATSIYA BAYONNOMASI & TAVSIYALAR", consId, "IXTISOSLASHGAN TIBBIY KO'RIK")}
      
      <div class="fmh-meta-grid fmh-meta-grid-4">
        <div class="fmh-meta-item">
          <span class="lbl">Bemor F.I.Sh.</span>
          <span class="val highlight">${pName}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Bemor KODI</span>
          <span class="val font-mono">${patient.patient_code || patient.id || '—'}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Ko'rik Sanasi</span>
          <span class="val">${formatDate(consData.date || new Date())}</span>
        </div>
        <div class="fmh-meta-item">
          <span class="lbl">Mas'ul Shifokor</span>
          <span class="val">${docName}</span>
        </div>
      </div>

      ${sectionsHtml}
      ${medsHtml}

      ${getCommonAuthZone({
        doctor: docName,
        patientTitle: "Bemor / Qonuniy Vakil",
        patient: pName
      })}

      ${getCommonFooter()}
    `;

    printDocument(html, `FMH_Konsultatsiya_${consId}`);
  }

  // Public Exports
  return {
    admissionSlip,
    blankIntakeForm,
    prescriptionSheet,
    dischargeEpicrisis,
    patientReceipt,
    transactionReceipt,
    zReport,
    caseHistory,
    employeePayslip,
    warehouseReceipt,
    warehouseInventory,
    consultationProtocol,
    printDocument
  };

})();

