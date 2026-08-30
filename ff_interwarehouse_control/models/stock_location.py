# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class StockLocation(models.Model):
    _inherit = 'stock.location'

    ff_interwarehouse_lane_id = fields.Many2one(
        'ff.interwarehouse.lane', string='Inter-Warehouse Lane',
        ondelete='restrict', index=True, copy=False)

    def unlink(self):
        for location in self:
            if location.ff_interwarehouse_lane_id:
                quant_count = self.env['stock.quant'].search_count(
                    [('location_id', '=', location.id)], limit=1)
                move_line_count = self.env['stock.move.line'].search_count(
                    ['|',
                     ('location_id', '=', location.id),
                     ('location_dest_id', '=', location.id)], limit=1)
                if quant_count or move_line_count:
                    raise UserError(
                        _('This transit location cannot be deleted because it has '
                          'stock or movement history. Archive the lane instead.'))
        return super().unlink()
