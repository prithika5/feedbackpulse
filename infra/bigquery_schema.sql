-- BigQuery schema for FeedbackPulse. Safe to re-run: nothing here deletes data.
-- __DATASET__ is replaced with BQ_DATASET when pipeline/load.py applies this file.

CREATE SCHEMA IF NOT EXISTS `__DATASET__` OPTIONS (location = "US");

CREATE TABLE IF NOT EXISTS `__DATASET__.apps` (
  app_id STRING,
  name STRING,
  category STRING,
  review_count INT64
);

-- DATETIME, not TIMESTAMP: the source file doesn't state a time zone, so we don't claim one.
CREATE TABLE IF NOT EXISTS `__DATASET__.reviews` (
  review_id STRING,
  app_id STRING,
  rating INT64,
  text STRING,
  review_date DATETIME,
  app_version STRING,
  thumbs_up INT64,
  text_len INT64
);

-- first_seen_date is the earliest review of a version: an estimate of its release date.
CREATE TABLE IF NOT EXISTS `__DATASET__.releases` (
  app_id STRING,
  version STRING,
  first_seen_date DATE,
  review_count INT64,
  low_volume BOOL
);

-- themes and review_themes are created empty here and filled in Step 6.
CREATE TABLE IF NOT EXISTS `__DATASET__.themes` (
  theme_id STRING,
  app_id STRING,
  name STRING,
  description STRING,
  sentiment STRING,
  keywords ARRAY<STRING>,
  created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS `__DATASET__.review_themes` (
  review_id STRING,
  theme_id STRING,
  distance FLOAT64
);

-- pct_negative runs from 0 to 100, and "negative" means 1 or 2 stars.
CREATE OR REPLACE VIEW `__DATASET__.daily_metrics` AS
SELECT
  app_id,
  DATE(review_date) AS date,
  AVG(rating) AS avg_rating,
  COUNT(*) AS review_count,
  100 * COUNTIF(rating <= 2) / COUNT(*) AS pct_negative
FROM `__DATASET__.reviews`
GROUP BY app_id, date;

CREATE OR REPLACE VIEW `__DATASET__.theme_daily` AS
SELECT
  r.app_id,
  rt.theme_id,
  DATE(r.review_date) AS date,
  COUNT(*) AS review_count,
  AVG(r.rating) AS avg_rating
FROM `__DATASET__.review_themes` AS rt
JOIN `__DATASET__.reviews` AS r USING (review_id)
GROUP BY r.app_id, rt.theme_id, date;
