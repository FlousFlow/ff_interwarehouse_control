# -*- coding: utf-8 -*-
from odoo.tests import tagged
from .common import InterwarehouseCommon


@tagged('standard', 'ff_interwarehouse', 'auto_setup')
class TestAutoSetup(InterwarehouseCommon):
    """Automatic lane setup - idempotent, covers the N*(N-1) matrix."""

    def test_01_lanes_created_for_two_warehouses(self):
        lanes = self.env['ff.interwarehouse.lane'].search([
            ('source_warehouse_id', 'in', (self.wh_a | self.wh_b).ids),
            ('destination_warehouse_id', 'in', (self.wh_a | self.wh_b).ids),
        ])
        self.assertTrue(lanes.filtered(
            lambda l: l.source_warehouse_id == self.wh_a
            and l.destination_warehouse_id == self.wh_b))
        self.assertTrue(lanes.filtered(
            lambda l: l.source_warehouse_id == self.wh_b
            and l.destination_warehouse_id == self.wh_a))
        self.assertEqual(len(lanes), 2)

    def test_02_new_warehouse_gets_all_missing_lanes(self):
        wh_c = self.env['stock.warehouse'].create({'name': 'WH-C', 'code': 'WHC'})
        lanes = self.env['ff.interwarehouse.lane'].search([
            ('source_warehouse_id', 'in', (self.wh_a | self.wh_b | wh_c).ids),
            ('destination_warehouse_id', 'in', (self.wh_a | self.wh_b | wh_c).ids),
        ])
        expected = {('WHA', 'WHB'), ('WHB', 'WHA'),
                    ('WHA', 'WHC'), ('WHC', 'WHA'),
                    ('WHB', 'WHC'), ('WHC', 'WHB')}
        actual = {(l.source_warehouse_id.code, l.destination_warehouse_id.code)
                  for l in lanes}
        self.assertEqual(actual, expected)

    def test_03_setup_is_idempotent(self):
        before = self.env['ff.interwarehouse.lane'].search_count([])
        self.env['ff.interwarehouse.lane']._ff_setup_all()
        self.env['ff.interwarehouse.lane']._ff_setup_all()
        self.env['ff.interwarehouse.lane']._ff_setup_for_company(self.company)
        after = self.env['ff.interwarehouse.lane'].search_count([])
        # running the setup many times never creates duplicates
        self.assertEqual(before, after)
        # the A<->B pair exists exactly once in each direction
        self.assertEqual(len(self.env['ff.interwarehouse.lane'].search([
            ('source_warehouse_id', '=', self.wh_a.id),
            ('destination_warehouse_id', '=', self.wh_b.id)])), 1)
        self.assertEqual(len(self.env['ff.interwarehouse.lane'].search([
            ('source_warehouse_id', '=', self.wh_b.id),
            ('destination_warehouse_id', '=', self.wh_a.id)])), 1)

    def test_04_each_lane_owns_a_transit_location(self):
        lane_ab = self._lane(self.wh_a, self.wh_b)
        lane_ba = self._lane(self.wh_b, self.wh_a)
        self.assertTrue(lane_ab.transit_location_id)
        self.assertTrue(lane_ba.transit_location_id)
        self.assertNotEqual(lane_ab.transit_location_id.id, lane_ba.transit_location_id.id)
        self.assertEqual(lane_ab.transit_location_id.usage, 'transit')
        self.assertEqual(lane_ab.transit_location_id.company_id, self.company)
        # duplicate lane rejected by SQL constraint
        with self.assertRaises(Exception):
            self.env['ff.interwarehouse.lane'].create({
                'source_warehouse_id': self.wh_a.id,
                'destination_warehouse_id': self.wh_b.id,
                'company_id': self.company.id,
            })
        # self-lane rejected
        with self.assertRaises(Exception):
            self.env['ff.interwarehouse.lane'].create({
                'source_warehouse_id': self.wh_a.id,
                'destination_warehouse_id': self.wh_a.id,
                'company_id': self.company.id,
            })

    def test_05_warehouse_gets_operation_types(self):
        self.assertTrue(self.wh_a.ff_dispatch_picking_type_id)
        self.assertTrue(self.wh_a.ff_receipt_picking_type_id)
        self.assertTrue(self.wh_b.ff_dispatch_picking_type_id)
        self.assertTrue(self.wh_b.ff_receipt_picking_type_id)
        self.assertEqual(self.wh_a.ff_dispatch_picking_type_id.create_backorder, 'always')
        self.assertEqual(self.wh_a.ff_receipt_picking_type_id.create_backorder, 'always')
