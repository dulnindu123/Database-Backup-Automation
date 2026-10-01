#!/usr/bin/env bash
# =============================================================================
# Automated Infrastructure-as-Code Deployment Script for Enterprise Backup
# =============================================================================
# Provisions:
# 1. GCS Bucket with Uniform Access & Object Retention Policy (WORM)
# 2. Upload Broker & Telemetry Broker Service Accounts & strict IAM bindings
# 3. Secret Manager Token Store for PC tokens
# 4. Upload Broker & Telemetry Broker Cloud Run microservices (max 3 instances)
# 5. Cloud Logging Alert Policies (Authentication rejection spikes & duplicate events)
# =============================================================================

set -euo pipefail

# Configuration (Customize prior to deployment)
PROJECT_ID="${PROJECT_ID:-my-backup-gcp-project}"
REGION="${REGION:-us-central1}"
BUCKET_NAME="${BUCKET_NAME:-${PROJECT_ID}-secure-backups}"
RETENTION_PERIOD="${RETENTION_PERIOD:-30d}"
MONITORING_SHEET_ID="${MONITORING_SHEET_ID:-YOUR_GOOGLE_SHEET_ID_HERE}"

# Rule of Thumb: Set MAX_BYTES to about 2x the size of your largest single database
# Default: 100 GiB (107,374,182,400 bytes)
MAX_BYTES="${MAX_BYTES:-107374182400}"

echo "================================================================="
echo "Deploying Enterprise Secure Database Cloud Backup Infrastructure"
echo "GCP Project: $PROJECT_ID | Region: $REGION"
echo "Bucket: $BUCKET_NAME | Retention: $RETENTION_PERIOD | Max Size: $MAX_BYTES bytes"
echo "================================================================="

gcloud config set project "$PROJECT_ID"

# 1. Enable Required GCP APIs
echo "[1/6] Enabling Cloud APIs..."
gcloud services enable \
    run.googleapis.com \
    storage.googleapis.com \
    secretmanager.googleapis.com \
    sheets.googleapis.com \
    firestore.googleapis.com \
    logging.googleapis.com \
    monitoring.googleapis.com

# 2. Provision GCS Retention-Locked Storage Bucket
echo "[2/6] Provisioning GCS Storage Bucket ($BUCKET_NAME)..."
if ! gcloud storage buckets describe "gs://${BUCKET_NAME}" &>/dev/null; then
    gcloud storage buckets create "gs://${BUCKET_NAME}" \
        --location="$REGION" \
        --uniform-bucket-level-access

    # Set retention period using modern gcloud storage syntax
    gcloud storage buckets update "gs://${BUCKET_NAME}" --retention-period="${RETENTION_PERIOD}"
    echo "Bucket created with ${RETENTION_PERIOD} retention policy (unlocked mode)."
fi

# 3. Provision Service Accounts & IAM Policies
echo "[3/6] Provisioning Service Accounts & IAM..."
# Upload Broker SA
UPLOAD_SA="upload-broker@${PROJECT_ID}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "$UPLOAD_SA" &>/dev/null; then
    gcloud iam service-accounts create upload-broker \
        --display-name="Upload Broker Cloud Run Service Account"
fi

# Grant STRICTLY roles/storage.objectCreator on bucket (NEVER objectAdmin or admin)
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
    --member="serviceAccount:${UPLOAD_SA}" \
    --role="roles/storage.objectCreator"

# Telemetry Broker SA
TELEMETRY_SA="telemetry-broker@${PROJECT_ID}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "$TELEMETRY_SA" &>/dev/null; then
    gcloud iam service-accounts create telemetry-broker \
        --display-name="Telemetry Broker Cloud Run Service Account"
fi

# Grant Datastore/Firestore User role for rate-limiting
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${TELEMETRY_SA}" \
    --role="roles/datastore.user"

# 4. Provision Secret Manager Secret for PC Tokens
echo "[4/6] Configuring Secret Manager for PC Tokens..."
if ! gcloud secrets describe pc-tokens &>/dev/null; then
    gcloud secrets create pc-tokens --replication-policy="automatic"
    echo "{}" | gcloud secrets versions add pc-tokens --data-file=-
fi

# Grant secret accessor strictly to both brokers
gcloud secrets add-iam-policy-binding pc-tokens \
    --member="serviceAccount:${UPLOAD_SA}" \
    --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding pc-tokens \
    --member="serviceAccount:${TELEMETRY_SA}" \
    --role="roles/secretmanager.secretAccessor"

# 5. Deploy Upload Broker Cloud Run Microservice (Max instances capped at 3)
echo "[5/6] Deploying Upload Broker Cloud Run Service..."
gcloud run deploy upload-broker \
    --source="./broker" \
    --region="$REGION" \
    --service-account="$UPLOAD_SA" \
    --set-env-vars="BUCKET=${BUCKET_NAME},ALLOWED_DBS=all,MAX_BYTES=${MAX_BYTES}" \
    --max-instances=3 \
    --no-allow-unauthenticated

# 6. Deploy Telemetry Broker Cloud Run Microservice (Max instances capped at 3)
echo "[6/6] Deploying Telemetry Broker Cloud Run Service..."
gcloud run deploy telemetry-broker \
    --source="./telemetry_broker" \
    --region="$REGION" \
    --service-account="$TELEMETRY_SA" \
    --set-env-vars="SHEET_ID=${MONITORING_SHEET_ID}" \
    --max-instances=3 \
    --no-allow-unauthenticated

# Setup Log-Based Alerts
gcloud logging metrics create auth_rejections_metric \
    --description="Counts failed authentication attempts across brokers" \
    --log-filter='jsonPayload.event="auth_rejected"' || true

gcloud logging metrics create duplicate_upload_alerts \
    --description="Alerts on 409 conflict duplicate slot upload attempts" \
    --log-filter='jsonPayload.event="duplicate"' || true

echo "================================================================="
echo "Deployment Complete!"
echo "Upload Broker URL: $(gcloud run services describe upload-broker --region="$REGION" --format='value(status.url)' 2>/dev/null || echo 'Check Cloud Run Console')"
echo "Telemetry Broker URL: $(gcloud run services describe telemetry-broker --region="$REGION" --format='value(status.url)' 2>/dev/null || echo 'Check Cloud Run Console')"
echo "================================================================="
echo "MANUAL STEP REMINDER (BUCKET LOCK):"
echo "To permanently lock the bucket retention policy against administrative deletion (IRREVERSIBLE):"
echo "  gcloud storage buckets update gs://${BUCKET_NAME} --lock-retention-period"
echo "================================================================="
