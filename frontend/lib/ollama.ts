"use client";

import { apiGet } from "@/lib/api";

export interface OllamaModel { name: string; size_bytes: number }
export interface OllamaStatus { available: boolean; models: OllamaModel[] }

export const OLLAMA_OPENAI_BASE_URL = "http://localhost:11434/v1";
export const OLLAMA_PLACEHOLDER_KEY = "ollama";

export const getOllamaModels = () => apiGet<OllamaStatus>("/api/ollama/models");

export function formatGb(bytes: number): string {
  return `${(bytes / 1e9).toFixed(1)} GB`;
}
