(() => {
  'use strict';
  if (window.__FLOODMAN_PWA_LOADED__) return;
  window.__FLOODMAN_PWA_LOADED__ = true;

  const RELEASE = '4.7.1';
  const isLocal = ['localhost', '127.0.0.1', '::1'].includes(location.hostname);
  const secureEnough = window.isSecureContext && (location.protocol === 'https:' || isLocal);
  const isStandalone = () => window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const isAndroid = /android/i.test(navigator.userAgent);
  let deferredInstall = null;
  let registration = null;
  let reloadingForUpdate = false;

  document.documentElement.classList.toggle('fm-pwa-standalone', isStandalone());
  document.documentElement.classList.toggle('fm-pwa-insecure', !secureEnough);

  function installPage() { return `/install-app?release=${encodeURIComponent(RELEASE)}`; }

  function announce(message, tone = 'info', action = null) {
    let root = document.getElementById('fm-pwa-toast');
    if (!root) {
      root = document.createElement('aside');
      root.id = 'fm-pwa-toast';
      root.className = 'fm-pwa-toast';
      root.setAttribute('role', 'status');
      root.innerHTML = '<div class="fm-pwa-toast-copy"></div><div class="fm-pwa-toast-actions"></div><button type="button" class="fm-pwa-toast-dismiss" aria-label="Dismiss notification">×</button>';
      root.querySelector('.fm-pwa-toast-dismiss').addEventListener('click', () => {
        root.classList.remove('is-visible');
        window.clearTimeout(root.__hideTimer);
      });
      document.body.appendChild(root);
    }
    root.dataset.tone = tone;
    root.querySelector('.fm-pwa-toast-copy').textContent = message;
    const actions = root.querySelector('.fm-pwa-toast-actions');
    actions.innerHTML = '';
    if (action) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = action.label;
      button.addEventListener('click', action.run, { once: true });
      actions.appendChild(button);
    }
    root.classList.add('is-visible');
    window.clearTimeout(root.__hideTimer);
    if (!action) root.__hideTimer = window.setTimeout(() => root.classList.remove('is-visible'), 5000);
  }

  async function requestInstall() {
    if (isStandalone()) {
      announce('Floodman is already installed on this device.', 'good');
      return;
    }
    if (!secureEnough) {
      location.assign(installPage());
      return;
    }
    if (deferredInstall) {
      deferredInstall.prompt();
      const choice = await deferredInstall.userChoice.catch(() => ({ outcome: 'dismissed' }));
      deferredInstall = null;
      refreshInstallControls();
      if (choice.outcome === 'accepted') announce('Floodman is being installed.', 'good');
      return;
    }
    location.assign(installPage());
  }

  function makeInstallButton(className = 'fm-pwa-install-button') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.dataset.fmPwaInstall = '1';
    button.innerHTML = '<span class="fm-pwa-install-icon">⇩</span><span><b>Install Floodman</b><small>Open full-screen from your Home Screen</small></span>';
    button.addEventListener('click', requestInstall);
    return button;
  }

  function refreshInstallControls() {
    const installed = isStandalone();
    document.querySelectorAll('[data-fm-pwa-install]').forEach((button) => {
      button.hidden = installed;
      if (!secureEnough) button.title = 'HTTPS is required before Floodman can be installed as an app.';
    });
  }

  function injectOfficeInstallCard() {
    if (isStandalone() || document.getElementById('fm-pwa-office-card')) return;
    const hero = document.querySelector('.mobile-hero');
    if (!hero) return;
    const card = document.createElement('section');
    card.id = 'fm-pwa-office-card';
    card.className = 'card fm-pwa-office-card';
    const status = secureEnough
      ? 'Install Floodman for a full-screen app, faster launches, update notices, and an offline recovery screen.'
      : 'The Floodman PWA is built. Add HTTPS to the Floodman subdomain, then install it from this screen.';
    card.innerHTML = `<div><span class="mobile-hero-kicker">FLOODMAN APP</span><h2>Install the field app</h2><p>${status}</p></div>`;
    const actions = document.createElement('div');
    actions.className = 'actions';
    const install = makeInstallButton('button good fm-pwa-office-install');
    install.innerHTML = secureEnough ? 'Install Floodman app' : 'View HTTPS readiness';
    actions.appendChild(install);
    const details = document.createElement('a');
    details.className = 'button secondary';
    details.href = installPage();
    details.textContent = 'App details';
    actions.appendChild(details);
    card.appendChild(actions);
    hero.insertAdjacentElement('afterend', card);
  }

  function injectHubInstallModule() {
    if (isStandalone() || document.getElementById('fm-pwa-hub-module')) return;
    const firstSection = document.querySelector('.fm-hub-module-list .fm-hub-section');
    if (!firstSection) return;
    const button = makeInstallButton('fm-hub-module fm-pwa-hub-module');
    button.id = 'fm-pwa-hub-module';
    button.dataset.label = 'install floodman app pwa home screen offline';
    button.innerHTML = '<span class="fm-hub-module-icon">⇩</span><span class="fm-hub-module-copy"><b>Install Floodman App</b><small>Full-screen Android, iPhone, iPad, and desktop app.</small></span><span class="fm-hub-module-arrow">›</span>';
    firstSection.insertBefore(button, firstSection.children[1] || null);
  }

  function injectNetworkBadge() {
    if (document.getElementById('fm-pwa-network')) return;
    const badge = document.createElement('div');
    badge.id = 'fm-pwa-network';
    badge.className = 'fm-pwa-network';
    badge.setAttribute('role', 'status');
    badge.setAttribute('aria-live', 'polite');
    document.body.appendChild(badge);

    let lastState = 'checking';
    let consecutiveFailures = 0;
    let activeProbe = null;

    const paint = (state, detail = '') => {
      badge.textContent = state === 'online' ? 'Online' : state === 'offline' ? 'Offline' : 'Checking…';
      badge.classList.toggle('is-offline', state === 'offline');
      badge.classList.toggle('is-checking', state === 'checking');
      badge.title = detail || (state === 'online'
        ? 'Floodman Office responded through this private HTTPS connection.'
        : state === 'offline'
          ? 'Floodman Office did not answer the private HTTPS health check.'
          : 'Checking the Floodman Office connection.');
      document.documentElement.classList.toggle('fm-is-offline', state === 'offline');
    };

    const probe = async ({ announceChanges = true } = {}) => {
      if (activeProbe) activeProbe.abort();
      const controller = new AbortController();
      activeProbe = controller;
      const timer = window.setTimeout(() => controller.abort(), 6500);
      if (lastState === 'checking') paint('checking');
      try {
        const response = await fetch(`/office-health/live?release=${encodeURIComponent(RELEASE)}&t=${Date.now()}`, {
          cache: 'no-store',
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
          signal: controller.signal
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.status !== 'ok') throw new Error(`health returned ${response.status}`);
        consecutiveFailures = 0;
        const previous = lastState;
        lastState = 'online';
        paint('online', `Floodman Office ${payload.version || RELEASE} is responding.`);
        if (announceChanges && previous === 'offline') announce('Floodman is back online.', 'good');
      } catch (error) {
        if (controller.signal.aborted && activeProbe !== controller) return;
        consecutiveFailures += 1;
        // One missed probe can be a page transition or service restart. Require
        // two consecutive failures before showing the full offline warning.
        if (consecutiveFailures < 2 && lastState !== 'offline') {
          lastState = 'checking';
          paint('checking', 'Floodman did not answer the first probe. Rechecking…');
          window.setTimeout(() => probe({ announceChanges }), 1600);
          return;
        }
        const previous = lastState;
        lastState = 'offline';
        paint('offline', `Floodman Office health check failed: ${error && error.message ? error.message : 'connection unavailable'}`);
        if (announceChanges && previous !== 'offline') {
          announce('Floodman Office is not responding. Live customer data will return after the server connection recovers.', 'warn');
        }
      } finally {
        window.clearTimeout(timer);
        if (activeProbe === controller) activeProbe = null;
      }
    };

    addEventListener('online', () => probe());
    addEventListener('offline', () => probe());
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') probe({ announceChanges: false });
    });
    window.setInterval(() => probe({ announceChanges: true }), 30000);
    paint('checking');
    probe({ announceChanges: false });
  }

  async function registerServiceWorker() {
    if (!secureEnough || !('serviceWorker' in navigator)) return;
    try {
      registration = await navigator.serviceWorker.register(`/floodman-sw.js?release=${encodeURIComponent(RELEASE)}`, { scope: '/', updateViaCache: 'none' });
      await registration.update().catch(() => {});
      if (registration.waiting) showUpdate(registration.waiting);
      registration.addEventListener('updatefound', () => {
        const worker = registration.installing;
        if (!worker) return;
        worker.addEventListener('statechange', () => {
          if (worker.state === 'installed' && navigator.serviceWorker.controller) showUpdate(worker);
        });
      });
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        if (reloadingForUpdate) return;
        reloadingForUpdate = true;
        location.reload();
      });
    } catch (error) {
      console.warn('[Floodman PWA] Service worker registration failed:', error);
    }
  }

  function showUpdate(worker) {
    announce('A new Floodman app version is ready.', 'info', {
      label: 'Update now',
      run: () => worker.postMessage({ type: 'SKIP_WAITING' })
    });
  }

  function observeShell() {
    const apply = () => {
      injectOfficeInstallCard();
      injectHubInstallModule();
      refreshInstallControls();
    };
    apply();
    const observer = new MutationObserver(apply);
    observer.observe(document.documentElement, { childList: true, subtree: true });
    window.setTimeout(() => observer.disconnect(), 120000);
  }

  addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredInstall = event;
    refreshInstallControls();
    if (!isStandalone()) announce('Floodman can now be installed on this device.', 'good', { label: 'Install', run: requestInstall });
  });

  addEventListener('appinstalled', () => {
    deferredInstall = null;
    document.documentElement.classList.add('fm-pwa-standalone');
    announce('Floodman was installed successfully.', 'good');
    refreshInstallControls();
  });

  window.FloodmanPWA = {
    release: RELEASE,
    secureEnough,
    isIOS,
    isAndroid,
    isStandalone,
    install: requestInstall,
    registration: () => registration
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { observeShell(); injectNetworkBadge(); registerServiceWorker(); }, { once: true });
  } else {
    observeShell(); injectNetworkBadge(); registerServiceWorker();
  }
})();
