/* ============================================================
   Voice Studio - Minimal Client Application
   Claude-inspired calm, quiet, and responsive behavior.
   ============================================================ */

document.addEventListener("DOMContentLoaded", () => {
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

  themeToggle.addEventListener("click", () => {
    applyTheme(state.theme === "light" ? "dark" : "light");
  });
  applyTheme(state.theme);

  // ============================================================
  // 2. Load & Render Saved Voices
  // ============================================================
  async function loadVoices() {
    try {
      const res = await fetch("/api/voices");
      const data = await res.json();
      state.voices = data.voices || [];
      renderVoices();
    } catch (e) {
      voicesListContainer.innerHTML = '<div class="quiet-text">Unable to load voices.</div>';
    }
  }

  function renderVoices() {
    if (!state.voices || state.voices.length === 0) {
      voicesListContainer.innerHTML = '<div class="quiet-text">No saved voices. Click "Add a voice" above to begin.</div>';
      updateGenerateState();
      return;
    }

    // Default select first voice if none selected
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
      selectBtn.textContent = isSelected ? "Selected" : "Select";
      selectBtn.disabled = isSelected;
      selectBtn.addEventListener("click", () => {
        state.selectedVoice = voice;
        renderVoices();
      });

      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "text-link danger-link";
      deleteBtn.textContent = "Delete";
      deleteBtn.addEventListener("click", async () => {
        if (!confirm(`Delete voice ${voice.name}?`)) return;
        try {
          const dRes = await fetch(`/api/voices/${encodeURIComponent(voice.name)}`, { method: "DELETE" });
          if (dRes.ok) {
            if (state.selectedVoice && state.selectedVoice.name === voice.name) {
              state.selectedVoice = null;
            }
            loadVoices();
          }
        } catch (e) {
          alert("Could not delete voice: " + e.message);
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
    addVoiceToggleBtn.textContent = isVisible ? "Add a voice" : "Close";
    if (!isVisible) voiceNameInput.focus();
  });

  cancelAddVoiceBtn.addEventListener("click", () => {
    addVoicePanel.style.display = "none";
    addVoiceToggleBtn.textContent = "Add a voice";
    resetAddVoiceForm();
  });

  voiceDropArea.addEventListener("click", () => voiceFileInput.click());

  voiceFileInput.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) {
      state.audioBlob = file;
      dropText.textContent = `${file.name} (${(file.size / 1024).toFixed(0)} KB)`;
      if (!voiceNameInput.value) {
        voiceNameInput.value = file.name.replace(/\.[^/.]+$/, "").replace(/[^a-zA-Z0-9_-]/g, "");
      }
    }
  });

  // Microphone recording
  micRecordBtn.addEventListener("click", async () => {
    if (state.mediaRecorder && state.mediaRecorder.state === "recording") {
      state.mediaRecorder.stop();
      micRecordBtn.textContent = "Record from microphone";
      recordStatus.textContent = "Recording stopped.";
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
        dropText.textContent = `Recorded voice sample (${(state.audioBlob.size / 1024).toFixed(0)} KB)`;
        stream.getTracks().forEach(t => t.stop());
      };

      state.mediaRecorder.start();
      micRecordBtn.textContent = "Stop recording";
      recordStatus.textContent = "Recording... speak naturally for 10-15 seconds.";
    } catch (err) {
      recordStatus.textContent = "Microphone access denied or unavailable.";
    }
  });

  saveNewVoiceBtn.addEventListener("click", async () => {
    const name = voiceNameInput.value.trim();
    if (!name) {
      addVoiceStatus.textContent = "Please provide a name for this voice.";
      addVoiceStatus.style.color = "var(--danger)";
      return;
    }
    if (!state.audioBlob) {
      addVoiceStatus.textContent = "Please upload or record an audio sample.";
      addVoiceStatus.style.color = "var(--danger)";
      return;
    }

    saveNewVoiceBtn.disabled = true;
    saveNewVoiceBtn.textContent = "Saving...";
    addVoiceStatus.textContent = "Processing audio sample...";
    addVoiceStatus.style.color = "var(--text-muted)";

    const formData = new FormData();
    formData.append("name", name);
    formData.append("file", state.audioBlob, `${name}.wav`);

    try {
      const res = await fetch("/api/voices/add", { method: "POST", body: formData });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Could not save voice sample.");
      }
      addVoiceStatus.textContent = `Saved ${name}.`;
      addVoiceStatus.style.color = "var(--text-main)";
      setTimeout(() => {
        addVoicePanel.style.display = "none";
        addVoiceToggleBtn.textContent = "Add a voice";
        resetAddVoiceForm();
        loadVoices();
      }, 1200);
    } catch (e) {
      addVoiceStatus.textContent = e.message;
      addVoiceStatus.style.color = "var(--danger)";
    } finally {
      saveNewVoiceBtn.disabled = false;
      saveNewVoiceBtn.textContent = "Save voice";
    }
  });

  function resetAddVoiceForm() {
    voiceNameInput.value = "";
    voiceFileInput.value = "";
    state.audioBlob = null;
    dropText.textContent = "Click to choose an audio file (5 to 20 seconds works best)";
    recordStatus.textContent = "";
    addVoiceStatus.textContent = "";
  }

  // ============================================================
  // 4. Text Input & Language Detection
  // ============================================================
  let detectTimeout = null;
  textInput.addEventListener("input", () => {
    const len = textInput.value.length;
    charCount.textContent = `${len} character${len === 1 ? "" : "s"}`;
    updateGenerateState();

    clearTimeout(detectTimeout);
    detectTimeout = setTimeout(checkTextDetection, 300);
  });

  async function checkTextDetection() {
    const text = textInput.value.trim();
    if (!text) {
      detectedLang.textContent = "Detected: Hindi (Devanagari)";
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
        detectedLang.textContent = `Detected: ${data.type_label}`;
      }
    } catch (e) {}
  }

  // ============================================================
  // 5. Style Pills
  // ============================================================
  stylePills.forEach(pill => {
    pill.addEventListener("click", () => {
      stylePills.forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      state.selectedStyle = pill.getAttribute("data-style");
    });
  });

  function updateGenerateState() {
    const hasText = textInput.value.trim().length > 0;
    const hasVoice = state.selectedVoice !== null;
    generateBtn.disabled = !(hasText && hasVoice) || state.isGenerating;
  }

  // ============================================================
  // 6. Speech Synthesis Generation
  // ============================================================
  generateBtn.addEventListener("click", generateSpeech);

  async function generateSpeech() {
    const text = textInput.value.trim();
    if (!text || !state.selectedVoice) return;

    state.isGenerating = true;
    updateGenerateState();

    generateBtn.style.display = "none";
    progressContainer.style.display = "block";
    statusNotification.textContent = "";
    progressBarFill.style.width = "4%";
    progressStatusText.textContent = "Initializing...";

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
        const err = await response.json();
        throw new Error(err.detail || "Unable to complete speech synthesis.");
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
            progressStatusText.textContent = `Generating 1 of ${data.total_chunks}...`;
          } else if (eventType === "chunk") {
            const pct = Math.min(95, Math.round(((data.chunk_index + 1) / data.total_chunks) * 100));
            progressBarFill.style.width = `${pct}%`;
            const elapsed = ((performance.now() - startTime) / 1000).toFixed(0);
            progressStatusText.textContent = `Generating. ${pct}%. About ${elapsed}s elapsed.`;
          } else if (eventType === "complete") {
            progressBarFill.style.width = "100%";
            progressStatusText.textContent = "Ready.";

            // Show Result
            resultSection.style.display = "block";
            resultAudioPlayer.src = data.audio_url;
            downloadResultLink.href = data.audio_url;
            downloadResultLink.download = data.filename;

            resultAudioPlayer.play().catch(() => {});
            loadHistory();
          } else if (eventType === "cancelled") {
            progressStatusText.textContent = "Generation stopped.";
          } else if (eventType === "error") {
            throw new Error(data.error || "Generation error.");
          }
        }
      }
    } catch (err) {
      if (err.name !== "AbortError") {
        statusNotification.textContent = "Unable to generate speech. Please try again in a moment.";
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
      const data = await res.json();
      renderHistory(data.items || []);
    } catch (e) {
      historyContainer.innerHTML = '<div class="quiet-text">Unable to load history.</div>';
    }
  }

  function renderHistory(items) {
    if (!items || items.length === 0) {
      historyContainer.innerHTML = '<div class="quiet-text">No previous generations found.</div>';
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
          <audio controls src="${item.audio_url}" style="height: 32px; width: 70%;"></audio>
          <div>
            <a class="text-link" href="${item.audio_url}" download="${item.filename}">Download</a>
            <button class="text-link danger-link delete-hist-btn" data-filename="${item.filename}" style="margin-left: 12px;">Delete</button>
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
        } catch (e) {}
      });
    });
  }

  refreshHistoryBtn.addEventListener("click", loadHistory);

  // ============================================================
  // Initialization
  // ============================================================
  loadVoices();
  loadHistory();
});
