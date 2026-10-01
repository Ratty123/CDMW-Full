// Private test receiver. Credentials belong in Worker secrets, never in CDMW.
const REPOSITORY = "Ratty123/CDMW-Reports";
const MAX_BYTES = 8 * 1024 * 1024;
const LOCK_MS = 120000;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const encoder = new TextEncoder();
const ADMISSION_KEY = "reports/_admission-v1.json";
const DAILY_REPORTS = 10;
const DAILY_PER_NETWORK = 5;
const NETWORK_COOLDOWN_MS = 120000;
const GLOBAL_COOLDOWN_MS = 2000;
const burstCounts = new Map();
let burstMinute = -1;
let burstTotal = 0;

class ReportError extends Error {
  constructor(status, message, code = "", retryAfter = 0, extra = {}) {
    super(message); this.status = status; this.code = code; this.retryAfter = retryAfter; this.extra = extra;
  }
}
function response(status, payload, headers = {}, raw = false) {
  return new Response(raw ? payload : JSON.stringify(payload), { status, headers: {
    "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", ...headers,
  }});
}
async function digest(text) {
  const hash = await crypto.subtle.digest("SHA-256", encoder.encode(text));
  return [...new Uint8Array(hash)].map(x => x.toString(16).padStart(2, "0")).join("");
}
async function sameSecret(a, b) {
  if (!a || !b) return false;
  return (await digest(a)) === (await digest(b));
}
function readToken(request) {
  const value = request.headers.get("Authorization") || "";
  return value.startsWith("Bearer ") && value.length <= 256 ? value.slice(7) : "";
}

async function boundedBody(request) {
  if (!/^application\/json(?:;|$)/i.test(request.headers.get("Content-Type") || ""))
    throw new ReportError(415, "Send a JSON report.");
  if (Number(request.headers.get("Content-Length")) > MAX_BYTES)
    throw new ReportError(413, "Report exceeds 8 MB.");
  const reader = request.body?.getReader();
  if (!reader) throw new ReportError(400, "Report is empty.");
  const chunks = [];
  let size = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.length;
    if (size > MAX_BYTES) { await reader.cancel(); throw new ReportError(413, "Report exceeds 8 MB."); }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  try {
    const raw = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
    return {raw,report:JSON.parse(raw)};
  }
  catch { throw new ReportError(400, "Report is not valid JSON."); }
}

export function validateReport(report) {
  if (!report || report.schema_version !== 1 || !UUID.test(report.report_id || ""))
    throw new ReportError(400, "Unsupported report format or report ID.");
  const details = report.details;
  if (!details || Array.isArray(details) || typeof details !== "object")
    throw new ReportError(400, "Report details are missing.");
  for (const [key, min, max] of [["summary",10,120],["tool",2,120],["steps",20,6000],
    ["expected",10,3000],["actual",10,3000],["game_version",2,80],["mod_setup",4,2000],["contact",0,200]]) {
    if (typeof details[key] !== "string" || details[key].trim().length < min || details[key].length > max)
      throw new ReportError(400, `Please complete ${key}.`);
  }
  for (const [key, choices] of [
    ["frequency",["Every time","Sometimes","Once"]],
    ["game_platform",["Steam","Epic Games","Other / unsure"]],
    ["clean_test",["Not tried","Still happens without mods","Works without mods","No mods installed"]],
  ]) if (!choices.includes(details[key])) throw new ReportError(400, `Please complete ${key}.`);
  // Optional additions preserve the first pilot's saved schema-v1 retry payloads.
  for (const [key,choices] of [["problem_type",["CDMW error / crash","Slow or unresponsive",
    "Mod export / installation","Unexpected in-game result","Other / unsure"]],
    ["last_working",["First time trying this","Worked before","Not sure"]]]) {
    if (details[key] !== undefined && !choices.includes(details[key])) throw new ReportError(400, `Please complete ${key}.`);
  }
  if (details.input_item !== undefined && (typeof details.input_item !== "string" ||
      details.input_item.trim().length < 4 || details.input_item.length > 300)) throw new ReportError(400,"Please complete input_item.");
  if (details.changes !== undefined && (typeof details.changes !== "string" || details.changes.length > 1000))
    throw new ReportError(400,"Please complete changes.");
  if (details.last_working === "Worked before" && (!details.changes || details.changes.trim().length < 10))
    throw new ReportError(400,"Describe changes since it last worked, or write Not sure yet.");
  if (!report.evidence || typeof report.evidence !== "object" || Array.isArray(report.evidence))
    throw new ReportError(400, "Report evidence is missing.");
  if (!Array.isArray(report.screenshots) || report.screenshots.length > 3)
    throw new ReportError(400, "Attach at most three screenshots.");
  for (let index = 0; index < report.screenshots.length; index++) {
    const shot = report.screenshots[index];
    if (shot?.name !== `screenshot-${index + 1}.jpg` || shot.mime !== "image/jpeg" ||
        typeof shot.data !== "string" || !/^[A-Za-z0-9+/]+={0,2}$/.test(shot.data) ||
        shot.data.length > Math.ceil(2 * 1024 * 1024 / 3) * 4)
      throw new ReportError(400, "Invalid screenshot.");
    let bytes;
    try { bytes = atob(shot.data); } catch { throw new ReportError(400, "Invalid screenshot encoding."); }
    if (bytes.length > 2 * 1024 * 1024 || bytes.length !== shot.size || bytes.charCodeAt(0) !== 255 || bytes.charCodeAt(1) !== 216 ||
        bytes.charCodeAt(2) !== 255 || bytes.charCodeAt(bytes.length - 2) !== 255 ||
        bytes.charCodeAt(bytes.length - 1) !== 217)
      throw new ReportError(400, "Screenshots must be normalized JPEG images.");
  }
  return report;
}

async function networkSubject(request, env, day) {
  // Cloudflare supplies this header. Never use a client installation ID or X-Forwarded-For.
  const ip = request.headers.get("CF-Connecting-IP");
  if (!ip || ip.length > 64 || !/^[0-9a-fA-F:.]+$/.test(ip))
    throw new ReportError(503,"The receiver cannot verify the request network. Keep the draft and retry.");
  const key = await crypto.subtle.importKey("raw",encoder.encode(env.REPORT_TEST_TOKEN),
    {name:"HMAC",hash:"SHA-256"},false,["sign"]);
  const signature = await crypto.subtle.sign("HMAC",key,encoder.encode(`cdmw-network:${day}:${ip}`));
  return [...new Uint8Array(signature)].map(x=>x.toString(16).padStart(2,"0")).join("");
}

function rateLimit(seconds, code = "report_limit") {
  return new ReportError(429,"Keep the saved draft and retry after the countdown.",code,Math.max(1,Math.ceil(seconds)));
}

async function checkBurst(request, env) {
  const now = Date.now();
  const minute = Math.floor(now/60000);
  if (minute !== burstMinute) { burstCounts.clear(); burstTotal = 0; burstMinute = minute; }
  const subject = await networkSubject(request,env,new Date(now).toISOString().slice(0,10));
  const count = burstCounts.get(subject) || 0;
  if (count >= 40 || burstTotal >= 120) throw rateLimit(60-now%60000/1000,"request_burst");
  burstCounts.set(subject,count+1); burstTotal++;
  // Best-effort early rejection only. R2 admission remains authoritative across isolates.
}

async function admitReport(request, env, report) {
  const now = Date.now();
  const day = new Date(now).toISOString().slice(0,10);
  const subject = await networkSubject(request,env,day);
  const fields = ["summary","tool","steps","expected","actual","game_version","game_platform","mod_setup",
    "clean_test","problem_type","input_item","last_working","changes"];
  const fingerprint = await digest(JSON.stringify(fields.map(key=>String(report.details[key] || "")
    .normalize("NFKC").trim().toLowerCase().replace(/\s+/g," "))));
  // One bounded, strongly consistent object governs all locations and concurrent requests.
  const stored = await env.REPORTS.get(ADMISSION_KEY);
  const previous = stored ? await stored.json() : null;
  if (stored && (!previous || previous.version !== 1 || !/^\d{4}-\d{2}-\d{2}$/.test(previous.day || "") ||
      !Array.isArray(previous.entries) || previous.entries.length > DAILY_REPORTS || previous.entries.some(entry=>
        !entry || !UUID.test(entry.report_id || "") || !/^[0-9a-f]{64}$/.test(entry.subject || "") ||
        !/^[0-9a-f]{64}$/.test(entry.fingerprint || "") || !Number.isFinite(entry.at) || entry.at < 1)))
    throw new ReportError(503,"Report protection needs maintenance. Keep the draft and retry.");
  const entries = previous?.day === day ? previous.entries : [];
  if (entries.some(entry=>entry.report_id === report.report_id)) return;
  const matching = entries.find(entry=>entry.subject === subject && entry.fingerprint === fingerprint);
  if (matching) {
    const original = await env.REPORTS.get(`reports/${matching.report_id}.json`);
    const record = original && await original.json();
    if (record?.receipt) throw new ReportError(409,"This problem was already reported.","already_reported",0,
      {report_id:report.report_id,original_report_id:matching.report_id,issue_number:record.receipt.issue_number});
    throw rateLimit(120,"matching_report_pending");
  }
  const midnight = Date.parse(`${day}T00:00:00Z`) + 86400000;
  if (entries.length >= DAILY_REPORTS) throw rateLimit((midnight-now)/1000,"daily_report_limit");
  const network = entries.filter(entry=>entry.subject === subject);
  if (network.length >= DAILY_PER_NETWORK) throw rateLimit((midnight-now)/1000,"network_daily_limit");
  const lastNetwork = Math.max(0,...network.map(entry=>entry.at));
  if (lastNetwork && now-lastNetwork < NETWORK_COOLDOWN_MS) throw rateLimit((lastNetwork+NETWORK_COOLDOWN_MS-now)/1000);
  const lastGlobal = Math.max(0,...entries.map(entry=>entry.at));
  if (lastGlobal && now-lastGlobal < GLOBAL_COOLDOWN_MS) throw rateLimit((lastGlobal+GLOBAL_COOLDOWN_MS-now)/1000);
  const state = {version:1,day,entries:[...entries,{report_id:report.report_id,subject,fingerprint,at:now}]};
  let saved;
  try {
    saved = await env.REPORTS.put(ADMISSION_KEY,JSON.stringify(state),{onlyIf:stored ?
      {etagMatches:stored.etag} : {etagDoesNotMatch:"*"}});
  } catch {
    throw rateLimit(10,"protection_busy");
  }
  if (!saved) throw rateLimit(10,"protection_busy");
}

function plain(text) {
  return String(text).replaceAll("`", "ˋ").replaceAll("@", "@\u200b")
    .replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}
function issueBody(report, url, downloadKey) {
  const d = report.details;
  const sections = [["Item or file",d.input_item || "Not provided"],["Steps to reproduce",d.steps],["Expected result",d.expected],["Actual result",d.actual],
    ["Recent changes",d.changes || "Not provided"],
    ["Mods and manager",d.mod_setup],["Contact (optional)",d.contact || "Not provided"]]
    .map(([name,value]) => `### ${name}\n\n\`\`\`text\n${plain(value)}\n\`\`\``).join("\n\n");
  return `Private CDMW test report. Report ID: ${report.report_id}\n\n` +
    `Type: ${plain(d.problem_type || "Other / unsure")}\nTool: ${plain(d.tool)}\nFrequency: ${plain(d.frequency)}\nGame: ${plain(d.game_platform)} / ${plain(d.game_version)}\n` +
    `Worked before: ${plain(d.last_working || "Not sure")}\n` +
    `Without mods: ${plain(d.clean_test)}\nCDMW: ${plain(report.evidence.environment?.cdmw_version || "Unknown")}\n\n` +
    `${sections}\n\n[Review evidence and download the report](${url.origin}/reports/${report.report_id}#${downloadKey})\n\n` +
    `Evidence expires after 90 days. This private link grants access to this report: do not repost it publicly.\n\n` +
    `<!-- cdmw-report:${report.report_id} -->`;
}

async function github(env, path, options = {}) {
  const result = await fetch(`https://api.github.com${path}`, { ...options, headers: {
    "Authorization": `Bearer ${env.GITHUB_TOKEN}`, "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "CDMW-private-report-test",
    "Content-Type": "application/json",
  }, signal: AbortSignal.timeout(15000) });
  if (!result.ok) throw new ReportError(503, "The private inbox is unavailable. Keep the draft and retry.");
  return result.json();
}
async function findExistingIssue(env, reportId) {
  // List rather than search: newly created issues may not yet be in GitHub's search index.
  for (let page = 1; page <= 10; page++) {
    const issues = await github(env, `/repos/${REPOSITORY}/issues?state=all&per_page=100&page=${page}`);
    if (!Array.isArray(issues)) throw new ReportError(503, "The inbox returned an invalid response.");
    const match = issues.find(issue => !issue.pull_request && issue.body?.includes(`<!-- cdmw-report:${reportId} -->`));
    if (match) return match;
    if (issues.length < 100) return null;
  }
  throw new ReportError(503, "The test inbox needs maintenance before accepting more reports.");
}

async function submit(request, env, url) {
  if (!env.REPORTS || !env.GITHUB_TOKEN || !env.REPORT_TEST_TOKEN)
    throw new ReportError(503, "The private test receiver is not configured.");
  if (!await sameSecret(readToken(request), env.REPORT_TEST_TOKEN))
    throw new ReportError(401, "A private test access key is required.");
  await checkBurst(request,env);
  const {raw,report:input} = await boundedBody(request);
  const report = validateReport(input);
  const sha256 = await digest(raw);
  const objectKey = `reports/${report.report_id}.json`;
  let stored = await env.REPORTS.get(objectKey);
  let record, lock;
  if (stored) {
    record = await stored.json();
    // Earlier pilot records used parsed JSON. Preserve their receipt/retry contract.
    const expectedHash = record.report_json === undefined ? await digest(JSON.stringify(report)) : sha256;
    if (record.sha256 !== expectedHash) throw new ReportError(409, "This report ID belongs to different content. Collect a new report.","report_id_conflict");
    if (record.receipt) return response(200, record.receipt);
    if (record.lock_until > Date.now()) return response(202, {status:"pending",report_id:report.report_id}, {"Retry-After":"120"});
    await admitReport(request,env,report);
    record.lock_until = Date.now() + LOCK_MS;
    lock = await env.REPORTS.put(objectKey, JSON.stringify(record), {onlyIf:{etagMatches:stored.etag}});
  } else {
    await admitReport(request,env,report);
    const random = crypto.getRandomValues(new Uint8Array(32));
    record = { sha256, report_json:raw, created_at:Date.now(), lock_until:Date.now() + LOCK_MS,
      download_key:[...random].map(x => x.toString(16).padStart(2,"0")).join("") };
    lock = await env.REPORTS.put(objectKey, JSON.stringify(record), {onlyIf:{etagDoesNotMatch:"*"}});
  }
  if (!lock) return response(202, {status:"pending",report_id:report.report_id}, {"Retry-After":"120"});
  try {
    const repository = await github(env, `/repos/${REPOSITORY}`);
    if (repository.private !== true || repository.full_name !== REPOSITORY)
      throw new ReportError(503, "The receiver requires its private inbox. Delivery stopped.");
    const existing = await findExistingIssue(env, report.report_id);
    const issue = existing || await github(env, `/repos/${REPOSITORY}/issues`, {method:"POST",body:JSON.stringify({
      title:`[CDMW test] ${plain(report.details.summary)} (${report.report_id})`,
      body:issueBody(report,url,record.download_key),
    })});
    if (!Number.isInteger(issue.number) || issue.number < 1)
      throw new ReportError(503, "The inbox returned an invalid receipt.");
    record.receipt = {status:"accepted",report_id:report.report_id,issue_number:issue.number};
    record.lock_until = 0;
    const saved = await env.REPORTS.put(objectKey, JSON.stringify(record), {onlyIf:{etagMatches:lock.etag}});
    if (!saved) throw new ReportError(503, "Receipt storage failed. Keep the draft and retry.");
    return response(201, record.receipt);
  } catch (error) {
    // Keep the exact report for recovery. A retry checks GitHub before creating another issue.
    record.lock_until = 0;
    await env.REPORTS.put(objectKey, JSON.stringify(record), {onlyIf:{etagMatches:lock.etag}}).catch(() => {});
    throw error;
  }
}

function viewer() {
  const nonce = crypto.randomUUID();
  const html = `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Private CDMW report</title><style>body{font:16px system-ui;max-width:1000px;margin:36px auto;padding:0 20px;background:#13181e;color:#e5eaf0}button{padding:12px;font:inherit;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;border:1px solid #405060;padding:16px}img{max-width:100%;margin:16px 0}a{color:#86c6ff}</style>
<h1>Private CDMW report</h1><p>Evidence expires after 90 days. Keep this link private.</p><button id="load">Review report</button><p id="status"></p><div id="content"></div>
<script nonce="${nonce}">const key=location.hash.slice(1);history.replaceState(null,'',location.pathname);document.getElementById('load').onclick=async()=>{const status=document.getElementById('status');status.textContent='Loading…';try{const r=await fetch(location.pathname+'/download',{headers:{Authorization:'Bearer '+key}});if(!r.ok)throw Error('Report unavailable, expired, or access key missing.');const raw=await r.text();const data=JSON.parse(raw);const content=document.getElementById('content');content.replaceChildren();const a=document.createElement('a');a.textContent='Download report JSON';a.download='cdmw-report-'+data.report_id+'.json';a.href=URL.createObjectURL(new Blob([raw],{type:'application/json'}));content.append(a);const pre=document.createElement('pre');const text={...data,screenshots:data.screenshots.map(({data,...rest})=>rest)};pre.textContent=JSON.stringify(text,null,2);content.append(pre);for(const shot of data.screenshots){const img=document.createElement('img');img.alt=shot.name;img.src='data:image/jpeg;base64,'+shot.data;content.append(img)}status.textContent='Report loaded.'}catch(e){status.textContent=e.message}};</script></html>`;
  return new Response(html, {headers:{"Content-Type":"text/html; charset=utf-8","Cache-Control":"no-store",
    "Content-Security-Policy":`default-src 'none'; script-src 'nonce-${nonce}'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'`,
    "Referrer-Policy":"no-referrer","X-Content-Type-Options":"nosniff"}});
}

export default {
  async fetch(request, env) {
    try {
      const url = new URL(request.url);
      if (request.method === "GET" && url.pathname === "/health")
        return response(200,{service:"CDMW private reporting test",configured:Boolean(env.REPORTS && env.GITHUB_TOKEN && env.REPORT_TEST_TOKEN),schema_version:1,max_bytes:MAX_BYTES});
      if (request.method === "POST" && url.pathname === "/reports") return await submit(request,env,url);
      const match = /^\/reports\/([0-9a-f-]+)(\/download)?$/.exec(url.pathname);
      if (request.method === "GET" && match && UUID.test(match[1])) {
        if (!match[2]) return viewer();
        if (!/^[0-9a-f]{64}$/.test(readToken(request))) throw new ReportError(404,"Report unavailable.");
        if (!env.REPORTS) throw new ReportError(404,"Report unavailable.");
        const object = await env.REPORTS.get(`reports/${match[1]}.json`);
        const record = object && await object.json();
        if (!record?.receipt || Date.now() - record.created_at > 90 * 86400000 ||
            !await sameSecret(readToken(request),record.download_key))
          throw new ReportError(404,"Report unavailable.");
        return response(200,record.report_json ?? record.report,
          {"Content-Disposition":`attachment; filename="cdmw-report-${match[1]}.json"`}, record.report_json !== undefined);
      }
      return response(404,{error:"Not found."});
    } catch (error) {
      return response(error instanceof ReportError ? error.status : 503,
        {error:error instanceof ReportError ? error.message : "Delivery is not confirmed. Keep the draft and retry.",
         ...(error instanceof ReportError && error.code ? {code:error.code} : {}),
         ...(error instanceof ReportError && error.retryAfter ? {retry_after:error.retryAfter} : {}),
         ...(error instanceof ReportError ? error.extra : {})},
        error instanceof ReportError && error.retryAfter ? {"Retry-After":String(error.retryAfter)} : {});
    }
  },
};
