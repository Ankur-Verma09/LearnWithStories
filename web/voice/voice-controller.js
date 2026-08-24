(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const languageCode = (value) => value === "Hindi" ? "hi-IN" : "en-IN";
  const noRetryCodes = new Set(["permission_denied", "permission_blocked", "permission_unavailable", "recognition_unsupported"]);

  class VoiceController {
    constructor() {
      const { PermissionManager, SpeechRecognitionService, SpeechSynthesisService } = globalThis.LWSVoice || {};
      this.question = byId("lessonQuestion");
      this.language = byId("language");
      this.micButton = byId("voiceInputButton");
      this.micStatus = byId("voiceInputStatus");
      this.micStatusText = byId("voiceInputStatusText");
      this.retryButton = byId("voiceRetryButton");
      this.controls = byId("storyPlaybackControls");
      this.playButton = byId("storyPlayButton");
      this.pauseButton = byId("storyPauseButton");
      this.resumeButton = byId("storyResumeButton");
      this.stopButton = byId("storyStopButton");
      this.playbackStatus = byId("storyPlaybackStatus");
      this.storyText = "";
      this.storyLanguage = "English";
      this.questionBeforeListening = "";
      this.permissionManager = new PermissionManager();
      this.recognition = new SpeechRecognitionService({
        onState: (state) => this._renderRecognitionState(state),
        onTranscript: (finalText, interimText) => this._applyTranscript(finalText, interimText),
        onError: (error) => this._showRecognitionError(error),
      });
      this.synthesis = new SpeechSynthesisService({
        onState: (state, progress) => this._renderPlaybackState(state, progress),
        onError: (error) => this._showPlaybackError(error),
      });
      this._bind();
      this._initializeAvailability();
    }

    _bind() {
      this.micButton.addEventListener("click", () => this.toggleRecognition());
      this.retryButton.addEventListener("click", () => this.startRecognition());
      this.playButton.addEventListener("click", () => this.synthesis.play(this.storyText, languageCode(this.storyLanguage)));
      this.pauseButton.addEventListener("click", () => this.synthesis.pause());
      this.resumeButton.addEventListener("click", () => this.synthesis.resume());
      this.stopButton.addEventListener("click", () => this.synthesis.stop());
      globalThis.addEventListener("lesson:generation-start", () => {
        if (this.recognition.isListening) this.recognition.stop();
        this.synthesis.stop();
      });
      globalThis.addEventListener("lesson:rendered", (event) => {
        this.synthesis.stop(false);
        this.storyText = String(event.detail?.text || "").trim();
        this.storyLanguage = String(event.detail?.language || "English");
        this.controls.classList.toggle("hidden", !this.storyText);
        this._renderPlaybackState("idle", { current: 0, total: 0 });
      });
      globalThis.addEventListener("pagehide", () => this.destroy(), { once: true });
    }

    _initializeAvailability() {
      if (!globalThis.LWSVoice.SpeechRecognitionService.isSupported()) {
        this.micButton.disabled = true;
        this.micButton.title = "Voice input is not supported by this browser";
        this._showMicStatus("Voice input is not supported by this browser. Type the question instead.", "error");
      }
      if (!globalThis.LWSVoice.SpeechSynthesisService.isSupported()) {
        this.controls.dataset.unsupported = "true";
        [this.playButton, this.pauseButton, this.resumeButton, this.stopButton].forEach((button) => {
          button.disabled = true;
        });
        this.playbackStatus.textContent = "Story playback is unavailable in this browser.";
      }
    }

    async toggleRecognition() {
      if (this.recognition.isListening) {
        this.recognition.stop();
        return;
      }
      await this.startRecognition();
    }

    async startRecognition() {
      this.retryButton.classList.add("hidden");
      this._showMicStatus("Checking microphone permission…", "checking");
      try {
        await this.permissionManager.requestMicrophone();
        this.questionBeforeListening = this.question.value.trim();
        this.recognition.start(languageCode(this.language.value));
      } catch (error) {
        this._showRecognitionError(error);
      }
    }

    _applyTranscript(finalText, interimText) {
      const spoken = `${finalText} ${interimText}`.replace(/\s+/g, " ").trim();
      const prefix = this.questionBeforeListening;
      this.question.value = [prefix, spoken].filter(Boolean).join(prefix && spoken ? " " : "");
      this.question.dispatchEvent(new Event("input", { bubbles: true }));
    }

    _renderRecognitionState(state) {
      const listening = state === "listening";
      this.micButton.classList.toggle("listening", listening);
      this.micButton.setAttribute("aria-pressed", String(listening));
      this.micButton.setAttribute("aria-label", listening ? "Stop voice input" : "Start voice input");
      if (listening) this._showMicStatus("Listening… select the microphone again when finished.", "listening");
      else if (state === "stopped" && !this.recognition.finalTranscript.trim()) {
        this._showMicStatus("No speech was captured. Retry or type the question instead.", "error");
        this.retryButton.classList.remove("hidden");
      } else if (state === "stopped") {
        this._showMicStatus("Voice input stopped. You can edit the question before submitting.", "stopped");
      }
    }

    _showMicStatus(message, state) {
      this.micStatus.dataset.state = state;
      this.micStatusText.textContent = message;
      this.micStatus.classList.remove("hidden");
    }

    _showRecognitionError(error) {
      const code = String(error?.code || "recognition_failed");
      this.recognition.stop();
      const state = code === "network" ? "unavailable" : "error";
      this._showMicStatus(error?.message || "Voice input failed. Please retry or type the question.", state);
      this.retryButton.classList.toggle("hidden", noRetryCodes.has(code));
    }

    _renderPlaybackState(state, progress = {}) {
      if (this.controls.dataset.unsupported === "true") return;
      const active = state === "playing" || state === "paused";
      this.controls.dataset.state = state;
      [this.playButton, this.pauseButton, this.resumeButton, this.stopButton].forEach((button) => {
        button.classList.remove("active");
        button.setAttribute("aria-pressed", "false");
      });
      if (state === "playing") {
        this.playButton.classList.add("active");
        this.playButton.setAttribute("aria-pressed", "true");
      }
      if (state === "paused") {
        this.pauseButton.classList.add("active");
        this.pauseButton.setAttribute("aria-pressed", "true");
      }
      this.pauseButton.classList.toggle("hidden", state === "paused");
      this.resumeButton.classList.toggle("hidden", state !== "paused");
      this.playButton.disabled = !this.storyText || state === "playing";
      this.pauseButton.disabled = state !== "playing";
      this.resumeButton.disabled = state !== "paused";
      this.stopButton.disabled = !active;
      const labels = {
        idle: "Ready to play.", playing: "Playing story…", paused: "Story paused.",
        stopped: "Playback stopped.", completed: "Story playback complete.", error: "Playback interrupted.",
      };
      const part = state === "playing" && progress.total ? ` Part ${Math.min(progress.current + 1, progress.total)} of ${progress.total}.` : "";
      this.playbackStatus.textContent = `${labels[state] || "Ready to play."}${part}`;
    }

    _showPlaybackError(error) {
      this._renderPlaybackState("error");
      this.playbackStatus.textContent = error?.message || "Story playback failed. Select Play Story to retry.";
      this.playButton.disabled = !this.storyText;
    }

    destroy() {
      this.recognition.destroy();
      this.synthesis.destroy();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => new VoiceController(), { once: true });
  } else {
    new VoiceController();
  }
})();
