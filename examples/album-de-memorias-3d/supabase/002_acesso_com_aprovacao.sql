-- V7: cadastro com solicitação de acesso, liberação exclusiva pelo proprietário.
-- Este script é idempotente e foi aplicado ao projeto Supabase album-de-memorias.
-- Não salvar dados pessoais dos participantes neste repositório.
create or replace function public.album_my_role()
returns text language sql stable security definer set search_path='' as $$
  select m.role from auth.users u
  join private.couple_allowlist m on m.email=lower(trim(u.email))
  where u.id=(select auth.uid()) and u.email_confirmed_at is not null limit 1;
$$;
revoke all on function public.album_my_role() from public,anon;
grant execute on function public.album_my_role() to authenticated;

create or replace function public.is_couple_member()
returns boolean language sql stable security invoker set search_path='' as $$
  select (select public.album_my_role()) is not null;
$$;
revoke all on function public.is_couple_member() from public,anon;
grant execute on function public.is_couple_member() to authenticated;

create table if not exists public.album_access_requests(
  id uuid primary key default gen_random_uuid(),
  requester_id uuid not null unique references auth.users(id) on delete cascade,
  email text not null,
  display_name text not null,
  status text not null default 'pending' check(status in('pending','approved','rejected')),
  created_at timestamptz not null default now(),
  reviewed_at timestamptz,
  reviewed_by uuid references auth.users(id),
  constraint album_request_email_normal check(email=lower(trim(email)) and char_length(email)<=254),
  constraint album_request_name_check check(char_length(trim(display_name)) between 2 and 60)
);
create index if not exists album_access_requests_pending_idx
 on public.album_access_requests(created_at) where status='pending';
alter table public.album_access_requests enable row level security;
revoke all on public.album_access_requests from anon;
grant select,insert on public.album_access_requests to authenticated;
revoke update,delete on public.album_access_requests from authenticated;

drop policy if exists "album_request_read" on public.album_access_requests;
create policy "album_request_read" on public.album_access_requests
  for select to authenticated using (
  requester_id=(select auth.uid()) or (select public.album_my_role())='owner'
);
drop policy if exists "album_request_create" on public.album_access_requests;
create policy "album_request_create" on public.album_access_requests
  for insert to authenticated with check(
    requester_id=(select auth.uid()) and status='pending'
    and reviewed_at is null and reviewed_by is null
    and email=lower(coalesce((select auth.jwt()->>'email'),''))
    and (select public.album_my_role()) is null
);

create or replace function public.review_album_request(p_request_id uuid,p_decision text)
returns text language plpgsql security definer set search_path='' as $$
declare
  req public.album_access_requests%rowtype;
  verified_email text;
begin
  if (select public.album_my_role()) is distinct from 'owner'
    then raise exception 'Sem permissão para revisar solicitações'; end if;
  if p_decision not in ('approved','rejected')
    then raise exception 'Decisão inválida'; end if;
  select * into req from public.album_access_requests where id=p_request_id for update;
  if not found then raise exception 'Solicitação não encontrada'; end if;
  if req.status<>'pending' then raise exception 'Solicitação já processada'; end if;
  select lower(trim(email)) into verified_email from auth.users
    where id=req.requester_id and email_confirmed_at is not null;
  if verified_email is null or verified_email<>req.email
    then raise exception 'O solicitante precisa confirmar seu e-mail'; end if;
  if p_decision='approved' then
    if exists(select 1 from private.couple_allowlist where role='partner' and email<>verified_email)
      then raise exception 'Já existe uma pessoa parceira autorizada'; end if;
    if exists(select 1 from private.couple_allowlist where role='owner' and email=verified_email)
      then raise exception 'Proprietário já autorizado'; end if;
    insert into private.couple_allowlist(email,role) values(verified_email,'partner')
      on conflict(email) do update set role='partner';
  end if;
  update public.album_access_requests
  set status=p_decision,reviewed_at=now(),reviewed_by=auth.uid()
  where id=p_request_id;
  return p_decision;
end;
$$;
revoke all on function public.review_album_request(uuid,text) from public,anon;
grant execute on function public.review_album_request(uuid,text) to authenticated;

do $$
begin
 if not exists(select 1 from pg_publication_tables
  where pubname='supabase_realtime' and schemaname='public' and tablename='album_access_requests')
 then alter publication supabase_realtime add table public.album_access_requests; end if;
end $$;
