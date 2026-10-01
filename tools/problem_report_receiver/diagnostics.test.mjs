import assert from "node:assert/strict";
import { test } from "node:test";
import { validateReport } from "./worker.mjs";

test("schema-v1 intake preserves the expanded, reviewed diagnostic evidence", () => {
  const report = {schema_version:1,report_id:"12345678-1234-4321-8765-123456789abc",created_at:1,
    details:{summary:"Synthetic report: mesh restore failed",tool:"Mesh Editor",steps:"1. Include a part. 2. Compare. 3. Finish Edit Mesh.",
      expected:"The edited mesh should finish.",actual:"Snapshot source identity mismatch.",frequency:"Every time",
      game_version:"Unknown",game_platform:"Steam",mod_setup:"None",clean_test:"Not tried",contact:""},
    evidence:{environment:{cdmw_version:"test",build_identity:{application:{sha256:"a".repeat(64)}}},
      logs:{runtime_events:[{event:"logging_error",session_id:"s",traceback:"ValueError: source changed"}],
        tool_logs:{translations:"Invalid table"},latest_failures:[{diagnostic_context:{command:"morph_snapshot_restore",snapshot_id:"snapshot-1"}}],
        crash_reports:[{file:"app_hang_detected_20261001_185434_555_1.log",excerpt:"Hang stack trace"}],
        collection:{native_events:{status:"missing"},mesh_protocol:{status:"available",truncated:true}}}},
    screenshots:[]};
  const body = JSON.stringify(report);
  assert.equal(validateReport(report), report);
  assert.equal(JSON.stringify(report), body, "validation changed the reviewed evidence");
  delete report.evidence.logs;
  report.evidence.collection_options = {logs:"omitted by user"};
  assert.equal(validateReport(report), report);
});
