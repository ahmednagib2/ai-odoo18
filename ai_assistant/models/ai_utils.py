import re

from odoo.exceptions import UserError

SENSITIVE = re.compile(r'(password|passwd|secret|token|api_?key|totp|private_key)', re.I)


def clean_values(Model, values, depth=0):
    """Return a safe copy of create/write values.

    - drops the active field and sensitive fields
    - drops unknown fields
    - for x2many fields only add / edit / link commands are allowed;
      delete / unlink / clear commands are refused (the assistant never deletes).
    """
    if not isinstance(values, dict):
        raise UserError('Values must be an object')
    if depth > 3:
        raise UserError('Values are nested too deeply')
    out = {}
    for key, val in values.items():
        if key == 'active' or SENSITIVE.search(key) or key not in Model._fields:
            continue
        field = Model._fields[key]
        if field.type in ('one2many', 'many2many'):
            val = _clean_commands(Model, field, val, depth)
        out[key] = val
    return out


def _clean_commands(Model, field, cmds, depth):
    if not isinstance(cmds, list):
        raise UserError('x2many values must be a list of commands')
    Comodel = Model.env[field.comodel_name]
    res = []
    for cmd in cmds:
        if not isinstance(cmd, (list, tuple)) or not cmd or not isinstance(cmd[0], int):
            raise UserError('Invalid x2many command')
        code = cmd[0]
        if code == 0 and len(cmd) >= 3:
            res.append([0, 0, clean_values(Comodel, cmd[2], depth + 1)])
        elif code == 1 and len(cmd) >= 3:
            res.append([1, int(cmd[1]), clean_values(Comodel, cmd[2], depth + 1)])
        elif code == 4 and len(cmd) >= 2:
            res.append([4, int(cmd), 0])
        else:
            raise UserError('Deleting, unlinking or clearing lines is not allowed.')
    return res
