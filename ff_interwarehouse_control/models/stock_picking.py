# -*- coding: utf-8 -*-
from odoo import fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    ff_interwarehouse_transfer_id = fields.Many2one(
        'ff.interwarehouse.transfer', string='Inter-Warehouse Transfer',
        ondelete='set null', index=True, copy=True)
    ff_interwarehouse_role = fields.Selection([
        ('dispatch', 'Dispatch'),
        ('receipt', 'Receipt'),
        ('return', 'Return to Source'),
    ], string='Inter-Warehouse Role', index=True, copy=True)
    ff_source_warehouse_id = fields.Many2one(
        'stock.warehouse', string='IWT Source Warehouse', index=True, copy=True)
    ff_destination_warehouse_id = fields.Many2one(
        'stock.warehouse', string='IWT Destination Warehouse', index=True, copy=True)
    ff_lane_id = fields.Many2one(
        'ff.interwarehouse.lane', string='IWT Lane', index=True, copy=True)

    def _action_done(self):
        """After the standard stock engine has validated the pickings, feed the
        linked inter-warehouse transfer master with the real dispatched /
        received / returned quantities and drive its notifications."""
        linked = self.filtered(lambda p: p.ff_interwarehouse_transfer_id)
        result = super()._action_done()
        for picking in linked:
            if picking.state == 'done' and picking.ff_interwarehouse_transfer_id:
                picking.ff_interwarehouse_transfer_id._ff_on_picking_done(picking)
        return result
