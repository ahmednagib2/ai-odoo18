from odoo import models
from odoo.osv import expression
from odoo.exceptions import UserError

from .ai_plus import NO_PERMISSION


class AiAssistantFix(models.AbstractModel):
    """Loaded last: fixes conflicts between the base engine and the access-tier layer.

    1. The base engine calls _scope_domain(Model, rule) and expects a domain list, while the tier
       layer defined _scope_domain(model_name, domain). For admins it returned the rule record,
       so `domain + scope` raised TypeError on every search/count/group/open and the model
       kept retrying until "I could not finish this request".
    2. Two different tier systems (_ai_tier / _tier) disagreed (an administrator without an AI
       group was 'none' in one and 'all' in the other).
    3. The tier layer ignored the Team Scopes screen.
    """
    _inherit = 'ai.assistant'

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
