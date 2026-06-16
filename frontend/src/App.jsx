import React, { useState, useEffect, useRef } from "react";
import { 
  Activity, CheckCircle2, AlertTriangle, Clock, History, Cpu, ShieldAlert, Check, X, Play, RefreshCw, Layers
} from "lucide-react";

const API_BASE_URL = "http://localhost:8020";
const WS_BASE_URL = "ws://localhost:8020";

const getDynamicAgentOrder = (liveAgentProgress, incidentDetails, activeProfile = "ecommerce") => {
  const plan = liveAgentProgress?.planner_agent?.data || incidentDetails?.findings?.investigation_plan || incidentDetails?.investigation_plan;
  
  // If we are completely idle (no live progress and no incident details selected)
  if (Object.keys(liveAgentProgress).length === 0 && !incidentDetails) {
    return [
      { id: "planner_agent", label: "Planner Agent" },
      { id: "dynamic_specialists", label: "Specialists Pool", isPlaceholder: true, placeholderText: "Awaiting alert" },
      { id: "rca_remediation", label: "RCA & Actions", isPlaceholder: true, placeholderText: "Awaiting findings" }
    ];
  }

  // If we are running, or viewing details
  const order = [
    { id: "planner_agent", label: "Planner Agent" }
  ];

  if (plan && plan.required_agents) {
    // Add specialists that are in the plan
    plan.required_agents.forEach(agentId => {
      let label = agentId.split("_").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
      order.push({ id: agentId, label: label });
    });

    // Check if specialists are completed or skipped
    const specialistsDone = plan.required_agents.every(agentId => {
      const status = liveAgentProgress[agentId]?.status;
      return status === "completed" || status === "skipped";
    });

    // Dynamically show the post-planning agents as they are spawned or when specialists are done
    const hasRcaStarted = !!liveAgentProgress?.rca_agent || !!incidentDetails;
    if (hasRcaStarted || specialistsDone) {
      order.push({ id: "rca_agent", label: "RCA Agent" });
    }

    const hasRemediationStarted = !!liveAgentProgress?.remediation_agent || !!incidentDetails;
    if (hasRemediationStarted || (liveAgentProgress?.rca_agent?.status === "completed")) {
      order.push({ id: "remediation_agent", label: "Remediation Agent" });
    }

    const hasApprovalStarted = !!liveAgentProgress?.approval_node || !!incidentDetails;
    if (hasApprovalStarted || (liveAgentProgress?.remediation_agent?.status === "completed")) {
      order.push({ id: "approval_node", label: "Approval Node" });
    }

    const hasResponseStarted = !!liveAgentProgress?.response_agent || !!incidentDetails;
    if (hasResponseStarted || (liveAgentProgress?.approval_node?.status === "completed")) {
      order.push({ id: "response_agent", label: "Response Agent" });
    }
  }

  return order;
};

function App() {
  const [incidents, setIncidents] = useState([]);
  const [activeIncidentId, setActiveIncidentId] = useState(null);
  const [incidentDetails, setIncidentDetails] = useState(null);
  const [liveAgentProgress, setLiveAgentProgress] = useState({});
  const [websocketStatus, setWebsocketStatus] = useState("disconnected");
  const [summaryStats, setSummaryStats] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [activeProfile, setActiveProfile] = useState("ecommerce");
  
  // Investigation Request Form State
  const [alertName, setAlertName] = useState("Database Outage Alert");
  const [errorQuery, setErrorQuery] = useState("search index=opspilot_logs ERROR earliest=-24h");
  const [earliestTime, setEarliestTime] = useState("-24h");
  const [latestTime, setLatestTime] = useState("now");
  const [isInvestigating, setIsInvestigating] = useState(false);
  
  const wsRef = useRef(null);

  // Fetch incidents list
  const fetchIncidents = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/incidents`);
      if (res.ok) {
        const data = await res.json();
        setIncidents(data.reverse()); // latest first
      }
    } catch (err) {
      console.error("Failed to fetch incidents:", err);
    }
  };

  // Fetch summary stats
  const fetchSummaryStats = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/dashboard/summary`);
      if (res.ok) {
        const data = await res.json();
        setSummaryStats(data);
      }
    } catch (err) {
      console.error("Failed to fetch summary stats:", err);
    }
  };

  // Fetch profiles
  const fetchProfiles = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/profiles`);
      if (res.ok) {
        const data = await res.json();
        setProfiles(data.available_profiles || []);
        setActiveProfile(data.active_profile || "ecommerce");
      }
    } catch (err) {
      console.error("Failed to fetch profiles:", err);
    }
  };

  // Handle profile change
  const handleProfileChange = async (profileName) => {
    try {
      const res = await fetch(`${API_BASE_URL}/profiles/select`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile: profileName })
      });
      if (res.ok) {
        setActiveProfile(profileName);
        fetchSummaryStats();
        fetchIncidents();
      }
    } catch (err) {
      console.error("Failed to update profile:", err);
    }
  };

  useEffect(() => {
    fetchIncidents();
    fetchSummaryStats();
    fetchProfiles();
    const interval = setInterval(() => {
      fetchIncidents();
      fetchSummaryStats();
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  // Fetch specific incident details
  const fetchIncidentDetails = async (id) => {
    try {
      const res = await fetch(`${API_BASE_URL}/incidents/${id}`);
      if (res.ok) {
        const data = await res.json();
        setIncidentDetails(data);
      }
    } catch (err) {
      console.error("Failed to fetch incident details:", err);
    }
  };

  useEffect(() => {
    if (activeIncidentId) {
      fetchIncidentDetails(activeIncidentId);
    }
  }, [activeIncidentId]);

  // Connect to WebSocket for streaming status updates
  const connectWebSocket = (id) => {
    if (wsRef.current) {
      wsRef.current.close();
    }

    setWebsocketStatus("connecting");
    const ws = new WebSocket(`${WS_BASE_URL}/ws/investigation/${id}`);
    wsRef.current = ws;

    ws.onopen = () => {
      setWebsocketStatus("connected");
      logger("WebSocket connection established");
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        setLiveAgentProgress(prev => ({
          ...prev,
          [message.agent]: {
            status: message.status,
            message: message.message,
            tools: message.tools,
            data: message.data
          }
        }));
      } catch (err) {
        console.error("Error parsing WS event:", err);
      }
    };

    ws.onclose = () => {
      setWebsocketStatus("disconnected");
    };

    ws.onerror = (err) => {
      console.error("WebSocket error:", err);
      setWebsocketStatus("error");
    };
  };

  // Log WebSocket activity
  const logger = (msg) => {
    console.log(`[WS Log] ${msg}`);
  };

  // Trigger manual investigation
  const handleStartInvestigation = async (e) => {
    e.preventDefault();
    setIsInvestigating(true);
    setLiveAgentProgress({});
    
    // Generate unique ID
    const newIncidentId = `manual-incident-${Date.now()}`;
    setActiveIncidentId(newIncidentId);
    connectWebSocket(newIncidentId);

    try {
      const res = await fetch(`${API_BASE_URL}/investigate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          incident_id: newIncidentId,
          alert_name: alertName,
          index: "opspilot_logs",
          error_query: errorQuery,
          earliest_time: earliestTime,
          latest_time: latestTime
        })
      });

      if (res.ok) {
        const data = await res.json();
        if (data.status === "pending_approval") {
          // Refresh list and get details
          await fetchIncidents();
          await fetchSummaryStats();
          // Synthesize details from the pending state
          setIncidentDetails({
            incident_id: newIncidentId,
            incident_name: alertName,
            status: "pending_approval",
            remediation_proposal: data.remediation_proposal,
            timestamp: data.timestamp
          });
        }
      }
    } catch (err) {
      console.error("Error starting investigation:", err);
    } finally {
      setIsInvestigating(false);
    }
  };

  // Handle remediation approval
  const handleApproval = async (approved) => {
    if (!activeIncidentId) return;

    try {
      const res = await fetch(`${API_BASE_URL}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          incident_id: activeIncidentId,
          approved: approved
        })
      });

      if (res.ok) {
        const data = await res.json();
        // Fetch details again to show final findings
        await fetchIncidentDetails(activeIncidentId);
        await fetchIncidents();
        await fetchSummaryStats();
      }
    } catch (err) {
      console.error("Approval request failed:", err);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-indigo-500 selection:text-white">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur-md sticky top-0 z-50 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="bg-gradient-to-tr from-indigo-500 to-violet-600 p-2.5 rounded-xl shadow-lg shadow-indigo-500/20">
            <Cpu className="w-6 h-6 text-white animate-pulse" />
          </div>
          <div>
            <h1 className="font-bold text-xl tracking-tight bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">
              OpsPilot AI Command Center
            </h1>
            <p className="text-xs text-indigo-400/80 font-medium">Autonomous Incident Response & Observability Platform</p>
          </div>
        </div>
        
        <div className="flex items-center gap-3">
          {/* Profile Switcher */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/80 border border-slate-700 text-xs">
            <span className="font-semibold text-slate-400">Profile:</span>
            <select
              value={activeProfile}
              onChange={(e) => handleProfileChange(e.target.value)}
              className="bg-slate-900 border border-slate-700 text-slate-200 rounded px-2.5 py-0.5 text-xs focus:outline-none focus:border-indigo-500 transition cursor-pointer font-semibold uppercase"
            >
              {profiles.map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/80 border border-slate-700 text-xs">
            <span className={`w-2.5 h-2.5 rounded-full ${websocketStatus === "connected" ? "bg-green-500 animate-pulse" : websocketStatus === "connecting" ? "bg-yellow-500 animate-pulse" : "bg-red-500"}`} />
            <span className="font-semibold text-slate-300">WS Connection: {websocketStatus.toUpperCase()}</span>
          </div>
          <button 
            onClick={fetchIncidents}
            className="p-2 bg-slate-800 hover:bg-slate-700 active:scale-95 transition rounded-lg border border-slate-700"
            title="Refresh database"
          >
            <RefreshCw className="w-4 h-4 text-slate-300" />
          </button>
        </div>
      </header>

      {/* Global Summary Metrics Bar */}
      <section className="bg-slate-900/40 border-b border-slate-800/80 px-6 py-3.5 grid grid-cols-3 gap-6">
        <div className="flex items-center gap-3.5">
          <div className="p-2 bg-indigo-500/10 rounded-lg text-indigo-400">
            <Activity className="w-5 h-5 animate-pulse" />
          </div>
          <div>
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Active Investigations</div>
            <div className="text-xl font-bold text-slate-200">{summaryStats?.active_count ?? 0}</div>
          </div>
        </div>
        <div className="flex items-center gap-3.5 border-l border-slate-800/60 pl-6">
          <div className="p-2 bg-emerald-500/10 rounded-lg text-emerald-400">
            <CheckCircle2 className="w-5 h-5" />
          </div>
          <div>
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Total Resolved Incidents</div>
            <div className="text-xl font-bold text-slate-200">{summaryStats?.resolved_count ?? 0}</div>
          </div>
        </div>
        <div className="flex items-center gap-3.5 border-l border-slate-800/60 pl-6">
          <div className="p-2 bg-amber-500/10 rounded-lg text-amber-400">
            <ShieldAlert className="w-5 h-5" />
          </div>
          <div>
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Remediation Approval Rate</div>
            <div className="text-xl font-bold text-slate-200">{summaryStats?.approval_rate ?? 100}%</div>
          </div>
        </div>
      </section>

      {/* Main Container */}
      <div className="flex-1 grid grid-cols-12 gap-6 p-6">
        
        {/* Left Column: Form & History List */}
        <div className="col-span-12 lg:col-span-4 flex flex-col gap-6">
          
          {/* Panel: Manual Investigation Trigger */}
          <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-5 shadow-xl backdrop-blur-sm">
            <h2 className="font-bold text-slate-200 mb-4 flex items-center gap-2">
              <Play className="w-5 h-5 text-indigo-400" />
              Trigger Investigation
            </h2>
            <form onSubmit={handleStartInvestigation} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Alert Name</label>
                <input 
                  type="text" 
                  value={alertName} 
                  onChange={(e) => setAlertName(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500 transition"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">SPL Error Query</label>
                <textarea 
                  value={errorQuery} 
                  onChange={(e) => setErrorQuery(e.target.value)}
                  rows="2"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500 transition font-mono"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Earliest Time</label>
                  <input 
                    type="text" 
                    value={earliestTime} 
                    onChange={(e) => setEarliestTime(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500 transition"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Latest Time</label>
                  <input 
                    type="text" 
                    value={latestTime} 
                    onChange={(e) => setLatestTime(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500 transition"
                  />
                </div>
              </div>
              <button 
                type="submit" 
                disabled={isInvestigating}
                className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800/50 py-2.5 rounded-xl font-semibold text-sm transition active:scale-98 flex items-center justify-center gap-2 text-white shadow-lg shadow-indigo-600/20"
              >
                {isInvestigating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Activity className="w-4 h-4" />}
                {isInvestigating ? "Investigating..." : "Execute Investigation"}
              </button>
            </form>
          </div>

          {/* Panel 1: Active & Stored Incidents */}
          <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-5 shadow-xl flex-1 flex flex-col backdrop-blur-sm overflow-hidden">
            <h2 className="font-bold text-slate-200 mb-4 flex items-center gap-2">
              <History className="w-5 h-5 text-indigo-400" />
              Incident Directory
            </h2>
            <div className="flex-1 overflow-y-auto space-y-2.5 pr-1.5 scrollbar-thin">
              {incidents.length === 0 ? (
                <p className="text-sm text-slate-500 italic text-center py-6">No incidents investigated yet.</p>
              ) : (
                incidents.map((inc) => (
                  <div 
                    key={inc.incident_id}
                    onClick={() => {
                      setActiveIncidentId(inc.incident_id);
                      connectWebSocket(inc.incident_id);
                    }}
                    className={`p-3.5 rounded-xl border transition cursor-pointer text-left ${activeIncidentId === inc.incident_id ? "bg-indigo-600/10 border-indigo-500 shadow-md shadow-indigo-500/5" : "bg-slate-950/60 border-slate-800 hover:border-slate-700"}`}
                  >
                    <div className="flex justify-between items-start gap-2 mb-1.5">
                      <span className="text-xs font-semibold text-slate-400 font-mono truncate max-w-[150px]">{inc.incident_id}</span>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${inc.success ? "bg-green-500/10 text-green-400 border border-green-500/20" : "bg-yellow-500/10 text-yellow-400 border border-yellow-500/20"}`}>
                        {inc.success ? "RESOLVED" : "ACTIVE"}
                      </span>
                    </div>
                    <h3 className="font-bold text-sm text-slate-200 line-clamp-1">{inc.root_cause || "Manual Run"}</h3>
                    <div className="mt-2.5 flex items-center justify-between text-[11px] text-slate-400">
                      <span className="font-medium bg-slate-900 border border-slate-800 px-2 py-0.5 rounded text-indigo-400">{inc.affected_service}</span>
                      <span className="flex items-center gap-1"><Clock className="w-3.5 h-3.5 text-slate-500" /> {new Date(inc.timestamp).toLocaleTimeString()}</span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Right Column: Live Progress & Findings Details */}
        <div className="col-span-12 lg:col-span-8 flex flex-col gap-6">
          
          {/* Panel 2: Live Agent Investigation timeline */}
          <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-5 shadow-xl backdrop-blur-sm">
            <h2 className="font-bold text-slate-200 mb-4 flex items-center justify-between">
              <span className="flex items-center gap-2">
                <Activity className="w-5 h-5 text-indigo-400" />
                Live Agent Execution Steps
              </span>
              {Object.keys(liveAgentProgress).length === 0 && !incidentDetails && (
                <span className="text-[10px] bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 px-2.5 py-0.5 rounded-full font-bold">
                  PIPELINE PREVIEW ({activeProfile.toUpperCase()})
                </span>
              )}
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3.5">
              {getDynamicAgentOrder(liveAgentProgress, incidentDetails, activeProfile).map((agent) => {
                if (agent.isPlaceholder) {
                  return (
                    <div 
                      key={agent.id}
                      className="relative p-3.5 rounded-xl border border-dashed border-slate-800/80 bg-slate-950/15 opacity-40 flex flex-col items-center justify-center text-center transition-all duration-300 hover:opacity-60"
                    >
                      <span className="absolute top-1 right-1 text-[7px] font-bold px-1 py-0.2 bg-slate-800/80 border border-slate-700/50 text-slate-500 rounded-sm scale-90">
                        DYNAMIC
                      </span>
                      <div className="w-8 h-8 rounded-full bg-slate-900/35 text-slate-600 flex items-center justify-center mb-1.5 border border-slate-800/40">
                        <Layers className="w-4 h-4 text-slate-500 animate-pulse" />
                      </div>
                      <span className="text-[10px] font-bold tracking-wider text-slate-500 uppercase">{agent.label}</span>
                      <span className="text-[8px] font-semibold mt-1 uppercase text-slate-600">
                        {agent.placeholderText}
                      </span>
                    </div>
                  );
                }

                const agentData = liveAgentProgress[agent.id];
                const status = typeof agentData === "object" ? agentData.status : (agentData || "pending");
                const isIdle = Object.keys(liveAgentProgress).length === 0 && !incidentDetails;
                
                return (
                  <div 
                    key={agent.id}
                    className={`relative p-3 rounded-xl border flex flex-col items-center justify-center text-center transition ${isIdle ? "bg-slate-950/20 border-dashed border-slate-800/80 opacity-55 hover:opacity-85" : status === "running" ? "bg-indigo-500/10 border-indigo-400 shadow-md shadow-indigo-500/10 scale-102" : status === "completed" ? "bg-emerald-500/5 border-emerald-500/20" : "bg-slate-950/60 border-slate-900/80"}`}
                  >
                    {/* Dispatched Badge */}
                    {!isIdle && agent.id !== "planner_agent" && agent.id !== "rca_agent" && agent.id !== "remediation_agent" && agent.id !== "approval_node" && agent.id !== "response_agent" && (
                      <span className="absolute top-1 right-1 text-[7px] font-bold px-1 py-0.2 bg-indigo-500/15 border border-indigo-500/30 text-indigo-300 rounded-sm scale-90">
                        DISPATCHED
                      </span>
                    )}
                    {isIdle && (
                      <span className="absolute top-1 right-1 text-[7px] font-bold px-1 py-0.2 bg-slate-800 border border-slate-700 text-slate-500 rounded-sm scale-90">
                        PREVIEW
                      </span>
                    )}

                    <div className={`w-8 h-8 rounded-full flex items-center justify-center mb-1.5 ${isIdle ? "bg-slate-900/50 text-slate-600" : status === "running" ? "bg-indigo-500/20 text-indigo-300 animate-spin" : status === "completed" ? "bg-emerald-500/20 text-emerald-400" : "bg-slate-900 text-slate-500"}`}>
                      {status === "completed" ? <CheckCircle2 className="w-4 h-4" /> : <Activity className="w-4 h-4" />}
                    </div>
                    <span className="text-[10px] font-bold tracking-wider text-slate-400 uppercase">{agent.label}</span>
                    <span className={`text-[9px] font-semibold mt-1 uppercase ${isIdle ? "text-slate-600" : status === "running" ? "text-indigo-400 animate-pulse" : status === "completed" ? "text-emerald-400" : "text-slate-600"}`}>
                      {isIdle ? "ready" : status}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Active Agent Thought Stream */}
            {(() => {
              const currentOrder = getDynamicAgentOrder(liveAgentProgress, incidentDetails, activeProfile);
              const runningAgent = currentOrder.find(a => liveAgentProgress[a.id]?.status === "running");
              const lastAgent = runningAgent || [...currentOrder].reverse().find(a => liveAgentProgress[a.id]?.status === "completed");
              
              if (!lastAgent || !liveAgentProgress[lastAgent.id]) return null;
              
              const progress = liveAgentProgress[lastAgent.id];
              return (
                <div className="mt-4 p-4 rounded-xl bg-gradient-to-r from-slate-900 to-indigo-950/30 border border-indigo-500/20 flex flex-col md:flex-row justify-between gap-4 text-left">
                  <div className="space-y-1.5 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="relative flex h-2 w-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
                      </span>
                      <strong className="text-xs uppercase tracking-wider text-indigo-400">{lastAgent.label} Reasoning & Workspace</strong>
                    </div>
                    <p className="text-sm text-slate-200 font-semibold italic">
                      "{progress.message || 'Processing and analyzing findings...'}"
                    </p>
                    {progress.tools && progress.tools.length > 0 && (
                      <div className="mt-2.5 flex items-center gap-2 flex-wrap">
                        <span className="text-[10px] text-slate-400 font-bold uppercase">Executing MCP Tools:</span>
                        {progress.tools.map((t, idx) => (
                          <span key={idx} className="text-[10px] bg-rose-500/20 text-rose-300 border border-rose-500/30 px-2 py-0.5 rounded font-mono font-bold animate-pulse">
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  {progress.data && (
                    <div className="md:w-1/3 min-w-[200px]">
                      <span className="text-[10px] text-slate-400 font-bold uppercase block mb-1">Extracted Workspace Findings:</span>
                      <div className="p-2.5 bg-slate-950/80 border border-slate-800 rounded-lg max-h-24 overflow-y-auto scrollbar-thin text-[10px] font-mono text-slate-300">
                        {JSON.stringify(progress.data, null, 2)}
                      </div>
                    </div>
                  )}
                </div>
              );
            })()}

            {/* Live Telemetry Console Feed */}
            {/* Live Telemetry Console Feed */}
            <div className="mt-5 p-4 bg-slate-950/90 border border-slate-800/80 rounded-xl font-mono text-xs h-72 overflow-y-auto space-y-3.5 scrollbar-thin shadow-2xl shadow-indigo-950/20">
              <div className="text-slate-500 border-b border-slate-800/60 pb-2.5 flex justify-between items-center sticky top-0 bg-slate-950/95 backdrop-blur-sm z-10">
                <span className="flex items-center gap-2 font-bold text-[10px] uppercase tracking-widest text-indigo-400">
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
                  </span>
                  Real-time Multi-Agent Observability & Telemetry Stream
                </span>
                <span className="text-[9px] bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 px-2 py-0.5 rounded font-bold animate-pulse">MCP TOOL LOGS ACTIVE</span>
              </div>
              
              {Object.keys(liveAgentProgress).length === 0 ? (
                <div className="text-slate-600 italic py-16 text-center">Observability stream idle. Trigger an investigation to stream live telemetry.</div>
              ) : (
                <div className="relative border-l border-slate-800/80 ml-3 pl-5 space-y-3 pt-2">
                  {getDynamicAgentOrder(liveAgentProgress, incidentDetails, activeProfile).map(agent => {
                    const data = liveAgentProgress[agent.id];
                    if (!data) return null;
                    const isRunning = data.status === "running";
                    return (
                      <div key={agent.id} className="relative group transition-all duration-300 hover:bg-slate-900/30 rounded-xl p-3 border border-transparent hover:border-slate-800/40 text-left">
                        {/* Timeline connector dot */}
                        <div className="absolute left-[-26px] top-[20px] w-3 h-3 rounded-full bg-slate-950 border-2 border-slate-800 group-hover:border-indigo-500/80 transition-colors z-10 flex items-center justify-center">
                          <div className={`w-1 h-1 rounded-full ${isRunning ? "bg-amber-400 animate-ping" : "bg-emerald-400"}`}></div>
                        </div>
                        <div className="flex flex-col gap-1.5">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-[10px] text-slate-500 font-mono">[{new Date().toLocaleTimeString()}]</span>
                            <span className="text-indigo-400 font-bold uppercase text-[10px] tracking-wide">{agent.label}</span>
                            <span className={`text-[8px] font-bold px-1.5 py-0.5 rounded uppercase border ${isRunning ? "bg-amber-500/10 text-amber-400 border-amber-500/20 animate-pulse" : "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"}`}>
                              {data.status}
                            </span>
                            {data.tools && data.tools.length > 0 && (
                              <span className="text-[8px] font-bold px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20 animate-pulse">
                                MCP TOOL CALL: {data.tools.join(", ")}
                              </span>
                            )}
                          </div>
                          {data.message && (
                            <div className="text-slate-300 text-xs pl-0.5 leading-relaxed bg-slate-900/50 p-2 border border-slate-800/30 rounded-md font-sans">
                              {data.message}
                            </div>
                          )}
                          {data.data && (
                            <details className="mt-0.5">
                              <summary className="text-[10px] text-indigo-400/70 hover:text-indigo-400 cursor-pointer select-none font-semibold flex items-center gap-1">
                                <Layers className="w-3.5 h-3.5" />
                                Inspect Telemetry Data
                              </summary>
                              <pre className="mt-1.5 p-2.5 bg-slate-900 border border-slate-800/60 rounded-lg text-[10px] text-slate-400 overflow-x-auto max-h-36 scrollbar-thin leading-relaxed">
                                {JSON.stringify(data.data, null, 2)}
                              </pre>
                            </details>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          {/* Details & Findings Grid */}
          {incidentDetails ? (
            <div className="grid grid-cols-12 gap-6">
              
              {/* Panel 7: Anomaly Detection Results */}
              {incidentDetails.anomaly_findings && (
                <div className="col-span-12 bg-slate-900/50 border border-slate-800 rounded-2xl p-5 shadow-xl backdrop-blur-sm">
                  <h3 className="font-bold text-slate-200 mb-3 flex items-center gap-2">
                    <ShieldAlert className="w-5 h-5 text-rose-500" />
                    Anomaly Detection Findings
                  </h3>
                  <div className="bg-rose-950/10 border border-rose-500/20 rounded-xl p-4 flex flex-col md:flex-row gap-4 justify-between items-start md:items-center">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold bg-rose-500/20 text-rose-400 border border-rose-500/30 px-2 py-0.5 rounded">
                          ANOMALY TYPE: {incidentDetails.anomaly_findings.anomaly_type.toUpperCase()}
                        </span>
                        <span className="text-xs text-slate-400">Confidence: {(incidentDetails.anomaly_findings.confidence * 100).toFixed(0)}%</span>
                      </div>
                      <p className="text-sm text-slate-300 font-medium">{incidentDetails.anomaly_findings.description}</p>
                    </div>
                    <div className="text-right text-xs">
                      <span className="text-slate-400">Impacted Service: </span>
                      <span className="font-bold text-indigo-400">{incidentDetails.anomaly_findings.affected_service}</span>
                    </div>
                  </div>
                </div>
              )}

              {/* Classification Findings */}
              {incidentDetails.classification_findings && (
                <div className="col-span-12 bg-slate-900/50 border border-slate-800 rounded-2xl p-5 shadow-xl backdrop-blur-sm">
                  <h3 className="font-bold text-slate-200 mb-3 flex items-center gap-2">
                    <Layers className="w-5 h-5 text-indigo-400" />
                    Incident Classification Details
                  </h3>
                  <div className="bg-indigo-950/10 border border-indigo-500/20 rounded-xl p-4 flex flex-col md:flex-row gap-4 justify-between items-start md:items-center">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 px-2 py-0.5 rounded">
                          INCIDENT TYPE: {incidentDetails.classification_findings.incident_type?.toUpperCase()}
                        </span>
                        <span className="text-xs font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30 px-2 py-0.5 rounded">
                          SEVERITY: {incidentDetails.classification_findings.severity?.toUpperCase()}
                        </span>
                        <span className="text-xs text-slate-400">Confidence: {((incidentDetails.classification_findings.confidence || 0) * 100).toFixed(0)}%</span>
                      </div>
                      <p className="text-sm text-slate-300 font-medium">
                        OpsPilot classified the active outage under the {incidentDetails.classification_findings.incident_type} category.
                      </p>
                    </div>
                    <div className="text-right text-xs">
                      <span className="text-slate-400">Affected Component: </span>
                      <span className="font-bold text-indigo-400">{incidentDetails.classification_findings.affected_domain}</span>
                    </div>
                  </div>
                </div>
              )}

              {/* Dynamic Investigation Plan */}
              {(() => {
                const plan = incidentDetails?.findings?.investigation_plan || incidentDetails?.investigation_plan || liveAgentProgress.planner_agent?.data;
                if (!plan) return null;
                return (
                  <div className="col-span-12 bg-slate-900/50 border border-slate-800 rounded-2xl p-5 shadow-xl backdrop-blur-sm">
                    <h3 className="font-bold text-slate-200 mb-3 flex items-center gap-2">
                      <Cpu className="w-5 h-5 text-indigo-400" />
                      Dynamic Investigation Plan
                    </h3>
                    <div className="bg-indigo-950/10 border border-indigo-500/20 rounded-xl p-4 space-y-3">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] font-bold text-slate-400 uppercase">Detected Incident Type:</span>
                          <span className="text-xs font-bold bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 px-2.5 py-0.5 rounded uppercase">
                            {plan.incident_type}
                          </span>
                        </div>
                        <div className="text-xs text-slate-400">
                          Confidence: <strong className="text-emerald-400">{((plan.confidence || 0) * 100).toFixed(0)}%</strong>
                        </div>
                      </div>
                      
                      <div>
                        <span className="text-[10px] font-bold text-slate-400 uppercase block mb-1">Selected Agent Chain:</span>
                        <div className="flex flex-wrap gap-2">
                          {plan.required_agents?.map((agentId, idx) => (
                            <span key={idx} className="text-xs bg-slate-900 border border-slate-800 text-slate-300 px-2 py-1 rounded font-semibold font-mono">
                              {agentId.split("_").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ")}
                            </span>
                          ))}
                        </div>
                      </div>
                      
                      <div className="pt-2.5 border-t border-slate-800/60">
                        <span className="text-[10px] font-bold text-slate-400 uppercase block mb-0.5">Planner Reasoning:</span>
                        <p className="text-sm text-slate-300 font-medium italic">"{plan.reasoning}"</p>
                      </div>
                    </div>
                  </div>
                );
              })()}

              {/* Domain Agent Specific Findings */}
              {incidentDetails?.findings?.domain_findings && Object.keys(incidentDetails.findings.domain_findings).map((agentKey) => {
                const findings = incidentDetails.findings.domain_findings[agentKey];
                if (!findings) return null;
                let label = agentKey.split("_").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
                return (
                  <div key={agentKey} className="col-span-12 bg-slate-900/50 border border-slate-800 rounded-2xl p-5 shadow-xl backdrop-blur-sm">
                    <h3 className="font-bold text-slate-200 mb-3 flex items-center gap-2">
                      <Cpu className="w-5 h-5 text-indigo-400" />
                      {label} Diagnostics
                    </h3>
                    <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-4 space-y-3">
                      <p className="text-sm text-slate-300 leading-relaxed font-medium">{findings.analysis}</p>
                      
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-3 border-t border-slate-800/60">
                        <div>
                          <span className="text-[10px] font-bold text-slate-500 uppercase block mb-1">Discovered Issues</span>
                          <ul className="list-disc list-inside text-xs text-rose-400 space-y-1.5 font-medium">
                            {findings.discovered_issues?.map((issue, idx) => (
                              <li key={idx}>{issue}</li>
                            ))}
                          </ul>
                        </div>
                        <div>
                          <span className="text-[10px] font-bold text-slate-500 uppercase block mb-1">Suggested Remediation Actions</span>
                          <ul className="list-disc list-inside text-xs text-indigo-300 space-y-1.5 font-medium">
                            {findings.suggested_actions?.map((action, idx) => (
                              <li key={idx}>{action}</li>
                            ))}
                          </ul>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}

              {/* Panel 3: Root Cause Analysis */}
              <div className="col-span-12 md:col-span-6 bg-slate-900/50 border border-slate-800 rounded-2xl p-5 shadow-xl backdrop-blur-sm flex flex-col">
                <h3 className="font-bold text-slate-200 mb-3 flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5 text-yellow-500" />
                  Root Cause Hypothesis
                </h3>
                <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-4 flex-1 flex flex-col justify-between">
                  <div>
                    <h4 className="font-bold text-slate-200 text-sm mb-1.5">
                      {incidentDetails.root_cause_analysis?.rca_hypothesis || incidentDetails.remediation_proposal?.reasoning || "Analyzing..."}
                    </h4>
                    <p className="text-xs text-slate-400 line-clamp-4">
                      {incidentDetails.root_cause_analysis?.evidence || "RCA evidence compilation details will appear here."}
                    </p>
                  </div>
                  <div className="mt-4 pt-3 border-t border-slate-800/60 flex items-center justify-between text-xs text-slate-400">
                    <span>Affected: <strong className="text-indigo-400">{incidentDetails.logs?.affected_services?.[0] || incidentDetails.remediation_proposal?.target_service || "Unknown"}</strong></span>
                    <span>Confidence: <strong className="text-emerald-400">{((incidentDetails.root_cause_analysis?.confidence_score || 0.85) * 100).toFixed(0)}%</strong></span>
                  </div>
                </div>
              </div>

              {/* Panel 4: Historical Incident Memory */}
              <div className="col-span-12 md:col-span-6 bg-slate-900/50 border border-slate-800 rounded-2xl p-5 shadow-xl backdrop-blur-sm flex flex-col">
                <h3 className="font-bold text-slate-200 mb-3 flex items-center gap-2">
                  <History className="w-5 h-5 text-indigo-400" />
                  Historical Incident Context
                </h3>
                <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-4 flex-1 flex flex-col justify-between">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="bg-slate-900/60 border border-slate-800/80 p-3 rounded-lg text-center">
                      <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1">Similar Incidents</span>
                      <strong className="text-2xl text-indigo-400">{incidentDetails.historical_context?.similar_incidents_found || 0}</strong>
                    </div>
                    <div className="bg-slate-900/60 border border-slate-800/80 p-3 rounded-lg text-center">
                      <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1">Success Rate</span>
                      <strong className="text-2xl text-emerald-400">{((incidentDetails.historical_context?.historical_success_rate || 1.0) * 100).toFixed(0)}%</strong>
                    </div>
                  </div>
                  <div className="mt-4 pt-3 border-t border-slate-800/60 text-xs">
                    <span className="text-slate-400 block mb-1">Recommended Historical Fix:</span>
                    <strong className="text-slate-200 bg-slate-900 border border-slate-800 px-2 py-1 rounded block truncate">{incidentDetails.historical_context?.recommended_fix || "No history available"}</strong>
                  </div>
                </div>
              </div>

              {/* Executive Summary Card */}
              {incidentDetails.executive_summary && (
                <div className="col-span-12 bg-slate-900/50 border border-slate-800 rounded-2xl p-5 shadow-xl backdrop-blur-sm">
                  <h3 className="font-bold text-slate-200 mb-3 flex items-center gap-2">
                    <Activity className="w-5 h-5 text-indigo-400" />
                    Executive Briefing
                  </h3>
                  <div className="bg-indigo-950/5 border border-indigo-500/10 rounded-xl p-4">
                    <p className="text-sm text-slate-300 leading-relaxed font-medium">
                      {incidentDetails.executive_summary}
                    </p>
                  </div>
                </div>
              )}

              {/* Panel 6: Remediation Approval */}
              {incidentDetails.status === "pending_approval" && (
                <div className="col-span-12 bg-slate-900/50 border border-slate-800 rounded-2xl p-5 shadow-xl backdrop-blur-sm">
                  <h3 className="font-bold text-slate-200 mb-3 flex items-center gap-2">
                    <ShieldAlert className="w-5 h-5 text-indigo-400" />
                    Operator Action Required: Remediation Approval
                  </h3>
                  <div className="bg-indigo-950/10 border border-indigo-500/20 rounded-xl p-4 flex flex-col md:flex-row gap-4 justify-between items-start md:items-center">
                    <div>
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className="text-xs font-bold bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 px-2.5 py-0.5 rounded">
                          PROPOSED ACTION: {incidentDetails.remediation_proposal?.recommended_action?.toUpperCase()}
                        </span>
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${incidentDetails.remediation_proposal?.risk_level === "high" ? "bg-red-500/10 text-red-400 border border-red-500/20" : "bg-yellow-500/10 text-yellow-400 border border-yellow-500/20"}`}>
                          RISK: {incidentDetails.remediation_proposal?.risk_level?.toUpperCase()}
                        </span>
                      </div>
                      <p className="text-sm text-slate-300 font-medium">{incidentDetails.remediation_proposal?.reasoning}</p>
                    </div>
                    <div className="flex gap-2 w-full md:w-auto">
                      <button 
                        onClick={() => handleApproval(true)}
                        className="flex-1 md:flex-none px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg font-bold text-sm transition active:scale-95 flex items-center justify-center gap-1.5"
                      >
                        <Check className="w-4 h-4" /> Approve
                      </button>
                      <button 
                        onClick={() => handleApproval(false)}
                        className="flex-1 md:flex-none px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg font-bold text-sm transition border border-slate-700 active:scale-95 flex items-center justify-center gap-1.5"
                      >
                        <X className="w-4 h-4" /> Reject
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Panel 5: Incident Timeline */}
              <div className="col-span-12 bg-slate-900/50 border border-slate-800 rounded-2xl p-5 shadow-xl backdrop-blur-sm">
                <h3 className="font-bold text-slate-200 mb-4 flex items-center gap-2">
                  <Layers className="w-5 h-5 text-indigo-400" />
                  Chronological Incident Timeline
                </h3>
                <div className="relative border-l border-slate-800 ml-3.5 space-y-5">
                  {incidentDetails.timeline?.events ? (
                    incidentDetails.timeline.events.map((ev, idx) => (
                      <div key={idx} className="relative pl-6">
                        <div className="absolute -left-1.5 top-1.5 w-3 h-3 rounded-full bg-indigo-500 border-2 border-slate-950" />
                        <span className="text-[10px] font-bold text-slate-500 font-mono block mb-1">
                          {new Date(ev.timestamp).toLocaleString()}
                        </span>
                        <strong className="text-xs uppercase text-indigo-400 bg-indigo-950/20 px-2 py-0.5 border border-indigo-900/30 rounded inline-block mb-1">
                          {ev.event_type}
                        </strong>
                        <p className="text-sm text-slate-300">{ev.description}</p>
                      </div>
                    ))
                  ) : (
                    <p className="text-sm text-slate-500 italic pl-4">No timeline events compiled yet.</p>
                  )}
                </div>
              </div>

            </div>
          ) : (
            <div className="bg-slate-900/30 border border-slate-800/80 border-dashed rounded-2xl p-12 text-center flex flex-col items-center justify-center flex-1">
              <Activity className="w-12 h-12 text-slate-600 mb-3 animate-pulse" />
              <h3 className="font-bold text-slate-400 text-lg">No Incident Selected</h3>
              <p className="text-sm text-slate-500 max-w-sm mt-1">Select an incident from the directory or execute a manual investigation to view RCA logs and remediation playbooks.</p>
            </div>
          )}

        </div>

      </div>
    </div>
  );
}

export default App;
