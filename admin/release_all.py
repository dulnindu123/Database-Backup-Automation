"""
Admin Fleet Release Engine
=============================================================================
Rolls out a new container image to all provisioned customer Upload Broker
Cloud Run microservices.

Actions:
1. Loads active services from admin/customer_registry.json.
2. Deploys updated container image to each customer service:
   gcloud run deploy broker-<slug> --image <image> --region <region>
   (preserves existing customer secrets, IAM policies, and environment variables).
3. Verifies /healthz endpoint on each customer broker URL.
4. Updates registry with release metadata.
5. Emits deployment report.
"""

import os
import sys
import json
import time
import argparse
import subprocess
import urllib.request
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from admin.onboard_customer import load_registry, save_registry, run_gcloud

DEFAULT_IMAGE = "us-central1-docker.pkg.dev/backupbot-506604/backup-broker/upload-broker:latest"
DEFAULT_PROJECT = "backupbot-506604"


def check_health(url: str, timeout: int = 5, max_attempts: int = 10) -> bool:
    """Probes /healthz on the deployed service URL."""
    healthz_url = f"{url.rstrip('/')}/healthz"
    for _ in range(max_attempts):
        try:
            with urllib.request.urlopen(healthz_url, timeout=timeout) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(2)
    return False


def release_all_customers(
    image: str = DEFAULT_IMAGE,
    project_id: str = DEFAULT_PROJECT,
    mock: bool = False,
    target_customer: str = ""
) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Deploys a container image to all active customer microservices.
    Returns (exit_code, results_list).
    """
    registry = load_registry()
    if not registry:
        print("[!] No registered customers found in customer_registry.json")
        return 0, []

    candidates = {}
    for slug, entry in registry.items():
        if entry.get("status") == "active":
            if not target_customer or target_customer.lower() == slug.lower():
                candidates[slug] = entry

    if not candidates:
        print(f"[*] No active customers match filter (target='{target_customer}'). Nothing to release.")
        return 0, []

    print("=" * 70)
    print(f"  ADMIN FLEET ROLLOUT: {len(candidates)} Customer Service(s)")
    print(f"  Target Image: {image}")
    print(f"  Mode        : {'MOCKED' if mock else 'REAL'}")
    print("=" * 70)

    results = []
    has_failure = False

    for slug, entry in candidates.items():
        service_name = entry.get("service_name", f"broker-{slug}")
        region = entry.get("region", "us-central1")
        broker_url = entry.get("broker_url", "")

        print(f"\n[*] Updating customer '{slug}' -> {service_name}...")
        start_t = time.time()

        if mock:
            print(f"    [MODE: MOCKED] Simulated gcloud run deploy {service_name} --image {image}")
            success = True
            err_msg = ""
        else:
            rc, out, err = run_gcloud([
                "run", "deploy", service_name,
                f"--image={image}",
                f"--region={region}",
                f"--project={project_id}",
                "--platform=managed"
            ], timeout=180)
            if rc != 0:
                print(f"    [!] Deploy failed: {err}")
                success = False
                err_msg = err
            else:
                print(f"    [*] Deploy succeeded. Verifying health...")
                healthy = check_health(broker_url)
                if not healthy:
                    print(f"    [!] Warning: /healthz probe timed out on {broker_url}")
                success = healthy
                err_msg = "" if healthy else "healthz timeout"

        elapsed = round(time.time() - start_t, 2)
        status_str = "SUCCESS" if success else "FAILED"
        if not success:
            has_failure = True

        res_item = {
            "slug": slug,
            "service_name": service_name,
            "status": status_str,
            "image": image,
            "broker_url": broker_url,
            "elapsed_seconds": elapsed,
            "error": err_msg
        }
        results.append(res_item)

        # Update registry entry with deployment timestamp
        if success:
            entry["last_image"] = image
            entry["last_deployed_at"] = datetime.now(timezone.utc).isoformat()
            registry[slug] = entry

    save_registry(registry)

    # Print summary table
    print("\n" + "=" * 70)
    print("  FLEET RELEASE SUMMARY")
    print("=" * 70)
    for r in results:
        print(f"  [{r['status']}] {r['slug']:<12} | {r['service_name']:<18} | {r['elapsed_seconds']}s")
        if r['error']:
            print(f"         Error: {r['error']}")
    print("=" * 70)

    exit_code = 1 if has_failure else 0
    return exit_code, results


def main():
    parser = argparse.ArgumentParser(description="Roll out a new container image to all customer Upload Brokers.")
    parser.add_argument("--image", default=DEFAULT_IMAGE, help="Container image URI to deploy")
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="GCP project ID")
    parser.add_argument("--customer", default="", help="Optional single customer slug to update")
    parser.add_argument("--mock", action="store_true", help="Simulate rollout without GCP calls")
    args = parser.parse_args()

    rc, _ = release_all_customers(
        image=args.image,
        project_id=args.project,
        mock=args.mock,
        target_customer=args.customer
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
