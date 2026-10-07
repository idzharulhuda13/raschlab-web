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
      if (kind === 'anchors') {
        var existingPos = carriersContainer.querySelectorAll('input[name="anchor_pos"]');
        existingPos.forEach(function (el) { el.remove(); });
        var existingVal = carriersContainer.querySelectorAll('input[name="anchor_value"]');
        existingVal.forEach(function (el) { el.remove(); });

        var kindSel = selections.anchors;
        var positions = Object.keys(kindSel).sort(function (a, b) {
          return parseInt(a, 10) - parseInt(b, 10);
        });

        positions.forEach(function (pos) {
          var item = kindSel[pos];
          var posInput = document.createElement('input');
          posInput.type = 'hidden';
          posInput.name = 'anchor_pos';
          posInput.value = pos;
          carriersContainer.appendChild(posInput);

          var valInput = document.createElement('input');
          valInput.type = 'hidden';
          valInput.name = 'anchor_value';
          valInput.value = item.value != null ? item.value : '';
          carriersContainer.appendChild(valInput);
        });
        return;
      }

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
      if (kind === 'anchors') {
        summaryEl.textContent = count > 0 ? (count + ' jangkar') : 'Belum ada';
      } else {
        summaryEl.textContent = count > 0 ? (count + ' dipilih') : 'Belum ada';
      }
    }

    function renderChips() {
      if (!chosenEl) return;
      chosenEl.innerHTML = '';
      if (!currentKind) return;

      var chipRow = document.createElement('div');
      chipRow.className = 'chip-row';

      if (currentKind === 'anchors') {
        var kindSel = selections.anchors;
        var positions = Object.keys(kindSel).sort(function (a, b) {
          return parseInt(a, 10) - parseInt(b, 10);
        });

        positions.forEach(function (pos) {
          var item = kindSel[pos];
          var chip = document.createElement('span');
          chip.className = 'chip';
          chip.setAttribute('data-pos', pos);

          var labelSpan = document.createElement('span');
          labelSpan.textContent = item.label || pos;
          chip.appendChild(labelSpan);

          var numInput = document.createElement('input');
          numInput.type = 'number';
          numInput.step = 'any';
          numInput.className = 'field-input';
          numInput.setAttribute('data-pos', pos);
          numInput.setAttribute('aria-label', 'Nilai jangkar ' + (item.label || pos));
          numInput.setAttribute('value', item.value != null ? item.value : '');
          numInput.value = item.value != null ? item.value : '';

          function handleValueChange() {
            item.value = numInput.value;
            numInput.setAttribute('value', numInput.value);
            syncCarriers('anchors');
          }
          numInput.addEventListener('input', handleValueChange);
          numInput.addEventListener('change', handleValueChange);
          chip.appendChild(numInput);

          var removeBtn = document.createElement('button');
          removeBtn.type = 'button';
          removeBtn.className = 'chip-remove';
          removeBtn.setAttribute('aria-label', 'Hapus jangkar ' + (item.label || pos));
          removeBtn.textContent = '×';
          removeBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            delete kindSel[pos];
            syncCarriers('anchors');
            updateRowSummary('anchors');
            renderChips();
            syncCheckboxesInResults();
          });

          chip.appendChild(removeBtn);
          chipRow.appendChild(chip);
        });
      } else if (currentKind === 'items') {
        var itemPositions = Object.keys(selections.items).sort(function (a, b) {
          return parseInt(a, 10) - parseInt(b, 10);
        });

        itemPositions.forEach(function (pos) {
          var item = selections.items[pos];
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
            delete selections.items[pos];
            syncCarriers('items');
            updateRowSummary('items');
            renderChips();
            syncCheckboxesInResults();
          });

          chip.appendChild(removeBtn);
          chipRow.appendChild(chip);
        });

        var anchorPositions = Object.keys(selections.anchors).sort(function (a, b) {
          return parseInt(a, 10) - parseInt(b, 10);
        });

        anchorPositions.forEach(function (pos) {
          var item = selections.anchors[pos];
          var chip = document.createElement('span');
          chip.className = 'chip';
          chip.setAttribute('data-pos', pos);
          chip.setAttribute('data-kind', 'anchor');

          var labelSpan = document.createElement('span');
          labelSpan.textContent = item.label || pos;
          chip.appendChild(labelSpan);

          var numInput = document.createElement('input');
          numInput.type = 'number';
          numInput.step = 'any';
          numInput.className = 'field-input';
          numInput.setAttribute('data-pos', pos);
          numInput.setAttribute('aria-label', 'Nilai jangkar ' + (item.label || pos));
          numInput.setAttribute('value', item.value != null ? item.value : '');
          numInput.value = item.value != null ? item.value : '';

          function handleValueChange() {
            item.value = numInput.value;
            numInput.setAttribute('value', numInput.value);
            syncCarriers('anchors');
          }
          numInput.addEventListener('input', handleValueChange);
          numInput.addEventListener('change', handleValueChange);
          chip.appendChild(numInput);

          var removeBtn = document.createElement('button');
          removeBtn.type = 'button';
          removeBtn.className = 'chip-remove';
          removeBtn.setAttribute('aria-label', 'Hapus jangkar ' + (item.label || pos));
          removeBtn.textContent = '×';
          removeBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            delete selections.anchors[pos];
            syncCarriers('anchors');
            updateRowSummary('anchors');
            renderChips();
            syncCheckboxesInResults();
          });

          chip.appendChild(removeBtn);
          chipRow.appendChild(chip);
        });
      } else {
        var kindSel = selections[currentKind];
        var positions = Object.keys(kindSel).sort(function (a, b) {
          return parseInt(a, 10) - parseInt(b, 10);
        });

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
      }

      chosenEl.appendChild(chipRow);
    }

    function syncCheckboxesInResults() {
      if (!resultsEl || !currentKind) return;
      var checkboxes = resultsEl.querySelectorAll('input[type="checkbox"][data-pos]');
      checkboxes.forEach(function (cb) {
        var pos = cb.getAttribute('data-pos');
        var action = cb.getAttribute('data-action');
        if (action === 'anchor') {
          cb.checked = !!(selections.anchors && selections.anchors[pos]);
        } else if (action === 'delete') {
          cb.checked = !!(selections.items && selections.items[pos]);
        } else {
          cb.checked = !!(selections[currentKind] && selections[currentKind][pos]);
        }
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

      var anchorPosInputs = carriersContainer.querySelectorAll('input[name="anchor_pos"]');
      var anchorValInputs = carriersContainer.querySelectorAll('input[name="anchor_value"]');
      for (var i = 0; i < anchorPosInputs.length; i++) {
        var aPos = anchorPosInputs[i].value;
        var aVal = anchorValInputs[i] ? anchorValInputs[i].value : '';
        if (aPos) {
          selections.anchors[aPos] = {
            pos: aPos,
            label: aPos,
            value: aVal
          };
        }
      }
      updateRowSummary('anchors');
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

        if (selections.anchors[posStr] && item.label) {
          selections.anchors[posStr].label = labelStr;
        }
        if (selections.items[posStr] && item.label) {
          selections.items[posStr].label = labelStr;
        }

        if (currentKind === 'anchors') {
          var row = document.createElement('label');
          row.className = 'field--toggle pick-row pick-row--anchor';
          row.setAttribute('data-pos', posStr);

          var checkbox = document.createElement('input');
          checkbox.type = 'checkbox';
          checkbox.setAttribute('data-pos', posStr);
          checkbox.setAttribute('data-action', 'anchor');
          checkbox.setAttribute('aria-label', 'Jadikan jangkar ' + labelStr);
          if (selections.anchors && selections.anchors[posStr]) {
            checkbox.checked = true;
          }

          checkbox.addEventListener('change', function () {
            if (checkbox.checked) {
              var prevVal = selections.anchors[posStr] ? selections.anchors[posStr].value : '';
              selections.anchors[posStr] = { pos: posStr, label: labelStr, value: prevVal || '' };
            } else {
              delete selections.anchors[posStr];
            }
            syncCarriers('anchors');
            updateRowSummary('anchors');
            renderChips();
          });

          row.appendChild(checkbox);

          var posSpan = document.createElement('span');
          posSpan.className = 'pick-pos';
          posSpan.textContent = posStr;
          row.appendChild(posSpan);

          var monoSpan = document.createElement('span');
          monoSpan.className = 'mono';
          monoSpan.textContent = (labelStr && labelStr !== posStr) ? labelStr : '';
          row.appendChild(monoSpan);

          var textSpan = document.createElement('span');
          textSpan.className = 'sec';
          textSpan.textContent = 'Jadikan jangkar';
          row.appendChild(textSpan);

          resultsEl.appendChild(row);
        } else if (currentKind === 'items') {
          var row = document.createElement('div');
          row.className = 'field--toggle pick-row pick-row--anchor';
          row.setAttribute('data-pos', posStr);

          var delLabel = document.createElement('label');
          delLabel.className = 'field--toggle';
          var delCheckbox = document.createElement('input');
          delCheckbox.type = 'checkbox';
          delCheckbox.setAttribute('data-pos', posStr);
          delCheckbox.setAttribute('data-action', 'delete');
          delCheckbox.setAttribute('aria-label', 'Hapus butir ' + labelStr);
          if (selections.items && selections.items[posStr]) {
            delCheckbox.checked = true;
          }
          delCheckbox.addEventListener('change', function () {
            if (delCheckbox.checked) {
              selections.items[posStr] = { pos: posStr, label: labelStr };
            } else {
              delete selections.items[posStr];
            }
            syncCarriers('items');
            updateRowSummary('items');
            renderChips();
          });
          delLabel.appendChild(delCheckbox);
          row.appendChild(delLabel);

          var posSpan = document.createElement('span');
          posSpan.className = 'pick-pos';
          posSpan.textContent = posStr;
          row.appendChild(posSpan);

          var monoSpan = document.createElement('span');
          monoSpan.className = 'mono';
          monoSpan.textContent = (labelStr && labelStr !== posStr) ? labelStr : '';
          row.appendChild(monoSpan);

          var anchorLabel = document.createElement('label');
          anchorLabel.className = 'field--toggle';
          var anchorCheckbox = document.createElement('input');
          anchorCheckbox.type = 'checkbox';
          anchorCheckbox.setAttribute('data-pos', posStr);
          anchorCheckbox.setAttribute('data-action', 'anchor');
          anchorCheckbox.setAttribute('aria-label', 'Jadikan jangkar ' + labelStr);
          if (selections.anchors && selections.anchors[posStr]) {
            anchorCheckbox.checked = true;
          }
          anchorCheckbox.addEventListener('change', function () {
            if (anchorCheckbox.checked) {
              var prevVal = selections.anchors[posStr] ? selections.anchors[posStr].value : '';
              selections.anchors[posStr] = { pos: posStr, label: labelStr, value: prevVal || '' };
            } else {
              delete selections.anchors[posStr];
            }
            syncCarriers('anchors');
            updateRowSummary('anchors');
            renderChips();
          });
          anchorLabel.appendChild(anchorCheckbox);
          var anchorText = document.createElement('span');
          anchorText.className = 'sec';
          anchorText.textContent = 'Jadikan jangkar';
          anchorLabel.appendChild(anchorText);
          row.appendChild(anchorLabel);

          resultsEl.appendChild(row);
        } else {
          var row = document.createElement('label');
          row.className = 'field--toggle pick-row';
          row.setAttribute('data-pos', posStr);

          var checkbox = document.createElement('input');
          checkbox.type = 'checkbox';
          checkbox.setAttribute('data-pos', posStr);
          checkbox.setAttribute('aria-label', 'Hapus peserta ' + labelStr);
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
        }
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

      var queryKind = (currentKind === 'anchors') ? 'items' : currentKind;
      var url = '/datasets/' + encodeURIComponent(datasetId) +
                '/picker?kind=' + encodeURIComponent(queryKind) +
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
