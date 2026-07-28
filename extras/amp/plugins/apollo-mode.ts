// @amp-agent-mode {"key":"apollo","label":"Apollo"}

import type { PluginAPI } from "@ampcode/plugin";

const MAIN_AGENT_NAME = "apollo-main";

const FABLE_ORACLE_TOOLS = [
    "find_thread",
    "finder",
    "librarian",
    "Read",
    "read_mcp_resource",
    "read_thread",
    "read_web_page",
    "shell_command",
    "shell_command_status",
    "view_media",
    "web_search",
] as const;

export default function (amp: PluginAPI) {
    const main = amp.createAgent({
        name: MAIN_AGENT_NAME,
        model: "openai/gpt-5.6-sol",
        instructions:
            "The oracle tool is routed to Claude Fable 5 for an independent second opinion.",
        tools: "all",
        reasoningEffort: "low",
        display: { label: "Apollo", color: "#0ea5e9" },
    });

    const fableOracle = amp.createAgent({
        name: "apollo-oracle",
        model: "anthropic/claude-fable-5",
        instructions: [
            "You are the Oracle, a read-only advisory subagent for code review, architecture, debugging, and planning.",
            "Use inspection tools to verify claims against the actual code before advising.",
            "Do not modify files or repository state; use shell only for read-only commands.",
            "Follow the caller's scope and requested output shape, lead with your recommendation, and return one complete response.",
        ].join(" "),
        tools: FABLE_ORACLE_TOOLS,
        reasoningEffort: "high",
        display: { label: "Apollo Oracle", color: "#d97706" },
    });

    amp.on("tool.call", async (event, ctx) => {
        if (event.tool !== "oracle") {
            return { action: "allow" };
        }

        const currentAgent = await ctx.thread.agent();
        if (
            currentAgent.definition.kind !== "agent-definition" ||
            currentAgent.definition.name !== MAIN_AGENT_NAME
        ) {
            return { action: "allow" };
        }

        const task =
            typeof event.input.task === "string" ? event.input.task.trim() : "";
        if (!task) {
            return {
                action: "synthesize",
                result: { output: "Fable Oracle requires a non-empty task." },
            };
        }

        const oracleThread = await fableOracle.createThread({
            parentThreadID: ctx.thread.id,
            speed: "standard",
        });
        const responsePromise = oracleThread.waitForResponse({
            timeoutMs: 10 * 60 * 1000,
        });
        responsePromise.catch(() => {});
        await oracleThread.appendUserMessage({
            type: "user-message",
            content: task,
        });
        const response = await responsePromise;
        const text = response.content
            .map((block) => (block.type === "text" ? block.text : ""))
            .join("");

        return {
            action: "synthesize",
            result: { output: text },
        };
    });

    amp.registerAgentMode({
        key: "apollo",
        label: "Apollo",
        description: "Fast execution with a deeper second opinion on demand.",
        color: "#0ea5e9",
        agent: main.definition,
    });
}
