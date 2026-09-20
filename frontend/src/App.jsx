import React, { useState, useEffect, useCallback, useRef, memo } from 'react'
import axios from 'axios'
import {
  AlertTriangle, CheckCircle2, Clock, Zap, Shield, Activity,
  RefreshCw, Terminal, FileCode, DollarSign, Brain, Play,
  XCircle, AlertCircle, Loader2, Wifi, WifiOff,
  TrendingDown, List, ChevronDown, ChevronUp, Cpu, Globe, Database,
} from 'lucide-react'
import clsx from 'clsx'

// ─── API Configuration ────────────────────────────────────────────────────────
const API_BASE = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || ''
const api = axios.create({ baseURL: API_BASE, timeout: 20000 })
const POLL_INTERVAL_MS = 5000

// ─── Status Configuration ────────────────────────────────────────────────────
const STATUS_CONFIG = {
  TRIGGERED: {
    label: 'Triggered', color: 'text-amber-400',
    bg: 'bg-amber-500/10 border-amber-500/30', dot: 'bg-amber-400', step: 0, icon: AlertTriangle,
  },
  AUDITOR_DIAGNOSING: {
    label: 'Auditor Diagnosing', color: 'text-violet-400',
    bg: 'bg-violet-500/10 border-violet-500/30', dot: 'bg-violet-400', step: 1, icon: Brain,
  },
  PATCHER_DRAFTING: {
    label: 'Patcher Drafting', color: 'text-blue-400',
    bg: 'bg-blue-500/10 border-blue-500/30', dot: 'bg-blue-400', step: 2, icon: FileCode,
  },
  VALIDATOR_CHECKING: {
    label: 'Validator Checking', color: 'text-orange-400',
    bg: 'bg-orange-500/10 border-orange-500/30', dot: 'bg-orange-400', step: 3, icon: Shield,
  },
  AUTO_REMEDIATING: {
    label: 'Auto Remediating', color: 'text-teal-400',
    bg: 'bg-teal-500/10 border-teal-500/30', dot: 'bg-teal-400', step: 4, icon: Zap,
  },
  AUTO_REMEDIATED: {
    label: 'Auto Remediated', color: 'text-emerald-400',
    bg: 'bg-emerald-500/10 border-emerald-500/30', dot: 'bg-emerald-400', step: 5, icon: CheckCircle2,
  },
  ESCALATED_TO_SRE: {
    label: 'Escalated to SRE', color: 'text-red-400',
    bg: 'bg-red-500/10 border-red-500/30', dot: 'bg-red-400', step: 5, icon: AlertCircle,
  },
  ESCALATED: {
    label: 'Escalated', color: 'text-red-400',
    bg: 'bg-red-500/10 border-red-500/30', dot: 'bg-red-400', step: 5, icon: AlertCircle,
  },
  PIPELINE_ERROR: {
    label: 'Pipeline Error', color: 'text-red-400',
    bg: 'bg-red-500/10 border-red-500/30', dot: 'bg-red-400', step: 5, icon: XCircle,
  },
}

const PIPELINE_STAGES = [
  { key: 'TRIGGERED',          label: 'Alert Triggered',    icon: AlertTriangle, step: 0 },
  { key: 'AUDITOR_DIAGNOSING', label: 'Auditor Diagnosing', icon: Brain,         step: 1 },
  { key: 'PATCHER_DRAFTING',   label: 'Patcher Drafting',   icon: FileCode,      step: 2 },
  { key: 'VALIDATOR_CHECKING', label: 'Validator Checking', icon: Shield,        step: 3 },
  { key: 'AUTO_REMEDIATING',   label: 'Executing Fix',      icon: Zap,           step: 4 },
  { key: 'AUTO_REMEDIATED',    label: 'Incident Resolved',  icon: CheckCircle2,  step: 5 },
]

const TABS = [
  { id: 'logs',      label: 'CloudWatch Logs',    icon: Terminal   },
  { id: 'reasoning', label: 'Agent Reasoning',    icon: Brain      },
  { id: 'script',    label: 'Remediation Script', icon: FileCode   },
  { id: 'impact',    label: 'Cost Impact ₹',      icon: DollarSign },
]

const SEVERITY_COLORS = {
  P1: 'bg-red-500/20 text-red-300 border-red-500/40',
  P2: 'bg-orange-500/20 text-orange-300 border-orange-500/40',
  P3: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/40',
}

const ACTIVE_STATUSES = new Set([
  'TRIGGERED', 'AUDITOR_DIAGNOSING', 'PATCHER_DRAFTING', 'VALIDATOR_CHECKING', 'AUTO_REMEDIATING',
])

const TELEMETRY_LINES = [
  '{"source":"omnitrace.alert","detail-type":"OmniTraceIncident","region":"us-east-1"}',
  '[EventBridge] Event delivered to OmniTrace-Pipeline target ✓',
  '[StepFunctions] Execution started — state: AuditorDiagnosis',
  '[Bedrock] Converse API request → amazon.nova-pro-v1:0 | inputTokens: 842',
  '[AUDITOR] Parsing CloudWatch error logs — 10 lines ingested',
  '[AUDITOR] Root cause identified — financial impact calculated in ₹ INR',
  '[StepFunctions] Transition: AuditorDiagnosis → PatcherDrafting',
  '[Bedrock] Converse API request → amazon.nova-pro-v1:0 | inputTokens: 1247',
  '[PATCHER] Generating non-destructive AWS CLI remediation commands',
  '[PATCHER] Commands generated — rollback scripts included',
  '[StepFunctions] Transition: PatcherDrafting → ValidatorCheck',
  '[Bedrock] Converse API request → amazon.nova-pro-v1:0 | inputTokens: 1891',
  '[VALIDATOR] Running 8 safety checks on remediation plan',
  '[VALIDATOR] Verdict: EXECUTE — all checks passed',
  '[StepFunctions] Transition: ValidatorCheck → ExecuteRemediation',
  '[SelfHealer] Executing approved commands (simulated mode)',
  '[SelfHealer] All remediation steps completed — status: AUTO_REMEDIATED ✓',
  '[DynamoDB] Incident record updated — resolutionSummary persisted',
  '[CloudWatch] Metrics emitted: IncidentsAutoRemediated=1, CostSavedINR=173000',
]

// ─── Helpers ─────────────────────────────────────────────────────────────────
function formatINR(amount) {
  if (amount === undefined || amount === null) return '₹0'
  const n = Number(amount)
  if (isNaN(n)) return '₹0'
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(2)} Cr`
  if (n >= 100000)   return `₹${(n / 100000).toFixed(2)} L`
  if (n >= 1000)     return `₹${(n / 1000).toFixed(1)}K`
  return `₹${n.toLocaleString('en-IN')}`
}

function timeAgo(isoString) {
  if (!isoString) return ''
  const diff = Date.now() - new Date(isoString).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60)   return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  return `${Math.floor(s / 3600)}h ago`
}

function getStatusConfig(status) {
  return STATUS_CONFIG[status] || {
    label: status || 'Unknown', color: 'text-slate-400',
    bg: 'bg-slate-500/10 border-slate-500/30', dot: 'bg-slate-400', step: 0, icon: Clock,
  }
}

// Stable fingerprint for an incident — only fields that matter for rendering
function incidentFingerprint(inc) {
  if (!inc) return ''
  return `${inc.incidentId}|${inc.status}|${inc.auditorResult ? '1' : '0'}|${inc.patcherResult ? '1' : '0'}|${inc.validatorResult ? '1' : '0'}|${inc.resolutionSummary ? '1' : '0'}`
}

// ─── Telemetry Live Feed ──────────────────────────────────────────────────────
function TelemetryFeed({ incidentId, status }) {
  const [lines, setLines]   = useState([])
  const [cursor, setCursor] = useState(0)
  const containerRef = useRef(null)

  useEffect(() => {
    if (!ACTIVE_STATUSES.has(status)) return
    if (cursor >= TELEMETRY_LINES.length) return
    const t = setTimeout(() => {
      setLines(prev => [...prev, TELEMETRY_LINES[cursor]])
      setCursor(c => c + 1)
    }, 900 + Math.random() * 600)
    return () => clearTimeout(t)
  }, [cursor, status])

  useEffect(() => { setLines([]); setCursor(0) }, [incidentId])

  useEffect(() => {
    const el = containerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines])

  if (!ACTIVE_STATUSES.has(status) && lines.length === 0) return null

  return (
    <div ref={containerRef} className="mt-4 code-block max-h-56 overflow-y-auto">
      <div className="flex items-center gap-2 mb-3 pb-2 border-b border-white/5">
        <Loader2 size={13} className="text-brand-400 animate-spin" />
        <span className="text-xs text-brand-400 font-medium uppercase tracking-wide">
          Live EventBridge Telemetry Feed
        </span>
        <span className="ml-auto text-[10px] text-slate-500">us-east-1 · omnitrace.alert</span>
      </div>
      {lines.map((line, i) => (
        <div key={i} className="flex gap-3 leading-6 text-xs">
          <span className="text-slate-600 select-none shrink-0 w-5 text-right">{i + 1}</span>
          <span className={clsx(
            'break-all',
            line.startsWith('[EventBridge]') || line.startsWith('{"source"') ? 'text-amber-400' :
            line.startsWith('[Bedrock]')       ? 'text-violet-400' :
            line.startsWith('[AUDITOR]')       ? 'text-violet-300' :
            line.startsWith('[PATCHER]')       ? 'text-blue-400'   :
            line.startsWith('[VALIDATOR]')     ? 'text-orange-400' :
            line.startsWith('[SelfHealer]')    ? 'text-teal-400'   :
            line.startsWith('[DynamoDB]') || line.startsWith('[CloudWatch]') ? 'text-emerald-400' :
            line.startsWith('[StepFunctions]') ? 'text-cyan-400'   : 'text-slate-300',
          )}>
            {line}
          </span>
        </div>
      ))}
      {ACTIVE_STATUSES.has(status) && (
        <div className="flex gap-3 leading-6 text-xs mt-1">
          <span className="text-slate-600 select-none w-5 text-right">{lines.length + 1}</span>
          <span className="text-brand-400 cursor-blink">▋</span>
        </div>
      )}
    </div>
  )
}

// ─── Subcomponents ────────────────────────────────────────────────────────────
// memo: only re-renders when status string changes
const StatusBadge = memo(function StatusBadge({ status }) {
  const cfg  = getStatusConfig(status)
  const Icon = cfg.icon
  return (
    <span className={clsx('status-badge border', cfg.bg, cfg.color)}>
      <Icon size={12} />
      {cfg.label}
    </span>
  )
})

// memo: only re-renders when status string changes — kills the pipeline blink
const PipelineProgress = memo(function PipelineProgress({ status }) {
  const currentStep = getStatusConfig(status)?.step ?? 0
  const isError  = ['ESCALATED_TO_SRE', 'ESCALATED', 'PIPELINE_ERROR'].includes(status)
  const isActive = ACTIVE_STATUSES.has(status)

  return (
    <div className="flex items-center gap-1 w-full overflow-x-auto scrollbar-none py-2">
      {PIPELINE_STAGES.map((stage, idx) => {
        const Icon    = stage.icon
        const done    = currentStep > stage.step
        const active  = currentStep === stage.step
        const errored = isError && active

        return (
          <React.Fragment key={stage.key}>
            <div className={clsx(
              'flex flex-col items-center gap-1.5 min-w-[80px]',
              (done || active) ? 'opacity-100' : 'opacity-30',
            )}>
              <div className={clsx(
                'w-9 h-9 rounded-full flex items-center justify-center border-2',
                done              ? 'bg-emerald-500/20 border-emerald-500 text-emerald-400' : '',
                active && !errored ? 'bg-brand-500/20 border-brand-500 text-brand-400'     : '',
                errored            ? 'bg-red-500/20 border-red-500 text-red-400'            : '',
                !done && !active   ? 'bg-surface-600 border-surface-400 text-slate-500'     : '',
              )}>
                {done    ? <CheckCircle2 size={16} /> :
                 errored ? <XCircle size={16} /> :
                 active && isActive ? <Loader2 size={16} className="animate-spin" /> :
                 <Icon size={16} />}
              </div>
              <span className={clsx(
                'text-[10px] text-center leading-tight font-medium',
                done ? 'text-emerald-400' : active ? 'text-brand-400' : 'text-slate-500',
              )}>
                {stage.label}
              </span>
            </div>
            {idx < PIPELINE_STAGES.length - 1 && (
              <div className={clsx('flex-1 h-px min-w-[8px]', done ? 'bg-emerald-500/50' : 'bg-surface-400')} />
            )}
          </React.Fragment>
        )
      })}
    </div>
  )
})

function LogsTab({ incident }) {
  const logs  = incident?.errorLogs || ''
  const lines = logs.split('\n').filter(Boolean)
  const lineColor = (line) => {
    const u = line.toUpperCase()
    if (u.includes('[CRITICAL]')) return 'text-red-400'
    if (u.includes('[ERROR]'))    return 'text-orange-400'
    if (u.includes('[WARN]'))     return 'text-yellow-400'
    if (u.includes('[INFO]'))     return 'text-slate-300'
    return 'text-slate-400'
  }
  return (
    <div className="space-y-3">
      <div className="code-block max-h-80 overflow-y-auto">
        <div className="flex items-center gap-2 mb-3 pb-2 border-b border-white/5">
          <Terminal size={14} className="text-brand-400" />
          <span className="text-xs text-slate-400 font-medium">
            CloudWatch Logs — {incident?.service || 'unknown'} — {lines.length} lines
          </span>
        </div>
        {lines.length === 0 ? (
          <p className="text-slate-500 text-xs">No logs available yet.</p>
        ) : (
          lines.map((line, i) => (
            <div key={i} className="flex gap-3 leading-6">
              <span className="text-surface-400 select-none w-8 shrink-0 text-right">{i + 1}</span>
              <span className={clsx('break-all text-xs', lineColor(line))}>{line}</span>
            </div>
          ))
        )}
      </div>
      <TelemetryFeed incidentId={incident?.incidentId} status={incident?.status} />
    </div>
  )
}

function ReasoningTab({ incident, agentTrail }) {
  const [openAgent, setOpenAgent] = useState('AUDITOR')
  const agents = [
    {
      key: 'AUDITOR', label: 'AUDITOR', icon: Brain,
      color: 'text-violet-400', borderColor: 'border-violet-500/30',
      data: incident?.auditorResult || agentTrail?.find(t => t.agentRole === 'AUDITOR')?.agentPayload,
    },
    {
      key: 'PATCHER', label: 'PATCHER', icon: FileCode,
      color: 'text-blue-400', borderColor: 'border-blue-500/30',
      data: incident?.patcherResult || agentTrail?.find(t => t.agentRole === 'PATCHER')?.agentPayload,
    },
    {
      key: 'VALIDATOR', label: 'VALIDATOR', icon: Shield,
      color: 'text-orange-400', borderColor: 'border-orange-500/30',
      data: incident?.validatorResult || agentTrail?.find(t => t.agentRole === 'VALIDATOR')?.agentPayload,
    },
  ]

  return (
    <div className="space-y-3">
      {agents.map(agent => {
        const Icon      = agent.icon
        const isOpen    = openAgent === agent.key
        const data      = agent.data
        const isPending = !data && ACTIVE_STATUSES.has(incident?.status)
        return (
          <div key={agent.key} className={clsx('glass-card border overflow-hidden', agent.borderColor)}>
            <button
              onClick={() => setOpenAgent(isOpen ? null : agent.key)}
              className="w-full flex items-center justify-between p-4 text-left hover:bg-white/[0.02] transition-colors"
            >
              <div className="flex items-center gap-3">
                <Icon size={16} className={agent.color} />
                <span className={clsx('font-mono text-sm font-semibold', agent.color)}>{agent.label}</span>
                {data ? (
                  <span className="text-xs text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full">Complete</span>
                ) : isPending ? (
                  <span className="flex items-center gap-1.5 text-xs text-slate-400">
                    <Loader2 size={11} className="animate-spin" /> Processing…
                  </span>
                ) : (
                  <span className="text-xs text-slate-500">Pending</span>
                )}
              </div>
              {isOpen ? <ChevronUp size={14} className="text-slate-400" /> : <ChevronDown size={14} className="text-slate-400" />}
            </button>
            {isOpen && (
              <div className="border-t border-white/5 p-4 space-y-4">
                {!data ? (
                  <div className="flex items-center gap-3 py-2">
                    {isPending && <Loader2 size={14} className="animate-spin text-brand-400 shrink-0" />}
                    <p className="text-slate-500 text-sm">
                      {isPending ? `${agent.label} is actively processing this incident via Bedrock Nova Pro…` : `Waiting for ${agent.label} to complete…`}
                    </p>
                  </div>
                ) : (
                  <>
                    {data.reasoning_chain && (
                      <div>
                        <p className="text-xs text-slate-400 uppercase tracking-wide mb-2 font-semibold">Reasoning Chain</p>
                        <div className="space-y-1.5">
                          {data.reasoning_chain.map((step, i) => (
                            <div key={i} className="reasoning-item">
                              <span className="text-brand-400 font-mono text-xs shrink-0 pt-0.5">{String(i + 1).padStart(2, '0')}</span>
                              <span className="text-slate-300 text-sm">{step}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {agent.key === 'AUDITOR' && data.root_cause && (
                      <div className="space-y-2">
                        <div className="p-3 rounded-lg bg-violet-500/5 border border-violet-500/20">
                          <p className="text-xs text-violet-400 font-semibold mb-1">Root Cause</p>
                          <p className="text-sm text-slate-200">{data.root_cause}</p>
                        </div>
                        <div className="grid grid-cols-2 gap-2 text-xs">
                          <div className="p-2.5 rounded-lg bg-surface-700"><span className="text-slate-400">Category</span><p className="text-slate-100 font-mono mt-0.5">{data.error_category || '—'}</p></div>
                          <div className="p-2.5 rounded-lg bg-surface-700"><span className="text-slate-400">Blast Radius</span><p className="text-slate-100 font-mono mt-0.5">{data.blast_radius || '—'}</p></div>
                          <div className="p-2.5 rounded-lg bg-surface-700"><span className="text-slate-400">Confidence</span><p className="text-emerald-400 font-mono mt-0.5">{data.confidence_score ? `${(data.confidence_score * 100).toFixed(0)}%` : '—'}</p></div>
                          <div className="p-2.5 rounded-lg bg-surface-700"><span className="text-slate-400">Downtime Est.</span><p className="text-amber-400 font-mono mt-0.5">{data.estimated_downtime_minutes ? `${data.estimated_downtime_minutes} min` : '—'}</p></div>
                        </div>
                      </div>
                    )}
                    {agent.key === 'PATCHER' && data.remediation_strategy && (
                      <div className="p-3 rounded-lg bg-blue-500/5 border border-blue-500/20">
                        <p className="text-xs text-blue-400 font-semibold mb-1">Strategy</p>
                        <p className="text-sm text-slate-200">{data.remediation_strategy}</p>
                      </div>
                    )}
                    {agent.key === 'VALIDATOR' && (
                      <div className={clsx('p-3 rounded-lg border flex items-center gap-3',
                        data.verdict === 'EXECUTE' ? 'bg-emerald-500/5 border-emerald-500/30' : 'bg-red-500/5 border-red-500/30',
                      )}>
                        {data.verdict === 'EXECUTE'
                          ? <CheckCircle2 size={18} className="text-emerald-400 shrink-0" />
                          : <XCircle      size={18} className="text-red-400 shrink-0" />}
                        <div>
                          <p className={clsx('font-bold text-sm', data.verdict === 'EXECUTE' ? 'text-emerald-400' : 'text-red-400')}>
                            VERDICT: {data.verdict}
                          </p>
                          {data.veto_reason && data.veto_reason !== 'null' && (
                            <p className="text-xs text-slate-300 mt-0.5">{data.veto_reason}</p>
                          )}
                        </div>
                      </div>
                    )}
                    {agent.key === 'VALIDATOR' && data.safety_checks && (
                      <div>
                        <p className="text-xs text-slate-400 uppercase tracking-wide mb-2 font-semibold">Safety Checks</p>
                        <div className="space-y-1.5">
                          {data.safety_checks.map((check, i) => (
                            <div key={i} className="flex items-start gap-2 p-2.5 rounded-lg bg-surface-700/50 text-xs">
                              {check.result === 'PASS'
                                ? <CheckCircle2 size={12} className="text-emerald-400 mt-0.5 shrink-0" />
                                : <XCircle      size={12} className="text-red-400 mt-0.5 shrink-0" />}
                              <div>
                                <span className="text-slate-200 font-medium">{check.check}</span>
                                {check.detail && <p className="text-slate-400 mt-0.5">{check.detail}</p>}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function ScriptTab({ incident, agentTrail }) {
  const [copied, setCopied] = useState(false)
  const resolution    = incident?.resolutionSummary
  const patcherResult = incident?.patcherResult || agentTrail?.find(t => t.agentRole === 'PATCHER')?.agentPayload
  const script   = resolution?.mitigationScript
  const commands = patcherResult?.commands || []
  const handleCopy = async () => {
    if (!script) return
    await navigator.clipboard.writeText(script)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <div className="space-y-4">
      {commands.length > 0 && (
        <div>
          <h4 className="text-xs text-slate-400 uppercase tracking-wide font-semibold mb-3">Approved Commands ({commands.length})</h4>
          <div className="space-y-2">
            {commands.map((cmd, i) => (
              <div key={i} className="glass-card p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-brand-400 bg-brand-500/10 px-2 py-0.5 rounded">Step {cmd.step}</span>
                    <span className={clsx('text-xs px-2 py-0.5 rounded font-medium',
                      cmd.risk_level === 'LOW' ? 'bg-emerald-500/10 text-emerald-400' :
                      cmd.risk_level === 'MEDIUM' ? 'bg-yellow-500/10 text-yellow-400' : 'bg-red-500/10 text-red-400',
                    )}>{cmd.risk_level || 'LOW'} risk</span>
                  </div>
                  <span className="text-xs text-slate-500">~{cmd.estimated_duration_seconds}s</span>
                </div>
                <p className="text-xs text-slate-300">{cmd.description}</p>
                <div className="code-block py-2 px-3">
                  <span className="text-emerald-400">$ </span>
                  <span className="text-slate-200 break-all text-xs">{cmd.command}</span>
                </div>
                {cmd.rollback_command && (
                  <div className="code-block py-2 px-3 opacity-50">
                    <span className="text-yellow-400"># rollback: </span>
                    <span className="text-slate-400 break-all text-xs">{cmd.rollback_command}</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
      {script ? (
        <div>
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-xs text-slate-400 uppercase tracking-wide font-semibold">Generated Bash Script</h4>
            <button onClick={handleCopy} className="btn-secondary text-xs py-1.5 px-3">
              {copied ? <CheckCircle2 size={12} /> : <FileCode size={12} />}
              {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>
          <pre className="code-block max-h-64 overflow-y-auto text-xs text-slate-300 leading-6">{script}</pre>
        </div>
      ) : (
        <div className="glass-card p-8 text-center">
          <FileCode size={32} className="text-slate-600 mx-auto mb-3" />
          <p className="text-slate-400 text-sm">
            {ACTIVE_STATUSES.has(incident?.status)
              ? 'Patcher is generating remediation commands via Bedrock Nova Pro…'
              : 'No remediation script available for this incident.'}
          </p>
          {ACTIVE_STATUSES.has(incident?.status) && <Loader2 size={20} className="animate-spin text-brand-400 mx-auto mt-3" />}
        </div>
      )}
    </div>
  )
}

function ImpactTab({ incident, agentTrail }) {
  const auditorResult = incident?.auditorResult || agentTrail?.find(t => t.agentRole === 'AUDITOR')?.agentPayload
  const resolution = incident?.resolutionSummary
  const financial  = auditorResult?.financial_impact_inr || {}
  const impact     = resolution?.impactMetrics || {}
  const metrics = [
    { label: 'Total Incident Cost',      value: formatINR(financial.total),                                    sub: 'Estimated loss if unresolved',      icon: AlertTriangle, color: 'text-red-400',    iconBg: 'bg-red-500/10'    },
    { label: 'Revenue Loss Prevented',   value: formatINR(financial.revenue_loss ?? impact.revenueProtectedINR), sub: 'Downtime revenue impact averted',   icon: TrendingDown,  color: 'text-emerald-400', iconBg: 'bg-emerald-500/10' },
    { label: 'SLA Penalty Avoided',      value: formatINR(financial.sla_penalty ?? impact.slaPenaltyAvoidedINR), sub: 'P1 breach penalty prevented',      icon: Shield,        color: 'text-blue-400',   iconBg: 'bg-blue-500/10'   },
    { label: 'Engineering Cost Saved',   value: formatINR(financial.engineering_cost),                          sub: `~${impact.engineeringHoursSaved || 2} eng-hrs @ ₹3,500/hr`, icon: Cpu, color: 'text-violet-400', iconBg: 'bg-violet-500/10' },
    { label: 'Downtime Prevented',       value: `${impact.downtimePreventedMinutes || auditorResult?.estimated_downtime_minutes || 0} min`, sub: 'Customer-facing downtime averted', icon: Clock, color: 'text-amber-400', iconBg: 'bg-amber-500/10' },
    { label: 'Auto-Healed By',           value: resolution?.resolvedBy || '—',                                 sub: resolution?.resolvedAt ? `at ${new Date(resolution.resolvedAt).toLocaleTimeString()}` : 'Pending', icon: Zap, color: 'text-brand-400', iconBg: 'bg-brand-500/10' },
  ]
  if (!auditorResult) {
    return (
      <div className="glass-card p-8 text-center">
        <DollarSign size={32} className="text-slate-600 mx-auto mb-3" />
        <p className="text-slate-400 text-sm">
          {ACTIVE_STATUSES.has(incident?.status)
            ? 'AUDITOR is calculating financial impact in ₹ INR via Bedrock Nova Pro…'
            : 'Cost analysis not available for this incident.'}
        </p>
        {ACTIVE_STATUSES.has(incident?.status) && <Loader2 size={20} className="animate-spin text-brand-400 mx-auto mt-3" />}
      </div>
    )
  }
  return (
    <div className="space-y-4">
      {resolution && (
        <div className="p-4 rounded-xl border border-emerald-500/30 bg-gradient-to-r from-emerald-950/40 to-teal-950/40">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-emerald-500/20 flex items-center justify-center">
              <CheckCircle2 size={20} className="text-emerald-400" />
            </div>
            <div>
              <p className="text-xs text-emerald-400/70 uppercase tracking-wide font-semibold">Total Savings from Auto-Remediation (₹ INR)</p>
              <p className="text-2xl font-bold text-emerald-400 font-mono">{formatINR(impact.costSavedINR ?? financial.total)}</p>
            </div>
          </div>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        {metrics.map((metric, i) => {
          const Icon = metric.icon
          return (
            <div key={i} className="metric-card">
              <div className="flex items-center gap-2">
                <div className={clsx('w-7 h-7 rounded-lg flex items-center justify-center', metric.iconBg)}>
                  <Icon size={14} className={metric.color} />
                </div>
                <span className="text-xs text-slate-400">{metric.label}</span>
              </div>
              <p className={clsx('text-xl font-bold font-mono', metric.color)}>{metric.value}</p>
              <p className="text-xs text-slate-500">{metric.sub}</p>
            </div>
          )
        })}
      </div>
      {resolution?.executionLog && resolution.executionLog.length > 0 && (
        <div>
          <p className="text-xs text-slate-400 uppercase tracking-wide font-semibold mb-2">Execution Summary</p>
          <div className="flex gap-3">
            <div className="metric-card flex-1 text-center"><p className="text-2xl font-bold text-emerald-400 font-mono">{resolution.commandsSucceeded}</p><p className="text-xs text-slate-400">Commands OK</p></div>
            <div className="metric-card flex-1 text-center"><p className="text-2xl font-bold text-red-400 font-mono">{resolution.commandsFailed}</p><p className="text-xs text-slate-400">Commands Failed</p></div>
            <div className="metric-card flex-1 text-center"><p className="text-2xl font-bold text-brand-400 font-mono">{(resolution.totalDurationMs / 1000).toFixed(1)}s</p><p className="text-xs text-slate-400">Total Time</p></div>
          </div>
        </div>
      )}
    </div>
  )
}

// memo: only re-renders when incidentId or isSelected changes — not on every poll
const IncidentCard = memo(function IncidentCard({ incident, isSelected, onClick }) {
  const cfg    = getStatusConfig(incident.status)
  const Icon   = cfg.icon
  return (
    <button
      onClick={() => onClick(incident)}
      className={clsx(
        'w-full text-left p-4 rounded-xl border hover:border-brand-500/40',
        isSelected ? 'border-brand-500/50 bg-brand-950/20' : 'border-white/5 bg-surface-700/30 hover:bg-surface-700/60',
      )}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 bg-surface-600">
            <Icon size={13} className={cfg.color} />
          </div>
          <span className="text-xs font-mono text-slate-300 truncate">{incident.incidentId}</span>
        </div>
        {incident.severity && (
          <span className={clsx('text-[10px] px-1.5 py-0.5 rounded border font-bold shrink-0', SEVERITY_COLORS[incident.severity] || SEVERITY_COLORS.P3)}>
            {incident.severity}
          </span>
        )}
      </div>
      <p className="text-xs text-slate-300 mb-2 truncate font-medium">{incident.service || 'Unknown Service'}</p>
      <div className="flex items-center justify-between">
        <StatusBadge status={incident.status} />
        <span className="text-[10px] text-slate-500">{timeAgo(incident.timestamp)}</span>
      </div>
    </button>
  )
})

// memo: only re-renders when connected changes
const ConnectionStatus = memo(function ConnectionStatus({ connected }) {
  return (
    <div className={clsx(
      'flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full',
      connected ? 'text-emerald-400 bg-emerald-500/10' : 'text-red-400 bg-red-500/10',
    )}>
      {connected ? <Wifi size={11} /> : <WifiOff size={11} />}
      {connected ? 'Live' : 'Offline'}
    </div>
  )
})

// ─── Main App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [incidents,        setIncidents]        = useState([])
  const [selectedIncident, setSelectedIncident] = useState(null)
  const [agentTrail,       setAgentTrail]       = useState([])
  const [activeTab,        setActiveTab]        = useState('logs')
  const [triggering,       setTriggering]       = useState(false)
  const [loading,          setLoading]          = useState(true)
  const [connected,        setConnected]        = useState(true)
  const [triggerError,     setTriggerError]     = useState(null)
  const [triggerSuccess,   setTriggerSuccess]   = useState(null)

  const selectedIdRef   = useRef(null)
  const isPollActiveRef = useRef(false)
  const pollTimerRef    = useRef(null)
  // Track fingerprints so we only setState when data actually changed
  const incidentsFingerprintRef = useRef('')
  const selectedFingerprintRef  = useRef('')

  useEffect(() => {
    selectedIdRef.current = selectedIncident?.incidentId
  }, [selectedIncident?.incidentId])

  // ── Fetch all incidents list ────────────────────────────────────────────
  const fetchIncidents = useCallback(async () => {
    try {
      const { data } = await api.get('/api/incidents')
      const list = data.incidents || []

      // Only update incidents array if something actually changed
      const newFp = list.map(i => `${i.incidentId}:${i.status}`).join(',')
      if (newFp !== incidentsFingerprintRef.current) {
        incidentsFingerprintRef.current = newFp
        setIncidents(list)
      }

      setConnected(true)

      // Only update selectedIncident from list if fingerprint changed
      const currentId = selectedIdRef.current
      if (currentId) {
        const updated = list.find(i => i.incidentId === currentId)
        if (updated) {
          const fp = incidentFingerprint(updated)
          if (fp !== selectedFingerprintRef.current) {
            selectedFingerprintRef.current = fp
            setSelectedIncident(updated)
          }
        }
      }
    } catch {
      setConnected(false)
    } finally {
      setLoading(false)
    }
  }, [])

  // ── Fetch single incident detail (only called on select or manual refresh) ──
  const fetchIncidentDetail = useCallback(async (incidentId) => {
    try {
      const { data } = await api.get(`/api/incidents/${incidentId}`)
      if (data.incident) {
        const fp = incidentFingerprint(data.incident)
        if (fp !== selectedFingerprintRef.current) {
          selectedFingerprintRef.current = fp
          setSelectedIncident(data.incident)
        }
      }
      setAgentTrail(prev => {
        const next = data.agentTrail || []
        return prev.length !== next.length ? next : prev
      })
    } catch (err) {
      console.error('Failed to fetch incident detail:', err)
    }
  }, [])

  // ── Select incident ────────────────────────────────────────────────────
  const handleSelectIncident = useCallback((incident) => {
    selectedFingerprintRef.current = incidentFingerprint(incident)
    setSelectedIncident(incident)
    setAgentTrail([])
    setActiveTab('logs')
    fetchIncidentDetail(incident.incidentId)
  }, [fetchIncidentDetail])

  // ── Trigger simulation ─────────────────────────────────────────────────
  const handleTrigger = async () => {
    setTriggering(true)
    setTriggerError(null)
    setTriggerSuccess(null)
    try {
      const { data } = await api.post('/api/trigger', { triggeredBy: 'UI_SIMULATION' })
      setTriggerSuccess(`Incident ${data.incidentId} created — pipeline starting`)
      if (data.incidentId) {
        const newInc = {
          incidentId: data.incidentId, status: 'TRIGGERED',
          service: data.service, severity: data.severity, timestamp: data.timestamp,
        }
        selectedFingerprintRef.current = incidentFingerprint(newInc)
        setSelectedIncident(newInc)
        setAgentTrail([])
        setActiveTab('logs')
        fetchIncidents()
        setTimeout(() => fetchIncidentDetail(data.incidentId), 1500)
      }
      setTimeout(() => setTriggerSuccess(null), 5000)
    } catch (err) {
      const msg = err.response?.data?.error || err.message || 'Failed to trigger simulation'
      setTriggerError(msg)
      setTimeout(() => setTriggerError(null), 6000)
    } finally {
      setTriggering(false)
    }
  }

  // ── Poll — only fetchIncidents; fetchIncidentDetail only on manual select/refresh ──
  const runPollCycle = useCallback(async () => {
    if (isPollActiveRef.current) return
    isPollActiveRef.current = true
    try {
      await fetchIncidents()
    } finally {
      isPollActiveRef.current = false
    }
  }, [fetchIncidents])

  useEffect(() => {
    runPollCycle()
    pollTimerRef.current = setInterval(runPollCycle, POLL_INTERVAL_MS)
    return () => clearInterval(pollTimerRef.current)
  }, [runPollCycle])

  const activeIncidents   = incidents.filter(i => ACTIVE_STATUSES.has(i.status))
  const resolvedIncidents = incidents.filter(i => !ACTIVE_STATUSES.has(i.status))
  const isTerminal = selectedIncident && !ACTIVE_STATUSES.has(selectedIncident.status)

  return (
    <div className="min-h-screen bg-surface-900 bg-grid-pattern bg-grid">

      {/* ── Header ── */}
      <header className="sticky top-0 z-50 border-b border-white/5 bg-surface-900/90 backdrop-blur-sm">
        <div className="max-w-screen-xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 shrink-0">
            <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center">
              <Activity size={18} className="text-white" />
            </div>
            <div>
              <span className="text-base font-bold text-white tracking-tight">OmniTrace</span>
              <span className="hidden sm:inline text-xs text-slate-500 ml-2">Autonomous Cloud Incident Triage</span>
            </div>
          </div>
          <div className="hidden md:flex items-center gap-5 text-xs">
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-red-400" />
              <span className="text-slate-400">{activeIncidents.length} Active</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              <span className="text-slate-400">{resolvedIncidents.length} Resolved</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <ConnectionStatus connected={connected} />
            <button onClick={handleTrigger} disabled={triggering} className="btn-primary text-sm">
              {triggering ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
              <span className="hidden sm:inline">{triggering ? 'Triggering…' : 'Trigger Incident'}</span>
              <span className="sm:hidden">{triggering ? '…' : 'Trigger'}</span>
            </button>
          </div>
        </div>
      </header>

      {/* ── Toast notifications ── */}
      <div className="fixed top-16 right-4 z-50 space-y-2 w-80 max-w-[calc(100vw-2rem)]">
        {triggerSuccess && (
          <div className="flex items-start gap-3 p-3 rounded-lg bg-emerald-950 border border-emerald-500/40 text-sm text-emerald-300 animate-slide-up shadow-xl">
            <CheckCircle2 size={16} className="shrink-0 mt-0.5 text-emerald-400" />{triggerSuccess}
          </div>
        )}
        {triggerError && (
          <div className="flex items-start gap-3 p-3 rounded-lg bg-red-950 border border-red-500/40 text-sm text-red-300 animate-slide-up shadow-xl">
            <XCircle size={16} className="shrink-0 mt-0.5 text-red-400" />{triggerError}
          </div>
        )}
      </div>

      {/* ── Main layout ── */}
      <main className="max-w-screen-xl mx-auto px-4 sm:px-6 py-6">
        <div className="flex gap-6">

          {/* ── Left Sidebar ── */}
          <aside className="w-72 shrink-0 hidden lg:flex flex-col gap-4">
            <div className="glass-card p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <AlertTriangle size={14} className="text-red-400" />
                  <span className="text-xs font-semibold text-slate-300 uppercase tracking-wide">Active</span>
                  <span className="text-xs bg-red-500/20 text-red-400 px-1.5 py-0.5 rounded-full font-bold">{activeIncidents.length}</span>
                </div>
              </div>
              {loading ? (
                <div className="space-y-2">
                  {[1, 2].map(i => <div key={i} className="h-20 rounded-xl bg-surface-700/40 animate-pulse" />)}
                </div>
              ) : activeIncidents.length === 0 ? (
                <div className="py-6 text-center">
                  <CheckCircle2 size={24} className="text-emerald-400/50 mx-auto mb-2" />
                  <p className="text-xs text-slate-500">All systems operational</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {activeIncidents.map(inc => (
                    <IncidentCard
                      key={inc.incidentId}
                      incident={inc}
                      isSelected={selectedIncident?.incidentId === inc.incidentId}
                      onClick={handleSelectIncident}
                    />
                  ))}
                </div>
              )}
            </div>
            {resolvedIncidents.length > 0 && (
              <div className="glass-card p-4">
                <div className="flex items-center gap-2 mb-3">
                  <List size={14} className="text-slate-400" />
                  <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Recent</span>
                  <span className="text-xs bg-surface-500 text-slate-400 px-1.5 py-0.5 rounded-full font-bold">{resolvedIncidents.length}</span>
                </div>
                <div className="space-y-2 max-h-80 overflow-y-auto scrollbar-none">
                  {resolvedIncidents.slice(0, 6).map(inc => (
                    <IncidentCard
                      key={inc.incidentId}
                      incident={inc}
                      isSelected={selectedIncident?.incidentId === inc.incidentId}
                      onClick={handleSelectIncident}
                    />
                  ))}
                </div>
              </div>
            )}
          </aside>

          {/* ── Main Content ── */}
          <div className="flex-1 min-w-0 space-y-5">

            {!selectedIncident && !loading && (
              <div className="glass-card p-16 text-center animate-fade-in">
                <div className="w-16 h-16 rounded-full bg-brand-500/10 flex items-center justify-center mx-auto mb-4">
                  <Activity size={32} className="text-brand-400" />
                </div>
                <h2 className="text-xl font-bold text-white mb-2">OmniTrace is Standing By</h2>
                <p className="text-slate-400 text-sm max-w-md mx-auto mb-6">
                  Autonomous cloud incident triage powered by Amazon Bedrock Nova Pro.
                  Trigger a simulated incident to watch the AI pipeline in action.
                  All financial impact shown in ₹ INR.
                </p>
                <button onClick={handleTrigger} disabled={triggering} className="btn-primary">
                  {triggering ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
                  {triggering ? 'Triggering…' : 'Trigger Simulated Cloud Incident'}
                </button>
              </div>
            )}

            {selectedIncident && (
              <>
                {/* Incident header — keyed by incidentId so it only remounts on new incident */}
                <div key={`header-${selectedIncident.incidentId}`} className="glass-card p-5">
                  <div className="flex items-start justify-between gap-4 mb-4">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        <span className="font-mono text-xs text-slate-400">{selectedIncident.incidentId}</span>
                        {selectedIncident.severity && (
                          <span className={clsx('text-xs px-2 py-0.5 rounded border font-bold', SEVERITY_COLORS[selectedIncident.severity] || SEVERITY_COLORS.P3)}>
                            {selectedIncident.severity}
                          </span>
                        )}
                      </div>
                      <h2 className="text-lg font-bold text-white truncate">{selectedIncident.service}</h2>
                      <p className="text-xs text-slate-400 mt-0.5">
                        {selectedIncident.errorType}
                        {selectedIncident.description && ` — ${selectedIncident.description}`}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <StatusBadge status={selectedIncident.status} />
                      {!isTerminal && (
                        <button onClick={() => fetchIncidentDetail(selectedIncident.incidentId)} className="btn-secondary py-1.5 px-2.5" title="Refresh">
                          <RefreshCw size={13} />
                        </button>
                      )}
                    </div>
                  </div>
                  <PipelineProgress status={selectedIncident.status} />
                </div>

                {/* Detail tabs */}
                <div className="glass-card p-5">
                  <div className="flex items-center gap-1.5 mb-5 overflow-x-auto scrollbar-none">
                    {TABS.map(tab => {
                      const Icon = tab.icon
                      return (
                        <button
                          key={tab.id}
                          onClick={() => setActiveTab(tab.id)}
                          className={clsx('tab-button flex items-center gap-2 whitespace-nowrap', activeTab === tab.id ? 'tab-button-active' : 'tab-button-inactive')}
                        >
                          <Icon size={13} />{tab.label}
                        </button>
                      )
                    })}
                  </div>
                  {activeTab === 'logs'      && <LogsTab      incident={selectedIncident} />}
                  {activeTab === 'reasoning' && <ReasoningTab incident={selectedIncident} agentTrail={agentTrail} />}
                  {activeTab === 'script'    && <ScriptTab    incident={selectedIncident} agentTrail={agentTrail} />}
                  {activeTab === 'impact'    && <ImpactTab    incident={selectedIncident} agentTrail={agentTrail} />}
                </div>
              </>
            )}
          </div>
        </div>
      </main>

      {/* ── Footer ── */}
      <footer className="border-t border-white/5 mt-8 py-4">
        <div className="max-w-screen-xl mx-auto px-4 sm:px-6 flex items-center justify-between text-xs text-slate-500">
          <div className="flex items-center gap-4">
            <span>OmniTrace v1.0</span>
            <span className="hidden sm:inline">Powered by Amazon Bedrock Nova Pro + Step Functions</span>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5"><Database size={11} className="text-slate-600" /><span>DynamoDB</span></div>
            <div className="flex items-center gap-1.5"><Globe size={11} className="text-slate-600" /><span>EventBridge</span></div>
            <div className="flex items-center gap-1.5"><Cpu size={11} className="text-slate-600" /><span>Nova Pro · ₹ INR</span></div>
          </div>
        </div>
      </footer>
    </div>
  )
}
