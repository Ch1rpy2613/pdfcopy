/* global pdfjsLib */

const SCALE = 1.35;
const NARROW_FIXTURE = "13-narrow-column.pdf";

const state = {
  pdfDoc: null,
  page: 1,
  bytes: null,
  name: "document.pdf",
  result: null,
  mode: "fix",
  drag: null,
  selection: null,
};

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

const $ = (id) => document.getElementById(id);

function setHasDoc(on) {
  document.body.classList.toggle("has-doc", on);
  const chip = $("doc-chip");
  const empty = $("empty-sheet");
  const stack = document.querySelector(".page-stack");
  if (empty) empty.hidden = on;
  if (stack) stack.hidden = !on;
  if (on) {
    chip.hidden = false;
    chip.textContent = state.name;
  } else {
    chip.hidden = true;
    chip.textContent = "";
  }
}

function setBodyMode(mode) {
  document.body.classList.remove("mode-fix", "mode-naive", "mode-chrome");
  document.body.classList.add(`mode-${mode}`);
}

async function loadCorpus() {
  const res = await fetch("/api/corpus");
  const data = await res.json();
  const select = $("corpus");
  for (const item of data.fixtures || []) {
    const option = document.createElement("option");
    option.value = item.file;
    option.textContent = item.title;
    select.appendChild(option);
  }
}

async function loadFixture(name) {
  const res = await fetch(`/api/corpus/${encodeURIComponent(name)}`);
  await ingestBytes(new Uint8Array(await res.arrayBuffer()), name);
  const select = $("corpus");
  if (select) select.value = name;
}

async function ingestBytes(bytes, name) {
  state.bytes = bytes;
  state.name = name || "document.pdf";
  state.page = 1;
  state.selection = null;
  state.pdfDoc = await pdfjsLib.getDocument({ data: bytes.slice(0) }).promise;
  $("status").hidden = true;
  setHasDoc(true);
  await renderPage();
  await extractCurrent();
}

async function renderPage() {
  if (!state.pdfDoc) return;
  const page = await state.pdfDoc.getPage(state.page);
  const canvas = $("page");
  const context = canvas.getContext("2d");
  const viewport = page.getViewport({ scale: SCALE });
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  await page.render({ canvasContext: context, viewport }).promise;
  $("page-label").textContent = `${state.page} / ${state.pdfDoc.numPages}`;
  const svg = $("mesh");
  svg.setAttribute("viewBox", `0 0 ${canvas.width} ${canvas.height}`);
  svg.setAttribute("width", canvas.width);
  svg.setAttribute("height", canvas.height);
  drawSelection();
}

async function extractCurrent() {
  if (!state.bytes) return;
  const body = new FormData();
  body.append("file", new Blob([state.bytes], { type: "application/pdf" }), state.name);
  const res = await fetch("/api/extract", { method: "POST", body });
  state.result = await res.json();
  showText();
  drawSelection();
  if (state.result.warnings && state.result.warnings.length) {
    $("status").hidden = false;
    $("status").textContent = state.result.warnings.join(" ");
  }
}

function currentOverlayPage() {
  const pages = (state.result && state.result.overlay && state.result.overlay.pages) || [];
  return pages.find((item) => item.index === state.page - 1) || pages[state.page - 1] || null;
}

function pageHeight() {
  const overlay = currentOverlayPage();
  return overlay && overlay.height ? overlay.height : 792;
}

function showText() {
  const paste = $("paste");
  const title = $("paste-title");
  paste.classList.remove("naive", "empty-paste");
  if (!state.result) {
    paste.textContent = "划过折行，贴出一句。";
    paste.classList.add("empty-paste");
    title.textContent = "贴出来";
    return;
  }
  if (state.selection && state.selection.plain) {
    paste.textContent = state.selection.plain;
    title.textContent = "贴出来";
    return;
  }
  if (state.mode === "naive") {
    paste.textContent = state.result.naive_text || "";
    paste.classList.add("naive");
    title.textContent = "一般阅读器";
  } else if (state.mode === "chrome") {
    paste.textContent = state.result.reader_text || state.result.text || "";
    title.textContent = "修复后全页";
  } else {
    const pageText = (state.result.pages || [])[state.page - 1];
    paste.textContent = pageText || state.result.text || "";
    title.textContent = "贴出来";
  }
}

function boxesOverlap(a, b) {
  return !(a[2] <= b[0] || b[2] <= a[0] || a[3] <= b[1] || b[3] <= a[1]);
}

function svgPoint(event) {
  const svg = $("mesh");
  const rect = svg.getBoundingClientRect();
  const vb = svg.viewBox.baseVal;
  const x = ((event.clientX - rect.left) * vb.width) / Math.max(rect.width, 1);
  const y = ((event.clientY - rect.top) * vb.height) / Math.max(rect.height, 1);
  return { x, y };
}

function svgToPdf(x, y) {
  return { x: x / SCALE, y: pageHeight() - y / SCALE };
}

function pdfBBoxFromSvg(a, b) {
  const p1 = svgToPdf(a.x, a.y);
  const p2 = svgToPdf(b.x, b.y);
  return [
    Math.min(p1.x, p2.x),
    Math.min(p1.y, p2.y),
    Math.max(p1.x, p2.x),
    Math.max(p1.y, p2.y),
  ];
}

function pdfToSvgBox(bbox) {
  const [x0, y0, x1, y1] = bbox;
  const h = pageHeight();
  return {
    x: x0 * SCALE,
    y: (h - y1) * SCALE,
    w: (x1 - x0) * SCALE,
    h: (y1 - y0) * SCALE,
  };
}

function sentencesOnPage() {
  const overlay = currentOverlayPage();
  return (overlay && overlay.sentences) || [];
}

function hitSentences(bbox) {
  const hit = [];
  for (const sentence of sentencesOnPage()) {
    const glyphs = sentence.glyphs || [];
    const overlap =
      glyphs.some((glyph) => boxesOverlap(glyph.bbox, bbox)) ||
      (sentence.bbox && boxesOverlap(sentence.bbox, bbox));
    if (overlap) hit.push(sentence);
  }
  return hit;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function sentencesPlain(sentences) {
  const parts = [];
  let prev = null;
  for (const sentence of sentences) {
    if (
      prev &&
      (sentence.blockId !== prev.blockId ||
        sentence.role === "table" ||
        sentence.role === "code" ||
        sentence.role === "l")
    ) {
      parts.push(sentence.blockId !== prev.blockId ? "\n\n" : "\n");
    } else if (parts.length) {
      parts.push(" ");
    }
    parts.push(sentence.text);
    prev = sentence;
  }
  return parts.join("").trim();
}

function sentencesHtml(sentences) {
  if (!sentences.length) return "";
  const groups = [];
  for (const sentence of sentences) {
    if (groups.length && groups[groups.length - 1][0].blockId === sentence.blockId) {
      groups[groups.length - 1].push(sentence);
    } else {
      groups.push([sentence]);
    }
  }
  return groups
    .map((group) => {
      const role = group[0].role;
      const texts = group.map((item) => escapeHtml(item.text));
      if (role === "h") return `<h1>${texts[0]}</h1>`;
      if (role === "l") return `<ul>${texts.map((text) => `<li>${text}</li>`).join("")}</ul>`;
      if (role === "table") {
        return `<table>${texts.map((text) => `<tr><td>${text}</td></tr>`).join("")}</table>`;
      }
      if (role === "code") return `<pre>${texts.join("\n")}</pre>`;
      return `<p>${texts.join(" ")}</p>`;
    })
    .join("");
}

function setSelection(sentences) {
  if (!sentences.length) {
    state.selection = null;
    showText();
    drawSelection();
    return;
  }
  state.selection = {
    sentences,
    plain: sentencesPlain(sentences),
    html: sentencesHtml(sentences),
  };
  showText();
  drawSelection();
}

function drawSelection() {
  const svg = $("mesh");
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const ns = "http://www.w3.org/2000/svg";
  if (state.drag) {
    const box = {
      x: Math.min(state.drag.start.x, state.drag.now.x),
      y: Math.min(state.drag.start.y, state.drag.now.y),
      w: Math.abs(state.drag.now.x - state.drag.start.x),
      h: Math.abs(state.drag.now.y - state.drag.start.y),
    };
    const marquee = document.createElementNS(ns, "rect");
    marquee.setAttribute("x", box.x);
    marquee.setAttribute("y", box.y);
    marquee.setAttribute("width", box.w);
    marquee.setAttribute("height", box.h);
    marquee.setAttribute("class", "mesh-marquee");
    svg.appendChild(marquee);
  }
  const sentences = (state.selection && state.selection.sentences) || [];
  for (const sentence of sentences) {
    for (const glyph of sentence.glyphs || []) {
      const box = pdfToSvgBox(glyph.bbox);
      if (box.w < 0.4 || box.h < 0.4) continue;
      const rect = document.createElementNS(ns, "rect");
      rect.setAttribute("x", box.x);
      rect.setAttribute("y", box.y);
      rect.setAttribute("width", box.w);
      rect.setAttribute("height", box.h);
      rect.setAttribute("class", "mesh-glyph");
      svg.appendChild(rect);
    }
  }
}

function onMeshDown(event) {
  if (!state.result) return;
  event.preventDefault();
  const point = svgPoint(event);
  state.drag = { start: point, now: point };
  setSelection([]);
}

function onMeshMove(event) {
  if (!state.drag) return;
  state.drag.now = svgPoint(event);
  const bbox = pdfBBoxFromSvg(state.drag.start, state.drag.now);
  state.selection = {
    sentences: hitSentences(bbox),
    plain: "",
    html: "",
  };
  if (state.selection.sentences.length) {
    state.selection.plain = sentencesPlain(state.selection.sentences);
    state.selection.html = sentencesHtml(state.selection.sentences);
  }
  showText();
  drawSelection();
}

function onMeshUp(event) {
  if (!state.drag) return;
  state.drag.now = svgPoint(event);
  const bbox = pdfBBoxFromSvg(state.drag.start, state.drag.now);
  state.drag = null;
  setSelection(hitSentences(bbox));
}

$("file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  await ingestBytes(new Uint8Array(await file.arrayBuffer()), file.name);
});

document.addEventListener("dragover", (event) => event.preventDefault());
document.addEventListener("drop", async (event) => {
  event.preventDefault();
  const file = event.dataTransfer.files[0];
  if (!file) return;
  await ingestBytes(new Uint8Array(await file.arrayBuffer()), file.name);
});

$("corpus").addEventListener("change", async (event) => {
  const name = event.target.value;
  if (!name) return;
  await loadFixture(name);
});

$("btn-try-narrow").addEventListener("click", async () => {
  await loadFixture(NARROW_FIXTURE);
});

$("prev").addEventListener("click", async () => {
  if (!state.pdfDoc || state.page <= 1) return;
  state.page -= 1;
  state.selection = null;
  await renderPage();
  showText();
});

$("next").addEventListener("click", async () => {
  if (!state.pdfDoc || state.page >= state.pdfDoc.numPages) return;
  state.page += 1;
  state.selection = null;
  await renderPage();
  showText();
});

function setMode(mode) {
  state.mode = mode;
  state.selection = null;
  setBodyMode(mode);
  $("btn-fix").classList.toggle("on", mode === "fix");
  $("btn-naive").classList.toggle("on", mode === "naive");
  $("btn-chrome").classList.toggle("on", mode === "chrome");
  showText();
  drawSelection();
}

$("btn-fix").addEventListener("click", () => setMode("fix"));
$("btn-naive").addEventListener("click", () => setMode("naive"));
$("btn-chrome").addEventListener("click", () => setMode("chrome"));

async function writeClipboard(plain, html) {
  if (navigator.clipboard && window.ClipboardItem) {
    const item = new ClipboardItem({
      "text/plain": new Blob([plain], { type: "text/plain" }),
      "text/html": new Blob([html || `<p>${escapeHtml(plain)}</p>`], {
        type: "text/html",
      }),
    });
    await navigator.clipboard.write([item]);
    return;
  }
  await navigator.clipboard.writeText(plain);
}

$("btn-copy").addEventListener("click", async () => {
  const plain = (state.selection && state.selection.plain) || $("paste").textContent;
  if (!plain || $("paste").classList.contains("empty-paste")) return;
  const html = (state.selection && state.selection.html) || `<p>${escapeHtml(plain)}</p>`;
  await writeClipboard(plain, html);
  const btn = $("btn-copy");
  btn.textContent = "已复制";
  setTimeout(() => {
    btn.textContent = "复制";
  }, 1200);
});

document.addEventListener("copy", (event) => {
  if (!state.selection || !state.selection.plain) return;
  event.preventDefault();
  event.clipboardData.setData("text/plain", state.selection.plain);
  event.clipboardData.setData("text/html", state.selection.html);
});

$("btn-download").addEventListener("click", async () => {
  if (!state.bytes) return;
  const body = new FormData();
  body.append("file", new Blob([state.bytes], { type: "application/pdf" }), state.name);
  const res = await fetch("/api/fix", { method: "POST", body });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = state.name.replace(/\.pdf$/i, "") + ".fixed.pdf";
  link.click();
  URL.revokeObjectURL(url);
});

const mesh = $("mesh");
mesh.addEventListener("mousedown", onMeshDown);
window.addEventListener("mousemove", onMeshMove);
window.addEventListener("mouseup", onMeshUp);

setBodyMode("fix");
setHasDoc(false);
loadCorpus();
