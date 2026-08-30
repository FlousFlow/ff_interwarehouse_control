# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero


class InterwarehouseTransferLine(models.Model):
    """One product line of an inter-warehouse transfer.

    All audit quantities are stored and only ever updated by the stock-engine
    hooks (never typed manually). The derived figures are computed:
        pending_dispatch_qty = requested_qty - dispatched_qty
        in_transit_qty       = dispatched_qty - received_qty - returned_qty - scrapped_qty
    """

    _name = 'ff.interwarehouse.transfer.line'
    _description = 'Inter-Warehouse Transfer Line'
    _order = 'id'

    transfer_id = fields.Many2one(
        'ff.interwarehouse.transfer', string='Transfer', required=True,
        ondelete='cascade', index=True)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True, index=True)
    product_uom_id = fields.Many2one(
        'uom.uom', string='Unit of Measure', required=True)
    requested_qty = fields.Float(
        string='Requested Qty', required=True, default=0.0,
        digits='Product Unit of Measure')
    dispatched_qty = fields.Float(
        string='Dispatched Qty', readonly=True, default=0.0,
        digits='Product Unit of Measure', copy=False)
    received_qty = fields.Float(
        string='Received Qty', readonly=True, default=0.0,
        digits='Product Unit of Measure', copy=False)
    returned_qty = fields.Float(
        string='Returned Qty', readonly=True, default=0.0,
        digits='Product Unit of Measure', copy=False)
    scrapped_qty = fields.Float(
        string='Scrapped Qty', readonly=True, default=0.0,
        digits='Product Unit of Measure', copy=False)

    pending_dispatch_qty = fields.Float(
        string='Pending Dispatch', compute='_compute_derived',
        digits='Product Unit of Measure')
    in_transit_qty = fields.Float(
        string='In Transit', compute='_compute_derived',
        digits='Product Unit of Measure')

    partial_receipt_reason = fields.Selection([
        ('physical_shortage', 'Physical shortage'),
        ('damaged_in_transit', 'Damaged in transit'),
        ('counting_difference', 'Counting difference'),
        ('partial_delivery', 'Partial delivery'),
        ('other', 'Other'),
    ], string='Partial Receipt Reason')
    partial_receipt_note = fields.Text(string='Partial Receipt Note')

    @api.depends('requested_qty', 'dispatched_qty', 'received_qty',
                 'returned_qty', 'scrapped_qty')
    def _compute_derived(self):
        for line in self:
            line.pending_dispatch_qty = line.requested_qty - line.dispatched_qty
            line.in_transit_qty = (
                line.dispatched_qty - line.received_qty
                - line.returned_qty - line.scrapped_qty)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id

    @api.constrains('requested_qty')
    def _check_requested_qty(self):
        for line in self:
            rounding = line.product_uom_id.rounding
            if float_is_zero(line.requested_qty, precision_rounding=rounding) or \
               float_compare(line.requested_qty, 0.0, precision_rounding=rounding) < 0:
                raise ValidationError(_('The requested quantity must be greater than zero.'))

    @api.constrains('dispatched_qty', 'received_qty', 'returned_qty', 'scrapped_qty')
    def _check_quantities(self):
        for line in self:
            rounding = line.product_uom_id.rounding
            if float_compare(line.received_qty, line.dispatched_qty,
                             precision_rounding=rounding) > 0:
                raise ValidationError(
                    _('The received quantity cannot exceed the quantity currently '
                      'in transit (dispatched).'))
            outstanding = line.dispatched_qty - line.received_qty
            if float_compare(line.returned_qty, outstanding,
                             precision_rounding=rounding) > 0:
                raise ValidationError(
                    _('The returned quantity cannot exceed the outstanding in-transit '
                      'quantity.'))
            if float_compare(line.scrapped_qty, outstanding,
                             precision_rounding=rounding) > 0:
                raise ValidationError(
                    _('The scrapped quantity cannot exceed the outstanding in-transit '
                      'quantity.'))

    def write(self, vals):
        for line in self:
            if line.transfer_id.state not in ('draft', 'confirmed'):
                if set(vals) & {'product_id', 'product_uom_id', 'requested_qty'}:
                    raise UserError(
                        _('Transfer lines cannot be edited once the transfer has been '
                          'dispatched. Create a new transfer instead.'))
        if set(vals) & {'dispatched_qty', 'received_qty', 'returned_qty', 'scrapped_qty'}:
            if not self.env.context.get('ff_allow_quantity_write') and \
               not self.env.user.has_group('ff_interwarehouse_control.group_interwarehouse_manager'):
                raise UserError(
                    _('Quantities are updated automatically by the stock engine and '
                      'cannot be edited manually.'))
        return super().write(vals)

    def unlink(self):
        for line in self:
            if line.transfer_id.state not in ('draft', 'confirmed'):
                raise UserError(
                    _('Transfer lines cannot be removed once the transfer has been '
                      'dispatched.'))
        return super().unlink()


class InterwarehouseTransfer(models.Model):
    """Master business/audit layer over standard ``stock.picking`` records.

    The master only orchestrates workflow, security and traceability - the
    stock engine (stock.picking -> stock.move -> stock.move.line) is
    responsible for all quants. State and audit quantities are derived from the
    real pickings through the ``_action_done`` hooks.
    """

    _name = 'ff.interwarehouse.transfer'
    _description = 'Inter-Warehouse Transfer'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Reference', required=True, readonly=True, copy=False, index=True,
        default=lambda self: _('New'))
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company, ondelete='cascade')
    lane_id = fields.Many2one(
        'ff.interwarehouse.lane', string='Inter-Warehouse Lane', required=True,
        tracking=True, index=True)
    source_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Source Warehouse', index=True,
        related='lane_id.source_warehouse_id', store=True, readonly=True)
    destination_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Destination Warehouse', index=True,
        related='lane_id.destination_warehouse_id', store=True, readonly=True)
    source_name = fields.Char(string='Source', related='lane_id.source_name', store=True, readonly=True)
    destination_name = fields.Char(string='Destination', related='lane_id.destination_name', store=True, readonly=True)

    initiator_user_id = fields.Many2one(
        'res.users', string='Initiator', default=lambda self: self.env.user,
        required=True, tracking=True)
    responsible_user_id = fields.Many2one(
        'res.users', string='Responsible', default=lambda self: self.env.user,
        tracking=True)
    request_date = fields.Date(string='Request Date', default=fields.Date.context_today, required=True, tracking=True)
    dispatch_date = fields.Datetime(string='Dispatch Date', readonly=True, tracking=True)
    completion_date = fields.Datetime(string='Completion Date', readonly=True, tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('partially_dispatched', 'Partially Dispatched'),
        ('in_transit', 'In Transit'),
        ('partially_received', 'Partially Received'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', readonly=True, tracking=True, copy=False)

    notes = fields.Text(string='Notes')

    line_ids = fields.One2many(
        'ff.interwarehouse.transfer.line', 'transfer_id', string='Lines', copy=True)
    dispatch_picking_ids = fields.One2many(
        'stock.picking', 'ff_interwarehouse_transfer_id', string='Dispatches',
        domain=[('ff_interwarehouse_role', '=', 'dispatch')])
    receipt_picking_ids = fields.One2many(
        'stock.picking', 'ff_interwarehouse_transfer_id', string='Receipts',
        domain=[('ff_interwarehouse_role', '=', 'receipt')])
    return_picking_ids = fields.One2many(
        'stock.picking', 'ff_interwarehouse_transfer_id', string='Returns',
        domain=[('ff_interwarehouse_role', '=', 'return')])

    ff_is_overdue = fields.Boolean(
        string='Overdue', compute='_compute_ff_is_overdue', store=True)
    dispatched_qty_total = fields.Float(
        string='Dispatched', compute='_compute_qty_totals', digits='Product Unit of Measure')
    received_qty_total = fields.Float(
        string='Received', compute='_compute_qty_totals', digits='Product Unit of Measure')
    in_transit_qty_total = fields.Float(
        string='In Transit', compute='_compute_qty_totals', digits='Product Unit of Measure')

    @api.depends('line_ids.dispatched_qty', 'line_ids.received_qty',
                 'line_ids.returned_qty', 'line_ids.scrapped_qty')
    def _compute_qty_totals(self):
        for transfer in self:
            transfer.dispatched_qty_total = sum(transfer.line_ids.mapped('dispatched_qty'))
            transfer.received_qty_total = sum(transfer.line_ids.mapped('received_qty'))
            transfer.in_transit_qty_total = sum(transfer.line_ids.mapped('in_transit_qty'))

    @api.depends('request_date', 'state')
    def _compute_ff_is_overdue(self):
        today = fields.Date.context_today(self)
        for transfer in self:
            transfer.ff_is_overdue = (
                bool(transfer.request_date)
                and transfer.request_date < today
                and transfer.state not in ('done', 'cancelled', 'draft'))

    # ------------------------------------------------------------------
    # Derived state (from real pickings / stored audit quantities)
    # ------------------------------------------------------------------
    def _ff_compute_state_value(self):
        """Derive the master state from the stored line quantities. The stored
        quantities are themselves fed by the real pickings in ``_action_done``,
        so this reflects reality - not button clicks."""
        self.ensure_one()
        if not self.line_ids:
            return 'confirmed'
        all_done = True
        any_partial_received = False
        any_partial_dispatched = False
        any_dispatched = False
        for line in self.line_ids:
            rounding = line.product_uom_id.rounding
            requested = line.requested_qty
            dispatched = line.dispatched_qty
            received = line.received_qty
            if float_is_zero(requested, precision_rounding=rounding):
                all_done = False
                continue
            if not float_is_zero(dispatched, precision_rounding=rounding):
                any_dispatched = True
            if not float_is_zero(received, precision_rounding=rounding) and \
               float_compare(received, dispatched, precision_rounding=rounding) < 0:
                any_partial_received = True
            if not float_is_zero(dispatched, precision_rounding=rounding) and \
               float_compare(dispatched, requested, precision_rounding=rounding) < 0:
                any_partial_dispatched = True
            if float_compare(dispatched, requested, precision_rounding=rounding) != 0 or \
               float_compare(received, dispatched, precision_rounding=rounding) != 0:
                all_done = False
        if all_done:
            return 'done'
        if any_partial_received:
            return 'partially_received'
        if any_partial_dispatched:
            return 'partially_dispatched'
        if any_dispatched:
            return 'in_transit'
        return 'confirmed'

    def _ff_update_state(self):
        for transfer in self:
            if transfer.state in ('done', 'cancelled'):
                continue
            new_state = transfer._ff_compute_state_value()
            if new_state == 'done' and not transfer.completion_date:
                transfer.write({'completion_date': fields.Datetime.now()})
            if new_state != transfer.state:
                transfer.write({'state': new_state})

    # ------------------------------------------------------------------
    # Workflow actions
    # ------------------------------------------------------------------
    def action_confirm(self):
        for transfer in self:
            if transfer.state != 'draft':
                raise UserError(_('Only draft transfers can be confirmed.'))
            if not transfer.line_ids:
                raise UserError(_('Please add at least one product line before confirming.'))
            if transfer.source_warehouse_id == transfer.destination_warehouse_id:
                raise UserError(_('The source and destination warehouses must be different.'))
            if self.env.user.has_group('ff_interwarehouse_control.group_restricted_warehouse_user'):
                allowed = self.env.user.allowed_warehouse_ids
                if transfer.source_warehouse_id not in allowed:
                    raise UserError(
                        _('You are not allowed to initiate a transfer from this warehouse.'))
            transfer._ff_create_dispatch_picking()
            transfer.write({
                'state': 'confirmed',
                'dispatch_date': fields.Datetime.now(),
            })
            transfer.message_post(body=_('Transfer %s confirmed. Dispatch picking created.', transfer.name))
        return True

    def action_cancel(self):
        for transfer in self:
            if transfer.state not in ('draft', 'confirmed'):
                raise UserError(
                    _('Only draft or confirmed (not yet dispatched) transfers can be '
                      'cancelled. Use "Return to Source" for in-transit quantities.'))
            for line in transfer.line_ids:
                if not float_is_zero(line.dispatched_qty,
                                     precision_rounding=line.product_uom_id.rounding):
                    raise UserError(
                        _('Transfer %s has already been dispatched and cannot be '
                          'cancelled. Use "Return to Source" to handle in-transit '
                          'quantities.', transfer.name))
            for picking in transfer.dispatch_picking_ids.filtered(
                    lambda p: p.state not in ('done', 'cancel')):
                picking.action_cancel()
            transfer.write({'state': 'cancelled'})
            transfer.message_post(body=_('Transfer %s cancelled.', transfer.name))
        return True

    def action_return_to_source(self):
        self.ensure_one()
        if self.state not in ('in_transit', 'partially_received', 'partially_dispatched'):
            raise UserError(_('There is nothing to return in the current state.'))
        if not any(float_compare(l.in_transit_qty, 0.0,
                                 precision_rounding=l.product_uom_id.rounding) > 0
                   for l in self.line_ids):
            raise UserError(_('There is no in-transit quantity to return.'))
        return {
            'name': _('Return to Source'),
            'type': 'ir.actions.act_window',
            'res_model': 'ff.interwarehouse.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_transfer_id': self.id},
        }

    def action_resolve_difference(self):
        self.ensure_one()
        if not self.env.user.has_group('ff_interwarehouse_control.group_interwarehouse_manager'):
            raise UserError(_('Only the Inter-Warehouse Manager can resolve transit differences.'))
        if self.state not in ('in_transit', 'partially_received', 'partially_dispatched'):
            raise UserError(_('There is no transit difference to resolve in the current state.'))
        return {
            'name': _('Resolve Transit Difference'),
            'type': 'ir.actions.act_window',
            'res_model': 'ff.interwarehouse.resolve.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_transfer_id': self.id},
        }

    def action_record_partial_reason(self):
        self.ensure_one()
        if self.state != 'partially_received':
            raise UserError(_('The partial receipt reason can only be recorded after a partial receipt.'))
        return {
            'name': _('Record Partial Receipt Reason'),
            'type': 'ir.actions.act_window',
            'res_model': 'ff.interwarehouse.partial.reason.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_transfer_id': self.id},
        }

    def action_open_dispatch(self):
        self.ensure_one()
        return self._ff_open_pickings(self.dispatch_picking_ids, _('Dispatches'))

    def action_open_receipt(self):
        self.ensure_one()
        return self._ff_open_pickings(self.receipt_picking_ids, _('Receipts'))

    def _ff_open_pickings(self, pickings, title):
        if not pickings:
            raise UserError(_('No pickings to display.'))
        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', pickings.ids)],
        }

    # ------------------------------------------------------------------
    # Stock-engine hooks (called from stock.picking._action_done)
    # ------------------------------------------------------------------
    def _ff_on_picking_done(self, picking):
        """Update the master from a real picking validation. Called after the
        standard stock engine has completed the movement, so quants are already
        correct - this only maintains the business/audit layer."""
        self.ensure_one()
        old_state = self.state
        if picking.ff_interwarehouse_role == 'dispatch':
            self._ff_update_dispatched_qty()
            self._ff_create_receipt_picking(picking)
            self._ff_notify_destination()
        elif picking.ff_interwarehouse_role == 'receipt':
            self._ff_update_received_qty()
        elif picking.ff_interwarehouse_role == 'return':
            self._ff_update_returned_qty()
        self._ff_update_state()
        if self.state != old_state:
            if self.state == 'done':
                self._ff_notify_completion()
            elif self.state in ('partially_received',) and \
                    old_state in ('confirmed', 'partially_dispatched', 'in_transit'):
                self._ff_notify_partial_receipt()
        return True

    def _ff_update_dispatched_qty(self):
        """Recompute dispatched quantities from the done dispatch moves."""
        self.ensure_one()
        for line in self.line_ids:
            qty = 0.0
            rounding = line.product_uom_id.rounding
            for picking in self.dispatch_picking_ids:
                for move in picking.move_ids:
                    if move.product_id.id != line.product_id.id or move.state != 'done':
                        continue
                    qty += move.product_uom._compute_quantity(move.quantity, line.product_uom_id)
            if float_compare(qty, line.dispatched_qty, precision_rounding=rounding) != 0:
                line.with_context(ff_allow_quantity_write=True).write({'dispatched_qty': qty})

    def _ff_update_received_qty(self):
        """Recompute received quantities from the done receipt moves."""
        self.ensure_one()
        for line in self.line_ids:
            qty = 0.0
            rounding = line.product_uom_id.rounding
            for picking in self.receipt_picking_ids:
                for move in picking.move_ids:
                    if move.product_id.id != line.product_id.id or move.state != 'done':
                        continue
                    qty += move.product_uom._compute_quantity(move.quantity, line.product_uom_id)
            if float_compare(qty, line.received_qty, precision_rounding=rounding) != 0:
                line.with_context(ff_allow_quantity_write=True).write({'received_qty': qty})

    def _ff_update_returned_qty(self):
        """Recompute returned quantities from the done return moves."""
        self.ensure_one()
        for line in self.line_ids:
            qty = 0.0
            rounding = line.product_uom_id.rounding
            for picking in self.return_picking_ids:
                for move in picking.move_ids:
                    if move.product_id.id != line.product_id.id or move.state != 'done':
                        continue
                    qty += move.product_uom._compute_quantity(move.quantity, line.product_uom_id)
            if float_compare(qty, line.returned_qty, precision_rounding=rounding) != 0:
                line.with_context(ff_allow_quantity_write=True).write({'returned_qty': qty})

    # ------------------------------------------------------------------
    # Dispatch / Receipt picking creation
    # ------------------------------------------------------------------
    def _ff_create_dispatch_picking(self):
        """Create the dispatch picking ``Source/Stock -> Lane Transit`` for the
        full requested quantity. Runs in the initiator's session (they own the
        source warehouse), so no sudo is needed here."""
        self.ensure_one()
        source = self.source_warehouse_id
        lane = self.lane_id
        picking_type = source.ff_dispatch_picking_type_id
        if not picking_type:
            raise UserError(
                _('The source warehouse has no Inter-Warehouse Dispatch operation '
                  'type. Run the warehouse setup first.'))
        move_vals = []
        for line in self.line_ids:
            if float_is_zero(line.requested_qty, precision_rounding=line.product_uom_id.rounding):
                continue
            move_vals.append((0, 0, {
                'name': _('%s (inter-warehouse dispatch)', line.product_id.display_name),
                'product_id': line.product_id.id,
                'product_uom_qty': line.requested_qty,
                'product_uom': line.product_uom_id.id,
                'location_id': source.lot_stock_id.id,
                'location_dest_id': lane.transit_location_id.id,
                'picking_type_id': picking_type.id,
                'company_id': self.company_id.id,
            }))
        if not move_vals:
            raise UserError(_('No products to dispatch.'))
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': source.lot_stock_id.id,
            'location_dest_id': lane.transit_location_id.id,
            'origin': self.name,
            'move_ids': move_vals,
            'ff_interwarehouse_transfer_id': self.id,
            'ff_interwarehouse_role': 'dispatch',
            'ff_source_warehouse_id': self.source_warehouse_id.id,
            'ff_destination_warehouse_id': self.destination_warehouse_id.id,
            'ff_lane_id': lane.id,
        })
        picking.action_confirm()
        return picking

    def _ff_create_receipt_picking(self, dispatch_picking):
        """After a dispatch is validated, create the receipt picking
        ``Lane Transit -> Destination/Stock`` covering exactly the dispatched
        quantity (partial dispatches produce a receipt for the done part only).

        Security note: this is an internal system creation. It runs in the
        source user's session but touches the destination warehouse, so it uses
        a controlled ``sudo()`` to read fixed values (destination stock location
        and receipt operation type) derived only from the lane / destination
        warehouse. No user-controlled value can leak another warehouse - the
        resulting picking is still protected by the inter-warehouse record rules
        (visible only to the two parties)."""
        self.ensure_one()
        done_moves = dispatch_picking.move_ids.filtered(
            lambda m: m.state == 'done'
            and not float_is_zero(m.quantity, precision_rounding=m.product_uom.rounding))
        if not done_moves:
            return self.env['stock.picking']

        lane = self.lane_id
        wh_sudo = self.env['stock.warehouse'].sudo()
        lane_sudo = self.env['ff.interwarehouse.lane'].sudo()
        dest = wh_sudo.browse(self.destination_warehouse_id.id)
        lane_rec = lane_sudo.browse(lane.id)
        receipt_type = dest.ff_receipt_picking_type_id
        if not receipt_type:
            raise UserError(
                _('The destination warehouse has no Inter-Warehouse Receipt operation '
                  'type. Run the warehouse setup first.'))

        move_vals = []
        for move in done_moves:
            line = self.line_ids.filtered(lambda l: l.product_id.id == move.product_id.id)
            qty = move.product_uom._compute_quantity(
                move.quantity, line.product_uom_id) if line else move.quantity
            if float_is_zero(qty, precision_rounding=move.product_uom.rounding):
                continue
            move_vals.append((0, 0, {
                'name': _('%s (inter-warehouse receipt)', move.product_id.display_name),
                'product_id': move.product_id.id,
                'product_uom_qty': qty,
                'product_uom': line.product_uom_id.id if line else move.product_uom_id.id,
                'location_id': lane_rec.transit_location_id.id,
                'location_dest_id': dest.lot_stock_id.id,
                'picking_type_id': receipt_type.id,
                'company_id': self.company_id.id,
            }))
        if not move_vals:
            return self.env['stock.picking']

        picking = self.env['stock.picking'].sudo().create({
            'picking_type_id': receipt_type.id,
            'location_id': lane_rec.transit_location_id.id,
            'location_dest_id': dest.lot_stock_id.id,
            'origin': self.name,
            'move_ids': move_vals,
            'ff_interwarehouse_transfer_id': self.id,
            'ff_interwarehouse_role': 'receipt',
            'ff_source_warehouse_id': self.source_warehouse_id.id,
            'ff_destination_warehouse_id': self.destination_warehouse_id.id,
            'ff_lane_id': lane.id,
        })
        picking.sudo().action_confirm()
        picking.sudo().action_assign()
        self.message_post(body=_(
            'Receipt picking %s created for the dispatched quantity. Please ask '
            'the destination warehouse to validate it.', picking.name))
        return picking

    # ------------------------------------------------------------------
    # Notifications (chatter + activities)
    # ------------------------------------------------------------------
    def _ff_notify_destination(self):
        self.ensure_one()
        if self.env['ir.config_parameter'].sudo().get_param(
                'ff_interwarehouse_control.notify_destination', 'True') != 'True':
            return
        note = _(
            'Incoming inter-warehouse transfer %s from %s to %s has been dispatched. '
            'Please validate the receipt.', self.name, self.source_name,
            self.destination_name)
        self.message_post(body=note)
        # Reading the destination responsible users is an internal notification
        # concern; only the responsible user ids are used (no stock data).
        dest_wh = self.env['stock.warehouse'].sudo() \
            .browse(self.destination_warehouse_id.id)
        for user in dest_wh.ff_interwarehouse_responsible_user_ids:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('Incoming Inter-Warehouse Transfer: %s', self.name),
                note=note,
                user_id=user.id,
            )
        return True

    def _ff_notify_partial_receipt(self):
        self.ensure_one()
        if self.env['ir.config_parameter'].sudo().get_param(
                'ff_interwarehouse_control.partial_receipt_notifications', 'True') != 'True':
            return
        lines_desc = '\n'.join(
            _('%s: Dispatched %s / Received %s', l.product_id.display_name,
              l.dispatched_qty, l.received_qty)
            for l in self.line_ids)
        body = _(
            'Transfer %s was only partially received.\n%s\nOutstanding quantity '
            'remains in transit.', self.name, lines_desc)
        self.message_post(body=body)
        user = self.initiator_user_id or self.responsible_user_id
        if user:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('Partial receipt: %s', self.name),
                note=body,
                user_id=user.id,
            )
        return True

    def _ff_notify_completion(self):
        self.ensure_one()
        self.message_post(body=_(
            'Transfer %s fully received by %s. Status: Done.', self.name,
            self.destination_name))
        return True

    # ------------------------------------------------------------------
    # CRUD guards
    # ------------------------------------------------------------------
    def write(self, vals):
        if 'lane_id' in vals and any(t.state not in ('draft',) for t in self):
            raise UserError(
                _('The source/destination warehouse of a transfer cannot be changed '
                  'after confirmation.'))
        return super().write(vals)

    def unlink(self):
        for transfer in self:
            if transfer.state != 'draft':
                raise UserError(_('Only draft transfers can be deleted.'))
        return super().unlink()

    def copy(self, default=None):
        default = dict(default or {})
        default.update({
            'name': '/',
            'state': 'draft',
            'dispatch_date': False,
            'completion_date': False,
        })
        return super().copy(default)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] in ('/', _('New')):
                vals['name'] = (
                    self.env['ir.sequence'].with_company(vals.get('company_id'))
                    .next_by_code('ff.interwarehouse.transfer') or '/')
            if not vals.get('lane_id'):
                raise UserError(_('An inter-warehouse lane is required.'))
            if not vals.get('request_date'):
                vals['request_date'] = fields.Date.context_today(self)
            if not vals.get('initiator_user_id'):
                vals['initiator_user_id'] = self.env.user.id
            if not vals.get('responsible_user_id'):
                vals['responsible_user_id'] = self.env.user.id
        return super().create(vals_list)
