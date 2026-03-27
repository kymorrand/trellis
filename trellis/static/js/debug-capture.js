/**
 * Debug Capture Panel — Gardener's Notebook
 * Floating dev-mode panel for triggering display screenshot captures.
 * Only activates on localhost or with ?debug query param.
 */
(function DebugCapturePanel() {
  'use strict';

  // Gate: only activate in dev mode
  const isLocalhost = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
  const hasDebugParam = new URLSearchParams(location.search).has('debug');
  if (!isLocalhost && !hasDebugParam) return;

  // State
  let isCapturing = false;

  // Build the panel DOM
  const panel = document.createElement('div');
  panel.className = 'debug-capture';
  panel.innerHTML = [
    '<div class="debug-capture__header">',
    '  <span class="debug-capture__title">Capture</span>',
    '  <span class="debug-capture__controls">',
    '    <button class="debug-capture__toggle" title="Collapse/expand">&#x25BC;</button>',
    '    <button class="debug-capture__close" title="Close panel">&times;</button>',
    '  </span>',
    '</div>',
    '<div class="debug-capture__body">',
    '  <button class="debug-capture__btn" id="debug-capture-btn">',
    '    &#x1F4F8; Capture for Ivy',
    '  </button>',
    '  <div class="debug-capture__shortcut">Ctrl+Shift+S</div>',
    '  <div class="debug-capture__status" id="debug-capture-status"></div>',
    '</div>',
  ].join('\n');

  // Restore collapsed state
  const wasCollapsed = sessionStorage.getItem('debug-capture-collapsed') === 'true';
  if (wasCollapsed) {
    panel.dataset.collapsed = 'true';
  }

  // Wait for DOM, then append
  function mount() {
    document.body.appendChild(panel);
    bindEvents();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }

  function bindEvents() {
    const header = panel.querySelector('.debug-capture__header');
    const toggleBtn = panel.querySelector('.debug-capture__toggle');
    const closeBtn = panel.querySelector('.debug-capture__close');
    const captureBtn = panel.querySelector('#debug-capture-btn');

    // Collapse / expand
    header.addEventListener('click', function (e) {
      // Don't toggle if clicking close button
      if (e.target === closeBtn) return;
      const isCollapsed = panel.dataset.collapsed === 'true';
      panel.dataset.collapsed = isCollapsed ? 'false' : 'true';
      toggleBtn.innerHTML = isCollapsed ? '&#x25BC;' : '&#x25B6;';
      sessionStorage.setItem('debug-capture-collapsed', !isCollapsed);
    });

    // Close panel
    closeBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      panel.dataset.hidden = 'true';
    });

    // Capture button
    captureBtn.addEventListener('click', triggerCapture);

    // Keyboard shortcut: Ctrl+Shift+S (or Cmd+Shift+S on Mac)
    document.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'S') {
        e.preventDefault();
        triggerCapture();
      }
    });
  }

  async function triggerCapture() {
    if (isCapturing) return;
    isCapturing = true;

    const btn = panel.querySelector('#debug-capture-btn');
    const status = panel.querySelector('#debug-capture-status');

    // Loading state
    btn.disabled = true;
    btn.classList.add('debug-capture__btn--loading');
    btn.textContent = 'Capturing...';
    status.className = 'debug-capture__status';
    status.textContent = '';

    try {
      const res = await fetch('/api/screenshot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });

      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(errorText || ('HTTP ' + res.status));
      }

      const data = await res.json();

      // Build success display
      // Response shape: {image, metadata: {timestamp, display: {width, height, monitor}, monitors_available}}
      const meta = data.metadata || {};
      const display = meta.display || {};
      const timestamp = meta.timestamp || new Date().toLocaleTimeString();
      const lines = [];
      lines.push(row('Captured', timestamp));
      if (display.width && display.height) {
        lines.push(row('Display', display.width + ' \u00d7 ' + display.height));
      }
      if (meta.monitors_available) {
        lines.push(row('Monitors', meta.monitors_available));
      }
      status.innerHTML = lines.join('');
      status.className = 'debug-capture__status debug-capture__status--success';

      // Remove success highlight after 2s
      setTimeout(function () {
        status.classList.remove('debug-capture__status--success');
      }, 2000);

    } catch (err) {
      status.textContent = 'Error: ' + err.message;
      status.className = 'debug-capture__status debug-capture__status--error';
    } finally {
      btn.disabled = false;
      btn.classList.remove('debug-capture__btn--loading');
      btn.innerHTML = '&#x1F4F8; Capture for Ivy';
      isCapturing = false;
    }
  }

  function row(label, value) {
    return '<div class="debug-capture__detail">' +
      '<span class="debug-capture__detail-label">' + label + '</span>' +
      '<span class="debug-capture__detail-value">' + value + '</span>' +
      '</div>';
  }
})();
