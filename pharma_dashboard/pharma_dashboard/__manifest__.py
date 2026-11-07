{
    "name": "Pharma Management Dashboard",
    "summary": "لوحة تحكم شاملة: الصناديق، الذمم، المبيعات، المخزون، الأرباح وحصص الشركاء",
    "version": "19.0.1.0.0",
    "category": "Reporting",
    "author": "Custom",
    "license": "LGPL-3",
    "depends": ["base", "web", "account", "sale", "purchase", "stock"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pharma_dashboard/static/src/dashboard.js",
            "pharma_dashboard/static/src/dashboard.xml",
            "pharma_dashboard/static/src/dashboard.scss",
        ],
    },
    "application": True,
    "installable": True,
}
