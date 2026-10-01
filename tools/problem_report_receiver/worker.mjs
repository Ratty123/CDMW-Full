// Private test receiver. Credentials belong in Worker secrets, never in CDMW.
const REPOSITORY = "Ratty123/CDMW-Reports";
const MAX_BYTES = 8 * 1024 * 1024;
const LOCK_MS = 120000;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const encoder = new TextEncoder();

class ReportError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
function response(status, payload, headers = {}) {
  return new Response(JSON.stringify(payload), { status, headers: {
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
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); }
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
    if (bytes.length !== shot.size || bytes.charCodeAt(0) !== 255 || bytes.charCodeAt(1) !== 216 ||
        bytes.charCodeAt(2) !== 255 || bytes.charCodeAt(bytes.length - 2) !== 255 ||
        bytes.charCodeAt(bytes.length - 1) !== 217)
      throw new ReportError(400, "Screenshots must be normalized JPEG images.");
  }
  return report;
}

function plain(text) {
  return String(text).replaceAll("`", "ˋ").replaceAll("@", "@\u200b")
    .replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}
function issueBody(report, url, downloadKey) {
  const d = report.details;
  const sections = [["Steps to reproduce",d.steps],["Expected result",d.expected],["Actual result",d.actual],
    ["Mods and manager",d.mod_setup],["Contact (optional)",d.contact || "Not provided"]]
    .map(([name,value]) => `### ${name}\n\n\`\`\`text\n${plain(value)}\n\`\`\``).join("\n\n");
  return `Private CDMW test report. Report ID: ${report.report_id}\n\n` +
    `Tool: ${plain(d.tool)}\nFrequency: ${plain(d.frequency)}\nGame: ${plain(d.game_platform)} / ${plain(d.game_version)}\n` +
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
  const report = validateReport(await boundedBody(request));
  const body = JSON.stringify(report);
  const sha256 = await digest(body);
  const objectKey = `reports/${report.report_id}.json`;
  let stored = await env.REPORTS.get(objectKey);
  let record, lock;
  if (stored) {
    record = await stored.json();
    if (record.sha256 !== sha256) throw new ReportError(409, "This report ID belongs to different content. Collect a new report.");
    if (record.receipt) return response(200, record.receipt);
    if (record.lock_until > Date.now()) return response(202, {status:"pending",report_id:report.report_id}, {"Retry-After":"120"});
    record.lock_until = Date.now() + LOCK_MS;
    lock = await env.REPORTS.put(objectKey, JSON.stringify(record), {onlyIf:{etagMatches:stored.etag}});
  } else {
    const random = crypto.getRandomValues(new Uint8Array(32));
    record = { sha256, report, created_at:Date.now(), lock_until:Date.now() + LOCK_MS,
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
<script nonce="${nonce}">const key=location.hash.slice(1);history.replaceState(null,'',location.pathname);document.getElementById('load').onclick=async()=>{const status=document.getElementById('status');status.textContent='Loading…';try{const r=await fetch(location.pathname+'/download',{headers:{Authorization:'Bearer '+key}});if(!r.ok)throw Error('Report unavailable, expired, or access key missing.');const data=await r.json();const content=document.getElementById('content');content.replaceChildren();const a=document.createElement('a');a.textContent='Download report JSON';a.download='cdmw-report-'+data.report_id+'.json';a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));content.append(a);const pre=document.createElement('pre');const text={...data,screenshots:data.screenshots.map(({data,...rest})=>rest)};pre.textContent=JSON.stringify(text,null,2);content.append(pre);for(const shot of data.screenshots){const img=document.createElement('img');img.alt=shot.name;img.src='data:image/jpeg;base64,'+shot.data;content.append(img)}status.textContent='Report loaded.'}catch(e){status.textContent=e.message}};</script></html>`;
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
        return response(200,record.report,{"Content-Disposition":`attachment; filename="cdmw-report-${match[1]}.json"`});
      }
      return response(404,{error:"Not found."});
    } catch (error) {
      return response(error instanceof ReportError ? error.status : 503,
        {error:error instanceof ReportError ? error.message : "Delivery is not confirmed. Keep the draft and retry."});
    }
  },
};
