/**
 * Fayz Medical House — the one price list, shared by every page
 *
 * Each portal used to carry its own copy of the tariffs (reception, accounting,
 * the doctor wizard and superpage each hardcoded 720 000 / 1 100 000 / ...), so
 * a price changed in the editor reached some screens and not others, and the
 * desk could bill a stay at a rate that no longer existed. Every page now reads
 * data/pricing_config.json through GET /api/settings/pricing, once, here.
 *
 * Load after js/fmh_dialogs.js.
 *
 *   FMH_Pricing.ready            Promise, resolves with the price list
 *   FMH_Pricing.get()            deep copy of the current price list
 *   FMH_Pricing.rate(pkgId)      daily rate of a package (0 if unknown)
 *   FMH_Pricing.label(pkgId)     Uzbek name of a package
 *   FMH_Pricing.services()       copy of additional_services
 *   FMH_Pricing.consultationFee()
 *   FMH_Pricing.isFallback()     true while the server list is not loaded;
 *                                a page must never save the fallback back
 *   FMH_Pricing.reload()         fetch again (after a save); returns a Promise
 */
(function () {
  'use strict';

  function deepFreeze(obj) {
    Object.keys(obj).forEach(function (k) {
      const v = obj[k];
      if (v && typeof v === 'object') deepFreeze(v);
    });
    return Object.freeze(obj);
  }

  // The only browser-side copy of the defaults (it mirrors DEFAULT_PRICING in
  // server.py). It is shown only when the server cannot be reached, and is
  // flagged so that nothing is billed or saved from it unnoticed.
  const FALLBACK = deepFreeze({
    packages: {
      statsionar_shared: { daily_rate: 720000, name_uz: 'Statsionar (1 karavot / 2 kishilik xona)' },
      statsionar_full_room: { daily_rate: 1100000, name_uz: 'Statsionar Butun Xona (VIP Solo)' },
      kunlik_statsionar: { daily_rate: 630000, name_uz: "Kunlik Statsionar (Kunduzgi o'rin)" },
      ambulator_1: { daily_rate: 310000, name_uz: 'Ambulator (1 mahal)' },
      ambulator_2: { daily_rate: 500000, name_uz: 'Ambulator (2 mahal)' },
      consultation: { daily_rate: 250000, name_uz: "Shifokor Konsultatsiyasi (Birlamchi ko'rik)" }
    },
    additional_services: []
  });

  let current = FALLBACK;
  let fallback = true;

  function clone(obj) {
    return JSON.parse(JSON.stringify(obj));
  }

  function load() {
    return fetch('/api/settings/pricing', { cache: 'no-store', credentials: 'same-origin' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) {
        if (!data || typeof data.packages !== 'object' || !data.packages) {
          throw new Error('no packages');
        }
        if (!Array.isArray(data.additional_services)) data.additional_services = [];
        current = deepFreeze(data);
        fallback = false;
        return clone(current);
      })
      .catch(function (err) {
        console.warn('FMH_Pricing: server price list not loaded, using defaults', err);
        current = FALLBACK;
        fallback = true;
        return clone(current);
      });
  }

  function pkg(id) {
    const p = current.packages && current.packages[id];
    return (p && typeof p === 'object') ? p : null;
  }

  const api = {
    ready: load(),
    get: function () { return clone(current); },
    rate: function (id) {
      const p = pkg(id);
      const n = p ? Number(p.daily_rate) : 0;
      return Number.isFinite(n) ? n : 0;
    },
    label: function (id) {
      const p = pkg(id);
      return (p && p.name_uz) ? String(p.name_uz) : String(id || '');
    },
    services: function () { return clone(current.additional_services || []); },
    consultationFee: function () { return api.rate('consultation'); },
    isFallback: function () { return fallback; },
    reload: function () {
      api.ready = load();
      return api.ready;
    }
  };

  window.FMH_Pricing = api;
})();
