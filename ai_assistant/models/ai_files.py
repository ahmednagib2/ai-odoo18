import base64
import html
import io
import re
import zipfile

from odoo import api, models
from odoo.exceptions import UserError

from .ai_assistant import MAX_B64, MAX_FILES

# Sent as-is to the model (vision / PDF / audio understanding)
INLINE_TYPES = (
    'image/png', 'image/jpeg', 'image/webp', 'image/gif', 'application/pdf',
    'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav', 'audio/ogg', 'audio/webm',
    'audio/mp4', 'audio/aac', 'audio/flac', 'audio/x-m4a', 'audio/m4a',
)
# Converted to text on the server and added to the message
TEXT_EXT = ('txt', 'csv', 'tsv', 'json', 'xml', 'md', 'log', 'docx', 'xlsx')
MAX_TEXT = 20000


class AiAssistantFiles(models.AbstractModel):
    _inherit = 'ai.assistant'

    @staticmethod
    def _clean_attachments(attachments):
        out = []
        for a in (attachments or [])[:MAX_FILES]:
            if not isinstance(a, dict) or a.get('mimetype') not in INLINE_TYPES:
                raise UserError('Unsupported file type: %s' % (a.get('name') if isinstance(a, dict) else ''))
            data = a.get('data') or ''
            if not data or len(data) > MAX_B64:
                raise UserError('File too large or empty (max about 8 MB).')
            out.append({'name': str(a.get('name') or 'file')[:80], 'mimetype': a['mimetype'], 'data': data})
        return out

    @staticmethod
    def _ext(name):
        return name.rsplit('.', 1)[-1].lower() if '.' in name else ''

    @staticmethod
    def _extract_text(name, ext, data):
        try:
            raw = base64.b64decode(data)
            if ext == 'docx':
                xml = zipfile.ZipFile(io.BytesIO(raw)).read('word/document.xml').decode('utf-8', 'replace')
                xml = xml.replace('</w:p>', '\n').replace('<w:tab/>', '\t')
                text = html.unescape(re.sub(r'<[^>]+>', '', xml))
            elif ext == 'xlsx':
                try:
                    import openpyxl
                except ImportError:
                    raise UserError('Excel files need the openpyxl python package on the server.')
                wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
                lines = []
                for ws in wb.worksheets[:5]:
                    lines.append('## sheet: %s' % ws.title)
                    for i, row in enumerate(ws.iter_rows(values_only=True)):
                        if i >= 300:
                            lines.append('... (truncated)')
                            break
                        lines.append('\t'.join('' if c is None else str(c) for c in row))
                text = '\n'.join(lines)
            else:
                try:
                    text = raw.decode('utf-8-sig')
                except UnicodeDecodeError:
                    text = raw.decode('cp1256', 'replace')
        except UserError:
            raise
        except Exception as e:
            raise UserError('Cannot read the file %s: %s' % (name, e))
        return text[:MAX_TEXT]

    @api.model
    def chat(self, provider_id, text, context=None, attachments=None):
        rest, blocks = [], []
        for a in (attachments or [])[:MAX_FILES]:
            if not isinstance(a, dict):
                continue
            name = str(a.get('name') or 'file')
            ext = self._ext(name)
            if ext in TEXT_EXT or str(a.get('mimetype') or '').startswith('text/'):
                blocks.append('[Attached file: %s]\n%s' % (name, self._extract_text(name, ext, a.get('data') or '')))
            else:
                rest.append(a)
        if blocks:
            text = ((text or '') + '\n\n' + '\n\n'.join(blocks)).strip()
        return super().chat(provider_id, text, context, rest)
