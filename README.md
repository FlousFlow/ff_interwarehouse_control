# Inter-Warehouse Control (Odoo 18 Community)

Production-ready Odoo 18 Community module for inter-warehouse transfers with
**lane transit tracking** and **real per-warehouse user security**.

> Built for Odoo **18.0** Community. It does not depend on Enterprise modules,
> does not modify core Odoo, does not monkey-patch, and does not re-implement
> the stock engine.

---

## Purpose

In a company with several warehouses (Cairo, Alexandria, Mansoura, Giza), a
warehouse user should:

* see **only their own warehouse** stock, locations, quantities, receipts,
  deliveries, internal operations and inventory adjustments;
* not see other warehouses' balances, locations, quantities or pickings;
* still be able to send goods to / receive goods from another warehouse,
  **without ever gaining full access** to the other warehouse.

An inter-warehouse transfer never goes `A/Stock -> B/Stock` directly. It always
goes through a lane-specific transit location:

```
A/Stock  ->  Transit A->B  ->  B/Stock
```

If A sends 100 and B confirms only 90, then:

```
Sent 100 | Received 90 | In Transit 10 | B/Stock +90 | Transit A->B +10
```

The outstanding 10 stays **in transit** as a standard Odoo backorder - it is
never silently received, returned, scrapped or cancelled.

---

## Features

### Inter-warehouse lanes and automatic setup
* Directed lane model `ff.interwarehouse.lane` (e.g. `Cairo -> Alexandria` is
  different from `Alexandria -> Cairo`).
* Each lane owns a dedicated `usage="transit"` location, so transit quantities
  are always attributed to one specific direction.
* Idempotent automatic setup: on install, all existing warehouses are
  discovered and every missing lane is created. When a new warehouse is
  created, its lanes with every other warehouse of the same company are created
  automatically. Running the setup many times never creates duplicates.
* `N * (N - 1)` directed lanes, but **no per-lane routes or operation types** -
  each warehouse only gets two operation types: *Inter-Warehouse Dispatch* and
  *Inter-Warehouse Receipt*.

### Master transfer + audit trail
* `ff.interwarehouse.transfer` (master) + `ff.interwarehouse.transfer.line`.
* Per product line, stored audit quantities:
  `Requested`, `Dispatched`, `Received`, `Returned`, `Scrapped`, plus computed
  `Pending Dispatch = Requested - Dispatched` and
  `In Transit = Dispatched - Received - Returned - Scrapped`.
* `Received > Dispatched` is blocked by a real constraint.
* Master state (`draft, confirmed, partially_dispatched, in_transit,
  partially_received, done, cancelled`) is derived from the real pickings
  through the `stock.picking._action_done` hooks - not from button clicks.

### Partial dispatch / partial receipt (standard backorders)
* Dispatch and receipt operation types use `create_backorder = always`, so a
  partial dispatch or partial receipt automatically creates a standard Odoo
  backorder that keeps all the inter-warehouse links.
* Partial receipt reason is optional/configurable (physical shortage, damaged
  in transit, counting difference, partial delivery, other) and never changes
  quantities.

### Controlled resolution of transit differences
* **Return to Source**: explicit, audited action that moves the in-transit
  quantity back to the source via a standard picking.
* **Resolve Difference (Scrap)**: manager-only action using the standard Odoo
  scrap mechanism, requiring a reason, note, responsible and date.
* Nothing is ever cancelled, scrapped or returned automatically.

### Real warehouse security (ACL + record rules)
* New group **Restricted Warehouse User** (`ff.group_restricted_warehouse_user`).
* New group **Global Warehouse Manager** (`ff.group_interwarehouse_manager`).
* `res.users` gets `warehouse_restriction_enabled` + `allowed_warehouse_ids`.
* `ir.rule` record rules (not view domains) restrict for restricted users:
  `stock.warehouse`, `stock.location`, `stock.quant`, `stock.picking`,
  `stock.picking.type`, `stock.move`, `stock.move.line`, `stock.scrap` and the
  module's own models.
* Because the rules live on `stock.quant` / `stock.move`, the product form
  quantities (`qty_available`, `free_qty`, `incoming_qty`, `outgoing_qty`,
  `virtual_available`), `read_group` and RPC-style `search`/`read` are all
  scoped to the allowed warehouses - no warehouse-balance leakage.
* **Fail closed**: enabled restriction with an empty allowed list = no internal
  warehouse stock visible at all.
* The inter-warehouse **lane is the only endpoint** for selecting a destination:
  a sender chooses the lane and sees a stored destination *name*, but cannot
  open the destination warehouse, its locations or its stock.
* Administrators and the Global Warehouse Manager bypass the restrictions and
  keep full multi-company-aware access.

### Multi-company
* Lanes are always same-company; cross-company lanes are rejected.
* `allowed_warehouse_ids` is constrained to the user's allowed companies.
* All record rules are ANDed with the standard multi-company rules.

---

## Installation

1. Copy `ff_interwarehouse_control` into your addons path.
2. Restart Odoo, then install the module from *Apps*.

Or from the command line:

```bash
./odoo-bin -d mydb -i ff_interwarehouse_control --stop-after-init
```

On install, the module automatically:
1. creates the company-level transit root location;
2. discovers all active warehouses;
3. creates every missing lane (and its transit location);
4. creates the *Inter-Warehouse Dispatch* / *Inter-Warehouse Receipt* operation
   types for every warehouse.

---

## User guide

### Warehouse auto setup
Nothing to do - it runs automatically on install and on every new warehouse.
You can also run it manually (as a manager) from the **Inter-Warehouse Lanes**
menu, or re-open the settings block **Inter-Warehouse Control**.

### Sending a transfer
1. Open **Inventory > Operations > Inter-Warehouse Transfers > New**.
2. Pick the lane (e.g. `Cairo -> Alexandria`), add product lines and quantities.
3. **Confirm**. A dispatch picking `Cairo/Stock -> Transit Cairo->Alexandria`
   is created.
4. Validate the dispatch picking. A receipt picking
   `Transit Cairo->Alexandria -> Alexandria/Stock` is created automatically and
   the destination responsible users are notified.
5. Partial dispatch? The remaining quantity stays as a standard backorder.

### Receiving a transfer
1. The destination user sees the incoming transfer and the receipt picking.
2. Validate the receipt. Partial receipt creates a standard backorder for the
   outstanding quantity and notifies the initiator.
3. When everything is received the transfer becomes **Done**.

### In-transit difference
* **Return to Source**: open the transfer > *Return to Source* > confirm the
  quantity. A standard picking moves it back from the transit location.
* **Resolve Difference (Scrap)**: manager only, standard scrap, requires reason.

---

## Security model (summary)

| Resource | Restricted warehouse user sees |
|---|---|
| `stock.warehouse` | only `allowed_warehouse_ids` |
| `stock.location` | allowed warehouses' locations + own lane transits + global/shared locations |
| `stock.quant` | only quants in allowed warehouses / own lane transits |
| `stock.picking` | own warehouse operations + IWT pickings they are part of |
| `stock.move` / `stock.move.line` | only moves of allowed pickings / allowed locations |
| `stock.picking.type` | only operation types of allowed warehouses |
| `stock.scrap` | only scrap from allowed locations |
| Product quantities | scoped to allowed warehouses (via the quant/move rules) |

Administrators and the Global Warehouse Manager are never restricted.

---

## Known limitations

* The sender can see the receipt pickings and their move lines of a transfer
  they dispatched (this is intentional - the sender must see "received 90 /
  in transit 10"), but never the destination warehouse's total balance.
* `stock.lot` records are not directly restricted (a lot record carries no
  quantity); quantity/location confidentiality is enforced through the
  `stock.quant` and `stock.move.line` rules.
* Company-level operation types without a warehouse are hidden from restricted
  users.
* Odoo's standard cross-warehouse **resupply routes** are not created per lane
  (by design, to avoid O(N^2) configuration records); inter-warehouse movement
  is done through the module's transfer workflow.

## Tests

Run on a dedicated database (from the Odoo 18 project):

```bash
# Standard module test suite (43 functional tests + 6 accounting tests skipped
# when the stock_account registry is not loaded):
odoo --db_host=db --db_user=odoo --db_password=odoo -d ff_test \
     --test-enable -u ff_interwarehouse_control --stop-after-init --http-port=8072

# Full suite including the accounting-soundness tests (needs stock_account):
odoo --db_host=db --db_user=odoo --db_password=odoo -d ff_test \
     --test-enable -u ff_interwarehouse_control,stock_account --stop-after-init --http-port=8072
```

Result (verified on a fresh Odoo 18 Community DB and on a DB with `sale` /
`purchase` / `account` installed):

```
49 tests: 0 failed, 0 errors  (43 functional + 6 accounting-soundness)
```

Coverage:

* `test_auto_setup` - lane auto-setup, new warehouses, idempotency, per-lane
  transit locations, operation types.
* `test_transfer_flow` - full dispatch -> transit -> receipt -> done, audit
  quantities, edit restriction after dispatch, cancellation rules.
* `test_partial_receipt` - partial receipt with backorder and finish, partial
  dispatch, receive-more-than-sent is blocked, negative transit never happens,
  return to source, partial reason required.
* `test_security` - warehouse/location/quant/picking scoping, transfer
  endpoint, receiver access, RPC-like search blocked, read_group scoped,
  fail-closed, admin bypass, users cannot edit their own access.
* `test_multicompany` - cross-company lanes rejected, allowed-warehouses
  company constraint, no cross-company lanes in auto-setup.
* `test_quantity_visibility` - `qty_available` / `virtual_available` /
  `free_qty` / template quantities scoped per warehouse; in-transit visibility
  to both parties only.
* `test_multistep_warehouses` - works when installed on a DB whose warehouses
  are ALREADY configured with 2-step / 3-step reception & delivery: the flow
  stays a single internal move (never routed through Pick/Pack/Output/Input/QC),
  the install hook equips pre-existing warehouses, and the existing step
  configuration is never modified.
* `test_accounting` - **accounting-soundness**: an inter-warehouse transfer is
  an internal move between valued locations of the same company, so it creates
  no SVL and no journal entry (zero P&L), exactly like Odoo's own standard
  Internal Transfers; the only ledger event is the manager "Resolve Difference"
  (scrap) which posts a loss; a control test proves the valuation engine is
  active because a vendor receipt IS accounted.

### End-to-end proof (100 / 90 / 10)

```
after dispatch : A=0   Transit=100   B=0    Dispatched=100   state=in_transit
after receipt  : A=0   Transit=10    B=90   Received=90     state=partially_received
master line    : requested=100 dispatched=100 received=90 pending=0 intransit=10
backorder receipt exists: True
```

### Security proof (User A cannot access User B's quantities)

```
User A can search own warehouse      : [wa]
User A searching B warehouse         : []
User A searching B location          : []
User A searching B quants            : []
User A reading B warehouse           : BLOCKED (AccessError)
User B can search own warehouse      : [wb]
User B searching A quants            : []
User A qty_available (own only)      : 10   (not 100)
User B qty_available (own only)      : 90   (not 100)
Admin   qty_available (total)        : 100
```

## File tree

```
ff_interwarehouse_control/
├── __init__.py
├── __manifest__.py
├── hooks.py                        # post_init_hook: discover warehouses + setup
├── data/sequence.xml               # IWT/00001 master sequence
├── models/
│   ├── __init__.py
│   ├── interwarehouse_lane.py      # ff.interwarehouse.lane + auto setup
│   ├── interwarehouse_transfer.py  # master transfer + lines + hooks + notify
│   ├── stock_warehouse.py          # ops types, responsible users, archive guard
│   ├── stock_location.py           # ff_interwarehouse_lane_id on transit locations
│   ├── stock_picking.py            # ff_* fields + _action_done hook
│   ├── res_users.py                # warehouse_restriction_enabled + allowed_warehouse_ids
│   ├── res_company.py              # transit root location
│   └── res_config_settings.py      # Inter-Warehouse Control settings
├── security/
│   ├── security.xml                # groups
│   ├── ir.model.access.csv
│   └── record_rules.xml            # restricted warehouse user record rules
├── views/
│   ├── interwarehouse_transfer_views.xml
│   ├── interwarehouse_lane_views.xml
│   ├── stock_warehouse_views.xml
│   ├── stock_picking_views.xml
│   ├── res_users_views.xml
│   ├── res_config_settings_views.xml
│   └── menus.xml
├── wizard/
│   ├── partial_receipt_wizard.py (+views)   # partial receipt reason
│   ├── return_wizard.py (+views)            # Return to Source
│   └── resolve_transit_wizard.py (+views)   # Resolve Difference (scrap)
├── tests/
│   ├── __init__.py
│   ├── common.py
│   ├── test_auto_setup.py
│   ├── test_transfer_flow.py
│   ├── test_partial_receipt.py
│   ├── test_security.py
│   ├── test_multicompany.py
│   ├── test_quantity_visibility.py
│   ├── test_multistep_warehouses.py
│   └── test_accounting.py
├── static/description/icon.png, banner.png, thumbnail.png, cover.png, index.html
├── i18n/ar.po, ff_interwarehouse_control.pot
└── README.md
```

## License

LGPL-3
