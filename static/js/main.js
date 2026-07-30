// Shared, site-wide JS: theme toggle + toast notifications.
// Page-specific logic lives in upload.html / dashboard.js, both of which
// can call window.showToast(...) since this file loads first on every page.

document.addEventListener('DOMContentLoaded', () => {
  initThemeToggle();
});

function initThemeToggle() {
  const toggle = document.getElementById('themeToggle');
  const label = document.getElementById('themeToggleLabel');
  if (!toggle) return;

  function applyLabel() {
    const isLight = document.documentElement.getAttribute('data-theme') === 'light';
    if (label) label.textContent = isLight ? 'Light mode' : 'Dark mode';
  }
  applyLabel();

  toggle.addEventListener('click', () => {
    const isLight = document.documentElement.getAttribute('data-theme') === 'light';
    if (isLight) {
      document.documentElement.removeAttribute('data-theme');
      localStorage.setItem('datagrid-theme', 'dark');
    } else {
      document.documentElement.setAttribute('data-theme', 'light');
      localStorage.setItem('datagrid-theme', 'light');
    }
    applyLabel();
  });
}

// ---------- Toasts ----------
// window.showToast('Upload complete', 'success' | 'error' | 'info', durationMs)
window.showToast = function (message, type = 'info', duration = 4000) {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('fade-out');
    setTimeout(() => toast.remove(), 200);
  }, duration);
};
