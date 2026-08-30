# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class InterwarehousePartialReasonWizard(models.TransientModel):
    """Record an optional / configurable reason for a partial receipt.

    This does NOT alter quantities - the difference stays in transit (handled
    by the standard backorder). It only documents why the receipt was partial.
    """

    _name = 'ff.interwarehouse.partial.reason.wizard'
    _description = 'Record Partial Receipt Reason'

    transfer_id = fields.Many2one(
        'ff.interwarehouse.transfer', string='Transfer', required=True, readonly=True)
    line_ids = fields.One2many(
        'ff.interwarehouse.partial.reason.wizard.line', 'wizard_id', string='Lines')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        transfer = self.env['ff.interwarehouse.transfer'].browse(
            self.env.context.get('default_transfer_id'))
        if transfer:
            res['transfer_id'] = transfer.id
            lines = []
            for line in transfer.line_ids:
                if line.in_transit_qty > 0:
                    lines.append((0, 0, {
                        'line_id': line.id,
                        'product_id': line.product_id.id,
                        'dispatched_qty': line.dispatched_qty,
                        'received_qty': line.received_qty,
                        'in_transit_qty': line.in_transit_qty,
                        'reason': line.partial_receipt_reason,
                        'note': line.partial_receipt_note,
                    }))
            if lines:
                res['line_ids'] = lines
        return res

    def action_save(self):
        self.ensure_one()
        require_reason = self.env['ir.config_parameter'].sudo().get_param(
            'ff_interwarehouse_control.require_partial_reason', 'False') == 'True'
        for wline in self.line_ids:
            if require_reason and not wline.reason:
                raise UserError(_('A reason is required for every partially received product.'))
            wline.line_id.write({
                'partial_receipt_reason': wline.reason,
                'partial_receipt_note': wline.note,
            })
        self.transfer_id.message_post(body=_('Partial receipt reason recorded.'))
        return {'type': 'ir.actions.act_window_close'}


class InterwarehousePartialReasonWizardLine(models.TransientModel):
    _name = 'ff.interwarehouse.partial.reason.wizard.line'
    _description = 'Partial Receipt Reason Line'

    wizard_id = fields.Many2one(
        'ff.interwarehouse.partial.reason.wizard', ondelete='cascade')
    line_id = fields.Many2one(
        'ff.interwarehouse.transfer.line', string='Transfer Line', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    dispatched_qty = fields.Float(string='Dispatched', readonly=True)
    received_qty = fields.Float(string='Received', readonly=True)
    in_transit_qty = fields.Float(string='In Transit', readonly=True)
    reason = fields.Selection([
        ('physical_shortage', 'Physical shortage'),
        ('damaged_in_transit', 'Damaged in transit'),
        ('counting_difference', 'Counting difference'),
        ('partial_delivery', 'Partial delivery'),
        ('other', 'Other'),
    ], string='Reason')
    note = fields.Text(string='Note')
