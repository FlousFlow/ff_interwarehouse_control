# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.exceptions import AccessError, UserError
from .common import InterwarehouseCommon


@tagged('standard', 'ff_interwarehouse', 'security')
class TestSecurity(InterwarehouseCommon):
    """Warehouse security via ir.rule - no quantity / record leakage."""

    def setUp(self):
        super().setUp()
        self.user_a = self._create_user('User A', 'user_a_sec', [self.wh_a])
        self.user_b = self._create_user('User B', 'user_b_sec', [self.wh_b])
        self.env_a = self.env(user=self.user_a.id)
        self.env_b = self.env(user=self.user_b.id)
        self._add_stock(self.wh_a, self.product, 10)
        self._add_stock(self.wh_b, self.product, 90)

    def test_01_read_own_warehouse_only(self):
        WhA = self.env_a['stock.warehouse']
        found = WhA.search([('id', 'in', (self.wh_a | self.wh_b).ids)])
        self.assertEqual(found.ids, [self.wh_a.id])
        # direct read of a hidden warehouse raises AccessError
        with self.assertRaises(AccessError):
            WhA.browse(self.wh_b.id).read(['name'])

    def test_02_locations_scoped(self):
        LocA = self.env_a['stock.location']
        self.assertEqual(LocA.search([('id', '=', self.wh_a.lot_stock_id.id)]).ids,
                         [self.wh_a.lot_stock_id.id])
        self.assertEqual(LocA.search([('id', '=', self.wh_a.view_location_id.id)]).ids,
                         [self.wh_a.view_location_id.id])
        self.assertEqual(LocA.search([('id', '=', self.wh_b.lot_stock_id.id)]).ids, [])
        with self.assertRaises(AccessError):
            LocA.browse(self.wh_b.lot_stock_id.id).read(['name'])

    def test_03_quants_scoped(self):
        QuantA = self.env_a['stock.quant']
        self.assertTrue(QuantA.search(
            [('location_id', '=', self.wh_a.lot_stock_id.id)]))
        self.assertFalse(QuantA.search(
            [('location_id', '=', self.wh_b.lot_stock_id.id)]))

    def test_04_pickings_scoped(self):
        lane_ab = self._lane(self.wh_a, self.wh_b)
        transfer = self._create_transfer(lane_ab, self.product, 10)
        transfer.action_confirm()
        dispatch = transfer.dispatch_picking_ids
        self.assertTrue(dispatch)
        # both parties can search the dispatch picking
        self.assertEqual(self.env_a['stock.picking'].search(
            [('id', '=', dispatch.id)]).ids, [dispatch.id])
        self.assertEqual(self.env_b['stock.picking'].search(
            [('id', '=', dispatch.id)]).ids, [dispatch.id])

    def test_05_transfer_endpoint_without_reading_destination(self):
        lane_ab = self._lane(self.wh_a, self.wh_b)
        # user A sees lane A->B and can create a transfer
        self.assertEqual(self.env_a['ff.interwarehouse.lane'].search(
            [('id', '=', lane_ab.id)]).ids, [lane_ab.id])
        transfer = self._create_transfer(
            lane_ab, self.product, 10, env=self.env_a)
        transfer.action_confirm()
        self.assertEqual(transfer.state, 'confirmed')
        # destination name is visible (stored display), B stock is not
        self.assertEqual(transfer.destination_name, self.wh_b.name)
        self.assertEqual(self.env_a['stock.warehouse'].search(
            [('id', '=', self.wh_b.id)]).ids, [])

    def test_06_receiver_validates_incoming(self):
        lane_ab = self._lane(self.wh_a, self.wh_b)
        self._add_stock(self.wh_a, self.product, 100)
        transfer = self._create_transfer(lane_ab, self.product, 100)
        transfer.action_confirm()
        self._dispatch_all(transfer)
        transfer.invalidate_recordset()
        receipt = transfer.receipt_picking_ids
        self.assertTrue(receipt)

        # user B sees the incoming transfer and the receipt picking (search)
        self.assertEqual(self.env_b['ff.interwarehouse.transfer'].search(
            [('id', '=', transfer.id)]).ids, [transfer.id])
        self.assertEqual(self.env_b['stock.picking'].search(
            [('id', '=', receipt.id)]).ids, [receipt.id])

        # user B validates the receipt
        receipt_b = self.env_b['stock.picking'].browse(receipt.id)
        self._validate_picking(receipt_b)
        transfer.invalidate_recordset()
        self.assertEqual(transfer.line_ids.received_qty, 100)
        # user B still cannot read A's stock
        self.assertEqual(self.env_b['stock.quant'].search(
            [('location_id', '=', self.wh_a.lot_stock_id.id)]).ids, [])
        self.assertEqual(self.env_b['stock.location'].search(
            [('id', '=', self.wh_a.lot_stock_id.id)]).ids, [])

    def test_07_rpc_like_search_blocked(self):
        self.assertEqual(
            self.env_a['stock.warehouse'].search([('id', '=', self.wh_b.id)]).ids, [])
        self.assertEqual(
            self.env_a['stock.location'].search(
                [('id', '=', self.wh_b.lot_stock_id.id)]).ids, [])
        self.assertEqual(
            self.env_a['stock.quant'].search(
                [('location_id', '=', self.wh_b.lot_stock_id.id)]).ids, [])

    def test_08_read_group_scoped(self):
        res = self.env_a['stock.quant'].read_group(
            [('product_id', '=', self.product.id)],
            ['quantity:sum'], ['location_id'])
        total = sum(r['quantity'] for r in res)
        self.assertEqual(total, 10)
        loc_ids = {r['location_id'][0] for r in res if r['location_id']}
        self.assertNotIn(self.wh_b.lot_stock_id.id, loc_ids)

    def test_09_fail_closed_when_no_allowed_warehouse(self):
        user_none = self._create_user('User None', 'user_none', [])
        env_none = self.env(user=user_none.id)
        self.assertEqual(env_none['stock.warehouse'].search([]).ids, [])
        self.assertEqual(env_none['stock.quant'].search([]).ids, [])

    def test_10_admin_bypass(self):
        self.assertTrue(self.env['stock.warehouse'].browse(self.wh_b.id).exists())
        quants = self.env['stock.quant'].search(
            [('product_id', '=', self.product.id)])
        self.assertEqual(sum(quants.mapped('quantity')), 100)

    def test_11_users_cannot_edit_own_warehouse_access(self):
        # a non-manager user cannot change their own restriction
        me = self.env_a['res.users'].browse(self.user_a.id)
        with self.assertRaises(UserError):
            me.write({'warehouse_restriction_enabled': False})
        with self.assertRaises(UserError):
            me.write({'allowed_warehouse_ids': [(6, 0, [self.wh_b.id])]})

    def test_12_manager_can_edit_warehouse_access(self):
        manager = self._create_user('Manager', 'manager_sec', [self.wh_a],
                                    restricted=False, manager=True)
        manager.write({'allowed_warehouse_ids': [(6, 0, [self.wh_b.id])]})
        self.assertEqual(manager.allowed_warehouse_ids, self.wh_b)
