/**
 * Test helpers: render a page with a fresh QueryClient and an in-memory router,
 * and replace fetch with canned JSON responses per URL.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { vi } from "vitest";

export function renderPage(element: ReactElement, { route = "/", path = "/" } = {}) {
  // No retries: a failing request must show the error state immediately
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={element} />
          <Route path="*" element={<p>other page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

type Reply = { status?: number; body: unknown } | (() => Promise<Response>);

/** Stub fetch: the first route whose key is a prefix of the URL answers. */
export function mockFetch(routes: Record<string, Reply>) {
  // Same signature as fetch, so tests can inspect the request options (init) too
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const key = Object.keys(routes)
      .sort((a, b) => b.length - a.length)
      .find((prefix) => url.startsWith(prefix));
    if (key === undefined) throw new Error(`Unexpected request: ${url}`);
    const reply = routes[key]!;
    if (typeof reply === "function") return reply();
    return new Response(JSON.stringify(reply.body), {
      status: reply.status ?? 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
