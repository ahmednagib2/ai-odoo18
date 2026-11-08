import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class AiAssistantController(http.Controller):

    def _engine(self):
        return request.env['ai.assistant']

    @http.route('/ai_assistant/me', type='json', auth='user')
    def me(self, **kw):
        try:
            allowed = bool(self._engine()._has_access())
        except Exception:
            _logger.exception('AI Assistant: access check failed')
            allowed = False
        return {'allowed': allowed, 'name': request.env.user.name or ''}

    @http.route('/ai_assistant/providers', type='json', auth='user')
    def providers(self, **kw):
        if not self._engine()._has_access():
            return []
        recs = request.env['ai.provider'].sudo().search([('active', '=', True)])
        return [{'id': r.id, 'name': r.name} for r in recs]

    @http.route('/ai_assistant/history', type='json', auth='user')
    def history(self, **kw):
        return self._engine().history()

    @http.route('/ai_assistant/chat', type='json', auth='user')
    def chat(self, provider_id=None, text='', context=None, attachments=None, **kw):
        return self._engine().chat(provider_id, text, context or {}, attachments or [])

    @http.route('/ai_assistant/confirm', type='json', auth='user')
    def confirm(self, pending_id=None, approve=False, **kw):
        return self._engine().decide(pending_id, approve)

    @http.route('/ai_assistant/status', type='json', auth='user')
    def status(self, **kw):
        rec = request.env['ai.run'].sudo().search([('user_id', '=', request.env.uid)], limit=1)
        return {'status': rec.status or '' if rec else ''}

    @http.route('/ai_assistant/new', type='json', auth='user')
    def new(self, **kw):
        if self._engine()._has_access():
            convs = request.env['ai.conversation'].sudo().search([('user_id', '=', request.env.uid)])
            convs.write({'active': False})
        return {'ok': True}
