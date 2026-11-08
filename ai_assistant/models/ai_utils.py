import re

from odoo.exceptions import UserError

SENSITIVE = re.compile(r'(password|passwd|secret|token|api_?key|totp|private_key)', re.I)


def clean_values(Model, values, depth=0):
    """إرجاع نسخة آمنة من قيم الإنشاء/التعديل.

    - تحذف حقل active والحقول الحساسة
    - تحذف الحقول غير المعروفة
    - في حقول x2many يُسمح فقط بأوامر الإضافة والتعديل والربط؛
      أوامر الحذف وفك الارتباط والمسح مرفوضة (المساعد لا يحذف أبداً).
    """
    if not isinstance(values, dict):
        raise UserError('يجب أن تكون القيم على شكل كائن (dict).')
    if depth > 3:
        raise UserError('القيم متداخلة بعمق زائد.')
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
        raise UserError('قيم حقول x2many يجب أن تكون قائمة أوامر.')
    Comodel = Model.env[field.comodel_name]
    res = []
    for cmd in cmds:
        if not isinstance(cmd, (list, tuple)) or not cmd or not isinstance(cmd[0], int):
            raise UserError('أمر x2many غير صالح.')
        code = cmd[0]
        if code == 0 and len(cmd) >= 3:
            res.append([0, 0, clean_values(Comodel, cmd[2], depth + 1)])
        elif code == 1 and len(cmd) >= 3:
            res.append([1, int(cmd[1]), clean_values(Comodel, cmd[2], depth + 1)])
        elif code == 4 and len(cmd) >= 2:
            res.append([4, int(cmd[1]), 0])
        else:
            raise UserError('حذف السطور أو فك ارتباطها أو مسحها غير مسموح.')
    return res
