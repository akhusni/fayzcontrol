/**
 * Fayz Medical House - Clinical Pharmacology & Drug Search Engine
 * Universal Bi-directional Transliteration (Cyrillic ⇄ Latin)
 * Version: 4.0.0-ENTERPRISE
 * 
 * Capabilities:
 * - Single input for all scripts (Kirill yoki Lotin yozuvida yozganda ham dorini aniq topadi)
 * - Medical phonetic normalization (x <-> ks, c <-> ts <-> s, ph <-> f, th <-> t)
 * - Clinic Formulary (#1-#88) number search (18, №18, #18)
 * - INN/MNN, Trade Name, Paper Name, Indication multi-field search
 * - Smart Scoring & Relevance ranking
 * - Interactive Accessible Dropdown with Keyboard Navigation
 */

(function (global) {
  'use strict';

  // 1. Cyrillic to Latin character map (Russian & Uzbek Cyrillic)
  const CYR_TO_LAT_MAP = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
    'ж': 'j', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'x', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ъ': '', 'ы': 'i', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    'ў': "o'", 'ғ': "g'", 'қ': 'q', 'ҳ': 'h'
  };

  // 2. Latin to Cyrillic rules (ordered from multi-character to single)
  const LAT_TO_CYR_RULES = [
    ['shch', 'щ'], ['ch', 'ч'], ['sh', 'ш'], ['yo', 'ё'], ['yu', 'ю'], ['ya', 'я'],
    ['ts', 'ц'], ['tc', 'ц'],
    ["o'", 'ў'], ["o`", 'ў'], ["o‘", 'ў'], ["o’", 'ў'], ["õ", 'ў'],
    ["g'", 'ғ'], ["g`", 'ғ'], ["g‘", 'ғ'], ["g’", 'ғ'], ["ğ", 'ғ'],
    ['ye', 'е'], ['ph', 'ф'], ['th', 'т'], ['kh', 'х'], ['zh', 'ж'],
    ['a', 'а'], ['b', 'б'], ['c', 'ц'], ['d', 'д'], ['e', 'е'], ['f', 'ф'],
    ['g', 'г'], ['h', 'ҳ'], ['i', 'и'], ['j', 'ж'], ['k', 'к'], ['l', 'л'],
    ['m', 'м'], ['n', 'н'], ['o', 'о'], ['p', 'п'], ['q', 'қ'], ['r', 'р'],
    ['s', 'с'], ['t', 'т'], ['u', 'у'], ['v', 'в'], ['w', 'в'], ['x', 'кс'],
    ['y', 'й'], ['z', 'з']
  ];

  function cyrToLat(text) {
    if (!text) return '';
    const str = String(text).toLowerCase();
    let res = '';
    for (let i = 0; i < str.length; i++) {
      const c = str[i];
      res += CYR_TO_LAT_MAP[c] !== undefined ? CYR_TO_LAT_MAP[c] : c;
    }
    return res;
  }

  function latToCyr(text) {
    if (!text) return '';
    let str = String(text).toLowerCase();
    for (const [lat, cyr] of LAT_TO_CYR_RULES) {
      str = str.split(lat).join(cyr);
    }
    return str;
  }

  function normalizePunctuation(text) {
    if (!text) return '';
    return String(text).toLowerCase()
      .replace(/[ʻʼ`'"]/g, '')
      .replace(/[-\s.,;:\/\\()№#+]/g, '');
  }

  function detectScript(text) {
    if (!text) return 'empty';
    const cyrRegex = /[\u0400-\u04FF]/;
    const latRegex = /[a-zA-Z]/;
    const hasCyr = cyrRegex.test(text);
    const hasLat = latRegex.test(text);
    if (hasCyr && hasLat) return 'mixed';
    if (hasCyr) return 'cyrillic';
    if (hasLat) return 'latin';
    return 'numeric';
  }

  /**
   * Generates comprehensive search token variants for forgiving fuzzy matching
   */
  function getSearchVariants(query) {
    if (!query) return [];
    const raw = String(query).trim().toLowerCase();
    if (!raw) return [];

    const variants = new Set();
    variants.add(raw);

    const normRaw = normalizePunctuation(raw);
    if (normRaw) variants.add(normRaw);

    const lat = cyrToLat(raw);
    const cyr = latToCyr(raw);
    variants.add(lat);
    variants.add(cyr);

    const normLat = normalizePunctuation(lat);
    const normCyr = normalizePunctuation(cyr);
    if (normLat) variants.add(normLat);
    if (normCyr) variants.add(normCyr);

    // Phonetic alternates: x <-> ks (mexidol <-> meksidol)
    [lat, normLat].forEach(t => {
      if (!t) return;
      if (t.includes('x')) {
        variants.add(t.replace(/x/g, 'ks'));
      }
      if (t.includes('ks')) {
        variants.add(t.replace(/ks/g, 'x'));
      }
      // c <-> ts <-> s (ceftriaxone <-> tseftriakson, ceraxon <-> serakson)
      if (t.includes('c')) {
        variants.add(t.replace(/c/g, 'ts'));
        variants.add(t.replace(/c/g, 's'));
      }
      if (t.includes('ts')) {
        variants.add(t.replace(/ts/g, 'c'));
        variants.add(t.replace(/ts/g, 's'));
      }
      if (t.includes('s')) {
        variants.add(t.replace(/s/g, 'ts'));
        variants.add(t.replace(/s/g, 'c'));
      }
      // ti/tia -> si/sia (essentiale -> essensiale)
      if (t.includes('tia')) {
        variants.add(t.replace(/tia/g, 'sia'));
      }
      if (t.includes('sia')) {
        variants.add(t.replace(/sia/g, 'tia'));
      }
      // double consonant normalization (ss -> s, ll -> l, tt -> t, etc.)
      const dedup = t.replace(/([b-df-hj-np-tv-z])\1+/g, '$1');
      if (dedup !== t) variants.add(dedup);
    });

    // Cyrillic alternates: ц <-> с, х <-> ҳ
    [cyr, normCyr].forEach(t => {
      if (!t) return;
      if (t.includes('ц')) variants.add(t.replace(/ц/g, 'с'));
      if (t.includes('с')) variants.add(t.replace(/с/g, 'ц'));
      if (t.includes('х')) variants.add(t.replace(/х/g, 'ҳ'));
      if (t.includes('ҳ')) variants.add(t.replace(/ҳ/g, 'х'));
      // B6 vs В6
      if (t.includes('б') && t.includes('6')) variants.add(t.replace(/б/g, 'в'));
      if (t.includes('в') && t.includes('6')) variants.add(t.replace(/в/g, 'б'));
      const dedup = t.replace(/([бвгджзклмнпрстфхцчшщ])\1+/g, '$1');
      if (dedup !== t) variants.add(dedup);
    });

    return Array.from(variants).filter(v => v.length > 0);
  }

  /**
   * Evaluates match quality between a medication item and a query
   * Returns a score (higher is better), 0 if no match
   */
  function scoreMedMatch(med, queryTokens, rawQuery, isPureNum, targetNum) {
    let score = 0;
    const medNum = String(med.fayz_house_num || '');

    // Number match bonus (e.g. searching "18" or "№18" or "#18")
    if (isPureNum && targetNum && medNum === targetNum) {
      score += 2000;
      return score;
    }

    const fields = [
      { text: med.name || '', weight: 120, isMain: true },
      { text: med.paper_name || '', weight: 110, isMain: true },
      { text: med.trade_name || '', weight: 90 },
      { text: med.trade_name_uz || '', weight: 90 },
      { text: med.trade_name_ru || '', weight: 90 },
      { text: med.trade_name_en || '', weight: 80 },
      { text: med.inn || '', weight: 75 },
      { text: med.inn_uz || '', weight: 75 },
      { text: med.inn_ru || '', weight: 75 },
      { text: med.dosage_form || med.form || '', weight: 20 },
      { text: med.category_name_uz || med.category_label || '', weight: 25 },
      { text: (med.indications && (med.indications.uz || med.indications.ru || '')) || '', weight: 35 }
    ];

    let maxFieldScore = 0;

    function extractText(val) {
      if (!val) return '';
      if (typeof val === 'string') return val;
      if (typeof val === 'number') return String(val);
      if (typeof val === 'object') {
        return Object.values(val).filter(v => typeof v === 'string').join(' ');
      }
      return '';
    }

    for (const f of fields) {
      const rawText = extractText(f.text);
      if (!rawText) continue;
      const fLower = rawText.toLowerCase();
      const fLat = cyrToLat(fLower);
      const fCyr = latToCyr(fLower);
      const fNorm = normalizePunctuation(fLower);
      const fNormLat = normalizePunctuation(fLat);
      const fNormCyr = normalizePunctuation(fCyr);

      for (const tok of queryTokens) {
        if (!tok) continue;
        const len = tok.length;
        // Skip single character tokens unless it is a whole standalone word or clinic number
        if (len < 2) continue;

        // Exact full match
        if (fLower === tok || fLat === tok || fCyr === tok || fNorm === tok || fNormLat === tok || fNormCyr === tok) {
          maxFieldScore = Math.max(maxFieldScore, f.weight * 6);
        }
        // Prefix match at start of field
        else if (fLower.startsWith(tok) || fLat.startsWith(tok) || fCyr.startsWith(tok) ||
                 fNorm.startsWith(tok) || fNormLat.startsWith(tok) || fNormCyr.startsWith(tok)) {
          maxFieldScore = Math.max(maxFieldScore, f.weight * 4);
        }
        // Word boundary match (e.g. "(Diazepam)" in "Verzepam 0.5% (Diazepam)")
        else if (
          fLower.includes(' ' + tok) || fLower.includes('(' + tok) ||
          fLat.includes(' ' + tok) || fLat.includes('(' + tok) ||
          fCyr.includes(' ' + tok) || fCyr.includes('(' + tok)
        ) {
          maxFieldScore = Math.max(maxFieldScore, f.weight * 3);
        }
        // General substring match
        else if (
          fLower.includes(tok) || fLat.includes(tok) || fCyr.includes(tok) ||
          fNorm.includes(tok) || fNormLat.includes(tok) || fNormCyr.includes(tok)
        ) {
          maxFieldScore = Math.max(maxFieldScore, f.weight * 1.5);
        }
      }
    }

    score += maxFieldScore;

    // Small boost for clinic formulary drugs so they rank nicely
    if (score > 0 && med.fayz_house_list) {
      score += 15;
    }

    return score;
  }

  /**
   * Search and rank medications by any query (Cyrillic, Latin, or Number)
   * @param {Array} medications - list of drug objects
   * @param {string} query - search query
   * @param {string} [categoryFilter='all'] - optional category key
   * @returns {Array} - sorted array of matching drug objects
   */
  function search(medications, query, categoryFilter = 'all') {
    if (!Array.isArray(medications)) return [];
    const qRaw = String(query || '').trim();
    if (!qRaw) {
      const base = (categoryFilter && categoryFilter !== 'all')
        ? medications.filter(m => m.category === categoryFilter)
        : medications;
      const seen = new Set();
      const deduped = [];
      for (const m of base) {
        const key = m.id || (m.fayz_house_num ? 'num_' + m.fayz_house_num : (m.name ? m.name.toLowerCase().trim() : null));
        if (key && seen.has(key)) continue;
        if (key) seen.add(key);
        deduped.push(m);
      }
      return deduped;
    }

    const numClean = qRaw.replace(/^[№#\s]+/, '').trim();
    const isPureNum = /^\d+$/.test(numClean);
    const tokens = getSearchVariants(qRaw);

    const scored = [];
    const seen = new Set();
    for (let i = 0; i < medications.length; i++) {
      const med = medications[i];
      if (categoryFilter && categoryFilter !== 'all' && med.category !== categoryFilter) {
        continue;
      }
      const key = med.id || (med.fayz_house_num ? 'num_' + med.fayz_house_num : (med.name ? med.name.toLowerCase().trim() : i));
      if (seen.has(key)) continue;
      seen.add(key);

      const score = scoreMedMatch(med, tokens, qRaw, isPureNum, numClean);
      if (score > 0) {
        scored.push({ med, score });
      }
    }

    scored.sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      return (a.med.fayz_house_num || 999) - (b.med.fayz_house_num || 999);
    });

    return scored.map(s => s.med);
  }

  /**
   * Find single best matching medication (useful for auto-fill on input blur or enter)
   */
  function findBestMatch(medications, query) {
    if (!query || !Array.isArray(medications)) return null;
    const results = search(medications, query);
    return results.length > 0 ? results[0] : null;
  }

  /**
   * Escapes HTML entities
   */
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /**
   * Highlights matched portion in text safely
   */
  function highlightMatched(text, query) {
    if (!text) return '';
    if (!query) return escapeHtml(text);
    const safeText = String(text);
    const tokens = getSearchVariants(query)
      .filter(t => t.length >= 2)
      .sort((a, b) => b.length - a.length);

    if (tokens.length === 0) return escapeHtml(safeText);

    // Escape regex characters
    const escaped = tokens.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    try {
      const regex = new RegExp(`(${escaped.join('|')})`, 'gi');
      return safeText.replace(regex, '<mark class="fmh-med-highlight">$1</mark>');
    } catch (e) {
      return escapeHtml(safeText);
    }
  }

  /**
   * Generates badge HTML for prescription type
   */
  function getBadgeHTML(prescriptionType) {
    if (prescriptionType === 'Rx_Strict_Psychotropic') {
      return '<span class="fmh-badge-rx-strict"><i class="fas fa-exclamation-triangle"></i> Qat\'iy Psixotrop</span>';
    } else if (prescriptionType === 'Rx_Standard') {
      return '<span class="fmh-badge-rx-std"><i class="fas fa-file-prescription"></i> Rx Retseptli</span>';
    }
    return '<span class="fmh-badge-otc"><i class="fas fa-check-circle"></i> OTC Retseptsiz</span>';
  }

  /**
   * Attaches interactive live autocomplete dropdown to a search input
   * @param {Object} options
   * @param {HTMLInputElement} options.input - search input element
   * @param {Function|Array} options.getMedications - returns array of meds
   * @param {Function} options.onSelect - callback(selectedMed)
   * @param {Function} [options.onClear] - optional callback on clear
   */
  function attachAutocomplete(options) {
    const input = options.input;
    if (!input) return null;
    input.removeAttribute('list');
    input.setAttribute('autocomplete', 'off');

    const getMeds = typeof options.getMedications === 'function' ? options.getMedications : () => options.getMedications || [];
    const onSelect = options.onSelect || (() => {});
    const onClear = options.onClear || (() => {});

    // Ensure styling is present in document head
    injectStyles();

    // Wrap input container if not already wrapped
    let wrapper = input.closest('.fmh-med-search-wrapper');
    if (!wrapper) {
      wrapper = document.createElement('div');
      wrapper.className = 'fmh-med-search-wrapper';
      input.parentNode.insertBefore(wrapper, input);
      wrapper.appendChild(input);
    }

    // Add script indicator pill and clear button inside wrapper
    let clearBtn = wrapper.querySelector('.fmh-med-clear-btn');
    if (!clearBtn) {
      clearBtn = document.createElement('button');
      clearBtn.type = 'button';
      clearBtn.className = 'fmh-med-clear-btn';
      clearBtn.title = 'Tozalash (Clear)';
      clearBtn.innerHTML = '<i class="fas fa-times"></i>';
      clearBtn.style.display = input.value ? 'flex' : 'none';
      wrapper.appendChild(clearBtn);

      clearBtn.addEventListener('click', (e) => {
        e.preventDefault();
        input.value = '';
        clearBtn.style.display = 'none';
        closeDropdown();
        input.focus();
        onClear();
        if (options.onInput) options.onInput('');
      });
    }

    // Add script indicator
    let scriptBadge = wrapper.querySelector('.fmh-med-script-badge');
    if (!scriptBadge) {
      scriptBadge = document.createElement('span');
      scriptBadge.className = 'fmh-med-script-badge';
      scriptBadge.title = 'Kirill yoki Lotin alifbosida qidirish mumkin (Bitta qidiruv maydoni)';
      scriptBadge.innerHTML = '🔤 Lotin ⇄ Кирилл';
      wrapper.appendChild(scriptBadge);
    }

    // Create dropdown container
    let dropdown = wrapper.querySelector('.fmh-med-dropdown');
    if (!dropdown) {
      dropdown = document.createElement('div');
      dropdown.className = 'fmh-med-dropdown';
      wrapper.appendChild(dropdown);
    }

    let activeIndex = -1;
    let currentResults = [];

    function updateScriptBadge(val) {
      if (!val) {
        scriptBadge.innerHTML = '🔤 Lotin ⇄ Кирилл';
        scriptBadge.className = 'fmh-med-script-badge';
        return;
      }
      const s = detectScript(val);
      if (s === 'cyrillic') {
        scriptBadge.innerHTML = '🇷🇺 Кирилл ➔ Lotin';
        scriptBadge.className = 'fmh-med-script-badge fmh-script-cyr';
      } else if (s === 'latin') {
        scriptBadge.innerHTML = '🇺🇿 Lotin ➔ Кирилл';
        scriptBadge.className = 'fmh-med-script-badge fmh-script-lat';
      } else {
        scriptBadge.innerHTML = '🔤 Aqlli Qidiruv';
        scriptBadge.className = 'fmh-med-script-badge';
      }
    }

    function renderDropdown(items, query) {
      currentResults = items;
      activeIndex = -1;

      if (!items || items.length === 0) {
        if (!query.trim()) {
          closeDropdown();
          return;
        }
        dropdown.innerHTML = `
          <div class="fmh-med-no-results">
            <i class="fas fa-search"></i>
            <div><strong>"${escapeHtml(query)}"</strong> bo'yicha dori topilmadi</div>
            <span>Kirill yoki Lotin alifbosida yozib ko'ring (masalan: <em>mexidol / мексидол / 18</em>)</span>
          </div>
        `;
        openDropdown();
        return;
      }

      const limit = Math.min(items.length, 12);
      const rows = [];

      for (let i = 0; i < limit; i++) {
        const m = items[i];
        const numBadge = m.fayz_house_num ? `<span class="fmh-med-num">№${m.fayz_house_num}</span>` : '';
        const badgeHTML = getBadgeHTML(m.prescription_type);

        const displayName = highlightMatched(m.name || m.trade_name_uz || 'Dori', query);
        const paperName = m.paper_name && m.paper_name !== m.name
          ? `<span class="fmh-med-sub-paper">Qog'ozda: ${highlightMatched(m.paper_name, query)}</span>`
          : '';
        const innText = m.inn ? `<span class="fmh-med-inn">МНН: ${highlightMatched(m.inn, query)}</span>` : '';

        const metaForm = m.dosage_form || m.form || '—';
        const metaDose = m.default_dosage ? ` • ${m.default_dosage}` : '';
        const metaRoute = m.default_route ? ` • ${m.default_route}` : '';

        rows.push(`
          <div class="fmh-med-item" data-index="${i}">
            <div class="fmh-med-item-main">
              <div class="fmh-med-item-title">
                ${numBadge}
                <strong>${displayName}</strong>
                ${badgeHTML}
              </div>
              <div class="fmh-med-item-synonyms">
                ${paperName}
                ${innText}
              </div>
              <div class="fmh-med-item-dosage">
                <i class="fas fa-pills"></i> <span>${escapeHtml(metaForm)}${escapeHtml(metaDose)}${escapeHtml(metaRoute)}</span>
              </div>
            </div>
            <div class="fmh-med-item-action">
              <span class="fmh-btn-select-chip"><i class="fas fa-check"></i> Tanlash</span>
            </div>
          </div>
        `);
      }

      if (items.length > limit) {
        rows.push(`
          <div class="fmh-med-more-hint">
            Yana +${items.length - limit} ta dori mavjud. Qidiruvni aniqlashtiring...
          </div>
        `);
      }

      dropdown.innerHTML = rows.join('');
      openDropdown();

      // Add click handlers
      dropdown.querySelectorAll('.fmh-med-item').forEach(itemEl => {
        itemEl.addEventListener('click', () => {
          const idx = parseInt(itemEl.getAttribute('data-index'), 10);
          if (currentResults[idx]) {
            chooseItem(currentResults[idx]);
          }
        });
      });
    }

    function openDropdown() {
      dropdown.classList.add('fmh-dropdown-open');
    }

    function closeDropdown() {
      dropdown.classList.remove('fmh-dropdown-open');
      activeIndex = -1;
    }

    function highlightActiveItem() {
      const items = dropdown.querySelectorAll('.fmh-med-item');
      items.forEach((it, idx) => {
        if (idx === activeIndex) {
          it.classList.add('fmh-item-active');
          it.scrollIntoView({ block: 'nearest' });
        } else {
          it.classList.remove('fmh-item-active');
        }
      });
    }

    function chooseItem(med) {
      if (!med) return;
      input.value = med.name || med.paper_name || '';
      clearBtn.style.display = 'flex';
      updateScriptBadge(input.value);
      closeDropdown();
      onSelect(med);
    }

    // Input event handler
    input.addEventListener('input', (e) => {
      const val = e.target.value;
      clearBtn.style.display = val ? 'flex' : 'none';
      updateScriptBadge(val);

      if (options.onInput) options.onInput(val);

      if (!val.trim()) {
        closeDropdown();
        return;
      }

      const meds = getMeds();
      const filtered = search(meds, val);
      renderDropdown(filtered, val);
    });

    // Keyboard navigation
    input.addEventListener('keydown', (e) => {
      if (!dropdown.classList.contains('fmh-dropdown-open')) {
        if (e.key === 'ArrowDown' && input.value.trim()) {
          const meds = getMeds();
          const filtered = search(meds, input.value);
          renderDropdown(filtered, input.value);
          e.preventDefault();
        }
        return;
      }

      const items = dropdown.querySelectorAll('.fmh-med-item');
      const max = items.length;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        activeIndex = (activeIndex + 1) % max;
        highlightActiveItem();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        activeIndex = (activeIndex - 1 + max) % max;
        highlightActiveItem();
      } else if (e.key === 'Enter') {
        if (activeIndex >= 0 && currentResults[activeIndex]) {
          e.preventDefault();
          chooseItem(currentResults[activeIndex]);
        } else {
          closeDropdown();
        }
      } else if (e.key === 'Escape') {
        e.preventDefault();
        closeDropdown();
      }
    });

    // Close on outside click
    document.addEventListener('click', (e) => {
      if (!wrapper.contains(e.target)) {
        closeDropdown();
      }
    });

    // Open suggestions on input focus if there is text
    input.addEventListener('focus', () => {
      if (input.value.trim()) {
        const meds = getMeds();
        const filtered = search(meds, input.value);
        renderDropdown(filtered, input.value);
      }
    });

    return {
      close: closeDropdown,
      search: (q) => {
        const meds = getMeds();
        return search(meds, q);
      },
      select: chooseItem
    };
  }

  /**
   * Injects CSS for modern high-polish search dropdown and badges
   */
  function injectStyles() {
    if (document.getElementById('fmh-med-search-styles')) return;
    const style = document.createElement('style');
    style.id = 'fmh-med-search-styles';
    style.innerHTML = `
      .fmh-med-search-wrapper {
        position: relative;
        width: 100%;
        display: flex;
        align-items: center;
      }
      .fmh-med-clear-btn {
        position: absolute;
        right: 130px;
        top: 50%;
        transform: translateY(-50%);
        width: 22px;
        height: 22px;
        border-radius: 50%;
        border: none;
        background: rgba(148, 163, 184, 0.25);
        color: var(--text-secondary, #64748b);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 0.72rem;
        cursor: pointer;
        transition: all 0.15s;
        z-index: 5;
      }
      .fmh-med-clear-btn:hover {
        background: #ef4444;
        color: #ffffff;
      }
      .fmh-med-script-badge {
        position: absolute;
        right: 8px;
        top: 50%;
        transform: translateY(-50%);
        font-size: 0.68rem;
        font-weight: 700;
        padding: 3px 8px;
        border-radius: 6px;
        background: rgba(13, 148, 136, 0.12);
        color: #0d9488;
        border: 1px solid rgba(13, 148, 136, 0.25);
        pointer-events: none;
        white-space: nowrap;
        transition: all 0.2s;
        z-index: 4;
      }
      .fmh-med-script-badge.fmh-script-cyr {
        background: rgba(14, 165, 233, 0.14);
        color: #0284c7;
        border-color: rgba(14, 165, 233, 0.3);
      }
      .fmh-med-script-badge.fmh-script-lat {
        background: rgba(168, 85, 247, 0.14);
        color: #9333ea;
        border-color: rgba(168, 85, 247, 0.3);
      }
      .fmh-med-dropdown {
        position: absolute;
        top: calc(100% + 4px);
        left: 0;
        right: 0;
        max-height: 380px;
        overflow-y: auto;
        background: var(--card-bg, #ffffff);
        border: 1px solid var(--border-color, #cbd5e1);
        border-radius: 12px;
        box-shadow: 0 15px 35px -5px rgba(0, 0, 0, 0.25), 0 5px 15px rgba(0,0,0,0.1);
        z-index: 99999;
        display: none;
        flex-direction: column;
        padding: 6px;
      }
      .fmh-med-dropdown.fmh-dropdown-open {
        display: flex;
      }
      .fmh-med-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 8px 12px;
        border-radius: 8px;
        cursor: pointer;
        transition: background 0.12s;
        border-bottom: 1px solid rgba(226, 232, 240, 0.5);
      }
      .fmh-med-item:last-child {
        border-bottom: none;
      }
      .fmh-med-item:hover,
      .fmh-med-item.fmh-item-active {
        background: rgba(13, 148, 136, 0.08);
      }
      .fmh-med-item-main {
        flex: 1;
        min-width: 0;
      }
      .fmh-med-item-title {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
        font-size: 0.9rem;
        color: var(--text-primary, #0f172a);
      }
      .fmh-med-num {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 28px;
        height: 20px;
        padding: 0 5px;
        font-size: 0.72rem;
        font-weight: 800;
        border-radius: 5px;
        background: #f1f5f9;
        color: #0b3b60;
        border: 1px solid #cbd5e1;
      }
      .fmh-badge-rx-strict {
        font-size: 0.68rem;
        font-weight: 700;
        padding: 1px 6px;
        border-radius: 4px;
        background: #fef2f2;
        color: #dc2626;
        border: 1px solid #fecaca;
      }
      .fmh-badge-rx-std {
        font-size: 0.68rem;
        font-weight: 700;
        padding: 1px 6px;
        border-radius: 4px;
        background: #eff6ff;
        color: #2563eb;
        border: 1px solid #bfdbfe;
      }
      .fmh-badge-otc {
        font-size: 0.68rem;
        font-weight: 700;
        padding: 1px 6px;
        border-radius: 4px;
        background: #f0fdf4;
        color: #16a34a;
        border: 1px solid #bbf7d0;
      }
      .fmh-med-item-synonyms {
        display: flex;
        gap: 8px;
        font-size: 0.76rem;
        color: var(--text-muted, #64748b);
        margin-top: 2px;
        flex-wrap: wrap;
      }
      .fmh-med-sub-paper {
        color: #0284c7;
        font-weight: 500;
      }
      .fmh-med-inn {
        color: #64748b;
      }
      .fmh-med-item-dosage {
        font-size: 0.73rem;
        color: #475569;
        margin-top: 3px;
        display: flex;
        align-items: center;
        gap: 5px;
      }
      .fmh-med-item-dosage i {
        color: #0d9488;
        font-size: 0.68rem;
      }
      .fmh-btn-select-chip {
        font-size: 0.72rem;
        font-weight: 600;
        color: #0d9488;
        background: rgba(13, 148, 136, 0.1);
        padding: 4px 8px;
        border-radius: 6px;
        white-space: nowrap;
        display: flex;
        align-items: center;
        gap: 4px;
      }
      .fmh-med-item:hover .fmh-btn-select-chip,
      .fmh-med-item.fmh-item-active .fmh-btn-select-chip {
        background: #0d9488;
        color: #ffffff;
      }
      .fmh-med-highlight {
        background: #fef08a;
        color: #854d0e;
        padding: 0 2px;
        border-radius: 3px;
        font-weight: 700;
      }
      .fmh-med-no-results {
        padding: 24px 16px;
        text-align: center;
        color: #64748b;
      }
      .fmh-med-no-results i {
        font-size: 1.8rem;
        color: #cbd5e1;
        margin-bottom: 8px;
        display: block;
      }
      .fmh-med-no-results strong {
        color: #0f172a;
        font-size: 0.9rem;
      }
      .fmh-med-no-results span {
        font-size: 0.78rem;
        display: block;
        margin-top: 4px;
      }
      .fmh-med-more-hint {
        padding: 6px 12px;
        text-align: center;
        font-size: 0.72rem;
        color: #94a3b8;
        background: #f8fafc;
        border-top: 1px solid #e2e8f0;
      }
    `;
    document.head.appendChild(style);
  }

  // Export
  const FMH_MedSearch = {
    cyrToLat,
    latToCyr,
    detectScript,
    normalizePunctuation,
    getSearchVariants,
    search,
    findBestMatch,
    highlightMatched,
    getBadgeHTML,
    attachAutocomplete,
    injectStyles
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = FMH_MedSearch;
  } else {
    global.FMH_MedSearch = FMH_MedSearch;
  }
})(typeof window !== 'undefined' ? window : globalThis);
