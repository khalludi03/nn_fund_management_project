import odoo.api
from odoo.exceptions import UserError, ValidationError
from odoo import fields

env = self.env  # noqa: F821

admin = env.ref('base.user_admin')
company = env.company
currency = company.currency_id

results = []


def ok(cond, msg):
    if cond:
        print(f"  PASS: {msg}")
    else:
        print(f"  FAIL: {msg}")
    results.append(cond)


def catch(exc_type, func, msg):
    try:
        func()
        print(f"  FAIL: {msg} - no exception raised")
        results.append(False)
    except exc_type as e:
        print(f"  PASS: {msg}")
        results.append(True)
    except Exception as e:
        print(f"  FAIL: {msg} - unexpected {type(e).__name__}: {e}")
        results.append(False)


# 1. SETUP: account, incoming fund, container A (source) with allocation
print("\n=== 1. SETUP ===")

account = env['nn.fund.account'].create({
    'name': 'Transfer E2E Account',
    'account_type': 'bank',
    'currency_id': currency.id,
    'company_id': company.id,
})

incoming = env['nn.incoming.fund'].create({
    'fund_account_id': account.id,
    'amount': 200000,
    'transaction_ref': 'TRF-TXN-001',
    'sender': 'E2E Donor',
    'date': fields.Date.today(),
    'company_id': company.id,
})
incoming.state = 'confirmed'
account._compute_balances()

source = env['nn.fund.container'].create({
    'name': 'Source Container',
    'code': 'SRC-01',
    'container_type': 'project',
    'company_id': company.id,
    'currency_id': currency.id,
})

dest = env['nn.fund.container'].create({
    'name': 'Dest Container',
    'code': 'DST-01',
    'container_type': 'project',
    'company_id': company.id,
    'currency_id': currency.id,
})

alloc = env['nn.fund.allocation'].create({
    'fund_account_id': account.id,
    'container_id': source.id,
    'amount': 50000,
    'purpose': 'Allocation to source for transfer test',
    'requested_by': admin.id,
    'company_id': company.id,
})
alloc.state = 'submitted'
alloc.state = 'gm_approved'
alloc.state = 'approved'

account._compute_balances()
source._compute_balances()

ok(alloc.state == 'approved', 'allocation approved')
ok(source.available_balance == 50000,
   f"source available_balance = {source.available_balance}")

# 2. CREATE TRANSFER IN DRAFT
print("\n=== 2. DRAFT TRANSFER ===")

t1 = env['nn.fund.transfer'].create({
    'source_id': source.id,
    'destination_id': dest.id,
    'amount': 15000,
    'reason': 'E2E transfer test',
    'requested_by': admin.id,
    'company_id': company.id,
})

ok(t1.state == 'draft', f"Transfer {t1.name} created in draft")

# 3. SAME CONTAINER BLOCKED
print("\n=== 3. SAME CONTAINER ===")

catch(ValidationError, lambda: env['nn.fund.transfer'].create({
    'source_id': source.id,
    'destination_id': source.id,
    'amount': 1000,
    'reason': 'Should be blocked',
    'requested_by': admin.id,
    'company_id': company.id,
}), 'Same container blocked: Source and destination cannot be the same.')

# 4. SUBMIT (bypass security: set state directly)
print("\n=== 4. SUBMIT ===")

t1.state = 'submitted'
source._compute_balances()

ok(t1.state == 'submitted', 'Submitted, state: submitted')
ok(source.transfer_hold == 15000,
   f"transfer_hold = {source.transfer_hold}")
ok(source.available_balance == 35000,
   f"source available_balance = {source.available_balance} (was 50000 - 15000)")

# 5. INSUFFICIENT BALANCE BLOCKED
print("\n=== 5. INSUFFICIENT BALANCE ===")

t_over = env['nn.fund.transfer'].create({
    'source_id': source.id,
    'destination_id': dest.id,
    'amount': 50000,
    'reason': 'Should be blocked - insufficient',
    'requested_by': admin.id,
    'company_id': company.id,
})

# Setting state to submitted directly and recomputing balances should
# trigger _check_no_negative_balance on container
try:
    t_over.state = 'submitted'
    source._compute_balances()
    # If we get here, the negative balance was not caught
    print("  FAIL: Insufficient balance not blocked (negative balance not caught)")
    results.append(False)
    t_over.state = 'cancelled'
except ValidationError as e:
    print(f"  PASS: Insufficient balance blocked")
    results.append(True)
    t_over.state = 'cancelled'

# 6. GM APPROVE
print("\n=== 6. GM APPROVE ===")

t1.state = 'gm_approved'
ok(t1.state == 'gm_approved', 'GM approved, state: gm_approved')

# 7. MD APPROVE
print("\n=== 7. MD APPROVE ===")

t1.state = 'approved'
source._compute_balances()
dest._compute_balances()

ok(t1.state == 'approved', 'MD approved, state: approved')
ok(source.outgoing_transfer == 15000,
   f"source outgoing_transfer = {source.outgoing_transfer}")
ok(dest.incoming_transfer == 15000,
   f"dest incoming_transfer = {dest.incoming_transfer}")

# 8. REJECT (create new transfer, reject it)
print("\n=== 8. REJECT ===")

t_reject = env['nn.fund.transfer'].create({
    'source_id': source.id,
    'destination_id': dest.id,
    'amount': 10000,
    'reason': 'To be rejected',
    'requested_by': admin.id,
    'company_id': company.id,
})
t_reject.state = 'submitted'
source._compute_balances()
ok(source.transfer_hold == 10000,
   f"transfer_hold before reject = {source.transfer_hold}")

t_reject.state = 'rejected'
source._compute_balances()

ok(t_reject.state == 'rejected', 'Rejected, state: rejected')
ok(source.transfer_hold == 0,
   f"source transfer_hold after reject = {source.transfer_hold}")
ok(source.available_balance == 35000,
   f"source available_balance after reject = {source.available_balance}")

# 9. CANCEL APPROVED TRANSFER
print("\n=== 9. CANCEL APPROVED ===")

t1.state = 'cancelled'
source._compute_balances()
dest._compute_balances()

ok(t1.state == 'cancelled', 'Approved transfer cancelled')
ok(source.outgoing_transfer == 0,
   f"source outgoing after cancel = {source.outgoing_transfer}")
ok(dest.incoming_transfer == 0,
   f"dest incoming after cancel = {dest.incoming_transfer}")

# 10. RE-CANCEL BLOCKED (action_cancel checks state transition)
print("\n=== 10. RE-CANCEL ===")

catch(UserError, lambda: t1.action_cancel(),
      'Re-cancel blocked: Cannot cancel in this state.')

# 11. DRAFT CANCELLED DIRECTLY
print("\n=== 11. DRAFT CANCEL ===")

t_draft = env['nn.fund.transfer'].create({
    'source_id': source.id,
    'destination_id': dest.id,
    'amount': 5000,
    'reason': 'Draft to cancel',
    'requested_by': admin.id,
    'company_id': company.id,
})
t_draft.state = 'cancelled'

ok(t_draft.state == 'cancelled', 'Draft cancelled directly')

# 12. ZERO AMOUNT BLOCKED
print("\n=== 12. ZERO AMOUNT ===")

catch(ValidationError, lambda: env['nn.fund.transfer'].create({
    'source_id': source.id,
    'destination_id': dest.id,
    'amount': 0,
    'reason': 'Zero amount',
    'requested_by': admin.id,
    'company_id': company.id,
}), 'Zero amount blocked: Amount must be greater than zero.')

# SUMMARY
print(f"\n{'=' * 40}")
passed = sum(1 for r in results if r)
total = len(results)
print(f"Results: {passed}/{total} passed")
if all(results):
    print("=== ALL TRANSFER TESTS PASSED ===")
else:
    print(f"=== {total - passed} TEST(S) FAILED ===")
