ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'
    CHECK(role IN ('user', 'admin'));
ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1
    CHECK(is_active IN (0, 1));
ALTER TABLE users ADD COLUMN membership_tier TEXT NOT NULL DEFAULT 'free'
    CHECK(membership_tier IN ('free', 'vip', 'svip'));
ALTER TABLE users ADD COLUMN membership_expires_at TEXT;
ALTER TABLE users ADD COLUMN balance_cents INTEGER NOT NULL DEFAULT 0
    CHECK(balance_cents >= 0);
ALTER TABLE users ADD COLUMN generation_quota INTEGER NOT NULL DEFAULT 5
    CHECK(generation_quota >= 0);
ALTER TABLE users ADD COLUMN generations_used INTEGER NOT NULL DEFAULT 0
    CHECK(generations_used >= 0 AND generations_used <= generation_quota);
ALTER TABLE users ADD COLUMN payment_password_hash TEXT;

-- Existing free accounts do not receive five additional attempts on upgrade.
UPDATE users
SET generations_used = MIN(
    generation_quota,
    (SELECT COUNT(*) FROM video_tasks WHERE video_tasks.user_id = users.id)
);

CREATE TABLE account_ledger (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('cdk_recharge', 'membership_payment')),
    amount_cents INTEGER NOT NULL,
    balance_after_cents INTEGER NOT NULL CHECK(balance_after_cents >= 0),
    reference_type TEXT NOT NULL,
    reference_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX account_ledger_user_created_idx
    ON account_ledger(user_id, created_at DESC, id DESC);

CREATE TABLE membership_orders (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tier TEXT NOT NULL CHECK(tier IN ('vip', 'svip')),
    price_cents INTEGER NOT NULL CHECK(price_cents > 0),
    generation_credits INTEGER NOT NULL CHECK(generation_credits > 0),
    status TEXT NOT NULL CHECK(status = 'paid'),
    idempotency_key TEXT,
    request_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX membership_orders_owner_idempotency_idx
    ON membership_orders(user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE cdks (
    id TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL UNIQUE,
    code_hint TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
    status TEXT NOT NULL DEFAULT 'unused' CHECK(status IN ('unused', 'used')),
    created_by TEXT NOT NULL REFERENCES users(id),
    used_by TEXT REFERENCES users(id),
    used_at TEXT,
    created_at TEXT NOT NULL,
    CHECK((status = 'unused' AND used_by IS NULL AND used_at IS NULL)
       OR (status = 'used' AND used_by IS NOT NULL AND used_at IS NOT NULL))
);
CREATE INDEX cdks_status_created_idx ON cdks(status, created_at DESC, id DESC);
