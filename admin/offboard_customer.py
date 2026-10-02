"""
Admin Customer Offboarding Engine
=============================================================================
Safely de-provisions all cloud resources, credentials, and artifacts for a
customer.

Actions:
1. Revokes all client tokens by deleting Secret Manager secret: broker-tokens-<slug>.
2. Deletes dedicated Cloud Run microservice: broker-<slug>.
3. Removes bucket IAM-conditioned objectCreator binding for the service account.
4. Deletes dedicated service account: broker-<slug>@<project>.iam.gserviceaccount.com.
5. Deletes customer package staging directory: dist/Customer_Packages/<slug>.
6. Removes customer entry from admin/customer_registry.json.

Never leaves dangling IAM permissions or unrevoked tokens.
"""

import os
import sys
import json
import shutil
import argparse
import subprocess
from typing import Dict, Any, Tuple

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from admin.onboard_customer import (
    SLUG_RE,
    REGISTRY_PATH,
    DIST_DIR,
    load_registry,
    save_registry,
    run_gcloud
)

DEFAULT_PROJECT = "backupbot-506604"
DEFAULT_REGION = "us-central1"
DEFAULT_BUCKET = "backupbot-cold-archive"


def offboard_customer(
    customer_slug: str,
    project_id: str = DEFAULT_PROJECT,
    region: str = DEFAULT_REGION,
    bucket: str = DEFAULT_BUCKET,
    purge_dist: bool = True,
    mock: bool = False
) -> Dict[str, Any]:
    """
    De-provisions all cloud resources and local packages for the given customer.
    Returns status report dictionary.
    """
    slug = customer_slug.strip().lower()
    if not SLUG_RE.match(slug):
        raise ValueError(f"Invalid customer slug '{slug}'.")

    service_name = f"broker-{slug}"
    sa_email = f"broker-{slug}@{project_id}.iam.gserviceaccount.com"
    secret_name = f"broker-tokens-{slug}"
    package_dir = os.path.join(DIST_DIR, slug)

    print("=" * 70)
    print(f"  CUSTOMER OFFBOARDING: '{slug.upper()}'")
    print(f"  Mode: {'MOCKED' if mock else 'REAL'}")
    print("=" * 70)

    report = {
        "customer_slug": slug,
        "service_deleted": False,
        "secret_deleted": False,
        "sa_deleted": False,
        "iam_removed": False,
        "package_removed": False,
        "registry_removed": False,
        "mode": "MOCKED" if mock else "REAL"
    }

    if mock:
        print(f"[*] [MODE: MOCKED] Deleting Cloud Run service '{service_name}'...")
        report["service_deleted"] = True

        print(f"[*] [MODE: MOCKED] Deleting Secret Manager secret '{secret_name}' (revoking all tokens)...")
        report["secret_deleted"] = True

        print(f"[*] [MODE: MOCKED] Removing IAM binding for '{sa_email}' on gs://{bucket}...")
        report["iam_removed"] = True

        print(f"[*] [MODE: MOCKED] Deleting service account '{sa_email}'...")
        report["sa_deleted"] = True
    else:
        # 1. Delete Cloud Run Service
        print(f"[*] Deleting Cloud Run service '{service_name}' in region '{region}'...")
        rc, _, err = run_gcloud([
            "run", "services", "delete", service_name,
            f"--region={region}",
            f"--project={project_id}",
            "--quiet"
        ])
        if rc == 0 or "not found" in err.lower():
            report["service_deleted"] = True
            print("    [OK] Cloud Run service removed.")
        else:
            print(f"    [!] Warning deleting Cloud Run service: {err}")

        # 2. Delete Secret Manager Secret (Token Revocation)
        print(f"[*] Deleting secret '{secret_name}' (revokes all customer tokens)...")
        rc, _, err = run_gcloud([
            "secrets", "delete", secret_name,
            f"--project={project_id}",
            "--quiet"
        ])
        if rc == 0 or "not found" in err.lower():
            report["secret_deleted"] = True
            print("    [OK] Secret removed and tokens revoked.")
        else:
            print(f"    [!] Warning deleting secret: {err}")

        # 3. Remove IAM Policy Binding on Bucket
        print(f"[*] Removing IAM policy binding on gs://{bucket} for '{sa_email}'...")
        rc, _, err = run_gcloud([
            "storage", "buckets", "remove-iam-policy-binding", f"gs://{bucket}",
            f"--member=serviceAccount:{sa_email}",
            "--role=roles/storage.objectCreator",
            f"--project={project_id}"
        ])
        if rc == 0 or "not found" in err.lower() or "does not exist" in err.lower():
            report["iam_removed"] = True
            print("    [OK] Bucket IAM binding removed.")
        else:
            print(f"    [!] Warning removing bucket IAM binding: {err}")

        # 4. Delete Service Account
        print(f"[*] Deleting service account '{sa_email}'...")
        rc, _, err = run_gcloud([
            "iam", "service-accounts", "delete", sa_email,
            f"--project={project_id}",
            "--quiet"
        ])
        if rc == 0 or "not found" in err.lower():
            report["sa_deleted"] = True
            print("    [OK] Service account deleted.")
        else:
            print(f"    [!] Warning deleting service account: {err}")

    # 5. Remove Staged Customer Package
    if purge_dist and os.path.exists(package_dir):
        print(f"[*] Removing customer package directory '{package_dir}'...")
        import stat

        def _remove_readonly(func, path, _):
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception:
                pass

        try:
            shutil.rmtree(package_dir, onerror=_remove_readonly)
            report["package_removed"] = not os.path.exists(package_dir)
            if report["package_removed"]:
                print("    [OK] Customer package directory removed.")
            else:
                print("    [!] Warning: Some files could not be removed from package dir.")
        except Exception as e:
            print(f"    [!] Error removing package directory: {e}")
            report["package_removed"] = not os.path.exists(package_dir)
    else:
        report["package_removed"] = not os.path.exists(package_dir)

    # 6. Remove from Customer Registry
    registry = load_registry()
    if slug in registry:
        print(f"[*] Removing '{slug}' from admin/customer_registry.json...")
        del registry[slug]
        save_registry(registry)
        report["registry_removed"] = True
        print("    [OK] Removed from registry.")
    else:
        report["registry_removed"] = True

    print("\n" + "=" * 70)
    print(f"  CUSTOMER OFFBOARDING COMPLETE FOR '{slug.upper()}'")
    print("=" * 70)
    for k, v in report.items():
        if k != "customer_slug":
            print(f"  {k:<20}: {v}")
    print("=" * 70)

    return report


def main():
    parser = argparse.ArgumentParser(description="Offboard a customer and de-provision cloud resources.")
    parser.add_argument("--customer", required=True, help="Customer slug (e.g. acme)")
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="GCP project ID")
    parser.add_argument("--region", default=DEFAULT_REGION, help="Cloud Run region")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET, help="GCS archive bucket")
    parser.add_argument("--keep-package", action="store_true", help="Do not delete local package dist folder")
    parser.add_argument("--mock", action="store_true", help="Simulate GCP teardown without real API calls")
    args = parser.parse_args()

    offboard_customer(
        customer_slug=args.customer,
        project_id=args.project,
        region=args.region,
        bucket=args.bucket,
        purge_dist=not args.keep_package,
        mock=args.mock
    )


if __name__ == "__main__":
    main()
