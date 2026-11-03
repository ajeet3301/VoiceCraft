// ============================================================
// Voice Studio - UI Strings and Messages
// Human-written, calm, polite, and emoji-free.
// All visible UI text is centralized here for easy editing.
// ============================================================

const MESSAGES = {
  // Page header & navigation
  title: "Voice Studio",
  subtitle: "Choose a voice, then write what it should say.",
  themeToggle: "Theme",
  tabs: {
    studio: "Studio",
    batch: "Batch clips",
    history: "History",
    settings: "Settings & bot"
  },

  // Voices section
  voicesTitle: "Voices",
  addVoiceLink: "Add a voice",
  closeAddVoiceLink: "Close",
  voiceNameLabel: "Voice name",
  voiceNamePlaceholder: "For example, Tamanna or Ayushi",
  voiceSampleLabel: "Voice recording",
  dropTextDefault: "Choose an audio file (5 to 20 seconds works best)",
  dropTextRecorded: (kb) => `Recorded audio sample (${kb} KB)`,
  recordMicBtn: "Record with microphone",
  stopMicBtn: "Stop recording",
  recordingStatus: "Recording. Speak naturally for 10 to 15 seconds.",
  recordingStopped: "Recording finished.",
  micUnavailable: "Microphone access was not granted or is unsupported.",
  saveVoiceBtn: "Save voice",
  savingVoiceBtn: "Saving...",
  cancelBtn: "Cancel",
  loadingVoices: "Loading voices...",
  noVoices: "No saved voices yet. Add a voice above to begin.",
  voiceSelected: "Selected",
  selectVoiceAction: "Select",
  deleteVoiceAction: "Delete",
  confirmDeleteVoice: (name) => `Delete the voice "${name}"?`,
  voiceSavedNotice: (name) => `Saved voice "${name}".`,
  nameRequired: "Please enter a name for this voice.",
  sampleRequired: "Please select or record an audio sample.",
  voiceDeleteError: "Unable to delete voice. Please try again.",

  // Text section
  textLabel: "Text",
  textPlaceholder: "Write what you would like spoken.",
  charCount: (count) => `${count} character${count === 1 ? "" : "s"}`,
  detectedLangPrefix: "Detected language: ",
  detectedDefault: "Hindi",
  languageSupportHint: "Hindi, English, and Hinglish are supported.",

  // Voice style
  styleLabel: "Speaking style",
  styles: {
    natural: "Natural",
    happy: "Happy",
    soft: "Soft",
    husky: "Husky",
    whisper: "Whisper"
  },

  // Actions & generation
  generateBtn: "Generate",
  generatingInit: "Starting generation...",
  generatingProgress: (pct, seconds) => `Generating. ${pct}%. About ${seconds} seconds remaining.`,
  generatingChunk: (current, total) => `Generating section ${current} of ${total}...`,
  generatingReady: "Ready.",
  stoppedStatus: "Generation stopped.",
  stopAction: "Stop",
  regenerateAction: "Generate again",
  downloadAction: "Download",

  // Results & history
  resultTitle: "Result",
  recentTitle: "Recent recordings",
  refreshAction: "Refresh",
  noHistory: "No recent recordings.",
  loadingHistory: "Loading recent recordings...",

  // Batch clips
  batchTitle: "Batch generation",
  batchDesc: "Generate multiple audio clips in sequence using the selected voice.",
  batchAddClip: "Add clip",
  batchPasteLines: "Paste multiple lines",
  batchGenerateBtn: "Generate all clips",
  batchStopBtn: "Stop batch",
  batchDownloadZip: "Download all as ZIP",
  batchEmpty: "No clips added. Click 'Add clip' or 'Paste multiple lines' to start.",
  batchPastePrompt: "Paste your text below. Each separate line will become one audio clip:",

  // Settings & Telegram Bot
  settingsTitle: "Studio settings",
  settingsDesc: "Configure bot parameters and local server settings.",
  hostLabel: "Server host",
  portLabel: "Server port",
  tokenLabel: "Telegram bot token",
  tokenHint: "Provided by @BotFather. Stored locally in .env.",
  allowedUsersLabel: "Authorized Telegram user IDs",
  allowedUsersHint: "Comma-separated Telegram user IDs allowed to use the bot.",
  maxWordsLabel: "Maximum words per request",
  maxWordsHint: "Limits the length of text accepted by the bot in a single message.",
  maxUsersLabel: "Maximum allowed users",
  maxUsersHint: "Maximum number of users allowed to access the bot (0 = unlimited).",
  saveSettingsBtn: "Save settings",
  savingSettingsBtn: "Saving...",
  settingsSavedNotice: "Settings saved successfully to .env.",
  settingsError: "Could not save settings. Please try again.",

  botControllerTitle: "Telegram bot controller",
  botStatusLabel: "Status:",
  startBotBtn: "Start bot",
  restartBotBtn: "Restart bot",
  stopBotBtn: "Stop bot",
  refreshStatusBtn: "Check status",
  botLinkText: "Open Telegram bot: @VoiceCraftBitchsBot",

  // Error messages
  errorGeneric: "Unable to complete generation. Please try again in a moment.",
  errorConnection: "Could not connect to the server. Please check that the server is running.",
  errorEmptyText: "Please enter some text before generating.",
  errorNoVoice: "Please select a voice before generating.",

  // Footer
  footer: "Voice Studio"
};

window.MESSAGES = MESSAGES;
