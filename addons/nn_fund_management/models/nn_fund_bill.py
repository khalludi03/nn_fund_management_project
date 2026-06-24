from odoo import fields, models


class NnFundBill(models.Model):
    _name = 'nn.fund.bill'
    _description = 'Fund Bill'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Bill Number', required=True, copy=False, default='New')
    requisition_id = fields.Many2one(
        'nn.fund.requisition',
        string='Requisition',
        required=True,
        ondelete='cascade',
    )
    amount = fields.Monetary(string='Amount', required=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', related='requisition_id.currency_id', store=True)
    date = fields.Date(string='Bill Date', required=True, default=fields.Date.today)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                  default=lambda self: self.env.company)
