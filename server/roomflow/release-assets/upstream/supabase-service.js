// --- ROOMFLOW SUPABASE INTEGRATION & OFFLINE PERSISTENCE SERVICE ---

let supabaseClient = null;

function initSupabase() {
    if (typeof supabase === 'undefined') {
        console.warn("Supabase library not loaded yet.");
        return null;
    }
    const config = window.RoomFlowConfig || {};
    if (!config.supabaseUrl || !config.supabaseAnonKey) {
        console.error("Supabase config is missing endpoints.");
        return null;
    }
    supabaseClient = supabase.createClient(config.supabaseUrl, config.supabaseAnonKey);
    return supabaseClient;
}

// Global cached permissions
state.userCapabilities = [];
state.userOrganizations = [];
state.currentOrganization = null;
state.sessionUser = null;
state.syncStatus = 'offline'; // 'saving', 'saved', 'uploading', 'synced', 'offline', 'conflict'

// 1. Authentication helpers
window.RoomFlowAuth = {
    async signUp(email, password, fullName) {
        const client = supabaseClient || initSupabase();
        if (!client) throw new Error("Database offline");

        const { data, error } = await client.auth.signUp({
            email,
            password,
            options: {
                data: { full_name: fullName }
            }
        });
        if (error) throw new Error(translateAuthError(error.message));
        return data;
    },

    async signIn(email, password) {
        const client = supabaseClient || initSupabase();
        if (!client) throw new Error("Database offline");

        const { data, error } = await client.auth.signInWithPassword({ email, password });
        if (error) throw new Error(translateAuthError(error.message));
        
        state.sessionUser = data.user;
        await this.loadSessionContext();
        return data;
    },

    async sendMagicLink(email) {
        const client = supabaseClient || initSupabase();
        if (!client) throw new Error("Database offline");

        const { error } = await client.auth.signInWithOtp({ email });
        if (error) throw new Error(translateAuthError(error.message));
        return true;
    },

    async signOut() {
        const client = supabaseClient || initSupabase();
        if (client) {
            await client.auth.signOut();
        }
        state.sessionUser = null;
        state.userCapabilities = [];
        state.userOrganizations = [];
        state.currentOrganization = null;
        localStorage.removeItem('roomflow_active_org_id');
        window.location.reload();
    },

    async loadSessionContext() {
        const client = supabaseClient || initSupabase();
        if (!client) return;

        const { data: { session } } = await client.auth.getSession();
        if (!session) {
            state.sessionUser = null;
            state.syncStatus = 'offline';
            if (typeof RoomFlowSync !== 'undefined' && RoomFlowSync.updateSyncBadge) {
                RoomFlowSync.updateSyncBadge();
            }
            return;
        }

        state.sessionUser = session.user;
        state.syncStatus = 'synced';
        if (typeof RoomFlowSync !== 'undefined' && RoomFlowSync.updateSyncBadge) {
            RoomFlowSync.updateSyncBadge();
        }
        
        // Fetch organization memberships for current user
        const { data: members, error: memErr } = await client
            .from('organization_members')
            .select('organization_id, role_id')
            .eq('user_id', session.user.id);

        if (memErr) {
            console.error("Error fetching organization memberships:", memErr);
        }

        if (members && members.length > 0) {
            const orgIds = members.map(m => m.organization_id);
            const roleIds = members.map(m => m.role_id).filter(Boolean);

            // Fetch organizations
            const { data: orgsData } = await client
                .from('organizations')
                .select('id, name, address, phone, email, logo_url, colors, default_measurement_units, timezone')
                .in('id', orgIds);

            // Fetch custom roles
            let rolesData = [];
            if (roleIds.length > 0) {
                const { data: rData } = await client
                    .from('custom_roles')
                    .select('id, name')
                    .in('id', roleIds);
                rolesData = rData || [];
            }

            const orgMap = new Map((orgsData || []).map(o => [o.id, o]));
            const roleMap = new Map((rolesData || []).map(r => [r.id, r]));

            state.userOrganizations = members.map(m => {
                const orgObj = orgMap.get(m.organization_id);
                const roleObj = roleMap.get(m.role_id);
                return {
                    id: m.organization_id,
                    name: orgObj ? orgObj.name : 'Organization',
                    role: roleObj ? roleObj.name : 'Company Owner',
                    colors: orgObj ? orgObj.colors : null,
                    units: orgObj ? orgObj.default_measurement_units : 'ft',
                    timezone: orgObj ? orgObj.timezone : 'UTC'
                };
            });

            // Restore active company selection
            let activeOrgId = localStorage.getItem('roomflow_active_org_id');
            if (!activeOrgId || !state.userOrganizations.some(o => o.id === activeOrgId)) {
                if (state.userOrganizations.length > 0) {
                    activeOrgId = state.userOrganizations[0].id;
                }
            }
            if (activeOrgId) {
                await this.setActiveOrganization(activeOrgId);
            }
        } else {
            state.userOrganizations = [];
        }
        
        // Update header display if elements exist
        const nameEl = document.getElementById('session-user-name');
        if (nameEl) nameEl.innerText = session.user.email;
    },

    async setActiveOrganization(orgId) {
        const client = supabaseClient || initSupabase();
        if (!client || !state.sessionUser) return;

        const org = state.userOrganizations.find(o => o.id === orgId);
        if (org) {
            state.currentOrganization = org;
            localStorage.setItem('roomflow_active_org_id', orgId);
        }

        // Fetch user's role_id in this organization
        const { data: member } = await client
            .from('organization_members')
            .select('id, role_id')
            .eq('organization_id', orgId)
            .eq('user_id', state.sessionUser.id)
            .maybeSingle();

        state.userCapabilities = [];

        if (member && member.role_id) {
            // Fetch capabilities for this role
            const { data: caps } = await client
                .from('role_capabilities')
                .select('capability')
                .eq('role_id', member.role_id);

            if (caps && caps.length > 0) {
                state.userCapabilities = caps.map(c => c.capability).filter(Boolean);
            }
        }

        // Check for individual member capability overrides
        if (member && member.id) {
            const { data: overrides } = await client
                .from('member_capability_overrides')
                .select('capability, allowed')
                .eq('member_id', member.id);

            if (overrides) {
                overrides.forEach(ov => {
                    if (ov.allowed && !state.userCapabilities.includes(ov.capability)) {
                        state.userCapabilities.push(ov.capability);
                    } else if (!ov.allowed) {
                        state.userCapabilities = state.userCapabilities.filter(c => c !== ov.capability);
                    }
                });
            }
        }

        // Apply branding colors dynamically
        if (org && org.colors) {
            const root = document.documentElement;
            if (org.colors.primary) root.style.setProperty('--accent-blue', org.colors.primary);
            if (org.colors.accent) root.style.setProperty('--accent-teal', org.colors.accent);
        }

        // Re-render costing screens with capability context
        if (typeof window.renderCostUI === 'function') window.renderCostUI();
        if (typeof window.renderGuidedStep === 'function') window.renderGuidedStep();
        if (window.RoomFlowSync?.refreshSharedJobs) {
            await window.RoomFlowSync.refreshSharedJobs().catch(error => console.warn('Shared jobs refresh failed after company switch:', error));
        }
    },

    async createCompany(name) {
        const client = supabaseClient || initSupabase();
        if (!client || !state.sessionUser) throw new Error("Authentication required");

        let newOrgId = null;

        // Try RPC procedure first
        try {
            const { data, error } = await client.rpc('create_new_company_with_owner', {
                company_name: name,
                owner_id: state.sessionUser.id
            });
            if (!error && data) {
                newOrgId = data;
            }
        } catch (rpcErr) {
            console.warn("RPC company creation failed, using direct client fallback:", rpcErr);
        }

        // Direct client fallback if RPC failed or had permission restrictions
        if (!newOrgId) {
            // 1. Create Organization
            const { data: orgData, error: orgErr } = await client
                .from('organizations')
                .insert([{ name: name }])
                .select('id')
                .single();

            if (orgErr) throw new Error("Could not create company: " + orgErr.message);
            newOrgId = orgData.id;

            // 2. Create Company Owner Role
            const { data: roleData, error: roleErr } = await client
                .from('custom_roles')
                .insert([{
                    organization_id: newOrgId,
                    name: 'Company Owner',
                    description: 'Full control over company settings and pricing',
                    is_system: true
                }])
                .select('id')
                .single();

            if (!roleErr && roleData) {
                const ownerRoleId = roleData.id;

                // 3. Add all owner capabilities
                const allCapabilities = [
                    'manage_company', 'manage_members', 'manage_roles', 'manage_groups',
                    'create_jobs', 'view_company_jobs', 'edit_job_information', 'edit_floor_plans',
                    'edit_measurements', 'edit_job_scope', 'upload_attachments', 'view_material_quantities',
                    'edit_material_quantities', 'view_internal_costs', 'edit_internal_costs',
                    'view_customer_prices', 'edit_customer_prices', 'view_margin', 'edit_margin',
                    'generate_proposals', 'approve_proposals', 'generate_work_orders',
                    'approve_work_orders', 'assign_jobs', 'manage_catalog', 'delete_jobs',
                    'restore_jobs', 'view_audit_logs'
                ];

                const capInserts = allCapabilities.map(cap => ({
                    role_id: ownerRoleId,
                    capability: cap
                }));

                await client.from('role_capabilities').insert(capInserts);

                // 4. Add User to organization_members as Owner
                await client
                    .from('organization_members')
                    .insert([{
                        organization_id: newOrgId,
                        user_id: state.sessionUser.id,
                        role_id: ownerRoleId
                    }]);
            } else {
                // Fallback membership insertion
                await client
                    .from('organization_members')
                    .insert([{
                        organization_id: newOrgId,
                        user_id: state.sessionUser.id
                    }]);
            }
        }

        if (newOrgId) {
            localStorage.setItem('roomflow_active_org_id', newOrgId);
            await this.loadSessionContext();
            await this.setActiveOrganization(newOrgId);
            if (typeof populateCompanySwitcher === 'function') {
                populateCompanySwitcher();
            }
        }
        return newOrgId;
    }
};

// Check permissions locally
window.hasCapability = function(capabilityName) {
    if (!state.sessionUser) return true; // offline/standalone local user has full permissions
    return state.userCapabilities.includes(capabilityName);
};

// Translate auth exceptions to friendly user-facing alerts
function translateAuthError(msg) {
    if (!msg) return "An unexpected error occurred.";
    if (msg.includes("Failed to fetch") || msg.includes("fetch") || msg.includes("NetworkError") || msg.includes("your-project-id")) {
        return "Cannot connect to Supabase cloud. Please update config.js with your live Supabase project URL & API key, or use RoomFlow offline.";
    }
    if (msg.includes("Invalid login credentials")) {
        return "Incorrect email or password. Please verify and try again.";
    }
    if (msg.includes("JWT expired") || msg.includes("session_expired")) {
        return "Your session expired. Please sign in again. Your saved work remains available locally.";
    }
    if (msg.includes("User already exists")) {
        return "An account with this email address has already been registered.";
    }
    return msg;
}

// 2. Offline Database Sync Service (IndexedDB)
const DB_NAME = 'roomflow_offline_store';
const STORE_NAME = 'sync_queue';
const ROOMFLOW_PROJECT_SNAPSHOT_KEYS = [
    'schemaVersion', 'currentStep', 'guidedStep3Mode', 'currentLevelId', 'levels',
    'rooms', 'walls', 'roomConnections', 'doors', 'windows', 'openings', 'stairs',
    'floorHatches', 'utilities', 'sumpPumps', 'dehumidifiers', 'dischargeLines',
    'interiorPipes', 'stanchions', 'mainBeams', 'capturedMeasurements',
    'createdTimestamp', 'updatedTimestamp', 'revisionNumber', 'leadIntake'
];
const ROOMFLOW_CLOUD_JOB_MAP_KEY = 'roomflow_cloud_job_ids_v1';
const ROOMFLOW_ESTIMATE_DRAFT_KEY = 'roomflow_estimate_drafts_v1';

function cloneRoomFlowValue(value, fallback = null) {
    try {
        return value === undefined ? fallback : JSON.parse(JSON.stringify(value));
    } catch (error) {
        return fallback;
    }
}

function buildRoomFlowProjectSnapshot(payload) {
    const snapshot = {};
    ROOMFLOW_PROJECT_SNAPSHOT_KEYS.forEach(key => {
        if (payload?.[key] !== undefined) snapshot[key] = cloneRoomFlowValue(payload[key], payload[key]);
    });
    return snapshot;
}

function buildRoomFlowCostingSnapshot(costing) {
    const snapshot = cloneRoomFlowValue(costing, null);
    if (!snapshot) return null;
    // Photos are shared through the protected attachment bucket. Keeping base64 image
    // bodies out of JSON prevents a field photo from blocking the rest of a job sync.
    if (Array.isArray(snapshot.photos)) {
        snapshot.photos = snapshot.photos.map(photo => {
            if (!photo || typeof photo !== 'object') return photo;
            const cleaned = { ...photo };
            ['data', 'dataUrl', 'base64', 'preview'].forEach(key => {
                if (typeof cleaned[key] === 'string' && cleaned[key].startsWith('data:')) delete cleaned[key];
            });
            return cleaned;
        });
    }
    return snapshot;
}

function isMissingRoomFlowTable(error) {
    return Boolean(error && (
        ['42P01', 'PGRST204', 'PGRST205'].includes(error.code)
        || /does not exist|schema cache|could not find the table/i.test(error.message || '')
    ));
}

function isUuid(value) {
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(String(value || ''));
}

function waitForIndexedDBTransaction(transaction) {
    return new Promise((resolve, reject) => {
        transaction.oncomplete = () => resolve();
        transaction.onerror = () => reject(transaction.error);
        transaction.onabort = () => reject(transaction.error || new Error('IndexedDB transaction aborted'));
    });
}

function openIndexedDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, 1);
        request.onupgradeneeded = (e) => {
            const db = e.target.result;
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                db.createObjectStore(STORE_NAME, { keyPath: 'id' });
            }
        };
        request.onsuccess = (e) => resolve(e.target.result);
        request.onerror = (e) => reject(e.target.error);
    });
}

window.RoomFlowSync = {
    processingQueue: false,
    refreshPromise: null,

    async enqueueOffline(jobName, payload) {
        try {
            const db = await openIndexedDB();
            const tx = db.transaction(STORE_NAME, 'readwrite');
            const store = tx.objectStore(STORE_NAME);
            const organizationId = payload?.organizationId || state.currentOrganization?.id || 'local';
            
            await new Promise((resolve, reject) => {
                const req = store.put({
                    id: `${organizationId}:${jobName}`,
                    jobName,
                    payload: payload,
                    timestamp: Date.now(),
                    status: 'pending'
                });
                req.onsuccess = () => resolve();
                req.onerror = () => reject(req.error);
            });
            
            state.syncStatus = navigator.onLine && state.sessionUser ? 'saved' : 'offline';
            this.updateSyncBadge();
        } catch (e) {
            console.error("IndexedDB Cache failed:", e);
        }
    },

    async processSyncQueue() {
        if (this.processingQueue || !navigator.onLine || !state.sessionUser || !state.currentOrganization) return;

        const client = supabaseClient || initSupabase();
        if (!client) return;

        this.processingQueue = true;
        try {
            const db = await openIndexedDB();
            const tx = db.transaction(STORE_NAME, 'readonly');
            const store = tx.objectStore(STORE_NAME);
            
            const queue = await new Promise((resolve, reject) => {
                const req = store.getAll();
                req.onsuccess = () => resolve(req.result);
                req.onerror = () => reject(req.error);
            });

            const currentOrgId = state.currentOrganization.id;
            const currentQueue = queue.filter(item => {
                const queuedOrgId = item.payload?.organizationId;
                return !queuedOrgId || queuedOrgId === currentOrgId;
            });

            if (currentQueue.length === 0) {
                return await this.refreshSharedJobs();
            }

            state.syncStatus = 'uploading';
            this.updateSyncBadge();

            for (const item of currentQueue) {
                const p = item.payload;
                const jobName = item.jobName || p.currentJobName || item.id;
                const customerName = p.costing?.customerName || p.customerName || jobName;
                const customerAddress = p.costing?.customerAddress || p.customerAddress || '';

                // 1. Fetch or create Customer record
                let customerId = null;
                const { data: custs, error: customerLookupError } = await client
                    .from('customers')
                    .select('id')
                    .eq('organization_id', currentOrgId)
                    .eq('name', customerName)
                    .limit(1);
                if (customerLookupError) throw customerLookupError;

                if (custs && custs.length > 0) {
                    customerId = custs[0].id;
                    const customerUpdate = await client
                        .from('customers')
                        .update({
                            name: customerName,
                            phone: p.costing?.customerPhone || '',
                            email: p.costing?.customerEmail || '',
                            address: customerAddress,
                            notes: p.costing?.notes || ''
                        })
                        .eq('id', customerId);
                    if (customerUpdate.error) console.warn('Customer contact details were not updated during job sync:', customerUpdate.error.message || customerUpdate.error);
                } else {
                    const { data: newCust, error: custErr } = await client
                        .from('customers')
                        .insert({
                            organization_id: currentOrgId,
                            name: customerName,
                            phone: p.costing?.customerPhone || '',
                            email: p.costing?.customerEmail || '',
                            address: customerAddress,
                            notes: p.costing?.notes || ''
                        })
                        .select('id')
                        .single();
                    if (custErr) throw custErr;
                    customerId = newCust.id;
                }

                // 2. Fetch or create Job record
                let jobId = null;
                let currentVersion = 1;
                let map = {};
                try { map = JSON.parse(localStorage.getItem(ROOMFLOW_CLOUD_JOB_MAP_KEY) || '{}'); } catch (error) { map = {}; }
                const requestedJobId = isUuid(p.jobId) ? p.jobId : (isUuid(map[jobName]) ? map[jobName] : null);
                let jobLookup = client
                    .from('jobs')
                    .select('id, current_version_number')
                    .eq('organization_id', currentOrgId);
                jobLookup = requestedJobId ? jobLookup.eq('id', requestedJobId) : jobLookup.eq('name', jobName);
                const { data: jobs, error: jobLookupError } = await jobLookup.limit(1);
                if (jobLookupError) throw jobLookupError;

                if (jobs && jobs.length > 0) {
                    jobId = jobs[0].id;
                    currentVersion = jobs[0].current_version_number;
                    const jobUpdate = await client
                        .from('jobs')
                        .update({ customer_id: customerId, name: jobName, property_address: customerAddress })
                        .eq('id', jobId);
                    if (jobUpdate.error && !isMissingRoomFlowTable(jobUpdate.error)) throw jobUpdate.error;
                } else {
                    const { data: newJob, error: jobErr } = await client
                        .from('jobs')
                        .insert({
                            organization_id: currentOrgId,
                            customer_id: customerId,
                            name: jobName,
                            status: 'Draft',
                            property_address: customerAddress,
                            current_version_number: 1
                        })
                        .select('id')
                        .single();
                    if (jobErr) throw jobErr;
                    jobId = newJob.id;
                }

                // 3. Upsert Layout (Footprints geometry)
                const projectSnapshot = buildRoomFlowProjectSnapshot(p);
                const { error: layoutErr } = await client
                    .from('job_layouts')
                    .upsert({
                        job_id: jobId,
                        version_number: currentVersion,
                        layout_json: projectSnapshot
                    }, { onConflict: 'job_id,version_number' });
                if (layoutErr) throw layoutErr;

                // The complete project snapshot enables true cross-device restoration.
                const projectResult = await client
                    .from('job_project_snapshots')
                    .upsert({
                        job_id: jobId,
                        organization_id: currentOrgId,
                        project_state: projectSnapshot,
                        client_updated_at: new Date(p.lastModified || Date.now()).toISOString(),
                        updated_by: state.sessionUser?.id || null
                    }, { onConflict: 'job_id' });
                if (projectResult.error && !isMissingRoomFlowTable(projectResult.error)) throw projectResult.error;

                // 4. Upsert protected costing only for users allowed to edit every
                // sensitive portion of the snapshot. Customer estimate lines use
                // their own permissioned estimates tables.
                if (hasCapability('edit_internal_costs') && hasCapability('edit_customer_prices') && hasCapability('edit_margin') && p.costing) {
                    const costingResult = await client
                        .from('job_costing_snapshots')
                        .upsert({
                            job_id: jobId,
                            organization_id: currentOrgId,
                            costing_state: buildRoomFlowCostingSnapshot(p.costing),
                            client_updated_at: new Date(p.lastModified || Date.now()).toISOString(),
                            updated_by: state.sessionUser?.id || null
                        }, { onConflict: 'job_id' });
                    if (costingResult.error && !isMissingRoomFlowTable(costingResult.error)) throw costingResult.error;
                }

                // Maintain the legacy aggregate pricing row for older installations.
                if (hasCapability('edit_margin') && p.costing) {
                    const pricingResult = await client
                        .from('job_pricing')
                        .upsert({
                            job_id: jobId,
                            target_gross_margin: p.costing.settings?.targetGrossMargin || 40.0,
                            sales_tax_rate: p.costing.settings?.salesTaxRate || 6.0,
                            additional_overhead_rate: p.costing.settings?.overhead || 15.0,
                            commission_rate: p.costing.commission || 0.0
                        }, { onConflict: 'job_id' });
                    if (pricingResult.error) throw pricingResult.error;
                }

                map[jobName] = jobId;
                localStorage.setItem(ROOMFLOW_CLOUD_JOB_MAP_KEY, JSON.stringify(map));
                const localJobs = JSON.parse(localStorage.getItem('roomflow_jobs') || '{}');
                if (localJobs[jobName]) {
                    localJobs[jobName].jobId = jobId;
                    localJobs[jobName].organizationId = currentOrgId;
                    localJobs[jobName].sharedFromCloud = true;
                    localJobs[jobName].syncState = 'synchronized';
                    localJobs[jobName].cloudUpdatedAt = Date.now();
                    localStorage.setItem('roomflow_jobs', JSON.stringify(localJobs));
                }

                // Delete from sync queue
                const delTx = db.transaction(STORE_NAME, 'readwrite');
                delTx.objectStore(STORE_NAME).delete(item.id);
                await waitForIndexedDBTransaction(delTx);
            }

            state.syncStatus = 'synced';
            this.updateSyncBadge();
            return await this.refreshSharedJobs();
        } catch (e) {
            console.error("Reconciliation failed:", e);
            state.syncStatus = 'offline';
            this.updateSyncBadge();
            return { error: e, loadedJobs: 0, loadedEstimates: 0 };
        } finally {
            this.processingQueue = false;
        }
    },

    async refreshSharedJobs() {
        if (this.refreshPromise) return this.refreshPromise;
        if (!navigator.onLine || !state.sessionUser || !state.currentOrganization) {
            return { loadedJobs: 0, loadedEstimates: 0, skipped: true };
        }

        const client = supabaseClient || initSupabase();
        if (!client) return { loadedJobs: 0, loadedEstimates: 0, skipped: true };
        const orgId = state.currentOrganization.id;

        this.refreshPromise = (async () => {
            const jobResult = await client
                .from('jobs')
                .select('id, organization_id, customer_id, name, status, current_version_number, property_address, city, state, postal_code, issue_description, appointment_start, estimate_status, updated_at, created_at, customers(id,name,phone,email,address,city,state,postal_code,notes)')
                .eq('organization_id', orgId)
                .order('updated_at', { ascending: false })
                .limit(250);
            if (jobResult.error) throw jobResult.error;

            const cloudJobs = jobResult.data || [];
            const jobIds = cloudJobs.map(job => job.id);
            if (!jobIds.length) {
                if (typeof window.renderRoomFlowJobsList === 'function') window.renderRoomFlowJobsList();
                return { loadedJobs: 0, loadedEstimates: 0, requiresSnapshotMigration: false };
            }

            let requiresSnapshotMigration = false;
            const projectByJob = new Map();
            const projectResult = await client
                .from('job_project_snapshots')
                .select('job_id, project_state, client_updated_at, updated_at')
                .in('job_id', jobIds);
            if (projectResult.error) {
                if (!isMissingRoomFlowTable(projectResult.error)) throw projectResult.error;
                requiresSnapshotMigration = true;
            } else {
                (projectResult.data || []).forEach(row => projectByJob.set(row.job_id, row));
            }

            // job_layouts remains a backwards-compatible source for installations
            // that have not applied the shared snapshot migration yet.
            const layoutByJob = new Map();
            const layoutResult = await client
                .from('job_layouts')
                .select('job_id, version_number, layout_json, created_at')
                .in('job_id', jobIds)
                .order('version_number', { ascending: false });
            if (layoutResult.error) throw layoutResult.error;
            (layoutResult.data || []).forEach(row => {
                if (!layoutByJob.has(row.job_id)) layoutByJob.set(row.job_id, row);
            });

            const costingByJob = new Map();
            if (hasCapability('view_internal_costs') && hasCapability('view_customer_prices') && hasCapability('view_margin')) {
                const costingResult = await client
                    .from('job_costing_snapshots')
                    .select('job_id, costing_state, client_updated_at, updated_at')
                    .in('job_id', jobIds);
                if (costingResult.error) {
                    if (!isMissingRoomFlowTable(costingResult.error)) throw costingResult.error;
                    requiresSnapshotMigration = true;
                } else {
                    (costingResult.data || []).forEach(row => costingByJob.set(row.job_id, row));
                }
            }

            const estimateByJob = new Map();
            const estimateResult = await client
                .from('estimates')
                .select('id, job_id, status, estimate_number, version_number, updated_at, created_at')
                .eq('organization_id', orgId)
                .order('version_number', { ascending: false })
                .order('updated_at', { ascending: false });
            if (estimateResult.error && !isMissingRoomFlowTable(estimateResult.error)) throw estimateResult.error;
            (estimateResult.data || []).forEach(row => {
                if (!estimateByJob.has(row.job_id)) estimateByJob.set(row.job_id, row);
            });

            const linesByEstimate = new Map();
            const estimateIds = Array.from(estimateByJob.values()).map(estimate => estimate.id);
            if (estimateIds.length) {
                let lineResult = await client
                    .from('estimate_lines')
                    .select('id, estimate_id, catalog_item_id, room_id, section_name, roomflow_line_id, category, name, description, pricing_method, quantity, unit, unit_price, taxable, optional, selected, sort_order, calculation_metadata, updated_at')
                    .in('estimate_id', estimateIds)
                    .order('sort_order', { ascending: true })
                    .limit(5000);
                if (lineResult.error && isMissingRoomFlowTable(lineResult.error)) {
                    requiresSnapshotMigration = true;
                    lineResult = await client
                        .from('estimate_lines')
                        .select('id, estimate_id, catalog_item_id, room_id, section_name, name, description, pricing_method, quantity, unit, unit_price, taxable, optional, selected, sort_order, calculation_metadata, updated_at')
                        .in('estimate_id', estimateIds)
                        .order('sort_order', { ascending: true })
                        .limit(5000);
                }
                if (lineResult.error) throw lineResult.error;
                (lineResult.data || []).forEach(line => {
                    if (!linesByEstimate.has(line.estimate_id)) linesByEstimate.set(line.estimate_id, []);
                    linesByEstimate.get(line.estimate_id).push({
                        ...line,
                        roomflow_line_id: line.roomflow_line_id || `cloud_${line.id}`,
                        category: line.category || line.calculation_metadata?.category || 'other'
                    });
                });
            }

            let localJobs = {};
            let jobMap = {};
            let estimateDrafts = {};
            try { localJobs = JSON.parse(localStorage.getItem('roomflow_jobs') || '{}'); } catch (error) { localJobs = {}; }
            try { jobMap = JSON.parse(localStorage.getItem(ROOMFLOW_CLOUD_JOB_MAP_KEY) || '{}'); } catch (error) { jobMap = {}; }
            try { estimateDrafts = JSON.parse(localStorage.getItem(ROOMFLOW_ESTIMATE_DRAFT_KEY) || '{}'); } catch (error) { estimateDrafts = {}; }

            let loadedJobs = 0;
            let loadedEstimates = 0;
            cloudJobs.forEach(job => {
                const customer = Array.isArray(job.customers) ? job.customers[0] : job.customers;
                const projectRow = projectByJob.get(job.id);
                const layoutRow = layoutByJob.get(job.id);
                const costingRow = costingByJob.get(job.id);
                const remoteProject = cloneRoomFlowValue(projectRow?.project_state || layoutRow?.layout_json, null);
                const linkedName = Object.keys(localJobs).find(name => localJobs[name]?.jobId === job.id || jobMap[name] === job.id);
                let storageName = linkedName || job.name || customer?.name || `Job ${job.id.slice(0, 8)}`;
                if (!linkedName && localJobs[storageName]?.jobId && localJobs[storageName].jobId !== job.id) {
                    storageName = `${storageName} (${job.id.slice(0, 6)})`;
                }

                const existing = localJobs[storageName] || null;
                const remoteTimestamp = Math.max(
                    Date.parse(projectRow?.client_updated_at || projectRow?.updated_at || '') || 0,
                    Date.parse(job.updated_at || job.created_at || '') || 0
                );
                const localTimestamp = Number(existing?.lastModified || existing?.updatedTimestamp || 0);
                const localPending = existing && (existing.syncState === 'pending' || (!existing.sharedFromCloud && localTimestamp > remoteTimestamp));

                const defaultCosting = {
                    customerName: customer?.name || job.name || storageName,
                    customerAddress: job.property_address || customer?.address || '',
                    serviceStreet: job.property_address || customer?.address || '',
                    serviceCity: job.city || customer?.city || '',
                    serviceState: job.state || customer?.state || '',
                    servicePostalCode: job.postal_code || customer?.postal_code || '',
                    customerPhone: customer?.phone || '',
                    customerEmail: customer?.email || '',
                    notes: customer?.notes || job.issue_description || '',
                    photos: [],
                    settings: { targetGrossMargin: 40, salesTaxRate: 6, overhead: 15 }
                };
                let merged;
                if (localPending || (!remoteProject && existing)) {
                    merged = { ...existing };
                } else {
                    merged = remoteProject || {
                        schemaVersion: '2.0.0', rooms: [], walls: [], roomConnections: [], doors: [], windows: [],
                        openings: [], stairs: [], floorHatches: [], utilities: [], sumpPumps: [], dehumidifiers: [],
                        dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [], capturedMeasurements: []
                    };
                }
                merged.costing = cloneRoomFlowValue(costingRow?.costing_state || merged.costing || existing?.costing || defaultCosting, defaultCosting);
                merged.costing.customerName = customer?.name || merged.costing.customerName || job.name;
                merged.costing.customerAddress = job.property_address || customer?.address || merged.costing.customerAddress || '';
                merged.costing.serviceStreet = job.property_address || customer?.address || merged.costing.serviceStreet || '';
                merged.costing.serviceCity = job.city || customer?.city || merged.costing.serviceCity || '';
                merged.costing.serviceState = job.state || customer?.state || merged.costing.serviceState || '';
                merged.costing.servicePostalCode = job.postal_code || customer?.postal_code || merged.costing.servicePostalCode || '';
                merged.costing.customerPhone = customer?.phone || merged.costing.customerPhone || '';
                merged.costing.customerEmail = customer?.email || merged.costing.customerEmail || '';
                merged.customerName = merged.costing.customerName;
                merged.customerAddress = merged.costing.customerAddress;
                merged.jobId = job.id;
                merged.organizationId = orgId;
                merged.currentJobName = storageName;
                merged.cloudStatus = job.status || 'Draft';
                merged.estimateStatus = job.estimate_status || 'not_started';
                merged.sharedFromCloud = true;
                merged.cloudUpdatedAt = remoteTimestamp || Date.now();
                merged.lastModified = localPending ? localTimestamp : (remoteTimestamp || Date.now());
                merged.syncState = localPending ? (existing.syncState || 'pending') : 'synchronized';
                localJobs[storageName] = merged;
                jobMap[storageName] = job.id;
                loadedJobs += 1;

                const estimate = estimateByJob.get(job.id);
                if (estimate) {
                    const remoteEstimateTime = Date.parse(estimate.updated_at || estimate.created_at || '') || 0;
                    const existingDraft = estimateDrafts[storageName];
                    const existingIsLocalOnly = existingDraft?.lines?.length && !existingDraft.estimateId;
                    if (!existingIsLocalOnly && (!existingDraft?.cloudUpdatedAt || remoteEstimateTime >= existingDraft.cloudUpdatedAt)) {
                        const estimateLines = linesByEstimate.get(estimate.id) || [];
                        estimateDrafts[storageName] = {
                            lines: estimateLines,
                            estimateId: estimate.id,
                            header: estimateLines.find(line => line.section_name)?.section_name || `${storageName} Estimate`,
                            estimateNumber: estimate.estimate_number,
                            status: estimate.status,
                            cloudUpdatedAt: remoteEstimateTime
                        };
                    }
                    loadedEstimates += 1;
                }
            });

            localStorage.setItem('roomflow_jobs', JSON.stringify(localJobs));
            localStorage.setItem(ROOMFLOW_CLOUD_JOB_MAP_KEY, JSON.stringify(jobMap));
            localStorage.setItem(ROOMFLOW_ESTIMATE_DRAFT_KEY, JSON.stringify(estimateDrafts));
            if (typeof window.renderRoomFlowJobsList === 'function') window.renderRoomFlowJobsList();
            window.dispatchEvent(new CustomEvent('roomflow-shared-jobs-updated', {
                detail: { organizationId: orgId, loadedJobs, loadedEstimates, requiresSnapshotMigration }
            }));
            return { loadedJobs, loadedEstimates, requiresSnapshotMigration };
        })().catch(error => {
            console.error('Shared jobs refresh failed:', error);
            throw error;
        }).finally(() => {
            this.refreshPromise = null;
        });

        return this.refreshPromise;
    },

    async createCloudJobRecord(jobName, customerName, email, phone) {
        if (!supabaseClient || !state.currentOrganization) return null;
        
        try {
            // 1. Create or get customer
            let customerId = null;
            const { data: custs } = await supabaseClient
                .from('customers')
                .select('id')
                .eq('organization_id', state.currentOrganization.id)
                .eq('name', customerName)
                .limit(1);

            if (custs && custs.length > 0) {
                customerId = custs[0].id;
            } else {
                const { data: newCust, error: custErr } = await supabaseClient
                    .from('customers')
                    .insert({
                        organization_id: state.currentOrganization.id,
                        name: customerName,
                        phone: phone || '',
                        email: email || ''
                    })
                    .select('id')
                    .single();
                if (custErr) throw custErr;
                customerId = newCust.id;
            }

            // 2. Create Job
            const { data: newJob, error: jobErr } = await supabaseClient
                .from('jobs')
                .insert({
                    organization_id: state.currentOrganization.id,
                    customer_id: customerId,
                    name: jobName,
                    status: 'Draft',
                    current_version_number: 1
                })
                .select('id')
                .single();
            if (jobErr) throw jobErr;

            return newJob;
        } catch (err) {
            console.error("Failed to create cloud job record:", err);
            return null;
        }
    },

    updateSyncBadge() {
        const badge = document.getElementById('sync-status-badge');
        if (!badge) return;

        const maps = {
            'saving': { text: 'Saving...', color: '#f59e0b' },
            'saved': { text: 'Saved locally', color: '#10b981' },
            'uploading': { text: 'Syncing...', color: '#3b82f6' },
            'synced': { text: 'Cloud Online', color: '#10b981' },
            'offline': { text: 'Offline (Click to Sign In)', color: '#64748b' },
            'conflict': { text: 'Conflict review needed', color: '#ef4444' }
        };

        const current = maps[state.syncStatus] || (state.sessionUser ? maps.synced : maps.offline);
        badge.innerText = current.text;
        badge.style.background = current.color;
        badge.style.cursor = !state.sessionUser ? 'pointer' : 'default';
        badge.onclick = () => {
            if (!state.sessionUser && typeof showModal === 'function') {
                showModal('auth-overlay');
            }
        };
    }
};

// Bind online/offline network alerts
window.addEventListener('online', () => {
    RoomFlowSync.processSyncQueue();
});
window.addEventListener('offline', () => {
    state.syncStatus = 'offline';
    RoomFlowSync.updateSyncBadge();
});

// UI Account Overlay controller logic
let authMode = 'signin'; // 'signin' or 'signup' or 'magic'

function updateAuthUI() {
    const title = document.querySelector('#auth-overlay h2');
    const subtitle = document.getElementById('auth-subtitle');
    const passRow = document.getElementById('auth-password-row');
    const nameRow = document.getElementById('auth-name-row');
    const submitBtn = document.getElementById('btn-auth-submit');
    const toggleBtn = document.getElementById('btn-auth-toggle-mode');
    
    if (authMode === 'signin') {
        if (title) title.innerText = "RoomFlow Sign In";
        if (subtitle) subtitle.innerText = "Sign in to sync your estimating jobs with your team.";
        if (passRow) passRow.style.display = 'flex';
        if (nameRow) nameRow.style.display = 'none';
        if (submitBtn) submitBtn.innerText = "Sign In";
        if (toggleBtn) toggleBtn.innerText = "Don't have an account? Sign Up";
    } else if (authMode === 'signup') {
        if (title) title.innerText = "Create RoomFlow Account";
        if (subtitle) subtitle.innerText = "Create a secure account to join your company organization.";
        if (passRow) passRow.style.display = 'flex';
        if (nameRow) nameRow.style.display = 'flex';
        if (submitBtn) submitBtn.innerText = "Create Account";
        if (toggleBtn) toggleBtn.innerText = "Already have an account? Sign In";
    } else if (authMode === 'magic') {
        if (title) title.innerText = "Passwordless Access";
        if (subtitle) subtitle.innerText = "Enter your email below to receive a secure sign-in magic link.";
        if (passRow) passRow.style.display = 'none';
        if (nameRow) nameRow.style.display = 'none';
        if (submitBtn) submitBtn.innerText = "Send Magic Link";
        if (toggleBtn) toggleBtn.innerText = "Return to Standard Sign In";
    }
}

function showAuthAlert(msg, type = 'error') {
    const alertBox = document.getElementById('auth-alert-box');
    if (!alertBox) return;
    alertBox.style.display = 'block';
    alertBox.innerText = msg;
    if (type === 'success') {
        alertBox.style.background = 'rgba(16, 185, 129, 0.1)';
        alertBox.style.borderColor = 'rgba(16, 185, 129, 0.2)';
        alertBox.style.color = '#a7f3d0';
    } else {
        alertBox.style.background = 'rgba(239, 68, 68, 0.1)';
        alertBox.style.borderColor = 'rgba(239, 68, 68, 0.2)';
        alertBox.style.color = '#fca5a5';
    }
}

function checkAuthOverlay() {
    const overlay = document.getElementById('auth-overlay');
    if (!overlay) return;
    if (supabaseClient && !state.sessionUser) {
        overlay.classList.remove('hidden');
    } else {
        overlay.classList.add('hidden');
    }
}

window.addEventListener('load', () => {
    initSupabase();
    
    // Bind UI actions
    const toggleBtn = document.getElementById('btn-auth-toggle-mode');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', (e) => {
            e.preventDefault();
            if (authMode === 'signin') {
                authMode = 'signup';
            } else {
                authMode = 'signin';
            }
            updateAuthUI();
        });
    }
    
    const magicLinkBtn = document.getElementById('btn-auth-magic-link');
    if (magicLinkBtn) {
        magicLinkBtn.addEventListener('click', (e) => {
            e.preventDefault();
            if (authMode === 'magic') {
                authMode = 'signin';
            } else {
                authMode = 'magic';
            }
            updateAuthUI();
        });
    }

    const submitBtn = document.getElementById('btn-auth-submit');
    if (submitBtn) {
        submitBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            const email = document.getElementById('auth-email').value.trim();
            const password = document.getElementById('auth-password').value;
            const name = document.getElementById('auth-name').value.trim();
            
            if (!email) {
                showAuthAlert("Please enter a valid email address.");
                return;
            }

            try {
                if (authMode === 'signin') {
                    await RoomFlowAuth.signIn(email, password);
                    checkAuthOverlay();
                    populateCompanySwitcher();
                } else if (authMode === 'signup') {
                    if (!password || password.length < 6) {
                        showAuthAlert("Password must be at least 6 characters long.");
                        return;
                    }
                    await RoomFlowAuth.signUp(email, password, name);
                    showAuthAlert("Registration successful! Check your email to confirm activation.", 'success');
                } else if (authMode === 'magic') {
                    await RoomFlowAuth.sendMagicLink(email);
                    showAuthAlert("Magic link sent! Check your email inbox.", 'success');
                }
            } catch (err) {
                showAuthAlert(translateAuthError(err.message));
            }
        });
    }

    // Switcher Dropdown Change handler
    const switcher = document.getElementById('header-company-switcher');
    if (switcher) {
        switcher.addEventListener('change', async (e) => {
            if (e.target.value) {
                await RoomFlowAuth.setActiveOrganization(e.target.value);
            }
        });
    }

    const switcherMore = document.getElementById('more-company-switcher');
    if (switcherMore) {
        switcherMore.addEventListener('change', async (e) => {
            if (e.target.value) {
                await RoomFlowAuth.setActiveOrganization(e.target.value);
            }
        });
    }

    const createCompanyBtn = document.getElementById('btn-more-create-company');
    if (createCompanyBtn) {
        createCompanyBtn.addEventListener('click', async () => {
            if (!state.sessionUser) {
                if (typeof showModal === 'function') showModal('auth-overlay');
                alert("Please Sign In or Create an Account first to setup your company organization.");
                return;
            }
            const input = document.getElementById('more-new-company-name');
            if (input) {
                const name = input.value.trim();
                if (!name) {
                    alert("Please enter a valid company name.");
                    return;
                }
                try {
                    await RoomFlowAuth.createCompany(name);
                    input.value = '';
                    populateCompanySwitcher();
                    alert(`Company "${name}" created successfully! You are now the Company Owner.`);
                } catch (e) {
                    alert("Failed to create company: " + e.message);
                }
            }
        });
    }

    const refreshSharedJobsBtn = document.getElementById('btn-refresh-shared-jobs');
    if (refreshSharedJobsBtn) {
        refreshSharedJobsBtn.addEventListener('click', async () => {
            if (!state.sessionUser) {
                if (typeof showModal === 'function') showModal('auth-overlay');
                return;
            }
            const originalHtml = refreshSharedJobsBtn.innerHTML;
            refreshSharedJobsBtn.disabled = true;
            refreshSharedJobsBtn.innerHTML = 'Refreshing...';
            try {
                const syncResult = await RoomFlowSync.processSyncQueue();
                if (syncResult?.error) throw syncResult.error;
                const result = syncResult?.loadedJobs !== undefined ? syncResult : await RoomFlowSync.refreshSharedJobs();
                const message = `Shared jobs updated: ${result.loadedJobs || 0} jobs and ${result.loadedEstimates || 0} estimates.`;
                if (window.RoomFlowIntegrations?.toast) {
                    window.RoomFlowIntegrations.toast(
                        result.requiresSnapshotMigration ? `${message} Apply the shared job snapshot migration for complete project and costing sync.` : message,
                        result.requiresSnapshotMigration ? 'warning' : 'success'
                    );
                }
            } catch (error) {
                if (window.RoomFlowIntegrations?.toast) window.RoomFlowIntegrations.toast(error.message || String(error), 'error');
            } finally {
                refreshSharedJobsBtn.disabled = false;
                refreshSharedJobsBtn.innerHTML = originalHtml;
                if (window.lucide) window.lucide.createIcons();
            }
        });
    }

    setTimeout(async () => {
        await RoomFlowAuth.loadSessionContext();
        checkAuthOverlay();
        populateCompanySwitcher();
        await RoomFlowSync.processSyncQueue();
    }, 500);
});

function populateCompanySwitcher() {
    const switcher = document.getElementById('header-company-switcher');
    const switcherMore = document.getElementById('more-company-switcher');

    if (switcher) {
        if (!state.sessionUser || state.userOrganizations.length === 0) {
            switcher.innerHTML = `<option value="">No Companies</option>`;
        } else {
            let html = '';
            state.userOrganizations.forEach(o => {
                const selected = (state.currentOrganization && state.currentOrganization.id === o.id) ? 'selected' : '';
                html += `<option value="${o.id}" ${selected}>${o.name} (${o.role})</option>`;
            });
            switcher.innerHTML = html;
        }
    }

    if (switcherMore) {
        if (!state.sessionUser || state.userOrganizations.length === 0) {
            switcherMore.innerHTML = `<option value="">No Companies</option>`;
        } else {
            let html = '';
            state.userOrganizations.forEach(o => {
                const selected = (state.currentOrganization && state.currentOrganization.id === o.id) ? 'selected' : '';
                html += `<option value="${o.id}" ${selected}>${o.name} (${o.role})</option>`;
            });
            switcherMore.innerHTML = html;
        }
    }
}

