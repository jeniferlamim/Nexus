-- NEXUS · 0003 · Append-only, hash-chained audit trail
-- hash_n = sha256(prev_hash || canonical_json(entry_n)) — computed in the engine (audit/log.py)
-- and protected here against UPDATE/DELETE, gaps and forks.

create table nexus.audit_log (
  id          bigint generated always as identity primary key,
  tenant_id   uuid not null references nexus.tenants(id),
  seq         integer not null,
  actor_id    uuid not null,
  actor_name  text not null,
  action      text not null,
  entity_type text not null,
  entity_id   text not null,
  payload     jsonb not null default '{}'::jsonb,
  created_at  text not null,        -- ISO-8601 string, hashed verbatim
  prev_hash   char(64) not null,
  hash        char(64) not null,
  unique (tenant_id, seq),          -- concurrent writers cannot fork the chain
  unique (tenant_id, hash)
);

create trigger audit_log_immutable before update or delete on nexus.audit_log
  for each row execute function nexus.forbid_mutation();

-- Chain continuity: seq must be last+1 and prev_hash must equal the last hash.
create or replace function nexus.audit_chain_guard() returns trigger language plpgsql as $$
declare last nexus.audit_log%rowtype;
begin
  perform pg_advisory_xact_lock(hashtext('nexus.audit:' || new.tenant_id::text));
  select * into last from nexus.audit_log where tenant_id = new.tenant_id order by seq desc limit 1;
  if last.id is null then
    if new.seq <> 1 or new.prev_hash <> repeat('0', 64) then
      raise exception 'audit chain must start at seq 1 with genesis hash';
    end if;
  elsif new.seq <> last.seq + 1 or new.prev_hash <> last.hash then
    raise exception 'audit chain broken: expected seq % / prev %', last.seq + 1, last.hash;
  end if;
  return new;
end $$;
create trigger audit_log_chain before insert on nexus.audit_log
  for each row execute function nexus.audit_chain_guard();

alter table nexus.audit_log enable row level security;
alter table nexus.audit_log force row level security;
create policy audit_read on nexus.audit_log for select to authenticated
  using (nexus.has_permission(tenant_id, 'view_audit'));
create policy audit_engine on nexus.audit_log for all to nexus_engine
  using (nexus.is_member(tenant_id)) with check (nexus.is_member(tenant_id));
grant select on nexus.audit_log to authenticated;
grant select, insert on nexus.audit_log to nexus_engine;
revoke update, delete, truncate on nexus.audit_log from public, authenticated, nexus_engine;
