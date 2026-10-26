/* 서버 API. 화면 코드는 fetch를 직접 쓰지 않고 이 파일만 쓴다 (오류 처리를 한 곳에서). */

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(method, url, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(url, options);
  } catch (err) {
    throw new ApiError("서버에 연결할 수 없습니다. 서버(python app.py)가 켜져 있는지 확인하세요.", 0);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map(d => d.msg).join(", ") : data.detail;
    throw new ApiError(detail || `요청 실패 (HTTP ${res.status})`, res.status);
  }
  return data;
}

const get = url => request("GET", url);
const post = (url, body = {}) => request("POST", url, body);
const P = pid => `/api/projects/${pid}`;

export const api = {
  config: () => get("/api/config"),
  listProjects: () => get("/api/projects"),
  createProject: name => post("/api/projects", { name }),
  getProject: pid => get(P(pid)),
  patchProject: (pid, body) => request("PATCH", P(pid), body),
  deleteProject: pid => request("DELETE", P(pid)),
  deleteClip: (pid, cid) => request("DELETE", `${P(pid)}/clips/${cid}`),
  analyze: (pid, profile) => post(`${P(pid)}/analyze`, { profile }),
  getAnalysis: pid => get(`${P(pid)}/analysis`),
  getPlan: pid => get(`${P(pid)}/plan`),
  putPlan: (pid, body) => request("PUT", `${P(pid)}/plan`, body),
  patchLines: (pid, changes) => request("PATCH", `${P(pid)}/plan/lines`, { changes }),
  select: (pid, body) => post(`${P(pid)}/select`, body),
  revise: (pid, body) => post(`${P(pid)}/revise`, body),
  render: (pid, quality) => post(`${P(pid)}/render`, { quality }),
  metrics: pid => get(`${P(pid)}/metrics`),
  job: jid => get(`/api/jobs/${jid}`),
  cancelJob: jid => post(`/api/jobs/${jid}/cancel`),

  // 업로드는 진행률을 보여 주려고 XMLHttpRequest를 쓴다 (fetch는 업로드 진행률이 없음)
  uploadClip(pid, file, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${P(pid)}/clips`);
      xhr.upload.onprogress = e => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
      xhr.onload = () => {
        let data = {};
        try { data = JSON.parse(xhr.responseText); } catch (e) { /* 빈 응답 */ }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new ApiError(data.detail || `업로드 실패 (HTTP ${xhr.status})`, xhr.status));
      };
      xhr.onerror = () => reject(new ApiError("업로드 중 연결이 끊겼습니다.", 0));
      const form = new FormData();
      form.append("files", file);
      xhr.send(form);
    });
  },
};

/* 작업이 끝날 때까지 상태를 묻는다. onUpdate(job)는 매번 호출. 끝난 작업을 돌려준다. */
export async function pollJob(jobId, onUpdate, interval = 700) {
  for (;;) {
    const job = await api.job(jobId);
    if (onUpdate) onUpdate(job);
    if (["done", "failed", "canceled"].includes(job.status)) return job;
    await new Promise(r => setTimeout(r, interval));
  }
}
