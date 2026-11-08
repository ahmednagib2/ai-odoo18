{
    'name': 'AI Assistant',
    'version': '18.0.4.3.0',
    'category': 'Productivity',
    'summary': 'AI copilot in the navbar (OpenAI, Gemini, Claude, OpenClaw / any OpenAI-compatible API) with access tiers, form drafts and safe actions. Never deletes.',
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
