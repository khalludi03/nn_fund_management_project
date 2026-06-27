from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError


class NnFundRequisition(models.Model):
    _name = 'nn.fund.requisition'
    _description = 'Fund Requisition'
    _inherit = [
        'mail.thread',
        'mail.activity.mixin',
        'nn.approval.mixin',
    ]
    _order = 'request_date desc, id desc'

    name = fields.Char(
        string='Requisition Number',
        required=True,
        copy=False,
        default='New',
        tracking=True,
    )
    container_id = fields.Many2one(
        'nn.fund.container',
        string='Project / Expense Head',
        required=True,
        tracking=True,
    )
    container_type = fields.Selection(
        related='container_id.container_type',
        string='Type',
        store=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='container_id.currency_id',
        store=True,
    )
    purpose = fields.Text(
        string='Purpose',
        required=True,
    )
    request_date = fields.Date(
        string='Request Date',
        default=fields.Date.today,
        required=True,
        tracking=True,
    )
    required_date = fields.Date(
        string='Required Date',
        required=True,
        tracking=True,
    )
    requested_by = fields.Many2one(
        'res.users',
        string='Requested By',
        default=lambda self: self.env.user,
        required=True,
        tracking=True,
    )
    attachment_ids = fields.Many2many(
        'ir.attachment',
        string='Attachments',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )

    state = fields.Selection([
        ('draft',       'Draft'),
        ('submitted',   'Submitted'),
        ('gm_approved', 'GM Approved'),
        ('approved',    'Approved'),
        ('rejected',   'Rejected'),
        ('cancelled',   'Cancelled'),
        ('closed',      'Closed'),
    ], string='Status',
       default='draft',
       tracking=True,
       copy=False,
    )

    amount = fields.Monetary(
        string='Requested Amount',
        required=True,
        tracking=True,
        currency_field='currency_id',
    )

    bill_ids = fields.One2many(
        'nn.fund.bill',
        'requisition_id',
        string='Bills',
        readonly=True,
    )
    total_billed = fields.Monetary(
        string='Total Billed',
        compute='_compute_bill_amounts',
        store=True,
        currency_field='currency_id',
    )
    remaining_billable = fields.Monetary(
        string='Remaining Billable',
        compute='_compute_bill_amounts',
        store=True,
        currency_field='currency_id',
    )

    approval_log_ids = fields.One2many(
        'nn.approval.log',
        'requisition_id',
        string='Approval History',
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'nn.fund.requisition'
                ) or 'New'
        return super().create(vals_list)

    @api.depends(
        'bill_ids.state',
        'bill_ids.amount',
        'amount',
    )
    def _compute_bill_amounts(self):
        for rec in self:
            posted_bills = rec.bill_ids.filtered(
                lambda b: b.state == 'posted'
            )
            rec.total_billed = sum(
                posted_bills.mapped('amount')
            )
            rec.remaining_billable = (
                rec.amount - rec.total_billed
                if rec.state == 'approved'
                else 0.0
            )

    @api.constrains('required_date', 'request_date')
    def _check_required_date(self):
        for rec in self:
            if rec.required_date < rec.request_date:
                raise ValidationError(
                    "Required date cannot be before request date."
                )

    def _get_balance_source(self):
        return self.container_id

    def _get_approval_log_vals(self, level, action):
        return {
            'requisition_id': self.id,
            'approver_id':    self.env.user.id,
            'level':          level,
            'action':         action,
            'date':           fields.Datetime.now(),
        }

    def _check_submit_balance(self):
        available = self.container_id.available_balance
        if self.amount > available:
            raise ValidationError(
                f"Insufficient balance!\n"
                f"Available: {available:,.2f}\n"
                f"Requested: {self.amount:,.2f}"
            )

    def _on_submit(self):
        self.message_post(
            body=f"Requisition submitted by "
                 f"{self.env.user.name}. "
                 f"Amount {self.amount:,.2f} placed on hold."
        )

    def _on_gm_approve(self):
        self.message_post(
            body=f"GM approved by {self.env.user.name}."
        )

    def _on_md_approve(self):
        self.message_post(
            body=f"MD approved by {self.env.user.name}. "
                 f"Amount {self.amount:,.2f} reserved for bills."
        )

    def _on_reject(self):
        self.message_post(
            body=f"Rejected by {self.env.user.name}. "
                 f"Amount {self.amount:,.2f} returned to "
                 f"available balance."
        )

    def _on_cancel(self):
        self.message_post(
            body=f"Cancelled by {self.env.user.name}."
        )

    def _get_cancel_checks(self):
        return {
            'requester_or_finance': ('draft', 'submitted', 'gm_approved'),
            'admin_only': ('approved',),
            'blocked': ('rejected', 'cancelled', 'closed'),
        }

    def action_close(self):
        for rec in self:
            if not self.env.user.has_group(
                'nn_fund_management.group_finance_user'
            ):
                raise UserError(
                    "Only a Finance User can close a requisition."
                )
            if rec.state != 'approved':
                raise UserError(
                    "Only approved requisitions can be closed."
                )

            unused = rec.remaining_billable
            rec.state = 'closed'
            rec.container_id.sudo()._compute_balances()
            rec.message_post(
                body=f"Closed by {rec.env.user.name}. "
                     f"Unused amount {unused:,.2f} "
                     f"returned to available balance."
            )
