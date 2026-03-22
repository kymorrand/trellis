/**
 * Trellis API Client
 * Shared by canvas.html and brief.html for fetching live data.
 */

const TrellisAPI = {
  async getStatus() {
    const res = await fetch('/api/status');
    return res.json();
  },

  async getVaultItems(limit = 12) {
    const res = await fetch(`/api/vault/items?limit=${limit}`);
    return res.json();
  },

  async getJournalRecent(limit = 10) {
    const res = await fetch(`/api/journal/recent?limit=${limit}`);
    return res.json();
  },

  async getAgentState() {
    const res = await fetch('/api/agent/state');
    return res.json();
  },

  async getQueue() {
    const res = await fetch('/api/queue');
    return res.json();
  },

  async getBrief() {
    const res = await fetch('/api/brief');
    return res.json();
  },

  async approveItem(id) {
    const res = await fetch(`/api/queue/${id}/approve`, { method: 'POST' });
    return res.json();
  },

  async dismissItem(id) {
    const res = await fetch(`/api/queue/${id}/dismiss`, { method: 'POST' });
    return res.json();
  },

  /**
   * Connect to the agent state SSE stream.
   * Calls onStateChange(stateDict) on each update.
   * Returns the EventSource for cleanup.
   */
  connectStateStream(onStateChange) {
    const es = new EventSource('/api/agent/state/stream');
    es.addEventListener('state', (e) => {
      try {
        onStateChange(JSON.parse(e.data));
      } catch (err) {
        console.warn('Failed to parse state event:', err);
      }
    });
    es.onerror = () => {
      console.warn('SSE connection lost, reconnecting...');
      // EventSource auto-reconnects; no manual action needed
    };
    return es;
  },

  /**
   * Format seconds into a human-readable uptime string.
   */
  formatUptime(seconds) {
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    if (hours < 24) return `${hours}h ${remainingMinutes}m`;
    const days = Math.floor(hours / 24);
    const remainingHours = hours % 24;
    return `${days}d ${remainingHours}h`;
  },

  /**
   * Format an ISO date as relative garden language.
   */
  formatGardenTime(isoDate, verb = 'planted') {
    const date = new Date(isoDate);
    const now = new Date();
    const diffMs = now - date;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return `${verb} today`;
    if (diffDays === 1) return `${verb} yesterday`;
    if (diffDays < 7) return `${verb} ${diffDays} days ago`;
    if (diffDays < 14) return `${verb} 1 week ago`;
    if (diffDays < 30) return `${verb} ${Math.floor(diffDays / 7)} weeks ago`;
    if (diffDays < 60) return `${verb} 1 month ago`;
    return `${verb} ${Math.floor(diffDays / 30)} months ago`;
  },

  /**
   * Return the SVG string for a growth stage icon.
   */
  growthSVG(stage, size = 28) {
    const colors = {
      seed: 'var(--color-earth-light)',
      growing: 'var(--color-leaf)',
      evergreen: 'var(--color-leaf-dark)',
    };
    const color = colors[stage] || colors.seed;

    const paths = {
      seed: `<line x1="14" y1="22" x2="14" y2="14"/>
             <path d="M14 14 C12 12, 10 13, 10 11"/>
             <path d="M14 16 C16 14, 18 15, 18 13"/>`,
      growing: `<line x1="14" y1="24" x2="14" y2="10"/>
                <path d="M14 10 C11 8, 8 9, 7 7"/>
                <path d="M14 13 C17 11, 20 12, 21 10"/>
                <path d="M14 16 C11 14, 9 16, 8 14"/>
                <path d="M14 19 C17 17, 19 18, 20 16"/>`,
      evergreen: `<line x1="14" y1="26" x2="14" y2="8"/>
                  <path d="M14 8 C11 5, 7 6, 5 4"/>
                  <path d="M14 8 C17 5, 21 6, 23 4"/>
                  <path d="M14 12 C10 9, 7 11, 5 9"/>
                  <path d="M14 12 C18 9, 21 11, 23 9"/>
                  <path d="M14 16 C11 14, 8 15, 6 13"/>
                  <path d="M14 16 C17 14, 20 15, 22 13"/>
                  <path d="M14 20 C11 18, 9 19, 7 17"/>
                  <path d="M14 20 C17 18, 19 19, 21 17"/>
                  <circle cx="14" cy="6" r="2.5" fill="none"/>`,
    };

    return `<svg viewBox="0 0 ${size} ${size}" fill="none" stroke="currentColor"
                 stroke-width="1.5" stroke-linecap="round" style="color: ${color}">
              ${paths[stage] || paths.seed}
            </svg>`;
  },
};
