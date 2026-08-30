# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    ff_dispatch_picking_type_id = fields.Many2one(
        'stock.picking.type', string='Inter-Warehouse Dispatch Type', copy=False)
    ff_receipt_picking_type_id = fields.Many2one(
        'stock.picking.type', string='Inter-Warehouse Receipt Type', copy=False)
    ff_interwarehouse_responsible_user_ids = fields.Many2many(
        'res.users', string='Inter-Warehouse Responsible Users')
    ff_interwarehouse_outgoing_lane_count = fields.Integer(
        string='Outgoing Lanes', compute='_compute_ff_lane_counts')
    ff_interwarehouse_incoming_lane_count = fields.Integer(
        string='Incoming Lanes', compute='_compute_ff_lane_counts')

    @api.depends('company_id')
    def _compute_ff_lane_counts(self):
        Lane = self.env['ff.interwarehouse.lane']
        for warehouse in self:
            warehouse.ff_interwarehouse_outgoing_lane_count = Lane.search_count([
                ('source_warehouse_id', '=', warehouse.id), ('active', '=', True)])
            warehouse.ff_interwarehouse_incoming_lane_count = Lane.search_count([
                ('destination_warehouse_id', '=', warehouse.id), ('active', '=', True)])

    @api.model_create_multi
    def create(self, vals_list):
        # Let Odoo's own create() build the standard warehouse locations, routes
        # and operation types first; we only add our inter-warehouse bits after.
        warehouses = super().create(vals_list)
        for warehouse in warehouses:
            warehouse._ff_setup_interwarehouse_ops()
        if self.env['ir.config_parameter'].sudo().get_param(
                'ff_interwarehouse_control.auto_create_lanes', 'True') == 'True':
            for warehouse in warehouses:
                self.env['ff.interwarehouse.lane']._ff_setup_for_company(
                    warehouse.company_id)
        return warehouses

    def write(self, vals):
        if 'active' in vals and not vals.get('active'):
            for warehouse in self:
                warehouse._check_ff_archive_allowed()
        return super().write(vals)

    def _check_ff_archive_allowed(self):
        """A warehouse with open inter-warehouse transfers or in-transit stock
        cannot be archived (would break traceability)."""
        self.ensure_one()
        Lane = self.env['ff.interwarehouse.lane']
        Transfer = self.env['ff.interwarehouse.transfer']
        lanes = Lane.search([
            '|',
            ('source_warehouse_id', '=', self.id),
            ('destination_warehouse_id', '=', self.id),
        ])
        open_transfer = Transfer.search([
            ('state', 'not in', ('done', 'cancelled')),
            '|',
            ('source_warehouse_id', '=', self.id),
            ('destination_warehouse_id', '=', self.id),
        ], limit=1)
        if open_transfer:
            raise UserError(
                _('Warehouse %s cannot be archived while inter-warehouse transfers '
                  'are still open.', self.name))
        for lane in lanes:
            transit = lane.transit_location_id
            if transit and self.env['stock.quant'].search_count(
                    [('location_id', '=', transit.id)], limit=1):
                raise UserError(
                    _('Warehouse %s cannot be archived while there is stock in '
                      'transit on its lanes.', self.name))
        return True

    def _ff_setup_interwarehouse_ops(self):
        """Idempotently create the Inter-Warehouse Dispatch / Receipt operation
        types for this warehouse. ``stock.picking.type.create`` automatically
        creates the linked ``ir.sequence`` from ``sequence_code``."""
        self.ensure_one()
        if not self.ff_dispatch_picking_type_id:
            self.ff_dispatch_picking_type_id = self.env['stock.picking.type'].create({
                'name': 'Inter-Warehouse Dispatch',
                'code': 'internal',
                'warehouse_id': self.id,
                'sequence_code': 'IWD',
                'default_location_src_id': self.lot_stock_id.id,
                'default_location_dest_id': self.lot_stock_id.id,
                'create_backorder': 'always',
                'company_id': self.company_id.id,
            })
        if not self.ff_receipt_picking_type_id:
            self.ff_receipt_picking_type_id = self.env['stock.picking.type'].create({
                'name': 'Inter-Warehouse Receipt',
                'code': 'internal',
                'warehouse_id': self.id,
                'sequence_code': 'IWR',
                'default_location_src_id': self.lot_stock_id.id,
                'default_location_dest_id': self.lot_stock_id.id,
                'create_backorder': 'always',
                'company_id': self.company_id.id,
            })
        return True

    def action_open_ff_outgoing_lanes(self):
        self.ensure_one()
        return self._ff_open_lane_action(_('Outgoing Lanes'))

    def action_open_ff_incoming_lanes(self):
        self.ensure_one()
        return self._ff_open_lane_action(_('Incoming Lanes'))

    def _ff_open_lane_action(self, title):
        self.ensure_one()
        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'ff.interwarehouse.lane',
            'view_mode': 'list,form',
            'domain': [
                '|',
                ('source_warehouse_id', '=', self.id),
                ('destination_warehouse_id', '=', self.id),
            ],
        }
