// Theme management
function initTheme() {
  function getCookie(name) {
    const match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return match ? decodeURIComponent(match[1]) : null;
  }

  const themeCookie = getCookie('rl_theme');
  if (themeCookie === 'light' || themeCookie === 'dark') {
    document.documentElement.dataset.theme = themeCookie;
  }

  const toggleBtn = document.getElementById('theme-toggle');
  if (!toggleBtn) return;

  const labelEl = toggleBtn.querySelector('.theme-toggle-label');

  function updateToggleButton() {
    const effective = document.documentElement.dataset.theme ||
      (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const target = effective === 'dark' ? 'light' : 'dark';

    toggleBtn.setAttribute('aria-label', 'Aktifkan tema ' + (target === 'dark' ? 'gelap' : 'terang'));
    if (labelEl) {
      labelEl.textContent = target === 'dark' ? 'Gelap' : 'Terang';
    }
  }

  updateToggleButton();

  toggleBtn.addEventListener('click', function () {
    const current = document.documentElement.dataset.theme ||
      (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = current === 'dark' ? 'light' : 'dark';

    document.cookie = 'rl_theme=' + next + '; path=/; max-age=31536000; samesite=lax';
    document.documentElement.dataset.theme = next;
    updateToggleButton();
  });
}

// Table column sorting
function initSortableTables() {
  const tables = document.querySelectorAll('table[data-sortable]');
  tables.forEach(function (table) {
    const tbody = table.querySelector('tbody');
    if (!tbody) return;

    let originalRows = Array.from(tbody.querySelectorAll('tr'));

    table.addEventListener('click', function (e) {
      const button = e.target.closest('.th-sort');
      if (!button) return;

      const th = button.closest('th');
      if (!th || !th.dataset.sort) return;

      const headerRow = th.parentElement;
      const thList = Array.from(headerRow.children);
      const colIndex = thList.indexOf(th);
      if (colIndex === -1) return;

      const currentSort = th.getAttribute('aria-sort') || 'none';
      let nextSort = 'ascending';
      if (currentSort === 'ascending') {
        nextSort = 'descending';
      } else if (currentSort === 'descending') {
        nextSort = 'none';
      }

      thList.forEach(function (otherTh) {
        otherTh.setAttribute('aria-sort', 'none');
      });
      th.setAttribute('aria-sort', nextSort);

      if (nextSort === 'none') {
        originalRows.forEach(function (row) {
          tbody.appendChild(row);
        });
        return;
      }

      const rows = Array.from(tbody.querySelectorAll('tr'));
      const isNumber = th.dataset.sort === 'number';

      rows.sort(function (rowA, rowB) {
        const cellA = rowA.children[colIndex];
        const cellB = rowB.children[colIndex];
        const valA = cellA ? cellA.textContent.trim() : '';
        const valB = cellB ? cellB.textContent.trim() : '';

        let comparison = 0;
        if (isNumber) {
          const numA = parseFloat(valA.replace(/[\s%]/g, '')) || 0;
          const numB = parseFloat(valB.replace(/[\s%]/g, '')) || 0;
          comparison = numA - numB;
        } else {
          comparison = valA.localeCompare(valB, undefined, { sensitivity: 'base' });
        }

        return nextSort === 'descending' ? -comparison : comparison;
      });

      rows.forEach(function (row) {
        tbody.appendChild(row);
      });
    });
  });
}

// File dropzone behavior
function initDropzones() {
  const dropzones = document.querySelectorAll('.dropzone');
  dropzones.forEach(function (zone) {
    const input = zone.querySelector('.dropzone-input');
    const nameEl = zone.querySelector('.dropzone-name');

    function renderFilename() {
      if (!nameEl) return;
      if (input && input.files && input.files.length > 0) {
        nameEl.textContent = input.files[0].name;
      } else {
        nameEl.textContent = 'Belum ada berkas dipilih';
      }
    }

    zone.addEventListener('dragenter', function (e) {
      e.preventDefault();
      zone.classList.add('is-dragover');
    });

    zone.addEventListener('dragover', function (e) {
      e.preventDefault();
      zone.classList.add('is-dragover');
    });

    zone.addEventListener('dragleave', function (e) {
      if (!zone.contains(e.relatedTarget)) {
        zone.classList.remove('is-dragover');
      }
    });

    zone.addEventListener('drop', function (e) {
      e.preventDefault();
      zone.classList.remove('is-dragover');
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        if (input) {
          input.files = e.dataTransfer.files;
          renderFilename();
          input.dispatchEvent(new Event('change', { bubbles: true }));
        }
      }
    });

    if (input) {
      input.addEventListener('change', renderFilename);
    }
  });
}

// Form loading states
function initLoadingStates() {
  const forms = document.querySelectorAll('form[data-loading]');
  forms.forEach(function (form) {
    form.addEventListener('submit', function (e) {
      const fileInputs = form.querySelectorAll('input[type="file"]');
      for (let i = 0; i < fileInputs.length; i++) {
        const fileInput = fileInputs[i];
        if (fileInput.required && (!fileInput.files || fileInput.files.length === 0)) {
          return true;
        }
      }

      const submitBtn = form.querySelector('button[type="submit"]');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.setAttribute('aria-busy', 'true');
        submitBtn.classList.add('is-loading');
        if (form.dataset.loading) {
          submitBtn.textContent = form.dataset.loading;
        }
      }
    });
  });
}

// Bootstrap after DOM ready
document.addEventListener('DOMContentLoaded', function () {
  initTheme();
  initSortableTables();
  initDropzones();
  initLoadingStates();
});
