document.addEventListener('DOMContentLoaded', function () {
  var picker = document.getElementById('pd-picker');
  if (!picker) return;

  var dataEl = document.getElementById('pd-picker-data');
  var labels = [];
  if (dataEl && dataEl.textContent) {
    try {
      labels = JSON.parse(dataEl.textContent);
    } catch (e) {
      labels = [];
    }
  }

  var picksAttr = picker.getAttribute('data-picks');
  var picks = [];
  if (picksAttr) {
    try {
      picks = JSON.parse(picksAttr);
    } catch (e) {
      picks = [];
    }
  }
  var pickSet = {};
  if (Array.isArray(picks)) {
    for (var p = 0; p < picks.length; p++) {
      pickSet[String(picks[p])] = true;
    }
  }

  var nAttr = picker.getAttribute('data-n-persons');
  var n = nAttr ? parseInt(nAttr, 10) : labels.length;

  var filterLabel = document.createElement('label');
  filterLabel.className = 'field-label';
  filterLabel.htmlFor = 'pd-filter';
  filterLabel.textContent = 'Cari peserta';

  var filterInput = document.createElement('input');
  filterInput.type = 'search';
  filterInput.id = 'pd-filter';
  filterInput.className = 'field-input';
  filterInput.autocomplete = 'off';

  picker.parentNode.insertBefore(filterLabel, picker);
  picker.parentNode.insertBefore(filterInput, picker);

  var fragment = document.createDocumentFragment();
  var rows = [];

  for (var i = 1; i <= n; i++) {
    var row = document.createElement('label');
    row.className = 'field--toggle pick-row';

    var checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.name = 'pd_pick';
    checkbox.value = String(i);
    if (pickSet[String(i)]) {
      checkbox.checked = true;
    }
    row.appendChild(checkbox);

    var srOnly = document.createElement('span');
    srOnly.className = 'sr-only';
    srOnly.textContent = 'Hapus peserta ';
    row.appendChild(srOnly);

    var posSpan = document.createElement('span');
    posSpan.className = 'pick-pos';
    posSpan.textContent = String(i);
    row.appendChild(posSpan);

    var labelText = labels[i - 1] ? String(labels[i - 1]) : '';
    if (labelText && labelText !== String(i)) {
      var monoSpan = document.createElement('span');
      monoSpan.className = 'mono';
      monoSpan.textContent = labelText;
      row.appendChild(monoSpan);
    }

    fragment.appendChild(row);
    rows.push({
      el: row,
      pos: String(i),
      label: labelText.toLowerCase()
    });
  }

  picker.appendChild(fragment);

  filterInput.addEventListener('input', function () {
    var query = filterInput.value.trim().toLowerCase();
    for (var j = 0; j < rows.length; j++) {
      var r = rows[j];
      if (!query || r.pos.indexOf(query) !== -1 || (r.label && r.label.indexOf(query) !== -1)) {
        r.el.removeAttribute('hidden');
      } else {
        r.el.setAttribute('hidden', '');
      }
    }
  });
});
