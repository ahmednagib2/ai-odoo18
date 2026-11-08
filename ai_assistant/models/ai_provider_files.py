from odoo import models

from .ai_provider import AiProvider


class AiProviderFiles(models.Model):
    _inherit = 'ai.provider'

    @staticmethod
    def _anthropic_messages(msgs):
        """Claude does not accept audio: tell the model instead of silently dropping the file."""
        fixed = []
        for m in msgs:
            audio = [a for a in m['attachments'] if a['mimetype'].startswith('audio/')]
            if audio:
                note = ''.join('\n[attachment %s is not supported by this provider]' % a.get('name') for a in audio)
                m = dict(m, content=(m['content'] or '') + note,
                         attachments=[a for a in m['attachments'] if not a['mimetype'].startswith('audio/')])
            fixed.append(m)
        return AiProvider._anthropic_messages(fixed)

    def _complete_checked(self, system, messages):
        """Publish the live status (which provider is thinking) before every model call."""
        label = 'جاري التفكير...'
        if self.sudo().search_count([]) > 1:
            label = 'جاري التفكير (%s)...' % self.name
        self.env['ai.assistant']._set_status(label)
        return super()._complete_checked(system, messages)
