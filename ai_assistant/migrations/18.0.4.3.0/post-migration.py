from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['ai.allowed.model']._apply_default_scopes()
    icp = env['ir.config_parameter'].sudo()
    if not icp.get_param('ai_assistant.require_group'):
        icp.set_param('ai_assistant.require_group', '1')
