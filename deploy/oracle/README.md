# Oracle Cloud promotion gate (not deployed)

**Reason:** GitHub Actions schedule can be delayed or dropped. The new workflow-run fallback and independent GitHub watchdog reduce blind spots, but they DO NOT establish a reliable hourly service if GitHub stops issuing events.

This repo is not connected to the user's Oracle host from this chat; do not presume SSH access, service permissions, Python installation, or credentials.

## Target deployment

- Run a dedicated unprivileged service account on the user's existing Oracle Cloud machine, using a pinned checkout of this repository.
- Verify outbound network connectivity to api.binance.us and GitHub, available disk space, and supported Python.
- Only ONE system may write alpha-crypto-history/history/paper-state.json. Never leave GitHub Actions and Oracle writing state simultaneously.
- Back up and validate current versioned paper state. Refuse malformed or missing prior state after initialization; do not silently reset six simulated portfolios.
- Use a systemd timer at UTC minute 20 of each hour, Persistent=true and a flock lock to prevent overlapping executions. Catch-up invocations must NOT synthesize historical fills.
- Each run: fetch committed state; read public unauthenticated market data; execute ONLY python -m alpha.crypto_cli forward; write temporary results; validate; and atomically commit/push state to the research branch using a narrowly scoped noninteractive GitHub credential kept outside the repository.
- Run python -m alpha.crypto_health after saving. Notify on stale/invalid transitions and recovery; not every hour.
- Never store GitHub credentials, wallet keys, private account data or SSH keys in code, logs or public GitHub issues. No trading API keys, leverage, buying or selling.
- Once two Oracle-originated state updates are independently verified, disable the GitHub crypto paper schedule/fallback so only Oracle writes state. Keep GitHub tests and read-only watchdog. Monitor 24 consecutive UTC hours before claiming hourly reliability.

## Completion gates

1. Authorized remote-administration connection to the existing Oracle host.
2. Read-only server preflight and user-approved installation path.
3. Verified single-writer state and secure branch-scoped GitHub push permission.
4. On-host run, state read-back, and 24-hour cadence check.

**Not done:** No Oracle server has been contacted or modified. No new hosting expenditure. Track in issue #10.
