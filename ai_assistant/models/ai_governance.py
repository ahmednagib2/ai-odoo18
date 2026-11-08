import json

from odoo import api, fields, models
from odoo.exceptions import UserError


class AiAuditLog(models.Model):
    _name = 'ai.audit.log'
    _description = 'AI Assistant Audit Log'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', string='User', default=lambda s: s.env.user, index=True)
    conversation_id = fields.Many2one('ai.conversation', string='Conversation', ondelete='set null')
    action = fields.Char(required=True, index=True)
    model_name = fields.Char(index=True)
    record_ids = fields.Text()
    domain = fields.Text()
    scope = fields.Char()
    status = fields.Selection([
        ('success', 'Success'),
        ('denied', 'Denied'),
        ('error', 'Error'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='success', index=True)
    details = fields.Text()
    duration = fields.Float(string='Duration (s)')
    create_date = fields.Datetime(string='Created On', index=True)

    @api.model
    def log_event(self, action, model_name=None, record_ids=None, domain=None,
                  scope=None, status='success', details=None, conversation_id=None, duration=None):
        vals = {
            'user_id': self.env.user.id,
            'action': (action or '')[:64],
            'model_name': model_name,
            'scope': scope,
            'status': status,
            'details': details,
            'conversation_id': conversation_id,
            'duration': duration,
        }
        if record_ids is not None:
            vals['record_ids'] = json.dumps(record_ids, default=str)
        if domain is not None:
            vals['domain'] = json.dumps(domain, default=str)
        return self.sudo().create(vals)


class AiFieldRule(models.Model):
    _name = 'ai.field.rule'
    _description = 'AI Assistant Field Permission'
    _order = 'model_id, field_name, tier'

    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade', string='Model')
    model_name = fields.Char(related='model_id.model', store=True)
    field_name = fields.Char(required=True, index=True)
    tier = fields.Selection([
        ('user', 'Employee (own data)'),
        ('team', 'Manager (team data)'),
        ('manager', 'General Manager'),
    ], required=True, default='user', index=True)
    action = fields.Selection([
        ('hide', 'Hide field'),
        ('mask', 'Mask value'),
    ], required=True, default='mask')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('field_rule_uniq', 'unique(model_id, field_name, tier)',
         'This field rule already exists for this model and access level.'),
    ]

    @api.model
    def get_rules(self, model_name, tier):
        tiers = {
            'user': ['user'],
            'team': ['user', 'team'],
            'manager': ['user', 'team', 'manager'],
        }
        return self.sudo().search([
            ('model_name', '=', model_name),
            ('tier', 'in', tiers.get(tier, [])),
            ('active', '=', True),
        ])


class AiTeamScope(models.Model):
    _name = 'ai.team.scope'
    _description = 'AI Assistant Team Scope'
    _order = 'manager_id'

    manager_id = fields.Many2one('res.users', required=True, ondelete='cascade', string='Manager')
    member_ids = fields.Many2many('res.users', string='Team Members')
    include_hierarchy = fields.Boolean(
        string='Include HR hierarchy',
        default=True,
        help='Also include employees reporting to this manager in the HR organization chart.')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('manager_uniq', 'unique(manager_id)', 'This user already has a team scope configuration.'),
    ]

    @api.model
    def get_team_user_ids(self, manager_id):
        rec = self.sudo().search([('manager_id', '=', manager_id), ('active', '=', True)], limit=1)
        if not rec:
            return []
        users = set(rec.member_ids.ids)
        if rec.include_hierarchy and 'hr.employee' in self.env:
            Employee = self.env['hr.employee']
            employee = Employee.search([('user_id', '=', manager_id)], limit=1)
            if employee:
                subordinates = Employee.search([('parent_id', 'child_of', employee.ids)])
                users.update(subordinates.mapped('user_id').ids)
        return list(users)


class AiElevatedAccess(models.Model):
    _name = 'ai.elevated.access'
    _description = 'AI Assistant Temporary Elevated Access'
    _order = 'date_start desc'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', string='User')
    tier = fields.Selection([
        ('team', 'Team Leader'),
        ('manager', 'General Manager'),
    ], required=True, default='team')
    date_start = fields.Datetime(required=True, default=fields.Datetime.now)
    date_end = fields.Datetime(required=True)
    reason = fields.Text()
    active = fields.Boolean(default=True)

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_end <= rec.date_start:
                raise UserError('End date must be after start date.')

    @api.model
    def get_active_tier(self, user_id):
        now = fields.Datetime.now()
        grants = self.sudo().search([
            ('user_id', '=', user_id),
            ('active', '=', True),
            ('date_start', '<=', now),
            ('date_end', '>', now),
        ])
        if any(g.tier == 'manager' for g in grants):
            return 'manager'
        if any(g.tier == 'team' for g in grants):
            return 'team'
        return False

    @api.model
    def _cron_expire(self):
        """Deactivate elevated-access grants whose end date has passed."""
        now = fields.Datetime.now()
        expired = self.sudo().search([
            ('active', '=', True),
            ('date_end', '<=', now),
        ])
        expired.write({'active': False})
        return True


class AiQuota(models.Model):
    _name = 'ai.quota'
    _description = 'AI Assistant Usage Quota'
    _order = 'id'

    name = fields.Char(required=True)
    user_id = fields.Many2one('res.users', string='User', ondelete='cascade')
    target = fields.Selection([
        ('user', 'Specific user'),
        ('group', 'Access level'),
    ], required=True, default='user')
    access_tier = fields.Selection([
        ('user', 'Employee'),
        ('team', 'Manager'),
        ('manager', 'General Manager'),
    ])
    period = fields.Selection([
        ('day', 'Per day'),
        ('month', 'Per month'),
    ], required=True, default='day')
    max_requests = fields.Integer(required=True, default=100)
    active = fields.Boolean(default=True)

    @api.model
    def check_quota(self):
        user = self.env.user
        tier = self.env['ai.assistant']._ai_tier()
        rules = self.sudo().search([
            ('active', '=', True),
            '|', ('user_id', '=', user.id),
            '&', ('target', '=', 'group'), ('access_tier', '=', tier),
        ])
        for rule in rules:
            if rule.target == 'user' and rule.user_id.id != user.id:
                continue
            if rule.target == 'group' and rule.access_tier != tier:
                continue
            start = fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            if rule.period == 'month':
                start = start.replace(day=1)
            used = self.env['ai.audit.log'].sudo().search_count([
                ('user_id', '=', user.id),
                ('create_date', '>=', start),
                ('action', '=', 'chat'),
            ])
            if used >= rule.max_requests:
                raise UserError(
                    'AI usage limit reached (%s requests per %s). Please try again later.'
                    % (rule.max_requests, rule.period))


class AiApprovalRule(models.Model):
    _name = 'ai.approval.rule'
    _description = 'AI Assistant Approval Matrix'
    _order = 'model_id, kind'

    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade', string='Model')
    model_name = fields.Char(related='model_id.model', store=True)
    kind = fields.Selection([
        ('write', 'Update'),
        ('call', 'Workflow'),
    ], required=True, default='write')
    requires_manager_approval = fields.Boolean(string='Manager approval required', default=False)
    amount_field = fields.Char(
        string='Amount field',
        help='Optional numeric field used to compare against the approval threshold.')
    threshold = fields.Float(string='Threshold')
    approver_id = fields.Many2one('res.users', string='Approver')

    _sql_constraints = [
        ('approval_rule_uniq', 'unique(model_id, kind)', 'This approval rule already exists for this model.'),
    ]

    @api.model
    def get_rule(self, model_name, kind):
        return self.sudo().search([
            ('model_name', '=', model_name),
            ('kind', '=', kind),
        ], limit=1)

    def needs_approval(self, values=None):
        self.ensure_one()
        if not self.requires_manager_approval:
            return False
        if not self.amount_field or self.amount_field not in (values or {}):
            return True
        try:
            amount = float(values.get(self.amount_field) or 0)
        except (TypeError, ValueError):
            return True
        return amount >= self.threshold
