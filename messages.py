"""
Centralized UI and Telegram Bot Message Texts
Claude-inspired: calm, minimal, polite, and free of emojis or hype.
"""

# Telegram Bot Messages
BOT_START = (
    "Send a voice message to save a voice. "
    "Then send text, and I will read it in that voice."
)

BOT_ASK_VOICE_NAME = (
    "Whose voice is this?\n\n"
    "Reply with a name to save it."
)

BOT_VOICE_SAVED = (
    "Saved as {name}. Send text whenever you are ready."
)

BOT_VOICE_DELETED = (
    "Deleted {name}."
)

BOT_VOICE_NOT_FOUND = (
    "Voice not found. Send text to choose another voice."
)

BOT_CHOOSE_VOICE = (
    "Which voice should I use?"
)

BOT_NO_VOICES = (
    "No saved voices yet. Send a voice message first to save one."
)

BOT_RECEIVING_AUDIO = "Receiving voice sample..."
BOT_PROCESSING_AUDIO = "Processing audio..."
BOT_ANALYZING_VOICE = "Analyzing voice..."

BOT_GENERATING_PROGRESS = (
    "Generating. {percent}% complete. About {time_left} remaining."
)

BOT_GENERATING_QUEUED = (
    "Another request is currently processing. You are next in queue."
)

BOT_DONE = "Ready."

BOT_AUDIO_DELETED = "Audio deleted."
BOT_AUDIO_SAVED = "Saved to outputs folder."

BOT_TEXT_TOO_LONG = (
    "That text exceeds the limit of {max_words} words. "
    "Please send a shorter passage."
)

BOT_CAPACITY_REACHED = (
    "This bot has reached its user limit ({max_users}). "
    "Please contact the administrator to expand capacity."
)

BOT_ACCESS_RESTRICTED = (
    "Access is restricted to authorized accounts. "
    "Your account ID is {uid}."
)

BOT_ERROR_AUDIO_QUALITY = (
    "That recording was too quiet or unclear. Please send a clearer voice sample."
)

BOT_ERROR_GENERIC = (
    "Unable to complete request. Please try again in a moment."
)

BOT_LANGUAGE_UPDATED = (
    "Default language set to {lang}."
)

BOT_STATUS = (
    "Voice Studio Status\n\n"
    "Saved voices: {voice_count}\n"
    "Cached audio files: {audio_count}\n"
    "Max words per message: {max_words}\n"
    "Language: {language}"
)

# Web Studio Messages
WEB_TITLE = "Voice Studio"
WEB_SUBTITLE = "Save a voice, then write what it should say."
WEB_VOICES_HEADING = "Voices"
WEB_ADD_VOICE = "Add a voice"
WEB_TEXT_LABEL = "Text"
WEB_TEXT_PLACEHOLDER = "Write or paste what you would like spoken..."
WEB_GENERATE_BTN = "Generate"
WEB_GENERATING_BTN = "Generating..."
WEB_DOWNLOAD = "Download"
WEB_REGENERATE = "Regenerate"
WEB_DELETE = "Delete"
WEB_SELECT = "Select"
WEB_CANCEL = "Cancel"
