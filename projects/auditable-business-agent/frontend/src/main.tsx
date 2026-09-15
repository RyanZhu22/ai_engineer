import { FormEvent, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type Event = { event_type: string; occurred_at: string; actor_id: string; payload: Record<string, unknown> };
type CaseResult = { case_id: string; status: string; decision?: { action: string; reason: string; rule_id: string; requires_approval: boolean }; approval?: { action: string; reason: string; rule_id: string }; ticket_id?: string };

function App() {
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("请先登录客服或审批账号。");
  const [result, setResult] = useState<CaseResult | null>(null);
  const [events, setEvents] = useState<Event[]>([]);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const response = await fetch("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: form.get("username"), password: form.get("password") }) });
    if (!response.ok) return setMessage("登录失败：请检查账号和密码。");
    const body = await response.json();
    setToken(body.access_token);
    setMessage("登录成功。创建案例后可查看规则、政策证据和审批状态。");
  }

  async function createCase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return setMessage("请先登录。");
    const form = new FormData(event.currentTarget);
    const response = await fetch("/cases", { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify({ customer_id: form.get("customer_id"), order_id: form.get("order_id"), request_type: form.get("request_type"), summary: form.get("summary"), submitted_on: form.get("submitted_on") }) });
    const body = await response.json();
    if (!response.ok) return setMessage(body.detail || "创建案例失败。");
    setResult(body);
    setMessage(body.status === "pending_approval" ? "案例已暂停，等待审批人操作。" : "案例已完成，无需审批。");
    await loadAudit(body.case_id);
  }

  async function loadAudit(caseId: string) {
    const response = await fetch(`/cases/${caseId}/audit`, { headers: { Authorization: `Bearer ${token}` } });
    if (response.ok) setEvents(await response.json());
  }

  async function decide(status: "approved" | "rejected") {
    if (!result || !token) return;
    const response = await fetch(`/cases/${result.case_id}/approval`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify({ status, note: "由演示页面提交" }) });
    const body = await response.json();
    if (!response.ok) return setMessage(body.detail || "审批失败：请以审批人账号重新登录。");
    setResult(body);
    setMessage(status === "approved" ? "审批已通过，模拟工单已创建。" : "审批已拒绝，未创建工单。");
    await loadAudit(result.case_id);
  }

  return <main>
    <header><p className="eyebrow">AUDITABLE BUSINESS AGENT</p><h1>可审计业务 Agent</h1><p>规则决定业务动作，政策检索提供证据，人工审批控制副作用。</p></header>
    <section className="panel"><h2>1. 登录</h2><form onSubmit={login} className="grid"><input name="username" placeholder="账号，例如 agent-1" required /><input name="password" type="password" placeholder="密码" required /><button>登录</button></form></section>
    <section className="panel"><h2>2. 创建售后案例</h2><form onSubmit={createCase} className="grid"><input name="customer_id" defaultValue="customer-1" required /><input name="order_id" defaultValue="ORD-100" required /><select name="request_type" defaultValue="return"><option value="return">退货</option><option value="defect">故障维修</option><option value="tracking">物流查询</option></select><input name="submitted_on" type="date" defaultValue="2026-09-15" required /><textarea name="summary" defaultValue="商品不适合，申请退货。" required /><button>提交案例</button></form></section>
    <p className="message">{message}</p>
    {result && <section className="panel"><h2>处理结果 · {result.case_id}</h2><p><strong>状态：</strong>{result.status}</p><p><strong>建议动作：</strong>{result.decision?.action || result.approval?.action}</p><p><strong>规则：</strong>{result.decision?.rule_id || result.approval?.rule_id}</p><p>{result.decision?.reason || result.approval?.reason}</p><p>{result.ticket_id && `工单：${result.ticket_id}`}</p>{result.status === "pending_approval" && <div className="actions"><button onClick={() => decide("approved")}>以审批人身份批准</button><button className="secondary" onClick={() => decide("rejected")}>拒绝</button></div>}</section>}
    {events.length > 0 && <section className="panel"><h2>审计轨迹</h2><ol>{events.map((item, index) => <li key={`${item.occurred_at}-${index}`}><strong>{item.event_type}</strong><span>{item.actor_id} · {new Date(item.occurred_at).toLocaleString()}</span><pre>{JSON.stringify(item.payload, null, 2)}</pre></li>)}</ol></section>}
  </main>;
}

createRoot(document.getElementById("root")!).render(<App />);
