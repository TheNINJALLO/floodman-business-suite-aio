// RoomFlow Townsquare Interactive integration UI.
// API credentials are sent only to the authenticated Supabase Edge Function.
(function () {
  'use strict';

  const Townsquare = {
    version: '1.0.3',
    configuration: null,
    extension: { installed: false, configured: false, destinationOrigin: '' },
    stationStatus: { configured: false, online: false, stations: [] },
    stations: [],
    stationTimer: null,
    queuedMonitorToken: 0,
    currentSync: null,
    syncCache: new Map(),
    observer: null,
    initialized: false,
    messageHandlersInstalled: false,

    get integration() { return window.RoomFlowIntegrations || null; },
    get client() { return this.integration?.getClient?.() || (typeof initSupabase === 'function' ? initSupabase() : null); },
    get organizationId() { return window.state?.currentOrganization?.id || ''; },
    get isAndroid() { return /Android/i.test(navigator.userAgent) || Boolean(window.RoomFlowAndroid); },
    get canManage() { return typeof hasCapability !== 'function' || hasCapability('manage_integrations'); },
    get canSync() { return typeof hasCapability !== 'function' || hasCapability('generate_proposals') || hasCapability('approve_proposals'); },

    escape(value) { return this.integration?.escape?.(value) || String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char])); },
    moneyMinor(value, currency = 'USD') { return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(Number(value || 0) / 100); },
    toast(message, type = 'info') { if (this.integration?.toast) this.integration.toast(message, type); },

    async invoke(action, payload = {}) {
      const client = this.client;
      if (!client || !this.organizationId || !state?.sessionUser) throw new Error('Sign in and select a RoomFlow company first.');
      const { data, error } = await client.functions.invoke('townsquare-sync', {
        body: { action, organization_id: this.organizationId, ...payload }
      });
      if (error) {
        let message = error.message || 'The Townsquare service request failed.';
        try {
          const response = error.context;
          if (response?.clone) {
            const detail = await response.clone().json();
            message = detail?.error?.message || message;
          }
        } catch { /* use sanitized SDK message */ }
        throw Object.assign(new Error(message), { code: data?.error?.code || 'EDGE_FUNCTION_ERROR' });
      }
      if (!data?.ok) throw Object.assign(new Error(data?.error?.message || 'The Townsquare request failed.'), { code: data?.error?.code || 'TOWNSQUARE_ERROR', details: data?.error?.details });
      return data;
    },

    async waitForRoomFlow() {
      for (let attempt = 0; attempt < 60; attempt += 1) {
        if (window.RoomFlowIntegrations && window.state) return true;
        await new Promise(resolve => setTimeout(resolve, 250));
      }
      return false;
    },

    async init() {
      if (this.initialized) return;
      this.initialized = true;
      this.installMessageHandlers();
      if (!await this.waitForRoomFlow()) {
        this.initialized = false;
        setTimeout(() => this.init(), 1000);
        return;
      }
      this.injectSettingsCard();
      this.renderEstimateAction();
      this.observer = new MutationObserver(() => {
        this.injectSettingsCard();
        this.renderEstimateAction();
      });
      this.observer.observe(document.body, { childList: true, subtree: true });
      await Promise.allSettled([
        this.detectExtension(),
        this.canManage ? this.loadConfiguration() : Promise.resolve(),
        this.canSync ? this.loadStationStatus() : Promise.resolve(),
        this.canManage ? this.loadStations() : Promise.resolve()
      ]);
      if (!this.stationTimer) {
        this.stationTimer = setInterval(() => {
          if (this.canSync) this.loadStationStatus().catch(() => {});
          if (this.canManage) this.loadStations().catch(() => {});
        }, 60000);
      }
    },

    installMessageHandlers() {
      if (this.messageHandlersInstalled) return;
      this.messageHandlersInstalled = true;
      window.addEventListener('message', event => {
        if (event.source !== window || event.origin !== location.origin || !event.data) return;
        if (event.data.type === 'ROOMFLOW_TOWNSQUARE_BRIDGE_STATUS' && event.data.protocolVersion === 1) {
          this.extension = {
            installed: Boolean(event.data.installed || event.data.connected),
            configured: Boolean(event.data.configured),
            destinationOrigin: event.data.destinationOrigin || ''
          };
          this.renderExtensionStatus();
        }
        if (event.data.type === 'ROOMFLOW_TOWNSQUARE_SYNC_PROGRESS' && event.data.protocolVersion === 1 && event.data.runId === this.currentSync?.runId) {
          this.updateProgress(event.data.status, event.data.message);
        }
        if (event.data.type === 'ROOMFLOW_TOWNSQUARE_SYNC_RESULT' && event.data.protocolVersion === 1 && event.data.runId === this.currentSync?.runId) {
          this.completeBridgeResult(event.data).catch(error => this.failSync(error));
        }
        if (event.data.type === 'ROOMFLOW_TOWNSQUARE_MAPPING_STATUS' && event.data.protocolVersion === 1) {
          this.toast(event.data.message, event.data.ok ? 'success' : 'error');
        }
      });
    },

    async detectExtension(timeout = 900) {
      this.extension.installed = false;
      window.postMessage({ type: 'ROOMFLOW_TOWNSQUARE_BRIDGE_PING', protocolVersion: 1 }, location.origin);
      await new Promise(resolve => setTimeout(resolve, timeout));
      this.renderExtensionStatus();
      return this.extension;
    },

    injectSettingsCard() {
      const host = document.getElementById('more-viewport');
      if (!host || document.getElementById('roomflow-townsquare-settings-card')) return;
      const card = document.createElement('section');
      card.id = 'roomflow-townsquare-settings-card';
      card.className = 'checklist-room-card townsquare-settings-card';
      if (!this.canManage) {
        card.innerHTML = `<div class="townsquare-card-heading"><div><span class="townsquare-eyebrow">External estimating</span><h3>Townsquare Interactive</h3><p>An integration manager must configure this company connection. Authorized estimators can run draft synchronization from the estimate builder.</p></div><span class="townsquare-status-pill">Managed by your company</span></div>`;
        host.appendChild(card);
        return;
      }
      card.innerHTML = `
        <div class="townsquare-card-heading">
          <div><span class="townsquare-eyebrow">External estimating</span><h3>Townsquare Interactive</h3><p>Create or update a Townsquare draft for final manual review. RoomFlow never sends, issues, approves, emails, or charges the customer.</p></div>
          <span id="townsquare-config-status" class="townsquare-status-pill">Loading…</span>
        </div>
        <div class="townsquare-settings-grid">
          <label class="townsquare-toggle"><input id="townsquare-enabled" type="checkbox"><span>Integration enabled</span></label>
          <label>Connection mode<select id="townsquare-mode"><option value="auto">Auto — API when complete, otherwise bridge</option><option value="api">Official API only</option><option value="browser_bridge">Desktop Browser Bridge only</option></select></label>
          <label class="townsquare-wide">Official API base URL<input id="townsquare-api-base" type="url" value="https://api.vcita.biz"><small>The Edge Function accepts only server-allowlisted HTTPS API hosts.</small></label>
          <label class="townsquare-wide">Townsquare browser destination URL<input id="townsquare-destination" type="url" placeholder="https://your Townsquare business-management page"></label>
          <label>Currency<input id="townsquare-currency" value="USD" maxlength="3"></label>
          <label>Estimate expiration (days)<input id="townsquare-expiration" type="number" min="1" max="365" value="30"></label>
          <label>Optional attachments<select id="townsquare-attachments"><option value="selected">Selected estimate attachments</option><option value="all_estimate">All estimate attachments</option><option value="none">Do not attach</option></select></label>
          <label>Official business UID (optional)<input id="townsquare-business-uid" autocomplete="off"></label>
          <label>Official tax UID (required for taxable API lines)<input id="townsquare-tax-uid" autocomplete="off"></label>
          <label class="townsquare-wide">Replace official API token<input id="townsquare-api-token" type="password" autocomplete="new-password" placeholder="Leave blank to keep the saved encrypted credential"><small>Sent directly to the Edge Function, encrypted with AES-GCM, and never stored in this browser or returned to RoomFlow.</small></label>
        </div>
        <div class="townsquare-settings-actions"><button id="townsquare-save-config" class="btn-primary">Save Configuration</button><button id="townsquare-test-api" class="btn-secondary">Test API</button><button id="townsquare-clear-token" class="btn-secondary">Clear API Credential</button><button id="townsquare-refresh-config" class="btn-secondary">Refresh</button></div>
        <div class="townsquare-connection-grid">
          <div><strong>Official API</strong><span id="townsquare-api-status">Not tested</span></div>
          <div><strong>Browser extension</strong><span id="townsquare-extension-status">Checking…</span></div>
          <div><strong>Last successful sync</strong><span id="townsquare-last-success">Never</span></div>
          <div><strong>Last failed sync</strong><span id="townsquare-last-failure">Never</span></div>
        </div>
        <div class="townsquare-bridge-instructions"><strong>Desktop bridge setup</strong><ol><li>Install the unpacked extension from <code>townsquare-bridge-extension</code> in Chrome or Edge.</li><li>Open its popup, save the same Townsquare URL, and grant access.</li><li>Sign in to Townsquare normally; the extension never reads your password or exports cookies.</li><li>Use guided mapping below if automatic control detection needs help.</li></ol><div class="townsquare-settings-actions"><button id="townsquare-start-mapping" class="btn-secondary">Start Guided Mapping</button><button id="townsquare-reset-mapping" class="btn-secondary">Test / Reset Mapping</button><button id="townsquare-view-diagnostics" class="btn-secondary">View Diagnostics</button></div></div>
        <div class="townsquare-station-management"><div class="townsquare-station-heading"><div><strong>Always-on Sync Station</strong><p>Pair a dedicated browser worker on an always-on Windows PC or Pterodactyl. Any authorized RoomFlow device can queue a draft for it.</p></div><span id="townsquare-station-summary" class="townsquare-status-pill">Not paired</span></div><div class="townsquare-station-create"><input id="townsquare-station-name" maxlength="80" value="Primary Sync Station" aria-label="Sync Station name"><button id="townsquare-create-station" class="btn-primary">Create Pairing Key</button><button id="townsquare-refresh-stations" class="btn-secondary">Refresh Stations</button></div><div id="townsquare-station-list" class="townsquare-station-list"><span>No Sync Station has been paired.</span></div></div>
        <div class="townsquare-api-limitation"><strong>Verified API limitation:</strong> current official inTandem OpenAPI specifications publish clients and draft estimates, but no separate service-property or estimate-attachment endpoint. Auto mode therefore uses the desktop bridge for the complete workflow.</div>`;
      host.appendChild(card);
      card.querySelector('#townsquare-save-config').addEventListener('click', () => this.saveConfiguration());
      card.querySelector('#townsquare-test-api').addEventListener('click', () => this.testApi());
      card.querySelector('#townsquare-clear-token').addEventListener('click', () => this.clearApiToken());
      card.querySelector('#townsquare-refresh-config').addEventListener('click', () => this.loadConfiguration());
      card.querySelector('#townsquare-start-mapping').addEventListener('click', () => this.startMapping(false));
      card.querySelector('#townsquare-reset-mapping').addEventListener('click', () => this.startMapping(true));
      card.querySelector('#townsquare-view-diagnostics').addEventListener('click', () => this.viewDiagnostics());
      card.querySelector('#townsquare-create-station').addEventListener('click', () => this.createStation());
      card.querySelector('#townsquare-refresh-stations').addEventListener('click', () => Promise.allSettled([this.loadStations(), this.loadStationStatus()]));
      card.querySelector('#townsquare-station-list').addEventListener('click', event => {
        const button = event.target.closest('[data-revoke-station]');
        if (button) this.revokeStation(button.dataset.revokeStation, button.dataset.stationName || 'Sync Station');
      });
    },

    fillConfiguration(configuration) {
      this.configuration = configuration;
      const values = {
        'townsquare-enabled': configuration.enabled,
        'townsquare-mode': configuration.connection_mode || 'auto',
        'townsquare-api-base': configuration.api_base_url || 'https://api.vcita.biz',
        'townsquare-destination': configuration.browser_destination_url || '',
        'townsquare-currency': configuration.currency || 'USD',
        'townsquare-expiration': configuration.estimate_expiration_days || 30,
        'townsquare-attachments': configuration.attachment_mode || 'selected',
        'townsquare-business-uid': configuration.provider_business_uid || '',
        'townsquare-tax-uid': configuration.provider_tax_uid || ''
      };
      Object.entries(values).forEach(([id, value]) => {
        const element = document.getElementById(id);
        if (!element) return;
        if (element.type === 'checkbox') element.checked = Boolean(value);
        else element.value = value;
      });
      const pill = document.getElementById('townsquare-config-status');
      if (pill) { pill.textContent = configuration.enabled ? 'Enabled' : 'Disabled'; pill.dataset.state = configuration.enabled ? 'success' : 'neutral'; }
      const api = document.getElementById('townsquare-api-status');
      if (api) api.textContent = configuration.has_api_token ? `Credential saved${configuration.credential_updated_at ? ` · ${new Date(configuration.credential_updated_at).toLocaleString()}` : ''}` : 'No API credential saved';
      const success = document.getElementById('townsquare-last-success');
      if (success) success.textContent = configuration.last_successful_sync_at ? new Date(configuration.last_successful_sync_at).toLocaleString() : 'Never';
      const failure = document.getElementById('townsquare-last-failure');
      if (failure) failure.textContent = configuration.last_failed_sync_at ? `${new Date(configuration.last_failed_sync_at).toLocaleString()}${configuration.last_error_code ? ` · ${configuration.last_error_code}` : ''}` : 'Never';
      this.renderExtensionStatus();
    },

    async loadConfiguration() {
      if (!this.canManage || !this.organizationId || !state?.sessionUser) return;
      try {
        const data = await this.invoke('get_configuration');
        this.fillConfiguration(data.configuration);
      } catch (error) {
        const pill = document.getElementById('townsquare-config-status');
        if (pill) { pill.textContent = error.message; pill.dataset.state = 'error'; }
      }
    },

    configurationFromForm() {
      return {
        enabled: document.getElementById('townsquare-enabled')?.checked,
        connection_mode: document.getElementById('townsquare-mode')?.value,
        api_base_url: document.getElementById('townsquare-api-base')?.value.trim() || 'https://api.vcita.biz',
        browser_destination_url: document.getElementById('townsquare-destination')?.value.trim(),
        currency: document.getElementById('townsquare-currency')?.value.trim().toUpperCase(),
        estimate_expiration_days: Number(document.getElementById('townsquare-expiration')?.value || 30),
        attachment_mode: document.getElementById('townsquare-attachments')?.value,
        provider_business_uid: document.getElementById('townsquare-business-uid')?.value.trim(),
        provider_tax_uid: document.getElementById('townsquare-tax-uid')?.value.trim(),
        api_token: document.getElementById('townsquare-api-token')?.value || ''
      };
    },

    async saveConfiguration() {
      try {
        const data = await this.invoke('save_configuration', { configuration: this.configurationFromForm() });
        const token = document.getElementById('townsquare-api-token');
        if (token) token.value = '';
        this.fillConfiguration(data.configuration);
        this.toast('Townsquare configuration saved securely.', 'success');
      } catch (error) { this.toast(error.message, 'error'); }
    },

    async testApi() {
      const output = document.getElementById('townsquare-api-status');
      if (output) output.textContent = 'Testing official API…';
      try {
        const data = await this.invoke('test_connection');
        if (output) output.textContent = data.connection.connected ? 'Connected · customers and draft estimates available' : 'Connection could not be confirmed';
        this.toast(data.connection.connected ? 'Official Townsquare API connection confirmed.' : 'API connection was not confirmed.', data.connection.connected ? 'success' : 'warning');
      } catch (error) { if (output) output.textContent = error.message; this.toast(error.message, 'error'); }
    },

    async clearApiToken() {
      if (!confirm('Clear the saved encrypted Townsquare API credential? Browser Bridge configuration will remain.')) return;
      try {
        const data = await this.invoke('clear_api_token');
        this.fillConfiguration(data.configuration);
        this.toast('Townsquare API credential cleared.', 'success');
      } catch (error) { this.toast(error.message, 'error'); }
    },

    async loadStationStatus() {
      if (!this.canSync || !this.organizationId || !state?.sessionUser) return;
      const previous = `${this.stationStatus.configured}:${this.stationStatus.online}`;
      try {
        const data = await this.invoke('get_sync_station_status');
        this.stationStatus = data.station_status || { configured: false, online: false, stations: [] };
        this.renderStationSummary();
        const current = `${this.stationStatus.configured}:${this.stationStatus.online}`;
        if (previous !== current) {
          document.querySelector('.townsquare-estimate-action')?.remove();
          this.renderEstimateAction();
        }
      } catch { /* synchronization can still fall back to a local desktop bridge */ }
    },

    async loadStations() {
      if (!this.canManage || !this.organizationId || !state?.sessionUser) return;
      try {
        const data = await this.invoke('list_sync_stations');
        this.stations = data.stations || [];
        this.renderStations();
      } catch (error) {
        const list = document.getElementById('townsquare-station-list');
        if (list) list.innerHTML = `<span>${this.escape(error.message)}</span>`;
      }
    },

    renderStationSummary() {
      const summary = document.getElementById('townsquare-station-summary');
      if (!summary) return;
      summary.textContent = this.stationStatus.online ? 'Online' : (this.stationStatus.configured ? 'Paired · offline' : 'Not paired');
      summary.dataset.state = this.stationStatus.online ? 'success' : (this.stationStatus.configured ? 'error' : 'neutral');
    },

    renderStations() {
      const list = document.getElementById('townsquare-station-list');
      if (!list) return;
      const active = this.stations.filter(station => station.enabled && !station.revoked_at);
      if (!active.length) {
        list.innerHTML = '<span>No active Sync Station has been paired.</span>';
      } else {
        list.innerHTML = active.map(station => {
          const seen = station.last_seen_at ? new Date(station.last_seen_at).toLocaleString() : 'Never';
          const state = station.online ? 'Online' : 'Offline';
          return `<div class="townsquare-station-row"><div><strong>${this.escape(station.name)}</strong><span data-state="${station.online ? 'success' : 'warning'}">${state} · last seen ${this.escape(seen)}</span>${station.last_error_code ? `<small>${this.escape(station.last_error_code)}</small>` : ''}</div><button class="btn-secondary" data-revoke-station="${this.escape(station.id)}" data-station-name="${this.escape(station.name)}">Revoke</button></div>`;
        }).join('');
      }
      this.stationStatus = {
        configured: active.length > 0,
        online: active.some(station => station.online),
        stations: active
      };
      this.renderStationSummary();
    },

    async createStation() {
      const name = document.getElementById('townsquare-station-name')?.value.trim() || 'Primary Sync Station';
      try {
        const data = await this.invoke('create_sync_station', { station_name: name });
        const credentials = data.result.credentials;
        const pairing = [
          `ROOMFLOW_FUNCTION_URL=${credentials.function_url}`,
          `ROOMFLOW_STATION_ID=${credentials.station_id}`,
          `ROOMFLOW_STATION_TOKEN=${credentials.station_token}`
        ].join('\n');
        this.showInformationDialog('Sync Station pairing key', `<div class="townsquare-result-card"><strong>Copy this now</strong><p>The token is shown once. Use these values with the Windows installer or add them as Pterodactyl variables.</p></div><pre class="townsquare-diagnostics" id="townsquare-station-pairing">${this.escape(pairing)}</pre><button class="btn-primary" data-copy-station-pairing>Copy Pairing Variables</button>`);
        document.querySelector('[data-copy-station-pairing]')?.addEventListener('click', async event => {
          try {
            await navigator.clipboard.writeText(pairing);
            event.currentTarget.textContent = 'Copied';
          } catch { this.toast('Select and copy the pairing variables manually.', 'warning'); }
        });
        await Promise.allSettled([this.loadStations(), this.loadStationStatus()]);
      } catch (error) { this.toast(error.message, 'error'); }
    },

    async revokeStation(stationId, stationName) {
      if (!confirm(`Revoke ${stationName}? Its station runner will no longer be able to claim queued drafts.`)) return;
      try {
        await this.invoke('revoke_sync_station', { station_id: stationId });
        await Promise.allSettled([this.loadStations(), this.loadStationStatus()]);
        this.toast('Sync Station access revoked.', 'success');
      } catch (error) { this.toast(error.message, 'error'); }
    },

    renderExtensionStatus() {
      const output = document.getElementById('townsquare-extension-status');
      if (!output) return;
      output.textContent = this.extension.installed
        ? (this.extension.configured ? `Connected · ${this.extension.destinationOrigin || 'destination configured'}` : 'Installed · save destination in extension popup')
        : 'Not detected · desktop Chrome/Edge extension required';
      output.dataset.state = this.extension.installed && this.extension.configured ? 'success' : 'warning';
    },

    startMapping(reset) {
      if (!this.canManage) return this.toast('Integration management permission is required.', 'error');
      window.postMessage({ type: 'ROOMFLOW_TOWNSQUARE_START_MAPPING', protocolVersion: 1, reset: Boolean(reset) }, location.origin);
      setTimeout(() => { if (!this.extension.installed) this.toast('The Townsquare bridge extension was not detected. Install it and refresh RoomFlow.', 'warning'); }, 800);
    },

    async viewDiagnostics() {
      try {
        const data = await this.invoke('get_diagnostics');
        this.showInformationDialog('Townsquare sync diagnostics', `<pre class="townsquare-diagnostics">${this.escape(JSON.stringify(data.diagnostics, null, 2))}</pre>`);
      } catch (error) { this.toast(error.message, 'error'); }
    },

    renderEstimateAction() {
      const panel = document.getElementById('roomflow-inline-estimate-builder');
      if (!panel || panel.querySelector('.townsquare-estimate-action')) return;
      const area = document.createElement('section');
      area.className = 'townsquare-estimate-action';
      const estimateId = this.integration?.currentEstimateId || '';
      const cached = estimateId ? this.syncCache.get(estimateId) : null;
      const mapping = cached?.mapping;
      const update = Boolean(mapping?.provider_entity_id);
      const label = this.stationStatus.configured
        ? `${update ? 'Update' : 'Create'} via Sync Station`
        : (this.isAndroid && !update ? 'Queue Townsquare Sync for Desktop' : `${update ? 'Update' : 'Create'} Townsquare Draft`);
      const description = this.stationStatus.configured
        ? `The paired Sync Station will process this draft${this.stationStatus.online ? ' now' : ' when it comes online'}. Final sending remains manual in Townsquare.`
        : (this.isAndroid ? 'Browser Bridge requires desktop Chrome or Edge. Queue this estimate and finish from the desktop RoomFlow page.' : 'RoomFlow validates and transfers this estimate only after you press the button. Final sending remains manual in Townsquare.');
      area.innerHTML = `
        <div><span class="townsquare-eyebrow">Final external draft</span><h4>${update ? 'Townsquare draft connected' : 'Create a Townsquare draft'}</h4><p>${this.escape(description)}</p></div>
        <div class="townsquare-estimate-buttons"><button class="btn-primary townsquare-sync-button" ${this.canSync ? '' : 'disabled'}>${this.escape(label)}</button>${mapping?.provider_url ? `<a class="btn-secondary" href="${this.escape(mapping.provider_url)}" target="_blank" rel="noopener">Review in Townsquare</a>` : ''}</div>
        <div class="townsquare-sync-mini-history">${this.renderMiniHistory(cached?.runs || [])}</div>`;
      panel.appendChild(area);
      area.querySelector('.townsquare-sync-button')?.addEventListener('click', () => this.syncEstimate());
      if (estimateId && !cached) this.loadEstimateSync(estimateId);
    },

    renderMiniHistory(runs) {
      if (!runs?.length) return '<span>No Townsquare synchronization has been recorded for this estimate.</span>';
      return runs.slice(0, 3).map(run => `<span><strong>${this.escape(run.status.replaceAll('_', ' '))}</strong> · ${this.escape(new Date(run.created_at).toLocaleString())}${run.error_message ? ` · ${this.escape(run.error_message)}` : ''}</span>`).join('');
    },

    async loadEstimateSync(estimateId) {
      try {
        const data = await this.invoke('get_estimate_sync', { estimate_id: estimateId });
        this.syncCache.set(estimateId, data.sync);
        document.querySelector('.townsquare-estimate-action')?.remove();
        this.renderEstimateAction();
      } catch { /* button remains usable; server will validate on click */ }
    },

    async activeSyncForEstimate(estimateId) {
      const data = await this.invoke('get_estimate_sync', { estimate_id: estimateId });
      const sync = data.sync || { mapping: null, runs: [] };
      this.syncCache.set(estimateId, sync);
      return sync.runs?.find(run => ['validating', 'queued', 'opening_townsquare'].includes(run.status)) || null;
    },

    progressStages() {
      return [
        ['validating', 'Validate RoomFlow estimate'], ['queued', 'Queue for Sync Station'], ['opening_townsquare', 'Open Townsquare'],
        ['finding_customer', 'Match or create customer'], ['finding_property', 'Match or create property'],
        ['creating_estimate', 'Create or update draft'], ['attaching_documents', 'Attach selected documents'],
        ['draft_created', 'Confirm Townsquare draft'], ['completed', 'Ready for manual review']
      ];
    },

    showProgressDialog() {
      document.getElementById('townsquare-progress-dialog')?.remove();
      const overlay = document.createElement('div');
      overlay.id = 'townsquare-progress-dialog';
      overlay.className = 'townsquare-dialog-overlay';
      overlay.innerHTML = `<div class="townsquare-dialog" role="dialog" aria-modal="true" aria-labelledby="townsquare-progress-title"><div class="townsquare-dialog-heading"><div><span class="townsquare-eyebrow">Draft-only synchronization</span><h3 id="townsquare-progress-title">Creating Townsquare Draft</h3></div><button class="townsquare-dialog-close" aria-label="Close" disabled>×</button></div><p id="townsquare-progress-message">Preparing the RoomFlow estimate…</p><ol class="townsquare-progress-list">${this.progressStages().map(([status, label]) => `<li data-stage="${status}"><span></span><strong>${label}</strong></li>`).join('')}</ol><div id="townsquare-progress-result"></div></div>`;
      document.body.appendChild(overlay);
      overlay.querySelector('.townsquare-dialog-close').addEventListener('click', () => overlay.remove());
    },

    updateProgress(status, message) {
      const aliases = { customer_matched: 'finding_customer', customer_created: 'finding_customer', property_matched: 'finding_property', property_created: 'finding_property', updating_estimate: 'creating_estimate', review_required: 'draft_created' };
      const target = aliases[status] || status;
      const stages = this.progressStages().map(([key]) => key);
      const index = stages.indexOf(target);
      document.querySelectorAll('.townsquare-progress-list li').forEach((item, itemIndex) => {
        item.dataset.state = itemIndex < index ? 'complete' : itemIndex === index ? 'current' : 'pending';
      });
      const text = document.getElementById('townsquare-progress-message');
      if (text) text.textContent = message || status.replaceAll('_', ' ');
      const button = document.querySelector('.townsquare-sync-button');
      if (button) { button.disabled = true; button.textContent = message || status.replaceAll('_', ' '); }
    },

    async syncEstimate() {
      if (!this.canSync) return this.toast('Estimate permission is required.', 'error');
      if (!this.organizationId || !state?.sessionUser) return this.toast('Sign in and select a company first.', 'warning');
      this.showProgressDialog();
      this.updateProgress('validating', 'Checking for an existing Townsquare synchronization');
      try {
        const existingEstimateId = this.integration?.currentEstimateId || '';
        if (existingEstimateId) {
          const activeRun = await this.activeSyncForEstimate(existingEstimateId);
          if (activeRun) {
            await this.loadStationStatus().catch(() => {});
            const stationRun = Boolean(activeRun.station_id) || (activeRun.status === 'queued' && this.stationStatus.configured);
            const queueTarget = stationRun ? 'station' : 'desktop';
            this.currentSync = { runId: activeRun.id, estimateId: existingEstimateId, queueTarget };
            if (activeRun.status === 'queued') {
              this.updateProgress('queued', stationRun
                ? (this.stationStatus.online ? 'This draft is already queued for the online Sync Station' : 'This draft is already queued until the Sync Station reconnects')
                : 'This draft is already queued for a desktop browser');
              this.showQueued({ queue_target: queueTarget, station_online: this.stationStatus.online, run: activeRun });
            } else {
              this.updateProgress(activeRun.status, stationRun
                ? 'The Sync Station already claimed this draft and is working in Townsquare'
                : 'This Townsquare synchronization is already in progress');
              const output = document.getElementById('townsquare-progress-result');
              if (output) output.innerHTML = '<div class="townsquare-result-card"><strong>Synchronization already in progress</strong><p>RoomFlow reconnected to the existing run. No duplicate draft was queued.</p></div>';
              const close = document.querySelector('.townsquare-dialog-close');
              if (close) close.disabled = false;
              this.resetActionButton();
            }
            this.monitorQueuedSync(existingEstimateId, activeRun.id).catch(error => this.failSync(error));
            return;
          }
        }
        this.updateProgress('validating', 'Saving and validating the RoomFlow draft');
        const estimate = await this.integration.saveDraftEstimate({ throwOnError: true });
        if (!estimate?.id) throw new Error('RoomFlow did not return a saved estimate ID. Save Draft and retry.');
        await this.loadStationStatus().catch(() => {});
        const response = await this.invoke('sync_estimate', { estimate_id: estimate.id, prefer_station: true });
        const result = response.result;
        if (result.completed) {
          this.showSuccess(result.run);
          return;
        }
        if (result.queued) {
          const stationQueued = result.queue_target === 'station';
          if (stationQueued) {
            this.stationStatus = { ...this.stationStatus, configured: true, online: Boolean(result.station_online) };
          }
          this.updateProgress('queued', stationQueued
            ? (result.station_online ? 'Queued for the online Sync Station' : 'Queued until the Sync Station comes online')
            : 'Queued for a desktop browser');
          this.showQueued(result);
          await this.loadEstimateSync(estimate.id);
          if (stationQueued && result.run?.id) {
            this.currentSync = { runId: result.run.id, estimateId: estimate.id, queueTarget: 'station' };
            this.monitorQueuedSync(estimate.id, result.run.id).catch(error => this.failSync(error));
          }
          return;
        }
        if (!result.bridge_required) throw new Error('Townsquare did not return a supported synchronization route.');
        if (this.isAndroid) {
          const queued = await this.invoke('queue_bridge_sync', { estimate_id: estimate.id });
          this.updateProgress('completed', 'Queued for desktop Browser Bridge');
          this.showQueued(queued.result);
          await this.loadEstimateSync(estimate.id);
          return;
        }
        this.currentSync = { runId: result.run.id, bridgeToken: result.bridge_token, estimateId: estimate.id };
        this.updateProgress('opening_townsquare', 'Opening Townsquare in your authenticated desktop browser');
        await this.detectExtension(700);
        if (!this.extension.installed) {
          await this.invoke('cancel_bridge_sync', { run_id: result.run.id, bridge_token: result.bridge_token }).catch(() => {});
          throw new Error('The RoomFlow Townsquare Bridge extension is not detected. Install it in desktop Chrome or Edge, refresh RoomFlow, and retry.');
        }
        window.postMessage({
          type: 'ROOMFLOW_TOWNSQUARE_SYNC_REQUEST', protocolVersion: 1,
          runId: result.run.id, bridgeToken: result.bridge_token,
          destinationUrl: result.destination_url, expiresAt: result.run.expires_at,
          payload: result.payload
        }, location.origin);
      } catch (error) { this.failSync(error); }
    },

    async completeBridgeResult(message) {
      if (!this.currentSync || message.runId !== this.currentSync.runId) return;
      const data = await this.invoke('complete_bridge_sync', {
        run_id: message.runId,
        bridge_token: message.bridgeToken,
        result: message.result
      });
      if (data.result.status === 'completed') {
        this.updateProgress('completed', 'Draft confirmed. Review and send manually in Townsquare.');
        this.showSuccess(data.result);
      } else if (data.result.status === 'review_required') {
        throw new Error(data.result.review_reason || 'Townsquare requires manual review before the draft can be confirmed.');
      } else if (data.result.status === 'cancelled') {
        throw new Error('Townsquare synchronization was cancelled.');
      } else {
        throw new Error(data.result.error?.message || 'Townsquare synchronization failed.');
      }
      await this.loadEstimateSync(this.currentSync.estimateId);
      this.currentSync = null;
    },

    async monitorQueuedSync(estimateId, runId) {
      const token = ++this.queuedMonitorToken;
      for (let attempt = 0; attempt < 200; attempt += 1) {
        await new Promise(resolve => setTimeout(resolve, attempt === 0 ? 1000 : 3000));
        if (token !== this.queuedMonitorToken || this.currentSync?.runId !== runId) return;
        let data;
        try {
          data = await this.invoke('get_estimate_sync', { estimate_id: estimateId });
        } catch {
          if (attempt < 3) continue;
          this.updateProgress('queued', 'Queued; waiting for the next server status update');
          continue;
        }
        const sync = data.sync || { mapping: null, runs: [] };
        this.syncCache.set(estimateId, sync);
        const run = sync.runs?.find(item => item.id === runId);
        if (!run) continue;
        if (run.status === 'queued') {
          if (this.currentSync?.queueTarget !== 'station') {
            this.updateProgress('queued', 'Queued for a desktop browser to continue');
          } else if (attempt >= 5) {
            await this.loadStationStatus().catch(() => {});
            this.updateProgress('queued', this.stationStatus.online
              ? 'Queued; the online Sync Station has not claimed this draft yet'
              : 'Queued; waiting for the Sync Station to reconnect');
          }
          continue;
        }
        if (run.status === 'opening_townsquare') {
          this.updateProgress('opening_townsquare', this.currentSync?.queueTarget === 'station'
            ? 'The Sync Station claimed this draft and is opening Townsquare'
            : 'The desktop Browser Bridge is opening Townsquare');
          continue;
        }
        if (run.status === 'completed') {
          this.updateProgress('completed', 'The Sync Station confirmed the saved Townsquare draft');
          this.showSuccess(run);
          this.currentSync = null;
          document.querySelector('.townsquare-estimate-action')?.remove();
          this.renderEstimateAction();
          return;
        }
        if (run.status === 'failed') throw Object.assign(new Error(run.error_message || 'The Sync Station failed to create the Townsquare draft.'), { code: run.error_code || 'STATION_SYNC_FAILED' });
        if (run.status === 'review_required') throw Object.assign(new Error(run.review_reason || 'Review Townsquare before retrying this draft.'), { code: 'STATION_REVIEW_REQUIRED' });
        if (run.status === 'cancelled') throw Object.assign(new Error('The Sync Station synchronization was cancelled.'), { code: 'STATION_SYNC_CANCELLED' });
      }
      this.updateProgress('queued', 'Still queued; check that the paired Sync Station remains online and ready');
    },

    showQueued(result) {
      const output = document.getElementById('townsquare-progress-result');
      const stationQueued = result?.queue_target === 'station';
      const stationOnline = stationQueued && Boolean(result?.station_online);
      if (output) output.innerHTML = stationQueued
        ? `<div class="townsquare-result-card"><strong>Queued for Sync Station</strong><p>${stationOnline ? 'The station is online and will claim this draft automatically.' : 'The station is currently unavailable. The draft will remain queued and will be claimed after it reconnects.'} Nothing will be sent to the customer.</p></div>`
        : `<div class="townsquare-result-card"><strong>Queued for desktop</strong><p>Open this estimate in the desktop RoomFlow site with Chrome or Edge, then press Create Townsquare Draft. Browser extensions cannot run inside the Android application.</p></div>`;
      const close = document.querySelector('.townsquare-dialog-close');
      if (close) close.disabled = false;
      this.resetActionButton();
    },

    showSuccess(result) {
      const draft = result.draft || result;
      const summary = result.summary || result.result_summary || {};
      const totalMinor = draft.total_minor ?? result.provider_total_minor ?? result.roomflow_total_minor;
      const draftId = draft.id || draft.provider_estimate_id || result.provider_estimate_id;
      const draftUrl = draft.url || draft.provider_estimate_url || result.provider_estimate_url;
      const syncTime = result.completed_at || result.sync_time || new Date().toISOString();
      const output = document.getElementById('townsquare-progress-result');
      if (output) output.innerHTML = `<div class="townsquare-success-banner"><strong>Draft Created</strong><span>Nothing was sent to the customer.</span></div><div class="townsquare-result-grid"><div><span>Customer</span><strong>${this.escape(summary.customer || 'matched')}</strong></div><div><span>Property</span><strong>${this.escape(summary.property || 'matched')}</strong></div><div><span>Estimate</span><strong>${this.escape(summary.estimate || draftId || 'draft')}</strong></div><div><span>Total</span><strong>${Number.isFinite(Number(totalMinor)) ? this.moneyMinor(Number(totalMinor), this.configuration?.currency || 'USD') : 'Confirmed in Townsquare'}</strong></div><div><span>Sync time</span><strong>${this.escape(new Date(syncTime).toLocaleString())}</strong></div></div>${draftUrl ? `<a class="btn-primary townsquare-review-button" href="${this.escape(draftUrl)}" target="_blank" rel="noopener">Review in Townsquare</a>` : '<p>Return to the authenticated Townsquare tab to review this draft.</p>'}`;
      const close = document.querySelector('.townsquare-dialog-close');
      if (close) close.disabled = false;
      this.toast('Townsquare draft confirmed. Final sending remains manual.', 'success');
      this.resetActionButton();
    },

    failSync(error) {
      this.queuedMonitorToken += 1;
      const output = document.getElementById('townsquare-progress-result');
      if (output) output.innerHTML = `<div class="townsquare-error-banner"><strong>Sync Failed</strong><p>${this.escape(error.message || String(error))}</p><button class="btn-secondary townsquare-retry">Retry Sync</button></div>`;
      output?.querySelector('.townsquare-retry')?.addEventListener('click', () => this.syncEstimate());
      const text = document.getElementById('townsquare-progress-message');
      if (text) text.textContent = 'RoomFlow stopped safely before claiming success.';
      const close = document.querySelector('.townsquare-dialog-close');
      if (close) close.disabled = false;
      this.toast(error.message || String(error), 'error');
      this.resetActionButton();
      this.currentSync = null;
    },

    resetActionButton() {
      const button = document.querySelector('.townsquare-sync-button');
      if (!button) return;
      const estimateId = this.integration?.currentEstimateId || '';
      const update = Boolean(estimateId && this.syncCache.get(estimateId)?.mapping?.provider_entity_id);
      button.disabled = !this.canSync;
      button.textContent = this.stationStatus.configured
        ? `${update ? 'Update' : 'Create'} via Sync Station`
        : (this.isAndroid ? 'Queue Townsquare Sync for Desktop' : `${update ? 'Update' : 'Create'} Townsquare Draft`);
    },

    showInformationDialog(title, html) {
      const overlay = document.createElement('div');
      overlay.className = 'townsquare-dialog-overlay';
      overlay.innerHTML = `<div class="townsquare-dialog" role="dialog" aria-modal="true"><div class="townsquare-dialog-heading"><h3>${this.escape(title)}</h3><button class="townsquare-dialog-close" aria-label="Close">×</button></div>${html}</div>`;
      document.body.appendChild(overlay);
      overlay.querySelector('.townsquare-dialog-close').addEventListener('click', () => overlay.remove());
    }
  };

  window.RoomFlowTownsquare = Townsquare;
  if (document.readyState === 'loading') window.addEventListener('load', () => setTimeout(() => Townsquare.init(), 900), { once: true });
  else setTimeout(() => Townsquare.init(), 0);
})();
