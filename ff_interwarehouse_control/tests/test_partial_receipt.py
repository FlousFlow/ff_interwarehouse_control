# -*- coding: utf-8 -*-
from odoo.tests import tagged
from .common import InterwarehouseCommon


@tagged('standard', 'ff_interwarehouse', 'partial')
class TestPartialReceipt(InterwarehouseCommon):
    """Partial receipt, partial dispatch and backorders."""

    def test_partial_receipt_backorder_and_finish(self):
        lane_ab = self._lane(self.wh_a, self.wh_b)
        self._add_stock(self.wh_a, self.product, 100)
        transfer = self._create_transfer(lane_ab, self.product, 100)
        transfer.action_confirm()
        self._dispatch_all(transfer)
        transfer.invalidate_recordset()
        self.assertEqual(transfer.line_ids.dispatched_qty, 100)

        # receive only 90
        self._receive_all(transfer, qty=90)
        transfer.invalidate_recordset()
        self.assertEqual(transfer.line_ids.received_qty, 90)
        self.assertEqual(transfer.line_ids.in_transit_qty, 10)
        self.assertEqual(transfer.state, 'partially_received')
        self.assertEqual(self._on_hand(self.wh_b), 90)
        self.assertEqual(self._qty_at(lane_ab.transit_location_id.id), 10)

        # a backorder receipt picking was created for the remaining 10
        backorders = transfer.receipt_picking_ids.filtered(
            lambda p: p.backorder_id)
        self.assertTrue(backorders)
        self.assertEqual(backorders.move_ids.product_uom_qty, 10)

        # finish the backorder
        backorder = backorders[0]
        self._validate_picking(backorder)
        transfer.invalidate_recordset()
        self.assertEqual(transfer.line_ids.received_qty, 100)
        self.assertEqual(transfer.line_ids.in_transit_qty, 0)
        self.assertEqual(transfer.state, 'done')
        self.assertEqual(self._on_hand(self.wh_b), 100)
        self.assertEqual(self._qty_at(lane_ab.transit_location_id.id), 0)

    def test_partial_dispatch(self):
        lane_ab = self._lane(self.wh_a, self.wh_b)
        self._add_stock(self.wh_a, self.product, 100)
        transfer = self._create_transfer(lane_ab, self.product, 100)
        transfer.action_confirm()
        dispatch = transfer.dispatch_picking_ids

        # dispatch only 70 (requested stays 100)
        self._validate_picking(dispatch, qty=70)
        transfer.invalidate_recordset()
        self.assertEqual(transfer.line_ids.requested_qty, 100)
        self.assertEqual(transfer.line_ids.dispatched_qty, 70)
        self.assertEqual(transfer.line_ids.pending_dispatch_qty, 30)
        self.assertEqual(transfer.state, 'partially_dispatched')
        self.assertEqual(self._qty_at(lane_ab.transit_location_id.id), 70)
        # a receipt picking for the dispatched 70 was created
        self.assertTrue(transfer.receipt_picking_ids)

        # a dispatch backorder exists for the remaining 30
        dispatch_backorder = transfer.dispatch_picking_ids.filtered(
            lambda p: p.backorder_id)
        self.assertTrue(dispatch_backorder)
        self._validate_picking(dispatch_backorder)
        transfer.invalidate_recordset()
        self.assertEqual(transfer.line_ids.dispatched_qty, 100)
        self.assertEqual(self._qty_at(lane_ab.transit_location_id.id), 100)

    def test_receive_more_than_sent_is_blocked(self):
        lane_ab = self._lane(self.wh_a, self.wh_b)
        self._add_stock(self.wh_a, self.product, 100)
        transfer = self._create_transfer(lane_ab, self.product, 100)
        transfer.action_confirm()
        self._dispatch_all(transfer)
        transfer.invalidate_recordset()
        self.assertEqual(transfer.line_ids.dispatched_qty, 100)

        # model-level constraint: received cannot exceed dispatched
        with self.assertRaises(Exception):
            transfer.line_ids.with_context(
                ff_allow_quantity_write=True).write({'received_qty': 120})
        # and physically you cannot receive more than what is in transit
        receipt = transfer.receipt_picking_ids[0]
        with self.assertRaises(Exception):
            self._validate_picking(receipt, qty=120)

    def test_negative_transit_never_happens(self):
        lane_ab = self._lane(self.wh_a, self.wh_b)
        self._add_stock(self.wh_a, self.product, 100)
        transfer = self._create_transfer(lane_ab, self.product, 100)
        transfer.action_confirm()
        self._dispatch_all(transfer)
        transfer.invalidate_recordset()
        line = transfer.line_ids
        self.assertGreaterEqual(line.in_transit_qty, 0)
        # returned/scrapped cannot exceed outstanding
        with self.assertRaises(Exception):
            line.with_context(ff_allow_quantity_write=True).write({'returned_qty': 200})

    def test_return_to_source(self):
        lane_ab = self._lane(self.wh_a, self.wh_b)
        self._add_stock(self.wh_a, self.product, 100)
        transfer = self._create_transfer(lane_ab, self.product, 100)
        transfer.action_confirm()
        self._dispatch_all(transfer)
        self._receive_all(transfer, qty=90)
        transfer.invalidate_recordset()
        self.assertEqual(transfer.line_ids.in_transit_qty, 10)

        # return the remaining 10 to source through the wizard
        wizard = self.env['ff.interwarehouse.return.wizard'].with_context(
            default_transfer_id=transfer.id).create({})
        self.assertEqual(wizard.line_ids.qty, 10)
        wizard.action_return()
        # the return picking must be validated to actually move the stock
        return_picking = transfer.return_picking_ids
        self.assertTrue(return_picking)
        self._validate_picking(return_picking)
        transfer.invalidate_recordset()

        # transit cleared, source got 10 back, destination still 90
        self.assertEqual(self._qty_at(lane_ab.transit_location_id.id), 0)
        self.assertEqual(self._on_hand(self.wh_a), 10)
        self.assertEqual(self._on_hand(self.wh_b), 90)
        self.assertEqual(transfer.line_ids.returned_qty, 10)
        self.assertEqual(transfer.line_ids.in_transit_qty, 0)

    def test_require_partial_reason_when_enabled(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'ff_interwarehouse_control.require_partial_reason', 'True')
        lane_ab = self._lane(self.wh_a, self.wh_b)
        self._add_stock(self.wh_a, self.product, 100)
        transfer = self._create_transfer(lane_ab, self.product, 100)
        transfer.action_confirm()
        self._dispatch_all(transfer)
        self._receive_all(transfer, qty=90)
        transfer.invalidate_recordset()

        wizard = self.env['ff.interwarehouse.partial.reason.wizard'].with_context(
            default_transfer_id=transfer.id).create({})
        with self.assertRaises(Exception):
            wizard.action_save()  # no reason set and it is required
        wizard.line_ids.write({'reason': 'physical_shortage'})
        wizard.action_save()
        self.assertEqual(transfer.line_ids.partial_receipt_reason, 'physical_shortage')
