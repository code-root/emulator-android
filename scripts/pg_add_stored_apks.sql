-- جدول مكتبة APK (لقواعد بيانات موجودة قبل إضافة StoredApk)
CREATE TABLE IF NOT EXISTS stored_apks (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    display_name VARCHAR(256),
    stored_filename VARCHAR(512) NOT NULL UNIQUE,
    original_filename VARCHAR(256) NOT NULL,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_stored_apks_owner_id ON stored_apks (owner_id);
