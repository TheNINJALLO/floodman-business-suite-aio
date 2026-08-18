// --- ROOMFLOW LEGACY ESTIMATES DATA MIGRATION ENGINE ---

window.RoomFlowMigration = {
    upgradeLegacyJob(job) {
        if (!job) return job;
        if (!job.rooms) job.rooms = [];
        if (!job.walls) job.walls = [];
        if (!job.roomConnections) job.roomConnections = [];
        if (!job.doors) job.doors = [];
        if (!job.windows) job.windows = [];
        if (!job.openings) job.openings = [];

        const oldRooms = state.rooms;
        const oldWalls = state.walls;
        const oldConnections = state.roomConnections;
        const oldDoors = state.doors;
        const oldWindows = state.windows;
        const oldOpenings = state.openings;
        const oldLevel = state.currentLevelId;

        state.rooms = job.rooms;
        state.walls = [];
        state.roomConnections = [];
        state.doors = [];
        state.windows = [];
        state.openings = [];
        state.currentLevelId = job.currentLevelId || 'basement';

        job.rooms.forEach(r => {
            if (Array.isArray(r.openings)) {
                r.openings.forEach(op => {
                    let side = op.wall || 'n';
                    let offset = op.offset || 3.0;
                    let width = op.w || 3.0;
                    const dummyWallId = 'wall_' + r.id + '_' + side + '_dummy';
                    if (op.type === 'window') {
                        state.windows.push({
                            id: op.id || 'win_' + Math.random().toString(36).substr(2, 9),
                            levelId: state.currentLevelId,
                            hostWallId: dummyWallId,
                            roomId: r.id,
                            w: width,
                            h: op.h || 4.0,
                            sillHeight: 3.0,
                            offset: offset,
                            type: 'standard'
                        });
                    } else {
                        state.doors.push({
                            id: op.id || 'door_' + Math.random().toString(36).substr(2, 9),
                            levelId: state.currentLevelId,
                            hostWallId: dummyWallId,
                            roomA: r.id,
                            roomB: null,
                            w: width,
                            h: op.h || 6.8,
                            offset: offset,
                            hingeSide: 'left',
                            swingDirection: 'in',
                            type: 'interior'
                        });
                    }
                });
            }
        });

        if (typeof window.rebuildLogicalLayout === 'function') {
            window.rebuildLogicalLayout();
        }

        (state.doors || []).forEach(d => {
            if (d.hostWallId && d.hostWallId.endsWith('_dummy')) {
                const actualWall = (state.walls || []).find(w => w.primaryRoomId === d.roomA || w.secondaryRoomId === d.roomA);
                if (actualWall) {
                    d.hostWallId = actualWall.id;
                }
            }
        });
        (state.windows || []).forEach(win => {
            if (win.hostWallId && win.hostWallId.endsWith('_dummy')) {
                const actualWall = (state.walls || []).find(w => w.primaryRoomId === win.roomId);
                if (actualWall) {
                    win.hostWallId = actualWall.id;
                }
            }
        });

        job.walls = state.walls;
        job.roomConnections = state.roomConnections;
        job.doors = state.doors;
        job.windows = state.windows;
        job.openings = state.openings;

        state.rooms = oldRooms;
        state.walls = oldWalls;
        state.roomConnections = oldConnections;
        state.doors = oldDoors;
        state.windows = oldWindows;
        state.openings = oldOpenings;
        state.currentLevelId = oldLevel;

        return job;
    },

    openModal() {
        // Verify active login session
        if (!state.sessionUser) {
            alert("Please sign in to your RoomFlow account before importing legacy data.");
            return;
        }

        let modal = document.getElementById('migration-modal');
        if (!modal) {
            modal = this.createMigrationModalHTML();
            document.body.appendChild(modal);
        }

        modal.classList.remove('hidden');
        this.populateMigrationFields();
    },

    createMigrationModalHTML() {
        const div = document.createElement('div');
        div.id = 'migration-modal';
        div.className = 'modal hidden';
        div.style.position = 'fixed';
        div.style.top = '0';
        div.style.left = '0';
        div.style.width = '100%';
        div.style.height = '100%';
        div.style.background = 'rgba(15, 23, 42, 0.8)';
        div.style.zIndex = '9999';
        div.style.display = 'flex';
        div.style.alignItems = 'center';
        div.style.justifyContent = 'center';
        div.style.padding = '1.5rem';

        div.innerHTML = `
            <div style="background: #111827; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; width: 100%; max-width: 580px; max-height: calc(100vh - 3rem); display: flex; flex-direction: column; box-shadow: var(--shadow-2xl);">
                <div style="padding: 1.5rem; border-bottom: 1px solid rgba(255, 255, 255, 0.08); display: flex; justify-content: space-between; align-items: center;">
                    <h3 style="font-size: 1.25rem; font-weight: 700; color: white; display: flex; align-items: center; gap: 0.5rem;"><i data-lucide="database-backup"></i> Legacy Estimate Importer</h3>
                    <button onclick="document.getElementById('migration-modal').classList.add('hidden')" style="background: transparent; border: none; color: #cbd5e1; cursor: pointer;"><i data-lucide="x"></i></button>
                </div>
                
                <div style="padding: 1.5rem; overflow-y: auto; display: flex; flex-direction: column; gap: 1.25rem;">
                    <p style="font-size: 0.85rem; color: #cbd5e1; margin: 0;">This utility transfers your local browser estimates to Supabase. This updates both geometry blueprints and costing settings under RLS protection.</p>
                    
                    <div id="migration-status-box" style="display:none; padding:0.75rem 1rem; border-radius:8px; font-size:0.85rem; font-weight:600;"></div>

                    <div style="display:flex; flex-direction:column; gap:0.25rem;">
                        <label style="font-size:0.75rem; font-weight:700; color:#cbd5e1; text-transform:uppercase;">Select Source Local Estimates</label>
                        <div id="migration-source-list" style="display:flex; flex-direction:column; gap:0.5rem; background:rgba(0,0,0,0.2); padding:0.75rem; border-radius:8px; max-height:160px; overflow-y:auto; border:1px solid rgba(255,255,255,0.05);">
                            <!-- Local jobs checkboxes -->
                        </div>
                    </div>

                    <div style="display:flex; flex-direction:column; gap:0.25rem;">
                        <label style="font-size:0.75rem; font-weight:700; color:#cbd5e1; text-transform:uppercase;">Destination Company Organization</label>
                        <select id="migration-target-org" style="background:#1f2937; border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:0.5rem 0.75rem; color:white; font-size:0.85rem;">
                            <!-- Populate dynamic active orgs -->
                        </select>
                    </div>
                </div>
                
                <div style="padding: 1.5rem; border-top: 1px solid rgba(255, 255, 255, 0.08); display: flex; justify-content: flex-end; gap: 0.75rem; background: #0f172a; border-bottom-left-radius:12px; border-bottom-right-radius:12px;">
                    <button onclick="document.getElementById('migration-modal').classList.add('hidden')" class="btn-secondary" style="padding: 0.5rem 1rem;">Cancel</button>
                    <button id="btn-run-migration" class="btn-primary" style="padding: 0.5rem 1.5rem; font-weight:700;"><i data-lucide="refresh-cw" style="width:14px; height:14px; display:inline-block; vertical-align:middle; margin-right:2px;"></i> Start Migration</button>
                </div>
            </div>
        `;
        if (window.lucide) window.lucide.createIcons();
        return div;
    },

    populateMigrationFields() {
        const list = document.getElementById('migration-source-list');
        const switcher = document.getElementById('migration-target-org');
        if (!list || !switcher) return;

        // Load local browser storage estimates
        let localJobs = {};
        try {
            const stored = localStorage.getItem('roomflow_jobs');
            if (stored) localJobs = JSON.parse(stored);
        } catch (e) {
            console.error(e);
        }

        const keys = Object.keys(localJobs);
        if (keys.length === 0) {
            list.innerHTML = `<span style="font-size:0.8rem; color:#64748b; padding: 1rem 0; text-align:center;">No offline jobs found in local browser storage.</span>`;
        } else {
            let html = '';
            keys.forEach(k => {
                html += `
                    <label style="display:flex; align-items:center; gap:0.5rem; color:white; font-size:0.8rem; cursor:pointer;">
                        <input type="checkbox" name="migration-jobs" value="${k}" checked style="width:14px; height:14px;">
                        <span>${k}</span>
                    </label>
                `;
            });
            list.innerHTML = html;
        }

        // Populate destination company
        let orgHtml = '';
        state.userOrganizations.forEach(o => {
            const selected = (state.currentOrganization && state.currentOrganization.id === o.id) ? 'selected' : '';
            orgHtml += `<option value="${o.id}" ${selected}>${o.name}</option>`;
        });
        switcher.innerHTML = orgHtml;

        // Reset status alert
        const alertBox = document.getElementById('migration-status-box');
        if (alertBox) alertBox.style.display = 'none';
    },

    async execute() {
        const checked = Array.from(document.querySelectorAll('input[name="migration-jobs"]:checked')).map(el => el.value);
        const orgId = document.getElementById('migration-target-org').value;
        const statusBox = document.getElementById('migration-status-box');
        
        if (checked.length === 0) {
            alert("Please select at least one estimate to migrate.");
            return;
        }
        if (!orgId) {
            alert("No destination company organization selected.");
            return;
        }

        statusBox.style.display = 'block';
        statusBox.style.background = 'rgba(245, 158, 11, 0.1)';
        statusBox.style.borderColor = 'rgba(245, 158, 11, 0.2)';
        statusBox.style.color = '#fde047';
        statusBox.innerText = `Migrating ${checked.length} project estimates...`;

        const client = supabase.createClient(RoomFlowConfig.supabaseUrl, RoomFlowConfig.supabaseAnonKey);

        let successCount = 0;
        let duplicateCount = 0;
        let errors = [];

        let localJobs = {};
        try {
            const stored = localStorage.getItem('roomflow_jobs');
            if (stored) localJobs = JSON.parse(stored);
        } catch(e) {}

        for (const name of checked) {
            try {
                const job = localJobs[name];
                if (!job) continue;

                // 1. Identify duplicates
                const { data: duplicateJobs } = await client
                    .from('jobs')
                    .select('id')
                    .eq('organization_id', orgId)
                    .eq('name', name)
                    .limit(1);

                if (duplicateJobs && duplicateJobs.length > 0) {
                    duplicateCount++;
                    continue;
                }

                // 2. Create customer
                const { data: cust, error: custErr } = await client
                    .from('customers')
                    .insert({
                        organization_id: orgId,
                        name: job.customerName || name,
                        phone: job.costing?.customerPhone || '',
                        email: job.costing?.customerEmail || ''
                    })
                    .select('id')
                    .single();

                if (custErr) throw custErr;

                // 3. Create job
                const { data: newJob, error: jobErr } = await client
                    .from('jobs')
                    .insert({
                        organization_id: orgId,
                        customer_id: cust.id,
                        name: name,
                        status: 'Draft',
                        current_version_number: 1
                    })
                    .select('id')
                    .single();

                if (jobErr) throw jobErr;

                // Upgrade to new structural model
                const upgradedJob = RoomFlowMigration.upgradeLegacyJob(job);

                // 4. Create geometry layouts
                const { error: layoutErr } = await client
                    .from('job_layouts')
                    .insert({
                        job_id: newJob.id,
                        version_number: 1,
                        layout_json: {
                            rooms: upgradedJob.rooms,
                            walls: upgradedJob.walls || [],
                            roomConnections: upgradedJob.roomConnections || [],
                            doors: upgradedJob.doors || [],
                            windows: upgradedJob.windows || [],
                            openings: upgradedJob.openings || [],
                            sumpPumps: upgradedJob.sumpPumps,
                            dehumidifiers: upgradedJob.dehumidifiers || [],
                            dischargeLines: upgradedJob.dischargeLines,
                            floorHatches: upgradedJob.floorHatches,
                            interiorPipes: upgradedJob.interiorPipes,
                            stanchions: upgradedJob.stanchions,
                            mainBeams: upgradedJob.mainBeams,
                            capturedMeasurements: upgradedJob.capturedMeasurements
                        }
                    });

                if (layoutErr) throw layoutErr;

                // 5. Create pricing costs configurations (if allowed)
                const showCosting = (typeof window.hasCapability !== 'function' || window.hasCapability('view_internal_costs'));
                if (showCosting && job.costing) {
                    const { error: priceErr } = await client
                        .from('job_pricing')
                        .insert({
                            job_id: newJob.id,
                            target_gross_margin: job.costing.settings?.targetGrossMargin || 40.0,
                            sales_tax_rate: job.costing.settings?.salesTaxRate || 6.0,
                            additional_overhead_rate: job.costing.settings?.overhead || 15.0,
                            commission_rate: job.costing.commission || 0.0
                        });
                    if (priceErr) throw priceErr;
                }

                successCount++;
            } catch (err) {
                errors.push(`${name}: ${err.message}`);
            }
        }

        // Produce migration report
        statusBox.style.background = 'rgba(16, 185, 129, 0.1)';
        statusBox.style.borderColor = 'rgba(16, 185, 129, 0.2)';
        statusBox.style.color = '#a7f3d0';
        
        let report = `Migration Complete!\n- Successfully imported: ${successCount}\n- Skipped duplicates: ${duplicateCount}`;
        if (errors.length > 0) {
            report += `\n- Errors encountered: ${errors.length}\n  ${errors.slice(0, 3).join('\n  ')}`;
        }
        statusBox.innerText = report;

        // Reload dashboard
        if (typeof window.renderJobsList === 'function') window.renderJobsList();
    }
};

window.addEventListener('load', () => {
    const showMigBtn = document.getElementById('btn-show-migration-modal');
    if (showMigBtn) {
        showMigBtn.addEventListener('click', () => {
            window.RoomFlowMigration.openModal();
        });
    }

    const runMigBtn = document.getElementById('btn-run-migration');
    if (runMigBtn) {
        runMigBtn.addEventListener('click', () => {
            window.RoomFlowMigration.execute();
        });
    }
});
