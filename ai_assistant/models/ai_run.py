from odoo import fields, models


class AiRun(models.Model):
    """One row per user holding what the assistant is doing right now.

    It is written from a separate cursor (committed immediately) so the browser can read it
    while the long chat request is still running.
    """
    _name = 'ai.run'
    _description = 'AI live status (per user)'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    status = fields.Char()

    _sql_constraints = [('user_uniq', 'unique(user_id)', 'One status row per user.')]
