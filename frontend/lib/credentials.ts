"use client";

import { apiDelete, apiGet, apiPut } from "@/lib/api";

export type ActiveProvider = "free" | "anthropic" | "openai";

export interface CredentialsState {
  active_provider: ActiveProvider;
  anthropic_configured: boolean;
  openai: { configured: boolean; base_url: string | null; model: string | null };
}

export const getCredentials = () => apiGet<CredentialsState>("/api/credentials");

export const putAnthropicKey = (key: string) =>
  apiPut("/api/credentials/anthropic", { key });
export const deleteAnthropicKey = () => apiDelete("/api/credentials/anthropic");

export const putOpenAIConfig = (cfg: { baseUrl: string; model: string; key: string }) =>
  apiPut("/api/credentials/openai", {
    base_url: cfg.baseUrl,
    model: cfg.model,
    key: cfg.key,
  });
export const deleteOpenAIConfig = () => apiDelete("/api/credentials/openai");

export const setActiveProvider = (provider: ActiveProvider) =>
  apiPut("/api/credentials/active", { provider });
