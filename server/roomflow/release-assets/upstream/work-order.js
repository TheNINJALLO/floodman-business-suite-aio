// --- ROOMFLOW WORK-ORDER PACKET GENERATOR SYSTEM ---

window.RoomFlowWorkOrder = {
    // Open a visual builder modal populated with the current job state
    openBuilder() {
        if (!state.currentJobName) {
            alert("Please start or select a job first.");
            return;
        }

        // Verify permission
        if (typeof window.hasCapability === 'function' && !window.hasCapability('generate_work_orders')) {
            alert("Access Denied: You do not have permission to generate work orders.");
            return;
        }

        // Create or show modal
        let modal = document.getElementById('work-order-builder-modal');
        if (!modal) {
            modal = this.createBuilderModalHTML();
            document.body.appendChild(modal);
        }

        modal.classList.remove('hidden');
        this.populateBuilderForm();
    },

    createBuilderModalHTML() {
        const div = document.createElement('div');
        div.id = 'work-order-builder-modal';
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
            <div style="background: #111827; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; width: 100%; max-width: 680px; max-height: calc(100vh - 3rem); display: flex; flex-direction: column; box-shadow: var(--shadow-2xl);">
                <div style="padding: 1.5rem; border-bottom: 1px solid rgba(255, 255, 255, 0.08); display: flex; justify-content: space-between; align-items: center;">
                    <h3 style="font-size: 1.25rem; font-weight: 700; color: white; display: flex; align-items: center; gap: 0.5rem;"><i data-lucide="printer"></i> Work-Order Packet Builder</h3>
                    <button onclick="document.getElementById('work-order-builder-modal').classList.add('hidden')" style="background: transparent; border: none; color: #cbd5e1; cursor: pointer;"><i data-lucide="x"></i></button>
                </div>
                
                <div id="wo-builder-body" style="padding: 1.5rem; overflow-y: auto; display: flex; flex-direction: column; gap: 1.25rem;">
                    <!-- Form fields -->
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                        <div style="display:flex; flex-direction:column; gap:0.25rem;">
                            <label style="font-size:0.75rem; font-weight:700; color:#cbd5e1; text-transform:uppercase;">Assigned Crew / Group</label>
                            <input type="text" id="wo-assigned-crew" value="Crew Alpha" style="background:#1f2937; border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:0.5rem; color:white; font-size:0.85rem;">
                        </div>
                        <div style="display:flex; flex-direction:column; gap:0.25rem;">
                            <label style="font-size:0.75rem; font-weight:700; color:#cbd5e1; text-transform:uppercase;">Planned Start Date</label>
                            <input type="date" id="wo-start-date" style="background:#1f2937; border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:0.5rem; color:white; font-size:0.85rem;">
                        </div>
                        <div style="display:flex; flex-direction:column; gap:0.25rem;">
                            <label style="font-size:0.75rem; font-weight:700; color:#cbd5e1; text-transform:uppercase;">Expected Duration</label>
                            <input type="text" id="wo-duration" value="2 Days" style="background:#1f2937; border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:0.5rem; color:white; font-size:0.85rem;">
                        </div>
                        <div style="display:flex; flex-direction:column; gap:0.25rem;">
                            <label style="font-size:0.75rem; font-weight:700; color:#cbd5e1; text-transform:uppercase;">Project Manager</label>
                            <input type="text" id="wo-pm" value="${state.costing?.estimator || ''}" style="background:#1f2937; border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:0.5rem; color:white; font-size:0.85rem;">
                        </div>
                    </div>
                    
                    <div style="display:flex; flex-direction:column; gap:0.25rem;">
                        <label style="font-size:0.75rem; font-weight:700; color:#cbd5e1; text-transform:uppercase;">General Safety Instructions</label>
                        <textarea id="wo-safety-instructions" style="background:#1f2937; border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:0.5rem; color:white; font-size:0.85rem; height:60px;">Wear dust masks and eye protection when cutting drywall. Ensure sump pump discharge line is fully routed to the exterior. Inspect structural supports before post load-bearing adjustment.</textarea>
                    </div>

                    <div style="display:flex; flex-direction:column; gap:0.25rem;">
                        <label style="font-size:0.75rem; font-weight:700; color:#cbd5e1; text-transform:uppercase;">Parking & Access Instructions</label>
                        <textarea id="wo-parking-instructions" style="background:#1f2937; border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:0.5rem; color:white; font-size:0.85rem; height:50px;">Park on the driveway, do not block mailboxes. Basement entry is through the bulk head stairs on the north side.</textarea>
                    </div>
                    
                    <div style="border-top:1px solid rgba(255,255,255,0.08); padding-top:1rem;">
                        <h4 style="font-size:0.9rem; font-weight:700; color:white; margin-bottom:0.5rem;">Select Rooms to Include</h4>
                        <div id="wo-builder-rooms-list" style="display:flex; flex-direction:column; gap:0.5rem;">
                            <!-- Room checkboxes populated dynamically -->
                        </div>
                    </div>
                </div>
                
                <div style="padding: 1.5rem; border-top: 1px solid rgba(255, 255, 255, 0.08); display: flex; justify-content: flex-end; gap: 0.75rem; background: #0f172a; border-bottom-left-radius:12px; border-bottom-right-radius:12px;">
                    <button onclick="document.getElementById('work-order-builder-modal').classList.add('hidden')" class="btn-secondary" style="padding: 0.5rem 1rem;">Cancel</button>
                    <button onclick="window.RoomFlowWorkOrder.printPacket()" class="btn-primary" style="padding: 0.5rem 1.5rem; display:flex; align-items:center; gap:0.25rem;"><i data-lucide="printer" style="width:14px; height:14px;"></i> Generate & Print</button>
                </div>
            </div>
        `;
        if (window.lucide) window.lucide.createIcons();
        return div;
    },

    populateBuilderForm() {
        const list = document.getElementById('wo-builder-rooms-list');
        if (!list) return;

        if (!state.rooms || state.rooms.length === 0) {
            list.innerHTML = `<span style="font-size:0.8rem; color:#64748b;">No rooms added to this project.</span>`;
            return;
        }

        let html = '';
        state.rooms.forEach(r => {
            const width = Number(r.w) || 0;
            const length = Number(r.l) || 0;
            html += `
                <label style="display:flex; align-items:center; gap:0.5rem; color:white; font-size:0.85rem; cursor:pointer;">
                    <input type="checkbox" name="wo-rooms" value="${r.id}" checked style="width:16px; height:16px;">
                    <span>${r.name} (${r.levelId}) - ${width.toFixed(1)} x ${length.toFixed(1)} ft</span>
                </label>
            `;
        });
        list.innerHTML = html;
        
        // Default planned date to today
        const dateInput = document.getElementById('wo-start-date');
        if (dateInput) {
            dateInput.value = new Date().toISOString().split('T')[0];
        }
    },

    // Build the formatted HTML print window
    async printPacket() {
        const crew = document.getElementById('wo-assigned-crew').value.trim();
        const date = document.getElementById('wo-start-date').value;
        const duration = document.getElementById('wo-duration').value.trim();
        const pm = document.getElementById('wo-pm').value.trim();
        const safety = document.getElementById('wo-safety-instructions').value.trim();
        const parking = document.getElementById('wo-parking-instructions').value.trim();
        
        const checkedRooms = Array.from(document.querySelectorAll('input[name="wo-rooms"]:checked')).map(el => el.value);
        if (checkedRooms.length === 0) {
            alert("Please select at least one room to include in the packet.");
            return;
        }

        // Hide config builder modal
        document.getElementById('work-order-builder-modal').classList.add('hidden');

        // Grab layout 2D screenshot
        let blueprint2D = '';
        const rawCanvas = document.getElementById('sketch-canvas');
        if (rawCanvas) {
            try {
                blueprint2D = rawCanvas.toDataURL('image/png');
            } catch(e) {
                console.warn("Canvas capture blocked:", e);
            }
        }

        // Open print tab window
        const win = window.open('', '_blank');
        if (!win) {
            alert("Pop-up blocker active. Please allow popups to view printable packet.");
            return;
        }

        const companyName = state.currentOrganization ? state.currentOrganization.name : 'RoomFlow Contracting';
        const companyAddr = state.currentOrganization?.address || '100 Main St, Grand Rapids, MI';
        const companyPhone = state.currentOrganization?.phone || '(616) 555-0199';
        
        const documentModel = window.RoomFlowDocuments ? window.RoomFlowDocuments.buildModel() : null;
        const customer = documentModel ? documentModel.customer : {
            name: state.costing?.customerName || state.currentJobName,
            address: state.costing?.customerAddress || 'No address specified'
        };
        
        let roomHTML = '';
        state.rooms.forEach(r => {
            if (!checkedRooms.includes(r.id)) return;
            
            // Build plain language tasks for this specific room
            const instructions = generateRoomWorkInstructions(r);
            const roomWidth = Number(r.w) || 0;
            const roomLength = Number(r.l) || 0;
            const roomHeight = Number(r.h) || 8;
            const floorArea = r.type === 'custom' && r.vertices && r.vertices.length >= 3
                ? getPolygonArea(r.vertices)
                : roomWidth * roomLength;
            const perimeter = r.type === 'custom' && r.vertices && r.vertices.length >= 3
                ? getPolygonPerimeter(r.vertices)
                : (roomWidth + roomLength) * 2;

            roomHTML += `
                <div class="page-break-before room-section" style="padding-top: 1rem;">
                    <div style="display:flex; justify-content:space-between; align-items:center; border-bottom: 2px solid #000; padding-bottom: 0.25rem; margin-bottom: 1rem;">
                        <h2 style="margin:0; font-size:1.4rem; text-transform:uppercase;">Room Instruction: ${r.name}</h2>
                        <span style="font-weight:700; font-size:0.9rem;">Level: ${r.levelId.toUpperCase()}</span>
                    </div>
                    
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:1.5rem; margin-bottom:1rem; font-size:0.9rem;">
                        <div>
                            <strong>Physical Dimensions:</strong> ${roomWidth.toFixed(1)} x ${roomLength.toFixed(1)} ft bounding area (Height ${roomHeight} ft)<br>
                            <strong>Floor Area:</strong> ${Math.round(floorArea)} sq ft<br>
                            <strong>Wall Perimeter:</strong> ${Math.round(perimeter)} ft<br>
                            <strong>Wall Layout:</strong> ${getRoomWallStatus(r)}
                        </div>
                        <div>
                            <strong>Room Notes:</strong> ${r.notes || 'No custom layout comments entered.'}
                        </div>
                    </div>
                    
                    <h3 style="font-size:1.1rem; border-bottom:1px solid #ddd; padding-bottom:0.15rem; margin-top:1.5rem;">Required Scope & Work Instructions</h3>
                    <ul style="padding-left:1.25rem; line-height:1.6; font-size:0.95rem;">
                        ${instructions.map(inst => `
                            <li style="margin-bottom:0.5rem; display:flex; gap:0.5rem; align-items:flex-start;">
                                <input type="checkbox" style="width:16px; height:16px; margin-top:3px;">
                                <span>${inst}</span>
                            </li>
                        `).join('')}
                    </ul>

                    <div style="margin-top: 2rem; border:1px dashed #64748b; border-radius:6px; padding:1rem; background:#fafafa;">
                        <label style="font-size:0.75rem; font-weight:700; color:#475569; text-transform:uppercase;">Crew Field Progress Comments</label>
                        <div style="height:100px; border-bottom:1px solid #ccc; margin-top:2rem;"></div>
                        <div style="display:flex; justify-content:space-between; font-size:0.8rem; color:#475569; margin-top:1rem;">
                            <span>Lead Sign-off: _______________________</span>
                            <span>Date: _______________</span>
                        </div>
                    </div>
                </div>
            `;
        });

        const docHTML = `
            <!DOCTYPE html>
            <html>
            <head>
                <title>Work Order - ${state.currentJobName}</title>
                <style>
                    body {
                        font-family: 'Outfit', sans-serif;
                        color: #000;
                        background: #fff;
                        margin: 0;
                        padding: 1.5cm;
                        line-height: 1.4;
                    }
                    h1, h2, h3, h4 {
                        margin-top: 0;
                        color: #000;
                    }
                    table {
                        width: 100%;
                        border-collapse: collapse;
                        margin-bottom: 1.5rem;
                    }
                    th {
                        background: #f1f5f9;
                        text-align: left;
                        font-weight: 700;
                    }
                    th, td {
                        border: 1px solid #cbd5e1;
                        padding: 0.5rem 0.75rem;
                        font-size: 0.85rem;
                    }
                    .page-break-before {
                        page-break-before: always;
                    }
                    .header-banner {
                        display: flex;
                        justify-content: space-between;
                        border-bottom: 4px solid #000;
                        padding-bottom: 1rem;
                        margin-bottom: 2rem;
                    }
                    @media print {
                        body {
                            padding: 0;
                        }
                        .no-print {
                            display: none;
                        }
                    }
                </style>
            </head>
            <body>
                <div class="no-print" style="position:fixed; top:10px; right:10px; background:#1e293b; color:white; padding:0.5rem 1rem; border-radius:6px; cursor:pointer; font-weight:bold; box-shadow:0 4px 6px -1px rgba(0,0,0,0.1);" onclick="window.print()">
                    🖨 Click to Print / Save PDF
                </div>

                <!-- Cover Page -->
                <div class="header-banner">
                    <div>
                        <h2 style="margin:0; font-size:1.8rem; font-weight:700;">${companyName}</h2>
                        <p style="margin:0.25rem 0 0 0; font-size:0.85rem; color:#475569;">${companyAddr} | Tel: ${companyPhone}</p>
                    </div>
                    <div style="text-align:right;">
                        <h1 style="margin:0; font-size:2rem; letter-spacing:0.02em;">WORK ORDER</h1>
                        <span style="font-size:0.9rem; font-weight:bold;">Job: ${state.currentJobName}</span>
                    </div>
                </div>

                <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 2rem; margin-bottom: 2rem;">
                    <div style="border:1px solid #ddd; padding:1.25rem; border-radius:8px;">
                        <h3 style="border-bottom:1px solid #ccc; padding-bottom:0.25rem; font-size:1rem; text-transform:uppercase;">Project Details</h3>
                        <p style="font-size:0.9rem; line-height:1.6; margin:0;">
                            <strong>Customer Name:</strong> ${customer.name}<br>
                            <strong>Job-Site Address:</strong> ${customer.address}<br>
                            <strong>PM:</strong> ${pm}<br>
                            <strong>Assigned Crew:</strong> ${crew}
                        </p>
                    </div>
                    
                    <div style="border:1px solid #ddd; padding:1.25rem; border-radius:8px;">
                        <h3 style="border-bottom:1px solid #ccc; padding-bottom:0.25rem; font-size:1rem; text-transform:uppercase;">Scheduling</h3>
                        <p style="font-size:0.9rem; line-height:1.6; margin:0;">
                            <strong>Planned Start Date:</strong> ${date || 'TBD'}<br>
                            <strong>Expected Duration:</strong> ${duration}<br>
                            <strong>Status:</strong> Ready for Production
                        </p>
                    </div>
                </div>

                <div style="margin-bottom: 2rem;">
                    <h3 style="border-bottom:2px solid #000; padding-bottom:0.25rem; font-size:1rem; text-transform:uppercase;">Access & Parking Notes</h3>
                    <p style="font-size:0.9rem; line-height:1.5; margin:0.25rem 0 0 0;">${parking}</p>
                </div>

                <div style="margin-bottom: 2.5rem;">
                    <h3 style="border-bottom:2px solid #000; padding-bottom:0.25rem; font-size:1rem; text-transform:uppercase;">General Safety Rules</h3>
                    <p style="font-size:0.9rem; line-height:1.5; margin:0.25rem 0 0 0;">${safety}</p>
                </div>

                ${blueprint2D ? `
                    <div style="text-align:center; margin-bottom: 2rem;">
                        <h3 style="border-bottom:2px solid #000; padding-bottom:0.25rem; font-size:1rem; text-transform:uppercase; text-align:left; margin-bottom:1rem;">2D Floor-Plan Blueprint</h3>
                        <img src="${blueprint2D}" style="max-width:100%; max-height:380px; border:1px solid #cbd5e1; border-radius:6px; padding:0.5rem;" />
                    </div>
                ` : ''}

                <!-- Project Materials List Page -->
                <div class="page-break-before">
                    <h2 style="border-bottom: 2px solid #000; padding-bottom: 0.25rem; margin-bottom: 1.5rem; text-transform:uppercase; font-size:1.3rem;">Calculated Material Quantities Sheets</h2>
                    <p style="font-size:0.85rem; color:#475569; margin-bottom:1rem;">Deliver the following calculated packages to the site. All prices have been masked.</p>
                    
                    <table>
                        <thead>
                            <tr>
                                <th style="width: 40%;">Material Description</th>
                                <th style="width: 25%;">Required Count</th>
                                <th style="width: 35%;">Category Placement</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${(documentModel ? documentModel.workOrderItems : []).map(item => {
                                if (!(item.qty > 0)) return '';
                                return `
                                    <tr>
                                        <td><strong>${item.name}</strong>${item.notes ? `<br><small>${item.notes}</small>` : ''}</td>
                                        <td>${Number(item.qty).toFixed(2).replace(/\.00$/, '')} ${item.unit || 'ea'}</td>
                                        <td>${item.roomId ? ((state.rooms.find(room => room.id === item.roomId) || {}).name || 'Assigned room') : 'Whole project'}</td>
                                    </tr>
                                `;
                            }).join('')}
                        </tbody>
                    </table>
                </div>

                <!-- Room Detailed sections -->
                ${roomHTML}
            </body>
            </html>
        `;

        win.document.open();
        win.document.write(docHTML);
        win.document.close();
    }
};

function getRoomWallStatus(room) {
    const walls = (state.walls || []).filter(w => w.primaryRoomId === room.id || w.secondaryRoomId === room.id);
    const descriptions = [];
    
    walls.forEach(w => {
        let side = 'wall';
        const mx = (w.x1 + w.x2) / 2;
        const my = (w.y1 + w.y2) / 2;
        
        const rx = room.x + room.w / 2;
        const ry = room.y + room.l / 2;
        
        const dx = mx - rx;
        const dy = my - ry;
        
        if (Math.abs(dx) > Math.abs(dy)) {
            side = dx > 0 ? 'East Wall' : 'West Wall';
        } else {
            side = dy > 0 ? 'South Wall' : 'North Wall';
        }
        
        if (w.secondaryRoomId) {
            const otherId = w.primaryRoomId === room.id ? w.secondaryRoomId : w.primaryRoomId;
            const other = state.rooms.find(o => o.id === otherId);
            const otherName = other ? other.name : 'Adjacent Room';
            descriptions.push(`${side} (shared with ${otherName})`);
        } else {
            descriptions.push(`${side} (exterior)`);
        }
    });
    
    return descriptions.length > 0 ? descriptions.join(', ') : 'No defined wall segments.';
}

// Plain text instructions builder matching costing items
function generateRoomWorkInstructions(r) {
    const list = window.RoomFlowDocuments
        ? window.RoomFlowDocuments.roomScope(r)
        : [];
    const documentModel = window.RoomFlowDocuments ? window.RoomFlowDocuments.buildModel() : null;
    if (documentModel) {
        documentModel.workOrderItems
            .filter(item => item.roomId === r.id)
            .forEach(item => {
                const quantity = Number(item.qty).toFixed(2).replace(/\.00$/, '');
                list.push(`Complete ${item.name}: ${quantity} ${item.unit || 'ea'}${item.notes ? ` — ${item.notes}` : ''}.`);
            });
    }

    // Default room instruction if no scope matches
    if (list.length === 0) {
        list.push("Validate field measurements and confirm the room is ready for the approved project scope.");
    }

    return list;
}

window.addEventListener('load', () => {
    const woBtn = document.getElementById('btn-create-work-order');
    if (woBtn) {
        woBtn.addEventListener('click', () => {
            window.RoomFlowWorkOrder.openBuilder();
        });
    }
});
