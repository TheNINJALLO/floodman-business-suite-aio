/** Convert RoomFlow's server-reloaded canonical estimate snapshot to the orchestrator contract.
 *
 * The caller must pass data loaded inside the Supabase function after user, organization,
 * permissions, revision and totals have been verified. Do not pass browser-calculated totals
 * or expose Floodman integration secrets to browser JavaScript.
 */
function required(value, name) {
  if (value === null || value === undefined || value === '') throw new Error(`Missing ${name}`);
  return value;
}

function cents(value, name) {
  if (!Number.isSafeInteger(value)) throw new Error(`${name} must be integer cents`);
  return value;
}

function normalizeConsent(customer) {
  let status = `${customer.sms_consent || ''}`.toUpperCase();
  if (!['UNKNOWN', 'OPTED_IN', 'OPTED_OUT'].includes(status)) {
    status = customer.sms_opt_in === true ? 'OPTED_IN' : customer.sms_opt_in === false ? 'OPTED_OUT' : 'UNKNOWN';
  }
  const normalized = {
    first_name: `${required(customer.first_name, 'customer.first_name')}`,
    last_name: `${required(customer.last_name, 'customer.last_name')}`,
    email: `${required(customer.email, 'customer.email')}`,
    phone: `${required(customer.phone, 'customer.phone')}`,
    billing_address: customer.billing_address || null,
    timezone: `${customer.timezone || 'America/Detroit'}`,
    sms_consent: status,
    sms_consent_captured_at: customer.sms_consent_captured_at || null,
    sms_consent_source: `${customer.sms_consent_source || 'UNSPECIFIED'}`,
    sms_consent_disclosure_version: customer.sms_consent_disclosure_version || null,
    sms_consent_disclosure_text: customer.sms_consent_disclosure_text || null,
    sms_consent_evidence_id: customer.sms_consent_evidence_id || null
  };
  if (status === 'OPTED_IN') {
    for (const field of ['sms_consent_captured_at', 'sms_consent_disclosure_version', 'sms_consent_disclosure_text']) {
      if (!normalized[field]) throw new Error(`OPTED_IN SMS consent requires customer.${field}`);
    }
    if (normalized.sms_consent_source === 'UNSPECIFIED') {
      throw new Error('OPTED_IN SMS consent requires customer.sms_consent_source');
    }
  }
  return normalized;
}

export function buildFloodmanEstimate(input) {
  const lines = required(input.lines, 'lines').map((line, index) => ({
    line_id: `${required(line.id ?? line.line_id, `lines[${index}].id`)}`,
    name: `${required(line.name, `lines[${index}].name`)}`,
    description: `${line.description || ''}`,
    quantity: `${required(line.quantity, `lines[${index}].quantity`)}`,
    unit_price_cents: cents(line.unit_price_cents, `lines[${index}].unit_price_cents`),
    line_total_cents: cents(line.line_total_cents, `lines[${index}].line_total_cents`),
    taxable: Boolean(line.taxable)
  }));
  const tax = cents(input.tax_cents || 0, 'tax_cents');
  const discount = cents(input.discount_cents || 0, 'discount_cents');
  const calculated = lines.reduce((sum, line) => sum + line.line_total_cents, 0) + tax - discount;
  const total = cents(required(input.total_cents, 'total_cents'), 'total_cents');
  if (calculated !== total) throw new Error(`RoomFlow export total mismatch: ${calculated} != ${total}`);
  return {
    idempotency_key: `roomflow:${required(input.organization_id, 'organization_id')}:${required(input.job_id, 'job_id')}:r${required(input.revision, 'revision')}`,
    organization_id: `${input.organization_id}`,
    roomflow_job_id: `${input.job_id}`,
    roomflow_estimate_id: `${required(input.estimate_id, 'estimate_id')}`,
    revision: Number(input.revision),
    invoice_number: Number(required(input.invoice_number, 'invoice_number')),
    currency: 'USD',
    customer: normalizeConsent(required(input.customer, 'customer')),
    property: required(input.property, 'property'),
    lines,
    tax_cents: tax,
    discount_cents: discount,
    total_cents: total,
    terms: `${input.terms || ''}`,
    internal_note: `${input.internal_note || ''}`,
    authorization: required(input.authorization, 'authorization'),
    payment_schedule: required(input.payment_schedule, 'payment_schedule')
  };
}
