# -*- coding: utf-8 -*-
"""Accounting-soundness tests.

What these tests prove about the flow:

1. An inter-warehouse transfer (dispatch ``Stock -> Transit`` + receipt
   ``Transit -> Stock``) is an INTERNAL movement between valued locations of
   the SAME company. Odoo's valuation engine therefore creates NO stock
   valuation layer and NO journal entry for it (verified empirically against
   Odoo's own standard "Internal Transfers" operation which behaves the same).
   That is CORRECT accounting: the value stays in stock, there is zero P&L
   impact and zero balance-sheet movement - an internal transfer between the
   company's own warehouses must not hit the P&L.

2. The only place the flow touches the ledger is a manager "Resolve
   Difference" (scrap), which posts a loss through the standard Odoo scrap
   mechanism (SVL + posted journal entry to the loss account).

3. A control test proves the valuation engine IS active (a vendor receipt
   DOES create an SVL + journal entry), so the zero-entries result above is
   intentional internal-transfer behaviour - not a broken valuation config.

These tests require the ``account`` module; they are skipped otherwise.
"""
from odoo.addons.ff_interwarehouse_control.tests.common import InterwarehouseCommon


class TestAccountingSoundness(InterwarehouseCommon):

    def setUp(self):
        super().setUp()
        # These tests need the full valuation registry (account + stock_account
        # modules). During a targeted `-u ff_interwarehouse_control` those
        # models are not loaded, so skip instead of failing. Run them with
        # `-u ff_interwarehouse_control,stock_account` to actually execute.
        if 'property_valuation' not in self.env['product.category']._fields:
            self.skipTest('stock_account module not loaded in this registry')
        Account = self.env['account.account'].with_company(self.company)
        def _acc(name, code, acc_type):
            return Account.create({
                'name': name, 'code': code, 'account_type': acc_type,
                'company_ids': [(6, 0, [self.company.id])],
            })
        self.stock_acc = _acc('Stock (test)', '200000', 'asset_current')
        self.input_acc = _acc('Stock Input (test)', '200001', 'asset_current')
        self.output_acc = _acc('Stock Output (test)', '200002', 'asset_current')
        self.transit_acc = _acc('Stock Transit (test)', '200003', 'asset_current')
        self.loss_acc = _acc('Stock Loss (test)', '200004', 'expense')

        self.categ = self.env['product.category'].create({
            'name': 'CAT-Accounting',
            'property_valuation': 'real_time',
            'property_cost_method': 'standard',
            'property_stock_valuation_account_id': self.stock_acc.id,
            'property_stock_account_input_categ_id': self.input_acc.id,
            'property_stock_account_output_categ_id': self.output_acc.id,
            'property_loss_account_id': self.loss_acc.id,
        })
        self.product = self.env['product.product'].create({
            'name': 'P-Accounting',
            'type': 'consu',
            'is_storable': True,
            'categ_id': self.categ.id,
            'standard_price': 100.0,
        })
        # Lane transit location gets the interim transit accounts (same as
        # Odoo's own resupply transit locations).
        lane = self._lane(self.wh_a, self.wh_b)
        lane.transit_location_id.write({
            'valuation_in_account_id': self.transit_acc.id,
            'valuation_out_account_id': self.transit_acc.id,
        })

    # Helpers ------------------------------------------------------------
    def _svl(self):
        return self.env['stock.valuation.layer'].search(
            [('product_id', '=', self.product.id)], order='id')

    def _account_moves(self, pickings):
        return self.env['account.move'].search(
            [('stock_move_id', 'in', pickings.move_ids.ids)])

    def _validate(self, picking, qty=None):
        moves = picking.move_ids
        if qty is None:
            moves.quantity = moves.product_uom_qty
        else:
            moves.quantity = qty
        moves.picked = True
        picking._action_done()
        return picking

    # ------------------------------------------------------------------
    # 1) Internal transfer = zero P&L / zero ledger movement (correct)
    # ------------------------------------------------------------------
    def test_01_internal_transfer_is_accounting_neutral(self):
        lane = self._lane(self.wh_a, self.wh_b)
        self._add_stock(self.wh_a, self.product, 10)
        transfer = self._create_transfer(lane, self.product, 4)
        transfer.action_confirm()

        dispatch = transfer.dispatch_picking_ids
        self._validate(dispatch)
        receipt = transfer.receipt_picking_ids
        self._validate(receipt)

        # The business flow completed with correct stock quantities...
        self.assertEqual(transfer.state, 'done')
        self.assertEqual(self._on_hand(self.wh_b), 4.0)
        self.assertEqual(self._on_hand(self.wh_a), 6.0)
        self.assertEqual(self._qty_at(lane.transit_location_id.id), 0.0)

        # ...and, as an internal move between valued locations of one company,
        # it creates NO valuation layer and NO journal entry (zero P&L).
        pickings = transfer.dispatch_picking_ids | transfer.receipt_picking_ids
        self.assertEqual(self._svl(), self.env['stock.valuation.layer'])
        self.assertEqual(self._account_moves(pickings), self.env['account.move'])

    # ------------------------------------------------------------------
    # 2) Parity with Odoo's own standard internal transfer
    # ------------------------------------------------------------------
    def test_02_parity_with_standard_internal_transfer(self):
        """A standard Odoo Internal Transfers move between the same warehouses
        also creates no SVL / no journal entry -> our flow matches the stock
        engine exactly."""
        self._add_stock(self.wh_a, self.product, 20)
        pt = self.wh_a.int_type_id
        picking = self.env['stock.picking'].create({
            'picking_type_id': pt.id,
            'location_id': self.wh_a.lot_stock_id.id,
            'location_dest_id': self.wh_b.lot_stock_id.id,
            'move_ids': [(0, 0, {
                'name': 'std internal',
                'product_id': self.product.id,
                'product_uom_qty': 6,
                'product_uom': self.product.uom_id.id,
                'location_id': self.wh_a.lot_stock_id.id,
                'location_dest_id': self.wh_b.lot_stock_id.id,
                'picking_type_id': pt.id,
                'company_id': self.company.id,
            })],
        })
        picking.action_confirm()
        picking.action_assign()
        self._validate(picking)
        self.assertEqual(picking.state, 'done')
        self.assertEqual(self._svl(), self.env['stock.valuation.layer'])
        self.assertEqual(self._account_moves(picking), self.env['account.move'])

    # ------------------------------------------------------------------
    # 3) Partial flow (backorder) stays accounting-neutral
    # ------------------------------------------------------------------
    def test_03_partial_flow_stays_accounting_neutral(self):
        lane = self._lane(self.wh_a, self.wh_b)
        self._add_stock(self.wh_a, self.product, 20)
        transfer = self._create_transfer(lane, self.product, 20)
        transfer.action_confirm()
        self._validate(transfer.dispatch_picking_ids)

        receipt = transfer.receipt_picking_ids
        self._validate(receipt, 15)
        transfer._ff_update_state()
        self.assertEqual(transfer.state, 'partially_received')
        backorder = transfer.receipt_picking_ids.filtered(lambda p: p.state != 'done')
        self.assertTrue(backorder)
        self._validate(backorder)
        transfer._ff_update_state()
        self.assertEqual(transfer.state, 'done')

        pickings = transfer.dispatch_picking_ids | transfer.receipt_picking_ids
        self.assertEqual(self._svl(), self.env['stock.valuation.layer'])
        self.assertEqual(self._account_moves(pickings), self.env['account.move'])
        self.assertEqual(self._on_hand(self.wh_b), 20.0)

    # ------------------------------------------------------------------
    # 4) Return to source stays accounting-neutral
    # ------------------------------------------------------------------
    def test_04_return_to_source_stays_accounting_neutral(self):
        lane = self._lane(self.wh_a, self.wh_b)
        self._add_stock(self.wh_a, self.product, 10)
        transfer = self._create_transfer(lane, self.product, 6)
        transfer.action_confirm()
        self._validate(transfer.dispatch_picking_ids)
        self._validate(transfer.receipt_picking_ids)
        self.assertEqual(transfer.state, 'done')

        # Return the received quantity back to the source warehouse.
        transfer.action_return_to_source()
        returned = transfer.return_picking_ids
        self.assertTrue(returned)
        self._validate(returned)
        transfer._ff_update_state()
        self.assertEqual(self._on_hand(self.wh_a), 10.0)
        self.assertEqual(self._on_hand(self.wh_b), 0.0)

        pickings = (transfer.dispatch_picking_ids | transfer.receipt_picking_ids
                    | transfer.return_picking_ids)
        self.assertEqual(self._svl(), self.env['stock.valuation.layer'])
        self.assertEqual(self._account_moves(pickings), self.env['account.move'])

    # ------------------------------------------------------------------
    # 5) Control: the valuation engine IS active (vendor receipt accounts)
    # ------------------------------------------------------------------
    def test_05_control_vendor_receipt_is_accounted(self):
        """A real incoming receipt DOES create an SVL + journal entry, proving
        the zero-entries above are intentional internal-move behaviour and not
        a broken valuation configuration."""
        pt = self.wh_a.in_type_id
        vendors = self.env.ref('stock.stock_location_suppliers')
        picking = self.env['stock.picking'].create({
            'picking_type_id': pt.id,
            'location_id': vendors.id,
            'location_dest_id': self.wh_a.lot_stock_id.id,
            'move_ids': [(0, 0, {
                'name': 'vendor receipt',
                'product_id': self.product.id,
                'product_uom_qty': 5,
                'product_uom': self.product.uom_id.id,
                'location_id': vendors.id,
                'location_dest_id': self.wh_a.lot_stock_id.id,
                'picking_type_id': pt.id,
                'company_id': self.company.id,
            })],
        })
        picking.action_confirm()
        picking.action_assign()
        self._validate(picking)
        self.assertEqual(picking.state, 'done')

        svls = self._svl()
        self.assertTrue(svls)
        self.assertEqual(sum(svls.mapped('value')), 5.0 * 100.0)
        moves = self._account_moves(picking)
        self.assertTrue(moves)
        # Journal entry must be balanced and use the valuation account.
        for am in moves:
            self.assertTrue(am._check_balanced())
        accounts = moves.mapped('line_ids.account_id')
        self.assertIn(self.stock_acc, accounts)

    # ------------------------------------------------------------------
    # 6) Manager scrap resolution IS accounted (loss entry)
    # ------------------------------------------------------------------
    def test_06_scrap_resolution_is_accounted(self):
        """The only ledger event of the flow: a manager resolving an in-transit
        difference scraps the missing quantity -> standard stock.scrap posts a
        loss through the valuation engine."""
        lane = self._lane(self.wh_a, self.wh_b)
        self._add_stock(self.wh_a, self.product, 8)
        transfer = self._create_transfer(lane, self.product, 4)
        transfer.action_confirm()
        self._validate(transfer.dispatch_picking_ids)
        # 4 units are now in transit (never received) -> resolve by scrapping.
        self.assertEqual(self._qty_at(lane.transit_location_id.id), 4.0)

        wizard = self.env['ff.interwarehouse.resolve.wizard'].with_context(
            default_transfer_id=transfer.id).create({})
        self.assertTrue(wizard.line_ids)
        wizard.action_scrap()

        # A scrap creates an SVL (negative value) and a posted journal entry.
        svls = self._svl().filtered(lambda s: s.quantity < 0)
        self.assertTrue(svls)
        self.assertEqual(sum(svls.mapped('quantity')), -4.0)
        scrap_moves = self.env['stock.move'].search(
            [('scrapped', '=', True),
             ('product_id', '=', self.product.id)])
        self.assertTrue(scrap_moves)
        moves = self.env['account.move'].search(
            [('stock_move_id', 'in', scrap_moves.ids)])
        self.assertTrue(moves)
        for am in moves:
            self.assertTrue(am._check_balanced())
        accounts = moves.mapped('line_ids.account_id')
        self.assertIn(self.loss_acc, accounts)
