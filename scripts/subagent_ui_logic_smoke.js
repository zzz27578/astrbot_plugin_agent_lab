// 子Agent 数据逻辑 harness：从 app.js 抽取真实函数源码，注入 stub 运行断言。
const fs = require("fs");
const src = fs.readFileSync("webui/app.js", "utf8");

function extract(name) {
  const marker = "function " + name + "(";
  const i = src.indexOf(marker);
  if (i < 0) throw new Error("not found: " + name);
  let j = src.indexOf("{", i), d = 0, str = null, esc = false;
  for (let k = j; k < src.length; k++) {
    const c = src[k];
    if (str) { if (esc) esc = false; else if (c === "\\") esc = true; else if (c === str) str = null; continue; }
    if (c === '"' || c === "'" || c === "`") { str = c; continue; }
    if (c === "{") d++;
    else if (c === "}") { d--; if (d === 0) return src.slice(i, k + 1); }
  }
  throw new Error("unbalanced: " + name);
}

const names = ["ensureSubAgents", "subAgentById", "subAgentHex", "subAgentColorOf", "newSubAgentLocalId", "setNodeOwner", "removeSubAgentById"];
const code = names.map(extract).join("\n\n");

// sandbox：提供 currentAgent + ensureWorkflow stub
const harness = `
let currentAgent;
function ensureWorkflow() {}
${code}
return { ensureSubAgents, subAgentById, setNodeOwner, removeSubAgentById, subAgentColorOf,
  setAgent: (a) => { currentAgent = a; }, getAgent: () => currentAgent };
`;
const api = new Function(harness)();

function assert(c, m) { if (!c) throw new Error("FAIL: " + m); }

// 构造一个含 2 子Agent + 3 节点 的方案
const agent = {
  sub_agents: [
    { sub_agent_id: "sa_a", name: "A", color: "#11aa22", member_node_ids: [] },
    { sub_agent_id: "sa_b", name: "B", color: "bad", member_node_ids: [] },
  ],
  workflow_nodes: [{ id: "n1" }, { id: "n2" }, { id: "n3" }],
};
api.setAgent(agent);

// 指派 n1,n2 -> A
api.setNodeOwner("n1", "sa_a");
api.setNodeOwner("n2", "sa_a");
assert(agent.workflow_nodes[0].owner === "sa_a", "n1.owner=sa_a");
assert(agent.workflow_nodes[1].owner === "sa_a", "n2.owner=sa_a");
const A = api.subAgentById("sa_a");
assert(JSON.stringify(A.member_node_ids) === JSON.stringify(["n1", "n2"]), "A 领地 [n1,n2]，得 " + JSON.stringify(A.member_node_ids));

// 改派 n1 -> B：应从 A 移除、加入 B
api.setNodeOwner("n1", "sa_b");
assert(agent.workflow_nodes[0].owner === "sa_b", "n1 改派 B");
assert(JSON.stringify(api.subAgentById("sa_a").member_node_ids) === JSON.stringify(["n2"]), "A 应只剩 n2");
assert(JSON.stringify(api.subAgentById("sa_b").member_node_ids) === JSON.stringify(["n1"]), "B 应有 n1");

// 颜色：A 合法返回，B 非法回退默认
assert(api.subAgentColorOf("sa_a") === "#11aa22", "A 颜色");
assert(api.subAgentColorOf("sa_b") === "#5b8def", "B 非法颜色回退默认，得 " + api.subAgentColorOf("sa_b"));

// 移出领地（subId 空）
api.setNodeOwner("n2", "");
assert(!("owner" in agent.workflow_nodes[1]), "n2 owner 应被删除");
assert(JSON.stringify(api.subAgentById("sa_a").member_node_ids) === JSON.stringify([]), "A 领地清空");

// 删除子Agent B：其成员 n1 的 owner 应清掉
api.removeSubAgentById("sa_b");
assert(api.subAgentById("sa_b") === null, "B 已删除");
assert(!("owner" in agent.workflow_nodes[0]), "删除 B 后 n1.owner 应被清，得 " + agent.workflow_nodes[0].owner);
assert(agent.sub_agents.length === 1, "应剩 1 个子Agent");

// ensureSubAgents 对缺字段方案安全
api.setAgent({ workflow_nodes: [] });
assert(Array.isArray(api.ensureSubAgents()) && api.getAgent().sub_agents.length === 0, "ensureSubAgents 惰性建数组");

console.log("ALL SUBAGENT-UI LOGIC TESTS PASSED");
