# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_is_zero


class InterwarehouseReturnWizard(models.TransientModel):
    """Controlled 'Return to Source': moves the in-transit quantity back to the
    source warehouse through a standard picking (Transit -> Source/Stock).

    This is an explicit, audited action - quantities are never returned
    automatically and never cancelled silently.
    """

    _name = 'ff.interwarehouse.return.wizard'
    _description = 'Return to Source'

    transfer_id = fields.Many2one(
        'ff.interwarehouse.transfer', string='Transfer', required=True, readonly=True)
    line_ids = fields.One2many(
        'ff.interwarehouse.return.wizard.line', 'wizard_id', string='Products to Return')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        transfer = self.env['ff.interwarehouse.transfer'].browse(
            self.env.context.get('default_transfer_id'))
        if transfer:
            res['transfer_id'] = transfer.id
            lines = []
            for line in transfer.line_ids:
                qty = line.in_transit_qty
                if qty > 0:
                    lines.append((0, 0, {
                        'line_id': line.id,
                        'product_id': line.product_id.id,
                        'product_uom_id': line.product_uom_id.id,
                        'in_transit_qty': qty,
                        'qty': qty,
                    }))
            if lines:
                res['line_ids'] = lines
        return res

    def action_return(self):
        self.ensure_one()
        transfer = self.transfer_id
        lane = transfer.lane_id
        source = self.env['stock.warehouse'].sudo().browse(
            transfer.source_warehouse_id.id)
        receipt_type = source.ff_receipt_picking_type_id
        if not receipt_type:
            raise UserError(_('The source warehouse has no Inter-Warehouse Receipt '
                              'operation type. Run the warehouse setup first.'))

        move_vals = []
        for wline in self.line_ids:
            if float_is_zero(wline.qty, precision_rounding=wline.product_uom_id.rounding):
                continue
            move_vals.append((0, 0, {
                'name': _('%s (return to source)', wline.product_id.display_name),
                'product_id': wline.product_id.id,
                'product_uom_qty': wline.qty,
                'product_uom': wline.product_uom_id.id,
                'location_id': lane.transit_location_id.id,
                'location_dest_id': source.lot_stock_id.id,
                'picking_type_id': receipt_type.id,
                'company_id': transfer.company_id.id,
            }))
        if not move_vals:
            raise UserError(_('No quantity to return.'))

        # Internal system creation with fixed values (lane + source warehouse);
        # the resulting picking is protected by the inter-warehouse record rules.
        picking = self.env['stock.picking'].sudo().create({
            'picking_type_id': receipt_type.id,
            'location_id': lane.transit_location_id.id,
            'location_dest_id': source.lot_stock_id.id,
            'origin': '%s (return)' % transfer.name,
            'move_ids': move_vals,
            'ff_interwarehouse_transfer_id': transfer.id,
            'ff_interwarehouse_role': 'return',
            'ff_source_warehouse_id': transfer.source_warehouse_id.id,
            'ff_destination_warehouse_id': transfer.destination_warehouse_id.id,
            'ff_lane_id': lane.id,
        })
        picking.sudo().action_confirm()
        picking.sudo().action_assign()
        transfer.message_post(body=_(
            'Return to source picking %s created (transit -> %s).',
            picking.name, source.name))
        return {'type': 'ir.actions.act_window_close'}


class InterwarehouseReturnWizardLine(models.TransientModel):
    _name = 'ff.interwarehouse.return.wizard.line'
    _description = 'Return to Source Line'

    wizard_id = fields.Many2one('ff.interwarehouse.return.wizard', ondelete='cascade')
    line_id = fields.Many2one('ff.interwarehouse.transfer.line', string='Transfer Line', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    product_uom_id = fields.Many2one('uom.uom', string='Unit of Measure', readonly=True)
    in_transit_qty = fields.Float(string='In Transit', readonly=True)
    qty = fields.Float(string='Quantity to Return', default=0.0)
