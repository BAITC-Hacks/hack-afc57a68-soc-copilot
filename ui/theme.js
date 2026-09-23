/* Trusted, local-only theme controller. No document content or remote scripts. */
(() => {
  "use strict";
  const storageKey = "orgtrace.theme";
  const allowed = new Set(["light", "dark", "system"]);
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const root = document.documentElement;
  const previous = window.orgTraceThemeController;
  let preference = previous?.preference || "system";
  previous?.destroy();
  try {
    const saved = window.localStorage.getItem(storageKey);
    if (allowed.has(saved)) preference = saved;
  } catch (_) {
    // Storage may be blocked: retain the choice in memory for this page.
  }

  const apply = () => {
    root.dataset.orgTheme = preference === "system"
      ? (media.matches ? "dark" : "light") : preference;
    root.dataset.orgThemePreference = preference;
    document.querySelectorAll("[data-org-theme-choice]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.orgThemeChoice === preference));
    });
  };
  // The native menu is a lazily mounted portal. Insert a separate group before
  // its menu list, leaving Streamlit's actions and keyboard handling intact.
  const mountMenuControl = () => {
    const menu = document.querySelector('[data-testid="stMainMenuList"], [role="menu"][aria-label="Main menu"]');
    if (!menu || menu.parentElement.querySelector('[data-org-theme-menu]')) return;
    const template = document.querySelector('.st-key-theme_bootstrap .theme-control');
    if (!template) return;
    const control = template.cloneNode(true);
    control.dataset.orgThemeMenu = '';
    menu.before(control);
    apply();
  };
  const click = (event) => {
    const button = event.target.closest?.("[data-org-theme-choice]");
    if (!button || !allowed.has(button.dataset.orgThemeChoice)) return;
    preference = button.dataset.orgThemeChoice;
    try {
      window.localStorage.setItem(storageKey, preference);
    } catch (_) { /* The switch still works without persistent storage. */ }
    apply();
  };
  const keydown = (event) => {
    const button = event.target.closest?.('[data-org-theme-choice]');
    if (!button || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const buttons = [...document.querySelectorAll('[data-org-theme-menu] [data-org-theme-choice]')];
    const index = buttons.indexOf(button);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
    event.preventDefault();
    event.stopPropagation();
    buttons[next].focus();
  };
  const sync = (event) => {
    if (event.key !== storageKey && event.key !== null) return;
    preference = allowed.has(event.newValue) ? event.newValue : "system";
    apply();
  };
  document.addEventListener("click", click);
  document.addEventListener("keydown", keydown, true);
  media.addEventListener("change", apply);
  window.addEventListener("storage", sync);
  const observer = new MutationObserver(mountMenuControl);
  observer.observe(document.body, { childList: true, subtree: true });
  window.orgTraceThemeController = {
    get preference() { return preference; },
    destroy() {
      document.removeEventListener("click", click);
      document.removeEventListener("keydown", keydown, true);
      media.removeEventListener("change", apply);
      window.removeEventListener("storage", sync);
      observer.disconnect();
    },
  };
  apply();
  mountMenuControl();
})();
