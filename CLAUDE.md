# CLAUDE.md — ServerWatch AI Development Instructions

> This file is the operational instruction set for AI coding agents working on ServerWatch.
>
> **Primary objective:** Implement ServerWatch according to `PROJECT_PLAN.md` without hallucinating requirements, silently changing architecture, or adding unnecessary features.

---

# 1. Source of Truth

The repository's `PROJECT_PLAN.md` is the authoritative product and architecture blueprint.

Before implementing or modifying a significant feature:

1. Read the relevant section of `PROJECT_PLAN.md`.
2. Inspect the existing repository/code.
3. Understand the current architecture.
4. Implement only what is supported by the plan.
5. If the plan is ambiguous or contradictory, stop and ask for clarification instead of inventing a requirement.

Do not assume that a common pattern is automatically appropriate for ServerWatch.

---

# 2. Critical Anti-Hallucination Rule

Never invent:

- APIs
- Linux files
- systemd behavior
- permissions
- Tailscale headers
- database tables
- environment variables
- configuration values
- frontend routes
- security behavior
- library APIs
- unsupported hardware capabilities

If unsure, verify using authoritative documentation or inspect the actual environment/code.

For Linux behavior, prefer:

1. official Linux/kernel/systemd documentation
2. official Python/package documentation
3. official Tailscale documentation
4. official SQLite documentation
5. official FastAPI/Uvicorn documentation
6. official React/TypeScript documentation

Do not present guesses as facts.

---

# 3. No Silent Architecture Changes

Do NOT silently:

- replace SQLite with PostgreSQL
- introduce Redis
- introduce Docker
- introduce Kubernetes
- add Nginx
- change FastAPI to another backend
- change React to another frontend framework
- change Tailscale Serve to Funnel
- expose FastAPI publicly
- run the application as root
- introduce a remote agent architecture
- add arbitrary shell execution
- add privileged operations

If a change appears necessary, explain why and request approval.

---

# 4. MVP Scope

The MVP is READ-ONLY.

Do not implement:

- service restart/stop/start
- process killing
- reboot
- shutdown
- arbitrary command execution
- arbitrary shell execution
- web terminal
- arbitrary filesystem access

Monitoring and visualization are the priority.

---

# 5. Security Rules

These rules are mandatory.

## Never run the main application as root.

Use:

```text
serverwatch:serverwatch
```

## Never use arbitrary shell commands for application functionality.

Forbidden pattern:

```python
subprocess.run(user_input, shell=True)
```

Do not replace it with a different form of arbitrary command execution.

## Never accept arbitrary filesystem paths from users.

## Never trust client-provided roles.

Roles must be determined server-side.

## Never blindly trust Tailscale identity headers.

They are trusted only when the request is guaranteed to have passed through the trusted Tailscale Serve path.

FastAPI should bind to localhost in the intended deployment.

## Never expose secrets in:

- API responses
- logs
- exceptions
- frontend source
- WebSocket messages
- error pages

## Validate all external input.

This includes:

- REST parameters
- query ranges
- pagination
- WebSocket messages
- process IDs
- service identifiers
- configuration values

---

# 6. Tailscale Rules

MVP network architecture:

```text
Tailnet
   |
Tailscale Serve
   |
127.0.0.1:8000
   |
FastAPI
```

Use Tailscale Serve, not Funnel.

Tailscale provides the private network/identity boundary.

ServerWatch provides application-level authorization.

Do not make ServerWatch dependent on public Internet access.

Do not add public DNS or port forwarding.

---

# 7. Privilege Model

The monitoring application should run unprivileged.

Do not add Linux capabilities just to make a collector easier.

If a metric is unavailable due to permissions:

1. determine whether the metric is truly required;
2. document the limitation;
3. use the narrowest permission possible;
4. never make the entire application root merely to access one metric.

Future privileged operations must use a separate narrowly scoped helper.

---

# 8. Monitoring Architecture

Collectors must be independent.

Expected collector concepts:

```text
CPU
Memory
Disk
Network
Filesystem
Temperature
Processes
Services
Events
```

A collector failure must not crash the monitoring engine.

Each collector should report:

- state
- timestamp
- data
- errors/diagnostics
- collection duration where useful

Use bounded retry behavior.

---

# 9. Missing Data

Never fabricate values.

Bad:

```text
temperature = 0
```

when no sensor exists.

Bad:

```text
network = 0
```

when the collector failed.

Prefer an explicit representation such as:

```text
status = unavailable
value = null
reason = ...
```

Stale data must be distinguishable from current data.

---

# 10. Timing Rules

Use monotonic time for:

- elapsed intervals
- rate calculations
- collector duration
- timeout calculations

Use UTC wall-clock timestamps for:

- stored events
- database timestamps
- user-facing dates/times

Never calculate rates from wall-clock timestamps if a monotonic clock is available.

---

# 11. Performance Rules

ServerWatch is intended for resource-constrained Linux systems.

Avoid:

- spawning shell commands for routine metrics
- unnecessarily frequent process enumeration
- unbounded memory structures
- unlimited WebSocket clients
- unlimited database queues
- huge historical queries
- continuous detailed process history
- unnecessary background services
- excessive frontend animations

Prefer:

```text
/proc
/sys
psutil
systemd APIs
journald APIs
```

over repeatedly executing:

```text
top
free
df
iostat
ip
sensors
systemctl
journalctl
```

from subprocesses.

Do not optimize prematurely. Measure first.

---

# 12. Process Monitoring

Use psutil efficiently.

Collect only fields needed for the current view.

For multiple process attributes, use appropriate psutil batching mechanisms such as `oneshot()` when beneficial.

Be aware of PID reuse.

When process identity matters, consider:

```text
PID + process start time
```

rather than PID alone.

---

# 13. Database Rules

SQLite is the MVP database.

Use:

```text
WAL
foreign keys enabled
UTC timestamps
schema versioning
batched writes
bounded queue
```

The database is for historical persistence, not live application state.

Do not scatter raw SQL across API routes and collectors.

Prefer a clear storage/repository layer.

Do not allow the frontend to access SQLite directly.

---

# 14. Database Writer

Use:

```text
Collector
   |
DB Queue
   |
DB Writer
   |
SQLite transaction
```

Do not perform an independent database transaction for every tiny metric update if batching can safely reduce overhead.

The queue must be bounded.

Never allow database backlog to grow without limit.

Low-priority raw metric samples may be dropped under pressure according to the documented policy.

Important events/alerts should receive higher persistence priority.

---

# 15. Database Schema

Initial conceptual tables:

```text
servers
cpu_samples
memory_samples
disk_samples
network_samples
filesystem_samples
temperature_samples
events
alerts
metric_rollups
schema_metadata
```

Do not add tables simply because they seem conventional.

Every table should have a clear purpose.

Do not rename or restructure schema tables casually once data exists.

Use migrations.

---

# 16. API Rules

API prefix:

```text
/api/v1
```

Use Pydantic models for request/response validation.

Use consistent error responses.

Do not expose internal Python exception details.

Bound:

- time ranges
- page sizes
- result counts
- chart points
- expensive operations

Do not allow a client to request arbitrary amounts of historical data.

---

# 17. WebSocket Rules

Endpoint:

```text
/ws/live
```

Every connection must be authenticated and authorized.

Validate Origin.

Use:

```text
sequence
timestamp
type
data
```

for messages.

Support heartbeat and reconnect.

Do not assume every live update reaches every client.

If a sequence gap occurs, clients should resynchronize through REST.

Bound:

- number of connections
- message size
- message rate
- outgoing queue size

A slow client must not block the monitoring engine.

---

# 18. Authentication and RBAC

Use the internal abstraction:

```text
UserIdentity
```

Do not spread Tailscale-specific logic through business code.

MVP roles:

```text
Viewer
Administrator
```

Viewer is read-only.

Administrator can manage ServerWatch application settings when implemented.

Administrator is NOT Linux root.

Never accept:

```json
{
  "role": "Administrator"
}
```

from the client as authoritative.

The server determines roles.

---

# 19. Frontend Rules

Stack:

```text
React
TypeScript
Vite
```

Keep API communication in a dedicated service layer.

Do not put fetch logic everywhere in components.

Use typed API models.

Avoid excessive re-rendering.

Charts must have bounded data.

Large process/event tables should be virtualized if necessary.

Do not rely only on color to communicate status.

---

# 20. UI Design Rules

Use the ServerWatch visual system:

```text
#A60E35  Crimson
#FEA24F  Orange
#10BBC3  Cyan
#068187  Teal
#051A2D  Deep Navy
```

Preferred visual direction:

- dark
- technical
- compact
- modern
- information-dense
- restrained

Avoid:

- excessive neon
- excessive glow
- cyberpunk styling
- decorative gradients
- 3D charts
- oversized cards
- unnecessary animations

---

# 21. Systemd Rules

Production deployment must use systemd.

Expected characteristics:

```text
dedicated user
automatic startup
Restart=on-failure
bounded restart rate
graceful shutdown
journald logging
security hardening
```

Potential hardening options must be tested rather than copied blindly.

If hardening prevents legitimate monitoring access, diagnose the exact restriction and adjust narrowly.

Do not disable all security hardening just because one collector fails.

---

# 22. Logging Rules

Use journald/stdout/stderr.

Default:

```text
INFO
```

Do not log every metric sample.

Do not log:

- passwords
- access tokens
- private keys
- session secrets
- credentials

Sanitize sensitive exceptions before returning/logging them.

---

# 23. Reliability Rules

The application should fail soft.

Examples:

```text
temperature failure
→ temperature unavailable
→ other monitoring continues
```

```text
database failure
→ live state continues
→ historical storage degraded
```

```text
Tailscale failure
→ monitoring continues locally
→ remote dashboard unavailable
```

```text
WebSocket failure
→ REST remains available
```

```text
collector exception
→ collector degraded/failed
→ retry
```

Do not make optional functionality a single point of failure.

---

# 24. Health States

Use:

```text
HEALTHY
DEGRADED
FAILED
RECOVERING
```

Avoid declaring the whole application failed because one optional sensor is unavailable.

Distinguish:

```text
Server Health
```

from:

```text
ServerWatch Health
```

---

# 25. Alert Rules

Alerting must include persistence.

Avoid:

```text
CPU > 90%
→ immediate alert
```

Prefer:

```text
CPU > 90%
for N duration
→ pending/firing
```

Use hysteresis where appropriate.

Avoid alert storms.

Deduplicate ongoing conditions.

Alert states:

```text
OK
PENDING
FIRING
RECOVERED
```

MVP notification channel is the dashboard.

---

# 26. Error Handling

Never do:

```python
except Exception:
    pass
```

without recording meaningful diagnostics.

Also do not expose raw exceptions to users.

Expected approach:

```text
catch
→ classify
→ log useful diagnostic
→ mark component degraded
→ retry/recover where appropriate
```

Unexpected programming errors should remain visible in developer logs/tests.

---

# 27. Testing Rules

Every meaningful backend component should have tests.

Important test categories:

- normal operation
- missing data
- permission errors
- malformed Linux data
- counter resets
- PID reuse
- database lock
- database failure
- disk pressure
- WebSocket disconnect
- authentication failure
- authorization failure
- invalid input
- rate limiting
- collector crash
- system reboot/restart

Do not mark a feature complete merely because the happy path works.

---

# 28. Security Testing

Before declaring a security-sensitive feature complete, test:

- authentication bypass
- authorization bypass
- forged roles
- forged identity headers
- Origin bypass
- oversized WebSocket messages
- connection exhaustion
- query exhaustion
- path traversal
- command injection
- SQL injection
- SSRF in any future remote functionality
- sensitive data leakage
- log leakage

---

# 29. Dependency Rules

Prefer a small dependency set.

Before adding a dependency:

1. Determine whether the standard library or existing dependency can solve the problem.
2. Check whether the dependency is maintained.
3. Check its license compatibility.
4. Consider its resource cost.
5. Consider its security history.
6. Explain why it is needed.

Do not add libraries merely for convenience.

---

# 30. Documentation Rules

When implementing a significant component, update relevant documentation.

Document:

- purpose
- data source
- permissions
- interval
- failure behavior
- security implications
- performance implications

Do not let code and architecture documentation silently diverge.

---

# 31. Git Rules

Use small, logical commits.

Preferred examples:

```text
feat: add CPU collector
feat: add memory collector
feat: add SQLite storage
feat: add REST state API
feat: add live WebSocket updates
fix: handle missing temperature sensors
test: add process collector tests
docs: update deployment architecture
```

Do not create huge commits containing unrelated changes.

Never commit:

- secrets
- `.env` containing credentials
- production databases
- private keys
- temporary dumps
- generated junk

---

# 32. Implementation Workflow for AI

For every task:

## Step 1 — Inspect

Read:

```text
PROJECT_PLAN.md
CLAUDE.md
relevant source files
tests
configuration
```

## Step 2 — Plan

Before editing, state:

- what will change
- which files are affected
- why
- what existing architecture is being reused

## Step 3 — Implement

Make the smallest coherent change.

## Step 4 — Test

Run relevant tests.

## Step 5 — Inspect

Review the diff.

Check for:

- accidental architecture changes
- unnecessary dependencies
- security regressions
- debug code
- hardcoded values
- duplicated logic

## Step 6 — Report

Summarize:

- files changed
- functionality added
- tests run
- failures
- remaining concerns

---

# 33. When to Stop and Ask

Stop instead of guessing if:

- requirements conflict
- architecture is ambiguous
- a security decision is required
- a dependency choice materially changes the architecture
- a Linux permission is unclear
- a Tailscale behavior is unclear
- a database migration could destroy data
- a proposed implementation requires root
- a requested feature conflicts with MVP scope
- a feature would introduce public network exposure
- a third-party API behavior is uncertain

The correct behavior is to explain the uncertainty and ask.

---

# 34. No Hallucinated Completion

Never say:

```text
implemented
tested
verified
working
secure
production-ready
```

unless the corresponding work was actually performed.

Distinguish:

```text
planned
implemented
tested
verified
```

These are different states.

---

# 35. No Fake Testing

Never claim tests passed unless they were actually executed.

Never claim:

```text
systemd verified
Tailscale verified
database migration verified
performance benchmark passed
```

without performing those tests.

---

# 36. No Premature Optimization

Do not optimize based on assumptions.

First measure:

```text
CPU
RAM
disk
latency
queue depth
DB write cost
frontend render cost
```

Then optimize the actual bottleneck.

---

# 37. No Feature Creep

If an idea is outside the MVP:

1. identify it as future work;
2. do not implement it automatically;
3. preserve the architecture for possible future support if inexpensive.

Examples:

```text
email
mobile app
multi-server
remote agents
service control
reboot
SMART
external notifications
```

---

# 38. Definition of a Good Implementation

A good ServerWatch implementation should be:

```text
Correct
Secure
Small
Testable
Observable
Recoverable
Maintainable
Documented
```

Not merely:

```text
"It works on my machine."
```

---

# 39. Final Rule

When uncertain:

> **Do not invent. Inspect, verify, document, and ask.**

The goal is to implement the existing ServerWatch blueprint faithfully, not to redesign the project autonomously.
