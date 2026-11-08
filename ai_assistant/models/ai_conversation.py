from odoo import fields, models


class AiConversation(models.Model):
    _name = 'ai.conversation'
    _description = 'AI conversation'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', required=True, default=lambda s: s.env.user, index=True)
    active = fields.Boolean(default=True)
    message_ids = fields.One2many('ai.message', 'conversation_id')


class AiMessage(models.Model):
    _name = 'ai.message'
    _description = 'AI message'
    _order = 'id'

    conversation_id = fields.Many2one('ai.conversation', required=True, ondelete='cascade', index=True)
    role = fields.Selection([('user', 'User'), ('assistant', 'Assistant')], required=True)
    content = fields.Text()
    pending_id = fields.Many2one('ai.pending.action', ondelete='set null')
