import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { runInNewContext } from "node:vm";
import worker from "./worker.mjs";

const originalFetch = globalThis.fetch;
const originalNow = Date.now;
afterEach(() => { globalThis.fetch = originalFetch; Date.now = originalNow; });

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
  return new Request("https://reports.example/reports",{method:"POST",headers:{"Content-Type":"application/json","Authorization":`Bearer ${token}`,
    "CF-Connecting-IP":"198.51.100.10"},body:JSON.stringify(data)});
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
  assert.match(mock.issues[0].body,/maintainer and invited collaborators of this private GitHub repository/);
  assert.match(mock.issues[0].body,/Anyone with the complete evidence link can read this report without a GitHub account/);
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
  assert.equal(download.headers.get("Cache-Control"),"no-store");
  assert.match(download.headers.get("X-Robots-Tag"),/noindex/);
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
  assert.match(html,/<h1>CDMW report evidence<\/h1>/);
  assert.match(html,/Anyone with the complete evidence link can read this report/);
  assert.equal(html.includes("Private CDMW report"),false);
  assert.match(viewer.headers.get("X-Robots-Tag"),/noindex/);
  assert.match(viewer.headers.get("Content-Security-Policy"),/frame-ancestors 'none'/);
});

test("viewer disables access without a complete key and only sends the key in an authorization header", async () => {
  const result = await worker.fetch(new Request(`https://reports.example/reports/${report().report_id}`),{});
  const script = (await result.text()).match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/)[1];
  for (const key of ["", "partial-key", "a".repeat(64)]) {
    const elements = {load:{disabled:true},status:{textContent:""}};
    const requests = [], replaced = [];
    const location = {hash:key ? `#${key}` : "",pathname:`/reports/${report().report_id}`};
    runInNewContext(script,{
      location,history:{replaceState:(...args)=>replaced.push(args)},
      document:{getElementById:id=>elements[id]},
      fetch:async (...args)=>{requests.push(args);return new Response("",{status:404})},
    });
    assert.deepEqual(replaced,[[null,"",location.pathname]]);
    assert.equal(requests.length,0);
    assert.equal(elements.load.disabled,key.length !== 64);
    await elements.load.onclick();
    if (key.length !== 64) {
      assert.match(elements.status.textContent,/Access key missing.*complete evidence link/);
      assert.equal(requests.length,0);
    } else {
      assert.equal(requests[0][0],location.pathname+"/download");
      assert.equal(requests[0][1].headers.Authorization,`Bearer ${key}`);
      assert.match(elements.status.textContent,/unavailable, expired, or access key incorrect/);
    }
  }
});

function clock(day) {
  let now = Date.UTC(2026,10,day,12);
  Date.now = () => now;
  return milliseconds => { now += milliseconds; };
}
function freshReport(index) {
  const data = report();
  data.report_id = `12345678-1234-4321-8765-${String(index).padStart(12,"0")}`;
  data.details.summary += ` case ${index}`;
  return data;
}
function fromNetwork(data,index) {
  const value = request(data);
  value.headers.set("CF-Connecting-IP",`198.51.100.${index}`);
  return value;
}

test("new IDs and new evidence cannot duplicate the same problem from a network", async () => {
  clock(1);
  const env=environment(); const mock=githubMock();
  const original=report();
  assert.equal((await worker.fetch(request(original),env)).status,201);
  const changed=structuredClone(original);
  changed.report_id=freshReport(2).report_id; changed.created_at=999;
  changed.evidence={environment:{cdmw_version:"different"}};
  changed.details.steps="  "+changed.details.steps.toUpperCase()+"  ";
  const duplicate=await worker.fetch(request(changed),env);
  assert.equal(duplicate.status,409);
  assert.equal((await duplicate.json()).code,"already_reported");
  assert.equal(mock.creates(),1);
  assert.equal(await env.REPORTS.get(`reports/${changed.report_id}.json`),undefined);
});

test("cooldown and network daily cap persist through separate receiver requests", async () => {
  const advance=clock(2); const env=environment(); const mock=githubMock();
  assert.equal((await worker.fetch(request(freshReport(1)),env)).status,201);
  const tooSoon=await worker.fetch(request(freshReport(2)),env);
  assert.equal(tooSoon.status,429); assert.equal(tooSoon.headers.get("Retry-After"),"120");
  for(let i=2;i<=5;i++) {
    advance(121000);
    assert.equal((await worker.fetch(request(freshReport(i)),env)).status,201);
  }
  advance(121000);
  const capped=await worker.fetch(request(freshReport(6)),env);
  assert.equal(capped.status,429); assert.equal((await capped.json()).code,"network_daily_limit");
  assert.equal(mock.creates(),5);
  // Existing receipts remain usable when the network quota is exhausted.
  assert.equal((await worker.fetch(request(freshReport(1)),env)).status,200);
  const state=await (await env.REPORTS.get("reports/_admission-v1.json")).json();
  assert.equal(JSON.stringify(state).includes("198.51.100"),false);
  assert.equal(JSON.stringify(state).includes("private-test-key"),false);
});

test("global cap cannot be bypassed by changing networks and resets at UTC midnight", async () => {
  const advance=clock(3); const env=environment(); const mock=githubMock();
  for(let i=1;i<=10;i++) {
    advance(2100);
    assert.equal((await worker.fetch(fromNetwork(freshReport(i),i),env)).status,201);
  }
  const capped=await worker.fetch(fromNetwork(freshReport(11),11),env);
  assert.equal(capped.status,429); assert.equal((await capped.json()).code,"daily_report_limit");
  assert.equal(mock.creates(),10);
  advance(86400000);
  assert.equal((await worker.fetch(fromNetwork(freshReport(11),11),env)).status,201);
});

test("concurrent different reports cannot overrun admission or write extra evidence", async () => {
  clock(4); const env=environment(); const mock=githubMock();
  const results=await Promise.all(Array.from({length:30},(_,i)=>worker.fetch(fromNetwork(freshReport(i+1),i+1),env)));
  assert.equal(results.filter(result=>result.status===201).length,1);
  assert.equal(results.filter(result=>result.status===429).length,29);
  assert.equal(mock.creates(),1);
  assert.equal(env.REPORTS.values.size,2); // one admission ledger, one report
});

test("protection fails closed on missing network or unavailable/corrupt admission storage", async () => {
  clock(5); const env=environment(); const mock=githubMock();
  const missing=request(); missing.headers.delete("CF-Connecting-IP");
  assert.equal((await worker.fetch(missing,env)).status,503);
  assert.equal(env.REPORTS.values.size,0);
  const put=env.REPORTS.put.bind(env.REPORTS);
  env.REPORTS.put=async (key,...args)=> { if(key.includes("_admission")) throw Error("unavailable"); return put(key,...args); };
  assert.equal((await worker.fetch(request(),env)).status,429);
  assert.equal(env.REPORTS.values.size,0); assert.equal(mock.creates(),0);
  await put("reports/_admission-v1.json",JSON.stringify({version:2,entries:[]}));
  assert.equal((await worker.fetch(request(),env)).status,503);
  await put("reports/_admission-v1.json","null");
  assert.equal((await worker.fetch(request(),env)).status,503);
});

test("a pending delivery from a previous day must reserve today's capacity before creating an issue", async () => {
  const advance=clock(6); const env=environment(); githubMock({failCreate:true});
  assert.equal((await worker.fetch(request(),env)).status,503);
  advance(86400000); const mock=githubMock();
  for(let i=1;i<=10;i++) {
    advance(2100);
    assert.equal((await worker.fetch(fromNetwork(freshReport(i),i+20),env)).status,201);
  }
  assert.equal((await worker.fetch(request(),env)).status,429);
  assert.equal(mock.creates(),10);
});

test("rapid invalid requests are rejected before repeatedly reading storage", async () => {
  clock(8); const env=environment();
  let reads=0; const get=env.REPORTS.get.bind(env.REPORTS);
  env.REPORTS.get=async(...args)=>{reads++; return get(...args);};
  const invalid=report(); invalid.details.steps="broken";
  for(let i=0;i<40;i++) assert.equal((await worker.fetch(request(invalid),env)).status,400);
  assert.equal((await worker.fetch(request(invalid),env)).status,429);
  assert.equal(reads,0);
});

test("evidence download preserves exact reviewed JSON bytes and large integer timestamps", async () => {
  clock(9); const env=environment(); githubMock();
  const raw=JSON.stringify(report(),null,2).replace('"created_at": 1','"created_at": 1790840000000000100');
  const submission=request();
  const value=new Request(submission.url,{method:'POST',headers:submission.headers,body:raw});
  assert.equal((await worker.fetch(value,env)).status,201);
  const stored=await (await env.REPORTS.get(`reports/${report().report_id}.json`)).json();
  assert.equal(stored.report_json,raw);
  const download=await worker.fetch(new Request(`https://reports.example/reports/${report().report_id}/download`,{
    headers:{Authorization:`Bearer ${stored.download_key}`}}),env);
  assert.equal(await download.text(),raw);
  const altered=raw.replace('1790840000000000100','1790840000000000101');
  assert.equal((await worker.fetch(new Request(submission.url,{method:'POST',headers:submission.headers,body:altered}),env)).status,409);
  const viewer=await worker.fetch(new Request(`https://reports.example/reports/${report().report_id}`),env);
  assert.match(await viewer.text(),/new Blob\(\[raw\]/);
});

test("earlier pilot record format retains accepted receipts and downloads", async () => {
  clock(10); const env=environment(); const mock=githubMock();
  await worker.fetch(request(),env);
  const key=`reports/${report().report_id}.json`;
  const stored=await (await env.REPORTS.get(key)).json();
  stored.report=JSON.parse(stored.report_json); delete stored.report_json;
  await env.REPORTS.put(key,JSON.stringify(stored));
  assert.equal((await worker.fetch(request(),env)).status,200);
  assert.equal(mock.creates(),1);
  const downloaded=await worker.fetch(new Request(`https://reports.example/reports/${report().report_id}/download`,{
    headers:{Authorization:`Bearer ${stored.download_key}`}}),env);
  assert.deepEqual(await downloaded.json(),report());
});
