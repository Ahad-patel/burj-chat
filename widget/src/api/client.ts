/**
 * Backend client.
 *
 * Deliberately small. The widget holds no API key — the LLM credential is
 * server-side only, and this endpoint is protected by CORS and rate limiting
 * rather than by a secret the browser would have to carry.
 */

export interface ChatReply {
  conversationId: string;
  answer: string;
  isFallback: boolean;
}

export class ChatApiError extends Error {
  constructor(
    message: string,
    readonly kind: "rate_limited" | "network" | "server" | "timeout",
    readonly retryAfterSeconds?: number,
  ) {
    super(message);
    this.name = "ChatApiError";
  }
}

interface ChatApiOptions {
  baseUrl: string;
  timeoutMs?: number;
}

export class ChatApi {
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private conversationId: string | null = null;

  constructor({ baseUrl, timeoutMs = 30_000 }: ChatApiOptions) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.timeoutMs = timeoutMs;
  }

  /**
   * Send a message and return the reply.
   *
   * The conversation id is server-minted on the first exchange and echoed
   * thereafter — the widget never invents one, because the backend requires
   * UUID4 and treats the id as the only thing standing between one visitor's
   * history and another's.
   */
  async send(message: string): Promise<ChatReply> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const response = await fetch(`${this.baseUrl}/api/v1/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          ...(this.conversationId ? { conversation_id: this.conversationId } : {}),
        }),
        signal: controller.signal,
      });

      if (response.status === 429) {
        const retryAfter = Number(response.headers.get("Retry-After") ?? "30");
        throw new ChatApiError("Rate limited", "rate_limited", retryAfter);
      }

      if (!response.ok) {
        throw new ChatApiError(`Server returned ${response.status}`, "server");
      }

      const data = (await response.json()) as {
        conversation_id: string;
        answer: string;
        is_fallback: boolean;
      };

      this.conversationId = data.conversation_id;

      return {
        conversationId: data.conversation_id,
        answer: data.answer,
        isFallback: data.is_fallback,
      };
    } catch (error) {
      if (error instanceof ChatApiError) throw error;
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new ChatApiError("Request timed out", "timeout");
      }
      throw new ChatApiError("Network request failed", "network");
    } finally {
      clearTimeout(timer);
    }
  }

  /** Exposed for tests and for a "start over" affordance. */
  reset(): void {
    this.conversationId = null;
  }

  get currentConversationId(): string | null {
    return this.conversationId;
  }
}
