-- Complete cross-device RoomFlow job restoration.
-- Project geometry and protected costing are deliberately stored separately so
-- internal costs never inherit the broader job/layout read policy.

BEGIN;

ALTER TABLE public.estimate_lines
  ADD COLUMN IF NOT EXISTS roomflow_line_id text,
  ADD COLUMN IF NOT EXISTS category text NOT NULL DEFAULT 'other';

CREATE INDEX IF NOT EXISTS estimate_lines_roomflow_line_idx
  ON public.estimate_lines (estimate_id, roomflow_line_id);

CREATE TABLE IF NOT EXISTS public.job_project_snapshots (
  job_id uuid PRIMARY KEY REFERENCES public.jobs(id) ON DELETE CASCADE,
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  project_state jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (NOT (project_state ? 'costing')),
  client_updated_at timestamptz,
  updated_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  updated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS job_project_snapshots_org_updated_idx
  ON public.job_project_snapshots (organization_id, updated_at DESC);

DROP TRIGGER IF EXISTS roomflow_job_project_snapshots_updated_at ON public.job_project_snapshots;
CREATE TRIGGER roomflow_job_project_snapshots_updated_at
BEFORE UPDATE ON public.job_project_snapshots
FOR EACH ROW EXECUTE FUNCTION public.roomflow_set_updated_at();

CREATE TABLE IF NOT EXISTS public.job_costing_snapshots (
  job_id uuid PRIMARY KEY REFERENCES public.jobs(id) ON DELETE CASCADE,
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  costing_state jsonb NOT NULL DEFAULT '{}'::jsonb,
  client_updated_at timestamptz,
  updated_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
  updated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS job_costing_snapshots_org_updated_idx
  ON public.job_costing_snapshots (organization_id, updated_at DESC);

DROP TRIGGER IF EXISTS roomflow_job_costing_snapshots_updated_at ON public.job_costing_snapshots;
CREATE TRIGGER roomflow_job_costing_snapshots_updated_at
BEFORE UPDATE ON public.job_costing_snapshots
FOR EACH ROW EXECUTE FUNCTION public.roomflow_set_updated_at();

ALTER TABLE public.job_project_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.job_costing_snapshots ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Authorized members can view project snapshots" ON public.job_project_snapshots;
CREATE POLICY "Authorized members can view project snapshots"
ON public.job_project_snapshots FOR SELECT TO authenticated
USING (EXISTS (
  SELECT 1
  FROM public.jobs j
  WHERE j.id = job_project_snapshots.job_id
    AND j.organization_id = job_project_snapshots.organization_id
    AND public.roomflow_is_org_member(j.organization_id)
    AND (public.has_capability(j.organization_id, 'view_company_jobs') OR j.assigned_user_id = auth.uid())
));

DROP POLICY IF EXISTS "Authorized members can create project snapshots" ON public.job_project_snapshots;
CREATE POLICY "Authorized members can create project snapshots"
ON public.job_project_snapshots FOR INSERT TO authenticated
WITH CHECK (EXISTS (
  SELECT 1
  FROM public.jobs j
  WHERE j.id = job_project_snapshots.job_id
    AND j.organization_id = job_project_snapshots.organization_id
    AND (
      public.has_capability(j.organization_id, 'edit_floor_plans')
      OR public.has_capability(j.organization_id, 'edit_job_information')
      OR j.assigned_user_id = auth.uid()
    )
));

DROP POLICY IF EXISTS "Authorized members can update project snapshots" ON public.job_project_snapshots;
CREATE POLICY "Authorized members can update project snapshots"
ON public.job_project_snapshots FOR UPDATE TO authenticated
USING (EXISTS (
  SELECT 1
  FROM public.jobs j
  WHERE j.id = job_project_snapshots.job_id
    AND j.organization_id = job_project_snapshots.organization_id
    AND (
      public.has_capability(j.organization_id, 'edit_floor_plans')
      OR public.has_capability(j.organization_id, 'edit_job_information')
      OR j.assigned_user_id = auth.uid()
    )
))
WITH CHECK (EXISTS (
  SELECT 1
  FROM public.jobs j
  WHERE j.id = job_project_snapshots.job_id
    AND j.organization_id = job_project_snapshots.organization_id
    AND (
      public.has_capability(j.organization_id, 'edit_floor_plans')
      OR public.has_capability(j.organization_id, 'edit_job_information')
      OR j.assigned_user_id = auth.uid()
    )
));

DROP POLICY IF EXISTS "Authorized members can delete project snapshots" ON public.job_project_snapshots;
CREATE POLICY "Authorized members can delete project snapshots"
ON public.job_project_snapshots FOR DELETE TO authenticated
USING (public.has_capability(organization_id, 'delete_jobs'));

-- A full costing snapshot includes internal costs, sell prices, and margin settings.
-- Reading or writing it therefore requires every corresponding capability.
DROP POLICY IF EXISTS "Financial managers can view costing snapshots" ON public.job_costing_snapshots;
CREATE POLICY "Financial managers can view costing snapshots"
ON public.job_costing_snapshots FOR SELECT TO authenticated
USING (
  public.roomflow_is_org_member(organization_id)
  AND public.has_capability(organization_id, 'view_internal_costs')
  AND public.has_capability(organization_id, 'view_customer_prices')
  AND public.has_capability(organization_id, 'view_margin')
  AND EXISTS (
    SELECT 1 FROM public.jobs j
    WHERE j.id = job_costing_snapshots.job_id
      AND j.organization_id = job_costing_snapshots.organization_id
      AND (public.has_capability(j.organization_id, 'view_company_jobs') OR j.assigned_user_id = auth.uid())
  )
);

DROP POLICY IF EXISTS "Financial managers can create costing snapshots" ON public.job_costing_snapshots;
CREATE POLICY "Financial managers can create costing snapshots"
ON public.job_costing_snapshots FOR INSERT TO authenticated
WITH CHECK (
  public.has_capability(organization_id, 'edit_internal_costs')
  AND public.has_capability(organization_id, 'edit_customer_prices')
  AND public.has_capability(organization_id, 'edit_margin')
  AND EXISTS (
    SELECT 1 FROM public.jobs j
    WHERE j.id = job_costing_snapshots.job_id
      AND j.organization_id = job_costing_snapshots.organization_id
  )
);

DROP POLICY IF EXISTS "Financial managers can update costing snapshots" ON public.job_costing_snapshots;
CREATE POLICY "Financial managers can update costing snapshots"
ON public.job_costing_snapshots FOR UPDATE TO authenticated
USING (
  public.has_capability(organization_id, 'edit_internal_costs')
  AND public.has_capability(organization_id, 'edit_customer_prices')
  AND public.has_capability(organization_id, 'edit_margin')
)
WITH CHECK (
  public.has_capability(organization_id, 'edit_internal_costs')
  AND public.has_capability(organization_id, 'edit_customer_prices')
  AND public.has_capability(organization_id, 'edit_margin')
  AND EXISTS (
    SELECT 1 FROM public.jobs j
    WHERE j.id = job_costing_snapshots.job_id
      AND j.organization_id = job_costing_snapshots.organization_id
  )
);

DROP POLICY IF EXISTS "Financial managers can delete costing snapshots" ON public.job_costing_snapshots;
CREATE POLICY "Financial managers can delete costing snapshots"
ON public.job_costing_snapshots FOR DELETE TO authenticated
USING (public.has_capability(organization_id, 'delete_jobs'));

GRANT SELECT, INSERT, UPDATE, DELETE ON public.job_project_snapshots TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.job_costing_snapshots TO authenticated;

COMMIT;
