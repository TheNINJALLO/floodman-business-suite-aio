-- =============================================================
-- RoomFlow Phase 1: email intake, shared tracker, catalog, estimates
-- Safe additive migration for the existing RoomFlow Supabase schema.
-- Run in Supabase SQL Editor as a database owner.
-- =============================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- -------------------------------------------------------------
-- Shared helpers
-- -------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.roomflow_set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = timezone('utc'::text, now());
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.roomflow_is_org_member(target_org_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.organization_members om
    WHERE om.organization_id = target_org_id
      AND om.user_id = auth.uid()
  );
$$;

-- Replace the original self-referencing membership policy. Querying
-- organization_members from its own RLS policy causes infinite recursion and
-- hides memberships that were successfully created by the company RPC.
DROP POLICY IF EXISTS "Members can view other members in company" ON public.organization_members;
CREATE POLICY "Members can view other members in company" ON public.organization_members
FOR SELECT TO authenticated
USING (public.roomflow_is_org_member(organization_id));

DROP POLICY IF EXISTS "Members can view organization" ON public.organizations;
CREATE POLICY "Members can view organization" ON public.organizations
FOR SELECT TO authenticated
USING (public.roomflow_is_org_member(id));


-- Correct the original capability helper. The earlier implementation reused
-- variable names such as member_id on both sides of comparisons, which can
-- produce ambiguous or self-comparing expressions.
CREATE OR REPLACE FUNCTION public.has_capability(org_id uuid, req_cap text)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_member_id uuid;
  v_role_id uuid;
  v_override_allowed boolean;
BEGIN
  SELECT om.id, om.role_id
  INTO v_member_id, v_role_id
  FROM public.organization_members om
  WHERE om.organization_id = org_id
    AND om.user_id = auth.uid()
  LIMIT 1;

  IF v_member_id IS NULL THEN
    RETURN false;
  END IF;

  SELECT mco.allowed
  INTO v_override_allowed
  FROM public.member_capability_overrides mco
  WHERE mco.member_id = v_member_id
    AND mco.capability = req_cap
  LIMIT 1;

  IF v_override_allowed IS NOT NULL THEN
    RETURN v_override_allowed;
  END IF;

  RETURN EXISTS (
    SELECT 1
    FROM public.role_capabilities rc
    WHERE rc.role_id = v_role_id
      AND rc.capability = req_cap
  );
END;
$$;

REVOKE ALL ON FUNCTION public.has_capability(uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.has_capability(uuid, text) TO authenticated, service_role;

-- -------------------------------------------------------------
-- Fix company creation: atomic, authenticated, and verified.
-- -------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.create_new_company_with_owner(company_name text)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  new_org_id uuid;
  owner_role_id uuid;
  current_user_id uuid := auth.uid();
  owner_capabilities text[] := ARRAY[
    'manage_company','manage_members','manage_roles','manage_groups',
    'create_jobs','view_company_jobs','edit_job_information','edit_floor_plans',
    'edit_measurements','edit_job_scope','upload_attachments','view_material_quantities',
    'edit_material_quantities','view_internal_costs','edit_internal_costs',
    'view_customer_prices','edit_customer_prices','view_margin','edit_margin',
    'generate_proposals','approve_proposals','generate_work_orders',
    'approve_work_orders','assign_jobs','manage_catalog','delete_jobs',
    'restore_jobs','view_audit_logs','manage_integrations','manage_outreach'
  ];
BEGIN
  IF current_user_id IS NULL THEN
    RAISE EXCEPTION 'Authentication required';
  END IF;

  IF company_name IS NULL OR length(trim(company_name)) < 2 THEN
    RAISE EXCEPTION 'Company name must contain at least 2 characters';
  END IF;

  -- Backfill a profile if the original signup trigger was not installed yet.
  INSERT INTO public.profiles (id, full_name)
  SELECT u.id, COALESCE(u.raw_user_meta_data->>'full_name', u.email)
  FROM auth.users u
  WHERE u.id = current_user_id
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO public.organizations (name)
  VALUES (trim(company_name))
  RETURNING id INTO new_org_id;

  INSERT INTO public.custom_roles (organization_id, name, description, is_system)
  VALUES (new_org_id, 'Company Owner', 'Full control over company settings and pricing', true)
  RETURNING id INTO owner_role_id;

  INSERT INTO public.role_capabilities (role_id, capability)
  SELECT owner_role_id, capability
  FROM unnest(owner_capabilities) AS capability
  ON CONFLICT (role_id, capability) DO NOTHING;

  INSERT INTO public.organization_members (organization_id, user_id, role_id)
  VALUES (new_org_id, current_user_id, owner_role_id);

  INSERT INTO public.audit_logs (organization_id, user_id, action, details)
  VALUES (
    new_org_id,
    current_user_id,
    'company.created',
    jsonb_build_object('company_name', trim(company_name))
  );

  RETURN new_org_id;
END;
$$;

-- Compatibility overload. It cannot create a company for another user.
CREATE OR REPLACE FUNCTION public.create_new_company_with_owner(company_name text, owner_id uuid)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF owner_id IS DISTINCT FROM auth.uid() THEN
    RAISE EXCEPTION 'Owner must be the authenticated user';
  END IF;
  RETURN public.create_new_company_with_owner(company_name);
END;
$$;

REVOKE ALL ON FUNCTION public.create_new_company_with_owner(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.create_new_company_with_owner(text, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.create_new_company_with_owner(text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.create_new_company_with_owner(text, uuid) TO authenticated;

-- Backfill the two new capabilities into existing owner roles.
INSERT INTO public.role_capabilities (role_id, capability)
SELECT cr.id, capability
FROM public.custom_roles cr
CROSS JOIN (VALUES ('manage_integrations'), ('manage_outreach')) AS caps(capability)
WHERE cr.name = 'Company Owner'
ON CONFLICT (role_id, capability) DO NOTHING;

-- -------------------------------------------------------------
-- Expand customers/jobs so email intake and tracker share fields.
-- -------------------------------------------------------------
ALTER TABLE public.customers
  ADD COLUMN IF NOT EXISTS first_name text,
  ADD COLUMN IF NOT EXISTS last_name text,
  ADD COLUMN IF NOT EXISTS address text,
  ADD COLUMN IF NOT EXISTS city text,
  ADD COLUMN IF NOT EXISTS state text,
  ADD COLUMN IF NOT EXISTS postal_code text,
  ADD COLUMN IF NOT EXISTS lead_source text,
  ADD COLUMN IF NOT EXISTS external_key text,
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now());

CREATE UNIQUE INDEX IF NOT EXISTS customers_org_external_key_uidx
  ON public.customers (organization_id, external_key)
  WHERE external_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS customers_org_email_idx
  ON public.customers (organization_id, lower(email));
CREATE INDEX IF NOT EXISTS customers_org_phone_idx
  ON public.customers (organization_id, phone);

DROP TRIGGER IF EXISTS roomflow_customers_updated_at ON public.customers;
CREATE TRIGGER roomflow_customers_updated_at
BEFORE UPDATE ON public.customers
FOR EACH ROW EXECUTE FUNCTION public.roomflow_set_updated_at();

ALTER TABLE public.jobs
  ADD COLUMN IF NOT EXISTS property_address text,
  ADD COLUMN IF NOT EXISTS city text,
  ADD COLUMN IF NOT EXISTS state text,
  ADD COLUMN IF NOT EXISTS postal_code text,
  ADD COLUMN IF NOT EXISTS issue_description text,
  ADD COLUMN IF NOT EXISTS appointment_start timestamptz,
  ADD COLUMN IF NOT EXISTS appointment_end timestamptz,
  ADD COLUMN IF NOT EXISTS lead_source text,
  ADD COLUMN IF NOT EXISTS source_email_message_id text,
  ADD COLUMN IF NOT EXISTS tracking_color text DEFAULT 'gray',
  ADD COLUMN IF NOT EXISTS estimate_status text DEFAULT 'not_started',
  ADD COLUMN IF NOT EXISTS followup_status text DEFAULT 'inactive',
  ADD COLUMN IF NOT EXISTS external_key text;

CREATE UNIQUE INDEX IF NOT EXISTS jobs_org_source_email_uidx
  ON public.jobs (organization_id, source_email_message_id)
  WHERE source_email_message_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS jobs_org_external_key_uidx
  ON public.jobs (organization_id, external_key)
  WHERE external_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS jobs_org_status_idx
  ON public.jobs (organization_id, status, updated_at DESC);

DROP TRIGGER IF EXISTS roomflow_jobs_updated_at ON public.jobs;
CREATE TRIGGER roomflow_jobs_updated_at
BEFORE UPDATE ON public.jobs
FOR EACH ROW EXECUTE FUNCTION public.roomflow_set_updated_at();

-- -------------------------------------------------------------
-- Secured webhook endpoint registrations for Zapier/email sources.
-- Only SHA-256 hashes are stored. Never store the plain secret.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.integration_endpoints (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  endpoint_key text NOT NULL UNIQUE,
  secret_hash text NOT NULL,
  source_type text NOT NULL DEFAULT 'zapier_email',
  name text NOT NULL DEFAULT 'Inbound Lead Email',
  enabled boolean NOT NULL DEFAULT true,
  created_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  updated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now())
);

DROP TRIGGER IF EXISTS roomflow_integration_endpoints_updated_at ON public.integration_endpoints;
CREATE TRIGGER roomflow_integration_endpoints_updated_at
BEFORE UPDATE ON public.integration_endpoints
FOR EACH ROW EXECUTE FUNCTION public.roomflow_set_updated_at();

-- Helper called from the Edge Function using service-role credentials.
CREATE OR REPLACE FUNCTION public.verify_integration_endpoint(
  requested_endpoint_key text,
  supplied_secret_hash text
)
RETURNS TABLE (organization_id uuid, endpoint_id uuid, source_type text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT ie.organization_id, ie.id, ie.source_type
  FROM public.integration_endpoints ie
  WHERE ie.endpoint_key = requested_endpoint_key
    AND ie.secret_hash = supplied_secret_hash
    AND ie.enabled = true
  LIMIT 1;
$$;

REVOKE ALL ON FUNCTION public.verify_integration_endpoint(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.verify_integration_endpoint(text, text) TO service_role;

-- -------------------------------------------------------------
-- Lead imports and tracker timeline
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.lead_imports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  endpoint_id uuid REFERENCES public.integration_endpoints(id) ON DELETE SET NULL,
  customer_id uuid REFERENCES public.customers(id) ON DELETE SET NULL,
  job_id uuid REFERENCES public.jobs(id) ON DELETE SET NULL,
  source text NOT NULL DEFAULT 'email',
  source_message_id text,
  source_sender text,
  source_subject text,
  raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  normalized_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  import_status text NOT NULL DEFAULT 'imported',
  import_error text,
  received_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  UNIQUE (organization_id, source_message_id)
);

CREATE INDEX IF NOT EXISTS lead_imports_org_received_idx
  ON public.lead_imports (organization_id, received_at DESC);
CREATE INDEX IF NOT EXISTS lead_imports_job_idx ON public.lead_imports (job_id);

CREATE TABLE IF NOT EXISTS public.job_status_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  job_id uuid NOT NULL REFERENCES public.jobs(id) ON DELETE CASCADE,
  event_type text NOT NULL,
  old_status text,
  new_status text,
  note text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  actor_user_id uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS job_status_events_job_created_idx
  ON public.job_status_events (job_id, created_at DESC);

-- -------------------------------------------------------------
-- Customer-facing estimate catalog and inline estimate records
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.estimate_catalog_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  external_key text,
  name text NOT NULL,
  description text,
  category text NOT NULL DEFAULT 'general-services',
  pricing_method text NOT NULL DEFAULT 'fixed',
  unit text NOT NULL DEFAULT 'each',
  unit_price numeric(12,2) NOT NULL DEFAULT 0,
  internal_cost numeric(12,2),
  taxable boolean NOT NULL DEFAULT false,
  active boolean NOT NULL DEFAULT true,
  source text,
  review_required boolean NOT NULL DEFAULT false,
  review_notes text,
  formula jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  updated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  UNIQUE (organization_id, external_key)
);

CREATE INDEX IF NOT EXISTS estimate_catalog_org_active_idx
  ON public.estimate_catalog_items (organization_id, active, category, name);

DROP TRIGGER IF EXISTS roomflow_estimate_catalog_updated_at ON public.estimate_catalog_items;
CREATE TRIGGER roomflow_estimate_catalog_updated_at
BEFORE UPDATE ON public.estimate_catalog_items
FOR EACH ROW EXECUTE FUNCTION public.roomflow_set_updated_at();

CREATE TABLE IF NOT EXISTS public.estimates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  job_id uuid NOT NULL REFERENCES public.jobs(id) ON DELETE CASCADE,
  estimate_number text NOT NULL,
  version_number integer NOT NULL DEFAULT 1,
  status text NOT NULL DEFAULT 'draft',
  subtotal numeric(12,2) NOT NULL DEFAULT 0,
  discount_total numeric(12,2) NOT NULL DEFAULT 0,
  taxable_subtotal numeric(12,2) NOT NULL DEFAULT 0,
  tax_rate numeric(7,4) NOT NULL DEFAULT 0,
  tax_total numeric(12,2) NOT NULL DEFAULT 0,
  total numeric(12,2) NOT NULL DEFAULT 0,
  customer_message text,
  terms text,
  sent_at timestamptz,
  viewed_at timestamptz,
  accepted_at timestamptz,
  declined_at timestamptz,
  expires_at timestamptz,
  created_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  updated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  UNIQUE (organization_id, estimate_number, version_number)
);

CREATE INDEX IF NOT EXISTS estimates_job_idx ON public.estimates (job_id, version_number DESC);
DROP TRIGGER IF EXISTS roomflow_estimates_updated_at ON public.estimates;
CREATE TRIGGER roomflow_estimates_updated_at
BEFORE UPDATE ON public.estimates
FOR EACH ROW EXECUTE FUNCTION public.roomflow_set_updated_at();

CREATE TABLE IF NOT EXISTS public.estimate_lines (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  estimate_id uuid NOT NULL REFERENCES public.estimates(id) ON DELETE CASCADE,
  catalog_item_id uuid REFERENCES public.estimate_catalog_items(id) ON DELETE SET NULL,
  room_id text,
  section_name text,
  name text NOT NULL,
  description text,
  pricing_method text NOT NULL DEFAULT 'fixed',
  quantity numeric(12,3) NOT NULL DEFAULT 1,
  unit text NOT NULL DEFAULT 'each',
  unit_price numeric(12,2) NOT NULL DEFAULT 0,
  line_total numeric(12,2) GENERATED ALWAYS AS (round(quantity * unit_price, 2)) STORED,
  taxable boolean NOT NULL DEFAULT false,
  optional boolean NOT NULL DEFAULT false,
  selected boolean NOT NULL DEFAULT true,
  sort_order integer NOT NULL DEFAULT 0,
  calculation_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  updated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS estimate_lines_estimate_sort_idx
  ON public.estimate_lines (estimate_id, sort_order, created_at);
DROP TRIGGER IF EXISTS roomflow_estimate_lines_updated_at ON public.estimate_lines;
CREATE TRIGGER roomflow_estimate_lines_updated_at
BEFORE UPDATE ON public.estimate_lines
FOR EACH ROW EXECUTE FUNCTION public.roomflow_set_updated_at();

CREATE TABLE IF NOT EXISTS public.estimate_attachments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  estimate_id uuid NOT NULL REFERENCES public.estimates(id) ON DELETE CASCADE,
  attachment_type text NOT NULL,
  storage_bucket text NOT NULL DEFAULT 'estimate-attachments',
  storage_path text NOT NULL,
  display_name text,
  mime_type text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  UNIQUE (estimate_id, attachment_type)
);

-- Private storage bucket used for 2D/3D estimate layouts.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('estimate-attachments', 'estimate-attachments', false, 20971520, ARRAY['image/png','image/jpeg','application/pdf'])
ON CONFLICT (id) DO UPDATE SET
  public = EXCLUDED.public,
  file_size_limit = EXCLUDED.file_size_limit,
  allowed_mime_types = EXCLUDED.allowed_mime_types;

DROP POLICY IF EXISTS "Organization members can read estimate attachments" ON storage.objects;
CREATE POLICY "Organization members can read estimate attachments" ON storage.objects
FOR SELECT TO authenticated
USING (
  bucket_id = 'estimate-attachments'
  AND public.roomflow_is_org_member((storage.foldername(name))[1]::uuid)
);

DROP POLICY IF EXISTS "Proposal users can upload estimate attachments" ON storage.objects;
CREATE POLICY "Proposal users can upload estimate attachments" ON storage.objects
FOR INSERT TO authenticated
WITH CHECK (
  bucket_id = 'estimate-attachments'
  AND public.has_capability((storage.foldername(name))[1]::uuid, 'generate_proposals')
);

DROP POLICY IF EXISTS "Proposal users can update estimate attachments" ON storage.objects;
CREATE POLICY "Proposal users can update estimate attachments" ON storage.objects
FOR UPDATE TO authenticated
USING (
  bucket_id = 'estimate-attachments'
  AND public.has_capability((storage.foldername(name))[1]::uuid, 'generate_proposals')
)
WITH CHECK (
  bucket_id = 'estimate-attachments'
  AND public.has_capability((storage.foldername(name))[1]::uuid, 'generate_proposals')
);

-- -------------------------------------------------------------
-- Shared equipment inventory for the tracker
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.equipment_types (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  name text NOT NULL,
  total_owned integer NOT NULL DEFAULT 0 CHECK (total_owned >= 0),
  active boolean NOT NULL DEFAULT true,
  notes text,
  created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  updated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  UNIQUE (organization_id, name)
);

DROP TRIGGER IF EXISTS roomflow_equipment_types_updated_at ON public.equipment_types;
CREATE TRIGGER roomflow_equipment_types_updated_at
BEFORE UPDATE ON public.equipment_types
FOR EACH ROW EXECUTE FUNCTION public.roomflow_set_updated_at();

CREATE TABLE IF NOT EXISTS public.equipment_deployments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  job_id uuid REFERENCES public.jobs(id) ON DELETE SET NULL,
  customer_name text,
  location text,
  status text NOT NULL DEFAULT 'active',
  dropped_off_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  pickup_due_at timestamptz,
  picked_up_at timestamptz,
  notes text,
  created_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  updated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS equipment_deployments_org_status_idx
  ON public.equipment_deployments (organization_id, status, dropped_off_at DESC);
DROP TRIGGER IF EXISTS roomflow_equipment_deployments_updated_at ON public.equipment_deployments;
CREATE TRIGGER roomflow_equipment_deployments_updated_at
BEFORE UPDATE ON public.equipment_deployments
FOR EACH ROW EXECUTE FUNCTION public.roomflow_set_updated_at();

CREATE TABLE IF NOT EXISTS public.equipment_deployment_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  deployment_id uuid NOT NULL REFERENCES public.equipment_deployments(id) ON DELETE CASCADE,
  equipment_type_id uuid NOT NULL REFERENCES public.equipment_types(id) ON DELETE RESTRICT,
  quantity integer NOT NULL CHECK (quantity > 0),
  created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  UNIQUE (deployment_id, equipment_type_id)
);

-- -------------------------------------------------------------
-- Follow-up sequences and delivery queue
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.outreach_sequences (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  name text NOT NULL,
  trigger_event text NOT NULL DEFAULT 'estimate_sent',
  active boolean NOT NULL DEFAULT true,
  steps jsonb NOT NULL DEFAULT '[
    {"step":1,"delay_days":2,"subject":"Checking that you received your estimate","body":"Hi {{first_name}}, I wanted to make sure you received estimate {{estimate_number}}. Please let us know if you have any questions."},
    {"step":2,"delay_days":5,"subject":"Questions about your estimate?","body":"Hi {{first_name}}, I am checking in regarding estimate {{estimate_number}}. We would be happy to review the scope, pricing, or scheduling options with you."},
    {"step":3,"delay_days":9,"subject":"Estimate follow-up","body":"Hi {{first_name}}, are you still considering moving forward with estimate {{estimate_number}}? Let us know if there is anything we can clarify."},
    {"step":4,"delay_days":14,"subject":"Final scheduled estimate check-in","body":"Hi {{first_name}}, this is our final scheduled check-in for estimate {{estimate_number}}. We will keep it on file whenever you are ready."}
  ]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  updated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  UNIQUE (organization_id, name)
);

DROP TRIGGER IF EXISTS roomflow_outreach_sequences_updated_at ON public.outreach_sequences;
CREATE TRIGGER roomflow_outreach_sequences_updated_at
BEFORE UPDATE ON public.outreach_sequences
FOR EACH ROW EXECUTE FUNCTION public.roomflow_set_updated_at();

CREATE TABLE IF NOT EXISTS public.outreach_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  job_id uuid NOT NULL REFERENCES public.jobs(id) ON DELETE CASCADE,
  estimate_id uuid REFERENCES public.estimates(id) ON DELETE CASCADE,
  sequence_id uuid REFERENCES public.outreach_sequences(id) ON DELETE SET NULL,
  sequence_step integer,
  channel text NOT NULL DEFAULT 'email',
  recipient text NOT NULL,
  subject text,
  body text NOT NULL,
  status text NOT NULL DEFAULT 'scheduled',
  scheduled_at timestamptz NOT NULL,
  sent_at timestamptz,
  provider_message_id text,
  error_message text,
  created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  updated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS outreach_due_idx
  ON public.outreach_messages (status, scheduled_at)
  WHERE status = 'scheduled';
DROP TRIGGER IF EXISTS roomflow_outreach_messages_updated_at ON public.outreach_messages;
CREATE TRIGGER roomflow_outreach_messages_updated_at
BEFORE UPDATE ON public.outreach_messages
FOR EACH ROW EXECUTE FUNCTION public.roomflow_set_updated_at();

-- -------------------------------------------------------------
-- RLS
-- -------------------------------------------------------------
ALTER TABLE public.integration_endpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lead_imports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.job_status_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.estimate_catalog_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.estimates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.estimate_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.estimate_attachments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outreach_sequences ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outreach_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.equipment_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.equipment_deployments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.equipment_deployment_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Members can view integration endpoints" ON public.integration_endpoints;
CREATE POLICY "Members can view integration endpoints" ON public.integration_endpoints
FOR SELECT TO authenticated
USING (public.roomflow_is_org_member(organization_id) AND public.has_capability(organization_id, 'manage_integrations'));

DROP POLICY IF EXISTS "Managers can manage integration endpoints" ON public.integration_endpoints;
CREATE POLICY "Managers can manage integration endpoints" ON public.integration_endpoints
FOR ALL TO authenticated
USING (public.roomflow_is_org_member(organization_id) AND public.has_capability(organization_id, 'manage_integrations'))
WITH CHECK (public.roomflow_is_org_member(organization_id) AND public.has_capability(organization_id, 'manage_integrations'));

DROP POLICY IF EXISTS "Members can view lead imports" ON public.lead_imports;
CREATE POLICY "Members can view lead imports" ON public.lead_imports
FOR SELECT TO authenticated
USING (public.roomflow_is_org_member(organization_id));

DROP POLICY IF EXISTS "Members can view job status events" ON public.job_status_events;
CREATE POLICY "Members can view job status events" ON public.job_status_events
FOR SELECT TO authenticated
USING (public.roomflow_is_org_member(organization_id));

DROP POLICY IF EXISTS "Members can add job status events" ON public.job_status_events;
CREATE POLICY "Members can add job status events" ON public.job_status_events
FOR INSERT TO authenticated
WITH CHECK (public.roomflow_is_org_member(organization_id));

DROP POLICY IF EXISTS "Members can view estimate catalog" ON public.estimate_catalog_items;
CREATE POLICY "Members can view estimate catalog" ON public.estimate_catalog_items
FOR SELECT TO authenticated
USING (public.roomflow_is_org_member(organization_id));

DROP POLICY IF EXISTS "Catalog managers can edit estimate catalog" ON public.estimate_catalog_items;
CREATE POLICY "Catalog managers can edit estimate catalog" ON public.estimate_catalog_items
FOR ALL TO authenticated
USING (public.has_capability(organization_id, 'manage_catalog'))
WITH CHECK (public.has_capability(organization_id, 'manage_catalog'));

DROP POLICY IF EXISTS "Members can view estimates" ON public.estimates;
CREATE POLICY "Members can view estimates" ON public.estimates
FOR SELECT TO authenticated
USING (public.roomflow_is_org_member(organization_id));

DROP POLICY IF EXISTS "Authorized users can manage estimates" ON public.estimates;
CREATE POLICY "Authorized users can manage estimates" ON public.estimates
FOR ALL TO authenticated
USING (public.has_capability(organization_id, 'generate_proposals'))
WITH CHECK (public.has_capability(organization_id, 'generate_proposals'));

DROP POLICY IF EXISTS "Members can view estimate lines" ON public.estimate_lines;
CREATE POLICY "Members can view estimate lines" ON public.estimate_lines
FOR SELECT TO authenticated
USING (EXISTS (
  SELECT 1 FROM public.estimates e
  WHERE e.id = estimate_id AND public.roomflow_is_org_member(e.organization_id)
));

DROP POLICY IF EXISTS "Authorized users can manage estimate lines" ON public.estimate_lines;
CREATE POLICY "Authorized users can manage estimate lines" ON public.estimate_lines
FOR ALL TO authenticated
USING (EXISTS (
  SELECT 1 FROM public.estimates e
  WHERE e.id = estimate_id AND public.has_capability(e.organization_id, 'generate_proposals')
))
WITH CHECK (EXISTS (
  SELECT 1 FROM public.estimates e
  WHERE e.id = estimate_id AND public.has_capability(e.organization_id, 'generate_proposals')
));

DROP POLICY IF EXISTS "Members can view estimate attachments" ON public.estimate_attachments;
CREATE POLICY "Members can view estimate attachments" ON public.estimate_attachments
FOR SELECT TO authenticated
USING (EXISTS (
  SELECT 1 FROM public.estimates e
  WHERE e.id = estimate_id AND public.roomflow_is_org_member(e.organization_id)
));

DROP POLICY IF EXISTS "Authorized users can manage estimate attachments" ON public.estimate_attachments;
CREATE POLICY "Authorized users can manage estimate attachments" ON public.estimate_attachments
FOR ALL TO authenticated
USING (EXISTS (
  SELECT 1 FROM public.estimates e
  WHERE e.id = estimate_id AND public.has_capability(e.organization_id, 'generate_proposals')
))
WITH CHECK (EXISTS (
  SELECT 1 FROM public.estimates e
  WHERE e.id = estimate_id AND public.has_capability(e.organization_id, 'generate_proposals')
));

DROP POLICY IF EXISTS "Members can view outreach sequences" ON public.outreach_sequences;
CREATE POLICY "Members can view outreach sequences" ON public.outreach_sequences
FOR SELECT TO authenticated
USING (public.roomflow_is_org_member(organization_id));

DROP POLICY IF EXISTS "Managers can manage outreach sequences" ON public.outreach_sequences;
CREATE POLICY "Managers can manage outreach sequences" ON public.outreach_sequences
FOR ALL TO authenticated
USING (public.has_capability(organization_id, 'manage_outreach'))
WITH CHECK (public.has_capability(organization_id, 'manage_outreach'));

DROP POLICY IF EXISTS "Members can view outreach messages" ON public.outreach_messages;
CREATE POLICY "Members can view outreach messages" ON public.outreach_messages
FOR SELECT TO authenticated
USING (public.roomflow_is_org_member(organization_id));

DROP POLICY IF EXISTS "Managers can manage outreach messages" ON public.outreach_messages;
CREATE POLICY "Managers can manage outreach messages" ON public.outreach_messages
FOR ALL TO authenticated
USING (public.has_capability(organization_id, 'manage_outreach'))
WITH CHECK (public.has_capability(organization_id, 'manage_outreach'));

-- Correct the existing ambiguous policies. These were comparing a column to itself.
DROP POLICY IF EXISTS "Members can view customers" ON public.customers;
CREATE POLICY "Members can view customers" ON public.customers
FOR SELECT TO authenticated
USING (public.roomflow_is_org_member(customers.organization_id));

DROP POLICY IF EXISTS "Members can view jobs if authorized" ON public.jobs;
CREATE POLICY "Members can view jobs if authorized" ON public.jobs
FOR SELECT TO authenticated
USING (
  public.roomflow_is_org_member(jobs.organization_id)
  AND (
    public.has_capability(jobs.organization_id, 'view_company_jobs')
    OR jobs.assigned_user_id = auth.uid()
  )
);

DROP POLICY IF EXISTS "Members can view catalog materials" ON public.material_catalog;
CREATE POLICY "Members can view catalog materials" ON public.material_catalog
FOR SELECT TO authenticated
USING (public.roomflow_is_org_member(material_catalog.organization_id));

DROP POLICY IF EXISTS "Members can view work orders" ON public.work_orders;
CREATE POLICY "Members can view work orders" ON public.work_orders
FOR SELECT TO authenticated
USING (public.roomflow_is_org_member(work_orders.organization_id));

DROP POLICY IF EXISTS "Members can view equipment types" ON public.equipment_types;
CREATE POLICY "Members can view equipment types" ON public.equipment_types
FOR SELECT TO authenticated
USING (public.roomflow_is_org_member(organization_id));

DROP POLICY IF EXISTS "Managers can manage equipment types" ON public.equipment_types;
CREATE POLICY "Managers can manage equipment types" ON public.equipment_types
FOR ALL TO authenticated
USING (public.has_capability(organization_id, 'edit_job_information'))
WITH CHECK (public.has_capability(organization_id, 'edit_job_information'));

DROP POLICY IF EXISTS "Members can view equipment deployments" ON public.equipment_deployments;
CREATE POLICY "Members can view equipment deployments" ON public.equipment_deployments
FOR SELECT TO authenticated
USING (public.roomflow_is_org_member(organization_id));

DROP POLICY IF EXISTS "Members can manage equipment deployments" ON public.equipment_deployments;
CREATE POLICY "Members can manage equipment deployments" ON public.equipment_deployments
FOR ALL TO authenticated
USING (public.has_capability(organization_id, 'edit_job_information'))
WITH CHECK (public.has_capability(organization_id, 'edit_job_information'));

DROP POLICY IF EXISTS "Members can view equipment deployment items" ON public.equipment_deployment_items;
CREATE POLICY "Members can view equipment deployment items" ON public.equipment_deployment_items
FOR SELECT TO authenticated
USING (EXISTS (
  SELECT 1 FROM public.equipment_deployments d
  WHERE d.id = deployment_id AND public.roomflow_is_org_member(d.organization_id)
));

DROP POLICY IF EXISTS "Members can manage equipment deployment items" ON public.equipment_deployment_items;
CREATE POLICY "Members can manage equipment deployment items" ON public.equipment_deployment_items
FOR ALL TO authenticated
USING (EXISTS (
  SELECT 1 FROM public.equipment_deployments d
  WHERE d.id = deployment_id AND public.has_capability(d.organization_id, 'edit_job_information')
))
WITH CHECK (EXISTS (
  SELECT 1 FROM public.equipment_deployments d
  WHERE d.id = deployment_id AND public.has_capability(d.organization_id, 'edit_job_information')
));

GRANT SELECT, INSERT, UPDATE, DELETE ON public.integration_endpoints TO authenticated;
GRANT SELECT ON public.lead_imports TO authenticated;
GRANT SELECT, INSERT ON public.job_status_events TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.estimate_catalog_items TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.estimates TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.estimate_lines TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.estimate_attachments TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.outreach_sequences TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.outreach_messages TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.equipment_types TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.equipment_deployments TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.equipment_deployment_items TO authenticated;


-- Keep outreach state synchronized when staff changes a job status from
-- RoomFlow or the external tracker.
CREATE OR REPLACE FUNCTION public.roomflow_prepare_job_followup_state()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.status = 'Customer Replied' THEN
    NEW.followup_status := 'paused';
  ELSIF NEW.status IN (
    'Approved','Declined','Work Scheduled','In Progress','Completed',
    'Invoiced','Paid','Service Not Needed'
  ) THEN
    NEW.followup_status := 'completed';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS roomflow_prepare_job_followup_state ON public.jobs;
CREATE TRIGGER roomflow_prepare_job_followup_state
BEFORE UPDATE OF status ON public.jobs
FOR EACH ROW
EXECUTE FUNCTION public.roomflow_prepare_job_followup_state();

CREATE OR REPLACE FUNCTION public.roomflow_cancel_outreach_for_job_state()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF NEW.status IN (
    'Customer Replied','Approved','Declined','Work Scheduled','In Progress',
    'Completed','Invoiced','Paid','Service Not Needed'
  ) THEN
    UPDATE public.outreach_messages
    SET
      status = 'cancelled',
      error_message = 'Stopped by job status: ' || NEW.status,
      updated_at = timezone('utc'::text, now())
    WHERE job_id = NEW.id
      AND status IN ('scheduled', 'ready_for_zapier');

    IF NEW.status = 'Approved' THEN
      UPDATE public.estimates
      SET status = 'accepted',
          accepted_at = COALESCE(accepted_at, timezone('utc'::text, now()))
      WHERE job_id = NEW.id
        AND status NOT IN ('accepted', 'declined', 'void');
    ELSIF NEW.status IN ('Declined', 'Service Not Needed') THEN
      UPDATE public.estimates
      SET status = 'declined',
          declined_at = COALESCE(declined_at, timezone('utc'::text, now()))
      WHERE job_id = NEW.id
        AND status NOT IN ('accepted', 'declined', 'void');
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS roomflow_cancel_outreach_for_job_state ON public.jobs;
CREATE TRIGGER roomflow_cancel_outreach_for_job_state
AFTER UPDATE OF status ON public.jobs
FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION public.roomflow_cancel_outreach_for_job_state();

-- Realtime updates for tracker and RoomFlow dashboards.
DO $$
BEGIN
  BEGIN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.jobs;
  EXCEPTION WHEN duplicate_object THEN NULL;
  END;
  BEGIN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.lead_imports;
  EXCEPTION WHEN duplicate_object THEN NULL;
  END;
  BEGIN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.job_status_events;
  EXCEPTION WHEN duplicate_object THEN NULL;
  END;
  BEGIN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.estimates;
  EXCEPTION WHEN duplicate_object THEN NULL;
  END;
  BEGIN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.equipment_deployments;
  EXCEPTION WHEN duplicate_object THEN NULL;
  END;
END $$;

-- Default follow-up sequence for every existing company.
INSERT INTO public.outreach_sequences (organization_id, name)
SELECT o.id, 'Standard Estimate Follow-up'
FROM public.organizations o
ON CONFLICT (organization_id, name) DO NOTHING;
