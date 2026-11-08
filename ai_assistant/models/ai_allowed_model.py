from odoo import api, fields, models
from odoo.exceptions import UserError

# النموذج -> (مسار حقل المالك، بيانات مشتركة). حقل المالك هو المسار (على ذلك النموذج) إلى
# المستخدم (res.users) المالك للسجل، ويُستخدم لتحديد ما يراه مستوى "بياناتي فقط" ومستوى "الفريق".
DEFAULT_SCOPES = {
    'sale.order': ('user_id', False),
    'sale.order.line': ('salesman_id', False),
    'crm.lead': ('user_id', False),
    'account.move': ('invoice_user_id', False),
    'account.move.line': ('move_id.invoice_user_id', False),
    'account.payment': ('create_uid', False),
    'purchase.order': ('user_id', False),
    'purchase.order.line': ('order_id.user_id', False),
    'stock.picking': ('user_id', False),
    'stock.move': ('picking_id.user_id', False),
    'stock.quant': ('', True),
    'product.template': ('', True),
    'product.product': ('', True),
    'res.partner': ('user_id', False),
    'project.task': ('user_ids', False),
    'hr.employee': ('user_id', False),
    'hr.leave': ('employee_id.user_id', False),
    'hr.attendance': ('employee_id.user_id', False),
    'account.analytic.line': ('user_id', False),
    'helpdesk.ticket': ('user_id', False),
    'pos.order': ('user_id', False),
    'pos.session': ('user_id', False),
    'pos.order.line': ('order_id.user_id', False),
}


class AiAllowedModel(models.Model):
    _name = 'ai.allowed.model'
    _description = 'النماذج المسموح للمساعد الذكي بالوصول إليها'

    model_id = fields.Many2one('ir.model', string='النموذج', required=True, ondelete='cascade')
    model_name = fields.Char(string='الاسم التقني', related='model_id.model', store=True)
    perm_read = fields.Boolean('قراءة', default=True)
    perm_create = fields.Boolean('إنشاء', default=False)
    perm_write = fields.Boolean('تعديل', default=False)
    perm_call = fields.Boolean('أزرار سير العمل', default=False,
                               help='السماح بأزرار محددة مسبقاً (تأكيد الطلب، ترحيل الفاتورة...) بعد موافقة المستخدم.')
    perm_draft = fields.Boolean('نموذج مسودة', default=False,
                                help='يستطيع المساعد فتح نموذج جديد من هذا النموذج معبّأً بالبيانات. '
                                     'لا يتم حفظ أي شيء: يراجع المستخدم النموذج ويحفظه بنفسه.')
    owner_field = fields.Char(
        'حقل المالك',
        help='مسار الحقل الذي يشير إلى مالك السجل (مثل user_id أو invoice_user_id أو employee_id.user_id). '
             'مستخدمو مستوى "بياناتي فقط" يرون السجلات التي هم مالكوها فقط، وقادة الفرق يرون سجلاتهم وسجلات فريقهم. '
             'اتركه فارغاً مع عدم تفعيل "بيانات مشتركة" لإخفاء النموذج عن هذه المستويات.')
    shared_data = fields.Boolean(
        'بيانات مشتركة', default=False,
        help='بيانات واحدة للجميع (المنتجات، أرصدة المخزون...). يستطيع مستوى "بياناتي فقط" ومستوى "الفريق" قراءتها دون فلتر مالك.')
    max_records = fields.Integer('أقصى عدد سجلات لكل استعلام', default=30)

    _sql_constraints = [('model_uniq', 'unique(model_id)', 'هذا النموذج مُعدّ مسبقاً.')]

    @api.constrains('model_id', 'owner_field')
    def _check_owner_field(self):
        """التأكد من أن مسار حقل المالك موجود في النموذج المختار."""
        for rec in self:
            if not rec.owner_field:
                continue
            Model = self.env.get(rec.model_name)
            if not Model:
                continue
            parts = rec.owner_field.split('.')
            cursor = Model
            for part in parts:
                if part not in cursor._fields:
                    raise UserError(
                        'مسار الحقل "%s" غير موجود في النموذج %s.'
                        % (rec.owner_field, rec.model_name)
                    )
                cursor = self.env[cursor._fields[part].comodel_name]

    @api.model
    def _apply_default_scopes(self):
        """تعبئة حقل المالك والبيانات المشتركة للسجلات التي ليس لها نطاق بعد."""
        for rec in self.search([]):
            if rec.owner_field or rec.shared_data:
                continue
            scope = DEFAULT_SCOPES.get(rec.model_name)
            if scope:
                rec.write({'owner_field': scope[0], 'shared_data': scope[1]})
