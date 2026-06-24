from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError


class NnFundTransfer(models.Model):
    _name = 'nn.fund.transfer'
    _description = 'Fund Transfer'
    _inherit = ['mail.thread', 'mail.activity.mixin']
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
    requested_by = fields.Many2one(
        'res.users',
        string='Requested By',
        default=lambda self: self.env.user,
        required=True,
        tracking=True,
    )
    request_date = fields.Date(
        string='Request Date',
        default=fields.Date.today,
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

    @api.constrains('amount')
    def _check_positive_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(
                    "Amount must be greater than zero."
                )

    @api.constrains('source_id', 'destination_id')
    def _check_different_containers(self):
        for rec in self:
            if rec.source_id == rec.destination_id:
                raise ValidationError(
                    "Source and destination cannot be the same."
                )

    def _get_approval_config(self):
        config = self.env['nn.approval.config'].search([
            ('company_id', '=', self.company_id.id)
        ], limit=1)
        if not config:
            raise UserError(
                "Approval configuration not found. "
                "Please set GM and MD from Configuration menu."
            )
        return config

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(
                    "Only draft records can be submitted."
                )

            available = rec.source_id.available_balance
            if rec.amount > available:
                raise ValidationError(
                    f"Insufficient balance in source!\n"
                    f"Available: {available:,.2f}\n"
                    f"Transfer amount: {rec.amount:,.2f}"
                )

            rec.state = 'submitted'
            rec.source_id.sudo()._compute_balances()
            rec.message_post(
                body=f"Transfer submitted by "
                     f"{rec.env.user.name}. "
                     f"Amount {rec.amount:,.2f} placed on hold "
                     f"from source."
            )

    def action_gm_approve(self):
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(
                    "GM approval is only allowed in Submitted state."
                )

            config = rec._get_approval_config()

            if rec.env.user != config.gm_user_id:
                raise UserError(
                    "Only the configured GM can approve this request."
                )

            if rec.requested_by == rec.env.user:
                raise UserError(
                    "You cannot approve your own transfer."
                )

            self.env['nn.approval.log'].create({
                'transfer_id':   rec.id,
                'approver_id':   rec.env.user.id,
                'level':         'gm',
                'action':        'approved',
                'date':          fields.Datetime.now(),
            })

            rec.state = 'gm_approved'
            rec.message_post(
                body=f"GM approved by {rec.env.user.name}."
            )

    def action_md_approve(self):
        for rec in self:
            if rec.state != 'gm_approved':
                raise UserError(
                    "MD approval is only allowed after GM approval."
                )

            config = rec._get_approval_config()

            if rec.env.user != config.md_user_id:
                raise UserError(
                    "Only the configured MD can approve this request."
                )

            if rec.requested_by == rec.env.user:
                raise UserError(
                    "You cannot approve your own transfer."
                )

            self.env['nn.approval.log'].create({
                'transfer_id':   rec.id,
                'approver_id':   rec.env.user.id,
                'level':         'md',
                'action':        'approved',
                'date':          fields.Datetime.now(),
            })

            rec.state = 'approved'
            rec.source_id.sudo()._compute_balances()
            rec.destination_id.sudo()._compute_balances()
            rec.message_post(
                body=f"MD approved by {rec.env.user.name}. "
                     f"Amount {rec.amount:,.2f} transferred to "
                     f"destination."
            )

    def action_reject(self):
        for rec in self:
            if rec.state not in ('submitted', 'gm_approved'):
                raise UserError(
                    "Rejection is only allowed in Submitted "
                    "or GM Approved state."
                )

            config = rec._get_approval_config()
            current_user = rec.env.user

            if rec.state == 'submitted':
                if current_user != config.gm_user_id:
                    raise UserError(
                        "Only the GM can reject at this stage."
                    )
                level = 'gm'
            else:
                if current_user != config.md_user_id:
                    raise UserError(
                        "Only the MD can reject at this stage."
                    )
                level = 'md'

            self.env['nn.approval.log'].create({
                'transfer_id':   rec.id,
                'approver_id':   current_user.id,
                'level':         level,
                'action':        'rejected',
                'date':          fields.Datetime.now(),
            })

            rec.state = 'rejected'
            rec.source_id.sudo()._compute_balances()
            rec.message_post(
                body=f"Rejected by {current_user.name}. "
                     f"Amount {rec.amount:,.2f} returned to "
                     f"source balance."
            )

    def action_cancel(self):
        for rec in self:
            if rec.state == 'approved':
                if not self.env.user.has_group(
                    'nn_fund_management.group_fund_admin'
                ):
                    raise UserError(
                        "Only an Administrator can cancel an approved "
                        "transfer."
                    )
            elif rec.state in ('rejected', 'cancelled'):
                raise UserError(
                    "Cannot cancel in this state."
                )
            rec.state = 'cancelled'
            rec.source_id.sudo()._compute_balances()
            if rec.destination_id:
                rec.destination_id.sudo()._compute_balances()
            rec.message_post(
                body=f"Cancelled by {rec.env.user.name}."
            )
