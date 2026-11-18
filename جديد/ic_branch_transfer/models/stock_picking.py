from odoo import fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    ic_transfer_id = fields.Many2one(
        'ic.stock.transfer', string='Branch Transfer', copy=False,
        index='btree_not_null', ondelete='set null', readonly=True)

    def _action_done(self):
        res = super()._action_done()
        for picking in self.filtered(lambda p: p.state == 'done' and p.ic_transfer_id):
            picking.ic_transfer_id.sudo()._on_picking_done(picking)
        return res
