from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError


class NnFundBill(models.Model):
    _name = 'nn.fund.bill'
    _description = 'Fund Bill'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Bill Number',
        required=True,
        copy=False,
        default='New',
        tracking=True,
    )
    requisition_id = fields.Many2one(
        'nn.fund.requisition',
        string='Requisition',
        required=True,
        ondelete='cascade',
        tracking=True,
    )
    amount = fields.Monetary(
        string='Amount',
        required=True,
        currency_field='currency_id',
        tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='requisition_id.currency_id',
        store=True,
    )
    date = fields.Date(
        string='Bill Date',
        required=True,
        default=fields.Date.today,
        tracking=True,
    )
    state = fields.Selection([
        ('draft',    'Draft'),
        ('posted',   'Posted'),
        ('cancelled','Cancelled'),
    ], string='Status',
       default='draft',
       tracking=True,
       copy=False,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'nn.fund.bill'
                ) or 'New'
            requisition = self.env['nn.fund.requisition'].browse(
                vals.get('requisition_id')
            )
            if requisition and requisition.state != 'approved':
                raise UserError(
                    "Bills can only be created against approved requisitions."
                )
        return super().create(vals_list)

    def write(self, vals):
        for rec in self:
            if rec.state == 'posted' and list(vals.keys()) != ['state']:
                raise UserError("Cannot modify a posted bill.")
            if rec.state == 'cancelled':
                raise UserError("Cannot modify a cancelled bill.")
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state in ('posted', 'cancelled'):
                raise UserError(
                    "Cannot delete a posted or cancelled bill."
                )
        return super().unlink()

    @api.constrains('amount')
    def _check_positive_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError("Bill amount must be greater than zero.")

    @api.constrains('amount', 'requisition_id')
    def _check_bill_under_remaining(self):
        for rec in self:
            if rec.state != 'draft':
                continue
            remaining = rec.requisition_id.remaining_billable
            new_total = sum(
                rec.requisition_id.bill_ids.filtered(
                    lambda b: b.state == 'draft' and b.id != rec.id
                ).mapped('amount')
            ) + rec.amount
            if new_total > rec.requisition_id.amount:
                raise ValidationError(
                    f"Total draft bill amount would exceed the approved "
                    f"amount ({rec.requisition_id.amount:,.2f})."
                )

    def action_post(self):
        for rec in self:
            if not self.env.user.has_group(
                'nn_fund_management.group_finance_user'
            ):
                raise UserError(
                    "Only a Finance User can post bills."
                )
            if rec.state != 'draft':
                raise UserError(
                    "Only draft bills can be posted."
                )
            remaining = rec.requisition_id.remaining_billable
            if rec.amount > remaining:
                raise ValidationError(
                    f"Bill amount ({rec.amount:,.2f}) exceeds "
                    f"remaining billable ({remaining:,.2f})."
                )
            rec.state = 'posted'
            rec.requisition_id.container_id.sudo()._compute_balances()
            rec.message_post(
                body=f"Bill posted by {rec.env.user.name}. "
                     f"Amount {rec.amount:,.2f}."
            )

    def action_cancel(self):
        for rec in self:
            if rec.state == 'posted':
                if not self.env.user.has_group(
                    'nn_fund_management.group_fund_admin'
                ):
                    raise UserError(
                        "Only an Administrator can cancel a posted bill."
                    )
            elif rec.state == 'draft':
                if not self.env.user.has_group(
                    'nn_fund_management.group_finance_user'
                ):
                    raise UserError(
                        "Only a Finance User can cancel a draft bill."
                    )
            elif rec.state == 'cancelled':
                raise UserError("Bill is already cancelled.")
            rec.state = 'cancelled'
            rec.requisition_id.sudo()._compute_bill_amounts()
            rec.requisition_id.container_id.sudo()._compute_balances()
            rec.message_post(
                body=f"Bill cancelled by {rec.env.user.name}."
            )
