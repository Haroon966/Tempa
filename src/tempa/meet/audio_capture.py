"""Browser-side Meet audio capture hooks and PCM analysis helpers."""

from __future__ import annotations

import math
import struct
from pathlib import Path

# RMS below this across a long recording indicates failed remote audio hook.
SILENT_CAPTURE_RMS_THRESHOLD = 50.0


def early_webrtc_hook_script() -> str:
    """Install before Meet loads so WebRTC peer connections are not missed."""
    return """
(() => {
  if (window.__gmeetEarlyAudioHook) return;
  window.__gmeetEarlyAudioHook = true;
  window.__gmeetPendingStreams = window.__gmeetPendingStreams || [];

  function enqueue(stream, label) {
    if (!stream || !stream.getAudioTracks) return;
    const tracks = stream.getAudioTracks();
    if (!tracks.length) return;
    if (tracks.every((t) => !t.enabled || t.readyState === "ended")) return;
    window.__gmeetPendingStreams.push({ stream, label: label || "early", ts: Date.now() });
    window.dispatchEvent(new CustomEvent("tempa-gmeet-audio-stream", { detail: { label } }));
  }

  function hookPc(pc) {
    if (!pc || pc.__gmeetHooked) return;
    pc.__gmeetHooked = true;
    pc.addEventListener("track", (ev) => {
      if (!ev.track || ev.track.kind !== "audio") return;
      const stream = (ev.streams && ev.streams[0]) || new MediaStream([ev.track]);
      enqueue(stream, "ontrack");
    });
  }

  const OrigPC = window.RTCPeerConnection;
  if (!OrigPC) return;

  window.RTCPeerConnection = function (...args) {
    const pc = new OrigPC(...args);
    hookPc(pc);
    return pc;
  };
  window.RTCPeerConnection.prototype = OrigPC.prototype;

  const origSetRemote = OrigPC.prototype.setRemoteDescription;
  OrigPC.prototype.setRemoteDescription = async function (...args) {
    const result = await origSetRemote.apply(this, args);
    try {
      (this.getReceivers?.() || []).forEach((receiver) => {
        if (receiver.track && receiver.track.kind === "audio") {
          enqueue(new MediaStream([receiver.track]), "receiver");
        }
      });
    } catch (_err) {}
    return result;
  };
})();
"""


def audio_capture_script(sample_rate: int, chunk_ms: int, debug: bool) -> str:
    return f"""
(() => {{
  if (window.__gmeetAudioCaptureRunning) return;
  window.__gmeetAudioCaptureRunning = true;
  window.__gmeetAudioCaptureStopped = false;
  window.__gmeetAttachedCount = 0;
  window.__gmeetLastRms = 0;

  const targetSampleRate = {sample_rate};
  const chunkMs = {chunk_ms};
  const chunkFrames = Math.max(1, Math.floor(targetSampleRate * chunkMs / 1000));

  const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const elementSources = new Map();
  const streamSources = new Map();
  let attachedCount = 0;
  const processor = audioCtx.createScriptProcessor(4096, 1, 1);
  const intervalIds = [];
  let sampleBuffer = [];
  let lastDebugTs = 0;
  const debugEnabled = {str(debug).lower()};

  function publishStats() {{
    window.__gmeetAttachedCount = attachedCount;
  }}

  function downsampleBuffer(buffer, inRate, outRate) {{
    if (outRate === inRate) return buffer;
    const ratio = inRate / outRate;
    const newLength = Math.floor(buffer.length / ratio);
    const result = new Float32Array(newLength);
    for (let i = 0; i < newLength; i++) {{
      const start = Math.floor(i * ratio);
      const end = Math.floor((i + 1) * ratio);
      let sum = 0;
      let count = 0;
      for (let j = start; j < end && j < buffer.length; j++) {{
        sum += buffer[j];
        count++;
      }}
      result[i] = count ? sum / count : 0;
    }}
    return result;
  }}

  function floatTo16BitPCM(float32) {{
    const output = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {{
      let s = Math.max(-1, Math.min(1, float32[i]));
      output[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }}
    return output;
  }}

  function base64FromBytes(bytes) {{
    let binary = "";
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
  }}

  function emitSamples(int16Samples, floatSamples) {{
    if (window.__gmeetAudioCaptureStopped) return;
    for (let i = 0; i < int16Samples.length; i++) sampleBuffer.push(int16Samples[i]);
    while (sampleBuffer.length >= chunkFrames) {{
      const chunk = sampleBuffer.splice(0, chunkFrames);
      const pcm = new Int16Array(chunk);
      try {{
        window.onAudioChunk({{ pcm16_b64: base64FromBytes(new Uint8Array(pcm.buffer)), sample_rate: targetSampleRate }});
      }} catch (_err) {{}}
    }}

    let sumSquares = 0;
    for (let i = 0; i < int16Samples.length; i++) sumSquares += int16Samples[i] * int16Samples[i];
    const rms = Math.sqrt(sumSquares / Math.max(1, int16Samples.length));
    window.__gmeetLastRms = rms;

    if (debugEnabled) {{
      const now = Date.now();
      if (now - lastDebugTs >= 1000) {{
        lastDebugTs = now;
        let peak = 0;
        for (let i = 0; i < int16Samples.length; i++) peak = Math.max(peak, Math.abs(int16Samples[i]));
        try {{
          window.onAudioDebug({{
            event: "rms",
            rms,
            peak,
            attached_count: attachedCount,
            audio_elements: document.querySelectorAll("audio").length,
            video_elements: document.querySelectorAll("video").length,
            audio_state: audioCtx.state,
          }});
        }} catch (_err) {{}}
      }}
    }}
  }}

  processor.onaudioprocess = (event) => {{
    if (window.__gmeetAudioCaptureStopped) return;
    const input = event.inputBuffer.getChannelData(0);
    const downsampled = downsampleBuffer(input, audioCtx.sampleRate, targetSampleRate);
    emitSamples(floatTo16BitPCM(downsampled), downsampled);
    event.outputBuffer.getChannelData(0).fill(0);
  }};
  processor.connect(audioCtx.destination);

  function attachStream(stream, label) {{
    if (!stream || streamSources.has(stream)) return;
    try {{
      const source = audioCtx.createMediaStreamSource(stream);
      source.connect(processor);
      streamSources.set(stream, source);
      attachedCount += 1;
      publishStats();
      if (debugEnabled) {{
        try {{
          window.onAudioDebug({{
            event: "attach_stream",
            label: label || "stream",
            attached_count: attachedCount,
            track_count: stream.getAudioTracks ? stream.getAudioTracks().length : 0,
          }});
        }} catch (_err) {{}}
      }}
    }} catch (err) {{
      console.debug("GMeet stream attach failed", err);
    }}
  }}

  function attachMediaElement(el) {{
    if (elementSources.has(el)) return;
    try {{
      if (el.srcObject) {{
        attachStream(el.srcObject, el.tagName.toLowerCase() + "_srcobject");
        elementSources.set(el, el.srcObject);
        return;
      }}
      if (el.paused) el.play().catch(() => {{}});
      const source = audioCtx.createMediaElementSource(el);
      source.connect(processor);
      elementSources.set(el, source);
      attachedCount += 1;
      publishStats();
    }} catch (err) {{
      console.debug("GMeet media element attach failed", err);
    }}
  }}

  function drainPendingStreams() {{
    const pending = window.__gmeetPendingStreams || [];
    window.__gmeetPendingStreams = [];
    for (const item of pending) {{
      if (item && item.stream) attachStream(item.stream, item.label || "pending");
    }}
  }}

  function hookPeerConnections() {{
    if (window.__gmeetPcHookedMain) return;
    window.__gmeetPcHookedMain = true;
    const OrigPC = window.RTCPeerConnection;
    if (!OrigPC) return;
    if (!window.__gmeetEarlyAudioHook) {{
      window.RTCPeerConnection = function (...args) {{
        const pc = new OrigPC(...args);
        pc.addEventListener("track", (ev) => {{
          if (!ev.track || ev.track.kind !== "audio") return;
          const stream = (ev.streams && ev.streams[0]) || new MediaStream([ev.track]);
          attachStream(stream, "ontrack");
        }});
        return pc;
      }};
      window.RTCPeerConnection.prototype = OrigPC.prototype;
    }}
    const origSetRemote = OrigPC.prototype.setRemoteDescription;
    if (!origSetRemote.__gmeetWrapped) {{
      OrigPC.prototype.setRemoteDescription = async function (...args) {{
        const result = await origSetRemote.apply(this, args);
        try {{
          (this.getReceivers?.() || []).forEach((receiver) => {{
            if (receiver.track && receiver.track.kind === "audio") {{
              attachStream(new MediaStream([receiver.track]), "receiver_main");
            }}
          }});
        }} catch (_err) {{}}
        return result;
      }};
      OrigPC.prototype.setRemoteDescription.__gmeetWrapped = true;
    }}
  }}

  function scan() {{
    document.querySelectorAll("audio, video").forEach(attachMediaElement);
    drainPendingStreams();
    publishStats();
    if (debugEnabled) {{
      try {{
        window.onAudioDebug({{
          event: "scan",
          audio_elements: document.querySelectorAll("audio").length,
          video_elements: document.querySelectorAll("video").length,
          attached_count: attachedCount,
          audio_state: audioCtx.state,
          last_rms: window.__gmeetLastRms,
        }});
      }} catch (_err) {{}}
    }}
  }}

  window.__gmeetForceRescan = scan;
  window.addEventListener("tempa-gmeet-audio-stream", () => scan());

  hookPeerConnections();
  scan();
  try {{
    const observer = new MutationObserver(() => scan());
    observer.observe(document.documentElement, {{ childList: true, subtree: true }});
  }} catch (_err) {{}}

  let scanDelay = 500;
  const scanLoop = () => {{
    scan();
    if (attachedCount === 0 && scanDelay < 5000) scanDelay = Math.min(5000, scanDelay + 500);
    intervalIds.push(setTimeout(scanLoop, scanDelay));
  }};
  scanLoop();

  function ensureRunning() {{
    if (audioCtx.state !== "running") audioCtx.resume().catch(() => {{}});
  }}
  ensureRunning();
  intervalIds.push(setInterval(ensureRunning, 2000));

  window.__gmeetStopAudioCapture = async () => {{
    if (window.__gmeetAudioCaptureStopped) return true;
    window.__gmeetAudioCaptureStopped = true;
    window.__gmeetAudioCaptureRunning = false;
    for (const id of intervalIds) {{
      clearTimeout(id);
      clearInterval(id);
    }}
    try {{
      processor.onaudioprocess = null;
      processor.disconnect();
    }} catch (_err) {{}}
    try {{
      for (const source of elementSources.values()) source.disconnect?.();
      elementSources.clear();
      for (const source of streamSources.values()) source.disconnect?.();
      streamSources.clear();
    }} catch (_err) {{}}
    try {{ await audioCtx.close(); }} catch (_err) {{}}
    return true;
  }};
}})();
"""


def audio_capture_stats_script() -> str:
    return """() => ({
  attached_count: window.__gmeetAttachedCount || 0,
  last_rms: window.__gmeetLastRms || 0,
  pending_streams: (window.__gmeetPendingStreams || []).length,
  audio_elements: document.querySelectorAll('audio').length,
  video_elements: document.querySelectorAll('video').length,
})"""


def pcm16_peak_rms(pcm: bytes, *, sample_stride: int = 16000 * 2 * 10) -> float:
    """Peak RMS across fixed-size PCM16 mono windows."""
    if len(pcm) < 4:
        return 0.0
    peak = 0.0
    for offset in range(0, len(pcm) - 2, sample_stride):
        chunk = pcm[offset : offset + sample_stride]
        if len(chunk) < 4:
            break
        samples = struct.unpack("<" + "h" * (len(chunk) // 2), chunk)
        rms = math.sqrt(sum(s * s for s in samples) / len(samples))
        peak = max(peak, rms)
    return peak


def pcm_file_peak_rms(path: str | Path, *, max_bytes: int = 32 * 1024 * 1024) -> float:
    data = Path(path).read_bytes()
    if len(data) > max_bytes:
        # Sample start, middle, and end for very long recordings.
        third = max_bytes // 3
        data = data[:third] + data[len(data) // 2 : len(data) // 2 + third] + data[-third:]
    return pcm16_peak_rms(data)


def is_silent_capture(peak_rms: float, duration_seconds: float) -> bool:
    return duration_seconds >= 60 and peak_rms < SILENT_CAPTURE_RMS_THRESHOLD


async def monitor_audio_capture_health(page, meeting_id: str) -> None:
    """Warn and rescan when remote audio is not being captured after admission."""
    import asyncio
    import logging

    log = logging.getLogger(__name__)
    healthy_rms = 15.0
    for attempt in range(10):
        await asyncio.sleep(30)
        try:
            stats = await page.evaluate(audio_capture_stats_script())
        except Exception:
            return
        attached = int(stats.get("attached_count") or 0)
        rms = float(stats.get("last_rms") or 0)
        if attached > 0 and rms >= healthy_rms:
            log.info("GMEET: audio capture healthy meeting=%s stats=%s", meeting_id, stats)
            return
        log.warning(
            "GMEET: low remote audio meeting=%s attempt=%s stats=%s",
            meeting_id,
            attempt + 1,
            stats,
        )
        try:
            await page.evaluate("() => { if (window.__gmeetForceRescan) window.__gmeetForceRescan(); }")
        except Exception:
            pass

