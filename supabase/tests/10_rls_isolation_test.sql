-- Run after migrations. Every block raises on failure; prints PASS lines on success.
\set ON_ERROR_STOP on
set client_min_messages = notice;

insert into auth.users values ('00000000-0000-0000-0000-0000000000a1','a@a.example'),
                              ('00000000-0000-0000-0000-0000000000b1','b@b.example'),
                              ('00000000-0000-0000-0000-0000000000a2','a2@a.example');
insert into nexus.tenants (id, name, legal_name, cnpj_roots, plan_code) values
  ('aaaaaaaa-0000-0000-0000-000000000000','A','Empresa A S.A.',array['11111111'],'ENTERPRISE'),
  ('bbbbbbbb-0000-0000-0000-000000000000','B','Empresa B S.A.',array['22222222'],'ESSENTIALS');
insert into nexus.memberships (tenant_id, user_id, role) values
  ('aaaaaaaa-0000-0000-0000-000000000000','00000000-0000-0000-0000-0000000000a1','tax_director'),
  ('aaaaaaaa-0000-0000-0000-000000000000','00000000-0000-0000-0000-0000000000a2','tax_analyst'),
  ('bbbbbbbb-0000-0000-0000-000000000000','00000000-0000-0000-0000-0000000000b1','tax_director');
insert into nexus.tax_rules (code, version, name, category, valid_from, methodology, legal_basis, legal_review_status)
values ('NX-T-001', 1, 't', 'RECONCILIATION', '2020-01-01', 'm', 'l', 'NOT_REQUIRED');

-- engine writes data for tenant A, then for tenant B, each inside its own declared tenant context
create role engine_login login in role nexus_engine;
set role engine_login;
begin;
select set_config('nexus.service_tenant', 'aaaaaaaa-0000-0000-0000-000000000000', true);
insert into nexus.ingestion_batches (id, tenant_id, source_type, filename, sha256, size_bytes, created_by)
  values ('a0000000-0000-0000-0000-000000000001','aaaaaaaa-0000-0000-0000-000000000000','LEDGER','a.csv', repeat('a',64), 1,
          '00000000-0000-0000-0000-0000000000a1');
insert into nexus.analysis_runs (id, tenant_id, trigger, started_by, engine_version)
  values ('a1000000-0000-0000-0000-000000000001','aaaaaaaa-0000-0000-0000-000000000000','MANUAL','00000000-0000-0000-0000-0000000000a1','t');
insert into nexus.findings (id, tenant_id, seq, fingerprint, first_run_id, last_run_id, rule_code, rule_version, category,
  kind, severity, title, description, methodology, legal_basis, confidence, amount_type, estimated_amount)
  values ('af000000-0000-0000-0000-000000000001','aaaaaaaa-0000-0000-0000-000000000000',1,'fp-a',
          'a1000000-0000-0000-0000-000000000001','a1000000-0000-0000-0000-000000000001','NX-T-001',1,'RECONCILIATION',
          'ESTIMATE','HIGH','A finding','d','m','l',0.7,'RECOVERABLE_ESTIMATE',1000);
-- cross-tenant write from tenant-A context must fail
do $$ begin
  insert into nexus.ingestion_batches (tenant_id, source_type, filename, sha256, size_bytes, created_by)
    values ('bbbbbbbb-0000-0000-0000-000000000000','LEDGER','x.csv', repeat('x',64), 1, gen_random_uuid());
  raise exception 'FAIL: engine wrote into another tenant';
exception when insufficient_privilege then raise notice 'PASS engine cannot write across tenants';
end $$;
commit;
begin;
select set_config('nexus.service_tenant', 'bbbbbbbb-0000-0000-0000-000000000000', true);
insert into nexus.ingestion_batches (tenant_id, source_type, filename, sha256, size_bytes, created_by)
  values ('bbbbbbbb-0000-0000-0000-000000000000','LEDGER','b.csv', repeat('b',64), 1, '00000000-0000-0000-0000-0000000000b1');
do $$ begin
  if (select count(*) from nexus.findings) <> 0 then raise exception 'FAIL: engine in B sees A findings'; end if;
  raise notice 'PASS engine context scoped to declared tenant';
end $$;
commit;
-- engine without declared tenant sees nothing
do $$ begin
  if (select count(*) from nexus.ingestion_batches) <> 0 then raise exception 'FAIL: engine without tenant sees data'; end if;
  raise notice 'PASS engine without tenant context sees nothing';
end $$;
reset role;

-- end users
set role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000000b1', false);
do $$ begin
  if (select count(*) from nexus.findings) <> 0 or (select count(*) from nexus.ingestion_batches) <> 1 then
    raise exception 'FAIL: user B sees tenant A data';
  end if;
  raise notice 'PASS user of tenant B cannot see tenant A';
end $$;
do $$ begin
  insert into nexus.findings (tenant_id, seq, fingerprint, first_run_id, last_run_id, rule_code, rule_version, category,
    kind, severity, title, description, methodology, legal_basis, confidence, amount_type)
    values ('bbbbbbbb-0000-0000-0000-000000000000', 9, 'x', gen_random_uuid(), gen_random_uuid(), 'NX-T-001', 1, 'X',
            'ALERT','LOW','t','d','m','l',0.5,'NONE');
  raise exception 'FAIL: end user inserted a finding directly';
exception when insufficient_privilege then raise notice 'PASS end users cannot write findings directly';
end $$;

-- analyst A proposes, cannot approve own proposal (DB-level segregation of duties)
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-0000000000a2', false);
do $$ begin
  if (select count(*) from nexus.findings) <> 1 then raise exception 'FAIL: analyst A cannot see own tenant'; end if;
  raise notice 'PASS analyst A sees tenant A';
end $$;
do $$ begin
  insert into nexus.finding_reviews (tenant_id, finding_id, actor_id, actor_name, actor_role, action, from_status, to_status, comment)
    values ('aaaaaaaa-0000-0000-0000-000000000000','af000000-0000-0000-0000-000000000001',
            '00000000-0000-0000-0000-0000000000a2','Analista','tax_analyst','approve','PENDING_APPROVAL','VALIDATED','aprovando sozinho');
  raise exception 'FAIL: analyst approved';
exception when insufficient_privilege or raise_exception then
  if sqlerrm like 'FAIL%' then raise; end if;
  raise notice 'PASS analyst cannot approve (%)', sqlerrm;
end $$;
reset role;

-- audit log: chain guard + immutability (as superuser, the strongest case)
insert into nexus.audit_log (tenant_id, seq, actor_id, actor_name, action, entity_type, entity_id, created_at, prev_hash, hash)
  values ('aaaaaaaa-0000-0000-0000-000000000000', 1, gen_random_uuid(), 'x', 'a', 'e', '1', now()::text, repeat('0',64), repeat('1',64));
do $$ begin
  insert into nexus.audit_log (tenant_id, seq, actor_id, actor_name, action, entity_type, entity_id, created_at, prev_hash, hash)
    values ('aaaaaaaa-0000-0000-0000-000000000000', 2, gen_random_uuid(), 'x', 'a', 'e', '1', now()::text, repeat('9',64), repeat('2',64));
  raise exception 'FAIL: forked chain accepted';
exception when raise_exception then
  if sqlerrm like 'FAIL%' then raise; end if;
  raise notice 'PASS audit chain rejects wrong prev_hash';
end $$;
do $$ begin
  update nexus.audit_log set actor_name = 'tampered';
  raise exception 'FAIL: audit update accepted';
exception when raise_exception then
  if sqlerrm like 'FAIL%' then raise; end if;
  raise notice 'PASS audit log is append-only';
end $$;
do $$ begin
  insert into nexus.tax_rules (code, version, name, category, valid_from, valid_to, methodology, legal_basis, legal_review_status)
    values ('NX-T-001', 2, 't', 'RECONCILIATION', '2021-01-01', null, 'm', 'l', 'NOT_REQUIRED');
  raise exception 'FAIL: overlapping rule validity accepted';
exception when exclusion_violation then raise notice 'PASS overlapping rule validity rejected';
end $$;
do $$ begin
  update nexus.findings set status = 'VALIDATED' where id = 'af000000-0000-0000-0000-000000000001';
  raise exception 'FAIL: validated status without validated kind';
exception when check_violation then raise notice 'PASS estimate cannot be marked validated inconsistently';
end $$;
