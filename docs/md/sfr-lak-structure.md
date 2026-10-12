# SFR vs LAK: same relation, different shape

Both SFR and LAK are "advanced" MODFLOW 6 packages: each defines a set of
features (reaches / lakes) in a `packagedata` block, then references those
features by number from several other blocks. Structurally this is the same
one-(feature)-to-many-(rows) relation in both packages, but the two DFNs
express it differently, and LAK's expression of it is inconsistent internally.
This note documents the difference and suggests standardizing on LAK's
per-row form — a change that's worth doing but not free.

## SFR: one row per reach *or* per connection

SFR's `connectiondata` block has exactly one row per **reach**, and each
row's `ic` field is an inline array holding *all* of that reach's connected
reach numbers:

```
connectiondata
  ifno   ic
  1      -2
  2       1 -3
  3       2
```

Reach 2 connects to two reaches, reach 1 and 3 connect to one each — so `ic`
is jagged: its length varies per row, driven by another field (`ncon`) in
that reach's `packagedata` row. The v1 DFN expresses this with a shape
expression on `ic`: `shape (ncon(ifno))`, i.e. "look up `ncon` in the row of
`packagedata` selected by this row's `ifno`". This idiom is how the current
v2 migration (`_resolve_relations` in
`modflow_devtools/dfns/migrate_to_v2_0_0_dev2.py`) originally learned that
`packagedata.ifno` is a primary key at all — it's a side effect of parsing
the shape expression, not a deliberate relational annotation.

## LAK: one row per connection

LAK's `connectiondata` normalizes the same information into one row **per
connection** instead of per lake:

```
connectiondata
  ifno   iconn  cellid ...
  1      1      (1,1,1) ...
  2      1      (1,1,2) ...
  2      2      (1,1,3) ...
```

There's no inline jagged array and nothing to size with a shape expression —
`ifno` is just an ordinary integer column that happens to repeat the same
value across a lake's connections. This is why the shape-idiom detector
never found a pk/fk relation in LAK: there's no shape expression for it to
find. It's also arguably the cleaner of the two designs — row-per-connection
avoids variable-length fields and reads more like a normal relational table.

MAW and UZF follow LAK's row-per-connection pattern too (`ifno` repeated
verbatim across `packagedata`, `connectiondata`/`perioddata`), and the GWT/GWE
transport counterparts of SFR/LAK/MAW/UZF (`sft`/`lkt`/`mwt`/`uzt`,
`sfe`/`lke`/`mwe`/`uze`) do the same with their own key names (`rno`,
`lakeno`, `mawno`, `uzfno`). The `_resolve_relations` generalization added
alongside this note detects all of these by matching an integer field name
that recurs, unchanged, between `packagedata` and any other block — no shape
expression required.

## Where LAK's own naming is inconsistent

Two LAK relations don't fit the "same name repeats" pattern the general
mechanism relies on, for different reasons, and both are now patched
explicitly in `_fix_lak_relations` (`migrate_to_v2_0_0_dev2.py`):

- **`outlets.lakein` / `outlets.lakeout`** reference `packagedata.ifno`
  unambiguously, but under different names (each row needs two lake
  references, so they can't both be called `ifno`) — a naming gap, not an
  ambiguity. `_fix_lak_relations` aliases both directly to
  `fk: packagedata.ifno`, since that's correct for every row.
- **`period.perioddata.number`** was worse than a naming gap: it's a single
  column that means *either* a lake number (`packagedata.ifno`) or an outlet
  number (`outlets.outletno`), depending on which keyword follows it in
  `laksetting` (`STAGE`/`RAINFALL`/... vs. `RATE`/`INVERT`/...). A single
  `fk` string can't correctly describe a column whose target type is
  conditional on a sibling value — annotating it either way would be
  actively wrong for the other half of the rows, not just imprecise. This
  needs restructuring, not just an alias; see below.

### Resolving `number`

`_fix_lak_relations` splits the shared `number` field into an arm-local
copy, pushed inside each `laksetting` union arm with a name and `fk`
appropriate to that arm's category: `lakeno` / `fk: packagedata.ifno` for
the 8 lake-setting arms, `outletno` / `fk: outlets.outletno` for the 5
outlet-setting arms. That leaves `laksetting` the only field of the period
list's element, so the element becomes the union itself, as PRP's
`releasesetting` is. (`outlets.outletno` is also newly marked `pk`, since
nothing else previously pointed at it — needed for the new `outletno` fk to
resolve.)

This is a **schema-only** change, entirely inside `modflow-devtools`'s own
v1→v2 migration — it does not touch the upstream MF6 `.dfn` files, MF6's
Fortran reader, or the on-disk `.lak` file format. The token sequence MF6
actually parses (`<number> <keyword> <value>`) is unchanged; we've only
changed where `number` sits in *our* representation of it, so each copy can
carry a correct, non-conditional `fk`. This mirrors existing precedent in
the same file — `_collapse_sto_keywords` and `_wrap_oc_period_records`
already restructure v1 fields into a different v2 shape for other packages
without touching upstream DFNs.

## Recommendation

Both relations now have correct `pk`/`fk` annotations in the v2 schema, so
neither blocks anything in this repo. `outlets.lakein`/`outlets.lakeout`
could still be renamed upstream for clarity (e.g. `lakein_no`/`lakeout_no`,
matching `ifno` more closely) — that would only affect generated docs/APIs
(flopy parameter names, Fortran variable names in the LAK module), since the
on-disk file format doesn't care what a positional column is named. MF6 has
precedent for this kind of rename (SFR's `rno` → `ifno` between the version
underlying this repo's older fixtures and 6.7.0). Low risk, purely cosmetic,
worth proposing upstream on its own if desired — not something this repo
needs.

By contrast, changing the *input format itself* — e.g. requiring a
`LAKE`/`OUTLET` discriminator keyword before `number` so the ambiguity is
resolved in the file rather than only in our schema — would be a real
breaking change: every existing LAK input file that sets an outlet
property (`RATE`, `INVERT`, `WIDTH`, `ROUGH`, `SLOPE`) would need to change.
That's not needed to fix anything in this repo (the schema-only split above
already gives `number` a correct `pk`/`fk` representation), so it should
only be pursued upstream, if at all, through MF6's normal deprecation path —
not as a consequence of this document.

`fk_ref` already exists in the v2 schema for harder cross-component cases
(e.g. `gwf-mvr` referencing an arbitrary package's `packagedata` pk at
runtime; see "Primary/foreign keys" in `docs/md/dfnspec.md`), in case some
future relation needs real runtime resolution instead of a static `fk`.

## Aside: a pre-existing, unrelated bug noticed along the way (now fixed)

While tracing how LAK's `laksetting` union arms get built, one arm came out
wrong independent of anything above: `period.perioddata.laksetting.stage`
resolved to `type: keyword, description: "keyword to specify that record
corresponds to stage."` — that's actually LAK's *options* block
`stage_filerecord.stage` field (a bare keyword), not `period`'s own `stage`
field (the real, `double precision`/time-series-capable lake stage value).

The cause: `_subfield_map`/`_row_field` in `migrate_to_v2_0_0_dev2.py`
resolved a keystring/record's named sub-fields by scanning *all* fields in
the component (`fields.values(multi=True)`) for the first name match with
`in_record: true`, without also requiring the match to come from the same
block. Since v1 DFNs reuse field names across blocks routinely (`stage`
appears in both `options` and `period` here), whichever block's field was
declared first in the raw DFN won, regardless of which block actually
contained the arm being resolved. This predated the changes in this
document — it was already present in the committed `v2.0.0.dev2`/`dev3`
snapshots — and is unrelated to pk/fk. The same bug affected every other
package with a same-named field in two blocks, e.g. GWE/GWT's
`temperature`/`concentration` arms resolving to their `options` filerecord
keyword instead of their own `period` value.

**Fix:** all three lookups now additionally require `fi["block"] ==
f["block"]`, i.e. the candidate sub-field must live in the same block as the
record/union/keystring being resolved (`f`, the enclosing field, is already
in scope via closure). Sub-fields of a composite are always declared in that
composite's own block, so this scoping is always correct, never just a
best-effort heuristic. All `2.0.0.dev2`/`dev3` snapshots were regenerated
accordingly; the only substantive diffs were the previously-misresolved
arms (LAK's `stage`, and the analogous `temperature`/`concentration` arms in
the GWE/GWT transport packages) — everything else in the corpus was
unaffected, so the blast radius in practice was much narrower than the
worst case.
