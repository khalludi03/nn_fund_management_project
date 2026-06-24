from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError


class NnIncomingFund(models.Model):
    _name = 'nn.incoming.fund'
    _description = 'Incoming Fund'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    # ── Basic Fields ─────────────────────────────────────
    name = fields.Char(
        string='Reference',
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
    )
    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.today,
        tracking=True,
    )
    amount = fields.Monetary(
        string='Amount',
        required=True,
        tracking=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='fund_account_id.currency_id',
        store=True,
    )
    transaction_ref = fields.Char(
        string='Transaction Reference',
        required=True,
        tracking=True,
    )
    sender = fields.Char(
        string='Sender / Source',
        required=True,
    )
    description = fields.Text(string='Description')
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
        ('draft',     'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ], string='Status',
       default='draft',
       tracking=True,
       copy=False,
    )

    # ── Sequence ─────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'nn.incoming.fund'
                ) or 'New'
        return super().create(vals_list)

    # ── Constraints ──────────────────────────────────────
    @api.constrains('transaction_ref', 'fund_account_id')
    def _check_unique_transaction_ref(self):
        """একই fund account এ same transaction ref দুইবার চলবে না"""
        for rec in self:
            duplicate = self.search([
                ('transaction_ref', '=', rec.transaction_ref),
                ('fund_account_id', '=', rec.fund_account_id.id),
                ('state', '!=', 'cancelled'),
                ('id', '!=', rec.id),
            ])
            if duplicate:
                raise ValidationError(
                    f"Transaction reference '{rec.transaction_ref}' "
                    f"already exists in account "
                    f"'{rec.fund_account_id.name}'."
                )

    @api.constrains('amount')
    def _check_positive_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError("Amount অবশ্যই শূন্যের বেশি হতে হবে।")

    # ── Actions ──────────────────────────────────────────
    def action_confirm(self):
        """Finance user confirm করলে unassigned balance বাড়বে"""
        for rec in self:
            if not self.env.user.has_group(
                'nn_fund_management.group_finance_user'
            ):
                raise UserError(
                    "শুধু Finance User incoming fund confirm করতে পারবে।"
                )
            if rec.state != 'draft':
                raise ValidationError("শুধু Draft record confirm করা যাবে।")
            rec.state = 'confirmed'
            rec.fund_account_id._compute_balances()

    def action_cancel(self):
        for rec in self:
            if rec.state == 'confirmed':
                raise ValidationError(
                    "Confirmed fund cancel করতে পারবে না। "
                    "Reversal entry করো।"
                )
            rec.state = 'cancelled'