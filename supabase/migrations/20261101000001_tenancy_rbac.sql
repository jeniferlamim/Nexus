-- NEXUS · 0001 · Tenancy, plans, RBAC and isolation primitives
-- Target: Supabase (PostgreSQL 15+). Requires the `auth` schema provided by Supabase.

create schema if not exists nexus;
create extension if not exists pgcrypto;

-- Backend engine role: NO bypassrls. It must declare the tenant per transaction:
--   select set_config('nexus.service_tenant', '<tenant uuid>', true);
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'nexus_engine') then
    create role nexus_engine nologin;
  end if;
end $$;

create type nexus.app_role as enum ('admin', 'tax_director', 'tax_analyst', 'auditor', 'viewer');
create type nexus.permission as enum ('view', 'ingest', 'run_analysis', 'review', 'approve', 'view_audit',
                                      'export', 'manage_settings');

create table nexus.plans (
  code                 text primary key,
  name                 text not null,
  modules              text[] not null,
  max_documents_month  integer not null check (max_documents_month > 0),
  max_users            integer not null check (max_users > 0),
  max_file_mb          integer not null default 200
);

create table nexus.tenants (
  id                   uuid primary key default gen_random_uuid(),
  name                 text not null,
  legal_name           text not null,
  segment              text not null default '',
  cnpj_roots           text[] not null check (array_length(cnpj_roots, 1) >= 1),
  plan_code            text not null references nexus.plans(code),
  tax_regime           text not null default 'NON_CUMULATIVE' check (tax_regime in ('NON_CUMULATIVE', 'CUMULATIVE')),
  ledger_accounts      jsonb not null default '{}'::jsonb,
  data_retention_days  integer not null default 1825,
  created_at           timestamptz not null default now()
);

create table nexus.memberships (
  id         uuid primary key default gen_random_uuid(),
  tenant_id  uuid not null references nexus.tenants(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  role       nexus.app_role not null,
  created_at timestamptz not null default now(),
  unique (tenant_id, user_id)
);
create index on nexus.memberships (user_id);

-- Role → permission matrix (mirrors services/engine/nexus_engine/security/rbac.py)
create or replace function nexus.role_has_permission(r nexus.app_role, p nexus.permission)
returns boolean language sql immutable as $$
  select case r
    when 'admin'        then true
    when 'tax_director' then p in ('view','ingest','run_analysis','review','approve','view_audit','export')
    when 'tax_analyst'  then p in ('view','ingest','run_analysis','review','export')
    when 'auditor'      then p in ('view','view_audit','export')
    when 'viewer'       then p = 'view'
  end
$$;

-- Is the current caller allowed into tenant t?  (end user via membership, or engine via session setting)
create or replace function nexus.is_member(t uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (select 1 from nexus.memberships m where m.tenant_id = t and m.user_id = auth.uid())
      or (pg_has_role(current_user, 'nexus_engine', 'member')
          and nullif(current_setting('nexus.service_tenant', true), '')::uuid = t)
$$;

create or replace function nexus.has_permission(t uuid, p nexus.permission)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (select 1 from nexus.memberships m
                  where m.tenant_id = t and m.user_id = auth.uid() and nexus.role_has_permission(m.role, p))
      or (pg_has_role(current_user, 'nexus_engine', 'member')
          and nullif(current_setting('nexus.service_tenant', true), '')::uuid = t)
$$;

create or replace function nexus.has_module(t uuid, module text)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (select 1 from nexus.tenants tn join nexus.plans pl on pl.code = tn.plan_code
                  where tn.id = t and module = any(pl.modules))
$$;

alter table nexus.plans       enable row level security;
alter table nexus.tenants     enable row level security;
alter table nexus.memberships enable row level security;

create policy plans_read on nexus.plans for select to authenticated using (true);
create policy tenants_read on nexus.tenants for select to authenticated, nexus_engine using (nexus.is_member(id));
create policy tenants_update on nexus.tenants for update to authenticated
  using (nexus.has_permission(id, 'manage_settings')) with check (nexus.has_permission(id, 'manage_settings'));
create policy memberships_read on nexus.memberships for select to authenticated
  using (user_id = auth.uid() or nexus.has_permission(tenant_id, 'manage_settings'));
create policy memberships_admin on nexus.memberships for all to authenticated
  using (nexus.has_permission(tenant_id, 'manage_settings'))
  with check (nexus.has_permission(tenant_id, 'manage_settings'));

grant usage on schema nexus to authenticated, nexus_engine;
grant select on nexus.plans to authenticated, nexus_engine;
grant select, update on nexus.tenants to authenticated;
grant select on nexus.tenants to nexus_engine;
grant select, insert, update, delete on nexus.memberships to authenticated;

insert into nexus.plans (code, name, modules, max_documents_month, max_users, max_file_mb) values
  ('ESSENTIALS', 'Essentials', array['executive_dashboard','ingestion','tax_reconciliation','audit_trail'], 50000, 10, 100),
  ('PROFESSIONAL', 'Professional', array['executive_dashboard','ingestion','tax_reconciliation','tax_intelligence',
                                         'credit_recovery','tax_risk','audit_trail'], 250000, 40, 200),
  ('ENTERPRISE', 'Enterprise', array['executive_dashboard','ingestion','tax_reconciliation','tax_intelligence',
                                     'credit_recovery','tax_risk','audit_trail','tax_simulator','supplier_intelligence',
                                     'financial_intelligence','ai_copilot'], 2000000, 500, 500)
on conflict (code) do nothing;
