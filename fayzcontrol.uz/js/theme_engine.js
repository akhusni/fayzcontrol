/**
 * FAYZ MEDICAL HOUSE — CENTRALIZED ENTERPRISE THEME & SHIFT ENGINE
 * Provides instant zero-flash theme persistence, synchronized Day/Night shifts,
 * cross-tab reactivity, and unified button state management across all portals.
 */

(function () {
  'use strict';

  const STORAGE_KEY = 'fmh_theme';
  const DEFAULT_THEME = 'night'; // Enterprise clinic default

  // 1. Instant Evaluator: Determine active theme immediately
  function getStoredTheme() {
    try {
      return localStorage.getItem(STORAGE_KEY) || DEFAULT_THEME;
    } catch (e) {
      return DEFAULT_THEME;
    }
  }

  // 2. Core Theme Applier
  function applyTheme(theme, showNotification = false) {
    const activeTheme = (theme === 'day' || theme === 'light') ? 'day' : 'night';
    
    // Set root attributes
    document.documentElement.setAttribute('data-theme', activeTheme);
    
    // Update body classes safely without erasing portal-specific classes
    if (document.body) {
      document.body.classList.remove('day-mode', 'night-mode', 'light-mode', 'dark-mode');
      document.body.classList.add(`${activeTheme}-mode`);
    }

    // Persist to localStorage
    try {
      localStorage.setItem(STORAGE_KEY, activeTheme);
    } catch (e) {
      console.warn('localStorage access denied:', e);
    }

    // Synchronize all theme toggle buttons in the DOM
    syncButtons(activeTheme);

    // Optional Toast Notification
    if (showNotification) {
      const msg = activeTheme === 'day' 
        ? '☀️ <strong>Kunduzgi smena (Day Shift)</strong> yoqildi' 
        : '🌙 <strong>Tungi smena (Night Shift)</strong> yoqildi';
      showThemeToast(msg, activeTheme);
    }

    // Dispatch custom event for charts or components that need redrawing
    try {
      window.dispatchEvent(new CustomEvent('fmh-theme-changed', { detail: { theme: activeTheme } }));
    } catch (e) {}

    return activeTheme;
  }

  // 3. Toggle Shift (Debounced against rapid clicks & dual event triggers)
  let lastToggleTime = 0;
  function toggleTheme() {
    const now = Date.now();
    if (now - lastToggleTime < 250) {
      return getStoredTheme();
    }
    lastToggleTime = now;
    const current = getStoredTheme();
    const next = current === 'day' ? 'night' : 'day';
    applyTheme(next, true);
    return next;
  }

  // 4. Synchronize Button UI
  function syncButtons(theme) {
    const activeTheme = theme || getStoredTheme();
    const isDay = activeTheme === 'day';

    // Find all theme toggle buttons by class, id, or attribute
    const buttons = document.querySelectorAll(
      '.btn-unified-theme-toggle, .theme-toggle-btn, [data-action="toggle-theme"], ' +
      '#super-theme-toggle-btn, #building-theme-toggle, #reception-theme-toggle, ' +
      '#accounting-theme-toggle, #doctor-theme-toggle, #crm-theme-toggle, #hr-theme-toggle, #report-theme-toggle, #blank-theme-toggle'
    );

    buttons.forEach(btn => {
      if (isDay) {
        btn.innerHTML = '<i class="fas fa-moon"></i> <span>Tungi</span>';
        btn.title = "Tungi rejimga o'tish (Night Shift)";
        btn.setAttribute('aria-label', "Tungi rejimga o'tish");
        btn.classList.add('shift-day-active');
        btn.classList.remove('shift-night-active');
      } else {
        btn.innerHTML = '<i class="fas fa-sun"></i> <span>Kunduzgi</span>';
        btn.title = "Kunduzgi rejimga o'tish (Day Shift)";
        btn.setAttribute('aria-label', "Kunduzgi rejimga o'tish");
        btn.classList.add('shift-night-active');
        btn.classList.remove('shift-day-active');
      }
    });
  }

  // 5. Shared Toast Notification
  function showThemeToast(htmlMsg, theme) {
    let container = document.getElementById('fmh-theme-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'fmh-theme-toast-container';
      container.style.cssText = `
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 999999;
        display: flex;
        flex-direction: column;
        gap: 8px;
        pointer-events: none;
      `;
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    const isDay = theme === 'day';
    toast.style.cssText = `
      background: ${isDay ? '#ffffff' : '#0a172e'};
      color: ${isDay ? '#0f172a' : '#f8fafc'};
      border: 1px solid ${isDay ? '#cbd5e1' : 'rgba(56, 189, 248, 0.35)'};
      border-left: 4px solid ${isDay ? '#0284c7' : '#38bdf8'};
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, ${isDay ? '0.15' : '0.5'});
      padding: 10px 16px;
      border-radius: 8px;
      font-family: 'Plus Jakarta Sans', sans-serif;
      font-size: 0.82rem;
      display: flex;
      align-items: center;
      gap: 10px;
      pointer-events: auto;
      transform: translateY(15px);
      opacity: 0;
      transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1);
    `;
    toast.innerHTML = htmlMsg;
    container.appendChild(toast);

    // Animate in
    requestAnimationFrame(() => {
      toast.style.transform = 'translateY(0)';
      toast.style.opacity = '1';
    });

    // Auto dismiss
    setTimeout(() => {
      toast.style.transform = 'translateY(-10px)';
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 250);
    }, 2800);
  }

  // 6. Cross-Tab Real-Time Sync
  window.addEventListener('storage', (e) => {
    if (e.key === STORAGE_KEY && e.newValue) {
      applyTheme(e.newValue, false);
    }
  });

  // 7. Global API Export & Portal Adapters
  window.FMH_Theme = {
    get: getStoredTheme,
    set: applyTheme,
    toggle: toggleTheme,
    syncButtons: syncButtons
  };

  // Safe wrapper for portal namespaces
  function bridgeToPortals() {
    const portals = ['FMH_Super', 'FMH_Reception', 'FMH_Building', 'FMH_Accounting', 'FMH_Doctor', 'FMH_CRM', 'FMH_HR', 'FMH_Report'];
    portals.forEach(portalName => {
      window[portalName] = window[portalName] || {};
      window[portalName].toggleTheme = toggleTheme;
      window[portalName].applyTheme = applyTheme;
    });
  }
  bridgeToPortals();

  // 8. Run Immediately on Execution
  const initial = getStoredTheme();
  document.documentElement.setAttribute('data-theme', initial);
  if (document.body) {
    document.body.classList.add(`${initial}-mode`);
  }

  // 9. DOM Ready Initialization
  function onReady() {
    applyTheme(getStoredTheme(), false);
    bridgeToPortals();
    syncButtons();
    
    // Bind click handlers to any un-bound theme toggle buttons (skip if inline onclick exists)
    document.querySelectorAll('.btn-unified-theme-toggle, .theme-toggle-btn').forEach(btn => {
      if (!btn.getAttribute('data-theme-bound')) {
        btn.setAttribute('data-theme-bound', 'true');
        if (!btn.getAttribute('onclick')) {
          btn.addEventListener('click', (e) => {
            e.preventDefault();
            toggleTheme();
          });
        }
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', onReady);
  } else {
    onReady();
  }

})();
