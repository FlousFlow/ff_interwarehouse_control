# -*- coding: utf-8 -*-
from odoo.tests import tagged
from .common import InterwarehouseCommon


@tagged('standard', 'ff_interwarehouse', 'multicompany')
class TestMultiCompany(InterwarehouseCommon):

    def test_01_cross_company_lane_rejected(self):
        company2 = self.env['res.company'].create({'name': 'Company 2'})
        wh_c2 = self.env['stock.warehouse'].create({
            'name': 'WH-C2', 'code': 'WC2', 'company_id': company2.id})
        with self.assertRaises(Exception):
            self.env['ff.interwarehouse.lane'].create({
                'source_warehouse_id': self.wh_a.id,
                'destination_warehouse_id': wh_c2.id,
                'company_id': self.company.id,
            })

    def test_02_allowed_warehouses_company_constraint(self):
        company2 = self.env['res.company'].create({'name': 'Company 2'})
        wh_c2 = self.env['stock.warehouse'].create({
            'name': 'WH-C2', 'code': 'WC2', 'company_id': company2.id})
        user = self.env['res.users'].create({
            'name': 'MultiCo User',
            'login': 'multico_user',
            'password': 'password',
            'groups_id': [(6, 0, [self.env.ref('stock.group_stock_user').id,
                                  self.env.ref('ff_interwarehouse_control.group_restricted_warehouse_user').id])],
            'company_id': self.company.id,
            'company_ids': [(6, 0, [self.company.id])],
        })
        # Warehouse of a company the user is not in -> rejected
        with self.assertRaises(Exception):
            user.write({'allowed_warehouse_ids': [(6, 0, [wh_c2.id])]})

    def test_03_no_cross_company_lane_in_auto_setup(self):
        company2 = self.env['res.company'].create({'name': 'Company 2'})
        self.env['stock.warehouse'].create({
            'name': 'WH-C2', 'code': 'WC2', 'company_id': company2.id})
        self.env['ff.interwarehouse.lane']._ff_setup_all()
        lanes = self.env['ff.interwarehouse.lane'].search([])
        cross = [l for l in lanes
                 if l.source_warehouse_id.company_id != l.destination_warehouse_id.company_id]
        self.assertEqual(len(cross), 0)
        # every lane is same-company
        for lane in lanes:
            self.assertEqual(lane.company_id, lane.source_warehouse_id.company_id)
            self.assertEqual(lane.company_id, lane.destination_warehouse_id.company_id)
