// RoomFlow Phase 1 Integration Layer
// Adds atomic company creation, inbound email leads, shared tracking,
// cloud estimate catalog, inline estimates, layout attachments, and outreach scheduling.
(function () {
    'use strict';

    const Integration = {
        version: '1.2.2',
        client: null,
        leadChannel: null,
        leadChannelOrgId: null,
        sharedRefreshTimer: null,
        jobIdMapKey: 'roomflow_cloud_job_ids_v1',
        estimateDraftKey: 'roomflow_estimate_drafts_v1',
        catalogCache: [],
        currentLines: [],
        currentEstimateId: null,
        currentEstimateHeader: '',
        currentServiceStreet: '',
        currentServiceCity: '',
        currentServiceState: '',
        currentServicePostalCode: '',
        currentEstimateJobName: null,
        mainEstimateSyncJob: null,
        initialized: false,

        getClient() {
            if (this.client) return this.client;
            if (typeof initSupabase === 'function') this.client = initSupabase();
            return this.client;
        },

        escape(value) {
            return String(value ?? '')
                .replaceAll('&', '&amp;')
                .replaceAll('<', '&lt;')
                .replaceAll('>', '&gt;')
                .replaceAll('"', '&quot;')
                .replaceAll("'", '&#039;');
        },

        money(value) {
            return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
                .format(Number(value) || 0);
        },

        parseServiceAddress(value) {
            const parts = String(value || '').split(',').map(part => part.trim()).filter(Boolean);
            if (parts.length < 2) return { street: parts[0] || '', city: '', state: '', postalCode: '' };
            const tail = parts.at(-1) || '';
            const region = tail.match(/^(.+?)\s+([A-Za-z0-9-]{3,12})$/);
            const stateValue = region ? region[1].trim() : (parts.length >= 3 ? tail : '');
            const postalCode = region ? region[2].trim() : '';
            const cityIndex = parts.length >= 3 ? parts.length - 2 : 1;
            return {
                street: parts.slice(0, cityIndex).join(', '),
                city: parts[cityIndex] || '',
                state: stateValue,
                postalCode
            };
        },

        serviceAddress() {
            return [
                this.currentServiceStreet,
                this.currentServiceCity,
                [this.currentServiceState, this.currentServicePostalCode].filter(Boolean).join(' ')
            ].map(value => String(value || '').trim()).filter(Boolean).join(', ');
        },

        slug(value) {
            return String(value || '')
                .toLowerCase()
                .normalize('NFKD')
                .replace(/[\u0300-\u036f]/g, '')
                .replace(/[^a-z0-9]+/g, '-')
                .replace(/^-+|-+$/g, '')
                .slice(0, 64) || `item-${Date.now()}`;
        },

        randomToken(bytes = 24) {
            const values = new Uint8Array(bytes);
            crypto.getRandomValues(values);
            return Array.from(values, b => b.toString(16).padStart(2, '0')).join('');
        },

        async sha256(value) {
            const data = new TextEncoder().encode(value);
            const digest = await crypto.subtle.digest('SHA-256', data);
            return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
        },

        currentOrgId() {
            return state?.currentOrganization?.id || null;
        },

        currentJobId() {
            const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
            if (uuidPattern.test(String(state?.jobId || ''))) return state.jobId;
            const map = JSON.parse(localStorage.getItem(this.jobIdMapKey) || '{}');
            const mapped = state?.currentJobName ? map[state.currentJobName] || null : null;
            return uuidPattern.test(String(mapped || '')) ? mapped : null;
        },

        setJobMapping(jobName, jobId) {
            if (!jobName || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(String(jobId || ''))) return;
            const map = JSON.parse(localStorage.getItem(this.jobIdMapKey) || '{}');
            map[jobName] = jobId;
            localStorage.setItem(this.jobIdMapKey, JSON.stringify(map));
            state.jobId = jobId;
        },

        toast(message, type = 'info') {
            const existing = document.getElementById('roomflow-integration-toast');
            if (existing) existing.remove();
            const el = document.createElement('div');
            el.id = 'roomflow-integration-toast';
            el.textContent = message;
            const colors = { info: '#2563eb', success: '#059669', error: '#dc2626', warning: '#d97706' };
            Object.assign(el.style, {
                position: 'fixed', right: '20px', bottom: '20px', zIndex: '20000',
                maxWidth: '420px', padding: '0.85rem 1rem', borderRadius: '10px',
                background: colors[type] || colors.info, color: '#fff', fontWeight: '700',
                boxShadow: '0 18px 40px rgba(0,0,0,.35)'
            });
            document.body.appendChild(el);
            setTimeout(() => el.remove(), 5000);
        },

        async init() {
            if (this.initialized) return;
            this.initialized = true;
            this.patchCompanyCreation();
            this.patchOrganizationSwitching();
            this.patchJobPersistence();
            this.patchRenderers();
            this.injectSettingsCards();
            this.injectLeadPanel();
            await this.waitForSession();
            await Promise.allSettled([
                this.refreshInboundLeads(),
                this.refreshIntegrationDiagnostics(),
                this.loadCatalog(),
                window.RoomFlowSync?.refreshSharedJobs?.()
            ]);
            this.subscribeRealtime();
        },

        async waitForSession() {
            for (let i = 0; i < 30; i++) {
                if (state?.sessionUser && state?.currentOrganization) return true;
                await new Promise(resolve => setTimeout(resolve, 250));
            }
            return false;
        },

        patchCompanyCreation() {
            const install = () => {
                if (!window.RoomFlowAuth || window.RoomFlowAuth.__phase1CompanyPatch) return false;
                const original = window.RoomFlowAuth.createCompany?.bind(window.RoomFlowAuth);
                window.RoomFlowAuth.createCompany = async (name) => {
                    const client = Integration.getClient();
                    if (!client || !state.sessionUser) throw new Error('Authentication required');
                    const companyName = String(name || '').trim();
                    if (companyName.length < 2) throw new Error('Company name must contain at least 2 characters');

                    let result = await client.rpc('create_new_company_with_owner', { company_name: companyName });
                    if (result.error && /function.*does not exist|schema cache/i.test(result.error.message || '')) {
                        result = await client.rpc('create_new_company_with_owner', {
                            company_name: companyName,
                            owner_id: state.sessionUser.id
                        });
                    }
                    if (result.error) {
                        if (original && /does not exist/i.test(result.error.message || '')) return original(companyName);
                        throw new Error(result.error.message);
                    }

                    const newOrgId = result.data;
                    localStorage.setItem('roomflow_active_org_id', newOrgId);
                    await window.RoomFlowAuth.loadSessionContext();
                    await window.RoomFlowAuth.setActiveOrganization(newOrgId);
                    const visible = state.userOrganizations.some(org => org.id === newOrgId);
                    if (!visible) throw new Error('Company was created, but owner membership was not established. Apply the Phase 1 Supabase migration.');
                    if (typeof populateCompanySwitcher === 'function') populateCompanySwitcher();
                    Integration.injectSettingsCards();
                    await Integration.refreshInboundLeads();
                    return newOrgId;
                };
                window.RoomFlowAuth.__phase1CompanyPatch = true;
                return true;
            };
            if (!install()) setTimeout(install, 500);
        },

        patchOrganizationSwitching() {
            const install = () => {
                if (!window.RoomFlowAuth || window.RoomFlowAuth.__phase1OrganizationPatch) return false;
                const original = window.RoomFlowAuth.setActiveOrganization?.bind(window.RoomFlowAuth);
                if (!original) return false;
                window.RoomFlowAuth.setActiveOrganization = async orgId => {
                    const result = await original(orgId);
                    Integration.resetRealtimeSubscription();
                    await Promise.allSettled([
                        Integration.refreshInboundLeads(),
                        Integration.refreshIntegrationDiagnostics(),
                        Integration.loadCatalog(true)
                    ]);
                    Integration.subscribeRealtime();
                    return result;
                };
                window.RoomFlowAuth.__phase1OrganizationPatch = true;
                return true;
            };
            if (!install()) setTimeout(install, 500);
        },

        patchJobPersistence() {
            const install = () => {
                if (window.__roomflowPhase1PersistencePatched) return true;
                if (typeof window.loadJobData !== 'function' || typeof window.autosaveJob !== 'function') return false;

                const originalLoad = window.loadJobData;
                window.loadJobData = function (data) {
                    const result = originalLoad(data);
                    if (data?.jobId) Integration.setJobMapping(state.currentJobName || data.currentJobName || data.name, data.jobId);
                    else if (state.currentJobName) state.jobId = Integration.currentJobId();
                    return result;
                };

                const originalAutosave = window.autosaveJob;
                window.autosaveJob = function () {
                    const result = originalAutosave();
                    if (state.currentJobName) {
                        const jobs = JSON.parse(localStorage.getItem('roomflow_jobs') || '{}');
                        if (jobs[state.currentJobName]) {
                            jobs[state.currentJobName].jobId = Integration.currentJobId();
                            jobs[state.currentJobName].organizationId = Integration.currentOrgId();
                            localStorage.setItem('roomflow_jobs', JSON.stringify(jobs));
                        }
                    }
                    return result;
                };
                window.__roomflowPhase1PersistencePatched = true;
                return true;
            };
            if (!install()) setTimeout(install, 800);
        },

        patchRenderers() {
            const install = () => {
                if (window.__roomflowPhase1RenderPatched) return true;
                let installed = false;
                if (typeof window.renderGuidedStep === 'function') {
                    const original = window.renderGuidedStep;
                    window.renderGuidedStep = function (...args) {
                        const result = original.apply(this, args);
                        setTimeout(() => Integration.renderEstimateBuilder(), 0);
                        return result;
                    };
                    installed = true;
                }
                if (typeof window.renderCostUI === 'function') {
                    const originalCost = window.renderCostUI;
                    window.renderCostUI = function (...args) {
                        const result = originalCost.apply(this, args);
                        setTimeout(() => Integration.renderEstimateBuilder(true), 0);
                        return result;
                    };
                    installed = true;
                }
                if (installed) window.__roomflowPhase1RenderPatched = true;
                return installed;
            };
            if (!install()) setTimeout(install, 900);
        },

        injectLeadPanel() {
            const host = document.getElementById('jobs-viewport');
            if (!host || document.getElementById('roomflow-inbound-leads-card')) return;
            const card = document.createElement('section');
            card.id = 'roomflow-inbound-leads-card';
            card.className = 'checklist-room-card';
            card.style.padding = '1.25rem';
            card.innerHTML = `
                <div class="roomflow-leads-heading">
                    <div><h3 style="margin:0;color:#fff;">Leads</h3><p style="margin:.25rem 0 0;color:#94a3b8;font-size:.8rem;">New inquiries from Zapier and RoomFlow appear here with every available lead field.</p></div>
                    <button id="roomflow-refresh-leads" class="btn-secondary">Refresh</button>
                </div>
                <div id="roomflow-inbound-leads-list" class="roomflow-inbound-leads-list" tabindex="0" role="region" aria-label="Leads list"><div style="color:#64748b;">Sign in and select a company to load leads.</div></div>`;
            const listSection = host.querySelector('.jobs-list-section');
            host.insertBefore(card, listSection || host.lastChild);
            document.getElementById('roomflow-refresh-leads')?.addEventListener('click', () => this.refreshInboundLeads());
        },

        leadAddress(street, city, region, postalCode) {
            const base = String(street || '').trim();
            const baseLower = base.toLowerCase();
            const missing = value => value && !baseLower.includes(String(value).trim().toLowerCase());
            const locality = [
                missing(city) ? city : '',
                [missing(region) ? region : '', missing(postalCode) ? postalCode : ''].filter(Boolean).join(' ')
            ].filter(Boolean).join(', ');
            return [base, locality].filter(Boolean).join(', ');
        },

        leadViewModel(job, intake = null) {
            const customer = Array.isArray(job?.customers) ? job.customers[0] : job?.customers;
            const normalized = intake?.normalized_payload || {};
            const appointmentStart = job?.appointment_start || normalized.appointmentStart || null;
            const appointmentEnd = normalized.appointmentEnd || null;
            const appointment = appointmentStart
                ? `${new Date(appointmentStart).toLocaleString()}${appointmentEnd ? ` to ${new Date(appointmentEnd).toLocaleString()}` : ''}`
                : '';
            return {
                id: job?.id || '',
                name: customer?.name || normalized.fullName || normalized.name || job?.name || 'Unidentified lead',
                phone: customer?.phone || normalized.phone || '',
                email: customer?.email || normalized.email || '',
                address: this.leadAddress(
                    job?.property_address || customer?.address || normalized.address,
                    job?.city || customer?.city || normalized.city,
                    job?.state || customer?.state || normalized.state,
                    job?.postal_code || customer?.postal_code || normalized.postalCode
                ),
                issue: job?.issue_description || normalized.issueDescription || '',
                appointment,
                estimator: normalized.assignedEstimator || '',
                source: job?.lead_source || intake?.source || normalized.leadSource || 'RoomFlow',
                status: job?.status || 'New Lead',
                estimateStatus: job?.estimate_status || 'not started',
                sender: intake?.source_sender || normalized.sourceSender || '',
                subject: intake?.source_subject || normalized.sourceSubject || '',
                messageId: intake?.source_message_id || normalized.sourceMessageId || '',
                externalKey: normalized.externalKey || '',
                receivedAt: intake?.received_at ? new Date(intake.received_at).toLocaleString() : '',
                importStatus: intake?.import_status || '',
                warnings: Array.isArray(normalized.warnings) ? normalized.warnings : [],
                updatedAt: job?.updated_at ? new Date(job.updated_at).toLocaleString() : ''
            };
        },

        renderLeadCard(job, intake = null) {
            const lead = this.leadViewModel(job, intake);
            const field = (label, value, wide = false) => `<div class="roomflow-lead-field${wide ? ' roomflow-lead-field-wide' : ''}"><span>${this.escape(label)}</span><strong class="${value ? '' : 'roomflow-lead-missing'}">${this.escape(value || 'Not provided')}</strong></div>`;
            return `<article class="roomflow-lead-card" data-lead-card="${this.escape(lead.id)}">
                <div class="roomflow-lead-card-header">
                    <div><span class="roomflow-lead-kicker">Lead</span><h4>${this.escape(lead.name)}</h4></div>
                    <div class="roomflow-lead-badges"><span>${this.escape(lead.status)}</span><span>${this.escape(lead.source)}</span></div>
                </div>
                <div class="roomflow-lead-field-grid">
                    ${field('Name', lead.name)}
                    ${field('Phone', lead.phone)}
                    ${field('Email', lead.email)}
                    ${field('Service address', lead.address, true)}
                    ${field('Appointment', lead.appointment)}
                    ${field('Assigned estimator', lead.estimator)}
                    ${field('Lead source', lead.source)}
                    ${field('Estimate status', lead.estimateStatus)}
                    ${field('Source sender', lead.sender)}
                    ${field('Source subject', lead.subject, true)}
                    ${field('Source record / message ID', lead.messageId, true)}
                    ${lead.externalKey ? field('External lead ID', lead.externalKey) : ''}
                    ${field('Received', lead.receivedAt || lead.updatedAt)}
                    ${field('Issue / request', lead.issue, true)}
                </div>
                ${lead.warnings.length ? `<div class="roomflow-lead-warning"><strong>Intake notes:</strong> ${this.escape(lead.warnings.join(' '))}</div>` : ''}
                <div class="roomflow-lead-card-actions">
                    <span>${this.escape(lead.importStatus ? `Intake ${lead.importStatus}` : 'RoomFlow lead')}</span>
                    <div class="roomflow-lead-action-buttons">
                        <button class="btn-secondary roomflow-remove-lead" data-job-id="${this.escape(lead.id)}" data-lead-name="${this.escape(lead.name)}">Remove Lead</button>
                        <button class="btn-primary roomflow-open-lead" data-job-id="${this.escape(lead.id)}">Open in RoomFlow</button>
                    </div>
                </div>
            </article>`;
        },

        async refreshInboundLeads() {
            this.injectLeadPanel();
            const list = document.getElementById('roomflow-inbound-leads-list');
            const client = this.getClient();
            const orgId = this.currentOrgId();
            if (!list || !client || !orgId) return;
            list.innerHTML = '<div style="color:#94a3b8;">Loading leads…</div>';

            const [jobResult, importResult] = await Promise.all([
                client.from('jobs')
                    .select('id,name,status,property_address,city,state,postal_code,issue_description,appointment_start,lead_source,tracking_color,estimate_status,updated_at,customers(id,name,first_name,last_name,email,phone,address,city,state,postal_code)')
                    .eq('organization_id', orgId)
                    .in('status', ['New Lead', 'Contacted', 'Inspection Scheduled', 'Layout In Progress', 'Estimate Draft'])
                    .order('updated_at', { ascending: false })
                    .limit(50),
                client.from('lead_imports')
                    .select('job_id,source,source_message_id,source_sender,source_subject,normalized_payload,import_status,import_error,received_at')
                    .eq('organization_id', orgId)
                    .order('received_at', { ascending: false })
                    .limit(100)
            ]);

            if (jobResult.error) {
                list.innerHTML = `<div style="color:#fca5a5;">${this.escape(jobResult.error.message)}</div>`;
                return;
            }
            const jobs = jobResult.data || [];
            if (!jobs.length) {
                list.innerHTML = '<div style="color:#64748b;">No leads yet.</div>';
                return;
            }
            const importsByJob = new Map();
            if (!importResult.error) {
                (importResult.data || []).forEach(item => {
                    if (item.job_id && !importsByJob.has(item.job_id)) importsByJob.set(item.job_id, item);
                });
            }
            list.innerHTML = jobs.map(job => this.renderLeadCard(job, importsByJob.get(job.id))).join('');

            list.querySelectorAll('.roomflow-open-lead').forEach(button => {
                button.addEventListener('click', () => this.openInboundLead(button.dataset.jobId));
            });
            list.querySelectorAll('.roomflow-remove-lead').forEach(button => {
                button.addEventListener('click', () => this.removeInboundLead(button.dataset.jobId, button.dataset.leadName, button));
            });
        },

        async removeInboundLead(jobId, leadName = 'this lead', button = null) {
            const client = this.getClient();
            const orgId = this.currentOrgId();
            if (!client || !orgId || !jobId) return;
            const confirmation = window.prompt(
                `Remove "${leadName}" from Leads?\n\nThis permanently deletes the shared lead job and its job-linked layouts, estimates, work orders, and timeline. The intake record remains for audit.\n\nType REMOVE to confirm.`,
                ''
            );
            if (confirmation === null) return;
            if (String(confirmation).trim().toUpperCase() !== 'REMOVE') {
                this.toast('Lead was not removed. Type REMOVE to confirm.', 'warning');
                return;
            }

            const originalText = button?.textContent || 'Remove Lead';
            if (button) {
                button.disabled = true;
                button.textContent = 'Removing…';
            }
            try {
                const deploymentResult = await client
                    .from('equipment_deployments')
                    .select('id', { count: 'exact', head: true })
                    .eq('organization_id', orgId)
                    .eq('job_id', jobId)
                    .eq('status', 'active');
                if (deploymentResult.error) throw new Error(`Could not verify equipment: ${deploymentResult.error.message}`);
                if (deploymentResult.count) {
                    this.toast('Pick up active equipment before removing this lead.', 'error');
                    return;
                }

                const result = await client
                    .from('jobs')
                    .delete()
                    .eq('organization_id', orgId)
                    .eq('id', jobId)
                    .select('id')
                    .maybeSingle();
                if (result.error) {
                    const permissionDenied = /permission|policy|row-level|rls/i.test(result.error.message || '');
                    throw new Error(permissionDenied
                        ? 'Your role needs the delete_jobs permission before it can remove leads.'
                        : result.error.message);
                }
                if (!result.data) throw new Error('The lead was not removed. Your role may need the delete_jobs permission.');

                this.removeDeletedCloudJobMapping(jobId);
                const card = Array.from(document.querySelectorAll('[data-lead-card]')).find(item => item.dataset.leadCard === jobId);
                if (card) card.remove();
                const auditResult = await client.from('audit_logs').insert({
                    organization_id: orgId,
                    user_id: state.sessionUser?.id || null,
                    action: 'lead.removed_from_roomflow',
                    details: { job_id: jobId, lead_name: leadName, removed_at: new Date().toISOString() }
                });
                if (auditResult.error) console.warn('Lead removal audit failed', auditResult.error);
                this.toast('Lead permanently removed.', 'success');
                await this.refreshInboundLeads();
            } catch (error) {
                this.toast(error.message || String(error), 'error');
            } finally {
                if (button?.isConnected) {
                    button.disabled = false;
                    button.textContent = originalText;
                }
            }
        },

        async openInboundLead(jobId) {
            const client = this.getClient();
            if (!client || !jobId) return;
            const orgId = this.currentOrgId();
            const [jobResult, importResult] = await Promise.all([
                client.from('jobs').select('*,customers(*)').eq('organization_id', orgId).eq('id', jobId).single(),
                client.from('lead_imports').select('source,source_message_id,source_sender,source_subject,normalized_payload,import_status,received_at').eq('organization_id', orgId).eq('job_id', jobId).order('received_at', { ascending: false }).limit(1).maybeSingle()
            ]);
            if (jobResult.error) return this.toast(jobResult.error.message, 'error');
            const job = jobResult.data;
            const intake = importResult.error ? null : importResult.data;
            const normalized = intake?.normalized_payload || {};
            const customer = Array.isArray(job.customers) ? job.customers[0] : job.customers;
            const fullAddress = this.leadAddress(
                job.property_address || customer?.address || normalized.address,
                job.city || customer?.city || normalized.city,
                job.state || customer?.state || normalized.state,
                job.postal_code || customer?.postal_code || normalized.postalCode
            );
            let jobName = job.name || `${customer?.name || 'Customer'} Estimate`;
            const stored = JSON.parse(localStorage.getItem('roomflow_jobs') || '{}');
            if (stored[jobName] && stored[jobName].jobId !== jobId) jobName += ` ${jobId.slice(0, 6)}`;

            const initial = typeof getInitialProjectState === 'function'
                ? getInitialProjectState(
                    jobName,
                    customer?.name || normalized.fullName || jobName,
                    fullAddress,
                    customer?.phone || normalized.phone || '',
                    customer?.email || normalized.email || '',
                    normalized.assignedEstimator || '',
                    job.appointment_start ? job.appointment_start.slice(0, 10) : '',
                    'basement',
                    job.issue_description || normalized.issueDescription || customer?.notes || '',
                    job.organization_id,
                    job.id
                )
                : { rooms: [], costing: {} };
            initial.jobId = job.id;
            initial.currentJobName = jobName;
            initial.leadIntake = {
                source: job.lead_source || intake?.source || normalized.leadSource || 'RoomFlow',
                sender: intake?.source_sender || normalized.sourceSender || '',
                subject: intake?.source_subject || normalized.sourceSubject || '',
                sourceMessageId: intake?.source_message_id || normalized.sourceMessageId || '',
                externalKey: normalized.externalKey || '',
                receivedAt: intake?.received_at || '',
                appointmentEnd: normalized.appointmentEnd || '',
                city: job.city || customer?.city || normalized.city || '',
                state: job.state || customer?.state || normalized.state || '',
                postalCode: job.postal_code || customer?.postal_code || normalized.postalCode || ''
            };
            state.currentJobName = jobName;
            this.setJobMapping(jobName, job.id);
            window.loadJobData(initial);
            window.autosaveJob();
            await client.from('jobs').update({ status: 'Layout In Progress', tracking_color: 'blue' }).eq('id', job.id);
            await client.from('job_status_events').insert({
                organization_id: job.organization_id,
                job_id: job.id,
                event_type: 'roomflow.opened',
                old_status: job.status,
                new_status: 'Layout In Progress',
                note: 'Lead opened in RoomFlow layout workflow',
                actor_user_id: state.sessionUser?.id || null
            });
            if (typeof switchTab === 'function') switchTab('project');
            this.toast('Lead loaded into RoomFlow.', 'success');
            this.refreshInboundLeads();
        },

        injectSettingsCards() {
            const host = document.getElementById('more-viewport');
            if (!host) return;
            if (!document.getElementById('roomflow-email-integration-card')) {
                const card = document.createElement('section');
                card.id = 'roomflow-email-integration-card';
                card.className = 'checklist-room-card roomflow-more-card';
                card.style.padding = '1.25rem';
                card.innerHTML = `
                    <h3 style="color:#fff;margin:0 0 .35rem;">Lead Intake / Zapier</h3>
                    <p style="color:#94a3b8;font-size:.8rem;">Create a secure endpoint for Zapier. It accepts mapped lead fields, nested Zapier data, or a raw Gmail/Email Parser body. The secret is displayed once and only its SHA-256 hash is stored.</p>
                    <div style="display:flex;gap:.5rem;flex-wrap:wrap;"><input id="roomflow-endpoint-name" value="Lead Intake" style="flex:1;min-width:220px;background:#1f2937;border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:.55rem;color:#fff;"><button id="roomflow-create-endpoint" class="btn-primary">Create Endpoint</button><button id="roomflow-refresh-endpoints" class="btn-secondary">Refresh Activity</button></div>
                    <pre id="roomflow-endpoint-output" style="display:none;white-space:pre-wrap;margin-top:.8rem;padding:.8rem;border-radius:8px;background:#020617;color:#cbd5e1;font-size:.72rem;overflow:auto;"></pre>
                    <div id="roomflow-endpoint-diagnostics" style="display:grid;gap:.65rem;margin-top:.8rem;"><div style="color:#64748b;font-size:.78rem;">Sign in and select a company to view webhook activity.</div></div>`;
                card.querySelector('#roomflow-endpoint-name')?.parentElement?.classList.add('roomflow-more-toolbar');
                host.appendChild(card);
                card.querySelector('#roomflow-create-endpoint')?.addEventListener('click', () => this.createIntegrationEndpoint());
                card.querySelector('#roomflow-refresh-endpoints')?.addEventListener('click', () => this.refreshIntegrationDiagnostics());
            }
            if (!document.getElementById('roomflow-catalog-import-card')) {
                const card = document.createElement('section');
                card.id = 'roomflow-catalog-import-card';
                card.className = 'checklist-room-card roomflow-more-card';
                card.style.padding = '1.25rem';
                card.innerHTML = `
                    <div style="display:flex;justify-content:space-between;gap:1rem;align-items:center;"><div><h3 style="color:#fff;margin:0;">Estimate Product Catalog</h3><p style="color:#94a3b8;font-size:.8rem;margin:.25rem 0;">Import the copied product list, then edit prices, units, tax settings, and descriptions.</p></div><button id="roomflow-import-seed" class="btn-primary">Import 229 Products</button></div>
                    <div style="display:flex;gap:.5rem;margin:.7rem 0;"><input id="roomflow-catalog-search" placeholder="Search products…" style="flex:1;background:#1f2937;border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:.55rem;color:#fff;"><button id="roomflow-refresh-catalog" class="btn-secondary">Refresh</button></div>
                    <div id="roomflow-catalog-summary" style="font-size:.75rem;color:#94a3b8;margin-bottom:.5rem;"></div>
                    <div id="roomflow-catalog-list" style="max-height:420px;overflow:auto;display:grid;gap:.45rem;"></div>`;
                card.querySelector('#roomflow-import-seed')?.parentElement?.classList.add('roomflow-catalog-heading');
                card.querySelector('#roomflow-catalog-search')?.parentElement?.classList.add('roomflow-more-toolbar');
                host.appendChild(card);
                card.querySelector('#roomflow-import-seed')?.addEventListener('click', () => this.importSeedCatalog());
                card.querySelector('#roomflow-refresh-catalog')?.addEventListener('click', () => this.loadCatalog(true));
                card.querySelector('#roomflow-catalog-search')?.addEventListener('input', () => this.renderCatalogManager());
            }
        },

        async createIntegrationEndpoint() {
            const client = this.getClient();
            const orgId = this.currentOrgId();
            if (!client || !orgId) return this.toast('Sign in and select a company first.', 'warning');
            const secret = this.randomToken(24);
            const endpointKey = `${this.slug(state.currentOrganization.name)}-${this.randomToken(6)}`;
            const secretHash = await this.sha256(secret);
            const name = document.getElementById('roomflow-endpoint-name')?.value?.trim() || 'Lead Intake';
            const { error } = await client.from('integration_endpoints').insert({
                organization_id: orgId,
                endpoint_key: endpointKey,
                secret_hash: secretHash,
                source_type: 'zapier_email',
                name,
                created_by: state.sessionUser?.id || null
            });
            if (error) return this.toast(error.message, 'error');
            const base = window.RoomFlowConfig?.supabaseUrl;
            const output = document.getElementById('roomflow-endpoint-output');
            if (output) {
                output.style.display = 'block';
                output.textContent = `POST URL\n${base}/functions/v1/intake-lead?endpoint=${endpointKey}\n\nHEADERS\nx-roomflow-webhook-secret: ${secret}\nContent-Type: application/json\n\nRECOMMENDED ZAPIER JSON\n{\n  "source_message_id": "{{Gmail Message ID}}",\n  "source_sender": "{{From Email}}",\n  "source_subject": "{{Subject}}",\n  "body_plain": "{{Body Plain}}"\n}\n\nOPTIONAL PRE-MAPPED CALLER FIELDS\ncustomer_name, email, phone, address, city, state, postal_code, issue_description, appointment_start\n\nRoomFlow extracts labeled caller information from plain-text or HTML email bodies. Always map Gmail's stable Message ID so Zapier retries update the same job. A successful test returns ok: true, job_id, normalized fields, and any warnings. Save this secret now; RoomFlow cannot display it again.`;
            }
            this.toast('Secure Zapier endpoint created.', 'success');
            await this.refreshIntegrationDiagnostics();
        },

        async refreshIntegrationDiagnostics() {
            const host = document.getElementById('roomflow-endpoint-diagnostics');
            const client = this.getClient();
            const orgId = this.currentOrgId();
            if (!host || !client || !orgId) return;
            host.innerHTML = '<div style="color:#94a3b8;font-size:.78rem;">Loading endpoint activity…</div>';
            const [endpointResult, importResult] = await Promise.all([
                client.from('integration_endpoints').select('id,name,endpoint_key,source_type,enabled,created_at,updated_at').eq('organization_id', orgId).order('created_at', { ascending: false }),
                client.from('lead_imports').select('id,endpoint_id,job_id,source,source_message_id,source_sender,source_subject,normalized_payload,import_status,import_error,received_at').eq('organization_id', orgId).order('received_at', { ascending: false }).limit(8)
            ]);
            if (endpointResult.error) {
                host.innerHTML = `<div style="color:#fca5a5;font-size:.78rem;">${this.escape(endpointResult.error.message)}</div>`;
                return;
            }
            if (importResult.error) {
                host.innerHTML = `<div style="color:#fca5a5;font-size:.78rem;">Endpoints loaded, but delivery history could not be read: ${this.escape(importResult.error.message)}</div>`;
                return;
            }
            const endpoints = endpointResult.data || [];
            const imports = importResult.data || [];
            const endpointRows = endpoints.length ? endpoints.map(endpoint => {
                const latest = imports.find(item => item.endpoint_id === endpoint.id);
                return `<div style="display:grid;grid-template-columns:minmax(150px,1fr) auto;gap:.7rem;padding:.7rem;border:1px solid rgba(255,255,255,.08);border-radius:9px;background:rgba(2,6,23,.3);"><div><strong style="color:#fff;">${this.escape(endpoint.name)}</strong><div style="font-size:.7rem;color:#64748b;word-break:break-all;">${this.escape(endpoint.endpoint_key)}</div></div><div style="text-align:right;font-size:.72rem;color:${endpoint.enabled ? '#86efac' : '#fca5a5'};">${endpoint.enabled ? 'Enabled' : 'Disabled'}<div style="color:#94a3b8;">${latest ? `Last delivery ${this.escape(new Date(latest.received_at).toLocaleString())}` : 'No deliveries recorded'}</div></div></div>`;
            }).join('') : '<div style="color:#64748b;font-size:.78rem;">No webhook endpoints have been created for this company.</div>';
            const importRows = imports.length ? imports.map(item => {
                const normalized = item.normalized_payload || {};
                const identity = normalized.fullName || normalized.name || item.source_subject || 'Unidentified caller';
                const details = [normalized.phone, normalized.email, normalized.address].filter(Boolean).join(' · ');
                return `<div style="padding:.65rem;border-left:3px solid ${item.import_error ? '#ef4444' : '#10b981'};background:rgba(15,23,42,.35);border-radius:0 8px 8px 0;"><div style="display:flex;justify-content:space-between;gap:.7rem;"><strong style="color:#e2e8f0;font-size:.78rem;">${this.escape(identity)}</strong><span style="color:#94a3b8;font-size:.68rem;">${this.escape(item.import_status)} · ${this.escape(new Date(item.received_at).toLocaleString())}</span></div><div style="color:#64748b;font-size:.7rem;margin-top:.2rem;">${this.escape(details || item.source_sender || 'No contact fields parsed')}</div>${item.import_error ? `<div style="color:#fca5a5;font-size:.7rem;">${this.escape(item.import_error)}</div>` : ''}</div>`;
            }).join('') : '<div style="color:#64748b;font-size:.76rem;">No Zapier deliveries have reached RoomFlow yet.</div>';
            host.innerHTML = `<div><div style="color:#94a3b8;font-size:.7rem;font-weight:800;text-transform:uppercase;margin-bottom:.4rem;">Endpoints</div>${endpointRows}</div><div><div style="color:#94a3b8;font-size:.7rem;font-weight:800;text-transform:uppercase;margin-bottom:.4rem;">Recent deliveries</div><div style="display:grid;gap:.4rem;">${importRows}</div></div>`;
        },

        async importSeedCatalog() {
            const client = this.getClient();
            const orgId = this.currentOrgId();
            if (!client || !orgId) return this.toast('Sign in and select a company first.', 'warning');
            let source;
            try {
                const result = await fetch('catalog/floodman-products.json?v=1', { cache: 'no-store' });
                if (!result.ok) throw new Error(`Catalog file returned ${result.status}`);
                source = await result.json();
            } catch (error) {
                return this.toast(`Could not load catalog seed: ${error.message}`, 'error');
            }
            const rows = source.map(item => ({
                organization_id: orgId,
                external_key: item.external_key,
                name: item.name,
                description: item.description || null,
                category: item.category || 'general-services',
                pricing_method: item.pricing_method || 'fixed',
                unit: item.unit || 'each',
                unit_price: Number(item.unit_price) || 0,
                internal_cost: item.internal_cost,
                taxable: Boolean(item.taxable),
                active: item.active !== false,
                source: item.source || 'catalog-import',
                review_required: Boolean(item.review_required),
                review_notes: item.review_notes || null,
                created_by: state.sessionUser?.id || null
            }));
            for (let i = 0; i < rows.length; i += 75) {
                const { error } = await client.from('estimate_catalog_items').upsert(rows.slice(i, i + 75), { onConflict: 'organization_id,external_key' });
                if (error) return this.toast(`Catalog import failed: ${error.message}`, 'error');
            }
            this.toast(`${rows.length} products imported. Review zero-price and duplicate entries.`, 'success');
            await this.loadCatalog(true);
        },

        async loadCatalog(force = false) {
            const client = this.getClient();
            const orgId = this.currentOrgId();
            if (!client || !orgId) return [];
            if (this.catalogCache.length && !force) return this.catalogCache;
            const { data, error } = await client
                .from('estimate_catalog_items')
                .select('*')
                .eq('organization_id', orgId)
                .order('category')
                .order('name');
            if (error) {
                this.toast(error.message, 'error');
                return [];
            }
            this.catalogCache = data || [];
            this.renderCatalogManager();
            this.renderEstimateBuilder();
            return this.catalogCache;
        },

        renderCatalogManager() {
            const list = document.getElementById('roomflow-catalog-list');
            const summary = document.getElementById('roomflow-catalog-summary');
            if (!list) return;
            const query = (document.getElementById('roomflow-catalog-search')?.value || '').toLowerCase();
            const items = this.catalogCache.filter(item => !query || `${item.name} ${item.category} ${item.description || ''}`.toLowerCase().includes(query));
            if (summary) summary.textContent = `${this.catalogCache.length} products · ${this.catalogCache.filter(i => i.review_required).length} require review · ${this.catalogCache.filter(i => Number(i.unit_price) === 0).length} have a $0.00 price`;
            list.innerHTML = items.slice(0, 250).map(item => `<div class="roomflow-catalog-row" style="display:grid;grid-template-columns:minmax(180px,1fr) 120px 105px 85px;gap:.5rem;align-items:center;padding:.55rem;border:1px solid rgba(255,255,255,.07);border-radius:8px;background:rgba(15,23,42,.3);">
                <div class="roomflow-catalog-name"><strong style="color:#fff;font-size:.8rem;">${this.escape(item.name)}</strong><div style="font-size:.68rem;color:${item.review_required ? '#fbbf24' : '#64748b'};">${this.escape(item.category)}${item.review_required ? ' · Review required' : ''}</div></div>
                <select data-catalog-field="pricing_method" data-id="${item.id}" style="background:#1f2937;color:#fff;border:1px solid rgba(255,255,255,.1);border-radius:6px;padding:.4rem;font-size:.72rem;">
                    ${['fixed','per_square_foot','per_linear_foot','per_hour','per_day','manual','discount','deposit'].map(value => `<option ${item.pricing_method === value ? 'selected' : ''}>${value}</option>`).join('')}
                </select>
                <input data-catalog-field="unit_price" data-id="${item.id}" type="number" step="0.01" value="${Number(item.unit_price || 0).toFixed(2)}" style="background:#1f2937;color:#fff;border:1px solid rgba(255,255,255,.1);border-radius:6px;padding:.4rem;">
                <button class="btn-secondary roomflow-save-catalog-item" data-id="${item.id}" style="font-size:.7rem;">Save</button>
            </div>`).join('') || '<div style="color:#64748b;">No catalog items found.</div>';
            list.querySelectorAll('.roomflow-save-catalog-item').forEach(button => button.addEventListener('click', () => this.saveCatalogItem(button.dataset.id)));
        },

        async saveCatalogItem(id) {
            const row = document.querySelector(`[data-catalog-field="unit_price"][data-id="${id}"]`);
            const method = document.querySelector(`[data-catalog-field="pricing_method"][data-id="${id}"]`);
            const client = this.getClient();
            const { error } = await client.from('estimate_catalog_items').update({
                unit_price: Number(row?.value) || 0,
                pricing_method: method?.value || 'fixed',
                review_required: false,
                review_notes: null
            }).eq('id', id);
            if (error) return this.toast(error.message, 'error');
            this.toast('Catalog price updated.', 'success');
            await this.loadCatalog(true);
        },

        lineId() {
            return globalThis.crypto?.randomUUID?.() || `rf-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        },

        ensureMainEstimateState() {
            if (typeof initDefaultCosting === 'function') initDefaultCosting(state);
            if (!state.costing) state.costing = {};
            if (!Array.isArray(state.costing.customItems)) state.costing.customItems = [];
            return state.costing.customItems;
        },

        syncLineToMainEstimate(line) {
            const items = this.ensureMainEstimateState();
            if (!line.roomflow_line_id) line.roomflow_line_id = this.lineId();
            const catalogItem = this.catalogCache.find(item => item.id === line.catalog_item_id);
            const allowed = new Set(['material','equipment','supply','rental','subcontractor','permit','disposal','delivery','travel','other']);
            const requestedCategory = String(line.category || catalogItem?.category || 'other').toLowerCase();
            const category = allowed.has(requestedCategory) ? requestedCategory : 'other';
            const mapped = {
                roomflowImported: true,
                roomflowLineId: line.roomflow_line_id,
                catalogItemId: line.catalog_item_id,
                name: line.name,
                category,
                qty: Number(line.quantity) || 0,
                unit: line.unit || 'each',
                unitCost: Number(line.unit_price) || 0,
                waste: 0,
                laborHours: 0,
                laborRate: 0,
                taxable: Boolean(line.taxable),
                includeInOverhead: true,
                includeInMarkup: true
            };
            const index = items.findIndex(item => item.roomflowLineId === line.roomflow_line_id);
            if (index >= 0) items[index] = { ...items[index], ...mapped };
            else items.push(mapped);
        },

        syncAllLinesToMainEstimate() {
            const items = this.ensureMainEstimateState();
            this.currentLines.forEach(line => this.syncLineToMainEstimate(line));
            const activeIds = new Set(this.currentLines.map(line => line.roomflow_line_id));
            state.costing.customItems = items.filter(item => !item.roomflowImported || activeIds.has(item.roomflowLineId));
            this.saveEstimateStorage();
        },

        refreshMainEstimate() {
            if (typeof window.autosaveJob === 'function') window.autosaveJob();
            if (typeof window.renderCostUI === 'function') window.renderCostUI();
            if (typeof window.renderGuidedStep === 'function') window.renderGuidedStep();
        },

        estimateStorage() {
            const all = JSON.parse(localStorage.getItem(this.estimateDraftKey) || '{}');
            return { all, current: all[state.currentJobName] || { lines: [], estimateId: null, header: '', serviceStreet: '', serviceCity: '', serviceState: '', servicePostalCode: '' } };
        },

        saveEstimateStorage() {
            if (!state.currentJobName) return;
            const { all } = this.estimateStorage();
            all[state.currentJobName] = {
                lines: this.currentLines,
                estimateId: this.currentEstimateId,
                header: this.currentEstimateHeader,
                serviceStreet: this.currentServiceStreet,
                serviceCity: this.currentServiceCity,
                serviceState: this.currentServiceState,
                servicePostalCode: this.currentServicePostalCode
            };
            localStorage.setItem(this.estimateDraftKey, JSON.stringify(all));
        },

        restoreEstimateDraftState() {
            if (!state?.currentJobName) return;
            const saved = this.estimateStorage().current;
            const storedLines = Array.isArray(saved.lines) ? saved.lines : [];
            const jobChanged = this.currentEstimateJobName !== state.currentJobName;
            const parsed = this.parseServiceAddress(state.costing?.customerAddress || state.customerAddress || '');
            const savedHeader = String(saved.header || storedLines.find(line => line.section_name)?.section_name || '').slice(0, 240);
            const savedStreet = String(saved.serviceStreet || state.costing?.serviceStreet || parsed.street || '').slice(0, 300);
            const savedCity = String(saved.serviceCity || state.costing?.serviceCity || parsed.city || '').slice(0, 120);
            const savedState = String(saved.serviceState || state.costing?.serviceState || parsed.state || '').slice(0, 80);
            const savedPostalCode = String(saved.servicePostalCode || state.costing?.servicePostalCode || parsed.postalCode || '').slice(0, 32);
            if (jobChanged || (!this.currentLines.length && storedLines.length)) {
                this.currentEstimateJobName = state.currentJobName;
                this.currentLines = JSON.parse(JSON.stringify(storedLines));
                this.currentEstimateId = saved.estimateId || null;
            }
            if (jobChanged) {
                this.currentEstimateHeader = savedHeader;
                this.currentServiceStreet = savedStreet;
                this.currentServiceCity = savedCity;
                this.currentServiceState = savedState;
                this.currentServicePostalCode = savedPostalCode;
                return;
            }
            if (!String(this.currentEstimateHeader || '').trim()) this.currentEstimateHeader = savedHeader;
            if (!this.currentServiceStreet) this.currentServiceStreet = savedStreet;
            if (!this.currentServiceCity) this.currentServiceCity = savedCity;
            if (!this.currentServiceState) this.currentServiceState = savedState;
            if (!this.currentServicePostalCode) this.currentServicePostalCode = savedPostalCode;
        },

        renderEstimateBuilder(forceCost = false) {
            if (!state?.currentJobName) return;
            const target = forceCost
                ? document.getElementById('cost-container')
                : document.getElementById('guided-step-content-container');
            if (!target) return;
            if (!forceCost && Number(state.currentStep || 0) < 6) return;
            let panel = target.querySelector('#roomflow-inline-estimate-builder');
            if (!panel) {
                panel = document.createElement('section');
                panel.id = 'roomflow-inline-estimate-builder';
                panel.className = 'checklist-room-card';
                panel.style.cssText = 'padding:1.25rem;margin-top:1rem;';
                target.appendChild(panel);
            }
            const saved = this.estimateStorage().current;
            if (this.currentEstimateJobName !== state.currentJobName) {
                this.currentEstimateJobName = state.currentJobName;
                this.currentLines = Array.isArray(saved.lines) ? JSON.parse(JSON.stringify(saved.lines)) : [];
                this.currentEstimateId = saved.estimateId || null;
                this.currentEstimateHeader = String(saved.header || this.currentLines.find(line => line.section_name)?.section_name || `${state.currentJobName} Estimate`).slice(0, 240);
                const parsedAddress = this.parseServiceAddress(state.costing?.customerAddress || state.customerAddress || '');
                this.currentServiceStreet = String(saved.serviceStreet || state.costing?.serviceStreet || parsedAddress.street || '').slice(0, 300);
                this.currentServiceCity = String(saved.serviceCity || state.costing?.serviceCity || parsedAddress.city || '').slice(0, 120);
                this.currentServiceState = String(saved.serviceState || state.costing?.serviceState || parsedAddress.state || '').slice(0, 80);
                this.currentServicePostalCode = String(saved.servicePostalCode || state.costing?.servicePostalCode || parsedAddress.postalCode || '').slice(0, 32);
                this.syncAllLinesToMainEstimate();
                if (this.mainEstimateSyncJob !== state.currentJobName) {
                    this.mainEstimateSyncJob = state.currentJobName;
                    setTimeout(() => this.refreshMainEstimate(), 0);
                }
            }
            const catalogOptions = this.catalogCache.filter(item => item.active).slice(0, 500).map(item => `<option value="${item.id}">${this.escape(item.name)} · ${this.money(item.unit_price)}</option>`).join('');
            const total = this.currentLines.filter(line => line.selected !== false).reduce((sum, line) => sum + (Number(line.quantity) || 0) * (Number(line.unit_price) || 0), 0);
            panel.innerHTML = `
                <div style="display:flex;justify-content:space-between;gap:1rem;align-items:center;"><div><h3 style="color:#fff;margin:0;">Inline Customer Estimate</h3><p style="color:#94a3b8;font-size:.78rem;margin:.25rem 0;">Build the draft here. Prices remain editable per estimate without changing the catalog.</p></div><strong style="font-size:1.25rem;color:#34d399;">${this.money(total)}</strong></div>
                <label class="roomflow-estimate-header-field"><span>Estimate Header</span><input id="roomflow-estimate-header" type="text" maxlength="240" value="${this.escape(this.currentEstimateHeader)}" placeholder="Example: Basement Waterproofing"><small>This becomes the header in the Townsquare draft.</small></label>
                <div class="roomflow-service-address-grid"><label class="roomflow-service-address-street"><span>Service Street Address</span><input data-service-field="street" maxlength="300" value="${this.escape(this.currentServiceStreet)}" placeholder="123 Main Street"></label><label><span>Service City</span><input data-service-field="city" maxlength="120" value="${this.escape(this.currentServiceCity)}" placeholder="Grand Rapids"></label><label><span>Service State</span><input data-service-field="state" maxlength="80" value="${this.escape(this.currentServiceState)}" placeholder="MI"></label><label><span>Postal Code</span><input data-service-field="postalCode" maxlength="32" value="${this.escape(this.currentServicePostalCode)}" placeholder="49503"></label></div>
                <div style="display:flex;gap:.5rem;margin:.8rem 0;flex-wrap:wrap;"><select id="roomflow-add-catalog-select" style="flex:1;min-width:260px;background:#1f2937;color:#fff;border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:.55rem;"><option value="">Select a product or service…</option>${catalogOptions}</select><button id="roomflow-add-estimate-line" class="btn-secondary">Add Item</button><button id="roomflow-save-estimate" class="btn-primary">Save Draft</button><button id="roomflow-mark-estimate-sent" class="btn-primary" style="background:#059669;">Mark Sent + Follow-ups</button></div>
                <div style="overflow:auto;"><table style="width:100%;border-collapse:collapse;font-size:.78rem;"><thead><tr style="color:#94a3b8;text-align:left;"><th>Item</th><th style="width:90px;">Qty</th><th style="width:120px;">Price</th><th style="width:110px;">Total</th><th style="width:65px;"></th></tr></thead><tbody>${this.currentLines.map((line, index) => `<tr style="border-top:1px solid rgba(255,255,255,.07);"><td style="padding:.55rem 0;color:#fff;"><strong>${this.escape(line.name)}</strong><div style="font-size:.68rem;color:#64748b;">${this.escape(line.unit || 'each')}</div></td><td><input class="roomflow-line-qty" data-index="${index}" type="number" step="0.01" value="${Number(line.quantity || 1)}" style="width:78px;background:#1f2937;color:#fff;border:1px solid rgba(255,255,255,.1);border-radius:6px;padding:.35rem;"></td><td><input class="roomflow-line-price" data-index="${index}" type="number" step="0.01" value="${Number(line.unit_price || 0).toFixed(2)}" style="width:105px;background:#1f2937;color:#fff;border:1px solid rgba(255,255,255,.1);border-radius:6px;padding:.35rem;"></td><td style="color:#cbd5e1;">${this.money((Number(line.quantity)||0)*(Number(line.unit_price)||0))}</td><td><button class="roomflow-remove-line btn-secondary" data-index="${index}">×</button></td></tr>`).join('') || '<tr><td colspan="5" style="padding:1rem;color:#64748b;text-align:center;">No estimate items added yet.</td></tr>'}</tbody></table></div>`;
            panel.querySelector('#roomflow-add-estimate-line')?.addEventListener('click', () => this.addEstimateLine());
            panel.querySelector('#roomflow-save-estimate')?.addEventListener('click', () => this.saveDraftEstimate());
            panel.querySelector('#roomflow-mark-estimate-sent')?.addEventListener('click', () => this.markEstimateSent());
            panel.querySelector('#roomflow-estimate-header')?.addEventListener('input', event => {
                this.currentEstimateHeader = String(event.target.value || '').slice(0, 240);
                this.currentLines.forEach(line => { line.section_name = this.currentEstimateHeader || null; });
                this.saveEstimateStorage();
            });
            panel.querySelectorAll('[data-service-field]').forEach(input => input.addEventListener('input', event => {
                const values = { street: 'currentServiceStreet', city: 'currentServiceCity', state: 'currentServiceState', postalCode: 'currentServicePostalCode' };
                const property = values[event.target.dataset.serviceField];
                if (property) this[property] = String(event.target.value || '').trimStart();
                if (state.costing) {
                    state.costing.serviceStreet = this.currentServiceStreet;
                    state.costing.serviceCity = this.currentServiceCity;
                    state.costing.serviceState = this.currentServiceState;
                    state.costing.servicePostalCode = this.currentServicePostalCode;
                    state.costing.customerAddress = this.serviceAddress();
                }
                this.saveEstimateStorage();
            }));
            panel.querySelectorAll('.roomflow-line-qty,.roomflow-line-price').forEach(input => input.addEventListener('change', () => {
                const index = Number(input.dataset.index);
                if (input.classList.contains('roomflow-line-qty')) this.currentLines[index].quantity = Number(input.value) || 0;
                else this.currentLines[index].unit_price = Number(input.value) || 0;
                this.syncLineToMainEstimate(this.currentLines[index]);
                this.saveEstimateStorage();
                this.refreshMainEstimate();
                this.renderEstimateBuilder(forceCost);
            }));
            panel.querySelectorAll('.roomflow-remove-line').forEach(button => button.addEventListener('click', () => {
                const [removed] = this.currentLines.splice(Number(button.dataset.index), 1);
                if (removed?.roomflow_line_id) {
                    const items = this.ensureMainEstimateState();
                    state.costing.customItems = items.filter(item => item.roomflowLineId !== removed.roomflow_line_id);
                }
                this.saveEstimateStorage();
                this.refreshMainEstimate();
                this.renderEstimateBuilder(forceCost);
            }));
        },

        addEstimateLine() {
            const select = document.getElementById('roomflow-add-catalog-select');
            const item = this.catalogCache.find(row => row.id === select?.value);
            if (!item) return;
            const line = {
                roomflow_line_id: this.lineId(),
                catalog_item_id: item.id,
                name: item.name,
                description: item.description || '',
                section_name: this.currentEstimateHeader || null,
                category: item.category || 'other',
                pricing_method: item.pricing_method,
                quantity: 1,
                unit: item.unit,
                unit_price: Number(item.unit_price) || 0,
                taxable: Boolean(item.taxable),
                optional: false,
                selected: true
            };
            this.currentLines.push(line);
            this.syncLineToMainEstimate(line);
            this.saveEstimateStorage();
            this.refreshMainEstimate();
            this.renderEstimateBuilder();
        },

        async ensureCloudJob() {
            const jobId = this.currentJobId();
            if (jobId) return jobId;
            if (window.RoomFlowSync?.createCloudJobRecord) {
                const created = await window.RoomFlowSync.createCloudJobRecord(
                    state.currentJobName,
                    state.costing?.customerName || state.currentJobName,
                    state.costing?.customerEmail || '',
                    state.costing?.customerPhone || ''
                );
                if (created?.id) {
                    this.setJobMapping(state.currentJobName, created.id);
                    window.autosaveJob();
                    return created.id;
                }
            }
            throw new Error('Could not create or resolve the cloud job record.');
        },

        async saveDraftEstimate(options = {}) {
            const throwOnError = Boolean(options?.throwOnError);
            const fail = (reason, type = 'error') => {
                const error = reason instanceof Error ? reason : new Error(String(reason));
                this.toast(error.message, type);
                if (throwOnError) throw error;
                return null;
            };
            this.restoreEstimateDraftState();
            if (!this.currentLines.length) return fail('Add at least one item to the Inline Customer Estimate before saving or syncing.', 'warning');
            this.currentEstimateHeader = String(this.currentEstimateHeader || '').trim().slice(0, 240);
            if (!this.currentEstimateHeader) return fail('Enter an Estimate Header before saving or syncing.', 'warning');
            this.currentServiceStreet = String(this.currentServiceStreet || '').trim().slice(0, 300);
            this.currentServiceCity = String(this.currentServiceCity || '').trim().slice(0, 120);
            this.currentServiceState = String(this.currentServiceState || '').trim().slice(0, 80);
            this.currentServicePostalCode = String(this.currentServicePostalCode || '').trim().slice(0, 32);
            if (!this.currentServiceStreet) return fail('Enter the Service Street Address before saving or syncing.', 'warning');
            if (!this.currentServiceCity) return fail('Enter the Service City before saving or syncing.', 'warning');
            if (!this.currentServiceState) return fail('Enter the Service State before saving or syncing.', 'warning');
            if (!this.currentServicePostalCode) return fail('Enter the Postal Code before saving or syncing.', 'warning');
            this.currentLines.forEach(line => { line.section_name = this.currentEstimateHeader; });
            if (state.costing) {
                state.costing.serviceStreet = this.currentServiceStreet;
                state.costing.serviceCity = this.currentServiceCity;
                state.costing.serviceState = this.currentServiceState;
                state.costing.servicePostalCode = this.currentServicePostalCode;
                state.costing.customerAddress = this.serviceAddress();
            }
            const client = this.getClient();
            const orgId = this.currentOrgId();
            try {
                const jobId = await this.ensureCloudJob();
                if (!this.currentEstimateId) {
                    const existing = await client
                        .from('estimates')
                        .select('id')
                        .eq('job_id', jobId)
                        .eq('status', 'draft')
                        .order('version_number', { ascending: false })
                        .limit(1)
                        .maybeSingle();
                    if (existing.error) throw existing.error;
                    if (existing.data?.id) this.currentEstimateId = existing.data.id;
                }
                const subtotal = this.currentLines.reduce((sum, line) => sum + Number(line.quantity || 0) * Number(line.unit_price || 0), 0);
                const taxableSubtotal = this.currentLines.filter(line => line.taxable).reduce((sum, line) => sum + Number(line.quantity || 0) * Number(line.unit_price || 0), 0);
                const taxRate = Number(state.costing?.settings?.salesTaxRate ?? state.costing?.settings?.taxRate ?? 0);
                const taxTotal = taxableSubtotal * taxRate / 100;
                const estimatePayload = {
                    organization_id: orgId,
                    job_id: jobId,
                    estimate_number: `RF-${new Date().getFullYear()}-${jobId.replaceAll('-', '').slice(0, 8).toUpperCase()}`,
                    status: 'draft', subtotal, taxable_subtotal: taxableSubtotal,
                    tax_rate: taxRate, tax_total: taxTotal, total: subtotal + taxTotal,
                    terms: state.currentOrganization?.default_proposal_terms || null,
                    created_by: state.sessionUser?.id || null
                };
                let estimate;
                if (this.currentEstimateId) {
                    const result = await client.from('estimates').update(estimatePayload).eq('id', this.currentEstimateId).select('*').single();
                    if (result.error) throw result.error;
                    estimate = result.data;
                    await client.from('estimate_lines').delete().eq('estimate_id', estimate.id);
                } else {
                    const result = await client.from('estimates').insert(estimatePayload).select('*').single();
                    if (result.error) throw result.error;
                    estimate = result.data;
                    this.currentEstimateId = estimate.id;
                }
                const rows = this.currentLines.map((line, index) => ({
                    estimate_id: estimate.id,
                    catalog_item_id: line.catalog_item_id || null,
                    room_id: line.room_id || null,
                    section_name: this.currentEstimateHeader,
                    roomflow_line_id: line.roomflow_line_id || this.lineId(),
                    category: line.category || 'other',
                    name: line.name,
                    description: line.description || '',
                    pricing_method: line.pricing_method || 'fixed',
                    quantity: Number(line.quantity) || 0,
                    unit: line.unit || 'each',
                    unit_price: Number(line.unit_price) || 0,
                    taxable: Boolean(line.taxable),
                    optional: Boolean(line.optional),
                    selected: line.selected !== false,
                    sort_order: index,
                    calculation_metadata: { ...(line.calculation_metadata || {}), category: line.category || 'other' }
                }));
                const linesResult = await client.from('estimate_lines').insert(rows);
                if (linesResult.error) throw linesResult.error;
                const jobResult = await client.from('jobs').update({
                    status: 'Estimate Draft', estimate_status: 'draft', tracking_color: 'purple',
                    property_address: this.currentServiceStreet,
                    city: this.currentServiceCity,
                    state: this.currentServiceState,
                    postal_code: this.currentServicePostalCode
                }).eq('id', jobId);
                if (jobResult.error) throw jobResult.error;
                await this.uploadLayoutAttachments(estimate.id, jobId);
                this.saveEstimateStorage();
                this.toast(`Draft ${estimate.estimate_number} saved.`, 'success');
                this.refreshInboundLeads();
                return estimate;
            } catch (error) {
                return fail(error);
            }
        },

        canvasBlob(canvas) {
            return new Promise(resolve => canvas?.toBlob(resolve, 'image/png', 0.92));
        },

        async uploadLayoutAttachments(estimateId, jobId) {
            const client = this.getClient();
            const orgId = this.currentOrgId();
            const canvases = [
                { type: 'layout_2d', canvas: document.getElementById('sketch-canvas'), name: 'layout-2d.png' },
                { type: 'layout_3d', canvas: document.querySelector('#three-container canvas'), name: 'layout-3d.png' }
            ];
            for (const item of canvases) {
                if (!item.canvas) continue;
                const blob = await this.canvasBlob(item.canvas);
                if (!blob) continue;
                const path = `${orgId}/${jobId}/${estimateId}/${item.name}`;
                const upload = await client.storage.from('estimate-attachments').upload(path, blob, { contentType: 'image/png', upsert: true });
                if (upload.error) {
                    console.warn('Layout attachment upload failed', upload.error);
                    continue;
                }
                await client.from('estimate_attachments').upsert({
                    estimate_id: estimateId,
                    attachment_type: item.type,
                    storage_bucket: 'estimate-attachments',
                    storage_path: path,
                    display_name: item.name,
                    mime_type: 'image/png'
                }, { onConflict: 'estimate_id,attachment_type' });
            }
        },

        async markEstimateSent() {
            const estimate = await this.saveDraftEstimate();
            if (!estimate) return;
            const client = this.getClient();
            const jobId = await this.ensureCloudJob();
            const { data: job } = await client.from('jobs').select('*,customers(*)').eq('id', jobId).single();
            const customer = Array.isArray(job?.customers) ? job.customers[0] : job?.customers;
            if (!customer?.email) return this.toast('Customer email is required before follow-ups can be scheduled.', 'warning');
            const sentAt = new Date();
            await client.from('estimates').update({ status: 'sent', sent_at: sentAt.toISOString() }).eq('id', estimate.id);
            await client.from('jobs').update({ status: 'Estimate Sent', estimate_status: 'sent', followup_status: 'active', tracking_color: 'green' }).eq('id', jobId);
            const { data: sequences } = await client.from('outreach_sequences').select('*').eq('organization_id', this.currentOrgId()).eq('active', true).limit(1);
            const sequence = sequences?.[0];
            if (sequence?.steps?.length) {
                const messages = sequence.steps.map(step => ({
                    organization_id: this.currentOrgId(), job_id: jobId, estimate_id: estimate.id,
                    sequence_id: sequence.id, sequence_step: step.step, channel: 'email', recipient: customer.email,
                    subject: String(step.subject || 'Estimate follow-up').replaceAll('{{first_name}}', customer.first_name || customer.name?.split(' ')[0] || '').replaceAll('{{estimate_number}}', estimate.estimate_number),
                    body: String(step.body || '').replaceAll('{{first_name}}', customer.first_name || customer.name?.split(' ')[0] || '').replaceAll('{{estimate_number}}', estimate.estimate_number),
                    status: 'scheduled',
                    scheduled_at: new Date(sentAt.getTime() + Number(step.delay_days || 0) * 86400000).toISOString()
                }));
                await client.from('outreach_messages').delete().eq('estimate_id', estimate.id).eq('status', 'scheduled');
                const result = await client.from('outreach_messages').insert(messages);
                if (result.error) return this.toast(`Estimate marked sent, but follow-up scheduling failed: ${result.error.message}`, 'warning');
            }
            await client.from('job_status_events').insert({
                organization_id: this.currentOrgId(), job_id: jobId, event_type: 'estimate.sent',
                old_status: job?.status, new_status: 'Estimate Sent', note: `${estimate.estimate_number} marked sent`,
                actor_user_id: state.sessionUser?.id || null
            });
            this.toast('Estimate marked sent and follow-ups scheduled.', 'success');
            this.refreshInboundLeads();
        },

        resetRealtimeSubscription() {
            const client = this.getClient();
            if (client && this.leadChannel) client.removeChannel(this.leadChannel);
            this.leadChannel = null;
            this.leadChannelOrgId = null;
        },

        removeDeletedCloudJobMapping(jobId) {
            if (!jobId) return;
            try {
                const map = JSON.parse(localStorage.getItem(this.jobIdMapKey) || '{}');
                const linkedNames = [];
                let changed = false;
                Object.keys(map).forEach(name => {
                    if (map[name] === jobId) { linkedNames.push(name); delete map[name]; changed = true; }
                });
                if (changed) localStorage.setItem(this.jobIdMapKey, JSON.stringify(map));
                const jobs = JSON.parse(localStorage.getItem('roomflow_jobs') || '{}');
                let jobsChanged = false;
                Object.keys(jobs).forEach(name => {
                    if (jobs[name]?.jobId === jobId || linkedNames.includes(name)) {
                        delete jobs[name];
                        jobsChanged = true;
                    }
                });
                if (jobsChanged) localStorage.setItem('roomflow_jobs', JSON.stringify(jobs));
                if (state.jobId === jobId) state.jobId = null;
            } catch (error) {
                console.warn('Local RoomFlow lead cleanup failed', error);
            }
        },

        scheduleSharedJobsRefresh() {
            clearTimeout(this.sharedRefreshTimer);
            this.sharedRefreshTimer = setTimeout(() => {
                window.RoomFlowSync?.refreshSharedJobs?.().catch(error => console.warn('Realtime shared job refresh failed', error));
            }, 350);
        },

        subscribeRealtime() {
            const client = this.getClient();
            const orgId = this.currentOrgId();
            if (!client || !orgId) return;
            if (this.leadChannel && this.leadChannelOrgId === orgId) return;
            this.resetRealtimeSubscription();
            this.leadChannelOrgId = orgId;
            this.leadChannel = client.channel(`roomflow-tracker-${orgId}`)
                .on('postgres_changes', { event: '*', schema: 'public', table: 'jobs', filter: `organization_id=eq.${orgId}` }, payload => {
                    if (payload.eventType === 'DELETE') this.removeDeletedCloudJobMapping(payload.old?.id);
                    this.refreshInboundLeads();
                    this.scheduleSharedJobsRefresh();
                })
                .on('postgres_changes', { event: '*', schema: 'public', table: 'lead_imports', filter: `organization_id=eq.${orgId}` }, payload => {
                    if (payload.eventType === 'INSERT') this.toast(`New lead imported${payload.new?.source_subject ? `: ${payload.new.source_subject}` : ''}.`, 'success');
                    this.refreshInboundLeads();
                    this.refreshIntegrationDiagnostics();
                })
                .subscribe();
        }
    };

    window.RoomFlowIntegrations = Integration;
    window.addEventListener('load', () => setTimeout(() => Integration.init(), 650));
})();
