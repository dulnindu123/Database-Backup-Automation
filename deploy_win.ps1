$ErrorActionPreference = "Stop"
$env:PATH += ";$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin"

$PROJECT_ID = "backupsystem-509315"
$REGION = "us-central1"
$BUCKET_NAME = "$PROJECT_ID-secure-backups"
$RETENTION_PERIOD = "30d"
$MONITORING_SHEET_ID = "YOUR_GOOGLE_SHEET_ID_HERE"
$MAX_BYTES = "107374182400"

Write-Host "Setting project to $PROJECT_ID..."
gcloud config set project $PROJECT_ID

Write-Host "[1/6] Enabling APIs..."
gcloud services enable run.googleapis.com storage-component.googleapis.com secretmanager.googleapis.com iam.googleapis.com cloudbuild.googleapis.com

Write-Host "[2/6] Provisioning Secure Storage Bucket..."
try {
    gcloud storage buckets describe "gs://$BUCKET_NAME" 2>$null
} catch {
    gcloud storage buckets create "gs://$BUCKET_NAME" --location="$REGION" --uniform-bucket-level-access
}
gcloud storage buckets update "gs://$BUCKET_NAME" --retention-period="$RETENTION_PERIOD"

Write-Host "[3/6] Configuring Service Accounts & IAM..."
$UPLOAD_SA = "upload-broker@${PROJECT_ID}.iam.gserviceaccount.com"
try {
    gcloud iam service-accounts describe "$UPLOAD_SA" 2>$null
} catch {
    gcloud iam service-accounts create upload-broker --display-name="Upload Broker Cloud Run Service Account"
}
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_NAME" --member="serviceAccount:$UPLOAD_SA" --role="roles/storage.objectCreator"

$TELEMETRY_SA = "telemetry-broker@${PROJECT_ID}.iam.gserviceaccount.com"
try {
    gcloud iam service-accounts describe "$TELEMETRY_SA" 2>$null
} catch {
    gcloud iam service-accounts create telemetry-broker --display-name="Telemetry Broker Cloud Run Service Account"
}
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$TELEMETRY_SA" --role="roles/datastore.user"

Write-Host "[4/6] Configuring Secret Manager for PC Tokens..."
try {
    gcloud secrets describe pc-tokens 2>$null
} catch {
    gcloud secrets create pc-tokens --replication-policy="automatic"
    "{}" | gcloud secrets versions add pc-tokens --data-file=-
}
gcloud secrets add-iam-policy-binding pc-tokens --member="serviceAccount:$UPLOAD_SA" --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding pc-tokens --member="serviceAccount:$TELEMETRY_SA" --role="roles/secretmanager.secretAccessor"

Write-Host "[5/6] Deploying Upload Broker Cloud Run Service..."
gcloud run deploy upload-broker --source ./broker --region "$REGION" --service-account "$UPLOAD_SA" --allow-unauthenticated --max-instances 3 --set-env-vars="BUCKET_NAME=${BUCKET_NAME},PROJECT_ID=${PROJECT_ID},MAX_BYTES=${MAX_BYTES}" --quiet

Write-Host "[6/6] Deploying Telemetry Broker Cloud Run Service..."
gcloud run deploy telemetry-broker --source ./telemetry_broker --region "$REGION" --service-account "$TELEMETRY_SA" --allow-unauthenticated --max-instances 3 --set-env-vars="PROJECT_ID=${PROJECT_ID},MONITORING_SHEET_ID=${MONITORING_SHEET_ID}" --quiet

Write-Host "Deployment Complete!"
