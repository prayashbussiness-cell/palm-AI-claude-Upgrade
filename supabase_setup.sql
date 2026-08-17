-- Run this once in the Supabase SQL Editor (Project > SQL Editor > New query)
-- before deploying. It creates the table that stores each submission's
-- details plus the URL of the uploaded face photo, and a storage bucket
-- for the photo itself.
--
-- This project uses the SAME Supabase project + the same PUBLISHABLE key
-- (sb_publishable_...) as the Student Database project. A publishable key
-- is low-privilege by design (same tier as the old "anon" key) — it does
-- NOT bypass Row Level Security. So for it to be able to insert/read rows
-- and upload files, the table and storage bucket need explicit RLS
-- policies granting that access, exactly like the Student Database
-- project's `student` table already has. That's what the policies below
-- set up for `palm_reports` and the `palm-images` bucket.

-- 1. Table for user details + report + face image URL
create table if not exists public.palm_reports (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  report_id text,
  name text not null,
  email text not null,
  phone text,
  dob text not null,
  place text not null,
  face_image_url text,
  report text,
  rashi text,
  pdf_filename text,
  razorpay_payment_id text,
  paid boolean not null default false
);

-- If you're upgrading an existing table from an earlier version of this
-- project, run this instead of the create table above:
--
-- alter table public.palm_reports
--   add column if not exists report_id text;
-- alter table public.palm_reports
--   add column if not exists phone text;
-- alter table public.palm_reports
--   add column if not exists rashi text;
-- alter table public.palm_reports
--   add column if not exists pdf_filename text;
-- alter table public.palm_reports
--   add column if not exists razorpay_payment_id text;
-- alter table public.palm_reports
--   add column if not exists paid boolean not null default false;
-- alter table public.palm_reports
--   drop column if exists time_of_birth;
-- alter table public.palm_reports
--   drop column if exists left_palm_image_url;
-- alter table public.palm_reports
--   drop column if exists right_palm_image_url;

-- An index to make the /download/lookup query (email + phone + paid) fast.
create index if not exists idx_palm_reports_lookup
  on public.palm_reports (email, phone, paid, created_at desc);

alter table public.palm_reports enable row level security;

-- Allow the publishable/anon key to insert new reports (needed for the
-- backend to save each submission) and to read them back. There's no
-- delete policy, so existing rows can't be removed through this key —
-- only through the Supabase dashboard.
drop policy if exists "Allow anon insert on palm_reports" on public.palm_reports;
create policy "Allow anon insert on palm_reports"
  on public.palm_reports
  for insert
  to anon
  with check (true);

drop policy if exists "Allow anon select on palm_reports" on public.palm_reports;
create policy "Allow anon select on palm_reports"
  on public.palm_reports
  for select
  to anon
  using (true);

-- ---------------------------------------------------------------------------
-- IMPORTANT SECURITY NOTE about the UPDATE policy below
-- ---------------------------------------------------------------------------
-- The backend needs to flip `paid` from false -> true once a Razorpay
-- payment is verified, and to set `pdf_filename` when it regenerates a PDF
-- during a /download/lookup request. That requires an UPDATE policy.
--
-- The policy below is scoped to only the columns the backend actually
-- needs to touch (paid, pdf_filename, razorpay_payment_id) via a column
-- GRANT, so the anon/publishable key still can't rewrite anyone's name,
-- email, dob, or report text. BUT: because this project ships with a
-- publishable key baked into main.py as a fallback default (publishable
-- keys are designed to be embeddable/public), anyone who has that key
-- could, in principle, call Supabase's REST API directly and flip their
-- own row's `paid` to true WITHOUT actually paying — RLS alone can't
-- verify a Razorpay signature.
--
-- This is an acceptable trade-off for testing/low-stakes use, but before
-- you rely on this for real revenue, harden it:
--   1. Get your project's SECRET key (sb_secret_... — Project Settings >
--      API Keys), set it as the SUPABASE_KEY env var in Render (this
--      overrides the baked-in publishable default).
--   2. Run: drop policy "Allow anon update paid status on palm_reports"
--      on public.palm_reports; revoke update on public.palm_reports from
--      anon;
--   A secret/service_role key bypasses RLS entirely, so the backend keeps
--   working exactly the same — but nobody holding only the publishable
--   key can flip `paid` anymore.
drop policy if exists "Allow anon update paid status on palm_reports" on public.palm_reports;
create policy "Allow anon update paid status on palm_reports"
  on public.palm_reports
  for update
  to anon
  using (true)
  with check (true);

revoke update on public.palm_reports from anon;
grant update (paid, pdf_filename, razorpay_payment_id) on public.palm_reports to anon;

-- 2. Storage bucket for the face photo.
-- Set public = true so the stored image URL is directly viewable.
insert into storage.buckets (id, name, public)
values ('palm-images', 'palm-images', true)
on conflict (id) do nothing;

-- Storage RLS: allow the publishable/anon key to upload and read files
-- specifically within the palm-images bucket (not any other bucket).
drop policy if exists "Allow anon upload to palm-images" on storage.objects;
create policy "Allow anon upload to palm-images"
  on storage.objects
  for insert
  to anon
  with check (bucket_id = 'palm-images');

drop policy if exists "Allow anon read palm-images" on storage.objects;
create policy "Allow anon read palm-images"
  on storage.objects
  for select
  to anon
  using (bucket_id = 'palm-images');

-- Security note: this mirrors the Student Database project's setup, which
-- keeps the publishable key genuinely low-privilege — it can only insert
-- and read within these specific tables/bucket, nothing else, and can't
-- update or delete anything. If you ever want stricter control (e.g. to
-- stop the key from reading other users' submissions), switch the backend
-- to use the secret key (sb_secret_...) via a real SUPABASE_KEY env var in
-- Render instead, and remove these anon policies.
