import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import worker from "./worker.mjs";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

class Bucket {
  values = new Map();
  serial = 0;
  async get(key) {
    const value = this.values.get(key);
    return value && {etag:value.etag,json:async()=>JSON.parse(value.body)};
  }
  async put(key, body, options) {
    const old = this.values.get(key);
    if (options?.onlyIf?.etagDoesNotMatch === "*" && old) return null;
    if (options?.onlyIf?.etagMatches && old?.etag !== options.onlyIf.etagMatches) return null;
    const etag = String(++this.serial);
    this.values.set(key,{body,etag});
    return {etag};
  }
}
function report() {
  return {schema_version:1,report_id:"12345678-1234-4321-8765-123456789abc",created_at:1,
    details:{summary:"Synthetic test: export fails",tool:"Archive Browser",steps:"1. Select the synthetic test asset. 2. Click Export.",
      expected:"The test asset should export.",actual:"A synthetic error is displayed.",frequency:"Every time",
      game_version:"Unknown",game_platform:"Steam",mod_setup:"None",clean_test:"Not tried",contact:""},
    evidence:{environment:{cdmw_version:"test"}},screenshots:[]};
}
function environment() { return {REPORTS:new Bucket(),GITHUB_TOKEN:"server-only",REPORT_TEST_TOKEN:"private-test-key"}; }
function request(data = report(), token = "private-test-key") {
  return new Request("https://reports.example/reports",{method:"POST",headers:{"Content-Type":"application/json","Authorization":`Bearer ${token}`},body:JSON.stringify(data)});
}
function githubMock({privateRepo = true, failCreate = false, acceptedButTimedOut = false} = {}) {
  const issues = [];
  let creates = 0;
  globalThis.fetch = async (url, options) => {
    assert.match(options.headers.Authorization,/^Bearer server-only$/);
    if (url.endsWith("/CDMW-Reports")) return Response.json({private:privateRepo,full_name:"Ratty123/CDMW-Reports"});
    if (options.method === "POST") {
      creates++;
      if (failCreate) return new Response("failed",{status:500});
      const issue = {number:creates,...JSON.parse(options.body)};
      issues.push(issue);
      if (acceptedButTimedOut && creates === 1) throw Error("Ambiguous network timeout");
      return Response.json(issue,{status:201});
    }
    return Response.json(issues);
  };
  return {issues,creates:()=>creates};
}

test("rejects unauthenticated, incomplete and oversized reports without creating objects", async () => {
  const env = environment();
  assert.equal((await worker.fetch(request(report(),"wrong"),env)).status,401);
  const incomplete = report(); incomplete.details.steps = "broken";
  assert.equal((await worker.fetch(request(incomplete),env)).status,400);
  const oversized = request(); oversized.headers.set("Content-Length",String(9 * 1024 * 1024));
  assert.equal((await worker.fetch(oversized,env)).status,413);
  const huge = report(); huge.evidence.padding = "x".repeat(9 * 1024 * 1024);
  assert.equal((await worker.fetch(request(huge),env)).status,413);
  assert.equal(env.REPORTS.values.size,0);
});

test("stays closed until both secrets and the bucket are configured", async () => {
  const env = environment(); delete env.GITHUB_TOKEN;
  assert.equal((await worker.fetch(request(),env)).status,503);
  const health = await (await worker.fetch(new Request("https://reports.example/health"),env)).json();
  assert.equal(health.configured,false);
  assert.equal(JSON.stringify(health).includes("server-only"),false);
});

test("creates one private issue, stores evidence and returns a matching receipt", async () => {
  const env = environment(); const mock = githubMock();
  const result = await worker.fetch(request(),env);
  assert.equal(result.status,201);
  const receipt = await result.json();
  assert.deepEqual(receipt,{status:"accepted",report_id:report().report_id,issue_number:1});
  assert.equal(mock.creates(),1);
  assert.match(mock.issues[0].body,/Steps to reproduce/);
  assert.match(mock.issues[0].body,/\/reports\/[0-9a-f-]+#[0-9a-f]{64}/);
  assert.equal(JSON.stringify(receipt).includes("download_key"),false);
  assert.equal(JSON.stringify(receipt).includes("server-only"),false);
});

test("accepted retries are idempotent; changed content cannot reuse a report ID", async () => {
  const env = environment(); const mock = githubMock();
  await worker.fetch(request(),env);
  assert.equal((await worker.fetch(request(),env)).status,200);
  assert.equal(mock.creates(),1);
  const changed = report(); changed.details.actual = "A different result happened.";
  assert.equal((await worker.fetch(request(changed),env)).status,409);
});

test("concurrent delivery returns pending rather than creating a second issue", async () => {
  const env = environment(); const mock = githubMock();
  const fetchMock = globalThis.fetch;
  let entered, release;
  const waiting = new Promise(resolve=>{entered=resolve});
  const blocked = new Promise(resolve=>{release=resolve});
  globalThis.fetch = async (...args) => { entered(); await blocked; return fetchMock(...args); };
  const first = worker.fetch(request(),env);
  await waiting;
  assert.equal((await worker.fetch(request(),env)).status,202);
  release();
  assert.equal((await first).status,201);
  assert.equal(mock.creates(),1);
});

test("refuses a public repository and never marks a failed send as accepted", async () => {
  const env = environment(); const mock = githubMock({privateRepo:false});
  assert.equal((await worker.fetch(request(),env)).status,503);
  assert.equal(mock.creates(),0);
  const stored = await (await env.REPORTS.get(`reports/${report().report_id}.json`)).json();
  assert.equal(stored.receipt,undefined);
  assert.equal(stored.lock_until,0);
});

test("recovers an issue accepted before a network timeout without duplicating it", async () => {
  const env = environment(); const mock = githubMock({acceptedButTimedOut:true});
  assert.equal((await worker.fetch(request(),env)).status,503);
  const retry = await worker.fetch(request(),env);
  assert.equal(retry.status,201);
  assert.equal((await retry.json()).issue_number,1);
  assert.equal(mock.creates(),1);
});

test("download requires its own report key, expires and never accepts the intake key", async () => {
  const env = environment(); githubMock();
  await worker.fetch(request(),env);
  const objectKey = `reports/${report().report_id}.json`;
  const record = await (await env.REPORTS.get(objectKey)).json();
  const url = `https://reports.example/reports/${report().report_id}/download`;
  assert.equal((await worker.fetch(new Request(url),env)).status,404);
  assert.equal((await worker.fetch(new Request(url,{headers:{Authorization:"Bearer private-test-key"}}),env)).status,404);
  const good = new Request(url,{headers:{Authorization:`Bearer ${record.download_key}`}});
  const download = await worker.fetch(good,env);
  assert.equal(download.status,200);
  assert.deepEqual(await download.json(),report());
  record.created_at = Date.now() - 91 * 86400000;
  await env.REPORTS.put(objectKey,JSON.stringify(record));
  assert.equal((await worker.fetch(good,env)).status,404);
});

test("issue text cannot render remote images or notify arbitrary GitHub users", async () => {
  const env = environment(); const mock = githubMock();
  const data = report(); data.details.actual = "@someone ![image](https://example.com) <img src=x> ``` injected";
  await worker.fetch(request(data),env);
  assert.match(mock.issues[0].body,/@\u200bsomeone/);
  assert.match(mock.issues[0].body,/&lt;img/);
  assert.match(mock.issues[0].body,/ˋˋˋ injected/);
});

test("viewer uses a fragment key and renders report content as text", async () => {
  const viewer = await worker.fetch(new Request(`https://reports.example/reports/${report().report_id}`),{});
  assert.equal(viewer.status,200);
  const html = await viewer.text();
  assert.match(html,/location.hash.slice/);
  assert.match(html,/history.replaceState/);
  assert.match(html,/pre.textContent/);
  assert.match(viewer.headers.get("Content-Security-Policy"),/frame-ancestors 'none'/);
});
