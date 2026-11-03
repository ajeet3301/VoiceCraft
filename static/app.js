/* ============================================================
   Voice Studio - Complete Client Application
   Calm, quiet, and responsive behavior.
   Full support for Studio, Batch Clips, History, Settings & Bot.
   Connects to messages.js for all user-facing wording.
   ============================================================ */

document.addEventListener("DOMContentLoaded", () => {
  const M = window.MESSAGES || {};

  // --- State ---
  const state = {
    theme: localStorage.getItem("voice_studio_theme") || "light",
    activeTab: "tab-studio",
    voices: [],
    selectedVoice: null,
    selectedStyle: "natural",
    isGenerating: false,
    mediaRecorder: null,
    recordedChunks: [],
    audioBlob: null,
    activeController: null,
    batchItems: [
      { id: "1", text: "Welcome to Voice Studio. Natural voice synthesis made simple." },
      { id: "2", text: "Each sentence is synthesized directly in memory with seamless transitions." }
    ],
    isBatchGenerating: false,
    batchController: null
  };

  // --- Header & Navigation Elements ---
  const themeToggle = document.getElementById("theme-toggle");
  const navTabs = document.querySelectorAll(".nav-tab");
  const tabPanes = document.querySelectorAll(".tab-pane");

  // --- Studio Elements ---
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

  // --- Batch Elements ---
  const batchItemsContainer = document.getElementById("batch-items-container");
  const batchAddBtn = document.getElementById("batch-add-btn");
  const batchPasteLinesBtn = document.getElementById("batch-paste-lines-btn");
  const batchGenerateBtn = document.getElementById("batch-generate-btn");
  const batchStopBtn = document.getElementById("batch-stop-btn");
  const batchDownloadZip = document.getElementById("batch-download-zip");
  const batchStatusMsg = document.getElementById("batch-status-msg");

  // --- History Elements ---
  const historyContainer = document.getElementById("history-container");
  const refreshHistoryBtn = document.getElementById("refresh-history-btn");

  // --- Settings & Telegram Elements ---
  const cfgHost = document.getElementById("cfg-host");
  const cfgPort = document.getElementById("cfg-port");
  const cfgToken = document.getElementById("cfg-token");
  const tokenEyeBtn = document.getElementById("token-eye-btn");
  const cfgAllowedIds = document.getElementById("cfg-allowed-ids");
  const cfgMaxWords = document.getElementById("cfg-max-words");
  const cfgMaxUsers = document.getElementById("cfg-max-users");
  const saveEnvBtn = document.getElementById("save-env-btn");
  const saveEnvStatus = document.getElementById("save-env-status");

  const tgStatusText = document.getElementById("tg-status-text");
  const startTgBtn = document.getElementById("start-tg-btn");
  const restartTgBtn = document.getElementById("restart-tg-btn");
  const stopTgBtn = document.getElementById("stop-tg-btn");
  const refreshTgBtn = document.getElementById("refresh-tg-btn");

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
  // 2. Tab Navigation
  // ============================================================
  navTabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const targetId = tab.getAttribute("data-tab");
      navTabs.forEach(t => {
        t.classList.remove("active");
        t.setAttribute("aria-selected", "false");
      });
      tabPanes.forEach(pane => {
        pane.style.display = "none";
        pane.classList.remove("active");
      });

      tab.classList.add("active");
      tab.setAttribute("aria-selected", "true");
      const activePane = document.getElementById(targetId);
      if (activePane) {
        activePane.style.display = "block";
        activePane.classList.add("active");
      }
      state.activeTab = targetId;

      if (targetId === "tab-history") {
        loadHistory();
      } else if (targetId === "tab-settings") {
        loadTelegramSettings();
        checkTelegramStatus();
      } else if (targetId === "tab-batch") {
        renderBatchItems();
      }
    });
  });

  // ============================================================
  // 3. Load & Render Saved Voices
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
  // 4. Add Voice Panel & Audio Recording
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
  // 5. Studio Text Input & Language Detection
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
  // 7. Batch Clips Manager
  // ============================================================
  function renderBatchItems() {
    if (!batchItemsContainer) return;
    batchItemsContainer.innerHTML = "";

    if (state.batchItems.length === 0) {
      batchItemsContainer.innerHTML = `<div class="quiet-text">${M.batchEmpty || "No clips added."}</div>`;
      return;
    }

    state.batchItems.forEach((item, index) => {
      const card = document.createElement("div");
      card.className = "batch-card-item";
      card.id = `batch-card-${item.id}`;
      card.innerHTML = `
        <div class="batch-card-header">
          <span>Clip ${index + 1}</span>
          <button class="text-link danger-link remove-batch-item-btn" data-id="${item.id}" type="button">Remove</button>
        </div>
        <textarea class="textarea batch-item-text" data-id="${item.id}" rows="2" placeholder="Text for this clip...">${item.text}</textarea>
        <div class="batch-player-box" id="batch-player-${item.id}" style="display: none; margin-top: 6px;">
          <audio controls style="width: 100%; height: 32px;"></audio>
        </div>
      `;
      batchItemsContainer.appendChild(card);
    });

    document.querySelectorAll(".remove-batch-item-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-id");
        state.batchItems = state.batchItems.filter(i => i.id !== id);
        renderBatchItems();
      });
    });

    document.querySelectorAll(".batch-item-text").forEach(txt => {
      txt.addEventListener("input", () => {
        const id = txt.getAttribute("data-id");
        const found = state.batchItems.find(i => i.id === id);
        if (found) found.text = txt.value;
      });
    });
  }

  if (batchAddBtn) {
    batchAddBtn.addEventListener("click", () => {
      const nextId = String(Date.now());
      state.batchItems.push({ id: nextId, text: "" });
      renderBatchItems();
    });
  }

  if (batchPasteLinesBtn) {
    batchPasteLinesBtn.addEventListener("click", () => {
      const promptText = M.batchPastePrompt || "Paste your text below (one clip per line):";
      const linesStr = prompt(promptText);
      if (!linesStr) return;
      const lines = linesStr.split("\n").map(l => l.trim()).filter(l => l.length > 0);
      if (lines.length === 0) return;

      state.batchItems = lines.map((text, idx) => ({ id: String(Date.now() + idx), text }));
      renderBatchItems();
    });
  }

  if (batchGenerateBtn) {
    batchGenerateBtn.addEventListener("click", async () => {
      if (state.batchItems.length === 0) {
        alert("Please add at least one clip.");
        return;
      }
      if (!state.selectedVoice) {
        alert(M.errorNoVoice || "Please select a voice first.");
        return;
      }

      state.isBatchGenerating = true;
      batchGenerateBtn.disabled = true;
      batchGenerateBtn.style.display = "none";
      if (batchStopBtn) batchStopBtn.style.display = "inline-flex";
      if (batchDownloadZip) batchDownloadZip.style.display = "none";
      if (batchStatusMsg) {
        batchStatusMsg.textContent = "Starting batch synthesis...";
        batchStatusMsg.style.color = "var(--text-muted)";
      }

      state.batchController = new AbortController();

      const payload = {
        items: state.batchItems,
        voice_path: state.selectedVoice.path,
        language: "auto",
        style: state.selectedStyle
      };

      try {
        const res = await fetch("/api/batch/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: state.batchController.signal
        });

        if (!res.ok) throw new Error("Batch generation request failed.");

        const reader = res.body.getReader();
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

            for (const line of block.split("\n")) {
              if (line.startsWith("event:")) eventType = line.slice(6).trim();
              if (line.startsWith("data:")) dataStr = line.slice(5).trim();
            }

            if (!dataStr) continue;
            const data = JSON.parse(dataStr);

            if (eventType === "clip_done") {
              const playerBox = document.getElementById(`batch-player-${data.item_id}`);
              if (playerBox) {
                playerBox.style.display = "block";
                const aud = playerBox.querySelector("audio");
                if (aud) aud.src = data.audio_url;
              }
              if (batchStatusMsg) batchStatusMsg.textContent = `Completed clip #${data.index + 1}...`;
            } else if (eventType === "batch_complete") {
              if (batchDownloadZip) {
                batchDownloadZip.href = data.zip_url;
                batchDownloadZip.style.display = "inline-block";
              }
              if (batchStatusMsg) {
                batchStatusMsg.textContent = "Batch generation complete.";
                batchStatusMsg.style.color = "var(--text-main)";
              }
            }
          }
        }
      } catch (err) {
        if (err.name !== "AbortError" && batchStatusMsg) {
          batchStatusMsg.textContent = "Batch generation error.";
          batchStatusMsg.style.color = "var(--danger)";
        }
      } finally {
        state.isBatchGenerating = false;
        batchGenerateBtn.disabled = false;
        batchGenerateBtn.style.display = "inline-flex";
        if (batchStopBtn) batchStopBtn.style.display = "none";
      }
    });
  }

  if (batchStopBtn) {
    batchStopBtn.addEventListener("click", () => {
      if (state.batchController) state.batchController.abort();
      fetch("/api/generate/stop", { method: "POST" });
    });
  }

  // ============================================================
  // 8. Recent Generation History
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
    items.slice(0, 15).forEach(item => {
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

  if (refreshHistoryBtn) {
    refreshHistoryBtn.addEventListener("click", loadHistory);
  }

  // ============================================================
  // 9. Settings & Telegram Bot Controller
  // ============================================================
  async function loadTelegramSettings() {
    try {
      const res = await fetch("/api/telegram/settings");
      if (res.ok) {
        const data = await res.json();
        if (cfgHost && data.host) cfgHost.value = data.host;
        if (cfgPort && data.port) cfgPort.value = data.port;
        if (cfgToken && data.token) cfgToken.value = data.token;
        if (cfgAllowedIds && data.allowed_ids !== undefined) cfgAllowedIds.value = data.allowed_ids;
        if (cfgMaxWords && data.max_words) cfgMaxWords.value = data.max_words;
        if (cfgMaxUsers && data.max_users !== undefined) cfgMaxUsers.value = data.max_users;
      }
    } catch {}
  }

  if (tokenEyeBtn) {
    tokenEyeBtn.addEventListener("click", () => {
      if (cfgToken.type === "password") {
        cfgToken.type = "text";
        tokenEyeBtn.textContent = "Hide";
      } else {
        cfgToken.type = "password";
        tokenEyeBtn.textContent = "Show";
      }
    });
  }

  if (saveEnvBtn) {
    saveEnvBtn.addEventListener("click", async () => {
      saveEnvBtn.disabled = true;
      saveEnvBtn.textContent = M.savingSettingsBtn || "Saving...";
      saveEnvStatus.textContent = "";

      try {
        const res = await fetch("/api/telegram/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            host: cfgHost ? cfgHost.value.trim() : "127.0.0.1",
            port: cfgPort ? cfgPort.value.trim() : "7860",
            token: cfgToken ? cfgToken.value.trim() : "",
            allowed_ids: cfgAllowedIds ? cfgAllowedIds.value.trim() : "",
            max_words: cfgMaxWords ? parseInt(cfgMaxWords.value) || 60 : 60,
            max_users: cfgMaxUsers ? parseInt(cfgMaxUsers.value) || 1 : 1
          })
        });

        if (res.ok) {
          saveEnvStatus.textContent = M.settingsSavedNotice || "Settings saved successfully.";
          saveEnvStatus.style.color = "var(--text-main)";
        } else {
          saveEnvStatus.textContent = M.settingsError || "Error saving settings.";
          saveEnvStatus.style.color = "var(--danger)";
        }
      } catch {
        saveEnvStatus.textContent = M.settingsError || "Error saving settings.";
        saveEnvStatus.style.color = "var(--danger)";
      } finally {
        saveEnvBtn.disabled = false;
        saveEnvBtn.textContent = M.saveSettingsBtn || "Save settings";
        setTimeout(() => { saveEnvStatus.textContent = ""; }, 4000);
      }
    });
  }

  async function checkTelegramStatus() {
    if (!tgStatusText) return;
    try {
      const res = await fetch("/api/telegram/status");
      if (res.ok) {
        const data = await res.json();
        tgStatusText.textContent = data.status;
        if (data.status && data.status.toUpperCase().includes("RUNNING")) {
          tgStatusText.classList.add("running");
        } else {
          tgStatusText.classList.remove("running");
        }
      }
    } catch {
      tgStatusText.textContent = "Offline";
      tgStatusText.classList.remove("running");
    }
  }

  if (startTgBtn) {
    startTgBtn.addEventListener("click", async () => {
      startTgBtn.disabled = true;
      try {
        await fetch("/api/telegram/start", { method: "POST" });
        setTimeout(checkTelegramStatus, 1500);
      } finally {
        startTgBtn.disabled = false;
      }
    });
  }

  if (restartTgBtn) {
    restartTgBtn.addEventListener("click", async () => {
      restartTgBtn.disabled = true;
      restartTgBtn.textContent = "Restarting...";
      try {
        await fetch("/api/telegram/restart", { method: "POST" });
        setTimeout(checkTelegramStatus, 2000);
      } finally {
        restartTgBtn.disabled = false;
        restartTgBtn.textContent = M.restartBotBtn || "Restart bot";
      }
    });
  }

  if (stopTgBtn) {
    stopTgBtn.addEventListener("click", async () => {
      stopTgBtn.disabled = true;
      try {
        await fetch("/api/telegram/stop", { method: "POST" });
        setTimeout(checkTelegramStatus, 1000);
      } finally {
        stopTgBtn.disabled = false;
      }
    });
  }

  if (refreshTgBtn) {
    refreshTgBtn.addEventListener("click", checkTelegramStatus);
  }

  // ============================================================
  // 10. Initialization
  // ============================================================
  loadVoices();
  loadHistory();
  renderBatchItems();
});
