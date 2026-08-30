# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class ResCompany(models.Model):
    _inherit = 'res.company'

    ff_interwarehouse_transit_root_location_id = fields.Many2one(
        'stock.location', string='Inter-Warehouse Transit Root Location',
        ondelete='restrict', copy=False)

    def _ff_ensure_transit_root(self):
        """Create (once) the company-level root location that parents every
        lane transit location. Idempotent."""
        self.ensure_one()
        if self.ff_interwarehouse_transit_root_location_id:
            return self.ff_interwarehouse_transit_root_location_id
        parent = self.env.ref('stock.stock_location_locations', raise_if_not_found=False)
        root = self.env['stock.location'].create({
            'name': _('Inter-Warehouse Transit - %s', self.name),
            'usage': 'view',
            'location_id': parent.id if parent else False,
            'company_id': self.id,
        })
        self.write({'ff_interwarehouse_transit_root_location_id': root.id})
        return root
