(() => {
  "use strict";

  function splitForSpeech(text, limit = 240) {
    const sentences = String(text || "").replace(/\s+/g, " ").trim().match(/[^.!?।]+[.!?।]?/g) || [];
    const chunks = [];
    for (const sentence of sentences) {
      const clean = sentence.trim();
      if (!clean) continue;
      if (clean.length <= limit) {
        chunks.push(clean);
        continue;
      }
      let current = "";
      for (const word of clean.split(" ")) {
        if (current && `${current} ${word}`.length > limit) {
          chunks.push(current);
          current = word;
        } else {
          current = `${current} ${word}`.trim();
        }
      }
      if (current) chunks.push(current);
    }
    return chunks;
  }

  class SpeechSynthesisService {
    constructor({ onState = () => {}, onError = () => {} } = {}) {
      this.engine = globalThis.speechSynthesis;
      this.onState = onState;
      this.onError = onError;
      this.state = "idle";
      this.chunks = [];
      this.index = 0;
      this.language = "en-IN";
      this.currentUtterance = null;
      this.session = 0;
    }

    static isSupported() {
      return Boolean(globalThis.speechSynthesis && globalThis.SpeechSynthesisUtterance);
    }

    _setState(state) {
      this.state = state;
      this.onState(state, { current: this.index, total: this.chunks.length });
    }

    _voiceForLanguage() {
      const wanted = this.language.toLowerCase();
      const prefix = wanted.split("-")[0];
      const voices = this.engine?.getVoices?.() || [];
      return voices.find((voice) => voice.lang.toLowerCase() === wanted)
        || voices.find((voice) => voice.lang.toLowerCase().startsWith(prefix))
        || null;
    }

    play(text, language = "en-IN") {
      if (!SpeechSynthesisService.isSupported()) {
        this.onError({ code: "playback_unsupported", message: "Story playback is not supported by this browser." });
        return false;
      }
      const chunks = splitForSpeech(text);
      if (!chunks.length) {
        this.onError({ code: "empty_story", message: "There is no story text available to play." });
        return false;
      }
      this.stop(false);
      this.session += 1;
      this.chunks = chunks;
      this.index = 0;
      this.language = language;
      this._setState("playing");
      this._speakNext(this.session);
      return true;
    }

    _speakNext(session) {
      if (session !== this.session || this.state === "stopped") return;
      if (this.index >= this.chunks.length) {
        this.currentUtterance = null;
        this._setState("completed");
        return;
      }
      const utterance = new SpeechSynthesisUtterance(this.chunks[this.index]);
      utterance.lang = this.language;
      const voice = this._voiceForLanguage();
      if (voice) utterance.voice = voice;
      utterance.rate = 1;
      utterance.pitch = 1;
      utterance.onend = () => {
        if (session !== this.session || this.state === "stopped") return;
        this.index += 1;
        this._speakNext(session);
      };
      utterance.onerror = (event) => {
        if (session !== this.session || ["canceled", "interrupted"].includes(String(event.error)) && this.state === "stopped") return;
        this.currentUtterance = null;
        this._setState("error");
        this.onError({ code: String(event.error || "playback_failed"), message: "Story playback was interrupted. Select Play Story to retry." });
      };
      this.currentUtterance = utterance;
      try {
        this.engine.speak(utterance);
      } catch (error) {
        this._setState("error");
        this.onError({ code: "playback_failed", message: "The browser could not start audio playback. Select Play Story again.", cause: error });
      }
    }

    pause() {
      if (this.state !== "playing" || !this.engine?.speaking) return false;
      this.engine.pause();
      this._setState("paused");
      return true;
    }

    resume() {
      if (this.state !== "paused") return false;
      this.engine.resume();
      this._setState("playing");
      return true;
    }

    stop(notify = true) {
      this.session += 1;
      this.engine?.cancel();
      if (this.currentUtterance) {
        this.currentUtterance.onend = null;
        this.currentUtterance.onerror = null;
      }
      this.currentUtterance = null;
      this.chunks = [];
      this.index = 0;
      this.state = "stopped";
      if (notify) this._setState("stopped");
    }

    destroy() {
      this.stop(false);
      this.onState = () => {};
      this.onError = () => {};
    }
  }

  globalThis.LWSVoice = Object.assign(globalThis.LWSVoice || {}, { SpeechSynthesisService, splitForSpeech });
})();
