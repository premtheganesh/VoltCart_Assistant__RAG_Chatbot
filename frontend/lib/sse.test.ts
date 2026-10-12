import { describe, expect, it } from "vitest";
import { SseParser } from "./sse";

describe("SseParser", () => {
  it("parses complete events", () => {
    const events = new SseParser().feed(
      'event: start\ndata: {"a":1}\n\nevent: token\ndata: {"text":"Hi"}\n\n',
    );
    expect(events).toEqual([
      { event: "start", data: '{"a":1}' },
      { event: "token", data: '{"text":"Hi"}' },
    ]);
  });

  it("waits for the blank line when an event is split across network chunks", () => {
    const parser = new SseParser();
    expect(parser.feed("event: tok")).toEqual([]);
    expect(parser.feed('en\ndata: {"text":')).toEqual([]);
    expect(parser.feed('"Hi"}\n')).toEqual([]);
    expect(parser.feed("\n")).toEqual([{ event: "token", data: '{"text":"Hi"}' }]);
  });

  it("splits every possible way and still gets the same events", () => {
    const stream = 'event: a\ndata: 1\n\nevent: b\ndata: 2\n\nevent: c\ndata: 3\n\n';
    for (let cut = 1; cut < stream.length; cut++) {
      const parser = new SseParser();
      const events = [...parser.feed(stream.slice(0, cut)), ...parser.feed(stream.slice(cut))];
      expect(events.map((e) => e.event + e.data)).toEqual(["a1", "b2", "c3"]);
    }
  });

  it("handles \\r\\n line endings, even split between chunks", () => {
    const parser = new SseParser();
    expect(parser.feed("event: x\r\ndata: 1\r")).toEqual([]);
    expect(parser.feed("\n\r\n")).toEqual([{ event: "x", data: "1" }]);
  });

  it("joins multi-line data and ignores comments and empty events", () => {
    const events = new SseParser().feed(": keep-alive\n\ndata: line1\ndata: line2\n\n");
    expect(events).toEqual([{ event: "message", data: "line1\nline2" }]);
  });

  it("keeps a colon inside the value", () => {
    expect(new SseParser().feed('data: {"t":"a: b"}\n\n')[0].data).toBe('{"t":"a: b"}');
  });
});
