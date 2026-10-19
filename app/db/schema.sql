-- Armonía del Ser Database Schema (Turso / SQLite3)

CREATE TABLE IF NOT EXISTS admin_allowlist (
    email TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'ASSISTANT' CHECK (role IN ('OWNER', 'ASSISTANT', 'ADMIN')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS services (
    id TEXT PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    service_type TEXT NOT NULL CHECK (service_type IN ('GROUP', 'INDIVIDUAL')),
    modality TEXT NOT NULL CHECK (modality IN ('PRESENCIAL', 'ONLINE')),
    default_schedule TEXT,
    price_mxn INTEGER NOT NULL DEFAULT 0,
    max_capacity INTEGER NOT NULL DEFAULT 1,
    duration_minutes INTEGER NOT NULL DEFAULT 60,
    buffer_minutes INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS clients (
    id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    phone_whatsapp TEXT NOT NULL,
    email TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS packages (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(id),
    service_id TEXT NOT NULL REFERENCES services(id),
    total_sessions INTEGER NOT NULL CHECK (total_sessions > 0),
    completed_sessions INTEGER NOT NULL DEFAULT 0 CHECK (completed_sessions >= 0),
    price_paid_mxn INTEGER NOT NULL DEFAULT 0,
    financial_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (financial_status IN ('PAID', 'PARTIAL', 'PENDING')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bookings (
    id TEXT PRIMARY KEY,
    booking_code TEXT UNIQUE NOT NULL,
    service_id TEXT NOT NULL REFERENCES services(id),
    client_id TEXT NOT NULL REFERENCES clients(id),
    package_id TEXT REFERENCES packages(id),
    scheduled_at TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL DEFAULT 60,
    buffer_minutes INTEGER NOT NULL DEFAULT 0,
    booking_status TEXT NOT NULL DEFAULT 'RESERVED'
        CHECK (booking_status IN ('RESERVED', 'RELEASED', 'CANCELLED', 'COMPLETED', 'NO_SHOW')),
    payment_arrangement TEXT NOT NULL DEFAULT 'PREPAID_DEFAULT'
        CHECK (payment_arrangement IN ('PREPAID_DEFAULT', 'DELAYED_ALLOWED', 'PACKAGE_REDEEMED')),
    payment_status TEXT NOT NULL DEFAULT 'AWAITING_ACKNOWLEDGMENT'
        CHECK (payment_status IN ('AWAITING_ACKNOWLEDGMENT', 'ACKNOWLEDGED', 'NOT_APPLICABLE')),
    amount_mxn INTEGER NOT NULL,
    exception_authorized_by TEXT REFERENCES admin_allowlist(email),
    exception_authorized_at TEXT,
    exception_notes TEXT,
    released_by TEXT REFERENCES admin_allowlist(email),
    released_at TEXT,
    release_reason TEXT,
    acknowledged_by TEXT REFERENCES admin_allowlist(email),
    acknowledged_at TEXT,
    gcal_event_id TEXT,
    gcal_sync_status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (gcal_sync_status IN ('PENDING', 'SYNCED', 'FAILED', 'NOT_CONFIGURED')),
    gcal_sync_error TEXT,
    gcal_synced_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    booking_id TEXT NOT NULL REFERENCES bookings(id),
    amount_mxn INTEGER NOT NULL,
    payment_method TEXT NOT NULL DEFAULT 'SPEI' CHECK (payment_method IN ('SPEI', 'OXXO', 'CASH')),
    status TEXT NOT NULL DEFAULT 'ACKNOWLEDGED' CHECK (status IN ('ACKNOWLEDGED', 'REVERSED')),
    acknowledged_by TEXT NOT NULL REFERENCES admin_allowlist(email),
    acknowledged_at TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id TEXT PRIMARY KEY,
    admin_email TEXT NOT NULL REFERENCES admin_allowlist(email),
    action_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    details_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_services_slug ON services(slug);
CREATE INDEX IF NOT EXISTS idx_bookings_code ON bookings(booking_code);
CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(booking_status);
CREATE INDEX IF NOT EXISTS idx_bookings_payment_status ON bookings(payment_status);
CREATE INDEX IF NOT EXISTS idx_bookings_scheduled ON bookings(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_bookings_package ON bookings(package_id);
CREATE INDEX IF NOT EXISTS idx_clients_phone ON clients(phone_whatsapp);
CREATE INDEX IF NOT EXISTS idx_packages_client ON packages(client_id);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON admin_audit_log(entity_type, entity_id);
