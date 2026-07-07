/** Module-level flag so layout can pause dashboard polling during agent streaming. */
let agentStreaming = false

export function setAgentStreaming(streaming: boolean) {
  agentStreaming = streaming
}

export function isAgentStreaming() {
  return agentStreaming
}
