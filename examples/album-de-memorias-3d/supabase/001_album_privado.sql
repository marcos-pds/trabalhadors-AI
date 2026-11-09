-- Executar uma única vez no SQL Editor do Supabase, com uma conta administradora.
-- O site GitHub Pages é público, mas o CONTEÚDO fica privado em RLS/Storage.
-- IMPORTANTÍSSIMO: após executar, cadastre os dois e-mails em private.couple_allowlist
-- pelo SQL Editor, conforme README. Nunca inclua os e-mails pessoais no GitHub.

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create table if not exists private.couple_allowlist (
  email text primary key,
  role text not null check (role in ('owner', 'partner')),
  created_at timestamptz not null default now(),
  constraint email_normalized check (email = lower(trim(email)))
);

alter table private.couple_allowlist enable row level security;
-- Sem policies e sem GRANT: a tabela não é exposta no cliente.

create or replace function public.is_couple_member()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select auth.uid() is not null
    and exists (
      select 1
      from private.couple_allowlist m
      where m.email = lower(coalesce(auth.jwt() ->> 'email', ''))
    );
$$;

revoke all on function public.is_couple_member() from public, anon;
grant execute on function public.is_couple_member() to authenticated;

create table if not exists public.album_pages (
  sheet_id text not null,
  side text not null check (side in ('front', 'back')),
  position integer not null check (position >= 0),
  content jsonb not null default '{}'::jsonb,
  photo_path text,
  updated_by uuid references auth.users(id) on delete set null,
  updated_at timestamptz not null default now(),
  primary key (sheet_id, side),
  constraint page_id_reasonable check (char_length(sheet_id) between 1 and 100),
  constraint photo_path_valid check (photo_path is null or photo_path ~ '^photos/[0-9a-f-]{36}/[0-9a-f-]{36}\.jpg$')
);

create or replace function public.album_pages_set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  -- Cannot impersonate another authenticated user with a forged UUID.
  new.updated_by := auth.uid();
  return new;
end;
$$;

create or replace trigger album_pages_updated_at
before insert or update on public.album_pages
for each row execute function public.album_pages_set_updated_at();

alter table public.album_pages enable row level security;

drop policy if exists "couple_read_pages" on public.album_pages;
create policy "couple_read_pages" on public.album_pages
  for select to authenticated using (public.is_couple_member());

drop policy if exists "couple_insert_pages" on public.album_pages;
create policy "couple_insert_pages" on public.album_pages
  for insert to authenticated with check (public.is_couple_member());

drop policy if exists "couple_edit_pages" on public.album_pages;
create policy "couple_edit_pages" on public.album_pages
  for update to authenticated using (public.is_couple_member()) with check (public.is_couple_member());

drop policy if exists "couple_delete_pages" on public.album_pages;
create policy "couple_delete_pages" on public.album_pages
  for delete to authenticated using (public.is_couple_member());

grant select, insert, update, delete on public.album_pages to authenticated;
revoke all on public.album_pages from anon;

-- O bucket precisa ser privado; nunca usar getPublicUrl() no aplicativo.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('album-private', 'album-private', false, 5242880, array['image/jpeg'])
on conflict (id) do update set
  public = false,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "couple_read_photos" on storage.objects;
create policy "couple_read_photos" on storage.objects
  for select to authenticated using (bucket_id = 'album-private' and public.is_couple_member());

drop policy if exists "couple_upload_photos" on storage.objects;
create policy "couple_upload_photos" on storage.objects
  for insert to authenticated with check (
    bucket_id = 'album-private'
    and public.is_couple_member()
    and name ~ ('^photos/' || auth.uid()::text || '/[0-9a-f-]{36}\.jpg$')
  );

-- Não permitir update/delete do Storage pelo browser: substituição gera arquivo novo.
-- Exclusão de fotos antigas pode ser feita por um administrador com backup.

-- Realtime: adicionar a tabela à publicação somente se ela ainda não estiver incluída.
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'album_pages'
  ) then
    alter publication supabase_realtime add table public.album_pages;
  end if;
end $$;

-- O segundo e-mail será autorizado por você, fora do repositório.
-- Execute separadamente no SQL Editor, substituindo os exemplos por e-mails reais:
-- insert into private.couple_allowlist(email, role) values
--   ('voce@exemplo.com', 'owner'),
--   ('namorada@exemplo.com', 'partner');
