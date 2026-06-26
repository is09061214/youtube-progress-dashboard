#!/usr/bin/env bash
# Cloud Run へ手動デプロイ（Google Cloud Shell または gcloud ログイン済み環境向け）
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-gen-lang-client-0188619772}"
REGION="${GCP_REGION:-asia-northeast1}"
SERVICE="${CLOUD_RUN_SERVICE:-youtube-progress-dashboard}"

cd "$(dirname "$0")/.."

gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --project "$PROJECT_ID"

echo "Deployed: https://${SERVICE}-${PROJECT_ID}.${REGION}.run.app/"
