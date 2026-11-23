-- NEXUS · 0002 · Ingestion, normalised fiscal data, findings and review workflow
-- Every business table carries tenant_id and is protected by RLS through nexus.is_member().

create table nexus.ingestion_batches (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references nexus.tenants(id),
  source_type       text not null check (source_type in ('NFE_XML','FISCAL_BOOK','LEDGER')),
  filename          text not null,
  sha256            char(64) not null,
  size_bytes        bigint not null,
  storage_path      text,            -- encrypted object storage; null when raw file is not retained
  status            text not null default 'QUEUED'
                    check (status in ('QUEUED','RUNNING','COMPLETED','COMPLETED_WITH_WARNINGS','FAILED')),
  stages            jsonb not null default '[]'::jsonb,
  records_total     integer not null default 0,
  records_valid     integer not null default 0,
  records_rejected  integer not null default 0,
  warnings          integer not null default 0,
  periods           text[] not null default '{}',
  error             text,
  analysis_run_id   uuid,
  created_by        uuid not null,
  created_at        timestamptz not null default now(),
  finished_at       timestamptz,
  unique (tenant_id, sha256)                                   -- idempotent re-upload
);

create table nexus.batch_errors (
  id        bigint generated always as identity primary key,
  tenant_id uuid not null references nexus.tenants(id),
  batch_id  uuid not null references nexus.ingestion_batches(id) on delete cascade,
  source    text not null, locator text not null, field text not null, value text not null default '',
  message   text not null, severity text not null check (severity in ('BLOCKING','WARNING'))
);
create index on nexus.batch_errors (tenant_id, batch_id);

create table nexus.fiscal_documents (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references nexus.tenants(id),
  batch_id          uuid not null references nexus.ingestion_batches(id),
  access_key        char(44) not null check (access_key ~ '^[0-9]{44}$'),
  model             char(2) not null,
  series            text not null,
  number            text not null,
  issue_date        date not null,
  period            char(7) not null,
  issuer_cnpj       char(14) not null,
  issuer_name       text not null,
  issuer_uf         char(2) not null,
  recipient_doc     text not null,      -- CNPJ or masked CPF (LGPD minimisation)
  recipient_uf      char(2) not null,
  operation_type    char(1) not null,
  total_amount      numeric(18,2) not null,
  icms_total        numeric(18,2) not null,
  status            text not null,
  has_ibs_cbs_group boolean not null default false,
  source_file       text not null,
  unique (tenant_id, access_key)
);
create index on nexus.fiscal_documents (tenant_id, period);
create index on nexus.fiscal_documents (tenant_id, issuer_cnpj);

-- Production: partition by RANGE(period) / HASH(tenant_id) when volume exceeds ~100M rows.
create table nexus.fiscal_document_items (
  id             bigint generated always as identity primary key,
  tenant_id      uuid not null references nexus.tenants(id),
  document_id    uuid not null references nexus.fiscal_documents(id) on delete cascade,
  item_number    integer not null,
  product_code   text not null, description text not null,
  ncm            char(8) not null default '', cfop char(4) not null,
  quantity       numeric(18,4) not null, gross_amount numeric(18,2) not null, discount numeric(18,2) not null default 0,
  icms_cst       text not null default '', icms_base numeric(18,2) not null default 0,
  icms_rate      numeric(7,4) not null default 0, icms_amount numeric(18,2) not null default 0,
  ipi_amount     numeric(18,2) not null default 0,
  pis_cst        text not null default '', pis_amount numeric(18,2) not null default 0,
  cofins_cst     text not null default '', cofins_amount numeric(18,2) not null default 0,
  ibs_cbs_base   numeric(18,2), ibs_amount numeric(18,2), cbs_amount numeric(18,2),
  unique (document_id, item_number)
);
create index on nexus.fiscal_document_items (tenant_id, ncm);

create table nexus.book_entries (
  id                bigint generated always as identity primary key,
  tenant_id         uuid not null references nexus.tenants(id),
  batch_id          uuid not null references nexus.ingestion_batches(id),
  access_key        char(44) not null,
  document_number   text not null default '',
  entry_date        date not null,
  period            char(7) not null,
  direction         text not null check (direction in ('INBOUND','OUTBOUND')),
  counterparty_cnpj char(14) not null,
  item_number       integer not null,
  cfop              char(4) not null,
  ncm               text not null default '',
  amount            numeric(18,2) not null,
  icms_base         numeric(18,2) not null default 0,
  icms_credit       numeric(18,2) not null default 0,
  pis_credit        numeric(18,2) not null default 0,
  cofins_credit     numeric(18,2) not null default 0,
  pis_cst           text not null default '',
  source_file       text not null,
  source_row        integer not null
);
create index on nexus.book_entries (tenant_id, access_key);
create index on nexus.book_entries (tenant_id, period);

create table nexus.ledger_entries (
  id           bigint generated always as identity primary key,
  tenant_id    uuid not null references nexus.tenants(id),
  batch_id     uuid not null references nexus.ingestion_batches(id),
  entry_date   date not null,
  period       char(7) not null,
  account      text not null, account_name text not null default '', history text not null default '',
  debit        numeric(18,2) not null default 0,
  credit       numeric(18,2) not null default 0,
  access_key   text not null default '',
  source_file  text not null, source_row integer not null
);
create index on nexus.ledger_entries (tenant_id, period, account);

-- ----------------------------------------------------------------------------- rules & analysis

-- Global, versioned rule catalog (not tenant-scoped). Mirrors rules/catalog.py; synced on deploy.
create table nexus.tax_rules (
  code                 text not null,
  version              integer not null,
  name                 text not null,
  category             text not null,
  valid_from           date not null,
  valid_to             date,
  parameters           jsonb not null default '{}'::jsonb,
  methodology          text not null,
  legal_basis          text not null,
  legal_review_status  text not null check (legal_review_status in ('NOT_REQUIRED','RECOMMENDED','PENDING','APPROVED')),
  change_note          text not null default '',
  primary key (code, version),
  check (valid_to is null or valid_to >= valid_from)
);
-- no overlapping validity windows for the same rule
create extension if not exists btree_gist;
alter table nexus.tax_rules add constraint tax_rules_no_overlap
  exclude using gist (code with =, daterange(valid_from, coalesce(valid_to, 'infinity'::date), '[]') with &&);

create table nexus.analysis_runs (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references nexus.tenants(id),
  trigger           text not null,
  status            text not null default 'RUNNING',
  started_by        uuid not null,
  started_at        timestamptz not null default now(),
  finished_at       timestamptz,
  engine_version    text not null,
  stats             jsonb not null default '{}'::jsonb,
  rule_versions     jsonb not null default '{}'::jsonb,   -- {"NX-CRD-003": [1,2], ...}
  findings_total    integer not null default 0,
  findings_new      integer not null default 0,
  findings_resolved integer not null default 0,
  report            jsonb not null default '{}'::jsonb
);
create index on nexus.analysis_runs (tenant_id, started_at desc);

create table nexus.findings (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references nexus.tenants(id),
  seq               integer not null,
  fingerprint       text not null,
  first_run_id      uuid not null references nexus.analysis_runs(id),
  last_run_id       uuid not null references nexus.analysis_runs(id),
  is_active         boolean not null default true,
  rule_code         text not null,
  rule_version      integer not null,
  category          text not null,
  kind              text not null check (kind in ('ESTIMATE','ALERT','VALIDATED')),
  severity          text not null check (severity in ('CRITICAL','HIGH','MEDIUM','LOW','INFO')),
  title             text not null,
  description       text not null,
  methodology       text not null,
  legal_basis       text not null,
  confidence        real not null check (confidence > 0 and confidence <= 1),
  amount_type       text not null check (amount_type in ('RECOVERABLE_ESTIMATE','EXPOSURE_ESTIMATE','DIVERGENCE_VALUE','NONE')),
  estimated_amount  numeric(18,2) not null default 0,
  validated_amount  numeric(18,2),
  tax               text, access_key text, counterparty_cnpj text, counterparty_name text, period text,
  calculation       jsonb not null default '{}'::jsonb,
  status            text not null default 'OPEN'
                    check (status in ('OPEN','IN_REVIEW','PENDING_APPROVAL','VALIDATED','DISMISSED')),
  proposal          text check (proposal in ('VALIDATE','DISMISS')),
  proposed_by       uuid,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (tenant_id, fingerprint),
  unique (tenant_id, seq),
  foreign key (rule_code, rule_version) references nexus.tax_rules(code, version),
  -- an estimate is never "validated" without the VALIDATED status, and vice-versa
  check ((kind = 'VALIDATED') = (status = 'VALIDATED')),
  check (validated_amount is null or (status = 'VALIDATED' and validated_amount >= 0))
);
create index on nexus.findings (tenant_id, status);
create index on nexus.findings (tenant_id, category);
create index on nexus.findings (tenant_id, counterparty_cnpj);

create table nexus.finding_evidence (
  id          bigint generated always as identity primary key,
  tenant_id   uuid not null references nexus.tenants(id),
  finding_id  uuid not null references nexus.findings(id) on delete cascade,
  source text not null, locator text not null, field text not null, observed text not null,
  expected text not null default '', note text not null default ''
);
create index on nexus.finding_evidence (finding_id);

create table nexus.finding_reviews (
  id                bigint generated always as identity primary key,
  tenant_id         uuid not null references nexus.tenants(id),
  finding_id        uuid not null references nexus.findings(id),
  actor_id          uuid not null,
  actor_name        text not null,
  actor_role        nexus.app_role not null,
  action            text not null check (action in ('start_review','propose_validation','propose_dismissal',
                                                      'approve','return','reopen')),
  from_status       text not null,
  to_status         text not null,
  comment           text not null default '',
  validated_amount  numeric(18,2),
  created_at        timestamptz not null default now(),
  check (action = 'start_review' or length(trim(comment)) >= 10)
);
create index on nexus.finding_reviews (finding_id);

-- Segregation of duties enforced by the database, not only by the API.
create or replace function nexus.enforce_review_rules() returns trigger language plpgsql as $$
declare f nexus.findings%rowtype;
begin
  select * into f from nexus.findings where id = new.finding_id;
  if f.tenant_id <> new.tenant_id then
    raise exception 'tenant mismatch';
  end if;
  if new.action in ('approve','return','reopen')
     and not nexus.role_has_permission(new.actor_role, 'approve') then
    raise exception 'role % cannot %', new.actor_role, new.action;
  end if;
  if new.action = 'approve' and f.proposed_by = new.actor_id then
    raise exception 'segregation of duties: proposer cannot approve own proposal';
  end if;
  return new;
end $$;
create trigger finding_reviews_rules before insert on nexus.finding_reviews
  for each row execute function nexus.enforce_review_rules();

-- Reviews are an immutable history.
create or replace function nexus.forbid_mutation() returns trigger language plpgsql as $$
begin
  raise exception '% is append-only', tg_table_name;
end $$;
create trigger finding_reviews_immutable before update or delete on nexus.finding_reviews
  for each row execute function nexus.forbid_mutation();

-- ----------------------------------------------------------------------------- RLS
do $$
declare t text;
begin
  foreach t in array array['ingestion_batches','batch_errors','fiscal_documents','fiscal_document_items',
                           'book_entries','ledger_entries','analysis_runs','findings','finding_evidence',
                           'finding_reviews']
  loop
    execute format('alter table nexus.%I enable row level security', t);
    execute format('alter table nexus.%I force row level security', t);
    execute format('create policy %I on nexus.%I for select to authenticated, nexus_engine using (nexus.is_member(tenant_id))',
                   t || '_read', t);
    execute format('grant select on nexus.%I to authenticated', t);
    execute format('grant select, insert, update, delete on nexus.%I to nexus_engine', t);
    execute format('create policy %I on nexus.%I for all to nexus_engine using (nexus.is_member(tenant_id)) with check (nexus.is_member(tenant_id))',
                   t || '_engine_write', t);
  end loop;
end $$;

-- End users never write fiscal data directly (ingestion goes through the engine). The only direct
-- user writes are workflow decisions, gated by permission:
grant insert on nexus.finding_reviews to authenticated;
create policy finding_reviews_insert on nexus.finding_reviews for insert to authenticated
  with check (actor_id = auth.uid() and nexus.has_permission(tenant_id, 'review')
              and (action not in ('approve','return','reopen') or nexus.has_permission(tenant_id, 'approve')));

alter table nexus.tax_rules enable row level security;
create policy tax_rules_read on nexus.tax_rules for select to authenticated, nexus_engine using (true);
grant select on nexus.tax_rules to authenticated, nexus_engine;
grant usage on all sequences in schema nexus to nexus_engine;
