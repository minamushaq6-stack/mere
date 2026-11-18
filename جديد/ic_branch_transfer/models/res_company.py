from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    ic_transfer_require_approval = fields.Boolean(
        string='Require approval for branch transfers',
        help='If enabled, a transfer created from this company must be approved '
             'by a Stock Manager before the delivery/receipt are generated.')
    ic_transfer_notify_user_ids = fields.Many2many(
        'res.users', 'ic_company_notify_users_rel', 'company_id', 'user_id',
        string='Branch transfer notification users',
        help='Users of THIS company who receive an activity + message for every '
             'branch transfer event (approval, shipment, receipt).')
