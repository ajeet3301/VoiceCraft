/* ============================================================
   VoiceCraft Studio Modern Client Application (app.js)
   ============================================================ */

document.addEventListener("DOMContentLoaded", () => {
  // --- Global State ---
  const state = {
    theme: localStorage.getItem("voicecraft_theme") || "dark",
    language: localStorage.getItem("voicecraft_language") || "en",
    hasVoice: false,
    isGenerating: false,
    activeAudioQueue: [],
    queueIndex: -1,
    audioChunksData: [],
    mediaRecorder: null,
    audioBlob: null,
    recordedChunks: [],
    recordTimer: null,
    recordSeconds: 0,
    currentController: null,
    batchItems: [
      { id: "1", text: "Welcome to VoiceCraft. Voice cloning made simple and fast." },
      { id: "2", text: "Each sentence is synthesized directly in memory without cluttering your disk." },
      { id: "3", text: "Generate as many voice clips as you need with a single click." }
    ]
  };

  // --- Element Selectors ---
  const themeToggle = document.getElementById("theme-toggle");
  const themeIcon = document.getElementById("theme-icon");
  const tabButtons = document.querySelectorAll(".tab-btn");
  const tabPanes = document.querySelectorAll(".tab-pane");

  const systemStatusBadge = document.getElementById("system-status-badge");
  const statusDot = document.getElementById("status-dot");
  const statusText = document.getElementById("status-text");
  const deviceName = document.getElementById("device-name");

  // Voice Elements
  const voiceDropzone = document.getElementById("voice-dropzone");
  const voiceFileInput = document.getElementById("voice-file-input");
  const dropzonePrompt = document.getElementById("dropzone-prompt");
  const audioPreviewBox = document.getElementById("audio-preview-box");
  const voicePreviewAudio = document.getElementById("voice-preview-audio");
  const previewFilename = document.getElementById("preview-filename");
  const previewDuration = document.getElementById("preview-duration");
  const durationWarning = document.getElementById("duration-warning");
  const voicePill = document.getElementById("voice-pill");
  const voiceDot = document.getElementById("voice-dot");
  const voicePillText = document.getElementById("voice-pill-text");
  const micRecordBtn = document.getElementById("mic-record-btn");
  const micIcon = document.getElementById("mic-icon");
  const micLabel = document.getElementById("mic-label");
  const saveVoiceBtn = document.getElementById("save-voice-btn");

  // Text Elements
  const textInput = document.getElementById("text-input");
  const wordCount = document.getElementById("word-count");
  const charCount = document.getElementById("char-count");
  const languageSelect = document.getElementById("language-select");
  const presetSelect = document.getElementById("preset-select");

  // Sliders & Advanced
  const exaggerationSlider = document.getElementById("exaggeration-slider");
  const exaggerationVal = document.getElementById("exaggeration-val");
  const cfgSlider = document.getElementById("cfg-slider");
  const cfgVal = document.getElementById("cfg-val");
  const tempSlider = document.getElementById("temp-slider");
  const tempVal = document.getElementById("temp-val");
  const seedInput = document.getElementById("seed-input");
  const randomizeSeedBtn = document.getElementById("randomize-seed-btn");
  const pauseSlider = document.getElementById("pause-slider");
  const pauseVal = document.getElementById("pause-val");
  const crossfadeSlider = document.getElementById("crossfade-slider");
  const crossfadeVal = document.getElementById("crossfade-val");
  const streamChk = document.getElementById("stream-chk");
  const keepPartialChk = document.getElementById("keep-partial-chk");
  const resetDefaultsBtn = document.getElementById("reset-defaults-btn");
  const saveCustomPresetBtn = document.getElementById("save-custom-preset-btn");

  // Generate & Stop Actions
  const generateBtn = document.getElementById("generate-btn");
  const stopBtn = document.getElementById("stop-btn");

  // Output Elements
  const outputBadge = document.getElementById("output-badge");
  const outputIdle = document.getElementById("output-idle");
  const liveStreamArea = document.getElementById("live-stream-area");
  const streamStatusTitle = document.getElementById("stream-status-title");
  const streamTimer = document.getElementById("stream-timer");
  const progressBar = document.getElementById("progress-bar");
  const streamSub = document.getElementById("stream-sub");
  const activeSentenceCard = document.getElementById("active-sentence-card");
  const activeSentenceIdx = document.getElementById("active-sentence-idx");
  const activeSentenceText = document.getElementById("active-sentence-text");
  const liveAudioPlayer = document.getElementById("live-audio-player");

  const finalOutputArea = document.getElementById("final-output-area");
  const finalFilename = document.getElementById("final-filename");
  const finalDuration = document.getElementById("final-duration");
  const finalGenTime = document.getElementById("final-gen-time");
  const masterAudioPlayer = document.getElementById("master-audio-player");
  const downloadWavBtn = document.getElementById("download-wav-btn");
  const openFolderBtn = document.getElementById("open-folder-btn");
  const regenerateBtn = document.getElementById("regenerate-btn");

  // Batch Elements
  const batchItemsContainer = document.getElementById("batch-items-container");
  const batchAddBtn = document.getElementById("batch-add-btn");
  const batchPasteLinesBtn = document.getElementById("batch-paste-lines-btn");
  const batchLangSelect = document.getElementById("batch-lang-select");
  const batchTotalCount = document.getElementById("batch-total-count");
  const batchGenerateBtn = document.getElementById("batch-generate-btn");
  const batchStopBtn = document.getElementById("batch-stop-btn");
  const batchDownloadZip = document.getElementById("batch-download-zip");

  // History Elements
  const historyListContainer = document.getElementById("history-list-container");
  const historySearch = document.getElementById("history-search");
  const historyOpenFolderBtn = document.getElementById("history-open-folder-btn");
  const historyRefreshBtn = document.getElementById("history-refresh-btn");
  const historyCount = document.getElementById("history-count");

  // Settings & Telegram
  const cfgHost = document.getElementById("cfg-host");
  const cfgPort = document.getElementById("cfg-port");
  const cfgToken = document.getElementById("cfg-token");
  const cfgAllowedIds = document.getElementById("cfg-allowed-ids");
  const cfgMaxWords = document.getElementById("cfg-max-words");
  const cfgMaxUsers = document.getElementById("cfg-max-users");
  const tokenEyeBtn = document.getElementById("token-eye-btn");
  const saveEnvBtn = document.getElementById("save-env-btn");
  const saveEnvStatus = document.getElementById("save-env-status");
  const tgStatusText = document.getElementById("tg-status-text");
  const tgStatusDot = document.getElementById("tg-status-dot");
  const startTgBtn = document.getElementById("start-tg-btn");
  const restartTgBtn = document.getElementById("restart-tg-btn");
  const stopTgBtn = document.getElementById("stop-tg-btn");
  const refreshTgBtn = document.getElementById("refresh-tg-btn");

  // Tips Modal
  const tipsBtn = document.getElementById("tips-btn");
  const tipsModal = document.getElementById("tips-modal");
  const closeTipsBtn = document.getElementById("close-tips-btn");

  // ============================================================
  // 1. Theme Management (Dark / Light)
  // ============================================================
  function applyTheme(theme) {
    state.theme = theme;
    document.documentElement.setAttribute("data-theme", theme);
    themeIcon.textContent = theme === "dark" ? "🌙" : "☀️";
    localStorage.setItem("voicecraft_theme", theme);
  }

  themeToggle.addEventListener("click", () => {
    applyTheme(state.theme === "dark" ? "light" : "dark");
  });
  applyTheme(state.theme);

  // ============================================================
  // 2. Tab Navigation
  // ============================================================
  tabButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      const targetTab = btn.getAttribute("data-tab");
      tabButtons.forEach(b => {
        b.classList.remove("active");
        b.setAttribute("aria-selected", "false");
      });
      tabPanes.forEach(p => p.classList.remove("active"));

      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
      document.getElementById(targetTab).classList.add("active");

      if (targetTab === "tab-history") {
        loadHistory();
      }
    });
  });

  // ============================================================
  // 3. System Status & Language Initialization
  // ============================================================
  async function loadSystemStatus() {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();
      deviceName.textContent = data.device_name;

      if (data.has_voice) {
        state.hasVoice = true;
        setVoiceStatusPill(true, `Voice loaded (${data.voice_duration_s}s)`);
      } else {
        state.hasVoice = false;
        setVoiceStatusPill(false, "No saved voice");
      }
    } catch (e) {
      console.error("Error loading status:", e);
    }
  }

  async function loadLanguages() {
    try {
      const res = await fetch("/api/languages");
      const data = await res.json();
      languageSelect.innerHTML = "";
      batchLangSelect.innerHTML = "";

      data.languages.forEach(lang => {
        const opt1 = document.createElement("option");
        opt1.value = lang.code;
        opt1.textContent = lang.label;
        if (lang.code === state.language) opt1.selected = true;
        languageSelect.appendChild(opt1);

        const opt2 = document.createElement("option");
        opt2.value = lang.code;
        opt2.textContent = lang.label;
        if (lang.code === state.language) opt2.selected = true;
        batchLangSelect.appendChild(opt2);
      });
    } catch (e) {
      console.error("Error loading languages:", e);
    }
  }

  languageSelect.addEventListener("change", () => {
    state.language = languageSelect.value;
    localStorage.setItem("voicecraft_language", state.language);
  });

  // ============================================================
  // 4. Voice Sample Handling (Upload, Record, Validate)
  // ============================================================
  function setVoiceStatusPill(isLoaded, text) {
    if (isLoaded) {
      voicePill.className = "voice-status-pill loaded";
      voiceDot.className = "status-dot green";
      voicePillText.textContent = `✅ ${text}`;
    } else {
      voicePill.className = "voice-status-pill";
      voiceDot.className = "status-dot gray";
      voicePillText.textContent = text;
    }
  }

  voiceDropzone.addEventListener("click", (e) => {
    if (e.target.closest("audio") || e.target.closest("button")) return;
    voiceFileInput.click();
  });

  voiceDropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    voiceDropzone.classList.add("dragover");
  });

  voiceDropzone.addEventListener("dragleave", () => {
    voiceDropzone.classList.remove("dragover");
  });

  voiceDropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    voiceDropzone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleSelectedVoiceFile(e.dataTransfer.files[0]);
    }
  });

  voiceFileInput.addEventListener("change", () => {
    if (voiceFileInput.files && voiceFileInput.files[0]) {
      handleSelectedVoiceFile(voiceFileInput.files[0]);
    }
  });

  function handleSelectedVoiceFile(file) {
    previewFilename.textContent = file.name;
    const objUrl = URL.createObjectURL(file);
    voicePreviewAudio.src = objUrl;

    const testAudio = new Audio(objUrl);
    testAudio.onloadedmetadata = () => {
      const dur = testAudio.duration;
      previewDuration.textContent = `${dur.toFixed(1)}s`;
      validateDuration(dur);
    };

    dropzonePrompt.style.display = "none";
    audioPreviewBox.style.display = "block";
    saveVoiceBtn.disabled = false;
    state.audioBlob = file;
  }

  function validateDuration(dur) {
    if (dur < 5.0) {
      durationWarning.textContent = "⚠️ Notice: Sample is under 5 seconds. 10–20 seconds recommended for high fidelity.";
      durationWarning.style.display = "block";
    } else if (dur > 30.0) {
      durationWarning.textContent = "ℹ️ Notice: Sample is over 30 seconds. Audio will be trimmed/averaged.";
      durationWarning.style.display = "block";
    } else {
      durationWarning.style.display = "none";
    }
  }

  // Microphone Recording
  micRecordBtn.addEventListener("click", async () => {
    if (state.mediaRecorder && state.mediaRecorder.state === "recording") {
      state.mediaRecorder.stop();
      clearInterval(state.recordTimer);
      micLabel.textContent = "Record Voice";
      micIcon.textContent = "🎙️";
      micRecordBtn.classList.remove("btn-danger");
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
        const blob = new Blob(state.recordedChunks, { type: "audio/wav" });
        state.audioBlob = new File([blob], "mic_recording.wav", { type: "audio/wav" });
        handleSelectedVoiceFile(state.audioBlob);
        stream.getTracks().forEach(t => t.stop());
      };

      state.mediaRecorder.start();
      state.recordSeconds = 0;
      micLabel.textContent = "Stop Recording (00:00)";
      micIcon.textContent = "⏹️";
      micRecordBtn.classList.add("btn-danger");

      state.recordTimer = setInterval(() => {
        state.recordSeconds++;
        const mins = String(Math.floor(state.recordSeconds / 60)).padStart(2, "0");
        const secs = String(state.recordSeconds % 60).padStart(2, "0");
        micLabel.textContent = `Stop Recording (${mins}:${secs})`;
      }, 1000);
    } catch (err) {
      alert("Could not access microphone: " + err.message);
    }
  });

  // Save Voice Sample to Server
  saveVoiceBtn.addEventListener("click", async () => {
    if (!state.audioBlob) return;
    saveVoiceBtn.disabled = true;
    saveVoiceBtn.textContent = "⏳ Saving...";

    const formData = new FormData();
    formData.append("file", state.audioBlob);

    try {
      const res = await fetch("/api/voice/upload", {
        method: "POST",
        body: formData
      });
      const data = await res.json();
      if (res.ok) {
        state.hasVoice = true;
        setVoiceStatusPill(true, `Voice loaded (${data.duration_s}s)`);
        saveVoiceBtn.textContent = "✅ Voice Saved!";
        setTimeout(() => {
          saveVoiceBtn.textContent = "💾 Save My Voice";
          saveVoiceBtn.disabled = false;
        }, 2000);
      } else {
        alert("Error saving voice: " + (data.detail || "Upload failed"));
        saveVoiceBtn.disabled = false;
        saveVoiceBtn.textContent = "💾 Save My Voice";
      }
    } catch (e) {
      alert("Upload failed: " + e.message);
      saveVoiceBtn.disabled = false;
      saveVoiceBtn.textContent = "💾 Save My Voice";
    }
  });

  // Check saved voice on startup
  async function checkInitialVoice() {
    try {
      const res = await fetch("/api/voice/status");
      const data = await res.json();
      if (data.has_voice) {
        state.hasVoice = true;
        setVoiceStatusPill(true, `Voice loaded (${data.duration_s}s)`);
        previewFilename.textContent = data.filename;
        previewDuration.textContent = `${data.duration_s}s`;
        voicePreviewAudio.src = data.audio_url;
        dropzonePrompt.style.display = "none";
        audioPreviewBox.style.display = "block";
      } else {
        setVoiceStatusPill(false, "No saved voice");
      }
    } catch (e) {
      setVoiceStatusPill(false, "Ready for upload");
    }
  }

  // ============================================================
  // 5. Text Input & Live Word/Char Counter
  // ============================================================
  function updateCounters() {
    const text = textInput.value;
    const words = text.trim() ? text.trim().split(/\s+/).length : 0;
    const chars = text.length;
    wordCount.textContent = `${words} ${words === 1 ? 'word' : 'words'}`;
    charCount.textContent = `${chars} characters`;
  }
  textInput.addEventListener("input", updateCounters);
  updateCounters();

  // Keyboard Shortcut: Ctrl+Enter to generate
  textInput.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      if (!state.isGenerating) generateSpeech();
    }
  });

  // Style Presets
  const presets = {
    natural: { exaggeration: 0.50, cfg_weight: 0.50, temperature: 0.80 },
    expressive: { exaggeration: 0.85, cfg_weight: 0.60, temperature: 0.85 },
    calm: { exaggeration: 0.35, cfg_weight: 0.40, temperature: 0.70 },
    fast: { exaggeration: 0.50, cfg_weight: 0.00, temperature: 0.80 }
  };

  presetSelect.addEventListener("change", () => {
    const val = presetSelect.value;
    if (presets[val]) {
      setSliders(presets[val]);
    }
  });

  function setSliders(p) {
    exaggerationSlider.value = p.exaggeration;
    exaggerationVal.textContent = Number(p.exaggeration).toFixed(2);
    cfgSlider.value = p.cfg_weight;
    cfgVal.textContent = Number(p.cfg_weight).toFixed(2);
    tempSlider.value = p.temperature;
    tempVal.textContent = Number(p.temperature).toFixed(2);
  }

  exaggerationSlider.addEventListener("input", () => {
    exaggerationVal.textContent = Number(exaggerationSlider.value).toFixed(2);
    presetSelect.value = "custom";
  });
  cfgSlider.addEventListener("input", () => {
    cfgVal.textContent = Number(cfgSlider.value).toFixed(2);
    presetSelect.value = "custom";
  });
  tempSlider.addEventListener("input", () => {
    tempVal.textContent = Number(tempSlider.value).toFixed(2);
    presetSelect.value = "custom";
  });
  pauseSlider.addEventListener("input", () => {
    pauseVal.textContent = `${pauseSlider.value} ms`;
  });
  crossfadeSlider.addEventListener("input", () => {
    crossfadeVal.textContent = `${crossfadeSlider.value} ms`;
  });

  randomizeSeedBtn.addEventListener("click", () => {
    seedInput.value = Math.floor(Math.random() * 1000000);
  });

  resetDefaultsBtn.addEventListener("click", () => {
    setSliders(presets.natural);
    pauseSlider.value = 200;
    pauseVal.textContent = "200 ms";
    crossfadeSlider.value = 30;
    crossfadeVal.textContent = "30 ms";
    seedInput.value = "";
    streamChk.checked = true;
    keepPartialChk.checked = false;
    presetSelect.value = "natural";
  });

  saveCustomPresetBtn.addEventListener("click", () => {
    const custom = {
      exaggeration: parseFloat(exaggerationSlider.value),
      cfg_weight: parseFloat(cfgSlider.value),
      temperature: parseFloat(tempSlider.value)
    };
    localStorage.setItem("voicecraft_custom_preset", JSON.stringify(custom));
    alert("Custom preset saved! You can load it anytime.");
  });

  // ============================================================
  // 6. Speech Generation & Live In-Memory Audio Queue
  // ============================================================
  async function generateSpeech() {
    const text = textInput.value.trim();
    if (!text) {
      alert("Please enter some text to speak.");
      textInput.focus();
      return;
    }
    if (!state.hasVoice) {
      alert("Please save your voice sample first in Step 1.");
      return;
    }

    state.isGenerating = true;
    state.activeAudioQueue = [];
    state.queueIndex = -1;

    generateBtn.disabled = true;
    generateBtn.style.display = "none";
    stopBtn.style.display = "inline-flex";

    outputBadge.textContent = "Generating";
    outputBadge.className = "badge badge-success";
    outputIdle.style.display = "none";
    finalOutputArea.style.display = "none";
    liveStreamArea.style.display = "block";

    progressBar.style.width = "5%";
    streamStatusTitle.textContent = "Initializing voice & model...";
    streamSub.textContent = "First chunk will play automatically in memory...";
    activeSentenceText.textContent = "Preparing text...";

    const startTime = performance.now();
    const timerInterval = setInterval(() => {
      const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);
      streamTimer.textContent = `${elapsed}s elapsed`;
    }, 100);

    state.currentController = new AbortController();

    const payload = {
      text: text,
      language: languageSelect.value,
      exaggeration: parseFloat(exaggerationSlider.value),
      cfg_weight: parseFloat(cfgSlider.value),
      temperature: parseFloat(tempSlider.value),
      seed: seedInput.value ? parseInt(seedInput.value) : null,
      pause_ms: parseInt(pauseSlider.value),
      crossfade_ms: parseInt(crossfadeSlider.value),
      stream_playback: streamChk.checked,
      keep_partial: keepPartialChk.checked
    };

    try {
      const response = await fetch("/api/generate/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: state.currentController.signal
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || "Generation failed.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop(); // Keep partial remainder

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

          // Handle SSE Events
          if (eventType === "start") {
            streamStatusTitle.textContent = `Synthesizing ${data.total_chunks} sentence chunks...`;
            progressBar.style.width = "10%";
          } else if (eventType === "chunk") {
            const pct = Math.round(((data.chunk_index + 1) / data.total_chunks) * 90);
            progressBar.style.width = `${pct}%`;
            streamStatusTitle.textContent = `Streaming chunk ${data.chunk_index + 1} of ${data.total_chunks}`;
            streamSub.textContent = `In-memory synthesis • ${data.elapsed_s}s elapsed`;

            // Highlight Active Sentence
            activeSentenceIdx.textContent = data.chunk_index + 1;
            activeSentenceText.textContent = `"${data.text}"`;

            // Queue Audio Chunk in Memory
            if (data.audio_b64) {
              enqueueAudioChunk(data.audio_b64, data.chunk_index + 1, data.total_chunks);
            }
          } else if (eventType === "complete") {
            clearInterval(timerInterval);
            progressBar.style.width = "100%";
            handleGenerationComplete(data);
          } else if (eventType === "cancelled") {
            clearInterval(timerInterval);
            handleGenerationCancelled(data);
          } else if (eventType === "error") {
            clearInterval(timerInterval);
            alert("Synthesis error: " + data.error);
            resetGenerateUI();
          }
        }
      }
    } catch (e) {
      clearInterval(timerInterval);
      if (e.name !== "AbortError") {
        alert("Generation error: " + e.message);
      }
      resetGenerateUI();
    }
  }

  // Audio Queue Manager (Gapless in-memory playback)
  function enqueueAudioChunk(b64Data, idx, total) {
    state.activeAudioQueue.push({ url: b64Data, idx: idx, total: total });
    if (liveAudioPlayer.paused && state.queueIndex < state.activeAudioQueue.length - 1) {
      playNextChunk();
    }
  }

  function playNextChunk() {
    if (state.queueIndex + 1 < state.activeAudioQueue.length) {
      state.queueIndex++;
      const item = state.activeAudioQueue[state.queueIndex];
      liveAudioPlayer.src = item.url;
      liveAudioPlayer.play().catch(e => console.log("Live audio autoplay:", e));
    }
  }

  liveAudioPlayer.addEventListener("ended", () => {
    playNextChunk();
  });

  // Stop Button
  stopBtn.addEventListener("click", async () => {
    if (state.currentController) {
      state.currentController.abort();
    }
    await fetch("/api/generate/stop", { method: "POST" });
    liveAudioPlayer.pause();
    resetGenerateUI();
  });

  function resetGenerateUI() {
    state.isGenerating = false;
    generateBtn.disabled = false;
    generateBtn.style.display = "inline-flex";
    stopBtn.style.display = "none";
    outputBadge.textContent = "Ready";
    outputBadge.className = "badge";
  }

  function handleGenerationComplete(data) {
    resetGenerateUI();
    liveStreamArea.style.display = "none";
    finalOutputArea.style.display = "block";

    finalFilename.textContent = data.filename;
    finalDuration.textContent = `${data.duration_s}s`;
    finalGenTime.textContent = `Gen: ${data.generation_time_s}s`;

    masterAudioPlayer.src = data.audio_url;
    downloadWavBtn.href = data.audio_url;
    downloadWavBtn.download = data.filename;

    outputBadge.textContent = "Complete";
    outputBadge.className = "badge badge-success";
    loadHistoryCount();
  }

  function handleGenerationCancelled(data) {
    resetGenerateUI();
    if (data.saved_partial && data.audio_url) {
      alert("Generation stopped. Partial audio saved to " + data.audio_url);
    } else {
      liveStreamArea.style.display = "none";
      outputIdle.style.display = "block";
    }
  }

  generateBtn.addEventListener("click", generateSpeech);
  regenerateBtn.addEventListener("click", generateSpeech);

  openFolderBtn.addEventListener("click", async () => {
    await fetch("/api/open-folder", { method: "POST" });
  });

  // ============================================================
  // 7. Batch Clips Tab Manager
  // ============================================================
  function renderBatchItems() {
    batchItemsContainer.innerHTML = "";
    batchTotalCount.textContent = state.batchItems.length;

    state.batchItems.forEach((item, index) => {
      const card = document.createElement("div");
      card.className = "batch-card-item";
      card.id = `batch-card-${item.id}`;
      card.innerHTML = `
        <div class="batch-item-header">
          <span>Clip #${index + 1}</span>
          <button class="remove-clip-btn" data-id="${item.id}">✕ Remove</button>
        </div>
        <textarea class="batch-item-text" rows="2" data-id="${item.id}">${item.text}</textarea>
        <div class="batch-player-box" id="batch-player-${item.id}" style="display:none; margin-top:8px;">
          <audio controls style="width:100%; height:32px;"></audio>
        </div>
      `;
      batchItemsContainer.appendChild(card);
    });

    // Wire Remove Buttons
    document.querySelectorAll(".remove-clip-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-id");
        state.batchItems = state.batchItems.filter(i => i.id !== id);
        renderBatchItems();
      });
    });

    // Wire Text Changes
    document.querySelectorAll(".batch-item-text").forEach(txt => {
      txt.addEventListener("input", () => {
        const id = txt.getAttribute("data-id");
        const found = state.batchItems.find(i => i.id === id);
        if (found) found.text = txt.value;
      });
    });
  }

  batchAddBtn.addEventListener("click", () => {
    const nextId = String(Date.now());
    state.batchItems.push({ id: nextId, text: "" });
    renderBatchItems();
  });

  batchPasteLinesBtn.addEventListener("click", () => {
    const linesStr = prompt("Paste multiple lines below (each line becomes one clip):");
    if (!linesStr) return;
    const lines = linesStr.split("\n").map(l => l.trim()).filter(l => l.length > 0);
    if (lines.length === 0) return;

    state.batchItems = lines.map((text, idx) => ({ id: String(Date.now() + idx), text }));
    renderBatchItems();
  });

  renderBatchItems();

  // Batch Generation
  batchGenerateBtn.addEventListener("click", async () => {
    if (state.batchItems.length === 0) {
      alert("Please add at least one clip.");
      return;
    }
    if (!state.hasVoice) {
      alert("Please save your voice sample first in the Studio tab.");
      return;
    }

    batchGenerateBtn.disabled = true;
    batchGenerateBtn.style.display = "none";
    batchStopBtn.style.display = "inline-flex";
    batchDownloadZip.style.display = "none";

    const payload = {
      items: state.batchItems,
      language: batchLangSelect.value,
      exaggeration: parseFloat(exaggerationSlider.value),
      cfg_weight: parseFloat(cfgSlider.value),
      temperature: parseFloat(tempSlider.value),
      seed: seedInput.value ? parseInt(seedInput.value) : null,
      pause_ms: parseInt(pauseSlider.value),
      crossfade_ms: parseInt(crossfadeSlider.value)
    };

    try {
      const response = await fetch("/api/batch/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

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

          if (eventType === "clip_done") {
            const playerBox = document.getElementById(`batch-player-${data.item_id}`);
            if (playerBox) {
              playerBox.style.display = "block";
              const aud = playerBox.querySelector("audio");
              aud.src = data.audio_url;
            }
          } else if (eventType === "batch_complete") {
            batchDownloadZip.href = data.zip_url;
            batchDownloadZip.style.display = "inline-flex";
            alert("All batch clips synthesized successfully!");
          }
        }
      }
    } catch (e) {
      alert("Batch generation failed: " + e.message);
    } finally {
      batchGenerateBtn.disabled = false;
      batchGenerateBtn.style.display = "inline-flex";
      batchStopBtn.style.display = "none";
      loadHistoryCount();
    }
  });

  // ============================================================
  // 8. History Tab Manager
  // ============================================================
  let allHistoryItems = [];

  async function loadHistory() {
    try {
      const res = await fetch("/api/history");
      const data = await res.json();
      allHistoryItems = data.items || [];
      historyCount.textContent = allHistoryItems.length;
      renderHistoryList(allHistoryItems);
    } catch (e) {
      historyListContainer.innerHTML = `<div class="history-empty">Error loading history: ${e.message}</div>`;
    }
  }

  async function loadHistoryCount() {
    try {
      const res = await fetch("/api/history");
      const data = await res.json();
      historyCount.textContent = (data.items || []).length;
    } catch (e) {}
  }

  function renderHistoryList(items) {
    if (!items || items.length === 0) {
      historyListContainer.innerHTML = '<div class="history-empty">No generated audio files found in outputs/</div>';
      return;
    }

    historyListContainer.innerHTML = "";
    items.forEach(item => {
      const card = document.createElement("div");
      card.className = "history-item-card";
      card.innerHTML = `
        <div class="history-meta">
          <div class="history-title">${item.filename}</div>
          <div class="history-sub">${item.created_at} • ${item.duration_s}s • ${item.size_mb} MB</div>
        </div>
        <div class="history-actions">
          <audio controls src="${item.audio_url}" style="height:32px; width:220px;"></audio>
          <a class="btn btn-secondary btn-sm" href="${item.audio_url}" download="${item.filename}">⬇️</a>
          <button class="btn btn-danger btn-sm delete-hist-btn" data-filename="${item.filename}">🗑️</button>
        </div>
      `;
      historyListContainer.appendChild(card);
    });

    document.querySelectorAll(".delete-hist-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const fname = btn.getAttribute("data-filename");
        if (!confirm(`Delete ${fname}?`)) return;
        try {
          const res = await fetch(`/api/history/${fname}`, { method: "DELETE" });
          if (res.ok) {
            loadHistory();
          }
        } catch (e) {
          alert("Could not delete file: " + e.message);
        }
      });
    });
  }

  historySearch.addEventListener("input", () => {
    const q = historySearch.value.toLowerCase().trim();
    if (!q) {
      renderHistoryList(allHistoryItems);
      return;
    }
    const filtered = allHistoryItems.filter(i => 
      i.filename.toLowerCase().includes(q) || i.created_at.toLowerCase().includes(q)
    );
    renderHistoryList(filtered);
  });

  historyOpenFolderBtn.addEventListener("click", async () => {
    await fetch("/api/open-folder", { method: "POST" });
  });

  historyRefreshBtn.addEventListener("click", loadHistory);

  // ============================================================
  // 9. Settings & Telegram Bot
  // ============================================================
  tokenEyeBtn.addEventListener("click", () => {
    cfgToken.type = cfgToken.type === "password" ? "text" : "password";
    tokenEyeBtn.textContent = cfgToken.type === "password" ? "👁️" : "🙈";
  });

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
    } catch (e) {}
  }

  saveEnvBtn.addEventListener("click", async () => {
    saveEnvBtn.disabled = true;
    saveEnvBtn.textContent = "Saving...";
    try {
      const res = await fetch("/api/telegram/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          host: cfgHost ? cfgHost.value : "127.0.0.1",
          port: cfgPort ? cfgPort.value : "7860",
          token: cfgToken ? cfgToken.value : "",
          allowed_ids: cfgAllowedIds ? cfgAllowedIds.value : "",
          max_words: cfgMaxWords ? parseInt(cfgMaxWords.value) || 60 : 60,
          max_users: cfgMaxUsers ? parseInt(cfgMaxUsers.value) || 1 : 1
        })
      });
      saveEnvStatus.textContent = "✅ Settings saved safely to .env (Private & Ignored by Git)";
      saveEnvStatus.style.color = "var(--success)";
      setTimeout(() => { saveEnvStatus.textContent = ""; }, 4000);
    } catch (e) {
      saveEnvStatus.textContent = "❌ Error saving settings.";
      saveEnvStatus.style.color = "var(--danger)";
    } finally {
      saveEnvBtn.disabled = false;
      saveEnvBtn.textContent = "💾 Save Settings";
    }
  });

  async function checkTelegramStatus() {
    try {
      const res = await fetch("/api/telegram/status");
      const data = await res.json();
      tgStatusText.textContent = data.status;
      if (data.status.includes("RUNNING")) {
        tgStatusDot.className = "status-dot green";
      } else {
        tgStatusDot.className = "status-dot gray";
      }
    } catch (e) {}
  }

  startTgBtn.addEventListener("click", async () => {
    startTgBtn.disabled = true;
    try {
      await fetch("/api/telegram/start", { method: "POST" });
      setTimeout(checkTelegramStatus, 1500);
    } finally {
      startTgBtn.disabled = false;
    }
  });

  if (restartTgBtn) {
    restartTgBtn.addEventListener("click", async () => {
      restartTgBtn.disabled = true;
      restartTgBtn.textContent = "Restarting...";
      try {
        await fetch("/api/telegram/restart", { method: "POST" });
        setTimeout(checkTelegramStatus, 2000);
      } finally {
        restartTgBtn.disabled = false;
        restartTgBtn.textContent = "🔄 Restart Bot";
      }
    });
  }

  stopTgBtn.addEventListener("click", async () => {
    stopTgBtn.disabled = true;
    try {
      await fetch("/api/telegram/stop", { method: "POST" });
      setTimeout(checkTelegramStatus, 1000);
    } finally {
      stopTgBtn.disabled = false;
    }
  });

  refreshTgBtn.addEventListener("click", checkTelegramStatus);

  // ============================================================
  // 10. Tips Modal
  // ============================================================
  tipsBtn.addEventListener("click", () => {
    tipsModal.style.display = "flex";
  });
  closeTipsBtn.addEventListener("click", () => {
    tipsModal.style.display = "none";
  });
  tipsModal.addEventListener("click", (e) => {
    if (e.target === tipsModal) tipsModal.style.display = "none";
  });

  // ============================================================
  // Initialization
  // ============================================================
  function handleHash() {
    const hash = window.location.hash.replace("#", "");
    if (hash && document.getElementById(hash)) {
      const btn = document.querySelector(`.tab-btn[data-tab="${hash}"]`);
      if (btn) btn.click();
    }
  }
  window.addEventListener("hashchange", handleHash);

  loadSystemStatus();
  loadLanguages();
  checkInitialVoice();
  loadHistoryCount();
  checkTelegramStatus();
  loadTelegramSettings();
  handleHash();
});
