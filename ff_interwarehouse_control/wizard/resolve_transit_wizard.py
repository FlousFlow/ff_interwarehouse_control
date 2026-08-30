# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_is_zero


class InterwarehouseResolveWizard(models.TransientModel):
    """Manager-only action to resolve an in-transit difference by scrapping the
    missing quantity through the standard Odoo scrap mechanism.

    The difference is never scrapped automatically: the manager must enter a
    reason, a note, a responsible and a date for every scrapped line.
    """

    _name = 'ff.interwarehouse.resolve.wizard'
    _description = 'Resolve Transit Difference (Scrap)'

    transfer_id = fields.Many2one(
        'ff.interwarehouse.transfer', string='Transfer', required=True, readonly=True)
    responsible_user_id = fields.Many2one(
        'res.users', string='Responsible', required=True,
        default=lambda self: self.env.user)
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    line_ids = fields.One2many(
        'ff.interwarehouse.resolve.wizard.line', 'wizard_id', string='Lines')

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

    def action_scrap(self):
        self.ensure_one()
        if not self.env.user.has_group('ff_interwarehouse_control.group_interwarehouse_manager'):
            raise UserError(_('Only the Inter-Warehouse Manager can create scrap.'))
        transfer = self.transfer_id
        lane = transfer.lane_id
        if not lane.transit_location_id:
            raise UserError(_('No transit location to scrap from.'))
        scraps = self.env['stock.scrap']
        for wline in self.line_ids:
            if float_is_zero(wline.qty, precision_rounding=wline.product_uom_id.rounding):
                continue
            if not wline.reason:
                raise UserError(_('Please provide a reason for each scrapped product.'))
            scrap = self.env['stock.scrap'].create({
                'product_id': wline.product_id.id,
                'product_uom_id': wline.product_uom_id.id,
                'scrap_qty': wline.qty,
                'location_id': lane.transit_location_id.id,
                'name': _('IWT %s - %s', transfer.name, wline.product_id.display_name),
                'company_id': transfer.company_id.id,
            })
            scrap.action_validate()
            scraps |= scrap
        # Update the audit quantities.
        for wline in self.line_ids:
            if float_is_zero(wline.qty, precision_rounding=wline.product_uom_id.rounding):
                continue
            wline.line_id.with_context(ff_allow_quantity_write=True).write({
                'scrapped_qty': wline.line_id.scrapped_qty + wline.qty,
            })
        transfer.message_post(
            body=_('Transit difference resolved by scrapping %s on %s (responsible: %s).',
                   ', '.join('%s x %s' % (l.product_id.display_name, l.qty)
                             for l in self.line_ids if l.qty > 0),
                   self.date, self.responsible_user_id.display_name))
        transfer._ff_update_state()
        return {'type': 'ir.actions.act_window_close'}


class InterwarehouseResolveWizardLine(models.TransientModel):
    _name = 'ff.interwarehouse.resolve.wizard.line'
    _description = 'Resolve Transit Difference Line'

    wizard_id = fields.Many2one('ff.interwarehouse.resolve.wizard', ondelete='cascade')
    line_id = fields.Many2one('ff.interwarehouse.transfer.line', string='Transfer Line', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    product_uom_id = fields.Many2one('uom.uom', string='Unit of Measure', readonly=True)
    in_transit_qty = fields.Float(string='In Transit', readonly=True)
    qty = fields.Float(string='Quantity to Scrap', default=0.0)
    reason = fields.Selection([
        ('physical_shortage', 'Physical shortage'),
        ('damaged_in_transit', 'Damaged in transit'),
        ('counting_difference', 'Counting difference'),
        ('loss', 'Loss'),
        ('other', 'Other'),
    ], string='Reason')
    note = fields.Text(string='Note')
