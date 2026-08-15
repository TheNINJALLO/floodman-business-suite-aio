(() => {
  'use strict';

  const native = window.FloodmanNative;
  const clone = value => {
    try { return JSON.parse(JSON.stringify(value ?? {})); }
    catch (_error) { return {}; }
  };
  const decode = value => {
    if (value == null || value === '' || value === 'null') return null;
    if (typeof value !== 'string') return value;
    try { return JSON.parse(value); }
    catch (_error) { return null; }
  };
  const workspaceState = workspace => workspace ? {
    id: workspace.id,
    name: workspace.name || 'Floodman',
    role: 'Company Owner',
    colors: null,
    units: 'ft',
    timezone: workspace.timezone || 'America/Detroit',
    source: workspace.source || 'FLOODMAN_ROOMFLOW_NATIVE',
    imported: Boolean(workspace.imported),
  } : null;

  const F = window.FloodmanRoomFlow = {
    context: null,
    bootstrap: null,
    jobsById: {},
    workspacesById: {},
    activeWorkspace: null,
    selectedCustomer: null,
    selectedProperty: null,

    toast(message, bad = false) {
      const text = String(message || '');
      try { native.notify(text); } catch (_error) { }
      const badge = document.getElementById('fm-native-status');
      if (badge) {
        badge.textContent = text;
        badge.dataset.bad = bad ? '1' : '0';
      }
    },

    installWorkspaceCompatibility() {
      window.hasCapability = () => true;
      window.RoomFlowAuth = {
        loadSessionContext: async () => true,
        setActiveOrganization: async id => {
          if (id) native.selectWorkspace(String(id));
          return true;
        },
        createCompany: async name => {
          if (String(name || '').trim()) {
            native.createWorkspace(JSON.stringify({ name: String(name).trim(), timezone: F.activeWorkspace?.timezone || 'America/Detroit' }));
          } else {
            F.showWorkspaceDialog();
          }
          return null;
        },
        signOut: async () => true,
      };
    },

    applyWorkspace(workspace, workspaces = null) {
      if (!workspace?.id) return false;
      this.activeWorkspace = workspace;
      if (Array.isArray(workspaces)) {
        this.workspacesById = Object.fromEntries(workspaces.filter(item => item?.id).map(item => [item.id, item]));
      } else {
        this.workspacesById[workspace.id] = workspace;
      }
      if (window.state) {
        state.currentOrganization = workspaceState(workspace);
        state.userOrganizations = Object.values(this.workspacesById).map(workspaceState);
        state.sessionUser = state.sessionUser || { id: 'floodman-mobile', email: 'staff@floodman.local' };
        state.userCapabilities = ['manage_company', 'create_jobs', 'view_company_jobs', 'edit_job_information', 'edit_floor_plans', 'edit_measurements', 'edit_job_scope', 'manage_catalog', 'generate_proposals', 'approve_proposals'];
        state.syncStatus = 'synced';
        state.workspaceId = workspace.id;
        state.organizationId = workspace.id;
      }
      localStorage.setItem('roomflow_active_org_id', workspace.id);
      this.renderWorkspaceControl();
      return true;
    },

    renderWorkspaceControl() {
      const select = document.getElementById('fm-workspace-select');
      if (!select) return;
      const rows = Object.values(this.workspacesById);
      select.innerHTML = rows.map(item => `<option value="${this.escape(item.id)}">${this.escape(item.name || 'Floodman')}</option>`).join('');
      if (this.activeWorkspace?.id) select.value = this.activeWorkspace.id;
      select.disabled = rows.length < 2;
      select.title = this.activeWorkspace?.roomflow_organization_id
        ? `Imported RoomFlow company · ${this.activeWorkspace.name}`
        : `Floodman workspace · ${this.activeWorkspace?.name || ''}`;
    },

    escape(value) {
      return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
    },

    receiveBootstrap(encoded) {
      const bootstrap = decode(encoded);
      if (!bootstrap) return this.bootstrapFailed('Floodman returned an invalid RoomFlow bootstrap response.');
      this.bootstrap = bootstrap;
      const workspaces = Array.isArray(bootstrap.workspaces) ? bootstrap.workspaces : [];
      const active = bootstrap.active_workspace
        || workspaces.find(item => item.id === bootstrap.selected_workspace_id)
        || workspaces[0]
        || null;
      if (!active?.id) return this.bootstrapFailed('Floodman did not return a RoomFlow workspace. Create one with the + button.');
      this.applyWorkspace(active, workspaces);
      this.jobsById = {};
      const localJobs = (() => {
        try { return JSON.parse(localStorage.getItem('roomflow_jobs') || '{}'); }
        catch (_error) { return {}; }
      })();

      // Remove synchronized jobs belonging to a different company while keeping
      // unsynchronized field work safely on the device.
      Object.keys(localJobs).forEach(name => {
        const local = localJobs[name] || {};
        const localWorkspace = local.workspaceId || local.organizationId || '';
        if (local.sharedFromCloud && local.syncState !== 'pending' && localWorkspace && localWorkspace !== active.id) {
          delete localJobs[name];
        }
      });

      (bootstrap.jobs || []).forEach(detail => {
        const record = detail?.job || {};
        if (!record.id) return;
        const recordWorkspace = record.workspace_id || detail.workspace?.id || active.id;
        if (recordWorkspace !== active.id) return;
        this.jobsById[record.id] = detail;
        const name = record.job_name || record.name || detail.customer?.name || `RoomFlow Job ${record.id.slice(0, 8)}`;
        const imported = clone(record.snapshot || {});
        const existing = localJobs[name];
        const keepPending = existing && existing.syncState === 'pending';
        const snapshot = keepPending ? existing : imported;
        snapshot.jobId = record.id;
        snapshot.roomflowJobId = record.roomflow_job_id || record.roomflow_source_id || snapshot.roomflowJobId || null;
        snapshot.roomflowSourceJobId = record.roomflow_source_id || record.roomflow_job_id || snapshot.roomflowSourceJobId || null;
        snapshot.workspaceId = active.id;
        snapshot.organizationId = active.id;
        snapshot.currentOrganization = workspaceState(active);
        snapshot.currentJobName = name;
        snapshot.sharedFromCloud = true;
        snapshot.syncState = keepPending ? 'pending' : 'synchronized';
        snapshot.cloudStatus = record.status || 'DRAFT';
        snapshot.layoutCaptureRequired = Boolean(detail.layout_capture_required || record.layout_capture_required);
        snapshot.costing = snapshot.costing || {};
        snapshot.costing.customerName = detail.customer?.name || detail.customer?.company || record.customer_name || snapshot.costing.customerName || name;
        snapshot.costing.customerEmail = detail.customer?.email || snapshot.costing.customerEmail || '';
        snapshot.costing.customerPhone = detail.customer?.phone || detail.customer?.mobile_phone || snapshot.costing.customerPhone || '';
        snapshot.costing.customerAddress = [
          detail.property?.service_street,
          detail.property?.service_city,
          [detail.property?.service_state, detail.property?.service_postal_code].filter(Boolean).join(' '),
        ].filter(Boolean).join(', ') || record.property_address || snapshot.costing.customerAddress || '';
        snapshot.costing.serviceStreet = detail.property?.service_street || snapshot.costing.serviceStreet || '';
        snapshot.costing.serviceCity = detail.property?.service_city || snapshot.costing.serviceCity || '';
        snapshot.costing.serviceState = detail.property?.service_state || snapshot.costing.serviceState || '';
        snapshot.costing.servicePostalCode = detail.property?.service_postal_code || snapshot.costing.servicePostalCode || '';
        snapshot.costing.projectCategory = record.project_category || detail.estimate?.project_category || snapshot.costing.projectCategory || 'general-restoration';
        snapshot.costing.estimateHeader = detail.estimate?.title || record.name || snapshot.costing.estimateHeader || 'RoomFlow Estimate';

        if ((!Array.isArray(snapshot.costing.customItems) || !snapshot.costing.customItems.length) && Array.isArray(record.sections)) {
          snapshot.costing.customItems = record.sections.flatMap(section => (section.lines || []).map(line => ({
            roomflowLineId: line.id || line.roomflow_line_id || `imported-${Math.random().toString(36).slice(2)}`,
            catalogItemId: line.catalog_item_id || null,
            sectionName: section.title || line.section_name || 'Scope of Work',
            header: section.title || line.section_name || 'Scope of Work',
            name: line.name || 'Imported RoomFlow item',
            description: line.description || '',
            category: line.category || 'General Services',
            unit: line.unit || 'each',
            qty: Number(line.quantity ?? 1) || 0,
            quantity: Number(line.quantity ?? 1) || 0,
            unitCost: Number(line.unit_price_cents ?? 0) / 100,
            unit_price: Number(line.unit_price_cents ?? 0) / 100,
            taxable: Boolean(line.taxable),
            optional: Boolean(line.optional),
          })));
        }
        localJobs[name] = snapshot;
      });
      localStorage.setItem('roomflow_jobs', JSON.stringify(localJobs));
      this.installCatalog(bootstrap.catalog || []);
      if (typeof window.renderRoomFlowJobsList === 'function') window.renderRoomFlowJobsList();
      if (typeof window.renderJobsDashboard === 'function') window.renderJobsDashboard();
      if (typeof window.populateCompanySwitcher === 'function') {
        try { window.populateCompanySwitcher(); } catch (_error) { }
      }
      const latestImport = (bootstrap.imports || [])[0];
      const count = (bootstrap.jobs || []).length;
      this.toast(latestImport?.status === 'COMPLETED'
        ? `${active.name} ready · ${count} jobs`
        : `Floodman RoomFlow ready · ${active.name} · ${count} jobs`);
      const host = document.getElementById('fm-bootstrap-error');
      if (host) host.textContent = '';
    },

    installCatalog(items) {
      let existing = [];
      try { existing = JSON.parse(localStorage.getItem('roomflow_cost_catalog_v1') || '[]'); }
      catch (_error) { existing = []; }
      const activeId = this.activeWorkspace?.id || '';
      existing = existing.filter(item => !item.floodmanWorkspaceId || item.floodmanWorkspaceId === activeId);
      const byId = new Map(existing.map(item => [String(item.id), item]));
      (items || []).forEach(item => {
        const id = String(item.id || item.external_key || item.name || '').trim();
        if (!id) return;
        byId.set(id, {
          ...(byId.get(id) || {}),
          id,
          name: item.name || 'Floodman catalog item',
          packagePrice: Number(item.unit_price_cents || 0) / 100,
          packageQuantity: 1,
          purchaseUnit: item.unit || 'each',
          usageUnit: item.unit || 'each',
          taxable: Boolean(item.taxable),
          defaultWaste: Number(item.default_waste || 0),
          active: item.active !== false,
          notes: item.description || '',
          floodmanCatalogItemId: item.id,
          floodmanWorkspaceId: item.workspace_id || activeId,
          category: item.category || 'General Services',
        });
      });
      localStorage.setItem('roomflow_cost_catalog_v1', JSON.stringify(Array.from(byId.values())));
      if (window.RoomFlowCatalog?.loadCatalog) {
        try { window.state.costing.catalog = window.RoomFlowCatalog.loadCatalog(); }
        catch (_error) { }
      }
    },

    receiveContext(encoded) {
      const detail = decode(encoded);
      if (!detail?.job) {
        this.applyIdentity();
        return;
      }
      if (detail.workspace?.id && detail.workspace.id !== this.activeWorkspace?.id) {
        this.applyWorkspace(detail.workspace);
      }
      this.context = detail;
      this.jobsById[detail.job.id] = detail;
      this.selectedCustomer = detail.customer || null;
      this.selectedProperty = detail.property || null;
      const record = detail.job;
      const snapshot = clone(record.snapshot || {});
      snapshot.workspaceId = record.workspace_id || detail.workspace?.id || this.activeWorkspace?.id || null;
      snapshot.organizationId = snapshot.workspaceId;
      snapshot.currentOrganization = workspaceState(detail.workspace || this.activeWorkspace);
      setTimeout(() => {
        try {
          if (window.loadJobData && Object.keys(snapshot).length) window.loadJobData(snapshot);
          if (window.state) {
            state.jobId = record.id;
            state.currentJobName = record.job_name || record.name || state.currentJobName;
            state.currentOrganization = workspaceState(detail.workspace || this.activeWorkspace);
          }
          try { native.selectJob(record.id); } catch (_error) { }
          this.applyIdentity();
        } catch (error) {
          console.warn(error);
          this.toast('The saved RoomFlow job could not be restored.', true);
        }
      }, 600);
    },

    selectLocalJob(data) {
      const id = data?.jobId || data?.floodmanJobId || null;
      if (!id) return;
      try { native.selectJob(String(id)); } catch (_error) { }
      const detail = this.jobsById[id];
      if (detail) {
        this.context = detail;
        this.selectedCustomer = detail.customer || null;
        this.selectedProperty = detail.property || null;
        if (detail.workspace) this.applyWorkspace(detail.workspace);
        this.applyIdentity();
      }
    },

    patchJobLoading() {
      let attempts = 0;
      const timer = setInterval(() => {
        attempts += 1;
        if (typeof window.loadJobData === 'function' && !window.loadJobData.__floodmanNativeWrapped) {
          const original = window.loadJobData;
          const wrapped = function (data, ...args) {
            const result = original.call(this, data, ...args);
            if (window.state && F.activeWorkspace) {
              state.currentOrganization = workspaceState(F.activeWorkspace);
              state.workspaceId = F.activeWorkspace.id;
              state.organizationId = F.activeWorkspace.id;
            }
            setTimeout(() => F.selectLocalJob(data), 0);
            return result;
          };
          wrapped.__floodmanNativeWrapped = true;
          window.loadJobData = wrapped;
          clearInterval(timer);
        } else if (attempts > 80) {
          clearInterval(timer);
        }
      }, 250);
    },

    applyIdentity() {
      const customer = this.selectedCustomer || {};
      const property = this.selectedProperty || {};
      if (window.state) {
        state.currentOrganization = workspaceState(this.activeWorkspace);
        state.workspaceId = this.activeWorkspace?.id || state.workspaceId || null;
        state.organizationId = state.workspaceId;
        state.costing = state.costing || {};
        state.costing.customerName = customer.name || [customer.first_name, customer.last_name].filter(Boolean).join(' ') || state.costing.customerName || '';
        state.costing.customerEmail = customer.email || state.costing.customerEmail || '';
        state.costing.customerPhone = customer.phone || customer.mobile_phone || state.costing.customerPhone || '';
        state.costing.customerAddress = [property.service_street, property.service_city, [property.service_state, property.service_postal_code].filter(Boolean).join(' ')].filter(Boolean).join(', ') || state.costing.customerAddress || '';
      }
      this.renderIdentity();
    },

    renderIdentity() {
      const label = document.getElementById('fm-link-summary');
      if (label) label.textContent = `${this.selectedCustomer?.name || this.selectedCustomer?.company || 'Choose customer'} · ${this.selectedProperty?.property_name || this.selectedProperty?.service_street || 'Choose property'}`;
    },

    chooseCustomer() {
      if (!this.activeWorkspace?.id) return this.toast('Choose or create a RoomFlow workspace first.', true);
      const query = prompt('Search Floodman customers by name, email, phone, address, or tag:', '');
      if (query === null) return;
      let rows = [];
      try { rows = JSON.parse(native.searchCustomers(query)); } catch (_error) { }
      if (!rows.length) return this.toast('No matching Floodman customers.', true);
      const list = rows.slice(0, 20).map((item, index) => `${index + 1}. ${item.name || item.company || item.email || item.id}`).join('\n');
      const choice = Number(prompt(`Choose a customer:\n${list}`, '1'));
      if (!choice || !rows[choice - 1]) return;
      this.selectedCustomer = rows[choice - 1];
      this.selectedProperty = null;
      this.applyIdentity();
      this.chooseProperty();
    },

    chooseProperty() {
      if (!this.selectedCustomer) return this.chooseCustomer();
      const query = prompt("Search this customer's service properties:", '') ?? '';
      let rows = [];
      try { rows = JSON.parse(native.searchProperties(this.selectedCustomer.id, query)); } catch (_error) { }
      if (!rows.length) return this.toast('No property found. Enter the service address in RoomFlow and Floodman will create it when saved.');
      const list = rows.slice(0, 20).map((item, index) => `${index + 1}. ${item.property_name || item.name || item.service_street || item.id}`).join('\n');
      const choice = Number(prompt(`Choose a service property:\n${list}`, '1'));
      if (!choice || !rows[choice - 1]) return;
      this.selectedProperty = rows[choice - 1];
      this.applyIdentity();
    },

    changeWorkspace(id) {
      const selected = String(id || '').trim();
      if (!selected || selected === this.activeWorkspace?.id) return;
      this.toast('Switching RoomFlow company…');
      try { native.selectWorkspace(selected); }
      catch (_error) { this.workspaceFailed('The workspace switch could not be started.'); }
    },

    workspaceSelected(encoded) {
      const response = decode(encoded);
      if (!response?.bootstrap) return this.workspaceFailed('Floodman returned an invalid workspace response.');
      this.context = null;
      this.selectedCustomer = null;
      this.selectedProperty = null;
      this.receiveBootstrap(response.bootstrap);
      this.renderIdentity();
      this.toast(`RoomFlow workspace changed to ${response.workspace?.name || this.activeWorkspace?.name || 'Floodman'}.`);
    },

    workspaceCreated(encoded) {
      const response = decode(encoded);
      if (!response?.bootstrap) return this.workspaceFailed('Floodman returned an invalid new-workspace response.');
      document.getElementById('fm-roomflow-workspace-modal')?.remove();
      this.receiveBootstrap(response.bootstrap);
      this.toast(`Created ${response.workspace?.name || 'the Floodman workspace'}.`);
    },

    workspaceFailed(message) {
      this.toast(message || 'The RoomFlow workspace could not be changed.', true);
      this.renderWorkspaceControl();
    },

    showWorkspaceDialog() {
      document.getElementById('fm-roomflow-workspace-modal')?.remove();
      const modal = document.createElement('div');
      modal.id = 'fm-roomflow-workspace-modal';
      modal.className = 'fm-roomflow-modal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');
      modal.setAttribute('aria-labelledby', 'fm-workspace-title');
      modal.innerHTML = `
        <form id="fm-roomflow-workspace-form" autocomplete="off">
          <h2 id="fm-workspace-title">Create another company</h2>
          <p>Most teams need only the company Floodman created automatically. Add another only when its customers and jobs must stay in a separate company workspace.</p>
          <label>Company name<input id="fm-workspace-name" type="text" minlength="2" maxlength="200" autocomplete="organization" placeholder="Company name" required></label>
          <label>Business time zone<select id="fm-workspace-timezone"><option value="America/Detroit">Eastern Time (Detroit)</option></select></label>
          <div><button type="button" data-cancel>Cancel</button><button type="submit" class="primary">Create</button></div>
        </form>`;
      document.body.appendChild(modal);
      const close = () => modal.remove();
      modal.querySelector('[data-cancel]').onclick = close;
      modal.onclick = event => { if (event.target === modal) close(); };
      modal.onkeydown = event => { if (event.key === 'Escape') close(); };
      modal.querySelector('#fm-workspace-name').focus();
      modal.querySelector('#fm-roomflow-workspace-form').onsubmit = event => {
        event.preventDefault();
        const name = modal.querySelector('#fm-workspace-name').value.trim();
        const timezone = modal.querySelector('#fm-workspace-timezone').value.trim() || 'America/Detroit';
        if (!name) return;
        this.toast('Creating Floodman workspace…');
        try { native.createWorkspace(JSON.stringify({ name, timezone })); }
        catch (_error) { this.workspaceFailed('The workspace could not be created.'); }
      };
    },

    showImportDialog() {
      document.getElementById('fm-roomflow-import-modal')?.remove();
      const modal = document.createElement('div');
      modal.id = 'fm-roomflow-import-modal';
      modal.className = 'fm-roomflow-modal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');
      modal.setAttribute('aria-labelledby', 'fm-import-title');
      modal.innerHTML = `
        <form id="fm-roomflow-import-form" autocomplete="off">
          <h2 id="fm-import-title">Bring in old RoomFlow data</h2>
          <p>Use the sign-in from the original RoomFlow cloud account. Floodman uses the password for this import request only, clears it immediately, and updates matching source records instead of intentionally duplicating them.</p>
          <label>Original RoomFlow email<input id="fm-import-email" type="email" autocomplete="username" required></label>
          <label>Original RoomFlow password<input id="fm-import-password" type="password" autocomplete="current-password" required></label>
          <div><button type="button" data-cancel>Cancel</button><button type="submit" class="primary">Start secure import</button></div>
        </form>`;
      document.body.appendChild(modal);
      const close = () => modal.remove();
      modal.querySelector('[data-cancel]').onclick = close;
      modal.onclick = event => { if (event.target === modal) close(); };
      modal.onkeydown = event => { if (event.key === 'Escape') close(); };
      modal.querySelector('#fm-import-email').focus();
      modal.querySelector('#fm-roomflow-import-form').onsubmit = event => {
        event.preventDefault();
        const email = modal.querySelector('#fm-import-email').value.trim();
        const passwordInput = modal.querySelector('#fm-import-password');
        const password = passwordInput.value;
        passwordInput.value = '';
        if (!email || !password) return;
        modal.remove();
        this.toast('Importing original RoomFlow companies and cloud data…');
        try { native.importOriginalRoomFlow(JSON.stringify({ email, password })); }
        catch (_error) { this.importFailed('The import could not be started.'); }
      };
    },

    importCompleted(encoded) {
      const result = decode(encoded);
      if (!result) return this.importFailed('Floodman returned an invalid import result.');
      if (result.bootstrap) this.receiveBootstrap(result.bootstrap);
      const counts = result.counts || {};
      const message = `Imported ${counts.workspaces || counts.organizations || 0} companies, ${counts.jobs || 0} jobs, ${counts.customers || 0} customers, ${counts.estimates || 0} estimates, and ${counts.catalog_items || 0} catalog items.`;
      this.toast(message);
      if (Number(result.layout_capture_required || 0) > 0) {
        setTimeout(() => this.toast(`${result.layout_capture_required} imported jobs need to be opened and saved once to capture the actual PDF layout.`), 1200);
      }
    },

    importFailed(message) {
      this.toast(message || 'Original RoomFlow import failed.', true);
    },

    bootstrapFailed(message) {
      this.toast(message || 'Floodman RoomFlow cloud data could not be loaded.', true);
      const host = document.getElementById('fm-bootstrap-error');
      if (host) host.textContent = String(message || 'RoomFlow cloud loading failed.');
    },

    snapshot() {
      try {
        if (window.autosaveJob) window.autosaveJob();
        const jobs = JSON.parse(localStorage.getItem('roomflow_jobs') || '{}');
        const current = window.state?.currentJobName;
        const snapshot = current && jobs[current]
          ? clone(jobs[current])
          : clone(window.state || {});
        snapshot.workspaceId = this.activeWorkspace?.id || snapshot.workspaceId || null;
        snapshot.organizationId = snapshot.workspaceId;
        snapshot.currentOrganization = workspaceState(this.activeWorkspace);
        return snapshot;
      } catch (_error) { return {}; }
    },

    layout() {
      for (const canvas of [document.getElementById('sketch-canvas'), document.querySelector('#three-container canvas')]) {
        try { if (canvas?.toDataURL) return canvas.toDataURL('image/jpeg', 0.9); }
        catch (_error) { }
      }
      return '';
    },

    sections() {
      const custom = window.state?.costing?.customItems || [];
      const groups = {};
      custom.forEach(line => {
        const title = line.sectionName || line.header || line.category || 'RoomFlow Scope';
        (groups[title] ??= []).push(line);
      });
      return Object.entries(groups).map(([title, items]) => ({
        title,
        description: 'Measured and priced in Floodman RoomFlow.',
        lines: items.map(item => ({
          catalog_item_id: item.catalogItemId || item.floodmanCatalogItemId || null,
          name: item.name || 'RoomFlow line item',
          description: item.description || '',
          category: item.category || 'General Services',
          unit: item.unit || 'each',
          quantity: Number(item.qty ?? item.quantity ?? 1) || 0,
          unit_price_cents: Math.round((Number(item.unitCost ?? item.unit_price ?? 0) || 0) * 100),
          taxable: Boolean(item.taxable),
          optional: Boolean(item.optional),
          save_to_catalog: !(item.catalogItemId || item.floodmanCatalogItemId),
        })),
      }));
    },

    payload() {
      const snapshot = this.snapshot();
      const costing = snapshot.costing || window.state?.costing || {};
      const property = this.selectedProperty || {};
      const customer = this.selectedCustomer || {};
      const record = this.context?.job || {};
      return {
        workspace_id: this.activeWorkspace?.id || record.workspace_id || snapshot.workspaceId || null,
        roomflow_job_id: record.roomflow_job_id || record.roomflow_source_id || snapshot.roomflowSourceJobId || snapshot.roomflowJobId || null,
        job_name: window.state?.currentJobName || snapshot.currentJobName || costing.customerName || 'RoomFlow Job',
        contact_id: customer.id || this.context?.customer?.id || record.contact_id || null,
        property_id: property.id || this.context?.property?.id || record.property_id || null,
        estimate_id: this.context?.estimate?.id || record.estimate_id || null,
        estimate_number: this.context?.estimate?.estimate_number || record.estimate_number || '',
        status: 'DRAFT',
        project_category: costing.projectCategory || record.project_category || 'general-restoration',
        title: costing.estimateHeader || window.state?.currentJobName || 'RoomFlow Estimate',
        customer_name: costing.customerName || customer.name || '',
        customer_email: costing.customerEmail || customer.email || '',
        customer_phone: costing.customerPhone || customer.phone || '',
        property_address: costing.customerAddress || [property.service_street, property.service_city, [property.service_state, property.service_postal_code].filter(Boolean).join(' ')].filter(Boolean).join(', '),
        snapshot,
        summary: {
          rooms: Array.isArray(snapshot.rooms) ? snapshot.rooms.length : 0,
          levels: Array.isArray(snapshot.levels) ? snapshot.levels.length : 0,
          measurements: Array.isArray(snapshot.capturedMeasurements) ? snapshot.capturedMeasurements.length : 0,
        },
        layout_data_url: this.layout(),
        sections: this.sections(),
        sync_estimate: true,
      };
    },

    save() {
      if (!this.activeWorkspace?.id) {
        this.toast('Choose or create a RoomFlow company before saving.', true);
        return;
      }
      if (!window.state?.currentJobName) {
        this.toast('Start or select a RoomFlow job before saving.', true);
        return;
      }
      this.toast('Saving RoomFlow job, actual layout, catalog, and grouped estimate…');
      native.saveJob(JSON.stringify(this.payload()));
    },

    saveCompleted(encoded) {
      const result = decode(encoded);
      if (result) {
        this.context = { ...(this.context || {}), ...result };
        if (result.workspace) this.applyWorkspace(result.workspace);
        if (result.job?.id) {
          this.jobsById[result.job.id] = this.context;
          try { native.selectJob(result.job.id); } catch (_error) { }
        }
      }
      this.toast('RoomFlow job, actual layout, and grouped estimate synchronized.');
      try { native.refreshBootstrap(); } catch (_error) { }
    },

    saveFailed(message) {
      this.toast(message || 'RoomFlow synchronization failed.', true);
    },
  };

  function install() {
    F.installWorkspaceCompatibility();
    document.getElementById('auth-overlay')?.remove();
    document.querySelectorAll('[onclick*="RoomFlowAuth.signIn"],[onclick*="RoomFlowAuth.signUp"],[onclick*="RoomFlowAuth.signOut"]').forEach(element => element.remove());
    document.getElementById('header-company-switcher')?.closest('div')?.remove();
    const bar = document.createElement('div');
    bar.id = 'fm-native-bar';
    bar.innerHTML = `
      <button onclick="FloodmanNative.close()">‹ Floodman</button>
      <select id="fm-workspace-select" aria-label="RoomFlow company" onchange="FloodmanRoomFlow.changeWorkspace(this.value)"><option>Loading company…</option></select>
      <button class="compact" title="Create another company" aria-label="Create another company" onclick="FloodmanRoomFlow.showWorkspaceDialog()">＋</button>
      <div id="fm-link-summary">Choose customer · Choose property</div>
      <button title="Choose the customer and service property" onclick="FloodmanRoomFlow.chooseCustomer()">Customer</button>
      <button title="Bring in data from the original RoomFlow cloud account" onclick="FloodmanRoomFlow.showImportDialog()">Import</button>
      <button class="save" onclick="FloodmanRoomFlow.save()">Save</button>
      <span id="fm-native-status">Loading…</span>`;
    document.body.appendChild(bar);
    const error = document.createElement('div');
    error.id = 'fm-bootstrap-error';
    document.body.appendChild(error);
    const style = document.createElement('style');
    style.textContent = `
      #fm-native-bar{position:fixed;z-index:30000;left:0;right:0;top:0;display:flex;gap:6px;align-items:center;padding:7px 8px;background:#0f2435;color:white;box-shadow:0 2px 12px #0008;font:600 12px system-ui}
      #fm-native-bar button,#fm-native-bar select{border:0;border-radius:7px;padding:9px 10px;background:#29465d;color:white;min-height:36px}
      #fm-native-bar select{max-width:190px;font-weight:700;text-overflow:ellipsis}
      #fm-native-bar button.compact{font-size:18px;padding:5px 9px}
      #fm-native-bar button.save{background:#0783ad}
      #fm-link-summary{min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      #fm-native-status{border-radius:12px;background:#047857;padding:4px 8px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      #fm-native-status[data-bad="1"]{background:#b91c1c}
      #fm-bootstrap-error:empty{display:none}
      #fm-bootstrap-error{position:fixed;z-index:29999;top:52px;left:8px;right:8px;background:#7f1d1d;color:#fff;padding:10px;border-radius:8px;font:600 12px system-ui}
      .fm-roomflow-modal{position:fixed;z-index:40000;inset:0;background:#000b;display:flex;align-items:center;justify-content:center;padding:18px}
      .fm-roomflow-modal form{width:min(430px,100%);max-height:calc(100vh - 36px);overflow:auto;box-sizing:border-box;background:#102536;color:#fff;border-radius:18px;padding:22px;box-shadow:0 24px 80px #000}
      .fm-roomflow-modal h2{margin:0 0 8px}
      .fm-roomflow-modal p{color:#cbd5e1;line-height:1.45}
      .fm-roomflow-modal label{display:block;margin:12px 0;color:#dbeafe;font-weight:700}
      .fm-roomflow-modal input,.fm-roomflow-modal select{display:block;width:100%;box-sizing:border-box;margin-top:6px;padding:12px;border-radius:9px;border:1px solid #456;background:#071722;color:#fff;font-size:16px}
      .fm-roomflow-modal form>div{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}
      .fm-roomflow-modal button{padding:10px 16px;border:0;border-radius:9px;background:#334155;color:#fff}
      .fm-roomflow-modal button.primary{background:#0783ad}
      body{padding-top:50px!important}
      #auth-overlay{display:none!important}
      @media(max-width:860px){#fm-native-status{display:none}#fm-native-bar{font-size:11px}#fm-native-bar button,#fm-native-bar select{padding:8px 7px}#fm-workspace-select{max-width:135px}#fm-link-summary{display:none}}
    `;
    document.head.appendChild(style);
    F.patchJobLoading();
    setTimeout(() => native.ready(), 350);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
  else install();
})();
