// --- ROOMFLOW UNIFIED PROPOSAL / INVOICE / WORK-ORDER WORKFLOW ---
(function () {
    'use strict';

    const DEFAULTS = {
        proposalNumber: '',
        invoiceNumber: '',
        invoiceStatus: 'Draft',
        dueDate: '',
        paymentTerms: 'Due within 30 days',
        depositPaid: 0,
        notes: '',
        includeCustomerInfo: true,
        includeBlueprint: true,
        showItemizedPricing: true,
        includeTotalPricing: true,
        itemVisibility: {}
    };

    function escapeHTML(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function money(value) {
        const number = Number(value) || 0;
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD'
        }).format(number);
    }

    function number(value, fallback = 0) {
        const parsed = parseFloat(value);
        return Number.isFinite(parsed) ? parsed : fallback;
    }

    function ensureSettings() {
        if (typeof initDefaultCosting === 'function') initDefaultCosting(state);
        if (!state.costing.documents) state.costing.documents = {};
        Object.keys(DEFAULTS).forEach(key => {
            if (state.costing.documents[key] === undefined) {
                state.costing.documents[key] = JSON.parse(JSON.stringify(DEFAULTS[key]));
            }
        });
        if (!state.costing.documents.proposalNumber) {
            state.costing.documents.proposalNumber = `P-${String(state.jobId || Date.now()).replace(/[^a-z0-9]/gi, '').slice(-8).toUpperCase()}`;
        }
        if (!state.costing.documents.invoiceNumber) {
            state.costing.documents.invoiceNumber = `INV-${String(state.jobId || Date.now()).replace(/[^a-z0-9]/gi, '').slice(-8).toUpperCase()}`;
        }
        if (!state.costing.documents.dueDate) {
            const due = new Date();
            due.setDate(due.getDate() + 30);
            state.costing.documents.dueDate = due.toISOString().slice(0, 10);
        }
        return state.costing.documents;
    }

    function persist() {
        state.updatedTimestamp = Date.now();
        if (typeof window.triggerAutosave === 'function') window.triggerAutosave();
        else if (typeof window.autosaveJob === 'function') window.autosaveJob();
    }

    function customerModel() {
        const costing = state.costing || {};
        const sidebarName = document.getElementById('customer-name');
        const sidebarAddress = document.getElementById('customer-address');
        return {
            name: costing.customerName || (sidebarName ? sidebarName.value : '') || state.currentJobName || 'Customer',
            address: costing.customerAddress || (sidebarAddress ? sidebarAddress.value : '') || 'Address not provided',
            phone: costing.customerPhone || '',
            email: costing.customerEmail || '',
            estimator: costing.estimator || '',
            inspectionDate: costing.inspectionDate || ''
        };
    }

    function itemVisibility(id) {
        const settings = ensureSettings();
        const saved = settings.itemVisibility[id] || {};
        return {
            proposal: saved.proposal !== false,
            workOrder: saved.workOrder !== false
        };
    }

    function addItem(items, item) {
        if (!(item.qty > 0) || item.excluded) return;
        const visibility = itemVisibility(item.id);
        items.push(Object.assign({
            unit: 'ea',
            rawCost: 0,
            notes: '',
            source: 'Estimate',
            roomId: '',
            manualUnitPrice: null,
            includeProposal: visibility.proposal,
            includeWorkOrder: visibility.workOrder
        }, item));
    }

    function getLineItems() {
        ensureSettings();
        const catalog = RoomFlowCatalog.loadCatalog();
        const report = calculateProjectCosts(state, catalog);
        const items = [];

        Object.keys(report.items || {}).forEach(id => {
            const entry = report.items[id];
            if (!entry || entry.excluded || !(entry.purchaseQty > 0)) return;
            addItem(items, {
                id: `catalog:${id}`,
                name: entry.data.name || id,
                notes: entry.data.notes || '',
                qty: number(entry.purchaseQty),
                unit: entry.data.purchaseUnit || 'ea',
                rawCost: number(entry.cost),
                source: 'Calculated estimate'
            });
        });

        const rentals = state.costing.rentals || {};
        const rentalRows = [
            ['rental:dehumidifier', 'Dehumidifier rental', rentals.dehumidifierUnits, rentals.dehumidifierDays, 100, rentals.dehumidifierNotes],
            ['rental:air-mover', 'Air mover rental', rentals.airMoverUnits, rentals.airMoverDays, 38, rentals.airMoverNotes],
            ['rental:air-scrubber', 'Air scrubber rental', rentals.airScrubberUnits, rentals.airScrubberDays, 105, rentals.airScrubberNotes]
        ];
        rentalRows.forEach(row => {
            const units = Math.max(0, number(row[2]));
            const days = Math.max(0, number(row[3]));
            addItem(items, {
                id: row[0],
                name: row[1],
                qty: units * days,
                unit: 'unit-day',
                rawCost: units * days * row[4],
                notes: row[5] || `${units} unit(s) for ${days} day(s)`,
                source: 'Rental'
            });
        });
        (rentals.optionalCharges || []).forEach((charge, index) => {
            addItem(items, {
                id: `rental:optional:${charge.id || index}`,
                name: charge.description || 'Additional rental charge',
                qty: Math.max(0, number(charge.qty)),
                unit: charge.unit || 'ea',
                rawCost: Math.max(0, number(charge.qty)) * Math.max(0, number(charge.rate)),
                notes: charge.notes || '',
                source: 'Rental'
            });
        });

        (state.costing.customItems || []).forEach((custom, index) => {
            if (!custom.id) custom.id = `scope_${Date.now()}_${index}`;
            const qty = Math.max(0, number(custom.qty));
            const waste = 1 + Math.max(0, number(custom.waste)) / 100;
            const materialCost = qty * Math.max(0, number(custom.unitCost)) * waste;
            const laborCost = Math.max(0, number(custom.laborHours)) * Math.max(0, number(custom.laborRate));
            addItem(items, {
                id: `custom:${custom.id}`,
                name: custom.name || 'Custom scope item',
                qty,
                unit: custom.unit || 'ea',
                rawCost: materialCost + laborCost,
                notes: custom.notes || '',
                source: custom.documentOnly ? 'Added in documents' : 'Custom estimate item',
                roomId: custom.roomId || '',
                manualUnitPrice: number(custom.customerUnitPrice) > 0 ? number(custom.customerUnitPrice) : null
            });
        });

        if (report.subtotals.labor > 0) {
            const visibility = itemVisibility('labor:project');
            items.push({
                id: 'labor:project',
                name: 'Project labor and installation',
                qty: Math.max(1, number(report.laborHours, 1)),
                unit: report.laborHours > 0 ? 'hr' : 'project',
                rawCost: number(report.subtotals.labor),
                notes: (state.costing.labor && state.costing.labor.projectNotes) || 'Professional installation services',
                source: 'Labor',
                roomId: '',
                manualUnitPrice: null,
                includeProposal: visibility.proposal,
                includeWorkOrder: false
            });
        }

        const manualDocumentTotal = (state.costing.customItems || []).reduce((sum, custom) => {
            if (!custom.documentOnly) return sum;
            return sum + Math.max(0, number(custom.qty)) * Math.max(0, number(custom.customerUnitPrice));
        }, 0);
        const targetSellingPrice = Math.max(0, number(report.subtotals.sellingPrice)) + manualDocumentTotal;
        const manualTotal = items.reduce((sum, item) => {
            return sum + (item.manualUnitPrice == null ? 0 : item.manualUnitPrice * item.qty);
        }, 0);
        const autoRawTotal = items.reduce((sum, item) => {
            return sum + (item.manualUnitPrice == null ? Math.max(0, item.rawCost) : 0);
        }, 0);
        const autoTarget = Math.max(0, targetSellingPrice - manualTotal);
        const multiplier = autoRawTotal > 0 ? autoTarget / autoRawTotal : 0;

        items.forEach(item => {
            item.unitPrice = item.manualUnitPrice == null
                ? (item.qty > 0 ? (item.rawCost * multiplier) / item.qty : 0)
                : item.manualUnitPrice;
            item.total = item.unitPrice * item.qty;
        });

        return { report, items, targetSellingPrice };
    }

    function buildModel() {
        const settings = ensureSettings();
        const customer = customerModel();
        const data = getLineItems();
        const proposalItems = data.items.filter(item => item.includeProposal);
        const workOrderItems = data.items.filter(item => item.includeWorkOrder);
        return {
            settings,
            customer,
            report: data.report,
            items: data.items,
            proposalItems,
            workOrderItems,
            proposalTotal: proposalItems.reduce((sum, item) => sum + item.total, 0),
            rooms: state.rooms || [],
            jobName: state.currentJobName || 'Untitled job'
        };
    }

    function wallName(room, key) {
        const labels = { n: 'North wall', e: 'East wall', s: 'South wall', w: 'West wall' };
        return labels[key] || `Wall ${parseInt(key, 10) + 1}`;
    }

    function roomScope(room) {
        const tasks = [];
        if (room.drywallHeight && room.drywallHeight !== 'none') {
            const segments = typeof getRoomSegments === 'function' ? getRoomSegments(room) : [];
            const selected = Array.isArray(room.drywallWalls)
                ? segments.filter(segment => room.drywallWalls.includes(String(segment.wall)))
                : segments;
            if (selected.length) {
                tasks.push(`Cut drywall ${room.drywallHeight === 'full' ? 'full height' : `to ${room.drywallHeight}`} on ${selected.map(segment => wallName(room, segment.wall)).join(', ')}.`);
            }
        }
        if (room.nb1Height && room.nb1Height !== 'none') tasks.push(`Apply NB1 coating (${room.nb1Height}) to the specified wall area.`);
        if (room.foamBoard) tasks.push('Install 2-inch XPS foam board at the specified perimeter walls.');
        if (room.foamBondPockets) tasks.push('Apply spray foam at bond pockets.');
        if (room.carbonStraps > 0) tasks.push(`Install ${room.carbonStraps} carbon-fiber reinforcement strap(s) at marked locations.`);
        if (room.floorPerimeterStrap) tasks.push('Install the floor-perimeter carbon-fiber reinforcement.');
        if (room.removeInsulation) tasks.push('Remove damaged attic insulation.');
        if (room.blowInInsulation) tasks.push('Install blow-in attic insulation.');
        (room.openings || []).forEach(opening => {
            tasks.push(`Protect and account for ${opening.type || 'opening'} on ${wallName(room, String(opening.wall))}.`);
        });
        return tasks;
    }

    function renderWorkflow() {
        const model = buildModel();
        const settings = model.settings;
        const roomOptions = model.rooms.map(room => `<option value="${escapeHTML(room.id)}">${escapeHTML(room.name)}</option>`).join('');
        const itemRows = model.items.length ? model.items.map(item => `
            <tr>
                <td data-label="Scope item"><strong>${escapeHTML(item.name)}</strong><small>${escapeHTML(item.source)}${item.notes ? ` · ${escapeHTML(item.notes)}` : ''}</small></td>
                <td data-label="Quantity">${number(item.qty).toFixed(2).replace(/\.00$/, '')} ${escapeHTML(item.unit)}</td>
                <td data-label="Customer price">${money(item.total)}</td>
                <td data-label="Proposal"><input type="checkbox" aria-label="Include ${escapeHTML(item.name)} in proposal and invoice" ${item.includeProposal ? 'checked' : ''} onchange="RoomFlowDocuments.setItemVisibility('${escapeHTML(item.id)}','proposal',this.checked)"></td>
                <td data-label="Work order"><input type="checkbox" aria-label="Include ${escapeHTML(item.name)} in work order" ${item.includeWorkOrder ? 'checked' : ''} onchange="RoomFlowDocuments.setItemVisibility('${escapeHTML(item.id)}','workOrder',this.checked)"></td>
            </tr>
        `).join('') : '<tr><td colspan="5" class="document-empty">No priced scope items yet. Add one below or complete the room scope.</td></tr>';

        return `
            <div class="document-workflow">
                <div class="document-workflow-heading">
                    <div>
                        <span class="document-eyebrow">Final review</span>
                        <h2>Project documents</h2>
                        <p>One shared scope now powers the customer proposal, invoice, and crew work order.</p>
                    </div>
                    <div class="document-total-card"><span>Document total</span><strong>${money(model.proposalTotal)}</strong></div>
                </div>

                <section class="document-step-card">
                    <div class="document-step-number">1</div>
                    <div class="document-step-content">
                        <h3>Confirm customer and job</h3>
                        <div class="document-summary-grid">
                            <div><span>Customer</span><strong>${escapeHTML(model.customer.name)}</strong></div>
                            <div><span>Property</span><strong>${escapeHTML(model.customer.address)}</strong></div>
                            <div><span>Job</span><strong>${escapeHTML(model.jobName)}</strong></div>
                            <div><span>Estimator</span><strong>${escapeHTML(model.customer.estimator || 'Not assigned')}</strong></div>
                        </div>
                    </div>
                </section>

                <section class="document-step-card">
                    <div class="document-step-number">2</div>
                    <div class="document-step-content document-step-wide">
                        <div class="document-section-heading">
                            <div><h3>Review the shared scope</h3><p>Every checked line is carried into the selected documents.</p></div>
                        </div>
                        <div class="document-table-wrap">
                            <table class="document-items-table">
                                <thead><tr><th>Scope item</th><th>Quantity</th><th>Customer price</th><th>Proposal / invoice</th><th>Work order</th></tr></thead>
                                <tbody>${itemRows}</tbody>
                            </table>
                        </div>
                        <details class="document-add-scope">
                            <summary><i data-lucide="plus-circle"></i> Add a scope item here</summary>
                            <div class="document-add-grid">
                                <label><span>Description</span><input id="document-new-name" type="text" placeholder="Permit, disposal, custom repair…"></label>
                                <label><span>Quantity</span><input id="document-new-qty" type="number" min="0" step="0.1" value="1"></label>
                                <label><span>Unit</span><input id="document-new-unit" type="text" value="ea"></label>
                                <label><span>Customer unit price</span><input id="document-new-price" type="number" min="0" step="0.01" placeholder="0.00"></label>
                                <label><span>Assign to room</span><select id="document-new-room"><option value="">Whole project</option>${roomOptions}</select></label>
                                <label class="document-notes-field"><span>Field notes</span><input id="document-new-notes" type="text" placeholder="Instructions that should follow this item"></label>
                            </div>
                            <button type="button" class="btn-primary document-add-button" onclick="RoomFlowDocuments.addScopeItem()"><i data-lucide="plus"></i> Add to all documents</button>
                        </details>
                    </div>
                </section>

                <section class="document-step-card">
                    <div class="document-step-number">3</div>
                    <div class="document-step-content document-step-wide">
                        <h3>Set document details</h3>
                        <div class="document-settings-grid">
                            <label><span>Proposal number</span><input value="${escapeHTML(settings.proposalNumber)}" onchange="RoomFlowDocuments.setSetting('proposalNumber',this.value)"></label>
                            <label><span>Invoice number</span><input value="${escapeHTML(settings.invoiceNumber)}" onchange="RoomFlowDocuments.setSetting('invoiceNumber',this.value)"></label>
                            <label><span>Invoice status</span><select onchange="RoomFlowDocuments.setSetting('invoiceStatus',this.value)">${['Draft','Sent','Partially paid','Paid'].map(status => `<option ${settings.invoiceStatus === status ? 'selected' : ''}>${status}</option>`).join('')}</select></label>
                            <label><span>Due date</span><input type="date" value="${escapeHTML(settings.dueDate)}" onchange="RoomFlowDocuments.setSetting('dueDate',this.value)"></label>
                            <label><span>Deposit received</span><input type="number" min="0" step="0.01" value="${number(settings.depositPaid)}" onchange="RoomFlowDocuments.setSetting('depositPaid',this.value)"></label>
                            <label><span>Payment terms</span><input value="${escapeHTML(settings.paymentTerms)}" onchange="RoomFlowDocuments.setSetting('paymentTerms',this.value)"></label>
                            <label class="document-notes-field"><span>Customer-facing notes</span><textarea onchange="RoomFlowDocuments.setSetting('notes',this.value)">${escapeHTML(settings.notes)}</textarea></label>
                        </div>
                        <div class="document-option-row">
                            <label><input type="checkbox" ${settings.includeCustomerInfo ? 'checked' : ''} onchange="RoomFlowDocuments.setSetting('includeCustomerInfo',this.checked)"> Customer details</label>
                            <label><input type="checkbox" ${settings.includeBlueprint ? 'checked' : ''} onchange="RoomFlowDocuments.setSetting('includeBlueprint',this.checked)"> Blueprint</label>
                            <label><input type="checkbox" ${settings.showItemizedPricing ? 'checked' : ''} onchange="RoomFlowDocuments.setSetting('showItemizedPricing',this.checked)"> Itemized pricing</label>
                            <label><input type="checkbox" ${settings.includeTotalPricing ? 'checked' : ''} onchange="RoomFlowDocuments.setSetting('includeTotalPricing',this.checked)"> Total price</label>
                        </div>
                    </div>
                </section>

                <section class="document-step-card document-output-card">
                    <div class="document-step-number">4</div>
                    <div class="document-step-content document-step-wide">
                        <h3>Create the next document</h3>
                        <div class="document-output-grid">
                            <button type="button" onclick="RoomFlowDocuments.print('proposal')"><i data-lucide="file-text"></i><span><strong>Customer proposal</strong><small>Scope, blueprint, and approved pricing</small></span></button>
                            <button type="button" onclick="RoomFlowDocuments.print('invoice')"><i data-lucide="receipt"></i><span><strong>Invoice</strong><small>Same line items, payment status, and balance</small></span></button>
                            <button type="button" onclick="RoomFlowWorkOrder.openBuilder()"><i data-lucide="clipboard-check"></i><span><strong>Crew work order</strong><small>Room and wall instructions without prices</small></span></button>
                        </div>
                    </div>
                </section>
            </div>
        `;
    }

    function setSetting(key, value) {
        const settings = ensureSettings();
        if (key === 'depositPaid') value = Math.max(0, number(value));
        settings[key] = value;
        persist();
    }

    function setItemVisibility(id, documentType, checked) {
        const settings = ensureSettings();
        if (!settings.itemVisibility[id]) settings.itemVisibility[id] = {};
        settings.itemVisibility[id][documentType] = !!checked;
        persist();
        if (typeof window.renderGuidedStep === 'function' && state.currentStep === 8) window.renderGuidedStep();
    }

    function addScopeItem() {
        const nameInput = document.getElementById('document-new-name');
        const qtyInput = document.getElementById('document-new-qty');
        const unitInput = document.getElementById('document-new-unit');
        const priceInput = document.getElementById('document-new-price');
        const roomInput = document.getElementById('document-new-room');
        const notesInput = document.getElementById('document-new-notes');
        const name = nameInput ? nameInput.value.trim() : '';
        const qty = Math.max(0, number(qtyInput && qtyInput.value));
        const price = Math.max(0, number(priceInput && priceInput.value));
        if (!name || qty <= 0) {
            alert('Enter a description and a quantity greater than zero.');
            return;
        }
        state.costing.customItems.push({
            id: `scope_${Date.now()}`,
            name,
            category: 'other',
            qty,
            unit: (unitInput && unitInput.value.trim()) || 'ea',
            unitCost: 0,
            customerUnitPrice: price,
            waste: 0,
            laborHours: 0,
            laborRate: 0,
            taxable: false,
            includeInOverhead: false,
            includeInMarkup: false,
            includeInProposal: true,
            includeInWorkOrder: true,
            roomId: roomInput ? roomInput.value : '',
            notes: notesInput ? notesInput.value.trim() : '',
            documentOnly: true
        });
        persist();
        if (typeof window.renderGuidedStep === 'function') window.renderGuidedStep();
    }

    function companyModel() {
        const org = state.currentOrganization || {};
        return {
            name: org.name || 'RoomFlow Contracting',
            address: org.address || '',
            phone: org.phone || '',
            email: org.email || ''
        };
    }

    function blueprintImage() {
        const canvas = document.getElementById('sketch-canvas');
        if (!canvas) return '';
        try { return canvas.toDataURL('image/png'); }
        catch (error) { console.warn('Blueprint capture unavailable:', error); return ''; }
    }

    function printableRooms(model) {
        return model.rooms.map(room => {
            const tasks = roomScope(room);
            if (!tasks.length) return '';
            return `<section class="room-scope"><h3>${escapeHTML(room.name)} <span>${escapeHTML(room.levelId || '')}</span></h3><ul>${tasks.map(task => `<li>${escapeHTML(task)}</li>`).join('')}</ul></section>`;
        }).join('');
    }

    function print(kind) {
        const model = buildModel();
        const settings = model.settings;
        const company = companyModel();
        const isInvoice = kind === 'invoice';
        const title = isInvoice ? 'Invoice' : 'Customer Proposal';
        const numberText = isInvoice ? settings.invoiceNumber : settings.proposalNumber;
        const items = model.proposalItems;
        const subtotal = model.proposalTotal;
        const deposit = isInvoice ? Math.min(subtotal, Math.max(0, number(settings.depositPaid))) : 0;
        const balance = Math.max(0, subtotal - deposit);
        const blueprint = settings.includeBlueprint ? blueprintImage() : '';
        const itemRows = items.map(item => `
            <tr><td><strong>${escapeHTML(item.name)}</strong>${item.notes ? `<small>${escapeHTML(item.notes)}</small>` : ''}</td><td>${number(item.qty).toFixed(2).replace(/\.00$/, '')} ${escapeHTML(item.unit)}</td><td>${money(item.unitPrice)}</td><td>${money(item.total)}</td></tr>
        `).join('');
        const win = window.open('', '_blank');
        if (!win) {
            alert('Allow pop-ups for RoomFlow to preview and print documents.');
            return;
        }
        const html = `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHTML(title)} ${escapeHTML(numberText)}</title><style>
            :root{color:#172033;font-family:Arial,sans-serif;font-size:14px}*{box-sizing:border-box}body{margin:0;background:#eef2f7}.page{width:min(960px,100%);margin:24px auto;background:white;padding:48px;box-shadow:0 14px 40px rgba(15,23,42,.14)}header{display:flex;justify-content:space-between;gap:32px;border-bottom:3px solid #172033;padding-bottom:22px}h1{margin:0;font-size:34px;text-transform:uppercase;letter-spacing:.04em}.brand h2{margin:0 0 6px}.muted,small{color:#64748b}.meta{text-align:right}.meta strong{display:block;font-size:17px}.customer{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin:28px 0}.card{border:1px solid #dbe3ec;border-radius:10px;padding:18px}.card h3{margin:0 0 8px;font-size:12px;text-transform:uppercase;color:#64748b}table{width:100%;border-collapse:collapse;margin:20px 0}th{text-align:left;background:#edf2f7;font-size:12px;text-transform:uppercase}th,td{padding:12px;border-bottom:1px solid #dbe3ec;vertical-align:top}th:nth-child(n+2),td:nth-child(n+2){text-align:right}td small{display:block;margin-top:4px}.totals{margin-left:auto;width:min(380px,100%)}.totals div{display:flex;justify-content:space-between;padding:8px 0}.totals .balance{border-top:2px solid #172033;margin-top:4px;padding-top:12px;font-size:19px}.blueprint{margin:30px 0;page-break-inside:avoid}.blueprint img{width:100%;max-height:480px;object-fit:contain;border:1px solid #dbe3ec}.room-scope{break-inside:avoid;border-top:1px solid #dbe3ec;padding-top:16px;margin-top:18px}.room-scope h3{margin:0 0 8px}.room-scope h3 span{font-size:11px;text-transform:uppercase;color:#64748b;margin-left:8px}.room-scope li{margin:5px 0}.notes{white-space:pre-wrap}.print{position:fixed;right:18px;top:18px;background:#2563eb;color:white;border:0;border-radius:8px;padding:11px 18px;font-weight:bold;cursor:pointer}@media(max-width:640px){.page{margin:0;padding:24px}.customer{grid-template-columns:1fr}header{flex-direction:column}.meta{text-align:left}table{font-size:12px}th,td{padding:8px}}@media print{body{background:white}.page{margin:0;width:100%;padding:0;box-shadow:none}.print{display:none}}
        </style></head><body><button class="print" onclick="window.print()">Print / Save PDF</button><main class="page">
            <header><div class="brand"><h2>${escapeHTML(company.name)}</h2><div class="muted">${escapeHTML(company.address)}${company.phone ? `<br>${escapeHTML(company.phone)}` : ''}${company.email ? ` · ${escapeHTML(company.email)}` : ''}</div></div><div class="meta"><h1>${escapeHTML(title)}</h1><strong>${escapeHTML(numberText)}</strong><span class="muted">Issued ${new Date().toLocaleDateString()}${isInvoice ? `<br>Due ${escapeHTML(settings.dueDate)} · ${escapeHTML(settings.invoiceStatus)}` : ''}</span></div></header>
            ${settings.includeCustomerInfo ? `<section class="customer"><div class="card"><h3>Prepared for</h3><strong>${escapeHTML(model.customer.name)}</strong><div class="muted">${escapeHTML(model.customer.address)}${model.customer.phone ? `<br>${escapeHTML(model.customer.phone)}` : ''}${model.customer.email ? `<br>${escapeHTML(model.customer.email)}` : ''}</div></div><div class="card"><h3>Project</h3><strong>${escapeHTML(model.jobName)}</strong><div class="muted">Estimator: ${escapeHTML(model.customer.estimator || 'Not assigned')}${isInvoice ? `<br>${escapeHTML(settings.paymentTerms)}` : ''}</div></div></section>` : ''}
            <h2>Approved scope</h2>${settings.showItemizedPricing ? `<table><thead><tr><th>Scope item</th><th>Quantity</th><th>Unit price</th><th>Total</th></tr></thead><tbody>${itemRows || '<tr><td colspan="4">No scope items selected.</td></tr>'}</tbody></table>` : `<div class="card">Professional services and materials for the approved project scope.</div>`}
            ${settings.includeTotalPricing ? `<div class="totals"><div><span>${isInvoice ? 'Invoice subtotal' : 'Project investment'}</span><strong>${money(subtotal)}</strong></div>${isInvoice && deposit > 0 ? `<div><span>Deposit received</span><strong>−${money(deposit)}</strong></div>` : ''}${isInvoice ? `<div class="balance"><span>Balance due</span><strong>${money(balance)}</strong></div>` : ''}</div>` : ''}
            ${blueprint ? `<section class="blueprint"><h2>Project blueprint</h2><img src="${blueprint}" alt="RoomFlow blueprint"></section>` : ''}
            <section><h2>Room-by-room scope</h2>${printableRooms(model) || '<p class="muted">No room-specific tasks have been selected.</p>'}</section>
            ${settings.notes ? `<section class="card notes"><h3>Notes</h3>${escapeHTML(settings.notes)}</section>` : ''}
        </main></body></html>`;
        win.document.open();
        win.document.write(html);
        win.document.close();
    }

    function openWorkflow() {
        if (!state.currentJobName) {
            alert('Please start or select a job first.');
            return;
        }
        if (typeof window.setInterfaceMode === 'function') window.setInterfaceMode('guided');
        state.currentStep = 8;
        if (typeof window.switchTab === 'function') window.switchTab('project');
        if (typeof window.renderGuidedStep === 'function') window.renderGuidedStep();
    }

    window.RoomFlowDocuments = {
        ensureSettings,
        buildModel,
        getLineItems,
        roomScope,
        wallName,
        renderWorkflow,
        setSetting,
        setItemVisibility,
        addScopeItem,
        print,
        openWorkflow,
        escapeHTML,
        money
    };
    window.printCustomerProposal = () => print('proposal');
    window.printCustomerInvoice = () => print('invoice');

    window.addEventListener('load', () => {
        ensureSettings();
        const invoiceButton = document.getElementById('btn-create-invoice');
        if (invoiceButton) invoiceButton.addEventListener('click', () => print('invoice'));
        const documentsButton = document.getElementById('btn-open-documents');
        if (documentsButton) documentsButton.addEventListener('click', openWorkflow);
    });
})();
