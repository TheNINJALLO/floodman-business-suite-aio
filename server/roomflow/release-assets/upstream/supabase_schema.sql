-- ==========================================
-- ROOMFLOW SUPABASE DATABASE SCHEMA MIGRATION
-- ==========================================

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Profiles (linked to auth.users)
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name TEXT,
    avatar_url TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Automatically create profile on user signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, full_name, avatar_url)
    VALUES (
        new.id,
        COALESCE(new.raw_user_meta_data->>'full_name', new.email),
        new.raw_user_meta_data->>'avatar_url'
    );
    RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE OR REPLACE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- 2. Organizations (Companies)
CREATE TABLE IF NOT EXISTS public.organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    logo_url TEXT,
    address TEXT,
    phone TEXT,
    email TEXT,
    license_info TEXT,
    default_estimator TEXT,
    default_proposal_terms TEXT,
    default_work_order_instructions TEXT,
    default_measurement_units TEXT DEFAULT 'us' NOT NULL,
    timezone TEXT DEFAULT 'America/Detroit' NOT NULL,
    colors JSONB DEFAULT '{"primary": "#3b82f6", "secondary": "#1e293b", "accent": "#14b8a6"}'::jsonb,
    code TEXT UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 3. Custom Roles
CREATE TABLE IF NOT EXISTS public.custom_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    is_system BOOLEAN DEFAULT false NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    UNIQUE(organization_id, name)
);

-- 4. Role Capabilities
CREATE TABLE IF NOT EXISTS public.role_capabilities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role_id UUID REFERENCES public.custom_roles(id) ON DELETE CASCADE NOT NULL,
    capability TEXT NOT NULL,
    UNIQUE(role_id, capability)
);

-- 5. Organization Members
CREATE TABLE IF NOT EXISTS public.organization_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE NOT NULL,
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE NOT NULL,
    role_id UUID REFERENCES public.custom_roles(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    UNIQUE(organization_id, user_id)
);

-- 6. Member Capability Overrides
CREATE TABLE IF NOT EXISTS public.member_capability_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID REFERENCES public.organization_members(id) ON DELETE CASCADE NOT NULL,
    capability TEXT NOT NULL,
    allowed BOOLEAN NOT NULL,
    UNIQUE(member_id, capability)
);

-- 7. Organization Groups (Teams)
CREATE TABLE IF NOT EXISTS public.organization_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    UNIQUE(organization_id, name)
);

-- 8. Organization Group Members
CREATE TABLE IF NOT EXISTS public.organization_group_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id UUID REFERENCES public.organization_groups(id) ON DELETE CASCADE NOT NULL,
    member_id UUID REFERENCES public.organization_members(id) ON DELETE CASCADE NOT NULL,
    UNIQUE(group_id, member_id)
);

-- 9. Organization Invitations
CREATE TABLE IF NOT EXISTS public.organization_invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE NOT NULL,
    email TEXT NOT NULL,
    role_id UUID REFERENCES public.custom_roles(id) ON DELETE SET NULL,
    invited_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    status TEXT DEFAULT 'pending'::text NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 10. Customers
CREATE TABLE IF NOT EXISTS public.customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE NOT NULL,
    name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 11. Jobs
CREATE TABLE IF NOT EXISTS public.jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE NOT NULL,
    customer_id UUID REFERENCES public.customers(id) ON DELETE CASCADE NOT NULL,
    name TEXT NOT NULL,
    status TEXT DEFAULT 'Draft'::text NOT NULL,
    current_version_number INTEGER DEFAULT 1 NOT NULL,
    assigned_user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    assigned_group_id UUID REFERENCES public.organization_groups(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 12. Job Layouts (Geometry footprints without financial costs)
CREATE TABLE IF NOT EXISTS public.job_layouts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES public.jobs(id) ON DELETE CASCADE NOT NULL,
    version_number INTEGER DEFAULT 1 NOT NULL,
    layout_json JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    UNIQUE(job_id, version_number)
);

-- 13. Material Catalog
CREATE TABLE IF NOT EXISTS public.material_catalog (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE NOT NULL,
    name TEXT NOT NULL,
    product_code TEXT,
    category TEXT NOT NULL,
    unit TEXT NOT NULL,
    waste_factor NUMERIC DEFAULT 10.0 NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    UNIQUE(organization_id, name)
);

-- 14. Material Costs (PROTECTED FINANCIAL TABLE)
CREATE TABLE IF NOT EXISTS public.material_costs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    material_id UUID REFERENCES public.material_catalog(id) ON DELETE CASCADE UNIQUE NOT NULL,
    unit_cost NUMERIC DEFAULT 0.0 NOT NULL,
    labor_cost NUMERIC DEFAULT 0.0 NOT NULL,
    rental_cost NUMERIC DEFAULT 0.0 NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 15. Job Pricing Config (PROTECTED FINANCIAL TABLE)
CREATE TABLE IF NOT EXISTS public.job_pricing (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES public.jobs(id) ON DELETE CASCADE UNIQUE NOT NULL,
    target_gross_margin NUMERIC DEFAULT 40.0 NOT NULL,
    sales_tax_rate NUMERIC DEFAULT 6.0 NOT NULL,
    additional_overhead_rate NUMERIC DEFAULT 15.0 NOT NULL,
    markup_override NUMERIC,
    commission_rate NUMERIC DEFAULT 0.0 NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 16. Work Orders
CREATE TABLE IF NOT EXISTS public.work_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES public.jobs(id) ON DELETE CASCADE NOT NULL,
    work_order_number TEXT UNIQUE NOT NULL,
    version_number INTEGER DEFAULT 1 NOT NULL,
    organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE NOT NULL,
    assigned_crew_id UUID REFERENCES public.organization_groups(id) ON DELETE SET NULL,
    planned_start_date DATE,
    expected_duration TEXT,
    general_instructions TEXT,
    parking_instructions TEXT,
    safety_notes TEXT,
    status TEXT DEFAULT 'Draft'::text NOT NULL,
    generated_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 17. Work Order Tasks
CREATE TABLE IF NOT EXISTS public.work_order_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    work_order_id UUID REFERENCES public.work_orders(id) ON DELETE CASCADE NOT NULL,
    room_name TEXT NOT NULL,
    task_code TEXT NOT NULL,
    instructions TEXT NOT NULL,
    required_materials JSONB DEFAULT '[]'::jsonb NOT NULL,
    sort_order INTEGER DEFAULT 0 NOT NULL
);

-- 18. Audit Logs
CREATE TABLE IF NOT EXISTS public.audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE,
    user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    details JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- ==========================================
-- SECURITY HELPER FUNCTIONS & RLS POLICIES
-- ==========================================

-- Function to check capability
CREATE OR REPLACE FUNCTION public.has_capability(org_id UUID, req_cap TEXT)
RETURNS BOOLEAN AS $$
DECLARE
    member_id UUID;
    role_id UUID;
    override_allowed BOOLEAN;
    has_cap BOOLEAN;
BEGIN
    SELECT id, m.role_id INTO member_id, role_id
    FROM public.organization_members m
    WHERE m.organization_id = org_id AND m.user_id = auth.uid();
    
    IF member_id IS NULL THEN
        RETURN FALSE;
    END IF;

    SELECT allowed INTO override_allowed
    FROM public.member_capability_overrides
    WHERE member_id = member_id AND capability = req_cap;

    IF override_allowed IS NOT NULL THEN
        RETURN override_allowed;
    END IF;

    SELECT EXISTS (
        SELECT 1 
        FROM public.role_capabilities rc
        WHERE rc.role_id = role_id AND rc.capability = req_cap
    ) INTO has_cap;

    RETURN has_cap;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Enable Row Level Security (RLS) on all tables
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.custom_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.role_capabilities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.member_capability_overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_group_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.job_layouts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.material_catalog ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.material_costs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.job_pricing ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.work_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.work_order_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;

-- Profiles Policies
DROP POLICY IF EXISTS "Public profiles are viewable by everyone" ON public.profiles;
CREATE POLICY "Public profiles are viewable by everyone" ON public.profiles FOR SELECT USING (true);
DROP POLICY IF EXISTS "Users can update their own profile" ON public.profiles;
CREATE POLICY "Users can update their own profile" ON public.profiles FOR UPDATE USING (auth.uid() = id);

-- Organizations Policies
DROP POLICY IF EXISTS "Members can view organization" ON public.organizations;
CREATE POLICY "Members can view organization" ON public.organizations
    FOR SELECT USING (EXISTS (SELECT 1 FROM public.organization_members m WHERE m.organization_id = public.organizations.id AND m.user_id = auth.uid()));
DROP POLICY IF EXISTS "Authenticated users can insert organization" ON public.organizations;
CREATE POLICY "Authenticated users can insert organization" ON public.organizations
    FOR INSERT WITH CHECK (auth.uid() IS NOT NULL);
DROP POLICY IF EXISTS "Owners can update organization settings" ON public.organizations;
CREATE POLICY "Owners can update organization settings" ON public.organizations
    FOR UPDATE USING (public.has_capability(id, 'manage_company'));

-- Members Policies
DROP POLICY IF EXISTS "Members can view other members in company" ON public.organization_members;
CREATE POLICY "Members can view other members in company" ON public.organization_members
    FOR SELECT USING (EXISTS (SELECT 1 FROM public.organization_members m WHERE m.organization_id = public.organization_members.organization_id AND m.user_id = auth.uid()));
DROP POLICY IF EXISTS "Users can insert membership" ON public.organization_members;
CREATE POLICY "Users can insert membership" ON public.organization_members
    FOR INSERT WITH CHECK (user_id = auth.uid() OR public.has_capability(organization_id, 'manage_members'));
DROP POLICY IF EXISTS "Admins can manage organization members" ON public.organization_members;
CREATE POLICY "Admins can manage organization members" ON public.organization_members
    FOR ALL USING (public.has_capability(organization_id, 'manage_members'));

-- Custom Roles Policies
DROP POLICY IF EXISTS "Members can select roles" ON public.custom_roles;
CREATE POLICY "Members can select roles" ON public.custom_roles
    FOR SELECT USING (EXISTS (SELECT 1 FROM public.organization_members m WHERE m.organization_id = public.custom_roles.organization_id AND m.user_id = auth.uid()));
DROP POLICY IF EXISTS "Authenticated users can insert roles" ON public.custom_roles;
CREATE POLICY "Authenticated users can insert roles" ON public.custom_roles
    FOR INSERT WITH CHECK (auth.uid() IS NOT NULL);
DROP POLICY IF EXISTS "Admins can edit custom roles" ON public.custom_roles;
CREATE POLICY "Admins can edit custom roles" ON public.custom_roles
    FOR ALL USING (public.has_capability(organization_id, 'manage_roles'));

-- Role Capabilities Policies
DROP POLICY IF EXISTS "Members can view capabilities" ON public.role_capabilities;
CREATE POLICY "Members can view capabilities" ON public.role_capabilities
    FOR SELECT USING (true);
DROP POLICY IF EXISTS "Authenticated users can insert capabilities" ON public.role_capabilities;
CREATE POLICY "Authenticated users can insert capabilities" ON public.role_capabilities
    FOR INSERT WITH CHECK (auth.uid() IS NOT NULL);

-- Customers Policies
DROP POLICY IF EXISTS "Members can view customers" ON public.customers;
CREATE POLICY "Members can view customers" ON public.customers
    FOR SELECT USING (EXISTS (SELECT 1 FROM public.organization_members WHERE organization_id = organization_id AND user_id = auth.uid()));
DROP POLICY IF EXISTS "Admins/Estimators can insert customers" ON public.customers;
CREATE POLICY "Admins/Estimators can insert customers" ON public.customers
    FOR INSERT WITH CHECK (public.has_capability(organization_id, 'create_jobs'));
DROP POLICY IF EXISTS "Admins/Estimators can update customers" ON public.customers;
CREATE POLICY "Admins/Estimators can update customers" ON public.customers
    FOR UPDATE USING (public.has_capability(organization_id, 'create_jobs'));

-- Jobs Policies
DROP POLICY IF EXISTS "Members can view jobs if authorized" ON public.jobs;
CREATE POLICY "Members can view jobs if authorized" ON public.jobs
    FOR SELECT USING (
        EXISTS (SELECT 1 FROM public.organization_members WHERE organization_id = organization_id AND user_id = auth.uid())
        AND (public.has_capability(organization_id, 'view_company_jobs') OR assigned_user_id = auth.uid())
    );
DROP POLICY IF EXISTS "Authorized members can create jobs" ON public.jobs;
CREATE POLICY "Authorized members can create jobs" ON public.jobs
    FOR INSERT WITH CHECK (public.has_capability(organization_id, 'create_jobs'));
DROP POLICY IF EXISTS "Authorized members can update jobs" ON public.jobs;
CREATE POLICY "Authorized members can update jobs" ON public.jobs
    FOR UPDATE USING (public.has_capability(organization_id, 'edit_job_information') OR assigned_user_id = auth.uid());
DROP POLICY IF EXISTS "Authorized members can delete jobs" ON public.jobs;
CREATE POLICY "Authorized members can delete jobs" ON public.jobs
    FOR DELETE USING (public.has_capability(organization_id, 'delete_jobs'));

-- Job Layouts Policies
DROP POLICY IF EXISTS "Members can view layouts" ON public.job_layouts;
CREATE POLICY "Members can view layouts" ON public.job_layouts
    FOR SELECT USING (EXISTS (
        SELECT 1 FROM public.jobs j
        JOIN public.organization_members m ON m.organization_id = j.organization_id
        WHERE j.id = job_id AND m.user_id = auth.uid()
    ));
DROP POLICY IF EXISTS "Designers can insert layouts" ON public.job_layouts;
CREATE POLICY "Designers can insert layouts" ON public.job_layouts
    FOR INSERT WITH CHECK (EXISTS (
        SELECT 1 FROM public.jobs j
        WHERE j.id = job_id AND (public.has_capability(j.organization_id, 'edit_floor_plans') OR j.assigned_user_id = auth.uid())
    ));
DROP POLICY IF EXISTS "Designers can update layouts" ON public.job_layouts;
CREATE POLICY "Designers can update layouts" ON public.job_layouts
    FOR UPDATE USING (EXISTS (
        SELECT 1 FROM public.jobs j
        WHERE j.id = job_id AND (public.has_capability(j.organization_id, 'edit_floor_plans') OR j.assigned_user_id = auth.uid())
    ));

-- Material Catalog Policies
DROP POLICY IF EXISTS "Members can view catalog materials" ON public.material_catalog;
CREATE POLICY "Members can view catalog materials" ON public.material_catalog
    FOR SELECT USING (EXISTS (SELECT 1 FROM public.organization_members WHERE organization_id = organization_id AND user_id = auth.uid()));

-- ====================================================
-- RLS POLICIES ENFORCING SEPARATED FINANCIAL DATA SECURITY
-- ====================================================

-- Material Costs: Restrict view access to users with 'view_internal_costs'
DROP POLICY IF EXISTS "Only authorized managers can view material costs" ON public.material_costs;
CREATE POLICY "Only authorized managers can view material costs" ON public.material_costs
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.material_catalog c
            JOIN public.organization_members m ON m.organization_id = c.organization_id
            WHERE c.id = material_id AND m.user_id = auth.uid()
            AND public.has_capability(c.organization_id, 'view_internal_costs')
        )
    );

DROP POLICY IF EXISTS "Only authorized managers can edit material costs" ON public.material_costs;
CREATE POLICY "Only authorized managers can edit material costs" ON public.material_costs
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.material_catalog c
            JOIN public.organization_members m ON m.organization_id = c.organization_id
            WHERE c.id = material_id AND m.user_id = auth.uid()
            AND public.has_capability(c.organization_id, 'edit_internal_costs')
        )
    );

-- Job Pricing: Restrict view access to users with 'view_customer_prices'
DROP POLICY IF EXISTS "Only authorized managers can view job pricing margins" ON public.job_pricing;
CREATE POLICY "Only authorized managers can view job pricing margins" ON public.job_pricing
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.jobs j
            JOIN public.organization_members m ON m.organization_id = j.organization_id
            WHERE j.id = job_id AND m.user_id = auth.uid()
            AND public.has_capability(j.organization_id, 'view_customer_prices')
        )
    );

DROP POLICY IF EXISTS "Only authorized managers can edit job pricing margins" ON public.job_pricing;
CREATE POLICY "Only authorized managers can edit job pricing margins" ON public.job_pricing
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.jobs j
            JOIN public.organization_members m ON m.organization_id = j.organization_id
            WHERE j.id = job_id AND m.user_id = auth.uid()
            AND public.has_capability(j.organization_id, 'edit_margin')
        )
    );

-- Work Orders Policies
DROP POLICY IF EXISTS "Members can view work orders" ON public.work_orders;
CREATE POLICY "Members can view work orders" ON public.work_orders
    FOR SELECT USING (EXISTS (SELECT 1 FROM public.organization_members WHERE organization_id = organization_id AND user_id = auth.uid()));
DROP POLICY IF EXISTS "Production managers can create work orders" ON public.work_orders;
CREATE POLICY "Production managers can create work orders" ON public.work_orders
    FOR INSERT WITH CHECK (public.has_capability(organization_id, 'generate_work_orders'));
DROP POLICY IF EXISTS "Production managers can update work orders" ON public.work_orders;
CREATE POLICY "Production managers can update work orders" ON public.work_orders
    FOR UPDATE USING (public.has_capability(organization_id, 'generate_work_orders'));

-- Audit Logs Policies
DROP POLICY IF EXISTS "Managers can view audit logs" ON public.audit_logs;
CREATE POLICY "Managers can view audit logs" ON public.audit_logs
    FOR SELECT USING (public.has_capability(organization_id, 'view_audit_logs'));
DROP POLICY IF EXISTS "System can record audit logs" ON public.audit_logs;
CREATE POLICY "System can record audit logs" ON public.audit_logs
    FOR INSERT WITH CHECK (true);

-- System Default Setup Function (Sets up Owner role & capabilities)
CREATE OR REPLACE FUNCTION public.create_new_company_with_owner(company_name TEXT, owner_id UUID)
RETURNS UUID AS $$
DECLARE
    new_org_id UUID;
    owner_role_id UUID;
BEGIN
    INSERT INTO public.organizations (name) VALUES (company_name) RETURNING id INTO new_org_id;

    INSERT INTO public.custom_roles (organization_id, name, description, is_system)
    VALUES (new_org_id, 'Company Owner', 'Full control over company settings and pricing', true)
    RETURNING id INTO owner_role_id;

    INSERT INTO public.role_capabilities (role_id, capability)
    VALUES 
        (owner_role_id, 'manage_company'),
        (owner_role_id, 'manage_members'),
        (owner_role_id, 'manage_roles'),
        (owner_role_id, 'manage_groups'),
        (owner_role_id, 'create_jobs'),
        (owner_role_id, 'view_company_jobs'),
        (owner_role_id, 'edit_job_information'),
        (owner_role_id, 'edit_floor_plans'),
        (owner_role_id, 'edit_measurements'),
        (owner_role_id, 'edit_job_scope'),
        (owner_role_id, 'upload_attachments'),
        (owner_role_id, 'view_material_quantities'),
        (owner_role_id, 'edit_material_quantities'),
        (owner_role_id, 'view_internal_costs'),
        (owner_role_id, 'edit_internal_costs'),
        (owner_role_id, 'view_customer_prices'),
        (owner_role_id, 'edit_customer_prices'),
        (owner_role_id, 'view_margin'),
        (owner_role_id, 'edit_margin'),
        (owner_role_id, 'generate_proposals'),
        (owner_role_id, 'approve_proposals'),
        (owner_role_id, 'generate_work_orders'),
        (owner_role_id, 'approve_work_orders'),
        (owner_role_id, 'assign_jobs'),
        (owner_role_id, 'manage_catalog'),
        (owner_role_id, 'delete_jobs'),
        (owner_role_id, 'restore_jobs'),
        (owner_role_id, 'view_audit_logs');

    INSERT INTO public.organization_members (organization_id, user_id, role_id)
    VALUES (new_org_id, owner_id, owner_role_id);

    RETURN new_org_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Grant Permissions for RPC Functions, Tables, and Sequences
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL ROUTINES IN SCHEMA public TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.create_new_company_with_owner(TEXT, UUID) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.has_capability(UUID, TEXT) TO anon, authenticated, service_role;
