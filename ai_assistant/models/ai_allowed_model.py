from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.exceptions import UserError

# model -> (owner field path, shared data). The owner field is the path (on that model) to the
# res.users who owns the record; it is used to limit what "own data" and "team" tiers can see.
DEFAULT_SCOPES = {
    'sale.order': ('user_id', False),
    'sale.order.line': ('salesman_id', False),
    'crm.lead': ('user_id', False),
    'account.move': ('invoice_user_id', False),
    'account.move.line': ('move_id.invoice_user_id', False),
    'account.payment': ('create_uid', False),
    'purchase.order': ('user_id', False),
    'purchase.order.line': ('order_id.user_id', False),
    'stock.picking': ('user_id', False),
    'stock.move': ('picking_id.user_id', False),
    'stock.quant': ('', True),
    'product.template': ('', True),
    'product.product': ('', True),
    'res.partner': ('user_id', False),
    'project.task': ('user_ids', False),
    'hr.employee': ('user_id', False),
    'hr.leave': ('employee_id.user_id', False),
    'hr.attendance': ('employee_id.user_id', False),
    'account.analytic.line': ('user_id', False),
    'helpdesk.ticket': ('user_id', False),
    'pos.order': ('user_id', False),
    'pos.session': ('user_id', False),
    'pos.order.line': ('order_id.user_id', False),
}


class AiAllowedModel(models.Model):
    _name = 'ai.allowed.model'
    _description = 'Models the AI assistant may access'

    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade', string='Model')
    model_name = fields.Char(related='model_id.model', store=True)
    perm_read = fields.Boolean('Read', default=True)
    perm_create = fields.Boolean('Create', default=False)
    perm_write = fields.Boolean('Update', default=False)
    perm_call = fields.Boolean('Workflow buttons', default=False,
                               help='Allow whitelisted buttons (confirm order, post invoice...) after user approval.')
    perm_draft = fields.Boolean('Draft form', default=False,
                                help='The assistant may open a NEW form of this model already filled with data. '
                                     'Nothing is saved: the user reviews the form and saves it himself.')
    owner_field = fields.Char(
        'Owner field',
        help='Path to the user who owns the record (e.g. user_id, invoice_user_id, employee_id.user_id). '
             'Users of the tier "own data only" see only records where this field is themselves; '
             'team leaders see themselves and their team. Leave empty together with "Shared data" unticked '
             'to hide the model from those tiers.')
    shared_data = fields.Boolean(
        'Shared data', default=False,
        help='Same data for everybody (products, stock levels...). Tiers "own data" and "team" can read it without an owner filter.')
    max_records = fields.Integer('Max records per query', default=30)

    _sql_constraints = [('model_uniq', 'unique(model_id)', 'This model is already configured.')]

    @api.constrains('model_id', 'owner_field')
    def _check_owner_field(self):
        """Ensure the configured owner path exists on the selected model."""
        for rec in self:
            if not rec.owner_field:
                continue
            Model = self.env.get(rec.model_name)
            if not Model:
                continue
            parts = rec.owner_field.split('.')
            cursor = Model
            for part in parts:
                if part not in cursor._fields:
                    raise UserError(
                        'Field path "%s" does not exist on model %s.'
                        % (rec.owner_field, rec.model_name)
                    )
                cursor = self.env[cursor._fields[part].comodel_name]

    @api.model
    def _apply_default_scopes(self):
        """Fill owner_field / shared_data of rows that do not have a scope yet."""
        for rec in self.search([]):
            if rec.owner_field or rec.shared_data:
                continue
            scope = DEFAULT_SCOPES.get(rec.model_name)
            if scope:
                rec.write({'owner_field': scope[0], 'shared_data': scope[1]})
