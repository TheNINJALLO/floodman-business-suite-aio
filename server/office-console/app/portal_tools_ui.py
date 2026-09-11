"""Small progressive job-tool interactions; no customer data in browser storage."""
PORTAL_TOOLS_JS = r"""(() => {
  'use strict';
  const chunkSize = 4 * 1024 * 1024;
  let uploading = 0;
  window.addEventListener('beforeunload', event => {
    if (uploading) { event.preventDefault(); event.returnValue = ''; }
  });
  const request = async (url, body, binary = false) => {
    const response = await fetch(url, {method: body === undefined ? 'GET' : 'POST', credentials:'same-origin',
      headers:body === undefined ? {} : {'Content-Type': binary ? 'application/octet-stream' : 'application/json'},
      body:body === undefined ? undefined : binary ? body : JSON.stringify(body)});
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Connection unavailable. Try again to resume your saved upload.');
    if (response.redirected || typeof result.operation_id !== 'string' || !['STAGING','PENDING','SENT','FAILED','BLOCKED','CANCELLED'].includes(result.status)) {
      throw new Error('Your session or upload response could not be verified. Sign in again, then resume this upload.');
    }
    return result;
  };
  const watch = async (job, operations, status) => {
    for (let check = 0; check < 150; check++) {
      const results = await Promise.all(operations.map(id => request(`/office/photo-portal/${job}/actions/${id}`)));
      if (results.some(row => ['FAILED','BLOCKED'].includes(row.status))) {
        status.textContent = results.find(row => row.error)?.error || 'A saved change needs review. Refresh this job.'; return;
      }
      if (results.every(row => row.status === 'SENT')) {
        status.replaceChildren(document.createTextNode('Saved to the portal. '));
        const link = document.createElement('a'); link.href = location.href; link.textContent = 'Refresh to view'; status.append(link); return;
      }
      const sent = results.filter(row => row.status === 'SENT').length;
      status.textContent = `Saved safely in Floodman. ${sent} of ${results.length} confirmed by the portal; syncing in the background.`;
      await new Promise(resolve => setTimeout(resolve, 2500));
    }
    status.textContent = 'Saved safely in Floodman. Synchronization continues in the background. Refresh later for the result.';
  };
  document.querySelectorAll('[data-portal-tool]').forEach(form => {
    let attempts = new Map(), batch = '';
    form.querySelectorAll('input[type=file]').forEach(input => input.addEventListener('change', () => {
      if (form.dataset.kind === 'receipt') form.querySelectorAll('input[type=file]').forEach(other => { if (other !== input) other.value=''; });
    }));
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (form.dataset.busy) return;
      const status = form.querySelector('[data-tool-status]'), button = form.querySelector('[type=submit]');
      const fields = {};
      new FormData(form).forEach((value,key) => { if (typeof value === 'string') fields[key] = value; });
      const files = [...(form.elements.files?.files || []), ...(form.elements.camera?.files || [])];
      const needsFile = form.dataset.mode === 'add' && ['photo','receipt','video'].includes(form.dataset.kind);
      if (needsFile && !files.length) { status.textContent = 'Choose images or use the camera first.'; return; }
      if (files.some(file => file.size === 0 || file.size > (form.dataset.kind === 'video' ? 100 : 12) * 1024 * 1024)) {
        status.textContent = 'Choose photos/receipt images up to 12 MB or videos up to 100 MB.'; return;
      }
      // Keep operation IDs stable on retry, but never reuse them for changed fields/files.
      const signature = JSON.stringify([fields,files.map(file => [file.name,file.size,file.lastModified])]);
      if (signature !== batch) { attempts = new Map(); batch = signature; }
      form.dataset.busy = '1'; button.disabled = true; uploading++;
      try {
        const operations = [];
        for (const [number,file] of (needsFile ? files : [null]).entries()) {
          const operation = attempts.get(number) || form.dataset.operation || crypto.randomUUID(); attempts.set(number,operation);
          const payload = {operation_id:operation,kind:form.dataset.kind,mode:form.dataset.mode,fields,
            record_id:form.dataset.record,revision:form.dataset.revision,content_id:form.dataset.content,size:file?.size || 0};
          let saved = await request(`/office/photo-portal/${form.dataset.job}/actions`,payload);
          if (file && saved.status === 'STAGING') {
            for (let start = 0, index = 0; start < file.size; start += chunkSize, index++) {
              status.textContent = `Uploading ${number+1} of ${files.length}: ${Math.round(start/file.size*100)}%`;
              saved = await request(`/office/photo-portal/${form.dataset.job}/uploads/${operation}/${index}`,file.slice(start,start+chunkSize),true);
            }
          }
          operations.push(operation);
        }
        status.textContent = 'Saved safely in Floodman. Waiting for portal confirmation.';
        // Do not reload automatically and discard drafts in another open form.
        watch(form.dataset.job,operations,status).catch(() => { status.textContent = 'Saved safely. Refresh to check portal synchronization.'; });
        button.textContent = 'Saved'; button.disabled = true;
      } catch (error) {
        status.textContent = error.message; button.disabled = false; button.textContent = 'Try again';
      } finally { uploading--; delete form.dataset.busy; }
    });
    form.addEventListener('input', () => {
      if (!form.dataset.busy) { const button=form.querySelector('[type=submit]'); button.disabled=false; button.textContent='Save'; }
    });
  });
  document.querySelectorAll('[data-portal-remove]').forEach(button => {
    let operation;
    button.addEventListener('click', async () => {
      if (!confirm('Remove this item from the job? Its original file and recovery record will be retained.')) return;
      const status = button.parentElement.querySelector('[data-remove-status]'); button.disabled=true;
      try {
        operation ||= crypto.randomUUID();
        await request(`/office/photo-portal/${button.dataset.job}/actions`,{operation_id:operation,kind:button.dataset.kind,
          mode:'remove',record_id:button.dataset.record,revision:button.dataset.revision,confirmed:true});
        await watch(button.dataset.job,[operation],status);
      } catch (error) { status.textContent=error.message; button.disabled=false; }
    });
  });
  document.querySelector('[data-portal-print]')?.addEventListener('click', async event => {
    const button = event.currentTarget, status = document.querySelector('[data-portal-status]');
    button.disabled=true;
    try {
      const images = [...document.querySelectorAll('.portal-tools[data-tab=receipts] .portal-item img')];
      images.forEach(image => { image.loading='eager'; });
      await Promise.all(images.map(image => image.decode()));
      document.body.classList.add('portal-print-receipts'); window.print();
    } catch (_) { status.textContent='A receipt image could not load. Refresh its private link before printing.'; }
    finally { document.body.classList.remove('portal-print-receipts'); button.disabled=false; }
  });
})();
"""
