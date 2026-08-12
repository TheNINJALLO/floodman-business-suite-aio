/**
 * Server-only Deno client for RoomFlow's existing Supabase Edge Function.
 * Never import this file into browser code. The HMAC secret belongs in Supabase secrets.
 */
const ORCHESTRATOR_URL = (Deno.env.get('FLOODMAN_ORCHESTRATOR_URL') || '').replace(/\/+$/, '');
const KEY_ID = Deno.env.get('FLOODMAN_ORCHESTRATOR_KEY_ID') || 'v1';
const SECRET_B64 = Deno.env.get('FLOODMAN_ORCHESTRATOR_HMAC_SECRET') || '';

function base64(bytes) {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function decodeBase64(value) {
  const binary = atob(value);
  return Uint8Array.from(binary, c => c.charCodeAt(0));
}

async function signature(timestamp, body) {
  if (!ORCHESTRATOR_URL || !SECRET_B64) throw new Error('Floodman orchestrator secrets are not configured');
  const key = await crypto.subtle.importKey(
    'raw', decodeBase64(SECRET_B64), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
  );
  const bytes = new TextEncoder().encode(`${timestamp}.${body}`);
  return base64(new Uint8Array(await crypto.subtle.sign('HMAC', key, bytes)));
}

async function requestFloodman(method, path, payload = null) {
  const body = payload == null ? '' : JSON.stringify(payload);
  const timestamp = `${Math.floor(Date.now() / 1000)}`;
  const headers = {
    'x-floodman-key-id': KEY_ID,
    'x-floodman-timestamp': timestamp,
    'x-floodman-signature': await signature(timestamp, body)
  };
  if (body) headers['content-type'] = 'application/json';
  const response = await fetch(`${ORCHESTRATOR_URL}${path}`, {
    method,
    headers,
    ...(body ? { body } : {})
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.detail || `Floodman orchestrator returned HTTP ${response.status}`);
    error.status = response.status;
    error.details = data;
    throw error;
  }
  return data;
}

export const postFloodman = (path, payload) => requestFloodman('POST', path, payload);
export const getFloodman = path => requestFloodman('GET', path);
export const syncEstimate = payload => postFloodman('/internal/v1/jobs/sync-estimate', payload);
export const getJob = jobId => getFloodman(`/internal/v1/jobs/${jobId}`);
export const startWork = (jobId, payload) => postFloodman(`/internal/v1/jobs/${jobId}/start`, payload);
export const createChangeOrder = (jobId, payload) => postFloodman(`/internal/v1/jobs/${jobId}/change-orders`, payload);
export const sendCompletion = (jobId, payload) => postFloodman(`/internal/v1/jobs/${jobId}/completion`, payload);
