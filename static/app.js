/* ============================================================
   Voice Studio - Minimal Client Application
   Calm, quiet, and responsive behavior.
   Connects to messages.js for all user-facing wording.
   ============================================================ */

document.addEventListener("DOMContentLoaded", () => {
  const M = window.MESSAGES || {};

  // --- State ---
  const state = {
    theme: localStorage.getItem("voice_studio_theme") || "light",
    voices: [],
    selectedVoice: null,
    selectedStyle: "natural",
    isGenerating: false,
    mediaRecorder: null,
    recordedChunks: [],
    audioBlob: null,
    activeController: null,
  };

  // --- Element References ---
  const themeToggle = document.getElementById("theme-toggle");
  const voicesListContainer = document.getElementById("voices-list");
  const addVoiceToggleBtn = document.getElementById("add-voice-toggle-btn");
  const addVoicePanel = document.getElementById("add-voice-panel");
  const voiceNameInput = document.getElementById("voice-name-input");
  const voiceDropArea = document.getElementById("voice-drop-area");
  const voiceFileInput = document.getElementById("voice-file-input");
  const dropText = document.getElementById("drop-text");
  const micRecordBtn = document.getElementById("mic-record-btn");
  const recordStatus = document.getElementById("record-status");
  const saveNewVoiceBtn = document.getElementById("save-new-voice-btn");
  const cancelAddVoiceBtn = document.getElementById("cancel-add-voice-btn");
  const addVoiceStatus = document.getElementById("add-voice-status");

  const textInput = document.getElementById("text-input");
  const charCount = document.getElementById("char-count");
  const detectedLang = document.getElementById("detected-lang");
  const stylePills = document.querySelectorAll("#style-pills .pill");

  const generateBtn = document.getElementById("generate-btn");
  const progressContainer = document.getElementById("progress-container");
  const progressBarFill = document.getElementById("progress-bar-fill");
  const progressStatusText = document.getElementById("progress-status-text");
  const stopGenerationBtn = document.getElementById("stop-generation-btn");
  const statusNotification = document.getElementById("status-notification");

  const resultSection = document.getElementById("result-section");
  const resultAudioPlayer = document.getElementById("result-audio-player");
  const downloadResultLink = document.getElementById("download-result-link");
  const regenerateBtn = document.getElementById("regenerate-btn");

  const historyContainer = document.getElementById("history-container");
  const refreshHistoryBtn = document.getElementById("refresh-history-btn");

  // ============================================================
  // 1. Theme Management
  // ============================================================
  function applyTheme(theme) {
    state.theme = theme;
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("voice_studio_theme", theme);
  }

  if (themeToggle) {
    themeToggle.addEventListener("click", () => {
      applyTheme(state.theme === "light" ? "dark" : "light");
    });
    applyTheme(state.theme);
  }

  // ============================================================
  // 2. Load & Render Saved Voices
  // ============================================================
  async function loadVoices() {
    try {
      const res = await fetch("/api/voices");
      if (!res.ok) throw new Error();
      const data = await res.json();
      state.voices = data.voices || [];
      renderVoices();
    } catch {
      voicesListContainer.innerHTML = `<div class="quiet-text">${M.loadingVoices || "Unable to load voices."}</div>`;
    }
  }

  function renderVoices() {
    if (!state.voices || state.voices.length === 0) {
      voicesListContainer.innerHTML = `<div class="quiet-text">${M.noVoices || "No saved voices yet."}</div>`;
      updateGenerateState();
      return;
    }

    if (!state.selectedVoice && state.voices.length > 0) {
      state.selectedVoice = state.voices[0];
    }

    voicesListContainer.innerHTML = "";
    state.voices.forEach(voice => {
      const isSelected = state.selectedVoice && state.selectedVoice.name.toLowerCase() === voice.name.toLowerCase();
      const row = document.createElement("div");
      row.className = `voice-row ${isSelected ? "selected" : ""}`;

      const info = document.createElement("div");
      info.className = "voice-info";
      info.innerHTML = `<span class="voice-name">${voice.name}</span> <span class="quiet-text">(${voice.duration_s}s)</span>`;

      const actions = document.createElement("div");
      actions.className = "voice-actions";

      const selectBtn = document.createElement("button");
      selectBtn.type = "button";
      selectBtn.className = "text-link";
      selectBtn.textContent = isSelected ? (M.voiceSelected || "Selected") : (M.selectVoiceAction || "Select");
      selectBtn.disabled = isSelected;
      selectBtn.addEventListener("click", () => {
        state.selectedVoice = voice;
        renderVoices();
      });

      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "text-link danger-link";
      deleteBtn.textContent = M.deleteVoiceAction || "Delete";
      deleteBtn.addEventListener("click", async () => {
        const confirmMsg = M.confirmDeleteVoice ? M.confirmDeleteVoice(voice.name) : `Delete voice ${voice.name}?`;
        if (!confirm(confirmMsg)) return;
        try {
          const dRes = await fetch(`/api/voices/${encodeURIComponent(voice.name)}`, { method: "DELETE" });
          if (dRes.ok) {
            if (state.selectedVoice && state.selectedVoice.name === voice.name) {
              state.selectedVoice = null;
            }
            loadVoices();
          } else {
            alert(M.voiceDeleteError || "Unable to delete voice.");
          }
        } catch {
          alert(M.voiceDeleteError || "Unable to delete voice.");
        }
      });

      actions.appendChild(selectBtn);
      actions.appendChild(deleteBtn);
      row.appendChild(info);
      row.appendChild(actions);
      voicesListContainer.appendChild(row);
    });

    updateGenerateState();
  }

  // ============================================================
  // 3. Add Voice Panel & Audio Recording
  // ============================================================
  addVoiceToggleBtn.addEventListener("click", () => {
    const isVisible = addVoicePanel.style.display !== "none";
    addVoicePanel.style.display = isVisible ? "none" : "block";
    addVoiceToggleBtn.textContent = isVisible ? (M.addVoiceLink || "Add a voice") : (M.closeAddVoiceLink || "Close");
    if (!isVisible) voiceNameInput.focus();
  });

  cancelAddVoiceBtn.addEventListener("click", () => {
    addVoicePanel.style.display = "none";
    addVoiceToggleBtn.textContent = M.addVoiceLink || "Add a voice";
    resetAddVoiceForm();
  });

  voiceDropArea.addEventListener("click", () => voiceFileInput.click());
  voiceDropArea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      voiceFileInput.click();
    }
  });

  voiceFileInput.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) {
      state.audioBlob = file;
      const sizeKb = (file.size / 1024).toFixed(0);
      dropText.textContent = `${file.name} (${sizeKb} KB)`;
      if (!voiceNameInput.value) {
        voiceNameInput.value = file.name.replace(/\.[^/.]+$/, "").replace(/[^a-zA-Z0-9_-]/g, "");
      }
    }
  });

  // Microphone recording
  micRecordBtn.addEventListener("click", async () => {
    if (state.mediaRecorder && state.mediaRecorder.state === "recording") {
      state.mediaRecorder.stop();
      micRecordBtn.textContent = M.recordMicBtn || "Record with microphone";
      recordStatus.textContent = M.recordingStopped || "Recording finished.";
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      state.recordedChunks = [];
      state.mediaRecorder = new MediaRecorder(stream);

      state.mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) state.recordedChunks.push(e.data);
      };

      state.mediaRecorder.onstop = () => {
        state.audioBlob = new Blob(state.recordedChunks, { type: "audio/wav" });
        const sizeKb = (state.audioBlob.size / 1024).toFixed(0);
        dropText.textContent = M.dropTextRecorded ? M.dropTextRecorded(sizeKb) : `Recorded voice (${sizeKb} KB)`;
        stream.getTracks().forEach(t => t.stop());
      };

      state.mediaRecorder.start();
      micRecordBtn.textContent = M.stopMicBtn || "Stop recording";
      recordStatus.textContent = M.recordingStatus || "Recording. Speak naturally for 10 to 15 seconds.";
    } catch {
      recordStatus.textContent = M.micUnavailable || "Microphone access was denied or is unsupported.";
    }
  });

  saveNewVoiceBtn.addEventListener("click", async () => {
    const name = voiceNameInput.value.trim();
    if (!name) {
      addVoiceStatus.textContent = M.nameRequired || "Please enter a name for this voice.";
      addVoiceStatus.style.color = "var(--danger)";
      return;
    }
    if (!state.audioBlob) {
      addVoiceStatus.textContent = M.sampleRequired || "Please select or record an audio sample.";
      addVoiceStatus.style.color = "var(--danger)";
      return;
    }

    saveNewVoiceBtn.disabled = true;
    saveNewVoiceBtn.textContent = M.savingVoiceBtn || "Saving...";
    addVoiceStatus.textContent = "Processing audio sample...";
    addVoiceStatus.style.color = "var(--text-muted)";

    const formData = new FormData();
    formData.append("name", name);
    formData.append("file", state.audioBlob, `${name}.wav`);

    try {
      const res = await fetch("/api/voices/add", { method: "POST", body: formData });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Could not save voice sample.");
      }
      addVoiceStatus.textContent = M.voiceSavedNotice ? M.voiceSavedNotice(name) : `Saved voice "${name}".`;
      addVoiceStatus.style.color = "var(--text-main)";
      setTimeout(() => {
        addVoicePanel.style.display = "none";
        addVoiceToggleBtn.textContent = M.addVoiceLink || "Add a voice";
        resetAddVoiceForm();
        loadVoices();
      }, 1000);
    } catch (e) {
      addVoiceStatus.textContent = e.message;
      addVoiceStatus.style.color = "var(--danger)";
    } finally {
      saveNewVoiceBtn.disabled = false;
      saveNewVoiceBtn.textContent = M.saveVoiceBtn || "Save voice";
    }
  });

  function resetAddVoiceForm() {
    voiceNameInput.value = "";
    voiceFileInput.value = "";
    state.audioBlob = null;
    dropText.textContent = M.dropTextDefault || "Choose an audio file (5 to 20 seconds works best)";
    recordStatus.textContent = "";
    addVoiceStatus.textContent = "";
  }

  // ============================================================
  // 4. Text Input & Language Detection
  // ============================================================
  let detectTimeout = null;
  textInput.addEventListener("input", () => {
    const len = textInput.value.length;
    charCount.textContent = M.charCount ? M.charCount(len) : `${len} characters`;
    updateGenerateState();

    clearTimeout(detectTimeout);
    detectTimeout = setTimeout(checkTextDetection, 300);
  });

  async function checkTextDetection() {
    const text = textInput.value.trim();
    if (!text) {
      detectedLang.textContent = `${M.detectedLangPrefix || "Detected language: "}${M.detectedDefault || "Hindi"}`;
      return;
    }
    try {
      const res = await fetch("/api/detect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text })
      });
      if (res.ok) {
        const data = await res.json();
        detectedLang.textContent = `${M.detectedLangPrefix || "Detected language: "}${data.type_label}`;
      }
    } catch {}
  }

  // ============================================================
  // 5. Speaking Style Selection
  // ============================================================
  stylePills.forEach(pill => {
    pill.addEventListener("click", () => {
      stylePills.forEach(p => {
        p.classList.remove("active");
        p.setAttribute("aria-checked", "false");
      });
      pill.classList.add("active");
      pill.setAttribute("aria-checked", "true");
      state.selectedStyle = pill.getAttribute("data-style");
    });
  });

  function updateGenerateState() {
    const hasText = textInput.value.trim().length > 0;
    const hasVoice = state.selectedVoice !== null;
    generateBtn.disabled = !(hasText && hasVoice) || state.isGenerating;
  }

  // ============================================================
  // 6. Speech Generation (SSE Streaming)
  // ============================================================
  generateBtn.addEventListener("click", generateSpeech);

  async function generateSpeech() {
    const text = textInput.value.trim();
    if (!text) {
      statusNotification.textContent = M.errorEmptyText || "Please enter some text before generating.";
      statusNotification.style.color = "var(--danger)";
      return;
    }
    if (!state.selectedVoice) {
      statusNotification.textContent = M.errorNoVoice || "Please select a voice before generating.";
      statusNotification.style.color = "var(--danger)";
      return;
    }

    state.isGenerating = true;
    updateGenerateState();

    generateBtn.style.display = "none";
    progressContainer.style.display = "block";
    statusNotification.textContent = "";
    progressBarFill.style.width = "4%";
    progressStatusText.textContent = M.generatingInit || "Starting generation...";

    const startTime = performance.now();
    state.activeController = new AbortController();

    const payload = {
      text: text,
      voice_path: state.selectedVoice.path,
      style: state.selectedStyle,
      stream_playback: false
    };

    try {
      const response = await fetch("/api/generate/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: state.activeController.signal
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || M.errorGeneric);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop();

        for (const block of lines) {
          if (!block.trim()) continue;
          let eventType = "message";
          let dataStr = "";

          const blockLines = block.split("\n");
          for (const line of blockLines) {
            if (line.startsWith("event:")) eventType = line.slice(6).trim();
            if (line.startsWith("data:")) dataStr = line.slice(5).trim();
          }

          if (!dataStr) continue;
          const data = JSON.parse(dataStr);

          if (eventType === "start") {
            const total = data.total_chunks || 1;
            progressStatusText.textContent = M.generatingChunk ? M.generatingChunk(1, total) : `Generating 1 of ${total}...`;
          } else if (eventType === "chunk") {
            const pct = Math.min(95, Math.round(((data.chunk_index + 1) / data.total_chunks) * 100));
            progressBarFill.style.width = `${pct}%`;
            const elapsed = Math.round((performance.now() - startTime) / 1000);
            progressStatusText.textContent = M.generatingProgress ? M.generatingProgress(pct, elapsed) : `Generating. ${pct}%. About ${elapsed}s elapsed.`;
          } else if (eventType === "complete") {
            progressBarFill.style.width = "100%";
            progressStatusText.textContent = M.generatingReady || "Ready.";

            // Show Result
            resultSection.style.display = "block";
            resultAudioPlayer.src = data.audio_url;
            downloadResultLink.href = data.audio_url;
            downloadResultLink.download = data.filename;

            resultAudioPlayer.play().catch(() => {});
            loadHistory();
          } else if (eventType === "cancelled") {
            progressStatusText.textContent = M.stoppedStatus || "Generation stopped.";
          } else if (eventType === "error") {
            throw new Error(data.error || M.errorGeneric);
          }
        }
      }
    } catch (err) {
      if (err.name !== "AbortError") {
        statusNotification.textContent = err.message || M.errorGeneric;
        statusNotification.style.color = "var(--danger)";
      }
    } finally {
      state.isGenerating = false;
      generateBtn.style.display = "block";
      progressContainer.style.display = "none";
      updateGenerateState();
    }
  }

  stopGenerationBtn.addEventListener("click", () => {
    if (state.activeController) {
      state.activeController.abort();
    }
    fetch("/api/generate/stop", { method: "POST" });
  });

  regenerateBtn.addEventListener("click", () => {
    generateSpeech();
  });

  // ============================================================
  // 7. Recent Generation History
  // ============================================================
  async function loadHistory() {
    try {
      const res = await fetch("/api/history");
      if (!res.ok) throw new Error();
      const data = await res.json();
      renderHistory(data.items || []);
    } catch {
      historyContainer.innerHTML = `<div class="quiet-text">${M.noHistory || "No recent recordings."}</div>`;
    }
  }

  function renderHistory(items) {
    if (!items || items.length === 0) {
      historyContainer.innerHTML = `<div class="quiet-text">${M.noHistory || "No recent recordings."}</div>`;
      return;
    }

    historyContainer.innerHTML = "";
    items.slice(0, 8).forEach(item => {
      const div = document.createElement("div");
      div.className = "history-item";
      div.innerHTML = `
        <div class="history-item-meta">
          <span>${item.filename}</span>
          <span>${item.created_at} • ${item.duration_s}s</span>
        </div>
        <div class="history-actions">
          <audio controls src="${item.audio_url}"></audio>
          <div class="history-links">
            <a class="text-link" href="${item.audio_url}" download="${item.filename}">${M.downloadAction || "Download"}</a>
            <button class="text-link danger-link delete-hist-btn" data-filename="${item.filename}">${M.deleteVoiceAction || "Delete"}</button>
          </div>
        </div>
      `;
      historyContainer.appendChild(div);
    });

    document.querySelectorAll(".delete-hist-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const fname = btn.getAttribute("data-filename");
        try {
          const res = await fetch(`/api/history/${encodeURIComponent(fname)}`, { method: "DELETE" });
          if (res.ok) loadHistory();
        } catch {}
      });
    });
  }

  refreshHistoryBtn.addEventListener("click", loadHistory);

  // ============================================================
  // 8. Initialization
  // ============================================================
  loadVoices();
  loadHistory();
});
