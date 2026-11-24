(function () {
  function getTheme() {
    return document.documentElement.getAttribute('data-theme') || localStorage.getItem('theme') || 'dark';
  }

  function applyTheme(val) {
    localStorage.setItem('theme', val);
    document.documentElement.setAttribute('data-theme', val);
    document.querySelectorAll('[data-theme-icon]').forEach(function (el) {
      el.textContent = val === 'dark' ? '☀️' : '🌙';
    });
    document.querySelectorAll('[data-theme-text]').forEach(function (el) {
      el.textContent = val === 'dark' ? 'Light Mode' : 'Dark Mode';
    });
  }

  window.toggleAppTheme = function () {
    applyTheme(getTheme() === 'dark' ? 'light' : 'dark');
  };

  window.formatMoney = function (n, currency) {
    var cur = currency || document.body.dataset.currency || 'KES';
    var num = Number(n || 0);
    var sign = num < 0 ? '-' : '';
    return sign + cur + ' ' + Math.abs(num).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  };

  window.openModal = function (id) {
    var modal = document.getElementById(id);
    if (modal) {
      modal.classList.remove('hidden');
      var firstInput = modal.querySelector('input:not([type="hidden"]):not([disabled]), select:not([disabled])');
      if (firstInput) setTimeout(function () { firstInput.focus(); }, 30);
    }
  };

  window.closeModal = function (id) {
    var modal = document.getElementById(id);
    if (modal) modal.classList.add('hidden');
  };

  document.addEventListener('DOMContentLoaded', function () {
    applyTheme(getTheme());

    // Mobile drawer toggle
    var sidebar = document.getElementById('app-sidebar');
    var backdrop = document.getElementById('sidebar-backdrop');
    var openBtn = document.getElementById('mobile-menu-btn');
    var closeBtn = document.getElementById('mobile-close-btn');

    function closeDrawer() {
      if (sidebar) sidebar.classList.remove('mobile-open');
      if (backdrop) backdrop.classList.add('hidden');
    }

    if (openBtn && sidebar) {
      openBtn.addEventListener('click', function () {
        sidebar.classList.add('mobile-open');
        if (backdrop) backdrop.classList.remove('hidden');
      });
    }
    if (closeBtn) closeBtn.addEventListener('click', closeDrawer);
    if (backdrop) backdrop.addEventListener('click', closeDrawer);

    // Close modals when clicking overlay or close buttons
    document.querySelectorAll('.modal-overlay').forEach(function (overlay) {
      overlay.addEventListener('click', function (e) {
        if (e.target === overlay) {
          overlay.classList.add('hidden');
        }
      });
    });

    document.querySelectorAll('[data-modal-close]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var targetId = btn.getAttribute('data-modal-close');
        if (targetId) {
          window.closeModal(targetId);
        } else {
          var overlay = btn.closest('.modal-overlay');
          if (overlay) overlay.classList.add('hidden');
        }
      });
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay:not(.hidden)').forEach(function (m) {
          m.classList.add('hidden');
        });
      }
    });
  });
})();
