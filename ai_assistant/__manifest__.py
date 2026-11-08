{
    'name': 'المساعد الذكي (AI Assistant)',
    'version': '18.0.4.4.0',
    'category': 'Productivity',
    'summary': 'مساعد ذكي في الشريط العلوي (OpenAI وGemini وClaude وأي API متوافق) مع مستويات صلاحيات ومسودات نماذج وإجراءات آمنة. لا يحذف أي بيانات أبداً.',
    'author': 'Ahmed Nagib',
    'depends': ['base', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'security/ai_security.xml',
        'views/ai_views.xml',
        'views/ai_views_plus.xml',
        'views/ai_governance_views.xml',
        'data/ai_data.xml',
        'data/ai_cron.xml',
    ],
    'post_init_hook': 'post_init',
    'assets': {
        'web.assets_backend': [
            'ai_assistant/static/src/**/*',
        ],
    },
    'license': 'LGPL-3',
    'application': True,
    'installable': True,
}
