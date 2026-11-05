# EVAL — idea-capture-01

How to check whether `idea-capture` works. Run the bundled script (`skills/idea-capture/scripts/capture.py`, Python, standard library only) against a throwaway store in `/tmp/orcinus-demo-ideas/ideas/`. No criterion may be skipped.

## Case 1 — capture three ideas, list them

**Input:** capture three ideas — one in English ("A weekly budget warning for food delivery, at 80% of the budget"), one in Persian ("ایده: یادآوری خرید هفتگی بر اساس بودجه"), one with quotes and symbols ("Sync the budget across devices — with 'quotes' & symbols!") — then `list`.

**Pass criteria:**

1. Three files exist in the store, one per idea, each with status `raw`.
2. `list` shows all three, with their ids, status `raw`, and dates.
3. The raw text in each file is byte-identical to what was captured (checked by hash).
4. Verdict is PASS.

**Fail criteria:**

- Fewer than three files, or any file missing its raw text.
- `list` does not show an idea.

## Case 2 — search, promote, drop

**Input:** `search` for `budget` and for `خرید`; `promote` the first idea to `calibrated` with a note; `drop` the third idea with a reason; `list` again.

**Pass criteria:**

1. `search budget` returns exactly the two English ideas; `search خرید` returns exactly the Persian idea.
2. The first idea's status is `calibrated`, with the note in its History.
3. The third idea's status is `dropped`, with the reason in its History — and the file still exists, with its raw text intact. Dropping never deletes.
4. Verdict is PASS.

**Fail criteria:**

- Search returns a wrong idea or misses one.
- A dropped idea's file is gone, or its raw text changed.

## Case 3 — durability and no loss

**Input:** in a fresh process (a new session reading the same store), `list` again and re-hash every raw text; then the four failure cases: capture an empty idea, promote an unknown id, promote a dropped idea back to `calibrated`, drop an idea without a reason.

**Pass criteria:**

1. The fresh `list` shows all three ideas with the same ids and the same statuses as before.
2. Every raw text is byte-identical to capture time (hashes match: `3864eecc0137`, `05a5085701db`, `0602e1c0bef2`).
3. All four failure cases exit 1 with a clear error, and no file is created or changed by them.
4. Verdict is PASS.

**Fail criteria:**

- An idea is missing or its status changed without a recorded move.
- A raw text differs from capture time.
- A failure case exits 0, or creates a file.

## Last run

- 2026-11-06: PASS. Case 1: 4/4. Case 2: 4/4. Case 3: 4/4. Real run, not simulated, with the bundled script (`skills/idea-capture/scripts/capture.py`, Python, standard library only) against a throwaway store in `/tmp/orcinus-demo-ideas/ideas/`. Case 1 (capture + list): three ideas captured — English, Persian, and one with quotes and symbols — three files, all status `raw`, all listed with ids and dates, every raw text byte-identical to what was captured (hashes `3864eecc0137`, `05a5085701db`, `0602e1c0bef2`). Case 2 (search + promote + drop): `search budget` returned exactly the two English ideas, `search خرید` exactly the Persian idea; the first idea moved to `calibrated` with its note in History; the third moved to `dropped` with its reason in History, and the file still exists with its raw text intact. Case 3 (durability + no loss): a fresh process listed all three ideas with the same ids and statuses, and every raw text was byte-identical to capture time (hashes match); all four failure cases exited 1 with a clear error — empty capture, unknown id, dropped → calibrated, drop without a reason — and none created or changed a file. The store lives in /tmp for the eval and is rebuildable; in real use it lives in the project and is committed with it.
