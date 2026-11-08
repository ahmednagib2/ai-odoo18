from odoo import fields, models


class AiConversation(models.Model):
    _name = 'ai.conversation'
    _description = 'محادثة المساعد الذكي'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', string='المستخدم', required=True,
                              default=lambda s: s.env.user, index=True)
    active = fields.Boolean(string='نشط', default=True)
    message_ids = fields.One2many('ai.message', 'conversation_id', string='الرسائل')


class AiMessage(models.Model):
    _name = 'ai.message'
    _description = 'رسالة المساعد الذكي'
    _order = 'id'

    conversation_id = fields.Many2one('ai.conversation', string='المحادثة', required=True,
                                      ondelete='cascade', index=True)
    role = fields.Selection([('user', 'المستخدم'), ('assistant', 'المساعد')], string='الدور', required=True)
    content = fields.Text(string='المحتوى')
    pending_id = fields.Many2one('ai.pending.action', string='الإجراء المعلّق', ondelete='set null')
