// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// Loads the dashboard's classic scripts into a jsdom page built from the
// real index.html, with the network faked: EventSource streams are driven
// by the test, fetch answers from a route table.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const WEB = join(ROOT, "resources", "web");

export function source(name) {
  return readFileSync(join(WEB, "js", name), "utf8");
}

/** An EventSource the test pushes frames into. */
function fakeEventSource(window, opened) {
  return class FakeEventSource {
    static CLOSED = 2;
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.listeners = {};
      opened.push(this);
    }
    addEventListener(type, handler) {
      (this.listeners[type] ||= []).push(handler);
    }
    emit(type, data) {
      const event = { data: typeof data === "string" ? data : JSON.stringify(data) };
      for (const handler of this.listeners[type] || []) handler(event);
    }
    close() { this.readyState = FakeEventSource.CLOSED; this.closed = true; }
  };
}

/**
 * A page with *scripts* (file names under resources/web/js) loaded in order.
 * *routes* maps a path to [status, body] for fetch.
 */
export function page({ scripts = ["core.js"], routes = {}, token = "" } = {}) {
  const html = readFileSync(join(WEB, "index.html"), "utf8");
  const dom = new JSDOM(html, {
    url: "http://kodi.local:8099/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  const streams = [];
  const requests = [];
  window.EventSource = fakeEventSource(window, streams);
  window.fetch = async (url, init) => {
    requests.push({ url: String(url), init });
    const path = String(url).replace(/\?.*$/, "");
    const [status, body] = routes[path] || [404, {}];
    return {
      status, ok: status >= 200 && status < 300,
      json: async () => body,
    };
  };
  window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  window.HTMLDialogElement.prototype.close = function () { this.open = false; };
  if (token) window.localStorage.setItem("tinyppi.token", token);
  for (const name of scripts) window.eval(source(name));
  return { window, streams, requests, dom };
}

/** Let pending promise callbacks run. */
export const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

/** Run classic scripts that need no page (pure helpers) and return window. */
export function bare(...scripts) {
  const { window } = new JSDOM("", { runScripts: "outside-only" });
  for (const name of scripts) window.eval(source(name));
  return window;
}
