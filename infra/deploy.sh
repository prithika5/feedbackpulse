#!/usr/bin/env bash
# Builds and deploys the API to Cloud Run. Safe to re-run. Reads settings from .env,
# passes secrets over stdin so they never appear in process lists or logs.
set -euo pipefail

env_value() { grep -E "^$1=" .env | head -1 | cut -d= -f2-; }

PROJECT="$(env_value GCP_PROJECT_ID)"
DATASET="$(env_value BQ_DATASET)"
REGION="us-central1"
REPO="feedbackpulse"
SERVICE="feedbackpulse-api"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/$REPO/api:latest"
RUNTIME_SA="feedbackpulse-api@$PROJECT.iam.gserviceaccount.com"

gcloud artifacts repositories describe "$REPO" --location "$REGION" --project "$PROJECT" >/dev/null 2>&1 ||
  gcloud artifacts repositories create "$REPO" --repository-format docker \
    --location "$REGION" --project "$PROJECT"

gcloud iam service-accounts describe "$RUNTIME_SA" --project "$PROJECT" >/dev/null 2>&1 ||
  gcloud iam service-accounts create feedbackpulse-api --project "$PROJECT" \
    --display-name "FeedbackPulse API (read-only)"

# Read-only by design: it can run queries and read this dataset, and nothing else.
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$RUNTIME_SA" \
  --role roles/bigquery.jobUser --condition None --quiet >/dev/null
bq --project_id="$PROJECT" query --quiet --use_legacy_sql=false \
  "GRANT \`roles/bigquery.dataViewer\` ON SCHEMA \`$DATASET\` TO 'serviceAccount:$RUNTIME_SA'" >/dev/null

for NAME in GEMINI_API_KEY DATABASE_URL; do
  gcloud secrets describe "$NAME" --project "$PROJECT" >/dev/null 2>&1 ||
    gcloud secrets create "$NAME" --replication-policy automatic --project "$PROJECT"
  # Only add a version when the value changed: the free tier covers 6 active versions.
  CURRENT="$(gcloud secrets versions access latest --secret "$NAME" --project "$PROJECT" 2>/dev/null || true)"
  if [ "$CURRENT" != "$(env_value "$NAME")" ]; then
    env_value "$NAME" | tr -d '\n' |
      gcloud secrets versions add "$NAME" --data-file=- --project "$PROJECT" >/dev/null
  fi
  gcloud secrets add-iam-policy-binding "$NAME" --project "$PROJECT" \
    --member "serviceAccount:$RUNTIME_SA" --role roles/secretmanager.secretAccessor >/dev/null
done

# New projects run builds as the default compute account, which needs this role first.
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)')"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role roles/cloudbuild.builds.builder --condition None --quiet >/dev/null

gcloud builds submit . --project "$PROJECT" --config infra/cloudbuild-api.yaml \
  --substitutions "_IMAGE=$IMAGE,_EMBEDDING_MODEL=$(env_value EMBEDDING_MODEL)"

# min-instances 0 means no idle cost, and max-instances caps what abuse could ever use.
gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" --image "$IMAGE" \
  --service-account "$RUNTIME_SA" --allow-unauthenticated \
  --min-instances 0 --max-instances 2 --memory 1Gi --cpu 1 --concurrency 4 --timeout 120 \
  --set-env-vars "GCP_PROJECT_ID=$PROJECT,BQ_DATASET=$DATASET,GEMINI_MODEL=$(env_value GEMINI_MODEL),EMBEDDING_MODEL=$(env_value EMBEDDING_MODEL)" \
  --set-secrets "GEMINI_API_KEY=GEMINI_API_KEY:latest,DATABASE_URL=DATABASE_URL:latest"

gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)'
