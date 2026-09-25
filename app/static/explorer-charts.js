/**
 * RaschLab Explorer Charts Module
 * Plain ES2019 inline-SVG visual renderers for Rasch measurement models.
 * Token-derived styling, pure DOM construction with document.createElementNS.
 */
(function () {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';

  function clearElement(element) {
    if (!element) return;
    while (element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function formatEntryAlias(entry) {
    return 'I-' + String(entry).padStart(3, '0');
  }

  function getToken(name) {
    if (typeof document === 'undefined' || !document.documentElement) return '';
    var val = getComputedStyle(document.documentElement).getPropertyValue(name);
    return val ? val.trim() : '';
  }

  function formatNum(val) {
    if (typeof window !== 'undefined' && window.RaschExplorer && typeof window.RaschExplorer.formatIdNum === 'function') {
      return window.RaschExplorer.formatIdNum(val);
    }
    if (val === null || val === undefined) return '';
    return String(val);
  }

  function svgEl(tag, attrs, text) {
    var el = document.createElementNS(SVG_NS, tag);
    if (attrs) {
      for (var k in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, k)) {
          el.setAttribute(k, String(attrs[k]));
        }
      }
    }
    if (text !== undefined && text !== null) {
      el.textContent = String(text);
    }
    return el;
  }

  /**
   * Replace container content with an item parameter definition list.
   * itemRow layout: [entry, label, measure, se, infitMNSQ, infitZSTD, outfitMNSQ, outfitZSTD, corr, exactOBS]
   */
  function writeReadout(container, itemRow) {
    if (!container) return;
    if (!itemRow || !Array.isArray(itemRow) || itemRow.length === 0) {
      if (!container.textContent.trim()) {
        container.textContent = 'Fokus pada butir di peta untuk melihat rincian.';
      }
      return;
    }
    clearElement(container);

    var entry = itemRow[0];
    var label = itemRow[1] !== null && itemRow[1] !== undefined ? String(itemRow[1]).trim() : '';
    var titleText = 'Butir ' + formatNum(entry) + (label ? ' ' + label : '');

    var heading = document.createElement('h3');
    heading.textContent = titleText;
    container.appendChild(heading);

    var infitVal = parseFloat(String(itemRow[4]).replace(',', '.'));
    if (!isNaN(infitVal) && infitVal >= 1.5) {
      var flag = document.createElement('p');
      var flagStrong = document.createElement('strong');
      flagStrong.textContent = 'Infit tinggi (MNSQ ≥ 1,50)';
      flag.appendChild(flagStrong);
      container.appendChild(flag);
    }

    var dl = document.createElement('dl');
    function addRow(term, def) {
      var dt = document.createElement('dt');
      dt.textContent = term;
      var dd = document.createElement('dd');
      dd.textContent = def;
      dl.appendChild(dt);
      dl.appendChild(dd);
    }

    addRow('Measure', formatNum(itemRow[2]));
    addRow('S.E.', formatNum(itemRow[3]));
    addRow('INFIT MNSQ', formatNum(itemRow[4]));
    addRow('INFIT ZSTD', formatNum(itemRow[5]));
    addRow('OUTFIT MNSQ', formatNum(itemRow[6]));
    addRow('OUTFIT ZSTD', formatNum(itemRow[7]));
    addRow('Korelasi butir-total', formatNum(itemRow[8]));

    var obsVal = itemRow[9] !== undefined && itemRow[9] !== null ? formatNum(itemRow[9]) : '';
    if (obsVal && obsVal.indexOf('%') === -1) {
      obsVal += '%';
    }
    addRow('Kesesuaian jawaban', obsVal);

    container.appendChild(dl);
  }

  /**
   * Wright Map: single logit scale with person histogram above and item ticks below.
   * payload layout: { schema, bins, items }
   * bin layout: [measure, nrPerson, nrItem, itemEntries]
   * item layout: [entry, label, measure, se, infitMNSQ, infitZSTD, outfitMNSQ, outfitZSTD, corr, exactOBS]
   */
  function drawWright(container, payload) {
    if (!container || !container.appendChild) return null;
    clearElement(container);

    if (!payload || !payload.bins || !Array.isArray(payload.bins) || payload.bins.length === 0) {
      return null;
    }

    var bins = payload.bins.slice().sort(function (a, b) {
      return parseFloat(String(a[0]).replace(',', '.')) - parseFloat(String(b[0]).replace(',', '.'));
    });

    var totalPersons = 0;
    var totalItems = 0;
    var maxPersons = 1;

    for (var i = 0; i < bins.length; i++) {
      var pCount = parseInt(bins[i][1], 10) || 0;
      var itCount = parseInt(bins[i][2], 10) || 0;
      totalPersons += pCount;
      totalItems += itCount;
      if (pCount > maxPersons) maxPersons = pCount;
    }

    var itemsByEntry = new Map();
    if (payload.items && Array.isArray(payload.items)) {
      for (var j = 0; j < payload.items.length; j++) {
        itemsByEntry.set(payload.items[j][0], payload.items[j]);
      }
    }

    var misfitToggle = document.getElementById('wright-misfit-toggle');
    var isMisfitChecked = Boolean(misfitToggle && misfitToggle.checked);

    var marginL = 50;
    var marginR = 30;
    var binWidth = 34;
    var plotWidth = Math.max(760, bins.length * binWidth);
    var svgWidth = plotWidth + marginL + marginR;
    var axisY = 190;
    var personAreaHeight = 145;
    var itemRowHeight = 18;
    var curBinW = plotWidth / bins.length;

    // Item label layout, computed before the canvas is built so the canvas can size itself to
    // the tallest column. Labels sit in columns on a grid whose pitch is wider than a label box
    // (38 + 8), so two boxes can never overlap however tightly the items cluster; a column that
    // is full spills to the nearest column with room instead of running off the bottom.
    var LABEL_BOX_W = 38;
    var LABEL_PITCH = 46;
    var ITEM_TOP = 54;
    var LABEL_ROWS_MAX = 12;
    var itemRows = [];
    for (var rIdx = 0; rIdx < bins.length; rIdx++) {
      var binEntries = String(bins[rIdx][3] || '').trim().split(/\s+/).filter(Boolean);
      for (var bEntry = 0; bEntry < binEntries.length; bEntry++) {
        var parsedEntry = parseInt(binEntries[bEntry], 10);
        if (isNaN(parsedEntry)) continue;
        itemRows.push({
          entry: parsedEntry,
          binX: marginL + rIdx * curBinW + curBinW / 2,
          measure: parseFloat(String(bins[rIdx][0]).replace(',', '.'))
        });
      }
    }
    var gridX = [];
    for (var gx = marginL + curBinW / 2; gx <= marginL + plotWidth - LABEL_BOX_W / 2 + 1; gx += LABEL_PITCH) {
      gridX.push(Math.round(gx));
    }
    if (gridX.length === 0) gridX.push(Math.round(marginL + plotWidth / 2));
    var columnOf = [];
    for (var cInit = 0; cInit < gridX.length; cInit++) columnOf.push([]);
    var tallestColumn = 1;
    var placedItems = 0;
    for (var iIdx = 0; iIdx < itemRows.length; iIdx++) {
      var preferred = Math.round((itemRows[iIdx].binX - gridX[0]) / LABEL_PITCH);
      if (preferred < 0) preferred = 0;
      if (preferred > gridX.length - 1) preferred = gridX.length - 1;
      var target = -1;
      for (var step = 0; step < gridX.length && target < 0; step++) {
        if (step === 0) {
          if (columnOf[preferred].length < LABEL_ROWS_MAX) target = preferred;
        } else {
          if (preferred + step < gridX.length && columnOf[preferred + step].length < LABEL_ROWS_MAX) target = preferred + step;
          else if (preferred - step >= 0 && columnOf[preferred - step].length < LABEL_ROWS_MAX) target = preferred - step;
        }
      }
      if (target < 0) continue;
      columnOf[target].push(itemRows[iIdx]);
      placedItems++;
      if (columnOf[target].length > tallestColumn) tallestColumn = columnOf[target].length;
    }
    var itemAreaHeight = Math.max(250, tallestColumn * itemRowHeight + 65);
    var svgHeight = axisY + itemAreaHeight;

    var fontUi = getToken('--font-ui') || 'system-ui, sans-serif';
    var fontMono = getToken('--font-mono') || 'ui-monospace, monospace';
    var colorInk = getToken('--ink');
    var colorMuted = getToken('--muted');
    var colorControl = getToken('--control');
    var colorLine = getToken('--line');
    var colorAccent = getToken('--accent');
    var colorWarn = getToken('--warn');
    var colorMisfit = getToken('--misfit');
    var step12 = getToken('--step-12') || '12';

    var svg = svgEl('svg', {
      role: 'img',
      'aria-label': 'Peta Wright: rentang ' + formatNum(bins[0][0]) + ' hingga ' + formatNum(bins[bins.length - 1][0]) + ' logit, ' + formatNum(totalPersons) + ' partisipan, ' + formatNum(totalItems) + ' butir',
      viewBox: '0 0 ' + svgWidth + ' ' + svgHeight,
      style: 'min-width: 600px; width: 100%; height: auto; display: block;'
    });
    svg.appendChild(svgEl('title', null, 'Histogram sebaran partisipan'));

    svg.appendChild(svgEl('text', {
      x: marginL,
      y: 20,
      'font-family': fontUi,
      'font-size': step12,
      'font-weight': '600',
      fill: colorMuted
    }, 'Histogram sebaran partisipan'));

    svg.appendChild(svgEl('text', {
      x: marginL,
      y: 36,
      'font-family': fontUi,
      'font-size': step12,
      'font-weight': '600',
      fill: colorMuted
    }, 'Partisipan'));

    // Gridlines at the count levels, behind the bars, so heights are readable without the scale.
    if (maxPersons > 0) {
      var gridGroup = svgEl('g');
      var gridFrag = document.createDocumentFragment();
      var gridLevels = [maxPersons, Math.round(maxPersons / 2)];
      for (var gIdx = 0; gIdx < gridLevels.length; gIdx++) {
        var gridY = axisY - (gridLevels[gIdx] / maxPersons) * personAreaHeight;
        gridFrag.appendChild(svgEl('line', {
          x1: marginL,
          y1: gridY,
          x2: marginL + plotWidth,
          y2: gridY,
          stroke: colorLine,
          'stroke-width': '1',
          'vector-effect': 'non-scaling-stroke'
        }));
      }
      gridGroup.appendChild(gridFrag);
      svg.appendChild(gridGroup);
    }

    var histGroup = svgEl('g');
    var histFrag = document.createDocumentFragment();
    for (var bIdx = 0; bIdx < bins.length; bIdx++) {
      var count = parseInt(bins[bIdx][1], 10) || 0;
      if (count > 0) {
        var bCenter = marginL + bIdx * curBinW + curBinW / 2;
        var barW = Math.max(4, curBinW - 2);
        var barH = (count / maxPersons) * personAreaHeight;
        var bar = svgEl('rect', {
          x: bCenter - barW / 2,
          y: axisY - barH,
          width: barW,
          height: barH,
          fill: colorAccent,
          rx: 1
        });
        bar.appendChild(svgEl('title', null, formatNum(bins[bIdx][0]) + ' logit: ' + formatNum(count) + ' partisipan'));
        histFrag.appendChild(bar);
      }
    }
    histGroup.appendChild(histFrag);
    svg.appendChild(histGroup);

    // Count scale on the left of the histogram, so bar heights are readable without hovering.
    if (maxPersons > 0) {
      var scaleGroup = svgEl('g');
      var scaleFrag = document.createDocumentFragment();
      var scaleValues = [maxPersons, Math.round(maxPersons / 2), 0];
      for (var sIdx = 0; sIdx < scaleValues.length; sIdx++) {
        var sVal = scaleValues[sIdx];
        scaleFrag.appendChild(svgEl('text', {
          x: marginL - 8,
          y: axisY - (sVal / maxPersons) * personAreaHeight,
          'text-anchor': 'end',
          'dominant-baseline': 'middle',
          'font-family': fontMono,
          'font-size': '11',
          fill: colorMuted
        }, formatNum(sVal)));
      }
      scaleGroup.appendChild(scaleFrag);
      svg.appendChild(scaleGroup);
    }

    var axisGroup = svgEl('g');
    var axisFrag = document.createDocumentFragment();
    axisFrag.appendChild(svgEl('line', {
      x1: marginL,
      y1: axisY,
      x2: marginL + plotWidth,
      y2: axisY,
      stroke: colorControl,
      'stroke-width': '1.5',
      'vector-effect': 'non-scaling-stroke'
    }));

    for (var tIdx = 0; tIdx < bins.length; tIdx++) {
      var mVal = parseFloat(String(bins[tIdx][0]).replace(',', '.'));
      var tickX = marginL + tIdx * curBinW + curBinW / 2;
      var isMajor = Math.abs(mVal - Math.round(mVal)) < 0.01;
      var isHalf = Math.abs(mVal * 2 - Math.round(mVal * 2)) < 0.01;
      var tickH = isMajor ? 8 : (isHalf ? 5 : 3);
      axisFrag.appendChild(svgEl('line', {
        x1: tickX,
        y1: axisY - tickH,
        x2: tickX,
        y2: axisY + tickH,
        stroke: isMajor ? colorControl : colorLine,
        'stroke-width': '1',
        'vector-effect': 'non-scaling-stroke'
      }));
      if (isMajor || tIdx === 0 || tIdx === bins.length - 1) {
        axisFrag.appendChild(svgEl('text', {
          x: tickX,
          y: axisY + 20,
          'text-anchor': 'middle',
          'font-family': fontMono,
          'font-size': '11',
          fill: colorInk
        }, formatNum(bins[tIdx][0])));
      }
    }

    axisFrag.appendChild(svgEl('text', {
      x: marginL,
      y: axisY + 36,
      'font-family': fontUi,
      'font-size': step12,
      'font-weight': '600',
      fill: colorMuted
    }, 'skala logit'));

    var legendX = marginL + plotWidth - 132;
    var bandGroup = svgEl('g', { 'aria-label': 'Batas misfit 1,50' });
    bandGroup.appendChild(svgEl('line', {
      x1: legendX,
      y1: 32,
      x2: legendX + 15,
      y2: 32,
      stroke: colorMisfit,
      'stroke-width': '2',
      'stroke-dasharray': '4 2',
      'vector-effect': 'non-scaling-stroke'
    }));
    bandGroup.appendChild(svgEl('text', {
      x: legendX + 22,
      y: 36,
      'font-family': fontUi,
      'font-size': '11',
      fill: colorMuted
    }, 'Batas misfit 1,50'));
    axisFrag.appendChild(bandGroup);

    axisFrag.appendChild(svgEl('text', {
      x: marginL + plotWidth,
      y: axisY + 36,
      'text-anchor': 'end',
      'font-family': fontUi,
      'font-size': '11',
      fill: colorMuted
    }, 'Butir soal (tingkat kesulitan)'));
    axisGroup.appendChild(axisFrag);
    svg.appendChild(axisGroup);

    var itemGroup = svgEl('g');
    var itemFrag = document.createDocumentFragment();

    function selectTick(elem, row) {
      var prev = svg.querySelectorAll('.wright-item-tick.is-active');
      for (var p = 0; p < prev.length; p++) {
        prev[p].classList.remove('is-active');
        prev[p].removeAttribute('aria-selected');
      }
      if (elem) {
        elem.classList.add('is-active');
        elem.setAttribute('aria-selected', 'true');
      }
      var readout = document.getElementById('wright-readout');
      if (readout && row) {
        writeReadout(readout, row);
      }
    }

    for (var colIdx = 0; colIdx < gridX.length; colIdx++) {
      var colRows = columnOf[colIdx];
      var colX = gridX[colIdx];
      var boxL = colX - LABEL_BOX_W / 2;
      var boxR = colX + LABEL_BOX_W / 2;

      for (var rowIdx = 0; rowIdx < colRows.length; rowIdx++) {
        var rowItem = colRows[rowIdx];
        var entryNum = rowItem.entry;
        var alias = formatEntryAlias(entryNum);
        var itemRow = itemsByEntry.get(entryNum);
        var infitVal = itemRow ? parseFloat(String(itemRow[4]).replace(',', '.')) : NaN;
        var isMisfit = !isNaN(infitVal) && infitVal >= 1.5;
        var itemY = axisY + ITEM_TOP + rowIdx * itemRowHeight;

        var gClass = 'wright-item-tick' + (isMisfit ? ' is-misfit' : '') + (isMisfit && isMisfitChecked ? ' is-misfit-highlight' : '');
        var g = svgEl('g', {
          class: gClass,
          tabindex: '0',
          role: 'button',
          'data-entry': entryNum,
          'data-item': entryNum,
          'data-bin-x': rowItem.binX,
          'aria-label': 'Butir ' + alias + ', ukuran ' + (itemRow ? formatNum(itemRow[2]) : formatNum(rowItem.measure)) + ' logit'
        });

        // The item's real position on the logit scale. A label may sit off that position only
        // while its own box still covers it (offset <= half a box); past that the box would
        // claim a position the item does not have, so a leader line tethers it to the exact x.
        var halfBox = (colX - boxL) - 0.5;
        var leaderFrom = 0;
        var leaderTo = 0;
        if (rowItem.binX < colX - halfBox) {
          leaderFrom = rowItem.binX;
          leaderTo = boxL;
        } else if (rowItem.binX > colX + halfBox) {
          leaderFrom = boxR;
          leaderTo = rowItem.binX;
        }
        if (leaderTo - leaderFrom > 0) {
          g.appendChild(svgEl('line', {
            x1: leaderFrom,
            y1: itemY - 4,
            x2: leaderTo,
            y2: itemY - 4,
            class: 'label-leader',
            stroke: colorLine,
            'stroke-width': '1',
            'stroke-dasharray': 'none',
            'vector-effect': 'non-scaling-stroke'
          }));
        }

        g.appendChild(svgEl('line', {
          x1: boxL - 4,
          y1: itemY,
          x2: boxL,
          y2: itemY,
          class: 'tick-mark',
          'stroke-width': '1',
          'vector-effect': 'non-scaling-stroke'
        }));
        g.appendChild(svgEl('rect', {
          class: 'focus-ring',
          x: boxL,
          y: itemY - 11,
          width: LABEL_BOX_W,
          height: 15,
          rx: 2
        }));
        g.appendChild(svgEl('rect', {
          x: boxL,
          y: itemY - 11,
          width: LABEL_BOX_W,
          height: 15,
          'pointer-events': 'all',
          opacity: '0'
        }));
        g.appendChild(svgEl('text', {
          x: colX,
          y: itemY,
          'text-anchor': 'middle',
          'font-family': fontMono,
          'font-size': '11',
          fill: isMisfit ? colorWarn : colorInk
        }, alias));
        g.appendChild(svgEl('title', null, 'Butir ' + alias + (itemRow ? ' (Measure: ' + formatNum(itemRow[2]) + ', INFIT MNSQ: ' + formatNum(itemRow[4]) + ')' : '')));

        (function (targetElem, targetRow) {
          function onAction(evt) {
            if (evt) evt.stopPropagation();
            selectTick(targetElem, targetRow);
          }
          targetElem.addEventListener('click', onAction);
          targetElem.addEventListener('focus', onAction);
          targetElem.addEventListener('keydown', function (evt) {
            if (evt.key === 'Enter' || evt.key === ' ' || evt.key === 'Spacebar') {
              evt.preventDefault();
              onAction(evt);
            }
          });
        })(g, itemRow);

        itemFrag.appendChild(g);
      }
    }
    itemGroup.appendChild(itemFrag);
    svg.appendChild(itemGroup);

    if (misfitToggle && !misfitToggle._hasWrightListener) {
      misfitToggle._hasWrightListener = true;
      misfitToggle.addEventListener('change', function () {
        var isChecked = Boolean(misfitToggle.checked);
        var ticks = container.querySelectorAll('.wright-item-tick.is-misfit');
        for (var t = 0; t < ticks.length; t++) {
          if (isChecked) {
            ticks[t].classList.add('is-misfit-highlight');
          } else {
            ticks[t].classList.remove('is-misfit-highlight');
          }
        }
      });
    }

    container.appendChild(svg);
    return svg;
  }

  /**
   * Delta chart comparing item measures across two analysis runs.
   * cmpData layout: { schema, from_id, to_id, from_label, to_label, pairs }
   * pair layout: [entry, label, measureFrom, measureTo, delta]
   */
  function drawDelta(container, cmpData) {
    if (!container || !container.appendChild) return null;
    clearElement(container);

    if (!cmpData || !cmpData.pairs || !Array.isArray(cmpData.pairs) || cmpData.pairs.length === 0) {
      return null;
    }

    var pairs = [];
    var maxAbsDelta = 0.5;

    for (var j = 0; j < cmpData.pairs.length; j++) {
      var item = cmpData.pairs[j];
      var entry = item[0];
      var label = item[1];
      var mFrom = item[2];
      var mTo = item[3];
      var deltaRaw = item[4];
      var dNum = parseFloat(String(deltaRaw).replace(',', '.'));
      if (isNaN(dNum)) dNum = 0;
      var absDelta = Math.abs(dNum);
      if (absDelta > maxAbsDelta) maxAbsDelta = absDelta;

      var deltaStr;
      if (typeof deltaRaw === 'string' && deltaRaw.length > 0) {
        deltaStr = deltaRaw;
      } else {
        deltaStr = (dNum >= 0 ? '+' : '') + dNum.toFixed(2);
      }

      pairs.push({
        entry: entry,
        label: label,
        alias: formatEntryAlias(entry),
        delta: dNum,
        absDelta: absDelta,
        deltaStr: deltaStr,
        fromMeasure: mFrom,
        toMeasure: mTo
      });
    }

    pairs.sort(function (a, b) {
      return b.absDelta - a.absDelta;
    });

    var minDelta = pairs[0].delta;
    var maxDelta = pairs[0].delta;
    for (var pIdx = 1; pIdx < pairs.length; pIdx++) {
      if (pairs[pIdx].delta < minDelta) minDelta = pairs[pIdx].delta;
      if (pairs[pIdx].delta > maxDelta) maxDelta = pairs[pIdx].delta;
    }

    var fromLabel = cmpData.from_label || ('#' + cmpData.from_id);
    var toLabel = cmpData.to_label || ('#' + cmpData.to_id);
    var maxRange = Math.max(0.6, Math.ceil(maxAbsDelta * 2) / 2);
    var rowHeight = 22;
    var topMargin = 50;
    var bottomMargin = 30;
    var svgWidth = 860;
    var marginLeft = 70;
    var marginRight = 65;
    var plotWidth = svgWidth - marginLeft - marginRight;
    var zeroX = marginLeft + plotWidth / 2;
    var svgHeight = topMargin + pairs.length * rowHeight + bottomMargin;

    container.classList.add('chart-scroll');

    var fontUi = getToken('--font-ui') || 'system-ui, sans-serif';
    var fontMono = getToken('--font-mono') || 'ui-monospace, monospace';
    var colorInk = getToken('--ink');
    var colorMuted = getToken('--muted');
    var colorControl = getToken('--control');
    var colorAccent = getToken('--accent');

    var svg = svgEl('svg', {
      role: 'img',
      'aria-label': 'Grafik selisih butir ' + fromLabel + ' ke ' + toLabel + ': ' + formatNum(pairs.length) + ' butir, rentang selisih dari ' + (minDelta >= 0 ? '+' : '') + formatNum(minDelta.toFixed(2)) + ' hingga ' + (maxDelta >= 0 ? '+' : '') + formatNum(maxDelta.toFixed(2)) + ' logit',
      viewBox: '0 0 ' + svgWidth + ' ' + svgHeight,
      width: '100%',
      height: svgHeight,
      style: 'display: block;'
    });
    svg.appendChild(svgEl('title', null, 'Grafik selisih butir'));

    var headerGroup = svgEl('g');
    var headerFrag = document.createDocumentFragment();
    headerFrag.appendChild(svgEl('text', {
      x: marginLeft - 8,
      y: 20,
      'text-anchor': 'end',
      'font-family': fontUi,
      'font-size': '12',
      'font-weight': '600',
      fill: colorMuted
    }, 'Butir'));
    headerFrag.appendChild(svgEl('text', {
      x: marginLeft + plotWidth * 0.25,
      y: 20,
      'text-anchor': 'middle',
      'font-family': fontUi,
      'font-size': '11',
      fill: colorMuted
    }, '<- Lebih mudah di ' + toLabel));
    headerFrag.appendChild(svgEl('text', {
      x: marginLeft + plotWidth * 0.75,
      y: 20,
      'text-anchor': 'middle',
      'font-family': fontUi,
      'font-size': '11',
      fill: colorMuted
    }, 'Lebih sukar di ' + toLabel + ' ->'));

    headerFrag.appendChild(svgEl('line', {
      x1: marginLeft,
      y1: topMargin - 12,
      x2: marginLeft + plotWidth,
      y2: topMargin - 12,
      stroke: colorControl,
      'stroke-width': '1',
      'vector-effect': 'non-scaling-stroke'
    }));
    headerFrag.appendChild(svgEl('line', {
      x1: zeroX,
      y1: topMargin - 18,
      x2: zeroX,
      y2: svgHeight - bottomMargin + 8,
      stroke: colorControl,
      'stroke-width': '1.5',
      'vector-effect': 'non-scaling-stroke'
    }));

    var ticks = [-maxRange, -maxRange / 2, 0, maxRange / 2, maxRange];
    for (var k = 0; k < ticks.length; k++) {
      var tVal = ticks[k];
      headerFrag.appendChild(svgEl('text', {
        x: zeroX + (tVal / maxRange) * (plotWidth / 2),
        y: topMargin - 18,
        'text-anchor': 'middle',
        'font-family': fontMono,
        'font-size': tVal === 0 ? '11' : '10',
        'font-weight': tVal === 0 ? '600' : '400',
        fill: tVal === 0 ? colorInk : colorMuted
      }, (tVal > 0 ? '+' : '') + formatNum(tVal.toFixed(2))));
    }
    headerGroup.appendChild(headerFrag);
    svg.appendChild(headerGroup);

    var rowGroup = svgEl('g');
    var rowFrag = document.createDocumentFragment();
    var halfPlot = plotWidth / 2;

    for (var rIdx = 0; rIdx < pairs.length; rIdx++) {
      var pair = pairs[rIdx];
      var rowY = topMargin + rIdx * rowHeight + 10;
      var isProminent = pair.absDelta >= 0.30;
      var barFill = isProminent ? colorAccent : colorControl;
      var textFill = isProminent ? colorInk : colorMuted;

      var rowG = svgEl('g', { class: 'delta-row' + (isProminent ? ' is-prominent' : ' is-muted') });
      rowG.appendChild(svgEl('text', {
        x: marginLeft - 8,
        y: rowY + 4,
        'text-anchor': 'end',
        'font-family': fontMono,
        'font-size': '11',
        fill: textFill
      }, pair.alias));

      var barLen = Math.max(1, (pair.absDelta / maxRange) * halfPlot);
      var barX = pair.delta >= 0 ? zeroX : zeroX - barLen;
      rowG.appendChild(svgEl('rect', {
        x: barX,
        y: rowY - 6,
        width: barLen,
        height: 12,
        fill: barFill,
        rx: 1
      }));

      rowG.appendChild(svgEl('circle', {
        cx: zeroX,
        cy: rowY,
        r: 2,
        fill: colorMuted
      }));
      rowG.appendChild(svgEl('circle', {
        cx: pair.delta >= 0 ? barX + barLen : barX,
        cy: rowY,
        r: 2.5,
        fill: barFill
      }));

      var valX = pair.delta >= 0 ? barX + barLen + 6 : barX - 6;
      var valAnchor = pair.delta >= 0 ? 'start' : 'end';
      rowG.appendChild(svgEl('text', {
        x: valX,
        y: rowY + 4,
        'text-anchor': valAnchor,
        'font-family': fontMono,
        'font-size': '10',
        fill: textFill
      }, formatNum(pair.deltaStr)));

      rowG.appendChild(svgEl('title', null, pair.alias + ': delta = ' + formatNum(pair.deltaStr) + ' (' + formatNum(pair.fromMeasure) + ' ke ' + formatNum(pair.toMeasure) + ')'));
      rowFrag.appendChild(rowG);
    }
    rowGroup.appendChild(rowFrag);
    svg.appendChild(rowGroup);

    container.appendChild(svg);
    return svg;
  }

  window.RaschExplorerCharts = {
    drawWright: drawWright,
    drawDelta: drawDelta,
    writeReadout: writeReadout
  };
})();
