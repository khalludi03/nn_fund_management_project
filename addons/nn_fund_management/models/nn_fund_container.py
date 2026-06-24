from odoo import api, fields, models
from odoo.exceptions import ValidationError


class NnFundContainer(models.Model):
    _name = 'nn.fund.container'
    _description = 'Project / Expense Head'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'container_type, name'

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

    total_allocated = fields.Monetary(
        string='Total Allocated',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='Total from approved allocations',
    )
    requisition_hold = fields.Monetary(
        string='Requisition Hold',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='Amount held in pending requisitions',
    )
    transfer_hold = fields.Monetary(
        string='Transfer Hold',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='Amount held in pending transfers',
    )
    incoming_transfer = fields.Monetary(
        string='Incoming Transfers',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='Approved transfers received from other containers',
    )
    outgoing_transfer = fields.Monetary(
        string='Outgoing Transfers',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='Approved transfers sent to other containers',
    )
    total_spent = fields.Monetary(
        string='Total Spent',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='Total amount of posted bills',
    )
    available_balance = fields.Monetary(
        string='Available Balance',
        compute='_compute_balances',
        store=True,
        currency_field='currency_id',
        help='Amount available for requisitions or transfers',
    )

    allocation_ids = fields.One2many(
        'nn.fund.allocation',
        'container_id',
        string='Allocations',
    )
    requisition_ids = fields.One2many(
        'nn.fund.requisition',
        'container_id',
        string='Requisitions',
    )

    @api.depends(
        'allocation_ids.state',
        'allocation_ids.amount',
        'requisition_ids.state',
        'requisition_ids.amount',
    )
    def _compute_balances(self):
        for rec in self:
            approved_alloc = self.env['nn.fund.allocation'].search([
                ('container_id', '=', rec.id),
                ('state', '=', 'approved'),
            ])
            rec.total_allocated = sum(
                approved_alloc.mapped('amount')
            )

            hold_reqs = self.env['nn.fund.requisition'].search([
                ('container_id', '=', rec.id),
                ('state', 'in', (
                    'submitted', 'gm_approved', 'approved'
                )),
            ])
            rec.requisition_hold = sum(
                hold_reqs.mapped('amount')
            )

            rec.total_spent = 0.0

            rec.transfer_hold     = 0.0
            rec.incoming_transfer = 0.0
            rec.outgoing_transfer = 0.0

            rec.available_balance = (
                rec.total_allocated
                + rec.incoming_transfer
                - rec.outgoing_transfer
                - rec.requisition_hold
                - rec.transfer_hold
                - rec.total_spent
            )

    @api.constrains('code', 'company_id')
    def _check_unique_code(self):
        """No duplicate code allowed within the same company"""
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
        """Negative balance is never allowed"""
        for rec in self:
            if rec.available_balance < 0:
                raise ValidationError(
                    f"'{rec.name}'s available balance "
                    f"cannot be negative."
                )

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