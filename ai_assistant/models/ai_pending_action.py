import json

from odoo import fields, models
from odoo.exceptions import UserError
from odoo.osv import expression

from .ai_utils import clean_values

# هذه الأزرار فقط هي التي يمكن تشغيلها (دائماً بعد موافقة المستخدم الصريحة).
# لا شيء هنا يحذف سجلات. الإلغاء وإعادة المسودة يغيّران حالة المستند فقط.
WORKFLOWS = {
    'sale.order': ['action_confirm', 'action_cancel', 'action_draft', 'create_invoice'],
    'purchase.order': ['button_confirm', 'button_cancel', 'button_draft', 'action_create_invoice'],
    'account.move': ['action_post', 'button_draft', 'button_cancel', 'register_payment'],
    'stock.picking': ['button_validate', 'action_cancel'],
    'crm.lead': ['action_set_won'],
    'hr.leave': ['action_approve', 'action_refuse'],
}
# معاملات اختيارية تقبلها بعض الدوال الخاصة
PARAMS = {
    'register_payment': ('amount', 'journal_id', 'payment_date', 'communication'),
}


class AiPendingAction(models.Model):
    _name = 'ai.pending.action'
    _description = 'إجراء مقترح من المساعد الذكي (يحتاج موافقة المستخدم) وسجل التدقيق'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', string='المستخدم', required=True, default=lambda s: s.env.user)
    kind = fields.Selection([('create', 'إنشاء'), ('write', 'تعديل'), ('call', 'سير عمل')],
                            string='النوع', required=True)
    model_name = fields.Char(string='النموذج')
    summary = fields.Char(string='الملخص')
    payload = fields.Text(string='البيانات', required=True)
    state = fields.Selection([
        ('pending', 'معلّق'), ('awaiting_approval', 'بانتظار الموافقة'),
        ('done', 'تم'), ('cancelled', 'ملغي'), ('failed', 'فشل')],
        string='الحالة', default='pending', index=True)
    result = fields.Text(string='النتيجة')

    def _scoped_records(self, Model, scope, ids):
        """إرجاع السجلات المطلوبة بشرط وقوعها ضمن نطاق صلاحيات المستخدم."""
        ids = [int(i) for i in (ids or [])]
        if not ids:
            raise UserError('لم يتم تحديد أي سجلات.')
        recs = Model.search(expression.AND([[('id', 'in', ids)], list(scope or [])]))
        if len(recs) != len(set(ids)):
            raise UserError('بعض السجلات غير موجودة أو خارج نطاق صلاحياتك.')
        return recs

    def _register_payment(self, moves, params):
        vals = {}
        if params.get('amount'):
            amount = float(params['amount'])
            if amount <= 0:
                raise UserError('يجب أن يكون مبلغ الدفعة أكبر من صفر.')
            vals['amount'] = amount
        if params.get('journal_id'):
            vals['journal_id'] = int(params['journal_id'])
        if params.get('payment_date'):
            vals['payment_date'] = str(params['payment_date'])
        if params.get('communication'):
            vals['communication'] = str(params['communication'])[:200]
        wizard = moves.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=moves.ids).create(vals)
        return wizard.action_create_payments()

    def action_execute(self):
        self.ensure_one()
        if self.user_id != self.env.user or self.state != 'pending':
            raise UserError('لا يمكن تنفيذ هذا الإجراء.')
        p = json.loads(self.payload)
        model = p['model']
        assistant = self.env['ai.assistant']
        rule = assistant._check(model, {'create': 'create', 'write': 'write', 'call': 'call'}[self.kind])
        scope = assistant._scope_domain(self.env[model], rule)
        Model = self.env(su=False)[model]
        action = None
        try:
            with self.env.cr.savepoint():
                if self.kind == 'create':
                    rec = Model.create(clean_values(Model, p['values']))
                    msg = 'تم إنشاء %s رقم %s (%s)' % (model, rec.id, rec.display_name)
                elif self.kind == 'write':
                    recs = self._scoped_records(Model, scope, p['ids'])
                    recs.write(clean_values(Model, p['values']))
                    msg = 'تم تعديل %s: %s' % (model, '، '.join(recs.mapped('display_name')))
                else:
                    method = p['method']
                    if method not in WORKFLOWS.get(model, []):
                        raise UserError('هذه الدالة غير مسموح بها.')
                    recs = self._scoped_records(Model, scope, p['ids'])
                    if method == 'create_invoice':
                        res = recs._create_invoices()
                    elif method == 'register_payment':
                        res = self._register_payment(recs, p.get('params') or {})
                    else:
                        res = getattr(recs, method)()
                    names = '، '.join(recs.mapped('display_name'))
                    if isinstance(res, dict) and res.get('type'):
                        action = json.loads(json.dumps(res, default=str))
                        msg = 'يلزم إدخال بيانات إضافية لإكمال العملية: فتحت لك النافذة الخاصة بـ %s.' % names
                    elif isinstance(res, models.BaseModel) and res:
                        msg = 'تم تنفيذ (%s) على %s. النتيجة: %s' % (method, names, '، '.join(res.mapped('display_name')))
                    else:
                        msg = 'تم تنفيذ (%s) على %s' % (method, names)
        except Exception as e:
            err = e.args[0] if e.args else str(e)
            self.write({'state': 'failed', 'result': str(err)})
            raise UserError('فشل التنفيذ: %s' % err)
        self.write({'state': 'done', 'result': msg})
        return {'message': msg, 'action': action}

    def action_cancel(self):
        self.ensure_one()
        if self.user_id == self.env.user and self.state == 'pending':
            self.state = 'cancelled'
