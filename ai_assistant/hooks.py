# (model, read, create, write, call workflow buttons)
DEFAULT_MODELS = [
    ('res.partner', True, True, True, False),
    ('crm.lead', True, True, True, True),
    ('project.task', True, True, True, False),
    ('product.template', True, True, True, False),
    ('product.product', True, False, False, False),
    ('sale.order', True, False, True, True),
    ('sale.order.line', True, False, False, False),
    ('purchase.order', True, False, True, True),
    ('purchase.order.line', True, False, False, False),
    ('account.move', True, False, False, True),
    ('account.move.line', True, False, False, False),
    ('account.payment', True, False, False, False),
    ('stock.picking', True, False, False, True),
    ('stock.quant', True, False, False, False),
    ('stock.move', True, False, False, False),
    ('hr.employee', True, False, False, False),
    ('hr.leave', True, False, False, True),
    ('hr.attendance', True, False, False, False),
    ('account.analytic.line', True, True, False, False),
    ('helpdesk.ticket', True, True, True, False),
]


def post_init(env):
    IrModel = env['ir.model']
    Allowed = env['ai.allowed.model']
    for name, r, c, w, call in DEFAULT_MODELS:
        model = IrModel.search([('model', '=', name)], limit=1)
        if model and not Allowed.search([('model_id', '=', model.id)], limit=1):
            Allowed.create({
                'model_id': model.id, 'perm_read': r, 'perm_create': c,
                'perm_write': w, 'perm_call': call,
            })
    Allowed._apply_default_scopes()
    icp = env['ir.config_parameter'].sudo()
    if not icp.get_param('ai_assistant.require_group'):
        icp.set_param('ai_assistant.require_group', '1')
