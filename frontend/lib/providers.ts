// Presets for the OpenAI-compatible provider card in Settings.
//
// Every vendor here speaks the OpenAI chat-completions format with function
// calling, so the backend needs no per-vendor code: a preset only pre-fills
// base URL, a sensible default model and where to get a key. Base URLs and
// default models were checked against each vendor's own docs on 2026-10-11;
// the user can edit any field after picking a preset.

export interface ProviderPreset {
  id: string;
  label: string;
  baseUrl: string;
  defaultModel: string;
  /** Where to create an API key; null for keyless local providers. */
  keyUrl: string | null;
  keyPlaceholder: string;
  note: string;
  /** Only offered in local mode (the hosted backend cannot reach localhost). */
  localOnly?: boolean;
}

export const PROVIDER_PRESETS: readonly ProviderPreset[] = [
  {
    id: "openai",
    label: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    defaultModel: "gpt-4.1-mini",
    keyUrl: "https://platform.openai.com/api-keys",
    keyPlaceholder: "sk-…",
    note: "Any current GPT model works; check your dashboard for the latest ids.",
  },
  {
    id: "gemini",
    label: "Google Gemini",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai/",
    defaultModel: "gemini-3.8-flash",
    keyUrl: "https://aistudio.google.com/apikey",
    keyPlaceholder: "AIza…",
    note: "Uses Google's OpenAI-compatible endpoint; the base URL must keep its trailing slash.",
  },
  {
    id: "groq",
    label: "Groq",
    baseUrl: "https://api.groq.com/openai/v1",
    defaultModel: "openai/gpt-oss-120b",
    keyUrl: "https://console.groq.com/keys",
    keyPlaceholder: "gsk_…",
    note: "Very fast open-weight models. Llama models are enterprise-only on Groq.",
  },
  {
    id: "mistral",
    label: "Mistral",
    baseUrl: "https://api.mistral.ai/v1",
    defaultModel: "mistral-medium-latest",
    keyUrl: "https://console.mistral.ai",
    keyPlaceholder: "Mistral API key",
    note: "mistral-small-latest is the budget option; mistral-large-latest the flagship.",
  },
  {
    id: "xai",
    label: "xAI Grok",
    baseUrl: "https://api.x.ai/v1",
    defaultModel: "grok-4.3",
    keyUrl: "https://console.x.ai/team/default/api-keys",
    keyPlaceholder: "xai-…",
    note: "grok-4.3 is the fast tool-calling model; grok-4.7 is the flagship.",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    baseUrl: "https://api.deepseek.com",
    defaultModel: "deepseek-flash",
    keyUrl: "https://platform.deepseek.com/api_keys",
    keyPlaceholder: "sk-…",
    note: "Base URL has no /v1 suffix (as DeepSeek documents). deepseek-v4-pro is the larger model.",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    baseUrl: "https://openrouter.ai/api/v1",
    defaultModel: "openai/gpt-oss-120b",
    keyUrl: "https://openrouter.ai/keys",
    keyPlaceholder: "sk-or-…",
    note: "One key for hundreds of models; use any slug from openrouter.ai/models. Pricing is pass-through.",
  },
  {
    id: "together",
    label: "Together AI",
    baseUrl: "https://api.together.ai/v1",
    defaultModel: "zai-org/GLM-5.3-Flash",
    keyUrl: "https://api.together.ai/settings/projects/~current/api-keys",
    keyPlaceholder: "Together API key",
    note: "Serverless open-weight models; GLM-5.3-Flash is Together's recommended function-calling model.",
  },
  {
    id: "ollama",
    label: "Ollama (local)",
    baseUrl: "http://localhost:11434/v1",
    defaultModel: "qwen2.5:7b",
    keyUrl: null,
    keyPlaceholder: "ollama",
    note: "Runs on your machine. No API key needed.",
    localOnly: true,
  },
];

const normalize = (url: string) => url.trim().replace(/\/+$/, "");

/** The preset whose base URL matches `baseUrl` (trailing slash ignored), or null. */
export function presetFor(baseUrl: string | null | undefined): ProviderPreset | null {
  if (!baseUrl) return null;
  const wanted = normalize(baseUrl);
  if (!wanted) return null;
  return PROVIDER_PRESETS.find((p) => normalize(p.baseUrl) === wanted) ?? null;
}
