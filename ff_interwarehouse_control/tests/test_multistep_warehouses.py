# -*- coding: utf-8 -*-
"""Multi-step warehouse coverage.

These tests prove the module's architecture works when installed on a database
whose warehouses are ALREADY configured with multi-step operations (2-step or
3-step delivery / reception) - exactly the scenario of installing on a live DB.

Why it works: the inter-warehouse dispatch/receipt picking types are created
with ``code='internal'`` and the moves are internal moves
``Stock -> Transit`` / ``Transit -> Stock``. Internal moves do NOT get routed
through the warehouse's delivery/reception routes (Pick / Pack / Output /
Input / QC), so the flow stays a single internal move regardless of the
warehouse step configuration. These tests lock that behaviour in.
"""
from odoo.addons.ff_interwarehouse_control.hooks import post_init_hook

from .common import InterwarehouseCommon


class TestMultistepWarehouses(InterwarehouseCommon):

    def _new_2step_warehouse(self):
        """A warehouse pre-configured with 2-step reception + pick-ship
        delivery, the exact config of a live DB."""
        return self.env['stock.warehouse'].create({
            'name': 'WH-2step', 'code': 'WH2',
            'reception_steps': 'two_steps',
            'delivery_steps': 'pick_ship',
        })

    def _new_3step_warehouse(self):
        return self.env['stock.warehouse'].create({
            'name': 'WH-3step', 'code': 'WH3',
            'reception_steps': 'three_steps',
            'delivery_steps': 'pick_pack_ship',
        })

    def _assert_single_internal_move(self, picking, src, dest, picking_type):
        """The dispatch/receipt move must stay ONE internal move from src to
        dest - never split into the warehouse's Pack/Output/Input/QC steps."""
        self.assertEqual(len(picking.move_ids), 1)
        move = picking.move_ids
        self.assertEqual(move.location_id, src)
        self.assertEqual(move.location_dest_id, dest)
        self.assertEqual(move.picking_type_id, picking_type)

    # ------------------------------------------------------------------
    # 1) Setup on an existing 2-step warehouse (the "install on live DB" case)
    # ------------------------------------------------------------------
    def test_01_post_init_hook_equips_existing_2step_warehouse(self):
        wh_c = self._new_2step_warehouse()
        # Simulate a warehouse that existed BEFORE the module was installed:
        # drop the inter-warehouse operation types and forget the links.
        old_dispatch = wh_c.ff_dispatch_picking_type_id
        old_receipt = wh_c.ff_receipt_picking_type_id
        wh_c.write({
            'ff_dispatch_picking_type_id': False,
            'ff_receipt_picking_type_id': False,
        })
        old_dispatch.unlink()
        old_receipt.unlink()
        self.assertFalse(wh_c.ff_dispatch_picking_type_id)
        self.assertFalse(wh_c.ff_receipt_picking_type_id)

        # Now run the actual install hook.
        post_init_hook(self.env)

        # The hook must equip the pre-existing 2-step warehouse.
        wh_c.invalidate_recordset(['ff_dispatch_picking_type_id',
                                   'ff_receipt_picking_type_id'])
        self.assertTrue(wh_c.ff_dispatch_picking_type_id)
        self.assertTrue(wh_c.ff_receipt_picking_type_id)
        self.assertEqual(wh_c.ff_dispatch_picking_type_id.code, 'internal')
        self.assertEqual(wh_c.ff_receipt_picking_type_id.code, 'internal')
        self.assertEqual(wh_c.ff_dispatch_picking_type_id.warehouse_id, wh_c)
        self.assertEqual(wh_c.ff_receipt_picking_type_id.warehouse_id, wh_c)
        # And lanes between the pre-existing warehouses must exist.
        self.assertTrue(self._lane(self.wh_a, wh_c))
        self.assertTrue(self._lane(wh_c, self.wh_a))

    # ------------------------------------------------------------------
    # 2) The install hook must NOT modify the existing step configuration
    # ------------------------------------------------------------------
    def test_02_setup_preserves_existing_step_config_and_is_idempotent(self):
        wh_c = self._new_2step_warehouse()
        in_type_before = wh_c.in_type_id
        out_type_before = wh_c.out_type_id
        dispatch_before = wh_c.ff_dispatch_picking_type_id
        receipt_before = wh_c.ff_receipt_picking_type_id

        # Re-run the setup several times (hook + create both call it).
        wh_c._ff_setup_interwarehouse_ops()
        wh_c._ff_setup_interwarehouse_ops()

        self.assertEqual(wh_c.reception_steps, 'two_steps')
        self.assertEqual(wh_c.delivery_steps, 'pick_ship')
        self.assertEqual(wh_c.in_type_id, in_type_before)
        self.assertEqual(wh_c.out_type_id, out_type_before)
        self.assertEqual(wh_c.ff_dispatch_picking_type_id, dispatch_before)
        self.assertEqual(wh_c.ff_receipt_picking_type_id, receipt_before)

    # ------------------------------------------------------------------
    # 3) Full flow INTO a 2-step reception warehouse (single internal move)
    # ------------------------------------------------------------------
    def test_03_transfer_into_2step_reception_warehouse(self):
        wh_c = self._new_2step_warehouse()
        lane = self._lane(self.wh_a, wh_c)
        self._add_stock(self.wh_a, self.product, 30)
        transfer = self._create_transfer(lane, self.product, 20)
        transfer.action_confirm()

        dispatch = transfer.dispatch_picking_ids
        self._assert_single_internal_move(
            dispatch, self.wh_a.lot_stock_id, lane.transit_location_id,
            self.wh_a.ff_dispatch_picking_type_id)
        self._validate_picking(dispatch)

        receipt = transfer.receipt_picking_ids
        self._assert_single_internal_move(
            receipt, lane.transit_location_id, wh_c.lot_stock_id,
            wh_c.ff_receipt_picking_type_id)
        self._validate_picking(receipt)

        self.assertEqual(transfer.state, 'done')
        self.assertEqual(self._on_hand(wh_c), 20.0)
        self.assertEqual(self._qty_at(lane.transit_location_id.id), 0.0)
        self.assertEqual(self._on_hand(self.wh_a), 10.0)

    # ------------------------------------------------------------------
    # 4) Full flow FROM a 2-step pick-ship warehouse (no Pick/Pack split)
    # ------------------------------------------------------------------
    def test_04_transfer_from_2step_pick_ship_warehouse(self):
        wh_c = self._new_2step_warehouse()
        lane = self._lane(wh_c, self.wh_a)
        self._add_stock(wh_c, self.product, 25)
        transfer = self._create_transfer(lane, self.product, 10)
        transfer.action_confirm()

        dispatch = transfer.dispatch_picking_ids
        self._assert_single_internal_move(
            dispatch, wh_c.lot_stock_id, lane.transit_location_id,
            wh_c.ff_dispatch_picking_type_id)
        # The move must NOT be routed through the Pick/Pack/Output chain.
        self.assertNotEqual(dispatch.move_ids.location_id, wh_c.wh_output_stock_loc_id)
        self._validate_picking(dispatch)

        receipt = transfer.receipt_picking_ids
        self._assert_single_internal_move(
            receipt, lane.transit_location_id, self.wh_a.lot_stock_id,
            self.wh_a.ff_receipt_picking_type_id)
        self._validate_picking(receipt)

        self.assertEqual(transfer.state, 'done')
        self.assertEqual(self._on_hand(self.wh_a), 10.0)
        self.assertEqual(self._on_hand(wh_c), 15.0)
        self.assertEqual(self._qty_at(lane.transit_location_id.id), 0.0)

    # ------------------------------------------------------------------
    # 5) Partial receipt with backorder into a 2-step destination
    # ------------------------------------------------------------------
    def test_05_partial_receipt_backorder_in_2step_destination(self):
        wh_c = self._new_2step_warehouse()
        lane = self._lane(self.wh_a, wh_c)
        self._add_stock(self.wh_a, self.product, 20)
        transfer = self._create_transfer(lane, self.product, 20)
        transfer.action_confirm()
        self._validate_picking(transfer.dispatch_picking_ids)

        receipt = transfer.receipt_picking_ids
        self._validate_picking(receipt, 15)
        transfer._ff_update_state()
        self.assertEqual(transfer.state, 'partially_received')
        backorder = transfer.receipt_picking_ids.filtered(lambda p: p.state != 'done')
        self.assertTrue(backorder)
        self.assertEqual(self._on_hand(wh_c), 15.0)
        self.assertEqual(self._qty_at(lane.transit_location_id.id), 5.0)

        # Receive the remaining quantity and finish.
        self._validate_picking(backorder)
        transfer._ff_update_state()
        self.assertEqual(transfer.state, 'done')
        self.assertEqual(self._on_hand(wh_c), 20.0)
        self.assertEqual(self._qty_at(lane.transit_location_id.id), 0.0)

    # ------------------------------------------------------------------
    # 6) 3-step warehouse, both directions (robustness beyond 2-step)
    # ------------------------------------------------------------------
    def test_06_three_step_warehouse_both_directions(self):
        wh_d = self._new_3step_warehouse()
        self.assertEqual(wh_d.reception_steps, 'three_steps')
        self.assertEqual(wh_d.delivery_steps, 'pick_pack_ship')

        # A -> D (receive into a 3-step warehouse).
        lane_ad = self._lane(self.wh_a, wh_d)
        self._add_stock(self.wh_a, self.product, 20)
        t1 = self._create_transfer(lane_ad, self.product, 10)
        t1.action_confirm()
        self._assert_single_internal_move(
            t1.dispatch_picking_ids, self.wh_a.lot_stock_id,
            lane_ad.transit_location_id, self.wh_a.ff_dispatch_picking_type_id)
        self._validate_picking(t1.dispatch_picking_ids)
        self._assert_single_internal_move(
            t1.receipt_picking_ids, lane_ad.transit_location_id,
            wh_d.lot_stock_id, wh_d.ff_receipt_picking_type_id)
        self._validate_picking(t1.receipt_picking_ids)
        self.assertEqual(t1.state, 'done')
        self.assertEqual(self._on_hand(wh_d), 10.0)

        # D -> A (dispatch from a 3-step warehouse).
        lane_da = self._lane(wh_d, self.wh_a)
        self._add_stock(wh_d, self.product, 5)
        t2 = self._create_transfer(lane_da, self.product, 5)
        t2.action_confirm()
        self._assert_single_internal_move(
            t2.dispatch_picking_ids, wh_d.lot_stock_id,
            lane_da.transit_location_id, wh_d.ff_dispatch_picking_type_id)
        self._validate_picking(t2.dispatch_picking_ids)
        self._validate_picking(t2.receipt_picking_ids)
        self.assertEqual(t2.state, 'done')
        self.assertEqual(self._on_hand(self.wh_a), 10.0 + 5.0)
        # D received 10 via t1, +5 added, then 5 dispatched via t2 = 10 left.
        self.assertEqual(self._on_hand(wh_d), 10.0)
