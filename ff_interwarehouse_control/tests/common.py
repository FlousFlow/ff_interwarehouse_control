# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase


class InterwarehouseCommon(TransactionCase):
    """Shared helpers for the inter-warehouse tests."""

    def setUp(self):
        super().setUp()
        # Environment quirk: the sale/purchase modules add required NOT NULL
        # columns to product_template without an ORM default that applies when
        # their Python is not loaded in the current registry (e.g. during a
        # targeted `-u ff_interwarehouse_control`). Give those leftover columns
        # a DB default so product creation works in any module-loading config.
        # The ALTER is transactional and rolled back with each test.
        self.env.cr.execute("""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='product_template' AND column_name='sale_line_warn') THEN
                    ALTER TABLE product_template ALTER COLUMN sale_line_warn SET DEFAULT 'no-message';
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='product_template' AND column_name='purchase_line_warn') THEN
                    ALTER TABLE product_template ALTER COLUMN purchase_line_warn SET DEFAULT 'no-message';
                END IF;
            END $$;
        """)
        self.company = self.env.company
        self.wh_a = self.env['stock.warehouse'].create({
            'name': 'WH-A', 'code': 'WHA'})
        self.wh_b = self.env['stock.warehouse'].create({
            'name': 'WH-B', 'code': 'WHB'})
        vals = {
            'name': 'Test Product',
            'type': 'consu',
            'is_storable': True,
            'categ_id': self.env.ref('product.product_category_all').id,
        }
        # Set the warn fields explicitly only when the field is actually in the
        # registry (avoids "Invalid field" when sale/purchase Python is not
        # loaded); otherwise the DB default above fills the NOT NULL column.
        template_model = self.env['product.template']
        if 'sale_line_warn' in template_model._fields:
            vals['sale_line_warn'] = 'no-message'
        if 'purchase_line_warn' in template_model._fields:
            vals['purchase_line_warn'] = 'no-message'
        template = template_model.create(vals)
        self.product = template.product_variant_id

    # ------------------------------------------------------------------
    # Stock helpers
    # ------------------------------------------------------------------
    def _add_stock(self, warehouse, product, qty):
        return self.env['stock.quant'].create({
            'product_id': product.id,
            'location_id': warehouse.lot_stock_id.id,
            'quantity': qty,
        })

    def _qty_at(self, location_id, product=None):
        """Total on-hand units physically present at the location (including
        reserved ones)."""
        domain = [('location_id', '=', location_id)]
        if product:
            domain.append(('product_id', '=', product.id))
        quants = self.env['stock.quant'].search(domain)
        return sum(quants.mapped('quantity'))

    def _on_hand(self, warehouse, product=None):
        return self._qty_at(warehouse.lot_stock_id.id, product)

    # ------------------------------------------------------------------
    # Model helpers
    # ------------------------------------------------------------------
    def _lane(self, source, destination):
        return self.env['ff.interwarehouse.lane'].search([
            ('source_warehouse_id', '=', source.id),
            ('destination_warehouse_id', '=', destination.id),
        ], limit=1)

    def _create_transfer(self, lane, product, qty, env=None):
        env = env or self.env
        return env['ff.interwarehouse.transfer'].create({
            'lane_id': lane.id,
            'line_ids': [(0, 0, {
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'requested_qty': qty,
            })],
        })

    # ------------------------------------------------------------------
    # User helpers
    # ------------------------------------------------------------------
    def _create_user(self, name, login, warehouses, restricted=True, manager=False):
        groups = [self.env.ref('stock.group_stock_user').id]
        if restricted:
            groups.append(self.env.ref('ff_interwarehouse_control.group_restricted_warehouse_user').id)
        if manager:
            groups.append(self.env.ref('ff_interwarehouse_control.group_interwarehouse_manager').id)
        return self.env['res.users'].create({
            'name': name,
            'login': login,
            'password': 'password',
            'email': '%s@example.com' % login,
            'groups_id': [(6, 0, groups)],
            'company_id': self.company.id,
            'company_ids': [(6, 0, [self.company.id])],
            'allowed_warehouse_ids': [(6, 0, [w.id for w in warehouses])],
            'warehouse_restriction_enabled': restricted,
        })

    def _validate_picking(self, picking, qty=None):
        """Validate a picking the way the UI does: set the done quantity and
        mark the moves as picked, then run the standard stock engine."""
        moves = picking.move_ids
        if qty is None:
            moves.quantity = moves.product_uom_qty
        else:
            moves.quantity = qty
        moves.picked = True
        picking._action_done()
        return picking

    def _dispatch_all(self, transfer, qty=None):
        dispatch = transfer.dispatch_picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel'))
        if not dispatch:
            dispatch = transfer.dispatch_picking_ids
        return self._validate_picking(dispatch, qty)

    def _receive_all(self, transfer, qty=None):
        receipt = transfer.receipt_picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel'))
        if not receipt:
            receipt = transfer.receipt_picking_ids
        return self._validate_picking(receipt, qty)
