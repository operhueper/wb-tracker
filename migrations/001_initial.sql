-- ============================================================
-- WB Tracker — Supabase PostgreSQL Schema
-- Run this in Supabase SQL Editor: https://supabase.com/dashboard
-- ============================================================

-- Enable UUID generation
create extension if not exists "uuid-ossp";

-- ── Products (справочник товаров + себестоимость) ────────────
create table if not exists products (
    id                uuid primary key default uuid_generate_v4(),
    wb_article        bigint unique not null,
    seller_article    text,
    name              text,
    cost_price        decimal(10,2) default 0,      -- себестоимость руб
    wb_commission     decimal(5,2) default 0,        -- комиссия WB %
    logistics_cost    decimal(10,2) default 0,       -- логистика руб за ед
    created_at        timestamptz default now(),
    updated_at        timestamptz default now()
);

-- ── Campaigns (реестр рекламных кампаний) ────────────────────
create table if not exists campaigns (
    id                uuid primary key default uuid_generate_v4(),
    wb_campaign_id    bigint unique not null,
    name              text,
    campaign_type     integer,
    bid_type          text,
    status            integer,
    created_at        timestamptz default now(),
    updated_at        timestamptz default now()
);

-- ── Campaign snapshots (снимок каждые 15 мин) ────────────────
create table if not exists campaign_snapshots (
    id                uuid primary key default uuid_generate_v4(),
    campaign_id       uuid references campaigns(id) on delete cascade,
    wb_campaign_id    bigint not null,
    bid               decimal(10,2),          -- текущая ставка CPM
    status            integer,                -- статус кампании
    budget_daily      decimal(12,2),          -- дневной лимит
    is_changed        boolean default false,  -- изменилось ли с прошлого снимка
    change_details    jsonb default '{}',     -- что именно изменилось
    raw_data          jsonb,                  -- полный ответ API
    snapshot_at       timestamptz default now()
);

-- ── Campaign daily stats (ежедневная статистика) ────────────
create table if not exists campaign_daily_stats (
    id                uuid primary key default uuid_generate_v4(),
    campaign_id       uuid references campaigns(id) on delete cascade,
    wb_campaign_id    bigint not null,
    stat_date         date not null,
    shows             bigint default 0,        -- показы
    clicks            bigint default 0,        -- клики
    ctr               decimal(8,4) default 0,  -- CTR %
    cpc               decimal(10,2) default 0, -- стоимость клика
    spend             decimal(12,2) default 0, -- расход руб
    orders            integer default 0,       -- заказы
    orders_sum        decimal(12,2) default 0, -- сумма заказов
    cpo               decimal(10,2) default 0, -- стоимость заказа
    drr               decimal(8,4) default 0,  -- ДРР %
    cr                decimal(8,4) default 0,  -- конверсия клик→заказ %
    raw_data          jsonb,
    created_at        timestamptz default now(),
    unique (wb_campaign_id, stat_date)
);

-- ── Price history (цены каждый час) ─────────────────────────
create table if not exists price_history (
    id                uuid primary key default uuid_generate_v4(),
    wb_article        bigint not null,
    product_id        uuid references products(id) on delete set null,
    price_base        decimal(10,2),           -- цена без скидок
    price_sale        decimal(10,2),           -- цена со скидкой продавца
    price_spp         decimal(10,2),           -- цена с учётом СПП (реальная для покупателя)
    spp_percent       decimal(5,2) default 0,  -- размер СПП %
    discount_percent  decimal(5,2) default 0,  -- скидка продавца %
    raw_data          jsonb,
    snapshot_at       timestamptz default now()
);

-- ── Margin calculations (расчёт маржи) ──────────────────────
create table if not exists margin_calculations (
    id                  uuid primary key default uuid_generate_v4(),
    product_id          uuid references products(id) on delete cascade,
    price_snapshot_id   uuid references price_history(id) on delete cascade,
    revenue             decimal(10,2),    -- выручка (цена с СПП)
    cost_price          decimal(10,2),    -- себестоимость
    wb_commission_amt   decimal(10,2),    -- комиссия WB в руб
    logistics_amt       decimal(10,2),    -- логистика в руб
    gross_profit        decimal(10,2),    -- валовая прибыль
    margin_pct          decimal(8,4),     -- маржинальность %
    calculated_at       timestamptz default now()
);

-- ── Indexes ──────────────────────────────────────────────────
create index if not exists idx_snapshots_campaign_id on campaign_snapshots(campaign_id);
create index if not exists idx_snapshots_snapshot_at on campaign_snapshots(snapshot_at desc);
create index if not exists idx_snapshots_wb_id on campaign_snapshots(wb_campaign_id);
create index if not exists idx_snapshots_is_changed on campaign_snapshots(is_changed) where is_changed = true;
create index if not exists idx_daily_stats_date on campaign_daily_stats(stat_date desc);
create index if not exists idx_price_article on price_history(wb_article);
create index if not exists idx_price_snapshot_at on price_history(snapshot_at desc);

-- ── Auto-update updated_at ────────────────────────────────────
create or replace function update_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end;
$$;

drop trigger if exists trg_products_updated_at on products;
create trigger trg_products_updated_at
    before update on products
    for each row execute function update_updated_at();

drop trigger if exists trg_campaigns_updated_at on campaigns;
create trigger trg_campaigns_updated_at
    before update on campaigns
    for each row execute function update_updated_at();

-- ── Useful views ──────────────────────────────────────────────

-- Latest price per article
create or replace view latest_prices as
select distinct on (wb_article)
    wb_article,
    price_base,
    price_sale,
    price_spp,
    spp_percent,
    discount_percent,
    snapshot_at
from price_history
order by wb_article, snapshot_at desc;

-- Recent campaign changes
create or replace view recent_changes as
select
    s.snapshot_at,
    c.name as campaign_name,
    s.wb_campaign_id,
    s.bid,
    s.status,
    s.budget_daily,
    s.change_details
from campaign_snapshots s
join campaigns c on c.id = s.campaign_id
where s.is_changed = true
  and s.change_details::text != '{"event": "first_snapshot"}'
order by s.snapshot_at desc;
