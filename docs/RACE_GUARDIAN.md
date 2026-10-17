# Race Guardian: autonomous recovery

The existing `Update race results` workflow polls Natsoft and retains the previous
verified results when a scrape fails. `Race Guardian - diagnose failures` opens
one incident instead of creating an issue for every failed poll.

## Required one-time repository setup

In Settings → Secrets and variables → Actions, create:

- `GUARDIAN_COPILOT_TOKEN`: a token with issue-write access that can assign
  GitHub Copilot coding agent. Confirm the GitHub Copilot coding agent is
  enabled for the repository and your GitHub plan.
- `GUARDIAN_MERGE_TOKEN`: a **separate, narrowly scoped** bot token with
  repository contents and pull-request write permissions and read access to
  Actions and issues. This is intentionally not the default `GITHUB_TOKEN`:
  GitHub-generated token actions do not trigger normal downstream workflows
  when they create commits. Store it only as an Actions secret. Never paste
  credentials in issues or log files.

Repository Settings → Actions → General must allow workflows to operate, and
branch protection must permit your designated automation account to merge only
after required checks. Do not disable broader branch protection to make this
work. If organizational policy prohibits unattended merges, this system fails
closed until policy is configured.

## Recovery process

1. Natsoft poll fails. The diagnostic workflow records the failed run and
   opens/reuses a `[Race Guardian]` issue.
2. Copilot must submit a PR from this repository, linked in its body to the
   **active Guardian issue** (e.g. `Fixes #1`); a PR that does not reference
   the active incident cannot be auto-merged.
3. The unprivileged `Race Guardian - validate Copilot repair` PR workflow
   checks that only `natsoft_browser.py` was modified (maximum 120 changed
   lines), preserves URL/transport protections, runs Python syntax validation
   and executes a live **read-only** Natsoft scrape in an ephemeral runner.
   The probe validates that results belong to the configured event and that
   it found real rows. It does not deploy or push scraped data.
4. On a successful check, the separate privileged workflow rechecks the exact
   tested commit, PR author, changed file, active issue and passing CI check.
   It then squash-merges using `GUARDIAN_MERGE_TOKEN`.
5. The ordinary main-branch workflow runs again after the PAT-authorized
   merge and publishes new results only after the scraper succeeds.

## Natsoft Live timing recovery contract

For the selected meeting, the **Live** column (`c2`) is authoritative. The date cell and **View** column (`c3`) are not acceptable fallback sources for race-day timing. Skynet's incident instructions require Copilot to preserve this behavior. The static gate rejects removal of the Live selection markers and known date/View fallbacks. This is a structural check, **not** proof that the Live timing payload is correctly parsed or fresh. The existing read-only smoke test must still pass, and race-day operators should verify its output against Natsoft Live. If parsing fails, retain the last verified result and fail closed.

## Safeguards and limitations

- Candidate code runs only in the unprivileged PR workflow, without secrets.
  The privileged merge workflow only calls GitHub's API.
- PRs by anyone other than `copilot-swe-agent[bot]`, from forks, with changed
  workflows/config/results, or missing a Guardian issue association will not
  auto-merge.
- The static gate is **not a proof of code safety**. Only grant the merge token
  the minimum practical privileges. External code, dependencies and GitHub
  branch rules remain important security boundaries.
- The smoke test needs a **currently published Natsoft result for the
  configured event**. Before that event has posted results, the check will fail
  closed, so autonomous repairs cannot be merged.
- The process does not auto-roll back a bad patch or auto-close incidents.
  A human should review failed incidents and abnormal automated activity.
- To disable automatic merges immediately, remove `GUARDIAN_MERGE_TOKEN`
  or disable `Race Guardian - auto-merge validated repair`.

## Controlled trial

With a known-good, published event configured, use a disposable test PR
authored by the Copilot agent and explicitly linked to the Guardian issue.
Confirm that an unrelated-file change fails the gate, a bad URL-change fails
the gate, and an invalid scrape fails the live probe. Only a fully successful
single-file patch should be merged. Review Actions run logs before relying on
unattended recovery on race day.

## Skynet identity and branded email

The autonomous recovery system is branded **Skynet**; GitHub Copilot remains
the underlying coding agent, and GitHub's own Copilot notification sender cannot
be renamed.

`.github/workflows/skynet-notifications.yml` sends lifecycle alerts using
`skynet_notify.py` and Resend:

- Failed `Update race results` run: **[SKYNET] Natsoft recovery initiated**.
- Copilot-created PR opened or marked ready: **[SKYNET] Copilot repair started**.
- Independent verification or merge workflow failed: **[SKYNET] Natsoft recovery failed**.
- Post-merge `Update race results` workflow succeeded with a Race Guardian
  recovery commit: **[SKYNET] Natsoft fix deployed**.

Sender display name: **Skynet | Gauge King**. Sender address:
`skynet@gaugeking.com.au`.

For actual delivery, first verify `gaugeking.com.au` as a sending domain in
Resend, and add these **repository Actions secrets**:

- `RESEND_API_KEY`: restricted API credential from Resend.
- `SKYNET_NOTIFY_EMAIL`: destination email address for alerts.

Notifications skip safely when credentials are missing, without disrupting the
scraper or the merge gate. No email delivery has been confirmed until the sender
domain and secrets are configured and a workflow emits an alert.

GitHub Copilot's native emails are separate. To avoid duplicates, adjust GitHub
notification preferences or filter GitHub messages in your mailbox.
