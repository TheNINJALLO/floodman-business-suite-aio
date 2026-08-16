(() => {
  'use strict';
  const RELEASE = '4.6.10';
  const $ = (selector, root = document) => root.querySelector(selector);
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[ch]));
  const money = cents => new Intl.NumberFormat('en-US', {style:'currency', currency:'USD'}).format((Number(cents)||0)/100);
  const currentState = () => {
    try { if (typeof state !== 'undefined') return state; } catch (_) {}
    return window.state || {};
  };
  const integration = () => window.RoomFlowIntegrations || {};
  const status = message => { const el = $('#fmrf-status'); if (el) el.textContent = message; };
  const toast = (message, tone='') => {
    const el = $('#fmrf-message'); if (!el) return;
    el.className = `fmrf-message ${tone}`; el.textContent = message; el.hidden = false;
  };

  function linesFromRoomFlow() {
    const source = Array.isArray(integration().currentLines) && integration().currentLines.length
      ? integration().currentLines.filter(line => line.selected !== false)
      : (Array.isArray(currentState()?.costing?.customItems) ? currentState().costing.customItems : []);
    return source.map((line, index) => {
      const quantity = Number(line.quantity ?? line.qty ?? 1) || 1;
      const unitPrice = Number(line.unit_price ?? line.unitCost ?? line.price ?? 0) || 0;
      return {
        id: line.roomflow_line_id || line.roomflowLineId || line.id || `rf-line-${index+1}`,
        name: line.name || line.description || `RoomFlow item ${index+1}`,
        description: line.description || '',
        quantity,
        unit: line.unit || 'each',
        unit_price_cents: Math.round(unitPrice * 100),
        taxable: Boolean(line.taxable)
      };
    });
  }

  function textareaLines() {
    const lines = linesFromRoomFlow();
    return lines.map(line => `${line.name} | ${line.quantity} | ${(line.unit_price_cents/100).toFixed(2)}`).join('\n');
  }

  function parseLines(text) {
    return String(text || '').split(/\r?\n/).map((raw, index) => {
      const line = raw.trim(); if (!line) return null;
      const parts = line.split('|').map(value => value.trim());
      if (parts.length < 3) throw new Error(`Line ${index+1} must use Description | Quantity | Unit price`);
      const quantity = Number(parts[1]); const price = Number(String(parts[2]).replace(/[$,]/g,''));
      if (!Number.isFinite(quantity) || quantity <= 0) throw new Error(`Line ${index+1} has an invalid quantity`);
      if (!Number.isFinite(price) || price < 0) throw new Error(`Line ${index+1} has an invalid unit price`);
      return {id:`manual-${index+1}`, name:parts[0], description:'', quantity, unit:'each', unit_price_cents:Math.round(price*100), taxable:false};
    }).filter(Boolean);
  }

  function inferred() {
    const s = currentState(); const i = integration();
    const parsed = typeof i.parseServiceAddress === 'function' ? i.parseServiceAddress(s.costing?.customerAddress || s.customerAddress || '') : {};
    const name = s.costing?.customerName || s.customerName || s.currentJobName || '';
    const pieces = String(name).trim().split(/\s+/);
    return {
      jobName: s.currentJobName || 'RoomFlow job',
      jobId: (typeof i.currentJobId === 'function' && i.currentJobId()) || s.jobId || '',
      estimateId: i.currentEstimateId || '',
      title: i.currentEstimateHeader || `${s.currentJobName || 'RoomFlow'} Estimate`,
      firstName: s.costing?.customerFirstName || s.customerFirstName || pieces[0] || '',
      lastName: s.costing?.customerLastName || s.customerLastName || pieces.slice(1).join(' ') || '',
      email: s.costing?.customerEmail || s.customerEmail || '',
      phone: s.costing?.customerPhone || s.customerPhone || '',
      street: i.currentServiceStreet || s.costing?.serviceStreet || parsed.street || '',
      city: i.currentServiceCity || s.costing?.serviceCity || parsed.city || '',
      region: i.currentServiceState || s.costing?.serviceState || parsed.state || 'MI',
      postalCode: i.currentServicePostalCode || s.costing?.servicePostalCode || parsed.postalCode || '',
      lines: textareaLines()
    };
  }

  async function search(kind, query, contactId='') {
    const endpoint = kind === 'contacts' ? '/office/api/search/contacts' : '/office/api/search/properties';
    const params = new URLSearchParams({q:query, limit:'12'}); if (contactId) params.set('contact_id', contactId);
    const response = await fetch(`${endpoint}?${params}`, {credentials:'include', cache:'no-store'});
    if (response.redirected || response.url.includes('/login')) throw new Error('Sign in to Floodman Office before linking RoomFlow.');
    if (!response.ok) throw new Error(`Floodman search returned HTTP ${response.status}`);
    return response.json();
  }

  function renderResults(root, items, onPick) {
    root.innerHTML = '';
    for (const item of items || []) {
      const button = document.createElement('button'); button.type='button'; button.className='fmrf-result';
      button.innerHTML = `<b>${escapeHtml(item.label || item.name || item.id)}</b><small>${escapeHtml(item.secondary || item.address || '')}</small>`;
      button.onclick = () => onPick(item); root.appendChild(button);
    }
  }

  let modalReturnFocus = null;
  function openModal() {
    const values = inferred(); const modal = $('#fmrf-modal'); modalReturnFocus = document.activeElement; modal.classList.add('open'); modal.setAttribute('aria-hidden','false'); document.documentElement.classList.add('fmrf-modal-open');
    $('#fmrf-job-name').value = values.jobName; $('#fmrf-title').value = values.title; $('#fmrf-first-name').value = values.firstName;
    $('#fmrf-last-name').value = values.lastName; $('#fmrf-email').value = values.email; $('#fmrf-phone').value = values.phone;
    $('#fmrf-street').value = values.street; $('#fmrf-city').value = values.city; $('#fmrf-state').value = values.region;
    $('#fmrf-postal').value = values.postalCode; $('#fmrf-lines').value = values.lines;
    $('#fmrf-roomflow-job-id').value = values.jobId; $('#fmrf-roomflow-estimate-id').value = values.estimateId;
    toast('Choose an existing customer or confirm the customer details, then save the estimate.', '');
    window.setTimeout(() => $('#fmrf-customer-search')?.focus(), 0);
  }
  function closeModal() { const modal=$('#fmrf-modal'); modal.classList.remove('open'); modal.setAttribute('aria-hidden','true'); document.documentElement.classList.remove('fmrf-modal-open'); if (modalReturnFocus?.focus) modalReturnFocus.focus(); }

  async function submit() {
    const button = $('#fmrf-save'); button.disabled = true; status('Saving to Floodman…');
    try {
      const lines = parseLines($('#fmrf-lines').value);
      const payload = {
        roomflow_job_id: $('#fmrf-roomflow-job-id').value || '', roomflow_estimate_id: $('#fmrf-roomflow-estimate-id').value || '',
        job_name: $('#fmrf-job-name').value, revision: Number($('#fmrf-revision').value || 1),
        customer: {contact_id:$('#fmrf-contact-id').value, first_name:$('#fmrf-first-name').value, last_name:$('#fmrf-last-name').value, email:$('#fmrf-email').value, phone:$('#fmrf-phone').value},
        property: {property_id:$('#fmrf-property-id').value, property_name:$('#fmrf-property-name').value, property_type:$('#fmrf-property-type').value, street:$('#fmrf-street').value, city:$('#fmrf-city').value, state:$('#fmrf-state').value, postal_code:$('#fmrf-postal').value, country:'US'},
        estimate: {estimate_number:$('#fmrf-estimate-number').value, title:$('#fmrf-title').value, lines, deposit_percent:Number($('#fmrf-deposit').value || 30), terms:$('#fmrf-terms').value, status:'DRAFT'}
      };
      const response = await fetch('/office/api/roomflow/sync', {method:'POST', credentials:'include', headers:{'content-type':'application/json'}, body:JSON.stringify(payload)});
      const contentType = response.headers.get('content-type') || '';
      if (response.redirected || response.url.includes('/login') || !contentType.includes('json')) throw new Error('Sign in to Floodman Office, then return to RoomFlow and save again.');
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || `Floodman returned HTTP ${response.status}`);
      $('#fmrf-contact-id').value = data.contact_id; $('#fmrf-property-id').value = data.property_id;
      $('#fmrf-customer-file').href = data.urls.customer; $('#fmrf-customer-file').classList.remove('fmrf-hide-mobile');
      status(`Saved ${data.estimate_number} · ${money(data.total_cents)}`);
      toast(`Saved ${data.estimate_number} to the customer file.${data.warnings?.length ? ' ' + data.warnings.join(' ') : ''}`, data.warnings?.length ? '' : 'good');
      const s=currentState(); if (s && data.roomflow_job?.roomflow_job_id) s.jobId=data.roomflow_job.roomflow_job_id;
    } catch (error) { status('Save needs attention'); toast(error.message || String(error), 'error'); }
    finally { button.disabled = false; }
  }

  function install() {
    if ($('#floodman-roomflow-bar')) return;
    document.body.classList.add('fm-roomflow-integrated');
    const bar=document.createElement('div'); bar.id='floodman-roomflow-bar'; bar.className='fmrf-bar';
    bar.innerHTML=`<div class="fmrf-brand"><span class="fmrf-mark">F</span><span><b>Floodman RoomFlow</b><small>Property layout, scope, and estimate workspace</small></span></div><div class="fmrf-actions"><span id="fmrf-status" class="fmrf-status">Ready to link</span><a class="fmrf-button fmrf-hide-mobile" href="/office/roomflow">Back to Floodman</a><a id="fmrf-customer-file" class="fmrf-button fmrf-hide-mobile" href="/office/contacts">Customer file</a><button id="fmrf-open" class="fmrf-button good" type="button">Save to Floodman</button></div>`;
    document.body.appendChild(bar);
    const modal=document.createElement('div'); modal.id='fmrf-modal'; modal.className='fmrf-modal-backdrop'; modal.setAttribute('aria-hidden','true');
    modal.innerHTML=`<section class="fmrf-modal" role="dialog" aria-modal="true" aria-labelledby="fmrf-title-heading"><h2 id="fmrf-title-heading">Save RoomFlow estimate to Floodman</h2><p>Search thousands of customers without a giant dropdown. Pick a customer, choose one of that customer’s properties, review the lines, and save.</p><input id="fmrf-roomflow-job-id" type="hidden"><input id="fmrf-roomflow-estimate-id" type="hidden"><input id="fmrf-contact-id" type="hidden"><input id="fmrf-property-id" type="hidden"><div class="fmrf-grid"><div class="fmrf-field full"><label>Find existing customer</label><input id="fmrf-customer-search" type="search" placeholder="Name, email, phone, company, or address"><div id="fmrf-customer-results" class="fmrf-results"></div></div><div class="fmrf-field"><label>First name</label><input id="fmrf-first-name"></div><div class="fmrf-field"><label>Last name</label><input id="fmrf-last-name"></div><div class="fmrf-field"><label>Email</label><input id="fmrf-email" type="email"></div><div class="fmrf-field"><label>Phone</label><input id="fmrf-phone"></div><div class="fmrf-field full"><label>Find this customer’s property</label><input id="fmrf-property-search" type="search" placeholder="Street, city, property name"><div id="fmrf-property-results" class="fmrf-results"></div></div><div class="fmrf-field"><label>Property name</label><input id="fmrf-property-name" placeholder="Home, cabin, commercial site"></div><div class="fmrf-field"><label>Property type</label><input id="fmrf-property-type" placeholder="Residential"></div><div class="fmrf-field full"><label>Service street address</label><input id="fmrf-street"></div><div class="fmrf-field"><label>City</label><input id="fmrf-city"></div><div class="fmrf-field"><label>State</label><input id="fmrf-state" value="MI"></div><div class="fmrf-field"><label>ZIP</label><input id="fmrf-postal"></div><div class="fmrf-field"><label>Job name</label><input id="fmrf-job-name"></div><div class="fmrf-field"><label>Estimate number</label><input id="fmrf-estimate-number" placeholder="Leave blank for automatic"></div><div class="fmrf-field"><label>Revision</label><input id="fmrf-revision" type="number" min="1" value="1"></div><div class="fmrf-field"><label>Deposit percent</label><input id="fmrf-deposit" type="number" min="0" max="100" step="0.01" value="30"></div><div class="fmrf-field full"><label>Estimate title</label><input id="fmrf-title"></div><div class="fmrf-field full"><label>Line items · Description | Quantity | Unit price</label><textarea id="fmrf-lines"></textarea></div><div class="fmrf-field full"><label>Terms</label><textarea id="fmrf-terms">Payment is due upon receipt of each issued invoice. Additional work requires a signed Change Order.</textarea></div></div><div id="fmrf-message" class="fmrf-message" hidden></div><div class="fmrf-modal-actions"><button id="fmrf-save" class="fmrf-button good" type="button">Save estimate to Floodman</button><button id="fmrf-close" class="fmrf-button" type="button">Close</button></div></section>`;
    const modalClose=document.createElement('button'); modalClose.id='fmrf-close-icon'; modalClose.className='fmrf-modal-close'; modalClose.type='button'; modalClose.setAttribute('aria-label','Close save dialog'); modalClose.textContent='×'; modal.querySelector('.fmrf-modal')?.prepend(modalClose);
    document.body.appendChild(modal);
    $('#fmrf-open').onclick=openModal; $('#fmrf-close').onclick=closeModal; $('#fmrf-close-icon').onclick=closeModal; modal.addEventListener('click', e => { if(e.target===modal) closeModal(); }); document.addEventListener('keydown', e => { if(e.key === 'Escape' && modal.classList.contains('open')) closeModal(); }); $('#fmrf-save').onclick=submit;
    let contactTimer; $('#fmrf-customer-search').addEventListener('input', e => { clearTimeout(contactTimer); contactTimer=setTimeout(async()=>{ try{ const data=await search('contacts', e.target.value); renderResults($('#fmrf-customer-results'), data.items, item=>{ $('#fmrf-contact-id').value=item.id; $('#fmrf-customer-search').value=item.label; $('#fmrf-customer-results').innerHTML=''; const raw=item.raw||{}; $('#fmrf-first-name').value=raw.first_name||raw.firstName||''; $('#fmrf-last-name').value=raw.last_name||raw.lastName||''; $('#fmrf-email').value=raw.email||raw.primaryEmail||''; $('#fmrf-phone').value=raw.phone||raw.primaryPhone||''; $('#fmrf-property-search').focus(); }); }catch(err){toast(err.message,'error');}},250); });
    let propertyTimer; $('#fmrf-property-search').addEventListener('input', e => { clearTimeout(propertyTimer); propertyTimer=setTimeout(async()=>{ try{ const data=await search('properties', e.target.value, $('#fmrf-contact-id').value); renderResults($('#fmrf-property-results'), data.items, item=>{ $('#fmrf-property-id').value=item.id; $('#fmrf-property-search').value=item.label; $('#fmrf-property-results').innerHTML=''; const raw=item.raw||{}; const address=raw.service_address||{}; $('#fmrf-property-name').value=raw.name||raw.property_name||''; $('#fmrf-property-type').value=raw.property_type||''; $('#fmrf-street').value=address.street||raw.service_street||''; $('#fmrf-city').value=address.city||raw.service_city||''; $('#fmrf-state').value=address.state||raw.service_state||'MI'; $('#fmrf-postal').value=address.postal_code||address.postalCode||raw.service_postal_code||''; }); }catch(err){toast(err.message,'error');}},250); });
    status('RoomFlow ready');
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install); else install();
})();
