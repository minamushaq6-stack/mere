{
    'name': 'Branch Stock Transfer (Inter-company, no SO/PO)',
    'version': '19.0.1.0.1',
    'category': 'Inventory/Inventory',
    'summary': 'Transfer stock from the main company to a separate branch company '
               'without sales/purchase, with notifications to both sides.',
    'depends': ['stock', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'data/sequence.xml',
        'views/ic_transfer_views.xml',
        'views/res_company_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
