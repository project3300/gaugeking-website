"""Skynet branded alerts. Uses Resend; never logs API keys or recipient addresses."""
import json
import os
import sys
import urllib.request
from urllib.error import HTTPError

FROM = "Skynet | Gauge King <skynet@gaugeking.com.au>"
SUBJECTS = {
    "failure_detected": "[SKYNET] Natsoft recovery initiated",
    "test": "[SKYNET] Test notification",
    "repair_started": "[SKYNET] Copilot repair started",
    "fix_deployed": "[SKYNET] Natsoft fix deployed",
    "recovery_failed": "[SKYNET] Natsoft recovery failed",
}

def classify(event_name, event):
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    root = "https://github.com/" + repo
    if event_name == "workflow_dispatch":
        return "test", "This is a controlled test of Skynet email delivery. No Natsoft failure or repair was triggered."
    if event_name == "pull_request":
        pr = event.get("pull_request") or {}
        if event.get("action") not in ("opened", "ready_for_review") or (pr.get("user") or {}).get("login") not in ("Copilot", "copilot-swe-agent[bot]"):
            return None
        return "repair_started", f"Copilot repair PR: {pr.get('html_url', root + '/pulls')}\nStatus: {pr.get('state')}\nSkynet will run independent safety checks before a merge."
    if event_name != "workflow_run":
        return None
    run = event.get("workflow_run") or {}
    name = run.get("name")
    conclusion = run.get("conclusion")
    url = run.get("html_url", root + "/actions")
    if name == "Update race results" and conclusion == "failure":
        return "failure_detected", f"Natsoft results workflow failed.\nDiagnostic run: {url}\nSkynet will preserve previously verified results and request Copilot investigation."
    if name == "Race Guardian - validate Copilot repair" and conclusion in ("failure", "timed_out", "action_required"):
        return "recovery_failed", f"Copilot repair has not passed independent checks. No automatic merge is permitted.\nValidation: {url}"
    if name == "Race Guardian - auto-merge validated repair" and conclusion == "failure":
        return "recovery_failed", f"Automatic merge was blocked or failed.\nWorkflow: {url}"
    if name == "Update race results" and conclusion == "success":
        message = ((run.get("head_commit") or {}).get("message") or "")
        if message.startswith("Race Guardian: verified Natsoft recovery"):
            return "fix_deployed", f"Recovery change passed the race-results publishing workflow.\nDeployment run: {url}"
    return None

def main():
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as stream:
        event = json.load(stream)
    result = classify(os.environ["GITHUB_EVENT_NAME"], event)
    if not result:
        print("Skynet: no notification required for this event.")
        return
    kind, body = result
    token = os.environ.get("RESEND_API_KEY", "")
    recipient = os.environ.get("SKYNET_NOTIFY_EMAIL", "")
    if not token or not recipient:
        if os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch":
            raise SystemExit("Test failed: RESEND_API_KEY or SKYNET_NOTIFY_EMAIL missing")
        print("Skynet: RESEND_API_KEY or SKYNET_NOTIFY_EMAIL missing; notification skipped.")
        return
    payload = {
        "from": FROM, "to": [recipient],
        "subject": SUBJECTS[kind],
        "text": "Skynet | Gauge King\n\n" + body + "\n\nAutomated race-results notification.",
    }
    req = urllib.request.Request("https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                 "User-Agent": "GaugeKing-Skynet/1.0 (GitHub Actions; transactional notifications)",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            if response.status not in (200, 201, 202):
                raise RuntimeError("Unexpected mail provider status")
            print("Skynet: alert accepted by email provider:", kind)
    except HTTPError as exc:
        # Report only Resend's documented error fields, never credentials or payloads.
        reason = "unspecified"
        try:
            error = json.loads(exc.read(4096).decode("utf-8"))
            if isinstance(error, dict):
                reason = str(error.get("message") or error.get("name") or "unspecified")
                # Avoid printing any sensitive or arbitrary server-supplied text.
                reason = reason.replace(token, "[redacted]").replace(recipient, "[redacted]")[:350]
        except (ValueError, UnicodeError):
            pass
        print(f"Skynet: Resend HTTP {exc.code}; reason: {reason}", file=sys.stderr)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
