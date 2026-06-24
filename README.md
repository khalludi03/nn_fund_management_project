# NN Fund Management

Odoo 17 module for managing company funds with multi-level approval workflow, allocation tracking, bill control, fund transfers, and double-spending prevention.

## Odoo Version

**17.0** — built and tested with `odoo:17.0` Docker image and PostgreSQL 15.

## Installation

### Prerequisites

- Docker and Docker Compose
- Git

### Steps

```bash
git clone https://github.com/khalludi03/nn_fund_management_project.git
cd nn_fund_management_project
docker compose up -d
```

Wait for both containers to be healthy, then access Odoo at `http://localhost:8069`.

1. Create a new database named `db` (set master password and click "Create Database").
2. Go to **Apps → Remove App Filter** → search `NN Fund Management` → **Install**.

### Manual Upgrade

After code changes, upgrade the module:

```bash
docker compose restart odoo
```

Then go to **Apps → NN Fund Management → Upgrade**.

## Required Dependencies

- `odoo:17.0` Docker image (includes all Odoo runtime dependencies)
- `postgres:15` for the database
- No additional Python packages beyond Odoo's built-in modules (`mail`, `base`).

The module declares two Odoo dependencies in its manifest:
- `base` — core Odoo framework
- `mail` — for chatter/tracking/notifications

## Configuration Steps

### 1. Security Groups

The module installs five groups under the **Fund Management** application category with inheritance:

| Group | Inherits | Access Level |
|---|---|---|
| Fund User | — | Create and view own records |
| GM Approver | Fund User | GM-level approval authority |
| Finance User | Fund User | Confirm incoming funds, post bills |
| MD Approver | GM Approver + Finance User | MD-level approval authority |
| Fund Administrator | MD Approver + Finance User | Full access, cancel approved records, configuration |

Assign users to appropriate groups at **Settings → Users & Companies → Users**.

### 2. Approval Configuration

Go to **Fund Management → Configuration → Approval Config** and create a record:

- Set **GM User** and **MD User** to the respective approvers for each company.

### 3. Fund Accounts

Go to **Fund Management → Fund Accounts** and create at least one account with a currency.

### 4. Containers (Projects / Expense Heads)

Go to **Fund Management → Configuration** and create containers with type **Project** or **Expense Head**.

### 5. Incoming Funds

Finance Users can create and confirm incoming fund entries, which increases the account's unassigned balance.

## Implemented Models

| Model | Description |
|---|---|
| `nn.fund.account` | Top-level fund accounts with computed balances (`amount_on_hold`, `total_assigned`) |
| `nn.incoming.fund` | Funds received into accounts, confirmable by Finance User |
| `nn.fund.container` | Projects/Expense Heads — central balance computation |
| `nn.fund.allocation` | Allocate container money, 4-state workflow (draft → submitted → gm_approved → approved) |
| `nn.fund.requisition` | Request funds from a container for bills, 5-state workflow |
| `nn.fund.bill` | Bills against requisitions, posted by Finance User, cancel returns funds |
| `nn.fund.transfer` | Transfer money between containers, 5-state workflow |
| `nn.approval.log` | Audit trail for every approval and rejection action |
| `nn.approval.config` | GM/MD user mapping per company |

## Container Balance Formula

The `available_balance` on `nn.fund.container` is computed as:

```
available_balance = total_allocated + incoming_transfer - outgoing_transfer
                    - requisition_hold - transfer_hold - total_spent
```

Where:
- `total_allocated` — sum of approved allocations
- `incoming_transfer` — sum of approved transfers into this container
- `outgoing_transfer` — sum of approved transfers out of this container
- `requisition_hold` — sum of submitted/gm_approved/approved requisitions
- `transfer_hold` — sum of submitted/gm_approved transfers
- `total_spent` — sum of posted bills

All fields are `store=True` computed fields — never manually editable.

## Security Architecture

### Server-Side Enforcement

Every action method includes server-side group checks (not just UI button visibility):

| Method | Required Access |
|---|---|
| `action_submit` (allocation/requisition/transfer) | Requester OR Finance User |
| `action_cancel` draft/submitted/gm_approved (allocation/requisition/transfer) | Requester OR Finance User |
| `action_cancel` approved (allocation/requisition/transfer) | Fund Administrator |
| `action_gm_approve` | Configured GM User (no self-approval) |
| `action_md_approve` | Configured MD User (no self-approval) |
| `action_confirm` (incoming fund) | Finance User |
| `action_post` (bill) | Finance User |
| `action_cancel` (incoming fund) | Finance User |
| `action_cancel` draft bill | Finance User |
| `action_close` (requisition) | Finance User |

### Record Rules

- Company-scoped rules per model for each applicable group
- Own-record-only rules for Fund Users (allocation, requisition)
- Finance/Admin rules grant full company visibility per model

### ACLs (ir.model.access.csv)

Each model has row-level access defined for each group:
- Fund User: read/create, no write/unlink on most
- Finance User: full CRUD on financial models
- Fund Administrator: full CRUD on all models

## Testing

### Setup Test Users

Run the following in an Odoo shell to create test users:

```python
from odoo import api

env = api.Environment(self.env.cr, self.env.user.id, {})
Admin = env.ref('base.user_admin')
Group_GM = env.ref('nn_fund_management.group_gm_approver')
Group_MD = env.ref('nn_fund_management.group_md_approver')
Group_Finance = env.ref('nn_fund_management.group_finance_user')

# Users created via shell with explicit commit:
# gm@test.com (GM Approver), md@test.com (MD Approver), finance@test.com (Finance User)
# Password: test123
```

### End-to-End Tests

24 automated e2e tests are available in the `/tmp/` directory of the odoo container:

**Bill Tests** (`test_bill_e2e.py` — 13 tests):
- Create approved allocation and approved requisition
- Create bills up to remaining_billable limit
- Block overspend
- Post bill, verify remaining decreases
- Cancel posted bill, verify remaining increases
- Block modify/delete of posted/cancelled bills
- Allow delete of draft bills

**Transfer Tests** (`test_transfer_e2e.py` — 11 tests):
- Create transfer in draft state
- Block same-container transfers
- Submit with sufficient balance, verify hold
- Reject insufficient balance
- GM approve → MD approve
- Reject, verify hold released
- Cancel approved transfer
- Block re-cancel after cancelled
- Cancel from draft directly
- Block zero-amount transfers

Run from host:
```bash
docker cp /path/to/test_bill_e2e.py nn_fund_management_project-odoo-1:/tmp/
docker exec -i nn_fund_management_project-odoo-1 \
  python3 /usr/bin/odoo shell \
  --db_host=db --db_user=odoo --db_password=odoo \
  --database=db --no-http \
  --addons-path=/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons \
  < /tmp/test_bill_e2e.py
```

## Manual Testing Flow

1. **Login as Finance User** (`finance@test.com` / `test123`)
   - Create and confirm an incoming fund entry.
   - Verify the fund account's unassigned balance increases.

2. **Login as Fund User** (regular user with Fund User group)
   - Create a new allocation request.
   - Submit it — you should see a confirmation message.

3. **Login as GM Approver** (`gm@test.com` / `test123`)
   - Open the submitted allocation.
   - Click **GM Approve** — state changes to GM Approved.
   - Verify the approval log entry is created.

4. **Login as MD Approver** (`md@test.com` / `test123`)
   - Open the GM Approved allocation.
   - Click **MD Approve** — state changes to Approved.
   - Verify the fund account's assigned balance and container's allocated balance update.

5. **Double-spending prevention**
   - Try submitting an allocation larger than the available balance.
   - Verify it is rejected with an "Insufficient balance" error.

6. **Fund Transfer Flow**
   - Create a transfer between two containers.
   - Submit → verify source `available_balance` decreases by `transfer_hold`.
   - GM approve → MD approve → verify source `outgoing_transfer` and destination `incoming_transfer` update.
   - Cancel the approved transfer → verify balances revert.

## Assumptions

- All monetary amounts are in a single currency per fund account.
- Approval follows a strict two-level chain: Draft → Submitted → GM Approved → Approved.
- Only configured GM and MD users can approve at their respective levels.
- A user cannot approve their own allocation, requisition, or transfer.
- Fund Administrator inherits all permissions (Finance + MD Approver).
- Containers unify Projects and Expense Heads under a single model with a type field.
- Fund Account and Container balances are computed from related records — never manually editable.
- The `mail` module is available for chatter and message tracking.
- Odoo is deployed via Docker; the module path is `/mnt/extra-addons`.

## Known Limitations

- **Configurable approval rules** (per-amount thresholds) — the `nn.approval.config` model exists but is not wired into the workflow; GM/MD users are set via Odoo shell.
- **Bank email integration** — not implemented; incoming funds must be entered manually.
- **Dashboard view** — not implemented; only standard tree/form views.
- **Test coverage** — 24 e2e tests cover core flows but not every edge case (concurrent submissions, race conditions).
- **Multi-company** — basic `company_id` field and record rules exist but no inter-company transfers or cross-company visibility.
- **No automated CI** — tests must be run manually via Docker exec.

## Git History

The repository uses conventional commits and a meaningful history of ~15 commits covering:
- Module skeleton, Docker setup
- Fund accounts, incoming funds, containers, approval workflow
- Allocations, requisitions, bills, transfers
- Security audit (server-side group checks, record rules)
- Bill write/unlink protection
- README, test scripts
