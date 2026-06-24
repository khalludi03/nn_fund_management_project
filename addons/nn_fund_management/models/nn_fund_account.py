from odoo import api, fields, models
from odoo.exceptions import ValidationError


class NnFundAccount(models.Model):
    _name = 'nn.fund.account'
    _description = 'Fund Account'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    # ── Basic Info ───────────────────────────────────────
    name = fields.Char(
        string='Account Name',
        required=True,
        tracking=True,
    )
    code = fields.Char(
        string='Account Code',
        copy=False,
        tracking=True,
    )
    account_type = fields.Selection([
        ('bank',  'Bank'),
        ('cash',  'Cash'),
        ('other', 'Other'),
    ], string='Account Type',
       required=True,
       default='bank',
       tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True, tracking=True)

    # ── Reverse Relation ─────────────────────────────────
    # nn.incoming.fund এর সব record এখানে link থাকবে
    incoming_fund_ids = fields.One2many(
        'nn.incoming.fund',
        'fund_account_id',
        string='Incoming Funds',
    )

    # ── Balance Fields ───────────────────────────────────
    total_received = fields.Monetary(
        string='Total Received',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='সব confirmed incoming fund এর মোট',
    )
    amount_on_hold = fields.Monetary(
        string='Amount on Hold',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='Pending allocation এ আটকে থাকা টাকা',
    )
    total_assigned = fields.Monetary(
        string='Total Assigned',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='Approved allocation এর মোট',
    )
    available_unassigned_balance = fields.Monetary(
        string='Available Unassigned Balance',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='Total Received - On Hold - Assigned',
    )

    # ── Compute ──────────────────────────────────────────
    @api.depends(
        'incoming_fund_ids.state',
        'incoming_fund_ids.amount',
    )
    def _compute_balances(self):
        """
        এখন শুধু incoming fund থেকে
        total_received calculate হচ্ছে।

        allocation model তৈরি হলে
        amount_on_hold ও total_assigned
        আপডেট করা হবে।
        """
        for rec in self:
            # ── Total Received ──────────────────────────
            # শুধু confirmed incoming fund count করবো
            confirmed_funds = rec.incoming_fund_ids.filtered(
                lambda f: f.state == 'confirmed'
            )
            rec.total_received = sum(
                confirmed_funds.mapped('amount')
            )

            # ── On Hold ─────────────────────────────────
            # nn.fund.allocation তৈরি হলে আসবে
            rec.amount_on_hold = 0.0

            # ── Total Assigned ───────────────────────────
            # nn.fund.allocation তৈরি হলে আসবে
            rec.total_assigned = 0.0

            # ── Available Unassigned ─────────────────────
            rec.available_unassigned_balance = (
                rec.total_received
                - rec.amount_on_hold
                - rec.total_assigned
            )

    # ── Constraints ──────────────────────────────────────
    @api.constrains('code', 'company_id')
    def _check_unique_code(self):
        """একই company তে duplicate code চলবে না"""
        for rec in self:
            if rec.code:
                duplicate = self.search([
                    ('code',       '=', rec.code),
                    ('company_id', '=', rec.company_id.id),
                    ('id',         '!=', rec.id),
                ])
                if duplicate:
                    raise ValidationError(
                        f"Account code '{rec.code}' already exists "
                        f"in '{rec.company_id.name}'."
                    )

    # ── Display Name ─────────────────────────────────────
    def name_get(self):
        result = []
        for rec in self:
            display = (
                f"[{rec.code}] {rec.name}"
                if rec.code else rec.name
            )
            result.append((rec.id, display))
        return result