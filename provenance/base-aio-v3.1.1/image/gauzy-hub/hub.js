(() => {
  'use strict';

  if (window.__FLOODMAN_GAUZY_HUB_INSTALLED__) return;
  window.__FLOODMAN_GAUZY_HUB_INSTALLED__ = true;

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

  const modules = [
    {
      section: 'Floodman Operations',
      items: [
        { label: 'Command Center', icon: '⌂', url: `${office}/office`, description: 'Company dashboard, setup, and operating overview.' },
        { label: 'RoomFlow Estimator', icon: '▱', url: normalize(config.roomflowUrl, 'https://theninjallo.github.io/roomflow/'), description: 'Property layouts, measurements, scopes, and field estimates.', external: true },
        { label: 'Properties & Jobs', icon: '⌑', url: `${office}/office/properties`, description: 'Service properties, jobs, and customer relationships.' },
        { label: 'Documents & Signatures', icon: '✎', url: `${office}/office/signing`, description: 'Work Authorizations, Change Orders, and Completion of Service.' },
        { label: 'Receivables', icon: '$', url: `${office}/office/receivables`, description: 'Due-now invoices, reminders, promises, disputes, and aging.' },
        { label: 'Customer Messages', icon: '✉', url: `${office}/office/messages`, description: 'Two-way SMS, AI triage, and staff handoff.' },
        { label: 'Competitor Intelligence', icon: '⌁', url: normalize(config.competitorUrl, `${office}/office/intelligence`), description: 'Scheduled competitor scans, evidence, and battle cards.' },
        { label: 'Import Center', icon: '⇩', url: `${office}/office/imports`, description: 'Validate and import contacts, estimates, invoices, payments, and files.' },
        { label: 'Members & Access', icon: '♙', url: `${office}/office/members`, description: 'Module permissions and staff onboarding.' },
        { label: 'Connections & Sync', icon: '⛓', url: `${office}/office/gauzy`, description: 'ERP context, RoomFlow mappings, and provider status.' }
      ]
    },
    {
      section: 'Floodman ERP',
      items: [
        { label: 'Operations Dashboard', icon: '◫', url: `${hubOrigin}/#/pages/dashboard`, native: true, description: 'Company dashboard and organizational scorecards.' },
        { label: 'Contacts & CRM', icon: '◎', url: `${hubOrigin}/#/pages/contacts`, native: true, description: 'Contacts, clients, CRM records, and relationships.' },
        { label: 'Employees & Invitations', icon: '♟', url: `${hubOrigin}/#/pages/employees`, native: true, description: 'Add staff, invite members, assign roles, teams, and departments.' },
        { label: 'Time & Timesheets', icon: '◷', url: `${hubOrigin}/#/pages/employees/timesheets`, native: true, description: 'Timer, timesheets, approvals, activity, and attendance.' },
        { label: 'Tasks & Work', icon: '☑', url: `${hubOrigin}/#/pages/tasks`, native: true, description: 'Tasks, assignments, projects, and work tracking.' },
        { label: 'Invoices', icon: '▤', url: `${hubOrigin}/#/pages/accounting/invoices`, native: true, description: 'Estimates, invoices, line items, and document status.' },
        { label: 'Payments', icon: '¤', url: `${hubOrigin}/#/pages/accounting/payments`, native: true, description: 'Payment ledger, partial payments, balances, and reports.' },
        { label: 'Reports', icon: '▥', url: `${hubOrigin}/#/pages/reports`, native: true, description: 'Organization, time, activity, accounting, and project reporting.' },
        { label: 'System Settings', icon: '⚙', url: `${hubOrigin}/#/pages/settings`, native: true, description: 'Roles, permissions, organization settings, and integrations.' }
      ]
    },
    {
      section: 'Specialized Applications',
      items: [
        { label: 'Document Signing', icon: '✓', url: normalize(config.documensoUrl, 'http://localhost:9001'), description: 'Full document templates, recipients, fields, and signature history.', external: true },
        { label: 'Local Email Inbox', icon: '✉', url: normalize(config.mailpitUrl, 'http://localhost:9002'), description: 'Captured invitations, invoices, and signing emails.', external: true },
        { label: 'Engineering Lab', icon: '⚙', url: normalize(config.engineeringUrl, 'http://localhost:9003/lab'), description: 'Provider simulation, test workflow, and diagnostics.', external: true },
        { label: 'API Explorer', icon: '{ }', url: normalize(config.apiUrl, 'http://localhost:9004/docs'), description: 'Floodman API documentation and test endpoints.', external: true }
      ]
    }
  ];

  function applyFloodmanBranding() {
    document.documentElement.classList.add('floodman-branded');
    const desiredTitle = 'Floodman Operations';
    if (!document.title || /gauzy|ever/i.test(document.title)) document.title = desiredTitle;

    let icon = document.querySelector('link[rel~="icon"]');
    if (!icon) {
      icon = document.createElement('link');
      icon.rel = 'icon';
      document.head.appendChild(icon);
    }
    icon.type = 'image/svg+xml';
    icon.href = brandMark;

    let appName = document.querySelector('meta[name="application-name"]');
    if (!appName) {
      appName = document.createElement('meta');
      appName.name = 'application-name';
      document.head.appendChild(appName);
    }
    appName.content = desiredTitle;

    for (const image of document.querySelectorAll('img')) {
      const source = `${image.getAttribute('src') || ''} ${image.getAttribute('alt') || ''}`;
      if (/logo[_-]?gauzy|gauzy[_-]?logo|ever\s*gauzy/i.test(source)) {
        image.src = brandWordmark;
        image.alt = desiredTitle;
        image.classList.add('fm-replaced-brand-logo');
      }
    }

    const replacements = new Map([
      ['Gauzy', desiredTitle],
      ['Ever Gauzy', desiredTitle],
      ['Ever® Gauzy™', desiredTitle],
      ['Gauzy Platform', desiredTitle],
      ['Welcome to Gauzy', 'Welcome to Floodman Operations'],
      ['About Gauzy', 'About Floodman Operations']
    ]);
    for (const element of document.querySelectorAll('h1,h2,h3,h4,p,span,a,button,label,small,strong')) {
      if (element.children.length) continue;
      const value = (element.textContent || '').trim();
      if (!value || value.length > 90) continue;
      if (replacements.has(value)) element.textContent = replacements.get(value);
    }
  }

  let brandingTimer = null;
  function scheduleBranding() {
    if (brandingTimer) return;
    brandingTimer = window.setTimeout(() => {
      brandingTimer = null;
      applyFloodmanBranding();
    }, 120);
  }

  function buildShell() {
    applyFloodmanBranding();
    const brandingObserver = new MutationObserver(scheduleBranding);
    brandingObserver.observe(document.documentElement, { childList: true, subtree: true });

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
          <p>Your ERP, RoomFlow, signing, billing, messaging, and intelligence tools in one workspace.</p>
        </div>
        <button type="button" class="fm-hub-icon-button" data-hub-close aria-label="Close hub">×</button>
      </header>
      <div class="fm-hub-status-row">
        <span class="fm-hub-status-dot"></span>
        <span>RoomFlow → Floodman ERP workflow</span>
        <a href="${escapeAttribute(config.syncStatusUrl || `${office}/office/gauzy`)}" target="_blank" rel="noreferrer">check sync</a>
      </div>
      <div class="fm-hub-search-wrap">
        <input class="fm-hub-search" type="search" placeholder="Find a Floodman tool…" aria-label="Find a Floodman tool">
      </div>
      <div class="fm-hub-module-list"></div>
      <footer class="fm-hub-drawer-footer">
        <div><b>The full Floodman ERP remains available underneath.</b><br>Use the normal sidebar for employees, time, projects, tasks, CRM, invoices, inventory, and reports.</div>
        <span>${escapeHtml(config.release || '')}</span>
      </footer>`;

    const backdrop = create('div', 'fm-hub-backdrop');
    backdrop.setAttribute('aria-hidden', 'true');

    const overlay = create('section', 'fm-hub-overlay');
    overlay.setAttribute('aria-hidden', 'true');
    overlay.innerHTML = `
      <div class="fm-hub-overlay-bar">
        <div class="fm-hub-overlay-title-wrap">
          <img class="fm-hub-overlay-mark" src="${brandMark}" alt="">
          <div><div class="fm-hub-overlay-kicker">Floodman module</div><strong class="fm-hub-overlay-title">Module</strong></div>
        </div>
        <div class="fm-hub-overlay-actions">
          <a class="fm-hub-overlay-link" href="#" target="_blank" rel="noreferrer">Open full screen ↗</a>
          <button class="fm-hub-overlay-close" type="button">Back to Floodman</button>
        </div>
      </div>
      <div class="fm-hub-frame-wrap">
        <div class="fm-hub-frame-loading"><div><span class="fm-hub-spinner"></span><b>Loading module…</b><small>This should take only a moment.</small></div></div>
        <iframe class="fm-hub-frame" title="Floodman module" referrerpolicy="same-origin"></iframe>
      </div>`;

    root.append(trigger, backdrop, drawer, overlay);
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
        button.innerHTML = `
          <span class="fm-hub-module-icon">${escapeHtml(item.icon)}</span>
          <span class="fm-hub-module-copy"><b>${escapeHtml(item.label)}</b><small>${escapeHtml(item.description)}</small></span>
          <span class="fm-hub-module-arrow">›</span>`;
        button.addEventListener('click', () => openModule(item));
        section.appendChild(button);
      }
      list.appendChild(section);
    }

    const search = $('.fm-hub-search', drawer);
    search.addEventListener('input', () => {
      const query = search.value.trim().toLowerCase();
      drawer.querySelectorAll('.fm-hub-module').forEach((node) => {
        node.hidden = Boolean(query) && !node.dataset.label.includes(query);
      });
      drawer.querySelectorAll('.fm-hub-section').forEach((section) => {
        const visible = Array.from(section.querySelectorAll('.fm-hub-module')).some((node) => !node.hidden);
        section.hidden = !visible;
      });
    });

    const closeDrawer = () => {
      drawer.classList.remove('is-open');
      backdrop.classList.remove('is-open');
      drawer.setAttribute('aria-hidden', 'true');
      backdrop.setAttribute('aria-hidden', 'true');
      trigger.setAttribute('aria-expanded', 'false');
    };
    const openDrawer = () => {
      drawer.classList.add('is-open');
      backdrop.classList.add('is-open');
      drawer.setAttribute('aria-hidden', 'false');
      backdrop.setAttribute('aria-hidden', 'false');
      trigger.setAttribute('aria-expanded', 'true');
      window.setTimeout(() => search.focus(), 80);
    };

    trigger.addEventListener('click', () => drawer.classList.contains('is-open') ? closeDrawer() : openDrawer());
    $('[data-hub-close]', drawer).addEventListener('click', closeDrawer);
    backdrop.addEventListener('click', closeDrawer);
    $('.fm-hub-overlay-close', overlay).addEventListener('click', closeModule);

    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      if (overlay.classList.contains('is-open')) closeModule();
      else closeDrawer();
    });

    function openModule(item) {
      closeDrawer();
      if (item.native) {
        window.location.assign(item.url);
        return;
      }
      let target;
      try { target = new URL(item.url, window.location.href); } catch { target = null; }
      if (item.external || !target || target.origin !== window.location.origin) {
        window.open(item.url, '_blank', 'noopener,noreferrer');
        return;
      }

      const frame = $('.fm-hub-frame', overlay);
      const loading = $('.fm-hub-frame-loading', overlay);
      $('.fm-hub-overlay-title', overlay).textContent = item.label;
      const openLink = $('.fm-hub-overlay-link', overlay);
      openLink.href = item.url;
      loading.classList.remove('is-hidden', 'is-error');
      loading.innerHTML = '<div><span class="fm-hub-spinner"></span><b>Loading module…</b><small>This should take only a moment.</small></div>';
      frame.title = item.label;
      overlay.classList.add('is-open');
      overlay.setAttribute('aria-hidden', 'false');
      document.documentElement.classList.add('fm-hub-module-open');

      let settled = false;
      const timeout = window.setTimeout(() => {
        if (settled) return;
        loading.classList.add('is-error');
        loading.innerHTML = `<div><b>${escapeHtml(item.label)} is taking longer than expected.</b><small>Open it full screen or check the service status.</small><a href="${escapeAttribute(item.url)}" target="_blank" rel="noreferrer">Open full screen ↗</a></div>`;
      }, 10000);
      frame.onload = () => {
        settled = true;
        window.clearTimeout(timeout);
        loading.classList.add('is-hidden');
      };
      frame.src = item.url;
    }

    function closeModule() {
      const frame = $('.fm-hub-frame', overlay);
      frame.onload = null;
      overlay.classList.remove('is-open');
      overlay.setAttribute('aria-hidden', 'true');
      document.documentElement.classList.remove('fm-hub-module-open');
      window.setTimeout(() => { frame.src = 'about:blank'; }, 180);
    }
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function escapeAttribute(value) {
    return escapeHtml(value).replace(/`/g, '&#096;');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', buildShell, { once: true });
  } else {
    buildShell();
  }
})();
