/**
 * RaschLab Explorer client orchestration module.
 * Implements tab navigation, dynamic fragment loading, delegated table sorting,
 * search and pagination interception, compare panel delta filtering, and chart wiring.
 */
(function () {
  'use strict';

  var booted = false;
  var cachedPayload = null;
  var itemMap = new Map();

  var TAB_IDS = {
    wright: 'tab-wright',
    butir: 'tab-butir',
    partisipan: 'tab-partisipan',
    ringkasan: 'tab-ringkasan',
    bandingkan: 'tab-bandingkan'
  };

  var PANEL_IDS = {
    wright: 'panel-wright',
    butir: 'panel-butir',
    partisipan: 'panel-partisipan',
    ringkasan: 'panel-ringkasan',
    bandingkan: 'panel-bandingkan'
  };

  var TAB_ORDER = ['wright', 'butir', 'partisipan', 'ringkasan', 'bandingkan'];

  /**
   * JavaScript mirror of Python id_num Jinja filter.
   * Groups integer digits with period and separates decimals with comma.
   * Non-numeric strings pass through unmodified.
   */
  function formatIdNum(value) {
    if (value === null || value === undefined) {
      return '';
    }
    var s = String(value);
    var m = s.match(/^([+-]?)(\d+)(?:\.(\d+))?$/);
    if (!m) {
      return s;
    }
    var sign = m[1];
    var intPart = m[2];
    var decPart = m[3];
    var rev = intPart.split('').reverse().join('');
    var chunks = [];
    for (var i = 0; i < rev.length; i += 3) {
      chunks.push(rev.slice(i, i + 3));
    }
    var grouped = chunks.join('.').split('').reverse().join('');
    if (decPart !== undefined) {
      return sign + grouped + ',' + decPart;
    }
    return sign + grouped;
  }

  /**
   * Inverse of formatIdNum used for sorting numeric table cells.
   * Strips thousand separator periods and translates comma back to period.
   */
  function parseNumericCell(value) {
    if (!value) return 0;
    var cleaned = String(value).trim().replace(/%/g, '');
    cleaned = cleaned.replace(/\./g, '').replace(',', '.');
    var n = parseFloat(cleaned);
    return isNaN(n) ? 0 : n;
  }

  /**
   * Requests HTML fragment from same-origin explore endpoint.
   * The fragment parameter is mandatory per contract.
   */
  function fetchFragment(view, queryParams, onSuccess, onError) {
    var searchParams = new URLSearchParams();
    searchParams.set('fragment', view);
    searchParams.set('view', view);
    if (queryParams) {
      for (var key in queryParams) {
        if (Object.prototype.hasOwnProperty.call(queryParams, key) && queryParams[key] !== undefined && queryParams[key] !== null && queryParams[key] !== '') {
          searchParams.set(key, queryParams[key]);
        }
      }
    }
    var targetUrl = window.location.pathname + '?' + searchParams.toString();
    fetch(targetUrl + (targetUrl.indexOf('fragment=') === -1 ? '?fragment=' : ''))
      .then(function (res) {
        if (!res.ok) {
          throw new Error('HTTP ' + res.status);
        }
        return res.text();
      })
      .then(function (html) {
        onSuccess(html);
      })
      .catch(function (err) {
        onError(err);
      });
  }

  function clearFetchError() {
    var existing = document.getElementById('explorer-fetch-error');
    if (existing) {
      existing.remove();
    }
  }

  function showFetchError(panel) {
    clearFetchError();
    var alertEl = document.createElement('div');
    alertEl.id = 'explorer-fetch-error';
    alertEl.className = 'alert alert--misfit';
    alertEl.setAttribute('role', 'alert');
    alertEl.textContent = 'Gagal memuat data. Muat ulang halaman dan coba lagi.';
    if (panel) {
      panel.insertBefore(alertEl, panel.firstChild);
    }
  }

  function showExplorerError(reason) {
    var errorEl = document.getElementById('explorer-error');
    var reasonEl = document.getElementById('explorer-error-reason');
    if (!errorEl) {
      errorEl = document.createElement('div');
      errorEl.id = 'explorer-error';
      errorEl.className = 'alert alert--misfit';
      errorEl.setAttribute('role', 'alert');
      var strong = document.createElement('strong');
      strong.textContent = 'Peta Wright tidak tersedia';
      reasonEl = document.createElement('p');
      reasonEl.id = 'explorer-error-reason';
      errorEl.appendChild(strong);
      errorEl.appendChild(reasonEl);
      var panelWright = document.getElementById('panel-wright');
      if (panelWright) {
        panelWright.appendChild(errorEl);
      }
    }
    if (reasonEl) {
      reasonEl.textContent = reason || 'Data peta Wright tidak dapat dibaca untuk analisis ini.';
    }
    errorEl.hidden = false;
  }

  function applyDeltaFilter() {
    var deltaOnly = document.getElementById('cmp-delta-only');
    var tbody = document.getElementById('cmp-tbody');
    if (!deltaOnly || !tbody) return;
    var checked = deltaOnly.checked;
    var rows = tbody.querySelectorAll('.delta-row');
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var absDeltaStr = row.getAttribute('data-abs-delta') || '';
      var absDelta = parseFloat(absDeltaStr.replace(',', '.'));
      if (checked && !isNaN(absDelta) && absDelta < 0.30) {
        row.hidden = true;
      } else {
        row.hidden = false;
      }
    }
  }

  function wireComparePanel(panel) {
    var cmpDataEl = document.getElementById('cmp-data');
    var cmpChartEl = document.getElementById('cmp-chart');
    if (cmpDataEl && cmpChartEl && window.RaschExplorerCharts && typeof window.RaschExplorerCharts.drawDelta === 'function') {
      try {
        var cmpData = JSON.parse(cmpDataEl.textContent);
        window.RaschExplorerCharts.drawDelta(cmpChartEl, cmpData);
      } catch (err) {
        // malformed cmp data
      }
    }

    var deltaOnly = document.getElementById('cmp-delta-only');
    if (deltaOnly && !deltaOnly._hasDeltaListener) {
      deltaOnly._hasDeltaListener = true;
      deltaOnly.addEventListener('change', applyDeltaFilter);
    }
    applyDeltaFilter();

    var cmpFrom = document.getElementById('cmp-from');
    var cmpTo = document.getElementById('cmp-to');
    function onSelectChange() {
      if (cmpFrom && cmpTo && cmpFrom.value && cmpTo.value && cmpFrom.value !== cmpTo.value) {
        loadCompareFragment(cmpFrom.value, cmpTo.value);
      }
    }

    if (cmpFrom && !cmpFrom._hasCmpListener) {
      cmpFrom._hasCmpListener = true;
      cmpFrom.addEventListener('change', onSelectChange);
    }
    if (cmpTo && !cmpTo._hasCmpListener) {
      cmpTo._hasCmpListener = true;
      cmpTo.addEventListener('change', onSelectChange);
    }

    var compareForm = panel.querySelector('form.compare-strip');
    if (compareForm && !compareForm._hasSubmitListener) {
      compareForm._hasSubmitListener = true;
      compareForm.addEventListener('submit', function (e) {
        e.preventDefault();
        onSelectChange();
      });
    }
  }

  function loadCompareFragment(fromId, toId) {
    var panel = document.getElementById('panel-bandingkan');
    if (!panel) return;
    clearFetchError();
    var prevHtml = panel.innerHTML;
    var params = { from: fromId, to: toId };

    fetchFragment('bandingkan', params, function (html) {
      panel.innerHTML = html;
      panel.classList.add('is-loaded');

      var currentUrl = new URL(window.location.href);
      currentUrl.searchParams.set('view', 'bandingkan');
      currentUrl.searchParams.set('from', fromId);
      currentUrl.searchParams.set('to', toId);
      window.history.replaceState(null, '', currentUrl.toString());

      wireComparePanel(panel);
    }, function () {
      panel.innerHTML = prevHtml;
      showFetchError(panel);
      wireComparePanel(panel);
    });
  }

  function wireSearchAndPager(view, panel) {
    if (!panel) return;

    var searchForm = panel.querySelector('form.search-bar');
    if (searchForm && !searchForm._hasSubmitListener) {
      searchForm._hasSubmitListener = true;
      searchForm.addEventListener('submit', function (e) {
        e.preventDefault();
        var searchInput = (view === 'butir')
          ? document.getElementById('butir-search')
          : document.getElementById('partisipan-search');
        var queryVal = searchInput ? searchInput.value.trim() : '';

        var params = {};
        if (view === 'butir') {
          params.q_item = queryVal;
          params.page_item = '1';
        } else if (view === 'partisipan') {
          params.q_person = queryVal;
          params.page_person = '1';
        }

        var prevHtml = panel.innerHTML;
        clearFetchError();

        fetchFragment(view, params, function (html) {
          panel.innerHTML = html;
          panel.classList.add('is-loaded');

          var currentUrl = new URL(window.location.href);
          currentUrl.searchParams.set('view', view);
          if (view === 'butir') {
            if (queryVal) {
              currentUrl.searchParams.set('q_item', queryVal);
            } else {
              currentUrl.searchParams.delete('q_item');
            }
            currentUrl.searchParams.set('page_item', '1');
          } else if (view === 'partisipan') {
            if (queryVal) {
              currentUrl.searchParams.set('q_person', queryVal);
            } else {
              currentUrl.searchParams.delete('q_person');
            }
            currentUrl.searchParams.set('page_person', '1');
          }
          window.history.replaceState(null, '', currentUrl.toString());

          wirePanelContent(view, panel);

          var newInput = (view === 'butir')
            ? document.getElementById('butir-search')
            : document.getElementById('partisipan-search');
          if (newInput) {
            newInput.focus();
          }
        }, function () {
          panel.innerHTML = prevHtml;
          showFetchError(panel);
          wirePanelContent(view, panel);
        });
      });
    }

    if (!panel._hasLinkListener) {
      panel._hasLinkListener = true;
      panel.addEventListener('click', function (e) {
        var link = e.target.closest('a');
        if (!link) return;

        var isPager = Boolean(link.closest('.pager'));
        var isEmptyReset = Boolean(link.closest('.empty'));
        if (!isPager && !isEmptyReset) return;

        var href = link.getAttribute('href');
        if (!href) return;

        e.preventDefault();

        var targetUrl = new URL(href, window.location.href);
        var targetParams = {};
        ['view', 'q_item', 'q_person', 'page_item', 'page_person', 'from', 'to'].forEach(function (key) {
          if (targetUrl.searchParams.has(key)) {
            targetParams[key] = targetUrl.searchParams.get(key);
          }
        });

        var targetView = targetParams.view || view;
        var prevHtml = panel.innerHTML;
        clearFetchError();

        fetchFragment(targetView, targetParams, function (html) {
          panel.innerHTML = html;
          panel.classList.add('is-loaded');

          window.history.replaceState(null, '', targetUrl.toString());

          wirePanelContent(targetView, panel);
        }, function () {
          panel.innerHTML = prevHtml;
          showFetchError(panel);
          wirePanelContent(targetView, panel);
        });
      });
    }
  }

  function wirePanelContent(view, panel) {
    if (view === 'bandingkan') {
      wireComparePanel(panel);
    } else if (view === 'butir' || view === 'partisipan') {
      wireSearchAndPager(view, panel);
    }
  }

  function handleTableSort(table, sortBtn) {
    var th = sortBtn.closest('th');
    if (!th) return;
    var tbody = table.querySelector('tbody');
    if (!tbody) return;

    var currentSort = th.getAttribute('aria-sort') || 'none';
    var nextSort = 'ascending';
    if (currentSort === 'ascending') {
      nextSort = 'descending';
    } else if (currentSort === 'descending') {
      nextSort = 'none';
    }

    var allTh = table.querySelectorAll('th[aria-sort]');
    for (var i = 0; i < allTh.length; i++) {
      allTh[i].setAttribute('aria-sort', 'none');
    }
    th.setAttribute('aria-sort', nextSort);

    var colIndex = th.cellIndex;
    var sortType = sortBtn.getAttribute('data-sort') || 'number';
    var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));

    rows.sort(function (rowA, rowB) {
      var orderA = parseInt(rowA.getAttribute('data-order'), 10) || 0;
      var orderB = parseInt(rowB.getAttribute('data-order'), 10) || 0;

      if (nextSort === 'none') {
        return orderA - orderB;
      }

      var cellA = rowA.cells[colIndex];
      var cellB = rowB.cells[colIndex];
      var textA = cellA ? cellA.textContent.trim() : '';
      var textB = cellB ? cellB.textContent.trim() : '';

      var cmp = 0;
      if (sortType === 'text') {
        cmp = textA.localeCompare(textB, 'id');
      } else {
        var numA = parseNumericCell(textA);
        var numB = parseNumericCell(textB);
        cmp = numA - numB;
      }

      if (cmp === 0) {
        return orderA - orderB;
      }
      return (nextSort === 'ascending') ? cmp : -cmp;
    });

    var frag = document.createDocumentFragment();
    for (var r = 0; r < rows.length; r++) {
      frag.appendChild(rows[r]);
    }
    tbody.appendChild(frag);
  }

  function activateTab(view, shouldFocus) {
    clearFetchError();

    for (var i = 0; i < TAB_ORDER.length; i++) {
      var k = TAB_ORDER[i];
      var tab = document.getElementById(TAB_IDS[k]);
      var panel = document.getElementById(PANEL_IDS[k]);
      var isActive = (k === view);

      if (tab) {
        tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
        tab.setAttribute('tabindex', isActive ? '0' : '-1');
        if (isActive) {
          tab.classList.add('is-active');
        } else {
          tab.classList.remove('is-active');
        }
        if (isActive && shouldFocus) {
          tab.focus();
        }
      }

      if (panel) {
        if (isActive) {
          panel.classList.add('is-active');
        } else {
          panel.classList.remove('is-active');
        }
      }
    }

    var currentUrl = new URL(window.location.href);
    currentUrl.searchParams.set('view', view);
    window.history.replaceState(null, '', currentUrl.toString());

    if (view !== 'wright') {
      var activePanel = document.getElementById(PANEL_IDS[view]);
      if (activePanel && !activePanel.classList.contains('is-loaded')) {
        activePanel.innerHTML = '<div class="empty"><p class="empty-text">Memuat data...</p></div>';

        var params = {};
        var currentParams = new URLSearchParams(window.location.search);
        ['q_item', 'q_person', 'page_item', 'page_person', 'from', 'to'].forEach(function (key) {
          if (currentParams.has(key)) {
            params[key] = currentParams.get(key);
          }
        });

        fetchFragment(view, params, function (html) {
          activePanel.innerHTML = html;
          activePanel.classList.add('is-loaded');
          wirePanelContent(view, activePanel);
        }, function () {
          showFetchError(activePanel);
        });
      } else if (activePanel && activePanel.classList.contains('is-loaded')) {
        wirePanelContent(view, activePanel);
      }
    }
  }

  function wireTablist() {
    var tablist = document.getElementById('tablist');
    if (!tablist || tablist._hasTabsListener) return;
    tablist._hasTabsListener = true;

    tablist.addEventListener('click', function (e) {
      var tab = e.target.closest('[role="tab"]');
      if (!tab) return;
      e.preventDefault();
      var view = tab.id.replace('tab-', '');
      activateTab(view, false);
    });

    tablist.addEventListener('keydown', function (e) {
      var currentTab = document.activeElement ? document.activeElement.closest('[role="tab"]') : null;
      if (!currentTab) return;
      var tabs = Array.prototype.slice.call(tablist.querySelectorAll('[role="tab"]'));
      var idx = tabs.indexOf(currentTab);
      if (idx === -1) return;

      var nextIdx = idx;
      if (e.key === 'ArrowRight') {
        nextIdx = (idx + 1) % tabs.length;
      } else if (e.key === 'ArrowLeft') {
        nextIdx = (idx - 1 + tabs.length) % tabs.length;
      } else if (e.key === 'Home') {
        nextIdx = 0;
      } else if (e.key === 'End') {
        nextIdx = tabs.length - 1;
      } else if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        var v = currentTab.id.replace('tab-', '');
        activateTab(v, true);
        return;
      } else {
        return;
      }

      e.preventDefault();
      var nextTab = tabs[nextIdx];
      var nextView = nextTab.id.replace('tab-', '');
      activateTab(nextView, true);
    });
  }

  function boot() {
    if (booted) return;
    booted = true;

    wireTablist();

    // Roving tabindex setup: exactly one active tab is in tab sequence
    var currentView = 'wright';
    for (var i = 0; i < TAB_ORDER.length; i++) {
      var k = TAB_ORDER[i];
      var tabEl = document.getElementById(TAB_IDS[k]);
      if (tabEl && tabEl.classList.contains('is-active')) {
        currentView = k;
        break;
      }
    }

    for (var j = 0; j < TAB_ORDER.length; j++) {
      var tKey = TAB_ORDER[j];
      var tEl = document.getElementById(TAB_IDS[tKey]);
      if (tEl) {
        var isAct = (tKey === currentView);
        tEl.setAttribute('tabindex', isAct ? '0' : '-1');
        tEl.setAttribute('aria-selected', isAct ? 'true' : 'false');
      }
    }

    if (currentView !== 'wright') {
      var initialPanel = document.getElementById(PANEL_IDS[currentView]);
      if (initialPanel && !initialPanel.querySelector('.empty-text')) {
        initialPanel.classList.add('is-loaded');
        wirePanelContent(currentView, initialPanel);
      }
    }

    var dataEl = document.getElementById('explorer-data');
    if (!dataEl) {
      showExplorerError('Data peta Wright tidak dapat dibaca untuk analisis ini.');
      return;
    }

    var payload = null;
    try {
      payload = JSON.parse(dataEl.textContent);
    } catch (err) {
      showExplorerError('Data peta Wright tidak dapat dibaca untuk analisis ini.');
      return;
    }

    if (!payload || !payload.bins || !Array.isArray(payload.bins) || !payload.items || !Array.isArray(payload.items)) {
      showExplorerError('Data peta Wright tidak dapat dibaca untuk analisis ini.');
      return;
    }

    cachedPayload = payload;

    itemMap.clear();
    for (var mIdx = 0; mIdx < payload.items.length; mIdx++) {
      itemMap.set(payload.items[mIdx][0], payload.items[mIdx]);
    }

    var wrightScale = document.getElementById('wright-scale');
    if (wrightScale && window.RaschExplorerCharts && typeof window.RaschExplorerCharts.drawWright === 'function') {
      window.RaschExplorerCharts.drawWright(wrightScale, payload);
    }

    var misfitCount = 0;
    for (var itIdx = 0; itIdx < payload.items.length; itIdx++) {
      var itemRow = payload.items[itIdx];
      var infit = parseFloat(String(itemRow[4]).replace(',', '.'));
      if (!isNaN(infit) && infit >= 1.50) {
        misfitCount++;
      }
    }

    var wrightMeta = document.getElementById('wright-meta');
    if (wrightMeta && wrightMeta.textContent.indexOf('Butir misfit') === -1) {
      wrightMeta.textContent += ' · Butir misfit (INFIT MNSQ ≥ 1,50): ' + formatIdNum(misfitCount) + '.';
    }

    var wrightReadout = document.getElementById('wright-readout');
    if (wrightReadout && !wrightReadout.textContent.trim()) {
      wrightReadout.textContent = 'Fokus pada butir di peta untuk melihat rincian.';
    }

    var misfitToggle = document.getElementById('wright-misfit-toggle');
    if (misfitToggle && !misfitToggle._hasExplorerListener) {
      misfitToggle._hasExplorerListener = true;
      misfitToggle.addEventListener('change', function () {
        if (wrightScale && window.RaschExplorerCharts && typeof window.RaschExplorerCharts.drawWright === 'function') {
          window.RaschExplorerCharts.drawWright(wrightScale, cachedPayload);
        }
      });
    }
  }

  // Delegated sorting handler for data-explorer-table tables
  document.addEventListener('click', function (e) {
    var sortBtn = e.target.closest('.th-sort');
    if (!sortBtn) return;
    var table = sortBtn.closest('table[data-explorer-table]');
    if (!table) return;
    e.preventDefault();
    handleTableSort(table, sortBtn);
  });

  // The listed rows are read-only (measured 26 Sep 2026: activating one changed nothing), so they carry no
  // tabindex and no keyboard handler. The column sort buttons and the pager are the keyboard path through
  // these tables. A row earns a tab stop only when a real action hangs off it.

  /**
   * The participant histogram has its own boot: the Wright payload the main boot waits for does not
   * exist on this view, and the earlier build returned before ever reaching the chart.
   */
  function bootPersonHistogram() {
    var histEl = document.getElementById('partisipan-chart');
    var histDataEl = document.getElementById('partisipan-hist-data');
    if (!histEl || !histDataEl) return;
    if (!window.RaschExplorerCharts || typeof window.RaschExplorerCharts.drawPersonHistogram !== 'function') return;
    try {
      window.RaschExplorerCharts.drawPersonHistogram(histEl, JSON.parse(histDataEl.textContent));
    } catch (err) {
      /* the server already rendered the caption and the table behind it */
    }
  }

  window.RaschExplorer = {
    boot: boot,
    formatIdNum: formatIdNum
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootPersonHistogram);
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    bootPersonHistogram();
    boot();
  }
})();
