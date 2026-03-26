-- قاعدة موجودة مسبقاً: أضف أعمدة AP/CSC لجدول البصمة
ALTER TABLE device_fingerprints
  ADD COLUMN IF NOT EXISTS ap_version VARCHAR(64),
  ADD COLUMN IF NOT EXISTS csc_version VARCHAR(64);
