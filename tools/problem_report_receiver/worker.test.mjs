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
function githubMock({privateRepo = true, repositoryName = "Ratty123/CDMW-Reports", failCreate = false, acceptedButTimedOut = false} = {}) {
  const issues = [];
  let creates = 0;
  globalThis.fetch = async (url, options) => {
    assert.match(options.headers.Authorization,/^Bearer server-only$/);
    if (url.endsWith("/CDMW-Reports")) return Response.json({private:privateRepo,full_name:repositoryName});
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

function publicEnvironment() {
  return {...environment(),PUBLIC_REPORTS:"1",TURNSTILE_SITE_KEY:"mock-live-site-key-123456789",
    TURNSTILE_SECRET_KEY:"mock-live-server-secret-123456789"};
}
function publicRequest(path,body,token="",ip="198.51.100.10") {
  return new Request("https://reports.example"+path,{method:body === undefined ? "GET" : "POST",
    headers:{"Content-Type":"application/json","CF-Connecting-IP":ip,...(token ? {Authorization:`Bearer ${token}`} : {})},
    ...(body === undefined ? {} : {body:typeof body === "string" ? body : JSON.stringify(body)})});
}
async function sha(text) {
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(text)))].map(x=>x.toString(16).padStart(2,"0")).join("");
}
function publicMock(options={}) {
  const mock=githubMock(options), githubFetch=globalThis.fetch, checks=[];
  globalThis.fetch=async (url,request)=>{
    if(url !== "https://challenges.cloudflare.com/turnstile/v0/siteverify") return githubFetch(url,request);
    const data=JSON.parse(request.body); checks.push(data);
    assert.equal(data.secret,"mock-live-server-secret-123456789");
    return Response.json({success:data.response.startsWith("valid-turnstile-token."),hostname:"reports.example",action:"cdmw_report",
      cdata:data.response.split(".")[1],challenge_ts:new Date(Date.now()).toISOString(),...options.validation});
  };
  return {...mock,checks};
}
async function startPublic(env,raw=JSON.stringify(report()),ip="198.51.100.10") {
  const result=await worker.fetch(publicRequest("/verification/start",{
    report_id:JSON.parse(raw).report_id,report_sha256:await sha(raw)},"",ip),env);
  assert.equal(result.status,200);
  return result.json();
}
async function approvePublic(env,check,token) {
  const ticket=JSON.parse(Buffer.from(check.ticket.split('.')[0],"base64url").toString());
  token ??= "valid-turnstile-token."+ticket.nonce;
  return worker.fetch(publicRequest("/verification/complete",{ticket:check.ticket,turnstile_token:token}),env);
}

test("public intake requires configured live verification and never accepts the private test key",async()=>{
  const env=publicEnvironment(); const mock=publicMock();
  assert.equal((await worker.fetch(request(),env)).status,401);
  assert.equal(env.REPORTS.values.size,0);
  const check=await startPublic(env);
  assert.equal(env.REPORTS.values.size,0);
  assert.equal(mock.checks.length,0);
  assert.equal(mock.creates(),0);
  assert.equal(check.verification_url,"https://reports.example/verify#"+check.ticket);
  assert.equal(JSON.stringify(check).includes(env.TURNSTILE_SECRET_KEY),false);
  const status=await worker.fetch(publicRequest("/verification/status",undefined,check.ticket),env);
  assert.deepEqual(await status.json(),{status:"pending",report_id:report().report_id});
  assert.equal((await worker.fetch(publicRequest("/reports",JSON.stringify(report()),check.ticket),env)).status,401);
  assert.equal(env.REPORTS.values.size,0);
  for(const patch of [{TURNSTILE_SECRET_KEY:""},{TURNSTILE_SITE_KEY:"1x00000000000000000000AA"},
      {TURNSTILE_SECRET_KEY:"1x0000000000000000000000000000000AA"}]) {
    const invalid={...env,...patch};
    assert.equal((await worker.fetch(publicRequest("/verification/start",{report_id:report().report_id,report_sha256:"a".repeat(64)}),invalid)).status,503);
    assert.equal((await (await worker.fetch(publicRequest("/health"),invalid)).json()).configured,false);
  }
});

test("public browser approval sends only the exact reviewed bytes to the private inbox",async()=>{
  const env=publicEnvironment(), mock=publicMock();
  const raw=JSON.stringify(report(),null,2).replace('"created_at": 1','"created_at": 1790840000000000100');
  const check=await startPublic(env,raw);
  assert.equal((await approvePublic(env,check)).status,200);
  assert.equal(mock.checks.length,1);
  assert.deepEqual(await (await worker.fetch(publicRequest("/verification/status",undefined,check.ticket),env)).json(),
    {status:"verified",report_id:report().report_id});
  assert.equal((await worker.fetch(publicRequest("/reports",raw,check.ticket),env)).status,201);
  const record=await (await env.REPORTS.get(`reports/${report().report_id}.json`)).json();
  assert.equal(record.report_json,raw);
  assert.match(mock.issues[0].title,/^\[CDMW\] /);
  assert.equal((await worker.fetch(publicRequest("/reports",raw,check.ticket),env)).status,200);
  assert.equal(mock.creates(),1);
  assert.equal((await approvePublic(env,check)).status,200);
  assert.equal(mock.checks.length,1);
  assert.equal((await worker.fetch(publicRequest(`/reports/${report().report_id}/download`,undefined,check.ticket),env)).status,404);
  const altered=raw.replace('1790840000000000100','1790840000000000101');
  assert.equal((await worker.fetch(publicRequest("/reports",altered,check.ticket),env)).status,401);
  const different={...report(),report_id:freshReport(901).report_id};
  assert.equal((await worker.fetch(publicRequest("/reports",different,check.ticket),env)).status,401);
  assert.equal(mock.creates(),1);
});

test("public verification rejects forged tickets, other networks, expiry and wrong provider claims",async()=>{
  const env=publicEnvironment(); publicMock(); const check=await startPublic(env);
  assert.equal((await worker.fetch(publicRequest("/verification/status",undefined,check.ticket+"x"),env)).status,401);
  assert.equal((await worker.fetch(publicRequest("/verification/status",undefined,check.ticket,"198.51.100.99"),env)).status,401);
  for(const validation of [{success:false},{hostname:"attacker.example"},{action:"other"},{cdata:"other"},
      {challenge_ts:new Date(Date.now()-301000).toISOString()}]) {
    publicMock({validation});
    assert.equal((await approvePublic(env,check)).status,400);
    assert.equal(env.REPORTS.values.size,0);
  }
  const now=Date.now(); Date.now=()=>now+600001;
  assert.equal((await approvePublic(env,check)).status,401);
});

test("a public client cannot post reports to a public or substituted GitHub inbox",async()=>{
  for(const options of [{privateRepo:false},{repositoryName:"Ratty123/CDMW-Full"}]) {
    const env=publicEnvironment(), mock=publicMock(options);
    const check=await startPublic(env);
    assert.equal((await approvePublic(env,check)).status,200);
    assert.equal((await worker.fetch(publicRequest("/reports",report(),check.ticket),env)).status,503);
    assert.equal(mock.creates(),0);
  }
});

test("fresh browser challenges do not reuse failed provider validation keys",async()=>{
  const env=publicEnvironment(), mock=publicMock({validation:{success:false}}), check=await startPublic(env);
  for(const token of ["failed-token-one","failed-token-one","failed-token-two"])
    assert.equal((await approvePublic(env,check,token)).status,400);
  const keys=mock.checks.map(value=>value.idempotency_key);
  assert.match(keys[0],/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.equal(keys[0],keys[1]);
  assert.notEqual(keys[0],keys[2]);
  assert.equal(env.REPORTS.values.size,0);
});

test("public verification reservations enforce persistent budgets and fail closed",async()=>{
  const advance=clock(15), env=publicEnvironment(); publicMock();
  const check=await startPublic(env), ticket=JSON.parse(Buffer.from(check.ticket.split('.')[0],"base64url").toString());
  const day=new Date(Date.now()).toISOString().slice(0,10);
  const entries=Array.from({length:20},(_,index)=>({nonce:freshReport(800+index).report_id,subject:ticket.subject,at:Date.now()-3000}));
  await env.REPORTS.put("reports/_verification-admission-v1.json",JSON.stringify({version:1,day,entries}));
  const blocked=await approvePublic(env,check);
  assert.equal(blocked.status,429);
  assert.equal((await blocked.json()).code,"verification_network_limit");
  assert.equal(env.REPORTS.values.size,1);
  entries.length=0;
  for(let index=0;index<500;index++) entries.push({nonce:freshReport(1000+index).report_id,subject:"a".repeat(64),at:Date.now()-3000});
  await env.REPORTS.put("reports/_verification-admission-v1.json",JSON.stringify({version:1,day,entries}));
  assert.equal((await approvePublic(env,check)).status,429);
  await env.REPORTS.put("reports/_verification-admission-v1.json",JSON.stringify({version:1,day,entries:[{nonce:"bad"}]}));
  assert.equal((await approvePublic(env,check)).status,503);
  advance(86400000);
  const next=await startPublic(env);
  // Corrupt protection is not silently replaced at midnight.
  assert.equal((await approvePublic(env,next)).status,503);
});

test("concurrent public verifications cannot overrun persistent reservations",async()=>{
  clock(16);const env=publicEnvironment();publicMock();
  const first=await startPublic(env),second=await startPublic(env);
  const results=await Promise.all([approvePublic(env,first),approvePublic(env,second)]);
  assert.deepEqual(results.map(r=>r.status).sort(),[200,429]);
  const ledger=await (await env.REPORTS.get("reports/_verification-admission-v1.json")).json();
  assert.equal(ledger.entries.length,1);
  assert.equal([...env.REPORTS.values.keys()].filter(key=>key.startsWith("reports/_verification/")).length,1);
});

test("verification page exposes only the public widget key and keeps credentials out of URLs",async()=>{
  const env=publicEnvironment();
  const page=await worker.fetch(publicRequest("/verify"),env), html=await page.text();
  assert.equal(page.status,200);
  assert.match(html,/location.hash.slice/);
  assert.match(html,/history.replaceState/);
  assert.match(html,/cData:data.nonce/);
  assert.match(html,/send automatically/);
  assert.equal(html.includes(env.TURNSTILE_SECRET_KEY),false);
  assert.equal(html.includes(env.GITHUB_TOKEN),false);
  assert.equal(html.includes(env.REPORT_TEST_TOKEN),false);
  assert.match(page.headers.get("Content-Security-Policy"),/frame-src https:\/\/challenges.cloudflare.com/);
  assert.equal(page.headers.get("Referrer-Policy"),"no-referrer");
});

test("completed browser verification stays successful after provider expiry or late callbacks",async()=>{
  const page=await worker.fetch(publicRequest("/verify"),publicEnvironment());
  const script=(await page.text()).match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/)[1];
  const ticket=Buffer.from(JSON.stringify({nonce:"owned-test-nonce"})).toString("base64url")+".signature";
  const elements={status:{textContent:""},retry:{hidden:true}},window={};
  let challenge,requests=0,resets=0;
  runInNewContext(script,{
    window,location:{hash:"#"+ticket,pathname:"/verify"},history:{replaceState:()=>{}},atob,
    document:{getElementById:id=>elements[id]},
    turnstile:{render:(selector,options)=>{challenge=options;return "owned-widget"},reset:()=>resets++},
    fetch:async()=>{requests++;return Response.json({status:"verified"})},
  });
  window.cdmwCheck();
  challenge["expired-callback"]();
  assert.match(elements.status.textContent,/expired/);
  assert.equal(elements.retry.hidden,false);
  elements.retry.onclick();
  assert.equal(resets,1);
  await challenge.callback("owned-token");
  assert.equal(elements.status.textContent,"Verified. Return to CDMW.");
  assert.equal(elements.retry.hidden,true);
  challenge["expired-callback"]();
  challenge["error-callback"]();
  elements.retry.onclick();
  await challenge.callback("late-token");
  assert.equal(elements.status.textContent,"Verified. Return to CDMW.");
  assert.equal(elements.retry.hidden,true);
  assert.equal(requests,1);
  assert.equal(resets,1);
});
