# NN Fund Management

Odoo 17 module for managing company funds with multi-level approval workflow, allocation tracking, and double-spending prevention.

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

The module installs five groups under the **Fund Management** application category:

| Group | Access Level |
|---|---|
| Fund User | Create and view own requests |
| Finance User | Fund User + confirm incoming funds |
| GM Approver | Fund User + GM-level approval |
| MD Approver | GM Approver + MD-level approval |
| Fund Administrator | Finance User + MD Approver + full configuration access |

Assign users to appropriate groups at **Settings → Users & Companies → Users**.

### 2. Approval Configuration

Go to **Fund Management → Configuration → Approval Config** and create a record:

- Set **GM User** and **MD User** to the respective approvers for each company.

### 3. Fund Accounts

Go to **Fund Management → Fund Accounts** and create at least one account with a currency.

### 4. Containers (Projects / Expense Heads)

Go to **Fund Management → Configuration** (menu) and create containers with type **Project** or **Expense Head**.

### 5. Incoming Funds

Finance Users can create and confirm incoming fund entries, which increases the account's unassigned balance.

## Testing Instructions

### Manual Testing Flow

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

### Automated Tests

No automated tests are written yet (see Known Limitations).

## Assumptions

- All monetary amounts are in a single currency per fund account.
- Approval follows a strict two-level chain: Draft → Submitted → GM Approved → Approved.
- Only configured GM and MD users can approve at their respective levels.
- A user cannot approve their own allocation request.
- Fund Administrator inherits all permissions (Finance + MD Approver).
- Containers unify Projects and Expense Heads under a single model with a type field.
- Fund Account balances are computed from related records — never manually editable.
- The `mail` module is available for chatter and message tracking.
- Odoo is deployed via Docker; the module path is `/mnt/extra-addons`.

## Known Limitations

- **Fund Transfer** model not yet implemented.
- **Bill Control** model is a stub with no full logic.
- **Configurable approval rules** (per-amount thresholds) not yet implemented.
- **Bank email integration** not yet implemented.
- **Dashboard view** not yet implemented.
- **No automated tests** — the `tests/` directory has not been created.
- **No multi-company isolation** beyond basic `company_id` record rules.
- Approval log entries are created manually; the module does not use Odoo's base approval framework.
- The `db_filter = ^db$` config means only databases matching exactly `db` are visible at login.
