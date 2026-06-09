# Audit Log Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich `address_offering` and `bulk_operation` audit log diffs with `technology_name` and `address_label` so the LMS plugin can display human-readable audit log rows without extra API calls.

**Architecture:** Backend adds denormalized human-readable fields at write time (correct at the time of the change, survives future renames). Two helper functions (`address_label_for_code`, `technology_display_name`) handle lookups. Plugin replaces raw JSON `<details>` with a 5-column friendly table.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + PostgreSQL (backend); PHP 8 + Smarty (plugin)

---

## File Map

**Create:**
- `app/db/audit_helpers.py` — `address_label_for_code()` and `technology_display_name()` DB helpers

**Modify (backend):**
- `app/api/v1/admin/addresses.py` — enrich diff in create/update/delete address_offering
- `app/api/v1/admin/bulk.py` — enrich bulk_operation logs + batch audit diffs in `_execute_*`

**Modify (tests):**
- `tests/api/test_audit.py` — add assertions for new diff fields in existing tests + new bulk test

**Modify (plugin — separate repo at `~/workspace/robertas/lms-etanetas/lms`):**
- `plugins/LMSEtaCoveragePlugin/modules/etacoverageaudit.php` — compute display fields per entity_type
- `plugins/LMSEtaCoveragePlugin/templates/eta/etacoverageaudit.html` — 5-column friendly view

---

## Task 1: Helper functions for audit diff enrichment

**Files:**
- Create: `app/db/audit_helpers.py`
- Modify: `tests/api/test_audit.py` (add helper tests at bottom)

- [ ] **Step 1: Write failing tests for helpers**

Add to the bottom of `tests/api/test_audit.py`:

```python
from app.db.audit_helpers import address_label_for_code, technology_display_name
import uuid as _uuid


@pytest.mark.integration
async def test_address_label_for_code_returns_label(db_session, seed_address):
    label = await address_label_for_code(db_session, seed_address)
    assert label is not None
    assert "1" in label        # house_no from seed_address fixture
    assert "Auditinkai" in label


@pytest.mark.integration
async def test_address_label_for_code_unknown_returns_none(db_session):
    label = await address_label_for_code(db_session, 999999999)
    assert label is None


@pytest.mark.integration
async def test_technology_display_name_returns_name(db_session, seed_tech):
    _, tech = seed_tech
    name = await technology_display_name(db_session, tech.id)
    assert name == "AuditVariant"


@pytest.mark.integration
async def test_technology_display_name_unknown_returns_none(db_session):
    name = await technology_display_name(db_session, _uuid.uuid4())
    assert name is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/api/test_audit.py::test_address_label_for_code_returns_label -v
```

Expected: `ImportError: cannot import name 'address_label_for_code'`

- [ ] **Step 3: Create `app/db/audit_helpers.py`**

```python
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.address_labels import _ADDR_JOINS, _FULL_ADDRESS


async def address_label_for_code(db: AsyncSession, rc_code: int) -> str | None:
    result = await db.execute(
        text(f"SELECT {_FULL_ADDRESS} AS label FROM addresses a {_ADDR_JOINS} WHERE a.rc_code = :rc_code"),
        {"rc_code": rc_code},
    )
    row = result.one_or_none()
    return row[0] if row else None


async def technology_display_name(db: AsyncSession, technology_id: uuid.UUID) -> str | None:
    from app.models.technology import Technology
    result = await db.execute(
        select(Technology.display_name).where(Technology.id == technology_id)
    )
    return result.scalar_one_or_none()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/api/test_audit.py::test_address_label_for_code_returns_label tests/api/test_audit.py::test_address_label_for_code_unknown_returns_none tests/api/test_audit.py::test_technology_display_name_returns_name tests/api/test_audit.py::test_technology_display_name_unknown_returns_none -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add app/db/audit_helpers.py tests/api/test_audit.py
git commit -m "feat: add address_label_for_code and technology_display_name helpers"
```

---

## Task 2: Enrich address_offering diffs in addresses.py

**Files:**
- Modify: `app/api/v1/admin/addresses.py`
- Modify: `tests/api/test_audit.py`

Context: Three endpoints in this file call `log_action()` for `address_offering`. Each needs `technology_name` and `address_label` added to the diff. The offering is already loaded before the log call in all three cases.

- [ ] **Step 1: Write failing test**

Add to `tests/api/test_audit.py`:

```python
@pytest.mark.integration
async def test_audit_diff_contains_enriched_fields(client, editor_user, admin_user, seed_address, seed_tech):
    _, editor_raw = editor_user
    _, admin_raw = admin_user
    _, tech = seed_tech

    await client.post(
        f"/api/v1/admin/addresses/{seed_address}/offerings",
        json={"technology_id": str(tech.id), "status": "available",
              "max_download_mbps": 100, "max_upload_mbps": 50, "status_since": "2026-01-01"},
        headers={"X-API-Key": editor_raw},
    )

    resp = await client.get(
        "/api/v1/admin/audit-log",
        params={"entity_type": "address_offering"},
        headers={"X-API-Key": admin_raw},
    )
    entry = next(e for e in resp.json()["items"] if e["action"] == "create")
    assert entry["diff"]["technology_name"] == "AuditVariant"
    assert "1" in entry["diff"]["address_label"]
    assert "Auditinkai" in entry["diff"]["address_label"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/api/test_audit.py::test_audit_diff_contains_enriched_fields -v
```

Expected: `KeyError: 'technology_name'`

- [ ] **Step 3: Add import and enrich create_address_offering diff**

In `app/api/v1/admin/addresses.py`, add the import after existing imports:

```python
from app.db.audit_helpers import address_label_for_code, technology_display_name
```

Then modify `create_address_offering` (currently line ~300–308). Replace:

```python
    await log_action(
        db,
        current_user.id,
        "address_offering",
        str(offering.id),
        "create",
        {"address_code": rc_code, **body.model_dump()},
        address_code=rc_code,
    )
```

With:

```python
    tech_name = await technology_display_name(db, body.technology_id)
    addr_label = await address_label_for_code(db, rc_code)
    await log_action(
        db,
        current_user.id,
        "address_offering",
        str(offering.id),
        "create",
        {"address_code": rc_code, "technology_name": tech_name, "address_label": addr_label, **body.model_dump()},
        address_code=rc_code,
    )
```

- [ ] **Step 4: Enrich update_address_offering diff**

Modify `update_address_offering` (currently line ~332–340). Replace:

```python
    await log_action(
        db,
        current_user.id,
        "address_offering",
        str(offering_id),
        "update",
        {"address_code": offering.address_code, **changes},
        address_code=offering.address_code,
    )
```

With:

```python
    tech_name = await technology_display_name(db, offering.technology_id)
    addr_label = await address_label_for_code(db, offering.address_code)
    await log_action(
        db,
        current_user.id,
        "address_offering",
        str(offering_id),
        "update",
        {"address_code": offering.address_code, "technology_name": tech_name, "address_label": addr_label, **changes},
        address_code=offering.address_code,
    )
```

- [ ] **Step 5: Enrich delete_address_offering diff**

Modify `delete_address_offering` (currently line ~360–368). The offering is loaded via `_require_offering` before `db.delete()`. Replace:

```python
    offering = await _require_offering(db, offering_id)
    address_code = offering.address_code
    await db.delete(offering)
    await log_action(
        db,
        current_user.id,
        "address_offering",
        str(offering_id),
        "delete",
        {"address_code": address_code},
        address_code=address_code,
    )
```

With:

```python
    offering = await _require_offering(db, offering_id)
    address_code = offering.address_code
    tech_name = await technology_display_name(db, offering.technology_id)
    addr_label = await address_label_for_code(db, address_code)
    await db.delete(offering)
    await log_action(
        db,
        current_user.id,
        "address_offering",
        str(offering_id),
        "delete",
        {"address_code": address_code, "technology_name": tech_name, "address_label": addr_label},
        address_code=address_code,
    )
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/api/test_audit.py -v
```

Expected: all PASSED (including existing `test_audit_log_created_on_offering_create`, `test_address_history`)

- [ ] **Step 7: Commit**

```bash
git add app/api/v1/admin/addresses.py tests/api/test_audit.py
git commit -m "feat: enrich address_offering audit diff with technology_name and address_label"
```

---

## Task 3: Enrich bulk_operation diffs and batch audit inserts

**Files:**
- Modify: `app/api/v1/admin/bulk.py`
- Modify: `tests/api/test_audit.py`

Five places to change:
1. `bulk_execute` log — add `technology_name`
2. `bulk_rollback` log — add `technology_name`
3. `_execute_add_offering` batch diff — add `technology_name` (pass as parameter)
4. `_execute_change_offering` batch diff — add `technology_name` (pass as parameter)
5. `_execute_remove_offering` batch diff — add `technology_name` (pass as parameter)

- [ ] **Step 1: Write failing test**

Add to `tests/api/test_audit.py`:

```python
@pytest.mark.integration
async def test_bulk_execute_audit_contains_technology_name(client, editor_user, admin_user, seed_address, seed_tech):
    _, editor_raw = editor_user
    _, admin_raw = admin_user
    _, tech = seed_tech

    # Preview
    prev = await client.post(
        "/api/v1/admin/bulk/preview",
        json={
            "filter": {"rc_codes": [seed_address]},
            "operation": {"type": "add_offering", "technology_id": str(tech.id),
                          "status": "available", "max_download_mbps": 100, "max_upload_mbps": 50},
        },
        headers={"X-API-Key": admin_raw},
    )
    assert prev.status_code == 201, prev.text
    token = prev.json()["preview_token"]

    # Execute
    await client.post(
        "/api/v1/admin/bulk/execute",
        json={"preview_token": token},
        headers={"X-API-Key": admin_raw},
    )

    resp = await client.get(
        "/api/v1/admin/audit-log",
        params={"entity_type": "bulk_operation"},
        headers={"X-API-Key": admin_raw},
    )
    entry = next(e for e in resp.json()["items"] if e["action"] == "execute")
    assert entry["diff"]["technology_name"] == "AuditVariant"
    assert entry["diff"]["affected_count"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/api/test_audit.py::test_bulk_execute_audit_contains_technology_name -v
```

Expected: `KeyError: 'technology_name'`

- [ ] **Step 3: Add import to bulk.py**

In `app/api/v1/admin/bulk.py`, add to existing imports:

```python
from app.db.audit_helpers import technology_display_name
```

- [ ] **Step 4: Enrich bulk_execute log and pass tech_name to _execute_* functions**

In `bulk_execute`, look up `technology_name` after `op` is parsed and before dispatch. Then thread it through each `_execute_*` call and the final `log_action`.

Current code block (lines ~129–176):

```python
    op_data: dict = preview["operation"]
    op = _parse_operation(op_data)
    op_type = op.type

    bulk_op = BulkOperations(...)
    db.add(bulk_op)
    await db.flush()

    if isinstance(op, AddOfferingOperation):
        modified = await _execute_add_offering(db, bulk_op.id, current_user.id, op, rc_codes)
        bulk_op.rollback_data = {...}
    elif isinstance(op, ChangeOfferingOperation):
        modified, old_values = await _execute_change_offering(db, bulk_op.id, current_user.id, op, rc_codes)
        bulk_op.rollback_data = {...}
    else:
        assert isinstance(op, RemoveOfferingOperation)
        modified, deleted_data = await _execute_remove_offering(db, bulk_op.id, current_user.id, op, rc_codes)
        bulk_op.rollback_data = {...}

    bulk_op.affected_count = len(modified)

    await log_action(
        db,
        current_user.id,
        "bulk_operation",
        str(bulk_op.id),
        "execute",
        {"type": op_type, "affected_count": len(modified)},
    )
```

Replace with (add `tech_name` lookup and thread it through):

```python
    op_data: dict = preview["operation"]
    op = _parse_operation(op_data)
    op_type = op.type

    tech_name = await technology_display_name(db, op.technology_id)

    bulk_op = BulkOperations(
        user_id=current_user.id,
        operation_type=op_type,
        filter_criteria=preview.get("filter", {}),
        affected_count=len(rc_codes),
        rollback_data=None,
    )
    db.add(bulk_op)
    await db.flush()

    if isinstance(op, AddOfferingOperation):
        modified = await _execute_add_offering(db, bulk_op.id, current_user.id, op, rc_codes, tech_name)
        bulk_op.rollback_data = {
            "type": "add_offering",
            "technology_id": str(op.technology_id),
            "created_codes": modified,
        }
    elif isinstance(op, ChangeOfferingOperation):
        modified, old_values = await _execute_change_offering(db, bulk_op.id, current_user.id, op, rc_codes, tech_name)
        bulk_op.rollback_data = {
            "type": "change_offering",
            "technology_id": str(op.technology_id),
            "old_values": old_values,
        }
    else:
        assert isinstance(op, RemoveOfferingOperation)
        modified, deleted_data = await _execute_remove_offering(db, bulk_op.id, current_user.id, op, rc_codes, tech_name)
        bulk_op.rollback_data = {
            "type": "remove_offering",
            "technology_id": str(op.technology_id),
            "deleted_offerings": deleted_data,
        }

    bulk_op.affected_count = len(modified)

    await log_action(
        db,
        current_user.id,
        "bulk_operation",
        str(bulk_op.id),
        "execute",
        {"type": op_type, "affected_count": len(modified), "technology_name": tech_name},
    )
```

- [ ] **Step 5: Enrich bulk_rollback log**

In `bulk_rollback`, `tech_id` is extracted at line ~207 as `tech_id = rd.get("technology_id")`. Add the name lookup immediately after that line (before the `if rd_type == ...` branches), then use it in the log call.

Find these lines (around line 207):
```python
    tech_id = rd.get("technology_id")
    affected = 0
```

Replace with:
```python
    tech_id = rd.get("technology_id")
    _rb_tech_uuid = uuid.UUID(tech_id) if tech_id else None
    rb_tech_name = await technology_display_name(db, _rb_tech_uuid) if _rb_tech_uuid else None
    affected = 0
```

Then find the rollback log call (around line 267):
```python
    await log_action(
        db,
        current_user.id,
        "bulk_operation",
        str(bulk_op_id),
        "rollback",
        {"rolled_back_count": affected, "type": rd_type},
    )
```

Replace with:
```python
    await log_action(
        db,
        current_user.id,
        "bulk_operation",
        str(bulk_op_id),
        "rollback",
        {"rolled_back_count": affected, "type": rd_type, "technology_name": rb_tech_name},
    )
```

- [ ] **Step 6: Add technology_name parameter to _execute_add_offering**

Update signature (line ~456) and the batch diff:

Change signature from:
```python
async def _execute_add_offering(
    db: AsyncSession,
    bulk_op_id: uuid.UUID,
    user_id: uuid.UUID,
    op: AddOfferingOperation,
    rc_codes: list[int],
) -> list[int]:
```

To:
```python
async def _execute_add_offering(
    db: AsyncSession,
    bulk_op_id: uuid.UUID,
    user_id: uuid.UUID,
    op: AddOfferingOperation,
    rc_codes: list[int],
    technology_name: str | None = None,
) -> list[int]:
```

Change diff_json (line ~504):
```python
        diff_json = json.dumps({"bulk_operation_id": str(bulk_op_id), "status": op.status})
```

To:
```python
        diff_json = json.dumps({"bulk_operation_id": str(bulk_op_id), "status": op.status, "technology_name": technology_name})
```

- [ ] **Step 7: Add technology_name parameter to _execute_change_offering**

Change signature from:
```python
async def _execute_change_offering(
    db: AsyncSession,
    bulk_op_id: uuid.UUID,
    user_id: uuid.UUID,
    op: ChangeOfferingOperation,
    rc_codes: list[int],
) -> tuple[list[int], list[dict]]:
```

To:
```python
async def _execute_change_offering(
    db: AsyncSession,
    bulk_op_id: uuid.UUID,
    user_id: uuid.UUID,
    op: ChangeOfferingOperation,
    rc_codes: list[int],
    technology_name: str | None = None,
) -> tuple[list[int], list[dict]]:
```

Change diff_json (line ~609):
```python
        diff_json = json.dumps({"bulk_operation_id": str(bulk_op_id), **changes})
```

To:
```python
        diff_json = json.dumps({"bulk_operation_id": str(bulk_op_id), "technology_name": technology_name, **changes})
```

- [ ] **Step 8: Add technology_name parameter to _execute_remove_offering**

Change signature from:
```python
async def _execute_remove_offering(
    db: AsyncSession,
    bulk_op_id: uuid.UUID,
    user_id: uuid.UUID,
    op: RemoveOfferingOperation,
    rc_codes: list[int],
) -> tuple[list[int], list[dict]]:
```

To:
```python
async def _execute_remove_offering(
    db: AsyncSession,
    bulk_op_id: uuid.UUID,
    user_id: uuid.UUID,
    op: RemoveOfferingOperation,
    rc_codes: list[int],
    technology_name: str | None = None,
) -> tuple[list[int], list[dict]]:
```

Change diff_json (line ~669):
```python
    diff_json = json.dumps({"bulk_operation_id": str(bulk_op_id), "technology_id": str(op.technology_id)})
```

To:
```python
    diff_json = json.dumps({"bulk_operation_id": str(bulk_op_id), "technology_id": str(op.technology_id), "technology_name": technology_name})
```

- [ ] **Step 9: Run all tests**

```bash
uv run pytest tests/api/test_audit.py tests/api/test_bulk.py -v
```

Expected: all PASSED

- [ ] **Step 10: Commit**

```bash
git add app/api/v1/admin/bulk.py tests/api/test_audit.py
git commit -m "feat: enrich bulk_operation audit diff with technology_name"
```

---

## Task 4: Plugin — PHP display field computation

**Files:**
- Modify: `~/workspace/robertas/lms-etanetas/lms/plugins/LMSEtaCoveragePlugin/modules/etacoverageaudit.php`

Current code (lines 57–62) converts diff to JSON for `<details>`. We keep that for fallback, and add new display fields per entity_type.

- [ ] **Step 1: Add display field computation after existing foreach loop**

The existing loop (lines 57–62):
```php
        foreach ($items as &$entry) {
            $entry['diff_json'] = (isset($entry['diff']) && $entry['diff'] !== null)
                ? json_encode($entry['diff'], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE)
                : null;
        }
        unset($entry);
```

Replace with:
```php
        foreach ($items as &$entry) {
            $entry['diff_json'] = (isset($entry['diff']) && $entry['diff'] !== null)
                ? json_encode($entry['diff'], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE)
                : null;

            $diff = $entry['diff'] ?? null;
            $et   = $entry['entity_type'] ?? '';

            if ($et === 'address_offering') {
                $addr_code = isset($diff['address_code']) ? intval($diff['address_code']) : 0;
                $entry['display_what'] = $diff['address_label']
                    ?? ($addr_code > 0 ? 'rc:' . $addr_code : substr($entry['entity_id'], 0, 13) . '…');
                $entry['display_what_link'] = $addr_code > 0
                    ? '?m=etacoverageaudit&rc_code=' . $addr_code
                    : null;
                $parts = array_filter([$diff['technology_name'] ?? null, $diff['status'] ?? null]);
                $entry['display_detail'] = $parts ? implode(' → ', $parts) : null;

            } elseif ($et === 'bulk_operation') {
                $count = isset($diff['affected_count']) ? intval($diff['affected_count']) : '?';
                $entry['display_what'] = trans('Bulk operation') . ' (' . $count . ')';
                $entry['display_what_link'] = null;
                $entry['display_detail'] = $diff['technology_name'] ?? ($diff['type'] ?? null);

            } else {
                $entry['display_what'] = $et . ': ' . substr($entry['entity_id'], 0, 13) . '…';
                $entry['display_what_link'] = null;
                $entry['display_detail'] = null;
            }
        }
        unset($entry);
```

- [ ] **Step 2: Assign new variables to Smarty**

After the existing `$SMARTY->assign('items', $items)` line, add:

```php
// display_what, display_what_link, display_detail are set on each $entry inside $items
// No extra assign needed — they're embedded in the $items array
```

(No extra assign needed — the fields are already in `$items`.)

- [ ] **Step 3: Commit**

```bash
cd ~/workspace/robertas/lms-etanetas
git add lms/plugins/LMSEtaCoveragePlugin/modules/etacoverageaudit.php
git commit -m "feat: compute display fields per entity_type in audit log"
```

---

## Task 5: Plugin — HTML template friendly 5-column view

**Files:**
- Modify: `~/workspace/robertas/lms-etanetas/lms/plugins/LMSEtaCoveragePlugin/templates/eta/etacoverageaudit.html`

Target view:
```
Data/laikas | Kto | Ko keista (Co zmieniono) | Veiksmas (Akcja) | Detalės (Szczegóły)
```

Entity ID hidden (tooltip on hover of display_what). Entity type hidden. Diff JSON kept as collapsible `<details>` inside Szczegóły for all types.

- [ ] **Step 1: Replace table header**

Current (lines 62–70):
```smarty
    <thead>
        <tr><td class="lms-ui-box-header" colspan="6">{trans("Audit log")}</td></tr>
        <tr>
            <td class="bold">{trans("Date/time")}</td>
            <td class="bold">{trans("User")}</td>
            <td class="bold">{trans("Entity type")}</td>
            <td class="bold">{trans("Entity ID")}</td>
            <td class="bold">{trans("Action")}</td>
            <td class="bold">{trans("Changes")}</td>
        </tr>
    </thead>
```

Replace with:
```smarty
    <thead>
        <tr><td class="lms-ui-box-header" colspan="5">{trans("Audit log")}</td></tr>
        <tr>
            <td class="bold">{trans("Date/time")}</td>
            <td class="bold">{trans("User")}</td>
            <td class="bold">{trans("Ko keista")}</td>
            <td class="bold">{trans("Action")}</td>
            <td class="bold">{trans("Detalės")}</td>
        </tr>
    </thead>
```

Also update the colgroup from 6 columns to 5:
```smarty
    <colgroup>
        <col style="width:13%;">
        <col style="width:12%;">
        <col style="width:30%;">
        <col style="width:10%;">
        <col style="width:35%;">
    </colgroup>
```

- [ ] **Step 2: Replace table rows**

Current rows (lines 73–89):
```smarty
    {foreach $items as $entry}
        <tr class="highlight">
            <td style="white-space:nowrap;">{$entry.at|date_format:'%Y-%m-%d %H:%M'|escape}</td>
            <td>{if $entry.username}{$entry.username|escape}{else}—{/if}</td>
            <td>{$entry.entity_type|escape}</td>
            <td><code style="font-size:11px;">{$entry.entity_id|escape}</code></td>
            <td>{$entry.action|escape}</td>
            <td>
                {if $entry.diff_json !== null}
                <details>
                    <summary style="cursor:pointer;font-size:11px;">{trans("Show")}</summary>
                    <pre style="font-size:10px;max-height:120px;overflow:auto;margin:4px 0;white-space:pre-wrap;">{$entry.diff_json|escape}</pre>
                </details>
                {else}—{/if}
            </td>
        </tr>
    {/foreach}
```

Replace with:
```smarty
    {foreach $items as $entry}
        <tr class="highlight">
            <td style="white-space:nowrap;">{$entry.at|date_format:'%Y-%m-%d %H:%M'|escape}</td>
            <td>{if $entry.username}{$entry.username|escape}{else}—{/if}</td>
            <td>
                {if $entry.display_what_link}
                    <a href="{$entry.display_what_link|escape}" title="{$entry.entity_type|escape}: {$entry.entity_id|escape}">{$entry.display_what|escape}</a>
                {else}
                    <span title="{$entry.entity_type|escape}: {$entry.entity_id|escape}">{$entry.display_what|escape}</span>
                {/if}
            </td>
            <td>{$entry.action|escape}</td>
            <td>
                {if $entry.display_detail}{$entry.display_detail|escape}{/if}
                {if $entry.diff_json !== null}
                <details style="margin-top:{if $entry.display_detail}4px{else}0{/if};">
                    <summary style="cursor:pointer;font-size:11px;color:#888;">{trans("Show raw")}</summary>
                    <pre style="font-size:10px;max-height:120px;overflow:auto;margin:4px 0;white-space:pre-wrap;">{$entry.diff_json|escape}</pre>
                </details>
                {/if}
                {if !$entry.display_detail && $entry.diff_json === null}—{/if}
            </td>
        </tr>
    {/foreach}
```

- [ ] **Step 3: Run and verify manually**

The project doesn't have automated tests for the PHP template. Open the LMS audit log in a browser and verify:
- For `address_offering` entries created after the backend change: "Ko keista" shows address label with link, "Detalės" shows "Ethernet (FTTB) → available"
- For `address_offering` entries created before the backend change (no address_label in diff): "Ko keista" shows "rc:156183656" as fallback
- For `bulk_operation` entries: "Ko keista" shows "Bulk operation (4)", "Detalės" shows technology name
- For other entity types (technology, user): shows truncated UUID with entity_type as tooltip
- Clicking address label link navigates to that address's history

- [ ] **Step 4: Commit**

```bash
cd ~/workspace/robertas/lms-etanetas
git add lms/plugins/LMSEtaCoveragePlugin/templates/eta/etacoverageaudit.html
git commit -m "feat: 5-column friendly audit log view with human-readable labels"
```

---

## Verification

After all tasks complete, run the full test suite:

```bash
cd ~/workspace/robertas/etanetas-coverage
uv run pytest -v
```

Expected: all existing tests pass + new tests pass.

Smoke test the API manually:
```bash
# Create an offering and check audit log
curl -H "X-API-Key: <key>" http://localhost:8000/api/v1/admin/audit-log?entity_type=address_offering | jq '.items[0].diff'
# Should contain: technology_name, address_label, address_code, technology_id, status
```
