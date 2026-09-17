/**
 * Fayz Medical House — Shared Dialog & Notification Layer
 *
 * The confirmation dialog used to live inside building_management.js, so it was
 * only defined on the Statsionar page. Every other module fell back either to
 * the browser's native confirm()/alert() boxes or, in doctor.js, to a fallback
 * that auto-confirmed and deleted without asking. It lives here so all portals
 * share one implementation; the matching .fmh-confirm-* styles are already in
 * css/unified_header.css, which every page loads.
 *
 * Provides:
 *   window.FMH_ConfirmDialog({...})   callback style (unchanged contract)
 *   window.fmhConfirm({...})          promise style, resolves true/false
 *   window.FMH_Toast(message, type)   accessible toast notification
 */
(function () {
  'use strict';

  // -------------------------------------------------------------------------
  // Confirmation dialog
  // -------------------------------------------------------------------------
  window.FMH_ConfirmDialog = function ({
    title = "Tasdiqlash",
    message = "Ushbu amalni bajarishni tasdiqlaysizmi?",
    confirmText = "Ha, Davom Etish",
    cancelText = "Bekor Qilish",
    type = "danger",
    onConfirm = () => {},
    onCancel = () => {}
  }) {
    const existing = document.getElementById('fmh-confirm-dialog-backdrop');
    if (existing) existing.remove();

    const iconClass = type === 'danger' ? 'fa-trash-alt' : (type === 'warning' ? 'fa-exclamation-triangle' : 'fa-procedures');
    const btnClass = type === 'danger' ? 'fmh-confirm-btn-danger' : 'fmh-confirm-btn-primary';

    // Return focus to whatever launched the dialog once it closes.
    const launcher = document.activeElement;

    const backdrop = document.createElement('div');
    backdrop.id = 'fmh-confirm-dialog-backdrop';
    backdrop.className = 'fmh-confirm-backdrop';

    backdrop.innerHTML = `
      <div class="fmh-confirm-card" role="dialog" aria-modal="true" aria-labelledby="fmh-confirm-title" aria-describedby="fmh-confirm-message">
        <div class="fmh-confirm-icon-badge fmh-confirm-icon-${type}">
          <i class="fas ${iconClass}"></i>
        </div>
        <div class="fmh-confirm-title" id="fmh-confirm-title">${title}</div>
        <div class="fmh-confirm-message" id="fmh-confirm-message">${message}</div>
        <div class="fmh-confirm-actions">
          <button type="button" class="fmh-confirm-btn fmh-confirm-btn-cancel" id="fmh-confirm-btn-cancel">
            ${cancelText}
          </button>
          <button type="button" class="fmh-confirm-btn ${btnClass}" id="fmh-confirm-btn-ok" autofocus>
            ${confirmText}
          </button>
        </div>
      </div>
    `;

    document.body.appendChild(backdrop);

    const confirmBtn = backdrop.querySelector('#fmh-confirm-btn-ok');
    const cancelBtn = backdrop.querySelector('#fmh-confirm-btn-cancel');

    setTimeout(() => confirmBtn && confirmBtn.focus(), 50);

    let settled = false;

    function close(isConfirmed) {
      if (settled) return;
      settled = true;
      document.removeEventListener('keydown', handleKeyDown);
      backdrop.style.opacity = '0';
      setTimeout(() => backdrop.remove(), 150);
      if (launcher && typeof launcher.focus === 'function') {
        setTimeout(() => { try { launcher.focus(); } catch (e) {} }, 160);
      }
      if (isConfirmed) onConfirm(); else onCancel();
    }

    function handleKeyDown(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        close(true);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        close(false);
      } else if (e.key === 'Tab') {
        // Keep keyboard focus inside the dialog while it is open.
        const focusables = [cancelBtn, confirmBtn].filter(Boolean);
        if (!focusables.length) return;
        const idx = focusables.indexOf(document.activeElement);
        e.preventDefault();
        const next = e.shiftKey
          ? focusables[(idx <= 0 ? focusables.length : idx) - 1]
          : focusables[(idx + 1) % focusables.length];
        next.focus();
      }
    }

    document.addEventListener('keydown', handleKeyDown);
    confirmBtn.addEventListener('click', () => close(true));
    cancelBtn.addEventListener('click', () => close(false));
    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) close(false);
    });
  };

  /**
   * Promise-flavoured confirmation, so a synchronous
   *   if (!confirm(msg)) return;
   * becomes
   *   if (!await fmhConfirm({message: msg})) return;
   * without restructuring the caller.
   */
  window.fmhConfirm = function (options) {
    return new Promise((resolve) => {
      window.FMH_ConfirmDialog(Object.assign({}, options, {
        onConfirm: () => resolve(true),
        onCancel: () => resolve(false)
      }));
    });
  };

  // -------------------------------------------------------------------------
  // Toast notifications
  //
  // The per-module versions cleared the container on every call, so a second
  // message destroyed an unread first one, auto-dismissed after 1800ms (too
  // short to read a clinical error), carried no aria-live region for screen
  // readers, and offered no way to dismiss one by hand. Errors and warnings now
  // stay noticeably longer than confirmations and can always be closed.
  // -------------------------------------------------------------------------
  const TOAST_DURATION = { success: 3200, info: 3600, warning: 6500, danger: 9000 };

  window.FMH_Toast = function (message, type = 'success', options = {}) {
    let container = document.getElementById('fmh-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'fmh-toast-container';
      container.style.cssText = 'position: fixed; top: 24px; right: 24px; z-index: 999999; display: flex; flex-direction: column; gap: 8px; pointer-events: none; max-width: min(420px, calc(100vw - 48px));';
      // Announce messages to assistive technology. Errors interrupt, the rest wait politely.
      container.setAttribute('aria-live', 'polite');
      container.setAttribute('aria-atomic', 'false');
      container.setAttribute('role', 'status');
      document.body.appendChild(container);
    }
    if (type === 'danger' || type === 'warning') {
      container.setAttribute('aria-live', 'assertive');
    } else {
      container.setAttribute('aria-live', 'polite');
    }

    // Cap the stack instead of wiping it, so a rapid second message cannot
    // erase one the user has not read yet; the oldest goes first.
    while (container.children.length >= 4) {
      container.firstElementChild.remove();
    }

    const bg = type === 'danger'
      ? 'rgba(225, 29, 72, 0.94)'
      : (type === 'warning' ? 'rgba(217, 119, 6, 0.94)' : (type === 'info' ? 'rgba(2, 132, 199, 0.94)' : 'rgba(16, 185, 129, 0.94)'));

    const toast = document.createElement('div');
    toast.className = 'fmh-toast';
    toast.style.cssText = `background: ${bg}; color: #ffffff; padding: 11px 14px 11px 16px; border-radius: 8px; font-family: 'Outfit', sans-serif; font-size: 0.84rem; font-weight: 600; box-shadow: 0 8px 20px rgba(0,0,0,0.25); display: flex; align-items: center; gap: 10px; pointer-events: auto; transition: opacity 0.2s ease; line-height: 1.35;`;

    const body = document.createElement('div');
    body.style.cssText = 'flex: 1 1 auto; min-width: 0;';
    body.innerHTML = message;

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.setAttribute('aria-label', 'Xabarni yopish');
    closeBtn.innerHTML = '&times;';
    closeBtn.style.cssText = 'flex: 0 0 auto; background: rgba(255,255,255,0.18); border: none; color: #fff; width: 22px; height: 22px; min-width: 22px; border-radius: 5px; cursor: pointer; font-size: 15px; line-height: 1; display: flex; align-items: center; justify-content: center; padding: 0;';

    toast.appendChild(body);
    toast.appendChild(closeBtn);
    container.appendChild(toast);

    let timer = null;
    function dismiss() {
      if (timer) clearTimeout(timer);
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 200);
    }
    closeBtn.addEventListener('click', dismiss);

    const duration = options.duration || TOAST_DURATION[type] || TOAST_DURATION.success;
    timer = setTimeout(dismiss, duration);

    // Reading time should not run out while the pointer is resting on the message.
    toast.addEventListener('mouseenter', () => { if (timer) { clearTimeout(timer); timer = null; } });
    toast.addEventListener('mouseleave', () => { if (!timer) timer = setTimeout(dismiss, 1500); });

    return dismiss;
  };
})();

/* ==========================================================================
   SESSION EXPIRY HANDLING
   --------------------------------------------------------------------------
   The API now requires a signed-in session. Rather than adding error handling
   to the ~100 fetch() calls spread across the portal scripts, window.fetch is
   wrapped once here: any 401 from our own /api/* means the session is gone, so
   the browser is sent to the login screen with a note to come back to this
   page. The response is still returned to the caller, so existing code paths
   behave exactly as before while the redirect is in flight.

   The session itself rides in an HttpOnly cookie, which same-origin fetch
   sends automatically — no request in the app needed changing.
   ========================================================================== */
(function () {
  'use strict';

  if (window.__fmhFetchWrapped) return;
  window.__fmhFetchWrapped = true;

  const nativeFetch = window.fetch.bind(window);
  let redirecting = false;

  function goToLogin() {
    if (redirecting) return;
    redirecting = true;
    const here = location.pathname + location.search;
    const target = '/login.html?next=' + encodeURIComponent(here);
    if (window.FMH_Toast) {
      window.FMH_Toast("Sessiya muddati tugadi — qaytadan kirish talab qilinadi", 'warning');
    }
    setTimeout(() => location.replace(target), 900);
  }

  window.fetch = async function (input, init) {
    const res = await nativeFetch(input, init);
    try {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      const sameOrigin = url.startsWith('/') || url.startsWith(location.origin);
      const isOwnApi = sameOrigin && url.indexOf('/api/') !== -1;
      // The login endpoint answers 401 for a wrong password; that is not an
      // expired session and must not trigger a redirect loop.
      const isLogin = url.indexOf('/api/auth/login') !== -1;
      if (res.status === 401 && isOwnApi && !isLogin) goToLogin();
    } catch (e) { /* never let the wrapper break a request */ }
    return res;
  };
})();
