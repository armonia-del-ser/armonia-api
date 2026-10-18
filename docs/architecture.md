# System Architecture & Technical Design

## Service: `armonia-api`

---

## 1. High-Level Component Topology

```
┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│        armonia-landing          │       │        armonia-dashboard        │
│   (Public Client Experience)    │       │     (Jazmín & Assistant UI)     │
│    Cloudflare Pages (Edge)      │       │     Cloudflare Pages (Edge)     │
└────────────────┬────────────────┘       └────────────────┬────────────────┘
                 │ (Public Booking Flow)                   │ (Admin & Payment Actions)
                 ▼                                         ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                    armonia-api (FastAPI / Python 3.13)                    │
│                                                                           │
│  ┌───────────────────────┐  ┌──────────────────────┐  ┌────────────────┐  │
│  │   Services & Catalog  │  │  Anti-Ghosting State │  │ Attendance &   │  │
│  │   Catalog Engine      │  │  Machine & Buffers   │  │ Package Ledger │  │
│  └───────────┬───────────┘  └──────────┬───────────┘  └────────┬───────┘  │
│              │                         │                       │          │
│              ▼                         ▼                       ▼          │
│       ┌────────────────────────────────────────────────────────────┐      │
│       │               Database Adapter (libsql-client)             │      │
│       └──────────────────────────────┬─────────────────────────────┘      │
└──────────────────────────────────────┼────────────────────────────────────┘
                                       │
                 ┌─────────────────────┴─────────────────────┐
                 ▼                                           ▼
      [Turso Edge Database]                         [Local SQLite3 File]
    (libsql://armonia-db.turso.io)                   (file:local.db)
```

---

## 2. The Anti-Ghosting Booking State Machine

```mermaid
stateDiagram-v2
    [*] --> PENDING_PAYMENT : Client submits reservation (Expires in 2h)
    
    PENDING_PAYMENT --> CONFIRMED : Jazmín acknowledges SPEI/Cash deposit
    PENDING_PAYMENT --> EXPIRED : 2-hour timeout reached without payment
    PENDING_PAYMENT --> CANCELLED : Client or Therapist cancels
    
    CONFIRMED --> COMPLETED : Consultation conducted successfully
    CONFIRMED --> NO_SHOW : Client failed to attend without notice
    CONFIRMED --> CANCELLED : Rescheduled or refunded cancellation
```

### Event Transitions & Side-Effects

| Transition | Trigger | Calendar Side-Effect | Notification / WhatsApp |
| :--- | :--- | :--- | :--- |
| `-> PENDING_PAYMENT` | Client submits reservation | Creates tentative event `[PENDIENTE] Nombre` (Yellow) | Pre-fills `wa.me` message with CLABE and Folio `ADS-XXXX` |
| `PENDING -> CONFIRMED` | Jazmín taps "Acreditar Pago" | Updates event to `[CONFIRMADO] Nombre` (Green) + Meet link | Sends confirmation message to client |
| `PENDING -> EXPIRED` | Background sweep (timeout) | Deletes tentative hold event | Frees slot for other clients |
| `CONFIRMED -> NO_SHOW` | Post-session audit | Marks status as `NO_SHOW` in audit log | Records history for future booking policies |

---

## 3. Buffer-Time Collision Prevention Algorithm

To resolve consultation overruns, individual appointment availability enforces a post-session buffer:

$$\text{Blocked Interval} = [\text{Start Time}, \text{Start Time} + \text{Duration} + \text{Buffer (15 min)}]$$

```
[Consultation Slot: 10:00 - 11:00] + [Buffer: 11:00 - 11:15]
                                                              Next Available: 11:15
```

When checking availability for a requested slot $[T_{start}, T_{end}]$:
1. Fetch existing bookings on the requested day where status $\in \{\text{PENDING\_PAYMENT}, \text{CONFIRMED}\}$.
2. Fetch busy blocks from Google Calendar API.
3. Compute overlap:
   $$\text{Overlap} \iff \max(T_{start}, E_{start}) < \min(T_{end} + \text{Buffer}, E_{end})$$
4. If overlap detected, slot is rejected as unavailable.

---

## 4. Multi-Session Package & Course Attendance Schema

```mermaid
erDiagram
    CLIENTS ||--o{ PACKAGES : "purchases"
    PACKAGES ||--o{ BOOKINGS : "redeems"
    SERVICES ||--o{ PACKAGES : "applies to"
    OCCURRENCES ||--o{ ATTENDANCE : "has"
    CLIENTS ||--o{ ATTENDANCE : "attends"

    PACKAGES {
        string id PK
        string client_id FK
        string service_id FK
        int total_sessions
        int completed_sessions
        int price_paid_mxn
        string financial_status "PAID | PARTIAL | PENDING"
        datetime created_at
    }

    OCCURRENCES {
        string id PK
        string service_id FK
        datetime scheduled_at
        string topic "e.g. Clase 3: Abundancia"
    }

    ATTENDANCE {
        string id PK
        string occurrence_id FK
        string client_id FK
        boolean attended
        int amount_paid_mxn
        string payment_method "SPEI | CASH"
        datetime recorded_at
    }
```

---

## 5. Future Extensibility: MCP & LLM Agent Readiness

The business layer is implemented as pure Python service functions returning Pydantic domain models, completely independent of the FastAPI routing layer.

This enables future exposure via:
1. **Model Context Protocol (MCP)**: An MCP server exposing tools (`list_available_slots`, `reserve_session`, `verify_payment`, `get_client_package_status`) directly to Claude, Cursor, or Antigravity agents.
2. **WhatsApp AI Bot**: A webhook listening to incoming WhatsApp messages from clients, querying `armonia-api` for availability, and answering booking inquiries conversationally.
