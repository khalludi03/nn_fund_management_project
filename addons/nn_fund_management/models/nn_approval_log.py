from odoo import fields, models


class NnApprovalLog(models.Model):
    _name = 'nn.approval.log'
    _description = 'Approval Log'
    _order = 'date desc'

    allocation_id = fields.Many2one(
        'nn.fund.allocation',
        string='Allocation',
        ondelete='cascade',
    )
    requisition_id = fields.Many2one(
        'nn.fund.requisition',
        string='Requisition',
        ondelete='cascade',
    )
    transfer_id = fields.Many2one(
        'nn.fund.transfer',
        string='Transfer',
        ondelete='cascade',
    )
    approver_id = fields.Many2one(
        'res.users',
        string='Approver',
        required=True,
    )
    level = fields.Selection([
        ('gm', 'General Manager'),
        ('md', 'Managing Director'),
    ], string='Approval Level',
       required=True,
    )
    action = fields.Selection([
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Action',
       required=True,
    )
    comment = fields.Text(string='Comment')
    date = fields.Datetime(
        string='Date',
        default=fields.Datetime.now,
    )