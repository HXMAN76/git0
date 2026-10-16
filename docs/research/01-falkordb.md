# FalkorDB research for Membranch (researched 2026-10-16)

> **Correction (2026-10-16, verified on the running container):** `falkordb/falkordb:latest` is graph module **4.22.1** (same image ID as `v4.22.1`), not 6.0.x. We pin `v4.22.1`. Our measurements on that image are in `docs/ARCHITECTURE.md` §3.

Method: official docs (raw `.md` of https://docs.falkordb.com/llms.txt pages, fetched with curl because
`new.docs.falkordb.com` does not resolve), PyPI/GitHub/Docker Hub metadata, AND a live test bench:
`falkordblite 0.10.0` (embedded module = FalkorDB **4.18.3** C engine, Redis 8.6.2) + `falkordb` py client **1.8.0**.
Items marked **[LIVE]** were executed and passed on that bench. Items marked **VERIFY ON LIVE DB** were not
provable here (mostly: Docker `latest`/6.0.x Rust engine, Cloud free tier).

Doc base URL: `https://docs.falkordb.com` (append `.md` for raw markdown). Abbreviations: CS = /cypher/cypher-support,
FN = /cypher/functions, KL = /cypher/known-limitations, CC = /design/concurrency.

---------------------------------------------------------------------------------------------------

## HEADLINE FINDINGS (things that change the plan)

1. **`EXISTS { ... }` subqueries are NOT supported** (parse error [LIVE]; not documented; `exists((n)-[]->())` also errors:
   "Unable to resolve filtered alias"). Use pattern predicates `WHERE (n)-[:R]->()` / `WHERE NOT (n)-[:R]->()` [LIVE],
   or `OPTIONAL MATCH ... count()`, or `CALL {}`.
2. **List de-dup exists natively: `list.dedup(list)`** (order-preserving) [LIVE]. No APOC/FLEX needed. FLEX (`flex.*`) is a
   separate UDF library, NOT preinstalled (`flex.collections.intersection` => "Unknown function") [LIVE].
3. **The CAS pattern is correct and race-safe [LIVE]**: 20 concurrent threads all CAS-ing from the same expected HEAD => exactly 1 winner,
   19 get 0 rows, exactly one HEAD edge remains. 8 threads x 15 retry-loop commits => perfect linear chain. A failed query
   (e.g. unique-constraint violation mid-query) rolls back ALL of its writes [LIVE]. One-query "CAS + N facts + removals" works (section R-b).
4. **Do NOT put `UNWIND $facts` between the CAS match and `DELETE r`/`CREATE HEAD`** - UNWIND multiplies rows and the DELETE/CREATE-HEAD would
   run per row. Use `FOREACH (f IN $facts | CREATE ...)` (does not change row count) and `CALL { WITH n UNWIND $removed AS rid MATCH ... CREATE ... }`
   (non-returning subquery keeps row count) [LIVE].
5. **Variable-length paths enumerate PATHS, not nodes -> exponential on merge-diamonds** [LIVE]: a ladder of 22 diamonds
   (67 distinct commits) = 16.7M paths, 2.4 s for `MATCH (h)-[:PARENT*0..200]->(c) RETURN count(c)`. Because Membranch has merge commits (2 parents),
   do NOT use `[:PARENT*0..200]` for ancestor sets. Use `CALL algo.bfs(h, 100000, 'PARENT') YIELD nodes` (reachability, 0.4 ms on the same ladder)
   or `WITH DISTINCT c`, or a materialised `ancestors` list.
6. **Materialised `commit.ancestors` list is O(N^2) memory** [LIVE]: 1000-commit linear history = 21 MB, 2000 = 82 MB, 4000 = 324 MB
   (string ids). Cloud free tier is 100 MB TOTAL. Fine for a demo (<~500 commits ~ 5 MB) but a trap for long histories; BFS variant costs
   ~140 ms for checkout at depth 3000 vs 143 ms with the list (equal), merge-base 200 ms vs 8 ms. Recommendation: use BFS by default
   (no extra memory), keep `ancestors` as an optional cache only if merge-base latency matters.
7. **Properties can only be primitives or arrays of primitives** [LIVE]: maps, arrays-of-maps, and arrays containing `null` are rejected
   ("Property values can only be of primitive types or arrays of primitive types"). Structured fact payloads must be stored as JSON strings
   (or flattened). `$facts` as a list of maps is fine as a *parameter* (only storing the map as a property fails).
8. **Docker `latest` now = FalkorDB 6.0.x, a NEW Rust engine** (v6.0.0 released 2026-09-29; `latest` tag moved; `latest-alpine` still C 4.20.7).
   FalkorDBLite embeds the old C 4.18.3. Dev/CI parity risk. Pin `falkordb/falkordb:v4.22.1` (C engine, same lineage as FalkorDBLite) unless you
   deliberately test on 6.0.x. All behaviours below were verified on 4.18.3 only. **VERIFY ON LIVE DB** for 6.0.x.
9. **Algorithms cannot be scoped to a branch/commit-visible subgraph** - only `nodeLabels` / `relationshipTypes` filters. Branch-scoped
   betweenness needs: compute in app code from the checkout rows (networkx), or GRAPH.COPY -> delete invisible facts -> run -> GRAPH.DELETE.
10. **Runaway queries can eat all memory**: a read-only `UNWIND range(1,100000000)` pushed the server to ~3 GB [LIVE]. On a 100 MB Cloud free
    instance set `QUERY_MEM_CAPACITY`, `TIMEOUT_MAX/TIMEOUT_DEFAULT` (if configurable there - VERIFY).

---------------------------------------------------------------------------------------------------

## 1. Cypher construct support (VERDICT table)

Sources: CS https://docs.falkordb.com/cypher/cypher-support.md , FN https://docs.falkordb.com/cypher/functions.md ,
https://docs.falkordb.com/cypher/call.md , /cypher/foreach.md , /cypher/unwind.md , /cypher/merge.md , /cypher/where.md , KL.

| Construct | VERDICT | Evidence / note |
|---|---|---|
| list concat `a + b` | supported | [LIVE] `[1,2]+[3]` => `[1,2,3]`; `[$new] + h.ancestors` works in CREATE props |
| `x IN list` | supported | [LIVE]; `IN` listed in /cypher/where.md. Index used only for literal/param lists (see 4) |
| `none(x IN l WHERE ..)`, `any`, `all`, `single` | supported | FN "Existential comprehension functions" [LIVE] |
| `collect(DISTINCT x)` | supported | [LIVE] `collect(DISTINCT x)` => `[1,2]` |
| `OPTIONAL MATCH` | supported | CS; [LIVE] |
| var-length `[:PARENT*0..200]` | supported, **path-enumerating** | [LIVE] `*0..200` on 3000-chain = 0.2 ms (chain), but exponential on DAG diamonds (headline #5). Zero-length `*0..` works |
| `EXISTS { }` subquery | **NOT supported** | [LIVE] parse error. Not in CS/FN. `exists(n.prop)` property form only (FN) |
| pattern predicate `WHERE (a)-[:R]->(b)` / `NOT (...)` | supported | /cypher/where.md [LIVE] - the replacement for EXISTS{} |
| `CALL { }` subquery | supported | /cypher/call.md [LIVE]. Import vars ONLY via opening `WITH n`/`WITH *`. Returning or non-returning (side-effect) |
| `UNWIND` + `CREATE` | supported | [LIVE] `UNWIND $facts AS f CREATE (...)` incl. list-of-maps param |
| `UNWIND` + `MERGE` | supported | [LIVE] `UNWIND $facts AS f MERGE (n:F {id:f.id}) SET n.t=f.t` |
| `FOREACH` | supported | /cypher/foreach.md [LIVE]; only updating clauses (CREATE/MERGE/SET/REMOVE/DELETE/FOREACH) inside; MATCH not allowed inside |
| `DELETE r` then `CREATE` in same query | supported | [LIVE] `MATCH..-[r:HEAD]->.. CREATE (n).. DELETE r CREATE (b)-[:HEAD]->(n) RETURN n.id`. CC: filters after a `WITH` see state after earlier DELETEs |
| `timestamp()` | supported | FN scalar (ms since epoch) [LIVE]. NB: server wall-clock, not monotonic - do not use for ordering/ids; use `depth` |
| `coalesce(a, b, ...)` | supported | FN [LIVE] |
| map projection `n{.id, k: n.v+1}` | supported | [LIVE] (FN also mentions `toJSON(node{.prop})`) |
| parameters `$x` | supported | [LIVE]. Python client inlines params as a `CYPHER \`k\`=<literal>` prefix; special chars/quotes/newlines/emoji/injection strings round-trip exactly [LIVE] |
| list-of-maps param `$facts` | supported | [LIVE] 5000 maps (1.2 MB) in 27 ms. Access `f.id`, `f.tags` |
| `reduce(acc=[], x IN l \| ...)` | supported | FN [LIVE] |
| list comprehension `[x IN l WHERE .. \| ..]` | supported | FN [LIVE] |
| pattern comprehension `[(n)-[:R]->(m) \| m.id]` | supported with bugs | FN. **Nested inside another list comprehension it returned WRONG results** (`[n IN nodes(p) \| head([(n)-[:ADDED_IN]->(c) \| c.id])]` returned the same commit for every n) [LIVE]. Also fails inside `none(... IN [pattern comp] ...)` ("Unable to resolve filtered alias"). Avoid; use OPTIONAL MATCH. No aggregates inside (KL #4) |
| `CASE WHEN` | supported | FN [LIVE] |
| `UNION`, `WITH DISTINCT`, `ORDER BY/SKIP/LIMIT` | supported | CS |
| `shortestPath()`, `allShortestPaths()` | supported (extension) | FN. Endpoints must already be bound; `allShortestPaths` needs `WITH a,b MATCH p=allShortestPaths(...)` (direct second MATCH => "Source and destination must already be resolved") [LIVE] |
| regex operator `=~`, label expressions `(n:A\|B)`, schema-retrieval | not supported | CS |

Quirks (KL https://docs.falkordb.com/cypher/known-limitations.md):
- Relationship not referenced elsewhere in a MATCH pattern => only existence checked (two parallel same-type edges counted once). Reference alias
  (e.g. `WHERE ID(e) >= 0`) when multiplicity matters. [LIVE] confirmed parallel edges collapse.
- `LIMIT` does not stop eager writes (`UNWIND [1,2,3] AS v CREATE (...) RETURN a LIMIT 1` creates 3).
- Indexes don't help `<>`.
- MERGE on a multi-element path creates duplicates if the whole path doesn't match; MERGE each node, then the edge (/cypher/merge.md).
- Null list elements can't be stored; property set to null = absent.

## 2. List de-duplicate

VERDICT: **supported natively** - `list.dedup(list)` (FalkorDB extension). Source FN list-functions table:
https://docs.falkordb.com/cypher/functions.md ("order is preserved, duplicates removed from the end; null in => null out").
[LIVE] `RETURN list.dedup([1,2,1,3,2])` => `[1,2,3]`; `list.dedup([$new] + h.ancestors + p2.ancestors)` works inside CREATE props.
Related builtins: `list.sort(list[, ascending])`, `list.insert`, `list.remove`, `reduce`, `range`, `head/last/tail/size`.
Fallback idiom (also [LIVE]): `reduce(acc = [], x IN l | CASE WHEN x IN acc THEN acc ELSE acc + [x] END)` (O(n^2)).
`collect(DISTINCT x)` for aggregation. FLEX (`flex.collections.union/intersection/frequencies/zip/shuffle`, https://docs.falkordb.com/udfs/flex/collections/index.md)
requires `GRAPH.UDF LOAD` of the flex library - NOT present by default; not needed.
Set intersection idiom (no library): `[x IN a WHERE x IN b]` [LIVE: 3000x3000 in ~8 ms].

## 3. Concurrency / atomicity / CAS

Source CC: https://docs.falkordb.com/design/concurrency.md
- Writes: serialised per graph, FIFO ("Only one write query executes at a time on a given graph"). Reads: parallel on a thread pool
  (`THREAD_COUNT`, default = logical cores), each sees a consistent snapshot as of its start (snapshot-isolation-like). Readers during a write see pre-write state.
- Each modifying query is fully atomic, including compound `WITH`/`UNION` queries and new labels/types; failure (e.g. constraint violation) applies nothing [LIVE].
- No native multi-query transactions. Redis `MULTI/EXEC` works (VERDICT: supported, workaround for multi-statement) [LIVE: 2 CREATEs in one
  `pipeline(transaction=True)`], but it blocks ALL graphs (and the redis-py pipeline returns raw un-parsed replies, not QueryResult). No rollback of an
  earlier statement if a later one errors inside EXEC (page doesn't say; VERIFY). Prefer single-query atomicity.
- Write queries are the bottleneck (batch). [LIVE] 8 threads x 15 CAS retry-loops (383 conflicts) finished in 0.19 s total.

CAS verdict: **the proposed pattern is correct** [LIVE]:
```cypher
MATCH (b:Branch {name:$b})-[r:HEAD]->(h:Commit {id:$expected})
CREATE (n:Commit {id:$new, ts:timestamp(), msg:$msg, depth:h.depth+1})-[:PARENT]->(h)
DELETE r
CREATE (b)-[:HEAD]->(n)
RETURN n.id
```
Zero rows <=> branch missing OR HEAD != $expected (stale). Because MATCH produced 0 rows nothing after it runs (nothing written; stats empty) [LIVE].
Python: `rs = g.query(CAS, params).result_set; ok = bool(rs)`. Distinguish "branch missing" from "stale" with a follow-up `ro_query` only on failure.
Safety net (recommended): unique constraint on `Commit.id` (see 4) so even a bug cannot create duplicate commits. Use a client-generated commit id (uuid / content hash).

## 4. Indexes & constraints

Sources: https://docs.falkordb.com/cypher/indexing/range-index.md , https://docs.falkordb.com/commands/graph.constraint-create.md
- Range index (node): `CREATE INDEX FOR (c:Commit) ON (c.id)` [LIVE]; old syntax `CREATE INDEX ON :Commit(id)` also OK; edge:
  `CREATE INDEX FOR ()-[f:R]-() ON (f.p)`. Multi-prop index: `ON (p.a, p.b)`. List: `CALL db.indexes()`. Python helper `g.create_node_range_index('Commit','id')`.
  NOTE: unlike Neo4j, create indexes BEFORE bulk loads or expect async build; schema-per-graph so do it for every tenant graph (see 5).
- Unique constraint: needs the exact-match (range) index first, then (it is a Redis command, not Cypher):
  `GRAPH.CONSTRAINT CREATE <graph> UNIQUE NODE Commit PROPERTIES 1 id` => `PENDING` (async; status via `CALL db.constraints()` -> `OPERATIONAL`) [LIVE].
  Python: `db.connection.execute_command("GRAPH.CONSTRAINT","CREATE",graph,"UNIQUE","NODE","Commit","PROPERTIES","1","id")`
  or `g.create_node_unique_constraint("Commit","id")` (exists in client 1.8.0; helper not exercised here - VERIFY signature). Also `MANDATORY` constraints.
  Violation => query error `unique constraint violation on node of type Commit` and whole query rolled back [LIVE]. Not enforced for null or array-valued props. Index backing a constraint can't be dropped.
- Does `IN` use an index? [LIVE via GRAPH.EXPLAIN]:
  - `WHERE c.id IN $ids` (param or literal list) => `Node By Index Scan` YES.
  - `UNWIND $ids AS i MATCH (c:Commit {id:i})` => Index Scan YES (best).
  - `WITH h.ancestors AS anc MATCH (a:Commit) WHERE a.id IN anc` (list bound in a previous WITH) => `Node By Label Scan + Filter` NO.
    => For checkout use `UNWIND anc AS cid MATCH (c:Commit {id:cid})...` not `WHERE a.id IN anc`.
  - `<>` never uses an index.

## 5. Multi-graph / tenants / COPY / Cloud free tier

- One graph per tenant: `db.select_graph(name)` (lazy; graph created on first write). `db.list_graphs()` = GRAPH.LIST (all graph keys in current Redis DB; also
  shows internal `telemetry{<graph>}` keys per docs example) https://docs.falkordb.com/commands/graph.list.md . `g.delete()` = `GRAPH.DELETE`
  (irreversible, takes write lock on that graph; `ASYNC_DELETE yes` by default) https://docs.falkordb.com/commands/graph.delete.md [LIVE].
  Indexes/constraints are per graph - run the schema bootstrap for each new tenant graph. Per-graph ACLs exist (Cloud "Graph Access Control").
- `GRAPH.COPY src dest` (python `g.copy('dest')`) https://docs.falkordb.com/commands/graph.copy.md : full clone incl. nodes, edges, properties, **indexes and
  constraints** (docs; index copy [LIVE]); consistent snapshot at start; source stays readable/writable during copy; **errors if dest exists** ("destination key already exists") [LIVE];
  temp folder `TEMP_FOLDER` used. Costs a full second copy of the data in RAM.
- Cloud free tier https://docs.falkordb.com/cloud/tiers/free.md : **100 MB RAM = max dataset 100 MB** (all graphs together), multi-graph/multi-tenancy YES,
  graph access control yes, **no TLS, no persistence, no backups**, no HA; AWS or GCP; **idle >1 day => stopped, deleted after 7 days**; community support.
  Whether `GRAPH.COPY` is allowed on the free tier: **not documented anywhere I could find => VERIFY ON LIVE DB** (copy also doubles memory use on a 100 MB box).
  Startup tier: $73/mo, 1 GB (0.75 GB dataset), TLS, backups.

## 6. Python client (`falkordb`)

Latest: **1.8.0 (2026-10-14)**, PyPI https://pypi.org/project/falkordb/ ; Python >=3.10 (3.10-3.14, PyPy); deps `redis>=8.0.0,<9`, `python-dateutil`.
Repo https://github.com/FalkorDB/falkordb-py
- Sync: `from falkordb import FalkorDB; db = FalkorDB(host=, port=, password=, ssl=, connection_pool=)`; `FalkorDB.from_url("redis://host:6379")`;
  `g = db.select_graph("tenant")`; `g.query(q, params, timeout_ms)`, `g.ro_query(q, params, timeout_ms)`, `g.explain(q, params)`, `g.profile(...)`,
  `g.copy(dest)`, `g.delete()`, `db.list_graphs()`, `db.config_get/config_set`, `g.list_constraints()`, `g.slowlog()`.
- Pool: `pool = redis.BlockingConnectionPool(host=, port=, max_connections=16, timeout=10, decode_responses=True); db = FalkorDB(connection_pool=pool)` [LIVE].
  The client already creates a pool internally (`max_connections=` kwarg); one `FalkorDB` object is thread-safe (20 threads each with own client in my test; fine either way).
- Async: `from falkordb.asyncio import FalkorDB`; `from redis.asyncio import BlockingConnectionPool` ; methods are `await g.query/ro_query(...)`, `await db.list_graphs()`, close with `await db.aclose()` / `await pool.aclose()` [LIVE].
- Params: plain `dict` passed as 2nd arg; client serialises into a `CYPHER` header in the query string (so the plan cache is keyed on query text, params don't bloat
  the cache; `CACHE_SIZE` default is only 25 - raise it). Supports str/int/float/bool/None/list/dict nesting [LIVE].
- Results: `res.result_set` (list of rows; scalars native, lists native, maps -> OrderedDict), `res.header` (`[[type, name], ...]`), `res.run_time_ms`, `res.cached_execution`,
  `res.nodes_created / nodes_deleted / relationships_created / relationships_deleted / properties_set / labels_added`.
  `Node`: `.id` (internal, NOT stable), `.labels`, `.properties` ; `Edge`: `.relation`, `.src_node`, `.dest_node` (ids), `.properties`, `.id`; `Path`: `.nodes()`, `.edges()` [LIVE].
  Return scalars/maps (`RETURN n{.id,.msg}`) instead of Nodes for speed. Never persist `id(n)`; use your own `id` property.
- Timeout: `timeout=` (ms) -> `GRAPH.QUERY ... timeout N`; server replies `Query timed out` [LIVE for read]. In legacy mode (TIMEOUT_DEFAULT/MAX unset) write queries DO NOT time out [LIVE: write with timeout=50 ran to completion].
  Set `TIMEOUT_MAX` + `TIMEOUT_DEFAULT` server-side (docs say these apply to writes too, VERIFY).
- `ro_query` with a write => `ResponseError: graph.RO_QUERY is to be executed only on read-only queries` [LIVE]. Use `ro_query` for checkout/diff/why (can run on replicas, parallel).
- Errors: `redis.exceptions.ResponseError` (message text from server, e.g. `unique constraint violation ...`).

Async example (verified [LIVE] against a real server; 10 concurrent CAS => exactly 1 winner):
```python
import asyncio
from falkordb.asyncio import FalkorDB
from redis.asyncio import BlockingConnectionPool

CAS = """MATCH (b:Branch {name:$b})-[r:HEAD]->(h:Commit {id:$e})
CREATE (n:Commit {id:$n, depth:h.depth+1})-[:PARENT]->(h) DELETE r CREATE (b)-[:HEAD]->(n) RETURN n.id"""

async def main():
    pool = BlockingConnectionPool(host="localhost", port=6379, max_connections=16, timeout=5, decode_responses=True)
    db = FalkorDB(connection_pool=pool)
    g = db.select_graph("tenant_acme")
    res = await asyncio.gather(*[g.query(CAS, {"b": "main", "e": "c0", "n": f"x{i}"}) for i in range(10)])
    print([r.result_set for r in res if r.result_set])      # exactly one non-empty
    rows = (await g.ro_query("MATCH (c:Commit) RETURN c.id", timeout=1000)).result_set
    await db.aclose()
asyncio.run(main())
```

## 7. FalkorDBLite (embedded) and CI

- PyPI `falkordblite` **0.10.0** (2026-05-02), `Requires-Python >=3.12`; wheels cp312/313/314 for manylinux_2_39 x86_64 + aarch64 and macOS (needs `brew install libomp`).
  Docs https://docs.falkordb.com/operations/falkordblite/falkordblite-py.md . **Import path is `redislite`, not `falkordblite`:**
  `from redislite.falkordb_client import FalkorDB; db = FalkorDB("/tmp/x.db"); g = db.select_graph("t")` (unix-socket embedded Redis 8.6.2 + FalkorDB module **4.18.3**; data persists in the file) [LIVE].
  Same API as `falkordb.FalkorDB` (query/ro_query/list_graphs/copy). It is a *older engine* than prod. All my "LIVE" results are from this.
- Trick that worked [LIVE]: the wheel ships `redislite/bin/redis-server` + `falkordb.so`; you can start a real TCP server from them
  (`redis-server --port 6391 --loadmodule .../redislite/bin/falkordb.so THREAD_COUNT 4`) and point `falkordb`/`falkordb.asyncio` clients at it. Useful for async + thread race tests without Docker.
- pytest fixture sketch: session-scoped FalkorDBLite on `tmp_path_factory`, new graph name per test (`uuid4().hex`), `g.delete()` in teardown.
- GitHub Actions service container (preferred when Docker is available; pin the tag, do NOT use `latest`):
```yaml
services:
  falkordb:
    image: falkordb/falkordb-server:v4.22.1   # C engine; server-only image (no browser)
    ports: ["6379:6379"]
    options: >-
      --health-cmd "redis-cli ping" --health-interval 5s --health-timeout 3s --health-retries 12
```
  Tags seen on Docker Hub 2026-10-15: `latest`/`6.0.2` (Rust engine), `v4.22.1`, `v4.22.1-alpine`, `edge` (main, Rust), `edge-c`, `latest-alpine` (C 4.20.7).

## 8. Algorithms

Sources https://docs.falkordb.com/algorithms/index.md , /betweenness-centrality.md , /sppath.md , /bfs.md
- Betweenness: `CALL algo.betweenness({nodeLabels:['Fact'], relationshipTypes:['DERIVED_FROM'], samplingSize: 32, samplingSeed: 42}) YIELD node, score`
  (all keys optional; default samplingSize 32 => approximate; set `samplingSeed` for reproducibility) [LIVE call shape]. Restriction = labels + rel types ONLY. No property/commit filter => cannot be limited to the facts visible on a branch (headline #9).
- Shortest paths: `CALL algo.SPpaths({sourceNode:a, targetNode:b, relTypes:['DERIVED_FROM'], weightProp:'w'?, costProp?, maxCost?, maxLen?, relDirection:'outgoing'|'incoming'|'both', pathCount: 1 (0 = all)}) YIELD path, pathWeight, pathCost`.
  [LIVE] works WITHOUT weightProp (unweighted) and with maxLen. `algo.SSpaths` = source to all. For plain hop counts, Cypher `shortestPath(...)` is simpler.
- `CALL algo.bfs(startNode, maxDepth, 'REL_TYPE'|null) YIELD nodes, edges` : reachability, excludes the start node, order is NOT reliably BFS order [LIVE] - treat as a set. maxDepth required (use 100000).
  Also: WCC, CDLP, PageRank, Harmonic, MaxFlow, MSF, A*, k-shortest (4.22).

## 9. Known limitations relevant to Membranch (consolidated)

- No `EXISTS {}`; use pattern predicates. Pattern comprehension bugs when nested (see table).
- Var-length path enumeration is exponential on DAG diamonds; always `DISTINCT` or use `algo.bfs` for ancestor/reachability sets. A depth cap like `*0..200` bounds length, not path count.
- `UNWIND`-before-CREATE row multiplication; `LIMIT` doesn't bound eager writes.
- Property types: primitives/arrays only (no maps, no null elements) -> JSON-encode structured facts (`toJSON` is for reading; store a Python-`json.dumps` string).
- Relationship-uniqueness quirk with unreferenced edge aliases (KL #1).
- `RESULTSET_SIZE`: docs say default 10,000 (rows beyond are silently dropped); my 4.18.3 build reported -1 (unlimited) [LIVE]. Image default VERIFY ON LIVE DB; set explicitly (`RESULTSET_SIZE 1000000`) so checkouts never truncate.
- `CACHE_SIZE` default 25 plans; `MAX_QUEUED_QUERIES` effectively unlimited; `QUERY_MEM_CAPACITY` unlimited by default.
- Param size: no FalkorDB-specific limit documented; Redis bulk-arg limit 512 MB; 1.2 MB / 5000 facts took 27 ms [LIVE]. Params are inlined into the query string, so very large params defeat nothing but do count against query-text parsing time.
- GRAPH.LIST is per Redis logical DB; Cloud/Cluster: one graph = one key = one shard.
- `id(n)` is internal and reusable - never store it.
- Constraints are created async (`PENDING`); wait for `OPERATIONAL` before relying on them.
- Own-write visibility: after `CREATE ... WITH n`, a later `MATCH` in the same query sees the new nodes (CC "post-write visibility") [LIVE], but an `UNWIND ... MATCH (a {id: <prev iteration's created node>}) CREATE` loop did NOT chain (each iteration's MATCH didn't see the previous iteration's create) - don't build chains inside one UNWIND; pass created nodes via variables.
- 4.x vs 6.0.x: engines differ (C vs Rust); 6.0.2 fixes list "CALL {} subqueries that import no variables no longer read outer variables", many parser fixes. VERIFY ON LIVE DB.

## 10. Docker image

Source https://docs.falkordb.com/operations/docker.md , https://docs.falkordb.com/operations/durability/persistence.md , https://docs.falkordb.com/getting-started/configuration.md
- `falkordb/falkordb`: server **6379** + Browser UI **3000**. `falkordb/falkordb-server`: 6379 only (use for CI/prod). `falkordb/falkordb-browser`: 3000, needs `FALKORDB_URL`.
- Env: `REDIS_ARGS` (Redis flags, e.g. `--requirepass pw --appendonly yes --save "60 1"`), `FALKORDB_ARGS` (module config, space-separated pairs).
  The docs' own example `FALKORDB_ARGS="THREAD_COUNT 4 TIMEOUT 5000"` uses the DEPRECATED `TIMEOUT`; use `TIMEOUT_MAX 30000 TIMEOUT_DEFAULT 5000`.
  Recommended: `FALKORDB_ARGS="THREAD_COUNT 4 CACHE_SIZE 200 TIMEOUT_MAX 30000 TIMEOUT_DEFAULT 10000 RESULTSET_SIZE 1000000 QUERY_MEM_CAPACITY 536870912 MAX_QUEUED_QUERIES 500"`
  (`THREAD_COUNT`, `CACHE_SIZE` load-time only; the rest runtime-settable via `GRAPH.CONFIG SET`, not persisted).
- Persistence volume: persistence page says data dir **`/var/lib/falkordb/data`** (`-v falkordb_data:/var/lib/falkordb/data`); the compose examples on the docker page mount `/data`.
  Inconsistent in docs => VERIFY ON LIVE DB (`docker exec ... redis-cli config get dir`). Add `--appendonly yes` for AOF durability.
- Run: `docker run -p 6379:6379 -p 3000:3000 -v falkordb_data:/var/lib/falkordb/data -e FALKORDB_ARGS="THREAD_COUNT 4" falkordb/falkordb:v4.22.1`

---------------------------------------------------------------------------------------------------

## RECOMMENDATIONS FOR MEMBRANCH (FalkorDB-valid Cypher)

Data model assumed: `(:Branch {name})-[:HEAD]->(:Commit {id, depth, msg, ts})`, `(:Commit)-[:PARENT {idx}]->(:Commit)`,
`(:Fact {id, ...scalar props, payload_json})-[:ADDED_IN]->(:Commit)`, `(:Fact)-[:REMOVED_IN]->(:Commit)`, `(:Fact)-[:DERIVED_FROM]->(:Fact)`.
A fact node is immutable (an "edit" = REMOVED_IN old + ADDED_IN new node). A fact is visible at commit H iff it has ADDED_IN to some commit in anc(H)
(anc includes H) and no REMOVED_IN to a commit in anc(H).

Schema bootstrap per tenant graph (all [LIVE]):
```cypher
CREATE INDEX FOR (c:Commit) ON (c.id)
CREATE INDEX FOR (f:Fact)   ON (f.id)
CREATE INDEX FOR (b:Branch) ON (b.name)
```
then (Redis commands, after indexes exist; poll `CALL db.constraints()` until OPERATIONAL):
`GRAPH.CONSTRAINT CREATE <g> UNIQUE NODE Commit PROPERTIES 1 id`, same for `Fact id`, `Branch name`.

### (a) Fast checkout (facts visible at a head) [LIVE]
Variant 1 - no extra storage (default): ancestors via `algo.bfs`.
```cypher
MATCH (h:Commit {id:$head})
CALL algo.bfs(h, 100000, 'PARENT') YIELD nodes
WITH [h.id] + [n IN nodes | n.id] AS anc
UNWIND anc AS cid
MATCH (c:Commit {id:cid})<-[:ADDED_IN]-(f:Fact)
OPTIONAL MATCH (f)-[:REMOVED_IN]->(x:Commit) WHERE x.id IN anc
WITH f, count(x) AS removed WHERE removed = 0
RETURN f.id AS id, f.subj AS subj, f.pred AS pred, f.obj AS obj, f.payload AS payload
```
Measured: 3000-commit chain, 15,000 facts, 14.5k visible rows: ~140-165 ms. Run with `ro_query`.
Variant 2 - materialised `Commit.ancestors` (O(N^2) memory! only if you need <10 ms merge-base):
replace the first 3 lines with `MATCH (h:Commit {id:$head}) WITH h.ancestors AS anc UNWIND anc AS cid`. (Same cost, 143 ms; memory 21 MB per 1000 commits.)
Do NOT use `MATCH (f)-[:ADDED_IN]->(a) WHERE a.id IN anc` (label scan, no index) nor `[:PARENT*0..N]` on a DAG (path explosion).

### (b) Atomic CAS commit + N facts + REMOVED_IN, ONE query [LIVE incl. stale, empty lists, unique-violation rollback]
```cypher
MATCH (b:Branch {name:$branch})-[r:HEAD]->(h:Commit {id:$expected})
CREATE (n:Commit {id:$new, ts:timestamp(), msg:$msg, author:$author, depth:h.depth + 1})-[:PARENT {idx:0}]->(h)
DELETE r
CREATE (b)-[:HEAD]->(n)
WITH n
FOREACH (f IN $facts |
  CREATE (:Fact {id:f.id, subj:f.subj, pred:f.pred, obj:f.obj, payload:f.payload, tags:f.tags})-[:ADDED_IN]->(n))
WITH n
CALL {
  WITH n
  UNWIND $removed AS rid
  MATCH (x:Fact {id:rid})
  CREATE (x)-[:REMOVED_IN]->(n)
}
RETURN n.id AS id
```
Params: `facts=[{id,subj,pred,obj,payload,tags}]` (no maps/null-containing arrays as values; `payload` = JSON string), `removed=[fact ids]`.
Semantics: 0 rows => CAS conflict (nothing written). Row returned => all of: commit, PARENT, HEAD move, facts, ADDED_IN, REMOVED_IN committed atomically; any error
(e.g. duplicate fact id via unique constraint) rolls back everything (HEAD unchanged) [LIVE]. Unknown ids in `$removed` are silently skipped (MATCH) - validate in app if that matters.
Add `DERIVED_FROM` edges in the same statement by extending the FOREACH body: `FOREACH (f IN $facts | CREATE (nf:Fact {...})-[:ADDED_IN]->(n) FOREACH (src IN f.derived_from | MERGE ...))`
- not tested; simpler and safe: a second UNWIND-based statement `UNWIND $deriv AS d MATCH (a:Fact {id:d.child}),(b:Fact {id:d.parent}) CREATE (a)-[:DERIVED_FROM]->(b)` (VERIFY ON LIVE DB if you need it inside the CAS).
Merge commit (2 parents) variant [LIVE]:
```cypher
MATCH (b:Branch {name:$branch})-[r:HEAD]->(h:Commit {id:$expected})
MATCH (p2:Commit {id:$parent2})
CREATE (n:Commit {id:$new, ts:timestamp(), msg:$msg,
                  depth: CASE WHEN h.depth > p2.depth THEN h.depth ELSE p2.depth END + 1})
CREATE (n)-[:PARENT {idx:0}]->(h), (n)-[:PARENT {idx:1}]->(p2)
DELETE r
CREATE (b)-[:HEAD]->(n)
WITH n
FOREACH (f IN $facts | CREATE (:Fact {id:f.id, subj:f.subj, pred:f.pred, obj:f.obj, payload:f.payload})-[:ADDED_IN]->(n))
WITH n
CALL { WITH n UNWIND $removed AS rid MATCH (x:Fact {id:rid}) CREATE (x)-[:REMOVED_IN]->(n) }
RETURN n.id
```
(If you keep the optional `ancestors` cache add `ancestors: list.dedup([$new] + h.ancestors + p2.ancestors)` to the CREATE props.)
Creating a new branch (fork): `MATCH (src:Branch {name:$from})-[:HEAD]->(h) CREATE (:Branch {name:$name})-[:HEAD]->(h)` (unique constraint on Branch.name makes it race-safe).

### (c) Merge-base = best common ancestor [LIVE, incl. a == b and a ancestor of b]
Highest-`depth` common ancestor is guaranteed maximal (a descendant always has strictly greater depth). `depth = 1 + max(parent depths)` is set in (b).
```cypher
MATCH (a:Commit {id:$a}), (b:Commit {id:$b})
CALL algo.bfs(a, 100000, 'PARENT') YIELD nodes AS an
WITH a, b, [a.id] + [n IN an | n.id] AS aids
CALL algo.bfs(b, 100000, 'PARENT') YIELD nodes AS bn
WITH aids, [b.id] + [n IN bn | n.id] AS bids
UNWIND aids AS x
WITH x, bids WHERE x IN bids
MATCH (c:Commit {id:x})
RETURN c.id AS base, c.depth AS depth
ORDER BY depth DESC LIMIT 1
```
~200 ms at 3000-deep history, sub-ms for demo-size. With the cached `ancestors` list: `WITH [x IN a.ancestors WHERE x IN b.ancestors] AS common UNWIND common AS cid MATCH (c:Commit {id:cid}) RETURN c.id, c.depth ORDER BY c.depth DESC LIMIT 1` (~8 ms).
Criss-cross merges can have several maximal bases; return `ORDER BY depth DESC LIMIT 2` and let the app pick/recurse if both are returned and neither is an ancestor of the other.
Then 3-way merge = checkout(base), checkout(ours), checkout(theirs) (query (a) x3, in parallel with `asyncio.gather` + `ro_query`) and diff in Python.

### (d) Dependents (what breaks if fact X changes) [LIVE]
All transitive dependents regardless of branch (always `DISTINCT`; path enumeration otherwise):
```cypher
MATCH (d:Fact)-[:DERIVED_FROM*1..6]->(x:Fact {id:$fid})
RETURN DISTINCT d.id AS id
```
Only those visible at a given head:
```cypher
MATCH (h:Commit {id:$head})
CALL algo.bfs(h, 100000, 'PARENT') YIELD nodes
WITH [h.id] + [n IN nodes | n.id] AS anc
MATCH (d:Fact)-[:DERIVED_FROM*1..6]->(x:Fact {id:$fid})
WITH DISTINCT d, anc
MATCH (d)-[:ADDED_IN]->(a:Commit) WHERE a.id IN anc
OPTIONAL MATCH (d)-[:REMOVED_IN]->(rm:Commit) WHERE rm.id IN anc
WITH d, count(rm) AS removed WHERE removed = 0
RETURN d.id AS id ORDER BY id
```
Caveat: `*1..6` bounds depth but not path count; DERIVED_FROM DAGs with many diamonds can blow up - `WITH DISTINCT` helps in the planner, but watch for it
(VERIFY ON LIVE DB with a realistic DERIVED_FROM fan-in; fall back to `algo.bfs(x, 6, 'DERIVED_FROM')` on the reversed direction or `algo.SSpaths`).
(Direction note: edge points derived -> source, so dependents = incoming `DERIVED_FROM*`, as written. `algo.bfs` direction semantics are undocumented (only the outgoing PARENT direction was exercised), so keep the var-length form for dependents.)

### (e) Why-path (provenance of fact X) [LIVE]
All derivation chains from X to root facts (no further DERIVED_FROM):
```cypher
MATCH p=(f:Fact {id:$fid})-[:DERIVED_FROM*1..6]->(r:Fact)
WHERE NOT (r)-[:DERIVED_FROM]->()
RETURN [n IN nodes(p) | n.id] AS chain, length(p) AS hops
ORDER BY hops
```
Shortest explanation only (endpoints bound, no property maps in the pattern):
```cypher
MATCH (a:Fact {id:$fid}), (b:Fact {id:$root})
WITH shortestPath((a)-[:DERIVED_FROM*..6]->(b)) AS p
RETURN [n IN nodes(p) | n.id] AS chain, length(p) AS hops
```
(`allShortestPaths` needs `WITH a,b MATCH p=allShortestPaths((a)-[:DERIVED_FROM*..6]->(b))`; `algo.SPpaths({sourceNode:a,targetNode:b,relTypes:['DERIVED_FROM'],pathCount:0})` also works.)
Enrich with the commit that introduced each fact in a SECOND query (do not use nested pattern comprehensions, they returned wrong results):
`MATCH (f:Fact)-[:ADDED_IN]->(c:Commit) WHERE f.id IN $chain_ids RETURN f.id, c.id, c.msg, c.ts`.

### Flags / VERIFY ON LIVE DB
- Everything on Docker `v4.22.1` and especially `6.0.x` (Rust engine): rerun the Python test suite once on each target image.
- `RESULTSET_SIZE` effective default in the image (docs 10,000 vs observed unlimited).
- Docker data dir (`/var/lib/falkordb/data` vs `/data`).
- Cloud free tier: `GRAPH.COPY`, `GRAPH.CONSTRAINT`, `CALL algo.*` availability; whether `GRAPH.CONFIG SET` is permitted; idle-stop behaviour for demos (keep a heartbeat).
- `TIMEOUT_DEFAULT` actually aborting write queries.
- MULTI/EXEC rollback semantics if a middle statement errors.
- `g.create_node_unique_constraint()` helper vs raw `GRAPH.CONSTRAINT CREATE`.
- DERIVED_FROM edges created inside the CAS query (FOREACH-nested forms).
- Fan-in-heavy DERIVED_FROM var-length performance.

## Sources
- https://docs.falkordb.com/llms.txt , /_llms/falkor-db.txt , /_llms/falkor-db/documentation.txt , /_llms/falkor-db-cloud.txt
- https://docs.falkordb.com/cypher/cypher-support.md , /cypher/functions.md , /cypher/call.md , /cypher/foreach.md , /cypher/unwind.md , /cypher/merge.md , /cypher/where.md , /cypher/known-limitations.md , /cypher/cheat-sheet.md
- https://docs.falkordb.com/cypher/indexing/range-index.md , /commands/graph.constraint-create.md , /commands/graph.copy.md , /commands/graph.list.md , /commands/graph.delete.md , /commands/graph.query.md
- https://docs.falkordb.com/design/concurrency.md , /getting-started/configuration.md , /operations/docker.md , /operations/durability/persistence.md , /operations/falkordblite/falkordblite-py.md
- https://docs.falkordb.com/algorithms/betweenness-centrality.md , /algorithms/sppath.md , /algorithms/bfs.md , /algorithms/index.md , /udfs/flex/collections/index.md
- https://docs.falkordb.com/cloud/tiers/free.md , /cloud/tiers/startup.md
- https://pypi.org/project/falkordb/ (1.8.0), https://pypi.org/project/falkordblite/ (0.10.0), https://github.com/FalkorDB/falkordb-py (README async example)
- https://github.com/FalkorDB/FalkorDB/releases (v4.22.1, v6.0.0, v6.0.2 notes), https://hub.docker.com/r/falkordb/falkordb/tags
