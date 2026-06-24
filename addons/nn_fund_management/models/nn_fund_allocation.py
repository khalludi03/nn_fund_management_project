from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError


class NnFundAllocation(models.Model):
    _name = 'nn.fund.allocation'
    _description = 'Fund Allocation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'request_date desc, id desc'

    # ── Basic Fields ─────────────────────────────────────
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

    # ── State ────────────────────────────────────────────
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

    # ── Approval Log ─────────────────────────────────────
    approval_log_ids = fields.One2many(
        'nn.approval.log',
        'allocation_id',
        string='Approval History',
        readonly=True,
    )

    # ── Computed: current approver info ──────────────────
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

    # ── Sequence ─────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'nn.fund.allocation'
                ) or 'New'
        return super().create(vals_list)

    # ── Compute Approvers ────────────────────────────────
    def _compute_approvers(self):
        """
        Company অনুযায়ী configured approver খুঁজে বের করো
        """
        for rec in self:
            config = self.env['nn.approval.config'].search([
                ('company_id', '=', rec.company_id.id)
            ], limit=1)
            rec.gm_user_id = config.gm_user_id if config else False
            rec.md_user_id = config.md_user_id if config else False

    # ── Constraints ──────────────────────────────────────
    @api.constrains('amount')
    def _check_positive_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(
                    "Amount অবশ্যই শূন্যের বেশি হতে হবে।"
                )

    # ── Helper: get approval config ──────────────────────
    def _get_approval_config(self):
        config = self.env['nn.approval.config'].search([
            ('company_id', '=', self.company_id.id)
        ], limit=1)
        if not config:
            raise UserError(
                "Approval configuration পাওয়া যায়নি। "
                "Configuration মেনু থেকে GM ও MD সেট করুন।"
            )
        return config

    # ── Action: Submit ───────────────────────────────────
    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError("শুধু Draft record submit করা যাবে।")

            # ── Balance Check ────────────────────────────
            available = rec.fund_account_id.available_unassigned_balance
            if rec.amount > available:
                raise ValidationError(
                    f"পর্যাপ্ত balance নেই!\n"
                    f"Available: {available:,.2f}\n"
                    f"Requested: {rec.amount:,.2f}"
                )

            rec.state = 'submitted'
            # balance recompute — amount hold এ যাবে
            rec.fund_account_id._compute_balances()
            rec.message_post(
                body=f"Request submitted by {rec.env.user.name}."
            )

    # ── Action: GM Approve ───────────────────────────────
    def action_gm_approve(self):
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(
                    "Submitted অবস্থায় GM approve করা যাবে।"
                )

            config = rec._get_approval_config()

            # ── Approver Check ───────────────────────────
            if rec.env.user != config.gm_user_id:
                raise UserError(
                    "শুধু configured GM এই request approve করতে পারবেন।"
                )

            # ── নিজের request নিজে approve করা যাবে না ──
            if rec.requested_by == rec.env.user:
                raise UserError(
                    "নিজের allocation request নিজে approve করা যাবে না।"
                )

            # ── Log ──────────────────────────────────────
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

    # ── Action: MD Approve ───────────────────────────────
    def action_md_approve(self):
        for rec in self:
            if rec.state != 'gm_approved':
                raise UserError(
                    "GM approval এর পরে MD approve করা যাবে।"
                )

            config = rec._get_approval_config()

            # ── Approver Check ───────────────────────────
            if rec.env.user != config.md_user_id:
                raise UserError(
                    "শুধু configured MD এই request approve করতে পারবেন।"
                )

            # ── নিজের request নিজে approve করা যাবে না ──
            if rec.requested_by == rec.env.user:
                raise UserError(
                    "নিজের allocation request নিজে approve করা যাবে না।"
                )

            # ── Log ──────────────────────────────────────
            self.env['nn.approval.log'].create({
                'allocation_id': rec.id,
                'approver_id':   rec.env.user.id,
                'level':         'md',
                'action':        'approved',
                'date':          fields.Datetime.now(),
            })

            rec.state = 'approved'

            # ── Balance Update ───────────────────────────
            # hold থেকে assigned এ যাবে
            # container এ total_allocated বাড়বে
            rec.fund_account_id._compute_balances()
            rec.container_id._compute_balances()

            rec.message_post(
                body=f"MD approved by {rec.env.user.name}. "
                     f"Amount {rec.amount:,.2f} allocated to "
                     f"{rec.container_id.name}."
            )

    # ── Action: Reject ───────────────────────────────────
    def action_reject(self):
        for rec in self:
            if rec.state not in ('submitted', 'gm_approved'):
                raise UserError(
                    "Submitted বা GM Approved অবস্থায় reject করা যাবে।"
                )

            config = rec._get_approval_config()
            current_user = rec.env.user

            # ── কে reject করতে পারবে ────────────────────
            if rec.state == 'submitted':
                if current_user != config.gm_user_id:
                    raise UserError(
                        "এই পর্যায়ে শুধু GM reject করতে পারবেন।"
                    )
                level = 'gm'
            else:
                if current_user != config.md_user_id:
                    raise UserError(
                        "এই পর্যায়ে শুধু MD reject করতে পারবেন।"
                    )
                level = 'md'

            # ── Log ──────────────────────────────────────
            self.env['nn.approval.log'].create({
                'allocation_id': rec.id,
                'approver_id':   current_user.id,
                'level':         level,
                'action':        'rejected',
                'date':          fields.Datetime.now(),
            })

            rec.state = 'rejected'

            # ── Balance Restore ──────────────────────────
            # hold থেকে unassigned এ ফিরে আসবে
            rec.fund_account_id._compute_balances()
            rec.message_post(
                body=f"Rejected by {current_user.name}. "
                     f"Amount {rec.amount:,.2f} returned to "
                     f"unassigned balance."
            )

    # ── Action: Cancel ───────────────────────────────────
    def action_cancel(self):
        for rec in self:
            if rec.state == 'approved':
                if not self.env.user.has_group(
                    'nn_fund_management.group_fund_admin'
                ):
                    raise UserError(
                        "Approved allocation শুধু Administrator "
                        "cancel করতে পারবে।"
                    )
            if rec.state in ('rejected', 'cancelled'):
                raise UserError(
                    "Rejected বা Cancelled record আর cancel করা যাবে না।"
                )
            rec.state = 'cancelled'
            rec.fund_account_id._compute_balances()
            rec.message_post(
                body=f"Cancelled by {rec.env.user.name}."
            )