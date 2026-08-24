(() => {
  "use strict";

  const DENIED_KEY = "learn-with-stories:microphone-denied";

  class VoicePermissionError extends Error {
    constructor(code, message, cause = null) {
      super(message);
      this.name = "VoicePermissionError";
      this.code = code;
      this.cause = cause;
    }
  }

  class PermissionManager {
    constructor(storage = null) {
      if (storage) {
        this.storage = storage;
        return;
      }
      try {
        this.storage = globalThis.sessionStorage;
      } catch {
        this.storage = null;
      }
    }

    _readDeniedFlag() {
      try {
        return this.storage?.getItem(DENIED_KEY) === "true";
      } catch {
        return false;
      }
    }

    _writeDeniedFlag(denied) {
      try {
        if (denied) this.storage?.setItem(DENIED_KEY, "true");
        else this.storage?.removeItem(DENIED_KEY);
      } catch {
        // Storage may be unavailable in private browsing; permission handling still works.
      }
    }

    async microphoneState() {
      if (!globalThis.isSecureContext) return "unavailable";
      if (!navigator.mediaDevices?.getUserMedia) return "unavailable";
      try {
        const permission = await navigator.permissions?.query({ name: "microphone" });
        if (permission?.state === "granted") {
          this._writeDeniedFlag(false);
          return "granted";
        }
        if (permission?.state === "denied") return "blocked";
        if (permission?.state === "prompt") return "prompt";
      } catch {
        // Some browsers support microphone capture without exposing it through Permissions API.
      }
      return this._readDeniedFlag() ? "blocked" : "unknown";
    }

    async requestMicrophone() {
      const current = await this.microphoneState();
      if (current === "unavailable") {
        throw new VoicePermissionError(
          "permission_unavailable",
          "Microphone access is unavailable. Use HTTPS or localhost and check that this browser supports audio capture.",
        );
      }
      if (current === "blocked") {
        throw new VoicePermissionError(
          "permission_blocked",
          "Microphone access is blocked for this site. Allow it in the browser's site settings, then reload the page.",
        );
      }

      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
          video: false,
        });
        this._writeDeniedFlag(false);
        return "granted";
      } catch (error) {
        const name = String(error?.name || "");
        if (name === "NotAllowedError" || name === "SecurityError") {
          this._writeDeniedFlag(true);
          throw new VoicePermissionError(
            "permission_denied",
            "Microphone permission was denied. Allow microphone access in the browser's site settings before trying again.",
            error,
          );
        }
        if (name === "NotFoundError" || name === "DevicesNotFoundError") {
          throw new VoicePermissionError("microphone_missing", "No microphone was detected on this device.", error);
        }
        if (name === "NotReadableError" || name === "TrackStartError" || name === "AbortError") {
          throw new VoicePermissionError(
            "microphone_busy",
            "The microphone is unavailable or already being used by another application. Close the other application and retry.",
            error,
          );
        }
        throw new VoicePermissionError(
          "microphone_unavailable",
          "The microphone could not be started. Check the selected input device and try again.",
          error,
        );
      } finally {
        stream?.getTracks().forEach((track) => track.stop());
      }
    }
  }

  globalThis.LWSVoice = Object.assign(globalThis.LWSVoice || {}, { PermissionManager, VoicePermissionError });
})();
