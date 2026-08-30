# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class ResUsers(models.Model):
    _inherit = 'res.users'

    warehouse_restriction_enabled = fields.Boolean(
        string='Warehouse Restriction Enabled',
        help='When enabled, this user only sees stock of the warehouses listed '
             'below (stock.warehouse, locations, quants, pickings, moves, '
             'operation types).')
    allowed_warehouse_ids = fields.Many2many(
        'stock.warehouse', string='Allowed Warehouses')

    @api.constrains('allowed_warehouse_ids', 'company_ids')
    def _check_allowed_warehouses_company(self):
        for user in self:
            for warehouse in user.allowed_warehouse_ids:
                if warehouse.company_id not in user.company_ids:
                    raise ValidationError(
                        _('Allowed warehouses must belong to the user\'s allowed '
                          'companies.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'allowed_warehouse_ids' in vals or 'warehouse_restriction_enabled' in vals:
                self._check_ff_warehouse_access_edit()
        return super().create(vals_list)

    def write(self, vals):
        if 'allowed_warehouse_ids' in vals or 'warehouse_restriction_enabled' in vals:
            self._check_ff_warehouse_access_edit()
        return super().write(vals)

    def _check_ff_warehouse_access_edit(self):
        """Only an administrator or the Inter-Warehouse Manager can change the
        warehouse access of any user (including themselves)."""
        if self.env.is_admin():
            return
        if self.env.user.has_group('ff_interwarehouse_control.group_interwarehouse_manager'):
            return
        raise UserError(
            _('Only administrators or the Inter-Warehouse Manager can change '
              'warehouse access settings.'))
