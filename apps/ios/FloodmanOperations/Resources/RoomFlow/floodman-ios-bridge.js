(() => {
  'use strict';

  const send = (type, data = {}) => webkit.messageHandlers.FloodmanNative.postMessage({ type, ...data });
  const decode = value => {
    if (value == null || value === '' || value === 'null') return null;
    if (typeof value !== 'string') return value;
    try { return JSON.parse(value); } catch (_error) { return null; }
  };
  const clone = value => {
    try { return JSON.parse(JSON.stringify(value ?? {})); } catch (_error) { return {}; }
  };
  const workspaceState = workspace => workspace ? {
    id: workspace.id,
    name: workspace.name || 'Floodman',
    role: 'Company Owner',
    units: 'ft',
    timezone: workspace.timezone || 'America/Detroit',
    source: workspace.source || 'FLOODMAN_ROOMFLOW_IOS',
    imported: Boolean(workspace.imported),
  } : null;

  const F = window.FloodmanRoomFlow = {
    context: null,
    bootstrap: null,
    customer: null,
    property: null,
    activeWorkspace: null,
    jobsById: {},

    toast(message, bad = false) {
      const badge = document.getElementById('fm-ios-status');
      if (badge) {
        badge.textContent = String(message || '');
        badge.dataset.bad = bad ? '1' : '0';
      }
    },

    applyWorkspace(workspace, workspaces = []) {
      if (!workspace?.id) return;
      this.activeWorkspace = workspace;
      if (window.state) {
        state.currentOrganization = workspaceState(workspace);
        state.userOrganizations = workspaces.map(workspaceState);
        state.sessionUser = state.sessionUser || { id: 'floodman-ios', email: 'staff@floodman.local' };
        state.userCapabilities = [
          'manage_company', 'create_jobs', 'view_company_jobs', 'edit_job_information',
          'edit_floor_plans', 'edit_measurements', 'edit_job_scope', 'manage_catalog',
          'generate_proposals', 'approve_proposals',
        ];
        state.workspaceId = workspace.id;
        state.organizationId = workspace.id;
        state.syncStatus = 'synced';
      }
      localStorage.setItem('roomflow_active_org_id', workspace.id);
      const label = document.getElementById('fm-ios-workspace');
      if (label) label.textContent = workspace.name || 'Floodman';
    },

    receiveBootstrap(encoded) {
      const bootstrap = decode(encoded);
      if (!bootstrap) return this.bootstrapFailed('Floodman returned an invalid RoomFlow bootstrap response.');
      this.bootstrap = bootstrap;
      const workspaces = Array.isArray(bootstrap.workspaces) ? bootstrap.workspaces : [];
      const active = bootstrap.active_workspace
        || workspaces.find(item => item.id === bootstrap.selected_workspace_id)
        || workspaces[0];
      if (!active?.id) return this.bootstrapFailed('Create a RoomFlow company workspace before starting an estimate.');
      this.applyWorkspace(active, workspaces);

      let localJobs = {};
      try { localJobs = JSON.parse(localStorage.getItem('roomflow_jobs') || '{}'); } catch (_error) { }
      Object.keys(localJobs).forEach(name => {
        const local = localJobs[name] || {};
        const localWorkspace = local.workspaceId || local.organizationId || '';
        if (local.sharedFromCloud && local.syncState !== 'pending' && localWorkspace && localWorkspace !== active.id) {
          delete localJobs[name];
        }
      });
      this.jobsById = {};
      (bootstrap.jobs || []).forEach(detail => {
        const job = detail?.job || {};
        if (!job.id || (job.workspace_id && job.workspace_id !== active.id)) return;
        this.jobsById[job.id] = detail;
        const name = job.job_name || job.name || detail.customer?.name || `RoomFlow Job ${job.id.slice(0, 8)}`;
        const existing = localJobs[name];
        const snapshot = existing?.syncState === 'pending' ? existing : clone(job.snapshot || {});
        snapshot.jobId = job.id;
        snapshot.roomflowJobId = job.roomflow_job_id || job.roomflow_source_id || snapshot.roomflowJobId || null;
        snapshot.roomflowSourceJobId = job.roomflow_source_id || job.roomflow_job_id || snapshot.roomflowSourceJobId || null;
        snapshot.currentJobName = name;
        snapshot.currentOrganization = workspaceState(active);
        snapshot.workspaceId = active.id;
        snapshot.organizationId = active.id;
        snapshot.sharedFromCloud = true;
        snapshot.syncState = existing?.syncState === 'pending' ? 'pending' : 'synchronized';
        snapshot.layoutCaptureRequired = Boolean(detail.layout_capture_required || job.layout_capture_required);
        snapshot.costing = snapshot.costing || {};
        snapshot.costing.customerName = detail.customer?.name || job.customer_name || snapshot.costing.customerName || name;
        snapshot.costing.customerEmail = detail.customer?.email || snapshot.costing.customerEmail || '';
        snapshot.costing.customerPhone = detail.customer?.phone || detail.customer?.mobile_phone || snapshot.costing.customerPhone || '';
        snapshot.costing.customerAddress = [
          detail.property?.service_street,
          detail.property?.service_city,
          [detail.property?.service_state, detail.property?.service_postal_code].filter(Boolean).join(' '),
        ].filter(Boolean).join(', ') || job.property_address || snapshot.costing.customerAddress || '';
        localJobs[name] = snapshot;
      });
      localStorage.setItem('roomflow_jobs', JSON.stringify(localJobs));
      this.installCatalog(bootstrap.catalog || []);
      if (typeof window.renderRoomFlowJobsList === 'function') window.renderRoomFlowJobsList();
      this.toast(`${active.name || 'Floodman'} ready · ${(bootstrap.jobs || []).length} jobs`);
    },

    installCatalog(items) {
      let existing = [];
      try { existing = JSON.parse(localStorage.getItem('roomflow_cost_catalog_v1') || '[]'); } catch (_error) { }
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
          active: item.active !== false,
          notes: item.description || '',
          floodmanCatalogItemId: item.id,
          floodmanWorkspaceId: item.workspace_id || this.activeWorkspace?.id || '',
          category: item.category || 'General Services',
        });
      });
      localStorage.setItem('roomflow_cost_catalog_v1', JSON.stringify(Array.from(byId.values())));
    },

    receiveContext(encoded) {
      const detail = decode(encoded);
      if (!detail?.job) {
        this.applyIdentity();
        return;
      }
      this.context = detail;
      this.customer = detail.customer || null;
      this.property = detail.property || null;
      if (detail.workspace?.id) this.applyWorkspace(detail.workspace, this.bootstrap?.workspaces || []);
      const job = detail.job;
      const snapshot = clone(job.snapshot || {});
      snapshot.jobId = job.id;
      snapshot.currentOrganization = workspaceState(detail.workspace || this.activeWorkspace);
      snapshot.workspaceId = job.workspace_id || detail.workspace?.id || this.activeWorkspace?.id || null;
      snapshot.organizationId = snapshot.workspaceId;
      setTimeout(() => {
        try {
          if (window.loadJobData && Object.keys(snapshot).length) window.loadJobData(snapshot);
          if (window.state) {
            state.jobId = job.id;
            state.currentJobName = job.job_name || job.name || state.currentJobName;
          }
          send('selectJob', { id: job.id });
          this.applyIdentity();
        } catch (error) {
          console.warn(error);
          this.toast('The saved RoomFlow job could not be restored.', true);
        }
      }, 600);
    },

    patchJobLoading() {
      let attempts = 0;
      const timer = setInterval(() => {
        attempts += 1;
        if (typeof window.loadJobData === 'function' && !window.loadJobData.__floodmanIOSWrapped) {
          const original = window.loadJobData;
          const wrapped = function (data, ...args) {
            const result = original.call(this, data, ...args);
            const id = data?.jobId || data?.floodmanJobId;
            if (id) send('selectJob', { id: String(id) });
            if (window.state && F.activeWorkspace) {
              state.currentOrganization = workspaceState(F.activeWorkspace);
              state.workspaceId = F.activeWorkspace.id;
              state.organizationId = F.activeWorkspace.id;
            }
            return result;
          };
          wrapped.__floodmanIOSWrapped = true;
          window.loadJobData = wrapped;
          clearInterval(timer);
        } else if (attempts > 80) {
          clearInterval(timer);
        }
      }, 250);
    },

    applyIdentity() {
      if (window.state) {
        state.currentOrganization = workspaceState(this.activeWorkspace);
        state.workspaceId = this.activeWorkspace?.id || state.workspaceId || null;
        state.organizationId = state.workspaceId;
        state.costing = state.costing || {};
        state.costing.customerName = this.customer?.name || state.costing.customerName || '';
        state.costing.customerEmail = this.customer?.email || state.costing.customerEmail || '';
        state.costing.customerPhone = this.customer?.phone || state.costing.customerPhone || '';
        state.costing.customerAddress = [
          this.property?.service_street,
          this.property?.service_city,
          [this.property?.service_state, this.property?.service_postal_code].filter(Boolean).join(' '),
        ].filter(Boolean).join(', ') || state.costing.customerAddress || '';
      }
      const label = document.getElementById('fm-link');
      if (label) label.textContent = `${this.customer?.name || 'Choose customer'} · ${this.property?.property_name || this.property?.service_street || 'Choose property'}`;
    },

    chooseCustomer() {
      const query = prompt('Search Floodman customers:', '');
      if (query !== null) send('searchCustomers', { query, workspaceId: this.activeWorkspace?.id || '' });
    },

    receiveCustomers(encoded) {
      const rows = decode(encoded) || [];
      if (!rows.length) return this.toast('No matching Floodman customers.', true);
      const choice = Number(prompt(rows.slice(0, 20).map((item, index) => `${index + 1}. ${item.name || item.company || item.email}`).join('\n'), '1'));
      if (choice && rows[choice - 1]) {
        this.customer = rows[choice - 1];
        this.property = null;
        this.applyIdentity();
        send('searchProperties', { contactId: this.customer.id, query: '', workspaceId: this.activeWorkspace?.id || '' });
      }
    },

    receiveProperties(encoded) {
      const rows = decode(encoded) || [];
      if (!rows.length) {
        this.property = null;
        this.applyIdentity();
        return this.toast('No property found. Enter the service address in RoomFlow and Floodman will create it when saved.');
      }
      const choice = Number(prompt(rows.slice(0, 20).map((item, index) => `${index + 1}. ${item.property_name || item.name || item.service_street}`).join('\n'), '1'));
      if (choice && rows[choice - 1]) {
        this.property = rows[choice - 1];
        this.applyIdentity();
      }
    },

    snapshot() {
      try {
        if (window.autosaveJob) window.autosaveJob();
        const jobs = JSON.parse(localStorage.getItem('roomflow_jobs') || '{}');
        const name = window.state?.currentJobName;
        return name && jobs[name] ? jobs[name] : clone(window.state || {});
      } catch (_error) { return {}; }
    },

    layout() {
      for (const canvas of [document.getElementById('sketch-canvas'), document.querySelector('#three-container canvas')]) {
        try { if (canvas?.toDataURL) return canvas.toDataURL('image/jpeg', 0.9); } catch (_error) { }
      }
      return '';
    },

    sections() {
      const groups = {};
      (window.state?.costing?.customItems || []).forEach(item => {
        const header = item.sectionName || item.header || item.category || 'RoomFlow Scope';
        (groups[header] ??= []).push(item);
      });
      return Object.entries(groups).map(([title, items]) => ({
        title,
        description: 'Measured and priced in Floodman RoomFlow.',
        lines: items.map(item => ({
          catalog_item_id: item.catalogItemId || null,
          name: item.name || 'RoomFlow line item',
          description: item.description || '',
          category: item.category || 'General Services',
          unit: item.unit || 'each',
          quantity: Number(item.qty ?? item.quantity ?? 1),
          unit_price_cents: Math.round(Number(item.unitCost || item.unit_price || 0) * 100),
          taxable: Boolean(item.taxable),
          optional: Boolean(item.optional),
          save_to_catalog: !item.catalogItemId,
        })),
      }));
    },

    save() {
      const snapshot = this.snapshot();
      const costing = snapshot.costing || window.state?.costing || {};
      const property = this.property || {};
      this.toast('Saving RoomFlow job, actual layout, and estimate…');
      send('save', { payload: {
        roomflow_job_id: this.context?.job?.roomflow_job_id || snapshot.roomflowSourceJobId || null,
        job_name: window.state?.currentJobName || snapshot.currentJobName || costing.customerName || 'RoomFlow Job',
        contact_id: this.customer?.id || this.context?.customer?.id || null,
        property_id: property.id || this.context?.property?.id || null,
        estimate_id: this.context?.estimate?.id || this.context?.job?.estimate_id || null,
        workspace_id: this.activeWorkspace?.id || null,
        status: 'DRAFT',
        project_category: costing.projectCategory || 'general-restoration',
        title: costing.estimateHeader || window.state?.currentJobName || 'RoomFlow Estimate',
        customer_name: costing.customerName || this.customer?.name || '',
        customer_email: costing.customerEmail || this.customer?.email || '',
        customer_phone: costing.customerPhone || this.customer?.phone || '',
        property_address: costing.customerAddress || [property.service_street, property.service_city].filter(Boolean).join(', '),
        snapshot,
        summary: { rooms: Array.isArray(snapshot.rooms) ? snapshot.rooms.length : 0 },
        layout_data_url: this.layout(),
        sections: this.sections(),
        sync_estimate: true,
      }});
    },

    saveCompleted(encoded) {
      const result = decode(encoded);
      if (result?.job?.id) {
        send('selectJob', { id: result.job.id });
        this.context = result;
      }
      this.toast('RoomFlow job, actual layout, and estimate synchronized.');
    },

    saveFailed(message) { this.toast(message || 'RoomFlow synchronization failed.', true); },
    bootstrapFailed(message) { this.toast(message || 'RoomFlow cloud loading failed.', true); },
    close() { send('close'); },
  };

  function install() {
    document.getElementById('auth-overlay')?.remove();
    document.querySelectorAll('[onclick*="RoomFlowAuth"]').forEach(element => element.remove());
    window.hasCapability = () => true;
    window.RoomFlowAuth = { loadSessionContext: async () => true, signOut: async () => true };
    const bar = document.createElement('div');
    bar.id = 'fm-ios';
    bar.innerHTML = `
      <button onclick="FloodmanRoomFlow.close()">‹ Floodman</button>
      <span id="fm-ios-workspace">Loading company…</span>
      <span id="fm-link">Choose customer · Choose property</span>
      <button onclick="FloodmanRoomFlow.chooseCustomer()">Link</button>
      <button onclick="FloodmanRoomFlow.save()">Save</button>
      <span id="fm-ios-status">Loading…</span>`;
    document.body.appendChild(bar);
    const style = document.createElement('style');
    style.textContent = `
      #fm-ios{position:fixed;z-index:30000;left:0;right:0;top:0;display:flex;gap:6px;align-items:center;padding:7px;background:#0f2435;color:#fff;font:600 12px system-ui;box-shadow:0 2px 12px #0008}
      #fm-ios button{border:0;border-radius:7px;padding:9px;background:#0783ad;color:#fff;min-height:36px}
      #fm-ios-workspace{max-width:150px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
      #fm-link{flex:1;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
      #fm-ios-status{max-width:180px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;background:#047857;border-radius:12px;padding:4px 8px}
      #fm-ios-status[data-bad="1"]{background:#b91c1c}
      body{padding-top:50px!important}#auth-overlay{display:none!important}
      @media(max-width:700px){#fm-ios-status,#fm-link{display:none}#fm-ios-workspace{flex:1}}
    `;
    document.head.appendChild(style);
    F.patchJobLoading();
    setTimeout(() => send('ready'), 350);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
  else install();
})();
