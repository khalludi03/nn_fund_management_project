from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError


class NnApprovalMixin(models.AbstractModel):
    _name = 'nn.approval.mixin'
    _description = 'Approval Workflow Mixin'

    @api.constrains('amount')
    def _check_positive_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError("Amount must be greater than zero.")

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

    def _get_balance_source(self):
        raise NotImplementedError

    def _get_approval_log_vals(self, level, action):
        raise NotImplementedError

    def _check_submit_balance(self):
        pass

    def _on_submit(self):
        pass

    def _on_gm_approve(self):
        pass

    def _on_md_approve(self):
        pass

    def _on_reject(self):
        pass

    def _on_cancel(self):
        pass

    def _get_cancel_checks(self):
        return {}

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError("Only draft records can be submitted.")
            if rec.env.user != rec.requested_by and not rec.env.user.has_group(
                'nn_fund_management.group_finance_user'
            ):
                raise UserError(
                    "Only the requester or a Finance User can submit."
                )
            rec._check_submit_balance()
            rec.state = 'submitted'
            rec._get_balance_source().sudo()._compute_balances()
            rec._on_submit()

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
                    "You cannot approve your own request."
                )
            self.env['nn.approval.log'].create(
                rec._get_approval_log_vals('gm', 'approved')
            )
            rec.state = 'gm_approved'
            rec._on_gm_approve()

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
                    "You cannot approve your own request."
                )
            self.env['nn.approval.log'].create(
                rec._get_approval_log_vals('md', 'approved')
            )
            rec.state = 'approved'
            rec._on_md_approve()

    def action_reject(self):
        for rec in self:
            if rec.state not in ('submitted', 'gm_approved'):
                raise UserError(
                    "Rejection is only allowed in "
                    "Submitted or GM Approved state."
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
            self.env['nn.approval.log'].create(
                rec._get_approval_log_vals(level, 'rejected')
            )
            rec.state = 'rejected'
            rec._get_balance_source().sudo()._compute_balances()
            rec._on_reject()

    def action_cancel(self):
        for rec in self:
            cancel_checks = rec._get_cancel_checks()
            if cancel_checks.get('requester_or_finance'):
                if rec.state in cancel_checks['requester_or_finance']:
                    if rec.env.user != rec.requested_by and \
                       not rec.env.user.has_group(
                        'nn_fund_management.group_finance_user'
                    ):
                        raise UserError(
                            "Only the requester or a Finance User "
                            "can cancel this request."
                        )
            if cancel_checks.get('admin_only'):
                if rec.state in cancel_checks['admin_only']:
                    if not self.env.user.has_group(
                        'nn_fund_management.group_fund_admin'
                    ):
                        raise UserError(
                            "Only an Administrator can cancel "
                            "an approved request."
                        )
            if cancel_checks.get('blocked'):
                if rec.state in cancel_checks['blocked']:
                    raise UserError("Cannot cancel in this state.")
            rec.state = 'cancelled'
            rec._get_balance_source().sudo()._compute_balances()
            rec._on_cancel()
