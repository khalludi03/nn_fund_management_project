from odoo import api, fields, models
from odoo.exceptions import ValidationError


class NnFundTransfer(models.Model):
    _name = 'nn.fund.transfer'
    _description = 'Fund Transfer'
    _inherit = [
        'mail.thread',
        'mail.activity.mixin',
        'nn.approval.mixin',
    ]
    _order = 'request_date desc, id desc'

    name = fields.Char(
        string='Transfer Number',
        required=True,
        copy=False,
        default='New',
        tracking=True,
    )
    source_id = fields.Many2one(
        'nn.fund.container',
        string='Source',
        required=True,
        tracking=True,
    )
    destination_id = fields.Many2one(
        'nn.fund.container',
        string='Destination',
        required=True,
        tracking=True,
    )
    source_type = fields.Selection(
        related='source_id.container_type',
        string='Source Type',
        store=True,
    )
    destination_type = fields.Selection(
        related='destination_id.container_type',
        string='Destination Type',
        store=True,
    )
    amount = fields.Monetary(
        string='Amount',
        required=True,
        currency_field='currency_id',
        tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='source_id.currency_id',
        store=True,
    )
    reason = fields.Text(
        string='Reason',
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
    ], string='Status',
       default='draft',
       tracking=True,
       copy=False,
    )

    approval_log_ids = fields.One2many(
        'nn.approval.log',
        'transfer_id',
        string='Approval History',
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'nn.fund.transfer'
                ) or 'New'
        return super().create(vals_list)

    @api.constrains('source_id', 'destination_id')
    def _check_different_containers(self):
        for rec in self:
            if rec.source_id == rec.destination_id:
                raise ValidationError(
                    "Source and destination cannot be the same."
                )

    def _get_balance_source(self):
        return self.source_id

    def _get_approval_log_vals(self, level, action):
        return {
            'transfer_id':   self.id,
            'approver_id':   self.env.user.id,
            'level':         level,
            'action':        action,
            'date':          fields.Datetime.now(),
        }

    def _check_submit_balance(self):
        available = self.source_id.available_balance
        if self.amount > available:
            raise ValidationError(
                f"Insufficient balance in source!\n"
                f"Available: {available:,.2f}\n"
                f"Transfer amount: {self.amount:,.2f}"
            )

    def _on_submit(self):
        self.message_post(
            body=f"Transfer submitted by "
                 f"{self.env.user.name}. "
                 f"Amount {self.amount:,.2f} placed on hold "
                 f"from source."
        )

    def _on_gm_approve(self):
        self.message_post(
            body=f"GM approved by {self.env.user.name}."
        )

    def _on_md_approve(self):
        self.destination_id.sudo()._compute_balances()
        self.message_post(
            body=f"MD approved by {self.env.user.name}. "
                 f"Amount {self.amount:,.2f} transferred to "
                 f"destination."
        )

    def _on_reject(self):
        self.message_post(
            body=f"Rejected by {self.env.user.name}. "
                 f"Amount {self.amount:,.2f} returned to "
                 f"source balance."
        )

    def _on_cancel(self):
        if self.destination_id:
            self.destination_id.sudo()._compute_balances()
        self.message_post(
            body=f"Cancelled by {self.env.user.name}."
        )

    def _get_cancel_checks(self):
        return {
            'requester_or_finance': ('draft', 'submitted', 'gm_approved'),
            'admin_only': ('approved',),
            'blocked': ('rejected', 'cancelled'),
        }
