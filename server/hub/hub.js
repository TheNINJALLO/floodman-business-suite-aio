(() => {
  'use strict';

  if (window.__FLOODMAN_HUB_INSTALLED__) return;
  window.__FLOODMAN_HUB_INSTALLED__ = true;

  const config = window.FLOODMAN_HUB_CONFIG || {};
  const $ = (selector, parent = document) => parent.querySelector(selector);
  const create = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  };
  const normalize = (value, fallback) => String(value || fallback || '').replace(/\/+$/, '');
  const office = normalize(config.officeUrl, window.location.origin);
  const hubOrigin = window.location.origin;
  const brandMark = '/floodman-brand/floodman-mark.svg';
  const brandWordmark = '/floodman-brand/floodman-wordmark.svg';
  const creator = 'Josh Aldrich';

  const mobileQuery = window.matchMedia('(max-width: 1100px)');
  const preferenceKey = 'floodmanWorkspaceMode';
  const urlParams = new URLSearchParams(window.location.search);
  const userAgent = String(navigator.userAgent || '');
  const isIPadOS = navigator.platform === 'MacIntel' && Number(navigator.maxTouchPoints || 0) > 1;
  const isPhoneOrTablet = () => {
    const clientHint = navigator.userAgentData && navigator.userAgentData.mobile === true;
    return Boolean(clientHint || isIPadOS || /Android|iPhone|iPad|iPod|Mobile|Tablet|Silk|Kindle/i.test(userAgent));
  };
  const readPreference = () => {
    try {
      const value = localStorage.getItem(preferenceKey);
      if (value === 'desktop' || value === 'mobile') return value;
      if (localStorage.getItem('floodmanDesktopMode') === '1') return 'desktop';
    } catch (_) {}
    return 'auto';
  };
  const writePreference = (value) => {
    try {
      if (value === 'desktop' || value === 'mobile') localStorage.setItem(preferenceKey, value);
      else localStorage.removeItem(preferenceKey);
      if (value === 'desktop') localStorage.setItem('floodmanDesktopMode', '1');
      else localStorage.removeItem('floodmanDesktopMode');
    } catch (_) {}
  };
  if (urlParams.get('desktop') === '1') writePreference('desktop');
  if (urlParams.get('mobile') === '1') writePreference('mobile');
  if (urlParams.get('workspace') === 'auto') writePreference('auto');
  const desktopMode = () => readPreference() === 'desktop';
  const mobileMode = () => readPreference() === 'mobile';
  const isMobileWorkspace = () => mobileMode() || (!desktopMode() && isPhoneOrTablet());
  const shouldUseMobileHome = () => {
    if (desktopMode()) return false;
    const route = String(window.location.hash || '').replace(/^#\/?/, '').split('?')[0].replace(/^\/+|\/+$/g, '');
    if (route && route !== 'pages' && route !== 'pages/dashboard') return false;
    if (mobileMode()) return true;
    return isPhoneOrTablet();
  };
  const routeMobileHome = () => {
    if (!shouldUseMobileHome()) return false;
    window.location.replace(`${office}/office/mobile?mobile=1`);
    return true;
  };

  const modules = [
    {
      section: 'Floodman Operations',
      items: [
        { label: 'Desktop Operations', icon: '▥', url: `${office}/office/desktop?desktop=1`, description: 'Desktop command center with the full sidebar, dense tables, and multi-column workflows.', desktop: true },
        { label: 'Mobile Operations', icon: '▣', url: `${office}/office/mobile?mobile=1`, description: 'Dedicated phone and tablet workspace with large touch controls.', mobile: true },
        { label: 'Install Floodman App', icon: '⇩', url: `${hubOrigin}/install-app`, description: 'Install the Android, iPhone, iPad, Windows, or macOS web app.' },
        { label: 'Full Floodman ERP', icon: '⌂', url: `${hubOrigin}/full-erp`, description: 'Desktop ERP for CRM, staff, accounting, reports, settings, and administration.', native: true, desktop: true },
        { label: 'Floodman RoomFlow Estimator', icon: '▱', url: `${office}/office/roomflow`, description: 'Customer-linked property layouts, measurements, scopes, and estimates inside Floodman.' },
        { label: 'Customer Files', icon: '◎', url: `${office}/office/contacts`, description: 'Contacts, service properties, signed documents, estimates, invoices, notes, and history.' },
        { label: 'Properties & Jobs', icon: '⌑', url: `${office}/office/properties`, description: 'Service properties, jobs, and customer relationships.' },
        { label: 'Documents & Signatures', icon: '✎', url: `${office}/office/signing`, description: 'Work Authorizations, Change Orders, Completion of Service, and client-file attachments.' },
        { label: 'Receivables', icon: '$', url: `${office}/office/receivables`, description: 'Due-now invoices, reminders, promises, disputes, and aging.' },
        { label: 'Customer Messages', icon: '✉', url: `${office}/office/messages`, description: 'Two-way SMS, AI triage, and staff handoff.' },
        { label: 'Competitor Intelligence', icon: '⌁', url: normalize(config.competitorUrl, `${office}/office/intelligence`), description: 'Scheduled competitor scans, evidence, and battle cards.' },
        { label: 'Import Customers', icon: '⇩', url: `${office}/office/imports`, description: 'Import a customer CSV or a complete historical business archive.' },
        { label: 'Members & Access', icon: '♙', url: `${office}/office/members`, description: 'Module permissions and staff onboarding.' },
        { label: 'Connections & Sync', icon: '⛓', url: `${office}/office/platform`, description: 'Floodman ERP context, RoomFlow mappings, and provider status.' }
      ]
    },
    {
      section: 'Floodman ERP',
      items: [
        { label: 'Operations Dashboard', icon: '◫', url: `${hubOrigin}/index.html?desktop=1#/pages/dashboard`, native: true, description: 'Company dashboard and organizational scorecards.' },
        { label: 'Contacts & CRM', icon: '◎', url: `${hubOrigin}/index.html?desktop=1#/pages/contacts`, native: true, description: 'Contacts, clients, CRM records, and relationships.' },
        { label: 'Employees & Invitations', icon: '♟', url: `${hubOrigin}/index.html?desktop=1#/pages/employees`, native: true, description: 'Add staff, invite members, assign roles, teams, and departments.' },
        { label: 'Time & Timesheets', icon: '◷', url: `${hubOrigin}/index.html?desktop=1#/pages/employees/timesheets`, native: true, description: 'Timer, timesheets, approvals, activity, and attendance.' },
        { label: 'Tasks & Work', icon: '☑', url: `${hubOrigin}/index.html?desktop=1#/pages/tasks`, native: true, description: 'Tasks, assignments, projects, and work tracking.' },
        { label: 'Invoices', icon: '▤', url: `${hubOrigin}/index.html?desktop=1#/pages/accounting/invoices`, native: true, description: 'Estimates, invoices, line items, and document status.' },
        { label: 'Payments', icon: '¤', url: `${hubOrigin}/index.html?desktop=1#/pages/accounting/payments`, native: true, description: 'Payment ledger, partial payments, balances, and reports.' },
        { label: 'Reports', icon: '▥', url: `${hubOrigin}/index.html?desktop=1#/pages/reports`, native: true, description: 'Organization, time, activity, accounting, and project reporting.' },
        { label: 'System Settings', icon: '⚙', url: `${hubOrigin}/index.html?desktop=1#/pages/settings`, native: true, description: 'Roles, permissions, organization settings, and integrations.' }
      ]
    },
    {
      section: 'Specialized Applications',
      items: [
        { label: 'Floodman Signing', icon: '✓', url: normalize(config.documensoUrl, 'http://localhost:9001'), description: 'Document templates, recipients, fields, and signature history.', external: true },
        { label: 'Test Email Inbox', icon: '✉', url: normalize(config.mailpitUrl, 'http://localhost:9002'), description: 'Captured invitations, invoices, and signing emails.', external: true },
        { label: 'Engineering Lab', icon: '⚙', url: normalize(config.engineeringUrl, 'http://localhost:9003/lab'), description: 'Provider simulation, test workflow, and diagnostics.', external: true },
        { label: 'API Explorer', icon: '{ }', url: normalize(config.apiUrl, 'http://localhost:9004/docs'), description: 'Floodman API documentation and test endpoints.', external: true }
      ]
    }
  ];

  function replaceBrandText(value) {
    return String(value == null ? '' : value)
      .replace(/Ever®?\s*Gauzy™?/gi, 'Floodman')
      .replace(/Ever\s+Technologies(?:\s+LTD)?/gi, 'Floodman')
      .replace(/Ever\s+Co\.?\s*(?:LTD)?/gi, 'Floodman')
      .replace(/Gauzy/gi, 'Floodman')
      .replace(/\bEver\b/gi, 'Floodman')
      .replace(/Floodman\s+Floodman/gi, 'Floodman');
  }

  function isBrandImage(image) {
    const source = `${image.getAttribute('src') || ''} ${image.getAttribute('alt') || ''} ${image.getAttribute('title') || ''}`;
    return /gauzy|ever[-_ ]?(?:co|logo)|logo[_-]?gauzy/i.test(source);
  }

  function sanitizeNode(root) {
    if (!root) return;
    const skip = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE']);
    if (root.nodeType === Node.TEXT_NODE) {
      const parent = root.parentElement;
      if (!parent || skip.has(parent.tagName)) return;
      const changed = replaceBrandText(root.nodeValue || '');
      if (changed !== root.nodeValue) root.nodeValue = changed;
      return;
    }
    if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE && root.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) return;

    const elements = [];
    if (root.nodeType === Node.ELEMENT_NODE) elements.push(root);
    if (root.querySelectorAll) elements.push(...root.querySelectorAll('*'));
    for (const element of elements) {
      if (skip.has(element.tagName)) continue;
      for (const attribute of ['title', 'aria-label', 'placeholder', 'alt', 'data-title']) {
        if (!element.hasAttribute(attribute)) continue;
        const original = element.getAttribute(attribute) || '';
        const changed = replaceBrandText(original);
        if (changed !== original) element.setAttribute(attribute, changed);
      }
      if (element instanceof HTMLImageElement && isBrandImage(element)) {
        element.src = brandWordmark;
        element.alt = 'Floodman Operations';
        element.classList.add('fm-replaced-brand-logo');
      }
      if (element instanceof HTMLAnchorElement && /gauzy\.co|ever\.co/i.test(`${element.href || ''}`)) {
        element.href = 'https://floodman.com';
        element.rel = 'noreferrer';
      }
    }

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        return parent && !skip.has(parent.tagName) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    let node;
    while ((node = walker.nextNode())) {
      const original = node.nodeValue || '';
      const changed = replaceBrandText(original);
      if (changed !== original) node.nodeValue = changed;
    }
  }

  function applyFloodmanBranding() {
    document.documentElement.classList.add('floodman-branded');
    document.title = replaceBrandText(document.title || 'Floodman Operations') || 'Floodman Operations';
    let viewport = document.querySelector('meta[name="viewport"]');
    if (!viewport) {
      viewport = document.createElement('meta');
      viewport.name = 'viewport';
      document.head.appendChild(viewport);
    }
    viewport.content = 'width=device-width,initial-scale=1,viewport-fit=cover';

    let icon = document.querySelector('link[rel~="icon"]');
    if (!icon) {
      icon = document.createElement('link');
      icon.rel = 'icon';
      document.head.appendChild(icon);
    }
    icon.type = 'image/svg+xml';
    icon.href = brandMark;

    const metaValues = {
      'application-name': 'Floodman Operations',
      author: creator,
      generator: 'Floodman Operations'
    };
    for (const [name, content] of Object.entries(metaValues)) {
      let meta = document.querySelector(`meta[name="${name}"]`);
      if (!meta) {
        meta = document.createElement('meta');
        meta.name = name;
        document.head.appendChild(meta);
      }
      meta.content = content;
    }
    sanitizeNode(document.body);
  }

  let brandingTimer = null;
  function scheduleBranding() {
    if (brandingTimer) return;
    brandingTimer = window.setTimeout(() => {
      brandingTimer = null;
      applyFloodmanBranding();
    }, 80);
  }

  function buildShell() {
    applyFloodmanBranding();
    const brandingObserver = new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes || []) sanitizeNode(node);
      }
      scheduleBranding();
    });
    brandingObserver.observe(document.documentElement, { childList: true, subtree: true, characterData: true });

    const root = create('div', 'fm-hub-root');
    root.id = 'fm-hub-root';

    const trigger = create('button', 'fm-hub-trigger');
    trigger.type = 'button';
    trigger.setAttribute('aria-label', 'Open Floodman Operations');
    trigger.innerHTML = '<img class="fm-hub-trigger-logo" src="/floodman-brand/floodman-mark.svg" alt=""><span class="fm-hub-trigger-text">Floodman</span>';

    const drawer = create('aside', 'fm-hub-drawer');
    drawer.setAttribute('aria-hidden', 'true');
    drawer.innerHTML = `
      <header class="fm-hub-drawer-header">
        <div>
          <img class="fm-hub-drawer-logo" src="${brandWordmark}" alt="Floodman Operations">
          <div class="fm-hub-eyebrow">ONE OPERATIONS HUB</div>
          <h2>${escapeHtml(config.title || 'Floodman Operations')}</h2>
          <p>Your ERP, RoomFlow, customer files, signing, billing, messaging, and intelligence tools in one workspace.</p>
        </div>
        <button type="button" class="fm-hub-icon-button" data-hub-close aria-label="Close hub">×</button>
      </header>
      <div class="fm-hub-status-row">
        <span class="fm-hub-status-dot"></span>
        <span>RoomFlow → Floodman workflow</span>
        <a href="${escapeAttribute(config.syncStatusUrl || `${office}/office/platform`)}" target="_blank" rel="noreferrer">check sync</a>
      </div>
      <div class="fm-hub-search-wrap"><input class="fm-hub-search" type="search" placeholder="Find a Floodman tool…" aria-label="Find a Floodman tool"></div>
      <div class="fm-hub-module-list"></div>
      <footer class="fm-hub-drawer-footer">
        <div><b>Floodman ERP and Operations</b><br>Created by ${escapeHtml(creator)} · <a href="/floodman-third-party-notices.html" target="_blank" rel="noreferrer">Third-party notices</a></div>
        <span>${escapeHtml(config.release || '')}</span>
      </footer>`;

    const backdrop = create('div', 'fm-hub-backdrop');
    backdrop.setAttribute('aria-hidden', 'true');

    const overlay = create('section', 'fm-hub-overlay');
    overlay.setAttribute('aria-hidden', 'true');
    overlay.innerHTML = `
      <div class="fm-hub-overlay-bar">
        <div class="fm-hub-overlay-title-wrap"><img class="fm-hub-overlay-mark" src="${brandMark}" alt=""><div><div class="fm-hub-overlay-kicker">Floodman module</div><strong class="fm-hub-overlay-title">Module</strong></div></div>
        <div class="fm-hub-overlay-actions"><a class="fm-hub-overlay-link" href="#" target="_blank" rel="noreferrer">Open full screen ↗</a><button class="fm-hub-overlay-close" type="button">Back to Floodman</button></div>
      </div>
      <div class="fm-hub-frame-wrap"><div class="fm-hub-frame-loading"><div><span class="fm-hub-spinner"></span><b>Loading module…</b><small>This should take only a moment.</small></div></div><iframe class="fm-hub-frame" title="Floodman module" referrerpolicy="same-origin"></iframe></div>`;

    const mobileDock = create('nav', 'fm-hub-mobile-dock');
    mobileDock.setAttribute('aria-label', 'Floodman mobile navigation');
    const mobileItems = [
      { label: 'Home', icon: '⌂', url: `${office}/office/mobile?mobile=1`, description: 'Floodman phone and tablet command center.', mobile: true },
      { label: 'Customers', icon: '◎', url: `${office}/office/contacts`, description: 'Customer files and signed documents.' },
      { label: 'Jobs', icon: '⌑', url: `${office}/office/properties`, description: 'Properties and jobs.' },
      { label: 'Billing', icon: '$', url: `${office}/office/invoices`, description: 'Invoices, payments, and balances.' }
    ];
    for (const item of mobileItems) {
      const button = create('button', 'fm-hub-mobile-item');
      button.type = 'button';
      button.innerHTML = `<span class="fm-hub-mobile-icon">${escapeHtml(item.icon)}</span><span>${escapeHtml(item.label)}</span>`;
      button.addEventListener('click', () => openModule(item));
      mobileDock.appendChild(button);
    }
    const moreButton = create('button', 'fm-hub-mobile-item');
    moreButton.type = 'button';
    moreButton.setAttribute('aria-label', 'Open all Floodman tools');
    moreButton.innerHTML = '<span class="fm-hub-mobile-icon">☰</span><span>More</span>';
    moreButton.addEventListener('click', openDrawer);
    mobileDock.appendChild(moreButton);

    root.append(trigger, backdrop, drawer, overlay, mobileDock);
    document.body.appendChild(root);

    const list = $('.fm-hub-module-list', drawer);
    for (const group of modules) {
      const section = create('section', 'fm-hub-section');
      section.dataset.section = group.section.toLowerCase();
      section.appendChild(create('h3', 'fm-hub-section-title', group.section));
      for (const item of group.items) {
        const button = create('button', 'fm-hub-module');
        button.type = 'button';
        button.dataset.label = `${item.label} ${item.description}`.toLowerCase();
        button.innerHTML = `<span class="fm-hub-module-icon">${escapeHtml(item.icon)}</span><span class="fm-hub-module-copy"><b>${escapeHtml(item.label)}</b><small>${escapeHtml(item.description)}</small></span><span class="fm-hub-module-arrow">›</span>`;
        button.addEventListener('click', () => openModule(item));
        section.appendChild(button);
      }
      list.appendChild(section);
    }

    const search = $('.fm-hub-search', drawer);
    search.addEventListener('input', () => {
      const query = search.value.trim().toLowerCase();
      drawer.querySelectorAll('.fm-hub-module').forEach((node) => { node.hidden = Boolean(query) && !node.dataset.label.includes(query); });
      drawer.querySelectorAll('.fm-hub-section').forEach((section) => { section.hidden = !Array.from(section.querySelectorAll('.fm-hub-module')).some((node) => !node.hidden); });
    });

    const closeDrawer = () => {
      drawer.classList.remove('is-open'); backdrop.classList.remove('is-open');
      drawer.setAttribute('aria-hidden', 'true'); backdrop.setAttribute('aria-hidden', 'true'); trigger.setAttribute('aria-expanded', 'false');
    };
    const openDrawer = () => {
      drawer.classList.add('is-open'); backdrop.classList.add('is-open');
      drawer.setAttribute('aria-hidden', 'false'); backdrop.setAttribute('aria-hidden', 'false'); trigger.setAttribute('aria-expanded', 'true');
      window.setTimeout(() => search.focus(), 80);
    };

    trigger.addEventListener('click', () => drawer.classList.contains('is-open') ? closeDrawer() : openDrawer());
    $('[data-hub-close]', drawer).addEventListener('click', closeDrawer);
    backdrop.addEventListener('click', closeDrawer);
    $('.fm-hub-overlay-close', overlay).addEventListener('click', closeModule);
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      if (overlay.classList.contains('is-open')) closeModule(); else closeDrawer();
    });

    function openModule(item) {
      closeDrawer();
      if (item.desktop) writePreference('desktop');
      if (item.mobile) writePreference('mobile');
      if (item.native) { window.location.assign(item.url); return; }
      let target;
      try { target = new URL(item.url, window.location.href); } catch { target = null; }
      if (isMobileWorkspace() && target && target.origin === window.location.origin) { window.location.assign(target.href); return; }
      if (item.external || !target || target.origin !== window.location.origin) { window.open(item.url, '_blank', 'noopener,noreferrer'); return; }
      const frame = $('.fm-hub-frame', overlay);
      const loading = $('.fm-hub-frame-loading', overlay);
      $('.fm-hub-overlay-title', overlay).textContent = item.label;
      const openLink = $('.fm-hub-overlay-link', overlay); openLink.href = item.url;
      loading.classList.remove('is-hidden', 'is-error');
      loading.innerHTML = '<div><span class="fm-hub-spinner"></span><b>Loading module…</b><small>This should take only a moment.</small></div>';
      frame.title = item.label; overlay.classList.add('is-open'); overlay.setAttribute('aria-hidden', 'false'); document.documentElement.classList.add('fm-hub-module-open');
      let settled = false;
      const timeout = window.setTimeout(() => {
        if (settled) return;
        loading.classList.add('is-error');
        loading.innerHTML = `<div><b>${escapeHtml(item.label)} is taking longer than expected.</b><small>Open it full screen or check the service status.</small><a href="${escapeAttribute(item.url)}" target="_blank" rel="noreferrer">Open full screen ↗</a></div>`;
      }, 10000);
      frame.onload = () => { settled = true; window.clearTimeout(timeout); loading.classList.add('is-hidden'); };
      frame.src = item.url;
    }

    function closeModule() {
      const frame = $('.fm-hub-frame', overlay); frame.onload = null;
      overlay.classList.remove('is-open'); overlay.setAttribute('aria-hidden', 'true'); document.documentElement.classList.remove('fm-hub-module-open');
      window.setTimeout(() => { frame.src = 'about:blank'; }, 180);
    }
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }
  function escapeAttribute(value) { return escapeHtml(value).replace(/`/g, '&#096;'); }

  if (routeMobileHome()) return;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', buildShell, { once: true });
  else buildShell();
})();
