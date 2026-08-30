# -*- coding: utf-8 -*-
{
    'name': 'Inter-Warehouse Control',
    'version': '18.0.1.1.0',
    'category': 'Inventory',
    'summary': 'Inter-warehouse transfers with lane transit tracking and real per-warehouse user security',
    'description': """
Inter-Warehouse Control
=======================

Production-ready Odoo 18 Community module for inter-warehouse transfers and
per-warehouse stock visibility.

* Directed inter-warehouse transfers through lane-specific transit locations:
  ``A/Stock -> Transit A->B -> B/Stock`` (never ``A/Stock -> B/Stock`` directly).
* Clear audit trail per product line: Requested / Dispatched / Received /
  Pending Dispatch / In Transit / Returned / Scrapped.
* Standard Odoo backorder mechanism for partial dispatch and partial receipt
  (no silent quantity changes, no automatic scrap, no automatic return).
* Controlled actions for in-transit differences: "Return to Source" and
  "Resolve Difference (Scrap)", both manager-guarded.
* Real warehouse security built on ACLs + ``ir.rule`` (not view domains):
  a restricted user only sees their own warehouse stock, locations, quants,
  pickings, moves and operation types - including on the product form
  (``qty_available`` / ``free_qty`` / ``incoming_qty`` / ``outgoing_qty`` /
  ``virtual_available``), ``read_group`` and RPC-style searches.
* Inter-warehouse lane used as the only endpoint: a sender can dispatch to a
  destination warehouse without ever reading its stock.
* Idempotent automatic setup of lanes and operation types for existing and new
  warehouses (``N * (N-1)`` directed lanes, no per-lane routes / picking types).
* Multi-company safe, upgrade-safe, no monkey patching, no core Odoo changes.
    """,
    'author': 'Flous Flow',
    'website': 'https://flousflow.com',
    'license': 'LGPL-3',
    'depends': [
        'stock',
        'mail',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/sequence.xml',
        'views/interwarehouse_lane_views.xml',
        'views/interwarehouse_transfer_views.xml',
        'views/stock_warehouse_views.xml',
        'views/stock_picking_views.xml',
        'views/res_users_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/partial_receipt_wizard_views.xml',
        'wizard/return_wizard_views.xml',
        'wizard/resolve_transit_wizard_views.xml',
        'views/menus.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'images': [
        'static/description/thumbnail.png',
        'static/description/banner.png',
        'static/description/cover.png',
        'static/description/icon.png',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
