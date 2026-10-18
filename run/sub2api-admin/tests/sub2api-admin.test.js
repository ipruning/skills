const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

// Endpoint and credential cases supply their own inputs, never the caller's.
for (const name of Object.keys(process.env)) {
    if (name.startsWith("SUB2API_")) delete process.env[name];
}

const script = path.join(__dirname, "..", "scripts", "sub2api-admin.js");
const { mapWithConcurrency } = require(script);

function response(res, data, status = 200) {
    res.writeHead(status, { "Content-Type": "application/json" });
    res.end(
        JSON.stringify({
            code: status >= 400 ? "ERROR" : 0,
            message: status >= 400 ? "error" : "success",
            data,
        }),
    );
}

function runCLI(baseURL, args, env = {}) {
    return new Promise((resolve, reject) => {
        const child = spawn(process.execPath, [script, ...args], {
            env: {
                ...process.env,
                SUB2API_BASE_URL: baseURL,
                SUB2API_ADMIN_API_KEY: "",
                SUB2API_JWT: "",
                SUB2API_ADMIN_EMAIL: "",
                SUB2API_ADMIN_PASSWORD: "",
                SUB2API_LOGIN_TOTP_CODE: "",
                SUB2API_REQUEST_TIMEOUT_MS: "30000",
                ...env,
            },
            stdio: ["ignore", "pipe", "pipe"],
        });
        let stdout = "";
        let stderr = "";
        child.stdout.on("data", (chunk) => {
            stdout += chunk;
        });
        child.stderr.on("data", (chunk) => {
            stderr += chunk;
        });
        child.on("error", reject);
        child.on("close", (code) => {
            if (code !== 0) {
                reject(new Error(`CLI exited ${code}: ${stderr}`));
                return;
            }
            resolve({ stdout, stderr });
        });
    });
}

async function withServer(handler, callback) {
    const server = http.createServer(handler);
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    try {
        await callback(`http://127.0.0.1:${address.port}`);
    } finally {
        await new Promise((resolve, reject) =>
            server.close((error) => (error ? reject(error) : resolve())),
        );
    }
}

test("upstream diagnostics require explicit opt-in", async () => {
    const requests = [];
    let loginCount = 0;
    let quotaRequestCount = 0;
    let usageRequestCount = 0;
    let failUsage = false;
    let omitUsageTokens = false;
    let negativeUsageTokens = false;
    let emptyQuota = false;
    let incompleteQuota = false;
    let malformedQuota = false;
    let malformedModel = false;
    let omitInputTokens = false;
    let omitRequests = false;
    let omitModel = false;
    let emptyPeriod = false;
    let inconsistentTokenTotals = false;
    let activeUsageWindowTokens = 0;
    let activeUsageUtilization = 0;
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-admin-test-"),
    );
    const pricingFile = path.join(tempDir, "pricing.json");
    fs.writeFileSync(
        pricingFile,
        JSON.stringify({
            as_of: "test",
            models: {
                "gpt-5.4": {
                    input: 2.5,
                    cached_input: 0.25,
                    output: 15,
                    cache_creation: 2.5,
                },
                "gpt-5.6-luna": {
                    input: 0.2,
                    cached_input: 0.02,
                    output: 1.2,
                    cache_creation: 0.25,
                },
            },
        }),
    );

    try {
        await withServer(
            (req, res) => {
                requests.push(req.url);
                if (req.url === "/api/v1/auth/login" && req.method === "POST") {
                    loginCount += 1;
                    response(res, {
                        access_token: "jwt-test",
                        token_type: "Bearer",
                        user: {
                            id: 1,
                            email: "admin@example.com",
                            role: "admin",
                        },
                    });
                    return;
                }
                assert.equal(req.headers.authorization, "Bearer jwt-test");
                if (req.url === "/api/v1/admin/system/version") {
                    response(res, { version: "1.2.3" });
                    return;
                }
                if (req.url.startsWith("/api/v1/admin/accounts?")) {
                    response(res, {
                        items: [
                            {
                                id: 6,
                                name: "account@example.com",
                                platform: "openai",
                                type: "oauth",
                                status: "active",
                                schedulable: true,
                            },
                        ],
                        page: 1,
                        page_size: 500,
                        pages: 1,
                        total: 1,
                    });
                    return;
                }
                if (req.url === "/api/v1/admin/openai/accounts/6/quota") {
                    quotaRequestCount += 1;
                    response(
                        res,
                        emptyQuota
                            ? null
                            : incompleteQuota
                              ? { fetched_at: 1 }
                              : malformedQuota
                                ? {
                                      rate_limit: {
                                          primary_window: { used_percent: 80 },
                                      },
                                  }
                                : {
                                      fetched_at: 1,
                                      rate_limit: {
                                          primary_window: { used_percent: 50 },
                                      },
                                  },
                    );
                    return;
                }
                if (req.url === "/api/v1/admin/accounts/6/usage") {
                    usageRequestCount += 1;
                    if (failUsage) {
                        response(res, null, 503);
                        return;
                    }
                    response(res, {
                        seven_day: {
                            utilization: activeUsageUtilization,
                            window_stats: omitUsageTokens
                                ? {}
                                : {
                                      tokens: negativeUsageTokens
                                          ? -1
                                          : activeUsageWindowTokens,
                                  },
                        },
                    });
                    return;
                }
                if (req.url.startsWith("/api/v1/admin/dashboard/models?")) {
                    response(res, {
                        start_date: "2026-08-26",
                        end_date: "2026-08-27",
                        models: [
                            {
                                ...(omitModel
                                    ? {}
                                    : {
                                          model: malformedModel
                                              ? "gpt-5.6-luna -> "
                                              : "gpt-5.6-luna -> gpt-5.4",
                                      }),
                                ...(omitRequests ? {} : { requests: 10 }),
                                ...(omitInputTokens
                                    ? {}
                                    : {
                                          input_tokens: emptyPeriod
                                              ? 0
                                              : 1_000_000,
                                      }),
                                cache_read_tokens: emptyPeriod ? 0 : 100_000,
                                cache_creation_tokens: 0,
                                output_tokens: emptyPeriod ? 0 : 100_000,
                                total_tokens: inconsistentTokenTotals
                                    ? 1
                                    : emptyPeriod
                                      ? 0
                                      : 1_200_000,
                                cost: 0.322,
                            },
                        ],
                    });
                    return;
                }
                response(res, null, 404);
            },
            async (baseURL) => {
                const args = [
                    "diagnostics",
                    "openai-routing",
                    "--start-date",
                    "2026-08-26",
                    "--end-date",
                    "2026-08-27",
                    "--timezone",
                    "Asia/Shanghai",
                    "--pricing-file",
                    pricingFile,
                    "--baseline-model",
                    "gpt-5.6-luna",
                ];
                const env = {
                    SUB2API_ADMIN_EMAIL: "admin@example.com",
                    SUB2API_ADMIN_PASSWORD: "secret",
                };
                const result = await runCLI(baseURL, args, env);
                const report = JSON.parse(result.stdout);
                assert.equal(loginCount, 1);
                assert.equal(quotaRequestCount, 0);
                assert.equal(report.upstream_quota_requested, false);
                assert.equal(report.active_usage_requested, false);
                assert.equal(report.system_version.version, "1.2.3");
                assert.equal(report.summary.complete, true);
                assert.equal(report.summary.accounts_failed, 0);
                assert.equal(report.summary.mismatch_tokens, 1_200_000);
                assert.equal(
                    report.accounts[0].pricing
                        .period_actual_model_equivalent_cost,
                    4.025,
                );
                assert.equal(
                    report.accounts[0].pricing.period_baseline_equivalent_cost,
                    0.322,
                );
                assert.equal(
                    report.accounts[0].pricing.implied_full_window_equivalent,
                    null,
                );
                assert.equal(report.accounts[0].pricing.used_percent, null);
                assert.equal(
                    report.accounts[0].pricing.scale_basis,
                    "selected_period_assumed_to_match_quota_window",
                );
                assert.equal(
                    requests.some((url) => url.includes("/accounts/6/usage")),
                    false,
                );

                const quotaResult = await runCLI(
                    baseURL,
                    [...args, "--include-upstream-quota"],
                    env,
                );
                const quotaReport = JSON.parse(quotaResult.stdout);
                assert.equal(loginCount, 2);
                assert.equal(quotaRequestCount, 1);
                assert.equal(quotaReport.upstream_quota_requested, true);
                assert.equal(quotaReport.accounts[0].pricing.used_percent, 50);
                assert.equal(
                    quotaReport.accounts[0].pricing
                        .implied_full_window_equivalent,
                    8.05,
                );

                emptyQuota = true;
                const emptyQuotaResult = await runCLI(
                    baseURL,
                    [...args, "--include-upstream-quota"],
                    env,
                );
                const emptyQuotaReport = JSON.parse(emptyQuotaResult.stdout);
                assert.equal(quotaRequestCount, 2);
                assert.match(
                    emptyQuotaReport.accounts[0].quota_error,
                    /quota object with fetched_at/,
                );
                assert.equal(emptyQuotaReport.summary.complete, false);
                assert.equal(
                    emptyQuotaReport.summary.upstream_evidence_failed,
                    1,
                );
                emptyQuota = false;

                incompleteQuota = true;
                const incompleteQuotaResult = await runCLI(
                    baseURL,
                    [...args, "--include-upstream-quota"],
                    env,
                );
                const incompleteQuotaReport = JSON.parse(
                    incompleteQuotaResult.stdout,
                );
                assert.match(
                    incompleteQuotaReport.accounts[0].quota_error,
                    /quota object with fetched_at/,
                );
                assert.equal(incompleteQuotaReport.summary.complete, false);
                assert.equal(
                    incompleteQuotaReport.summary.upstream_evidence_failed,
                    1,
                );
                incompleteQuota = false;

                malformedQuota = true;
                activeUsageWindowTokens = 1_200_000;
                const malformedQuotaResult = await runCLI(
                    baseURL,
                    [
                        ...args,
                        "--include-upstream-quota",
                        "--include-active-usage",
                    ],
                    env,
                );
                const malformedQuotaReport = JSON.parse(
                    malformedQuotaResult.stdout,
                );
                assert.match(
                    malformedQuotaReport.accounts[0].quota_error,
                    /quota object with fetched_at/,
                );
                assert.equal(
                    malformedQuotaReport.accounts[0].pricing.used_percent,
                    0,
                );
                assert.equal(
                    malformedQuotaReport.accounts[0].pricing
                        .implied_full_window_equivalent,
                    null,
                );
                malformedQuota = false;
                activeUsageWindowTokens = 0;

                const usageResult = await runCLI(
                    baseURL,
                    [...args, "--include-active-usage"],
                    env,
                );
                const usageReport = JSON.parse(usageResult.stdout);
                const usagePricing = usageReport.accounts[0].pricing;
                assert.equal(loginCount, 6);
                assert.equal(usageRequestCount, 2);
                assert.equal(usageReport.active_usage_requested, true);
                assert.equal(usagePricing.window_total_tokens, 0);
                assert.equal(usagePricing.approximate_window_scale, 0);
                assert.equal(
                    usagePricing.scale_basis,
                    "active_usage_window_tokens / selected_period_tokens",
                );
                assert.equal(
                    usagePricing.adjusted_window_actual_model_equivalent_cost,
                    0,
                );

                failUsage = true;
                const failedUsageResult = await runCLI(
                    baseURL,
                    [...args, "--include-active-usage"],
                    env,
                );
                const failedUsageReport = JSON.parse(failedUsageResult.stdout);
                const failedUsagePricing =
                    failedUsageReport.accounts[0].pricing;
                assert.equal(usageRequestCount, 3);
                assert.match(
                    failedUsageReport.accounts[0].usage_error,
                    /failed/,
                );
                assert.equal(failedUsageReport.summary.complete, false);
                assert.equal(
                    failedUsageReport.summary.upstream_evidence_failed,
                    1,
                );
                assert.equal(failedUsagePricing.approximate_window_scale, null);
                assert.equal(
                    failedUsagePricing.scale_basis,
                    "active_usage_unavailable",
                );
                assert.equal(
                    failedUsagePricing.adjusted_window_actual_model_equivalent_cost,
                    null,
                );
                assert.equal(
                    failedUsagePricing.adjusted_window_baseline_equivalent_cost,
                    null,
                );
                assert.equal(
                    failedUsagePricing.implied_full_window_equivalent,
                    null,
                );

                failUsage = false;
                omitUsageTokens = true;
                activeUsageUtilization = 75;
                const missingUsageTokensResult = await runCLI(
                    baseURL,
                    [...args, "--include-active-usage"],
                    env,
                );
                const missingUsageTokensReport = JSON.parse(
                    missingUsageTokensResult.stdout,
                );
                const missingUsageTokensPricing =
                    missingUsageTokensReport.accounts[0].pricing;
                assert.equal(usageRequestCount, 4);
                assert.match(
                    missingUsageTokensReport.accounts[0].usage_error,
                    /non-negative integer seven_day\.window_stats\.tokens/,
                );
                assert.equal(missingUsageTokensReport.summary.complete, false);
                assert.equal(
                    missingUsageTokensReport.summary.upstream_evidence_failed,
                    1,
                );
                assert.equal(
                    missingUsageTokensPricing.window_total_tokens,
                    null,
                );
                assert.equal(missingUsageTokensPricing.used_percent, null);
                assert.equal(
                    missingUsageTokensPricing.approximate_window_scale,
                    null,
                );
                assert.equal(
                    missingUsageTokensPricing.scale_basis,
                    "active_usage_unavailable",
                );
                assert.equal(
                    missingUsageTokensPricing.adjusted_window_actual_model_equivalent_cost,
                    null,
                );
                assert.equal(
                    missingUsageTokensPricing.implied_full_window_equivalent,
                    null,
                );

                omitUsageTokens = false;
                activeUsageUtilization = 0;
                negativeUsageTokens = true;
                const negativeUsageTokensResult = await runCLI(
                    baseURL,
                    [...args, "--include-active-usage"],
                    env,
                );
                const negativeUsageTokensPricing = JSON.parse(
                    negativeUsageTokensResult.stdout,
                ).accounts[0].pricing;
                const negativeUsageTokensReport = JSON.parse(
                    negativeUsageTokensResult.stdout,
                );
                assert.match(
                    negativeUsageTokensReport.accounts[0].usage_error,
                    /non-negative integer seven_day\.window_stats\.tokens/,
                );
                assert.equal(negativeUsageTokensReport.summary.complete, false);
                assert.equal(
                    negativeUsageTokensPricing.window_total_tokens,
                    null,
                );
                assert.equal(
                    negativeUsageTokensPricing.approximate_window_scale,
                    null,
                );

                omitInputTokens = true;
                const missingTokenCounterResult = await runCLI(
                    baseURL,
                    args,
                    env,
                );
                const missingTokenCounterPricing = JSON.parse(
                    missingTokenCounterResult.stdout,
                ).accounts[0].pricing;
                assert.equal(
                    missingTokenCounterPricing.token_counters_complete,
                    false,
                );
                assert.deepEqual(
                    missingTokenCounterPricing.invalid_token_counters,
                    ["input_tokens"],
                );
                assert.equal(
                    missingTokenCounterPricing.period_actual_model_equivalent_cost,
                    null,
                );

                omitInputTokens = false;
                omitRequests = true;
                const missingRequestCounterResult = await runCLI(
                    baseURL,
                    args,
                    env,
                );
                const missingRequestCounterReport = JSON.parse(
                    missingRequestCounterResult.stdout,
                );
                assert.equal(
                    missingRequestCounterReport.summary.complete,
                    false,
                );
                assert.equal(missingRequestCounterReport.summary.requests, 0);
                assert.equal(
                    missingRequestCounterReport.summary.total_tokens,
                    0,
                );
                assert.match(
                    missingRequestCounterReport.accounts[0].routing_error,
                    /routing response contains invalid fields: requests/,
                );

                omitRequests = false;
                omitModel = true;
                const missingModelLabelResult = await runCLI(
                    baseURL,
                    args,
                    env,
                );
                const missingModelLabelReport = JSON.parse(
                    missingModelLabelResult.stdout,
                );
                assert.equal(missingModelLabelReport.summary.complete, false);
                assert.match(
                    missingModelLabelReport.accounts[0].routing_error,
                    /routing response contains invalid fields: model/,
                );

                omitModel = false;
                malformedModel = true;
                const emptyModelComponentResult = await runCLI(
                    baseURL,
                    args,
                    env,
                );
                const emptyModelComponentReport = JSON.parse(
                    emptyModelComponentResult.stdout,
                );
                assert.equal(emptyModelComponentReport.summary.complete, false);
                assert.match(
                    emptyModelComponentReport.accounts[0].routing_error,
                    /routing response contains invalid fields: model/,
                );

                malformedModel = false;
                negativeUsageTokens = false;
                emptyPeriod = true;
                activeUsageWindowTokens = 100;
                const emptyPeriodResult = await runCLI(
                    baseURL,
                    [...args, "--include-active-usage"],
                    env,
                );
                const emptyPeriodPricing = JSON.parse(emptyPeriodResult.stdout)
                    .accounts[0].pricing;
                assert.equal(emptyPeriodPricing.period_total_tokens, 0);
                assert.equal(emptyPeriodPricing.approximate_window_scale, null);
                assert.equal(
                    emptyPeriodPricing.scale_basis,
                    "selected_period_empty",
                );

                emptyPeriod = false;
                inconsistentTokenTotals = true;
                const inconsistentTokenTotalsResult = await runCLI(
                    baseURL,
                    args,
                    env,
                );
                const inconsistentTokenTotalsReport = JSON.parse(
                    inconsistentTokenTotalsResult.stdout,
                );
                assert.equal(
                    inconsistentTokenTotalsReport.summary.complete,
                    false,
                );
                assert.match(
                    inconsistentTokenTotalsReport.accounts[0].routing_error,
                    /invalid fields: total_tokens/,
                );
                assert.deepEqual(
                    inconsistentTokenTotalsReport.accounts[0].pricing
                        .invalid_token_counters,
                    ["total_tokens"],
                );
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("upstream opt-in switches reject values before any request", async () => {
    let requestCount = 0;
    await withServer(
        (_req, res) => {
            requestCount += 1;
            response(res, null);
        },
        async (baseURL) => {
            for (const flag of [
                "--include-upstream-quota",
                "--include-active-usage",
            ]) {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "diagnostics",
                            "openai-routing",
                            "--start-date",
                            "2026-08-26",
                            "--end-date",
                            "2026-08-27",
                            flag,
                            "false",
                        ],
                        { SUB2API_ADMIN_API_KEY: "[REDACTED:api-key]" },
                    ),
                    new RegExp(`${flag} does not accept a value`),
                );
            }
            assert.equal(requestCount, 0);
        },
    );
});

test("diagnostics rejects an empty ID selection before any request", async () => {
    let requestCount = 0;
    await withServer(
        (_req, res) => {
            requestCount += 1;
            response(res, null);
        },
        async (baseURL) => {
            await assert.rejects(
                runCLI(
                    baseURL,
                    [
                        "diagnostics",
                        "openai-routing",
                        "--start-date",
                        "2026-08-26",
                        "--end-date",
                        "2026-08-27",
                        "--ids",
                        ",",
                    ],
                    { SUB2API_ADMIN_API_KEY: "[REDACTED:api-key]" },
                ),
                /--ids requires at least one ID/,
            );
            assert.equal(requestCount, 0);
        },
    );
});

test("diagnostics rejects non-decimal account IDs before any request", async () => {
    let requestCount = 0;
    await withServer(
        (_req, res) => {
            requestCount += 1;
            response(res, null);
        },
        async (baseURL) => {
            for (const id of ["1e2", "0x10", "01", "0"]) {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "diagnostics",
                            "openai-routing",
                            "--start-date",
                            "2026-08-26",
                            "--end-date",
                            "2026-08-27",
                            "--ids",
                            id,
                        ],
                        { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                    ),
                    new RegExp(`invalid id: ${id}`),
                );
            }
            assert.equal(requestCount, 0);
        },
    );
});

test("value flags reject missing values before any request", async () => {
    let requestCount = 0;
    await withServer(
        (_req, res) => {
            requestCount += 1;
            response(res, null);
        },
        async (baseURL) => {
            const cases = [
                [
                    ["api", "POST", "/admin/accounts/data", "--json"],
                    /--json requires a value/,
                ],
                [
                    [
                        "api",
                        "POST",
                        "/admin/accounts/data",
                        "--json",
                        "{}",
                        "--idempotency-key",
                    ],
                    /--idempotency-key requires a value/,
                ],
                [
                    ["api", "GET", "/admin/accounts/data", "--output-file"],
                    /--output-file requires a value/,
                ],
                [
                    ["api", "GET", "/admin/accounts/data", "--json", "{}"],
                    /api GET cannot include a request body/,
                ],
                [
                    [
                        "api",
                        "HEAD",
                        "/admin/accounts/data",
                        "--file",
                        "payload.json",
                    ],
                    /api HEAD cannot include a request body/,
                ],
                [
                    ["admin-key", "regenerate", "--file"],
                    /--file requires a value/,
                ],
            ];
            for (const [args, expected] of cases) {
                await assert.rejects(
                    runCLI(baseURL, args, {
                        SUB2API_ADMIN_API_KEY: "[REDACTED:api-key]",
                    }),
                    expected,
                );
            }
            assert.equal(requestCount, 0);
        },
    );
});

test("diagnostics marks malformed routing responses incomplete", async () => {
    await withServer(
        (req, res) => {
            if (req.url === "/api/v1/admin/system/version") {
                response(res, { version: "test" });
                return;
            }
            if (req.url.startsWith("/api/v1/admin/accounts?")) {
                response(res, {
                    items: [
                        {
                            id: 9,
                            name: "failed@example.com",
                            platform: "openai",
                            type: "oauth",
                            status: "active",
                            schedulable: true,
                        },
                    ],
                    page: 1,
                    pages: 1,
                });
                return;
            }
            if (req.url.startsWith("/api/v1/admin/dashboard/models?")) {
                response(res, {});
                return;
            }
            response(res, null, 404);
        },
        async (baseURL) => {
            const result = await runCLI(
                baseURL,
                [
                    "diagnostics",
                    "openai-routing",
                    "--start-date",
                    "2026-08-26",
                    "--end-date",
                    "2026-08-27",
                ],
                { SUB2API_JWT: "jwt-fixture" },
            );
            const report = JSON.parse(result.stdout);
            assert.equal(report.summary.complete, false);
            assert.equal(report.summary.accounts, 1);
            assert.equal(report.summary.accounts_failed, 1);
            assert.equal(report.summary.total_tokens, 0);
            assert.match(
                report.accounts[0].routing_error,
                /routing response must contain a models array/,
            );
        },
    );
});

test("diagnostics rejects routing data for a different requested period", async () => {
    await withServer(
        (req, res) => {
            if (req.url === "/api/v1/admin/system/version") {
                response(res, { version: "test" });
                return;
            }
            if (req.url.startsWith("/api/v1/admin/accounts?")) {
                response(res, {
                    items: [
                        {
                            id: 1,
                            name: "account@example.com",
                            platform: "openai",
                            type: "oauth",
                            status: "active",
                            schedulable: true,
                        },
                    ],
                    page: 1,
                    pages: 1,
                });
                return;
            }
            if (req.url.startsWith("/api/v1/admin/dashboard/models?")) {
                response(res, {
                    start_date: "2026-08-25",
                    end_date: "2026-08-27",
                    models: [
                        {
                            model: "gpt-5.6-luna -> gpt-5.4",
                            requests: 1,
                            input_tokens: 1,
                            cache_read_tokens: 0,
                            cache_creation_tokens: 0,
                            output_tokens: 0,
                            total_tokens: 1,
                            cost: 0,
                        },
                    ],
                });
                return;
            }
            response(res, null, 404);
        },
        async (baseURL) => {
            const result = await runCLI(
                baseURL,
                [
                    "diagnostics",
                    "openai-routing",
                    "--start-date",
                    "2026-08-26",
                    "--end-date",
                    "2026-08-27",
                ],
                { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
            );
            const report = JSON.parse(result.stdout);
            assert.equal(report.summary.complete, false);
            assert.equal(report.summary.accounts_failed, 1);
            assert.equal(report.summary.requests, 0);
            assert.match(
                report.accounts[0].routing_error,
                /period does not match requested dates: start_date/,
            );
        },
    );
});

test("diagnostics rejects incomplete account-list envelopes", async () => {
    let requestCount = 0;
    await withServer(
        (req, res) => {
            requestCount += 1;
            if (req.url === "/api/v1/admin/system/version") {
                response(res, { version: "test" });
                return;
            }
            if (req.url.startsWith("/api/v1/admin/accounts?")) {
                response(res, { items: [] });
                return;
            }
            response(res, null, 404);
        },
        async (baseURL) => {
            await assert.rejects(
                runCLI(
                    baseURL,
                    [
                        "diagnostics",
                        "openai-routing",
                        "--start-date",
                        "2026-08-26",
                        "--end-date",
                        "2026-08-27",
                    ],
                    { SUB2API_JWT: "jwt-fixture" },
                ),
                /positive integer pages value/,
            );
            assert.equal(requestCount, 2);
        },
    );
});

test("diagnostics rejects account totals that do not match assembled items", async () => {
    let requestCount = 0;
    await withServer(
        (req, res) => {
            requestCount += 1;
            if (req.url === "/api/v1/admin/system/version") {
                response(res, { version: "test" });
                return;
            }
            if (req.url.startsWith("/api/v1/admin/accounts?")) {
                response(res, {
                    items: [
                        {
                            id: 1,
                            name: "account@example.com",
                            platform: "openai",
                            type: "oauth",
                            status: "active",
                            schedulable: true,
                        },
                    ],
                    page: 1,
                    pages: 1,
                    total: 2,
                });
                return;
            }
            response(res, null, 404);
        },
        async (baseURL) => {
            await assert.rejects(
                runCLI(
                    baseURL,
                    [
                        "diagnostics",
                        "openai-routing",
                        "--start-date",
                        "2026-08-26",
                        "--end-date",
                        "2026-08-27",
                    ],
                    { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                ),
                /total does not match assembled items/,
            );
            assert.equal(requestCount, 2);
        },
    );
});

test("diagnostics rejects invalid account entries before opt-in requests", async () => {
    let quotaRequestCount = 0;
    let usageRequestCount = 0;
    await withServer(
        (req, res) => {
            if (req.url === "/api/v1/admin/system/version") {
                response(res, { version: "test" });
                return;
            }
            if (req.url.startsWith("/api/v1/admin/accounts?")) {
                response(res, {
                    items: [null],
                    page: 1,
                    pages: 1,
                });
                return;
            }
            if (req.url.includes("/quota")) quotaRequestCount += 1;
            if (req.url.includes("/usage")) usageRequestCount += 1;
            response(res, null, 404);
        },
        async (baseURL) => {
            await assert.rejects(
                runCLI(
                    baseURL,
                    [
                        "diagnostics",
                        "openai-routing",
                        "--start-date",
                        "2026-08-26",
                        "--end-date",
                        "2026-08-27",
                        "--include-upstream-quota",
                        "--include-active-usage",
                    ],
                    { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                ),
                /invalid account entries/,
            );
            assert.equal(quotaRequestCount, 0);
            assert.equal(usageRequestCount, 0);
        },
    );
});

test("diagnostics rejects duplicate and non-OpenAI accounts", async () => {
    const validAccount = {
        id: 1,
        name: "account@example.com",
        platform: "openai",
        type: "oauth",
        status: "active",
        schedulable: true,
    };
    const cases = [
        {
            items: [validAccount, { ...validAccount }],
            error: /duplicate account IDs/,
        },
        {
            items: [{ ...validAccount, platform: "anthropic" }],
            error: /non-OpenAI account/,
        },
    ];
    for (const { items, error } of cases) {
        let unexpectedRequestCount = 0;
        await withServer(
            (req, res) => {
                if (req.url === "/api/v1/admin/system/version") {
                    response(res, { version: "test" });
                    return;
                }
                if (req.url.startsWith("/api/v1/admin/accounts?")) {
                    response(res, { items, page: 1, pages: 1 });
                    return;
                }
                unexpectedRequestCount += 1;
                response(res, null, 404);
            },
            async (baseURL) => {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "diagnostics",
                            "openai-routing",
                            "--start-date",
                            "2026-08-26",
                            "--end-date",
                            "2026-08-27",
                        ],
                        { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                    ),
                    error,
                );
                assert.equal(unexpectedRequestCount, 0);
            },
        );
    }
});

test("diagnostics rejects impossible calendar dates before any request", async () => {
    let requestCount = 0;
    await withServer(
        (_req, res) => {
            requestCount += 1;
            response(res, null);
        },
        async (baseURL) => {
            await assert.rejects(
                runCLI(
                    baseURL,
                    [
                        "diagnostics",
                        "openai-routing",
                        "--start-date",
                        "2026-02-30",
                        "--end-date",
                        "2026-03-01",
                    ],
                    { SUB2API_ADMIN_API_KEY: "fixture-credential" },
                ),
                /valid ordered YYYY-MM-DD values/,
            );
            assert.equal(requestCount, 0);
        },
    );
});

test("diagnostics rejects invalid timezone before any request", async () => {
    let requestCount = 0;
    await withServer(
        (_req, res) => {
            requestCount += 1;
            response(res, null);
        },
        async (baseURL) => {
            await assert.rejects(
                runCLI(
                    baseURL,
                    [
                        "diagnostics",
                        "openai-routing",
                        "--start-date",
                        "2026-08-26",
                        "--end-date",
                        "2026-08-27",
                        "--timezone",
                        "Not/A/Timezone",
                    ],
                    { SUB2API_ADMIN_API_KEY: "[REDACTED:api-key]" },
                ),
                /invalid timezone/,
            );
            assert.equal(requestCount, 0);
        },
    );
});

test("diagnostics rejects invalid concurrency before any request", async () => {
    let requestCount = 0;
    await withServer(
        (_req, res) => {
            requestCount += 1;
            response(res, null);
        },
        async (baseURL) => {
            for (const value of ["0", "typo"]) {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "diagnostics",
                            "openai-routing",
                            "--start-date",
                            "2026-08-26",
                            "--end-date",
                            "2026-08-27",
                            "--concurrency",
                            value,
                        ],
                        { SUB2API_ADMIN_API_KEY: "[REDACTED:api-key]" },
                    ),
                    /--concurrency must be a positive integer/,
                );
            }
            assert.equal(requestCount, 0);
        },
    );
});

test("diagnostics rejects invalid prices before any request", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-negative-price-test-"),
    );
    const pricingFile = path.join(tempDir, "pricing.json");
    fs.writeFileSync(
        pricingFile,
        JSON.stringify({
            models: {
                model: {
                    input: -1,
                    cached_input: 0,
                    output: 0,
                    cache_creation: 0,
                },
            },
        }),
    );
    let requestCount = 0;
    try {
        await withServer(
            (_req, res) => {
                requestCount += 1;
                response(res, null);
            },
            async (baseURL) => {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "diagnostics",
                            "openai-routing",
                            "--start-date",
                            "2026-08-26",
                            "--end-date",
                            "2026-08-27",
                            "--pricing-file",
                            pricingFile,
                        ],
                        { SUB2API_ADMIN_API_KEY: "fixture-credential" },
                    ),
                    /must be non-negative numbers/,
                );

                fs.writeFileSync(
                    pricingFile,
                    JSON.stringify({
                        models: {
                            model: {
                                input: null,
                                cached_input: 0,
                                output: 0,
                                cache_creation: 0,
                            },
                        },
                    }),
                );
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "diagnostics",
                            "openai-routing",
                            "--start-date",
                            "2026-08-26",
                            "--end-date",
                            "2026-08-27",
                            "--pricing-file",
                            pricingFile,
                        ],
                        { SUB2API_ADMIN_API_KEY: "[REDACTED:api-key]" },
                    ),
                    /must be non-negative numbers/,
                );

                fs.writeFileSync(
                    pricingFile,
                    JSON.stringify({
                        models: {
                            model: {
                                input: 0,
                                cached_input: 0,
                                output: 0,
                            },
                        },
                    }),
                );
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "diagnostics",
                            "openai-routing",
                            "--start-date",
                            "2026-08-26",
                            "--end-date",
                            "2026-08-27",
                            "--pricing-file",
                            pricingFile,
                        ],
                        { SUB2API_ADMIN_API_KEY: "[REDACTED:api-key]" },
                    ),
                    /must be non-negative numbers/,
                );
                assert.equal(requestCount, 0);
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("diagnostic reports reserve a new file before requesting", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-report-existing-test-"),
    );
    const destination = path.join(tempDir, "report.json");
    fs.writeFileSync(destination, "keep\n");
    let requestCount = 0;
    try {
        await withServer(
            (_req, res) => {
                requestCount += 1;
                response(res, null);
            },
            async (baseURL) => {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "diagnostics",
                            "openai-routing",
                            "--start-date",
                            "2026-08-26",
                            "--end-date",
                            "2026-08-27",
                            "--file",
                            destination,
                        ],
                        { SUB2API_ADMIN_API_KEY: "fixture-credential" },
                    ),
                    /EEXIST/,
                );
                assert.equal(requestCount, 0);
                assert.equal(fs.readFileSync(destination, "utf8"), "keep\n");
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("credential-bearing requests reject redirects", async () => {
    let redirectedRequestCount = 0;
    await withServer(
        (_req, res) => {
            redirectedRequestCount += 1;
            response(res, { version: "must-not-be-read" });
        },
        async (redirectURL) => {
            await withServer(
                (_req, res) => {
                    res.writeHead(307, { Location: `${redirectURL}/capture` });
                    res.end();
                },
                async (baseURL) => {
                    await assert.rejects(
                        runCLI(baseURL, ["system", "version"], {
                            SUB2API_ADMIN_API_KEY: "fixture-credential",
                        }),
                        /failed: Temporary Redirect/,
                    );
                    await assert.rejects(
                        runCLI(baseURL, ["system", "version"], {
                            SUB2API_ADMIN_EMAIL: "admin@example.com",
                            SUB2API_ADMIN_PASSWORD: "fixture-password",
                        }),
                        /failed: Temporary Redirect/,
                    );
                    await assert.rejects(
                        runCLI(
                            baseURL,
                            ["api", "GET", "/admin/export", "--raw"],
                            { SUB2API_ADMIN_API_KEY: "fixture-credential" },
                        ),
                        /failed: Temporary Redirect/,
                    );
                },
            );
        },
    );
    assert.equal(redirectedRequestCount, 0);
});

test("Admin API Key takes precedence without logging in", async () => {
    const fixtureCredential = ["fixture", "credential"].join("-");
    await withServer(
        (req, res) => {
            assert.equal(req.url, "/api/v1/admin/system/version");
            assert.equal(req.headers["x-api-key"], fixtureCredential);
            assert.equal(req.headers.authorization, undefined);
            response(res, { version: "2.0.0" });
        },
        async (baseURL) => {
            const result = await runCLI(
                `${baseURL}/admin/dashboard`,
                ["system", "version"],
                {
                    SUB2API_ADMIN_API_KEY: fixtureCredential,
                    SUB2API_ADMIN_EMAIL: "should-not-login@example.com",
                    SUB2API_ADMIN_PASSWORD: ["unused", "fixture"].join("-"),
                },
            );
            assert.equal(JSON.parse(result.stdout).version, "2.0.0");
        },
    );
});

test("system version rejects an incomplete response", async () => {
    let requestCount = 0;
    await withServer(
        (req, res) => {
            requestCount += 1;
            assert.equal(req.url, "/api/v1/admin/system/version");
            response(res, {});
        },
        async (baseURL) => {
            await assert.rejects(
                runCLI(baseURL, ["system", "version"], {
                    SUB2API_JWT: "jwt-fixture",
                }),
                /system version response must contain a non-empty version/,
            );
            assert.equal(requestCount, 1);
        },
    );
});

test("Admin API Key regeneration writes the one-time secret to a new 0600 file", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-admin-key-test-"),
    );
    const destination = path.join(tempDir, "admin-key.txt");
    const fixtureCredential = ["old", "fixture", "credential"].join("-");
    try {
        await withServer(
            (req, res) => {
                assert.equal(req.method, "POST");
                assert.equal(
                    req.url,
                    "/api/v1/admin/settings/admin-api-key/regenerate",
                );
                assert.equal(req.headers["x-api-key"], fixtureCredential);
                response(res, { key: "admin-0123456789abcdef" });
            },
            async (baseURL) => {
                const result = await runCLI(
                    baseURL,
                    ["admin-key", "regenerate", "--file", destination],
                    {
                        SUB2API_ADMIN_API_KEY: fixtureCredential,
                    },
                );
                assert.equal(
                    fs.readFileSync(destination, "utf8"),
                    "admin-0123456789abcdef\n",
                );
                assert.equal(fs.statSync(destination).mode & 0o777, 0o600);
                assert.equal(
                    JSON.parse(result.stdout).masked_key,
                    "admin-0123...cdef",
                );
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("Admin API Key regeneration does not reveal short keys", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-admin-key-short-test-"),
    );
    const destination = path.join(tempDir, "admin-key.txt");
    try {
        await withServer(
            (_req, res) => {
                response(res, { key: "short-key" });
            },
            async (baseURL) => {
                const result = await runCLI(
                    baseURL,
                    ["admin-key", "regenerate", "--file", destination],
                    { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                );
                assert.equal(
                    fs.readFileSync(destination, "utf8"),
                    "short-key\n",
                );
                assert.equal(JSON.parse(result.stdout).masked_key, "***");
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("Admin API Key regeneration rejects an existing destination before any request", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-admin-key-existing-test-"),
    );
    const destination = path.join(tempDir, "admin-key.txt");
    fs.writeFileSync(destination, "keep\n");
    let requestCount = 0;
    try {
        await withServer(
            (_req, res) => {
                requestCount += 1;
                response(res, { key: "must-not-be-created" });
            },
            async (baseURL) => {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        ["admin-key", "regenerate", "--file", destination],
                        { SUB2API_ADMIN_API_KEY: "fixture-credential" },
                    ),
                    /EEXIST/,
                );
                assert.equal(requestCount, 0);
                assert.equal(fs.readFileSync(destination, "utf8"), "keep\n");
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("Admin API Key regeneration warns after the request starts", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-admin-key-ambiguous-test-"),
    );
    const destination = path.join(tempDir, "admin-key.txt");
    let requestCount = 0;
    try {
        await withServer(
            (req, res) => {
                requestCount += 1;
                assert.equal(req.method, "POST");
                assert.equal(
                    req.url,
                    "/api/v1/admin/settings/admin-api-key/regenerate",
                );
                response(res, { key: ["abc"] });
            },
            async (baseURL) => {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        ["admin-key", "regenerate", "--file", destination],
                        { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                    ),
                    /may have taken effect.*Do not retry regenerate automatically.*reserved file remains.*unset SUB2API_ADMIN_API_KEY.*SUB2API_JWT.*admin-key status/,
                );
                assert.equal(requestCount, 1);
                assert.equal(fs.existsSync(destination), true);
                assert.equal(fs.statSync(destination).size, 0);
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("Admin API Key deletion warns after the request starts", async () => {
    let requestCount = 0;
    await withServer(
        (req, res) => {
            requestCount += 1;
            assert.equal(req.method, "DELETE");
            assert.equal(req.url, "/api/v1/admin/settings/admin-api-key");
            res.destroy();
        },
        async (baseURL) => {
            await assert.rejects(
                runCLI(baseURL, ["admin-key", "delete"], {
                    SUB2API_ADMIN_API_KEY: "fixture-admin-key",
                }),
                /may have taken effect.*Do not retry automatically.*Unset SUB2API_ADMIN_API_KEY.*SUB2API_JWT.*admin-key status/,
            );
            assert.equal(requestCount, 1);
        },
    );
});

test("Admin API Key regeneration rejects control characters", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-admin-key-control-test-"),
    );
    const destination = path.join(tempDir, "admin-key.txt");
    try {
        await withServer(
            (_req, res) => {
                response(res, { key: "admin-abc\nxyz" });
            },
            async (baseURL) => {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        ["admin-key", "regenerate", "--file", destination],
                        { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                    ),
                    /control characters.*may have taken effect.*Do not retry regenerate automatically/,
                );
                assert.equal(fs.existsSync(destination), true);
                assert.equal(fs.statSync(destination).size, 0);
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("Admin API Key regeneration rejects values outside the HTTP header byte range", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-admin-key-byte-range-test-"),
    );
    const destination = path.join(tempDir, "admin-key.txt");
    try {
        await withServer(
            (_req, res) => {
                response(res, { key: "admin-🔑" });
            },
            async (baseURL) => {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        ["admin-key", "regenerate", "--file", destination],
                        { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                    ),
                    /outside the HTTP header byte range.*may have taken effect.*Do not retry regenerate automatically/,
                );
                assert.equal(fs.existsSync(destination), true);
                assert.equal(fs.statSync(destination).size, 0);
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("generic API output reserves a new 0600 file before requesting", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-account-export-test-"),
    );
    const destination = path.join(tempDir, "accounts.json");
    const payloadFile = path.join(tempDir, "payload.json");
    const misspelledOutputFlag = ["--output-", "fi", "el"].join("");
    fs.writeFileSync(payloadFile, "{}\n");
    let requestCount = 0;
    try {
        await withServer(
            (req, res) => {
                requestCount += 1;
                assert.equal(req.method, "GET");
                assert.equal(req.url, "/api/v1/admin/accounts/data");
                assert.equal(req.headers.authorization, "Bearer jwt-fixture");
                response(res, [
                    {
                        id: 7,
                        credentials: { access_token: "sensitive-fixture" },
                    },
                ]);
            },
            async (baseURL) => {
                const result = await runCLI(
                    baseURL,
                    [
                        "api",
                        "GET",
                        "/admin/accounts/data",
                        "--output-file",
                        destination,
                    ],
                    { SUB2API_JWT: "jwt-fixture" },
                );
                assert.equal(JSON.parse(result.stdout).format, "json");
                assert.equal(fs.statSync(destination).mode & 0o777, 0o600);
                assert.deepEqual(
                    JSON.parse(fs.readFileSync(destination, "utf8")),
                    [
                        {
                            id: 7,
                            credentials: { access_token: "sensitive-fixture" },
                        },
                    ],
                );
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "api",
                            "POST",
                            "/admin/accounts/data",
                            "--output-file",
                            destination,
                        ],
                        { SUB2API_JWT: "jwt-fixture" },
                    ),
                    /EEXIST/,
                );
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "api",
                            "GET",
                            "/admin/accounts/data",
                            misspelledOutputFlag,
                            path.join(tempDir, "misspelled.json"),
                        ],
                        { SUB2API_JWT: "jwt-fixture" },
                    ),
                    new RegExp(`unknown flag: ${misspelledOutputFlag}`),
                );
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "api",
                            "POST",
                            "/admin/accounts/data",
                            "--json",
                            "{}",
                            "--file",
                            payloadFile,
                        ],
                        { SUB2API_JWT: "jwt-fixture" },
                    ),
                    /--json and --file cannot be used together/,
                );
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "api",
                            "GET",
                            "/admin/accounts/data",
                            "--raw",
                            "false",
                        ],
                        { SUB2API_JWT: "jwt-fixture" },
                    ),
                    /--raw does not accept a value/,
                );
                assert.equal(requestCount, 1);
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("raw API output preserves response bytes", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-raw-output-test-"),
    );
    const destination = path.join(tempDir, "backup.bin");
    const content = Buffer.from([0x00, 0x61, 0x80, 0xff, 0xc3, 0x28]);
    try {
        await withServer(
            (req, res) => {
                assert.equal(req.url, "/api/v1/admin/backup");
                res.writeHead(200, {
                    "Content-Type": "application/octet-stream",
                });
                res.end(content);
            },
            async (baseURL) => {
                const result = await runCLI(
                    baseURL,
                    [
                        "api",
                        "GET",
                        "/admin/backup",
                        "--raw",
                        "--output-file",
                        destination,
                    ],
                    { SUB2API_JWT: "jwt-fixture" },
                );
                assert.equal(JSON.parse(result.stdout).format, "raw");
                assert.deepEqual(fs.readFileSync(destination), content);
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("generic JSON output streams the data field from a chunked response", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-json-stream-test-"),
    );
    const destination = path.join(tempDir, "large.json");
    const data = {
        items: Array.from({ length: 10_000 }, (_, id) => ({
            id,
            value: `account-${id}`,
        })),
    };
    const content = Buffer.from(
        JSON.stringify({ code: 0, message: "success", data }),
    );
    try {
        await withServer(
            (_req, res) => {
                res.writeHead(200, { "Content-Type": "application/json" });
                for (let offset = 0; offset < content.length; offset += 17) {
                    res.write(content.subarray(offset, offset + 17));
                }
                res.end();
            },
            async (baseURL) => {
                const result = await runCLI(
                    baseURL,
                    [
                        "api",
                        "GET",
                        "/admin/accounts/data",
                        "--output-file",
                        destination,
                    ],
                    { SUB2API_JWT: "jwt-fixture" },
                );
                assert.equal(JSON.parse(result.stdout).format, "json");
                assert.deepEqual(
                    JSON.parse(fs.readFileSync(destination)),
                    data,
                );
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("generic JSON output rejects invalid UTF-8 in streamed data", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-invalid-utf8-test-"),
    );
    const destination = path.join(tempDir, "invalid.json");
    const content = Buffer.concat([
        Buffer.from('{"code":0,"message":"success","data":"valid'),
        Buffer.from([0xff]),
        Buffer.from('"}'),
    ]);
    try {
        await withServer(
            (_req, res) => {
                res.writeHead(200, { "Content-Type": "application/json" });
                for (let offset = 0; offset < content.length; offset += 5) {
                    res.write(content.subarray(offset, offset + 5));
                }
                res.end();
            },
            async (baseURL) => {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "api",
                            "GET",
                            "/admin/invalid-utf8",
                            "--output-file",
                            destination,
                        ],
                        { SUB2API_JWT: "jwt-fixture" },
                    ),
                    /invalid UTF-8/,
                );
                assert.equal(fs.statSync(destination).size, 0);
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("raw JSON output rejects invalid UTF-8", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-raw-invalid-utf8-test-"),
    );
    const destination = path.join(tempDir, "invalid.json");
    const content = Buffer.concat([
        Buffer.from('{"code":0,"message":"success","data":"valid'),
        Buffer.from([0xff]),
        Buffer.from('"}'),
    ]);
    try {
        await withServer(
            (_req, res) => {
                res.writeHead(200, { "Content-Type": "application/json" });
                for (let offset = 0; offset < content.length; offset += 5) {
                    res.write(content.subarray(offset, offset + 5));
                }
                res.end();
            },
            async (baseURL) => {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "api",
                            "GET",
                            "/admin/raw-invalid-utf8",
                            "--raw",
                            "--output-file",
                            destination,
                        ],
                        { SUB2API_JWT: "jwt-fixture" },
                    ),
                    /invalid UTF-8/,
                );
                assert.equal(fs.statSync(destination).size, 0);
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("generic JSON output rejects invalid UTF-8 in buffered responses", async () => {
    const content = Buffer.concat([
        Buffer.from('{"code":0,"message":"success","data":"valid'),
        Buffer.from([0xff]),
        Buffer.from('"}'),
    ]);
    await withServer(
        (_req, res) => {
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(content);
        },
        async (baseURL) => {
            await assert.rejects(
                runCLI(baseURL, ["api", "GET", "/admin/invalid-utf8"], {
                    SUB2API_JWT: "jwt-fixture",
                }),
                /invalid UTF-8/,
            );
        },
    );
});

test("raw JSON output rejects malformed non-object roots", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-raw-malformed-json-test-"),
    );
    const destination = path.join(tempDir, "malformed.json");
    try {
        await withServer(
            (_req, res) => {
                res.writeHead(200, { "Content-Type": "application/json" });
                res.end("[broken");
            },
            async (baseURL) => {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "api",
                            "GET",
                            "/admin/malformed-json",
                            "--raw",
                            "--output-file",
                            destination,
                        ],
                        { SUB2API_JWT: "jwt-fixture" },
                    ),
                    /invalid compound JSON/,
                );
                assert.equal(fs.statSync(destination).size, 0);
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("raw output accepts bodyless JSON success responses", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-raw-bodyless-test-"),
    );
    const destination = path.join(tempDir, "empty.json");
    try {
        await withServer(
            (_req, res) => {
                res.writeHead(204, { "Content-Type": "application/json" });
                res.end();
            },
            async (baseURL) => {
                const result = await runCLI(
                    baseURL,
                    [
                        "api",
                        "POST",
                        "/admin/bodyless",
                        "--raw",
                        "--output-file",
                        destination,
                    ],
                    { SUB2API_JWT: "jwt-fixture" },
                );
                assert.equal(JSON.parse(result.stdout).format, "raw");
                assert.equal(fs.statSync(destination).size, 0);

                const stdoutResult = await runCLI(
                    baseURL,
                    ["api", "POST", "/admin/bodyless", "--raw"],
                    { SUB2API_JWT: "jwt-fixture" },
                );
                assert.equal(stdoutResult.stdout, "");

                const defaultResult = await runCLI(
                    baseURL,
                    ["api", "POST", "/admin/bodyless"],
                    { SUB2API_JWT: "jwt-fixture" },
                );
                assert.equal(defaultResult.stdout, "null\n");
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("generic API output rejects non-JSON and malformed success responses", async () => {
    let requestCount = 0;
    await withServer(
        (req, res) => {
            requestCount += 1;
            if (req.url === "/api/v1/admin/html") {
                res.writeHead(200, { "Content-Type": "text/html" });
                res.end("<html>blocked</html>");
                return;
            }
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ code: 0, message: "success" }));
        },
        async (baseURL) => {
            await assert.rejects(
                runCLI(baseURL, ["api", "GET", "/admin/html"], {
                    SUB2API_JWT: "jwt-fixture",
                }),
                /response is not valid JSON.*--raw for non-JSON responses/,
            );
            await assert.rejects(
                runCLI(baseURL, ["api", "GET", "/admin/malformed"], {
                    SUB2API_JWT: "jwt-fixture",
                }),
                /response is not a JSON envelope.*--raw for non-JSON responses/,
            );
            assert.equal(requestCount, 2);
        },
    );
});

test("raw JSON output rejects an application error with HTTP 200", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-raw-error-test-"),
    );
    const destination = path.join(tempDir, "error.json");
    let requestCount = 0;
    try {
        await withServer(
            (_req, res) => {
                requestCount += 1;
                res.writeHead(200, { "Content-Type": "application/json" });
                res.end(
                    JSON.stringify({
                        code: "PERMISSION_DENIED",
                        message: "permission denied",
                        data: null,
                    }),
                );
            },
            async (baseURL) => {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "api",
                            "GET",
                            "/admin/export",
                            "--raw",
                            "--output-file",
                            destination,
                        ],
                        { SUB2API_JWT: "jwt-fixture" },
                    ),
                    /permission denied/,
                );
                assert.equal(requestCount, 1);
                assert.equal(fs.statSync(destination).size, 0);
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("raw JSON output preserves compound data", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-raw-compound-test-"),
    );
    const stdoutContent = Buffer.from(
        JSON.stringify({
            code: 0,
            message: "success",
            data: { version: "1.2.3" },
        }),
    );
    const fileContent = Buffer.from(
        JSON.stringify({
            code: 0,
            message: "success",
            data: [1, { ok: true }],
        }),
    );
    const destination = path.join(tempDir, "compound.json");
    try {
        await withServer(
            (req, res) => {
                const content =
                    req.url === "/api/v1/admin/compound-stdout"
                        ? stdoutContent
                        : fileContent;
                res.writeHead(200, { "Content-Type": "application/json" });
                for (let offset = 0; offset < content.length; offset += 11) {
                    res.write(content.subarray(offset, offset + 11));
                }
                res.end();
            },
            async (baseURL) => {
                const stdoutResult = await runCLI(
                    baseURL,
                    ["api", "GET", "/admin/compound-stdout", "--raw"],
                    { SUB2API_JWT: "jwt-fixture" },
                );
                assert.equal(stdoutResult.stdout, stdoutContent.toString());

                await runCLI(
                    baseURL,
                    [
                        "api",
                        "GET",
                        "/admin/compound-file",
                        "--raw",
                        "--output-file",
                        destination,
                    ],
                    { SUB2API_JWT: "jwt-fixture" },
                );
                assert.deepEqual(fs.readFileSync(destination), fileContent);
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("Admin API errors preserve HTTP status for JSON null bodies", async () => {
    await withServer(
        (_req, res) => {
            res.writeHead(503, { "Content-Type": "application/json" });
            res.end("null");
        },
        async (baseURL) => {
            for (const extraArgs of [[], ["--raw"]]) {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        ["api", "GET", "/admin/null-error", ...extraArgs],
                        { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                    ),
                    /GET \/api\/v1\/admin\/null-error failed: Service Unavailable/,
                );
            }
        },
    );
});

test("raw JSON output accepts an empty object and rejects a trailing comma", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-raw-empty-object-test-"),
    );
    const destination = path.join(tempDir, "empty.json");
    const headDestination = path.join(tempDir, "head.json");
    try {
        await withServer(
            (req, res) => {
                if (req.method === "HEAD") {
                    res.writeHead(
                        req.url === "/api/v1/admin/head-error" ? 503 : 200,
                        { "Content-Type": "application/json" },
                    );
                    res.end();
                    return;
                }
                const content =
                    req.url === "/api/v1/admin/empty-object"
                        ? Buffer.from("{}")
                        : Buffer.from('{"data":1,}');
                res.writeHead(200, { "Content-Type": "application/json" });
                res.end(content);
            },
            async (baseURL) => {
                const stdoutResult = await runCLI(
                    baseURL,
                    ["api", "GET", "/admin/empty-object", "--raw"],
                    { SUB2API_JWT: "jwt-fixture" },
                );
                assert.equal(stdoutResult.stdout, "{}");

                await runCLI(
                    baseURL,
                    [
                        "api",
                        "GET",
                        "/admin/empty-object",
                        "--raw",
                        "--output-file",
                        destination,
                    ],
                    { SUB2API_JWT: "jwt-fixture" },
                );
                assert.deepEqual(
                    fs.readFileSync(destination),
                    Buffer.from("{}"),
                );

                await runCLI(
                    baseURL,
                    [
                        "api",
                        "HEAD",
                        "/admin/empty-object",
                        "--raw",
                        "--output-file",
                        headDestination,
                    ],
                    { SUB2API_JWT: "jwt-fixture" },
                );
                assert.equal(fs.statSync(headDestination).size, 0);

                await assert.rejects(
                    runCLI(baseURL, ["api", "HEAD", "/admin/head-error"], {
                        SUB2API_JWT: "jwt-fixture",
                    }),
                    /Service Unavailable/,
                );

                await assert.rejects(
                    runCLI(
                        baseURL,
                        ["api", "GET", "/admin/trailing-comma", "--raw"],
                        { SUB2API_JWT: "jwt-fixture" },
                    ),
                    /JSON response has an invalid key/,
                );
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("diagnostics defers upstream opt-in requests until routing succeeds", async () => {
    const requests = [];
    await withServer(
        (req, res) => {
            requests.push(req.url);
            if (req.url === "/api/v1/admin/system/version") {
                response(res, { version: "test" });
                return;
            }
            if (req.url.startsWith("/api/v1/admin/accounts?")) {
                response(res, {
                    items: [
                        {
                            id: 10,
                            name: "failed@example.com",
                            platform: "openai",
                            type: "oauth",
                            status: "active",
                            schedulable: true,
                        },
                    ],
                    page: 1,
                    pages: 1,
                });
                return;
            }
            if (req.url.startsWith("/api/v1/admin/dashboard/models?")) {
                response(res, null, 503);
                return;
            }
            response(res, null, 404);
        },
        async (baseURL) => {
            const result = await runCLI(
                baseURL,
                [
                    "diagnostics",
                    "openai-routing",
                    "--start-date",
                    "2026-08-26",
                    "--end-date",
                    "2026-08-27",
                    "--include-upstream-quota",
                    "--include-active-usage",
                ],
                { SUB2API_JWT: "jwt-fixture" },
            );
            const report = JSON.parse(result.stdout);
            assert.equal(report.summary.complete, false);
            assert.equal(
                requests.some((url) =>
                    /\/admin\/(?:openai\/accounts\/10\/quota|accounts\/10\/usage)/.test(
                        url,
                    ),
                ),
                false,
            );
        },
    );
});

test("generic API command accepts Admin paths and rejects path traversal", async () => {
    let requestCount = 0;
    await withServer(
        (req, res) => {
            requestCount += 1;
            assert.equal(req.url, "/api/v1/admin/system/version");
            response(res, { version: "test" });
        },
        async (baseURL) => {
            const valid = await runCLI(
                baseURL,
                ["api", "GET", "/admin/system/version"],
                { SUB2API_JWT: "jwt-fixture" },
            );
            assert.equal(JSON.parse(valid.stdout).version, "test");
            assert.equal(requestCount, 1);

            await assert.rejects(
                runCLI(baseURL, ["api", "GET", "/api/v1/admin/../auth/me"], {
                    SUB2API_ADMIN_API_KEY: "fixture-credential",
                }),
                /Admin API path must stay under \/api\/v1\/admin/,
            );
            await assert.rejects(
                runCLI(baseURL, ["api", "GET", "/api/v1/admin/..%2fauth/me"], {
                    SUB2API_ADMIN_API_KEY: "fixture-admin-key",
                }),
                /Admin API path must stay under \/api\/v1\/admin/,
            );
            await assert.rejects(
                runCLI(
                    baseURL,
                    [
                        "api",
                        "POST",
                        "/admin/settings//admin-api-key/regenerate",
                    ],
                    { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                ),
                /Admin API path must stay under \/api\/v1\/admin/,
            );
            assert.equal(requestCount, 1);
        },
    );
});

test("Admin API Key regeneration removes its reservation when authentication fails", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-admin-key-auth-failure-test-"),
    );
    const destination = path.join(tempDir, "admin-key.txt");
    let requestCount = 0;
    try {
        await withServer(
            (_req, res) => {
                requestCount += 1;
                response(res, { key: "must-not-be-created" });
            },
            async (baseURL) => {
                await assert.rejects(
                    runCLI(baseURL, [
                        "admin-key",
                        "regenerate",
                        "--file",
                        destination,
                    ]),
                    /Missing authentication/,
                );
                assert.equal(requestCount, 0);
                assert.equal(fs.existsSync(destination), false);
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("diagnostics removes its reserved report when account listing fails", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-report-failure-test-"),
    );
    const destination = path.join(tempDir, "report.json");
    try {
        await withServer(
            (_req, res) => response(res, null, 503),
            async (baseURL) => {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "diagnostics",
                            "openai-routing",
                            "--start-date",
                            "2026-08-26",
                            "--end-date",
                            "2026-08-27",
                            "--file",
                            destination,
                        ],
                        { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                    ),
                    /failed: error/,
                );
                assert.equal(fs.existsSync(destination), false);
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("diagnostics rejects invalid page sizes before any request", async () => {
    let requestCount = 0;
    await withServer(
        (_req, res) => {
            requestCount += 1;
            response(res, null);
        },
        async (baseURL) => {
            for (const value of ["0", "NaN", "-1", "1.5"]) {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "diagnostics",
                            "openai-routing",
                            "--start-date",
                            "2026-08-26",
                            "--end-date",
                            "2026-08-27",
                            "--page-size",
                            value,
                        ],
                        { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                    ),
                    /--page-size must be a positive integer/,
                );
            }
            assert.equal(requestCount, 0);
        },
    );
});

test("rejects plaintext remote Admin API origins", async () => {
    await assert.rejects(
        runCLI("http://sub2api.example.com", ["system", "version"], {
            SUB2API_ADMIN_API_KEY: "fixture-admin-key",
        }),
        /must use HTTPS for non-loopback hosts/,
    );
    await assert.rejects(
        runCLI("http://", ["system", "version"], {
            SUB2API_ADMIN_API_KEY: "fixture-admin-key",
        }),
        /must be a valid absolute URL/,
    );
    await assert.rejects(
        runCLI(
            "https://proxy-user:secret@sub2api.example.com",
            ["system", "version"],
            {
                SUB2API_ADMIN_API_KEY: "fixture-admin-key",
            },
        ),
        /must not contain URL credentials/,
    );
});

test("base URL markers match complete path segments", async () => {
    let requestPath;
    await withServer(
        (req, res) => {
            requestPath = req.url;
            response(res, { version: "test" });
        },
        async (baseURL) => {
            await runCLI(`${baseURL}/administer/admin`, ["system", "version"], {
                SUB2API_ADMIN_API_KEY: "fixture-admin-key",
            });
            assert.equal(
                requestPath,
                "/administer/api/v1/admin/system/version",
            );
        },
    );
});

test("diagnostics rejects account pagination page mismatches", async () => {
    for (const scenario of ["first", "later"]) {
        let accountRequestCount = 0;
        await withServer(
            (req, res) => {
                if (req.url === "/api/v1/admin/system/version") {
                    response(res, { version: "test" });
                    return;
                }
                if (req.url.startsWith("/api/v1/admin/accounts?")) {
                    accountRequestCount += 1;
                    response(res, {
                        items: [],
                        page:
                            scenario === "first" && accountRequestCount === 1
                                ? 2
                                : 1,
                        pages: 2,
                    });
                    return;
                }
                response(res, null, 404);
            },
            async (baseURL) => {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "diagnostics",
                            "openai-routing",
                            "--start-date",
                            "2026-08-26",
                            "--end-date",
                            "2026-08-27",
                        ],
                        { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                    ),
                    /invalid pagination metadata/,
                );
                assert.equal(accountRequestCount, scenario === "first" ? 1 : 2);
            },
        );
    }
});

test("diagnostics rejects contradictory account pagination before iterating", async () => {
    let accountRequestCount = 0;
    await withServer(
        (req, res) => {
            if (req.url === "/api/v1/admin/system/version") {
                response(res, { version: "test" });
                return;
            }
            if (req.url.startsWith("/api/v1/admin/accounts?")) {
                accountRequestCount += 1;
                response(res, {
                    items: [
                        {
                            id: 1,
                            name: "account@example.com",
                            platform: "openai",
                            type: "oauth",
                            status: "active",
                            schedulable: true,
                        },
                    ],
                    page: 1,
                    pages: 1_000_000,
                    total: 1,
                });
                return;
            }
            response(res, null, 404);
        },
        async (baseURL) => {
            await assert.rejects(
                runCLI(
                    baseURL,
                    [
                        "diagnostics",
                        "openai-routing",
                        "--start-date",
                        "2026-08-26",
                        "--end-date",
                        "2026-08-27",
                    ],
                    { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                ),
                /inconsistent pagination metadata/,
            );
            assert.equal(accountRequestCount, 1);
        },
    );
});

test("pricing treats inherited names as missing and preserves an explicit __proto__ model", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-pricing-prototype-test-"),
    );
    const pricingFile = path.join(tempDir, "pricing.json");
    fs.writeFileSync(
        pricingFile,
        '{"models":{"known":{"input":1,"cached_input":0,"output":0,"cache_creation":0},"__proto__":{"input":2,"cached_input":0,"output":0,"cache_creation":0}}}',
    );
    try {
        await withServer(
            (req, res) => {
                if (req.url === "/api/v1/admin/system/version") {
                    response(res, { version: "test" });
                    return;
                }
                if (req.url.startsWith("/api/v1/admin/accounts?")) {
                    response(res, {
                        items: [
                            {
                                id: 1,
                                name: "account@example.com",
                                platform: "openai",
                                type: "oauth",
                                status: "active",
                                schedulable: true,
                            },
                        ],
                        page: 1,
                        pages: 1,
                    });
                    return;
                }
                if (req.url.startsWith("/api/v1/admin/dashboard/models?")) {
                    response(res, {
                        models: [
                            {
                                model: "constructor",
                                requests: 1,
                                input_tokens: 1_000_000,
                                cache_read_tokens: 0,
                                cache_creation_tokens: 0,
                                output_tokens: 0,
                                total_tokens: 1_000_000,
                                cost: 0,
                            },
                            {
                                model: "__proto__",
                                requests: 1,
                                input_tokens: 1_000_000,
                                cache_read_tokens: 0,
                                cache_creation_tokens: 0,
                                output_tokens: 0,
                                total_tokens: 1_000_000,
                                cost: 0,
                            },
                        ],
                    });
                    return;
                }
                response(res, null, 404);
            },
            async (baseURL) => {
                const result = await runCLI(
                    baseURL,
                    [
                        "diagnostics",
                        "openai-routing",
                        "--start-date",
                        "2026-08-26",
                        "--end-date",
                        "2026-08-27",
                        "--pricing-file",
                        pricingFile,
                    ],
                    { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                );
                const pricing = JSON.parse(result.stdout).accounts[0].pricing;
                assert.deepEqual(pricing.missing_prices, ["constructor"]);
                assert.equal(pricing.routes[1].actual_model_equivalent_cost, 2);
                assert.equal(
                    pricing.routes[0].actual_model_equivalent_cost,
                    null,
                );
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("pricing avoids multiplication overflow and rejects non-finite costs", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-pricing-overflow-test-"),
    );
    const pricingFile = path.join(tempDir, "pricing.json");
    fs.writeFileSync(
        pricingFile,
        JSON.stringify({
            models: {
                huge: {
                    input: Number.MAX_VALUE,
                    cached_input: Number.MAX_VALUE,
                    output: 0,
                    cache_creation: 0,
                },
                cheap: {
                    input: 0,
                    cached_input: 0,
                    output: 0,
                    cache_creation: 0,
                },
            },
        }),
    );
    let overflow = false;
    let storedCostOverflow = false;
    try {
        await withServer(
            (req, res) => {
                if (req.url === "/api/v1/admin/system/version") {
                    response(res, { version: "test" });
                    return;
                }
                if (req.url.startsWith("/api/v1/admin/accounts?")) {
                    response(res, {
                        items: [
                            {
                                id: 1,
                                name: "account@example.com",
                                platform: "openai",
                                type: "oauth",
                                status: "active",
                                schedulable: true,
                            },
                        ],
                        page: 1,
                        pages: 1,
                    });
                    return;
                }
                if (req.url.startsWith("/api/v1/admin/dashboard/models?")) {
                    response(res, {
                        models: storedCostOverflow
                            ? [
                                  {
                                      model: "cheap",
                                      requests: 1,
                                      input_tokens: 0,
                                      cache_read_tokens: 0,
                                      cache_creation_tokens: 0,
                                      output_tokens: 0,
                                      total_tokens: 0,
                                      cost: Number.MAX_VALUE,
                                  },
                                  {
                                      model: "cheap",
                                      requests: 1,
                                      input_tokens: 0,
                                      cache_read_tokens: 0,
                                      cache_creation_tokens: 0,
                                      output_tokens: 0,
                                      total_tokens: 0,
                                      cost: Number.MAX_VALUE,
                                  },
                              ]
                            : [
                                  {
                                      model: "huge",
                                      requests: 1,
                                      input_tokens: 1_000_000,
                                      cache_read_tokens: overflow
                                          ? 1_000_000
                                          : 0,
                                      cache_creation_tokens: 0,
                                      output_tokens: 0,
                                      total_tokens: overflow
                                          ? 2_000_000
                                          : 1_000_000,
                                      cost: 0,
                                  },
                              ],
                    });
                    return;
                }
                response(res, null, 404);
            },
            async (baseURL) => {
                const args = [
                    "diagnostics",
                    "openai-routing",
                    "--start-date",
                    "2026-08-26",
                    "--end-date",
                    "2026-08-27",
                    "--pricing-file",
                    pricingFile,
                ];
                const result = await runCLI(baseURL, args, {
                    SUB2API_ADMIN_API_KEY: "fixture-admin-key",
                });
                assert.equal(
                    JSON.parse(result.stdout).accounts[0].pricing
                        .period_actual_model_equivalent_cost,
                    Number.MAX_VALUE,
                );

                overflow = true;
                await assert.rejects(
                    runCLI(baseURL, args, {
                        SUB2API_ADMIN_API_KEY: "fixture-admin-key",
                    }),
                    /pricing calculation produced a non-finite cost/,
                );

                overflow = false;
                storedCostOverflow = true;
                await assert.rejects(
                    runCLI(baseURL, args, {
                        SUB2API_ADMIN_API_KEY: "fixture-admin-key",
                    }),
                    /pricing calculation produced a non-finite cost/,
                );
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("diagnostics rejects unsafe aggregate token counts", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-aggregate-overflow-test-"),
    );
    const pricingFile = path.join(tempDir, "pricing.json");
    fs.writeFileSync(
        pricingFile,
        JSON.stringify({
            models: {
                cheap: {
                    input: 0,
                    cached_input: 0,
                    output: 0,
                    cache_creation: 0,
                },
            },
        }),
    );
    try {
        await withServer(
            (req, res) => {
                if (req.url === "/api/v1/admin/system/version") {
                    response(res, { version: "test" });
                    return;
                }
                if (req.url.startsWith("/api/v1/admin/accounts?")) {
                    response(res, {
                        items: [
                            {
                                id: 1,
                                name: "account@example.com",
                                platform: "openai",
                                type: "oauth",
                                status: "active",
                                schedulable: true,
                            },
                        ],
                        page: 1,
                        pages: 1,
                    });
                    return;
                }
                if (req.url.startsWith("/api/v1/admin/dashboard/models?")) {
                    response(res, {
                        models: [
                            {
                                model: "cheap",
                                requests: 1,
                                input_tokens: Number.MAX_SAFE_INTEGER,
                                cache_read_tokens: 0,
                                cache_creation_tokens: 0,
                                output_tokens: 0,
                                total_tokens: Number.MAX_SAFE_INTEGER,
                                cost: 0,
                            },
                            {
                                model: "cheap",
                                requests: 1,
                                input_tokens: 1,
                                cache_read_tokens: 0,
                                cache_creation_tokens: 0,
                                output_tokens: 0,
                                total_tokens: 1,
                                cost: 0,
                            },
                        ],
                    });
                    return;
                }
                response(res, null, 404);
            },
            async (baseURL) => {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "diagnostics",
                            "openai-routing",
                            "--start-date",
                            "2026-08-26",
                            "--end-date",
                            "2026-08-27",
                            "--pricing-file",
                            pricingFile,
                        ],
                        { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                    ),
                    /diagnostic aggregate exceeds safe integer range/,
                );
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("mapWithConcurrency waits for every worker after one worker fails", async () => {
    const failWorker = Promise.withResolvers();
    const finishWorker = Promise.withResolvers();
    const secondStarted = Promise.withResolvers();
    const failureObserved = Promise.withResolvers();
    const secondFinished = Promise.withResolvers();
    const failure = new Error("worker failed");
    const events = [];
    const work = mapWithConcurrency([0, 1], 2, async (item) => {
        events.push(`started:${item}`);
        if (item === 0) {
            await failWorker.promise;
            events.push("failed:0");
            failureObserved.resolve();
            throw failure;
        }
        secondStarted.resolve();
        await finishWorker.promise;
        events.push("finished:1");
        secondFinished.resolve();
        return item;
    });
    const settlement = work.then(
        () => {
            events.push("resolved");
            return null;
        },
        (error) => {
            events.push("rejected");
            return error;
        },
    );
    try {
        await secondStarted.promise;
        assert.deepEqual(events, ["started:0", "started:1"]);
        failWorker.resolve();
        await failureObserved.promise;
        // Drain rejection microtasks, not a timed guess at how long workers take.
        await new Promise(setImmediate);
        assert.deepEqual(events, ["started:0", "started:1", "failed:0"]);
    } finally {
        finishWorker.resolve();
        await secondFinished.promise;
    }
    assert.equal(await settlement, failure);
    assert.deepEqual(events, [
        "started:0",
        "started:1",
        "failed:0",
        "finished:1",
        "rejected",
    ]);
});

test("generic API warns about a possible write after a dispatched request fails", async () => {
    let requestCount = 0;
    await withServer(
        (req, res) => {
            requestCount += 1;
            assert.equal(req.method, "POST");
            assert.equal(req.url, "/api/v1/admin/accounts/data");
            response(res, null, 503);
        },
        async (baseURL) => {
            await assert.rejects(
                runCLI(baseURL, ["api", "POST", "/admin/accounts/data"], {
                    SUB2API_ADMIN_API_KEY: "fixture-admin-key",
                }),
                /may have taken effect.*do not retry automatically/,
            );
            assert.equal(requestCount, 1);
        },
    );
});

test("generic API reserves Admin API Key lifecycle routes for dedicated commands", async () => {
    let requestCount = 0;
    await withServer(
        (_req, res) => {
            requestCount += 1;
            response(res, { key: "must-not-be-created" });
        },
        async (baseURL) => {
            for (const [method, pathname] of [
                [
                    "POST",
                    "/admin/settings/admin-api-key/regenerate?source=generic",
                ],
                ["POST", "/admin/settings/%61dmin-api-key/regenerate"],
                ["DELETE", "/api/v1/admin/settings/admin-api-key/"],
            ]) {
                await assert.rejects(
                    runCLI(baseURL, ["api", method, pathname], {
                        SUB2API_ADMIN_API_KEY: "fixture-admin-key",
                    }),
                    /use the admin-key command for Admin API Key lifecycle operations/,
                );
            }
            assert.equal(requestCount, 0);
        },
    );
});

test("authenticated Admin requests time out while reading a response", async () => {
    let requestCount = 0;
    let requestSeen;
    const requestSeenPromise = new Promise((resolve) => {
        requestSeen = resolve;
    });
    await withServer(
        (_req, res) => {
            requestCount += 1;
            res.writeHead(200, { "Content-Type": "application/json" });
            res.write('{"code":0,"message":"success","data":');
            requestSeen();
        },
        async (baseURL) => {
            const result = runCLI(baseURL, ["api", "POST", "/admin/slow"], {
                SUB2API_ADMIN_API_KEY: "fixture-admin-key",
                SUB2API_REQUEST_TIMEOUT_MS: "100",
            });
            await requestSeenPromise;
            await assert.rejects(
                result,
                /request timed out after 100 ms.*may have taken effect.*do not retry automatically/,
            );
            assert.equal(requestCount, 1);
        },
    );
});

test("credential login timeouts warn against automatic retries", async () => {
    for (const twoFactor of [false, true]) {
        let requestCount = 0;
        let requestSeen;
        const requestSeenPromise = new Promise((resolve) => {
            requestSeen = resolve;
        });
        await withServer(
            (req, res) => {
                requestCount += 1;
                if (twoFactor && req.url === "/api/v1/auth/login") {
                    response(res, {
                        requires_2fa: true,
                        temp_token: "temp-token",
                    });
                    return;
                }
                assert.equal(
                    req.url,
                    twoFactor ? "/api/v1/auth/login/2fa" : "/api/v1/auth/login",
                );
                res.writeHead(200, { "Content-Type": "application/json" });
                res.write('{"code":0,"message":"success","data":');
                requestSeen();
            },
            async (baseURL) => {
                const result = runCLI(baseURL, ["system", "version"], {
                    SUB2API_ADMIN_EMAIL: "admin@example.com",
                    SUB2API_ADMIN_PASSWORD: "password-fixture",
                    SUB2API_LOGIN_TOTP_CODE: twoFactor ? "123456" : "",
                    SUB2API_REQUEST_TIMEOUT_MS: "100",
                });
                await requestSeenPromise;
                await assert.rejects(
                    result,
                    /request timed out after 100 ms.*authentication request may have taken effect; do not retry automatically/,
                );
                assert.equal(requestCount, twoFactor ? 2 : 1);
            },
        );
    }
});

test("request timeout rejects values above Node's timer limit", async () => {
    let requestCount = 0;
    await withServer(
        (_req, res) => {
            requestCount += 1;
            response(res, { ok: true });
        },
        async (baseURL) => {
            await assert.rejects(
                runCLI(baseURL, ["api", "GET", "/admin/ping"], {
                    SUB2API_ADMIN_API_KEY: "fixture-admin-key",
                    SUB2API_REQUEST_TIMEOUT_MS: "2147483648",
                }),
                /SUB2API_REQUEST_TIMEOUT_MS must be an integer from 1 to 2147483647/,
            );
            assert.equal(requestCount, 0);
        },
    );
});

test("generic JSON output rejects malformed compound data", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-malformed-compound-test-"),
    );
    const destination = path.join(tempDir, "response.json");
    try {
        await withServer(
            (_req, res) => {
                res.writeHead(200, { "Content-Type": "application/json" });
                res.end('{"code":0,"message":"success","data":{"x":1,}}');
            },
            async (baseURL) => {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "api",
                            "GET",
                            "/admin/malformed-compound",
                            "--output-file",
                            destination,
                        ],
                        { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                    ),
                    /invalid compound JSON/,
                );
                assert.equal(fs.statSync(destination).size, 0);
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("diagnostics records non-object routing rows as incomplete", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-diagnostics-side-effect-test-"),
    );
    const destination = path.join(tempDir, "report.json");
    try {
        await withServer(
            (req, res) => {
                if (req.url === "/api/v1/admin/system/version") {
                    response(res, { version: "test" });
                    return;
                }
                if (req.url.startsWith("/api/v1/admin/accounts?")) {
                    response(res, {
                        items: [
                            {
                                id: 1,
                                name: "account@example.com",
                                platform: "openai",
                                type: "oauth",
                                status: "active",
                                schedulable: true,
                            },
                        ],
                        page: 1,
                        pages: 1,
                    });
                    return;
                }
                if (req.url.startsWith("/api/v1/admin/dashboard/models?")) {
                    response(res, { models: [null] });
                    return;
                }
                if (req.url === "/api/v1/admin/openai/accounts/1/quota") {
                    response(res, { ok: true });
                    return;
                }
                response(res, null, 404);
            },
            async (baseURL) => {
                const result = await runCLI(
                    baseURL,
                    [
                        "diagnostics",
                        "openai-routing",
                        "--start-date",
                        "2026-08-26",
                        "--end-date",
                        "2026-08-27",
                        "--include-upstream-quota",
                        "--file",
                        destination,
                    ],
                    { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                );
                assert.equal(fs.existsSync(destination), true);
                assert.ok(fs.statSync(destination).size > 0);
                const report = JSON.parse(fs.readFileSync(destination, "utf8"));
                assert.equal(report.summary.complete, false);
                assert.match(
                    report.accounts[0].routing_error,
                    /routing response contains invalid fields: row/,
                );
                assert.equal(JSON.parse(result.stdout).summary.complete, false);
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test("generic API output rejects malformed captured strings and compound codes", async () => {
    const tempDir = fs.mkdtempSync(
        path.join(os.tmpdir(), "sub2api-json-envelope-validation-test-"),
    );
    const malformedStringDestination = path.join(tempDir, "malformed.json");
    const compoundCodeDestination = path.join(tempDir, "compound.json");
    try {
        await withServer(
            (req, res) => {
                if (req.url === "/api/v1/admin/malformed") {
                    res.writeHead(200, { "Content-Type": "application/json" });
                    res.end('{"code":0,"data":"bad\\q"}');
                    return;
                }
                if (req.url === "/api/v1/admin/compound") {
                    res.writeHead(200, { "Content-Type": "application/json" });
                    res.end('{"code":{"error":true},"data":{"ok":true}}');
                    return;
                }
                response(res, null, 404);
            },
            async (baseURL) => {
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "api",
                            "GET",
                            "/admin/malformed",
                            "--output-file",
                            malformedStringDestination,
                        ],
                        { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                    ),
                    /invalid compound JSON/,
                );
                await assert.rejects(
                    runCLI(
                        baseURL,
                        [
                            "api",
                            "GET",
                            "/admin/compound",
                            "--output-file",
                            compoundCodeDestination,
                        ],
                        { SUB2API_ADMIN_API_KEY: "fixture-admin-key" },
                    ),
                    /JSON response code must be a scalar/,
                );
                assert.equal(fs.statSync(malformedStringDestination).size, 0);
                assert.equal(fs.statSync(compoundCodeDestination).size, 0);
            },
        );
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});
