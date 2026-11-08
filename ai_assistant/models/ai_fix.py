import logging

from odoo import api, models
from odoo.osv import expression
from odoo.exceptions import UserError

from .ai_plus import NO_PERMISSION

_logger = logging.getLogger(__name__)

# آخر خطأ فني حدث في أداة لكل مستخدم (للتشخيص فقط، في الذاكرة)
_LAST = {}


class AiAssistantFix(models.AbstractModel):
    """يُحمّل أخيراً: يصلح التضارب بين المحرك الأساسي وطبقة مستويات الصلاحيات،
    ويسجّل أخطاء الأدوات في اللوج ويظهر سبب الفشل الحقيقي بدل الرسالة العامة.
    """
    _inherit = 'ai.assistant'

    def _note(self, where, err):
        _LAST[self.env.uid] = '%s -> %s' % (where, err)
        _logger.warning('AI Assistant tool failure [%s] user=%s: %s', where, self.env.uid, err)

    def _ai_tier(self):
        tier = super()._ai_tier()
        if tier != 'none':
            return tier
        return {'all': 'manager', 'team': 'team', 'own': 'user'}.get(self._tier(), 'none')

    def _scope_domain(self, model, domain=None):
        name = model._name if isinstance(model, models.BaseModel) else model
        if isinstance(domain, models.BaseModel):
            domain = []
        domain = list(domain or [])
        tier = self._tier()
        if tier in ('all', None) or not name:
            return domain
        rule = self._allowed().filtered(lambda r: r.model_name == name)
        if not rule:
            raise UserError(NO_PERMISSION % self._model_label(name))
        if rule.shared_data:
            return domain
        if not rule.owner_field:
            raise UserError(NO_PERMISSION % self._model_label(name))
        uids = [self.env.uid] if tier == 'own' else self._team_user_ids()
        return expression.AND([domain, [(rule.owner_field, 'in', uids)]])

    def _team_user_ids(self):
        uid = self.env.uid
        custom = self.env['ai.team.scope'].get_team_user_ids(uid)
        if custom:
            return list(set(custom) | {uid})
        return super()._team_user_ids()

    # ---------- تشخيص: تسجيل أخطاء الأدوات ----------
    def _run_read(self, d):
        where = 'read %s %s' % (d.get('action'), d.get('model'))
        try:
            res = super()._run_read(d)
        except Exception as e:
            self._note(where, repr(e))
            raise
        if isinstance(res, dict) and res.get('error'):
            self._note(where, res['error'])
        return res

    def _run_open(self, d):
        try:
            res = super()._run_open(d)
        except Exception as e:
            self._note('open %s' % (d.get('model') or d.get('menu')), repr(e))
            raise
        if isinstance(res, dict) and res.get('error'):
            self._note('open %s' % (d.get('model') or d.get('menu')), res['error'])
        return res

    def _run_fill(self, d, context):
        try:
            return super()._run_fill(d, context)
        except Exception as e:
            self._note('fill', repr(e))
            raise

    def _propose(self, d):
        try:
            return super()._propose(d)
        except Exception as e:
            self._note('propose %s' % d.get('model'), repr(e))
            raise

    @api.model
    def chat(self, provider_id, text, context=None, attachments=None):
        _LAST.pop(self.env.uid, None)
        try:
            res = super().chat(provider_id, text, context, attachments)
        except Exception:
            _logger.exception('AI Assistant chat crashed for user %s', self.env.uid)
            raise
        if isinstance(res, dict) and 'could not finish' in str(res.get('message') or ''):
            last = _LAST.get(self.env.uid)
            if last:
                msg = 'تعذّر إكمال الطلب.\nآخر خطأ فني: %s' % last
            else:
                msg = ('تعذّر إكمال الطلب: لم يُسجّل أي خطأ في الأدوات، غالباً رد الموديل غير مفهوم '
                       '(راجع اسم الموديل في إعدادات المزود أو جرّب مزوداً آخر).')
            _logger.warning('AI Assistant could-not-finish for user %s: %s', self.env.uid, msg)
            res = dict(res, message=msg)
        return res
