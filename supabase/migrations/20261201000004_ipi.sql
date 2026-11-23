-- NEXUS · 0004 · IPI credit support (industrial establishments)
alter table nexus.tenants add column if not exists ipi_taxpayer boolean not null default true;
alter table nexus.book_entries add column if not exists ipi_credit numeric(18,2) not null default 0;
