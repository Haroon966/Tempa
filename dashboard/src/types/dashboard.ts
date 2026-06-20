export type HealthStatus = "healthy" | "degraded" | "unhealthy" | "connected" | "disconnected" | "error"

export interface DashboardPayload {
  generated_at: string
  overall: {
    status: HealthStatus
    healthy: number
    degraded: number
    unhealthy: number
    total_components: number
  }
  connections: Record<string, ConnectionInfo>
  agents: AgentInfo[]
  components: ComponentInfo[]
  flows: FlowInfo[]
  data: DataStats
  calendar: {
    upcoming: CalendarEvent[]
    triggerable_now: { summary: string; meet_url: string | null; start: string }[]
    poll_interval_seconds: number
  }
  whatsapp: {
    recent_messages: { from: string; text: string; id: string }[]
  }
  meetings: MeetingRecord[]
  recent_activity: ActivityEvent[]
  pending_actions?: PendingActionSummary[]
  active_tasks?: TaskSummary[]
  environment: {
    data_dir: string
    evolution_api_url: string
    tempa_version: string
  }
}

export interface ConnectionInfo {
  status?: string
  connected?: boolean
  credentials_configured?: boolean
  email_address?: string
  detail?: string
  chunks?: number
  collection?: string
  path?: string
  port?: number
  reachable?: boolean
  reply?: string
  error?: unknown
  status_code?: number
  raw?: unknown
}

export interface AgentInfo {
  id: string
  name: string
  role: string
  model_category: string
  status: HealthStatus
}

export interface ComponentInfo {
  id: string
  name: string
  category: string
  status: HealthStatus
  message: string
}

export interface FlowInfo {
  id: string
  name: string
  status: HealthStatus
  description: string
  steps: { name: string; status: HealthStatus }[]
}

export interface DataStats {
  rag_chunks: number
  meetings_count: number
  chat_sessions_count?: number
  vector_db_path: string
  vector_db_bytes: number
  meetings_path: string
  meetings_bytes: number
  sessions_path: string
  db_path: string
  playwright_installed: boolean
}

export interface CalendarEvent {
  id: string
  summary: string
  start: string
  meet_url: string | null
  has_meet: boolean
}

export interface MeetingRecord {
  id: string
  title?: string
  meet_link?: string
  started_at?: string
  ended_at?: string
  participants?: string[]
}

export interface ActivityEvent {
  agent: string
  action: string
  detail?: string
  timestamp: string
  notification_type?: string
  pending_action_id?: string
  task_id?: string
  title?: string
  body?: string
}

export interface PendingActionSummary {
  id: string
  type: string
  title?: string
  status?: string
  created_at?: string
  payload?: Record<string, unknown>
}

export interface TaskSummary {
  id: string
  user_message?: string
  status?: string
  subtasks?: { agent: string; task: string; status: string }[]
}
