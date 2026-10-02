"""
Admin Log Alerting Setup Engine
=============================================================================
Configures per-customer Cloud Run security log metrics and alerting policies.

Monitored Security Events:
1. 'customer_mismatch': PC token prefix does not match the customer slug
   (indicates cross-tenant token replay or unauthorized access).
2. 'auth_rejected': Missing, malformed, or revoked token.

Cloud Monitoring Integration:
- Uses Google Cloud Logging log-based metric filters:
  resource.type = "cloud_run_revision"
  resource.labels.service_name = "broker-<slug>"
  jsonPayload.event = ("customer_mismatch" OR "auth_rejected")
- Supports real gcloud provisioning and unit-test mock execution.
"""

import os
import sys
import json
import argparse
import subprocess
from typing import Dict, Any, Tuple

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def run_gcloud(args_list, capture=True, timeout=60) -> Tuple[int, str, str]:
    """Executes gcloud command line tool."""
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


def build_log_filter(service_name: str, event_name: str) -> str:
    """Builds Cloud Logging query string for specific security audit events."""
    return (
        f'resource.type="cloud_run_revision" AND '
        f'resource.labels.service_name="{service_name}" AND '
        f'jsonPayload.event="{event_name}"'
    )


def configure_customer_alerts(
    customer_slug: str,
    project_id: str = "backupbot-506604",
    notification_channel: str = "",
    mock: bool = False
) -> Dict[str, Any]:
    """
    Configures log-based alert metric descriptors for a specific customer broker.
    """
    slug = customer_slug.strip().lower()
    service_name = f"broker-{slug}"
    metric_name = f"broker_{slug}_security_events"

    filter_expr = (
        f'resource.type="cloud_run_revision" AND '
        f'resource.labels.service_name="{service_name}" AND '
        f'(jsonPayload.event="customer_mismatch" OR jsonPayload.event="auth_rejected")'
    )

    alert_spec = {
        "customer_slug": slug,
        "service_name": service_name,
        "metric_name": metric_name,
        "log_filter": filter_expr,
        "monitored_events": ["customer_mismatch", "auth_rejected"],
        "condition": "count > 0 in 5 minutes",
        "severity": "WARNING",
        "status": "configured"
    }

    print(f"[*] Setting up log alert policies for '{service_name}'...")
    print(f"    - Metric Name : logging.googleapis.com/user/{metric_name}")
    print(f"    - Filter Expr : {filter_expr}")

    if mock:
        print("    [MODE: MOCKED] Simulated Cloud Monitoring alert policy creation.")
        return alert_spec

    # 1. Create or update log-based metric
    rc, _, err = run_gcloud([
        "logging", "metrics", "create", metric_name,
        f"--description=Security audit events for {service_name}",
        f"--log-filter={filter_expr}",
        f"--project={project_id}"
    ])
    if rc != 0 and "already exists" not in err.lower():
        print(f"    [!] Warning creating log metric: {err}")

    # 2. If notification channel is specified, link alert policy
    if notification_channel:
        policy_json = {
            "displayName": f"Security Alert - {service_name}",
            "conditions": [
                {
                    "displayName": "Cross-customer access or auth rejections",
                    "conditionThreshold": {
                        "filter": f'metric.type="logging.googleapis.com/user/{metric_name}" AND resource.type="cloud_run_revision"',
                        "comparison": "COMPARISON_GT",
                        "thresholdValue": 0,
                        "duration": "300s",
                        "trigger": {"count": 1}
                    }
                }
            ],
            "notificationChannels": [notification_channel],
            "combiner": "OR",
            "enabled": True
        }
        temp_policy = os.path.join(os.environ.get("TEMP", "."), f"policy_{slug}.json")
        try:
            with open(temp_policy, "w", encoding="utf-8") as f:
                json.dump(policy_json, f)
            run_gcloud([
                "alpha", "monitoring", "policies", "create",
                f"--policy-from-file={temp_policy}",
                f"--project={project_id}"
            ])
        finally:
            if os.path.exists(temp_policy):
                os.remove(temp_policy)

    return alert_spec


def main():
    parser = argparse.ArgumentParser(description="Configure per-service log alerts in Cloud Monitoring.")
    parser.add_argument("--customer", required=True, help="Customer slug (e.g. acme)")
    parser.add_argument("--project", default="backupbot-506604", help="GCP project ID")
    parser.add_argument("--channel", default="", help="Notification channel ID")
    parser.add_argument("--mock", action="store_true", help="Simulate GCP configuration")
    args = parser.parse_args()

    configure_customer_alerts(
        customer_slug=args.customer,
        project_id=args.project,
        notification_channel=args.channel,
        mock=args.mock
    )


if __name__ == "__main__":
    main()
