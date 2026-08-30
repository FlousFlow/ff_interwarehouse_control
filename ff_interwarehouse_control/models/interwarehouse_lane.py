# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class InterwarehouseLane(models.Model):
    """A directed inter-warehouse lane (e.g. ``Cairo -> Alexandria``).

    Each lane owns a dedicated transit location, so quantities in transit are
    always attributed to a single source/destination pair. The lane is also the
    security endpoint: a restricted user may see a lane (and its transit stock)
    whenever they are the source OR the destination warehouse, without ever
    gaining read access to the other warehouse.
    """

    _name = 'ff.interwarehouse.lane'
    _description = 'Inter-Warehouse Lane'
    _rec_name = 'name'
    _order = 'company_id, source_warehouse_id, destination_warehouse_id'

    name = fields.Char(string='Lane', compute='_compute_name')
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        ondelete='cascade', default=lambda self: self.env.company)
    source_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Source Warehouse', required=True, index=True)
    destination_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Destination Warehouse', required=True, index=True)
    # Stored display names so a restricted user can show the destination without
    # being able to read the destination warehouse record itself.
    source_name = fields.Char(string='Source', required=True, readonly=True, store=True)
    destination_name = fields.Char(string='Destination', required=True, readonly=True, store=True)
    transit_location_id = fields.Many2one(
        'stock.location', string='Transit Location', required=True, readonly=True,
        ondelete='restrict')
    active = fields.Boolean(string='Active', default=True)

    _sql_constraints = [
        ('lane_uniq', 'UNIQUE(company_id, source_warehouse_id, destination_warehouse_id)',
         _('A lane already exists for this source/destination pair.')),
        ('lane_source_dest_diff', 'CHECK(source_warehouse_id != destination_warehouse_id)',
         _('The source and destination warehouses of a lane cannot be the same.')),
    ]

    @api.depends('source_name', 'destination_name')
    def _compute_name(self):
        for lane in self:
            lane.name = '%s → %s' % (lane.source_name, lane.destination_name)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('company_id'):
                vals['company_id'] = self.env.company.id
            source = self.env['stock.warehouse'].browse(vals.get('source_warehouse_id'))
            destination = self.env['stock.warehouse'].browse(vals.get('destination_warehouse_id'))
            if not source or not destination:
                raise UserError(_('Source and destination warehouses are required to create a lane.'))
            if source.company_id.id != destination.company_id.id:
                raise UserError(_('Cross-company lanes are not allowed.'))
            if source.id == destination.id:
                raise UserError(_('The source and destination warehouses of a lane cannot be the same.'))
            # Fail fast on duplicates BEFORE creating any transit location
            # (keeps the setup idempotent and avoids orphan locations).
            existing = self.search([
                ('source_warehouse_id', '=', source.id),
                ('destination_warehouse_id', '=', destination.id),
                ('company_id', '=', vals['company_id']),
            ], limit=1)
            if existing:
                raise UserError(_('A lane already exists for this source/destination pair.'))
            company = self.env['res.company'].browse(vals['company_id'])
            root = company._ff_ensure_transit_root()
            if not vals.get('transit_location_id'):
                transit = self.env['stock.location'].create({
                    'name': _('Transit %s → %s', source.name, destination.name),
                    'usage': 'transit',
                    'location_id': root.id,
                    'company_id': company.id,
                    'barcode': 'IWT-%s-%s' % (source.code or source.id, destination.code or destination.id),
                })
                vals['transit_location_id'] = transit.id
            vals['source_name'] = source.name
            vals['destination_name'] = destination.name
        lanes = super().create(vals_list)
        for lane in lanes:
            lane.transit_location_id.write({'ff_interwarehouse_lane_id': lane.id})
        return lanes

    def unlink(self):
        for lane in self:
            lane._check_no_history(_('delete'))
        return super().unlink()

    def _check_no_history(self, action_label):
        """Block destroying a lane (or its transit location) once it carries
        stock history or is referenced by transfers."""
        self.ensure_one()
        if self.transit_location_id:
            quant_count = self.env['stock.quant'].search_count(
                [('location_id', '=', self.transit_location_id.id)], limit=1)
            move_line_count = self.env['stock.move.line'].search_count(
                ['|', ('location_id', '=', self.transit_location_id.id),
                     ('location_dest_id', '=', self.transit_location_id.id)], limit=1)
            if quant_count or move_line_count:
                raise UserError(
                    _('This lane cannot be %s because its transit location still has '
                      'stock or movement history. Archive the lane instead.',
                      action_label))
        transfer_count = self.env['ff.interwarehouse.transfer'].search_count(
            [('lane_id', '=', self.id)], limit=1)
        if transfer_count:
            raise UserError(
                _('This lane cannot be %s because it is referenced by inter-warehouse '
                  'transfers. Archive the lane instead.', action_label))

    def toggle_active(self):
        """Archiving a lane that still has open transfers or transit stock is not
        allowed (keeps the audit trail complete)."""
        for lane in self:
            if lane.active:
                lane._check_no_history(_('archived'))
        return super().toggle_active()

    # ------------------------------------------------------------------
    # Automatic setup helpers (idempotent)
    # ------------------------------------------------------------------
    @api.model
    def _ff_setup_all(self):
        """Create every missing lane between all active warehouses, grouped by
        company. Safe to call many times: only missing lanes are created."""
        for company in self.env['res.company'].search([]):
            self._ff_setup_for_company(company)
        return True

    @api.model
    def _ff_setup_for_company(self, company):
        company._ff_ensure_transit_root()
        warehouses = self.env['stock.warehouse'].search(
            [('company_id', '=', company.id), ('active', '=', True)])
        for source in warehouses:
            for destination in warehouses:
                if source.id == destination.id:
                    continue
                self._ff_get_or_create_lane(source, destination)
        return True

    @api.model
    def _ff_get_or_create_lane(self, source, destination):
        lane = self.search([
            ('source_warehouse_id', '=', source.id),
            ('destination_warehouse_id', '=', destination.id),
            ('company_id', '=', source.company_id.id),
        ], limit=1)
        if not lane:
            lane = self.create({
                'source_warehouse_id': source.id,
                'destination_warehouse_id': destination.id,
                'company_id': source.company_id.id,
            })
        return lane

    def action_open_transfers(self):
        self.ensure_one()
        return {
            'name': _('Inter-Warehouse Transfers'),
            'type': 'ir.actions.act_window',
            'res_model': 'ff.interwarehouse.transfer',
            'view_mode': 'list,form',
            'domain': [('lane_id', '=', self.id)],
        }

    def action_open_transit_stock(self):
        self.ensure_one()
        return {
            'name': _('Transit Stock: %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.quant',
            'view_mode': 'list',
            'domain': [('location_id', '=', self.transit_location_id.id)],
        }
