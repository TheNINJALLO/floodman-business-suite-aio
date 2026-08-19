(() => {
  'use strict';
  if (window.__FLOODMAN_ROOMFLOW_PANEL__) return;
  const params = new URLSearchParams(window.location.search);
  if (!window.location.pathname.startsWith('/roomflow/') && params.get('floodmanPanel') !== '1') return;
  window.__FLOODMAN_ROOMFLOW_PANEL__ = true;

  const RELEASE = '4.7.0';
  const LINK_KEY = 'floodman_roomflow_links_v2';
  const ESTIMATE_KEY = 'floodman_roomflow_estimate_ids_v1';
  const GUIDE_KEY = 'floodman_roomflow_quick_start_dismissed_v1';
  const API = '/office/api/roomflow';
  const appState = () => window.state || {};
  const integration = () => window.RoomFlowIntegrations || null;
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const sleep = (ms) => new Promise(resolve => window.setTimeout(resolve, ms));
  const model = { contact: null, property: null, notes: [], jobs: [], workspaces: [], activeWorkspace: null, searchTimer: null, propertyTimer: null, catalogTimer: null, lastJobKey: '', lastEstimateSignature: '', syncing: false, workspaceBusy: false, activeEstimateSection: '' };


  const SNAPSHOT_KEYS = [
    'schemaVersion','currentStep','guidedStep3Mode','currentLevelId','levels','rooms','walls','roomConnections',
    'doors','windows','openings','stairs','floorHatches','utilities','sumpPumps','dehumidifiers','dischargeLines',
    'interiorPipes','stanchions','mainBeams','capturedMeasurements','costing','createdTimestamp','updatedTimestamp',
    'revisionNumber','leadIntake','currentJobName','jobId','syncState','floodmanContactId','floodmanPropertyId',
    'floodmanEstimateId','floodmanEstimateUrl','floodmanLink','floodmanRoomFlowJobId','captureSchemaVersion','captureRevision'
  ];
  function roomflowSnapshot() {
    const state = appState(); const result = {};
    for (const key of SNAPSHOT_KEYS) if (state[key] !== undefined) result[key] = JSON.parse(JSON.stringify(state[key]));
    result.schemaVersion = result.schemaVersion || 'floodman-roomflow-4.4.0';
    result.updatedTimestamp = Date.now();
    return result;
  }

  function roomflowLayoutDataUrl() {
    const candidates = [
      document.getElementById('sketch-canvas'),
      document.querySelector('#floor-plan-canvas'),
      document.querySelector('#three-container canvas'),
      document.querySelector('canvas[data-roomflow-layout]'),
      document.querySelector('canvas')
    ].filter(Boolean);
    for (const canvas of candidates) {
      try {
        if (canvas.width > 20 && canvas.height > 20) return canvas.toDataURL('image/jpeg', 0.88);
      } catch (_) {}
    }
    return '';
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }
  const asText = value => String(value == null ? '' : value).trim();
  const cents = value => Math.round((Number(value) || 0) * 100);
  const money = value => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format((Number(value) || 0) / 100);
  function dateTime(value) {
    if (!value) return '';
    try { return new Intl.DateTimeFormat('en-US', { timeZone: 'America/Detroit', dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)); }
    catch (_) { return String(value); }
  }
  function uuid() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return `rf-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
  }
  function roomflowJobId() {
    const state = appState();
    return asText(integration()?.currentJobId?.() || state.jobId || state.currentJobName || 'untitled-job');
  }
  function currentJobKey() {
    return `${asText(model.activeWorkspace?.id || 'default')}:${roomflowJobId()}`;
  }
  function loadMap(key) { try { return JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch (_) { return {}; } }
  function saveMap(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {} }
  function linkedRecord() {
    const map = loadMap(LINK_KEY);
    return map[currentJobKey()] || ((model.workspaces.length === 1 || model.activeWorkspace?.is_default) ? map[roomflowJobId()] : null) || null;
  }
  function saveLink() {
    const map = loadMap(LINK_KEY);
    map[currentJobKey()] = { contact_id: model.contact?.id || null, property_id: model.property?.id || null, updated_at: new Date().toISOString() };
    saveMap(LINK_KEY, map);
    appState().floodmanLink = map[currentJobKey()];
    if (typeof window.autosaveJob === 'function') window.autosaveJob();
    updateJobChip();
  }
  function estimateIdentity() {
    const map = loadMap(ESTIMATE_KEY); const key = currentJobKey();
    if (!map[key] && (model.workspaces.length === 1 || model.activeWorkspace?.is_default) && map[roomflowJobId()]) {
      map[key] = map[roomflowJobId()]; saveMap(ESTIMATE_KEY, map);
    }
    if (!map[key]) { map[key] = uuid(); saveMap(ESTIMATE_KEY, map); }
    return map[key];
  }

  async function fetchJson(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin', cache: 'no-store', ...options,
      headers: { accept: 'application/json', ...(options.headers || {}) },
    });
    const contentType = response.headers.get('content-type') || '';
    if (response.redirected && /\/login(?:\?|$)/.test(response.url)) {
      const error = new Error('Your Floodman session has expired. Sign in again, then reopen RoomFlow.'); error.code = 'AUTH'; throw error;
    }
    const payload = contentType.includes('application/json') ? await response.json() : { detail: (await response.text()).slice(0, 500) };
    if (!response.ok) throw new Error(payload.detail || payload.message || `Floodman returned HTTP ${response.status}`);
    return payload;
  }

  function setStatus(message, kind = 'info') {
    const node = $('#fm-rf-status'); if (!node) return;
    node.replaceChildren(); node.className = `fm-rf-status ${kind} ${message ? 'is-open' : ''}`;
    if (!message) return;
    const copy = document.createElement('span'); copy.textContent = message;
    const close = document.createElement('button'); close.type = 'button'; close.className = 'fm-rf-status-close'; close.setAttribute('aria-label', 'Dismiss message'); close.textContent = '×'; close.addEventListener('click', () => setStatus(''));
    node.append(copy, close);
  }
  function guideDismissed() { try { return localStorage.getItem(GUIDE_KEY) === '1'; } catch (_) { return false; } }
  function showGuide(show = true) {
    const guide = $('#fm-rf-quick-start'); if (!guide) return;
    guide.hidden = !show;
    try { if (show) localStorage.removeItem(GUIDE_KEY); else localStorage.setItem(GUIDE_KEY, '1'); } catch (_) {}
  }
  function updateGuide() {
    const readiness = {
      customer: Boolean(model.contact),
      property: Boolean(model.property),
      scope: normalizeLines().length > 0,
      save: Boolean(appState().floodmanEstimateId),
    };
    $$('[data-guide-step]').forEach(node => {
      const complete = Boolean(readiness[node.dataset.guideStep]);
      node.classList.toggle('is-complete', complete);
      const mark = node.querySelector('b'); if (mark) mark.textContent = complete ? '✓' : node.dataset.guideNumber || '•';
    });
    const company = $('#fm-rf-guide-company');
    if (company) company.textContent = model.activeWorkspace?.name ? `Company: ${model.activeWorkspace.name}` : 'Loading company…';
  }
  function workspaceOptions() {
    if (!model.workspaces.length) return '<option value="">No Floodman companies available</option>';
    return model.workspaces.map(workspace => `<option value="${escapeHtml(workspace.id)}" ${workspace.id === model.activeWorkspace?.id ? 'selected' : ''}>${escapeHtml(workspace.name || 'Floodman')}</option>`).join('');
  }
  function renderWorkspaceControls() {
    for (const select of [$('#fm-rf-workspace-select'), document.getElementById('more-company-switcher')].filter(Boolean)) {
      const focused = document.activeElement === select;
      select.innerHTML = workspaceOptions();
      select.value = model.activeWorkspace?.id || '';
      select.disabled = model.workspaceBusy;
      if (focused) select.focus();
    }
    const label = $('#fm-rf-workspace-label');
    if (label) label.textContent = model.activeWorkspace?.name || 'Loading company…';
  }
  function applyWorkspaceContext(payload = {}) {
    model.workspaces = Array.isArray(payload.workspaces) ? payload.workspaces : (Array.isArray(payload.items) ? payload.items : model.workspaces);
    const selectedId = asText(payload.selected_workspace_id || payload.active_workspace?.id);
    model.activeWorkspace = payload.active_workspace || model.workspaces.find(item => String(item.id) === selectedId) || model.workspaces[0] || null;
    const state = appState();
    if (model.activeWorkspace) {
      state.currentOrganization = { ...model.activeWorkspace, role: 'FLOODMAN' };
      state.userOrganizations = model.workspaces.map(item => ({ ...item, role: 'FLOODMAN' }));
    }
    renderWorkspaceControls();
  }
  async function refreshWorkspaceContext() {
    const data = await fetchJson(`${API}/context`);
    applyWorkspaceContext(data);
    return data;
  }
  async function changeWorkspace(workspaceId) {
    const selected = asText(workspaceId);
    if (!selected || selected === model.activeWorkspace?.id || model.workspaceBusy) return;
    model.workspaceBusy = true; renderWorkspaceControls(); setStatus('Switching Floodman company…', 'info');
    try {
      const data = await fetchJson(`${API}/workspaces/${encodeURIComponent(selected)}/select`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' });
      applyWorkspaceContext(data); model.contact = null; model.property = null; model.notes = []; model.lastJobKey = ''; renderCustomer(); renderProperty(); await restoreLink(); await refreshJobs();
      setStatus(`Using ${model.activeWorkspace?.name || 'the selected Floodman company'}.`, 'good');
    } catch (error) { setStatus(error.message, error.code === 'AUTH' ? 'warn' : 'bad'); }
    finally { model.workspaceBusy = false; renderWorkspaceControls(); }
  }
  async function createWorkspace(input) {
    const name = asText(input?.value);
    if (name.length < 2) return setStatus('Enter a company name with at least two characters.', 'warn');
    if (model.workspaceBusy) return;
    model.workspaceBusy = true; renderWorkspaceControls(); setStatus('Creating Floodman company…', 'info');
    try {
      const data = await fetchJson(`${API}/workspaces`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name, timezone: 'America/Detroit' }),
      });
      applyWorkspaceContext(data); model.contact = null; model.property = null; model.notes = []; model.lastJobKey = ''; if (input) input.value = ''; renderCustomer(); renderProperty(); await restoreLink(); await refreshJobs();
      setStatus(`Company “${model.activeWorkspace?.name || name}” is ready. No separate RoomFlow account is required.`, 'good');
    } catch (error) { setStatus(error.message, error.code === 'AUTH' ? 'warn' : 'bad'); }
    finally { model.workspaceBusy = false; renderWorkspaceControls(); }
  }
  function panelOpen(open = true) {
    const root = document.documentElement;
    const panel = $('#fm-roomflow-panel');
    root.classList.toggle('fm-rf-panel-dismissed', !open && root.classList.contains('fm-rf-panel-pinned'));
    panel?.classList.toggle('is-open', open);
    $('#fm-roomflow-backdrop')?.classList.toggle('is-open', open && !root.classList.contains('fm-rf-panel-pinned'));
    panel?.setAttribute('aria-hidden', open ? 'false' : 'true');
    if ('inert' in HTMLElement.prototype && panel) panel.inert = !open;
  }
  function updateJobChip() {
    const value = model.contact?.name || appState().currentJobName || 'No customer selected';
    const chip = $('#fm-rf-job-chip'); if (chip) chip.textContent = value;
  }
  function setInputValue(id, value) {
    const input = document.getElementById(id); if (!input) return;
    input.value = value || ''; input.dispatchEvent(new Event('input', { bubbles: true }));
  }
  function applyCustomerToRoomFlow() {
    if (!model.contact) return;
    const state = appState(); state.costing = state.costing || {};
    Object.assign(state.costing, { customerName: model.contact.name || '', customerEmail: model.contact.email || '', customerPhone: model.contact.phone || '' });
    state.floodmanContactId = model.contact.id;
    setInputValue('customer-name', model.contact.name || '');
    if (!model.property && model.contact.mailing_address?.formatted) {
      state.costing.customerAddress = model.contact.mailing_address.formatted;
      setInputValue('customer-address', model.contact.mailing_address.formatted);
    }
    window.triggerAutosave?.();
  }
  function applyPropertyToRoomFlow() {
    if (!model.property) return;
    const state = appState(); state.costing = state.costing || {};
    const address = model.property.address || {};
    const formatted = address.formatted || [address.street, address.city, [address.state, address.postal_code].filter(Boolean).join(' ')].filter(Boolean).join(', ');
    Object.assign(state.costing, { serviceStreet: address.street || '', serviceCity: address.city || '', serviceState: address.state || 'MI', servicePostalCode: address.postal_code || '', customerAddress: formatted });
    state.floodmanPropertyId = model.property.id;
    setInputValue('customer-address', formatted);
    const api = integration();
    if (api) {
      api.currentServiceStreet = address.street || ''; api.currentServiceCity = address.city || '';
      api.currentServiceState = address.state || 'MI'; api.currentServicePostalCode = address.postal_code || '';
      api.saveEstimateStorage?.(); api.renderEstimateBuilder?.();
    }
    window.triggerAutosave?.();
  }

  function renderNotes() {
    const host = $('#fm-rf-note-list'); if (!host) return;
    if (!model.contact) { host.innerHTML = ''; return; }
    host.innerHTML = (model.notes || []).slice(0, 8).map(note => `
      <article class="fm-rf-note ${note.pinned ? 'is-pinned' : ''}">
        <p>${escapeHtml(note.body || note.note || '')}</p>
        <small>${escapeHtml(note.category || 'GENERAL')} · ${escapeHtml(note.author_name || 'Floodman staff')} · ${escapeHtml(dateTime(note.created_at))}</small>
      </article>`).join('') || '<p class="fm-rf-card-intro">No customer notes yet.</p>';
  }
  function renderCustomer() {
    const host = $('#fm-rf-customer-summary'), propertyInput = $('#fm-rf-property-search'); if (!host) return;
    if (!model.contact) {
      host.innerHTML = '<p class="fm-rf-card-intro">Search for an existing Floodman customer. The sketch, estimate, notes, documents, and billing history will stay on one customer file.</p>';
      if (propertyInput) { propertyInput.disabled = true; propertyInput.value = ''; }
      renderNotes(); return;
    }
    const c = model.contact, address = c.mailing_address?.formatted || '';
    host.innerHTML = `<div class="fm-rf-summary">
      <div class="fm-rf-summary-row"><span>Customer</span><strong>${escapeHtml(c.name || '')}</strong></div>
      <div class="fm-rf-summary-row"><span>Email</span><strong>${escapeHtml(c.email || 'Not provided')}</strong></div>
      <div class="fm-rf-summary-row"><span>Phone</span><strong>${escapeHtml(c.phone || 'Not provided')}</strong></div>
      <div class="fm-rf-summary-row"><span>Mailing</span><strong>${escapeHtml(address || 'Not provided')}</strong></div>
      <div class="fm-rf-summary-row"><span>Open balance</span><strong>${escapeHtml(money(c.open_balance_cents || 0))}</strong></div>
    </div><div class="fm-rf-tags">${(c.tags || []).map(tag => `<span class="fm-rf-tag">${escapeHtml(tag)}</span>`).join('') || '<span class="fm-rf-card-intro">No tags</span>'}</div>
    <div class="fm-rf-button-row"><a class="fm-rf-button secondary" href="${escapeHtml(c.url || `/office/contacts/${encodeURIComponent(c.id)}`)}" target="_top">Open customer file</a><a class="fm-rf-button secondary" href="/office/properties?contact_id=${encodeURIComponent(c.id)}" target="_top">Add property</a><button type="button" class="fm-rf-button secondary" id="fm-rf-change-customer">Change customer</button></div>`;
    if (propertyInput) propertyInput.disabled = false;
    $('#fm-rf-change-customer')?.addEventListener('click', clearCustomer);
    const tagsInput = $('#fm-rf-tags-input'); if (tagsInput) tagsInput.value = (c.tags || []).join(', ');
    renderNotes();
  }
  function renderProperty() {
    const host = $('#fm-rf-property-summary'); if (!host) return;
    if (!model.property) { host.innerHTML = '<p class="fm-rf-card-intro">Choose the service property. Results are limited to the selected customer.</p>'; return; }
    const p = model.property;
    host.innerHTML = `<div class="fm-rf-summary">
      <div class="fm-rf-summary-row"><span>Property</span><strong>${escapeHtml(p.name || 'Service property')}</strong></div>
      <div class="fm-rf-summary-row"><span>Address</span><strong>${escapeHtml(p.address?.formatted || '')}</strong></div>
      <div class="fm-rf-summary-row"><span>Type</span><strong>${escapeHtml(p.property_type || 'Not specified')}</strong></div>
      <div class="fm-rf-summary-row"><span>Claim</span><strong>${escapeHtml(p.claim_number || 'None')}</strong></div>
    </div><div class="fm-rf-button-row"><a class="fm-rf-button secondary" href="${escapeHtml(p.url || `/office/properties/${encodeURIComponent(p.id)}`)}" target="_top">Open property file</a><button type="button" class="fm-rf-button secondary" id="fm-rf-change-property">Change property</button></div>`;
    $('#fm-rf-change-property')?.addEventListener('click', clearProperty);
  }
  function showResults(host, items, onSelect, emptyText = 'No matches found', emptyHref = '', emptyAction = '') {
    if (!host) return; host.innerHTML = '';
    if (!items.length) { host.innerHTML = `<div class="fm-rf-result"><b>${escapeHtml(emptyText)}</b><small>Check the spelling or add the missing record in Floodman.</small>${emptyHref ? `<a class="fm-rf-empty-action" href="${escapeHtml(emptyHref)}" target="_top">${escapeHtml(emptyAction || 'Add record')}</a>` : ''}</div>`; host.classList.add('is-open'); return; }
    for (const item of items) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'fm-rf-result';
      button.innerHTML = `<b>${escapeHtml(item.label || '')}</b><small>${escapeHtml(item.meta || '')}</small>`;
      button.addEventListener('click', () => { host.classList.remove('is-open'); onSelect(item); }); host.appendChild(button);
    }
    host.classList.add('is-open');
  }
  async function searchCustomers(query) {
    const host = $('#fm-rf-customer-results'); if (query.trim().length < 2) { host?.classList.remove('is-open'); return; }
    try { const data = await fetchJson(`/office/api/search/contacts?q=${encodeURIComponent(query)}&workspace_id=${encodeURIComponent(model.activeWorkspace?.id || '')}&limit=25`); showResults(host, data.items || [], item => selectCustomer(item.id), 'No customer matches', '/office/contacts?new=1', 'Add a customer in Floodman'); }
    catch (error) { setStatus(error.message, error.code === 'AUTH' ? 'warn' : 'bad'); }
  }
  async function searchProperties(query) {
    const host = $('#fm-rf-property-results'); if (!model.contact) return;
    try { const data = await fetchJson(`/office/api/search/properties?q=${encodeURIComponent(query)}&contact_id=${encodeURIComponent(model.contact.id)}&workspace_id=${encodeURIComponent(model.activeWorkspace?.id || '')}&limit=25`); showResults(host, data.items || [], item => selectProperty(item.id), 'No properties found for this customer', `/office/properties?contact_id=${encodeURIComponent(model.contact.id)}`, 'Add a service property'); }
    catch (error) { setStatus(error.message, error.code === 'AUTH' ? 'warn' : 'bad'); }
  }
  async function selectCustomer(contactId, { silent = false } = {}) {
    try {
      setStatus('Loading customer file…', 'info'); const data = await fetchJson(`${API}/customers/${encodeURIComponent(contactId)}`);
      model.contact = data.customer; model.notes = data.notes || [];
      if (model.property && model.property.contact_id !== model.contact.id) model.property = null;
      $('#fm-rf-customer-search').value = model.contact.name || '';
      applyCustomerToRoomFlow(); saveLink(); renderCustomer(); renderProperty(); setStatus(silent ? '' : 'Customer linked to this RoomFlow job.', 'good');
    } catch (error) { setStatus(error.message, error.code === 'AUTH' ? 'warn' : 'bad'); }
  }
  async function selectProperty(propertyId, { silent = false } = {}) {
    if (!model.contact) return;
    try {
      setStatus('Loading service property…', 'info'); const data = await fetchJson(`${API}/properties/${encodeURIComponent(propertyId)}`);
      if (String(data.property?.contact_id || '') !== String(model.contact.id)) throw new Error('That property is not assigned to the selected customer.');
      model.property = data.property; $('#fm-rf-property-search').value = model.property.name || model.property.address?.formatted || '';
      applyPropertyToRoomFlow(); saveLink(); renderProperty(); setStatus(silent ? '' : 'Service property linked to this RoomFlow job.', 'good');
    } catch (error) { setStatus(error.message, error.code === 'AUTH' ? 'warn' : 'bad'); }
  }
  function clearProperty() { model.property = null; const input = $('#fm-rf-property-search'); if (input) input.value = ''; renderProperty(); saveLink(); }
  function clearCustomer() { model.contact = null; model.property = null; model.notes = []; const c = $('#fm-rf-customer-search'), p = $('#fm-rf-property-search'); if (c) c.value = ''; if (p) p.value = ''; renderCustomer(); renderProperty(); saveLink(); }
  async function addNote() {
    if (!model.contact) return setStatus('Select a customer before adding a note.', 'warn');
    const body = asText($('#fm-rf-note-body')?.value); if (!body) return setStatus('Enter a note first.', 'warn');
    try {
      const data = await fetchJson(`${API}/customers/${encodeURIComponent(model.contact.id)}/notes`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ body, category: $('#fm-rf-note-category')?.value || 'JOB', pinned: Boolean($('#fm-rf-note-pinned')?.checked) }) });
      model.notes = data.notes || []; $('#fm-rf-note-body').value = ''; $('#fm-rf-note-pinned').checked = false; renderNotes(); setStatus('Customer note saved.', 'good');
    } catch (error) { setStatus(error.message, 'bad'); }
  }
  async function saveTags() {
    if (!model.contact) return setStatus('Select a customer before changing tags.', 'warn');
    const tags = asText($('#fm-rf-tags-input')?.value).split(',').map(value => value.trim()).filter(Boolean);
    try { const data = await fetchJson(`${API}/customers/${encodeURIComponent(model.contact.id)}/tags`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ tags }) }); model.contact.tags = data.tags || []; renderCustomer(); setStatus('Customer tags updated.', 'good'); }
    catch (error) { setStatus(error.message, 'bad'); }
  }
  function normalizeLines() {
    const api = integration();
    const raw = Array.isArray(api?.currentLines) && api.currentLines.length ? api.currentLines : (Array.isArray(appState().costing?.customItems) ? appState().costing.customItems : []);
    return raw.map((line, index) => {
      const quantity = Number(line.quantity ?? line.qty ?? 1) || 0;
      const unitPrice = Number(line.unit_price ?? line.unitPrice ?? line.unitCost ?? line.price ?? 0) || 0;
      const sectionName = asText(line.section_name || line.sectionName || api?.currentEstimateHeader || line.category || 'Scope of Work');
      return {
        line_id: asText(line.roomflow_line_id || line.roomflowLineId || line.id || `line-${index + 1}`),
        section_id: asText(line.section_id || line.sectionId || ''), section_name: sectionName,
        catalog_item_id: asText(line.catalog_item_id || line.catalogItemId || ''),
        name: asText(line.name || line.description || `Line item ${index + 1}`), description: asText(line.description || line.name || ''),
        quantity, unit_price_cents: cents(unitPrice), line_total_cents: Math.round(quantity * cents(unitPrice)),
        taxable: Boolean(line.taxable || line.applyTax), optional: Boolean(line.optional), selected: line.selected !== false,
        unit: asText(line.unit || 'each'), category: asText(line.category || sectionName || 'other'), pricing_method: asText(line.pricing_method || line.pricingMethod || 'fixed'), sort_order: Number(line.sort_order ?? line.sortOrder ?? index) || 0,
        pricing_reference: asText(line.pricing_reference || ''), pricing_source: asText(line.pricing_source || ''),
        pricing_price_list: asText(line.pricing_price_list || ''), pricing_effective_date: asText(line.pricing_effective_date || ''),
        pricing_market: asText(line.pricing_market || ''),
      };
    }).filter(line => line.quantity > 0 && line.unit_price_cents >= 0 && line.line_total_cents >= 0);
  }

  function roomFlowEstimateApi() {
    const api = integration();
    if (!api) return null;
    if (!Array.isArray(api.currentLines)) api.currentLines = [];
    return api;
  }

  function estimateSectionNames() {
    const api = roomFlowEstimateApi();
    if (!api) return ['Waterproofing'];
    const values = [];
    const add = (value) => { const name = asText(value); if (name && !values.some(item => item.toLowerCase() === name.toLowerCase())) values.push(name); };
    add(api.currentEstimateHeader);
    api.currentLines.forEach(line => add(line.section_name || line.sectionName || line.category));
    if (!values.length) add('Waterproofing');
    if (!model.activeEstimateSection || !values.some(item => item.toLowerCase() === model.activeEstimateSection.toLowerCase())) model.activeEstimateSection = values[0];
    return values;
  }

  function estimateScopeSignature() {
    const api = roomFlowEstimateApi();
    if (!api) return '';
    return JSON.stringify((api.currentLines || []).map(line => [line.roomflow_line_id || line.id, line.section_name, line.name, line.quantity, line.unit_price]));
  }

  function persistEstimateScope() {
    const api = roomFlowEstimateApi(); if (!api) return;
    api.currentEstimateHeader = model.activeEstimateSection || api.currentEstimateHeader || 'Waterproofing';
    api.currentLines.forEach((line, index) => {
      line.section_name = asText(line.section_name || model.activeEstimateSection || 'Waterproofing');
      line.sort_order = Number(line.sort_order ?? index) || index;
    });
    api.syncAllLinesToMainEstimate?.();
    api.saveEstimateStorage?.();
    api.refreshMainEstimate?.();
    window.autosaveJob?.();
    model.lastEstimateSignature = estimateScopeSignature();
  }

  function addCatalogItemToEstimate(item) {
    const api = roomFlowEstimateApi(); if (!api) return;
    const section = model.activeEstimateSection || estimateSectionNames()[0] || 'Waterproofing';
    const pricing = item.formula?.xactimate || {};
    const line = {
      roomflow_line_id: uuid(), catalog_item_id: item.id || null,
      name: asText(item.name || 'Catalog item'), description: asText(item.description || ''),
      section_name: section, category: asText(item.category || section), pricing_method: asText(item.pricing_method || 'fixed'),
      quantity: 1, unit: asText(item.unit || 'each'), unit_price: Number(item.unit_price_cents || 0) / 100,
      taxable: Boolean(item.taxable), optional: false, selected: true, sort_order: api.currentLines.length,
      pricing_reference: asText(pricing.code || ''), pricing_source: asText(item.source_provider || ''),
      pricing_price_list: asText(pricing.price_list || ''), pricing_effective_date: asText(pricing.effective_date || ''),
      pricing_market: asText(pricing.market || ''),
    };
    api.currentLines.push(line);
    persistEstimateScope();
    renderEstimateScope();
    setStatus(`${line.name} added under ${section}.`, 'good');
  }

  async function searchEstimateCatalog(query = '') {
    const host = $('#fm-rf-estimate-catalog-results'); if (!host) return;
    host.innerHTML = '<div class="fm-rf-result"><b>Searching catalog…</b></div>'; host.classList.add('is-open');
    try {
      const data = await fetchJson(`/office/api/catalog/items?q=${encodeURIComponent(query)}&limit=40`);
      const items = data.items || [];
      host.innerHTML = '';
      if (!items.length) {
        host.innerHTML = '<div class="fm-rf-result"><b>No matching line items</b><small>Add a custom item below and Floodman will save it for future estimates.</small></div>';
        return;
      }
      for (const item of items) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'fm-rf-result';
        const pricing = item.formula?.xactimate || {};
        button.innerHTML = `<b>${escapeHtml(pricing.code ? `${pricing.code} · ${item.name || ''}` : item.name || '')}</b><small>${escapeHtml(item.default_section || item.category || 'General Services')} · ${escapeHtml(item.unit || 'each')} · ${escapeHtml(money(item.unit_price_cents || 0))}</small>`;
        button.addEventListener('click', () => { host.classList.remove('is-open'); addCatalogItemToEstimate(item); });
        host.appendChild(button);
      }
    } catch (error) {
      host.innerHTML = `<div class="fm-rf-result"><b>Catalog search failed</b><small>${escapeHtml(error.message)}</small></div>`;
    }
  }

  async function addCustomEstimateItem() {
    const name = asText($('#fm-rf-custom-item-name')?.value);
    if (!name) { $('#fm-rf-custom-item-name')?.focus(); return setStatus('Enter the custom line-item name.', 'warn'); }
    const section = model.activeEstimateSection || estimateSectionNames()[0] || 'Waterproofing';
    const payload = {
      name,
      description: asText($('#fm-rf-custom-item-description')?.value),
      category: asText($('#fm-rf-custom-item-category')?.value) || section,
      default_section: section,
      unit: asText($('#fm-rf-custom-item-unit')?.value) || 'each',
      unit_price_cents: Math.round((Number($('#fm-rf-custom-item-price')?.value) || 0) * 100),
      taxable: Boolean($('#fm-rf-custom-item-taxable')?.checked),
      source_provider: 'FLOODMAN_CUSTOM',
    };
    const button = $('#fm-rf-save-custom-item'); if (button) { button.disabled = true; button.textContent = 'Saving…'; }
    try {
      const data = await fetchJson('/office/api/catalog/items', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
      addCatalogItemToEstimate(data.item || payload);
      ['fm-rf-custom-item-name','fm-rf-custom-item-description'].forEach(id => { const input = $(`#${id}`); if (input) input.value = ''; });
      setStatus(`${name} saved to the catalog and added under ${section}.`, 'good');
    } catch (error) { setStatus(error.message, 'bad'); }
    finally { if (button) { button.disabled = false; button.textContent = 'Add & save to catalog'; } }
  }

  function renderEstimateScope() {
    const host = $('#fm-rf-estimate-scope'); if (!host) return;
    const api = roomFlowEstimateApi();
    if (!api) { host.innerHTML = '<p class="fm-rf-card-intro">RoomFlow estimate tools are still loading.</p>'; return; }
    const sections = estimateSectionNames();
    const optionHtml = sections.map(name => `<option value="${escapeHtml(name)}" ${name === model.activeEstimateSection ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('');
    const lines = api.currentLines || [];
    const grouped = sections.map(name => ({ name, lines: lines.filter(line => asText(line.section_name || line.category) === name) }));
    host.innerHTML = `<div class="fm-rf-estimate-head-controls"><div class="fm-rf-field"><label>Active estimate header</label><select class="fm-rf-select" id="fm-rf-active-estimate-section">${optionHtml}</select></div><div class="fm-rf-field"><label>Add another header</label><div class="fm-rf-inline"><input class="fm-rf-input" id="fm-rf-new-estimate-section" placeholder="Mold Remediation"><button class="fm-rf-button secondary" type="button" id="fm-rf-add-estimate-section">Add</button></div></div></div>
      <div class="fm-rf-quick-headers"><button type="button" data-quick-header="Waterproofing">Waterproofing</button><button type="button" data-quick-header="Mold Remediation">Mold Remediation</button><button type="button" data-quick-header="Demolition">Demolition</button><button type="button" data-quick-header="Landfill Fees">Landfill Fees</button></div>
      <div class="fm-rf-field"><label>Find a reusable line item</label><input class="fm-rf-input" id="fm-rf-estimate-catalog-search" autocomplete="off" placeholder="Search services, materials, equipment, disposal…"><div class="fm-rf-results" id="fm-rf-estimate-catalog-results"></div></div>
      <details class="fm-rf-custom-estimate-item"><summary>Add a custom line item</summary><div class="fm-rf-custom-grid"><div class="fm-rf-field"><label>Item name</label><input class="fm-rf-input" id="fm-rf-custom-item-name"></div><div class="fm-rf-field"><label>Category</label><input class="fm-rf-input" id="fm-rf-custom-item-category" value="${escapeHtml(model.activeEstimateSection)}"></div><div class="fm-rf-field"><label>Unit</label><input class="fm-rf-input" id="fm-rf-custom-item-unit" value="each"></div><div class="fm-rf-field"><label>Unit price</label><input class="fm-rf-input" id="fm-rf-custom-item-price" type="number" min="0" step="0.01" value="0.00"></div><div class="fm-rf-field fm-rf-wide"><label>Description</label><textarea class="fm-rf-textarea" id="fm-rf-custom-item-description"></textarea></div><label class="fm-rf-check"><input type="checkbox" id="fm-rf-custom-item-taxable"> Taxable</label></div><button class="fm-rf-button" type="button" id="fm-rf-save-custom-item">Add & save to catalog</button></details>
      <div class="fm-rf-estimate-groups">${grouped.map(group => {
        const subtotal = group.lines.reduce((sum, line) => sum + Math.round((Number(line.quantity || 0)) * (Number(line.unit_price || 0)) * 100), 0);
        return `<section class="fm-rf-estimate-group"><header><div><b>${escapeHtml(group.name)}</b><small>${group.lines.length} item${group.lines.length === 1 ? '' : 's'}</small></div><strong>${escapeHtml(money(subtotal))}</strong></header>${group.lines.map(line => {
          const index = lines.indexOf(line);
          return `<article class="fm-rf-estimate-line" data-estimate-line-index="${index}"><div><b>${escapeHtml(line.name || line.description || 'Line item')}</b><small>${escapeHtml(line.description || '')}</small></div><select class="fm-rf-select" data-estimate-line-field="section_name">${sections.map(name => `<option value="${escapeHtml(name)}" ${name === asText(line.section_name || line.category) ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('')}</select><div class="fm-rf-line-numbers"><input class="fm-rf-input" data-estimate-line-field="quantity" type="number" min="0.001" step="0.001" value="${Number(line.quantity || 1)}"><input class="fm-rf-input" data-estimate-line-field="unit_price" type="number" min="0" step="0.01" value="${Number(line.unit_price || 0).toFixed(2)}"><button class="fm-rf-button secondary" type="button" data-remove-estimate-line>Remove</button></div></article>`;
        }).join('') || '<p class="fm-rf-card-intro">No line items in this header yet.</p>'}</section>`;
      }).join('')}</div>`;

    $('#fm-rf-active-estimate-section')?.addEventListener('change', event => { model.activeEstimateSection = event.target.value; api.currentEstimateHeader = model.activeEstimateSection; renderEstimateScope(); });
    $('#fm-rf-add-estimate-section')?.addEventListener('click', () => {
      const input = $('#fm-rf-new-estimate-section'); const name = asText(input?.value);
      if (!name) return;
      model.activeEstimateSection = name; api.currentEstimateHeader = name; if (input) input.value = ''; renderEstimateScope();
    });
    $$('[data-quick-header]', host).forEach(button => button.addEventListener('click', () => { model.activeEstimateSection = button.dataset.quickHeader; api.currentEstimateHeader = model.activeEstimateSection; renderEstimateScope(); }));
    $('#fm-rf-estimate-catalog-search')?.addEventListener('input', event => { clearTimeout(model.catalogTimer); model.catalogTimer = setTimeout(() => searchEstimateCatalog(event.target.value), 220); });
    $('#fm-rf-estimate-catalog-search')?.addEventListener('focus', event => searchEstimateCatalog(event.target.value));
    $('#fm-rf-save-custom-item')?.addEventListener('click', addCustomEstimateItem);
    $$('.fm-rf-estimate-line', host).forEach(row => {
      const line = api.currentLines[Number(row.dataset.estimateLineIndex)]; if (!line) return;
      row.querySelectorAll('[data-estimate-line-field]').forEach(input => input.addEventListener('change', () => {
        const field = input.dataset.estimateLineField;
        if (field === 'quantity' || field === 'unit_price') line[field] = Number(input.value) || 0; else line[field] = input.value;
        persistEstimateScope(); renderEstimateScope();
      }));
      row.querySelector('[data-remove-estimate-line]')?.addEventListener('click', () => { api.currentLines.splice(Number(row.dataset.estimateLineIndex), 1); persistEstimateScope(); renderEstimateScope(); });
    });
    model.lastEstimateSignature = estimateScopeSignature();
  }

  async function syncRoomFlowCatalog(options = {}) {
    const api = integration();
    if (!api) return null;
    try {
      const items = await api.loadCatalog?.(Boolean(options.force));
      let catalog = Array.isArray(items) && items.length ? items : (Array.isArray(api.catalogCache) ? api.catalogCache : []);
      let source = 'ROOMFLOW_SUPABASE';
      if (!catalog.length) {
        const seedResponse = await fetch('/roomflow/catalog/floodman-products.json', { cache: 'no-store', credentials: 'same-origin' });
        if (seedResponse.ok) {
          const bundled = await seedResponse.json();
          if (Array.isArray(bundled)) {
            catalog = bundled;
            source = 'ROOMFLOW_BUNDLED_CATALOG';
          }
        }
      }
      if (!catalog.length) {
        const result = await fetchJson('/office/api/catalog/import/bundled-roomflow', {
          method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ force: Boolean(options.force) })
        });
        const summary = `${result.added || 0} added, ${result.updated || 0} updated`;
        const node = $('#fm-rf-catalog-sync-result'); if (node) node.textContent = `Catalog loaded: ${summary}.`;
        if (!options.silent) setStatus(`RoomFlow line-item catalog loaded: ${summary}.`, 'good');
        return result;
      }
      const result = await fetchJson('/office/api/catalog/import/roomflow', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ organization_id: api.currentOrgId?.() || null, source, items: catalog }),
      });
      const summary = `${result.added || 0} added, ${result.updated || 0} updated`;
      const node = $('#fm-rf-catalog-sync-result'); if (node) node.textContent = `Catalog synced: ${summary}.`;
      if (!options.silent) setStatus(`RoomFlow line-item catalog synced: ${summary}.`, 'good');
      return result;
    } catch (error) {
      const node = $('#fm-rf-catalog-sync-result'); if (node) node.textContent = `Catalog sync needs review: ${error.message}`;
      if (!options.silent) setStatus(error.message, 'bad');
      return null;
    }
  }

  function renderJobs() {
    const host = $('#fm-rf-job-list'); if (!host) return;
    host.innerHTML = (model.jobs || []).slice(0, 12).map(job => `
      <article class="fm-rf-note">
        <p><b>${escapeHtml(job.job_name || 'RoomFlow job')}</b><br>${escapeHtml(job.estimate_number || '')} · ${escapeHtml(money(job.total_cents || 0))}</p>
        <small>${escapeHtml(job.status || 'SYNCED')} · ${escapeHtml(dateTime(job.last_sync_at || job.updated_at))}</small>
        <div class="fm-rf-button-row"><button type="button" class="fm-rf-button secondary" data-load-roomflow-job="${escapeHtml(job.id)}">Load job</button>${job.estimate_id ? `<a class="fm-rf-button secondary" href="/office/estimates/${encodeURIComponent(job.estimate_id)}" target="_top">Estimate</a>` : ''}</div>
      </article>`).join('') || '<p class="fm-rf-card-intro">No server-saved RoomFlow jobs yet.</p>';
    $$('[data-load-roomflow-job]', host).forEach(button => button.addEventListener('click', () => loadServerJob(button.dataset.loadRoomflowJob)));
  }
  async function refreshJobs() {
    try { const data = await fetchJson(`${API}/jobs?limit=25`); model.jobs = data.items || []; renderJobs(); }
    catch (error) { setStatus(error.message, 'bad'); }
  }
  async function loadServerJob(jobId) {
    try {
      setStatus('Loading RoomFlow job…', 'info');
      const data = await fetchJson(`${API}/jobs/${encodeURIComponent(jobId)}`); const job = data.job || {};
      if (job.snapshot && typeof window.loadJobData === 'function') window.loadJobData(job.snapshot);
      else if (job.snapshot) Object.assign(appState(), JSON.parse(JSON.stringify(job.snapshot)));
      appState().jobId = job.roomflow_job_id || appState().jobId; appState().floodmanRoomFlowJobId = job.id; appState().currentJobName = job.job_name || appState().currentJobName;
      model.lastJobKey = currentJobKey();
      if (job.contact_id) await selectCustomer(job.contact_id, { silent: true });
      if (job.property_id) await selectProperty(job.property_id, { silent: true });
      if (job.roomflow_estimate_id) { const map = loadMap(ESTIMATE_KEY); map[currentJobKey()] = job.roomflow_estimate_id; saveMap(ESTIMATE_KEY, map); }
      window.autosaveJob?.(); window.draw?.(); window.renderGuidedStep?.(); window.updateGlobalStats?.();
      panelOpen(false); setStatus('RoomFlow job restored from the customer file.', 'good');
    } catch (error) { setStatus(error.message, 'bad'); }
  }

  async function syncEstimate() {
    if (model.syncing) return;
    if (!model.contact) return setStatus('Select the customer before syncing the estimate.', 'warn');
    if (!model.property) return setStatus('Select the service property before syncing the estimate.', 'warn');
    const lines = normalizeLines(); if (!lines.length) return setStatus('Add at least one priced line item before syncing.', 'warn');
    model.syncing = true; const button = $('#fm-rf-sync-estimate'); if (button) { button.disabled = true; button.textContent = 'Syncing…'; }
    try {
      const state = appState(), estimateApi = integration();
      const taxRate = Math.max(0, Math.min(100, Number(state.costing?.settings?.salesTaxRate ?? state.costing?.settings?.taxRate ?? 0) || 0));
      const taxableSubtotal = lines.filter(line => line.taxable).reduce((sum, line) => sum + Number(line.line_total_cents || 0), 0);
      const taxCents = Math.round(taxableSubtotal * taxRate / 100);
      const address = model.property.address || {};
      const payload = {
        contact_id: model.contact.id,
        workspace_id: model.activeWorkspace?.id || null,
        roomflow_job_id: roomflowJobId(),
        roomflow_estimate_id: estimateIdentity(),
        job_name: asText(state.currentJobName || model.property.name || 'RoomFlow job'),
        revision: Math.max(1, Number(state.revisionNumber || 1)),
        customer: {
          contact_id: model.contact.id, name: model.contact.name || '', company: model.contact.company || '',
          email: model.contact.email || '', phone: model.contact.phone || '', status: model.contact.status || 'ACTIVE'
        },
        property: {
          property_id: model.property.id, property_name: model.property.name || '', property_type: model.property.property_type || '',
          street: address.street || '', street2: address.street2 || '', city: address.city || '', state: address.state || 'MI',
          postal_code: address.postal_code || '', country: address.country || 'US', claim_number: model.property.claim_number || '', insurer: model.property.insurer || ''
        },
        roomflow_layout_data_url: roomflowLayoutDataUrl(),
        estimate: {
          roomflow_estimate_id: estimateIdentity(),
          estimate_number: asText(estimateApi?.currentEstimateId ? `RF-${String(estimateApi.currentEstimateId).replace(/[^A-Za-z0-9]/g, '').slice(0, 12)}` : ''),
          title: asText(estimateApi?.currentEstimateHeader || state.currentJobName || 'RoomFlow estimate'),
          sections: Array.from(new Set(lines.map(line => line.section_name).filter(Boolean))).map((name, index) => ({ id: `rf-section-${index + 1}`, name, description: '', sort_order: index })),
          lines, tax_cents: taxCents, discount_cents: 0, deposit_percent: Number(state.costing?.settings?.depositPercent ?? 30) || 30,
          terms: asText(state.currentOrganization?.default_proposal_terms || state.costing?.terms || 'Payment is due upon receipt of each issued invoice. Additional work requires a signed Change Order.'),
          internal_note: `Synced from Floodman RoomFlow at ${new Date().toLocaleString('en-US', { timeZone: 'America/Detroit' })}`,
          roomflow_snapshot: roomflowSnapshot()
        }
      };
      const data = await fetchJson(`${API}/sync`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
      const estimateUrl = data.estimate_url || data.urls?.estimate || `/office/estimates/${encodeURIComponent(data.estimate_id)}`;
      state.floodmanEstimateId = data.estimate_id; state.floodmanEstimateUrl = estimateUrl; state.floodmanRoomFlowJobId = data.roomflow_job?.id || state.floodmanRoomFlowJobId; window.autosaveJob?.();
      const result = $('#fm-rf-sync-result'); if (result) result.innerHTML = `Estimate <a class="fm-rf-link" href="${escapeHtml(estimateUrl)}" target="_top">${escapeHtml(data.estimate_number)}</a> synced. ${data.erp_synced ? 'Floodman ERP is linked.' : escapeHtml(data.warning || (data.warnings || []).join(' ') || '')}`;
      setStatus(data.created ? 'RoomFlow estimate created in Floodman.' : 'RoomFlow estimate updated in Floodman.', 'good'); await refreshJobs();
    } catch (error) { setStatus(error.message, 'bad'); }
    finally { model.syncing = false; if (button) { button.disabled = false; button.textContent = 'Save draft to Floodman'; } updateGuide(); }
  }
  async function restoreLink() {
    const key = currentJobKey(); model.lastJobKey = key; const link = linkedRecord();
    if (!link) { clearCustomer(); setStatus('', 'info'); return; }
    if (link.contact_id) await selectCustomer(link.contact_id, { silent: true });
    if (link.property_id) await selectProperty(link.property_id, { silent: true });
    setStatus(model.contact ? 'Customer and property restored for this job.' : '', 'info');
  }

  function neutralizeLegacyCloudControls() {
    const authOverlay = document.getElementById('auth-overlay');
    if (authOverlay) {
      authOverlay.classList.add('hidden'); authOverlay.style.display = 'none'; authOverlay.setAttribute('aria-hidden', 'true');
      if ('inert' in HTMLElement.prototype) authOverlay.inert = true;
    }
    const syncBadge = document.getElementById('sync-status-badge');
    if (syncBadge) {
      syncBadge.textContent = 'Floodman linked';
      syncBadge.style.background = '#0b7a50';
      syncBadge.title = 'RoomFlow jobs and estimates are stored in Floodman Operations.';
    }
    const legacyProvider = document.getElementById('sync-provider');
    const legacyCard = legacyProvider?.closest('div[style*="margin-bottom: 1.5rem"]');
    if (legacyCard) legacyCard.style.display = 'none';
    const companySwitcher = document.getElementById('header-company-switcher');
    if (companySwitcher?.parentElement) companySwitcher.parentElement.style.display = 'none';
    document.querySelectorAll('button[onclick*="RoomFlowAuth.signOut"]').forEach(button => { button.style.display = 'none'; button.setAttribute('aria-hidden', 'true'); });
    let moreSwitcher = document.getElementById('more-company-switcher');
    if (moreSwitcher && moreSwitcher.dataset.floodmanWorkspace !== '1') {
      const replacement = moreSwitcher.cloneNode(true); replacement.dataset.floodmanWorkspace = '1'; moreSwitcher.replaceWith(replacement); moreSwitcher = replacement;
      replacement.addEventListener('change', event => changeWorkspace(event.target.value));
      const card = replacement.closest('.checklist-room-card');
      const title = card?.querySelector('h3'); const description = card?.querySelector('p');
      if (title) title.textContent = 'Floodman Company Workspaces';
      if (description) description.textContent = 'Uses your current Floodman ERP sign-in. No separate RoomFlow account is needed.';
    }
    let legacyCreate = document.getElementById('btn-more-create-company');
    if (legacyCreate && legacyCreate.dataset.floodmanWorkspace !== '1') {
      const replacement = legacyCreate.cloneNode(true); replacement.dataset.floodmanWorkspace = '1'; legacyCreate.replaceWith(replacement); legacyCreate = replacement;
      replacement.addEventListener('click', () => createWorkspace(document.getElementById('more-new-company-name')));
    }
    let sharedRefresh = document.getElementById('btn-refresh-shared-jobs');
    if (sharedRefresh && sharedRefresh.dataset.floodmanWorkspace !== '1') {
      const replacement = sharedRefresh.cloneNode(true); replacement.dataset.floodmanWorkspace = '1'; sharedRefresh.replaceWith(replacement); sharedRefresh = replacement;
      replacement.title = 'Refresh jobs from the active Floodman company'; replacement.textContent = 'Refresh Floodman jobs';
      replacement.addEventListener('click', () => refreshJobs().then(() => setStatus('Floodman RoomFlow jobs refreshed.', 'good')));
    }
    window.populateCompanySwitcher = renderWorkspaceControls;
    renderWorkspaceControls();
    const duplicateInvoice = document.getElementById('btn-create-invoice');
    if (duplicateInvoice) duplicateInvoice.style.display = 'none';
    document.querySelectorAll('[id*="townsquare" i],[class*="townsquare" i]').forEach(node => { node.style.display = 'none'; });
  }

  function buildUi() {
    document.documentElement.classList.add('floodman-roomflow');
    const topbar = document.createElement('header'); topbar.id = 'fm-roomflow-topbar';
    topbar.innerHTML = `<div class="fm-rf-brand"><img class="fm-rf-brand-mark" src="/floodman-brand/floodman-mark.svg" alt=""><div class="fm-rf-brand-copy"><strong>Floodman RoomFlow</strong><small>Customer-linked field estimating</small></div></div><div class="fm-rf-top-actions"><span id="fm-rf-job-chip" class="fm-rf-job-chip">No customer selected</span><a class="fm-rf-top-button secondary" href="/office" target="_top">Back to Operations</a><button type="button" class="fm-rf-top-button fm-rf-help-button" id="fm-rf-help" aria-label="Show RoomFlow quick start">Help</button><button type="button" class="fm-rf-top-button" id="fm-rf-open-panel">Customer & job file</button></div>`;
    const backdrop = document.createElement('div'); backdrop.id = 'fm-roomflow-backdrop';
    const panel = document.createElement('aside'); panel.id = 'fm-roomflow-panel'; panel.setAttribute('aria-hidden', 'true'); panel.setAttribute('aria-label', 'Customer and job file');
    panel.innerHTML = `<header class="fm-rf-panel-header"><div><h2>Customer & job file</h2><p>Follow the four short steps, then save the estimate to the same Floodman file used by the office.</p></div><button type="button" class="fm-rf-icon-button" id="fm-rf-close-panel" aria-label="Close customer and job panel">×</button></header><div class="fm-rf-panel-body">
      <section class="fm-rf-card fm-rf-guide" id="fm-rf-quick-start"><button type="button" class="fm-rf-guide-close" id="fm-rf-guide-close" aria-label="Dismiss quick start">×</button><h3>Quick start</h3><p class="fm-rf-card-intro" id="fm-rf-guide-company">Loading company…</p><ol class="fm-rf-guide-steps"><li data-guide-step="customer" data-guide-number="1"><b>1</b><span>Choose the customer</span></li><li data-guide-step="property" data-guide-number="2"><b>2</b><span>Choose the service property</span></li><li data-guide-step="scope" data-guide-number="3"><b>3</b><span>Sketch and add priced services</span></li><li data-guide-step="save" data-guide-number="4"><b>4</b><span>Save the draft to Floodman</span></li></ol><p class="fm-rf-card-intro">You can dismiss this guide and reopen it with <b>Help</b> in the top bar.</p></section>
      <details class="fm-rf-card fm-rf-details"><summary>Company workspace <span id="fm-rf-workspace-label">Loading company…</span></summary><p class="fm-rf-card-intro">Your ERP sign-in already authorizes RoomFlow. Most teams never need to change this. Choose or create another company only when the job belongs to a different business workspace.</p><div class="fm-rf-field"><label for="fm-rf-workspace-select">Active company</label><select class="fm-rf-select" id="fm-rf-workspace-select"><option value="">Loading company…</option></select></div><div class="fm-rf-inline"><input class="fm-rf-input" id="fm-rf-new-workspace-name" minlength="2" maxlength="200" autocomplete="organization" placeholder="New company name"><button class="fm-rf-button secondary" type="button" id="fm-rf-create-workspace">Create company</button></div></details>
      <section class="fm-rf-card"><h3>1. Customer</h3><p class="fm-rf-card-intro">Search by name, company, email, phone, address, or tag. No thousand-item dropdown.</p><div class="fm-rf-field"><label>Find customer</label><input class="fm-rf-input" id="fm-rf-customer-search" autocomplete="off" placeholder="Start typing a customer…"><div class="fm-rf-results" id="fm-rf-customer-results"></div></div><div id="fm-rf-customer-summary"></div></section>
      <section class="fm-rf-card"><h3>2. Service property</h3><p class="fm-rf-card-intro">Results are filtered to the selected customer.</p><div class="fm-rf-field"><label>Find property</label><input class="fm-rf-input" id="fm-rf-property-search" autocomplete="off" disabled placeholder="Choose a customer first"><div class="fm-rf-results" id="fm-rf-property-results"></div></div><div id="fm-rf-property-summary"></div></section>
      <details class="fm-rf-card fm-rf-details"><summary>Customer notes and tags <span>Optional</span></summary><div class="fm-rf-field"><label>Tags</label><input class="fm-rf-input" id="fm-rf-tags-input" placeholder="Foundation, Repeat Customer, Insurance"><div class="fm-rf-button-row"><button class="fm-rf-button secondary" type="button" id="fm-rf-save-tags">Save tags</button></div></div><div class="fm-rf-field"><label>New note</label><textarea class="fm-rf-textarea" id="fm-rf-note-body" placeholder="Job-site access, customer request, call note…"></textarea></div><div class="fm-rf-field"><label>Note category</label><select class="fm-rf-select" id="fm-rf-note-category"><option value="JOB">Job</option><option value="CALL">Phone call</option><option value="SERVICE">Service</option><option value="BILLING">Billing</option><option value="GENERAL">General</option></select></div><label style="display:flex;align-items:center;gap:8px;font-size:12px"><input type="checkbox" id="fm-rf-note-pinned"> Keep this note at the top</label><div class="fm-rf-button-row"><button class="fm-rf-button" type="button" id="fm-rf-add-note">Add note to customer file</button></div><div class="fm-rf-note-list" id="fm-rf-note-list"></div></details>
      <details class="fm-rf-card fm-rf-details"><summary>Refresh shared services and prices <span>Usually automatic</span></summary><p class="fm-rf-card-intro">Pull the current RoomFlow/Supabase catalog into Floodman. Stable source IDs update matching services instead of creating duplicates.</p><div class="fm-rf-button-row"><button class="fm-rf-button secondary" type="button" id="fm-rf-sync-catalog">Refresh current prices</button><a class="fm-rf-button secondary" href="/office/catalog" target="_top">Open services & prices</a></div><p class="fm-rf-card-intro" id="fm-rf-catalog-sync-result"></p></details>
      <section class="fm-rf-card"><h3>3. Sketch and priced services</h3><p class="fm-rf-card-intro">Use simple estimate sections, search the shared service list, or add a custom service for this estimate.</p><div id="fm-rf-estimate-scope"></div></section>
      <section class="fm-rf-card"><h3>4. Save to Floodman</h3><p class="fm-rf-card-intro">The layout, measurements, sections, and prices stay on this customer and property. Saving again updates the same draft.</p><div class="fm-rf-button-row"><button class="fm-rf-button good" type="button" id="fm-rf-sync-estimate">Save draft to Floodman</button><a class="fm-rf-button secondary" href="/office/estimates" target="_top">Open estimates</a><a class="fm-rf-button secondary" href="/office/documents" target="_top">Documents & signing</a></div><p class="fm-rf-card-intro" id="fm-rf-sync-result" style="margin-top:10px"></p></section><details class="fm-rf-card fm-rf-details"><summary>Open a recent RoomFlow job</summary><p class="fm-rf-card-intro">Load a server-saved layout on another approved phone, tablet, or computer.</p><div id="fm-rf-job-list"></div></details><div id="fm-rf-status" class="fm-rf-status" role="status" aria-live="polite"></div></div>`;
    const mobileNav = document.createElement('nav'); mobileNav.className = 'fm-rf-mobile-nav';
    mobileNav.innerHTML = `<button type="button" data-rf-tab="jobs"><b>⌂</b>Jobs</button><button type="button" data-rf-tab="project"><b>▱</b>Sketch</button><button type="button" data-rf-tab="add"><b>＋</b>Add</button><button type="button" data-rf-tab="review"><b>✓</b>Review</button><button type="button" data-rf-panel><b>◎</b>Customer</button>`;
    document.body.append(topbar, backdrop, panel, mobileNav);
    neutralizeLegacyCloudControls();
    $('#fm-rf-workspace-select')?.addEventListener('change', event => changeWorkspace(event.target.value));
    $('#fm-rf-create-workspace')?.addEventListener('click', () => createWorkspace($('#fm-rf-new-workspace-name')));
    $('#fm-rf-help')?.addEventListener('click', () => { panelOpen(true); showGuide(true); $('#fm-rf-quick-start')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); });
    $('#fm-rf-guide-close')?.addEventListener('click', () => showGuide(false));
    $('#fm-rf-open-panel')?.addEventListener('click', () => { panelOpen(true); $('#fm-rf-close-panel')?.focus(); }); $('#fm-rf-close-panel')?.addEventListener('click', () => { panelOpen(false); $('#fm-rf-open-panel')?.focus(); }); backdrop.addEventListener('click', () => panelOpen(false));
    $('#fm-rf-customer-search')?.addEventListener('input', event => { clearTimeout(model.searchTimer); model.searchTimer = setTimeout(() => searchCustomers(event.target.value), 220); });
    $('#fm-rf-property-search')?.addEventListener('input', event => { clearTimeout(model.propertyTimer); model.propertyTimer = setTimeout(() => searchProperties(event.target.value), 220); });
    $('#fm-rf-property-search')?.addEventListener('focus', event => { if (model.contact && !event.target.value) searchProperties(''); });
    $('#fm-rf-add-note')?.addEventListener('click', addNote); $('#fm-rf-save-tags')?.addEventListener('click', saveTags); $('#fm-rf-sync-catalog')?.addEventListener('click', () => syncRoomFlowCatalog({ force: true })); $('#fm-rf-sync-estimate')?.addEventListener('click', syncEstimate);
    $$('[data-rf-tab]', mobileNav).forEach(button => button.addEventListener('click', () => { window.switchTab?.(button.dataset.rfTab); $$('button', mobileNav).forEach(item => item.classList.toggle('is-active', item === button)); }));
    $('[data-rf-panel]', mobileNav)?.addEventListener('click', () => panelOpen(true));
    document.addEventListener('click', event => { if (!event.target.closest('.fm-rf-field')) $$('.fm-rf-results').forEach(node => node.classList.remove('is-open')); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') panelOpen(false); });
    const widePanel = window.matchMedia('(min-width: 1200px)');
    const syncPinnedPanel = () => {
      if (widePanel.matches) {
        document.documentElement.classList.add('fm-rf-panel-pinned');
        if (!document.documentElement.classList.contains('fm-rf-panel-dismissed')) panelOpen(true);
      } else {
        document.documentElement.classList.remove('fm-rf-panel-pinned', 'fm-rf-panel-dismissed');
        panelOpen(false);
      }
    };
    if (widePanel.addEventListener) widePanel.addEventListener('change', syncPinnedPanel); else widePanel.addListener(syncPinnedPanel);
    syncPinnedPanel();
    renderCustomer(); renderProperty(); renderEstimateScope(); updateJobChip(); showGuide(!guideDismissed()); updateGuide();
  }
  async function initialize() {
    buildUi();
    for (let i = 0; i < 40 && !window.state; i += 1) await sleep(150);
    try { await refreshWorkspaceContext(); }
    catch (error) { setStatus(error.message, error.code === 'AUTH' ? 'warn' : 'bad'); }
    await restoreLink(); await refreshJobs();
    if (params.get('catalog_sync') === '1') {
      panelOpen(true); const catalogDetails = $('#fm-rf-sync-catalog')?.closest('details'); if (catalogDetails) catalogDetails.open = true;
      await syncRoomFlowCatalog({ force: true }).finally(() => renderEstimateScope());
    } else {
      window.setTimeout(() => syncRoomFlowCatalog({ silent: true }).finally(() => renderEstimateScope()), 1800);
    }
    setInterval(() => {
      const key = currentJobKey(); if (key !== model.lastJobKey) restoreLink();
      const signature = estimateScopeSignature(); if (signature !== model.lastEstimateSignature) renderEstimateScope();
      updateJobChip(); updateGuide(); neutralizeLegacyCloudControls();
    }, 1200);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, { once: true }); else initialize();
})();
