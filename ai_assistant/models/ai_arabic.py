from odoo import fields, models


class AiProviderArabic(models.Model):
    """تعريب حقول مزود الذكاء الاصطناعي (تُدمج الخصائص مع التعريف الأصلي)."""
    _inherit = 'ai.provider'
    _description = 'مزود الذكاء الاصطناعي'

    name = fields.Char(string='الاسم')
    sequence = fields.Integer(string='الترتيب', help='تتم تجربة المزودين بهذا الترتيب عند انشغال مزود أو فشله.')
    active = fields.Boolean(string='نشط')
    provider_type = fields.Selection([
        ('openai', 'OpenAI (ChatGPT)'),
        ('gemini', 'Google Gemini'),
        ('anthropic', 'Anthropic Claude'),
        ('compatible', 'متوافق مع OpenAI (OpenClaw وOpenRouter وOllama وDeepSeek وGroq...)'),
    ], string='نوع المزود')
    api_key = fields.Char(string='مفتاح API')
    base_url = fields.Char(string='رابط الخدمة', help='اتركه فارغاً لاستخدام الرابط الافتراضي لنوع المزود.')
    model_name = fields.Char(string='اسم الموديل',
                             help='أي معرّف موديل، مثل gpt-4.1-mini أو gemini-3.8-flash أو claude-sonnet-4-5')
    temperature = fields.Float(string='درجة الإبداع (Temperature)')
    max_tokens = fields.Integer(string='أقصى عدد توكنز',
                                help='يُستخدم دائماً 4096 على الأقل حتى تستطيع نماذج التفكير إكمال إجابتها.')
    timeout = fields.Integer(string='المهلة (بالثواني)')
    reasoning = fields.Selection([
        ('default', 'افتراضي الموديل'),
        ('low', 'منخفض (الأسرع)'),
        ('medium', 'متوسط'),
        ('high', 'عالٍ (الأدق والأبطأ)'),
    ], string='مستوى التفكير',
        help='لموديلات Gemini 3.x فقط: مقدار تفكير الموديل قبل الإجابة. كلما قلّ كان أسرع بكثير.')
