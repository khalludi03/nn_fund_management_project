from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError


class NnFundRequisition(models.Model):
    _name = 'nn.fund.requisition'
    _description = 'Fund Requisition'
    _inherit = ['mail.thread', 'mail.activity.mixin']
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
    amount = fields.Monetary(
        string='Requested Amount',
        required=True,
        tracking=True,
        currency_field='currency_id',
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

    @api.constrains('amount')
    def _check_positive_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(
                    "Amount must be greater than zero."
                )

    @api.constrains('required_date', 'request_date')
    def _check_required_date(self):
        for rec in self:
            if rec.required_date < rec.request_date:
                raise ValidationError(
                    "Required date cannot be before request date."
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

            if rec.env.user != rec.requested_by and not rec.env.user.has_group(
                'nn_fund_management.group_finance_user'
            ):
                raise UserError(
                    "Only the requester or a Finance User can submit."
                )

            available = rec.container_id.available_balance
            if rec.amount > available:
                raise ValidationError(
                    f"Insufficient balance!\n"
                    f"Available: {available:,.2f}\n"
                    f"Requested: {rec.amount:,.2f}"
                )

            rec.state = 'submitted'
            rec.container_id.sudo()._compute_balances()
            rec.message_post(
                body=f"Requisition submitted by "
                     f"{rec.env.user.name}. "
                     f"Amount {rec.amount:,.2f} placed on hold."
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
                    "You cannot approve your own requisition."
                )

            self.env['nn.approval.log'].create({
                'requisition_id': rec.id,
                'approver_id':    rec.env.user.id,
                'level':          'gm',
                'action':         'approved',
                'date':           fields.Datetime.now(),
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
                    "You cannot approve your own requisition."
                )

            self.env['nn.approval.log'].create({
                'requisition_id': rec.id,
                'approver_id':    rec.env.user.id,
                'level':          'md',
                'action':         'approved',
                'date':           fields.Datetime.now(),
            })

            rec.state = 'approved'
            rec.message_post(
                body=f"MD approved by {rec.env.user.name}. "
                     f"Amount {rec.amount:,.2f} reserved for bills."
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
                'requisition_id': rec.id,
                'approver_id':    current_user.id,
                'level':          level,
                'action':         'rejected',
                'date':           fields.Datetime.now(),
            })

            rec.state = 'rejected'
            rec.container_id.sudo()._compute_balances()
            rec.message_post(
                body=f"Rejected by {current_user.name}. "
                     f"Amount {rec.amount:,.2f} returned to "
                     f"available balance."
            )

    def action_cancel(self):
        for rec in self:
            if rec.state in ('draft', 'submitted', 'gm_approved'):
                if rec.env.user != rec.requested_by and not rec.env.user.has_group(
                    'nn_fund_management.group_finance_user'
                ):
                    raise UserError(
                        "Only the requester or a Finance User can cancel "
                        "this requisition."
                    )
            elif rec.state == 'approved':
                if not self.env.user.has_group(
                    'nn_fund_management.group_fund_admin'
                ):
                    raise UserError(
                        "Only an Administrator can cancel an approved "
                        "requisition."
                    )
            elif rec.state in ('rejected', 'cancelled', 'closed'):
                raise UserError(
                    "Cannot cancel in this state."
                )
            rec.state = 'cancelled'
            rec.container_id.sudo()._compute_balances()
            rec.message_post(
                body=f"Cancelled by {rec.env.user.name}."
            )

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
