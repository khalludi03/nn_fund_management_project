from odoo import api, fields, models
from odoo.exceptions import ValidationError


class NnFundAllocation(models.Model):
    _name = 'nn.fund.allocation'
    _description = 'Fund Allocation'
    _inherit = [
        'mail.thread',
        'mail.activity.mixin',
        'nn.approval.mixin',
    ]
    _order = 'request_date desc, id desc'

    name = fields.Char(
        string='Request Number',
        required=True,
        copy=False,
        default='New',
        tracking=True,
    )
    fund_account_id = fields.Many2one(
        'nn.fund.account',
        string='Fund Account',
        required=True,
        tracking=True,
        states={'draft': [('readonly', False)]},
    )
    container_id = fields.Many2one(
        'nn.fund.container',
        string='Project / Expense Head',
        required=True,
        tracking=True,
        states={'draft': [('readonly', False)]},
    )
    container_type = fields.Selection(
        related='container_id.container_type',
        string='Type',
        store=True,
    )
    amount = fields.Monetary(
        string='Amount',
        required=True,
        tracking=True,
        currency_field='currency_id',
        states={'draft': [('readonly', False)]},
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='fund_account_id.currency_id',
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
        ('rejected',    'Rejected'),
        ('cancelled',   'Cancelled'),
    ], string='Status',
       default='draft',
       tracking=True,
       copy=False,
    )

    approval_log_ids = fields.One2many(
        'nn.approval.log',
        'allocation_id',
        string='Approval History',
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'nn.fund.allocation'
                ) or 'New'
        return super().create(vals_list)

    def _get_balance_source(self):
        return self.fund_account_id

    def _get_approval_log_vals(self, level, action):
        return {
            'allocation_id': self.id,
            'approver_id':   self.env.user.id,
            'level':         level,
            'action':        action,
            'date':          fields.Datetime.now(),
        }

    def _check_submit_balance(self):
        available = self.fund_account_id.available_unassigned_balance
        if self.amount > available:
            raise ValidationError(
                f"Insufficient balance!\n"
                f"Available: {available:,.2f}\n"
                f"Requested: {self.amount:,.2f}"
            )

    def _on_submit(self):
        self.message_post(
            body=f"Request submitted by {self.env.user.name}."
        )

    def _on_gm_approve(self):
        self.message_post(
            body=f"GM approved by {self.env.user.name}."
        )

    def _on_md_approve(self):
        self.container_id.sudo()._compute_balances()
        self.message_post(
            body=f"MD approved by {self.env.user.name}. "
                 f"Amount {self.amount:,.2f} allocated to "
                 f"{self.container_id.name}."
        )

    def _on_reject(self):
        self.message_post(
            body=f"Rejected by {self.env.user.name}. "
                 f"Amount {self.amount:,.2f} returned to "
                 f"unassigned balance."
        )

    def _on_cancel(self):
        self.message_post(
            body=f"Cancelled by {self.env.user.name}."
        )

    def _get_cancel_checks(self):
        return {
            'requester_or_finance': ('draft', 'submitted', 'gm_approved'),
            'admin_only': ('approved',),
            'blocked': ('rejected', 'cancelled'),
        }