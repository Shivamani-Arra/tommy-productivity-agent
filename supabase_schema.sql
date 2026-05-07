-- Optional schema upgrades for the full productivity agent.
-- Run this in Supabase SQL editor if these tables/columns do not exist yet.

alter table if exists tasks add column if not exists user_id text default 'default';
alter table if exists tasks add column if not exists risk_score integer;
alter table if exists tasks add column if not exists risk_label text;
alter table if exists tasks add column if not exists calendar_event_id text;
alter table if exists tasks add column if not exists calendar_link text;

create table if not exists schedule (
    id uuid primary key default gen_random_uuid(),
    task_id text,
    user_id text default 'default',
    scheduled_date date not null,
    start_time text,
    end_time text,
    hours_planned numeric not null default 1,
    completed boolean not null default false,
    status text default 'planned',
    created_at timestamptz not null default now()
);

alter table if exists schedule add column if not exists user_id text default 'default';
alter table if exists schedule add column if not exists task_name text;
alter table if exists schedule add column if not exists start_time text;
alter table if exists schedule add column if not exists end_time text;
alter table if exists schedule add column if not exists status text default 'planned';
alter table if exists schedule add column if not exists calendar_event_id text;
alter table if exists schedule add column if not exists calendar_link text;
alter table if exists schedule add column if not exists created_at timestamptz not null default now();

create table if not exists daily_progress (
    id uuid primary key default gen_random_uuid(),
    task_id text,
    user_id text default 'default',
    date date not null default current_date,
    hours_completed numeric not null default 0,
    note text,
    created_at timestamptz not null default now()
);

alter table if exists daily_progress add column if not exists user_id text default 'default';
alter table if exists daily_progress add column if not exists note text;
alter table if exists daily_progress add column if not exists created_at timestamptz not null default now();

create table if not exists conversation_memory (
    id uuid primary key default gen_random_uuid(),
    user_id text default 'default',
    message text not null,
    assistant_response text,
    created_at timestamptz not null default now()
);

alter table if exists conversation_memory add column if not exists user_id text default 'default';
alter table if exists conversation_memory add column if not exists assistant_response text;
alter table if exists conversation_memory add column if not exists created_at timestamptz not null default now();

create table if not exists deadline_extension_requests (
    id uuid primary key default gen_random_uuid(),
    user_id text default 'default',
    task_id text,
    task_name text,
    current_deadline date,
    backlog_hours numeric not null default 0,
    suggested_deadline date,
    status text default 'pending',
    created_at timestamptz not null default now()
);

alter table if exists deadline_extension_requests add column if not exists user_id text default 'default';
alter table if exists deadline_extension_requests add column if not exists task_id text;
alter table if exists deadline_extension_requests add column if not exists task_name text;
alter table if exists deadline_extension_requests add column if not exists current_deadline date;
alter table if exists deadline_extension_requests add column if not exists backlog_hours numeric not null default 0;
alter table if exists deadline_extension_requests add column if not exists suggested_deadline date;
alter table if exists deadline_extension_requests add column if not exists status text default 'pending';
alter table if exists deadline_extension_requests add column if not exists created_at timestamptz not null default now();

create table if not exists pending_followups (
    id uuid primary key default gen_random_uuid(),
    user_id text default 'default',
    kind text not null,
    payload jsonb default '{}'::jsonb,
    question text,
    status text default 'pending',
    created_at timestamptz not null default now()
);

alter table if exists pending_followups add column if not exists user_id text default 'default';
alter table if exists pending_followups add column if not exists kind text;
alter table if exists pending_followups add column if not exists payload jsonb default '{}'::jsonb;
alter table if exists pending_followups add column if not exists question text;
alter table if exists pending_followups add column if not exists status text default 'pending';
alter table if exists pending_followups add column if not exists created_at timestamptz not null default now();

create table if not exists user_preferences (
    id uuid primary key default gen_random_uuid(),
    user_id text default 'default',
    study_start text default '',
    study_end text default '',
    sleep_start text default '23:00',
    sleep_end text default '07:00',
    max_session_hours numeric default 2,
    break_minutes integer default 10,
    no_study_days text default '',
    preferred_subjects text default '',
    updated_at timestamptz not null default now()
);

alter table if exists user_preferences add column if not exists user_id text default 'default';
alter table if exists user_preferences add column if not exists study_start text default '';
alter table if exists user_preferences add column if not exists study_end text default '';
alter table if exists user_preferences add column if not exists sleep_start text default '23:00';
alter table if exists user_preferences add column if not exists sleep_end text default '07:00';
alter table if exists user_preferences add column if not exists max_session_hours numeric default 2;
alter table if exists user_preferences add column if not exists break_minutes integer default 10;
alter table if exists user_preferences add column if not exists no_study_days text default '';
alter table if exists user_preferences add column if not exists preferred_subjects text default '';
alter table if exists user_preferences add column if not exists updated_at timestamptz not null default now();

update user_preferences
set study_start = '', study_end = ''
where study_start = '09:00' and study_end = '18:00';

create index if not exists idx_tasks_user_status on tasks(user_id, status);
create index if not exists idx_schedule_user_date on schedule(user_id, scheduled_date);
create index if not exists idx_progress_user_task on daily_progress(user_id, task_id);
create index if not exists idx_memory_user_created on conversation_memory(user_id, created_at desc);
create index if not exists idx_extension_user_status on deadline_extension_requests(user_id, status);
create index if not exists idx_followups_user_status on pending_followups(user_id, status);
create index if not exists idx_preferences_user on user_preferences(user_id);
