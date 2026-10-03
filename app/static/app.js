// ZHI.PAT Work – tương tác phía trình duyệt (không phụ thuộc thư viện ngoài)
(function () {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const NEED_NOTE = { revision: "Nhận xét cần sửa:", paused: "Lý do tạm dừng:", cancelled: "Lý do hủy:" };

  function toast(msg) {
    const el = document.createElement("div");
    el.className = "toast";
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  async function postJSON(url, data) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf, "X-Requested-With": "fetch" },
      body: JSON.stringify(data),
    });
    let body = {};
    try { body = await res.json(); } catch (e) { /* bỏ qua */ }
    return { ok: res.ok && body.ok !== false, body };
  }

  // Xác nhận trước khi gửi form nguy hiểm
  document.addEventListener("submit", (e) => {
    const msg = e.target.getAttribute("data-confirm");
    if (msg && !confirm(msg)) e.preventDefault();
  });

  // ---------------------------------------------------------- Kanban kéo-thả
  let dragged = null;
  document.querySelectorAll(".kcard[draggable]").forEach((card) => {
    card.addEventListener("dragstart", (e) => {
      dragged = card;
      card.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", card.dataset.id);
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("dragging");
      document.querySelectorAll(".kcol").forEach((c) => c.classList.remove("drop-ok"));
    });
  });

  document.querySelectorAll(".kcol").forEach((col) => {
    col.addEventListener("dragover", (e) => { e.preventDefault(); col.classList.add("drop-ok"); });
    col.addEventListener("dragleave", () => col.classList.remove("drop-ok"));
    col.addEventListener("drop", async (e) => {
      e.preventDefault();
      col.classList.remove("drop-ok");
      if (!dragged) return;
      const card = dragged;
      const from = card.closest(".kcol");
      const status = col.dataset.status;
      if (from === col) return;
      let note = "";
      if (NEED_NOTE[status]) {
        note = prompt(NEED_NOTE[status]) || "";
        if (!note.trim()) return;
      }
      col.querySelector(".kcards").prepend(card);
      const r = await postJSON(`/api/tasks/${card.dataset.id}/move`, { status, note });
      if (!r.ok) {
        from.querySelector(".kcards").prepend(card);
        toast(r.body.error || "Không chuyển được trạng thái.");
      } else {
        updateCounts();
      }
    });
  });

  function updateCounts() {
    document.querySelectorAll(".kcol").forEach((c) => {
      const n = c.querySelectorAll(".kcard").length;
      const el = c.querySelector(".kcount");
      if (el) el.textContent = n;
    });
  }

  // ---------------------------------------------------------- Sửa nhanh trên danh sách
  document.querySelectorAll("[data-quick]").forEach((el) => {
    el.dataset.prev = el.value;
    el.addEventListener("change", async () => {
      const id = el.dataset.task;
      const field = el.dataset.quick;
      let payload = { field, value: el.value };
      let r = await postJSON(`/api/tasks/${id}/quick`, payload);
      if (!r.ok && r.body.need_reason) {
        const reason = prompt("Lý do dời hạn:") || "";
        if (reason.trim()) {
          payload.reason = reason;
          r = await postJSON(`/api/tasks/${id}/quick`, payload);
        }
      }
      if (r.ok) {
        el.dataset.prev = el.value;
        toast("Đã lưu");
      } else {
        el.value = el.dataset.prev;
        toast(r.body.error || "Không lưu được.");
      }
    });
  });

  // ---------------------------------------------------------- Checklist
  document.querySelectorAll("form.cl-toggle input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", async () => {
      const form = cb.closest("form");
      const res = await fetch(form.action, {
        method: "POST", headers: { "X-CSRFToken": csrf, "X-Requested-With": "fetch" },
      });
      if (!res.ok) { cb.checked = !cb.checked; toast("Không cập nhật được."); return; }
      const data = await res.json();
      cb.closest(".cl-item").classList.toggle("done", data.done);
      const counter = document.getElementById("cl-count");
      if (counter) counter.textContent = `${data.count}/${data.total}`;
    });
  });

  // ---------------------------------------------------------- Nhắc tên @ trong bình luận
  const box = document.getElementById("comment-box");
  const names = document.getElementById("mention-names");
  if (box && names) {
    names.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      const pos = box.selectionStart;
      const before = box.value.slice(0, pos).replace(/@[^@\s]*$/, "");
      box.value = before + "@" + b.dataset.name + " " + box.value.slice(pos);
      box.focus();
      names.hidden = true;
    }));
    box.addEventListener("input", () => {
      const m = box.value.slice(0, box.selectionStart).match(/@([^@\n]{0,20})$/);
      if (!m) { names.hidden = true; return; }
      const q = m[1].toLowerCase();
      let shown = 0;
      names.querySelectorAll("button").forEach((b) => {
        const ok = b.dataset.name.toLowerCase().includes(q) && shown < 6;
        b.hidden = !ok;
        if (ok) shown++;
      });
      names.hidden = shown === 0;
    });
  }

  // Ghi chú bắt buộc trên các nút chuyển trạng thái cần lý do
  document.querySelectorAll("form.status-form").forEach((f) => {
    f.addEventListener("submit", (e) => {
      const status = e.submitter?.value;
      if (!NEED_NOTE[status]) return;
      const note = prompt(NEED_NOTE[status]) || "";
      if (!note.trim()) { e.preventDefault(); return; }
      f.querySelector("input[name=note]").value = note;
      const hidden = f.querySelector("input[name=status]");
      if (hidden) hidden.value = status;
    });
  });
})();
