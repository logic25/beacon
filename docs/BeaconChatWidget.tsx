import { useState, useRef, useEffect } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Send, Brain, FileText, Zap, X, ChevronDown, ChevronUp } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { cn } from "@/lib/utils";
import { useIsAdmin } from "@/hooks/useUserRoles";
import { useAuth } from "@/hooks/useAuth";
import { askBeacon, type BeaconSource } from "@/services/beaconApi";

const quickQuestions = [
  "Alt-1 vs Alt-2?",
  "How to file NB?",
  "Look up address",
  "Energy code?",
];

interface ChatMessage {
  role: "user" | "beacon";
  text: string;
  confidence?: number;
  sources?: BeaconSource[];
  responseTime?: number;
  flowType?: string;
}

function ConfidenceBadge({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  const color = pct >= 85 ? "bg-[#22c55e]" : pct >= 60 ? "bg-yellow-500" : "bg-destructive";
  const label = pct >= 85 ? "high" : pct >= 60 ? "medium" : "low";
  return (
    <Badge className={cn("text-[9px] text-white px-1.5 py-0", color)}>
      {label} ({pct}%)
    </Badge>
  );
}

function SourcesList({ sources }: { sources: BeaconSource[] }) {
  const [expanded, setExpanded] = useState(false);
  if (!sources.length) return null;

  return (
    <div className="mt-1">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
      >
        <FileText className="h-2.5 w-2.5" />
        {sources.length} source{sources.length !== 1 ? "s" : ""}
        {expanded ? <ChevronUp className="h-2.5 w-2.5" /> : <ChevronDown className="h-2.5 w-2.5" />}
      </button>
      {expanded && (
        <div className="mt-1 space-y-1">
          {sources.map((s, i) => (
            <div key={i} className="bg-muted/50 rounded p-1.5 text-[10px]">
              <div className="flex items-center justify-between gap-1">
                <span className="font-medium truncate">{s.title}</span>
                <span className="font-mono text-[#f59e0b] shrink-0">{Math.round(s.score * 100)}%</span>
              </div>
              {s.chunk_preview && (
                <p className="text-muted-foreground mt-0.5 line-clamp-2">{s.chunk_preview}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function BeaconChatWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const isAdmin = useIsAdmin();
  const { user, profile } = useAuth();
  const [showDebug, setShowDebug] = useState(false);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const userId = user?.email || user?.id || "anonymous";
  const userName = profile?.display_name || profile?.first_name || user?.user_metadata?.full_name || "User";

  const handleSend = async (text?: string) => {
    const q = text || input.trim();
    if (!q || loading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: q }]);
    setLoading(true);

    try {
      const res = await askBeacon(q, userId, userName);
      setMessages((prev) => [
        ...prev,
        {
          role: "beacon",
          text: res.response,
          confidence: res.confidence,
          sources: res.sources || [],
          responseTime: res.response_time_ms,
          flowType: res.flow_type,
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: "beacon",
          text: "Beacon is temporarily unavailable. Please try again.",
          confidence: 0,
          sources: [],
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const lastBeaconMsg = messages.filter((m) => m.role === "beacon").at(-1);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full bg-[#f59e0b] hover:bg-[#d97706] text-white shadow-lg flex items-center justify-center transition-all hover:scale-105"
        title="Ask Beacon"
      >
        <Brain className="h-6 w-6" />
      </button>
    );
  }

  return (
    <div className="fixed bottom-6 right-6 z-50 w-[400px] h-[560px] flex flex-col bg-background border rounded-xl shadow-2xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b bg-[#f59e0b] text-white">
        <div className="flex items-center gap-2">
          <Brain className="h-5 w-5" />
          <span className="font-semibold text-sm">Beacon</span>
        </div>
        <div className="flex items-center gap-1">
          {isAdmin && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-white/80 hover:text-white hover:bg-white/20"
              onClick={() => setShowDebug(!showDebug)}
              title="Toggle RAG debug"
            >
              <FileText className="h-3.5 w-3.5" />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-white/80 hover:text-white hover:bg-white/20"
            onClick={() => setOpen(false)}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 && (
          <div className="text-center py-4">
            <Brain className="h-8 w-8 mx-auto text-[#f59e0b]/40 mb-2" />
            <p className="text-xs text-muted-foreground mb-3">Ask Beacon anything about NYC construction & expediting</p>
            <div className="flex flex-wrap gap-1.5 justify-center">
              {quickQuestions.map((q, i) => (
                <button
                  key={i}
                  onClick={() => handleSend(q)}
                  className="text-[11px] px-2.5 py-1 rounded-full border hover:bg-muted transition-colors"
                >
                  <Zap className="h-3 w-3 inline mr-0.5" />
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={cn("flex gap-2", msg.role === "user" ? "justify-end" : "")}>
            {msg.role === "beacon" && (
              <div className="w-6 h-6 rounded-full bg-[#f59e0b] flex items-center justify-center shrink-0 mt-1">
                <Brain className="h-3 w-3 text-white" />
              </div>
            )}
            <div className={cn("max-w-[85%]", msg.role === "user" ? "bg-primary text-primary-foreground rounded-2xl rounded-br-sm px-3 py-2" : "")}>
              {msg.role === "beacon" ? (
                <div className="space-y-1.5">
                  <div className="prose prose-sm max-w-none text-xs">
                    <ReactMarkdown>{msg.text}</ReactMarkdown>
                  </div>
                  <div className="flex items-center gap-1.5 flex-wrap">
                    {msg.confidence != null && msg.confidence > 0 && (
                      <ConfidenceBadge confidence={msg.confidence} />
                    )}
                    {msg.responseTime != null && (
                      <span className="text-[9px] text-muted-foreground">
                        {(msg.responseTime / 1000).toFixed(1)}s
                      </span>
                    )}
                  </div>
                  {msg.sources && <SourcesList sources={msg.sources} />}
                </div>
              ) : (
                <p className="text-sm">{msg.text}</p>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex gap-2">
            <div className="w-6 h-6 rounded-full bg-[#f59e0b] flex items-center justify-center shrink-0">
              <Brain className="h-3 w-3 text-white animate-pulse" />
            </div>
            <span className="text-xs text-muted-foreground mt-1.5">Beacon is thinking<span className="animate-pulse">...</span></span>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Debug panel */}
      {showDebug && lastBeaconMsg && (
        <div className="border-t bg-muted/30 px-3 py-2 max-h-32 overflow-y-auto">
          <p className="text-[10px] font-semibold mb-1">RAG Debug</p>
          <div className="space-y-1 text-[10px]">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Confidence:</span>
              {lastBeaconMsg.confidence != null && lastBeaconMsg.confidence > 0 && (
                <ConfidenceBadge confidence={lastBeaconMsg.confidence} />
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Flow:</span>
              <span>{lastBeaconMsg.flowType || "unknown"}</span>
            </div>
            {lastBeaconMsg.sources?.map((s, i) => (
              <div key={i} className="flex items-center justify-between">
                <span className="truncate flex items-center gap-1"><FileText className="h-2.5 w-2.5" />{s.title}</span>
                <span className="font-mono text-[#f59e0b] shrink-0">{Math.round(s.score * 100)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="border-t p-3">
        <form onSubmit={(e) => { e.preventDefault(); handleSend(); }} className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask Beacon..."
            className="flex-1 h-9 text-sm"
            disabled={loading}
          />
          <Button
            type="submit"
            disabled={!input.trim() || loading}
            size="icon"
            className="h-9 w-9 bg-[#f59e0b] hover:bg-[#d97706] text-white shrink-0"
          >
            <Send className="h-4 w-4" />
          </Button>
        </form>
      </div>
    </div>
  );
}
