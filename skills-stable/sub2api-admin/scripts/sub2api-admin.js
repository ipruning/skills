#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { Readable } = require("node:stream");
const { pipeline } = require("node:stream/promises");

const BASE_URL = normalizeBaseURL(process.env.SUB2API_BASE_URL || "");
const ADMIN_API_KEY = process.env.SUB2API_ADMIN_API_KEY || "";
const ADMIN_JWT = process.env.SUB2API_JWT || "";
const ADMIN_EMAIL = process.env.SUB2API_ADMIN_EMAIL || "";
const ADMIN_PASSWORD = process.env.SUB2API_ADMIN_PASSWORD || "";
const LOGIN_TOTP_CODE = process.env.SUB2API_LOGIN_TOTP_CODE || "";
const USER_AGENT = process.env.SUB2API_USER_AGENT || "sub2api-admin-cli/1.0";
const MAX_REQUEST_TIMEOUT_MS = 2_147_483_647;
const REQUEST_TIMEOUT_MS = parseRequestTimeout(
    process.env.SUB2API_REQUEST_TIMEOUT_MS,
);
const TOKEN_COUNTER_FIELDS = [
    "input_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "output_tokens",
    "total_tokens",
];
const TOKEN_COMPONENT_FIELDS = TOKEN_COUNTER_FIELDS.filter(
    (field) => field !== "total_tokens",
);

let loginPromise;

function parseRequestTimeout(value) {
    if (value === undefined || value === "") return 30_000;
    const timeout = Number(value);
    if (
        !Number.isSafeInteger(timeout) ||
        timeout < 1 ||
        timeout > MAX_REQUEST_TIMEOUT_MS
    ) {
        throw new Error(
            `SUB2API_REQUEST_TIMEOUT_MS must be an integer from 1 to ${MAX_REQUEST_TIMEOUT_MS}`,
        );
    }
    return timeout;
}

function normalizeBaseURL(value) {
    const trimmed = String(value || "").trim();
    if (!trimmed) return "";
    let url;
    try {
        url = new URL(trimmed);
    } catch {
        throw new Error("SUB2API_BASE_URL must be a valid absolute URL");
    }
    const hostname = url.hostname.toLowerCase().replace(/^\[|\]$/g, "");
    const loopback =
        hostname === "localhost" ||
        hostname === "127.0.0.1" ||
        hostname === "::1";
    if (url.protocol !== "https:" && !(url.protocol === "http:" && loopback)) {
        throw new Error(
            "SUB2API_BASE_URL must use HTTPS for non-loopback hosts",
        );
    }
    if (url.username || url.password) {
        throw new Error("SUB2API_BASE_URL must not contain URL credentials");
    }
    const indexes = [
        ...url.pathname.matchAll(/\/(?:api\/v1|admin)(?=\/|$)/g),
    ].map((match) => match.index);
    if (indexes.length > 0) {
        url.pathname = url.pathname.slice(0, Math.min(...indexes));
    }
    url.search = "";
    url.hash = "";
    return url.toString().replace(/\/$/, "");
}

function validateSystemVersion(data) {
    if (
        !data ||
        typeof data.version !== "string" ||
        data.version.trim() === ""
    ) {
        throw new Error(
            "system version response must contain a non-empty version",
        );
    }
    return data;
}

function usage() {
    console.log(`Usage:
  sub2api-admin.js system version
  sub2api-admin.js diagnostics openai-routing --start-date YYYY-MM-DD --end-date YYYY-MM-DD [--ids 1,2] [--search TEXT] [--timezone Asia/Shanghai] [--pricing-file pricing.json] [--baseline-model MODEL] [--include-upstream-quota] [--include-active-usage] [--file report.json]
  sub2api-admin.js admin-key status
  sub2api-admin.js admin-key regenerate --file admin-api-key.txt
  sub2api-admin.js admin-key delete
  sub2api-admin.js api <METHOD> <admin-path> [--json '{...}' | --file payload.json] [--idempotency-key KEY] [--raw] [--output-file response]
`);
}

function parseArgs(argv) {
    const positional = [];
    const flags = {};
    for (let i = 0; i < argv.length; i += 1) {
        const token = argv[i];
        if (!token.startsWith("--")) {
            positional.push(token);
            continue;
        }
        const key = token.slice(2);
        const next = argv[i + 1];
        if (!next || next.startsWith("--")) {
            flags[key] = true;
        } else {
            flags[key] = next;
            i += 1;
        }
    }
    return { positional, flags };
}

function validateCommandArgs(args, positionalCount, allowedFlags = []) {
    const allowed = new Set(allowedFlags);
    const unknown = Object.keys(args.flags).filter(
        (flag) => !allowed.has(flag),
    );
    if (unknown.length > 0) {
        throw new Error(`unknown flag: --${unknown[0]}`);
    }
    if (args.positional.length !== positionalCount) {
        throw new Error("unexpected positional arguments");
    }
}

function validateSwitchFlags(args, flags) {
    for (const flag of flags) {
        if (args.flags[flag] !== undefined && args.flags[flag] !== true) {
            throw new Error(`--${flag} does not accept a value`);
        }
    }
}

function validateValueFlags(args, flags) {
    for (const flag of flags) {
        const value = args.flags[flag];
        if (
            value !== undefined &&
            (value === true || String(value).trim() === "")
        ) {
            throw new Error(`--${flag} requires a value`);
        }
    }
}

function requestHeaders(accept = "application/json") {
    return {
        Accept: accept,
        "User-Agent": USER_AGENT,
    };
}

function isJsonContentType(value) {
    return /(?:^|[;\s/+])json(?:$|[;\s])/i.test(value || "");
}

function writeAll(descriptor, buffer) {
    for (let offset = 0; offset < buffer.length; ) {
        offset += fs.writeSync(
            descriptor,
            buffer,
            offset,
            buffer.length - offset,
        );
    }
}

function jsonWhitespace(byte) {
    return byte === 0x20 || byte === 0x09 || byte === 0x0a || byte === 0x0d;
}

function jsonDigit(byte) {
    return byte >= 0x30 && byte <= 0x39;
}

function jsonNonZeroDigit(byte) {
    return byte >= 0x31 && byte <= 0x39;
}

function jsonHexDigit(byte) {
    return (
        (byte >= 0x30 && byte <= 0x39) ||
        (byte >= 0x41 && byte <= 0x46) ||
        (byte >= 0x61 && byte <= 0x66)
    );
}

function jsonValueDelimiter(byte) {
    return (
        jsonWhitespace(byte) || byte === 0x2c || byte === 0x5d || byte === 0x7d
    );
}

class JsonValueValidator {
    constructor() {
        this.stack = [];
        this.rootStarted = false;
        this.rootComplete = false;
        this.token = null;
    }

    fail() {
        throw new Error("JSON response contains invalid compound JSON");
    }

    startString(kind) {
        this.token = {
            kind,
            escaped: false,
            unicodeRemaining: 0,
        };
    }

    startValue(byte) {
        if (byte === 0x7b) {
            this.stack.push({ type: "object", state: "key-or-end" });
            return;
        }
        if (byte === 0x5b) {
            this.stack.push({ type: "array", state: "value-or-end" });
            return;
        }
        if (byte === 0x22) {
            this.startString("value");
            return;
        }
        if (byte === 0x74) {
            this.token = { kind: "literal", expected: "true", index: 1 };
            return;
        }
        if (byte === 0x66) {
            this.token = { kind: "literal", expected: "false", index: 1 };
            return;
        }
        if (byte === 0x6e) {
            this.token = { kind: "literal", expected: "null", index: 1 };
            return;
        }
        if (byte === 0x2d) {
            this.token = { kind: "number", state: "sign" };
            return;
        }
        if (byte === 0x30) {
            this.token = { kind: "number", state: "zero" };
            return;
        }
        if (jsonNonZeroDigit(byte)) {
            this.token = { kind: "number", state: "integer" };
            return;
        }
        this.fail();
    }

    completeValue() {
        const parent = this.stack[this.stack.length - 1];
        if (!parent) {
            this.rootComplete = true;
            return;
        }
        if (parent.state !== "value") this.fail();
        parent.state = "comma-or-end";
    }

    closeContainer(byte) {
        const context = this.stack[this.stack.length - 1];
        const expected = context.type === "object" ? 0x7d : 0x5d;
        if (byte !== expected) this.fail();
        this.stack.pop();
        this.completeValue();
    }

    consumeString(byte) {
        const token = this.token;
        if (token.unicodeRemaining > 0) {
            if (!jsonHexDigit(byte)) this.fail();
            token.unicodeRemaining -= 1;
            if (token.unicodeRemaining === 0) token.escaped = false;
            return false;
        }
        if (token.escaped) {
            if (byte === 0x75) {
                token.unicodeRemaining = 4;
            } else if (!'"\\/bfnrt'.includes(String.fromCharCode(byte))) {
                this.fail();
            } else {
                token.escaped = false;
            }
            return false;
        }
        if (byte === 0x5c) {
            token.escaped = true;
            return false;
        }
        if (byte === 0x22) {
            this.token = null;
            if (token.kind === "key") {
                this.stack[this.stack.length - 1].state = "colon";
            } else {
                this.completeValue();
            }
            return false;
        }
        if (byte < 0x20) this.fail();
        return false;
    }

    consumeLiteral(byte) {
        const token = this.token;
        if (byte !== token.expected.charCodeAt(token.index)) this.fail();
        token.index += 1;
        if (token.index === token.expected.length) {
            this.token = null;
            this.completeValue();
        }
        return false;
    }

    consumeNumber(byte) {
        const token = this.token;
        const finish = () => {
            this.token = null;
            this.completeValue();
            return true;
        };
        if (token.state === "sign") {
            if (byte === 0x30) token.state = "zero";
            else if (jsonNonZeroDigit(byte)) token.state = "integer";
            else this.fail();
            return false;
        }
        if (token.state === "zero") {
            if (byte === 0x2e) token.state = "fraction-start";
            else if (byte === 0x65 || byte === 0x45)
                token.state = "exponent-start";
            else if (jsonValueDelimiter(byte)) return finish();
            else this.fail();
            return false;
        }
        if (token.state === "integer") {
            if (jsonDigit(byte)) return false;
            if (byte === 0x2e) token.state = "fraction-start";
            else if (byte === 0x65 || byte === 0x45)
                token.state = "exponent-start";
            else if (jsonValueDelimiter(byte)) return finish();
            else this.fail();
            return false;
        }
        if (token.state === "fraction-start") {
            if (!jsonDigit(byte)) this.fail();
            token.state = "fraction";
            return false;
        }
        if (token.state === "fraction") {
            if (jsonDigit(byte)) return false;
            if (byte === 0x65 || byte === 0x45) token.state = "exponent-start";
            else if (jsonValueDelimiter(byte)) return finish();
            else this.fail();
            return false;
        }
        if (token.state === "exponent-start") {
            if (byte === 0x2b || byte === 0x2d) token.state = "exponent-sign";
            else if (jsonDigit(byte)) token.state = "exponent";
            else this.fail();
            return false;
        }
        if (token.state === "exponent-sign") {
            if (!jsonDigit(byte)) this.fail();
            token.state = "exponent";
            return false;
        }
        if (token.state === "exponent") {
            if (jsonDigit(byte)) return false;
            if (jsonValueDelimiter(byte)) return finish();
            this.fail();
        }
        return false;
    }

    consumeToken(byte) {
        if (this.token.kind === "value" || this.token.kind === "key") {
            return this.consumeString(byte);
        }
        if (this.token.kind === "literal") return this.consumeLiteral(byte);
        return this.consumeNumber(byte);
    }

    consume(byte) {
        let reprocess = true;
        while (reprocess) {
            reprocess = false;
            if (this.token) {
                reprocess = this.consumeToken(byte);
                continue;
            }
            if (this.rootComplete) {
                if (!jsonWhitespace(byte)) this.fail();
                continue;
            }
            if (!this.rootStarted) {
                if (jsonWhitespace(byte)) continue;
                this.rootStarted = true;
                this.startValue(byte);
                continue;
            }

            const context = this.stack[this.stack.length - 1];
            if (!context) this.fail();
            if (context.type === "object") {
                if (context.state === "key-or-end") {
                    if (jsonWhitespace(byte)) continue;
                    if (byte === 0x7d) {
                        this.closeContainer(byte);
                        continue;
                    }
                    if (byte !== 0x22) this.fail();
                    this.startString("key");
                    continue;
                }
                if (context.state === "key") {
                    if (jsonWhitespace(byte)) continue;
                    if (byte !== 0x22) this.fail();
                    this.startString("key");
                    continue;
                }
                if (context.state === "colon") {
                    if (jsonWhitespace(byte)) continue;
                    if (byte !== 0x3a) this.fail();
                    context.state = "value";
                    continue;
                }
                if (context.state === "value") {
                    if (jsonWhitespace(byte)) continue;
                    this.startValue(byte);
                    continue;
                }
                if (jsonWhitespace(byte)) continue;
                if (byte === 0x2c) context.state = "key";
                else if (byte === 0x7d) this.closeContainer(byte);
                else this.fail();
                continue;
            }

            if (context.state === "value-or-end") {
                if (jsonWhitespace(byte)) continue;
                if (byte === 0x5d) {
                    this.closeContainer(byte);
                    continue;
                }
                context.state = "value";
                this.startValue(byte);
                continue;
            }
            if (context.state === "value") {
                if (jsonWhitespace(byte)) continue;
                this.startValue(byte);
                continue;
            }
            if (jsonWhitespace(byte)) continue;
            if (byte === 0x2c) context.state = "value";
            else if (byte === 0x5d) this.closeContainer(byte);
            else this.fail();
        }
    }

    finish() {
        if (this.token?.kind === "number") {
            if (
                !["zero", "integer", "fraction", "exponent"].includes(
                    this.token.state,
                )
            ) {
                this.fail();
            }
            this.token = null;
            this.completeValue();
        }
        if (this.token || !this.rootComplete || this.stack.length > 0) {
            this.fail();
        }
    }
}

class JsonEnvelopeStream {
    constructor(descriptor, captureData, { allowOpaque = false } = {}) {
        this.descriptor = descriptor;
        this.captureData = captureData;
        this.allowOpaque = allowOpaque;
        this.state = "root";
        this.rootComplete = false;
        this.opaque = false;
        this.keyBytes = [];
        this.keyEscaped = false;
        this.key = null;
        this.valueKey = null;
        this.valueType = null;
        this.valueString = false;
        this.valueEscaped = false;
        this.valueStack = [];
        this.valueBytes = [];
        this.valueValidator = null;
        this.dataCapture = false;
        this.dataSeen = false;
        this.code = undefined;
        this.message = undefined;
        this.utf8Decoder = new TextDecoder("utf-8", { fatal: true });
        this.rootValidator = allowOpaque ? new JsonValueValidator() : null;
    }

    fail(message) {
        throw new Error(message);
    }

    beginValue(byte, index) {
        this.valueKey = this.key;
        this.dataCapture = this.captureData && this.valueKey === "data";
        if (this.dataCapture && this.dataSeen) {
            this.fail("JSON response contains duplicate data fields");
        }
        if (byte === 0x22) {
            this.valueType = "string";
            this.valueString = true;
            this.valueEscaped = false;
            if (this.dataCapture) {
                this.valueValidator = new JsonValueValidator();
                this.valueValidator.consume(byte);
            }
            if (!this.dataCapture) this.valueBytes = [byte];
            return { captureStart: this.dataCapture ? index : null };
        }
        if (byte === 0x7b || byte === 0x5b) {
            this.valueType = "compound";
            this.valueStack = [byte];
            this.valueValidator = new JsonValueValidator();
            this.valueValidator.consume(byte);
            return { captureStart: this.dataCapture ? index : null };
        }
        this.valueType = "scalar";
        this.valueBytes = [byte];
        return { captureStart: null };
    }

    finishValue(rawBytes) {
        const raw = Buffer.from(rawBytes).toString("utf8").trim();
        if (!raw) this.fail("JSON response contains an empty value");
        let value;
        try {
            value = JSON.parse(raw);
        } catch {
            this.fail("JSON response contains invalid JSON");
        }
        if (this.valueKey === "code") this.code = value;
        if (this.valueKey === "message") this.message = value;
        if (this.valueKey === "data") {
            if (this.captureData && this.descriptor !== undefined) {
                writeAll(this.descriptor, Buffer.from(raw));
            }
            this.dataSeen = true;
        }
        this.state = "after-value";
        this.valueKey = null;
        this.valueType = null;
        this.valueString = false;
        this.valueEscaped = false;
        this.valueStack = [];
        this.valueBytes = [];
        this.valueValidator = null;
        this.dataCapture = false;
    }

    finishCapturedValue() {
        this.valueValidator?.finish();
        if (this.valueKey === "code") {
            this.fail("JSON response code must be a scalar");
        }
        if (this.valueKey === "data") this.dataSeen = true;
        this.state = "after-value";
        this.valueKey = null;
        this.valueType = null;
        this.valueString = false;
        this.valueEscaped = false;
        this.valueStack = [];
        this.valueBytes = [];
        this.valueValidator = null;
        this.dataCapture = false;
    }

    completeStatus() {
        if (this.code !== undefined && this.code !== 0 && this.code !== "0") {
            throw new Error(this.message || this.code || "application error");
        }
    }

    consume(chunk) {
        if (this.utf8Decoder) {
            try {
                this.utf8Decoder.decode(chunk, { stream: true });
            } catch {
                this.fail("JSON response contains invalid UTF-8");
            }
        }
        let captureStart = null;
        const flushCapture = (end) => {
            if (
                captureStart !== null &&
                this.descriptor !== undefined &&
                end > captureStart
            ) {
                writeAll(this.descriptor, chunk.subarray(captureStart, end));
            }
            captureStart = null;
        };

        for (let index = 0; index < chunk.length; index += 1) {
            const byte = chunk[index];
            if (this.opaque) continue;
            if (
                this.dataCapture &&
                this.state === "value" &&
                this.valueType !== "scalar" &&
                captureStart === null
            ) {
                captureStart = index;
            }
            if (this.rootComplete) {
                if (!jsonWhitespace(byte))
                    this.fail("trailing data after JSON");
                continue;
            }
            if (this.state === "root") {
                if (jsonWhitespace(byte)) continue;
                if (byte !== 0x7b) {
                    if (this.allowOpaque) {
                        this.opaque = true;
                        continue;
                    }
                    this.fail("JSON response must be an object");
                }
                this.state = "key";
                continue;
            }
            if (this.state === "key") {
                if (jsonWhitespace(byte)) continue;
                if (byte === 0x7d) {
                    this.rootComplete = true;
                    this.state = "after-value";
                    continue;
                }
                if (byte !== 0x22)
                    this.fail("JSON response has an invalid key");
                this.keyBytes = [];
                this.keyEscaped = false;
                this.state = "key-string";
                continue;
            }
            if (this.state === "key-string") {
                if (this.keyEscaped) {
                    this.keyBytes.push(byte);
                    this.keyEscaped = false;
                } else if (byte === 0x5c) {
                    this.keyBytes.push(byte);
                    this.keyEscaped = true;
                } else if (byte === 0x22) {
                    try {
                        this.key = JSON.parse(
                            `"${Buffer.from(this.keyBytes).toString("utf8")}"`,
                        );
                    } catch {
                        this.fail("JSON response has an invalid key");
                    }
                    this.state = "after-key";
                } else {
                    this.keyBytes.push(byte);
                }
                continue;
            }
            if (this.state === "after-key") {
                if (jsonWhitespace(byte)) continue;
                if (byte !== 0x3a)
                    this.fail("JSON response is missing a colon");
                this.state = "value-start";
                continue;
            }
            if (this.state === "value-start") {
                if (jsonWhitespace(byte)) continue;
                const { captureStart: valueStart } = this.beginValue(
                    byte,
                    index,
                );
                captureStart = valueStart;
                this.state = "value";
                continue;
            }
            if (this.state === "after-value") {
                if (jsonWhitespace(byte)) continue;
                if (byte === 0x2c) {
                    this.state = "after-comma";
                    continue;
                }
                if (byte === 0x7d) {
                    this.rootComplete = true;
                    continue;
                }
                this.fail("JSON response has an invalid object separator");
            }
            if (this.state === "after-comma") {
                if (jsonWhitespace(byte)) continue;
                if (byte !== 0x22)
                    this.fail("JSON response has an invalid key");
                this.keyBytes = [];
                this.keyEscaped = false;
                this.state = "key-string";
                continue;
            }
            if (this.valueType === "scalar") {
                if (byte === 0x2c || byte === 0x7d) {
                    const scalarBytes = this.valueBytes;
                    this.finishValue(scalarBytes);
                    index -= 1;
                    continue;
                }
                this.valueBytes.push(byte);
                continue;
            }
            if (this.valueType === "string") {
                this.valueValidator?.consume(byte);
                if (this.valueEscaped) {
                    this.valueEscaped = false;
                    if (!this.dataCapture) this.valueBytes.push(byte);
                    continue;
                }
                if (byte === 0x5c) {
                    this.valueEscaped = true;
                    if (!this.dataCapture) this.valueBytes.push(byte);
                    continue;
                }
                if (byte === 0x22) {
                    if (this.dataCapture) {
                        flushCapture(index + 1);
                        this.finishCapturedValue();
                    } else {
                        this.valueBytes.push(byte);
                        this.finishValue(this.valueBytes);
                    }
                    continue;
                }
                if (!this.dataCapture) this.valueBytes.push(byte);
                continue;
            }
            if (this.valueType === "compound") {
                this.valueValidator.consume(byte);
                if (this.valueString) {
                    if (this.valueEscaped) {
                        this.valueEscaped = false;
                    } else if (byte === 0x5c) {
                        this.valueEscaped = true;
                    } else if (byte === 0x22) {
                        this.valueString = false;
                    }
                    continue;
                }
                if (byte === 0x22) {
                    this.valueString = true;
                    continue;
                }
                if (byte === 0x7b || byte === 0x5b) {
                    this.valueStack.push(byte);
                    continue;
                }
                if (byte === 0x7d || byte === 0x5d) {
                    const opening = this.valueStack.pop();
                    if (
                        (byte === 0x7d && opening !== 0x7b) ||
                        (byte === 0x5d && opening !== 0x5b)
                    ) {
                        this.fail("JSON response has mismatched brackets");
                    }
                    if (this.valueStack.length === 0) {
                        if (this.dataCapture) {
                            flushCapture(index + 1);
                            this.finishCapturedValue();
                        } else {
                            this.finishCapturedValue();
                        }
                    }
                }
            }
        }
        if (this.rootValidator) {
            for (const byte of chunk) this.rootValidator.consume(byte);
        }
        if (this.dataCapture) flushCapture(chunk.length);
    }

    finish() {
        if (this.utf8Decoder) {
            try {
                this.utf8Decoder.decode();
            } catch {
                this.fail("JSON response contains invalid UTF-8");
            }
        }
        this.rootValidator?.finish();
        if (this.opaque) return { dataSeen: false };
        if (!this.rootComplete || this.state !== "after-value") {
            this.fail("JSON response ended before the envelope was complete");
        }
        this.completeStatus();
        return { dataSeen: this.dataSeen };
    }
}

async function streamJsonDataResponse(response, method, pathname, descriptor) {
    const parser = new JsonEnvelopeStream(descriptor, true);
    try {
        if (!response.body) throw new Error("JSON response has no body");
        for await (const chunk of Readable.fromWeb(response.body)) {
            parser.consume(Buffer.from(chunk));
        }
        const result = parser.finish();
        if (!result.dataSeen) throw new Error("JSON response contains no data");
        writeAll(descriptor, Buffer.from("\n"));
    } catch (error) {
        fs.ftruncateSync(descriptor, 0);
        throw new Error(`${method} ${pathname} failed: ${error.message}`);
    }
}

async function streamRawJsonResponse(response, method, pathname, descriptor) {
    const parser = new JsonEnvelopeStream(undefined, false, {
        allowOpaque: true,
    });
    try {
        if (!response.body) throw new Error("JSON response has no body");
        for await (const chunk of Readable.fromWeb(response.body)) {
            const buffer = Buffer.from(chunk);
            writeAll(descriptor, buffer);
            parser.consume(buffer);
        }
        parser.finish();
    } catch (error) {
        fs.ftruncateSync(descriptor, 0);
        throw new Error(`${method} ${pathname} failed: ${error.message}`);
    }
}

async function requestWithTimeout(url, options, onRequestStart, handler) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
        const responsePromise = fetch(url, {
            ...options,
            signal: controller.signal,
        });
        onRequestStart?.();
        return await handler(await responsePromise);
    } catch (error) {
        if (error?.name === "AbortError") {
            throw new Error(`request timed out after ${REQUEST_TIMEOUT_MS} ms`);
        }
        throw error;
    } finally {
        clearTimeout(timer);
    }
}

async function unauthenticatedRequest(method, pathname, body) {
    if (!BASE_URL) throw new Error("Missing SUB2API_BASE_URL");
    const headers = requestHeaders();
    const options = { method, headers, redirect: "manual" };
    if (body !== undefined) {
        headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
    }

    let requestStarted = false;
    let responseCompleted = false;
    try {
        return await requestWithTimeout(
            `${BASE_URL}${pathname}`,
            options,
            () => {
                requestStarted = true;
            },
            async (response) => {
                const text = await response.text();
                responseCompleted = true;
                let payload;
                try {
                    payload = JSON.parse(text);
                } catch {
                    payload = { raw: text };
                }
                if (
                    !response.ok ||
                    (payload &&
                        payload.code !== undefined &&
                        payload.code !== 0 &&
                        payload.code !== "0")
                ) {
                    const detail =
                        payload?.message ||
                        payload?.code ||
                        response.statusText;
                    throw new Error(`${method} ${pathname} failed: ${detail}`);
                }
                return payload.data;
            },
        );
    } catch (error) {
        if (requestStarted && !responseCompleted) {
            throw new Error(
                `${error.message}; authentication request may have taken effect; do not retry automatically`,
            );
        }
        throw error;
    }
}

async function loginWithCredentials() {
    if (!ADMIN_EMAIL || !ADMIN_PASSWORD) {
        throw new Error(
            "Missing authentication: set SUB2API_ADMIN_API_KEY, SUB2API_JWT, or both SUB2API_ADMIN_EMAIL and SUB2API_ADMIN_PASSWORD",
        );
    }

    let data = await unauthenticatedRequest("POST", "/api/v1/auth/login", {
        email: ADMIN_EMAIL,
        password: ADMIN_PASSWORD,
    });
    if (data?.requires_2fa) {
        if (!LOGIN_TOTP_CODE) {
            throw new Error(
                "Admin login requires 2FA; set a fresh SUB2API_LOGIN_TOTP_CODE and retry",
            );
        }
        data = await unauthenticatedRequest("POST", "/api/v1/auth/login/2fa", {
            temp_token: data.temp_token,
            totp_code: LOGIN_TOTP_CODE,
        });
    }
    if (!data?.access_token) {
        throw new Error("Admin login returned no access_token");
    }
    if (data.user?.role !== "admin") {
        throw new Error("Authenticated user is not an administrator");
    }
    return data.access_token;
}

async function authHeaders() {
    if (!BASE_URL) throw new Error("Missing SUB2API_BASE_URL");
    if (ADMIN_API_KEY) return { "x-api-key": ADMIN_API_KEY };
    if (ADMIN_JWT) return { Authorization: `Bearer ${ADMIN_JWT}` };
    if (!loginPromise) loginPromise = loginWithCredentials();
    return { Authorization: `Bearer ${await loginPromise}` };
}

async function apiRequest(
    method,
    pathname,
    body,
    extraHeaders = {},
    outputDescriptor,
    onRequestStart,
) {
    const headers = {
        ...(await authHeaders()),
        ...requestHeaders(),
        ...extraHeaders,
    };
    const options = { method, headers, redirect: "manual" };
    if (body !== undefined) {
        headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
    }
    return requestWithTimeout(
        `${BASE_URL}${pathname}`,
        options,
        onRequestStart,
        async (response) => {
            if (
                response.ok &&
                (method === "HEAD" ||
                    response.status === 204 ||
                    response.status === 205)
            ) {
                return null;
            }
            if (outputDescriptor !== undefined && response.ok) {
                await streamJsonDataResponse(
                    response,
                    method,
                    pathname,
                    outputDescriptor,
                );
                return null;
            }
            const content = await response.arrayBuffer();
            let text;
            try {
                text = new TextDecoder("utf-8", { fatal: true }).decode(
                    content,
                );
            } catch {
                throw new Error(
                    `${method} ${pathname} failed: JSON response contains invalid UTF-8`,
                );
            }
            let payload;
            try {
                payload = JSON.parse(text);
            } catch {
                if (response.ok) {
                    throw new Error(
                        `${method} ${pathname} failed: response is not valid JSON; use --raw for non-JSON responses`,
                    );
                }
                payload = { raw: text };
            }
            if (
                response.ok &&
                (!payload ||
                    typeof payload !== "object" ||
                    Array.isArray(payload) ||
                    !Object.hasOwn(payload, "data"))
            ) {
                throw new Error(
                    `${method} ${pathname} failed: response is not a JSON envelope; use --raw for non-JSON responses`,
                );
            }
            if (
                !response.ok ||
                (payload &&
                    payload.code !== undefined &&
                    payload.code !== 0 &&
                    payload.code !== "0")
            ) {
                const detail =
                    payload?.message || payload?.code || response.statusText;
                throw new Error(`${method} ${pathname} failed: ${detail}`);
            }
            return payload.data;
        },
    );
}

async function apiRawRequest(
    method,
    pathname,
    body,
    extraHeaders = {},
    outputDescriptor,
    onRequestStart,
) {
    const headers = {
        ...(await authHeaders()),
        ...requestHeaders("*/*"),
        ...extraHeaders,
    };
    const options = { method, headers, redirect: "manual" };
    if (body !== undefined) {
        headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
    }
    return requestWithTimeout(
        `${BASE_URL}${pathname}`,
        options,
        onRequestStart,
        async (response) => {
            if (!response.ok) {
                const content = Buffer.from(await response.arrayBuffer());
                let detail = response.statusText;
                const text = content.toString("utf8");
                try {
                    const payload = JSON.parse(text);
                    detail = payload?.message || payload?.code || detail;
                } catch {
                    if (text) detail = text;
                }
                throw new Error(`${method} ${pathname} failed: ${detail}`);
            }
            if (response.status === 204 || response.status === 205) return null;
            if (outputDescriptor !== undefined) {
                if (
                    method !== "HEAD" &&
                    isJsonContentType(response.headers.get("content-type"))
                ) {
                    await streamRawJsonResponse(
                        response,
                        method,
                        pathname,
                        outputDescriptor,
                    );
                } else if (response.body) {
                    await pipeline(
                        Readable.fromWeb(response.body),
                        fs.createWriteStream(null, {
                            fd: outputDescriptor,
                            autoClose: false,
                        }),
                    );
                }
                return null;
            }
            const content = Buffer.from(await response.arrayBuffer());
            if (
                method !== "HEAD" &&
                isJsonContentType(response.headers.get("content-type"))
            ) {
                const parser = new JsonEnvelopeStream(undefined, false, {
                    allowOpaque: true,
                });
                try {
                    parser.consume(content);
                    parser.finish();
                } catch (error) {
                    throw new Error(
                        `${method} ${pathname} failed: ${error.message}`,
                    );
                }
            }
            return content;
        },
    );
}

function encodeQuery(params) {
    const pairs = [];
    for (const [key, value] of Object.entries(params)) {
        if (
            value === undefined ||
            value === null ||
            value === false ||
            value === ""
        ) {
            continue;
        }
        pairs.push(
            `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`,
        );
    }
    return pairs.length ? `?${pairs.join("&")}` : "";
}

function normalizeAdminPath(pathname) {
    let candidate = String(pathname || "").trim();
    if (!candidate.startsWith("/")) candidate = `/${candidate}`;
    if (candidate === "/admin" || candidate.startsWith("/admin/")) {
        candidate = `/api/v1${candidate}`;
    }

    let parsed;
    try {
        parsed = new URL(candidate, "http://sub2api.local");
    } catch {
        throw new Error("Admin API path must stay under /api/v1/admin");
    }
    if (/%(?:2e|2f|5c)/i.test(parsed.pathname)) {
        throw new Error("Admin API path must stay under /api/v1/admin");
    }
    if (parsed.pathname.includes("//")) {
        throw new Error("Admin API path must stay under /api/v1/admin");
    }
    const canonicalPathname = parsed.pathname.replace(
        /%([0-9a-f]{2})/gi,
        (encoded, hex) => {
            const character = String.fromCharCode(Number.parseInt(hex, 16));
            return /^[A-Za-z0-9\-._~]$/.test(character) ? character : encoded;
        },
    );
    if (
        parsed.origin !== "http://sub2api.local" ||
        parsed.hash ||
        (canonicalPathname !== "/api/v1/admin" &&
            !canonicalPathname.startsWith("/api/v1/admin/"))
    ) {
        throw new Error("Admin API path must stay under /api/v1/admin");
    }
    return `${canonicalPathname}${parsed.search}`;
}

async function adminRequest(
    method,
    adminPath,
    body,
    headers = {},
    onRequestStart,
) {
    return apiRequest(
        method,
        normalizeAdminPath(adminPath),
        body,
        headers,
        undefined,
        onRequestStart,
    );
}

async function listAccounts(options = {}) {
    return adminRequest(
        "GET",
        `/admin/accounts${encodeQuery({
            page: options.page || 1,
            page_size: options.pageSize ?? 500,
            sort_by: "name",
            sort_order: "asc",
            lite: 1,
            platform: "openai",
            search: options.search,
        })}`,
    );
}

async function listAllAccounts(options = {}) {
    const first = await listAccounts({ ...options, page: 1 });
    if (!Array.isArray(first.items)) {
        throw new Error("Admin accounts response must contain an items array");
    }
    if (!Number.isSafeInteger(first.pages) || first.pages < 1) {
        throw new Error(
            "Admin accounts response must contain a positive integer pages value",
        );
    }
    if (!Number.isSafeInteger(first.page) || first.page !== 1) {
        throw new Error(
            "Admin accounts response contains invalid pagination metadata",
        );
    }
    const items = [...first.items];
    const pages = first.pages;
    const pageSize = options.pageSize ?? 500;
    let declaredTotal = first.total;
    if (
        declaredTotal !== undefined &&
        (!Number.isSafeInteger(declaredTotal) || declaredTotal < 0)
    ) {
        throw new Error(
            "Admin accounts response must contain a non-negative integer total value",
        );
    }
    if (declaredTotal !== undefined) {
        const expectedPages = Math.max(1, Math.ceil(declaredTotal / pageSize));
        if (
            pages !== expectedPages ||
            first.items.length > Math.min(pageSize, declaredTotal)
        ) {
            throw new Error(
                "Admin accounts response contains inconsistent pagination metadata",
            );
        }
    }
    for (let page = 2; page <= pages; page += 1) {
        const result = await listAccounts({ ...options, page });
        if (!Array.isArray(result.items)) {
            throw new Error(
                "Admin accounts response must contain an items array",
            );
        }
        if (
            !Number.isSafeInteger(result.page) ||
            result.page !== page ||
            !Number.isSafeInteger(result.pages) ||
            result.pages !== pages
        ) {
            throw new Error(
                "Admin accounts response contains invalid pagination metadata",
            );
        }
        if (result.total !== undefined) {
            if (
                !Number.isSafeInteger(result.total) ||
                result.total < 0 ||
                (declaredTotal !== undefined && result.total !== declaredTotal)
            ) {
                throw new Error(
                    "Admin accounts response contains inconsistent total metadata",
                );
            }
            declaredTotal = result.total;
        }
        items.push(...result.items);
    }
    if (declaredTotal !== undefined && declaredTotal !== items.length) {
        throw new Error(
            "Admin accounts response total does not match assembled items",
        );
    }
    return { ...first, items };
}

function parseIds(value) {
    if (!value) throw new Error("requires --ids");
    const ids = String(value)
        .split(",")
        .map((id) => id.trim())
        .filter(Boolean)
        .map((id) => {
            if (!/^[1-9][0-9]*$/.test(id)) {
                throw new Error(`invalid id: ${id}`);
            }
            const number = Number(id);
            if (!Number.isSafeInteger(number) || number <= 0) {
                throw new Error(`invalid id: ${id}`);
            }
            return number;
        });
    if (ids.length === 0) throw new Error("--ids requires at least one ID");
    return ids;
}

function readJsonPayload(flags, { required = true } = {}) {
    if (flags.json !== undefined && flags.file !== undefined) {
        throw new Error("--json and --file cannot be used together");
    }
    if (flags.json !== undefined) return JSON.parse(flags.json);
    if (flags.file !== undefined) {
        return JSON.parse(fs.readFileSync(path.resolve(flags.file), "utf8"));
    }
    if (required) throw new Error("requires --json or --file");
    return undefined;
}

function printJson(data) {
    console.log(JSON.stringify(data, null, 2));
}

function finiteNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : 0;
}

function isCalendarDate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const date = new Date(`${value}T00:00:00.000Z`);
    return (
        !Number.isNaN(date.getTime()) &&
        date.toISOString().slice(0, 10) === value
    );
}

function parseModelRoute(label) {
    const parts = String(label || "").split(" -> ");
    const requestedModel = parts[0] || "";
    const upstreamModel =
        parts.length > 1 ? parts[parts.length - 1] : requestedModel;
    return {
        requested_model: requestedModel,
        upstream_model: upstreamModel,
        mismatch: requestedModel !== upstreamModel,
    };
}

function readPricing(filename) {
    if (!filename) return null;
    const raw = JSON.parse(fs.readFileSync(path.resolve(filename), "utf8"));
    const source =
        raw.models && typeof raw.models === "object" ? raw.models : raw;
    const models = Object.create(null);
    for (const [model, value] of Object.entries(source)) {
        if (!value || typeof value !== "object") continue;
        const input = value.input;
        const cachedInput = value.cached_input;
        const output = value.output;
        const cacheCreation = value.cache_creation;
        if (
            ![input, cachedInput, output, cacheCreation].every(
                (price) =>
                    typeof price === "number" &&
                    Number.isFinite(price) &&
                    price >= 0,
            )
        ) {
            throw new Error(
                `invalid pricing for ${model}: input, cached_input, output, and cache_creation must be non-negative numbers`,
            );
        }
        models[model] = {
            input,
            cached_input: cachedInput,
            output,
            cache_creation: cacheCreation,
        };
    }
    if (Object.keys(models).length === 0) {
        throw new Error("pricing file contains no model prices");
    }
    return {
        as_of: raw.as_of,
        source_urls: raw.source_urls,
        models,
    };
}

function tokenCost(row, price) {
    const cost =
        (finiteNumber(row.input_tokens) / 1_000_000) * price.input +
        (finiteNumber(row.cache_read_tokens) / 1_000_000) * price.cached_input +
        (finiteNumber(row.output_tokens) / 1_000_000) * price.output +
        (finiteNumber(row.cache_creation_tokens) / 1_000_000) *
            price.cache_creation;
    if (!Number.isFinite(cost)) {
        throw new Error("pricing calculation produced a non-finite cost");
    }
    return cost;
}

function isValidTokenCount(value) {
    return Number.isSafeInteger(value) && value >= 0;
}

function isUsableQuotaResponse(value) {
    const primaryWindow = value?.rate_limit?.primary_window;
    const usedPercent = primaryWindow?.used_percent;
    return Boolean(
        value &&
            typeof value === "object" &&
            !Array.isArray(value) &&
            Number.isSafeInteger(value.fetched_at) &&
            value.fetched_at >= 0 &&
            value.rate_limit &&
            typeof value.rate_limit === "object" &&
            !Array.isArray(value.rate_limit) &&
            primaryWindow &&
            typeof primaryWindow === "object" &&
            !Array.isArray(primaryWindow) &&
            typeof usedPercent === "number" &&
            Number.isFinite(usedPercent) &&
            usedPercent >= 0 &&
            usedPercent <= 100,
    );
}

function tokenCountersMatchTotal(row) {
    const values = TOKEN_COUNTER_FIELDS.map((field) => row[field]);
    if (!values.every(isValidTokenCount)) return true;
    const componentTotal = TOKEN_COMPONENT_FIELDS.reduce(
        (sum, field) => sum + row[field],
        0,
    );
    return row.total_tokens === componentTotal;
}

async function settled(request) {
    try {
        return { data: await request(), error: null };
    } catch (error) {
        return { data: null, error: error.message };
    }
}

async function mapWithConcurrency(items, concurrency, worker) {
    const workerCount = Number(concurrency);
    if (!Number.isInteger(workerCount) || workerCount < 1) {
        throw new Error("concurrency must be a positive integer");
    }
    if (items.length === 0) return [];
    const results = new Array(items.length);
    let next = 0;
    let firstError;
    async function run() {
        try {
            while (next < items.length) {
                const index = next;
                next += 1;
                results[index] = await worker(items[index], index);
            }
        } catch (error) {
            firstError ??= error;
        }
    }
    await Promise.all(
        Array.from({ length: Math.min(workerCount, items.length) }, run),
    );
    if (firstError) throw firstError;
    return results;
}

function addSafeInteger(total, value) {
    const result = total + value;
    if (!Number.isSafeInteger(result)) {
        throw new Error("diagnostic aggregate exceeds safe integer range");
    }
    return result;
}

function addFiniteCost(total, value) {
    const result = total + value;
    if (!Number.isFinite(result)) {
        throw new Error("pricing calculation produced a non-finite cost");
    }
    return result;
}

function multiplyFinite(left, right) {
    const result = left * right;
    if (!Number.isFinite(result)) {
        throw new Error("pricing calculation produced a non-finite cost");
    }
    return result;
}

function priceRoutingRows(
    modelRows,
    usage,
    quota,
    quotaError,
    pricing,
    baselineModel,
    usageError,
    activeUsageRequested,
) {
    if (!pricing) return null;

    const routes = [];
    const missingPrices = new Set();
    const invalidTokenCounters = new Set();
    let actualModelEquivalent = 0;
    let baselineEquivalent = 0;
    for (const row of modelRows) {
        const route = parseModelRoute(row.model);
        for (const field of TOKEN_COUNTER_FIELDS) {
            const value = row[field];
            if (!isValidTokenCount(value)) invalidTokenCounters.add(field);
        }
        if (!tokenCountersMatchTotal(row)) {
            invalidTokenCounters.add("total_tokens");
        }
        const upstreamPrice = Object.hasOwn(
            pricing.models,
            route.upstream_model,
        )
            ? pricing.models[route.upstream_model]
            : null;
        const baselinePrice = baselineModel
            ? Object.hasOwn(pricing.models, baselineModel)
                ? pricing.models[baselineModel]
                : null
            : null;
        if (!upstreamPrice) missingPrices.add(route.upstream_model);
        const actualCost = upstreamPrice ? tokenCost(row, upstreamPrice) : null;
        const baselineCost = baselinePrice
            ? tokenCost(row, baselinePrice)
            : null;
        if (actualCost !== null) {
            actualModelEquivalent = addFiniteCost(
                actualModelEquivalent,
                actualCost,
            );
        }
        if (baselineCost !== null) {
            baselineEquivalent = addFiniteCost(
                baselineEquivalent,
                baselineCost,
            );
        }
        routes.push({
            ...route,
            requests: finiteNumber(row.requests),
            total_tokens: finiteNumber(row.total_tokens),
            stored_cost: finiteNumber(row.cost),
            actual_model_equivalent_cost: actualCost,
            baseline_equivalent_cost: baselineCost,
        });
    }

    const periodTokens = modelRows.reduce(
        (sum, row) => addSafeInteger(sum, finiteNumber(row.total_tokens)),
        0,
    );
    const rawWindowTokens = usage?.seven_day?.window_stats?.tokens;
    const windowTokens =
        typeof rawWindowTokens !== "number" ||
        !Number.isFinite(rawWindowTokens) ||
        rawWindowTokens < 0
            ? null
            : rawWindowTokens;
    const windowUnavailable =
        usageError || (activeUsageRequested && windowTokens === null);
    const windowScale =
        windowUnavailable || periodTokens === 0
            ? null
            : windowTokens !== null
              ? windowTokens / periodTokens
              : 1;
    const scaleBasis = windowUnavailable
        ? "active_usage_unavailable"
        : periodTokens === 0
          ? "selected_period_empty"
          : windowTokens !== null
            ? "active_usage_window_tokens / selected_period_tokens"
            : "selected_period_assumed_to_match_quota_window";
    const validPercent = (value) =>
        typeof value === "number" &&
        Number.isFinite(value) &&
        value >= 0 &&
        value <= 100
            ? value
            : null;
    const usedPercent =
        (!quotaError
            ? validPercent(quota?.rate_limit?.primary_window?.used_percent)
            : null) ??
        (!usageError ? validPercent(usage?.seven_day?.utilization) : null);
    const tokenCountersComplete = invalidTokenCounters.size === 0;
    const actualComplete = missingPrices.size === 0 && tokenCountersComplete;
    const baselineComplete = Boolean(
        baselineModel &&
            Object.hasOwn(pricing.models, baselineModel) &&
            tokenCountersComplete,
    );
    const adjustedActual =
        actualComplete && windowScale !== null
            ? multiplyFinite(actualModelEquivalent, windowScale)
            : null;
    const adjustedBaseline =
        baselineComplete && windowScale !== null
            ? multiplyFinite(baselineEquivalent, windowScale)
            : null;
    const impliedFullWindowEquivalent =
        adjustedActual !== null && usedPercent > 0
            ? adjustedActual / (usedPercent / 100)
            : null;
    if (
        impliedFullWindowEquivalent !== null &&
        !Number.isFinite(impliedFullWindowEquivalent)
    ) {
        throw new Error("pricing calculation produced a non-finite cost");
    }

    return {
        routes,
        missing_prices: [...missingPrices].sort(),
        token_counters_complete: tokenCountersComplete,
        invalid_token_counters: [...invalidTokenCounters].sort(),
        period_total_tokens: periodTokens,
        period_stored_cost: modelRows.reduce(
            (sum, row) => addFiniteCost(sum, finiteNumber(row.cost)),
            0,
        ),
        period_actual_model_equivalent_cost: actualComplete
            ? actualModelEquivalent
            : null,
        baseline_model: baselineModel || null,
        period_baseline_equivalent_cost: baselineComplete
            ? baselineEquivalent
            : null,
        window_total_tokens: windowTokens,
        approximate_window_scale: windowScale,
        scale_basis: scaleBasis,
        adjusted_window_actual_model_equivalent_cost: adjustedActual,
        adjusted_window_baseline_equivalent_cost: adjustedBaseline,
        used_percent: usedPercent,
        implied_full_window_equivalent: impliedFullWindowEquivalent,
    };
}

async function commandDiagnostics(args) {
    validateCommandArgs(args, 2, [
        "start-date",
        "end-date",
        "ids",
        "search",
        "timezone",
        "pricing-file",
        "baseline-model",
        "include-upstream-quota",
        "include-active-usage",
        "file",
        "page-size",
        "concurrency",
    ]);
    validateSwitchFlags(args, [
        "include-upstream-quota",
        "include-active-usage",
    ]);
    validateValueFlags(args, [
        "start-date",
        "end-date",
        "ids",
        "search",
        "timezone",
        "pricing-file",
        "baseline-model",
        "file",
        "page-size",
        "concurrency",
    ]);
    const subcommand = args.positional[1];
    if (subcommand !== "openai-routing") {
        throw new Error(
            `unknown diagnostics subcommand: ${subcommand || "(missing)"}`,
        );
    }

    const startDate = args.flags["start-date"];
    const endDate = args.flags["end-date"];
    if (!startDate || !endDate) {
        throw new Error(
            "diagnostics openai-routing requires --start-date and --end-date",
        );
    }
    if (
        !isCalendarDate(startDate) ||
        !isCalendarDate(endDate) ||
        startDate > endDate
    ) {
        throw new Error(
            "diagnostic dates must be valid ordered YYYY-MM-DD values",
        );
    }
    const timezone =
        args.flags.timezone ||
        Intl.DateTimeFormat().resolvedOptions().timeZone ||
        "UTC";
    try {
        new Intl.DateTimeFormat("en-US", { timeZone: timezone }).format();
    } catch {
        throw new Error(`invalid timezone: ${timezone}`);
    }
    const pageSize =
        args.flags["page-size"] === undefined
            ? 500
            : Number(args.flags["page-size"]);
    if (!Number.isInteger(pageSize) || pageSize < 1) {
        throw new Error("--page-size must be a positive integer");
    }
    const pricing = readPricing(args.flags["pricing-file"]);
    const baselineModel = args.flags["baseline-model"] || null;
    if (baselineModel && !pricing) {
        throw new Error("--baseline-model requires --pricing-file");
    }
    if (baselineModel && !Object.hasOwn(pricing.models, baselineModel)) {
        throw new Error(`baseline model has no price: ${baselineModel}`);
    }
    const requestedIds =
        args.flags.ids === undefined ? null : new Set(parseIds(args.flags.ids));
    const concurrency =
        args.flags.concurrency === undefined
            ? 4
            : Number(args.flags.concurrency);
    if (!Number.isInteger(concurrency) || concurrency < 1) {
        throw new Error("--concurrency must be a positive integer");
    }
    const upstreamQuotaRequested = Boolean(
        args.flags["include-upstream-quota"],
    );
    const activeUsageRequested = Boolean(args.flags["include-active-usage"]);

    const outputFile = args.flags.file ? path.resolve(args.flags.file) : null;
    let outputDescriptor;
    let outputReserved = false;
    let outputCompleted = false;
    let sideEffectRequestStarted = false;
    try {
        if (outputFile) {
            outputDescriptor = fs.openSync(outputFile, "wx", 0o600);
            outputReserved = true;
            fs.fchmodSync(outputDescriptor, 0o600);
        }

        const [versionResult, accountsData] = await Promise.all([
            settled(async () =>
                validateSystemVersion(
                    await adminRequest("GET", "/admin/system/version"),
                ),
            ),
            listAllAccounts({
                pageSize,
                search: args.flags.search,
            }),
        ]);
        const accountItems = accountsData.items || [];
        const accountIds = new Set();
        for (const account of accountItems) {
            if (
                !account ||
                typeof account !== "object" ||
                Array.isArray(account) ||
                !Number.isSafeInteger(account.id) ||
                account.id <= 0
            ) {
                throw new Error(
                    "Admin accounts response contains invalid account entries",
                );
            }
            if (account.platform !== "openai") {
                throw new Error(
                    "Admin accounts response contains a non-OpenAI account",
                );
            }
            if (accountIds.has(account.id)) {
                throw new Error(
                    "Admin accounts response contains duplicate account IDs",
                );
            }
            accountIds.add(account.id);
        }
        const accounts = accountItems.filter(
            (account) => !requestedIds || requestedIds.has(account.id),
        );
        if (requestedIds && accounts.length !== requestedIds.size) {
            const found = new Set(accounts.map((account) => account.id));
            const missing = [...requestedIds].filter((id) => !found.has(id));
            throw new Error(
                `OpenAI account IDs not found: ${missing.join(",")}`,
            );
        }

        const accountReports = await mapWithConcurrency(
            accounts,
            concurrency,
            async (account) => {
                const modelQuery = encodeQuery({
                    start_date: startDate,
                    end_date: endDate,
                    timezone,
                    account_id: account.id,
                    model_source: "mapping",
                });
                const modelsResult = await settled(() =>
                    adminRequest("GET", `/admin/dashboard/models${modelQuery}`),
                );
                if (
                    !modelsResult.error &&
                    !Array.isArray(modelsResult.data?.models)
                ) {
                    modelsResult.error =
                        "routing response must contain a models array";
                }
                if (!modelsResult.error) {
                    const periodFields = [
                        ["start_date", startDate],
                        ["end_date", endDate],
                    ];
                    const mismatchedPeriodFields = periodFields
                        .filter(
                            ([field, expected]) =>
                                modelsResult.data[field] !== undefined &&
                                modelsResult.data[field] !== expected,
                        )
                        .map(([field]) => field);
                    if (mismatchedPeriodFields.length > 0) {
                        modelsResult.error = `routing response period does not match requested dates: ${mismatchedPeriodFields.join(", ")}`;
                    }
                }
                if (!modelsResult.error) {
                    const invalidCounters = new Set();
                    for (const row of modelsResult.data.models) {
                        if (
                            !row ||
                            typeof row !== "object" ||
                            Array.isArray(row)
                        ) {
                            invalidCounters.add("row");
                            continue;
                        }
                        if (
                            typeof row.model !== "string" ||
                            row.model.trim() === ""
                        ) {
                            invalidCounters.add("model");
                        } else if (
                            row.model
                                .split(" -> ")
                                .some((component) => component.trim() === "")
                        ) {
                            invalidCounters.add("model");
                        }
                        for (const field of [
                            "requests",
                            ...TOKEN_COUNTER_FIELDS,
                            "cost",
                        ]) {
                            const value = row[field];
                            if (
                                field === "cost"
                                    ? typeof value !== "number" ||
                                      !Number.isFinite(value) ||
                                      value < 0
                                    : !isValidTokenCount(value)
                            ) {
                                invalidCounters.add(field);
                            }
                        }
                        if (!tokenCountersMatchTotal(row)) {
                            invalidCounters.add("total_tokens");
                        }
                    }
                    if (invalidCounters.size > 0) {
                        modelsResult.error = `routing response contains invalid fields: ${[
                            ...invalidCounters,
                        ].join(", ")}`;
                    }
                }
                let quotaResult = { data: null, error: null };
                let usageResult = { data: null, error: null };
                if (!modelsResult.error) {
                    [quotaResult, usageResult] = await Promise.all([
                        upstreamQuotaRequested
                            ? settled(() =>
                                  adminRequest(
                                      "GET",
                                      `/admin/openai/accounts/${account.id}/quota`,
                                      undefined,
                                      {},
                                      () => {
                                          sideEffectRequestStarted = true;
                                      },
                                  ),
                              )
                            : Promise.resolve({ data: null, error: null }),
                        activeUsageRequested
                            ? settled(() =>
                                  adminRequest(
                                      "GET",
                                      `/admin/accounts/${account.id}/usage`,
                                      undefined,
                                      {},
                                      () => {
                                          sideEffectRequestStarted = true;
                                      },
                                  ),
                              )
                            : Promise.resolve({ data: null, error: null }),
                    ]);
                }
                if (
                    activeUsageRequested &&
                    !usageResult.error &&
                    !isValidTokenCount(
                        usageResult.data?.seven_day?.window_stats?.tokens,
                    )
                ) {
                    usageResult.error =
                        "active usage response must contain a non-negative integer seven_day.window_stats.tokens";
                }
                if (
                    upstreamQuotaRequested &&
                    !quotaResult.error &&
                    !isUsableQuotaResponse(quotaResult.data)
                ) {
                    quotaResult.error =
                        "upstream quota response must contain a quota object with fetched_at";
                }
                const modelRows = Array.isArray(modelsResult.data?.models)
                    ? modelsResult.data.models.filter(
                          (row) =>
                              row &&
                              typeof row === "object" &&
                              !Array.isArray(row),
                      )
                    : [];
                const routing = modelRows.map((row) => ({
                    ...parseModelRoute(row.model),
                    requests: finiteNumber(row.requests),
                    input_tokens: finiteNumber(row.input_tokens),
                    output_tokens: finiteNumber(row.output_tokens),
                    cache_creation_tokens: finiteNumber(
                        row.cache_creation_tokens,
                    ),
                    cache_read_tokens: finiteNumber(row.cache_read_tokens),
                    total_tokens: finiteNumber(row.total_tokens),
                    stored_cost: finiteNumber(row.cost),
                }));
                return {
                    account: {
                        id: account.id,
                        name: account.name,
                        platform: account.platform,
                        type: account.type,
                        status: account.status,
                        schedulable: account.schedulable,
                    },
                    quota: quotaResult.data,
                    quota_error: quotaResult.error,
                    usage: usageResult.data,
                    usage_error: usageResult.error,
                    routing,
                    routing_error: modelsResult.error,
                    pricing: priceRoutingRows(
                        modelRows,
                        usageResult.data,
                        quotaResult.data,
                        quotaResult.error,
                        pricing,
                        baselineModel,
                        usageResult.error,
                        activeUsageRequested,
                    ),
                };
            },
        );

        const upstreamEvidenceErrorCount = accountReports.reduce(
            (count, account) =>
                count +
                (upstreamQuotaRequested && account.quota_error ? 1 : 0) +
                (activeUsageRequested && account.usage_error ? 1 : 0),
            0,
        );
        const routingErrorCount = accountReports.filter(
            (account) => account.routing_error,
        ).length;
        const allRoutes = accountReports
            .filter((report) => !report.routing_error)
            .flatMap((report) => report.routing);
        const report = {
            generated_at: new Date().toISOString(),
            base_url: BASE_URL,
            auth_method: ADMIN_API_KEY
                ? "admin_api_key"
                : ADMIN_JWT
                  ? "jwt"
                  : "password_login",
            period: { start_date: startDate, end_date: endDate, timezone },
            upstream_quota_requested: upstreamQuotaRequested,
            active_usage_requested: activeUsageRequested,
            system_version: versionResult.data,
            system_version_error: versionResult.error,
            summary: {
                complete:
                    routingErrorCount === 0 &&
                    upstreamEvidenceErrorCount === 0 &&
                    !versionResult.error,
                accounts: accountReports.length,
                accounts_failed: routingErrorCount,
                upstream_evidence_failed: upstreamEvidenceErrorCount,
                requests: allRoutes.reduce(
                    (sum, route) => addSafeInteger(sum, route.requests),
                    0,
                ),
                total_tokens: allRoutes.reduce(
                    (sum, route) => addSafeInteger(sum, route.total_tokens),
                    0,
                ),
                mismatch_requests: allRoutes
                    .filter((route) => route.mismatch)
                    .reduce(
                        (sum, route) => addSafeInteger(sum, route.requests),
                        0,
                    ),
                mismatch_tokens: allRoutes
                    .filter((route) => route.mismatch)
                    .reduce(
                        (sum, route) => addSafeInteger(sum, route.total_tokens),
                        0,
                    ),
                pricing_as_of: pricing?.as_of || null,
                pricing_source_urls: pricing?.source_urls || null,
            },
            accounts: accountReports,
        };

        if (outputDescriptor !== undefined) {
            fs.writeFileSync(
                outputDescriptor,
                `${JSON.stringify(report, null, 2)}\n`,
            );
            fs.fsyncSync(outputDescriptor);
            fs.closeSync(outputDescriptor);
            outputDescriptor = undefined;
            outputCompleted = true;
            printJson({ file: outputFile, summary: report.summary });
        } else {
            printJson(report);
        }
    } catch (error) {
        if (outputDescriptor !== undefined) fs.closeSync(outputDescriptor);
        if (
            outputFile &&
            outputReserved &&
            !outputCompleted &&
            !sideEffectRequestStarted
        ) {
            fs.rmSync(outputFile, { force: true });
        }
        if (sideEffectRequestStarted) {
            const outputDetail =
                outputFile && outputReserved && !outputCompleted
                    ? `; reserved report file remains at ${outputFile}`
                    : "";
            throw new Error(
                `${error.message}; an opt-in upstream request may have taken effect${outputDetail}; do not retry diagnostics automatically`,
            );
        }
        throw error;
    }
}

async function commandAdminKey(args) {
    const subcommand = args.positional[1];
    if (subcommand === "status") {
        validateCommandArgs(args, 2);
        printJson(await adminRequest("GET", "/admin/settings/admin-api-key"));
        return;
    }
    if (subcommand === "regenerate") {
        validateCommandArgs(args, 2, ["file"]);
        validateValueFlags(args, ["file"]);
        if (!args.flags.file) {
            throw new Error(
                "admin-key regenerate requires --file; the full key is returned only once",
            );
        }
        const file = path.resolve(args.flags.file);
        let descriptor;
        let reservationCreated = false;
        let requestStarted = false;
        try {
            descriptor = fs.openSync(file, "wx", 0o600);
            reservationCreated = true;
            fs.fchmodSync(descriptor, 0o600);
            fs.fsyncSync(descriptor);
            const parentDescriptor = fs.openSync(path.dirname(file), "r");
            try {
                fs.fsyncSync(parentDescriptor);
            } finally {
                fs.closeSync(parentDescriptor);
            }
            const data = await adminRequest(
                "POST",
                "/admin/settings/admin-api-key/regenerate",
                undefined,
                {},
                () => {
                    requestStarted = true;
                },
            );
            if (typeof data?.key !== "string" || data.key.trim() === "") {
                throw new Error("admin key regeneration returned no key");
            }
            if (/\p{Cc}/u.test(data.key)) {
                throw new Error(
                    "admin key regeneration returned a key with control characters",
                );
            }
            if (
                data.key
                    .split("")
                    .some((character) => character.charCodeAt(0) > 0xff)
            ) {
                throw new Error(
                    "admin key regeneration returned a key outside the HTTP header byte range",
                );
            }
            fs.writeFileSync(descriptor, `${data.key}\n`, { encoding: "utf8" });
            fs.fsyncSync(descriptor);
            fs.closeSync(descriptor);
            descriptor = undefined;
            printJson({
                file,
                masked_key:
                    data.key.length <= 14
                        ? "***"
                        : `${data.key.slice(0, 10)}...${data.key.slice(-4)}`,
            });
        } catch (error) {
            if (descriptor !== undefined) fs.closeSync(descriptor);
            if (reservationCreated && !requestStarted) {
                fs.rmSync(file, { force: true });
            }
            if (requestStarted) {
                throw new Error(
                    `${error.message}; Admin API Key regeneration may have taken effect. Do not retry regenerate automatically. The reserved file remains at ${file}; unset SUB2API_ADMIN_API_KEY and provide SUB2API_JWT or administrator credentials before running admin-key status.`,
                );
            }
            throw error;
        }
        return;
    }
    if (subcommand === "delete") {
        validateCommandArgs(args, 2);
        let requestStarted = false;
        try {
            printJson(
                await adminRequest(
                    "DELETE",
                    "/admin/settings/admin-api-key",
                    undefined,
                    {},
                    () => {
                        requestStarted = true;
                    },
                ),
            );
        } catch (error) {
            if (requestStarted) {
                throw new Error(
                    `${error.message}; Admin API Key deletion may have taken effect. Do not retry automatically. Unset SUB2API_ADMIN_API_KEY and provide SUB2API_JWT or administrator credentials before running admin-key status.`,
                );
            }
            throw error;
        }
        return;
    }
    throw new Error(
        `unknown admin-key subcommand: ${subcommand || "(missing)"}`,
    );
}

async function commandSystem(args) {
    validateCommandArgs(args, 2);
    const subcommand = args.positional[1];
    if (subcommand !== "version") {
        throw new Error(
            `unknown system subcommand: ${subcommand || "(missing)"}`,
        );
    }
    printJson(
        validateSystemVersion(
            await adminRequest("GET", "/admin/system/version"),
        ),
    );
}

async function commandApi(args) {
    validateCommandArgs(args, 3, [
        "json",
        "file",
        "idempotency-key",
        "raw",
        "output-file",
    ]);
    validateSwitchFlags(args, ["raw"]);
    validateValueFlags(args, [
        "json",
        "file",
        "idempotency-key",
        "output-file",
    ]);
    const method = args.positional[1]?.toUpperCase();
    const pathname = args.positional[2];
    if (!method || !pathname) {
        throw new Error("api requires <METHOD> <admin-path>");
    }
    if (
        (method === "GET" || method === "HEAD") &&
        (args.flags.json !== undefined || args.flags.file !== undefined)
    ) {
        throw new Error(`api ${method} cannot include a request body`);
    }
    const body = readJsonPayload(args.flags, { required: false });
    const adminPath = normalizeAdminPath(pathname);
    const adminPathname = new URL(
        adminPath,
        "http://sub2api.local",
    ).pathname.replace(/\/+$/, "");
    if (
        (method === "POST" &&
            adminPathname ===
                "/api/v1/admin/settings/admin-api-key/regenerate") ||
        (method === "DELETE" &&
            adminPathname === "/api/v1/admin/settings/admin-api-key")
    ) {
        throw new Error(
            "use the admin-key command for Admin API Key lifecycle operations",
        );
    }
    const headers = args.flags["idempotency-key"]
        ? { "Idempotency-Key": args.flags["idempotency-key"] }
        : {};
    const raw = Boolean(args.flags.raw);
    const outputFile = args.flags["output-file"]
        ? path.resolve(args.flags["output-file"])
        : null;
    let descriptor;
    let reservationCreated = false;
    let requestStarted = false;
    try {
        if (outputFile) {
            descriptor = fs.openSync(outputFile, "wx", 0o600);
            reservationCreated = true;
            fs.fchmodSync(descriptor, 0o600);
        }
        const data = raw
            ? await apiRawRequest(
                  method,
                  adminPath,
                  body,
                  headers,
                  outputFile ? descriptor : undefined,
                  () => {
                      requestStarted = true;
                  },
              )
            : await apiRequest(
                  method,
                  adminPath,
                  body,
                  headers,
                  outputFile ? descriptor : undefined,
                  () => {
                      requestStarted = true;
                  },
              );

        if (outputFile) {
            fs.fsyncSync(descriptor);
            fs.closeSync(descriptor);
            descriptor = undefined;
            printJson({ file: outputFile, format: raw ? "raw" : "json" });
        } else if (raw) {
            if (data !== null) process.stdout.write(data);
        } else {
            printJson(data);
        }
    } catch (error) {
        if (descriptor !== undefined) fs.closeSync(descriptor);
        if (outputFile && reservationCreated && !requestStarted) {
            fs.rmSync(outputFile, { force: true });
        }
        if (requestStarted) {
            const outputDetail = outputFile
                ? `; output file reserved at ${outputFile}`
                : "";
            throw new Error(
                `${error.message}${outputDetail}; the Admin API request may have taken effect; do not retry automatically`,
            );
        }
        throw error;
    }
}

async function main() {
    const args = parseArgs(process.argv.slice(2));
    const command = args.positional[0];
    if (!command) {
        usage();
        process.exit(1);
    }
    if (command === "system") {
        await commandSystem(args);
        return;
    }
    if (command === "diagnostics") {
        await commandDiagnostics(args);
        return;
    }
    if (command === "admin-key") {
        await commandAdminKey(args);
        return;
    }
    if (command === "api") {
        await commandApi(args);
        return;
    }
    throw new Error(`unknown command: ${command}`);
}

module.exports = { mapWithConcurrency };

if (require.main === module) {
    main().catch((error) => {
        console.error(error.message);
        process.exitCode = 1;
    });
}
