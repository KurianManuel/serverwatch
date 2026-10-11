# ServerWatch — Implementation Specification

**Document status:** Implementation-ready specification  
**Project:** ServerWatch  
**Purpose:** Exact implementation contract for Claude Code and other development agents  
**Related documents:** `PROJECT_PLAN.md`, `CLAUDE.md`

---

## 1. Purpose and Authority

This document translates the ServerWatch architecture and project plan into an implementation-level specification.

The implementation agent MUST treat the following order as authoritative:

1. Explicit user decisions made during the project.
2. `PROJECT_PLAN.md`
3. This `IMPLEMENTATION_SPEC.md`
4. `CLAUDE.md` for development-agent behavior and guardrails.
5. Implementation-specific details that do not conflict with the above.

If documents conflict, **stop and report the conflict**. Do not silently choose an architecture.

This specification is intended to reduce architectural drift, invented requirements, and implementation hallucinations.

---

# 2. Scope

## 2.1 MVP

The MVP is a single Linux-server monitoring application with:

- CPU monitoring
- Per-core CPU monitoring
- Load average
- Memory and swap monitoring
- Disk I/O monitoring
- Filesystem/storage monitoring
- Network monitoring
- Temperature monitoring where available
- Process monitoring
- systemd service monitoring
- System information
- Historical metrics
- Events
- Dashboard alerts
- REST API
- WebSocket live updates
- Tailscale-based remote access
- Tailscale identity authentication
- Application-level RBAC
- SQLite persistence
- systemd deployment
- Read-only operational scope

## 2.2 Explicitly out of scope for MVP

Do NOT implement:

- Remote command execution
- Arbitrary shell execution
- Arbitrary filesystem browsing
- Process killing
- Service start/stop/restart controls
- Package management
- User management on the Linux host
- Firewall management
- Configuration management of the host OS
- Multi-server agents
- Public Internet exposure
- Tailscale Funnel
- Automatic Tailscale configuration
- Root application execution
- Complex notification providers
- Mobile application
- Kubernetes deployment
- Docker requirement
- Redis
- PostgreSQL
- Celery
- Kafka
- Prometheus/Grafana replacement architecture

These may be future work, but must not enter the MVP without an explicit architecture decision.

---

# 3. Technology Contract

## 3.1 Backend

Required:

- Python
- FastAPI
- Uvicorn
- Pydantic
- SQLite
- SQL-oriented persistence layer appropriate for SQLite
- psutil where useful
- native Linux interfaces where they provide better semantics

The implementation may use a small supporting dependency when justified.

Before adding a dependency, document:

- why the standard library is insufficient
- why an existing dependency cannot provide the required behavior
- runtime cost
- maintenance/security implications

Do not introduce a large framework for a small feature.

## 3.2 Frontend

Required:

- React
- TypeScript
- Vite

Charts:

- Recharts or another lightweight charting solution already approved by the project.

Do not introduce a UI framework solely to style a few components.

## 3.3 Runtime

Initial deployment:

- One ServerWatch application process
- One Uvicorn process
- systemd service
- FastAPI serves the built frontend initially
- Tailscale Serve provides tailnet HTTPS access

Do not introduce Nginx or another reverse proxy unless an explicit requirement appears.

---

# 4. Repository Structure

Use the following logical structure unless an implementation constraint requires a documented change.

```text
serverwatch/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── dependencies.py
│   │   │
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   └── v1/
│   │   │       ├── __init__.py
│   │   │       ├── state.py
│   │   │       ├── system.py
│   │   │       ├── metrics.py
│   │   │       ├── network.py
│   │   │       ├── storage.py
│   │   │       ├── processes.py
│   │   │       ├── services.py
│   │   │       ├── events.py
│   │   │       ├── alerts.py
│   │   │       ├── health.py
│   │   │       └── history.py
│   │   │
│   │   ├── auth/
│   │   │   ├── __init__.py
│   │   │   ├── models.py
│   │   │   ├── provider.py
│   │   │   ├── tailscale.py
│   │   │   ├── rbac.py
│   │   │   └── dependencies.py
│   │   │
│   │   ├── collectors/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── cpu.py
│   │   │   ├── memory.py
│   │   │   ├── disk.py
│   │   │   ├── network.py
│   │   │   ├── filesystem.py
│   │   │   ├── temperature.py
│   │   │   ├── processes.py
│   │   │   ├── services.py
│   │   │   └── system.py
│   │   │
│   │   ├── state/
│   │   │   ├── __init__.py
│   │   │   ├── manager.py
│   │   │   ├── models.py
│   │   │   └── sequences.py
│   │   │
│   │   ├── database/
│   │   │   ├── __init__.py
│   │   │   ├── connection.py
│   │   │   ├── migrations.py
│   │   │   ├── writer.py
│   │   │   ├── repositories/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── metrics.py
│   │   │   │   ├── events.py
│   │   │   │   ├── alerts.py
│   │   │   │   └── servers.py
│   │   │   └── schema/
│   │   │       └── ...
│   │   │
│   │   ├── events/
│   │   │   ├── __init__.py
│   │   │   ├── engine.py
│   │   │   ├── models.py
│   │   │   └── journal.py
│   │   │
│   │   ├── alerts/
│   │   │   ├── __init__.py
│   │   │   ├── engine.py
│   │   │   ├── models.py
│   │   │   └── rules.py
│   │   │
│   │   ├── health/
│   │   │   ├── __init__.py
│   │   │   ├── engine.py
│   │   │   └── models.py
│   │   │
│   │   ├── monitoring/
│   │   │   ├── __init__.py
│   │   │   ├── scheduler.py
│   │   │   └── supervisor.py
│   │   │
│   │   ├── websocket/
│   │   │   ├── __init__.py
│   │   │   ├── manager.py
│   │   │   ├── protocol.py
│   │   │   └── endpoint.py
│   │   │
│   │   └── logging/
│   │       ├── __init__.py
│   │       └── setup.py
│   │
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   ├── api/
│   │   ├── websocket/
│   │   ├── security/
│   │   ├── database/
│   │   └── failure/
│   │
│   ├── pyproject.toml
│   └── ...
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   ├── features/
│   │   ├── layouts/
│   │   ├── pages/
│   │   ├── services/
│   │   ├── hooks/
│   │   ├── stores/
│   │   ├── types/
│   │   ├── utils/
│   │   └── main.tsx
│   ├── public/
│   ├── tests/
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
│
├── deploy/
│   ├── systemd/
│   │   └── serverwatch.service
│   ├── config/
│   │   └── serverwatch.env.example
│   └── tailscale/
│       └── README.md
│
├── docs/
│   ├── architecture/
│   ├── operations/
│   ├── security/
│   └── development/
│
├── scripts/
├── .gitignore
├── README.md
├── PROJECT_PLAN.md
├── CLAUDE.md
└── IMPLEMENTATION_SPEC.md
```

The exact schema migration-file naming convention may be selected during implementation, but migrations MUST be ordered and versioned.

---

# 5. Backend Module Boundaries

## 5.1 API layer

Responsibilities:

- HTTP/WebSocket transport
- authentication dependencies
- authorization dependencies
- request validation
- response serialization
- pagination/range validation
- HTTP error mapping

API routes MUST NOT:

- read `/proc` directly
- read `/sys` directly
- execute shell commands
- contain collector logic
- contain database transaction logic
- modify monitoring state directly

## 5.2 Collector layer

Collectors translate Linux/system sources into normalized application data.

Collectors MUST:

- have a narrow interface
- report timestamps
- report collector status
- handle expected Linux errors
- avoid unbounded work
- avoid direct frontend interaction
- avoid direct HTTP interaction
- avoid direct alert decisions

Collectors SHOULD be independently testable with mocked data sources.

## 5.3 State manager

The state manager owns current in-memory state.

It receives normalized collector results and publishes:

- current state
- state transitions
- sequence numbers
- health changes
- event candidates
- live WebSocket updates

It does not become the historical database.

## 5.4 Database layer

The database layer owns persistence.

Repositories provide controlled data access.

API routes must call repositories/services rather than issuing arbitrary SQL.

The database writer must be bounded and capable of prioritizing important records.

## 5.5 Event engine

The event engine converts:

- service state changes
- collector failures/recoveries
- system events
- journal events
- important state transitions

into normalized events.

It must deduplicate where appropriate.

## 5.6 Alert engine

The alert engine evaluates configured rules against normalized state.

It owns:

- PENDING
- FIRING
- RECOVERED

transitions.

Alert rules must support:

- threshold
- duration
- severity
- hysteresis
- deduplication

---

# 6. Collector Contracts

A collector should conceptually implement:

```python
class Collector(Protocol):
    name: str
    interval_seconds: float

    async def collect(self) -> CollectorResult:
        ...
```

The exact Python type may be adjusted, but the following semantics are mandatory.

`CollectorResult` must contain enough information to determine:

- collector name
- collection timestamp
- state/status
- payload when available
- error information when unavailable
- duration/latency

Collector status:

```text
INITIALIZING
RUNNING
DEGRADED
FAILED
RECOVERING
DISABLED
```

A failed collector MUST NOT crash the entire monitoring process.

---

# 7. Metric Semantics

## 7.1 CPU

Collect:

- total CPU utilization
- per-core utilization
- user/system/idle/iowait/etc. counters where available
- load average
- CPU count
- logical/physical count where available
- CPU model (static system information)

CPU utilization MUST be derived from counter deltas or a semantically equivalent method.

Do not treat load average as CPU utilization.

Store enough data to support historical charts.

## 7.2 Memory

Collect:

- total memory
- available memory
- used memory
- cached/buffer information where available
- swap total
- swap used
- swap available

`MemAvailable` should be preferred to `MemFree` when deriving practical memory availability.

## 7.3 Disk I/O

Collect per relevant block device where available:

- read bytes
- write bytes
- read operations
- write operations
- derived read/write throughput
- derived IOPS

Counter resets and device disappearance must be handled.

## 7.4 Filesystem

Collect:

- mount point
- filesystem/device identity
- total
- used
- available
- utilization percentage
- inode usage where available

Avoid blindly exposing sensitive filesystem paths if not required by the UI.

## 7.5 Network

Collect per interface:

- interface state
- RX bytes
- TX bytes
- RX packets
- TX packets
- errors
- drops
- derived throughput

Interface appearance/disappearance must be handled.

## 7.6 Temperature

Read available temperature sources from supported Linux interfaces.

Potential sources:

- `/sys/class/thermal`
- `/sys/class/hwmon`

Temperature availability varies by hardware.

Missing temperature data is valid.

Do not invent values.

## 7.7 Processes

Collect at least:

- PID
- process name
- executable when safely available
- CPU percentage
- memory percentage
- RSS where available
- status
- start time
- user where permitted

Process collection MUST tolerate:

- `AccessDenied`
- `NoSuchProcess`
- `ZombieProcess`
- PID reuse

Never assume a PID remains valid between reads.

Process enumeration should be less frequent than CPU/memory sampling.

## 7.8 Services

Monitor systemd service state.

Preferred mechanism:

- systemd D-Bus/native API

Do not repeatedly shell out to `systemctl` for routine polling.

Track:

- unit/service name
- active state
- substate
- load state where available
- failure state
- timestamps for transitions

Service state should be primarily event-driven with periodic reconciliation.

---

# 8. Sampling and Scheduling

Default starting intervals:

| Collector | Interval |
|---|---:|
| CPU | ~5 s |
| Memory | ~5 s |
| Network | ~5 s |
| Disk I/O | ~5 s |
| Processes | ~10 s |
| Temperature | ~10 s |
| Filesystem | 30–60 s |
| System info | startup / infrequent |
| Services | event-driven + reconciliation |
| Journald events | event-driven + reconciliation |
| SMART | future / minutes |

These are starting values, not immutable constants.

All intervals must be configurable internally where practical.

Use monotonic time for:

- elapsed time
- rates
- durations
- scheduling

Use UTC wall-clock timestamps for:

- persisted timestamps
- API timestamps
- displayed event times

---

# 9. State Model

The state manager should expose a normalized current-state object containing at least:

```text
server
cpu
memory
disk
network
filesystem
temperature
processes
services
events_summary
alerts_summary
health
serverwatch_health
sequence
timestamp
```

Every metric/status object should make freshness explicit.

Recommended fields:

```text
timestamp
status
stale
value/payload
collector
```

The frontend MUST be able to distinguish:

- current
- stale
- unavailable
- failed

from a valid zero value.

---

# 10. Database Specification

## 10.1 Required tables

Initial logical tables:

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

Future tables may include:

```text
audit_log
users
server_credentials
```

Do not add them without an actual MVP requirement.

## 10.2 Servers

Logical fields:

```text
id                TEXT PRIMARY KEY, stable UUID
hostname          TEXT NOT NULL
display_name      TEXT
os_name           TEXT
os_version        TEXT
kernel_version    TEXT
architecture      TEXT
created_at        TIMESTAMP DEFAULT (datetime('now'))
updated_at        TIMESTAMP DEFAULT (datetime('now'))
```

Index: `idx_servers_hostname ON servers(hostname)`

The server UUID must remain stable across application restarts.

## 10.3 CPU Samples

Logical fields:

```text
id                  INTEGER PRIMARY KEY AUTOINCREMENT
server_id           TEXT NOT NULL REFERENCES servers(id)
timestamp           TIMESTAMP NOT NULL
total_utilization   REAL
per_core            TEXT NOT NULL      -- JSON array of per-core utilization
load_1min           REAL
load_5min           REAL
load_15min          REAL
cpu_count           INTEGER
```

Index: `idx_cpu_samples_server_time ON cpu_samples(server_id, timestamp DESC)`

## 10.4 Memory Samples

Logical fields:

```text
id                  INTEGER PRIMARY KEY AUTOINCREMENT
server_id           TEXT NOT NULL REFERENCES servers(id)
timestamp           TIMESTAMP NOT NULL
total_bytes         INTEGER NOT NULL
available_bytes     INTEGER NOT NULL
used_bytes          INTEGER NOT NULL
free_bytes          INTEGER
buffers_bytes       INTEGER
cached_bytes        INTEGER
swap_total_bytes    INTEGER
swap_used_bytes     INTEGER
swap_free_bytes     INTEGER
```

Index: `idx_memory_samples_server_time ON memory_samples(server_id, timestamp DESC)`

## 10.5 Disk Samples

Logical fields:

```text
id                  INTEGER PRIMARY KEY AUTOINCREMENT
server_id           TEXT NOT NULL REFERENCES servers(id)
timestamp           TIMESTAMP NOT NULL
device              TEXT NOT NULL
read_bytes          INTEGER
write_bytes         INTEGER
read_ops            INTEGER
write_ops           INTEGER
read_throughput     REAL
write_throughput    REAL
iops                REAL
```

Indexes:
- `idx_disk_samples_server_time ON disk_samples(server_id, timestamp DESC)`
- `idx_disk_samples_device ON disk_samples(server_id, device, timestamp DESC)`

## 10.6 Network Samples

Logical fields:

```text
id                  INTEGER PRIMARY KEY AUTOINCREMENT
server_id           TEXT NOT NULL REFERENCES servers(id)
timestamp           TIMESTAMP NOT NULL
interface           TEXT NOT NULL
rx_bytes            INTEGER
tx_bytes            INTEGER
rx_packets          INTEGER
tx_packets          INTEGER
rx_errors           INTEGER
tx_errors           INTEGER
rx_drops            INTEGER
tx_drops            INTEGER
```

Indexes:
- `idx_network_samples_server_time ON network_samples(server_id, timestamp DESC)`
- `idx_network_samples_interface ON network_samples(server_id, interface, timestamp DESC)`

## 10.7 Filesystem Samples

Logical fields:

```text
id                  INTEGER PRIMARY KEY AUTOINCREMENT
server_id           TEXT NOT NULL REFERENCES servers(id)
timestamp           TIMESTAMP NOT NULL
mount_point         TEXT NOT NULL
device              TEXT
fstype              TEXT
total_bytes         INTEGER
free_bytes          INTEGER
available_bytes     INTEGER
used_bytes          INTEGER
used_percent        REAL
inodes_total        INTEGER
inodes_free         INTEGER
```

Indexes:
- `idx_filesystem_samples_server_time ON filesystem_samples(server_id, timestamp DESC)`
- `idx_filesystem_samples_mount ON filesystem_samples(server_id, mount_point, timestamp DESC)`

## 10.8 Temperature Samples

Logical fields:

```text
id                  INTEGER PRIMARY KEY AUTOINCREMENT
server_id           TEXT NOT NULL REFERENCES servers(id)
timestamp           TIMESTAMP NOT NULL
sensor_name         TEXT NOT NULL
sensor_label        TEXT
temperature_celsius REAL
high_threshold      REAL
critical_threshold  REAL
```

Indexes:
- `idx_temperature_samples_server_time ON temperature_samples(server_id, timestamp DESC)`
- `idx_temperature_samples_sensor ON temperature_samples(server_id, sensor_name, timestamp DESC)`

## 10.9 Events

Logical fields:

```text
id                  INTEGER PRIMARY KEY AUTOINCREMENT
server_id           TEXT NOT NULL REFERENCES servers(id)
timestamp           TIMESTAMP NOT NULL
event_type          TEXT NOT NULL
severity            TEXT NOT NULL
source              TEXT
title               TEXT
message             TEXT
metadata            TEXT
```

Indexes:
- `idx_events_server_time ON events(server_id, timestamp DESC)`
- `idx_events_type ON events(server_id, event_type, timestamp DESC)`
- `idx_events_severity ON events(server_id, severity, timestamp DESC)`

Do not store secrets.

## 10.10 Alerts

Logical fields:

```text
id                  INTEGER PRIMARY KEY AUTOINCREMENT
server_id           TEXT NOT NULL REFERENCES servers(id)
rule_id             TEXT NOT NULL
state               TEXT NOT NULL
severity            TEXT NOT NULL
condition           TEXT
first_seen          TIMESTAMP NOT NULL
last_seen           TIMESTAMP NOT NULL
fired_at            TIMESTAMP
recovered_at        TIMESTAMP
metadata            TEXT
```

Indexes:
- `idx_alerts_server_time ON alerts(server_id, first_seen DESC)`
- `idx_alerts_state ON alerts(server_id, state, first_seen DESC)`
- `idx_alerts_rule ON alerts(server_id, rule_id, first_seen DESC)`

State:
```text
OK
PENDING
FIRING
RECOVERED
```

## 10.11 Metric Rollups

Logical fields:

```text
id                  INTEGER PRIMARY KEY AUTOINCREMENT
server_id           TEXT NOT NULL REFERENCES servers(id)
metric_name         TEXT NOT NULL
interval_type       TEXT NOT NULL
window_start        TIMESTAMP NOT NULL
window_end          TIMESTAMP NOT NULL
count               INTEGER NOT NULL
min_value           REAL NOT NULL
avg_value           REAL NOT NULL
max_value           REAL NOT NULL
```

Indexes:
- `idx_rollups_server_metric_time ON metric_rollups(server_id, metric_name, window_start DESC)`
- `idx_rollups_interval ON metric_rollups(interval_type, window_start DESC)`
- `idx_rollups_unique ON metric_rollups(server_id, metric_name, interval_type, window_start)` (UNIQUE)

Rollups must support:
- minimum
- average
- maximum
- count

Additional percentile statistics may be added later.

## 10.12 Schema Metadata

Logical fields:

```text
version         INTEGER PRIMARY KEY
applied_at      TIMESTAMP DEFAULT (datetime('now'))
description     TEXT
```

Version 1 is recorded LAST - only if all schema creation succeeds.

---

# 11. SQLite Contract

Configure SQLite for:

- WAL
- foreign keys
- bounded busy timeout/retry behavior
- `synchronous=NORMAL` initially

The database must not be placed on a network filesystem.

Use one controlled write path.

Use a bounded asynchronous queue between live monitoring and persistence.

Batch writes into transactions.

Important events/alerts must have higher persistence priority than disposable high-frequency raw samples.

Under sustained pressure:

1. preserve application liveness
2. preserve important events/alerts where possible
3. drop lower-priority raw samples rather than allowing unlimited memory growth

Database failure must not terminate live metric collection.

---

# 12. Retention

Initial policy:

```text
0–24 h    high-frequency/raw data
1–7 d     ~1 minute rollups
8–30 d    ~5 minute rollups
older     hourly/daily rollups
```

The exact retention durations may be configured later.

Retention must:

- run bounded work
- avoid locking the database for long periods
- monitor database/WAL size
- protect available disk space

Process history should not be stored as continuous high-frequency samples in the MVP.

Service history should be transition/event-oriented.

---

# 13. REST API

Base prefix:

```text
/api/v1
```

## 13.1 State

```http
GET /api/v1/state
```

Returns current authoritative state and sequence information.

## 13.2 System

```http
GET /api/v1/system
```

Returns static/system information.

## 13.3 Metrics

```http
GET /api/v1/metrics/cpu
GET /api/v1/metrics/memory
```

Support bounded historical queries.

## 13.4 Network

```http
GET /api/v1/network
```

Current network state and interface information.

## 13.5 Storage

```http
GET /api/v1/storage
```

Filesystem and storage state.

## 13.6 Processes

```http
GET /api/v1/processes
GET /api/v1/processes/{pid}
```

List endpoint must support bounded sorting/filtering.

Do not permit arbitrary query execution.

## 13.7 Services

```http
GET /api/v1/services
GET /api/v1/services/{service}
```

Service names must be validated.

## 13.8 Events

```http
GET /api/v1/events
```

Use cursor-based pagination.

Support bounded filters.

## 13.9 Alerts

```http
GET /api/v1/alerts
```

Support bounded filters.

## 13.10 Health

```http
GET /api/v1/health
```

Return application/serverwatch health.

## 13.11 History

```http
GET /api/v1/history/{metric}
```

Server controls the final resolution.

Target approximately:

```text
500–2000 chart points
```

Do not allow unbounded historical queries.

---

# 14. API Error Contract

All normal API errors should use:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message"
  }
}
```

Examples:

```text
INVALID_PARAMETER
UNAUTHORIZED
FORBIDDEN
NOT_FOUND
STALE_DATA
DATA_UNAVAILABLE
RATE_LIMITED
DATABASE_UNAVAILABLE
INTERNAL_ERROR
```

Do not expose:

- stack traces
- SQL statements
- filesystem internals unless required
- credentials
- tokens
- environment secrets

---

# 15. WebSocket Specification

Endpoint:

```text
/ws/live
```

## 15.1 Connection lifecycle

1. Connect
2. Authenticate
3. Authorize
4. Validate Origin
5. Register connection
6. Send initial synchronization as `state_snapshot` message (see §15.2, §37)
7. Send incremental updates as `state_update` messages (see §15.2, §37)
8. Heartbeat
9. Detect stale/disconnected clients
10. Remove connection cleanly

## 15.2 Sequence numbers

Every live update should carry a monotonically increasing sequence.

Example:

```json
{
  "type": "state_update",
  "sequence": 1234,
  "timestamp": "2026-09-21T12:00:00Z",
  "payload": {}
}
```

If the client detects a gap:

```text
GET /api/v1/state
```

REST is authoritative.

## 15.3 WebSocket security

Implement:

- authentication
- authorization
- Origin validation
- bounded message size
- bounded connection count
- heartbeat
- rate limiting where relevant
- clean disconnect handling

Live updates are allowed to be lossy.

---

# 16. Authentication

MVP authentication provider:

```text
Tailscale identity
```

Internal abstraction:

```python
class UserIdentity:
    id: str
    provider: str
    subject: str
    display_name: str | None
    email: str | None
    roles: set[str]
```

Provider:

```text
tailscale
```

Do not couple all application code directly to Tailscale header names.

Create a provider abstraction so a future local/OIDC provider can be added without rewriting the application.

---

# 17. Tailscale Identity Rules

The FastAPI application should listen on localhost.

Conceptually:

```text
Tailscale Serve
    ↓
127.0.0.1:8000
```

When using Tailscale identity headers:

- only trust them when requests arrive through the intended trusted proxy path
- do not expose the backend directly
- do not assume arbitrary clients can safely set those headers

Tailscale Serve is tailnet-only.

Do not configure:

```text
tailscale funnel
```

Do not make Tailscale configuration a runtime dependency for monitoring.

If Tailscale is unavailable:

- ServerWatch should continue local monitoring
- remote dashboard access may fail
- local monitoring state must remain functional

---

# 18. RBAC

Roles:

```text
Viewer
Administrator
```

## Viewer

Can read:

- overview
- metrics
- history
- processes
- services
- events
- alerts
- server information

## Administrator

Viewer permissions plus:

- ServerWatch configuration
- application user management where implemented

There are no Linux administrative operations in the MVP.

Do not equate:

```text
Administrator == Linux root
```

They are separate concepts.

---

# 19. Events

Event sources include:

- collector failure/recovery
- service transitions
- alert transitions
- journald events where selected
- important system state transitions

Event severity:

```text
INFO
WARNING
ERROR
CRITICAL
```

Events must contain enough information for:

- filtering
- chronological display
- source identification
- correlation

Avoid flooding the database with duplicate identical events.

---

# 20. Alerts

Alert lifecycle:

```text
OK → PENDING → FIRING → RECOVERED
```

A rule should define:

```text
rule_id
metric
operator
threshold
duration
severity
recovery threshold
enabled
```

Use hysteresis.

Example semantics:

```text
Trigger: CPU > 90% for 2 minutes
Recover: CPU < 80%
```

This example is illustrative, not a mandatory default rule.

MVP notification channel:

```text
Dashboard only
```

No email/Telegram/Discord/etc. is required.

---

# 21. Health Model

Overall ServerWatch health:

```text
HEALTHY
DEGRADED
FAILED
RECOVERING
```

Keep separate:

```text
server health
serverwatch application health
```

Examples:

- temperature collector failure → temperature unavailable; other metrics remain usable
- SQLite unavailable → live monitoring continues; historical persistence becomes degraded
- WebSocket failure → REST remains available
- Tailscale failure → local application remains functional
- one collector crash → supervisor isolates/restarts it

---

# 22. Monitoring ServerWatch Itself

Expose internal health/telemetry where practical:

- application CPU usage
- application memory usage
- collector latency
- collector error count
- DB queue depth
- DB write latency
- WebSocket client count
- event processing delay
- persistence drops
- stale collector count

This is important for diagnosing whether ServerWatch itself is causing resource pressure.

---

# 23. Configuration

Configuration should be centralized.

Conceptual categories:

```text
application
server
database
monitoring
retention
websocket
authentication
logging
security
```

Configuration precedence should be deterministic.

Sensitive values must not be logged.

Use environment/config-file mechanisms appropriate for systemd deployment.

Do not hard-code:

- credentials
- tokens
- private keys
- machine-specific paths that should be configurable

---

# 24. Logging

Use structured application logging where practical.

Log levels:

```text
DEBUG
INFO
WARNING
ERROR
CRITICAL
```

Logs should identify:

- timestamp
- component
- event
- severity
- relevant identifiers

Do not log:

- passwords
- authentication tokens
- private keys
- arbitrary request bodies containing secrets
- unnecessary personal data

Use journald through systemd in deployment.

---

# 25. Systemd Deployment

Create:

```text
deploy/systemd/serverwatch.service
```

Conceptually:

```text
[Unit]
Description=ServerWatch monitoring dashboard
After=network-online.target
Wants=network-online.target

[Service]
User=serverwatch
Group=serverwatch
WorkingDirectory=/opt/serverwatch/app
ExecStart=...
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

The exact executable path depends on the deployment layout.

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

These MUST be tested individually.

Do not enable a sandbox restriction that prevents required monitoring functionality without documenting why and adjusting the design.

---

# 26. Filesystem Layout

Recommended production layout:

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

Ownership:

```text
serverwatch:serverwatch
```

The application should not run as root.

---

# 27. Privilege Model

MVP is intentionally read-only.

The application user must have only the access needed to:

- read required system metrics
- inspect permitted processes
- observe systemd state
- read selected journal information
- write its own application data

Do not grant broad capabilities merely to make one collector easier.

If a future feature requires elevated privilege:

1. identify exact operation
2. define a separate security boundary
3. minimize capability
4. audit the operation
5. document threat model
6. obtain explicit architecture approval

---

# 28. Frontend Architecture

Suggested structure:

```text
src/
├── app/
├── components/
│   ├── layout/
│   ├── cards/
│   ├── charts/
│   ├── tables/
│   ├── status/
│   └── common/
├── features/
│   ├── overview/
│   ├── cpu/
│   ├── memory/
│   ├── storage/
│   ├── network/
│   ├── processes/
│   ├── services/
│   ├── events/
│   ├── alerts/
│   ├── server/
│   └── settings/
├── pages/
├── services/
├── hooks/
├── stores/
├── types/
└── utils/
```

Do not put API calls directly throughout components.

Create a service/API layer.

---

# 29. UI Screens

Required MVP screens:

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

Overview order:

1. server identity
2. health summary
3. warning/critical/failed counts
4. CPU
5. memory
6. storage
7. network
8. top processes
9. services
10. recent events

---

# 30. Visual Design Contract

Palette:

```text
Crimson: #A60E35
Orange:  #FEA24F
Cyan:    #10BBC3
Teal:    #068187
Navy:    #051A2D
```

Direction:

- dark
- technical
- compact
- modern
- information-dense
- readable

Avoid:

- excessive glow
- excessive gradients
- giant decorative cards
- unnecessary 3D
- cyberpunk decoration
- visual noise

Semantic use:

```text
Navy   = foundation
Teal   = healthy / secondary
Cyan   = live telemetry
Orange = warning
Crimson = critical/error
```

Do not rely only on color for status.

---

# 31. Frontend Performance

Must:

- bound chart points
- avoid rendering unlimited history
- virtualize large process/service/event tables where needed
- avoid unnecessary React re-renders
- avoid excessive animation
- unsubscribe from WebSocket state when components unmount
- clean timers/listeners
- handle reconnects cleanly

Charts should target approximately:

```text
500–2000 points
```

depending on range and resolution.

---

# 32. History Query Rules

The frontend should request:

```text
time range
metric
resolution
```

The backend remains authoritative over actual resolution.

Never permit the browser to request millions of raw points.

History endpoints must enforce:

- maximum time range
- maximum point count
- maximum page size
- safe resolution

---

# 33. Testing Contract

Use pytest for backend tests.

Testing layers:

```text
unit
integration
API
WebSocket
security
database
failure
system/deployment
performance
```

## Collector tests

Test:

- normal values
- missing source
- malformed source
- permission error
- counter reset
- disappearing interface/device
- process disappearance
- PID reuse

## Database tests

Test:

- migrations
- WAL
- concurrent reads
- writer behavior
- busy/locked behavior
- rollback
- retention
- rollups
- backup
- restore

## API tests

Test:

- schema validation
- authentication
- authorization
- pagination
- range limits
- errors
- no stack trace leakage

## WebSocket tests

Test:

- authentication
- authorization
- Origin
- initial state
- sequence numbers
- reconnect
- heartbeat
- disconnect
- oversized input
- rate limiting

## Failure tests

Simulate:

- collector crash
- collector timeout
- SQLite failure
- database lock
- full disk conditions where safely testable
- WebSocket disconnect
- Tailscale unavailable
- systemd restart
- application restart
- reboot

Do not claim a test passed unless it was actually executed.

---

# 34. Test Data and Mocking

Linux collectors should be testable without requiring every test to execute against the host machine.

Prefer dependency injection for:

- `/proc` readers
- `/sys` readers
- process enumeration
- systemd access
- journald access
- clock/time source

Tests may use:

- temporary directories
- temporary SQLite databases
- fixture files
- fake collectors
- mocked system interfaces

Do not make production code depend on test-only behavior.

---

# 35. Failure Injection

Failure injection should be deliberate and isolated.

Examples:

```text
Fake CPU collector raises exception
Fake database writer blocks
Fake database connection fails
Fake journal source disappears
Fake process vanishes during inspection
Fake network interface disappears
Fake temperature source returns malformed data
```

Expected behavior must be documented before the test.

---

# 36. API Schema Models

Use typed Pydantic models for external API contracts.

Representative models:

```text
ErrorResponse
ServerInfo
SystemState
CpuState
CpuCoreState
MemoryState
SwapState
DiskState
FilesystemState
NetworkInterfaceState
TemperatureState
ProcessSummary
ProcessDetail
ServiceState
Event
Alert
HealthState
HistoryPoint
StateSnapshot
LiveMessage
```

Do not expose internal Python objects directly.

API schemas should be versioned through the `/api/v1` prefix.

---

# 37. WebSocket Message Models

Use explicit message types.

Representative types:

```text
state_snapshot
state_update
event
alert
health_update
heartbeat
error
```

Every message should have enough metadata to identify:

- type
- sequence where applicable
- timestamp
- payload

Unknown message types must not crash the client.

---

# 38. Internal Event Bus

An internal event mechanism may be used between:

```text
collectors
state manager
event engine
alert engine
websocket manager
database writer
```

Requirements:

- bounded where messages can accumulate
- no infinite queues
- clear ownership
- backpressure policy
- important-event priority where required

Do not add a full message broker for the MVP.

---

# 39. Scheduling Model

A lightweight internal scheduler/supervisor is sufficient.

Each periodic collector should have:

```text
interval
next run
last run
last success
last error
consecutive failures
latency
```

The supervisor should:

- start collectors
- isolate collector failures
- restart failed collectors when appropriate
- expose collector health
- stop collectors during shutdown

One failed collector must not stop unrelated collectors.

---

# 40. Graceful Shutdown

Shutdown order should approximately be:

```text
1. Stop accepting new work
2. Stop periodic collectors
3. Stop event intake
4. Stop new database writes
5. Drain bounded database queue
6. Commit pending transactions
7. Close database
8. Close WebSocket connections
9. Exit
```

If the drain deadline is reached, preserve liveness and log what could not be persisted.

Never wait forever during shutdown.

---

# 41. Self-Healing Rules

Automatic recovery may include:

- restarting a failed collector
- reconnecting to systemd/journald
- reconnecting WebSocket clients
- reopening a recoverable database connection

Do not implement aggressive infinite retry loops.

Use bounded backoff.

Recovery transitions should be observable.

---

# 42. Security Requirements

MVP MUST satisfy:

- dedicated service account
- no root application
- localhost backend
- Tailscale Serve for intended remote access
- application-level RBAC
- input validation
- bounded resource usage
- no arbitrary shell commands
- no arbitrary filesystem paths
- no secret logging
- secure WebSocket behavior
- controlled database access
- dependency review
- systemd hardening where compatible

Threats to consider:

```text
compromised tailnet identity
malicious authenticated user
malicious viewer
malformed input
WebSocket abuse
resource exhaustion
command injection
path traversal
PID reuse
service-name confusion
dependency compromise
database theft/tampering
privilege escalation
```

---

# 43. Dependency Policy

Before adding a dependency:

1. identify requirement
2. check standard library
3. check existing dependencies
4. evaluate maintenance
5. evaluate security
6. evaluate runtime cost
7. document reason

Avoid dependency duplication.

Do not add:

- Redis
- PostgreSQL
- Celery
- Kafka
- large monitoring agents

unless the architecture is explicitly revised.

---

# 44. Documentation Requirements

Every implementation phase must update documentation when behavior changes.

Required documentation areas:

```text
README
architecture
installation
configuration
operations
security
backup/restore
upgrade
troubleshooting
development
testing
```

If a decision changes architecture:

1. stop implementation
2. document the conflict
3. explain the reason
4. present alternatives
5. obtain approval
6. update project documents
7. continue

---

# 45. Implementation Phases

Implementation MUST proceed in this dependency order.

## Phase 1 — Skeleton and tooling

Implement:

- repository structure
- Python environment
- dependency management
- FastAPI bootstrap
- React/Vite bootstrap
- linting/formatting/type checks
- basic test framework
- configuration skeleton

Validation:

- backend starts
- frontend builds
- basic tests run
- no unnecessary dependencies

## Phase 2 — Linux data layer

Implement:

- CPU
- memory
- disk
- network
- filesystem
- temperature
- process
- service
- system collectors

Validation:

- collector unit tests
- live Linux smoke tests
- permission/error handling

## Phase 3 — State manager

Implement:

- normalized state
- collector lifecycle
- sequence numbers
- stale tracking
- supervisor

Validation:

- collector isolation
- stale detection
- state updates

## Phase 4 — Database

Implement:

- schema
- migrations
- repositories
- SQLite WAL
- DB writer
- retention
- rollups

Validation:

- migration tests
- write/read tests
- failure tests
- backup/restore

## Phase 5 — Health/events/alerts

Implement:

- health engine
- event engine
- journald integration
- alert lifecycle
- hysteresis
- deduplication

Validation:

- state transition tests
- alert tests
- failure recovery tests

## Phase 6 — REST API

Implement:

- `/api/v1/state`
- system
- metrics
- network
- storage
- processes
- services
- events
- alerts
- health
- history

Validation:

- schema tests
- authorization tests
- query-bound tests

## Phase 7 — WebSocket

Implement:

- authentication
- initial state
- live updates
- sequence numbers
- heartbeat
- reconnect behavior
- limits

Validation:

- WS integration tests
- reconnect tests
- sequence gap recovery

## Phase 8 — Authentication/RBAC

Implement:

- Tailscale identity provider
- identity abstraction
- Viewer
- Administrator
- authorization dependencies

Validation:

- valid identity
- missing identity
- spoofed direct headers
- unauthorized endpoint access

## Phase 9 — Frontend foundation

Implement:

- application shell
- sidebar
- top bar
- API service layer
- WebSocket client
- shared status components
- chart infrastructure
- tables

Validation:

- production build
- reconnect
- loading/error/stale states

## Phase 10 — Dashboard

Implement:

- Overview
- CPU
- Memory
- Storage
- Network
- Processes
- Services
- Events
- Alerts
- Server
- Settings

Validation:

- every page works against real API
- no fake production data
- bounded rendering

## Phase 11 — Deployment

Implement:

- production build
- systemd unit
- dedicated user
- filesystem layout
- configuration
- journald logging
- startup/restart

Validation:

- reboot
- crash/restart
- permissions
- logs

## Phase 12 — Tailscale

Document/configure:

```text
Tailscale
→ Serve
→ localhost FastAPI
```

Validation:

- tailnet access
- identity extraction
- unauthorized access behavior
- backend not externally exposed

## Phase 13 — Failure handling

Validate:

- DB failure
- collector crash
- stale data
- WS failure
- Tailscale failure
- disk pressure
- restart/reboot

## Phase 14 — Security hardening

Validate:

- service sandboxing
- headers
- input validation
- rate limits
- WebSocket security
- dependency audit
- secret handling
- permissions

## Phase 15 — Performance

Measure:

- CPU overhead
- RAM overhead
- collector latency
- DB write throughput
- DB size growth
- API latency
- WebSocket fanout
- frontend rendering

Optimize only based on measurements.

## Phase 16 — Release validation

Complete:

- full tests
- installation test
- upgrade test
- backup/restore test
- rollback test
- documentation
- release notes
- Git tag/release

---

# 46. Phase Gate Rule

Claude Code MUST NOT automatically proceed through every phase after a successful build.

At each phase:

```text
Implement
→ Test
→ Inspect
→ Report
→ Confirm architecture remains unchanged
→ Proceed to next phase
```

If tests fail:

```text
Fix
→ Re-test
→ Report
```

If architecture conflict appears:

```text
STOP
→ Explain
→ Ask for decision
```

---

# 47. Acceptance Criteria

The implementation is complete only when:

## Monitoring

- CPU works
- per-core CPU works
- load average works
- memory works
- swap works
- disk I/O works
- filesystem usage works
- network works
- temperatures work where hardware exposes them
- processes work with permission handling
- services work
- system information works

## Backend

- REST works
- WebSocket works
- API schemas are typed
- validation exists
- authentication exists
- RBAC exists
- bounded history queries exist

## Database

- SQLite WAL works
- migrations work
- DB writer is bounded
- retention works
- rollups work
- backup/restore works

## Reliability

- collector failures are isolated
- stale data is visible
- DB failure does not kill live monitoring
- WebSocket reconnect works
- systemd restarts the application
- graceful shutdown works

## Security

- dedicated service account
- no root application
- localhost binding
- Tailscale Serve
- identity validation
- RBAC
- no arbitrary command execution
- no arbitrary filesystem access
- no secret leakage
- WebSocket security
- systemd hardening tested

## Frontend

All MVP screens exist and use real backend data.

## Operations

Document:

- installation
- startup
- shutdown
- logs
- health checks
- backup
- restore
- upgrade
- rollback
- troubleshooting

---

# 48. Anti-Hallucination Rules for Implementation Agents

Claude Code MUST NOT:

- invent Linux APIs
- invent Tailscale behavior
- invent package APIs without checking documentation/source
- claim tests passed without executing them
- claim performance targets were met without measuring them
- claim security properties without validating them
- fabricate hardware sensor availability
- fabricate service states
- fabricate historical data
- silently replace a selected technology
- silently add a database/message broker
- silently introduce root privileges
- silently expose an HTTP port publicly
- silently add write/control operations
- silently alter API contracts

When uncertain:

```text
inspect source
→ inspect installed environment
→ consult authoritative documentation
→ test
→ ask if architectural choice remains ambiguous
```

---

# 49. Real-System Verification Rules

Because ServerWatch is intended for Linux servers, implementation must distinguish:

```text
mock/unit behavior
```

from:

```text
real Linux behavior
```

A unit test passing does not prove the collector works on the target Linux system.

Before release, run a real-system validation covering:

- `/proc`
- `/sys`
- systemd
- journald
- process enumeration
- filesystem
- network
- temperature availability
- SQLite
- systemd service

Record unavailable sensors/features honestly.

---

# 50. No Fake Data in Production

The frontend may use fixtures during isolated UI development.

Production code MUST NOT silently fall back to fake values.

Examples of prohibited behavior:

```text
CPU unavailable → show 42%
Temperature unavailable → show 50°C
No process data → show sample processes
No history → generate random chart points
```

Instead:

```text
Unavailable
Stale
No data
Permission denied
Not supported
```

must be represented explicitly.

---

# 51. Performance Targets

These are engineering targets, not claims of guaranteed performance.

Initial goals:

- low single-digit CPU overhead under normal monitoring
- tens of MB rather than hundreds of MB of application memory
- bounded DB growth
- bounded WebSocket memory
- responsive dashboard on the target machine

Measure actual behavior.

The target machine is resource-constrained, so performance regressions must be treated seriously.

---

# 52. Benchmark Procedure

Benchmark in stages:

```text
1. Baseline idle server
2. ServerWatch collectors only
3. + SQLite persistence
4. + FastAPI
5. + WebSocket
6. + Browser dashboard
7. + Historical queries
```

Measure:

- CPU
- RAM
- disk writes
- DB size
- latency
- collector duration
- queue depth

Compare each stage against baseline.

---

# 53. Backup and Restore

Backup must cover:

- SQLite database
- configuration
- relevant metadata

Prefer SQLite-aware online backup behavior.

Restore procedure must be tested.

A backup that has never been restored is not considered validated.

---

# 54. Upgrade and Rollback

Upgrade sequence:

```text
backup
→ stop service
→ install new version
→ run migrations
→ start service
→ health check
```

Rollback must account for database migrations.

Destructive schema migrations require special handling and a verified backup.

---

# 55. Git and Release Discipline

Use small, meaningful commits.

Suggested progression:

```text
feat: initialize serverwatch backend
feat: add linux collectors
feat: add state manager
feat: add sqlite persistence
feat: add health and events
feat: add api
feat: add websocket
feat: add authentication
feat: add frontend shell
feat: add monitoring dashboards
feat: add systemd deployment
feat: add tailscale deployment docs
test: add failure coverage
docs: add operations guide
```

Do not create commits that claim functionality not actually implemented.

Before a release:

- run tests
- build frontend
- validate deployment
- validate backup/restore
- inspect Git diff
- update documentation
- create release notes
- tag version

---

# 56. Future Multi-Server Compatibility

Do not implement multi-server agents now.

However, avoid designs that make future expansion impossible.

The database should already contain a logical server identity.

Future model:

```text
ServerWatch Controller
    ├── Agent A
    ├── Agent B
    └── Agent C
```

Future agent communication/security is a separate architecture decision.

Do not invent it during MVP implementation.

---

# 57. Change-Control Procedure

If a requested feature conflicts with this specification:

### Step 1
Identify the exact conflict.

### Step 2
Explain the technical consequence.

### Step 3
Provide concise alternatives.

### Step 4
Wait for explicit decision.

### Step 5
Update the relevant project documents.

### Step 6
Only then implement.

Never hide architectural changes inside code.

---

# 58. Final Instruction to Claude Code

Build ServerWatch as a **small, reliable, observable, read-only Linux monitoring system**.

Prefer:

```text
simple
→ explicit
→ typed
→ bounded
→ testable
→ secure
→ measurable
```

over:

```text
clever
→ implicit
→ highly abstract
→ dependency-heavy
→ unbounded
```

The implementation must preserve the distinction between:

```text
live state
historical state
events
alerts
health
authentication
authorization
```

Do not collapse these concepts merely to reduce code.

The objective is not to produce the largest feature set.

The objective is to produce a maintainable ServerWatch MVP that can be trusted on a resource-constrained Linux server and expanded later without losing its security, reliability, or architectural clarity.
