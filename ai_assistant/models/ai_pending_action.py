import json

from odoo import fields, models
from odoo.exceptions import UserError

from .ai_utils import clean_values

# Only these buttons can ever be triggered (always after explicit user approval).
# Nothing here deletes records. cancel / draft only change the document state.
WORKFLOWS = {
    'sale.order': ['action_confirm', 'action_cancel', 'action_draft', 'create_invoice'],
    'purchase.order': ['button_confirm', 'button_cancel', 'button_draft', 'action_create_invoice'],
    'account.move': ['action_post', 'button_draft', 'button_cancel', 'register_payment'],
    'stock.picking': ['button_validate', 'action_cancel'],
    'crm.lead': ['action_set_won'],
    'hr.leave': ['action_approve', 'action_refuse'],
}
# Optional parameters accepted by special methods
PARAMS = {
    'register_payment': ('amount', 'journal_id', 'payment_date', 'communication'),
}


class AiPendingAction(models.Model):
    _name = 'ai.pending.action'
    _description = 'AI proposed action (needs user approval) and audit log'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', required=True, default=lambda s: s.env.user)
    kind = fields.Selection([('create', 'Create'), ('write', 'Update'), ('call', 'Workflow')], required=True)
    model_name = fields.Char()
    summary = fields.Char()
    payload = fields.Text(required=True)
    state = fields.Selection([
        ('pending', 'Pending'), ('awaiting_approval', 'Awaiting Approval'),
        ('done', 'Done'), ('cancelled', 'Cancelled'), ('failed', 'Failed')],
        default='pending', index=True)
    result = fields.Text()

    def _register_payment(self, moves, params):
        vals = {}
        if params.get('amount'):
            amount = float(params['amount'])
            if amount <= 0:
                raise UserError('Payment amount must be positive.')
            vals['amount'] = amount
            if amount <= 0:
                raise UserError('Payment amount must be positive.')
            vals['amount'] = amount
        if params.get('journal_id'):
            vals['journal_id'] = int(params['journal_id'])
        if params.get('payment_date'):
            vals['payment_date'] = str(params['payment_date'])
        if params.get('communication'):
            vals['communication'] = str(params['communication'])[:200]
        wizard = moves.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=moves.ids).create(vals)
        return wizard.action_create_payments()

    def action_execute(self):
        self.ensure_one()
        if self.user_id != self.env.user or self.state != 'pending':
            raise UserError('This action cannot be executed.')
        p = json.loads(self.payload)
        model = p['model']
        assistant = self.env['ai.assistant']
        rule = assistant._check(model, {'create': 'create', 'write': 'write', 'call': 'call'}[self.kind])
        scope = assistant._scope_domain(self.env[model], rule)
        Model = self.env(su=False)[model]
        action = None
        try:
            with self.env.cr.savepoint():
                if self.kind == 'create':
                    rec = Model.create(clean_values(Model, p['values']))
                    msg = 'Created %s #%s (%s)' % (model, rec.id, rec.display_name)
                elif self.kind == 'write':
                    recs = self._scoped_records(Model, scope, p['ids'])
                    recs.write(clean_values(Model, p['values']))
                    msg = 'Updated %s: %s' % (model, ', '.join(recs.mapped('display_name')))
                else:
                    method = p['method']
                    if method not in WORKFLOWS.get(model, []):
                        raise UserError('Method not allowed.')
                    recs = self._scoped_records(Model, scope, p['ids'])
                    if method == 'create_invoice':
                        res = recs._create_invoices()
                    elif method == 'register_payment':
                        res = self._register_payment(recs, p.get('params') or {})
                    else:
                        res = getattr(recs, method)()
                    names = ', '.join(recs.mapped('display_name'))
                    if isinstance(res, dict) and res.get('type'):
                        action = json.loads(json.dumps(res, default=str))
                        msg = 'More input is needed to finish: I opened the window for %s.' % names
                    elif isinstance(res, models.BaseModel) and res:
                        msg = 'Done (%s) on %s. Result: %s' % (method, names, ', '.join(res.mapped('display_name')))
                    else:
                        msg = 'Done (%s) on %s' % (method, names)
        except Exception as e:
            err = e.args[0] if e.args else str(e)
            self.write({'state': 'failed', 'result': str(err)})
            raise UserError('Failed: %s' % err)
        self.write({'state': 'done', 'result': msg})
        return {'message': msg, 'action': action}

    def action_cancel(self):
        self.ensure_one()
        if self.user_id == self.env.user and self.state == 'pending':
            self.state = 'cancelled'
