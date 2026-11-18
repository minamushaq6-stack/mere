import logging
from collections import defaultdict

from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class IcStockTransfer(models.Model):
    _name = 'ic.stock.transfer'
    _description = 'Branch Stock Transfer'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('to_approve', 'Waiting Approval'),
        ('confirmed', 'Confirmed'),
        ('shipped', 'Shipped (In Transit)'),
        ('done', 'Received'),
        ('cancel', 'Cancelled'),
    ], default='draft', tracking=True, copy=False, required=True)
    company_id = fields.Many2one(
        'res.company', string='From Company', required=True,
        default=lambda self: self.env.company, readonly=True)
    source_warehouse_id = fields.Many2one(
        'stock.warehouse', string='From Warehouse', required=True,
        domain="[('company_id', '=', company_id)]")
    dest_company_id = fields.Many2one(
        'res.company', string='To Company (Branch)', required=True,
        domain="[('id', '!=', company_id)]", tracking=True)
    dest_warehouse_id = fields.Many2one(
        'stock.warehouse', string='To Warehouse',
        domain="[('company_id', '=', dest_company_id)]",
        help='Leave empty to use the first warehouse of the branch company.')
    date = fields.Datetime(default=fields.Datetime.now)
    note = fields.Text()
    line_ids = fields.One2many('ic.stock.transfer.line', 'transfer_id', string='Products', copy=True)
    out_picking_id = fields.Many2one('stock.picking', string='Delivery', readonly=True, copy=False)
    in_picking_id = fields.Many2one('stock.picking', string='Receipt', readonly=True, copy=False)

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('ic.stock.transfer') or 'New'
        return super().create(vals_list)

    @api.constrains('company_id', 'dest_company_id', 'source_warehouse_id', 'dest_warehouse_id')
    def _check_companies(self):
        for rec in self:
            if rec.company_id == rec.dest_company_id:
                raise ValidationError(_('The destination company must be different from the source company.'))
            if rec.source_warehouse_id.company_id != rec.company_id:
                raise ValidationError(_('The source warehouse must belong to the source company.'))
            if rec.dest_warehouse_id and rec.dest_warehouse_id.company_id != rec.dest_company_id:
                raise ValidationError(_('The destination warehouse must belong to the branch company.'))

    @api.onchange('company_id')
    def _onchange_company_id(self):
        wh = self.env['stock.warehouse'].search([('company_id', '=', self.company_id.id)], limit=1)
        self.source_warehouse_id = wh

    @api.onchange('dest_company_id')
    def _onchange_dest_company_id(self):
        self.dest_warehouse_id = False

    def unlink(self):
        if any(rec.state not in ('draft', 'cancel') for rec in self):
            raise UserError(_('You can only delete draft or cancelled transfers.'))
        return super().unlink()

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                continue
            if not rec.line_ids:
                raise UserError(_('Please add at least one product.'))
            if rec.company_id.sudo().ic_transfer_require_approval:
                rec.state = 'to_approve'
                rec._notify(rec.company_id, _('Branch transfer %s needs approval', rec.name),
                            _('Transfer %(name)s to %(branch)s is waiting for approval.',
                              name=rec.name, branch=rec.dest_company_id.name))
            else:
                rec._do_confirm()
        return True

    def action_approve(self):
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError(_('Only Stock Managers can approve branch transfers.'))
        for rec in self:
            if rec.state == 'to_approve':
                rec._do_confirm()
        return True

    def action_draft(self):
        for rec in self:
            if rec.state in ('cancel', 'to_approve'):
                rec.state = 'draft'
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state in ('shipped', 'done'):
                raise UserError(_('A shipped transfer cannot be cancelled.'))
            for picking in (rec.out_picking_id | rec.in_picking_id).sudo():
                if picking.state not in ('done', 'cancel'):
                    picking.action_cancel()
            rec.state = 'cancel'
        return True

    def _get_transit_location(self):
        loc = self.env.ref('stock.stock_location_inter_company', raise_if_not_found=False)
        if not loc:
            loc = self.env['stock.location'].sudo().with_context(active_test=False).search(
                [('usage', '=', 'transit'), ('company_id', '=', False)], limit=1)
        if not loc:
            raise UserError(_('Inter-company transit location not found. Enable Multi-Companies '
                              'and check Inventory > Configuration > Locations.'))
        if not loc.active:
            loc.sudo().active = True
        return loc.sudo()

    def _get_dest_warehouse(self):
        self.ensure_one()
        wh = self.dest_warehouse_id or self.env['stock.warehouse'].sudo().search(
            [('company_id', '=', self.dest_company_id.id)], limit=1)
        if not wh:
            raise UserError(_('The branch company has no warehouse.'))
        return wh.sudo()

    def _do_confirm(self):
        self.ensure_one()
        transit = self._get_transit_location()
        src_wh = self.source_warehouse_id.sudo()
        dst_wh = self._get_dest_warehouse()
        Picking = self.env['stock.picking'].sudo()

        out_moves, in_moves = [], []
        for line in self.line_ids:
            base = {
                'product_id': line.product_id.id,
                'product_uom_qty': line.quantity,
                'product_uom': line.uom_id.id,
            }
            out_moves.append(Command.create(dict(
                base, location_id=src_wh.lot_stock_id.id, location_dest_id=transit.id,
                company_id=self.company_id.id)))
            in_moves.append(Command.create(dict(
                base, location_id=transit.id, location_dest_id=dst_wh.lot_stock_id.id,
                company_id=self.dest_company_id.id)))

        out = Picking.with_company(self.company_id).create({
            'picking_type_id': src_wh.out_type_id.id,
            'location_id': src_wh.lot_stock_id.id,
            'location_dest_id': transit.id,
            'company_id': self.company_id.id,
            'origin': self.name,
            'ic_transfer_id': self.id,
            'move_ids': out_moves,
        })
        inc = Picking.with_company(self.dest_company_id).create({
            'picking_type_id': dst_wh.in_type_id.id,
            'location_id': transit.id,
            'location_dest_id': dst_wh.lot_stock_id.id,
            'company_id': self.dest_company_id.id,
            'origin': self.name,
            'ic_transfer_id': self.id,
            'move_ids': in_moves,
        })
        out.with_company(self.company_id).action_confirm()
        out.with_company(self.company_id).action_assign()
        inc.with_company(self.dest_company_id).action_confirm()

        self.write({'state': 'confirmed', 'out_picking_id': out.id, 'in_picking_id': inc.id})
        self._notify(self.company_id, _('Prepare shipment %s', self.name),
                     _('Transfer %(name)s to %(branch)s is confirmed. Delivery %(pick)s is ready to be validated.',
                       name=self.name, branch=self.dest_company_id.name, pick=out.name))
        self._notify(self.dest_company_id, _('Incoming shipment %s', self.name),
                     _('Transfer %(name)s from %(company)s was created. Receipt %(pick)s will be ready once the goods are shipped.',
                       name=self.name, company=self.company_id.name, pick=inc.name))

    # ------------------------------------------------------------------
    # Hook called from stock.picking._action_done
    # ------------------------------------------------------------------
    def _on_picking_done(self, picking):
        self.ensure_one()
        if picking.id == self.out_picking_id.id and self.state == 'confirmed':
            self._sync_receipt_quantities(picking)
            self.state = 'shipped'
            self._notify(self.dest_company_id, _('Shipment %s is on the way', self.name),
                         _('Goods of transfer %(name)s were shipped from %(company)s. '
                           'Please validate receipt %(pick)s when they arrive.',
                           name=self.name, company=self.company_id.name,
                           pick=self.in_picking_id.name))
        elif picking.id == self.in_picking_id.id and self.state == 'shipped':
            self.state = 'done'
            self._notify(self.company_id, _('Shipment %s received', self.name),
                         _('Branch %(branch)s received the goods of transfer %(name)s.',
                           branch=self.dest_company_id.name, name=self.name))

    def _sync_receipt_quantities(self, out_picking):
        """Receipt quantities follow what was really shipped."""
        self.ensure_one()
        inc = self.in_picking_id.sudo().with_company(self.dest_company_id)
        shipped = defaultdict(float)
        for move in out_picking.sudo().move_ids:
            shipped[move.product_id.id] += move.quantity
        for move in inc.move_ids:
            qty = shipped.get(move.product_id.id, 0.0)
            if qty <= 0:
                move._action_cancel()
            else:
                move.product_uom_qty = qty
        inc.action_assign()

    # ------------------------------------------------------------------
    def _notify(self, company, summary, note):
        """Activity + message (email/inbox) to the notification users of `company`."""
        self.ensure_one()
        users = company.sudo().ic_transfer_notify_user_ids
        if not users:
            return
        try:
            with self.env.cr.savepoint():
                rec = self.sudo()
                for user in users:
                    rec.activity_schedule('mail.mail_activity_data_todo',
                                          summary=summary, note=note, user_id=user.id)
                rec.message_post(body=note, subject=summary,
                                 partner_ids=users.partner_id.ids,
                                 message_type='comment', subtype_xmlid='mail.mt_comment')
        except Exception:  # never block stock operations because of a notification
            _logger.exception('Branch transfer notification failed for %s', self.name)

    def action_view_out_picking(self):
        self.ensure_one()
        return self._open_picking(self.out_picking_id)

    def action_view_in_picking(self):
        self.ensure_one()
        return self._open_picking(self.in_picking_id)

    def _open_picking(self, picking):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': picking.id,
            'view_mode': 'form',
            'target': 'current',
        }


class IcStockTransferLine(models.Model):
    _name = 'ic.stock.transfer.line'
    _description = 'Branch Stock Transfer Line'

    transfer_id = fields.Many2one('ic.stock.transfer', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', required=True,
                                 domain="[('is_storable', '=', True)]")
    quantity = fields.Float(string='Quantity', required=True, default=1.0,
                            digits='Product Unit')
    uom_id = fields.Many2one('uom.uom', string='Unit', compute='_compute_uom_id',
                             store=True, readonly=False, required=True)

    @api.depends('product_id')
    def _compute_uom_id(self):
        for line in self:
            line.uom_id = line.product_id.uom_id

    @api.constrains('quantity')
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_('Quantity must be positive.'))
