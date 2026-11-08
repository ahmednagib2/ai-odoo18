from odoo import fields, models


class AiRun(models.Model):
    """سجل واحد لكل مستخدم يحمل ما يفعله المساعد الآن.

    يُكتب بمؤشر قاعدة بيانات منفصل (يُحفظ فوراً) ليقرأه المتصفح أثناء استمرار طلب المحادثة الطويل.
    """
    _name = 'ai.run'
    _description = 'الحالة الحية للمساعد الذكي (لكل مستخدم)'

    user_id = fields.Many2one('res.users', string='المستخدم', required=True, ondelete='cascade', index=True)
    status = fields.Char(string='الحالة')

    _sql_constraints = [('user_uniq', 'unique(user_id)', 'يوجد سجل حالة واحد فقط لكل مستخدم.')]
