let selectedChunk = null;
let lastVerifiedClaimIds = [];

const el = (id) => document.getElementById(id);

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(detail.detail || response.statusText);
  }
  return response.json();
}

function projectId() {
  return el("projectId").value.trim() || "default";
}

function setStatus(text) {
  el("status").textContent = text;
}

async function createProject() {
  const id = projectId();
  await request("/api/projects", {
    method: "POST",
    body: JSON.stringify({ project_id: id, name: id }),
  });
  await refreshDocuments();
  setStatus(`Project ${id} ready`);
}

async function refreshDocuments() {
  const docs = await request(`/api/projects/${encodeURIComponent(projectId())}/documents`);
  const list = el("documentList");
  list.innerHTML = "";
  if (!docs.length) {
    list.innerHTML = '<div class="meta">No documents yet.</div>';
    return;
  }
  for (const doc of docs) {
    const item = document.createElement("div");
    item.className = "doc-item";
    item.innerHTML = `
      <strong>${escapeHtml(doc.filename)}</strong>
      <div class="meta">${doc.status} · ${doc.id}</div>
      <button class="secondary">Parse</button>
    `;
    item.querySelector("button").addEventListener("click", async () => {
      setStatus(`Parsing ${doc.filename}...`);
      const parsed = await request(`/api/documents/${doc.id}/parse`, {
        method: "POST",
        body: JSON.stringify({ project_id: projectId() }),
      });
      setStatus(`Parsed ${parsed.pages} pages, ${parsed.chunks} chunks`);
      await refreshDocuments();
    });
    list.appendChild(item);
  }
}

async function importDocument() {
  const filePath = el("filePath").value.trim();
  if (!filePath) return;
  setStatus("Importing...");
  await request("/api/documents/import", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId(), file_path: filePath }),
  });
  await refreshDocuments();
  setStatus("Imported");
}

async function runSearch() {
  const query = el("searchQuery").value.trim();
  if (!query) return;
  setStatus("Searching...");
  const results = await request("/api/search", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId(), query, top_n: 12 }),
  });
  renderResults(results);
  setStatus(`${results.length} results`);
}

function renderResults(results) {
  const root = el("results");
  root.innerHTML = "";
  if (!results.length) {
    root.innerHTML = '<div class="empty">No chunks matched.</div>';
    return;
  }
  for (const chunk of results) {
    const item = document.createElement("button");
    item.className = "result-item secondary";
    item.innerHTML = `
      <div class="meta">${chunk.document_id} · page ${chunk.page_start} · ${chunk.id}</div>
      <div class="result-text">${escapeHtml(chunk.text)}</div>
    `;
    item.addEventListener("click", () => selectChunk(chunk, item));
    root.appendChild(item);
  }
}

function selectChunk(chunk, item) {
  selectedChunk = chunk;
  document.querySelectorAll(".result-item").forEach((node) => node.classList.remove("selected"));
  item.classList.add("selected");
  el("quoteText").value = chunk.text.slice(0, 500);
  el("viewerMeta").textContent = `Selected page ${chunk.page_start}`;
  showPage(chunk.document_id, chunk.page_start, chunk.bbox_json ? JSON.parse(chunk.bbox_json) : null);
}

async function verifyClaim() {
  if (!selectedChunk) {
    setStatus("Select a search result first");
    return;
  }
  const claimText = el("claimText").value.trim();
  const quoteText = el("quoteText").value.trim();
  if (!claimText || !quoteText) return;

  const result = await request("/api/verify/run", {
    method: "POST",
    body: JSON.stringify({
      project_id: projectId(),
      claims: [
        {
          text: claimText,
          citations: [{ chunk_id: selectedChunk.id, quote: quoteText, source_uri: selectedChunk.source_uri }],
        },
      ],
    }),
  });
  el("verifyOutput").textContent = JSON.stringify(result, null, 2);
  lastVerifiedClaimIds = result.claims.filter((claim) => claim.status === "verified").map((claim) => claim.id);
  const citation = result.claims[0]?.citations?.[0];
  if (citation?.bbox_json) {
    showPage(citation.document_id, JSON.parse(citation.bbox_json).page, JSON.parse(citation.bbox_json));
  }
  setStatus(result.claims[0]?.status === "verified" ? "Claim verified" : "Claim blocked");
}

async function renderMemo() {
  const result = await request("/api/memo/render", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId(), claim_ids: lastVerifiedClaimIds.length ? lastVerifiedClaimIds : null }),
  });
  el("memoOutput").textContent = result.markdown;
  setStatus("Memo rendered");
}

function showPage(documentId, pageNumber, bbox) {
  const viewer = el("viewer");
  viewer.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.className = "page-wrap";
  const img = document.createElement("img");
  img.src = `/api/documents/${documentId}/pages/${pageNumber}/render?project_id=${encodeURIComponent(projectId())}`;
  wrap.appendChild(img);
  if (bbox) {
    const highlight = document.createElement("div");
    highlight.className = "highlight";
    highlight.style.left = `${bbox.x0 * 100}%`;
    highlight.style.top = `${bbox.y0 * 100}%`;
    highlight.style.width = `${(bbox.x1 - bbox.x0) * 100}%`;
    highlight.style.height = `${(bbox.y1 - bbox.y0) * 100}%`;
    wrap.appendChild(highlight);
  }
  viewer.appendChild(wrap);
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

el("createProject").addEventListener("click", () => createProject().catch(reportError));
el("importDoc").addEventListener("click", () => importDocument().catch(reportError));
el("runSearch").addEventListener("click", () => runSearch().catch(reportError));
el("verifyClaim").addEventListener("click", () => verifyClaim().catch(reportError));
el("renderMemo").addEventListener("click", () => renderMemo().catch(reportError));

function reportError(error) {
  setStatus(error.message);
}

refreshDocuments().catch(reportError);
