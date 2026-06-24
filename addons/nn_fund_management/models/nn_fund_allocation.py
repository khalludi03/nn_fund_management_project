from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError


class NnFundAllocation(models.Model):
    _name = 'nn.fund.allocation'
    _description = 'Fund Allocation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
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

    gm_user_id = fields.Many2one(
        'res.users',
        string='GM Approver',
        compute='_compute_approvers',
    )
    md_user_id = fields.Many2one(
        'res.users',
        string='MD Approver',
        compute='_compute_approvers',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'nn.fund.allocation'
                ) or 'New'
        return super().create(vals_list)

    def _compute_approvers(self):
        """
        Find configured approver by company
        """
        for rec in self:
            config = self.env['nn.approval.config'].search([
                ('company_id', '=', rec.company_id.id)
            ], limit=1)
            rec.gm_user_id = config.gm_user_id if config else False
            rec.md_user_id = config.md_user_id if config else False

    @api.constrains('amount')
    def _check_positive_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(
                    "Amount must be greater than zero."
                )

    def _get_approval_config(self):
        config = self.env['nn.approval.config'].search([
            ('company_id', '=', self.company_id.id)
        ], limit=1)
        if not config:
            raise UserError(
                "Approval configuration not found. "
                "Set GM and MD from the Configuration menu."
            )
        return config

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError("Only draft records can be submitted.")

            available = rec.fund_account_id.available_unassigned_balance
            if rec.amount > available:
                raise ValidationError(
                    f"Insufficient balance!\n"
                    f"Available: {available:,.2f}\n"
                    f"Requested: {rec.amount:,.2f}"
                )

            rec.state = 'submitted'
            rec.fund_account_id.sudo()._compute_balances()
            rec.message_post(
                body=f"Request submitted by {rec.env.user.name}."
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
                    "You cannot approve your own allocation request."
                )

            self.env['nn.approval.log'].create({
                'allocation_id': rec.id,
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
                    "You cannot approve your own allocation request."
                )

            self.env['nn.approval.log'].create({
                'allocation_id': rec.id,
                'approver_id':   rec.env.user.id,
                'level':         'md',
                'action':        'approved',
                'date':          fields.Datetime.now(),
            })

            rec.state = 'approved'

            rec.fund_account_id.sudo()._compute_balances()
            rec.container_id.sudo()._compute_balances()

            rec.message_post(
                body=f"MD approved by {rec.env.user.name}. "
                     f"Amount {rec.amount:,.2f} allocated to "
                     f"{rec.container_id.name}."
            )

    def action_reject(self):
        for rec in self:
            if rec.state not in ('submitted', 'gm_approved'):
                raise UserError(
                    "Rejection is only allowed in Submitted or GM Approved state."
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
                'allocation_id': rec.id,
                'approver_id':   current_user.id,
                'level':         level,
                'action':        'rejected',
                'date':          fields.Datetime.now(),
            })

            rec.state = 'rejected'

            rec.fund_account_id.sudo()._compute_balances()
            rec.message_post(
                body=f"Rejected by {current_user.name}. "
                     f"Amount {rec.amount:,.2f} returned to "
                     f"unassigned balance."
            )

    def action_cancel(self):
        for rec in self:
            if rec.state == 'approved':
                if not self.env.user.has_group(
                    'nn_fund_management.group_fund_admin'
                ):
                    raise UserError(
                        "Only Administrator can cancel an approved "
                        "allocation."
                    )
            if rec.state in ('rejected', 'cancelled'):
                raise UserError(
                    "Rejected or cancelled records cannot be cancelled again."
                )
            rec.state = 'cancelled'
            rec.fund_account_id.sudo()._compute_balances()
            rec.message_post(
                body=f"Cancelled by {rec.env.user.name}."
            )