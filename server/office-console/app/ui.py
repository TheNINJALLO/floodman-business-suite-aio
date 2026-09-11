from __future__ import annotations

import html
import json
from typing import Any, Iterable

from .auth import has_permission


PWA_HEAD = """<meta name='mobile-web-app-capable' content='yes'><meta name='apple-mobile-web-app-capable' content='yes'><meta name='apple-mobile-web-app-status-bar-style' content='black-translucent'><meta name='apple-mobile-web-app-title' content='Floodman'><link rel='manifest' href='/manifest.webmanifest'><link rel='apple-touch-icon' href='/floodman-pwa-icons/apple-touch-icon-180.png'><link rel='icon' type='image/png' sizes='192x192' href='/floodman-pwa-icons/icon-192.png'><link rel='stylesheet' href='/floodman-pwa.css'>"""
PWA_BODY = "<script defer src='/floodman-pwa.js?release=4.7.3'></script>"
WORKSPACE_CSS = "<link rel='stylesheet' href='/floodman-workspace.css?release=4.7.3&portal-tools=1'>"

WORKSPACE_HEAD = """<script>(function(){try{localStorage.removeItem('floodmanWorkspaceMode');localStorage.removeItem('floodmanDesktopMode')}catch(e){}window.floodmanDeviceMode=function(){var ua=String(navigator.userAgent||''),w=window.innerWidth||document.documentElement.clientWidth,ipad=navigator.platform==='MacIntel'&&Number(navigator.maxTouchPoints||0)>1,handheld=Boolean((navigator.userAgentData&&navigator.userAgentData.mobile===true)||ipad||/Android|iPhone|iPad|iPod|Mobile|Tablet|Silk|Kindle/i.test(ua));return handheld||w<=720||(matchMedia('(pointer:coarse)').matches&&w<=1100)?'mobile':'desktop'};function apply(){var mode=window.floodmanDeviceMode();if(document.documentElement.dataset.workspace!==mode){document.documentElement.dataset.workspace=mode;window.dispatchEvent(new Event('floodman:layoutchange'))}}apply();window.addEventListener('resize',apply);var path=location.pathname,mode=window.floodmanDeviceMode();if((path==='/office'||path==='/office/desktop')&&mode==='mobile')location.replace('/office/mobile');else if(path==='/office/mobile'&&mode==='desktop')location.replace('/office');})();</script>"""


PRIMARY_NAV = [
    ("/office", "Dashboard", "dashboard", "dashboard.view"),
    ("/office/calls", "Calls", "calls", "call_intakes.view"),
    ("/office/contacts", "Customers", "contacts", "contacts.view"),
    ("/office/roomflow", "RoomFlow", "roomflow", "estimates.view"),
    ("/office/photo-portal", "Photo Portal", "photo-portal", "properties.view"),
    ("/office/estimates", "Estimates", "estimates", "estimates.view"),
    ("/office/invoices", "Billing", "invoices", "invoices.view"),
]


NAV_GROUPS = [
    ("Workspaces", [
        ("/office/apps", "All Applications", "apps", "apps.view"),
        ("/install-app", "Install App", "pwa", "dashboard.view"),
        ("/office/platform", "Floodman ERP", "platform", "apps.view"),
        ("/office/signing", "Signing Suite", "signing", "documents.view"),
    ]),
    ("Customer tools", [
        ("/office/properties", "Properties", "properties", "properties.view"),
        ("/office/tasks", "Tasks", "tasks", "tasks.view"),
        ("/office/notes", "Notes", "notes", "notes.view"),
        ("/office/catalog", "Services & Prices", "catalog", "estimates.view"),
        ("/office/documents", "Documents & Signing", "documents", "documents.view"),
        ("/office/messages", "Messages", "messages", "messages.view"),
    ]),
    ("Business tools", [
        ("/office/payments", "Payments", "payments", "payments.view"),
        ("/office/payment-settings", "Card Payment Setup", "payment-settings", "connections.manage"),
        ("/office/receivables", "Receivables", "receivables", "receivables.view"),
        ("/office/time", "Time Clock", "time", "time.self"),
        ("/office/members", "Team & Access", "members", "members.manage"),
        ("/office/alerts", "Staff Alerts", "alerts", "alerts.view"),
        ("/office/settings", "Settings & Setup", "settings", "connections.manage"),
        ("/office/intelligence", "AI Competitor Intelligence", "intelligence", "intelligence.view"),
        ("/office/imports", "Import Center", "imports", "imports.manage"),
        ("/office/linking", "Advanced Connections", "linking", "connections.manage"),
        ("/setup", "Go-Live Checklist", "setup", "connections.manage"),
    ]),
]


MOBILE_PRIMARY = [
    ("/office", "Home", "home", "mobile", "dashboard.view"),
    ("/office/contacts", "Customers", "users", "contacts", "contacts.view"),
    ("/office/roomflow", "RoomFlow", "scan", "roomflow", "estimates.view"),
    ("/office/invoices", "Billing", "receipt", "invoices", "invoices.view"),
]


MOBILE_ICONS = {
    "home": "<path d='M3 10.8 10 5l7 5.8V19a1 1 0 0 1-1 1h-4v-6H8v6H4a1 1 0 0 1-1-1z'/>",
    "users": "<path d='M7.5 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm5 9H2.5v-1.5a5 5 0 0 1 10 0zm1-9a2.5 2.5 0 1 0 0-5m.5 8a4 4 0 0 1 4 4v2h-3'/>",
    "scan": "<path d='M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4M8 12h8M12 8v8'/>",
    "receipt": "<path d='M6 3h12v18l-3-2-3 2-3-2-3 2zm3 5h6m-6 4h6m-6 4h4'/>",
    "menu": "<path d='M4 7h16M4 12h16M4 17h16'/>",
    "close": "<path d='m6 6 12 12M18 6 6 18'/>",
}


def mobile_icon(name: str) -> str:
    paths = MOBILE_ICONS.get(name, MOBILE_ICONS["menu"])
    return f"<svg viewBox='0 0 24 24' aria-hidden='true' focusable='false'>{paths}</svg>"


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def money_cents(value: Any, currency: str = "USD") -> str:
    try:
        cents = int(value or 0)
    except (TypeError, ValueError):
        cents = 0
    prefix = "$" if str(currency).upper() == "USD" else f"{esc(currency)} "
    return f"{prefix}{cents / 100:,.2f}"


def money_units(value: Any, currency: str = "USD") -> str:
    try:
        units = float(value or 0)
    except (TypeError, ValueError):
        units = 0
    prefix = "$" if str(currency).upper() == "USD" else f"{esc(currency)} "
    return f"{prefix}{units:,.2f}"


def badge(value: Any, tone: str | None = None) -> str:
    text = str(value or "UNKNOWN")
    normalized = text.upper()
    if tone is None:
        if normalized in {"CONNECTED", "READY", "PAID", "ACTIVE", "ACTIVE_CUSTOMER", "COMPLETED", "ACCEPTED", "OPTED_IN", "FULLY_PAID", "OWNER"}:
            tone = "good"
        elif normalized in {"FAILED", "INVALID", "DISABLED", "DEAD", "DISPUTED", "PAST_DUE", "ERROR", "CLOSED"}:
            tone = "bad"
        elif normalized in {"PREVIEWED", "PENDING", "INVITED", "QUEUED", "PARTIALLY_PAID", "WARNING", "UNPAID", "RUNNING", "LEAD"}:
            tone = "warn"
        else:
            tone = "neutral"
    return f"<span class='badge {tone}'>{esc(text)}</span>"


def progress(checklist: dict[str, bool]) -> tuple[int, int, int]:
    keys = ["owner_created", "profile_saved", "connections_tested", "import_reviewed", "legal_reviewed", "messaging_reviewed"]
    done = sum(1 for key in keys if checklist.get(key))
    return done, len(keys), int(done / len(keys) * 100)


def json_pre(value: Any) -> str:
    return f"<pre>{esc(json.dumps(value, indent=2, default=str))}</pre>"


def table(headers: Iterable[str], rows: Iterable[Iterable[Any]], empty: str = "No records yet.") -> str:
    header_values = [str(value) for value in headers]
    row_values = [list(row) for row in rows]
    head = "".join(f"<th scope='col'>{esc(value)}</th>" for value in header_values)
    if not row_values:
        body = f"<tr class='empty-row'><td colspan='{len(header_values)}' class='empty'>{esc(empty)}</td></tr>"
    else:
        rendered_rows: list[str] = []
        for row in row_values:
            padded = row + [""] * max(0, len(header_values) - len(row))
            cells = "".join(
                f"<td data-label='{esc(header_values[index])}'>{str(value if value is not None else '')}</td>"
                for index, value in enumerate(padded[: len(header_values)])
            )
            rendered_rows.append(f"<tr>{cells}</tr>")
        body = "".join(rendered_rows)
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


OFFICE_JS = r"""
(() => {
  const sidebar = document.getElementById('fm-office-sidebar');
  const backdrop = document.getElementById('fm-office-backdrop');
  if (!sidebar || !backdrop) return;
  const controls = Array.from(document.querySelectorAll('[data-mobile-menu]'));
  const closeControls = Array.from(document.querySelectorAll('[data-mobile-menu-close]'));
  const desktop = window.matchMedia('(min-width: 1101px)');
  const focusableSelector = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
  let returnFocus = null;
  const fixedSidebar = () => document.documentElement.dataset.workspace === 'desktop' && desktop.matches;
  const setDrawerAvailability = (available) => {
    if ('inert' in HTMLElement.prototype) sidebar.inert = !available;
    sidebar.querySelectorAll(focusableSelector).forEach((node) => {
      if (!available) {
        if (!node.hasAttribute('data-fm-saved-tabindex')) node.setAttribute('data-fm-saved-tabindex', node.getAttribute('tabindex') ?? '');
        node.setAttribute('tabindex', '-1');
      } else if (node.hasAttribute('data-fm-saved-tabindex')) {
        const saved = node.getAttribute('data-fm-saved-tabindex');
        if (saved) node.setAttribute('tabindex', saved); else node.removeAttribute('tabindex');
        node.removeAttribute('data-fm-saved-tabindex');
      }
    });
  };
  const setOpen = (requested, options = {}) => {
    const wasOpen = sidebar.classList.contains('is-open');
    const open = Boolean(requested && !fixedSidebar());
    if (open && !wasOpen) returnFocus = options.trigger || document.activeElement;
    sidebar.classList.toggle('is-open', open);
    backdrop.classList.toggle('is-open', open);
    backdrop.hidden = !open;
    backdrop.setAttribute('aria-hidden', open ? 'false' : 'true');
    document.documentElement.classList.toggle('fm-office-menu-open', open);
    sidebar.setAttribute('aria-hidden', fixedSidebar() || open ? 'false' : 'true');
    setDrawerAvailability(fixedSidebar() || open);
    controls.forEach((button) => button.setAttribute('aria-expanded', open ? 'true' : 'false'));
    if (open && !wasOpen) window.requestAnimationFrame(() => (closeControls[0] || sidebar.querySelector(focusableSelector))?.focus());
    if (!open && wasOpen && options.restore !== false && returnFocus?.focus) returnFocus.focus();
  };
  controls.forEach((button) => button.addEventListener('click', () => setOpen(!sidebar.classList.contains('is-open'), { trigger: button })));
  closeControls.forEach((button) => button.addEventListener('click', () => setOpen(false)));
  backdrop.addEventListener('click', () => setOpen(false));
  sidebar.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => setOpen(false, { restore: false })));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && sidebar.classList.contains('is-open')) { event.preventDefault(); setOpen(false); return; }
    if (event.key !== 'Tab' || !sidebar.classList.contains('is-open')) return;
    const focusable = Array.from(sidebar.querySelectorAll(focusableSelector)).filter((node) => !node.hidden && node.getClientRects().length);
    if (!focusable.length) return;
    const first = focusable[0]; const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  const updateMode = () => {
    setOpen(false, { restore: false });
    sidebar.setAttribute('aria-hidden', fixedSidebar() ? 'false' : 'true');
    setDrawerAvailability(fixedSidebar());
  };
  if (desktop.addEventListener) desktop.addEventListener('change', updateMode); else desktop.addListener(updateMode);
  updateMode();
  window.addEventListener('floodman:layoutchange', updateMode);

  const escapeText = (value) => String(value == null ? '' : value);
  const debounce = (fn, wait = 250) => {
    let timer;
    return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); };
  };
  const closePickers = (except) => {
    document.querySelectorAll('.fm-picker-results').forEach((node) => {
      if (node !== except) { node.hidden = true; node.innerHTML = ''; }
    });
  };
  document.querySelectorAll('[data-fm-picker]').forEach((root) => {
    const input = root.querySelector('.fm-picker-input');
    const hidden = root.querySelector('.fm-picker-value');
    const results = root.querySelector('.fm-picker-results');
    const endpoint = root.dataset.endpoint || '';
    const contactSource = root.dataset.contactSource || '';
    if (!input || !hidden || !results || !endpoint) return;
    let controller;
    const contactValue = () => {
      if (!contactSource) return '';
      const field = document.getElementById(contactSource) || document.querySelector(`[name="${contactSource}"]`);
      return field ? field.value : '';
    };
    const select = (item) => {
      hidden.value = escapeText(item.id);
      input.value = escapeText(item.label);
      input.dataset.selectedLabel = input.value;
      hidden.dispatchEvent(new Event('change', { bubbles: true }));
      input.setCustomValidity('');
      closePickers();
    };
    const load = async () => {
      const query = input.value.trim();
      if (query.length < 2 && !contactValue()) { results.hidden = true; return; }
      if (controller) controller.abort();
      controller = new AbortController();
      const url = new URL(endpoint, window.location.origin);
      url.searchParams.set('q', query);
      url.searchParams.set('limit', '25');
      if (contactValue()) url.searchParams.set('contact_id', contactValue());
      results.hidden = false;
      results.innerHTML = '<div class="fm-picker-message">Searching…</div>';
      try {
        const response = await fetch(url, { credentials: 'same-origin', signal: controller.signal, headers: { Accept: 'application/json' } });
        if (!response.ok) throw new Error(`Search returned ${response.status}`);
        const payload = await response.json();
        const items = Array.isArray(payload.items) ? payload.items : [];
        results.innerHTML = '';
        if (!items.length) {
          results.innerHTML = '<div class="fm-picker-message">No matching records</div>';
          return;
        }
        items.forEach((item) => {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'fm-picker-option';
          const title = document.createElement('b');
          title.textContent = escapeText(item.label);
          const meta = document.createElement('small');
          meta.textContent = escapeText(item.meta);
          button.append(title, meta);
          button.addEventListener('click', () => select(item));
          results.appendChild(button);
        });
      } catch (error) {
        if (error.name === 'AbortError') return;
        results.innerHTML = '<div class="fm-picker-message">Search is temporarily unavailable</div>';
      }
    };
    const debounced = debounce(load, 220);
    input.addEventListener('input', () => {
      if (input.value !== input.dataset.selectedLabel) hidden.value = '';
      debounced();
    });
    input.addEventListener('focus', () => { closePickers(results); if (input.value.trim() || contactValue()) load(); });
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { event.preventDefault(); event.stopPropagation(); load(); }
    });
    hidden.addEventListener('change', () => {
      document.querySelectorAll(`[data-contact-source="${hidden.id}"]`).forEach((propertyRoot) => {
        const propertyInput = propertyRoot.querySelector('.fm-picker-input');
        const propertyHidden = propertyRoot.querySelector('.fm-picker-value');
        if (propertyInput) { propertyInput.value = ''; propertyInput.dataset.selectedLabel = ''; }
        if (propertyHidden) propertyHidden.value = '';
      });
    });
    const form = root.closest('form');
    if (form && root.dataset.required === 'true') {
      form.addEventListener('submit', (event) => {
        if (!hidden.value) {
          input.setCustomValidity('Choose a record from the search results.');
          input.reportValidity();
          event.preventDefault();
        }
      });
    }
  });
  document.addEventListener('click', (event) => {
    if (!event.target.closest('[data-fm-picker]')) closePickers();
  });
})();

(() => {
  document.querySelectorAll('[data-estimate-workflow]').forEach((form) => {
    const customerMode = form.querySelector('[data-customer-mode-value]');
    const propertyMode = form.querySelector('[data-property-mode-value]');
    const customerPanels = Array.from(form.querySelectorAll('[data-customer-mode-panel]'));
    const propertyPanels = Array.from(form.querySelectorAll('[data-property-mode-panel]'));
    const customerButtons = Array.from(form.querySelectorAll('[data-customer-mode-button]'));
    const propertyButtons = Array.from(form.querySelectorAll('[data-property-mode-button]'));
    const contactId = form.querySelector('[name="contact_id"]');
    const propertyId = form.querySelector('[name="property_id"]');

    const setMode = (kind, value) => {
      const mode = kind === 'customer' ? customerMode : propertyMode;
      const panels = kind === 'customer' ? customerPanels : propertyPanels;
      const buttons = kind === 'customer' ? customerButtons : propertyButtons;
      if (!mode) return;
      mode.value = value;
      panels.forEach((panel) => { panel.hidden = panel.dataset[`${kind}ModePanel`] !== value; });
      buttons.forEach((button) => button.classList.toggle('active', button.dataset[`${kind}ModeButton`] === value));
      if (kind === 'customer' && value === 'new') setMode('property', 'new');
    };

    customerButtons.forEach((button) => button.addEventListener('click', () => setMode('customer', button.dataset.customerModeButton)));
    propertyButtons.forEach((button) => button.addEventListener('click', () => {
      if (customerMode?.value === 'new' && button.dataset.propertyModeButton === 'existing') {
        alert('Create the new customer first or create a new property for that customer.');
        return;
      }
      setMode('property', button.dataset.propertyModeButton);
    }));

    form.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' || event.target.tagName === 'TEXTAREA') return;
      if (event.target.matches('input[type="search"], [data-catalog-search], .fm-picker-input')) {
        event.preventDefault(); event.stopPropagation();
      } else if (event.target.tagName === 'INPUT') {
        event.preventDefault();
      }
    });

    form.addEventListener('submit', (event) => {
      const explicit = event.submitter?.matches('[data-estimate-submit]');
      if (!explicit) { event.preventDefault(); return; }
      let invalid = null;
      if (customerMode?.value === 'existing' && !contactId?.value) invalid = form.querySelector('[name="contact_id"]')?.closest('[data-fm-picker]')?.querySelector('.fm-picker-input');
      if (customerMode?.value === 'new') {
        const first = form.querySelector('[name="new_contact_first_name"]')?.value.trim();
        const company = form.querySelector('[name="new_contact_company"]')?.value.trim();
        const email = form.querySelector('[name="new_contact_email"]')?.value.trim();
        const phone = form.querySelector('[name="new_contact_phone"]')?.value.trim();
        if (!first && !company) invalid = form.querySelector('[name="new_contact_first_name"]');
        else if (!email && !phone) invalid = form.querySelector('[name="new_contact_email"]');
      }
      if (!invalid && propertyMode?.value === 'existing' && !propertyId?.value) invalid = form.querySelector('[name="property_id"]')?.closest('[data-fm-picker]')?.querySelector('.fm-picker-input');
      if (!invalid && propertyMode?.value === 'new') {
        for (const name of ['new_property_service_street','new_property_service_city','new_property_service_state','new_property_service_postal_code']) {
          const field = form.querySelector(`[name="${name}"]`);
          if (!field?.value.trim()) { invalid = field; break; }
        }
      }
      if (invalid) {
        event.preventDefault();
        invalid.setCustomValidity('Complete this step before saving the estimate.');
        invalid.reportValidity();
        invalid.addEventListener('input', () => invalid.setCustomValidity(''), { once: true });
        invalid.closest('.estimate-workflow-step')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
    setMode('customer', customerMode?.value || 'existing');
    setMode('property', propertyMode?.value || 'existing');
  });
})();
(() => {
  const money = (cents) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format((Number(cents) || 0) / 100);
  const uid = (prefix = 'id') => (crypto.randomUUID ? crypto.randomUUID() : `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  const text = (value) => String(value == null ? '' : value);
  const num = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const centsFromInput = (value) => Math.round(num(value, 0) * 100);
  const debounce = (fn, wait = 220) => { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); }; };

  document.querySelectorAll('[data-fm-estimate-builder]').forEach((root) => {
    const hidden = root.querySelector('.fm-estimate-payload');
    const sectionsHost = root.querySelector('.fm-estimate-sections');
    const addSectionButton = root.querySelector('[data-add-estimate-section]');
    const summary = root.querySelector('.fm-estimate-summary');
    if (!hidden || !sectionsHost) return;

    let state;
    try { state = JSON.parse(hidden.value || '{}'); } catch (_) { state = {}; }
    state.sections = Array.isArray(state.sections) ? state.sections : [];
    state.line_items = Array.isArray(state.line_items) ? state.line_items : [];
    if (!state.sections.length) state.sections.push({ id: uid('section'), name: root.dataset.defaultSection || 'Scope of Work', description: '', sort_order: 0 });

    const sectionById = (id) => state.sections.find((section) => section.id === id);
    const sectionLines = (id) => state.line_items.filter((line) => line.section_id === id).sort((a, b) => num(a.sort_order) - num(b.sort_order));
    const save = () => {
      state.sections.forEach((section, index) => { section.sort_order = index; });
      state.line_items.forEach((line) => {
        const section = sectionById(line.section_id);
        line.section_name = section ? section.name : 'Additional Items';
        line.line_total_cents = Math.round(num(line.quantity, 1) * num(line.unit_price_cents));
        line.price = num(line.unit_price_cents) / 100;
        line.totalValue = num(line.line_total_cents) / 100;
      });
      hidden.value = JSON.stringify(state);
      const total = state.line_items.filter((line) => line.selected !== false).reduce((sum, line) => sum + num(line.line_total_cents), 0);
      if (summary) summary.textContent = `${state.sections.length} header${state.sections.length === 1 ? '' : 's'} · ${state.line_items.length} line item${state.line_items.length === 1 ? '' : 's'} · ${money(total)}`;
    };

    const addLineFromCatalog = (sectionId, item) => {
      const lines = sectionLines(sectionId);
      const pricing = item.formula?.xactimate || {};
      state.line_items.push({
        id: uid('line'), section_id: sectionId, section_name: sectionById(sectionId)?.name || '',
        catalog_item_id: item.id || null, name: item.name || 'Catalog item', description: item.description || '',
        quantity: 1, unit: item.unit || 'each', unit_price_cents: num(item.unit_price_cents),
        line_total_cents: num(item.unit_price_cents), taxable: Boolean(item.taxable), optional: false,
        selected: true, pricing_method: item.pricing_method || 'fixed', category: item.category || '',
        pricing_reference: pricing.code || '', pricing_source: item.source_provider || '',
        pricing_price_list: pricing.price_list || '', pricing_effective_date: pricing.effective_date || '',
        pricing_market: pricing.market || '',
        custom: false, save_to_catalog: false, sort_order: lines.length,
      });
      render();
    };

    const saveCustomCatalogItem = async (sectionId, form) => {
      const name = form.querySelector('[data-custom-name]')?.value.trim();
      if (!name) { form.querySelector('[data-custom-name]')?.reportValidity(); return; }
      const payload = {
        name,
        description: form.querySelector('[data-custom-description]')?.value.trim() || '',
        category: form.querySelector('[data-custom-category]')?.value.trim() || sectionById(sectionId)?.name || 'General Services',
        default_section: sectionById(sectionId)?.name || 'General Services',
        unit: form.querySelector('[data-custom-unit]')?.value.trim() || 'each',
        unit_price_cents: centsFromInput(form.querySelector('[data-custom-price]')?.value),
        taxable: Boolean(form.querySelector('[data-custom-taxable]')?.checked),
        source_provider: 'FLOODMAN_CUSTOM',
      };
      const button = form.querySelector('[data-save-custom-item]');
      if (button) { button.disabled = true; button.textContent = 'Saving…'; }
      try {
        const response = await fetch('/office/api/catalog/items', {
          method: 'POST', credentials: 'same-origin', headers: { 'content-type': 'application/json', accept: 'application/json' }, body: JSON.stringify(payload),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.detail || `Catalog save returned ${response.status}`);
        addLineFromCatalog(sectionId, result.item || payload);
      } catch (error) {
        alert(`Could not save the custom line item: ${error.message}`);
      } finally {
        if (button) { button.disabled = false; button.textContent = 'Add & save to catalog'; }
      }
    };

    const catalogSearch = debounce(async (sectionId, input, results) => {
      const query = input.value.trim();
      if (query.length < 2) { results.innerHTML = ''; results.hidden = true; return; }
      results.hidden = false;
      results.innerHTML = '<div class="fm-catalog-message">Searching catalog…</div>';
      try {
        const url = new URL('/office/api/catalog/items', window.location.origin);
        url.searchParams.set('q', query); url.searchParams.set('limit', '30');
        const response = await fetch(url, { credentials: 'same-origin', headers: { accept: 'application/json' } });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || `Search returned ${response.status}`);
        const items = Array.isArray(payload.items) ? payload.items : [];
        results.innerHTML = '';
        if (!items.length) { results.innerHTML = '<div class="fm-catalog-message">No matching line items. Use Add custom item.</div>'; return; }
        items.forEach((item) => {
          const button = document.createElement('button'); button.type = 'button'; button.className = 'fm-catalog-option';
          const pricing = item.formula?.xactimate || {};
          const title = document.createElement('b'); title.textContent = pricing.code ? `${pricing.code} · ${item.name}` : item.name;
          const detail = document.createElement('small'); detail.textContent = `${item.default_section || item.category || 'General'} · ${item.unit || 'each'} · ${money(item.unit_price_cents)}`;
          button.append(title, detail); button.addEventListener('click', () => addLineFromCatalog(sectionId, item)); results.appendChild(button);
        });
      } catch (error) { results.innerHTML = `<div class="fm-catalog-message bad">Catalog search failed: ${text(error.message)}</div>`; }
    });

    const renderLine = (line, lineIndex) => {
      const section = sectionById(line.section_id);
      const sectionIndex = state.sections.indexOf(section);
      const globalIndex = state.line_items.indexOf(line);
      const origin = line.pricing_reference ? `${line.pricing_reference} · ${line.pricing_price_list || 'Imported pricing'}` : (line.catalog_item_id ? 'Catalog item' : 'Custom item');
      return `<article class="fm-estimate-line" data-line-index="${globalIndex}">
        <div class="fm-line-main"><label>Line item<input data-line-field="name" value="${text(line.name).replace(/&/g,'&amp;').replace(/"/g,'&quot;')}" required></label><label>Description<textarea data-line-field="description">${text(line.description).replace(/&/g,'&amp;').replace(/</g,'&lt;')}</textarea></label></div>
        <div class="fm-line-numbers"><label>Qty<input data-line-field="quantity" type="number" min="0.001" step="0.001" value="${num(line.quantity,1)}"></label><label>Unit<input data-line-field="unit" value="${text(line.unit || 'each').replace(/&/g,'&amp;').replace(/"/g,'&quot;')}"></label><label>Unit price<input data-line-field="unit_price" type="number" min="0" step="0.01" value="${(num(line.unit_price_cents)/100).toFixed(2)}"></label><div class="fm-line-total"><span>Total</span><b>${money(line.line_total_cents)}</b></div></div>
        <div class="fm-line-footer"><label class="fm-inline-check"><input data-line-field="taxable" type="checkbox" ${line.taxable ? 'checked' : ''}> Taxable</label><label class="fm-inline-check"><input data-line-field="optional" type="checkbox" ${line.optional ? 'checked' : ''}> Optional</label><span class="fm-catalog-origin">${text(origin).replace(/&/g,'&amp;').replace(/</g,'&lt;')}</span><button type="button" class="secondary small" data-move-line="up" ${lineIndex === 0 ? 'disabled' : ''}>↑</button><button type="button" class="secondary small" data-move-line="down" ${lineIndex === sectionLines(section.id).length - 1 ? 'disabled' : ''}>↓</button><button type="button" class="danger small" data-remove-line>Remove</button></div>
      </article>`;
    };

    const renderSection = (section, sectionIndex) => {
      const lines = sectionLines(section.id);
      const subtotal = lines.filter((line) => line.selected !== false).reduce((sum, line) => sum + num(line.line_total_cents), 0);
      return `<section class="fm-estimate-section" data-section-id="${section.id}">
        <header class="fm-section-header"><div class="fm-section-title-fields"><label>Header<input data-section-field="name" value="${text(section.name).replace(/&/g,'&amp;').replace(/"/g,'&quot;')}" placeholder="Waterproofing" required></label><label>Header note <span class="muted">optional</span><input data-section-field="description" value="${text(section.description).replace(/&/g,'&amp;').replace(/"/g,'&quot;')}" placeholder="Scope summary or customer note"></label></div><div class="fm-section-tools"><b>${money(subtotal)}</b><button type="button" class="secondary small" data-move-section="up" ${sectionIndex === 0 ? 'disabled' : ''}>↑</button><button type="button" class="secondary small" data-move-section="down" ${sectionIndex === state.sections.length - 1 ? 'disabled' : ''}>↓</button><button type="button" class="danger small" data-remove-section ${state.sections.length === 1 ? 'disabled' : ''}>Remove header</button></div></header>
        <div class="fm-catalog-add"><div class="fm-catalog-search"><label>Search line-item catalog<input data-catalog-search autocomplete="off" placeholder="Type waterproofing, mold, demolition, landfill…"></label><div class="fm-catalog-results" hidden></div></div><button type="button" class="secondary" data-toggle-custom>Add custom item</button></div>
        <div class="fm-custom-item" hidden><div class="form-grid three"><div class="field"><label>Item name</label><input data-custom-name required placeholder="Custom scope item"></div><div class="field"><label>Category</label><input data-custom-category value="${text(section.name).replace(/&/g,'&amp;').replace(/"/g,'&quot;')}"></div><div class="field"><label>Unit</label><input data-custom-unit value="each"></div><div class="field"><label>Unit price</label><input data-custom-price type="number" min="0" step="0.01" value="0.00"></div><div class="field checks"><label><input data-custom-taxable type="checkbox"> Taxable</label></div><div class="field full"><label>Description</label><input data-custom-description></div></div><div class="actions"><button type="button" data-save-custom-item>Add & save to catalog</button><button type="button" class="secondary" data-cancel-custom>Cancel</button></div></div>
        <div class="fm-estimate-lines">${lines.map((line, index) => renderLine(line, index)).join('') || '<div class="fm-empty-lines">No items in this header yet.</div>'}</div>
      </section>`;
    };

    function render() {
      state.sections.forEach((section, index) => { section.sort_order = index; });
      state.line_items.forEach((line) => {
        line.line_total_cents = Math.round(num(line.quantity,1) * num(line.unit_price_cents));
        line.section_name = sectionById(line.section_id)?.name || 'Additional Items';
      });
      sectionsHost.innerHTML = state.sections.map(renderSection).join('');
      save();
    }

    addSectionButton?.addEventListener('click', () => {
      state.sections.push({ id: uid('section'), name: `New Header ${state.sections.length + 1}`, description: '', sort_order: state.sections.length });
      render();
      const input = sectionsHost.querySelector(`[data-section-id="${state.sections.at(-1).id}"] [data-section-field="name"]`); input?.focus(); input?.select();
    });

    sectionsHost.addEventListener('input', (event) => {
      const sectionNode = event.target.closest('[data-section-id]');
      const lineNode = event.target.closest('[data-line-index]');
      if (sectionNode && event.target.dataset.sectionField) {
        const section = sectionById(sectionNode.dataset.sectionId); if (section) section[event.target.dataset.sectionField] = event.target.value;
      }
      if (lineNode && event.target.dataset.lineField) {
        const line = state.line_items[num(lineNode.dataset.lineIndex)]; if (!line) return;
        const field = event.target.dataset.lineField;
        if (field === 'quantity') line.quantity = num(event.target.value,1);
        else if (field === 'unit_price') line.unit_price_cents = centsFromInput(event.target.value);
        else if (field === 'taxable' || field === 'optional') line[field] = Boolean(event.target.checked);
        else line[field] = event.target.value;
        line.line_total_cents = Math.round(num(line.quantity,1) * num(line.unit_price_cents));
        lineNode.querySelector('.fm-line-total b').textContent = money(line.line_total_cents);
      }
      save();
    });
    sectionsHost.addEventListener('change', (event) => {
      if (event.target.dataset.lineField === 'taxable' || event.target.dataset.lineField === 'optional') {
        const lineNode = event.target.closest('[data-line-index]'); const line = state.line_items[num(lineNode?.dataset.lineIndex)]; if (line) line[event.target.dataset.lineField] = Boolean(event.target.checked); save();
      }
    });
    sectionsHost.addEventListener('click', (event) => {
      const sectionNode = event.target.closest('[data-section-id]'); if (!sectionNode) return;
      const sectionId = sectionNode.dataset.sectionId; const sectionIndex = state.sections.findIndex((section) => section.id === sectionId);
      if (event.target.closest('[data-remove-section]')) {
        if (state.sections.length <= 1) return;
        if (sectionLines(sectionId).length && !confirm('Remove this header and all line items inside it?')) return;
        state.line_items = state.line_items.filter((line) => line.section_id !== sectionId); state.sections.splice(sectionIndex,1); render(); return;
      }
      const moveSection = event.target.closest('[data-move-section]')?.dataset.moveSection;
      if (moveSection) { const next = moveSection === 'up' ? sectionIndex - 1 : sectionIndex + 1; if (next >= 0 && next < state.sections.length) { [state.sections[sectionIndex],state.sections[next]]=[state.sections[next],state.sections[sectionIndex]]; render(); } return; }
      if (event.target.closest('[data-toggle-custom]')) { sectionNode.querySelector('.fm-custom-item').hidden = false; sectionNode.querySelector('[data-custom-name]')?.focus(); return; }
      if (event.target.closest('[data-cancel-custom]')) { sectionNode.querySelector('.fm-custom-item').hidden = true; return; }
      if (event.target.closest('[data-save-custom-item]')) { saveCustomCatalogItem(sectionId, sectionNode.querySelector('.fm-custom-item')); return; }
      const lineNode = event.target.closest('[data-line-index]');
      if (lineNode && event.target.closest('[data-remove-line]')) { state.line_items.splice(num(lineNode.dataset.lineIndex),1); render(); return; }
      const moveLine = event.target.closest('[data-move-line]')?.dataset.moveLine;
      if (lineNode && moveLine) {
        const line = state.line_items[num(lineNode.dataset.lineIndex)]; const list = sectionLines(sectionId); const pos = list.indexOf(line); const target = moveLine === 'up' ? pos - 1 : pos + 1;
        if (target >= 0 && target < list.length) { const other = list[target]; const a = num(line.sort_order,pos), b = num(other.sort_order,target); line.sort_order=b; other.sort_order=a; render(); } return;
      }
    });
    sectionsHost.addEventListener('input', (event) => {
      if (!event.target.matches('[data-catalog-search]')) return;
      const sectionNode = event.target.closest('[data-section-id]'); catalogSearch(sectionNode.dataset.sectionId, event.target, sectionNode.querySelector('.fm-catalog-results'));
    });
    sectionsHost.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && event.target.matches('[data-catalog-search]')) { event.preventDefault(); event.stopPropagation(); }
    });
    document.addEventListener('click', (event) => { if (!event.target.closest('.fm-catalog-search')) root.querySelectorAll('.fm-catalog-results').forEach((node) => { node.hidden = true; }); });
    root.closest('form')?.addEventListener('submit', (event) => {
      save();
      if (!event.submitter?.matches('[data-estimate-submit]')) { event.preventDefault(); return; }
      if (!state.line_items.length) { event.preventDefault(); alert('Add at least one line item.'); return; }
      if (state.sections.some((section) => !text(section.name).trim())) { event.preventDefault(); alert('Every estimate header needs a name.'); }
    });
    render();
  });

  const callDrawer = document.getElementById('fm-call-intake-drawer');
  if (callDrawer) {
    const close = callDrawer.querySelector('[data-call-intake-dismiss]');
    const open = callDrawer.querySelector('[data-call-intake-open]');
    const fields = {
      name: callDrawer.querySelector('[data-call-name]'),
      phone: callDrawer.querySelector('[data-call-phone]'),
      reason: callDrawer.querySelector('[data-call-reason]'),
      status: callDrawer.querySelector('[data-call-status]'),
      property: callDrawer.querySelector('[data-call-property]'),
    };
    let activeId = '';
    let returnFocus = null;
    const hideCall = (remember = true) => {
      if (remember && activeId) { try { sessionStorage.setItem('floodmanDismissedCallIntake', activeId); } catch (_) {} }
      callDrawer.hidden = true;
      callDrawer.setAttribute('aria-hidden', 'true');
      callDrawer.setAttribute('inert', '');
      if (returnFocus?.focus) returnFocus.focus();
    };
    const showCall = (item) => {
      if (!item?.id) return;
      let dismissed = '';
      try { dismissed = sessionStorage.getItem('floodmanDismissedCallIntake') || ''; } catch (_) {}
      if (dismissed === item.id) return;
      const caller = item.caller || {};
      const property = item.property || {};
      activeId = String(item.id);
      fields.name.textContent = caller.name || [caller.first_name, caller.last_name].filter(Boolean).join(' ') || 'Incoming caller';
      fields.phone.textContent = caller.phone_e164 || caller.phone || 'Phone unavailable';
      fields.reason.textContent = item.summary || item.service_reason || 'The assistant is still collecting details.';
      fields.status.textContent = item.review_status === 'REVIEW_REQUIRED' ? 'Human review needed' : (item.status || 'ACTIVE').replaceAll('_', ' ');
      fields.property.textContent = [property.street, property.city, property.state, property.postal_code].filter(Boolean).join(', ') || 'Service property still being collected';
      open.href = `/office/calls/${encodeURIComponent(activeId)}`;
      returnFocus = document.activeElement;
      callDrawer.hidden = false;
      callDrawer.setAttribute('aria-hidden', 'false');
      callDrawer.removeAttribute('inert');
      if ('Notification' in window && Notification.permission === 'granted') {
        try {
          const noticeKey = `floodmanCallNotification:${activeId}`;
          if (!sessionStorage.getItem(noticeKey)) {
            new Notification(`Floodman incoming call: ${fields.name.textContent}`, { body: fields.reason.textContent, tag: `floodman-call-${activeId}` });
            sessionStorage.setItem(noticeKey, '1');
          }
        } catch (_) {}
      }
      window.requestAnimationFrame(() => close?.focus());
    };
    close?.addEventListener('click', () => hideCall(true));
    document.querySelectorAll('[data-enable-call-notifications]').forEach((button) => button.addEventListener('click', async () => {
      if (!('Notification' in window)) { button.textContent = 'Browser notifications unavailable'; return; }
      const permission = await Notification.requestPermission();
      button.textContent = permission === 'granted' ? 'Browser notifications enabled' : 'Browser notifications not enabled';
    }));
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !callDrawer.hidden) { event.preventDefault(); hideCall(true); }
    });
    fetch('/office/api/call-intakes/latest', { credentials: 'same-origin', cache: 'no-store' })
      .then((response) => response.ok ? response.json() : null)
      .then((payload) => showCall(payload?.item)).catch(() => {});
    if ('EventSource' in window) {
      const source = new EventSource('/office/api/call-intakes/events');
      source.addEventListener('call-intake', (event) => {
        try { showCall(JSON.parse(event.data)); } catch (_) {}
      });
      window.addEventListener('pagehide', () => source.close(), { once: true });
    }
  }
})();

"""


BASE_CSS = r"""
:root{--bg:#07111f;--panel:#101d2f;--panel2:#15263d;--line:#29415f;--text:#edf4ff;--muted:#9fb0c6;--accent:#32a7ff;--accent2:#67d5c4;--danger:#ff7878;--warn:#ffc65c;--good:#5be39d;--side:265px;--safe-bottom:env(safe-area-inset-bottom,0px);--safe-top:env(safe-area-inset-top,0px);--layer-nav:40;--layer-sticky:60;--layer-backdrop:80;--layer-drawer:90;--layer-popover:100;--layer-toast:110}
*{box-sizing:border-box}html{min-width:0;background:var(--bg);scroll-behavior:smooth}body{margin:0;background:radial-gradient(circle at 80% -10%,#193b5e 0,#07111f 44%);color:var(--text);font-family:"Segoe UI",Arial,sans-serif;min-height:100vh;min-height:100svh;-webkit-text-size-adjust:100%;text-rendering:optimizeLegibility}button,a,input,select,textarea{touch-action:manipulation}a{color:#8bd3ff;text-decoration:none;overflow-wrap:anywhere}a:hover{text-decoration:underline}:focus-visible{outline:3px solid #7dd3fc;outline-offset:3px}.skip-link{position:fixed;top:calc(8px + var(--safe-top));left:8px;z-index:var(--layer-toast);padding:10px 14px;border-radius:8px;background:#fff;color:#07111f;font-weight:800;transform:translateY(-180%)}.skip-link:focus{transform:translateY(0)}.shell{display:grid;grid-template-columns:var(--side) minmax(0,1fr);min-height:100vh;min-height:100svh}.office-sidebar{background:#081426f5;border-right:1px solid var(--line);padding:18px 13px;position:sticky;top:0;height:100vh;height:100svh;overflow:auto;z-index:var(--layer-nav)}.sidebar-mobile-head{display:none}.brand{font-size:21px;font-weight:800;letter-spacing:.2px;margin:3px 8px 4px}.brand.big{font-size:28px;margin:0 0 18px}.subbrand{font-size:12px;color:var(--muted);margin:0 8px 18px}.nav-group{margin:15px 0 5px;padding:0 10px;color:#7792b0;font-size:10px;letter-spacing:1px;text-transform:uppercase;font-weight:800}nav a{display:block;padding:10px 11px;border-radius:10px;color:#cfe0f4;margin:2px 0;font-weight:650;font-size:14px}nav a:hover{background:#162b45;text-decoration:none}nav a.active{background:#1c5f91;color:white;box-shadow:inset 3px 0 0 #8dd6ff}.side-note{margin-top:17px;border:1px solid #5c512d;background:#2a2516;padding:11px;border-radius:10px;font-size:12px;color:#f5d984}.user-box{margin-top:18px;padding:12px;border:1px solid var(--line);border-radius:10px;background:#0a1728}.user-box strong{display:block}.user-box form{margin-top:9px}.mobile-topbar,.mobile-bottom-nav,.mobile-nav-backdrop{display:none}main{padding:24px 30px 54px;min-width:0;width:100%}header.page-header{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:18px}h1{font-size:31px;line-height:1.12;margin:0 0 5px}h2{font-size:20px;line-height:1.25;margin:0 0 14px}h3{font-size:16px;margin:0 0 10px}.muted{color:var(--muted)}.card{min-width:0;background:linear-gradient(160deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:14px;padding:18px;margin:0 0 16px;box-shadow:0 14px 35px #0004;overflow-wrap:anywhere}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(220px,100%),1fr));gap:14px}.grid.two{grid-template-columns:repeat(2,minmax(0,1fr))}.metrics-grid{grid-template-columns:repeat(auto-fit,minmax(160px,1fr))}.metric strong{display:block;font-size:27px;line-height:1.15;margin-top:7px;overflow-wrap:anywhere}.metric small{color:var(--muted)}.app-card{display:flex;flex-direction:column;min-height:170px}.app-card .actions{margin-top:auto}.badge{display:inline-block;max-width:100%;border-radius:999px;padding:4px 9px;font-size:12px;font-weight:750;border:1px solid #50657e;background:#1e3149;overflow-wrap:anywhere}.badge.good{color:#9ff4c9;border-color:#25744e;background:#0b3827}.badge.warn{color:#ffe1a1;border-color:#806321;background:#453312}.badge.bad{color:#ffc0c0;border-color:#873e3e;background:#471c24}.badge.neutral{color:#c9d7e8}.notice{border:1px solid #276d8d;background:#0d3044;border-radius:11px;padding:12px 14px;margin-bottom:16px;color:#bfeaff}.callout{border-left:4px solid var(--accent);background:#0b2035;padding:13px 15px;border-radius:8px;margin:12px 0;overflow-wrap:anywhere}.warning{border-left-color:var(--warn);background:#2a2516}.danger{border-left-color:var(--danger);background:#351b22}.success{border-left-color:var(--good);background:#0b2d22}button,.button{display:inline-flex;min-height:42px;align-items:center;justify-content:center;background:#1888d4;color:white;border:0;border-radius:9px;padding:10px 14px;font-weight:750;cursor:pointer;text-decoration:none;font:inherit}button:hover,.button:hover{filter:brightness(1.12);text-decoration:none}.button.secondary,button.secondary{background:#263e59}.button.good,button.good{background:#16754a}.button.danger,button.danger{background:#8b3540}.button.small,button.small{min-height:36px;padding:7px 10px;font-size:12px}label{display:block;font-size:13px;color:#c8d8ea;margin:0 0 6px}input,select,textarea{width:100%;min-width:0;background:#081426;color:var(--text);border:1px solid #46617f;border-radius:8px;padding:11px 12px;font:inherit}textarea{min-height:110px;resize:vertical}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.form-grid.three{grid-template-columns:repeat(3,minmax(0,1fr))}.field{min-width:0}.field.full{grid-column:1/-1}.checks label{display:flex;gap:9px;align-items:flex-start;margin:9px 0}.checks input{width:auto;margin-top:3px}.table-wrap{max-width:100%;overflow:auto;border:1px solid var(--line);border-radius:11px;-webkit-overflow-scrolling:touch}table{width:100%;border-collapse:collapse;min-width:700px}th,td{padding:10px 12px;border-bottom:1px solid #263c58;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{font-size:12px;text-transform:uppercase;letter-spacing:.6px;color:#a9bdd4;background:#0a1728}td{font-size:14px}tr:last-child td{border-bottom:0}.empty{text-align:center;color:var(--muted);padding:24px}pre{white-space:pre-wrap;word-break:break-word;background:#06101d;border:1px solid #233a57;border-radius:9px;padding:12px;max-height:460px;overflow:auto}code{background:#071321;border:1px solid #28425f;border-radius:5px;padding:2px 5px}details{border:1px solid #29415f;border-radius:9px;padding:10px;margin:8px 0;background:#0a1728}summary{cursor:pointer;font-weight:700}.progress{height:12px;border-radius:999px;background:#091525;border:1px solid #29415f;overflow:hidden}.progress span{display:block;height:100%;background:linear-gradient(90deg,#1686d2,#5bd6bc)}.steps{display:grid;grid-template-columns:repeat(6,1fr);gap:7px;margin-top:9px}.step{text-align:center;font-size:12px;color:var(--muted);padding:7px;border-radius:7px;background:#0a1728}.step.done{color:#a7f0ce;background:#0d3528}.actions{display:flex;gap:9px;flex-wrap:wrap;align-items:center}.right{text-align:right}hr{border:0;border-top:1px solid var(--line);margin:18px 0}.mono{font-family:Consolas,monospace}.pill-list{display:flex;flex-wrap:wrap;gap:7px}.list-clean{margin:0;padding-left:20px}.auth-shell{min-height:100vh;min-height:100svh;display:grid;place-items:center;padding:20px}.auth-card{width:min(540px,100%);background:linear-gradient(160deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:16px;padding:28px;box-shadow:0 22px 60px #0008}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:15px}.tabs a{padding:8px 11px;border:1px solid var(--line);border-radius:8px;background:#0a1728}.tabs a.active{background:#1c5f91;color:white}.split{display:grid;grid-template-columns:2fr 1fr;gap:16px}.creator-footer{margin-top:30px;padding:16px 0 0;border-top:1px solid var(--line);color:var(--muted);font-size:12px}.creator-footer a{color:#8bd3ff}img,svg,video{max-width:100%;height:auto}
.primary-nav{margin-top:14px}.sidebar-more{margin:12px 0 0;padding:0;border:0;border-top:1px solid var(--line);border-radius:0;background:transparent}.sidebar-more>summary{padding:13px 11px 9px;color:#9fb6cf;font-size:13px}.sidebar-more[open]>summary{color:#edf4ff}.desktop-workspace-hero{display:flex;align-items:center;justify-content:space-between;gap:22px;padding:22px;margin:0 0 18px;border:1px solid #2d719c;border-radius:18px;background:linear-gradient(135deg,#0b2b47,#10243b 62%,#163c58);box-shadow:0 18px 45px #0004}.desktop-workspace-hero h2{margin:5px 0 7px;font-size:25px}.desktop-workspace-hero p{max-width:820px;margin:0;color:#bfd3e7;line-height:1.55}.desktop-workspace-kicker{color:#6ed0ff;font-size:11px;font-weight:900;letter-spacing:.14em}.desktop-workspace-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;min-width:260px}.desktop-workspace-actions .button{white-space:nowrap}@media(max-width:1100px){.desktop-workspace-hero{align-items:stretch;flex-direction:column}.desktop-workspace-actions{min-width:0;justify-content:stretch}.desktop-workspace-actions .button{flex:1}.desktop-workspace-hero{display:none}}
@media(max-width:1100px){.desktop-brand{display:none}html.fm-office-menu-open,html.fm-office-menu-open body{overflow:hidden}.shell{display:block;min-height:100vh}.office-sidebar{position:fixed;inset:0 auto 0 0;width:min(86vw,340px);height:100dvh;padding:calc(13px + var(--safe-top)) 13px calc(18px + var(--safe-bottom));border-right:1px solid var(--line);border-bottom:0;transform:translateX(-104%);transition:transform .22s ease;box-shadow:18px 0 55px #0009;z-index:var(--layer-drawer)}.office-sidebar.is-open{transform:translateX(0)}.sidebar-mobile-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}.sidebar-mobile-head .brand{margin:0}.mobile-close{width:44px;min-height:44px;padding:0;border-radius:50%;font-size:23px;background:#203853}.mobile-nav-backdrop{display:block;position:fixed;inset:0;z-index:var(--layer-backdrop);opacity:0;pointer-events:none;background:#020712b8;backdrop-filter:blur(3px);transition:opacity .2s}.mobile-nav-backdrop.is-open{opacity:1;pointer-events:auto}.mobile-topbar{position:sticky;top:0;z-index:var(--layer-sticky);display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:60px;padding:calc(8px + var(--safe-top)) 12px 8px;border-bottom:1px solid var(--line);background:#081426f2;backdrop-filter:blur(14px);box-shadow:0 8px 25px #0005}.mobile-topbar-brand{display:flex;align-items:center;gap:9px;min-width:0;font-weight:850}.mobile-topbar-mark{display:grid;place-items:center;width:38px;height:38px;border-radius:12px;background:linear-gradient(135deg,#1d4ed8,#0ea5e9);font-size:19px}.mobile-topbar-copy{min-width:0}.mobile-topbar-copy b,.mobile-topbar-copy small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mobile-topbar-copy small{color:var(--muted);font-size:10px;font-weight:600}.mobile-menu-button{width:46px;min-height:46px;padding:0;border-radius:12px;background:#1b3554}.mobile-menu-button svg,.mobile-close svg{width:23px;height:23px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round}.nav-group{display:block}.office-sidebar nav{display:block;overflow:visible}.office-sidebar nav a{min-height:44px;display:flex;align-items:center;white-space:normal}.mobile-bottom-nav{position:fixed;left:0;right:0;bottom:0;z-index:var(--layer-sticky);display:grid;grid-template-columns:repeat(5,minmax(0,1fr));padding:6px 5px calc(6px + var(--safe-bottom));border-top:1px solid #31506f;background:#081426f7;backdrop-filter:blur(16px);box-shadow:0 -10px 30px #0007}.mobile-bottom-nav a,.mobile-bottom-nav button{min-width:0;min-height:54px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;border-radius:10px;padding:4px 2px;color:#a9bed5;background:transparent;font-size:10px;font-weight:750;text-decoration:none}.mobile-bottom-nav .mobile-nav-icon{display:grid;place-items:center;width:24px;height:24px}.mobile-bottom-nav .mobile-nav-icon svg{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}.mobile-bottom-nav a.active{color:white;background:#1a5482}.mobile-bottom-nav button{border:0}.mobile-bottom-nav a:hover{text-decoration:none}.mobile-bottom-nav span:last-child{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}main{padding:15px 12px calc(90px + var(--safe-bottom))}.page-header{display:block!important}.page-header h1{font-size:26px}.header-meta{margin-top:10px}.form-grid,.form-grid.three,.grid.two,.split{grid-template-columns:1fr}.steps{grid-template-columns:repeat(2,1fr)}input,select,textarea{min-height:48px;font-size:16px}textarea{min-height:130px}button,.button{min-height:48px}.auth-shell{padding:calc(16px + var(--safe-top)) 12px calc(16px + var(--safe-bottom))}.auth-card{padding:20px 16px;border-radius:14px}}
@media(max-width:720px){.card{padding:14px;border-radius:13px;margin-bottom:12px}.grid{gap:10px}.metric strong{font-size:23px}.actions{display:grid;grid-template-columns:1fr;width:100%}.actions>*,.actions form,.actions form button{width:100%}.tabs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.tabs a{text-align:center}.table-wrap{overflow:visible;border:0;border-radius:0;background:transparent}table{display:block;min-width:0}thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap}tbody{display:block}tbody tr{display:block;margin:0 0 11px;border:1px solid var(--line);border-radius:12px;background:#0a1728;box-shadow:0 8px 20px #0003;overflow:hidden}tbody td{display:grid;grid-template-columns:minmax(104px,38%) minmax(0,1fr);gap:10px;align-items:start;min-height:43px;padding:10px 11px;border-bottom:1px solid #203752;font-size:13px}tbody td::before{content:attr(data-label);color:#91aac5;font-size:10px;font-weight:850;letter-spacing:.06em;text-transform:uppercase;overflow-wrap:anywhere}tbody tr:last-child td,tbody td:last-child{border-bottom:0}tbody .empty{display:block;text-align:center;padding:20px}.empty::before{content:none}.right{text-align:left}.creator-footer{padding-bottom:4px}.notice,.callout{font-size:13px}}

.roomflow-workspace-card{padding:0;overflow:hidden}.roomflow-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:13px 15px;border-bottom:1px solid var(--line);background:#0b1b2e}.roomflow-toolbar-copy b,.roomflow-toolbar-copy small{display:block}.roomflow-toolbar-copy small{margin-top:3px;color:var(--muted)}.roomflow-frame{display:block;width:100%;height:clamp(320px,calc(100dvh - 185px),820px);min-height:0;border:0;background:#07111f}.roomflow-history-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}.roomflow-history-card{padding:13px;border:1px solid var(--line);border-radius:12px;background:#0b192b}.roomflow-history-card b,.roomflow-history-card small{display:block}.roomflow-history-card small{margin-top:5px;color:var(--muted)}
@media(max-width:1100px){.roomflow-workspace-card{margin-left:-12px;margin-right:-12px;border-left:0;border-right:0;border-radius:0}.roomflow-toolbar{align-items:stretch;flex-direction:column}.roomflow-toolbar .actions{display:grid;grid-template-columns:1fr 1fr}.roomflow-toolbar .button{width:100%}.roomflow-frame{height:clamp(320px,calc(100dvh - 236px),720px);min-height:0}}
@media(max-width:560px){.roomflow-toolbar .actions{grid-template-columns:1fr}.roomflow-frame{height:clamp(280px,calc(100dvh - 280px),640px);min-height:0}}
@media(max-width:420px){main{padding-left:9px;padding-right:9px}.mobile-topbar{padding-left:9px;padding-right:9px}.card{padding:12px}.page-header h1{font-size:23px}.mobile-bottom-nav a,.mobile-bottom-nav button{font-size:9px}.mobile-bottom-nav .mobile-nav-icon{font-size:18px}tbody td{grid-template-columns:96px minmax(0,1fr);padding:9px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*::before,*::after{scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}

.call-intake-drawer{position:fixed;right:18px;bottom:18px;z-index:var(--layer-toast);width:min(430px,calc(100vw - 36px));max-height:min(680px,calc(100dvh - 36px));overflow:auto;border:1px solid #3f86b5;border-radius:18px;background:linear-gradient(160deg,#153552,#0a1728 74%);box-shadow:0 24px 80px #000c;padding:18px}.call-intake-drawer[hidden]{display:none}.call-intake-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}.call-intake-kicker{display:block;color:#6ed0ff;font-size:11px;font-weight:900;letter-spacing:.12em;text-transform:uppercase;margin-bottom:5px}.call-intake-close{flex:0 0 auto;width:44px;min-height:44px;padding:0;border-radius:50%;background:#263e59;font-size:22px}.call-intake-identity{margin:14px 0;padding:13px;border:1px solid #315776;border-radius:12px;background:#071422}.call-intake-identity b,.call-intake-identity span{display:block}.call-intake-identity span{margin-top:4px;color:var(--muted)}.call-intake-fact{margin:10px 0}.call-intake-fact small{display:block;color:#8fa9c4;font-weight:750;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px}.call-intake-drawer .actions{margin-top:15px}@media(max-width:560px){.call-intake-drawer{right:8px;bottom:calc(76px + var(--safe-bottom));width:calc(100vw - 16px);max-height:calc(100dvh - 92px - var(--safe-bottom));border-radius:15px;padding:15px}}


/* Professional customer workspace and scalable entity selectors */
.customer-searchbar{display:grid;grid-template-columns:minmax(220px,1fr) 190px auto;gap:10px;align-items:end;margin-bottom:14px}.customer-name{display:flex;flex-direction:column;gap:3px}.customer-name b{font-size:15px}.customer-name small{color:var(--muted)}.tag-list{display:flex;flex-wrap:wrap;gap:6px}.tag-chip{display:inline-flex;align-items:center;border:1px solid #3d6387;background:#102b45;color:#cfe9ff;border-radius:999px;padding:4px 9px;font-size:11px;font-weight:750}.customer-profile-grid{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(280px,.7fr);gap:16px}.timeline{display:grid;gap:10px}.timeline-item{padding:13px;border:1px solid var(--line);border-radius:12px;background:#0a1728}.timeline-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.timeline-item p{margin:7px 0 0;white-space:pre-wrap}.fm-picker{position:relative}.fm-picker-input{padding-right:38px}.fm-picker-results{position:absolute;z-index:1200;top:calc(100% + 5px);left:0;right:0;max-height:330px;overflow:auto;border:1px solid #4d759b;border-radius:11px;background:#071321;box-shadow:0 18px 50px #000b}.fm-picker-option{display:block;width:100%;min-height:0;padding:11px 12px;border-radius:0;border-bottom:1px solid #203a57;background:transparent;text-align:left}.fm-picker-option:hover,.fm-picker-option:focus{background:#173d60}.fm-picker-option b,.fm-picker-option small{display:block}.fm-picker-option small{margin-top:3px;color:var(--muted);font-size:11px}.fm-picker-message{padding:13px;color:var(--muted)}.payment-card-list{display:grid;gap:10px}.payment-card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center;padding:14px;border:1px solid var(--line);border-radius:12px;background:#0a1728}.payment-card strong,.payment-card small{display:block}.payment-card small{margin-top:4px;color:var(--muted)}.pci-box{border:1px solid #315f4c;background:#0c2d23;border-radius:11px;padding:12px;color:#c8f4df}.pagination{display:flex;gap:8px;align-items:center;justify-content:center;margin-top:14px}.invoice-collection-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.collection-choice{display:block;padding:12px;border:1px solid var(--line);border-radius:11px;background:#0a1728}.collection-choice input{width:auto;margin-right:7px}
@media(max-width:1100px){.customer-profile-grid{grid-template-columns:1fr}.customer-searchbar{grid-template-columns:1fr 1fr}.customer-searchbar button{grid-column:1/-1}.invoice-collection-grid{grid-template-columns:1fr}}
@media(max-width:720px){.customer-searchbar{grid-template-columns:1fr}.customer-searchbar button{grid-column:auto}.payment-card{grid-template-columns:1fr}.payment-card .actions{display:grid}.fm-picker-results{position:fixed;left:10px;right:10px;top:auto;bottom:calc(78px + var(--safe-bottom));max-height:52vh}.timeline-head{display:block}.timeline-head .muted{display:block;margin-top:4px}}

.mobile-hero{display:flex;align-items:center;justify-content:space-between;gap:18px;margin:0 0 16px;padding:22px;border:1px solid #2e5e88;border-radius:18px;background:linear-gradient(135deg,#102443,#123c67 62%,#0f6da0);box-shadow:0 18px 42px #0005}.mobile-hero h2{margin:6px 0 8px;font-size:27px}.mobile-hero p{max-width:760px;margin:0;color:#d0e5f8;line-height:1.55}.mobile-hero-kicker{color:#66d2ff;font-size:10px;font-weight:900;letter-spacing:.14em}.mobile-kpi-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin:0 0 15px}.mobile-kpi-grid a{min-width:0;padding:14px;border:1px solid var(--line);border-radius:14px;background:#0d1b2e;color:var(--text);box-shadow:0 10px 25px #0003}.mobile-kpi-grid small,.mobile-kpi-grid strong{display:block}.mobile-kpi-grid small{color:var(--muted);font-size:11px}.mobile-kpi-grid strong{margin-top:5px;font-size:24px}.mobile-launch-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:16px}.mobile-launch-card{display:grid;grid-template-columns:46px minmax(0,1fr) 18px;align-items:center;gap:11px;min-height:98px;padding:15px;border:1px solid var(--line);border-radius:15px;background:linear-gradient(155deg,#152a44,#0d1a2c);color:var(--text);box-shadow:0 12px 28px #0003}.mobile-launch-card:hover{text-decoration:none;border-color:#4e91c3}.mobile-launch-icon{display:grid;place-items:center;width:46px;height:46px;border-radius:14px;background:#183e61;color:#8bd3ff;font-size:24px;font-weight:900}.mobile-launch-card b,.mobile-launch-card small{display:block}.mobile-launch-card small{margin-top:4px;color:var(--muted);font-size:11px;line-height:1.4}.mobile-launch-arrow{color:#6f8eac;font-size:24px}.import-upload-card{padding:22px}.import-upload-copy{max-width:850px}.import-upload-copy h2{margin-top:6px}.import-upload-form{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:end;gap:12px;margin:18px 0}.file-drop-field{position:relative;display:grid;grid-template-columns:46px minmax(0,1fr);gap:10px;align-items:center;min-height:86px;padding:14px;border:2px dashed #3d719d;border-radius:15px;background:#0a1728;cursor:pointer}.file-drop-field:hover{border-color:#68c8ff;background:#0d2035}.file-drop-field b,.file-drop-field small{display:block}.file-drop-field small{grid-column:2;color:var(--muted);font-weight:500}.file-drop-icon{grid-row:1/3;display:grid;place-items:center;width:46px;height:46px;border-radius:13px;background:#173f63;color:#8bd3ff;font-size:25px}.file-drop-field input{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer}.import-format-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0}.import-format-grid>div{padding:13px;border:1px solid var(--line);border-radius:12px;background:#0b192b}.import-format-grid b,.import-format-grid span{display:block}.import-format-grid span{margin-top:5px;color:var(--muted);font-size:12px;line-height:1.45}
@media(max-width:1100px){.mobile-hero{align-items:stretch;flex-direction:column;padding:18px}.mobile-desktop-link{width:100%}.mobile-kpi-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.mobile-launch-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.import-upload-form{grid-template-columns:1fr}.import-upload-form button{width:100%}}
@media(max-width:720px){.mobile-hero h2{font-size:24px}.mobile-kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.mobile-launch-grid{grid-template-columns:1fr}.mobile-launch-card{min-height:88px}.import-format-grid{grid-template-columns:1fr}.file-drop-field{min-height:100px}.mobile-attention-card{margin-bottom:4px}}

/* Grouped estimates, invoices, and reusable line-item catalog */
.fm-estimate-builder{margin-top:14px}.fm-estimate-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.fm-estimate-summary{color:var(--muted);font-size:12px;font-weight:750}.fm-estimate-sections{display:grid;gap:14px}.fm-estimate-section{border:1px solid #365778;border-radius:14px;background:#091827;overflow:visible}.fm-section-header{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:end;padding:14px;background:linear-gradient(135deg,#183a5a,#10263e);border-radius:14px 14px 0 0}.fm-section-title-fields{display:grid;grid-template-columns:minmax(180px,.8fr) minmax(220px,1.2fr);gap:10px}.fm-section-title-fields label{margin:0}.fm-section-tools{display:flex;align-items:center;justify-content:flex-end;gap:7px;flex-wrap:wrap}.fm-section-tools>b{margin-right:4px;color:#7fe6b8;font-size:18px}.fm-catalog-add{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:end;padding:13px 14px;border-bottom:1px solid var(--line)}.fm-catalog-search{position:relative}.fm-catalog-results{position:absolute;z-index:1300;top:calc(100% + 5px);left:0;right:0;max-height:330px;overflow:auto;border:1px solid #4d759b;border-radius:11px;background:#071321;box-shadow:0 18px 50px #000b}.fm-catalog-option{display:block;width:100%;min-height:0;padding:11px 12px;border-radius:0;border-bottom:1px solid #203a57;background:transparent;text-align:left}.fm-catalog-option:hover,.fm-catalog-option:focus{background:#173d60}.fm-catalog-option b,.fm-catalog-option small{display:block}.fm-catalog-option small{margin-top:3px;color:var(--muted);font-size:11px}.fm-catalog-message{padding:13px;color:var(--muted)}.fm-catalog-message.bad{color:#ffb4b4}.fm-custom-item{margin:0 14px 14px;padding:14px;border:1px dashed #42698e;border-radius:11px;background:#0c2035}.fm-estimate-lines{display:grid;gap:10px;padding:14px}.fm-estimate-line{border:1px solid #2c4868;border-radius:11px;background:#0b192b;padding:12px}.fm-line-main{display:grid;grid-template-columns:minmax(190px,.75fr) minmax(240px,1.25fr);gap:10px}.fm-line-main textarea{min-height:48px}.fm-line-numbers{display:grid;grid-template-columns:100px 120px 140px minmax(110px,1fr);gap:10px;align-items:end;margin-top:10px}.fm-line-total{min-height:48px;padding:8px 11px;border:1px solid var(--line);border-radius:8px;background:#071321}.fm-line-total span,.fm-line-total b{display:block}.fm-line-total span{color:var(--muted);font-size:10px;text-transform:uppercase}.fm-line-total b{margin-top:3px;font-size:17px}.fm-line-footer{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:10px}.fm-inline-check{display:flex;align-items:center;gap:6px;margin:0}.fm-inline-check input{width:auto;min-height:0}.fm-catalog-origin{margin-right:auto;color:var(--muted);font-size:11px}.fm-empty-lines{padding:18px;text-align:center;color:var(--muted)}.fm-document-section{margin:0 0 16px;border:1px solid var(--line);border-radius:12px;overflow:hidden}.fm-document-section>header{display:flex;justify-content:space-between;gap:12px;align-items:start;padding:13px 14px;background:#122c47}.fm-document-section h3{margin:0}.fm-document-section header small{display:block;margin-top:4px;color:var(--muted)}.fm-document-section .table-wrap{border:0;border-radius:0}.catalog-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:11px}.catalog-card{padding:13px;border:1px solid var(--line);border-radius:12px;background:#0a1728}.catalog-card h3{margin-bottom:5px}.catalog-card small{display:block;color:var(--muted);margin-top:4px}.catalog-price{font-size:20px;color:#7fe6b8;font-weight:850}.catalog-source{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#8eb4d2}
@media(max-width:900px){.fm-section-header{grid-template-columns:1fr}.fm-section-title-fields,.fm-line-main{grid-template-columns:1fr}.fm-section-tools{justify-content:flex-start}.fm-line-numbers{grid-template-columns:1fr 1fr}.fm-line-total{grid-column:1/-1}.fm-catalog-add{grid-template-columns:1fr}.fm-catalog-add>button{width:100%}}
@media(max-width:620px){.fm-estimate-toolbar{align-items:stretch;flex-direction:column}.fm-estimate-toolbar .button,.fm-estimate-toolbar button{width:100%}.fm-section-header{padding:12px}.fm-section-tools{display:grid;grid-template-columns:1fr 1fr}.fm-section-tools>b{grid-column:1/-1}.fm-line-numbers{grid-template-columns:1fr}.fm-line-total{grid-column:auto}.fm-line-footer{display:grid;grid-template-columns:1fr 1fr}.fm-catalog-origin{grid-column:1/-1;margin:0}.fm-catalog-results{position:fixed;left:10px;right:10px;top:auto;bottom:calc(78px + var(--safe-bottom));max-height:55vh}}

/* v4.1 estimate workspace */
.estimate-index-hero{display:flex;justify-content:space-between;align-items:center;gap:18px;background:linear-gradient(135deg,#102c49,#0a1a2e)}.estimate-index-hero h2{margin:5px 0}.estimate-index-hero .eyebrow{color:#72cfff;font-size:11px;font-weight:900;letter-spacing:.12em}.estimate-index-metrics{grid-template-columns:repeat(4,minmax(0,1fr))}.estimate-workflow-step{position:relative;border-left:4px solid #2ea7df}.estimate-step-heading{display:flex;gap:12px;align-items:flex-start;margin-bottom:15px}.estimate-step-heading>span{display:grid;place-items:center;flex:0 0 38px;width:38px;height:38px;border-radius:50%;background:#1d78b7;color:#fff;font-weight:900}.estimate-step-heading h2{margin:0}.estimate-step-heading p{margin:4px 0 0;color:var(--muted)}.estimate-mode-buttons{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}.estimate-mode-buttons button.active{background:#1d78b7;border-color:#5fc5ff;color:#fff}.estimate-mode-panel[hidden]{display:none}.estimate-workflow-submit{display:flex;justify-content:space-between;align-items:center;gap:15px;border-color:#2f775c;background:#0b2a21}.estimate-workflow-submit h2{margin:0 0 4px}.estimate-linked-records{display:grid;grid-template-columns:1fr 1fr;gap:12px}.estimate-linked-records>div{padding:12px;border:1px solid var(--line);border-radius:10px;background:#0a1728}.estimate-linked-records small,.estimate-linked-records b{display:block}.estimate-linked-records small{color:var(--muted);text-transform:uppercase;font-size:10px}.estimate-linked-records b{margin-top:5px}.preline{white-space:pre-line}.two-wide{grid-column:span 2}
@media(max-width:1100px){.estimate-index-hero,.estimate-workflow-submit{align-items:stretch;flex-direction:column}.estimate-index-hero .actions,.estimate-workflow-submit .actions{width:100%}.estimate-index-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.estimate-linked-records{grid-template-columns:1fr}.two-wide{grid-column:auto}}
@media(max-width:720px){.estimate-index-metrics{grid-template-columns:1fr 1fr}.estimate-mode-buttons{display:grid;grid-template-columns:1fr}.estimate-step-heading>span{flex-basis:34px;width:34px;height:34px}.estimate-workflow-step{padding-top:15px}.estimate-workflow-submit .actions{display:grid}}

/* Low-training settings workspace */
.settings-hero{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding:22px;border-color:#39799d;background:linear-gradient(135deg,#123a5a,#0c2238)}.settings-hero h2{font-size:25px;margin:4px 0 7px}.settings-eyebrow{font-size:11px;font-weight:900;letter-spacing:.12em;color:#76d4ff;text-transform:uppercase}.settings-hero-copy{max-width:760px}.settings-hero-copy p{margin:0;color:#c4d6e8;line-height:1.55}.settings-progress{min-width:150px;text-align:center;padding:15px;border:1px solid #477492;border-radius:13px;background:#07192a}.settings-progress strong{display:block;font-size:30px;color:#7fe6b8}.settings-progress small{color:var(--muted)}.settings-section-head{display:flex;align-items:end;justify-content:space-between;gap:12px;margin:24px 0 12px}.settings-section-head h2,.settings-section-head p{margin:0}.settings-section-head p{color:var(--muted)}.settings-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(280px,100%),1fr));gap:13px}.settings-card{display:flex;flex-direction:column;min-height:235px;margin:0;padding:17px}.settings-card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.settings-card-number{display:grid;place-items:center;flex:0 0 34px;width:34px;height:34px;border-radius:50%;background:#1d78b7;color:#fff;font-weight:900}.settings-card h3{font-size:18px;margin:12px 0 6px}.settings-card p{margin:0 0 12px;color:#b9cada;line-height:1.5}.settings-card .settings-summary{margin-top:auto;padding:10px;border-radius:9px;background:#081727;color:var(--muted);font-size:12px}.settings-card .actions{margin-top:12px}.settings-card .button{width:100%}.field-help{display:block;margin-top:5px;color:var(--muted);font-size:11px;line-height:1.4}.required-mark{color:#8bd3ff;font-weight:750}.plain-details{margin-top:14px}.plain-details>summary{min-height:42px;display:flex;align-items:center}.choice-card{padding:13px;border:1px solid var(--line);border-radius:11px;background:#0a1728}.choice-card b,.choice-card small{display:block}.choice-card small{margin-top:5px;color:var(--muted);line-height:1.45}.role-guide{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:9px;margin:12px 0}.role-guide>div{padding:11px;border:1px solid var(--line);border-radius:10px;background:#0a1728}.role-guide b,.role-guide small{display:block}.role-guide small{margin-top:4px;color:var(--muted)}.advanced-banner{border-color:#5c512d;background:#2a2516}.connection-simple-table table{min-width:520px}
.conversation-shell{display:grid;grid-template-columns:minmax(240px,.75fr) minmax(0,1.75fr);gap:14px}.thread-list{display:grid;gap:8px}.thread-link{display:block;padding:12px;border:1px solid var(--line);border-radius:10px;background:#0a1728;color:var(--text)}.thread-link.active{border-color:#4aa9df;background:#123b5a}.thread-link b,.thread-link small{display:block}.thread-link small{margin-top:4px;color:var(--muted)}.staff-message-list{display:grid;gap:10px;max-height:540px;overflow:auto;padding:2px;margin:14px 0}.staff-message{max-width:84%;padding:12px 14px;border:1px solid var(--line);border-radius:13px;background:#0a1728}.staff-message.staff{justify-self:end;border-color:#2c6b58;background:#0d3026}.staff-message.customer{justify-self:start;border-color:#376b91;background:#0d2941}.staff-message-head{display:flex;justify-content:space-between;gap:14px;font-size:12px}.staff-message-head span{color:var(--muted)}.staff-message p{white-space:pre-wrap;margin:7px 0 0;line-height:1.45}.staff-message-delivery{display:block;margin-top:6px;color:var(--muted);font-size:11px}
@media(max-width:720px){.settings-hero{flex-direction:column;padding:18px}.settings-progress{width:100%}.settings-section-head{align-items:flex-start;flex-direction:column}.settings-card{min-height:0}.settings-grid{grid-template-columns:1fr}}
@media(max-width:900px){.conversation-shell{grid-template-columns:1fr}.staff-message{max-width:94%}}

"""


def simple_page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'><meta name='theme-color' content='#081426'><title>{esc(title)} · Floodman Operations</title><meta name='author' content='Josh Aldrich'><meta name='application-name' content='Floodman Operations'>{WORKSPACE_HEAD}{PWA_HEAD}<style>{BASE_CSS}</style>{WORKSPACE_CSS}</head><body><a class='skip-link' href='#fm-main-content'>Skip to main content</a><main id='fm-main-content' class='auth-shell' tabindex='-1'><div class='auth-card'><div class='brand big'>Floodman Operations</div><div class='subbrand'>Created by Josh Aldrich</div>{body}</div></main>{PWA_BODY}</body></html>"""


def layout(
    title: str,
    content: str,
    *,
    active: str = "dashboard",
    notice: str = "",
    setup_complete: bool = False,
    release: str = "",
    user: dict[str, Any] | None = None,
    unread_notifications: int = 0,
) -> str:
    primary_items = [item for item in PRIMARY_NAV if user is None or has_permission(user, item[3])]
    primary_nav = "".join(
        f"<a class={'active' if key == active else ''!r} href='{href}'>{esc(label)}</a>"
        for href, label, key, _permission in primary_items
    )
    nav_parts: list[str] = []
    secondary_keys: set[str] = set()
    for group, items in NAV_GROUPS:
        visible = [item for item in items if user is None or has_permission(user, item[3])]
        if not visible:
            continue
        secondary_keys.update(item[2] for item in visible)
        nav_parts.append(f"<div class='nav-group'>{esc(group)}</div>")
        nav_parts.extend(
            f"<a class={'active' if key == active else ''!r} href='{href}'>{esc(label)}{' ' + badge(unread_notifications, 'warn') if key == 'alerts' and unread_notifications else ''}</a>"
            for href, label, key, _permission in visible
        )
    secondary_nav = "".join(nav_parts)
    more_open = " open" if active in secondary_keys else ""
    nav = f"<div class='primary-nav'>{primary_nav}</div>" + (
        f"<details class='sidebar-more'{more_open}><summary>More tools</summary>{secondary_nav}</details>"
        if secondary_nav else ""
    )
    notice_html = f"<div class='notice'>{esc(notice)}</div>" if notice else ""
    setup_chip = (
        badge("Setup review complete", "good")
        if setup_complete
        else f"<a href='/setup' title='The server is running. Finish the optional operating review checklist.'>{badge('Setup review pending', 'warn')}</a>"
    )
    notification_chip = (
        f"<a href='/office/alerts' aria-label='{unread_notifications} unread staff notifications'>{badge(f'{unread_notifications} unread', 'warn')}</a>"
        if unread_notifications
        else ""
    )
    if user:
        user_box = (
            f"<div class='user-box'><strong>{esc(user.get('name'))}</strong><span class='muted'>{esc(user.get('email'))}</span>"
            f"<div style='margin-top:7px'>{badge(user.get('role'))}</div>"
            "<form method='post' action='/logout'><button class='secondary small'>Sign out</button></form></div>"
        )
        mobile_user = esc(user.get("role") or "Member")
    else:
        user_box = ""
        mobile_user = "Secure operations"

    call_intake_drawer = ""
    if user is not None and has_permission(user, "call_intakes.view"):
        call_intake_drawer = """
<aside id='fm-call-intake-drawer' class='call-intake-drawer' role='dialog' aria-modal='false' aria-labelledby='fm-call-intake-title' aria-describedby='fm-call-intake-reason' aria-hidden='true' inert hidden>
  <div class='call-intake-head'><div><span class='call-intake-kicker'>Live call intake</span><h2 id='fm-call-intake-title' data-call-name>Incoming caller</h2></div><button type='button' class='call-intake-close' data-call-intake-dismiss aria-label='Dismiss call card'>×</button></div>
  <div class='call-intake-identity'><b data-call-phone>Phone unavailable</b><span data-call-status>Active</span></div>
  <div class='call-intake-fact'><small>Reason for calling</small><div id='fm-call-intake-reason' data-call-reason>The assistant is collecting details.</div></div>
  <div class='call-intake-fact'><small>Service property</small><div data-call-property>Still being collected</div></div>
  <div class='actions'><a class='button' data-call-intake-open href='/office/calls'>Open unified call card</a><a class='button secondary' href='/office/calls'>View queue</a></div>
</aside>"""

    mobile_links: list[str] = []
    for href, label, icon, key, permission in MOBILE_PRIMARY:
        if user is not None and not has_permission(user, permission):
            continue
        mobile_links.append(
            f"<a href='{href}' class={'active' if active == key else ''!r}><span class='mobile-nav-icon'>{mobile_icon(icon)}</span><span>{esc(label)}</span></a>"
        )
    mobile_links.append(f"<button type='button' data-mobile-menu aria-label='Open all Floodman tools' aria-expanded='false' aria-controls='fm-office-sidebar'><span class='mobile-nav-icon'>{mobile_icon('menu')}</span><span>More</span></button>")
    mobile_bottom = "".join(mobile_links)

    return f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'><meta name='theme-color' content='#081426'>
<title>{esc(title)} · Floodman Operations</title><meta name='author' content='Josh Aldrich'><meta name='application-name' content='Floodman Operations'>{WORKSPACE_HEAD}{PWA_HEAD}<style>{BASE_CSS}</style>{WORKSPACE_CSS}</head><body>
<a class='skip-link' href='#fm-main-content'>Skip to main content</a>
<div class='mobile-topbar'><div class='mobile-topbar-brand'><span class='mobile-topbar-mark' aria-hidden='true'>F</span><span class='mobile-topbar-copy'><b>Floodman Operations</b><small>{mobile_user}</small></span></div><button class='mobile-menu-button' type='button' data-mobile-menu aria-label='Open navigation' aria-expanded='false' aria-controls='fm-office-sidebar'>{mobile_icon('menu')}</button></div>
<div id='fm-office-backdrop' class='mobile-nav-backdrop' aria-hidden='true' hidden></div>
<div class='shell'><aside id='fm-office-sidebar' class='office-sidebar' aria-label='Floodman tools' aria-hidden='false'>
<div class='sidebar-mobile-head'><div class='brand'>Floodman Operations</div><button class='mobile-close' type='button' data-mobile-menu-close aria-label='Close navigation'>{mobile_icon('close')}</button></div>
<div class='brand desktop-brand'>Floodman Operations</div><div class='subbrand'>Created by Josh Aldrich · {esc(release)}</div><nav>{nav}</nav>
{user_box}
</aside><main id='fm-main-content' tabindex='-1'><header class='page-header'><div><h1>{esc(title)}</h1></div><div class='header-meta actions'>{notification_chip}{setup_chip}</div></header>{notice_html}{content}<footer class='creator-footer'><b>Floodman Operations</b> · Created by Josh Aldrich · <a href='/floodman-third-party-notices.html' target='_blank' rel='noopener'>Third-party notices</a></footer></main></div>
<nav class='mobile-bottom-nav' aria-label='Primary mobile navigation'>{mobile_bottom}</nav>{call_intake_drawer}<script>{OFFICE_JS}</script>{PWA_BODY}</body></html>"""
