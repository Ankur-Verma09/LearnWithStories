(() => {
  "use strict";

  const Recognition = globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition;
  const ERROR_MESSAGES = {
    "no-speech": "No speech was detected. Move closer to the microphone and retry.",
    "audio-capture": "The microphone could not capture audio. Check the device and retry.",
    network: "Speech recognition could not reach the browser's recognition service. Check the connection and retry.",
    "not-allowed": "Microphone permission is denied or blocked for this site.",
    "service-not-allowed": "Speech recognition is blocked by this browser or device policy.",
    "language-not-supported": "Speech recognition does not support the selected language on this browser.",
  };

  class SpeechRecognitionService {
    constructor({ onState = () => {}, onTranscript = () => {}, onError = () => {}, maxSessionMs = 120000 } = {}) {
      this.onState = onState;
      this.onTranscript = onTranscript;
      this.onError = onError;
      this.maxSessionMs = maxSessionMs;
      this.recognition = null;
      this.shouldListen = false;
      this.startedAt = 0;
      this.finalTranscript = "";
      this.timeoutId = null;
      this.restartId = null;
      this.language = "en-IN";
      this.lastError = "";
    }

    static isSupported() {
      return Boolean(Recognition);
    }

    get isListening() {
      return this.shouldListen;
    }

    _createRecognition() {
      const recognition = new Recognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;
      recognition.lang = this.language;
      recognition.onstart = () => this.onState("listening");
      recognition.onresult = (event) => {
        let interim = "";
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const text = String(event.results[index][0]?.transcript || "").trim();
          if (!text) continue;
          if (event.results[index].isFinal) this.finalTranscript = `${this.finalTranscript} ${text}`.trim();
          else interim = `${interim} ${text}`.trim();
        }
        this.onTranscript(this.finalTranscript, interim);
      };
      recognition.onerror = (event) => {
        const code = String(event.error || "recognition_failed");
        if (code === "aborted" && !this.shouldListen) return;
        this.lastError = code;
        this.shouldListen = false;
        this._clearTimers();
        this.onState("error");
        this.onError({ code, message: ERROR_MESSAGES[code] || "Speech recognition stopped unexpectedly. Please retry." });
      };
      recognition.onend = () => {
        this.recognition = null;
        if (this.shouldListen && !this.lastError && Date.now() - this.startedAt < this.maxSessionMs) {
          this.restartId = globalThis.setTimeout(() => this._startRecognition(), 200);
          return;
        }
        if (!this.lastError) this.onState("stopped");
      };
      this.recognition = recognition;
      return recognition;
    }

    _startRecognition() {
      if (!this.shouldListen) return;
      try {
        this._createRecognition().start();
      } catch (error) {
        this.shouldListen = false;
        this._clearTimers();
        this.onState("error");
        this.onError({ code: "recognition_failed", message: "Speech recognition could not start. Wait a moment and retry.", cause: error });
      }
    }

    start(language = "en-IN") {
      if (!Recognition) {
        this.onError({ code: "recognition_unsupported", message: "Voice input is not supported by this browser. Type the question instead." });
        return false;
      }
      if (this.shouldListen) return true;
      this.abort();
      this.language = language;
      this.shouldListen = true;
      this.startedAt = Date.now();
      this.finalTranscript = "";
      this.lastError = "";
      this.timeoutId = globalThis.setTimeout(() => {
        if (!this.shouldListen) return;
        this.stop();
        this.onError({ code: "recognition_timeout", message: "Voice input stopped after two minutes. Review the text or retry to continue." });
      }, this.maxSessionMs);
      this._startRecognition();
      return true;
    }

    stop() {
      this.shouldListen = false;
      this._clearTimers();
      try {
        this.recognition?.stop();
      } catch {
        this.recognition = null;
      }
      this.onState("stopped");
    }

    abort() {
      this.shouldListen = false;
      this._clearTimers();
      if (this.recognition) {
        this.recognition.onend = null;
        try {
          this.recognition.abort();
        } catch {
          // The recognition instance may already be inactive.
        }
      }
      this.recognition = null;
    }

    _clearTimers() {
      globalThis.clearTimeout(this.timeoutId);
      globalThis.clearTimeout(this.restartId);
      this.timeoutId = null;
      this.restartId = null;
    }

    destroy() {
      this.abort();
      this.onState = () => {};
      this.onTranscript = () => {};
      this.onError = () => {};
    }
  }

  globalThis.LWSVoice = Object.assign(globalThis.LWSVoice || {}, { SpeechRecognitionService });
})();
