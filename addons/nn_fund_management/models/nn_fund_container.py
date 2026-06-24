from odoo import api, fields, models
from odoo.exceptions import ValidationError


class NnFundContainer(models.Model):
    _name = 'nn.fund.container'
    _description = 'Project / Expense Head'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'container_type, name'

    # ── Basic Info ───────────────────────────────────────
    name = fields.Char(
        string='Name',
        required=True,
        tracking=True,
    )
    code = fields.Char(
        string='Code',
        required=True,
        copy=False,
        tracking=True,
    )
    container_type = fields.Selection([
        ('project',      'Project'),
        ('expense_head', 'Expense Head'),
    ], string='Type',
       required=True,
       default='project',
       tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True, tracking=True)

    # ── Balance Fields (সব computed) ────────────────────
    total_allocated = fields.Monetary(
        string='Total Allocated',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='Approved allocation থেকে আসা মোট টাকা',
    )
    requisition_hold = fields.Monetary(
        string='Requisition Hold',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='Pending requisition এ আটকে থাকা টাকা',
    )
    transfer_hold = fields.Monetary(
        string='Transfer Hold',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='Pending transfer এ আটকে থাকা টাকা',
    )
    incoming_transfer = fields.Monetary(
        string='Incoming Transfers',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='অন্য container থেকে approved transfer এসেছে',
    )
    outgoing_transfer = fields.Monetary(
        string='Outgoing Transfers',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='অন্য container এ approved transfer গেছে',
    )
    total_spent = fields.Monetary(
        string='Total Spent',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='Posted bill এর মোট পরিমাণ',
    )
    available_balance = fields.Monetary(
        string='Available Balance',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='এখন requisition বা transfer করা যাবে এই পরিমাণ',
    )

    # ── Reverse Relation ─────────────────────────────────
    allocation_ids = fields.One2many(
        'nn.fund.allocation',
        'container_id',
        string='Allocations',
    )

    # ── Compute ──────────────────────────────────────────
    @api.depends(
        'allocation_ids.state',
        'allocation_ids.amount',
    )
    def _compute_balances(self):
        for rec in self:
            approved = self.env['nn.fund.allocation'].search([
                ('container_id', '=', rec.id),
                ('state', '=', 'approved'),
            ])
            rec.total_allocated = sum(approved.mapped('amount'))
            rec.requisition_hold  = 0.0
            rec.transfer_hold     = 0.0
            rec.incoming_transfer = 0.0
            rec.outgoing_transfer = 0.0
            rec.total_spent       = 0.0
            rec.available_balance = (
                rec.total_allocated
                + rec.incoming_transfer
                - rec.outgoing_transfer
                - rec.requisition_hold
                - rec.transfer_hold
                - rec.total_spent
            )

    # ── Constraints ──────────────────────────────────────
    @api.constrains('code', 'company_id')
    def _check_unique_code(self):
        """একই company তে duplicate code চলবে না"""
        for rec in self:
            duplicate = self.search([
                ('code',       '=', rec.code),
                ('company_id', '=', rec.company_id.id),
                ('id',         '!=', rec.id),
            ])
            if duplicate:
                raise ValidationError(
                    f"Code '{rec.code}' already exists "
                    f"in company '{rec.company_id.name}'."
                )

    @api.constrains('available_balance')
    def _check_no_negative_balance(self):
        """Negative balance কখনো allow করা যাবে না"""
        for rec in self:
            if rec.available_balance < 0:
                raise ValidationError(
                    f"'{rec.name}' এর available balance "
                    f"negative হতে পারবে না।"
                )

    # ── Display Name ─────────────────────────────────────
    def name_get(self):
        result = []
        for rec in self:
            type_label = (
                'PRJ' if rec.container_type == 'project'
                else 'EXP'
            )
            display = f"[{type_label}] {rec.name}"
            result.append((rec.id, display))
        return result