# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tools import float_compare
from .common import InterwarehouseCommon


@tagged('standard', 'ff_interwarehouse', 'quantity')
class TestQuantityVisibility(InterwarehouseCommon):
    """No product-quantity leakage across warehouses."""

    def setUp(self):
        super().setUp()
        self._add_stock(self.wh_a, self.product, 10)
        self._add_stock(self.wh_b, self.product, 90)
        self.user_a = self._create_user('User A', 'user_a_qty', [self.wh_a])
        self.user_b = self._create_user('User B', 'user_b_qty', [self.wh_b])
        self.env_a = self.env(user=self.user_a.id)
        self.env_b = self.env(user=self.user_b.id)

    def _product_qty(self, env, field):
        # env(user=X) instances derived from the same base env share the record
        # cache; invalidate between reads so each user is evaluated in isolation
        # (as separate sessions would be).
        self.env.invalidate_all()
        product = env['product.product'].browse(self.product.id)
        return getattr(product, field)

    def test_01_qty_available_scoped(self):
        self.assertEqual(self._product_qty(self.env_a, 'qty_available'), 10)
        self.assertEqual(self._product_qty(self.env_b, 'qty_available'), 90)
        self.assertEqual(self._product_qty(self.env, 'qty_available'), 100)

    def test_02_virtual_available_scoped(self):
        self.assertEqual(self._product_qty(self.env_a, 'virtual_available'), 10)
        self.assertEqual(self._product_qty(self.env_b, 'virtual_available'), 90)
        self.assertEqual(self._product_qty(self.env, 'virtual_available'), 100)

    def test_03_free_qty_scoped(self):
        self.assertEqual(self._product_qty(self.env_a, 'free_qty'), 10)
        self.assertEqual(self._product_qty(self.env_b, 'free_qty'), 90)

    def test_04_template_quantity_scoped(self):
        self.env.invalidate_all()
        template = self.env_a['product.template'].browse(self.product.product_tmpl_id.id)
        self.assertEqual(template.qty_available, 10)
        self.env.invalidate_all()
        template_b = self.env_b['product.template'].browse(self.product.product_tmpl_id.id)
        self.assertEqual(template_b.qty_available, 90)

    def test_05_forecast_quantities_scoped(self):
        # incoming/outgoing are also driven by the move rule; with no open
        # moves they equal the scoped on-hand.
        self.assertEqual(self._product_qty(self.env_a, 'incoming_qty'), 0)
        self.assertEqual(self._product_qty(self.env_a, 'outgoing_qty'), 0)
        self.assertEqual(self._product_qty(self.env_a, 'qty_available'), 10)

    def test_06_in_transit_visible_to_both_parties_only(self):
        lane_ab = self._lane(self.wh_a, self.wh_b)
        self._add_stock(self.wh_a, self.product, 100)
        transfer = self._create_transfer(lane_ab, self.product, 100)
        transfer.action_confirm()
        self._dispatch_all(transfer)
        transfer.invalidate_recordset()
        # 10 (A) + 90 (B) already there, plus 100 now in transit
        transit = self._qty_at(lane_ab.transit_location_id.id)
        self.assertEqual(transit, 100)
        # user A sees the transit quants of their lane (source party)
        transit_q = self.env_a['stock.quant'].search(
            [('location_id', '=', lane_ab.transit_location_id.id)])
        self.assertTrue(transit_q)
        # user A's on-hand is scoped to its own warehouse only (10): the transit
        # quantity is never added to the generic on-hand nor does the company
        # total (100) leak. In-transit info is shown contextually on the
        # transfer / pickings instead.
        self.env.invalidate_all()
        self.assertEqual(self._product_qty(self.env_a, 'qty_available'), 10)
        # user B sees the same lane transit (destination party)
        transit_q_b = self.env_b['stock.quant'].search(
            [('location_id', '=', lane_ab.transit_location_id.id)])
        self.assertTrue(transit_q_b)
        # ... and B's on-hand is scoped to its own warehouse only
        self.env.invalidate_all()
        self.assertEqual(self._product_qty(self.env_b, 'qty_available'), 90)
