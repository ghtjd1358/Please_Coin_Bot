-- please_coin — Supabase 스키마
--
-- 적용:
--   psql < supabase/schema.sql
--   또는 Supabase Dashboard → SQL Editor 에 붙여넣기
--
-- 설계 메모:
--   · 모든 테이블은 (symbol, created_at DESC) 조회가 핫 패스 → 복합 인덱스.
--   · trades / portfolio_snapshots / agent_logs는 상호 FK 없이 독립 append-only.
--     대시보드는 3 테이블을 각자 Realtime 구독하면 된다 (조인 불필요).
--   · RLS: 읽기는 anon 공개, 쓰기는 service role만. 대시보드는 anon key,
--     트레이더 봇은 service role key 사용.
--   · enum 대신 CHECK 제약 — 마이그레이션 부담 낮추려고.

create extension if not exists "pgcrypto";

-- ──────────────────────────────────────────────────────
-- 1) trades : 매매 이벤트 append-only
-- ──────────────────────────────────────────────────────
create table if not exists public.trades (
    id               uuid        primary key default gen_random_uuid(),
    created_at       timestamptz not null    default now(),
    symbol           text        not null,
    action           text        not null check (action in ('buy','sell','hold','stop_loss')),
    price            numeric     not null,
    amount           numeric     not null,          -- 코인 수량 (hold=0)
    fee              numeric     not null default 0,
    balance_after    numeric     not null,
    coin_held_after  numeric     not null,
    pnl              numeric,                        -- 청산 발생 시만 non-null
    mode             text        not null check (mode in ('paper','live')),
    note             text
);

create index if not exists trades_symbol_created_idx
    on public.trades (symbol, created_at desc);

-- ──────────────────────────────────────────────────────
-- 2) portfolio_snapshots : 매 tick 포트폴리오 상태
-- ──────────────────────────────────────────────────────
create table if not exists public.portfolio_snapshots (
    id                uuid        primary key default gen_random_uuid(),
    created_at        timestamptz not null    default now(),
    symbol            text        not null,
    total_value       numeric     not null,
    balance           numeric     not null,
    coin_held         numeric     not null,
    avg_buy_price     numeric     not null default 0,
    unrealized_pnl    numeric     not null default 0,
    current_price     numeric     not null,
    mode              text        not null check (mode in ('paper','live'))
);

create index if not exists portfolio_snapshots_symbol_created_idx
    on public.portfolio_snapshots (symbol, created_at desc);

-- ──────────────────────────────────────────────────────
-- 3) agent_logs : 에이전트 관측·행동 요약
-- ──────────────────────────────────────────────────────
create table if not exists public.agent_logs (
    id           uuid        primary key default gen_random_uuid(),
    created_at   timestamptz not null    default now(),
    symbol       text        not null,
    obs_summary  jsonb       not null    default '{}'::jsonb,
    action       smallint    not null check (action in (0,1,2)),
    reward       numeric,
    confidence   numeric,
    mode         text        not null check (mode in ('paper','live'))
);

create index if not exists agent_logs_symbol_created_idx
    on public.agent_logs (symbol, created_at desc);

-- ──────────────────────────────────────────────────────
-- RLS
--   anon/authenticated : SELECT만 허용 (대시보드 읽기)
--   service_role       : RLS 우회 (트레이더 봇 insert)
--
-- 쓰기를 막는 이유: 대시보드에 뿌리는 anon key가 노출되더라도 기록을 변조·삭제할 수 없게.
-- 봇은 반드시 service role key로 SupabaseLogger 를 구성해야 함.
-- ──────────────────────────────────────────────────────
alter table public.trades              enable row level security;
alter table public.portfolio_snapshots enable row level security;
alter table public.agent_logs          enable row level security;

drop policy if exists "trades read"              on public.trades;
drop policy if exists "portfolio_snapshots read" on public.portfolio_snapshots;
drop policy if exists "agent_logs read"          on public.agent_logs;

create policy "trades read"
    on public.trades
    for select
    using (true);

create policy "portfolio_snapshots read"
    on public.portfolio_snapshots
    for select
    using (true);

create policy "agent_logs read"
    on public.agent_logs
    for select
    using (true);

-- ──────────────────────────────────────────────────────
-- Realtime : 세 테이블 모두 broadcast
-- (Supabase Dashboard → Database → Replication 에서도 토글 가능)
-- ──────────────────────────────────────────────────────
alter publication supabase_realtime add table public.trades;
alter publication supabase_realtime add table public.portfolio_snapshots;
alter publication supabase_realtime add table public.agent_logs;
