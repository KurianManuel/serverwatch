# ServerWatch — Project Plan & Architecture Blueprint

> **Status:** Architecture and study phase complete. Implementation not yet started.
>
> **Purpose:** This document is the primary project blueprint for implementing ServerWatch. It records the decisions made during the complete pre-implementation study and should be treated as the source of truth unless an explicit architectural change is approved.

---

## 1. Project Overview

**ServerWatch** is a lightweight Linux server monitoring and health dashboard designed to run directly on a Linux server and provide a real-time web interface for observing system health, resources, services, processes, events, alerts, and historical metrics.

The initial target is a resource-constrained Ubuntu Server machine, so the application must be lightweight and must not materially interfere with the server it monitors.

The first release is intentionally **read-only**.

ServerWatch must behave like a native Linux service rather than a development script.

---

## 2. Core Goals

1. Monitor Linux system health in real time.
2. Store useful historical metrics without excessive disk usage.
3. Provide a responsive web dashboard.
4. Detect important system events and service failures.
5. Provide useful alerts without excessive alert noise.
6. Run with least privilege.
7. Avoid public Internet exposure.
8. Use Tailscale as the private network boundary.
9. Recover gracefully from component failures.
10. Keep CPU, RAM, disk, and network overhead low.
11. Make the system testable and maintainable.
12. Leave a clean path for future multi-server support without implementing it in the MVP.

---

# 3. Non-Goals for the MVP

The MVP must NOT implement:

- Arbitrary shell/command execution.
- A web terminal.
- Restart/stop/start services from the UI.
- Killing processes from the UI.
- Reboot/shutdown from the UI.
- Running the entire application as root.
- Public Internet exposure.
- Tailscale Funnel.
- Nginx unless a later architectural decision proves it necessary.
- Docker/Kubernetes.
- Multi-server management.
- Remote monitoring agents.
- Email/Telegram/Discord notification integrations.
- Mobile application.
- Automatic self-updating.
- Complex plugin architecture.
- SMART monitoring unless it can be added cleanly after the core MVP.
- Any feature that requires broad Linux privileges merely for convenience.

---

# 4. Technology Stack

## Backend

- Python 3.x
- FastAPI
- Uvicorn
- Pydantic
- psutil
- SQLite
- Python's SQLite interface
- systemd integration
- Linux `/proc`
- Linux `/sys`
- journald
- systemd D-Bus where appropriate

## Frontend

- React
- TypeScript
- Vite
- Recharts or another lightweight charting library if justified
- CSS-based design system

## Testing

- pytest
- FastAPI test tooling
- WebSocket testing
- mocked Linux data sources
- integration tests
- failure-injection tests

## Deployment

- Ubuntu Server
- systemd
- dedicated `serverwatch` Linux user
- Tailscale
- Tailscale Serve
- SQLite WAL

---

# 5. High-Level Architecture

```text
                         Tailnet
                            |
                     Tailscale Serve
                            |
                         HTTPS/WSS
                            |
                     127.0.0.1:8000
                            |
                         FastAPI
                            |
              +-------------+-------------+
              |                           |
        REST / WebSocket             Auth / RBAC
              |                           |
              +-------------+-------------+
                            |
                     State Manager
                            |
             +--------------+--------------+
             |              |              |
         Collectors       Events       Health/Alerts
             |              |              |
             +--------------+--------------+
                            |
                       Live State
                            |
                       DB Queue
                            |
                       SQLite WAL
                            |
                  Historical Storage

Linux data sources:
  /proc
  /sys
  psutil
  systemd
  journald
  D-Bus
```

---

# 6. Deployment Architecture

ServerWatch must run as a systemd-managed service.

Recommended filesystem layout:

```text
/opt/serverwatch/
    app/
    frontend/
    venv/

/etc/serverwatch/
    serverwatch.env

/var/lib/serverwatch/
    serverwatch.db
    backups/

/etc/systemd/system/
    serverwatch.service
```

Responsibilities:

- `/opt/serverwatch` — replaceable application software.
- `/etc/serverwatch` — configuration.
- `/var/lib/serverwatch` — persistent mutable application data.
- systemd — lifecycle and process supervision.
- journald — application logs.

The production backend should listen only on:

```text
127.0.0.1:8000
```

Tailscale Serve provides private HTTPS/WSS access to the tailnet.

---

# 7. Linux User and Privilege Model

Create a dedicated service identity:

```text
serverwatch:serverwatch
```

The main application must not run as root.

The MVP should require no additional Linux capabilities.

Do NOT solve permission problems by changing the entire service to root.

If a future feature requires privileged operations, use a narrowly scoped privileged helper rather than giving FastAPI root access.

Future helper examples:

```text
restart_service(service_id)
read_smart(device_id)
reboot()
```

Never implement:

```text
execute(command)
```

or any equivalent arbitrary-command interface.

---

# 8. Monitoring Data Sources

## CPU

Primary source:

```text
/proc/stat
```

Metrics:

- overall CPU utilization
- per-core utilization
- user time
- system time
- idle
- iowait where available
- CPU count
- CPU model (static system information)
- load average

CPU utilization must be calculated from counter deltas.

Use monotonic time for rate calculations.

---

## Memory

Primary source:

```text
/proc/meminfo
```

Metrics:

- total memory
- available memory
- used memory
- free memory
- buffers/cache where useful
- swap total
- swap used
- swap free

`MemAvailable` should be preferred over `MemFree` when representing usable memory.

---

## Disk I/O

Sources:

```text
/proc/diskstats
/sys/block/*
```

Metrics:

- read bytes
- write bytes
- read operations
- write operations
- throughput
- IOPS where practical
- utilization/busy time where practical

Disk capacity and disk I/O are separate concepts.

---

## Filesystem

Use filesystem APIs/psutil/statvfs-style data.

Metrics:

- total space
- used space
- available space
- percentage
- inode usage where available

Filesystem capacity collection should be slower than CPU/network collection.

---

## Network

Sources may include:

```text
/proc/net/dev
```

and netlink/rtnetlink where justified.

Metrics:

- interface state
- RX bytes
- TX bytes
- RX packets
- TX packets
- errors
- drops
- throughput

Do not use packet capture for normal bandwidth monitoring.

---

## Processes

Use psutil and `/proc`.

MVP fields:

- PID
- process name
- CPU percentage
- RSS memory
- process state
- start time where useful

Do not continuously collect every possible process attribute.

Process enumeration may be relatively expensive and should run less frequently than cheap system counters.

PID reuse must be considered. PID plus process start time should be used when a stable process identity is required.

---

## systemd Services

Use systemd/D-Bus APIs where practical instead of repeatedly spawning `systemctl`.

MVP information:

- service/unit name
- active state
- substate
- load state where available
- failed state
- state transitions where detectable

Service control is NOT part of the MVP.

---

## journald / Events

Use structured journal access rather than repeatedly parsing raw journal output.

Potential events:

- service failures
- service state changes
- OOM-related events
- kernel/disk errors where detectable
- network interface changes
- important authentication/security events where permission and privacy requirements are satisfied

Sensitive journal content must be minimized.

### Event Severity

```text
INFO
WARNING
ERROR
CRITICAL
```

---

## Temperature

Use available Linux sensor interfaces such as:

```text
/sys/class/thermal
/sys/class/hwmon
```

Hardware availability is platform-dependent.

Missing sensors must be represented as unavailable, never fabricated.

---

# 9. Collector Architecture

Each collector is an independent component with its own interval and error handling.

Conceptual modules (implemented as):

```text
collectors/
    cpu.py
    memory.py
    disk.py
    network.py
    filesystem.py
    temperature.py
    processes.py
    services.py
    system.py
events/
    engine.py
    journal.py
```

Each collector should produce structured data for the state manager.

A collector failure must not crash unrelated collectors.

Collector states:

```text
INITIALIZING
RUNNING
DEGRADED
FAILED
RECOVERING
DISABLED
```

Collectors should:

- catch expected failures
- report diagnostics
- retry with bounded backoff
- preserve the last valid value with an explicit timestamp/status where appropriate
- never convert missing data into fake zero values

---

# 10. Sampling Strategy

Initial design targets:

| Collector | Initial interval |
|---|---:|
| CPU | 5 s |
| Memory | 5 s |
| Network | 5 s |
| Disk I/O | 5 s |
| Processes | 10 s |
| Temperature | 10 s |
| Filesystem | 30–60 s |
| SMART | future / minutes |
| Static system info | startup / infrequent |
| Services | event-driven + periodic reconciliation |
| Journal/events | event-driven + reconciliation |

These are starting points and must be benchmarked.

Do not force every metric to use the same sampling frequency.

---

# 11. Live State vs Historical State

This is a core architectural rule.

## Live state

Held in memory:

```text
latest CPU
latest memory
latest network
latest disk
latest process snapshot
latest service states
current health
current alerts
```

Used by:

- dashboard
- REST state endpoint
- WebSocket updates

## Historical state

Stored in SQLite:

```text
metric samples
rollups
events
alerts
```

The database is not the live monitoring engine.

---

# 12. Database Architecture

Use SQLite initially.

Enable:

- WAL
- foreign keys
- UTC timestamps
- bounded write queue
- batched transactions

Initial tables:

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

Potential future additions:

```text
audit_log
users
server_credentials
```

Only add tables when required.

---

# 13. Database Write Architecture

Collectors should not perform arbitrary synchronous database writes on every sample.

Use:

```text
Collectors
    |
    v
Storage Queue
    |
    v
DB Writer
    |
    v
Batched SQLite transaction
```

The queue must be bounded.

If the queue becomes full:

- drop low-priority raw metric samples according to policy
- preserve important events/alerts/audit records as far as practical
- report storage pressure
- never allow unlimited memory growth

---

# 14. SQLite Durability

Initial configuration:

```text
WAL
synchronous=NORMAL
```

Benchmark before changing this.

`FULL` may be considered if stronger power-loss durability is required and the performance cost is acceptable.

Do not use a SQLite database over a network filesystem.

---

# 15. Historical Retention

Initial conceptual policy:

```text
0–24 hours   raw/high frequency
1–7 days     1-minute rollups
8–30 days    5-minute rollups
older        hourly/daily rollups
```

The exact retention periods must remain configurable.

Rollups should preserve at least:

- count
- minimum
- average
- maximum

p95/p99 can be considered later.

Do not store continuous detailed process history in the MVP.

Service history should be event/transition oriented rather than sampled every few seconds.

---

# 16. API Architecture

API prefix:

```text
/api/v1
```

Initial endpoints:

```text
GET /api/v1/state
GET /api/v1/system
GET /api/v1/metrics/cpu
GET /api/v1/metrics/memory
GET /api/v1/network
GET /api/v1/storage
GET /api/v1/processes
GET /api/v1/processes/{id}
GET /api/v1/services
GET /api/v1/services/{id}
GET /api/v1/events
GET /api/v1/alerts
GET /api/v1/health
GET /api/v1/history/{metric}
```

WebSocket:

```text
/ws/live
```

---

# 17. REST Responsibilities

REST should provide:

- initial dashboard state
- current state
- system information
- process data
- service data
- event data
- alert data
- historical metrics
- configuration
- health information

REST historical queries must have:

- maximum time ranges
- maximum point counts
- server-controlled resolution
- pagination where appropriate

Target chart response size:

```text
~500–2000 points
```

Do not return millions of raw points to a browser.

---

# 18. WebSocket Responsibilities

WebSocket is for live updates.

Message envelope:

```json
{
  "type": "state_update",
  "sequence": 1234,
  "timestamp": "...",
  "payload": {}
}
```

Supported message types:

- `state_snapshot` — initial full state synchronization
- `state_update` — incremental live metric updates
- `event` — system/collector/service events
- `alert` — alert state transitions
- `health_update` — ServerWatch/application health changes
- `heartbeat` — keep-alive
- `error` — connection/protocol errors

Requirements:

- authentication
- authorization
- Origin validation
- heartbeat
- connection limits
- message-size limits
- rate limits
- sequence numbers
- reconnect support
- bounded backpressure

WebSocket is intentionally allowed to be lossy for live telemetry.

REST remains authoritative for resynchronization.

If sequence numbers reveal missed updates:

```text
GET /api/v1/state
```

can resynchronize the client.

---

# 19. API Error Format

Use a consistent structure:

```json
{
  "error": {
    "code": "RESOURCE_UNAVAILABLE",
    "message": "Temperature sensor is unavailable."
  }
}
```

Do not expose:

- stack traces
- filesystem paths unnecessarily
- secrets
- internal exception details

---

# 20. Authentication

MVP authentication:

```text
Tailscale identity
```

Tailscale Serve provides identity information.

Application code should convert that into an internal abstraction:

```text
UserIdentity
    id
    provider
    subject
    display_name
    email
    roles
```

MVP provider:

```text
tailscale
```

Potential future providers:

```text
local
OIDC
```

Do not spread Tailscale-specific header handling throughout the application.

---

# 21. Authorization / RBAC

MVP roles:

## Viewer

Can access:

- dashboard
- metrics
- history
- processes
- services
- events
- alerts
- system information

Cannot:

- modify security settings
- perform privileged system operations

## Administrator

Can:

- do everything Viewer can
- manage ServerWatch configuration
- manage application users/roles when that functionality exists

Administrator does NOT mean Linux root.

---

# 22. Tailscale Architecture

Use:

```text
Tailscale
  |
  +-- grants/access policy
  |
  +-- Serve
       |
       +-- HTTPS/WSS
       |
       +-- localhost FastAPI
```

Do not use Funnel for the MVP.

Do not publicly expose FastAPI.

Tailscale identity headers must only be trusted when traffic is guaranteed to come through the trusted local Serve path.

Backend should bind to:

```text
127.0.0.1
```

---

# 23. Security Model

Threats to consider:

- compromised tailnet device
- compromised Tailscale account
- application vulnerability
- malformed input
- WebSocket abuse
- resource exhaustion
- command injection
- path traversal
- PID reuse
- service-name confusion
- CSRF where cookie authentication is used
- SSRF in future multi-server functionality
- dependency compromise
- malicious administrator
- database theft/tampering
- Linux privilege escalation

Defenses:

- private tailnet access
- Tailscale grants
- server-side RBAC
- input validation
- no arbitrary commands
- no arbitrary filesystem paths
- bounded requests
- rate limits
- localhost backend
- WebSocket Origin validation
- minimal privileges
- systemd sandboxing
- audit logging for security-sensitive actions
- secret minimization
- dependency review
- no public API

---

# 24. Systemd Deployment

ServerWatch should be a systemd service.

Desired behavior:

```text
boot
  |
systemd
  |
serverwatch.service
  |
Uvicorn/FastAPI
```

Requirements:

- automatic startup
- restart on unexpected failure
- bounded restart rate
- graceful SIGTERM handling
- journald logging
- dedicated user
- security hardening

Potential hardening:

```text
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
```

These must be tested individually because excessive sandboxing can interfere with legitimate monitoring.

---

# 25. Application Logging

Use journald via stdout/stderr.

Default level:

```text
INFO
```

Available levels:

```text
DEBUG
INFO
WARNING
ERROR
CRITICAL
```

Never log:

- passwords
- tokens
- session secrets
- private keys
- credentials
- unnecessary sensitive journal content

Do not log every metric sample.

---

# 26. Health Model

ServerWatch must distinguish:

## Server health

The monitored Linux machine's condition.

## ServerWatch health

The monitoring application's own condition.

Overall states:

```text
HEALTHY
DEGRADED
FAILED
RECOVERING
```

A missing optional temperature sensor should not make the entire monitoring system FAILED.

---

# 27. Reliability Rules

- One collector failing must not kill the application.
- Missing metrics must be explicitly unavailable.
- Stale data must be detectable.
- Internal queues must be bounded.
- Important events should have higher persistence priority than raw samples.
- Database failure should not immediately kill live monitoring.
- Disk usage must be monitored.
- Database retention must protect free space.
- Use monotonic clocks for rate calculations.
- Use UTC wall-clock timestamps for stored/displayed event times.
- Handle SQLite busy/locking conditions with bounded retries.
- Gracefully drain the DB queue on shutdown.
- systemd must restart unexpected process failures.

---

# 28. Alerting

Alert states:

```text
OK
PENDING
FIRING
RECOVERED
```

An alert should have:

- condition
- threshold
- duration
- severity
- first seen
- last seen
- recovery
- deduplication

Use hysteresis where appropriate.

Example:

```text
Trigger:
CPU > 90% for 2 minutes

Recover:
CPU < 80%
```

Do not alert on every instantaneous threshold crossing.

MVP notification channel:

```text
Dashboard
```

External notifications are future work.

---

# 29. UI / UX

Visual direction:

> Dark, technical, compact, modern monitoring UI. Information hierarchy over decoration.

Palette:

```text
Crimson  #A60E35
Orange   #FEA24F
Cyan     #10BBC3
Teal     #068187
Navy     #051A2D
```

Color semantics:

```text
Navy       foundation/background
Teal       healthy/secondary
Cyan       live telemetry
Orange     warning
Crimson    critical/error
```

Do not overuse bright colors.

Avoid:

- excessive neon
- excessive glow
- cyberpunk styling
- unnecessary gradients
- giant decorative cards
- 3D charts

---

# 30. Main Screens

MVP:

```text
Overview
CPU
Memory
Storage
Network
Processes
Services
Events
Alerts
Server
Settings
```

Sidebar:

```text
Monitor
  Overview
  CPU
  Memory
  Storage
  Network
  Processes
  Services

Activity
  Events
  Alerts

System
  Server
  Settings
```

Top bar:

```text
ServerWatch
hostname
● LIVE
current time
```

---

# 31. Dashboard Hierarchy

Overview should prioritize:

1. server identity
2. overall health
3. critical/warning/failed counts
4. CPU
5. memory
6. storage
7. network
8. top processes
9. service status
10. recent events

Metric cards should be compact and include current value plus small trend visualization where useful.

---

# 32. Frontend Performance

Avoid:

- excessive React re-renders
- unlimited chart points
- huge DOM tables
- unnecessary animations
- fetching from API directly inside every component

Use:

- service/API layer
- hooks/state management where appropriate
- bounded chart data
- table virtualization if required
- memoization where useful
- batched live updates

---

# 33. Accessibility

Do not rely on color alone.

For example:

```text
● HEALTHY
⚠ WARNING
✕ CRITICAL
```

rather than only:

```text
green
orange
red
```

Ensure sufficient contrast and usable keyboard navigation.

---

# 34. Performance Targets

These are engineering targets, not guaranteed specifications.

Initial goals:

- low single-digit CPU overhead under normal operation
- tens of MB of RAM where practical
- controlled disk writes
- minimal network overhead
- dashboard updates every few seconds rather than continuously redrawing
- bounded historical query sizes

All targets must be measured on the target hardware.

---

# 35. Performance Benchmark Plan

Measure:

```text
1. baseline Linux
2. + monitoring collectors
3. + SQLite
4. + FastAPI
5. + WebSocket
6. + browser
7. + historical queries
```

Measure:

- CPU
- RAM
- load average
- disk I/O
- network I/O
- ServerWatch CPU
- ServerWatch RAM
- database size
- WAL size
- DB queue depth

---

# 36. Testing Strategy

Testing layers:

```text
Unit
Integration
System
Performance
Security
Deployment
Failure injection
```

Test:

- normal operation
- missing files
- permission denied
- malformed Linux data
- counter reset
- process PID reuse
- database locked
- database unavailable
- database full
- WebSocket disconnect
- Tailscale unavailable
- collector crash
- system reboot
- service restart
- disk pressure
- memory pressure

---

# 37. Backup Strategy

Protect:

- SQLite database
- configuration
- metadata

Use SQLite-aware backup mechanisms for live databases.

A backup is not considered verified until it has been restored into a test environment and checked.

Application code should remain recoverable from version control.

---

# 38. Upgrade Strategy

Preferred process:

```text
backup
  |
stop
  |
upgrade application
  |
database migration
  |
start
  |
health check
```

Migration requirements:

- versioned
- tested
- ordered
- preferably transactional
- avoid destructive changes without a backup
- favor forward-compatible schema evolution

---

# 39. Future Multi-Server Architecture

Not MVP.

Future model:

```text
                 ServerWatch Controller
                         |
             +-----------+-----------+
             |           |           |
           Agent A     Agent B     Agent C
           Ubuntu       Pi          VM
```

Agents would collect local metrics and communicate with the controller.

The MVP should still model a logical:

```text
server
```

entity with a stable UUID so this future remains possible.

Do not implement remote agents now.

---

# 40. Architecture Rules

These are hard project rules.

1. API routes do not directly read `/proc`.
2. API routes do not execute shell commands.
3. API routes do not perform arbitrary SQL.
4. Collectors do not directly manipulate frontend state.
5. Frontend never accesses SQLite.
6. Live state and historical storage remain separate.
7. No arbitrary command execution.
8. No arbitrary filesystem access.
9. No root application.
10. No public API exposure.
11. Tailscale Serve is the intended external access path.
12. Privileged features require a separate security boundary.
13. All external input is validated.
14. All resource-intensive operations are bounded.
15. Missing data must be represented honestly.
16. Architecture changes must be documented.

---

# 41. Definition of Done for MVP

The MVP is not complete merely because the dashboard renders.

It must satisfy:

### Monitoring

- [ ] CPU works
- [ ] memory works
- [ ] swap works
- [ ] storage works
- [ ] disk I/O works
- [ ] network works
- [ ] processes work
- [ ] services work
- [ ] temperature works when available
- [ ] system information works

### Backend

- [ ] REST API works
- [ ] WebSocket works
- [ ] authentication works
- [ ] authorization works
- [ ] validation works
- [ ] rate limits exist
- [ ] historical queries work

### Database

- [ ] SQLite WAL configured
- [ ] schema versioning works
- [ ] migrations work
- [ ] bounded DB queue works
- [ ] retention works
- [ ] rollups work

### Reliability

- [ ] collector failures are isolated
- [ ] stale data is identified
- [ ] database failure is handled
- [ ] WebSocket reconnects
- [ ] systemd restarts crashes
- [ ] graceful shutdown works

### Security

- [ ] dedicated user
- [ ] localhost binding
- [ ] Tailscale access
- [ ] Tailscale identity
- [ ] RBAC
- [ ] no arbitrary commands
- [ ] no secrets in logs
- [ ] WebSocket security controls
- [ ] systemd hardening tested

### Frontend

- [ ] Overview
- [ ] CPU
- [ ] Memory
- [ ] Storage
- [ ] Network
- [ ] Processes
- [ ] Services
- [ ] Events
- [ ] Alerts
- [ ] Server
- [ ] Settings

### Operations

- [ ] boot startup
- [ ] crash recovery
- [ ] logs
- [ ] health endpoint
- [ ] backup
- [ ] restore test
- [ ] upgrade test
- [ ] rollback procedure documented

---

# 42. Implementation Phase Order

Do not attempt the entire application in one pass.

Recommended sequence:

```text
Phase 1
Project skeleton + tooling

Phase 2
Linux data/collector layer

Phase 3
State manager

Phase 4
SQLite + migrations + DB writer

Phase 5
Health/event engine

Phase 6
FastAPI REST API

Phase 7
WebSocket layer

Phase 8
Authentication + RBAC

Phase 9
React frontend

Phase 10
Dashboard pages

Phase 11
systemd deployment

Phase 12
Tailscale Serve integration

Phase 13
Failure handling

Phase 14
Security hardening

Phase 15
Performance optimization

Phase 16
Testing and release validation
```

Never skip directly to UI polish before the backend data model is stable.

---

# 43. Change Control

If implementation reveals a conflict with this document:

1. Stop.
2. Identify the conflict.
3. Explain the technical reason.
4. Propose alternatives.
5. Do not silently change the architecture.
6. Update the blueprint only after the change is intentionally approved.

The goal is to prevent accidental architecture drift.

---

# 44. Final Architectural Principle

ServerWatch should remain:

> **small, observable, secure, recoverable, and honest about system state.**

It should prefer simple Linux-native mechanisms over unnecessarily complicated infrastructure.

The MVP should solve one problem well:

> **Give the administrator a trustworthy real-time and historical view of a Linux server without becoming a burden or security risk itself.**
