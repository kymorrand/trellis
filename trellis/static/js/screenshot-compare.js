/**
 * Screenshot Compare Panel — Phase 2
 * Right-docked sidebar for comparing DOM captures vs physical display captures.
 * Only activates on localhost or with ?debug query param.
 */
(function ScreenshotComparePanel() {
  'use strict';

  // Gate: only activate in dev mode
  var isLocalhost = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
  var hasDebugParam = new URLSearchParams(location.search).has('debug');
  if (!isLocalhost && !hasDebugParam) return;

  // State
  var isOpen = false;
  var isCapturing = false;
  var hasGsap = typeof gsap !== 'undefined';
  var history = []; // {timestamp, displayUrl, domUrl}
  var activeHistoryIndex = -1;
  var MAX_HISTORY = 5;

  // Build the panel DOM
  var panel = document.createElement('div');
  panel.className = 'sc-panel' + (hasGsap ? '' : ' sc-panel--no-gsap');
  panel.innerHTML = [
    '<div class="sc-panel__header">',
    '  <span class="sc-panel__title">Screenshot Compare</span>',
    '  <button class="sc-panel__close" title="Close panel">&times;</button>',
    '</div>',
    '<div class="sc-panel__content">',
    '  <div class="sc-panel__status sc-panel__status--empty" id="sc-status">',
    '    <span class="sc-panel__status-dot"></span>',
    '    <span id="sc-status-text">No captures</span>',
    '  </div>',
    '  <div class="sc-section" id="sc-dom-section">',
    '    <div class="sc-section__label">DOM Capture <span class="sc-section__timestamp" id="sc-dom-ts"></span></div>',
    '    <div class="sc-section__image-area" id="sc-dom-area">',
    '      <div class="sc-section__placeholder">DOM capture<br>connect Playwright</div>',
    '    </div>',
    '  </div>',
    '  <div class="sc-section" id="sc-display-section">',
    '    <div class="sc-section__label">Display Capture <span class="sc-section__timestamp" id="sc-display-ts"></span></div>',
    '    <div class="sc-section__image-area" id="sc-display-area">',
    '      <div class="sc-section__placeholder">Capture to begin</div>',
    '    </div>',
    '  </div>',
    '  <div class="sc-history" id="sc-history" style="display:none;">',
    '    <div class="sc-history__label">History</div>',
    '    <div class="sc-history__pills" id="sc-history-pills"></div>',
    '  </div>',
    '</div>',
    '<div class="sc-panel__actions">',
    '  <button class="sc-panel__capture-btn" id="sc-capture-btn">Refresh Captures</button>',
    '  <div class="sc-panel__shortcut">Ctrl+D to toggle</div>',
    '</div>',
  ].join('\n');

  // Add the debug nav link to the nav bar
  function addDebugNavLink() {
    var navs = document.querySelectorAll('.trellis-nav');
    for (var i = 0; i < navs.length; i++) {
      var nav = navs[i];
      if (nav.querySelector('[data-sc-debug-link]')) continue;
      var link = document.createElement('a');
      link.href = '#';
      link.className = 'trellis-nav__link';
      link.textContent = 'Debug';
      link.dataset.scDebugLink = 'true';
      link.addEventListener('click', function (e) {
        e.preventDefault();
        togglePanel();
      });
      nav.appendChild(link);
    }
  }

  // Mount
  function mount() {
    document.body.appendChild(panel);
    addDebugNavLink();
    bindEvents();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }

  function bindEvents() {
    panel.querySelector('.sc-panel__close').addEventListener('click', function () {
      closePanel();
    });

    panel.querySelector('#sc-capture-btn').addEventListener('click', function () {
      triggerCapture();
    });

    // Keyboard shortcut: Ctrl+D
    document.addEventListener('keydown', function (e) {
      if (e.ctrlKey && !e.shiftKey && !e.altKey && e.key === 'd') {
        e.preventDefault();
        togglePanel();
      }
    });
  }

  function togglePanel() {
    if (isOpen) {
      closePanel();
    } else {
      openPanel();
    }
  }

  function openPanel() {
    if (isOpen) return;
    isOpen = true;
    if (hasGsap) {
      gsap.to(panel, { x: 0, duration: 0.35, ease: 'power2.out' });
    } else {
      panel.classList.add('sc-panel--open');
    }
  }

  function closePanel() {
    if (!isOpen) return;
    isOpen = false;
    if (hasGsap) {
      gsap.to(panel, { x: 320, duration: 0.25, ease: 'power2.in' });
    } else {
      panel.classList.remove('sc-panel--open');
    }
  }

  async function triggerCapture() {
    if (isCapturing) return;
    isCapturing = true;

    var btn = panel.querySelector('#sc-capture-btn');
    btn.disabled = true;
    btn.classList.add('sc-panel__capture-btn--loading');
    btn.textContent = 'Capturing...';

    try {
      var res = await fetch('/api/screenshot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });

      if (!res.ok) {
        var errorText = await res.text();
        throw new Error(errorText || ('HTTP ' + res.status));
      }

      // Response is raw PNG bytes; metadata in headers
      var blob = await res.blob();
      var displayUrl = URL.createObjectURL(blob);

      var timestamp = res.headers.get('X-Screenshot-Timestamp') || new Date().toLocaleTimeString();
      var width = res.headers.get('X-Screenshot-Width') || '?';
      var height = res.headers.get('X-Screenshot-Height') || '?';

      // Push to history, evict old entries
      if (history.length >= MAX_HISTORY) {
        var evicted = history.shift();
        if (evicted.displayUrl) URL.revokeObjectURL(evicted.displayUrl);
        if (evicted.domUrl) URL.revokeObjectURL(evicted.domUrl);
      }

      var entry = {
        timestamp: timestamp,
        displayUrl: displayUrl,
        domUrl: null,
        width: width,
        height: height,
      };
      history.push(entry);
      activeHistoryIndex = history.length - 1;

      renderCapture(entry);
      renderHistory();
      updateStatus();

    } catch (err) {
      showDisplayError('Error: ' + err.message);
    } finally {
      btn.disabled = false;
      btn.classList.remove('sc-panel__capture-btn--loading');
      btn.textContent = 'Refresh Captures';
      isCapturing = false;
    }
  }

  function renderCapture(entry) {
    // Display capture
    var displayArea = panel.querySelector('#sc-display-area');
    var displayTs = panel.querySelector('#sc-display-ts');

    if (entry.displayUrl) {
      var img = document.createElement('img');
      img.src = entry.displayUrl;
      img.alt = 'Display capture ' + entry.timestamp;
      img.title = entry.width + ' x ' + entry.height + ' — click to open full size';
      img.addEventListener('click', function () {
        window.open(entry.displayUrl, '_blank');
      });
      displayArea.innerHTML = '';
      displayArea.appendChild(img);
      displayTs.textContent = entry.timestamp;
    }

    // DOM capture
    var domArea = panel.querySelector('#sc-dom-area');
    var domTs = panel.querySelector('#sc-dom-ts');

    if (entry.domUrl) {
      var domImg = document.createElement('img');
      domImg.src = entry.domUrl;
      domImg.alt = 'DOM capture ' + entry.timestamp;
      domImg.addEventListener('click', function () {
        window.open(entry.domUrl, '_blank');
      });
      domArea.innerHTML = '';
      domArea.appendChild(domImg);
      domTs.textContent = entry.timestamp;
    } else {
      domArea.innerHTML = '<div class="sc-section__placeholder">DOM capture<br>connect Playwright</div>';
      domTs.textContent = '';
    }
  }

  function showDisplayError(message) {
    var displayArea = panel.querySelector('#sc-display-area');
    displayArea.innerHTML = '<div class="sc-section__error">' + escapeHtml(message) + '</div>';
  }

  function updateStatus() {
    var statusEl = panel.querySelector('#sc-status');
    var statusText = panel.querySelector('#sc-status-text');

    if (history.length === 0) {
      statusEl.className = 'sc-panel__status sc-panel__status--empty';
      statusText.textContent = 'No captures';
      return;
    }

    var current = history[activeHistoryIndex];
    if (current && current.displayUrl && current.domUrl) {
      statusEl.className = 'sc-panel__status sc-panel__status--ready';
      statusText.textContent = 'Ready for comparison';
    } else if (current && current.displayUrl) {
      statusEl.className = 'sc-panel__status sc-panel__status--partial';
      statusText.textContent = 'Missing DOM capture';
    } else {
      statusEl.className = 'sc-panel__status sc-panel__status--empty';
      statusText.textContent = 'No captures';
    }
  }

  function renderHistory() {
    var container = panel.querySelector('#sc-history');
    var pills = panel.querySelector('#sc-history-pills');

    if (history.length === 0) {
      container.style.display = 'none';
      return;
    }

    container.style.display = '';
    pills.innerHTML = '';

    for (var i = 0; i < history.length; i++) {
      var pill = document.createElement('button');
      pill.className = 'sc-history__pill' + (i === activeHistoryIndex ? ' sc-history__pill--active' : '');
      pill.textContent = history[i].timestamp;
      pill.dataset.index = i;
      pill.addEventListener('click', function () {
        var idx = parseInt(this.dataset.index, 10);
        activeHistoryIndex = idx;
        renderCapture(history[idx]);
        renderHistory();
        updateStatus();
      });
      pills.appendChild(pill);
    }
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  /**
   * Public API for Phase 3 integration.
   * Call window.ScreenshotCompare.setDomCapture(blobUrl, timestamp)
   * to set the DOM capture image for the current or latest entry.
   */
  window.ScreenshotCompare = {
    open: openPanel,
    close: closePanel,
    toggle: togglePanel,
    setDomCapture: function (blobUrl, timestamp) {
      if (history.length === 0) {
        history.push({
          timestamp: timestamp || new Date().toLocaleTimeString(),
          displayUrl: null,
          domUrl: blobUrl,
        });
        activeHistoryIndex = 0;
      } else {
        var current = history[activeHistoryIndex];
        if (current.domUrl) URL.revokeObjectURL(current.domUrl);
        current.domUrl = blobUrl;
        if (timestamp) current.timestamp = timestamp;
      }
      renderCapture(history[activeHistoryIndex]);
      renderHistory();
      updateStatus();
    },
  };
})();
