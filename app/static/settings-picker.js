(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var dialog = document.getElementById('picker-dialog');
    var form = document.querySelector('form.upload-form');
    var carriersContainer = document.getElementById('picker-carriers');
    if (!dialog || !form || !carriersContainer) return;

    var titleEl = document.getElementById('picker-title');
    var searchInput = document.getElementById('picker-search');
    var statusEl = document.getElementById('picker-status');
    var resultsEl = document.getElementById('picker-results');
    var moreBtn = document.getElementById('picker-more');
    var chosenEl = document.getElementById('picker-chosen');
    var fileSection = document.getElementById('picker-file');
    var closeBtn = dialog.querySelector('[data-close]');

    var currentKind = null;
    var lastActiveButton = null;
    var abortCtrl = null;
    var searchTimeout = null;
    var currentOffset = 0;
    var currentTotal = 0;
    var currentQuery = '';

    // Dataset ID extracted from form action (/datasets/{id}/analyze)
    var datasetId = '';
    var match = form.action.match(/\/datasets\/(\d+)\//);
    if (match) {
      datasetId = match[1];
    }

    // State per kind: map of position string -> { pos: string, label: string }
    var selections = {
      persons: {},
      items: {},
      anchors: {}
    };

    function carrierNameForKind(kind) {
      if (kind === 'persons') return 'pd_pick';
      if (kind === 'items') return 'id_pick';
      return null;
    }

    function titleForKind(kind) {
      if (kind === 'persons') return 'Pilih Peserta';
      if (kind === 'items') return 'Pilih Butir';
      if (kind === 'anchors') return 'Pilih Jangkar Butir';
      return 'Pilih';
    }

    function syncCarriers(kind) {
      var carrierName = carrierNameForKind(kind);
      if (!carrierName) return;

      var existing = carriersContainer.querySelectorAll('input[name="' + carrierName + '"]');
      existing.forEach(function (el) { el.remove(); });

      var kindSel = selections[kind];
      var positions = Object.keys(kindSel).sort(function (a, b) {
        return parseInt(a, 10) - parseInt(b, 10);
      });

      positions.forEach(function (pos) {
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = carrierName;
        input.value = pos;
        carriersContainer.appendChild(input);
      });
    }

    function updateRowSummary(kind) {
      var summaryEl = document.querySelector('.pick-summary[data-summary="' + kind + '"]');
      if (!summaryEl) return;
      var count = Object.keys(selections[kind]).length;
      summaryEl.textContent = count > 0 ? (count + ' dipilih') : 'Belum ada';
    }

    function renderChips() {
      if (!chosenEl) return;
      chosenEl.innerHTML = '';
      if (!currentKind) return;

      var kindSel = selections[currentKind];
      var positions = Object.keys(kindSel).sort(function (a, b) {
        return parseInt(a, 10) - parseInt(b, 10);
      });

      var chipRow = document.createElement('div');
      chipRow.className = 'chip-row';

      positions.forEach(function (pos) {
        var item = kindSel[pos];
        var chip = document.createElement('span');
        chip.className = 'chip';
        chip.setAttribute('data-pos', pos);

        var labelSpan = document.createElement('span');
        labelSpan.textContent = item.label || pos;
        chip.appendChild(labelSpan);

        var removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'chip-remove';
        removeBtn.setAttribute('aria-label', 'Hapus ' + (item.label || pos));
        removeBtn.textContent = '×';
        removeBtn.addEventListener('click', function (e) {
          e.stopPropagation();
          delete kindSel[pos];
          syncCarriers(currentKind);
          updateRowSummary(currentKind);
          renderChips();
          syncCheckboxesInResults();
        });

        chip.appendChild(removeBtn);
        chipRow.appendChild(chip);
      });

      chosenEl.appendChild(chipRow);
    }

    function syncCheckboxesInResults() {
      if (!resultsEl || !currentKind) return;
      var kindSel = selections[currentKind];
      var checkboxes = resultsEl.querySelectorAll('input[type="checkbox"][data-pos]');
      checkboxes.forEach(function (cb) {
        var pos = cb.getAttribute('data-pos');
        cb.checked = !!kindSel[pos];
      });
    }

    function initFromCarriers() {
      ['persons', 'items'].forEach(function (kind) {
        var carrierName = carrierNameForKind(kind);
        if (!carrierName) return;
        var inputs = carriersContainer.querySelectorAll('input[name="' + carrierName + '"]');
        inputs.forEach(function (inp) {
          var pos = inp.value;
          if (pos) {
            selections[kind][pos] = { pos: pos, label: pos };
          }
        });
        updateRowSummary(kind);
      });
    }

    function updateFileSectionVisibility() {
      if (!fileSection) return;
      var fields = fileSection.querySelectorAll('.field[data-kind]');
      fields.forEach(function (f) {
        if (f.getAttribute('data-kind') === currentKind) {
          f.removeAttribute('hidden');
        } else {
          f.setAttribute('hidden', '');
        }
      });
    }

    function renderResults(items, append) {
      if (!resultsEl) return;
      if (!append) {
        resultsEl.innerHTML = '';
      }

      items.forEach(function (item) {
        var posStr = String(item.pos);
        var labelStr = String(item.label || item.pos);

        var row = document.createElement('label');
        row.className = 'field--toggle pick-row';
        row.setAttribute('data-pos', posStr);

        var checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.setAttribute('data-pos', posStr);
        checkbox.setAttribute('aria-label', (currentKind === 'persons' ? 'Hapus peserta ' : 'Hapus butir ') + labelStr);
        if (selections[currentKind] && selections[currentKind][posStr]) {
          checkbox.checked = true;
        }

        checkbox.addEventListener('change', function () {
          if (checkbox.checked) {
            selections[currentKind][posStr] = { pos: posStr, label: labelStr };
          } else {
            delete selections[currentKind][posStr];
          }
          syncCarriers(currentKind);
          updateRowSummary(currentKind);
          renderChips();
        });

        row.appendChild(checkbox);

        var posSpan = document.createElement('span');
        posSpan.className = 'pick-pos';
        posSpan.textContent = posStr;
        row.appendChild(posSpan);

        if (labelStr && labelStr !== posStr) {
          var monoSpan = document.createElement('span');
          monoSpan.className = 'mono';
          monoSpan.textContent = labelStr;
          row.appendChild(monoSpan);
        }

        resultsEl.appendChild(row);
      });

      // Update picker status text
      if (statusEl) {
        if (currentTotal === 0 && items.length === 0) {
          statusEl.textContent = '';
        } else {
          var visibleCount = resultsEl.children.length;
          statusEl.textContent = visibleCount + ' dari ' + currentTotal;
        }
      }
    }

    function fetchResults(offset, append) {
      if (!currentKind || !datasetId) return;

      if (abortCtrl) {
        abortCtrl.abort();
      }
      abortCtrl = new AbortController();

      var url = '/datasets/' + encodeURIComponent(datasetId) +
                '/picker?kind=' + encodeURIComponent(currentKind) +
                '&q=' + encodeURIComponent(currentQuery) +
                '&offset=' + encodeURIComponent(offset);

      fetch(url, { signal: abortCtrl.signal })
        .then(function (res) {
          if (!res.ok) {
            throw new Error('HTTP ' + res.status);
          }
          return res.json();
        })
        .then(function (data) {
          currentOffset = data.offset;
          currentTotal = data.total;

          if (!append) {
            resultsEl.innerHTML = '';
          }

          if (data.total === 0 || data.items.length === 0 && !append) {
            if (moreBtn) moreBtn.hidden = true;
            if (statusEl) statusEl.textContent = '';
            var emptyP = document.createElement('p');
            emptyP.className = 'field-hint';
            if (currentQuery) {
              emptyP.textContent = "Tidak ada yang cocok dengan '" + currentQuery + "'. Coba kata lain atau kosongkan kotak cari.";
            } else {
              emptyP.textContent = 'Belum ada data untuk daftar ini.';
            }
            resultsEl.appendChild(emptyP);
            return;
          }

          renderResults(data.items, append);

          if (moreBtn) {
            moreBtn.hidden = !data.has_more;
          }
        })
        .catch(function (err) {
          if (err.name === 'AbortError') return;
          if (!append) {
            resultsEl.innerHTML = '';
          }
          if (moreBtn) moreBtn.hidden = true;
          if (statusEl) statusEl.textContent = '';

          var errP = document.createElement('p');
          errP.className = 'field-hint';
          errP.textContent = 'Gagal memuat data dari server. Periksa koneksi internet atau muat ulang halaman.';
          resultsEl.appendChild(errP);
        });
    }

    function openDialog(kind, triggerBtn) {
      currentKind = kind;
      lastActiveButton = triggerBtn;

      if (titleEl) {
        titleEl.textContent = titleForKind(kind);
      }

      updateFileSectionVisibility();
      renderChips();

      currentQuery = '';
      if (searchInput) {
        searchInput.value = '';
      }
      if (statusEl) {
        statusEl.textContent = '';
      }
      if (resultsEl) {
        resultsEl.innerHTML = '';
      }
      if (moreBtn) {
        moreBtn.hidden = true;
      }

      if (typeof dialog.showModal === 'function') {
        dialog.showModal();
      } else {
        dialog.setAttribute('open', '');
      }

      if (searchInput) {
        searchInput.focus();
      }

      fetchResults(0, false);
    }

    function closeDialog() {
      if (abortCtrl) {
        abortCtrl.abort();
      }
      if (dialog.open) {
        if (typeof dialog.close === 'function') {
          dialog.close();
        } else {
          dialog.removeAttribute('open');
        }
      }
      if (lastActiveButton) {
        lastActiveButton.focus();
        lastActiveButton = null;
      }
    }

    // Attach open triggers
    document.querySelectorAll('.pick-open').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var kind = btn.getAttribute('data-kind');
        if (kind) {
          openDialog(kind, btn);
        }
      });
    });

    // Close button
    if (closeBtn) {
      closeBtn.addEventListener('click', function (e) {
        e.preventDefault();
        closeDialog();
      });
    }

    // Close on backdrop click
    dialog.addEventListener('click', function (e) {
      if (e.target === dialog) {
        closeDialog();
      }
    });

    // Escape listener: close event or keydown
    dialog.addEventListener('cancel', function (e) {
      e.preventDefault();
      closeDialog();
    });

    // Search input with 150ms debounce
    if (searchInput) {
      searchInput.addEventListener('input', function () {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(function () {
          currentQuery = searchInput.value.trim();
          fetchResults(0, false);
        }, 150);
      });
    }

    // More button
    if (moreBtn) {
      moreBtn.addEventListener('click', function (e) {
        e.preventDefault();
        fetchResults(currentOffset + 5, true);
      });
    }

    // Initialize from pre-rendered carriers on DOM ready
    initFromCarriers();
  });
})();
