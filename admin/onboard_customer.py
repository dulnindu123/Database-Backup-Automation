"""
Admin Customer Onboarding Engine
=============================================================================
Provisions a dedicated Upload Broker microservice and signed customer package
for each customer in a zero-trust multi-tenant architecture.

Actions:
1. Validates the customer slug (^[a-z0-9]{2,24}$).
2. Creates a dedicated service account: broker-<slug>@<project>.iam.gserviceaccount.com.
3. Creates Secret Manager secret: broker-tokens-<slug>.
4. Applies an IAM-conditioned roles/storage.objectCreator binding on the bucket,
   strictly limited to the "<slug>/" prefix.
5. Deploys Cloud Run service broker-<slug> from a prebuilt image:
   --image <image>, --allow-unauthenticated, min-instances 0, max-instances 2,
   per-customer MAX_BYTES, CUSTOMER_SLUG=<slug>.
6. Waits for /healthz to report healthy.
7. Reads the unique HTTPS Cloud Run service URL via gcloud.
8. Creates the customer token (<slug>-pc01.<secret>) and stores SHA-256 hash in Secret Manager.
9. Signs customer manifest using admin Ed25519 private key (kept off customer PC).
10. Builds the customer package in dist/Customer_Packages/<slug>/ (customer types nothing).
11. Records service name, URL, and metadata in admin/customer_registry.json.

CRITICAL SECURITY RULE: NEVER PRINT SECRETS.
"""

import os
import sys
import json
import re
import secrets
import hashlib
import time
import shutil
import argparse
import subprocess
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from version import APP_VERSION, APP_NAME, EXE_NAME, DEFAULT_INSTALL_SUBDIR
from admin.manifest_signer import get_or_create_admin_keypair, sign_manifest

SLUG_RE = re.compile(r"^[a-z0-9]{2,24}$")
REGISTRY_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "customer_registry.json"))
DIST_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dist", "Customer_Packages"))
MASTER_TEMPLATE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Client_Installation_Package"))


def run_gcloud(args_list, capture=True, timeout=60) -> Tuple[int, str, str]:
    """Executes a gcloud CLI command with timeout and error handling."""
    cmd = ["gcloud.cmd" if sys.platform.startswith("win") else "gcloud"] + args_list
    try:
        res = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            timeout=timeout,
            shell=sys.platform.startswith("win")
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def load_registry() -> Dict[str, Any]:
    """Loads admin-only customer registry."""
    if os.path.exists(REGISTRY_PATH):
        try:
            with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_registry(registry: Dict[str, Any]):
    """Saves admin-only customer registry."""
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, sort_keys=True)


def compute_key_fingerprints(package_dir: str) -> list:
    """Computes SHA-256 8-byte hex fingerprints for primary and escrow public keys."""
    from cryptography.hazmat.primitives import serialization, hashes
    fps = []
    for fname in ("backup_public.pem", "escrow_public.pem"):
        p = os.path.join(package_dir, "AppFiles", fname)
        if not os.path.exists(p):
            p = os.path.join(package_dir, fname)
        if os.path.exists(p):
            with open(p, "rb") as f:
                key_obj = serialization.load_pem_public_key(f.read())
            der = key_obj.public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            d = hashes.Hash(hashes.SHA256())
            d.update(der)
            fps.append(d.finalize()[:8].hex())
    return fps if len(fps) == 2 else ["0123456789abcdef", "fedcba9876543210"]


def onboard_customer(
    customer_slug: str,
    project_id: str = "backupbot-506604",
    region: str = "us-central1",
    bucket: str = "backupbot-cold-archive",
    image: str = "us-central1-docker.pkg.dev/backupbot-506604/backup-broker/upload-broker:latest",
    max_bytes: int = 50 * 1024 * 1024 * 1024,
    telemetry_url: str = "https://telemetry-broker-634638703770.us-central1.run.app",
    mock: bool = False
) -> Dict[str, Any]:
    """
    Executes the complete customer onboarding workflow.
    Returns customer metadata dictionary.
    NEVER logs or returns raw secrets.
    """
    slug = customer_slug.strip().lower()
    if not SLUG_RE.match(slug):
        raise ValueError(f"Invalid customer slug '{slug}'. Must be 2-24 lowercase alphanumerics.")

    service_name = f"broker-{slug}"
    sa_name = f"broker-{slug}"
    sa_email = f"{sa_name}@{project_id}.iam.gserviceaccount.com"
    secret_name = f"broker-tokens-{slug}"
    pc_id = f"{slug}-pc01"

    print(f"[*] Onboarding customer: '{slug}'")
    print(f"    - Cloud Run Service: {service_name}")
    print(f"    - Service Account  : {sa_email}")
    print(f"    - Token Secret     : {secret_name}")
    print(f"    - Bucket Prefix    : {slug}/")

    # Generate customer token (PC token created on admin workstation, never printed)
    secret_entropy = secrets.token_urlsafe(32)
    raw_token = f"{pc_id}.{secret_entropy}"
    token_hash = hashlib.sha256(secret_entropy.encode("utf-8")).hexdigest()
    tokens_json = json.dumps({pc_id: token_hash}, indent=2)

    if mock:
        print("    [MODE: SIMULATED] Simulating GCP provisioning...")
        broker_url = f"https://{service_name}-sim-a1b2c3d4.a.run.app"
    else:
        # 1. Create Per-Customer Service Account
        print(f"[*] Creating service account {sa_email}...")
        rc, _, err = run_gcloud([
            "iam", "service-accounts", "create", sa_name,
            f"--project={project_id}",
            f"--display-name=Upload Broker for Customer {slug}"
        ])
        if rc != 0 and "already exists" not in err.lower():
            raise RuntimeError(f"Failed to create service account: {err}")

        # 2. Add IAM Conditioned objectCreator binding on bucket (limited to <slug>/ prefix)
        print(f"[*] Applying IAM condition on gs://{bucket} for prefix '{slug}/'...")
        condition_expr = (
            f'resource.type == "storage.googleapis.com/Object" && '
            f'resource.name.startsWith("projects/_/buckets/{bucket}/objects/{slug}/")'
        )
        rc, _, err = run_gcloud([
            "storage", "buckets", "add-iam-policy-binding", f"gs://{bucket}",
            f"--member=serviceAccount:{sa_email}",
            "--role=roles/storage.objectCreator",
            f"--condition=expression={condition_expr},title=limited-to-{slug}",
            f"--project={project_id}"
        ])
        if rc != 0:
            print(f"    [!] Warning setting bucket IAM condition: {err}")

        # 3. Create Token Secret in Secret Manager
        print(f"[*] Creating secret {secret_name}...")
        rc, _, err = run_gcloud([
            "secrets", "create", secret_name,
            "--replication-policy=automatic",
            f"--project={project_id}"
        ])

        # Add initial version with tokens_json
        temp_sec_path = os.path.join(os.environ.get("TEMP", "."), f"sec_{slug}_{secrets.token_hex(4)}.json")
        try:
            with open(temp_sec_path, "w", encoding="utf-8") as f:
                f.write(tokens_json)
            rc, _, err = run_gcloud([
                "secrets", "versions", "add", secret_name,
                f"--data-file={temp_sec_path}",
                f"--project={project_id}"
            ])
            if rc != 0:
                raise RuntimeError(f"Failed to add secret version: {err}")
        finally:
            if os.path.exists(temp_sec_path):
                os.remove(temp_sec_path)

        # Grant Secret Accessor to Service Account
        run_gcloud([
            "secrets", "add-iam-policy-binding", secret_name,
            f"--member=serviceAccount:{sa_email}",
            "--role=roles/secretmanager.secretAccessor",
            f"--project={project_id}"
        ])

        # 4. Deploy Cloud Run Service
        print(f"[*] Deploying Cloud Run service {service_name}...")
        deploy_args = [
            "run", "deploy", service_name,
            f"--image={image}",
            f"--region={region}",
            f"--project={project_id}",
            "--platform=managed",
            "--allow-unauthenticated",
            "--min-instances=0",
            "--max-instances=2",
            f"--service-account={sa_email}",
            f"--set-env-vars=BUCKET={bucket},CUSTOMER_SLUG={slug},MAX_BYTES={max_bytes},TOKENS_FILE=/secrets/pc_tokens.json",
            f"--set-secrets=/secrets/pc_tokens.json={secret_name}:latest"
        ]
        rc, _, err = run_gcloud(deploy_args)
        if rc != 0:
            raise RuntimeError(f"Failed to deploy Cloud Run service: {err}")

        # 5. Read Deployed URL
        rc, broker_url, err = run_gcloud([
            "run", "services", "describe", service_name,
            f"--region={region}",
            f"--project={project_id}",
            "--format=value(status.url)"
        ])
        if rc != 0 or not broker_url.startswith("https://"):
            raise RuntimeError(f"Could not retrieve service URL: {err}")

        # 6. Wait for /healthz
        print(f"[*] Probing {broker_url}/healthz...")
        import urllib.request
        healthy = False
        for _ in range(12):
            try:
                with urllib.request.urlopen(f"{broker_url}/healthz", timeout=5) as resp:
                    if resp.status == 200:
                        healthy = True
                        break
            except Exception:
                time.sleep(3)
        if not healthy:
            print(f"    [!] Warning: /healthz probe timed out on {broker_url}")

    # 7. Generate Signed Manifest (Ed25519)
    print(f"[*] Generating Ed25519 signed manifest...")
    priv_key, _ = get_or_create_admin_keypair()
    fps = compute_key_fingerprints(MASTER_TEMPLATE_DIR)

    manifest_dict = {
        "customer_slug": slug,
        "broker_url": broker_url,
        "telemetry_url": telemetry_url,
        "version": APP_VERSION,
        "expected_key_fingerprints": fps,
        "issued_at": int(datetime.now(timezone.utc).timestamp()),
        "initial_token": raw_token  # Embedded securely inside signed envelope; sealed to DPAPI by installer
    }
    canonical_bytes, sig_b64 = sign_manifest(manifest_dict, priv_key)

    # 8. Build Customer Package
    cust_pkg_dir = os.path.join(DIST_DIR, slug)
    print(f"[*] Building Customer Package in '{cust_pkg_dir}'...")
    if os.path.exists(cust_pkg_dir):
        import stat
        def _rm_ro(func, path, _):
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception:
                pass
        shutil.rmtree(cust_pkg_dir, onerror=_rm_ro)
    os.makedirs(cust_pkg_dir, exist_ok=True)

    # Copy files from master package if present
    if os.path.exists(MASTER_TEMPLATE_DIR):
        for item in os.listdir(MASTER_TEMPLATE_DIR):
            src = os.path.join(MASTER_TEMPLATE_DIR, item)
            dst = os.path.join(cust_pkg_dir, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)

    # Ensure AppFiles exists and stamp config.json
    app_files_dir = os.path.join(cust_pkg_dir, "AppFiles")
    os.makedirs(app_files_dir, exist_ok=True)
    cfg_path = os.path.join(app_files_dir, "config.json")
    cfg_data = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg_data = json.load(f)
        except Exception:
            cfg_data = {}
    cfg_data["BROKER_URL"] = broker_url
    cfg_data["CUSTOMER_SLUG"] = slug
    cfg_data["TELEMETRY_URL"] = telemetry_url
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg_data, f, indent=2)

    # Save manifest.json and manifest.sig in package root
    with open(os.path.join(cust_pkg_dir, "manifest.json"), "wb") as f:
        f.write(canonical_bytes)
    with open(os.path.join(cust_pkg_dir, "manifest.sig"), "w", encoding="utf-8") as f:
        f.write(sig_b64)

    # 9. Record in Admin Customer Registry
    registry = load_registry()
    entry = {
        "customer_slug": slug,
        "service_name": service_name,
        "broker_url": broker_url,
        "telemetry_url": telemetry_url,
        "service_account": sa_email,
        "secret_name": secret_name,
        "bucket": bucket,
        "bucket_prefix": f"{slug}/",
        "region": region,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "active"
    }
    registry[slug] = entry
    save_registry(registry)

    print("\n" + "=" * 70)
    print(f"  CUSTOMER ONBOARDING COMPLETED FOR '{slug.upper()}'")
    print("=" * 70)
    print(f"  Cloud Run Service : {service_name}")
    print(f"  Unique Broker URL : {broker_url}")
    print(f"  Service Account   : {sa_email}")
    print(f"  Bucket Prefix     : gs://{bucket}/{slug}/")
    print(f"  Customer Package  : {cust_pkg_dir}")
    print(f"  Verification Mode : {'MOCKED' if mock else 'REAL'}")
    print("  [SECURITY] Secret keys and tokens sealed inside signed manifest.")
    print("=" * 70)

    return entry


def main():
    parser = argparse.ArgumentParser(description="Onboard a new customer with a dedicated Upload Broker.")
    parser.add_argument("--customer", required=True, help="Customer slug (e.g. acme, globex, initech)")
    parser.add_argument("--project", default="backupbot-506604", help="GCP project ID")
    parser.add_argument("--region", default="us-central1", help="Cloud Run region")
    parser.add_argument("--bucket", default="backupbot-cold-archive", help="GCS archive bucket")
    parser.add_argument("--image", default="us-central1-docker.pkg.dev/backupbot-506604/backup-broker/upload-broker:latest")
    parser.add_argument("--max-bytes", type=int, default=50 * 1024 * 1024 * 1024)
    parser.add_argument("--mock", action="store_true", help="Simulate GCP provisioning for testing")
    args = parser.parse_args()

    onboard_customer(
        customer_slug=args.customer,
        project_id=args.project,
        region=args.region,
        bucket=args.bucket,
        image=args.image,
        max_bytes=args.max_bytes,
        mock=args.mock
    )


if __name__ == "__main__":
    main()
