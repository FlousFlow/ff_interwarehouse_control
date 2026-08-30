# -*- coding: utf-8 -*-
from odoo.tests import tagged
from .common import InterwarehouseCommon


@tagged('standard', 'ff_interwarehouse', 'flow')
class TestTransferFlow(InterwarehouseCommon):
    """Full transfer: dispatch -> transit -> receipt -> done."""

    def test_full_transfer(self):
        lane_ab = self._lane(self.wh_a, self.wh_b)
        self._add_stock(self.wh_a, self.product, 100)

        transfer = self._create_transfer(lane_ab, self.product, 100)
        self.assertEqual(transfer.state, 'draft')
        transfer.action_confirm()
        self.assertEqual(transfer.state, 'confirmed')

        dispatch = transfer.dispatch_picking_ids
        self.assertTrue(dispatch)
        self.assertEqual(dispatch.ff_interwarehouse_role, 'dispatch')
        self.assertEqual(dispatch.location_id, self.wh_a.lot_stock_id)
        self.assertEqual(dispatch.location_dest_id, lane_ab.transit_location_id)

        # validate dispatch fully
        self._dispatch_all(transfer)
        transfer.invalidate_recordset()
        self.assertEqual(transfer.line_ids.dispatched_qty, 100)
        self.assertEqual(transfer.state, 'in_transit')
        self.assertEqual(self._on_hand(self.wh_a), 0)
        self.assertEqual(self._qty_at(lane_ab.transit_location_id.id), 100)
        self.assertEqual(self._on_hand(self.wh_b), 0)

        # receipt picking auto-created
        receipt = transfer.receipt_picking_ids
        self.assertTrue(receipt)
        self.assertEqual(receipt.ff_interwarehouse_role, 'receipt')
        self.assertEqual(receipt.location_id, lane_ab.transit_location_id)
        self.assertEqual(receipt.location_dest_id, self.wh_b.lot_stock_id)

        # validate receipt fully
        self._receive_all(transfer)
        transfer.invalidate_recordset()
        self.assertEqual(transfer.line_ids.received_qty, 100)
        self.assertEqual(transfer.line_ids.in_transit_qty, 0)
        self.assertEqual(transfer.state, 'done')
        self.assertEqual(self._qty_at(lane_ab.transit_location_id.id), 0)
        self.assertEqual(self._on_hand(self.wh_b), 100)
        self.assertTrue(transfer.completion_date)

    def test_requested_dispatched_received_audit(self):
        lane_ab = self._lane(self.wh_a, self.wh_b)
        self._add_stock(self.wh_a, self.product, 100)
        transfer = self._create_transfer(lane_ab, self.product, 100)
        transfer.action_confirm()
        self._dispatch_all(transfer)
        self._receive_all(transfer)
        line = transfer.line_ids
        self.assertEqual(line.requested_qty, 100)
        self.assertEqual(line.dispatched_qty, 100)
        self.assertEqual(line.received_qty, 100)
        self.assertEqual(line.pending_dispatch_qty, 0)
        self.assertEqual(line.in_transit_qty, 0)

    def test_edit_restriction_after_dispatch(self):
        lane_ab = self._lane(self.wh_a, self.wh_b)
        self._add_stock(self.wh_a, self.product, 100)
        transfer = self._create_transfer(lane_ab, self.product, 100)
        transfer.action_confirm()
        self._dispatch_all(transfer)
        transfer.invalidate_recordset()
        # cannot change lane
        with self.assertRaises(Exception):
            transfer.write({'lane_id': self._lane(self.wh_b, self.wh_a).id})
        # cannot change line requested qty
        with self.assertRaises(Exception):
            transfer.line_ids.write({'requested_qty': 200})
        # cannot unlink a line
        with self.assertRaises(Exception):
            transfer.line_ids.unlink()

    def test_cancel_draft_and_confirmed(self):
        lane_ab = self._lane(self.wh_a, self.wh_b)
        transfer = self._create_transfer(lane_ab, self.product, 10)
        transfer.action_cancel()
        self.assertEqual(transfer.state, 'cancelled')

    def test_cannot_cancel_after_dispatch(self):
        lane_ab = self._lane(self.wh_a, self.wh_b)
        self._add_stock(self.wh_a, self.product, 100)
        transfer = self._create_transfer(lane_ab, self.product, 100)
        transfer.action_confirm()
        self._dispatch_all(transfer)
        transfer.invalidate_recordset()
        with self.assertRaises(Exception):
            transfer.action_cancel()
