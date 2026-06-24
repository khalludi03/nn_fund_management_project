from odoo import fields, models


class NnApprovalConfig(models.Model):
    _name = 'nn.approval.config'
    _description = 'Approval Configuration'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    gm_user_id = fields.Many2one(
        'res.users',
        string='General Manager',
        required=True,
    )
    md_user_id = fields.Many2one(
        'res.users',
        string='Managing Director',
        required=True,
    )