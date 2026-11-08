import json
import re
import time
import time
from datetime import date, datetime, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from .ai_pending_action import PARAMS, WORKFLOWS
from .ai_utils import SENSITIVE, clean_values

MAX_STEPS = 8
MAX_FILES = 4
MAX_B64 = 11 * 1024 * 1024
FILE_TYPES = ('image/png', 'image/jpeg', 'image/webp', 'image/gif', 'application/pdf')
SKIP_TYPES = ('binary',)
BLOCKED_PREFIXES = (
    'ir.', 'ai.', 'res.users.', 'res.groups', 'res.config', 'bus.', 'auth_', 'payment.token',
    'payment.provider', 'mail.', 'base.', 'fetchmail', 'iap.', 'google.', 'sms.')
AGG_FUNCS = ('sum', 'avg', 'min', 'max', 'count_distinct')

PROMPT = '''You are Odoo Copilot: a senior Odoo 18 consultant and a friendly colleague working inside the company Odoo of the user. Talk like a real, warm, practical person: natural wording, same language and dialect as the user (Egyptian or Saudi Arabic if they write like that), short and clear, no robotic phrases. Never mention JSON, tools or internal actions to the user.

USER: __USER__ | COMPANY: __COMPANY__ | NOW: __NOW__ (timezone __TZ__)
Datetime ranges in UTC for the user local periods (use them for datetime fields such as date_order, create_date):
__RANGES__
__SCREEN__

PERMITTED MODELS (explicit permissions):
__MODELS__
__READALL__
__SCOPE__

HOW YOU WORK: every turn you answer with ONE JSON object only (no code fences, no extra text). After a data action you receive TOOL_RESULT and continue until you can answer.
Actions:
{"action":"models","keyword":"sale"}  find model technical names
{"action":"fields","model":"sale.order","keyword":"amount"}  field names, types, selection values
{"action":"search","model":"sale.order","domain":[["state","in",["sale","done"]]],"fields":["name","partner_id","amount_total"],"limit":10,"order":"date_order desc"}
{"action":"count","model":"sale.order","domain":[]}
{"action":"group","model":"sale.order","domain":[],"groupby":["user_id"],"aggregates":["amount_total:sum"],"order":"amount_total:sum desc","limit":20}  totals/averages; groupby may use date granularity like date_order:month; functions: sum, avg, min, max, count_distinct; __count is always added
{"action":"open","menu":"Inventory","message":"short sentence to the user"}  opens an app or menu on the screen (use the app name in English or the user language; if not found you receive the list of available apps)
{"action":"open","model":"stock.picking","domain":[["state","=","assigned"]],"title":"Ready deliveries","message":"short sentence"}  opens a list of records
{"action":"open","model":"sale.order","res_id":5,"message":"short sentence"}  opens one record form
{"action":"fill","values":{"partner_id":"Acme","note":"text"},"message":"short sentence"}  fills fields of the form that is open on the user screen (nothing is saved, the user reviews and saves). Many2one by name or id, selection by key or label, datetimes as local time YYYY-MM-DD HH:MM, dates as YYYY-MM-DD. Only when SCREEN CONTEXT says a form is open.
{"action":"create","model":"res.partner","values":{"name":"X"},"summary":"short description"}  proposal
{"action":"write","model":"res.partner","ids":[1],"values":{"phone":"123"},"summary":"short description"}  proposal
{"action":"call","model":"sale.order","ids":[5],"method":"action_confirm","summary":"short description"}  proposal for an approved workflow button. Allowed buttons: __WORKFLOWS__. register_payment accepts optional "params":{"amount":500,"journal_id":7,"payment_date":"2026-10-08"}.
{"action":"reply","message":"your answer to the user"}

ODOO KNOWLEDGE:
- When the user asks to open, show me, take me to or go to a screen/app/list/record, use the open action instead of describing it. When the user asks to fill the form in front of them, use fill.
- Always compute totals with group/count, never by adding rows yourself. For totals over a period use group with no groupby. Check TOOL_RESULT total_matching to know if rows were truncated.
- sale.order: state draft (quotation), sent, sale (sales order), done (locked), cancel. Real sales = state in sale,done. Fields: name, partner_id, date_order (datetime), amount_untaxed, amount_total, user_id (salesperson), team_id, invoice_status, currency_id. Lines: order_line with product_id, product_uom_qty, price_unit.
- account.move: move_type out_invoice (customer invoice), out_refund (credit note), in_invoice (vendor bill), in_refund, entry; state draft, posted, cancel; payment_state not_paid, partial, in_payment, paid, reversed; fields invoice_date (date), invoice_date_due, amount_total, amount_residual, partner_id, ref (vendor bill number). Lines: invoice_line_ids with product_id, name, quantity, price_unit, tax_ids. Overdue = state posted, payment_state in not_paid,partial, invoice_date_due < today. Saudi ZATCA e-invoicing fields start with l10n_sa_ (discover with fields).
- account.payment, account.move.line (accounting entries; balance, debit, credit, account_id, partner_id). Account journals: model account.journal (type bank/cash/sale/purchase).
- purchase.order: state draft, sent, to approve, purchase, done, cancel; fields partner_id, amount_total, date_order; lines order_line.
- stock.picking: state draft, waiting, confirmed, assigned, done, cancel; picking_type_code incoming/outgoing/internal; stock.quant gives on-hand quantity (location usage internal); product.product/product.template: name, list_price, standard_price, qty_available, default_code.
- crm.lead: type lead/opportunity; stage_id, probability, expected_revenue, user_id, active.
- project.task: stage_id, user_ids, date_deadline, project_id; hr.employee, hr.leave (state confirm, validate1, validate), hr.attendance (check_in, check_out), account.analytic.line (timesheets: unit_amount, employee_id, date).
- Datetime fields are stored in UTC: use the UTC ranges above. Date fields (invoice_date, date, date_deadline) use plain local dates.
- Many2one values in filters are integer ids; to filter by a name first search the record id. In answers show names, never raw ids unless asked. Format money with thousands separators and mention the currency when known.
- One2many / many2many values in create or write use commands: [[0,0,{...new line...}]] to add lines, [[1,line_id,{...}]] to edit a line, [[4,id,0]] to link. Removing lines is not possible.
- Workflow meaning: create_invoice makes a draft customer invoice from a sale order; register_payment pays posted invoices; action_cancel / button_cancel / button_draft only change the document state (say what will happen in the summary); confirm and post change accounting or stock, so describe them clearly.
- ATTACHMENTS: the user may attach images or PDFs (invoices, receipts, business cards, screenshots). Read them carefully. For a vendor bill, first search the partner and products, then propose create on account.move with move_type in_invoice, partner_id, invoice_date, ref and invoice_line_ids commands. If something is unclear or unreadable, ask the user instead of guessing.
- If you are unsure about a field name, use the fields action first. If a search returns an error, fix the call and retry.

SAFETY RULES (absolute):
- Respect the user's data scope strictly. Never search, count, group, open or propose an action on records outside the user's permitted scope.
- You can NEVER delete, archive, unlink or deactivate anything, you cannot change the active field and you cannot remove lines. If asked, politely say you do not delete data and tell the user to do it manually.
- create, write and call are only proposals; the user approves in the UI. Never say they are done before approval.
- Never reveal or ask for passwords, API keys or tokens. Stay inside the permitted models and permissions.
- Do not invent data: only state what comes from TOOL_RESULT, attachments, or the screen context.'''


class AiAssistant(models.AbstractModel):
    _name = 'ai.assistant'
    _description = 'AI Assistant engine'

    # ---------- permissions ----------
    def _allowed(self):
        return self.env['ai.allowed.model'].sudo().search([])

    def _read_all(self):
        return self.env['ir.config_parameter'].sudo().get_param('ai_assistant.read_all', '1') == '1'

    def _log_audit(self, action, model_name=None, record_ids=None, domain=None,
                   scope=None, status='success', details=None, conversation_id=None,
                   duration=None):
        """Create a governance audit entry without exposing audit-model permissions to end users."""
        return self.env['ai.audit.log'].sudo().log_event(
            action=action,
            model_name=model_name,
            record_ids=record_ids,
            domain=domain,
            scope=scope,
            status=status,
            details=details,
            conversation_id=conversation_id,
            duration=duration,
        )

    def _check_quota(self):
        """Return False when the current user has exhausted an active AI quota rule."""
        try:
            self.env['ai.quota'].check_quota()
        except UserError:
            return False
        return True

    def _approval_required(self, model_name, kind, payload):
        """Return the approver display name when the pending action requires approval."""
        if kind not in ('write', 'call'):
            return False
        if isinstance(payload, str):
            try:
                payload = json.loads(payload or '{}')
            except ValueError:
                payload = {}
        values = (payload or {}).get('values') or {}
        rule = self.env['ai.approval.rule'].get_rule(model_name, kind)
        if not rule or not rule.needs_approval(values):
            return False
        return rule.approver_id.display_name or 'a manager'

    def _log_audit(self, action, model_name=None, record_ids=None, domain=None,
                   scope=None, status='success', details=None, conversation_id=None,
                   duration=None):
        """Create a governance audit entry without exposing audit-model permissions to end users."""
        return self.env['ai.audit.log'].sudo().log_event(
            action=action,
            model_name=model_name,
            record_ids=record_ids,
            domain=domain,
            scope=scope,
            status=status,
            details=details,
            conversation_id=conversation_id,
            duration=duration,
        )

    def _check_quota(self):
        """Return False when the current user has exhausted an active AI quota rule."""
        try:
            self.env['ai.quota'].check_quota()
        except UserError:
            return False
        return True

    def _approval_required(self, model_name, kind, payload):
        """Return the approver display name when the pending action requires approval."""
        if kind not in ('write', 'call'):
            return False
        if isinstance(payload, str):
            try:
                payload = json.loads(payload or '{}')
            except ValueError:
                payload = {}
        values = (payload or {}).get('values') or {}
        rule = self.env['ai.approval.rule'].get_rule(model_name, kind)
        if not rule or not rule.needs_approval(values):
            return False
        return rule.approver_id.display_name or 'a manager'

    def _ai_tier(self):
        user = self.env.user
        elevated = self.env['ai.elevated.access'].get_active_tier(user.id)
        if elevated:
            return elevated
        if user.has_group('ai_assistant.group_ai_manager'):
            return 'manager'
        if user.has_group('ai_assistant.group_ai_team'):
            return 'team'
        if user.has_group('ai_assistant.group_ai_user'):
            return 'user'
        return 'none'

    def _team_user_ids(self):
        uid = self.env.uid
        custom = self.env['ai.team.scope'].get_team_user_ids(uid)
        if custom:
            return list(set(custom) | {uid})
        users = {uid}
        if 'hr.employee' in self.env:
            Employee = self.env['hr.employee']
            employee = Employee.search([('user_id', '=', uid)], limit=1)
            if employee:
                subordinates = Employee.search([('parent_id', 'child_of', employee.ids)])
                users.update(subordinates.mapped('user_id').ids)
        if 'crm.team' in self.env:
            Team = self.env['crm.team']
            teams = Team.search([('user_id', '=', uid)])
            users.update(teams.mapped('member_ids').mapped('id'))
        return list(users)

    def _scope_domain(self, Model, rule):
        tier = self._ai_tier()
        if tier == 'manager':
            return []
        if not rule:
            raise UserError('Not allowed: this model is not available for your access level.')
        owner = rule.owner_field
        if not owner:
            if rule.shared_data:
                return []
            raise UserError('Not allowed: you can only access your own data on this model.')
        uid = self.env.uid
        if tier == 'user':
            return [(owner, '=', uid)]
        team_ids = self._team_user_ids()
        return ['|', (owner, '=', uid), (owner, 'in', team_ids)]

    def _check(self, model, perm):
        if not model or model not in self.env:
            raise UserError('Unknown model %s' % model)
        rec = self._allowed().filtered(lambda r: r.model_name == model)
        tier = self._ai_tier()
        if not rec and perm == 'read' and tier == 'manager' and self._read_all():
            if not model.startswith(BLOCKED_PREFIXES) and not self.env[model]._transient:
                return rec
        if not rec or not rec['perm_' + perm]:
            raise UserError('Not allowed: %s on %s' % (perm, model))
        return rec

    # ---------- helpers ----------
    @staticmethod
    def _parse_dsml(text):
        """Convert a DSML-style tool call (sent by some models) into an action dict."""
        call = re.search(r'invoke\s+name="(\w+)"\s*>(.*?)</[^<>]*invoke\s*>', text, flags=re.S)
        if not call:
            return None
        data = {'action': call.group(1)}
        for m in re.finditer(r'parameter\s+name="(\w+)"([^>]*)>(.*?)</[^<>]*parameter\s*>',
                             call.group(2), flags=re.S):
            name, attrs, value = m.group(1), m.group(2), m.group(3).strip()
            if 'string="true"' not in attrs:
                try:
                    value = json.loads(value)
                except ValueError:
                    pass
            data[name] = value
        return data

    @staticmethod
    def _parse(raw):
        text = (raw or '').strip()
        if 'DSML' in text:
            data = AiAssistant._parse_dsml(text)
            if data:
                return data
        text = re.sub(r'^```(?:json)?|```$', '', text, flags=re.M).strip()
        a, b = text.find('{'), text.rfind('}')
        if a < 0 or b <= a:
            return None
        try:
            data = json.loads(text[a:b + 1])
            return data if isinstance(data, dict) else None
        except ValueError:
            return None

    @staticmethod
    def _jsonable(v):
        if isinstance(v, models.BaseModel):
            if not v:
                return None
            return {'id': v.id, 'name': v.display_name} if len(v) == 1 else v.ids
        if isinstance(v, (datetime, date)):
            return str(v)
        return v

    @staticmethod
    def _json_arg(value):
        """Normalize JSON values that some models send as JSON-encoded strings."""
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                raise UserError('Invalid JSON parameter')
        return value

    @staticmethod
    def _string_list(value, label):
        value = AiAssistant._json_arg(value) or []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or any(not isinstance(item, (str, int, float)) for item in value):
            raise UserError('Invalid %s parameter' % label)
        return [str(item) for item in value]

    @staticmethod
    def _limit(value, default, maximum):
        value = AiAssistant._json_arg(value)
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise UserError('Invalid limit parameter')
        value = int(value)
        if value < 1:
            raise UserError('Invalid limit parameter')
        return min(value, maximum)

    def _domain(self, d):
        domain = self._json_arg(d.get('domain')) or []
        if isinstance(domain, tuple):
            domain = list(domain)
        if not isinstance(domain, list):
            raise UserError('Invalid domain')
        if SENSITIVE.search(json.dumps(domain, ensure_ascii=False)):
            raise UserError('Sensitive fields cannot be used')
        return domain

    def _field_rules(self, Model):
        return self.env['ai.field.rule'].get_rules(Model._name, self._ai_tier())

    def _apply_field_rules(self, Model, rows):
        rules = self._field_rules(Model)
        if not rules:
            return rows
        hide = set(rules.filtered(lambda r: r.action == 'hide').mapped('field_name'))
        mask = set(rules.filtered(lambda r: r.action == 'mask').mapped('field_name'))
        out = []
        for row in rows:
            item = dict(row)
            for f in hide:
                item.pop(f, None)
            for f in mask:
                if f in item:
                    item[f] = '*****'
            out.append(item)
        return out

    def _clean_fields(self, Model, names):
        names = self._string_list(names, 'fields')
        hide = set(self._field_rules(Model).filtered(lambda r: r.action == 'hide').mapped('field_name'))
        ok = [n for n in names if n in Model._fields
              and Model._fields[n].type not in SKIP_TYPES and not SENSITIVE.search(n)
              and n not in hide]
        return ok or ['display_name']

    def _ranges(self):
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        now = datetime.now(tz)
        d0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
        m0 = d0.replace(day=1)
        nm = (m0 + timedelta(days=32)).replace(day=1)
        w0 = d0 - timedelta(days=d0.weekday())
        utc = lambda x: x.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        spans = {
            'today': (d0, d0 + timedelta(days=1)), 'yesterday': (d0 - timedelta(days=1), d0),
            'this_week': (w0, w0 + timedelta(days=7)), 'this_month': (m0, nm),
        }
        lines = ['- %s: >= %s and < %s' % (k, utc(a), utc(b)) for k, (a, b) in spans.items()]
        return now.strftime('%Y-%m-%d %H:%M %A'), tz.zone, '\n'.join(lines), now.strftime('%Y-%m-%d')

    def _system(self, context=None):
        now, tzname, ranges, today = self._ranges()
        rows = []
        for r in self._allowed():
            perms = [p for p, f in (('read', r.perm_read), ('create', r.perm_create),
                                    ('update', r.perm_write), ('workflow', r.perm_call)) if f]
            rows.append('- %s: %s' % (r.model_name, ', '.join(perms)))
        screen = ''
        ctx = context or {}
        model = ctx.get('model')
        if isinstance(model, str) and model in self.env:
            screen = 'SCREEN CONTEXT: the user is looking at model %s' % model
            if ctx.get('view_type'):
                screen += ', view type %s' % str(ctx['view_type'])[:20]
            if ctx.get('view_type') == 'form':
                screen += ' (a form is open: fill is available)'
            if isinstance(ctx.get('res_id'), int):
                screen += ', record id %s' % ctx['res_id']
            if ctx.get('name'):
                screen += ', title "%s"' % str(ctx['name'])[:80]
            screen += '. Words like this record / this order / here refer to it.'
        tier = self._ai_tier()
        scope = {
            'user': 'DATA SCOPE: You may access only records owned by the current user.',
            'team': 'DATA SCOPE: You may access records owned by the current user and by users in their HR/sales team hierarchy.',
            'manager': 'DATA SCOPE: You may access all records permitted by the user’s Odoo access rights.',
        }.get(tier, 'DATA SCOPE: You do not have an AI Assistant access level.')
        readall = ('Any other business model can be READ (not changed) except system/technical ones; '
                   'use the models action to discover them.') if tier == 'manager' and self._read_all() else ''
        wf = '; '.join('%s.%s' % (m, ', '.join(v)) for m, v in WORKFLOWS.items())
        return (PROMPT.replace('__USER__', self.env.user.name).replace('__COMPANY__', self.env.company.name)
                .replace('__NOW__', now).replace('__TZ__', tzname).replace('__RANGES__', ranges)
                .replace('__SCREEN__', screen).replace('__MODELS__', '\n'.join(rows) or '(none)')
                .replace('__READALL__', readall).replace('__SCOPE__', scope)
                .replace('__WORKFLOWS__', wf)
                + '\nToday (user date): ' + today)

    # ---------- read tools ----------
    def _run_read(self, d):
        act = d['action']
        if act == 'models':
            kw = (d.get('keyword') or '').strip()
            recs = self.env['ir.model'].sudo().search(
                ['|', ('model', 'ilike', kw), ('name', 'ilike', kw)], limit=60)
            return [{'model': r.model, 'name': r.name} for r in recs
                    if not r.transient and not r.model.startswith(BLOCKED_PREFIXES)][:40]
        model = d.get('model') or ''
        rule = self._check(model, 'read')
        Model = self.env[model]
        maxr = rule.max_records or 30
        try:
            with self.env.cr.savepoint():
                if act == 'fields':
                    info = Model.fields_get(attributes=['string', 'type', 'required', 'relation', 'selection'])
                    kw = (d.get('keyword') or '').lower()
                    out = {}
                    for n, f in info.items():
                        if f['type'] in SKIP_TYPES or SENSITIVE.search(n):
                            continue
                        if kw and kw not in n.lower() and kw not in (f.get('string') or '').lower():
                            continue
                        out[n] = f
                        if len(out) >= 150:
                            break
                    return out
                scope = self._scope_domain(Model, rule)
                domain = self._domain(d) + scope
                if act == 'count':
                    return {'count': Model.search_count(domain)}
                if act == 'group':
                    return self._run_group(Model, d, domain)
                limit = self._limit(d.get('limit'), 10, maxr)
                order = self._json_arg(d.get('order'))
                if order is not None and not isinstance(order, str):
                    raise UserError('Invalid order parameter')
                total = Model.search_count(domain)
                rows = Model.search_read(domain, self._clean_fields(Model, d.get('fields')),
                                         limit=limit, order=order or None)
                rows = self._apply_field_rules(Model, rows)
                return {'total_matching': total, 'returned': len(rows), 'records': rows}
        except AccessError as e:
            return {'error': 'Access denied: %s' % e.args[0]}
        except UserError as e:
            return {'error': e.args[0]}
        except Exception as e:
            return {'error': str(e)}

    def _run_group(self, Model, d, domain):
        groupby = self._string_list(d.get('groupby'), 'groupby')[:3]
        restricted = set(self._field_rules(Model).mapped('field_name'))
        for g in groupby:
            fname = next(iter(g.split(':')))
            if fname not in Model._fields or SENSITIVE.search(fname) or fname in restricted:
                raise UserError('Invalid groupby %s' % g)
        aggregates = self._string_list(d.get('aggregates'), 'aggregates')
        aggs = []
        for a in aggregates:
            fname, _sep, fn = a.partition(':')
            if fname in Model._fields and fn in AGG_FUNCS and not SENSITIVE.search(fname) and fname not in restricted:
                aggs.append('%s:%s' % (fname, fn))
        aggs.append('__count')
        limit = self._limit(d.get('limit'), 50, 100)
        order = self._json_arg(d.get('order'))
        if order is not None and not isinstance(order, str):
            raise UserError('Invalid order parameter')
        rows = Model._read_group(domain, groupby, aggs, order=order or None, limit=limit)
        keys = groupby + aggs
        return {'groups': [{k: self._jsonable(v) for k, v in zip(keys, row)} for row in rows]}

    # ---------- navigation (opens screens, changes nothing) ----------
    def _run_open(self, d):
        kw = str(d.get('menu') or '').strip()
        if kw:
            Menu = self.env['ir.ui.menu']
            roots = Menu.search([('parent_id', '=', False)])
            hit = roots.filtered(lambda m: kw.lower() in (m.name or '').lower())[:1]
            if not hit:
                hit = Menu.search([('name', 'ilike', kw), ('action', '!=', False)], limit=1)
            if hit:
                return {'navigate': {'kind': 'menu', 'menu_id': hit.id, 'name': hit.name}}
            return {'error': 'Menu not found', 'available_apps': roots.mapped('name')}
        model = d.get('model') or ''
        rule = self._check(model, 'read')
        Model = self.env[model]
        scope = self._scope_domain(Model, rule)
        res_id = self._json_arg(d.get('res_id'))
        if isinstance(res_id, str) and res_id.strip().isdigit():
            res_id = int(res_id)
        if isinstance(res_id, int) and res_id:
            if not Model.search_count(scope + [('id', '=', res_id)]):
                return {'error': 'Record not found'}
            action = {'type': 'ir.actions.act_window', 'res_model': model, 'res_id': res_id,
                      'views': [[False, 'form']], 'target': 'current'}
            return {'navigate': {'kind': 'window', 'action': action}}
        domain = self._domain(d) + scope
        try:
            with self.env.cr.savepoint():
                count = Model.search_count(domain)
        except Exception as e:
            return {'error': str(e)}
        action = {
            'type': 'ir.actions.act_window',
            'name': str(d.get('title') or Model._description or model)[:80],
            'res_model': model,
            'views': [[False, 'list'], [False, 'form']],
            'domain': domain,
            'target': 'current',
        }
        return {'navigate': {'kind': 'window', 'action': action, 'count': count}}

    # ---------- fill the open form (client side only, nothing saved) ----------
    def _run_fill(self, d, context):
        ctx = context or {}
        model = ctx.get('model')
        if ctx.get('view_type') != 'form' or not isinstance(model, str) or model not in self.env:
            return {'error': 'No form is open on the screen. Tell the user to open the form first.'}
        Model = self.env[model]
        restricted = set(self._field_rules(Model).mapped('field_name'))
        values = d.get('values')
        if not isinstance(values, dict) or not values:
            return {'error': 'No values given'}
        out, skipped = {}, {}
        for name, v in values.items():
            f = Model._fields.get(name)
            if not f or name == 'active' or SENSITIVE.search(name) or name in restricted:
                skipped[name] = 'unknown or forbidden field'
                continue
            if f.readonly:
                skipped[name] = 'read-only field'
                continue
            try:
                item = self._fill_value(f, v)
            except (ValueError, TypeError, UserError) as e:
                skipped[name] = str(e.args[0] if e.args else e)
                continue
            if item is None:
                skipped[name] = 'type %s not supported or no match' % f.type
            else:
                out[name] = item
        if not out:
            return {'error': 'Nothing could be filled', 'skipped': skipped}
        return {'fill': {'model': model, 'values': out}, 'skipped': skipped}

    def _fill_value(self, f, v):
        t = f.type
        if t in ('char', 'text', 'html'):
            return {'type': t, 'value': str(v)}
        if t == 'integer':
            return {'type': t, 'value': int(float(str(v).replace(',', '')))}
        if t in ('float', 'monetary'):
            return {'type': t, 'value': float(str(v).replace(',', ''))}
        if t == 'boolean':
            return {'type': t, 'value': str(v).lower() in ('1', 'true', 'yes', 'y')}
        if t == 'selection':
            options = dict(f._description_selection(self.env))
            if v in options:
                return {'type': t, 'value': v}
            for key, label in options.items():
                if str(label).strip().lower() == str(v).strip().lower():
                    return {'type': t, 'value': key}
            return None
        if t == 'date':
            return {'type': t, 'value': str(fields.Date.to_date(str(v)))}
        if t == 'datetime':
            local = fields.Datetime.to_datetime(str(v))
            tz = pytz.timezone(self.env.user.tz or 'UTC')
            utc = tz.localize(local).astimezone(pytz.utc).replace(tzinfo=None)
            return {'type': t, 'value': fields.Datetime.to_string(utc)}
        if t == 'many2one':
            Co = self.env[f.comodel_name]
            if isinstance(v, int) or str(v).isdigit():
                rec = Co.search([('id', '=', int(v))], limit=1)
            else:
                found = Co.name_search(str(v), limit=1)
                rec = Co.browse(found) if found else Co
            if not rec:
                return None
            return {'type': t, 'value': rec.id, 'display': rec.display_name}
        return None

    # ---------- write proposals ----------
    def _propose(self, d):
        kind, model = d['action'], d.get('model') or ''
        rule = self._check(model, kind)
        Model = self.env[model]
        scope = self._scope_domain(Model, rule)
        payload = {'model': model}
        if kind in ('create', 'write'):
            values = clean_values(Model, d.get('values'))
            if not values:
                raise UserError('No valid values given')
            if kind == 'create' and rule.owner_field and rule.owner_field in Model._fields and rule.owner_field not in values:
                values[rule.owner_field] = self.env.user.id
            payload['values'] = values
        if kind in ('write', 'call'):
            raw_ids = self._json_arg(d.get('ids')) or []
            if isinstance(raw_ids, (int, float)) and not isinstance(raw_ids, bool):
                raw_ids = [raw_ids]
            if not isinstance(raw_ids, list):
                raise UserError('Invalid record ids')
            try:
                ids = [int(i) for i in raw_ids][:20]
            except (TypeError, ValueError):
                raise UserError('Invalid record ids')
            if not ids:
                raise UserError('No record ids given')
            if kind in ('write', 'call'):
                allowed = Model.search(scope + [('id', 'in', ids)])
                if set(allowed.ids) != set(ids):
                    raise UserError('Some records are outside your allowed data scope.')
                ids = allowed.ids
            payload['ids'] = ids
        if kind == 'call':
            method = d.get('method')
            if method not in WORKFLOWS.get(model, []):
                raise UserError('Method not allowed. Allowed: %s' % WORKFLOWS.get(model, []))
            payload['method'] = method
            params = d.get('params') if isinstance(d.get('params'), dict) else {}
            payload['params'] = {k: v for k, v in params.items() if k in PARAMS.get(method, ())}
        summary = d.get('summary') or '%s %s' % (kind, model)
        self._log_audit('propose', model, None, {'kind': kind, 'summary': summary[:200]})
        rec = self.env['ai.pending.action'].sudo().create({
            'user_id': self.env.user.id, 'kind': kind, 'model_name': model,
            'summary': summary[:250], 'payload': json.dumps(payload, default=str)})
        return rec, payload

    # ---------- conversations ----------
    def _conversation(self, create=True):
        Conv = self.env['ai.conversation'].sudo()
        conv = Conv.search([('user_id', '=', self.env.user.id), ('active', '=', True)], limit=1)
        if not conv and create:
            conv = Conv.create({'user_id': self.env.user.id})
        return conv

    def _save(self, conv, role, content, pending=None):
        return self.env['ai.message'].sudo().create({
            'conversation_id': conv.id, 'role': role, 'content': content,
            'pending_id': pending.id if pending else False})

    @api.model
    def history(self):
        conv = self._conversation(create=False)
        out = []
        for m in conv.message_ids.sorted('id')[-60:]:
            item = {'role': m.role, 'content': m.content}
            if m.pending_id:
                item.update(pendingId=m.pending_id.id, details=m.pending_id.payload,
                            status=m.pending_id.state)
            out.append(item)
        return out

    @api.model
    def new_conversation(self):
        conv = self._conversation(create=False)
        if conv:
            conv.active = False
        return True

    @staticmethod
    def _clean_attachments(attachments):
        out = []
        for a in (attachments or [])[:MAX_FILES]:
            if not isinstance(a, dict) or a.get('mimetype') not in FILE_TYPES:
                raise UserError('Only images (png, jpg, webp, gif) and PDF files are supported.')
            data = a.get('data') or ''
            if not data or len(data) > MAX_B64:
                raise UserError('File too large or empty (max about 8 MB).')
            out.append({'name': str(a.get('name') or 'file')[:80], 'mimetype': a['mimetype'], 'data': data})
        return out

    # ---------- main entry ----------
    @api.model
    def chat(self, provider_id, text, context=None, attachments=None):
        provider = self.env['ai.provider'].sudo().browse(int(provider_id or 0)).exists()
        if not provider or not provider.active:
            raise UserError('Select an active AI provider first (Settings > AI Assistant).')
        if not self._check_quota():
            raise UserError('You have reached your daily AI request limit. Please try again tomorrow.')
        text = (text or '').strip()
        files = self._clean_attachments(attachments)
        if not text and not files:
            raise UserError('Empty message')
        conv = self._conversation()
        self._log_audit('chat', 'ai.conversation', conv.id, {'text': text[:200]})
        shown = text + ''.join('\n[file: %s]' % f['name'] for f in files)
        self._save(conv, 'user', shown.strip())
        convo = [{'role': m.role, 'content': m.content} for m in conv.message_ids.sorted('id')[-20:]]
        if files:
            convo[-1]['attachments'] = files
        system = self._system(context)
        for _step in range(MAX_STEPS):
            raw = provider._complete_chain(system, convo)
            d = self._parse(raw)
            act = (d or {}).get('action')
            if act in (None, 'reply'):
                msg = (d or {}).get('message') or raw
                self._save(conv, 'assistant', msg)
                return {'type': 'reply', 'message': msg}
            if act in ('models', 'fields', 'search', 'count', 'group'):
                try:
                    result = self._run_read(d)
                except UserError as e:
                    result = {'error': e.args[0]}
                convo += [{'role': 'assistant', 'content': raw},
                          {'role': 'user', 'content': 'TOOL_RESULT: ' + json.dumps(result, default=str)[:14000]}]
                continue
            if act == 'open':
                try:
                    result = self._run_open(d)
                except UserError as e:
                    result = {'error': e.args[0]}
                if 'navigate' in result:
                    msg = d.get('message') or 'Opening...'
                    self._save(conv, 'assistant', msg)
                    return {'type': 'navigate', 'message': msg, 'navigate': result['navigate']}
                convo += [{'role': 'assistant', 'content': raw},
                          {'role': 'user', 'content': 'TOOL_RESULT: ' + json.dumps(result, default=str)[:6000]}]
                continue
            if act == 'fill':
                try:
                    result = self._run_fill(d, context)
                except UserError as e:
                    result = {'error': e.args[0]}
                if 'fill' in result:
                    msg = d.get('message') or 'Done, review the form and save.'
                    if result.get('skipped'):
                        msg += '\n(Not filled: %s)' % ', '.join(result['skipped'])
                    self._save(conv, 'assistant', msg)
                    return {'type': 'fill', 'message': msg, 'fill': result['fill']}
                convo += [{'role': 'assistant', 'content': raw},
                          {'role': 'user', 'content': 'TOOL_RESULT: ' + json.dumps(result, default=str)[:6000]}]
                continue
            if act in ('create', 'write', 'call'):
                try:
                    rec, payload = self._propose(d)
                except UserError as e:
                    convo += [{'role': 'assistant', 'content': raw},
                              {'role': 'user', 'content': 'TOOL_RESULT: ' + json.dumps({'error': e.args[0]})}]
                    continue
                self._save(conv, 'assistant', 'Proposed: ' + rec.summary, pending=rec)
                return {'type': 'confirm', 'pending_id': rec.id, 'summary': rec.summary,
                        'details': json.dumps(payload, ensure_ascii=False, default=str)}
            convo += [{'role': 'assistant', 'content': raw},
                      {'role': 'user', 'content': 'TOOL_RESULT: {"error":"unknown action"}'}]
        msg = 'I could not finish this request. Please rephrase it.'
        self._save(conv, 'assistant', msg)
        return {'type': 'reply', 'message': msg}

    @api.model
    def decide(self, pending_id, approve):
        rec = self.env['ai.pending.action'].sudo().browse(int(pending_id)).exists()
        if not rec or rec.user_id != self.env.user:
            raise UserError('Action not found.')
        nav = None
        if approve:
            required = self._approval_required(rec.model_name, rec.kind, rec.payload)
            if required:
                rec.state = 'awaiting_approval'
                self._log_audit(
                    'approval_required', rec.model_name, None,
                    {'pending_id': rec.id, 'approver': required}, status='pending')
                msg = 'This action requires approval from %s.' % required
                self._save(conv, 'assistant', msg)
                return {'type': 'reply', 'message': msg}
            self._log_audit('execute', rec.model_name, None, {'pending_id': rec.id})
            result = rec.action_execute()
            msg = result['message']
            if result.get('action'):
                nav = {'kind': 'window', 'action': result['action']}
        else:
            self._log_audit('cancel', rec.model_name, None, {'pending_id': rec.id})
            rec.action_cancel()
            msg = 'Cancelled.'
        conv = self._conversation()
        self._save(conv, 'assistant', msg)
        if nav:
            return {'type': 'navigate', 'message': msg, 'navigate': nav}
        return {'type': 'reply', 'message': msg}
