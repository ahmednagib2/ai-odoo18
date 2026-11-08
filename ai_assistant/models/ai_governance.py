import json

from odoo import api, fields, models
from odoo.exceptions import UserError


class AiAuditLog(models.Model):
    _name = 'ai.audit.log'
    _description = 'سجل تدقيق المساعد الذكي'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', string='المستخدم', default=lambda s: s.env.user, index=True)
    conversation_id = fields.Many2one('ai.conversation', string='المحادثة', ondelete='set null')
    action = fields.Char(string='الإجراء', required=True, index=True)
    model_name = fields.Char(string='النموذج', index=True)
    record_ids = fields.Text(string='السجلات')
    domain = fields.Text(string='الشرط (Domain)')
    scope = fields.Char(string='النطاق')
    status = fields.Selection([
        ('success', 'نجح'),
        ('denied', 'مرفوض'),
        ('error', 'خطأ'),
        ('pending', 'معلّق'),
        ('approved', 'تمت الموافقة'),
        ('rejected', 'مرفوض من المعتمد'),
    ], string='الحالة', default='success', index=True)
    details = fields.Text(string='التفاصيل')
    duration = fields.Float(string='المدة (ثانية)')
    create_date = fields.Datetime(string='تاريخ الإنشاء', index=True)

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
    _description = 'صلاحية حقل للمساعد الذكي'
    _order = 'model_id, field_name, tier'

    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade', string='النموذج')
    model_name = fields.Char(string='الاسم التقني للنموذج', related='model_id.model', store=True)
    field_name = fields.Char(string='اسم الحقل', required=True, index=True)
    tier = fields.Selection([
        ('user', 'موظف (بياناته فقط)'),
        ('team', 'مدير (بيانات الفريق)'),
        ('manager', 'مدير عام'),
    ], string='المستوى', required=True, default='user', index=True)
    action = fields.Selection([
        ('hide', 'إخفاء الحقل'),
        ('mask', 'تعتيم القيمة'),
    ], string='الإجراء', required=True, default='mask')
    active = fields.Boolean(string='نشط', default=True)

    _sql_constraints = [
        ('field_rule_uniq', 'unique(model_id, field_name, tier)',
         'قاعدة هذا الحقل موجودة مسبقاً لهذا النموذج ولهذا المستوى.'),
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
    _description = 'نطاق فريق المساعد الذكي'
    _order = 'manager_id'

    manager_id = fields.Many2one('res.users', required=True, ondelete='cascade', string='المدير')
    member_ids = fields.Many2many('res.users', string='أعضاء الفريق')
    include_hierarchy = fields.Boolean(
        string='تضمين الهيكل الإداري (HR)',
        default=True,
        help='إضافة الموظفين التابعين لهذا المدير في الهيكل التنظيمي للموارد البشرية.')
    active = fields.Boolean(string='نشط', default=True)

    _sql_constraints = [
        ('manager_uniq', 'unique(manager_id)', 'هذا المستخدم لديه إعداد نطاق فريق مسبقاً.'),
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
    _description = 'صلاحية مرتفعة مؤقتة للمساعد الذكي'
    _order = 'date_start desc'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', string='المستخدم')
    tier = fields.Selection([
        ('team', 'قائد فريق'),
        ('manager', 'مدير عام'),
    ], string='المستوى', required=True, default='team')
    date_start = fields.Datetime(string='من تاريخ', required=True, default=fields.Datetime.now)
    date_end = fields.Datetime(string='إلى تاريخ', required=True)
    reason = fields.Text(string='السبب')
    active = fields.Boolean(string='نشط', default=True)

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_end <= rec.date_start:
                raise UserError('يجب أن يكون تاريخ النهاية بعد تاريخ البداية.')

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
        """إيقاف الصلاحيات المرتفعة التي انتهى تاريخها."""
        now = fields.Datetime.now()
        expired = self.sudo().search([
            ('active', '=', True),
            ('date_end', '<=', now),
        ])
        expired.write({'active': False})
        return True


class AiQuota(models.Model):
    _name = 'ai.quota'
    _description = 'حصة استخدام المساعد الذكي'
    _order = 'id'

    name = fields.Char(string='الاسم', required=True)
    user_id = fields.Many2one('res.users', string='المستخدم', ondelete='cascade')
    target = fields.Selection([
        ('user', 'مستخدم محدد'),
        ('group', 'مستوى صلاحية'),
    ], string='ينطبق على', required=True, default='user')
    access_tier = fields.Selection([
        ('user', 'موظف'),
        ('team', 'مدير'),
        ('manager', 'مدير عام'),
    ], string='مستوى الصلاحية')
    period = fields.Selection([
        ('day', 'يومياً'),
        ('month', 'شهرياً'),
    ], string='الفترة', required=True, default='day')
    max_requests = fields.Integer(string='أقصى عدد طلبات', required=True, default=100)
    active = fields.Boolean(string='نشط', default=True)

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
                    'وصلت للحد الأقصى لاستخدام المساعد الذكي (%s طلب %s). حاول لاحقاً.'
                    % (rule.max_requests, 'يومياً' if rule.period == 'day' else 'شهرياً'))


class AiApprovalRule(models.Model):
    _name = 'ai.approval.rule'
    _description = 'قاعدة موافقة المساعد الذكي'
    _order = 'model_id, kind'

    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade', string='النموذج')
    model_name = fields.Char(string='الاسم التقني للنموذج', related='model_id.model', store=True)
    kind = fields.Selection([
        ('write', 'تعديل'),
        ('call', 'سير عمل'),
    ], string='نوع الإجراء', required=True, default='write')
    requires_manager_approval = fields.Boolean(string='تتطلب موافقة المدير', default=False)
    amount_field = fields.Char(
        string='حقل المبلغ',
        help='حقل رقمي اختياري تتم مقارنته بحد الموافقة.')
    threshold = fields.Float(string='حد الموافقة')
    approver_id = fields.Many2one('res.users', string='المعتمد')

    _sql_constraints = [
        ('approval_rule_uniq', 'unique(model_id, kind)', 'قاعدة الموافقة هذه موجودة مسبقاً لهذا النموذج.'),
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
