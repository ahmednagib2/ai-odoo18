import json
import logging
import time

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

RETRY_CODES = (429, 500, 502, 503, 504)
ATTEMPTS = 3
MIN_TOKENS = 4096
FAIL_COOLDOWN = 180  # seconds a failing provider is tried last
FAST_CAP = 30  # per-request timeout (s) for providers that have a fallback behind them

# provider id -> monotonic time of its last failure (per worker process, in memory)
_FAIL = {}

HINTS = {
    400: 'طلب غير صالح - راجع اسم الموديل والإعدادات',
    401: 'مفتاح API غير صالح أو منتهي',
    403: 'المفتاح لا يملك صلاحية - راجع القيود والفوترة',
    404: 'اسم الموديل غير متاح - غيّره في إعدادات المزود',
    429: 'تجاوزت الحد أو الحصة المسموحة',
    500: 'خطأ مؤقت عند المزود',
    502: 'المزود غير متاح مؤقتًا',
    503: 'المزود مزدحم حاليًا',
    504: 'المزود تأخر في الرد',
}

DEFAULTS = {
    'openai': ('https://api.openai.com/v1', 'gpt-4.1-mini'),
    'gemini': ('https://generativelanguage.googleapis.com/v1beta', 'gemini-3.8-flash'),
    'anthropic': ('https://api.anthropic.com/v1', 'claude-sonnet-4-5'),
    'compatible': ('http://localhost:18789/v1', 'openclaw'),
}


class AiProvider(models.Model):
    _name = 'ai.provider'
    _description = 'AI Provider'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10, help='Providers are tried in this order when one is busy or failing.')
    active = fields.Boolean(default=True)
    provider_type = fields.Selection([
        ('openai', 'OpenAI (ChatGPT)'),
        ('gemini', 'Google Gemini'),
        ('anthropic', 'Anthropic Claude'),
        ('compatible', 'OpenAI-compatible (OpenClaw, OpenRouter, Ollama, DeepSeek, Groq...)'),
    ], required=True, default='openai')
    api_key = fields.Char(groups='base.group_system')
    base_url = fields.Char(help='Leave empty to use the default URL of the provider type.')
    model_name = fields.Char(required=True, help='Any model id, e.g. gpt-4.1-mini, gemini-3.8-flash, claude-sonnet-4-5')
    temperature = fields.Float(default=0.2)
    max_tokens = fields.Integer(default=4096, help='At least 4096 is always used so that thinking models can finish their answer.')
    timeout = fields.Integer(default=60)
    reasoning = fields.Selection([
        ('default', 'Model default'),
        ('low', 'Low (fastest)'),
        ('medium', 'Medium'),
        ('high', 'High (most accurate, slowest)'),
    ], default='low', help='Gemini 3.x only: how much the model thinks before answering. Lower = much faster.')

    @api.onchange('provider_type')
    def _onchange_provider_type(self):
        if self.provider_type:
            self.base_url, self.model_name = DEFAULTS[self.provider_type]

    # ---------- connection test (button on the form) ----------
    def action_test_connection(self):
        self.ensure_one()
        start = time.monotonic()
        try:
            out = self.with_context(ai_deadline=time.monotonic() + 60)._complete(
                'You are a connectivity test. Reply with the single word OK.',
                [{'role': 'user', 'content': 'ping'}])
            ok = True
            msg = 'OK (%.1f s) - %s : %s' % (
                time.monotonic() - start, self.model_name, (out or '').strip()[:60] or '(empty reply)')
        except UserError as e:
            ok = False
            msg = str(e.args[0])[:600]
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': self.name, 'message': msg,
                       'type': 'success' if ok else 'danger', 'sticky': not ok},
        }

    @staticmethod
    def _normalize(messages):
        out = []
        for m in messages:
            role = 'assistant' if m.get('role') == 'assistant' else 'user'
            text = str(m.get('content') or '')
            atts = list(m.get('attachments') or [])
            if not text and not atts:
                continue
            if out and out[-1]['role'] == role:
                out[-1]['content'] += '\n' + text
                out[-1]['attachments'] += atts
            else:
                out.append({'role': role, 'content': text, 'attachments': atts})
        while out and out[0]['role'] != 'user':
            out.pop(0)
        return out

    # ---------- message builders (text + images + PDF) ----------
    @staticmethod
    def _openai_messages(rec, system, msgs):
        out = [{'role': 'system', 'content': system}]
        for m in msgs:
            if not m['attachments']:
                out.append({'role': m['role'], 'content': m['content']})
                continue
            text = m['content'] or '(see attachment)'
            parts = []
            for a in m['attachments']:
                uri = 'data:%s;base64,%s' % (a['mimetype'], a['data'])
                if a['mimetype'].startswith('image/'):
                    parts.append({'type': 'image_url', 'image_url': {'url': uri}})
                elif a['mimetype'] == 'application/pdf' and rec.provider_type == 'openai':
                    parts.append({'type': 'file', 'file': {'filename': a.get('name') or 'file.pdf', 'file_data': uri}})
                else:
                    text += '\n[attachment %s is not supported by this provider]' % a.get('name')
            out.append({'role': m['role'], 'content': [{'type': 'text', 'text': text}] + parts})
        return out

    @staticmethod
    def _gemini_contents(msgs):
        out = []
        for m in msgs:
            parts = []
            if m['content']:
                parts.append({'text': m['content']})
            for a in m['attachments']:
                parts.append({'inlineData': {'mimeType': a['mimetype'], 'data': a['data']}})
            out.append({'role': 'user' if m['role'] == 'user' else 'model', 'parts': parts or [{'text': '.'}]})
        return out

    @staticmethod
    def _anthropic_messages(msgs):
        out = []
        for m in msgs:
            if not m['attachments']:
                out.append({'role': m['role'], 'content': m['content']})
                continue
            blocks = []
            for a in m['attachments']:
                src = {'type': 'base64', 'media_type': a['mimetype'], 'data': a['data']}
                if a['mimetype'].startswith('image/'):
                    blocks.append({'type': 'image', 'source': src})
                elif a['mimetype'] == 'application/pdf':
                    blocks.append({'type': 'document', 'source': src})
            blocks.append({'type': 'text', 'text': m['content'] or '(see attachment)'})
            out.append({'role': m['role'], 'content': blocks})
        return out

    # ---------- HTTP ----------
    @staticmethod
    def _post(url, body, headers, timeout, deadline=None, attempts=ATTEMPTS):
        """POST with retries on temporary errors (429/5xx), bounded by a deadline."""
        resp = None
        for attempt in range(attempts):
            left = (deadline - time.monotonic()) if deadline else timeout
            if left <= 3:
                break
            try:
                resp = requests.post(url, json=body, headers=headers, timeout=min(timeout, left))
            except (requests.Timeout, requests.ConnectionError) as e:
                if attempt == attempts - 1:
                    raise
                _logger.warning('AI request retry after %s', e)
                time.sleep(1.0 * (attempt + 1))
                continue
            if resp.status_code not in RETRY_CODES:
                return resp
            if attempt < attempts - 1:
                _logger.warning('AI provider busy (%s), retrying', resp.status_code)
                time.sleep(1.0 * (attempt + 1))
        if resp is None:
            raise UserError('انتهى الوقت المسموح للطلب قبل الحصول على رد.')
        return resp

    @staticmethod
    def _looks_broken(text):
        """True when the reply looks like a truncated / invalid JSON action (not plain prose)."""
        a, b = text.find('{'), text.rfind('}')
        if '"action"' not in text:
            return False
        if a < 0 or b <= a:
            return True
        try:
            json.loads(text[a:b + 1])
            return False
        except ValueError:
            return True

    def _complete_checked(self, system, messages):
        text = self._complete(system, messages)
        if not (text or '').strip():
            raise UserError('رد فارغ من %s' % self.name)
        if self._looks_broken(text):
            fix = list(messages) + [
                {'role': 'assistant', 'content': text[:4000]},
                {'role': 'user', 'content': 'Your last reply was not valid JSON. Reply again with ONE complete valid JSON object only, no extra text.'},
            ]
            again = self._complete(system, fix)
            if (again or '').strip():
                return again
        return text

    def _complete_chain(self, system, messages):
        """Fast failover: providers that failed recently go last; providers with a fallback behind
        them get one short attempt only; the last provider gets the full retry policy."""
        self.ensure_one()
        deadline = self.env.context.get('ai_deadline')
        now = time.monotonic()
        failover = self.sudo().env['ir.config_parameter'].sudo().get_param(
            'ai_assistant.failover', '1') == '1'
        pool = list(self) if not failover else list(self | self.sudo().search([('id', '!=', self.id)]))
        chain = sorted(pool, key=lambda p: _FAIL.get(p.id, 0) > now - FAIL_COOLDOWN)
        errors = []
        for i, prov in enumerate(chain):
            if deadline and time.monotonic() > deadline - 3:
                errors.append('انتهى الوقت المسموح للطلب')
                break
            last = i == len(chain) - 1
            ctx = {} if last else {'ai_attempts': 1, 'ai_timeout_cap': FAST_CAP}
            try:
                text = prov.with_context(**ctx)._complete_checked(system, messages)
                _FAIL.pop(prov.id, None)
                return text
            except UserError as e:
                _FAIL[prov.id] = time.monotonic()
                _logger.warning('Provider %s failed: %s', prov.name, e.args[0])
                errors.append('%s: %s' % (prov.name, str(e.args[0])[:250]))
        raise UserError('تعذّر الحصول على رد من أي مزود:\n' + '\n'.join(errors)[:1200])

    def _complete(self, system, messages):
        self.ensure_one()
        rec = self.sudo()
        msgs = self._normalize(messages)
        base = (rec.base_url or DEFAULTS[rec.provider_type][0]).rstrip('/')
        key = (rec.api_key or '').strip()
        max_tokens = max(rec.max_tokens or 0, MIN_TOKENS)
        deadline = self.env.context.get('ai_deadline')
        attempts = self.env.context.get('ai_attempts', ATTEMPTS)
        timeout = min(rec.timeout or 60, self.env.context.get('ai_timeout_cap', 600))
        try:
            if rec.provider_type in ('openai', 'compatible'):
                body = {'model': rec.model_name, 'messages': self._openai_messages(rec, system, msgs)}
                if rec.provider_type == 'openai':
                    body['max_completion_tokens'] = max_tokens
                    body['response_format'] = {'type': 'json_object'}
                else:
                    body['max_tokens'] = max_tokens
                    body['temperature'] = rec.temperature
                headers = {'Content-Type': 'application/json'}
                if key:
                    headers['Authorization'] = 'Bearer ' + key
                url = base + '/chat/completions'
                r = self._post(url, body, headers, timeout, deadline, attempts)
                if r.status_code == 400 and 'response_format' in body and 'response_format' in r.text:
                    body.pop('response_format')
                    r = self._post(url, body, headers, timeout, deadline, attempts)
                self._raise_for(r)
                return r.json()['choices'][0]['message']['content'] or ''
            if rec.provider_type == 'gemini':
                gen = {'temperature': rec.temperature, 'maxOutputTokens': max_tokens,
                       'responseMimeType': 'application/json'}
                if rec.model_name.startswith('gemini-3') and rec.reasoning and rec.reasoning != 'default':
                    gen['thinkingConfig'] = {'thinkingLevel': rec.reasoning}
                body = {
                    'systemInstruction': {'parts': [{'text': system}]},
                    'contents': self._gemini_contents(msgs),
                    'generationConfig': gen,
                }
                headers = {'Content-Type': 'application/json', 'x-goog-api-key': key}
                url = '%s/models/%s:generateContent' % (base, rec.model_name)
                r = self._post(url, body, headers, timeout, deadline, attempts)
                if r.status_code == 400:
                    low = r.text.lower()
                    dropped = False
                    for opt, word in (('thinkingConfig', 'thinking'), ('responseMimeType', 'mime')):
                        if opt in gen and word in low:
                            gen.pop(opt)
                            dropped = True
                    if dropped:
                        r = self._post(url, body, headers, timeout, deadline, attempts)
                self._raise_for(r)
                parts = r.json()['candidates'][0]['content'].get('parts', [])
                return ''.join(p.get('text', '') for p in parts)
            if rec.provider_type == 'anthropic':
                body = {'model': rec.model_name, 'system': system, 'messages': self._anthropic_messages(msgs),
                        'max_tokens': max_tokens, 'temperature': rec.temperature}
                headers = {'Content-Type': 'application/json', 'x-api-key': key,
                           'anthropic-version': '2023-06-01'}
                r = self._post(base + '/messages', body, headers, timeout, deadline, attempts)
                self._raise_for(r)
                return ''.join(b.get('text', '') for b in r.json().get('content', []))
        except requests.RequestException as e:
            _logger.warning('AI provider request failed: %s', e)
            raise UserError('خطأ اتصال مع %s: %s' % (rec.name, e))
        except (KeyError, IndexError, ValueError) as e:
            raise UserError('رد غير متوقع من %s: %s' % (rec.name, e))
        raise UserError('Unsupported provider type')

    @staticmethod
    def _raise_for(r):
        if r.status_code >= 400:
            hint = HINTS.get(r.status_code)
            raise UserError('API error %s%s: %s' % (
                r.status_code, ' (%s)' % hint if hint else '', r.text[:400]))
